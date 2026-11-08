"""
PRJ-01 — the project lifecycle without hard delete (FLOW-001, CLAUDE.md §2 rule 9).

Package ``docs/architecture/tasks/PRJ-01_PROJECT_NO_DELETE_REOPEN_WARRANTY.md``; decision
R54; FLOW Guard FG-236..FG-240.

* :func:`business_links` — every tenant-owned record that names the project. A project
  with ANY of them is never deleted (FLOW-001 P-04 „Обект с движения не се изтрива“;
  „Какво НЕ“: offers, acts, invoices, photos, materials, payments) and its type is locked
  (R54: „типът на проект не се сменя след първия запис“).
* :func:`keyed_transaction` — the consequential-write shape of this package: an
  ``Idempotency-Key`` (R29; none → 428 before anything is read or written), the W0-04
  registry (same key + same body → the stored answer; another body → 409), ONE MongoDB
  transaction for the business write and its canonical AuditEvent (``record_event`` with
  the session, as ``auth_tx.run_in_transaction`` / AUTH-01).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import HTTPException

from app.db import db
from app.tenancy.ownership import ORG_KEYED

#: Named paths through which a tenant-owned record names a project — queried first, one
#: exists-query per path (an index on the path serves it). Nested array-of-refs shapes of the
#: codebase (FG-272): invoice-line ``allocations[].ref_id`` / ``refId`` (``POST
#: /invoice-lines``, ``models/invoice_lines.AllocationItem``), invoice ``lines[]`` with
#: ``project_id`` / ``allocation_ref_id`` / ``allocations[].ref_id``, worker-calendar
#: ``day_entries[].project_id``, warehouse ``transit_origin.project_id``, file
#: ``context.entity_id``.
PROJECT_LINK_FIELDS = ("project_id", "site_id", "subproject_id", "parent_project_id",
                       "warranty_of_project_id", "context_id", "entity_id",
                       "allocation_ref_id", "allocations.ref_id", "allocations.refId",
                       "lines.project_id", "lines.allocation_ref_id",
                       "lines.allocations.ref_id", "lines.allocations.refId",
                       "day_entries.project_id", "transit_origin.project_id",
                       "context.entity_id")

#: How deep the generic scan looks below the top level (FG-272): array → object → array →
#: value covers ``lines[].allocations[].ref_id`` and any other shape of that depth.
GENERIC_DEPTH = 4


def _contains(value: str, project_id: str, depth: int) -> Dict[str, Any]:
    """Aggregation expression: ``value`` is ``project_id`` or holds it at most ``depth``
    levels down (inside arrays and sub-documents)."""
    if depth <= 0:
        return {"$eq": [value, project_id]}
    elem, kv = "e%d" % depth, "kv%d" % depth
    return {"$switch": {"branches": [
        {"case": {"$isArray": value},
         "then": {"$anyElementTrue": [{"$map": {
             "input": value, "as": elem,
             "in": _contains("$$" + elem, project_id, depth - 1)}}]}},
        {"case": {"$eq": [{"$type": value}, "object"]},
         "then": {"$anyElementTrue": [{"$map": {
             "input": {"$objectToArray": value}, "as": kv,
             "in": _contains("$$%s.v" % kv, project_id, depth - 1)}}]}}],
        "default": {"$eq": [value, project_id]}}}


def _any_reference(project_id: str) -> Dict[str, Any]:
    """PRJ-01 / FG-254 + FG-272: a reference under ANY field name — top level
    (``context_id``, ``entity_id``, …) and inside arrays / sub-documents down to
    ``GENERIC_DEPTH`` (``allocations[].ref_id``, ``lines[].allocations[].ref_id``, …). Ids are
    UUIDs, so an equal value is a reference."""
    return {"$expr": _contains("$$ROOT", project_id, GENERIC_DEPTH)}


#: Records that are the project's own structure, not business history: the team
#: (an authorization relation), the phases (FLOW-001 P-06: an empty level may go) and the
#: legacy audit log (it names the project as ``entity_id``; it is the history itself).
STRUCTURAL = frozenset({"project_team", "project_phases", "audit_logs"})

#: Statuses that FLOW-001 P-08 reopens to ``Active``.
REOPENABLE = frozenset({"Completed"})
#: P-08 lists why a closed project is opened again.
REOPEN_KINDS = ("warranty", "defect", "completion", "additional_work", "correction")

#: The legacy status graph of ``PUT /projects/{id}`` (unchanged by PRJ-01); the archive /
#: cancel endpoints use the same edges.
TRANSITIONS: Dict[str, List[str]] = {
    "Draft": ["Active", "Cancelled"],
    "Active": ["Paused", "Stopped", "Completed"],
    "Paused": ["Active", "Stopped", "Cancelled"],
    "Stopped": ["Active", "Cancelled"],
    "Completed": ["Archived"],
    "Cancelled": ["Archived"],
    "Overhead": ["Active", "Archived"],
    "Archived": [],
}

KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def refuse(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message,
                                                     **extra})


def require_key(header: Optional[str]) -> str:
    """R29: a consequential write without an ``Idempotency-Key`` → 428, nothing written."""
    key = header.strip() if isinstance(header, str) else ""
    if not key or len(key) > 200:
        raise refuse(428, KEY_REQUIRED, "Липсва Idempotency-Key — заявката не е записана")
    return key


def require_reason(value: Any) -> str:
    """A lifecycle change states why (FLOW-001 P-08; CLAUDE.md §14). → 400 otherwise."""
    reason = value.strip() if isinstance(value, str) else ""
    if not reason:
        raise refuse(400, "REASON_REQUIRED", "Посочете причина")
    from app.services.money_amount import check_reason
    check_reason(reason)   # PAY-01-C01 rule: ≤ 500 chars, no control/invisible chars → 400
    return reason


async def business_links(tenant, project_id: str, session=None,
                         first_only: bool = True) -> Dict[str, str]:
    """``{collection: how}`` for the tenant's records that name ``project_id``.

    Every ``org_id``-keyed collection of the tenancy model (``ORG_KEYED``) except the
    project's own structure. FG-274: first ONE exists-query per collection over the named
    paths (``find_one`` on ``$or`` of ``{path: id}`` — an index on a path serves its
    branch), then the generic
    any-field / nested scan per collection; with ``first_only`` it stops at the first hit.
    ``how`` is the path that matched, or ``"nested"`` for the generic scan.
    """
    kw = {} if session is None else {"session": session}
    names = [n for n in sorted(ORG_KEYED) if n not in STRUCTURAL]
    out: Dict[str, str] = {}

    def scoped(name: str, flt: Dict[str, Any]) -> Dict[str, Any]:
        # the project's own document carries its id; it is not a reference to itself
        return {"$and": [flt, {"id": {"$ne": project_id}}]} if name == "projects" else flt

    named = {"$or": [{path: project_id} for path in PROJECT_LINK_FIELDS]}
    for name in names:
        # one exists-query per collection; each $or branch can use an index on its path
        doc = await tenant.collection(name).find_one(
            scoped(name, named), {"_id": 0, **{p.split(".")[0]: 1 for p in PROJECT_LINK_FIELDS}},
            **kw)
        if doc is not None:
            out[name] = next((p for p in PROJECT_LINK_FIELDS if p.split(".")[0] in doc),
                             "named")
            if first_only:
                return out
    generic = _any_reference(project_id)
    for name in names:
        if name in out:
            continue
        if await tenant.collection(name).find_one(scoped(name, generic), {"_id": 1}, **kw):
            out[name] = "nested"
            if first_only:
                return out
    return out


async def audit(session, user: Dict[str, Any], *, action: str, entity_type: str,
                entity_id: str, reason: Optional[str], diff: Dict[str, Any],
                key: Optional[str], source_flow: str = "FLOW-001") -> Dict[str, Any]:
    """The canonical W0-04 AuditEvent, in the business write's transaction."""
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=user["org_id"], actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow=source_flow, retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=entity_type, entity_id=entity_id, reason=reason, structured_diff=diff,
        effective_role_assignments=[user.get("role") or ""], idempotency_key=key,
        source_channel="api")
    return await record_event(db, event, session=session)


