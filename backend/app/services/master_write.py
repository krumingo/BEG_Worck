"""
CP-01 — one consequential master-data write (CLAUDE.md §14): Idempotency-Key (R29) →
one MongoDB transaction (auth_tx.run_in_transaction) holding the compare-and-set business
write, the canonical AuditEvent (record_event with the session) and the completion of the
key. Either all of it commits or none of it.

    key = require_key(header)                      # 428 before anything is read or written
    async def body(session):
        doc = await coll.find_one({...}, session=session)
        res = await coll.update_one({"id": x, "version": doc_version}, {...}, session=session)
        if res.matched_count != 1: raise conflict()        # CAS lost → 409, tx aborted
        await audit(session, user, "counterparty.updated", ...)
        return {...}
    return await once_in_tx(db, user, key, "counterparty.update", fingerprint, body)

* the same key + the same request → the stored first result, nothing written again;
* the same key + another request → 409 IDEMPOTENCY_KEY_REUSED;
* the same key while the first attempt runs → 409 IDEMPOTENCY_IN_PROGRESS;
* ``body`` refused (HTTPException) → the transaction is aborted, the key is marked failed
  (a clean retry may run again) and the refusal is returned unchanged.

A real MongoDB that cannot run transactions (standalone mongod) is refused with 503 —
auth_tx has deliberately no non-transactional fallback. Only the in-memory test double
(``TenantData.transaction_client`` is None) runs ``body(None)``, as invoice_line_lock does.
"""
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import HTTPException

IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"


def require_key(header: Optional[str]) -> str:
    """R29: a consequential write without an Idempotency-Key → 428, nothing written."""
    key = header.strip() if isinstance(header, str) else ""
    if not key:
        raise HTTPException(status_code=428, detail={
            "error_code": IDEMPOTENCY_KEY_REQUIRED,
            "message": "Липсва Idempotency-Key — заявката не е записана"})
    return key


def conflict(code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=409, detail=dict({"error_code": code, "message": message},
                                                      **extra))


def forbidden(message: str = "Нямате права за това действие", code: str = "FORBIDDEN") -> HTTPException:
    return HTTPException(status_code=403, detail={"error_code": code, "message": message})


def unprocessable(code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=422, detail=dict({"error_code": code, "message": message},
                                                      **extra))


def _is_test_double(db) -> bool:
    """mongomock_motor subclasses the motor classes, so the class tree is what tells it apart."""
    return any((c.__module__ or "").startswith("mongomock") for c in type(db).__mro__)


async def run_tx(db, body: Callable[[Any], Awaitable[Any]]) -> Any:
    from app.services.auth_tx import TransactionsUnavailable, run_in_transaction
    if _is_test_double(db):                             # the in-memory test double
        return await body(None)
    try:
        return await run_in_transaction(db, body)
    except TransactionsUnavailable:
        raise HTTPException(status_code=503, detail={
            "error_code": "TRANSACTIONS_UNAVAILABLE",
            "message": "Базата не поддържа транзакции — нищо не е записано"})


async def once_in_tx(db, user: Dict[str, Any], key: str, action: str, fingerprint: Any,
                     body: Callable[[Any], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
    from app.audit.idempotency import (IDEMPOTENCY_COLLECTION, IDEMPOTENCY_COMPLETED,
                                       IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED,
                                       IdempotencyConflict, _now_iso, _record_id,
                                       begin_idempotent, fail_idempotent, request_fingerprint)
    tenant_id = user["org_id"]
    try:
        state = await begin_idempotent(db, tenant_id=tenant_id, key=key, action=action,
                                       request_fingerprint=request_fingerprint(fingerprint))
    except IdempotencyConflict:
        raise conflict("IDEMPOTENCY_KEY_REUSED",
                       "Този Idempotency-Key вече е използван за друга заявка")
    if state["status"] == IDEMPOTENCY_DUPLICATE:
        if state.get("prior_status") == IDEMPOTENCY_COMPLETED:
            return json.loads(state["result_reference"])
        raise conflict("IDEMPOTENCY_IN_PROGRESS", "Заявка с този Idempotency-Key още се обработва")
    if state["status"] != IDEMPOTENCY_STARTED:
        raise conflict("IDEMPOTENCY_IN_PROGRESS", "Заявка с този Idempotency-Key още се обработва")
    record_id = _record_id(tenant_id, action, key)

    async def tx_body(session):
        result = await body(session)
        stored = json.dumps(result, sort_keys=True, default=str)
        kw = {} if session is None else {"session": session}
        await db[IDEMPOTENCY_COLLECTION].update_one(
            {"id": record_id, "tenant_id": tenant_id, "status": IDEMPOTENCY_STARTED},
            {"$set": {"status": IDEMPOTENCY_COMPLETED, "result_reference": stored,
                      "completed_at": _now_iso()}}, **kw)
        return stored

    try:
        stored = await run_tx(db, tx_body)
    except HTTPException as exc:
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=action,
                              error_code="HTTP_%d" % exc.status_code)
        raise
    except Exception:
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=action, error_code="ERROR")
        raise
    return json.loads(stored)


