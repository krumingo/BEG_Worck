"""
LIVE-OPS-01 / TASK 5B — Material Request command service (safe-write core).

The ONLY writer of the existing ``material_requests`` aggregate for request
control actions (contract v6 §2.2, §3.2). There is no second request model and
no new request collection: the stored ``status`` field remains the one control
state and is exposed to clients as ``request_state``.

Every consequential command:

1. requires ``PERMISSION_SERVICE_MODE=enforce`` (checked by the route
   dependency; anything else fails closed — LO-I-001);
2. resolves the tenant server-side (Tenant Guard) and loads the target inside
   that tenant; the project scope comes from the STORED request, never from the
   body (§7.1);
3. makes one Permission Service decision for the exact action and project scope
   (deny by default, no JWT-role fallback);
4. runs ONE Mongo transaction on a replica set that claims the idempotency key,
   re-reads the request, applies a version compare-and-set, appends the
   canonical AuditEvent and completes the idempotency record (§3.3, §4.3);
5. returns the original result on an identical retry and rejects a different
   payload under the same key (LO-I-009).

Denials, validation stops and idempotent replays are canonical AuditEvents too
(§7.2). Nothing here writes warehouse, batch/FIFO, invoice, asset, QR or Master
Data records: free text stays an explicit ``pending_mapping`` line and approval
fails closed until the line carries a confirmed ``item_id`` (LO-I-005).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.audit.envelope import (
    ACTOR_HUMAN,
    RESULT_DENIED,
    RESULT_FAILURE,
    RESULT_SUCCESS,
    RETENTION_R2_PROJECT_OPERATIONAL,
    build_event,
)
from app.audit.idempotency import (
    IDEMPOTENCY_COLLECTION,
    IDEMPOTENCY_COMPLETED,
    IDEMPOTENCY_DUPLICATE,
    IdempotencyConflict,
    begin_idempotent,
    complete_idempotent,
    request_fingerprint,
)
from app.audit.store import AUDIT_COLLECTION, record_event
from app.tenancy.data_access import TenantData

SOURCE_FLOW = "FLOW-020"
ENTITY_TYPE = "material_request"
COLLECTION = "material_requests"
LEDGER = "warehouse_transactions"           # read-only here: facts are projected, never written
ITEM_COLLECTION = "md_item"

# ---------------------------------------------------------------- control states
STATE_DRAFT = "draft"
STATE_SUBMITTED = "submitted"
STATE_APPROVED = "approved"
STATE_REJECTED = "rejected"
STATE_CANCELLED = "cancelled"
CONTROL_STATES = (STATE_DRAFT, STATE_SUBMITTED, STATE_APPROVED, STATE_REJECTED, STATE_CANCELLED)

# ---------------------------------------------------------------- command codes
CMD_CREATE = "create"
CMD_EDIT_DRAFT = "edit_draft"
CMD_SUBMIT = "submit"
CMD_APPROVE = "approve"
CMD_REJECT = "reject"
CMD_CANCEL = "cancel"
COMMANDS = (CMD_CREATE, CMD_EDIT_DRAFT, CMD_SUBMIT, CMD_APPROVE, CMD_REJECT, CMD_CANCEL)

# Permission action per command (contract §3.2). Reject uses the approve action;
# cancel of an APPROVED request needs the separate cancel_approved action.
ACTION_CREATE = "material_request.create"
ACTION_EDIT_DRAFT = "material_request.edit_draft"
ACTION_SUBMIT = "material_request.submit"
ACTION_APPROVE = "material_request.approve"
ACTION_CANCEL = "material_request.cancel"
ACTION_CANCEL_APPROVED = "material_request.cancel_approved"
REQUEST_ACTIONS = (ACTION_CREATE, ACTION_EDIT_DRAFT, ACTION_SUBMIT, ACTION_APPROVE,
                   ACTION_CANCEL, ACTION_CANCEL_APPROVED)

#: The only valid control transitions in the pilot (§3.2). No reopen.
TRANSITIONS = {
    CMD_EDIT_DRAFT: ((STATE_DRAFT,), STATE_DRAFT),
    CMD_SUBMIT: ((STATE_DRAFT,), STATE_SUBMITTED),
    CMD_APPROVE: ((STATE_SUBMITTED,), STATE_APPROVED),
    CMD_REJECT: ((STATE_SUBMITTED,), STATE_REJECTED),
    CMD_CANCEL: ((STATE_DRAFT, STATE_SUBMITTED, STATE_APPROVED), STATE_CANCELLED),
}

MAPPING_CONFIRMED = "confirmed"
MAPPING_PENDING = "pending_mapping"

PRIORITIES = ("low", "normal", "high", "urgent")
DESTINATION_TYPES = ("warehouse", "project")
BLOCKED_PROJECT_STATUSES = {"Completed", "Cancelled", "Archived"}

#: Bounded retry of the whole transaction (TransientTransactionError, an audit
#: sequence collision on the unique (tenant_id, sequence) index, or a
#: duplicate-key race on the idempotency claim). Each retry re-reads everything.
MAX_TXN_ATTEMPTS = 8

#: Display numbers: ``MR-`` followed by digits only. Anything else in legacy
#: data is reported by the inventory and ignored by the allocator.
REQUEST_NUMBER_PATTERN = r"^MR-[0-9]+$"
REQUEST_NUMBER_PREFIX = "MR-"
#: Partial filter of the request-number uniqueness index: legacy rows without a
#: number (e.g. the retired field writer) are not indexed, every string is.
REQUEST_NUMBER_PARTIAL = {"request_number": {"$type": "string"}}

#: Unique indexes that MUST exist before any write (contract §9.3, §12 item 5),
#: as ``(collection, keys, partialFilterExpression or None)``. This tuple is the
#: single source for the runtime gate AND the bootstrap/verify tool
#: (``scripts/live_ops_b_bootstrap.py``).
REQUIRED_UNIQUE_INDEXES = (
    (AUDIT_COLLECTION, (("event_id", 1),), None),
    (AUDIT_COLLECTION, (("tenant_id", 1), ("sequence", 1)), None),
    (IDEMPOTENCY_COLLECTION, (("id", 1),), None),
    (COLLECTION, (("org_id", 1), ("request_number", 1)), REQUEST_NUMBER_PARTIAL),
)

#: Draft fields a client may author (contract §2.2 "Mutable in DRAFT").
DRAFT_HEADER_FIELDS = (
    "needed_date", "priority", "reason", "notes", "stage_name",
    "destination_type", "destination_id", "sub_location", "work_package_ref",
    "partial_delivery_allowed",
)
LINE_INPUT_FIELDS = (
    "id", "item_id", "pending_mapping_id", "material_name", "category", "unit",
    "qty_requested", "dimension_spec", "notes", "allowed_equivalents",
)


class CommandError(Exception):
    """A refused command. Carries the HTTP status and a stable error code."""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def detail(self) -> Dict[str, Any]:
        return {"error_code": self.code, "message": self.message, **self.extra}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_transient(exc: BaseException) -> bool:
    labels = getattr(exc, "has_error_label", None)
    if callable(labels) and (labels("TransientTransactionError")
                             or labels("UnknownTransactionCommitResult")):
        return True
    return (type(exc).__name__ == "DuplicateKeyError"
            or getattr(exc, "code", None) in (11000, 112, 251))


# ═══════════════════════════════════════════════════════════════ validation
def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError(422, "INVALID_QUANTITY", "%s must be a number" % what)
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        raise CommandError(422, "INVALID_QUANTITY", "%s must be finite" % what)
    return value


def _text(value: Any, what: str, *, required: bool = False, limit: int = 2000) -> Optional[str]:
    if value is None or value == "":
        if required:
            raise CommandError(422, "FIELD_REQUIRED", "%s is required" % what, field=what)
        return None
    if not isinstance(value, str):
        raise CommandError(422, "INVALID_FIELD", "%s must be text" % what, field=what)
    value = value.strip()
    if required and not value:
        raise CommandError(422, "FIELD_REQUIRED", "%s is required" % what, field=what)
    if len(value) > limit:
        raise CommandError(422, "FIELD_TOO_LONG", "%s is too long" % what, field=what)
    return value or None


def _reject_unknown(payload: Dict[str, Any], allowed: Tuple[str, ...], where: str) -> None:
    """Raw state, actor, approval, fulfilment and derived fields are never accepted (§3.4)."""
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise CommandError(422, "FIELD_NOT_ALLOWED",
                           "Fields not allowed in %s: %s" % (where, ", ".join(unknown)),
                           fields=unknown)


def _header_from(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for f in DRAFT_HEADER_FIELDS:
        if f not in payload:
            continue
        v = payload[f]
        if f == "priority":
            if v is not None and v not in PRIORITIES:
                raise CommandError(422, "INVALID_PRIORITY", "priority must be one of %s" % ", ".join(PRIORITIES))
        elif f == "destination_type":
            if v is not None and v not in DESTINATION_TYPES:
                raise CommandError(422, "INVALID_DESTINATION",
                                   "destination_type must be one of %s" % ", ".join(DESTINATION_TYPES))
        elif f == "partial_delivery_allowed":
            if v is not None and not isinstance(v, bool):
                raise CommandError(422, "INVALID_FIELD", "partial_delivery_allowed must be true/false")
        elif f == "needed_date":
            v = _text(v, f, limit=40)
            if v is not None:
                try:
                    datetime.fromisoformat(v[:10])
                except ValueError:
                    raise CommandError(422, "INVALID_DATE", "needed_date must be an ISO date")
        else:
            v = _text(v, f)
        out[f] = v
    return out


async def _validate_lines(db, session, tenant_id: str, raw_lines: Any,
                          existing: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Normalize draft lines. A line keeps its stable id across draft edits;
    a confirmed ``item_id`` must be an active Master item of THIS tenant;
    anything else is an explicit pending-mapping line. Nothing is written to
    Master Data here."""
    if not isinstance(raw_lines, list):
        raise CommandError(422, "INVALID_LINES", "lines must be a list")
    if len(raw_lines) > 200:
        raise CommandError(422, "INVALID_LINES", "too many lines")
    known_ids = {l.get("id") for l in (existing or []) if l.get("id")}
    seen = set()
    out = []
    for i, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            raise CommandError(422, "INVALID_LINES", "line %d must be an object" % (i + 1))
        _reject_unknown(raw, LINE_INPUT_FIELDS, "line %d" % (i + 1))
        line_id = raw.get("id")
        if line_id is not None:
            if line_id not in known_ids:
                raise CommandError(422, "UNKNOWN_LINE_ID",
                                   "line %d id is not a line of this draft" % (i + 1))
        else:
            line_id = str(uuid.uuid4())
        if line_id in seen:
            raise CommandError(422, "DUPLICATE_LINE_ID", "duplicate line id")
        seen.add(line_id)

        qty = _num(raw.get("qty_requested"), "qty_requested")
        if qty <= 0:
            raise CommandError(422, "INVALID_QUANTITY", "qty_requested must be positive",
                               line=i + 1)
        unit = _text(raw.get("unit"), "unit", required=True, limit=40)
        name = _text(raw.get("material_name"), "material_name", limit=300)

        item_id = _text(raw.get("item_id"), "item_id", limit=200)
        if item_id is not None:
            extra = {"session": session} if session is not None else {}
            item = await db[ITEM_COLLECTION].find_one(
                {"tenant_id": tenant_id, "id": item_id, "status": "active"},
                {"_id": 0, "id": 1, "display_name": 1}, **extra)
            if not item:
                # A foreign, merged, archived or unknown id is never trusted.
                raise CommandError(422, "ITEM_NOT_FOUND",
                                   "item_id is not an active Master item of this tenant",
                                   line=i + 1)
            mapping_status = MAPPING_CONFIRMED
            name = name or item.get("display_name")
        else:
            mapping_status = MAPPING_PENDING
            if not name:
                raise CommandError(422, "FIELD_REQUIRED",
                                   "material_name is required for an unmapped line", line=i + 1)

        equivalents = raw.get("allowed_equivalents")
        if equivalents is not None:
            if not isinstance(equivalents, list) or not all(isinstance(e, str) for e in equivalents):
                raise CommandError(422, "INVALID_FIELD", "allowed_equivalents must be a list of text")
            equivalents = [e.strip() for e in equivalents if e.strip()][:20]

        prior = next((l for l in (existing or []) if l.get("id") == line_id), {})
        out.append({
            "id": line_id,
            "item_id": item_id,
            "mapping_status": mapping_status,
            "pending_mapping_id": _text(raw.get("pending_mapping_id"), "pending_mapping_id", limit=200)
            if item_id is None else None,
            "material_name": name,
            "category": _text(raw.get("category"), "category", limit=200),
            "qty_requested": qty,
            "unit": unit,
            "dimension_spec": _text(raw.get("dimension_spec"), "dimension_spec", limit=500),
            "notes": _text(raw.get("notes"), "notes"),
            "allowed_equivalents": equivalents or [],
            # Read-only legacy fact carried unchanged (no code writes it).
            "qty_fulfilled": prior.get("qty_fulfilled", 0),
            "sort_order": i,
        })
    return out