async def keyed_transaction(user: Dict[str, Any], key: str, action: str,
                            fingerprint: Dict[str, Any],
                            work: Callable[[Any], Awaitable[Dict[str, Any]]],
                            precheck: Optional[Callable[[], Awaitable[Any]]] = None
                            ) -> Dict[str, Any]:
    """Run ``work(session)`` once per (tenant, action, key), inside one transaction.

    * new key → ``work`` runs in ``run_in_transaction``; its result is stored with the key;
    * the same key and body again → the stored result, nothing written;
    * the same key with another body → 409 ``IDEMPOTENCY_KEY_REUSED``;
    * the same key while the first is running → 409 ``IDEMPOTENCY_IN_PROGRESS``;
    * ``work`` raised → the transaction rolled back, the key is marked failed, so the same
      request may be sent again (``work`` re-reads everything inside the transaction).
    """
    from app.audit.idempotency import (IDEMPOTENCY_COMPLETED, IDEMPOTENCY_DUPLICATE,
                                       IDEMPOTENCY_STARTED, IdempotencyConflict,
                                       begin_idempotent, complete_idempotent, fail_idempotent,
                                       request_fingerprint)
    from app.services.auth_tx import run_in_transaction
    tenant_id = user["org_id"]
    # The key is per user too: another user's key never replays someone else's answer.
    scoped_key = "%s:%s" % (user["id"], key)
    try:
        state = await begin_idempotent(db, tenant_id=tenant_id, key=scoped_key, action=action,
                                       request_fingerprint=request_fingerprint(fingerprint))
    except IdempotencyConflict:
        raise refuse(409, "IDEMPOTENCY_KEY_REUSED",
                     "Този Idempotency-Key вече е използван за друга заявка")
    if state["status"] == IDEMPOTENCY_DUPLICATE:
        if state.get("prior_status") == IDEMPOTENCY_COMPLETED:
            return json.loads(state["result_reference"])
        raise refuse(409, "IDEMPOTENCY_IN_PROGRESS", "Заявка с този Idempotency-Key още се обработва")
    if state["status"] != IDEMPOTENCY_STARTED:
        raise refuse(409, "IDEMPOTENCY_IN_PROGRESS", "Заявка с този Idempotency-Key още се обработва")
    try:
        if precheck is not None:
            # FG-274: a long read (e.g. the history scan) runs BEFORE the transaction; the
            # transaction then compare-and-sets on what the check saw.
            await precheck()
        result = await run_in_transaction(db, work)
    except HTTPException as exc:
        await fail_idempotent(db, tenant_id=tenant_id, key=scoped_key, action=action,
                              error_code="HTTP_%d" % exc.status_code)
        raise
    except Exception:
        await fail_idempotent(db, tenant_id=tenant_id, key=scoped_key, action=action,
                              error_code="ERROR")
        raise
    stored = json.dumps(result, sort_keys=True, default=str)
    await complete_idempotent(db, tenant_id=tenant_id, key=scoped_key, action=action,
                              result_reference=stored)
    return json.loads(stored)
