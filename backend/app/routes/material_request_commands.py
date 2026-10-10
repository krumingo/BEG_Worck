"""
LIVE-OPS-01 / TASK 5B — Material Request command and read routes.

Named command endpoints only (contract v6 §3.2, LO-I-008):

    POST  /material-requests                 create  → draft
    PATCH /material-requests/{id}/draft      draft edit (draft fields only)
    POST  /material-requests/{id}/submit     draft → submitted
    POST  /material-requests/{id}/approve    submitted → approved
    POST  /material-requests/{id}/reject     submitted → rejected
    POST  /material-requests/{id}/cancel     draft/submitted → cancelled;
                                             approved → remaining quantity only

Every command needs ``Idempotency-Key`` and runs only when
``PERMISSION_SERVICE_MODE`` is exactly ``enforce``; any other value, an unknown
value or an unavailable tenant/permission resolver fails closed before any
write. The legacy generic writers (raw ``PUT``, ``DELETE``, ``from-offer``) are
retired here and answer 410 with the canonical replacement.

Reads (list, detail view, history) never write. The detail view reports which
actions the caller may perform as a Permission Service evaluation, never as a
JWT-role guess; history is the canonical ``audit_events`` chain only.
"""
import os
import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.db import db
from app.deps.modules import require_m2
from app.tenancy.data_access import TenantData
from app.services import material_request_commands as mrc

router = APIRouter(tags=["Material Requests"])

_KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{8,200}$")
_CHANNELS = {"desktop", "phone"}


def _tenant(user: dict) -> TenantData:
    """The request's tenant for READS — from the server-loaded session user only."""
    return TenantData.for_user(db, user)


def _raw_mode() -> str:
    return (os.environ.get("PERMISSION_SERVICE_MODE") or "").strip().lower()


def _fail(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message, **extra})


async def _audit_not_enforced(user: dict, request: Request, mode: str) -> None:
    """Record the fail-closed refusal in the legacy context's own chain.

    Best effort by design: the request is refused whether or not this event can
    be written, and no business write follows either way.
    """
    try:
        from app.audit.envelope import build_event, ACTOR_HUMAN, RESULT_DENIED, \
            RETENTION_R3_SECURITY_ACCESS
        from app.audit.store import record_event
        from app.tenancy.guard import LegacyCompatContext
        ctx = LegacyCompatContext(user, mode=mode or "unset")
        await record_event(await ctx.db(), build_event(
            tenant_id=ctx.tenant_id, actor_type=ACTOR_HUMAN, actor_id=ctx.user_id,
            action="material_request.write_refused", source_flow=mrc.SOURCE_FLOW,
            retention_class=RETENTION_R3_SECURITY_ACCESS, result=RESULT_DENIED,
            entity_type=mrc.ENTITY_TYPE, error_code="PERMISSION_SERVICE_NOT_ENFORCED",
            tool_or_endpoint="%s %s" % (request.method, request.url.path),
            reason="PERMISSION_SERVICE_MODE=%r; LIVE-OPS writes fail closed" % (mode or "unset"),
            correlation_id=request.headers.get("x-correlation-id")))
    except Exception:                                          # noqa: BLE001
        pass


async def write_context(request: Request, user: dict = Depends(require_m2)):
    """Tenant Guard for a request COMMAND. Fails closed outside ``enforce``."""
    mode = _raw_mode()
    if mode != "enforce":
        await _audit_not_enforced(user, request, mode)
        raise _fail(503, "PERMISSION_SERVICE_NOT_ENFORCED",
                    "Записът на заявки е изключен: Permission Service не е в режим enforce.",
                    mode=mode or "unset")
    from app.tenancy.guard import get_tenant_context
    from app.tenancy.resolver import TenantNotFound, TenantNotOperational
    from app.permissions.deps import require_legacy_data_path
    try:
        ctx = await get_tenant_context(request, user)
    except HTTPException:
        raise
    except Exception as exc:                                   # noqa: BLE001
        raise _fail(503, "TENANT_RESOLUTION_UNAVAILABLE",
                    "Tenant не може да бъде определен; записът е отказан.", cause=type(exc).__name__)
    ctx.mode = "enforce"
    if not ctx.is_operational:
        raise _fail(402, "TENANT_READ_ONLY", "Tenant е в режим само за четене.", status=ctx.status)
    try:
        tdb = await ctx.db(require_operational=True)
    except TenantNotOperational:
        raise _fail(402, "TENANT_READ_ONLY", "Tenant е в режим само за четене.")
    except TenantNotFound:
        raise _fail(403, "TENANT_NOT_REGISTERED", "Unknown tenant")
    except Exception as exc:                                   # noqa: BLE001
        raise _fail(503, "TENANT_RESOLUTION_UNAVAILABLE",
                    "Базата на tenant-а не е достъпна; записът е отказан.", cause=type(exc).__name__)
    # Reads of this aggregate still use the legacy handle; a write must land in
    # the same database or not at all (PR-04 §5).
    await require_legacy_data_path(ctx, db)
    try:
        await mrc.assert_required_indexes(tdb)
    except mrc.CommandError as err:
        raise HTTPException(status_code=err.status, detail=err.detail())
    return ctx, tdb