# ═══════════════════════════════════════════════════════════════ line facts
async def line_facts(db, org_id: str, line_ids: List[str], session=None) -> Dict[str, Dict[str, float]]:
    """Physical/readiness facts per request line, READ from the canonical ledger.

    The request aggregate never writes these (LO-I-018). Lines are matched by a
    stable ``request_line_id`` either on the ledger row or on one of its lines.
    """
    facts: Dict[str, Dict[str, float]] = {
        lid: {"reserved": 0.0, "released": 0.0, "issued": 0.0, "accepted": 0.0} for lid in line_ids}
    if not line_ids:
        return facts
    extra = {"session": session} if session is not None else {}
    cursor = db[LEDGER].find(
        {"org_id": org_id,
         "$or": [{"request_line_id": {"$in": line_ids}},
                 {"lines.request_line_id": {"$in": line_ids}}]},
        {"_id": 0, "movement_type": 1, "type": 1, "qty": 1, "request_line_id": 1,
         "lines": 1, "status": 1}, **extra)
    key = {"reserve": "reserved", "release_reservation": "released",
           "issue": "issued", "receive": "accepted"}
    async for row in cursor:
        kind = key.get(row.get("movement_type") or row.get("type"))
        if kind is None or row.get("status") not in (None, "posted"):
            continue
        parts = [row] if row.get("request_line_id") in facts else [
            l for l in (row.get("lines") or []) if l.get("request_line_id") in facts]
        for part in parts:
            q = part.get("qty")
            if q is None:
                q = part.get("qty_received") or part.get("qty_issued") or 0
            try:
                facts[part["request_line_id"]][kind] += float(q or 0)
            except (TypeError, ValueError):
                continue
    return facts