async def audit(db, session, user: Dict[str, Any], action: str, *, entity_type: str,
                entity_id: str, diff: Optional[Dict[str, Any]] = None,
                reason: Optional[str] = None, key: Optional[str] = None,
                source_flow: str = "FLOW-010", approval_id: Optional[str] = None,
                related_file_ids: Optional[List[str]] = None,
                entity_version: Optional[str] = None, result: Optional[str] = None,
                error_code: Optional[str] = None) -> Dict[str, Any]:
    """The canonical W0-04 AuditEvent, appended inside the caller's transaction (D-08).
    The caller masks IBAN / ЕГН in ``diff`` before it gets here (R48.3, FLOW-040 §9)."""
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    kw = {}
    if result:
        kw["result"] = result
    event = build_event(
        tenant_id=user["org_id"], actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow=source_flow, retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=entity_type, entity_id=entity_id, entity_version=entity_version,
        structured_diff=diff, reason=reason, idempotency_key=key, approval_id=approval_id,
        related_file_ids=related_file_ids, effective_role_assignments=[user.get("role") or ""],
        source_channel="api", error_code=error_code, **kw)
    return await record_event(db, event, session=session)


def kw(session) -> Dict[str, Any]:
    return {} if session is None else {"session": session}


#: FG-230: the ONE ``dq_issues`` row shape, the same as #81 (WH-FIX-01,
#: ``invoice_allocation.sync_invoice_issue``): ``id, org_id, type, title, entity_type,
#: entity_id, status ("open" / "resolved"), owner_role, opened_at, updated_at``. CP-01 adds
#: ``severity``, ``message``, ``data``, ``created_by``, ``occurrences``, ``last_seen_at``.
DQ_OWNER_ROLE = "accountant"        # the office maps and corrects (FLOW-032 L110), as #81


async def dq_issue(tenant, session, *, code: str, severity: str, entity_type: str,
                   entity_id: Optional[str], message: str, data: Optional[Dict[str, Any]] = None,
                   created_by: Optional[str] = None, owner_role: str = DQ_OWNER_ROLE) -> Dict[str, Any]:
    """A Data Quality row (``dq_issues``) — until the canonical DQ/Approval runtime (W0-07)
    exists (debt CP-01-D3). One OPEN row per (type, entity): a repeat counts an occurrence."""
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-dq:%s:%s:%s:%s" % (
        tenant.org_id, code, entity_type, entity_id or "-")))
    doc = {"id": row_id, "org_id": tenant.org_id, "type": code, "title": message,
           "entity_type": entity_type, "entity_id": entity_id, "status": "open",
           "owner_role": owner_role, "opened_at": now,
           # CP-01 fields
           "code": code, "severity": severity, "message": message, "data": data or {},
           "created_by": created_by, "created_at": now}
    await tenant.dq_issues.update_one({"id": row_id},
                                      {"$setOnInsert": doc,
                                       "$set": {"last_seen_at": now, "updated_at": now},
                                       "$inc": {"occurrences": 1}},
                                      upsert=True, **kw(session))
    return doc


async def notify_roles(tenant, session, *, roles, ntype: str, title: str,
                       message: str, data: Optional[Dict[str, Any]] = None) -> int:
    """R48.2 — an immediate in-app notification (the existing ``notifications`` collection
    read by /api/notifications/my) to every active user of the given roles."""
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    users = await tenant.users.find({"role": {"$in": list(roles)},
                                    "is_active": {"$ne": False}},
                                   {"_id": 0, "id": 1}, **kw(session)).to_list(200)
    for u in users:
        await tenant.notifications.insert_one({
            "id": str(uuid.uuid4()), "org_id": tenant.org_id, "user_id": u["id"], "type": ntype,
            "title": title, "message": message, "data": data or {}, "is_read": False,
            "created_at": now}, **kw(session))
    return len(users)