def _headers(request: Request):
    key = (request.headers.get("idempotency-key") or "").strip()
    if not key:
        raise _fail(428, "IDEMPOTENCY_KEY_REQUIRED", "Липсва Idempotency-Key.")
    if not _KEY_RE.match(key):
        raise _fail(422, "IDEMPOTENCY_KEY_INVALID", "Невалиден Idempotency-Key.")
    corr = (request.headers.get("x-correlation-id") or "").strip()
    if not corr or not _KEY_RE.match(corr):
        corr = "corr_" + uuid.uuid4().hex
    channel = (request.headers.get("x-client-channel") or "").strip().lower()
    return key, corr, (channel if channel in _CHANNELS else "api")


def _decider(ctx, command: str):
    """The single Permission Service decision for this command (§7.1).

    The project scope is passed in by the service from the STORED request (or,
    for create, the project being created under). The requester basis for draft
    edit / pre-approval cancel still needs the requester's own project-scope
    ``material_request.create`` assignment — there is no role-name shortcut.
    """
    from app.permissions.service import evaluate_permission, ALLOWED
    from app.tenancy import registry

    async def revisions(ids):
        try:
            rows = await registry.list_role_assignments(ctx.user_id, ctx.tenant_id)
        except Exception:                                       # noqa: BLE001
            return {}
        return {r.get("id"): r.get("revision") for r in rows if r.get("id") in ids}

    async def decide(project_id, target):
        if command == mrc.CMD_CANCEL and target and target.get("status") == mrc.STATE_APPROVED:
            action = mrc.ACTION_CANCEL_APPROVED
        else:
            action = {mrc.CMD_CREATE: mrc.ACTION_CREATE, mrc.CMD_EDIT_DRAFT: mrc.ACTION_EDIT_DRAFT,
                      mrc.CMD_SUBMIT: mrc.ACTION_SUBMIT, mrc.CMD_APPROVE: mrc.ACTION_APPROVE,
                      mrc.CMD_REJECT: mrc.ACTION_APPROVE, mrc.CMD_CANCEL: mrc.ACTION_CANCEL}[command]
        try:
            d = await evaluate_permission(ctx, action, scope_type="project", scope_id=project_id)
            if d.allowed:
                return True, ALLOWED, d.effective_assignment_ids, action, \
                    await revisions(d.effective_assignment_ids)
            requester_ok = (
                target is not None
                and (target.get("requested_by") or target.get("created_by")) == ctx.user_id
                and ((command == mrc.CMD_EDIT_DRAFT and target.get("status") == mrc.STATE_DRAFT)
                     or (command == mrc.CMD_CANCEL
                         and target.get("status") in (mrc.STATE_DRAFT, mrc.STATE_SUBMITTED))))
            if requester_ok:
                d2 = await evaluate_permission(ctx, mrc.ACTION_CREATE, scope_type="project",
                                               scope_id=project_id)
                if d2.allowed:
                    return True, ALLOWED, d2.effective_assignment_ids, \
                        "requester+" + mrc.ACTION_CREATE, await revisions(d2.effective_assignment_ids)
            return False, d.reason_code, [], action, {}
        except Exception as exc:                                # noqa: BLE001
            # Unknown is never ALLOW.
            raise mrc.CommandError(503, "PERMISSION_EVALUATION_UNAVAILABLE",
                                   "Правата не могат да бъдат проверени; действието е отказано.",
                                   cause=type(exc).__name__)
    return decide