def project_line(line: Dict[str, Any], fact: Optional[Dict[str, float]], state: str) -> Dict[str, Any]:
    """Line with server-derived quantities. ``remaining_qty`` is never stored."""
    fact = fact or {"reserved": 0.0, "released": 0.0, "issued": 0.0, "accepted": 0.0}
    requested = float(line.get("qty_requested") or 0)
    approved = line.get("qty_approved")
    base = float(approved) if approved is not None else requested
    cancelled = float(line.get("qty_cancelled") or 0)
    legacy_fulfilled = float(line.get("qty_fulfilled") or 0)
    executed = fact["accepted"] + legacy_fulfilled
    open_qty = 0.0 if state in (STATE_REJECTED,) else base - cancelled - executed
    if state == STATE_CANCELLED:
        open_qty = 0.0
    active_reserved = max(0.0, fact["reserved"] - fact["released"] - fact["issued"])
    out = dict(line)
    out.update({
        "mapping_status": line.get("mapping_status")
        or (MAPPING_CONFIRMED if line.get("item_id") else MAPPING_PENDING),
        "qty_approved": approved,
        "qty_cancelled": cancelled,
        "facts": {
            "reserved_active_qty": active_reserved,
            "issued_qty": fact["issued"],
            "accepted_qty": fact["accepted"],
            "legacy_fulfilled_qty": legacy_fulfilled,
            "source": "warehouse_transactions (read-only) + legacy line field",
        },
        "remaining_qty": max(0.0, open_qty),
        "over_qty": max(0.0, -open_qty) if state not in (STATE_REJECTED, STATE_CANCELLED) else 0.0,
    })
    return out


