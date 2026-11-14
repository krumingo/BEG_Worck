"""
Routes - Asset Repairs (ремонти на активи) — ASSET-REP-01 (FLOW Guard FG-723).

Canon: FLOW-011 (BUSINESS LOCK: movements, two-phase handover, repairs), FLOW-012 §9
(acceptance), FLOW-039 §9–§11 (warranty), FLOW-006 (one Payment ledger), FLOW-040 / W0-04
(AuditEvent, idempotency), R16 / R20 (Krum). Oracle: docs/flow-guard/oracle/Q012 (branch
claude/flow-guard).

FG-723 (main): a Viewer sent an in-warranty asset to repair, returned it with cost 500 and
is_warranty=false and got 200; ``/repairs`` then showed ``total_paid`` 500 while
``finance_payments`` had 0 rows. No role check, no AuditEvent, no evidence.

Rules of this module
--------------------
* Rights through the Permission Service (catalog actions, the FIRST dependency of every
  write; off/shadow: legacy role check, enforce: Tenant Guard -> Permission Service):
    - ``asset_repair.send.create`` / ``asset_repair.return.create`` /
      ``asset_repair.handover.execute`` — the field/custody roles; Viewer and Driver never
      (R16 by analogy); Accountant is a finance role, not a custody role;
    - ``asset_repair.cost.update`` — entering or changing the repair COST: Owner / Admin /
      Accountant only (R20). INTERIM default until Krum decides on field roles.
* Two-phase custody (FLOW-011 §Двуфазно): the holder (active ``asset_custody``) or a
  responsible role INITIATES a handover (``PENDING_ACCEPTANCE``); only the named receiver
  ACCEPTS, REFUSES or reports a PROBLEM. The unit status, its location and its custody
  change ONLY on ``ACCEPTED``. While pending, the sender stays holder and responsible.
* The cost is an OBLIGATION (basis), never a payment (FLOW-006). Nothing here stores or
  shows "paid" of its own: ``/repairs`` reads paid from ``finance_payments`` through the
  linked invoice's active allocations (0 when no link). ``total_cost`` is the sum of the
  costs ("обща цена на ремонтите", FLOW-011 §Фирмено), labelled as cost.
* A cost is versioned (``cost_versions``, append only); a change is a new version with a
  reason — never an overwrite without history.
* Warranty: a unit inside its warranty period returned with ``is_warranty=false`` → a DQ
  signal, a non-empty reason is required, and an AuditEvent is written. No Approval
  (INTERIM default until Krum decides).
* Every transition (create, accept, refuse, problem, return, cost, warranty override) writes
  one canonical W0-04 AuditEvent naming sender, receiver, asset, locations, condition and the
  evidence ``file_id``s. No minimum number of photos (INTERIM).
* Every write needs an ``Idempotency-Key`` (428 without), runs at most once per
  (tenant, action, key), and is tenant-scoped (another tenant's record == missing → 404).
  No hard delete anywhere.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone, date
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.permissions.deps import require_permission
from app.permissions.money_write import (
    FINANCE_WRITE_ROLES, _legacy_data_path_guard, check_money_write, strip_money_for_non_finance,
)
from app.tenancy.data_access import TenantData
from app.tenancy.guard import TenantContext


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)


router = APIRouter(tags=["AssetRepairs"])

# ── catalog actions (app/permissions/catalog.py: ASSET_REPAIR_*_ACTIONS) ─────────────────
SEND_ACTION = "asset_repair.send.create"
RETURN_ACTION = "asset_repair.return.create"
HANDOVER_ACTION = "asset_repair.handover.execute"
COST_ACTION = "asset_repair.cost.update"
MODULE = "M8"
RESOURCE = "asset_repair"

# Legacy role strings that may write custody (off/shadow). Viewer and Driver never;
# Accountant is a finance role (it holds the cost only).
CUSTODY_WRITE_ROLES = ("Owner", "Admin", "SiteManager", "Warehousekeeper", "Technician")
# Roles RESPONSIBLE for an asset they do not hold (they may initiate its handover).
RESPONSIBLE_ROLE_IDS = frozenset({"owner", "admin", "site_manager", "project_manager",
                                  "warehouse"})

# ── handover / repair states (FLOW-011 §Двуфазно) ─────────────────────────────────────────
PENDING = "PENDING_ACCEPTANCE"
ACCEPTED = "ACCEPTED"
REFUSED = "REFUSED"          # „Отказано“
PROBLEM = "PROBLEM"          # „Проблем при приемане“

ST_SEND_PENDING = "send_pending"
ST_IN_REPAIR = "in_repair"
ST_RETURN_PENDING = "return_pending"
ST_DONE = "done"
ST_SEND_REFUSED = "send_refused"
ST_SEND_PROBLEM = "send_problem"
OPEN_STATUSES = (ST_SEND_PENDING, ST_IN_REPAIR, ST_RETURN_PENDING)
COSTABLE_STATUSES = (ST_IN_REPAIR, ST_RETURN_PENDING, ST_DONE)

DQ_WARRANTY_OVERRIDE = "ASSET_IN_WARRANTY_MARKED_NON_WARRANTY"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message,
                                                     **extra})


def _user_name(user: dict) -> str:
    return (user.get("name")
            or f"{user.get('first_name','')} {user.get('last_name','')}".strip()
            or (user.get("email", "").split("@")[0] if user.get("email") else ""))


def _clean(value: Any) -> Optional[str]:
    return (value.strip() or None) if isinstance(value, str) else None


async def _person_by_id(tenant: TenantData, user_id: Optional[str]) -> dict:
    """{name, avatar_url} of users.id in THIS tenant; empty when no id or no such user."""
    if not user_id:
        return {}
    u = await tenant.users.find_one(
        {"id": user_id},
        {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1, "email": 1,
         "avatar_url": 1, "role": 1, "is_active": 1},
    )
    if not u:
        return {}
    return {"id": u["id"], "name": _user_name(u) or None, "avatar_url": u.get("avatar_url"),
            "role": u.get("role"), "is_active": u.get("is_active", True)}


def _warranty_end(purchase_date: Optional[str], warranty_months: Optional[int]) -> Optional[date]:
    if not purchase_date or not warranty_months:
        return None
    try:
        y, m, d = str(purchase_date)[:10].split("-")
        start = date(int(y), int(m), int(d))
        total = start.month - 1 + int(warranty_months)
        return date(start.year + total // 12, total % 12 + 1, min(start.day, 28))
    except Exception:
        return None


def _in_warranty(purchase_date: Optional[str], warranty_months: Optional[int]) -> bool:
    """Warranty from the unit's purchase date + months (unchanged rule)."""
    end = _warranty_end(purchase_date, warranty_months)
    return bool(end and end > date.today())