async def _run(command: str, request: Request, wc, request_id: Optional[str], payload: Any):
    ctx, tdb = wc
    if not isinstance(payload, dict):
        raise _fail(422, "INVALID_BODY", "Body must be a JSON object")
    key, corr, channel = _headers(request)
    cmd = mrc.Command(ctx=ctx, db=tdb, command=command, request_id=request_id, payload=payload,
                      idempotency_key=key, correlation_id=corr, channel=channel,
                      endpoint="%s %s" % (request.method, request.url.path))
    try:
        out = await mrc.execute(cmd, decide=_decider(ctx, command))
    except mrc.CommandError as err:
        raise HTTPException(status_code=err.status, detail=err.detail())
    doc = out.get("request")
    projected = None
    if doc:
        facts = await mrc.line_facts(tdb, ctx.org_id, [l.get("id") for l in doc.get("lines") or []])
        projected = mrc.project_request(doc, facts)
    return {"replayed": out["replayed"], "result": out["result"], "request": projected}


# ═══════════════════════════════════════════════════════════════ commands
@router.post("/material-requests", status_code=201)
async def create_material_request(request: Request, payload: Any = Body(...),
                                  wc=Depends(write_context)):
    return await _run(mrc.CMD_CREATE, request, wc, None, payload)


@router.patch("/material-requests/{req_id}/draft")
async def edit_material_request_draft(req_id: str, request: Request, payload: Any = Body(...),
                                      wc=Depends(write_context)):
    return await _run(mrc.CMD_EDIT_DRAFT, request, wc, req_id, payload)


@router.post("/material-requests/{req_id}/submit")
async def submit_material_request(req_id: str, request: Request,
                                  payload: Any = Body(default={}), wc=Depends(write_context)):
    return await _run(mrc.CMD_SUBMIT, request, wc, req_id, payload)


@router.post("/material-requests/{req_id}/approve")
async def approve_material_request(req_id: str, request: Request,
                                   payload: Any = Body(default={}), wc=Depends(write_context)):
    return await _run(mrc.CMD_APPROVE, request, wc, req_id, payload)


@router.post("/material-requests/{req_id}/reject")
async def reject_material_request(req_id: str, request: Request, payload: Any = Body(...),
                                  wc=Depends(write_context)):
    return await _run(mrc.CMD_REJECT, request, wc, req_id, payload)


@router.post("/material-requests/{req_id}/cancel")
async def cancel_material_request(req_id: str, request: Request, payload: Any = Body(...),
                                  wc=Depends(write_context)):
    return await _run(mrc.CMD_CANCEL, request, wc, req_id, payload)


# ═══════════════════════════════════════════════════════════ retired writers
def _retired(replacement: str):
    raise _fail(410, "LEGACY_WRITER_RETIRED",
                "Този стар път за запис е изключен. Използвайте именуваните действия.",
                replacement=replacement)


@router.put("/material-requests/{req_id}")
async def retired_raw_update(req_id: str, user: dict = Depends(require_m2)):
    _retired("PATCH /api/material-requests/{id}/draft")


@router.delete("/material-requests/{req_id}")
async def retired_delete(req_id: str, user: dict = Depends(require_m2)):
    _retired("POST /api/material-requests/{id}/cancel")


@router.post("/material-requests/from-offer/{offer_id}")
async def retired_from_offer(offer_id: str, user: dict = Depends(require_m2)):
    _retired("POST /api/material-requests")


# ═══════════════════════════════════════════════════════════════ reads
async def _project_many(tenant: TenantData, docs):
    line_ids = [l.get("id") for d in docs for l in (d.get("lines") or []) if l.get("id")]
    facts = await mrc.line_facts(_TenantLedger(tenant), tenant.org_id, line_ids)
    return [mrc.project_request(d, facts) for d in docs]


class _TenantLedger:
    """Adapter so ``line_facts`` reads the ledger through the tenant view."""

    def __init__(self, tenant: TenantData):
        self._t = tenant

    def __getitem__(self, name):
        return self._t.collection(name)