def project_request(doc: Dict[str, Any], facts: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    """API projection of one request: control state + truthful line facts.

    ``fulfilled`` is derived only (§3.1); the legacy stored value ``fulfilled``
    is reported as ``legacy_status`` and is never trusted as a fact.
    """
    out = {k: v for k, v in doc.items() if k != "_id"}
    stored = doc.get("status")
    state = stored if stored in CONTROL_STATES else None
    out["request_state"] = state
    out["legacy_status"] = stored if state is None else None
    lines = [project_line(l, facts.get(l.get("id")), state or "") for l in (doc.get("lines") or [])]
    out["lines"] = lines
    out["unmapped_lines"] = sum(1 for l in lines if l["mapping_status"] != MAPPING_CONFIRMED)
    out["remaining_qty_total"] = sum(l["remaining_qty"] for l in lines)
    out["has_partial_facts"] = any(
        (l["facts"]["accepted_qty"] or l["facts"]["legacy_fulfilled_qty"]) and l["remaining_qty"] > 0
        for l in lines)
    out["fulfilled_derived"] = bool(
        state == STATE_APPROVED and lines and all(l["remaining_qty"] == 0 for l in lines)
        and any(l["facts"]["accepted_qty"] or l["facts"]["legacy_fulfilled_qty"] for l in lines))
    out["version"] = int(doc.get("version") or 0)
    return out


# ═══════════════════════════════════════════════════════════════ preconditions
def missing_required_indexes(info_by_collection: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure check: which required unique indexes are absent from ``index_information()``.

    An index satisfies a requirement only when it is unique, has exactly the
    required keys in order, and — for a partial requirement — carries a partial
    filter that is at least as wide (a non-partial unique index is wider and
    therefore accepted).
    """
    missing = []
    for coll, keys, partial in REQUIRED_UNIQUE_INDEXES:
        want = [tuple(k) for k in keys]
        ok = False
        for spec in (info_by_collection.get(coll) or {}).values():
            if not spec.get("unique") or [tuple(k) for k in spec.get("key", [])] != want:
                continue
            have_partial = spec.get("partialFilterExpression")
            if have_partial is None or (partial is not None and have_partial == partial):
                ok = True
                break
        if not ok:
            missing.append({"collection": coll, "keys": [k for k, _ in keys],
                            "partial": partial})
    return missing


async def assert_required_indexes(db) -> None:
    """Fail closed when a required unique index is absent.

    Checked on EVERY command — there is deliberately no positive cache, so an
    index dropped after an earlier successful check disables the very next
    write (CODEX C01 F-03).
    """
    info: Dict[str, Dict[str, Any]] = {}
    for coll in sorted({c for c, _, _ in REQUIRED_UNIQUE_INDEXES}):
        try:
            info[coll] = await db[coll].index_information()
        except Exception:                                       # noqa: BLE001
            info[coll] = {}          # absent collection / unreadable: nothing satisfied
    missing = missing_required_indexes(info)
    if missing:
        raise CommandError(503, "REQUIRED_INDEX_MISSING",
                           "Required unique indexes are not provisioned for this tenant database; "
                           "request writes are disabled. Run scripts/live_ops_b_bootstrap.py "
                           "(inventory, then --apply) for this database.",
                           missing=missing)


# ═══════════════════════════════════════════════════════════════ audit helpers
def _event(*, ctx, action: str, result: str, request_id: Optional[str], project_id: Optional[str],
           diff: Optional[Dict[str, Any]], reason: Optional[str], correlation_id: str,
           idempotency_key: Optional[str], role_ids: List[str], error_code: Optional[str] = None,
           version: Optional[int] = None, channel: Optional[str] = None,
           endpoint: Optional[str] = None) -> Dict[str, Any]:
    return build_event(
        tenant_id=ctx.tenant_id,
        actor_type=ACTOR_HUMAN,
        actor_id=ctx.user_id,
        action=action,
        source_flow=SOURCE_FLOW,
        retention_class=RETENTION_R2_PROJECT_OPERATIONAL,
        result=result,
        entity_type=ENTITY_TYPE,
        entity_id=request_id,
        entity_version=str(version) if version is not None else None,
        scope_type="project" if project_id else None,
        scope_id=project_id,
        structured_diff=diff,
        reason=reason,
        source_channel=channel,
        tool_or_endpoint=endpoint,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        effective_role_assignments=role_ids,
        error_code=error_code,
    )


async def append_standalone_event(db, event: Dict[str, Any]) -> Dict[str, Any]:
    """Append one event in its own transaction (denial / validation stop),
    retrying an audit sequence collision after re-reading the chain head."""
    client = db.client
    last_exc: Optional[BaseException] = None
    for attempt in range(MAX_TXN_ATTEMPTS):
        async with await client.start_session() as s:
            try:
                async with s.start_transaction():
                    stored = await record_event(db, dict(event), session=s)
                return stored
            except Exception as exc:  # noqa: BLE001
                if not _is_transient(exc):
                    raise
                last_exc = exc
                await asyncio.sleep(0.005 * (attempt + 1))
    raise CommandError(503, "AUDIT_APPEND_FAILED", "Audit append did not settle",
                       cause=type(last_exc).__name__ if last_exc else None)


# ═══════════════════════════════════════════════════════════════ the command
class Command:
    """One command invocation: who, what, under which key."""

    def __init__(self, *, ctx, db, command: str, request_id: Optional[str],
                 payload: Dict[str, Any], idempotency_key: str, correlation_id: str,
                 channel: Optional[str], endpoint: Optional[str]):
        self.ctx = ctx
        self.db = db
        self.command = command
        self.request_id = request_id
        self.payload = payload
        self.idempotency_key = idempotency_key
        self.correlation_id = correlation_id
        self.channel = channel
        self.endpoint = endpoint
        self.action = "material_request." + command
        self.fingerprint = request_fingerprint(
            {"command": command, "request_id": request_id, "payload": payload})


async def execute(cmd: Command, *, decide) -> Dict[str, Any]:
    """Run one command atomically.

    ``decide(project_id, request_doc)`` is the injected Permission Service call;
    it returns ``(allowed, reason_code, role_assignment_ids, basis, revisions)``
    where ``basis`` is a dict: the exact ``action`` evaluated, the Permission
    Service ``decision`` and the ``basis`` that allowed the command
    (``permission`` or the frozen §3.2 ``requester`` alternative).
    """
    db, ctx = cmd.db, cmd.ctx
    org_id = ctx.org_id

    # ---- 1. target + scope from the stored record (existing-object commands)
    target = None
    if cmd.command != CMD_CREATE:
        target = await db[COLLECTION].find_one({"id": cmd.request_id, "org_id": org_id}, {"_id": 0})
        if target is None:
            # A foreign or unknown id is not confirmed to exist; the stop is
            # still recorded in the CALLER's tenant chain (§7.1 last line).
            await append_standalone_event(db, _event(
                ctx=ctx, action=cmd.action, result=RESULT_FAILURE, request_id=cmd.request_id,
                project_id=None, diff=None, reason="request not found in tenant",
                correlation_id=cmd.correlation_id, idempotency_key=cmd.idempotency_key,
                role_ids=[], error_code="NOT_FOUND", channel=cmd.channel, endpoint=cmd.endpoint))
            raise CommandError(404, "NOT_FOUND", "Request not found")
        project_id = target.get("project_id")
    else:
        project_id = _text(cmd.payload.get("project_id"), "project_id", required=True, limit=200)

    # ---- 2. one Permission Service decision for the exact action/scope
    allowed, reason_code, role_ids, basis, revisions = await decide(project_id, target)
    if not allowed:
        await append_standalone_event(db, _event(
            ctx=ctx, action=cmd.action, result=RESULT_DENIED, request_id=cmd.request_id,
            project_id=project_id, diff={"permission": basis}, reason="permission denied",
            correlation_id=cmd.correlation_id, idempotency_key=cmd.idempotency_key,
            role_ids=[], error_code=reason_code, channel=cmd.channel, endpoint=cmd.endpoint))
        raise CommandError(403, "PERMISSION_DENIED", "Нямате право за това действие по този обект.",
                           reason=reason_code, action=basis.get("action"))

    # ---- 3. the atomic boundary
    client = db.client
    last_exc: Optional[BaseException] = None
    for attempt in range(MAX_TXN_ATTEMPTS):
        async with await client.start_session() as s:
            try:
                async with s.start_transaction():
                    result = await _apply(cmd, s, project_id, role_ids,
                                          {**basis, "role_assignment_revisions": revisions})
                return result
            except CommandError as err:
                # The transaction aborted: no partial write. Record the stop.
                await append_standalone_event(db, _event(
                    ctx=ctx, action=cmd.action, result=RESULT_FAILURE, request_id=cmd.request_id,
                    project_id=project_id, diff={"payload_fingerprint": cmd.fingerprint},
                    reason=err.message, correlation_id=cmd.correlation_id,
                    idempotency_key=cmd.idempotency_key, role_ids=role_ids, error_code=err.code,
                    channel=cmd.channel, endpoint=cmd.endpoint))
                raise
            except Exception as exc:  # noqa: BLE001
                if not _is_transient(exc):
                    raise
                last_exc = exc
                await asyncio.sleep(0.005 * (attempt + 1))
    raise CommandError(409, "CONCURRENT_COMMAND",
                       "Another command on this request is in progress; retry with the same key.",
                       cause=type(last_exc).__name__ if last_exc else None)


async def _apply(cmd: Command, s, project_id: str, role_ids: List[str],
                 basis: Dict[str, Any]) -> Dict[str, Any]:
    db, ctx = cmd.db, cmd.ctx
    org_id = ctx.org_id
    try:
        claim = await begin_idempotent(db, tenant_id=ctx.tenant_id, key=cmd.idempotency_key,
                                       action=cmd.action, request_fingerprint=cmd.fingerprint,
                                       session=s)
    except IdempotencyConflict:
        raise CommandError(409, "IDEMPOTENCY_CONFLICT",
                           "The same Idempotency-Key was already used with a different payload.")

    if claim["status"] == IDEMPOTENCY_DUPLICATE:
        prior = claim.get("result_reference")
        if claim.get("prior_status") != IDEMPOTENCY_COMPLETED or not prior:
            raise CommandError(409, "IDEMPOTENCY_IN_PROGRESS",
                               "The original command under this key has not completed.")
        original = json.loads(prior)
        replay = await record_event(db, _event(
            ctx=ctx, action=ENTITY_TYPE + ".replay", result=RESULT_SUCCESS,
            request_id=original.get("request_id"), project_id=project_id,
            diff={"replayed_action": cmd.action, "original_event_id": original.get("event_id")},
            reason="idempotent replay; no new effect", correlation_id=cmd.correlation_id,
            idempotency_key=cmd.idempotency_key, role_ids=role_ids,
            version=original.get("version"), channel=cmd.channel, endpoint=cmd.endpoint),
            session=s)
        current = await db[COLLECTION].find_one(
            {"id": original.get("request_id"), "org_id": org_id}, {"_id": 0}, session=s)
        return {"replayed": True, "result": original, "replay_event_id": replay["event_id"],
                "request": current}

    now = _now()
    if cmd.command == CMD_CREATE:
        before, after, diff = None, await _create(cmd, s, project_id, now), None
        diff = {"after": _audit_view(after)}
    else:
        before = await db[COLLECTION].find_one({"id": cmd.request_id, "org_id": org_id},
                                               {"_id": 0}, session=s)
        if before is None:
            raise CommandError(404, "NOT_FOUND", "Request not found")
        after, diff = await _transition(cmd, s, before, now)

    event = await record_event(db, _event(
        ctx=ctx, action=cmd.action, result=RESULT_SUCCESS, request_id=after["id"],
        project_id=project_id, diff={**diff, "permission_basis": basis},
        reason=diff.get("reason") if isinstance(diff, dict) else None,
        correlation_id=cmd.correlation_id, idempotency_key=cmd.idempotency_key,
        role_ids=role_ids, version=after.get("version"), channel=cmd.channel,
        endpoint=cmd.endpoint), session=s)

    result = {"request_id": after["id"], "action": cmd.action,
              "request_state": after.get("status"), "version": after.get("version"),
              "event_id": event["event_id"], "correlation_id": cmd.correlation_id}
    await complete_idempotent(db, tenant_id=ctx.tenant_id, key=cmd.idempotency_key,
                              action=cmd.action, result_reference=json.dumps(result, sort_keys=True),
                              session=s)
    return {"replayed": False, "result": result, "request": after}


def _audit_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Safe before/after: control fields and line quantities, not the whole payload."""
    if doc is None:
        return None
    return {
        "status": doc.get("status"), "version": doc.get("version"),
        "project_id": doc.get("project_id"),
        "lines": [{"id": l.get("id"), "item_id": l.get("item_id"),
                   "mapping_status": l.get("mapping_status"),
                   "qty_requested": l.get("qty_requested"), "qty_approved": l.get("qty_approved"),
                   "qty_cancelled": l.get("qty_cancelled"), "unit": l.get("unit")}
                  for l in (doc.get("lines") or [])],
    }


async def _next_request_number(db, s, org_id: str) -> str:
    """Next tenant display number: highest existing ``MR-<digits>`` + 1.

    The maximum is taken over the NUMBER, not over the newest row, so legacy
    history stored out of order (an older MR-0003 beside a newer MR-0002) can
    never hand out an existing number again. Concurrent allocators may compute
    the same candidate; the unique ``(org_id, request_number)`` index makes the
    loser's transaction fail and the bounded retry recomputes (F-01).
    """
    cursor = db[COLLECTION].aggregate([
        {"$match": {"org_id": org_id, "request_number": {"$regex": REQUEST_NUMBER_PATTERN}}},
        {"$group": {"_id": None, "top": {"$max": {"$toLong": {
            "$substrCP": ["$request_number", len(REQUEST_NUMBER_PREFIX), 30]}}}}},
    ], session=s)
    rows = await cursor.to_list(1)
    top = int(rows[0]["top"]) if rows and rows[0].get("top") is not None else 0
    return "%s%04d" % (REQUEST_NUMBER_PREFIX, top + 1)


async def _create(cmd: Command, s, project_id: str, now: str) -> Dict[str, Any]:
    db, ctx = cmd.db, cmd.ctx
    allowed = ("project_id", "lines", "source_offer_id") + DRAFT_HEADER_FIELDS
    _reject_unknown(cmd.payload, allowed, "create")
    project = await TenantData.for_context(db, ctx).projects.find_one(
        {"id": project_id}, {"_id": 0, "id": 1, "status": 1, "name": 1}, session=s)
    if project is None:
        raise CommandError(404, "PROJECT_NOT_FOUND", "Project not found")
    if project.get("status") in BLOCKED_PROJECT_STATUSES:
        raise CommandError(409, "PROJECT_NOT_WRITABLE",
                           "Обектът е %s; нови заявки не се приемат." % project.get("status"))
    header = _header_from(cmd.payload)
    lines = await _validate_lines(db, s, ctx.tenant_id, cmd.payload.get("lines") or [])
    doc = {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "source_offer_id": _text(cmd.payload.get("source_offer_id"), "source_offer_id", limit=200),
        "request_number": await _next_request_number(db, s, ctx.org_id),
        "status": STATE_DRAFT,
        "version": 1,
        **{f: None for f in DRAFT_HEADER_FIELDS},
        "priority": "normal",
        "partial_delivery_allowed": True,
        **{k: v for k, v in header.items() if v is not None},
        "lines": lines,
        "created_at": now,
        "updated_at": now,
        "created_by": ctx.user_id,
        "requested_by": ctx.user_id,
        "write_path": "live_ops_b_command_service",
        "org_id": ctx.org_id,          # last: nothing above can replace the server's tenant
    }
    await TenantData.for_context(db, ctx).material_requests.insert_one(dict(doc), session=s)
    return doc


async def _transition(cmd: Command, s, before: Dict[str, Any], now: str):
    db, ctx = cmd.db, cmd.ctx
    from_states, to_state = TRANSITIONS[cmd.command]
    state = before.get("status")
    if state not in from_states:
        raise CommandError(409, "INVALID_TRANSITION",
                           "Действието '%s' не е позволено от състояние '%s'." % (cmd.command, state),
                           from_state=state, command=cmd.command)
    expected = cmd.payload.get("expected_version")
    version = int(before.get("version") or 0)
    if expected is not None and (isinstance(expected, bool) or expected != version):
        raise CommandError(409, "VERSION_CONFLICT",
                           "Заявката е променена междувременно. Презаредете.",
                           expected_version=expected, current_version=version)

    set_: Dict[str, Any] = {"updated_at": now}
    diff: Dict[str, Any] = {"from_state": state}
    lines = [dict(l) for l in (before.get("lines") or [])]

    if cmd.command == CMD_EDIT_DRAFT:
        _reject_unknown(cmd.payload, ("expected_version", "lines") + DRAFT_HEADER_FIELDS, "draft edit")
        header = _header_from(cmd.payload)
        set_.update(header)
        if "lines" in cmd.payload:
            lines = await _validate_lines(db, s, ctx.tenant_id, cmd.payload["lines"], existing=lines)
            set_["lines"] = lines
        diff["changed_fields"] = sorted(set(header) | ({"lines"} if "lines" in cmd.payload else set()))

    elif cmd.command == CMD_SUBMIT:
        _reject_unknown(cmd.payload, ("expected_version",), "submit")
        if not lines:
            raise CommandError(422, "NO_LINES", "Заявка без редове не може да бъде подадена.")
        for i, l in enumerate(lines):
            if not l.get("unit") or not isinstance(l.get("qty_requested"), (int, float)) \
                    or l["qty_requested"] <= 0:
                raise CommandError(422, "INVALID_LINE", "Ред %d няма валидно количество/мярка." % (i + 1))
            if not l.get("item_id") and not l.get("material_name"):
                raise CommandError(422, "INVALID_LINE", "Ред %d няма материал." % (i + 1))
            l["mapping_status"] = MAPPING_CONFIRMED if l.get("item_id") else MAPPING_PENDING
            if l.get("item_id"):
                item = await db[ITEM_COLLECTION].find_one(
                    {"tenant_id": ctx.tenant_id, "id": l["item_id"], "status": "active"},
                    {"_id": 0, "id": 1}, session=s)
                if not item:
                    raise CommandError(409, "ITEM_NOT_ACTIVE",
                                       "Ред %d сочи към Master материал, който вече не е активен." % (i + 1),
                                       line_id=l["id"])
        if not before.get("needed_date"):
            raise CommandError(422, "FIELD_REQUIRED", "Нужната дата е задължителна при подаване.",
                               field="needed_date")
        dest_type = before.get("destination_type")
        if dest_type not in DESTINATION_TYPES:
            raise CommandError(422, "FIELD_REQUIRED",
                               "Изберете дестинация: склад или директно на обекта.",
                               field="destination_type")
        if dest_type == "warehouse":
            wh = await TenantData.for_context(db, ctx).warehouses.find_one(
                {"id": before.get("destination_id")}, {"_id": 0, "id": 1, "active": 1}, session=s)
            if not wh or wh.get("active") is False:
                raise CommandError(422, "INVALID_DESTINATION",
                                   "Избраният склад не съществува или не е активен.",
                                   field="destination_id")
        elif before.get("destination_id") not in (None, before.get("project_id")):
            raise CommandError(422, "INVALID_DESTINATION",
                               "Директна доставка е възможна само към обекта на заявката.",
                               field="destination_id")
        set_.update({"lines": lines, "submitted_at": now, "submitted_by": ctx.user_id})
        diff["unmapped_lines"] = sum(1 for l in lines if l["mapping_status"] != MAPPING_CONFIRMED)

    elif cmd.command == CMD_APPROVE:
        _reject_unknown(cmd.payload, ("expected_version", "lines", "note",
                                      "partial_delivery_allowed"), "approve")
        unmapped = [l["id"] for l in lines if not l.get("item_id")]
        if unmapped:
            raise CommandError(409, "UNMAPPED_MATERIAL",
                               "Има редове без потвърден Master материал; одобрението е блокирано "
                               "до мапване.", line_ids=unmapped)
        overrides = {}
        for o in cmd.payload.get("lines") or []:
            if not isinstance(o, dict):
                raise CommandError(422, "INVALID_LINES", "approval line must be an object")
            _reject_unknown(o, ("line_id", "qty_approved"), "approval line")
            overrides[o.get("line_id")] = _num(o.get("qty_approved"), "qty_approved")
        unknown = set(overrides) - {l["id"] for l in lines}
        if unknown:
            raise CommandError(422, "UNKNOWN_LINE_ID", "approval names a line that is not on this request")
        for l in lines:
            q = overrides.get(l["id"], float(l["qty_requested"]))
            if q <= 0 or q > float(l["qty_requested"]):
                raise CommandError(422, "INVALID_QUANTITY",
                                   "Одобреното количество трябва да е > 0 и ≤ заявеното.",
                                   line_id=l["id"])
            l["qty_approved"] = q
        pda = cmd.payload.get("partial_delivery_allowed")
        if pda is not None:
            if not isinstance(pda, bool):
                raise CommandError(422, "INVALID_FIELD", "partial_delivery_allowed must be true/false")
            set_["partial_delivery_allowed"] = pda
        set_.update({"lines": lines, "approved_at": now, "approved_by": ctx.user_id,
                     "approval_note": _text(cmd.payload.get("note"), "note")})
        diff["approved"] = {l["id"]: l["qty_approved"] for l in lines}

    elif cmd.command == CMD_REJECT:
        _reject_unknown(cmd.payload, ("expected_version", "reason"), "reject")
        reason = _text(cmd.payload.get("reason"), "reason", required=True)
        set_.update({"rejected_at": now, "rejected_by": ctx.user_id, "rejection_reason": reason})
        diff["reason"] = reason

    elif cmd.command == CMD_CANCEL:
        _reject_unknown(cmd.payload, ("expected_version", "reason", "lines"), "cancel")
        reason = _text(cmd.payload.get("reason"), "reason", required=True)
        diff["reason"] = reason
        facts = await line_facts(db, ctx.org_id, [l["id"] for l in lines], session=s)
        partial = cmd.payload.get("lines")
        if partial is not None and state != STATE_APPROVED:
            raise CommandError(422, "PARTIAL_CANCEL_NOT_ALLOWED",
                               "Частично анулиране е възможно само за одобрена заявка.")
        targets: Dict[str, Optional[float]] = {}
        if partial is not None:
            if not isinstance(partial, list) or not partial:
                raise CommandError(422, "INVALID_LINES", "lines must be a non-empty list")
            for o in partial:
                if not isinstance(o, dict):
                    raise CommandError(422, "INVALID_LINES", "cancel line must be an object")
                _reject_unknown(o, ("line_id", "qty"), "cancel line")
                targets[o.get("line_id")] = _num(o.get("qty"), "qty")
            if set(targets) - {l["id"] for l in lines}:
                raise CommandError(422, "UNKNOWN_LINE_ID", "cancel names a line that is not on this request")
        else:
            targets = {l["id"]: None for l in lines}

        cancelled_any = False
        deltas = {}
        for l in lines:
            if l["id"] not in targets:
                continue
            p = project_line(l, facts.get(l["id"]), state)
            remaining = p["remaining_qty"]
            want = targets[l["id"]]
            qty = remaining if want is None else want
            if want is not None and (qty <= 0 or qty > remaining):
                raise CommandError(422, "INVALID_QUANTITY",
                                   "Може да се анулира само оставащо количество (> 0 и ≤ остатъка).",
                                   line_id=l["id"], remaining_qty=remaining)
            if qty <= 0:
                continue
            if p["facts"]["reserved_active_qty"] > 0:
                # Cancelling would need a canonical reservation release, which
                # only the warehouse domain may write. Refuse atomically (C01 §8).
                raise CommandError(409, "RESERVATION_RELEASE_NOT_AVAILABLE",
                                   "Редът има активна резервация в склада. Анулирането изисква "
                                   "складово освобождаване, което не е налично в този модул.",
                                   line_id=l["id"])
            if state == STATE_APPROVED:
                l["qty_cancelled"] = float(l.get("qty_cancelled") or 0) + qty
            deltas[l["id"]] = qty
            cancelled_any = True
        if state == STATE_APPROVED and not cancelled_any:
            raise CommandError(409, "NOTHING_TO_CANCEL", "Няма оставащо количество за анулиране.")
        diff["cancelled_qty"] = deltas
        set_.update({"lines": lines, "cancellation_reason": reason})
        if partial is None:
            set_.update({"cancelled_at": now, "cancelled_by": ctx.user_id})
        else:
            to_state = state  # a partial line cancellation keeps the request approved

    new_version = version + 1
    set_["status"] = to_state
    set_["version"] = new_version
    res = await TenantData.for_context(db, ctx).material_requests.update_one(
        {"id": before["id"], "org_id": ctx.org_id, "status": state,
         "version": before.get("version") if "version" in before else {"$exists": False}},
        {"$set": set_}, session=s)
    if res.matched_count != 1:
        raise CommandError(409, "CONCURRENT_MODIFICATION",
                           "Заявката беше променена от друго действие. Презаредете.")
    after = await db[COLLECTION].find_one({"id": before["id"], "org_id": ctx.org_id},
                                          {"_id": 0}, session=s)
    diff.update({"to_state": to_state, "before": _audit_view(before), "after": _audit_view(after)})
    return after, diff