# ── permission dependencies ───────────────────────────────────────────────────────────────
def _require(action: str, roles=CUSTODY_WRITE_ROLES):
    """The W0-02 dependency of one repair write (first dependency of the route)."""
    permission = require_permission(
        action, module=MODULE, scope="company", resource_type=RESOURCE,
        legacy_check=lambda user, request: user.get("role") in roles,
    )

    async def dependency(request: Request, ctx: TenantContext = Depends(permission)) -> TenantContext:
        await _legacy_data_path_guard(ctx)
        return ctx

    dependency.asset_rep_action = action          # inspected by tests/test_asset_rep_01_*.py
    return dependency


async def _check_cost_right(request: Request, user: dict) -> None:
    """R20 from inside a handler: a body that carries a cost (or an invoice link) needs
    ``asset_repair.cost.update`` — refused (403) BEFORE anything is written."""
    await check_money_write(request, user, COST_ACTION, module=MODULE, resource_type=RESOURCE)


async def _role_ids(ctx: TenantContext) -> set:
    """The caller's company roles: enforce → active RoleAssignments (never user["role"]);
    off/shadow → the legacy role string mapped to its role_id."""
    from app.permissions.catalog import LEGACY_ROLE_MAP
    if ctx.enforced:
        from app.tenancy import registry
        rows = await registry.list_role_assignments(ctx.user_id, ctx.tenant_id)
        return {r.get("role_id") for r in rows
                if r.get("status") == "active" and r.get("scope_type") in (None, "company")}
    role = LEGACY_ROLE_MAP.get(ctx.user.get("role") or "")
    return {role} if role else set()


def _require_key(header: Optional[str]) -> str:
    from app.routes.finance import _require_key as require_key
    return require_key(header)


async def _once(user: dict, key: str, action: str, fingerprint: dict, work):
    """The PAY-01 W0-04 idempotency wrapper, reused (one result per tenant/action/key)."""
    from app.routes.finance import _once as once
    return await once(user, key, action, fingerprint, work)


async def _atomic(body):
    """One transaction when the deployment supports it; otherwise the body runs with
    ``session=None``. Every body starts with a compare-and-set on the repair document, so
    of two concurrent transitions only one wins (the loser gets 409, nothing else written)."""
    from app.services.auth_tx import run_in_transaction, transactions_supported
    if await transactions_supported(db):
        from app.audit.store import ensure_chain_index
        await ensure_chain_index(db)
        return await run_in_transaction(db, body)
    return await body(None)


def _kw(session) -> dict:
    return {} if session is None else {"session": session}


async def _audit(ctx: TenantContext, request: Request, *, action: str, repair: dict,
                 diff: Dict[str, Any], key: str, version: Optional[str] = None,
                 reason: Optional[str] = None, file_ids: Optional[List[str]] = None,
                 retention: Optional[str] = None, source_flow: str = "FLOW-011",
                 session=None) -> dict:
    """Canonical W0-04 AuditEvent of one repair transition, in the business transaction.
    A failure is raised, never swallowed."""
    from app.audit.envelope import (ACTOR_HUMAN, RESULT_SUCCESS, RETENTION_R1_CRITICAL_BUSINESS,
                                    RETENTION_R2_PROJECT_OPERATIONAL, build_event)
    from app.audit.store import record_event
    user = ctx.user
    event = build_event(
        tenant_id=ctx.tenant_id if ctx.enforced else user["org_id"],
        actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow=source_flow,
        retention_class=retention or RETENTION_R2_PROJECT_OPERATIONAL,
        result=RESULT_SUCCESS, entity_type="asset_repair", entity_id=repair["id"],
        entity_version=version, scope_type="asset_unit", scope_id=repair.get("unit_id"),
        structured_diff=diff, reason=reason, source_channel="api",
        tool_or_endpoint="%s %s" % (request.method, request.url.path),
        request_id=request.headers.get("x-request-id"), idempotency_key=key,
        related_file_ids=list(file_ids or []) or None,
    )
    if retention is None and action.startswith("asset_repair.cost"):
        event["retention_class"] = RETENTION_R1_CRITICAL_BUSINESS
    return await record_event(db, event, session=session)