@router.get("/material-requests")
async def list_material_requests(project_id: Optional[str] = None, status: Optional[str] = None,
                                 user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    query: Dict[str, Any] = {}
    if project_id:
        query["project_id"] = project_id
    if status:
        query["status"] = status
    docs = await tenant.material_requests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    projects = await tenant.projects.get_many({d.get("project_id") for d in docs},
                                              {"_id": 0, "id": 1, "code": 1, "name": 1})
    out = await _project_many(tenant, docs)
    for r in out:
        p = projects.get(r.get("project_id")) or {}
        r["project_code"] = p.get("code", "")
        r["project_name"] = p.get("name", "")
    return out


@router.get("/material-requests/write-status")
async def material_request_write_status(user: dict = Depends(require_m2)):
    """Whether request writes are enabled at all — the UI shows this honestly."""
    mode = _raw_mode()
    return {"writes_enabled": mode == "enforce", "permission_mode": mode or "unset",
            "message": None if mode == "enforce" else
            "Записът на заявки е изключен, докато Permission Service не е в режим enforce."}


@router.get("/material-requests/item-options")
async def material_request_item_options(request: Request, q: str = "",
                                        user: dict = Depends(require_m2)):
    """Active Master items of the SESSION tenant for the line picker (read-only).

    Free text is never turned into an item here: no match simply leaves the
    line as an explicit pending-mapping line.
    """
    if _raw_mode() != "enforce":
        return {"status": "unavailable", "items": [],
                "message": "Изборът на Master материал е наличен само в режим enforce."}
    from app.tenancy.guard import get_tenant_context
    ctx = await get_tenant_context(request, user)
    tdb = await ctx.db()
    flt: Dict[str, Any] = {"tenant_id": ctx.tenant_id, "status": "active"}
    q = (q or "").strip()[:100]
    if q:
        flt["display_name"] = {"$regex": re.escape(q), "$options": "i"}
    rows = await tdb[mrc.ITEM_COLLECTION].find(
        flt, {"_id": 0, "id": 1, "display_name": 1, "base_unit": 1, "category": 1}
    ).sort("display_name", 1).to_list(30)
    return {"status": "ok", "items": rows}


@router.get("/material-requests/{req_id}")
async def get_material_request(req_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    doc = await tenant.material_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    return (await _project_many(tenant, [doc]))[0]


@router.get("/material-requests/{req_id}/view")
async def view_material_request(req_id: str, request: Request, user: dict = Depends(require_m2)):
    """Detail + allowed actions + canonical history for the review screen."""
    tenant = _tenant(user)
    doc = await tenant.material_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    projected = (await _project_many(tenant, [doc]))[0]
    project = await tenant.projects.get(doc.get("project_id"), {"_id": 0, "id": 1, "code": 1,
                                                                "name": 1})
    projected["project_code"] = (project or {}).get("code", "")
    projected["project_name"] = (project or {}).get("name", "")

    mode = _raw_mode()
    actions: Dict[str, Any] = {}
    history: Dict[str, Any] = {"status": "unavailable",
                               "message": "Историята е налична само в режим enforce."}
    if mode != "enforce":
        reason = "PERMISSION_SERVICE_NOT_ENFORCED"
        for c in mrc.COMMANDS[1:]:
            actions[c] = {"allowed": False, "reason": reason}
    else:
        from app.tenancy.guard import get_tenant_context
        try:
            ctx = await get_tenant_context(request, user)
            ctx.mode = "enforce"
            for c in mrc.COMMANDS[1:]:
                from_states, _ = mrc.TRANSITIONS[c]
                if doc.get("status") not in from_states:
                    actions[c] = {"allowed": False, "reason": "INVALID_STATE"}
                    continue
                ok, reason, _, basis, _ = await _decider(ctx, c)(doc.get("project_id"), doc)
                actions[c] = {"allowed": ok, "reason": reason, "action": basis}
            tdb = await ctx.db()
            if ctx.owns(doc):
                events = await tdb["audit_events"].find(
                    {"tenant_id": ctx.tenant_id, "entity_type": mrc.ENTITY_TYPE, "entity_id": req_id},
                    {"_id": 0, "event_id": 1, "sequence": 1, "action": 1, "result": 1,
                     "actor_id": 1, "occurred_at": 1, "reason": 1, "error_code": 1,
                     "structured_diff": 1, "correlation_id": 1, "source_channel": 1,
                     "entity_version": 1}).sort("sequence", 1).to_list(500)
                history = {"status": "ok", "source": "audit_events", "events": events}
        except Exception as exc:                                # noqa: BLE001
            for c in mrc.COMMANDS[1:]:
                actions.setdefault(c, {"allowed": False, "reason": "PERMISSION_EVALUATION_UNAVAILABLE"})
            history = {"status": "unavailable", "message": "Историята не може да бъде заредена.",
                       "cause": type(exc).__name__}
    return {"request": projected, "allowed_actions": actions, "history": history,
            "write_mode": mode or "unset"}