async def _evidence(tenant: TenantData, file_ids: Optional[List[str]]) -> List[str]:
    """Evidence ``file_id``s must be files of THIS tenant (CLAUDE.md §2.6). The store is
    ``media_files``: the canonical File Registry (W0-06) is not built yet (as OFF-01,
    debt D-OFF01-12). No minimum count (INTERIM, Krum)."""
    ids = []
    for fid in file_ids or []:
        if not isinstance(fid, str) or not fid.strip():
            raise _err(422, "EVIDENCE_FILE_INVALID", "Невалиден файл-доказателство")
        fid = fid.strip()
        if fid in ids:
            continue
        if not await tenant.media_files.get(fid, {"_id": 0, "id": 1}):
            raise _err(422, "EVIDENCE_FILE_NOT_FOUND",
                       "Файлът-доказателство не е намерен в тази фирма")
        ids.append(fid)
    return ids


async def _unit_or_404(tenant: TenantData, unit_id: str) -> dict:
    unit = await tenant.asset_units.find_one({"id": unit_id}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


async def _repair_or_404(tenant: TenantData, repair_id: str) -> dict:
    rec = await tenant.asset_repairs.find_one({"id": repair_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Repair not found")
    return rec


async def _holder(tenant: TenantData, unit_id: str) -> Optional[str]:
    """The current holder: the custodian of the ACCEPTED custody record of the unit."""
    c = await tenant.asset_custody.find_one({"unit_id": unit_id, "status": "accepted"},
                                            {"_id": 0, "custodian_user_id": 1})
    return (c or {}).get("custodian_user_id")


async def _may_initiate(ctx: TenantContext, holder: Optional[str]) -> None:
    """FLOW-011: the holder or the responsible person initiates. Anyone else → 403."""
    if holder and holder == ctx.user["id"]:
        return
    if await _role_ids(ctx) & RESPONSIBLE_ROLE_IDS:
        return
    raise _err(403, "NOT_HOLDER_OR_RESPONSIBLE",
               "Предаването се инициира от държателя или отговорника на актива")


async def _receiver(tenant: TenantData, receiver_id: Optional[str], sender_id: str) -> dict:
    if not isinstance(receiver_id, str) or not receiver_id.strip():
        raise _err(422, "RECEIVER_REQUIRED", "Посочете получателя, който ще приеме актива")
    person = await _person_by_id(tenant, receiver_id.strip())
    if not person or person.get("is_active") is False:
        raise _err(422, "RECEIVER_NOT_FOUND", "Получателят не е активен потребител на фирмата")
    if person["id"] == sender_id:
        # INTERIM (Krum: acceptance by an external service without an account): the
        # receiver is a different user of the tenant, so a handover is never self-accepted.
        raise _err(422, "RECEIVER_IS_SENDER", "Получателят трябва да е различен от предаващия")
    if person.get("role") in ("Viewer", "Driver"):
        raise _err(422, "RECEIVER_CANNOT_ACCEPT", "Този потребител няма право да приема активи")
    return person


def _handover(repair: dict, handover_id: str) -> dict:
    for h in repair.get("handovers") or []:
        if h.get("id") == handover_id:
            return h
    raise HTTPException(status_code=404, detail="Handover not found")


def _changed() -> HTTPException:
    return _err(409, "REPAIR_STATE_CHANGED",
                "Ремонтът беше променен от друга заявка — презаредете и опитайте отново")


async def _custody_to(tenant: TenantData, unit_id: str, to_user: str, given_by: str,
                      session) -> None:
    """ACCEPTED: the custody moves to the receiver. The previous record is released (kept)."""
    now = _now()
    await tenant.asset_custody.update_many(
        {"unit_id": unit_id, "status": {"$in": ["given", "accepted"]}},
        {"$set": {"status": "released", "released_at": now}}, **_kw(session))
    await tenant.asset_custody.insert_one({
        "id": str(uuid.uuid4()), "unit_id": unit_id, "custodian_user_id": to_user,
        "status": "accepted", "given_by_user_id": given_by, "given_at": now,
        "accepted_at": now, "note": "asset_repair handover"}, **_kw(session))


async def _location_ok(tenant: TenantData, loc_type: Optional[str], loc_id: Optional[str]) -> None:
    if loc_type == "warehouse":
        if not loc_id or not await tenant.warehouses.find_one({"id": loc_id}, {"_id": 0, "id": 1}):
            raise _err(422, "RETURN_LOCATION_NOT_FOUND", "Складът не е намерен в тази фирма")
    elif loc_type == "project":
        if not loc_id or not await tenant.projects.find_one({"id": loc_id}, {"_id": 0, "id": 1}):
            raise _err(422, "RETURN_LOCATION_NOT_FOUND", "Обектът не е намерен в тази фирма")


def _cost_number(value: Any) -> float:
    from app.permissions.money_input import money_value
    return money_value(value, "cost", allow_zero=True)


async def _invoice_ok(tenant: TenantData, invoice_id: Optional[str]) -> Optional[str]:
    """The obligation link: a RECEIVED (supplier) invoice of THIS tenant."""
    if invoice_id is None:
        return None
    if not isinstance(invoice_id, str) or not invoice_id.strip():
        raise _err(422, "INVOICE_INVALID", "Невалидна фактура")
    inv = await tenant.invoices.get(invoice_id.strip(), {"_id": 0, "id": 1, "direction": 1})
    if not inv:
        raise _err(422, "INVOICE_NOT_FOUND", "Фактурата не е намерена в тази фирма")
    if inv.get("direction") != "Received":
        raise _err(422, "INVOICE_NOT_RECEIVED", "Ремонтът се свързва с входяща (доставчик) фактура")
    return inv["id"]


def _cost_version(repair: dict, *, cost: float, reason: Optional[str], invoice_id: Optional[str],
                  file_ids: List[str], user: dict) -> dict:
    versions = repair.get("cost_versions") or []
    return {"version": len(versions) + 1, "cost": cost, "reason": reason,
            "invoice_id": invoice_id, "file_ids": file_ids,
            "previous_cost": repair.get("cost"), "by": user["id"], "at": _now()}


# ═══════════════════════════════════════════════════════════════════════ request bodies
class RepairSend(BaseModel):
    receiver_user_id: Optional[str] = None   # who ACCEPTS the asset (service side)
    sent_by: Optional[str] = None            # users.id of the carrier (informational)
    sent_by_name: Optional[str] = None       # carrier snapshot (legacy rows)
    service: Optional[str] = None            # сервиз / при кого
    issue: Optional[str] = None              # причина / дефект
    condition: Optional[str] = None          # видимо състояние
    accessories: Optional[str] = None        # комплектовка
    due_date: Optional[str] = None           # срок
    file_ids: Optional[List[str]] = None     # доказателства (File Registry ids)


class RepairReturn(BaseModel):
    receiver_user_id: Optional[str] = None   # who ACCEPTS it back (склад / обект)
    returned_by: Optional[str] = None        # users.id of the carrier (informational)
    returned_by_name: Optional[str] = None
    return_location_type: Optional[str] = None   # warehouse | project (default: origin)
    return_location_id: Optional[str] = None
    work_done: Optional[str] = None
    result: Optional[str] = None
    condition: Optional[str] = None
    accessories: Optional[str] = None
    functional_test: Optional[str] = None
    is_warranty: Optional[bool] = None
    warranty_override_reason: Optional[str] = None
    cost: Optional[Any] = None               # R20: finance roles only
    invoice_id: Optional[str] = None         # R20: finance roles only
    file_ids: Optional[List[str]] = None


class HandoverDecision(BaseModel):
    condition: Optional[str] = None
    note: Optional[str] = None
    reason: Optional[str] = None             # required for refuse / problem
    file_ids: Optional[List[str]] = None


class RepairCost(BaseModel):
    cost: Any = None
    reason: Optional[str] = None             # required when a cost already exists
    invoice_id: Optional[str] = None
    file_ids: Optional[List[str]] = None


# ═══════════════════════════════════════════════════════════════════════ send (phase 1)
@router.post("/assets/units/{unit_id}/repair/send")
async def repair_send(unit_id: str, data: RepairSend, request: Request,
                      ctx: TenantContext = Depends(_require(SEND_ACTION)),
                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Initiate „обект/служител → ремонт“: a repair record with a PENDING_ACCEPTANCE
    handover. Unit status, location and custody are NOT changed until the receiver accepts."""
    user = ctx.user
    tenant = _tenant(user)
    key = _require_key(idempotency_key)

    async def work():
        unit = await _unit_or_404(tenant, unit_id)
        holder = await _holder(tenant, unit_id)
        await _may_initiate(ctx, holder)
        issue = _clean(data.issue)
        if not issue:
            raise _err(422, "ISSUE_REQUIRED", "Опишете причината / повредата")
        receiver = await _receiver(tenant, data.receiver_user_id, user["id"])
        files = await _evidence(tenant, data.file_ids)
        carrier = await _person_by_id(tenant, data.sent_by)
        now = _now()
        handover = {
            "id": "ho_" + uuid.uuid4().hex, "kind": "send", "status": PENDING,
            "from_user_id": user["id"], "from_holder_user_id": holder,
            "to_user_id": receiver["id"], "to_user_name": receiver.get("name"),
            "from_location_type": unit.get("location_type"),
            "from_location_id": unit.get("location_id"),
            "to_location_type": "service", "to_location_name": _clean(data.service),
            "condition": _clean(data.condition), "accessories": _clean(data.accessories),
            "serial_no": unit.get("serial_no"), "qr_id": unit.get("qr_id"),
            "due_date": _clean(data.due_date), "file_ids": files,
            "created_at": now, "created_by": user["id"],
        }
        rec = {
            "id": str(uuid.uuid4()), "unit_id": unit_id, "status": ST_SEND_PENDING,
            "sent_at": None, "sent_by": _clean(data.sent_by),
            "sent_by_name": carrier.get("name") or _clean(data.sent_by_name),
            "service": _clean(data.service), "issue": issue,
            "returned_at": None, "returned_by": None, "returned_by_name": None,
            "cost": None, "cost_versions": [], "invoice_id": None,
            "work_done": None, "is_warranty": None, "warranty_override": None,
            "dq_signals": [],
            "in_warranty_at_send": _in_warranty(unit.get("purchase_date"),
                                                unit.get("warranty_months")),
            "from_location_type": unit.get("location_type"),
            "from_location_id": unit.get("location_id"),
            "handovers": [handover], "created_at": now, "created_by": user["id"],
        }

        async def body(session):
            # one open repair per unit — the check is repeated inside the transaction
            if await tenant.asset_repairs.find_one(
                    {"unit_id": unit_id, "status": {"$in": list(OPEN_STATUSES)}},
                    {"_id": 0, "id": 1}, **_kw(session)):
                raise _err(409, "REPAIR_ALREADY_OPEN", "Този актив вече е на ремонт")
            await tenant.asset_repairs.insert_one(dict(rec), **_kw(session))
            await _audit(ctx, request, action="asset_repair.send.created", repair=rec,
                         version=handover["id"], key=key, file_ids=files, session=session,
                         diff=_handover_diff(handover, unit, status_after=ST_SEND_PENDING,
                                             issue=issue))
            return rec
        out = await _atomic(body)
        out.pop("_id", None)
        return out

    return await _once(user, key, SEND_ACTION, {"unit_id": unit_id, **data.model_dump()}, work)


def _handover_diff(h: dict, unit: dict, **extra) -> dict:
    return {"handover_id": h["id"], "kind": h["kind"], "handover_status": h["status"],
            "sender_user_id": h.get("from_user_id"), "receiver_user_id": h.get("to_user_id"),
            "asset": {"unit_id": unit.get("id"), "qr_id": unit.get("qr_id"),
                      "serial_no": unit.get("serial_no"), "item_id": unit.get("item_id")},
            "from_location": {"type": h.get("from_location_type"),
                              "id": h.get("from_location_id")},
            "to_location": {"type": h.get("to_location_type"), "id": h.get("to_location_id"),
                            "name": h.get("to_location_name")},
            "condition": h.get("condition"), "accessories": h.get("accessories"),
            "evidence_file_ids": list(h.get("file_ids") or []), **extra}


# ═══════════════════════════════════════════════════════════════════════ return (phase 1)
@router.post("/assets/units/{unit_id}/repair/return")
async def repair_return(unit_id: str, data: RepairReturn, request: Request,
                        ctx: TenantContext = Depends(_require(RETURN_ACTION)),
                        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Initiate „ремонт → склад/обект“: a PENDING_ACCEPTANCE return handover. The unit
    becomes available at the return location only when the receiver accepts.

    A body with ``cost`` / ``invoice_id`` needs the cost right (R20) — checked before
    anything is written. In warranty with ``is_warranty=false`` → a DQ signal and a
    required reason (``warranty_override_reason``)."""
    user = ctx.user
    tenant = _tenant(user)
    key = _require_key(idempotency_key)
    with_cost = data.cost is not None or data.invoice_id is not None
    if with_cost:
        await _check_cost_right(request, user)       # 403 before any read of the record

    async def work():
        unit = await _unit_or_404(tenant, unit_id)
        rec = await tenant.asset_repairs.find_one({"unit_id": unit_id, "status": ST_IN_REPAIR},
                                                  {"_id": 0})
        if not rec:
            raise _err(409, "REPAIR_NOT_IN_REPAIR", "Този актив не е приет в ремонт")
        await _may_initiate(ctx, await _holder(tenant, unit_id))
        receiver = await _receiver(tenant, data.receiver_user_id, user["id"])
        loc_type = data.return_location_type or (
            "warehouse" if data.return_location_id else rec.get("from_location_type"))
        loc_id = data.return_location_id or rec.get("from_location_id")
        if loc_type not in (None, "warehouse", "project", "employee", "guest"):
            raise _err(422, "RETURN_LOCATION_INVALID", "Невалидно място за връщане")
        await _location_ok(tenant, loc_type, loc_id)
        files = await _evidence(tenant, data.file_ids)
        cost = _cost_number(data.cost) if data.cost is not None else None
        invoice_id = await _invoice_ok(tenant, data.invoice_id)

        # ── warranty (FLOW-039 §9–§10): marker + DQ signal, never silent ──
        in_warranty = _in_warranty(unit.get("purchase_date"), unit.get("warranty_months"))
        warranty = data.is_warranty if data.is_warranty is not None else in_warranty
        override = None
        dq = []
        if in_warranty and data.is_warranty is False:
            signal = {"code": DQ_WARRANTY_OVERRIDE, "severity": "warning",
                      "message": "Активът е в гаранционен срок, а ремонтът е маркиран като "
                                 "негаранционен",
                      "warranty_until": str(_warranty_end(unit.get("purchase_date"),
                                                          unit.get("warranty_months")))}
            reason = _clean(data.warranty_override_reason)
            if not reason:
                raise _err(422, "WARRANTY_REASON_REQUIRED",
                           "Активът е в гаранция — посочете причина ремонтът да не е гаранционен",
                           dq_signals=[signal])
            override = {"reason": reason, "by": user["id"], "at": _now(),
                        "warranty_until": signal["warranty_until"], "approval": None}
            dq = [{**signal, "reason": reason, "at": override["at"]}]

        carrier = await _person_by_id(tenant, data.returned_by)
        now = _now()
        handover = {
            "id": "ho_" + uuid.uuid4().hex, "kind": "return", "status": PENDING,
            "from_user_id": user["id"], "to_user_id": receiver["id"],
            "to_user_name": receiver.get("name"),
            "from_location_type": "service", "from_location_id": None,
            "from_location_name": rec.get("service"),
            "to_location_type": loc_type, "to_location_id": loc_id,
            "condition": _clean(data.condition), "accessories": _clean(data.accessories),
            "functional_test": _clean(data.functional_test),
            "serial_no": unit.get("serial_no"), "qr_id": unit.get("qr_id"),
            "file_ids": files, "created_at": now, "created_by": user["id"],
        }
        update = {
            "status": ST_RETURN_PENDING,
            "returned_by": _clean(data.returned_by),
            "returned_by_name": carrier.get("name") or _clean(data.returned_by_name),
            "work_done": _clean(data.work_done), "result": _clean(data.result),
            "is_warranty": bool(warranty), "warranty_override": override,
        }
        version = None
        if cost is not None or invoice_id is not None:
            version = _cost_version(rec, cost=cost if cost is not None else rec.get("cost"),
                                    reason=None, invoice_id=invoice_id or rec.get("invoice_id"),
                                    file_ids=files, user=user)
            update["cost"] = version["cost"]
            update["invoice_id"] = version["invoice_id"]

        async def body(session):
            push = {"handovers": handover}
            if version:
                push["cost_versions"] = version
            if dq:
                push["dq_signals"] = {"$each": dq}
            done = await tenant.asset_repairs.update_one(
                {"id": rec["id"], "status": ST_IN_REPAIR},
                {"$set": update, "$push": push}, **_kw(session))
            if not done.modified_count:
                raise _changed()
            await _audit(ctx, request, action="asset_repair.return.created", repair=rec,
                         version=handover["id"], key=key, file_ids=files, session=session,
                         diff=_handover_diff(handover, unit, status_before=ST_IN_REPAIR,
                                             status_after=ST_RETURN_PENDING,
                                             work_done=update["work_done"],
                                             is_warranty=update["is_warranty"]))
            if version:
                await _audit(ctx, request, action="asset_repair.cost.recorded", repair=rec,
                             version=str(version["version"]), key=key, file_ids=files,
                             session=session, source_flow="FLOW-011",
                             diff={"cost": {"before": rec.get("cost"), "after": version["cost"]},
                                   "invoice_id": version["invoice_id"],
                                   "kind": "obligation", "payment": None})
            if override:
                await _audit(ctx, request, action="asset_repair.warranty_override.recorded",
                             repair=rec, version=handover["id"], key=key, session=session,
                             reason=override["reason"], source_flow="FLOW-039",
                             diff={"dq_signal": DQ_WARRANTY_OVERRIDE, "is_warranty": False,
                                   "in_warranty": True,
                                   "warranty_until": override["warranty_until"],
                                   "approval_id": None})
            return await tenant.asset_repairs.find_one({"id": rec["id"]}, {"_id": 0},
                                                       **_kw(session))
        out = await _atomic(body)
        out["dq_signals_raised"] = dq
        return out

    return await _once(user, key, RETURN_ACTION, {"unit_id": unit_id, **data.model_dump()}, work)


# ═══════════════════════════════════════════════════════════════ accept / refuse / problem
async def _decide(repair_id: str, handover_id: str, decision: str, data: HandoverDecision,
                  request: Request, ctx: TenantContext, idempotency_key: Optional[str]):
    user = ctx.user
    tenant = _tenant(user)
    key = _require_key(idempotency_key)

    async def work():
        rec = await _repair_or_404(tenant, repair_id)
        h = _handover(rec, handover_id)
        if h.get("to_user_id") != user["id"]:
            raise _err(403, "NOT_THE_RECEIVER", "Само посоченият получател приема или отказва")
        if h.get("status") != PENDING:
            raise _err(409, "HANDOVER_NOT_PENDING", "Предаването вече е решено")
        reason = _clean(data.reason)
        if decision in (REFUSED, PROBLEM) and not reason:
            raise _err(422, "REASON_REQUIRED", "Посочете причина")
        files = await _evidence(tenant, data.file_ids)
        unit = await _unit_or_404(tenant, rec["unit_id"])
        expect = ST_SEND_PENDING if h["kind"] == "send" else ST_RETURN_PENDING
        if rec.get("status") != expect:
            raise _changed()
        now = _now()
        if h["kind"] == "send":
            after = {ACCEPTED: ST_IN_REPAIR, REFUSED: ST_SEND_REFUSED,
                     PROBLEM: ST_SEND_PROBLEM}[decision]
        else:
            after = {ACCEPTED: ST_DONE, REFUSED: ST_IN_REPAIR, PROBLEM: ST_IN_REPAIR}[decision]
        hset = {"handovers.$.status": decision, "handovers.$.decided_at": now,
                "handovers.$.decided_by": user["id"],
                "handovers.$.decision_condition": _clean(data.condition),
                "handovers.$.decision_note": _clean(data.note),
                "handovers.$.decision_reason": reason,
                "handovers.$.decision_file_ids": files, "status": after}
        if decision == ACCEPTED and h["kind"] == "send":
            hset["sent_at"] = _today()
        if decision == ACCEPTED and h["kind"] == "return":
            hset["returned_at"] = _today()

        async def body(session):
            done = await tenant.asset_repairs.update_one(
                {"id": repair_id, "status": expect,
                 "handovers": {"$elemMatch": {"id": handover_id, "status": PENDING}}},
                {"$set": hset}, **_kw(session))
            if not done.modified_count:
                raise _changed()
            if decision == ACCEPTED:
                # custody, status and location change ONLY here (FLOW-011)
                if h["kind"] == "send":
                    await tenant.asset_units.update_one(
                        {"id": unit["id"]}, {"$set": {"status": "repair"}}, **_kw(session))
                else:
                    await tenant.asset_units.update_one(
                        {"id": unit["id"]},
                        {"$set": {"status": "available",
                                  "location_type": h.get("to_location_type"),
                                  "location_id": h.get("to_location_id")}}, **_kw(session))
                await _custody_to(tenant, unit["id"], user["id"], h.get("from_user_id"), session)
            verb = {ACCEPTED: "accepted", REFUSED: "refused", PROBLEM: "problem"}[decision]
            await _audit(ctx, request, action="asset_repair.handover.%s" % verb, repair=rec,
                         version=handover_id, key=key, reason=reason,
                         file_ids=list(h.get("file_ids") or []) + files, session=session,
                         diff=_handover_diff({**h, "status": decision}, unit,
                                             status_before=expect, status_after=after,
                                             decision_condition=_clean(data.condition),
                                             decision_file_ids=files,
                                             custody_changed=decision == ACCEPTED))
            return await tenant.asset_repairs.find_one({"id": repair_id}, {"_id": 0},
                                                       **_kw(session))
        return await _atomic(body)

    return await _once(user, key, "%s.%s" % (HANDOVER_ACTION, decision.lower()),
                       {"repair_id": repair_id, "handover_id": handover_id, **data.model_dump()},
                       work)


@router.post("/assets/repairs/{repair_id}/handovers/{handover_id}/accept")
async def accept_handover(repair_id: str, handover_id: str, request: Request,
                          data: Optional[HandoverDecision] = None,
                          ctx: TenantContext = Depends(_require(HANDOVER_ACTION)),
                          idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _decide(repair_id, handover_id, ACCEPTED, data or HandoverDecision(), request,
                         ctx, idempotency_key)


@router.post("/assets/repairs/{repair_id}/handovers/{handover_id}/refuse")
async def refuse_handover(repair_id: str, handover_id: str, data: HandoverDecision,
                          request: Request,
                          ctx: TenantContext = Depends(_require(HANDOVER_ACTION)),
                          idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _decide(repair_id, handover_id, REFUSED, data, request, ctx, idempotency_key)


@router.post("/assets/repairs/{repair_id}/handovers/{handover_id}/problem")
async def problem_handover(repair_id: str, handover_id: str, data: HandoverDecision,
                           request: Request,
                           ctx: TenantContext = Depends(_require(HANDOVER_ACTION)),
                           idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return await _decide(repair_id, handover_id, PROBLEM, data, request, ctx, idempotency_key)


# ═══════════════════════════════════════════════════════════════════════ cost (R20)
@router.put("/assets/repairs/{repair_id}/cost")
async def set_repair_cost(repair_id: str, data: RepairCost, request: Request,
                          ctx: TenantContext = Depends(_require(COST_ACTION, FINANCE_WRITE_ROLES)),
                          idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """Enter or correct the repair COST — an obligation, never a payment (FLOW-006).
    Owner/Admin/Accountant only (R20, INTERIM). A change of an existing cost is a NEW
    version with a reason; the old versions stay."""
    user = ctx.user
    tenant = _tenant(user)
    key = _require_key(idempotency_key)

    async def work():
        rec = await _repair_or_404(tenant, repair_id)
        if rec.get("status") not in COSTABLE_STATUSES:
            raise _err(409, "REPAIR_NOT_COSTABLE", "Ремонтът не е приет в сервиз")
        cost = _cost_number(data.cost)
        reason = _clean(data.reason)
        if rec.get("cost") is not None and not reason:
            raise _err(422, "CORRECTION_REASON_REQUIRED",
                       "Промяна на цената изисква причина (нова версия)")
        invoice_id = await _invoice_ok(tenant, data.invoice_id) if data.invoice_id is not None \
            else rec.get("invoice_id")
        files = await _evidence(tenant, data.file_ids)
        version = _cost_version(rec, cost=cost, reason=reason, invoice_id=invoice_id,
                                file_ids=files, user=user)
        n = len(rec.get("cost_versions") or [])

        async def body(session):
            done = await tenant.asset_repairs.update_one(
                {"id": repair_id, "cost_versions": {"$size": n}},
                {"$set": {"cost": cost, "invoice_id": invoice_id},
                 "$push": {"cost_versions": version}}, **_kw(session))
            if not done.modified_count:
                raise _changed()
            corrected = rec.get("cost") is not None
            await _audit(ctx, request,
                         action="asset_repair.cost.%s" % ("corrected" if corrected else "recorded"),
                         repair=rec, version=str(version["version"]), key=key, reason=reason,
                         file_ids=files, session=session,
                         diff={"cost": {"before": rec.get("cost"), "after": cost},
                               "invoice_id": {"before": rec.get("invoice_id"),
                                              "after": invoice_id},
                               "kind": "obligation", "payment": None})
            return await tenant.asset_repairs.find_one({"id": repair_id}, {"_id": 0},
                                                       **_kw(session))
        return await _atomic(body)

    return await _once(user, key, COST_ACTION, {"repair_id": repair_id, **data.model_dump()}, work)


# ═══════════════════════════════════════════════════════════════════════ reads
async def _ledger_paid(tenant: TenantData, invoice_ids: List[str]) -> Dict[str, float]:
    """Paid per invoice from the ONE Payment ledger (FLOW-006): the invoice's active
    allocations whose ``finance_payments`` row exists and counts (not a reversed pair)."""
    from app.services.payment_state import active_allocations, payment_counts
    out: Dict[str, float] = {}
    for inv in invoice_ids:
        total = 0.0
        allocs = await tenant.payment_allocations.find(
            active_allocations({"invoice_id": inv}), {"_id": 0}).to_list(500)
        for a in allocs:
            pay = await tenant.finance_payments.get(a.get("payment_id"),
                                                    {"_id": 0, "id": 1, "status": 1})
            if payment_counts(pay):
                total += float(a.get("amount_allocated") or 0)
        out[inv] = round(total, 2)
    return out


@router.get("/assets/units/{unit_id}/repairs")
@strip_money_for_non_finance
async def list_repairs(unit_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Repair history of the unit. ``cost`` is the obligation; ``paid`` / ``remaining`` come
    from ``finance_payments`` through the linked invoice (0 when no link). ``total_cost`` =
    the sum of the costs („обща цена на ремонтите“). Money keys are removed for callers
    without the finance read right (SEC-02, R20-5M)."""
    tenant = _tenant(user)
    items = await tenant.asset_repairs.find({"unit_id": unit_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(500)
    paid_by_invoice = await _ledger_paid(
        tenant, sorted({r["invoice_id"] for r in items if r.get("invoice_id")}))

    ids = {r.get("sent_by") for r in items if r.get("sent_by")} | \
          {r.get("returned_by") for r in items if r.get("returned_by")}
    people = {}
    if ids:
        async for u in tenant.users.find(
            {"id": {"$in": list(ids)}},
            {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1, "email": 1, "avatar_url": 1},
        ):
            people[u["id"]] = {"name": _user_name(u) or None, "avatar_url": u.get("avatar_url")}

    total_cost = 0.0
    total_ledger_paid = 0.0
    for r in items:
        sp = people.get(r.get("sent_by"), {})
        rp = people.get(r.get("returned_by"), {})
        r["sent_by_name"] = sp.get("name") or r.get("sent_by_name")
        r["sent_by_avatar"] = sp.get("avatar_url")
        r["returned_by_name"] = rp.get("name") or r.get("returned_by_name")
        r["returned_by_avatar"] = rp.get("avatar_url")
        cost = r.get("cost")
        paid = paid_by_invoice.get(r.get("invoice_id"), 0.0) if r.get("invoice_id") else 0.0
        r["paid"] = paid
        r["paid_source"] = "finance_payments"
        r["remaining"] = round(float(cost) - paid, 2) if cost is not None else None
        total_cost += float(cost or 0)
        total_ledger_paid += paid
        r.pop("total_paid", None)

    open_repair = next((r for r in items if r.get("status") in OPEN_STATUSES), None)
    return {"items": items,
            "total_cost": round(total_cost, 2),            # sum of costs (obligations)
            "paid": round(total_ledger_paid, 2),           # from finance_payments only
            "remaining": round(total_cost - total_ledger_paid, 2),
            "open": open_repair}


@router.get("/assets/repairs/my-pending")
async def my_pending_handovers(user: dict = Depends(get_current_user)):
    """Handovers waiting for the caller's acceptance (Action Inbox feed)."""
    tenant = _tenant(user)
    rows = await tenant.asset_repairs.find(
        {"status": {"$in": [ST_SEND_PENDING, ST_RETURN_PENDING]},
         "handovers": {"$elemMatch": {"to_user_id": user["id"], "status": PENDING}}},
        {"_id": 0, "id": 1, "unit_id": 1, "status": 1, "service": 1, "issue": 1,
         "handovers": 1}).to_list(200)
    out = []
    for r in rows:
        for h in r.get("handovers") or []:
            if h.get("to_user_id") == user["id"] and h.get("status") == PENDING:
                out.append({"repair_id": r["id"], "unit_id": r["unit_id"], "kind": h["kind"],
                            "handover_id": h["id"], "from_user_id": h.get("from_user_id"),
                            "service": r.get("service"), "issue": r.get("issue"),
                            "created_at": h.get("created_at")})
    return {"items": out}
