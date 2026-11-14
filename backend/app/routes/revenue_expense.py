"""
Routes - Revenue & Expense Core.
Phase 1: Client Acts (earned revenue)
Phase 2: Labor Cost Aggregation
Phase 3: Execution Packages
Phase 4: Project Profit Summary
"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from typing import Any, Dict, Optional, List
import math
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.utils.audit import log_audit
from app.tenancy.data_access import TenantData
from app.permissions.money_write import (
    money_values_visible, require_finance_read, require_money_write,
)
from app.services import client_acts as ca


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Revenue & Expense"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — CLIENT ACTS (EARNED REVENUE)
# ═══════════════════════════════════════════════════════════════════

# ACT-01 (FLOW-004, FG-106): every write goes through app/services/client_acts.py —
# price and contracted quantity from an offer line of an accepted offer of the same
# project, the remainder reserved in the act's transaction, the number from a counter,
# one canonical AuditEvent, an Idempotency-Key (R29) and the finance roles only (R14/R20).

_HEADER_FIELDS = ("act_date", "period_from", "period_to", "notes")


def _body_dict(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail={
            "error_code": "BODY_INVALID", "message": "Тялото на заявката трябва да е JSON обект"})
    return data


@router.post("/client-acts", status_code=201)
async def create_client_act(
    data: Dict[str, Any] = Body(...),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _sec01: dict = Depends(require_money_write(
        ca.ACTION_CREATE, module="M2", resource_type="client_act")),  # ACT-01 (R14): before any read
    user: dict = Depends(require_m2),
):
    """Create a draft client act; every line is an offer line of an accepted offer."""
    data = _body_dict(data)
    key = ca.KeyedWrite(db, user, ca.ACTION_CREATE, idempotency_key)        # 428 without
    if data.get("act_number") not in (None, ""):
        raise HTTPException(status_code=422, detail={
            "error_code": "ACT_NUMBER_SERVER_ASSIGNED",
            "message": "Номерът на акта се дава от системата"})
    project_id = data.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(status_code=422, detail={
            "error_code": "PROJECT_REQUIRED", "message": "Обектът (project_id) е задължителен"})
    raw_lines = ca.validate_raw_lines(data.get("lines"))
    source_offer_id = data.get("source_offer_id") or None
    tenant = _tenant(user)
    if not await tenant.projects.find_one({"id": project_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Project not found")
    header = {k: data.get(k) for k in _HEADER_FIELDS}
    return await key.run(
        {"route": "POST /client-acts", "body": data},
        lambda: ca.create_act(db, user=user, project_id=project_id, raw_lines=raw_lines,
                              header=header, key=key, endpoint="POST /api/client-acts",
                              source_offer_id=source_offer_id))


@router.get("/client-acts")
async def list_client_acts(
    request: Request,
    _sec02: dict = Depends(require_finance_read(
        "finance.client_act.read", module="M2", resource_type="client_act")),  # SEC-02 (R20-1): before any read
    project_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    acts = await tenant.client_acts.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    if not await money_values_visible(request, user):                 # FG-122 (R20-5)
        return [ca.strip_money(a) for a in acts]
    return acts


@router.get("/client-acts/remaining/{project_id}")
async def client_act_remaining(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        ca.ACTION_REMAINING_READ, module="M2", resource_type="client_act_remaining")),  # R20-1: client prices
    user: dict = Depends(require_m2),
):
    """FLOW-004 "Какво трябва да вижда Крум": contracted / acted / remaining per offer line."""
    tenant = _tenant(user)
    if not await tenant.projects.find_one({"id": project_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Project not found")
    return await ca.remaining_for_project(tenant, project_id)


@router.get("/client-acts/{act_id}")
async def get_client_act(
    act_id: str,
    request: Request,
    _sec02: dict = Depends(require_finance_read(
        "finance.client_act_detail.read", module="M2", resource_type="client_act_detail")),  # SEC-02 (R20-1): before any read
    user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    act = await tenant.client_acts.find_one({"id": act_id, "org_id": user["org_id"]}, {"_id": 0})
    if not act:
        raise HTTPException(status_code=404, detail="Act not found")
    view = await ca.act_view(tenant, act)
    if not await money_values_visible(request, user):                 # FG-122 (R20-5)
        return ca.strip_money(view)
    return view


@router.put("/client-acts/{act_id}")
async def update_client_act(
    act_id: str,
    data: Dict[str, Any] = Body(...),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _sec02: dict = Depends(require_finance_read(
        "finance.client_act.update", module="M2", resource_type="client_act")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2),
):
    """Edit a Draft (ACT-01). Lines are re-checked against the offer and the reservation
    moves by the difference; an accepted act is never edited (correction/reversal is debt)."""
    data = _body_dict(data)
    key = ca.KeyedWrite(db, user, ca.ACTION_UPDATE, idempotency_key)        # 428 without
    tenant = _tenant(user)
    act = await tenant.client_acts.find_one({"id": act_id}, {"_id": 0, "id": 1, "status": 1})
    if not act:
        raise HTTPException(status_code=404, detail="Act not found")
    allowed = list(_HEADER_FIELDS) + ["lines"]
    update = {k: v for k, v in data.items() if k in allowed}
    if "lines" in update:
        ca.validate_raw_lines(update["lines"])                          # 422 before the key
    return await key.run(
        {"route": "PUT /client-acts/{act_id}", "act_id": act_id, "body": update},
        lambda: ca.update_act(db, user=user, act_id=act_id, update=update, key=key,
                              endpoint="PUT /api/client-acts/{act_id}"))


@router.post("/client-acts/{act_id}/confirm")
async def confirm_client_act(
    act_id: str,
    data: Dict[str, Any] = Body(default_factory=dict),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _sec01: dict = Depends(require_money_write(
        "revenue.client_act_confirm.execute", module='M2',
        resource_type="client_act")),  # SEC-01-C02 (R14, FG-30, ACT-01 FG-119): before any read
    user: dict = Depends(require_m2),
):
    """Confirm act → status=Accepted → earned revenue (ACT-01 FG-119: finance roles,
    Idempotency-Key, one transaction with the offer/version/cap re-check and the canonical
    AuditEvent; FG-142: body ``expected_total`` + ``expected_line_values`` — the values the
    confirmer saw, in whole cents; a recomputed difference -> 409 ACT_VALUE_CHANGED)."""
    key = ca.KeyedWrite(db, user, ca.ACTION_CONFIRM, idempotency_key)       # 428 without
    tenant = _tenant(user)
    if not await tenant.client_acts.find_one({"id": act_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Act not found")
    expected = ca.validate_expected(data)       # FG-142: the values the confirmer saw (422)
    return await key.run(
        {"route": "POST /client-acts/{act_id}/confirm", "act_id": act_id, "body": data},
        lambda: ca.confirm_act(db, user=user, act_id=act_id, key=key,
                               endpoint="POST /api/client-acts/{act_id}/confirm",
                               expected=expected))


@router.post("/client-acts/from-offer/{offer_id}", status_code=201)
async def create_act_from_offer(
    offer_id: str,
    data: Dict[str, Any] = Body(default_factory=dict),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _sec02: dict = Depends(require_finance_read(
        "finance.client_act_from_offer.execute", module="M2", resource_type="client_act_from_offer")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2),
):
    """A draft act with ``percent`` of every line of an ACCEPTED offer — through the same
    checks as POST /client-acts (price from the offer, remainder, no double acting)."""
    data = _body_dict(data if data is not None else {})
    key = ca.KeyedWrite(db, user, ca.ACTION_FROM_OFFER, idempotency_key)    # 428 without
    tenant = _tenant(user)
    offer = await tenant.offers.find_one({"id": offer_id}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if offer.get("status") != ca.ACCEPTED:
        raise HTTPException(status_code=422, detail={
            "error_code": "OFFER_NOT_ACCEPTED",
            "message": "Акт се прави само по приета оферта (статусът е „%s“)" % offer.get("status")})
    percent = data.get("percent", 100)
    if (isinstance(percent, bool) or not isinstance(percent, (int, float))
            or not math.isfinite(percent) or percent <= 0):
        raise HTTPException(status_code=422, detail={
            "error_code": "PERCENT_INVALID", "message": "Процентът трябва да е число над 0"})
    raw_lines = []
    for ol in offer.get("lines") or []:
        qty = round(float(ol.get("qty") or 0) * float(percent) / 100, 4)
        if ol.get("id") and qty > 0:
            raw_lines.append({"offer_line_id": ol["id"], "executed_qty": qty})
    if not raw_lines:
        raise HTTPException(status_code=422, detail={
            "error_code": "LINES_REQUIRED", "message": "Офертата няма редове за актуване"})
    header = {k: data.get(k) for k in _HEADER_FIELDS}
    header["notes"] = header.get("notes") or f"От оферта {offer.get('offer_no', '')}"
    header["currency"] = offer.get("currency", "EUR")
    return await key.run(
        {"route": "POST /client-acts/from-offer/{offer_id}", "offer_id": offer_id, "body": data},
        lambda: ca.create_act(db, user=user, project_id=offer["project_id"],
                              raw_lines=raw_lines, header=header, key=key,
                              endpoint="POST /api/client-acts/from-offer/{offer_id}",
                              source_offer_id=offer_id))


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — LABOR COST AGGREGATION
# ═══════════════════════════════════════════════════════════════════

@router.get("/labor-cost/by-project/{project_id}")
async def get_labor_cost_by_project(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_labor_cost.read", module="M2", resource_type="project_labor_cost")),  # SEC-02 (R20-2): before any read
    date_from: Optional[str] = None, date_to: Optional[str] = None, user: dict = Depends(require_m2)):
    """R62 (FG-420): the project's labor cost from THE labor cost (approved reports priced by
    the one labor calculation + Owner-approved manual rows) — not work_reports × rate."""
    from app.services.labor_cost import project_labor_cost
    tenant = _tenant(user)
    org_id = user["org_id"]
    lc = await project_labor_cost(org_id, project_id, date_from, date_to)

    users = await tenant.users.find({"org_id": org_id}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(200)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}

    by_employee, by_activity = {}, {}
    for rec in lc["lines"]:
        uid, hours, cost = rec.get("worker_id"), float(rec.get("hours") or 0), float(rec.get("amount") or 0)
        e = by_employee.setdefault(uid, {"user_id": uid, "name": name_map.get(uid, ""),
                                          "hourly_rate": rec.get("rate"), "hours": 0, "cost": 0})
        e["hours"] += hours
        e["cost"] += cost
        act = rec.get("smr_type") or "Общо"
        a_ = by_activity.setdefault(act, {"activity_name": act, "hours": 0, "cost": 0})
        a_["hours"] += hours
        a_["cost"] += cost
    for v in list(by_employee.values()) + list(by_activity.values()):
        v["hours"] = round(v["hours"], 1)
        v["cost"] = round(v["cost"], 2)

    return {
        "project_id": project_id,
        "total_hours": round(lc["approved_hours"] + lc.get("downtime_hours", 0), 1),
        "total_cost": lc["total"],
        "currency": "EUR",
        "by_employee": sorted(by_employee.values(), key=lambda x: x["cost"], reverse=True),
        "by_activity": sorted(by_activity.values(), key=lambda x: x["cost"], reverse=True),
        "data_source": "project_labor_cost (R62: approved reports + Owner-approved manual rows)",
        "reports_count": len(lc["lines"]),
        "dq_warnings": lc["dq_warnings"],
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — EXECUTION PACKAGES
# ═══════════════════════════════════════════════════════════════════

@router.post("/execution-packages/from-offer/{offer_id}", status_code=201)
async def generate_execution_packages(offer_id: str, user: dict = Depends(require_m2)):
    """Generate execution packages from accepted offer lines"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    offer = await tenant.offers.find_one({"id": offer_id, "org_id": org_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    existing = await tenant.execution_packages.count_documents({"org_id": org_id, "source_offer_id": offer_id})
    if existing > 0:
        raise HTTPException(status_code=400, detail="Execution packages already exist for this offer")

    now = datetime.now(timezone.utc).isoformat()
    packages = []

    for ol in offer.get("lines", []):
        qty = ol.get("qty", 0)
        mat_cost = ol.get("material_unit_cost", 0)
        lab_cost = ol.get("labor_unit_cost", 0)
        sale_price = round(mat_cost + lab_cost, 2)

        pkg = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "project_id": offer["project_id"],
            "source_offer_id": offer_id,
            "offer_line_id": ol.get("id"),
            "activity_type": ol.get("activity_type", "Общо"),
            "activity_subtype": ol.get("activity_subtype", ""),
            "activity_name": ol.get("activity_name", ""),
            "unit": ol.get("unit", "m2"),
            "qty": qty,
            "sale_unit_price": sale_price,
            "sale_total": round(qty * sale_price, 2),
            "material_budget_total": round(qty * mat_cost, 2),
            "labor_budget_total": round(qty * lab_cost, 2),
            "subcontract_budget_total": 0,
            "overhead_budget_total": 0,
            "budget_total": round(qty * sale_price, 2),
            "planned_margin": 0,
            "planned_hours": 0,
            "actual_material_cost": 0,
            "actual_labor_cost": 0,
            "actual_subcontract_cost": 0,
            "actual_overhead_cost": 0,
            "actual_total_cost": 0,
            "used_hours": 0,
            "qty_executed": 0,
            "progress_percent": 0,
            "status": "Planning",
            "created_at": now,
            "updated_at": now,
        }
        packages.append(pkg)

    if packages:
        await tenant.execution_packages.insert_many(packages)

    return {"ok": True, "count": len(packages), "offer_id": offer_id, "project_id": offer["project_id"]}


async def live_package_actuals(tenant, org_id: str, pkgs: list) -> list:
    """R62 (FG-420): the package actuals at READ time — material from the one shared material
    helper, labor from THE labor cost; subcontract / overhead as stored. The cached
    ``actual_material_cost`` / ``actual_labor_cost`` / ``actual_total_cost`` are never shown."""
    from app.services.canonical_material_cost import project_material_cost, split_for_package
    from app.services.labor_cost import package_labor_split
    by_project = {}
    for p in pkgs:
        by_project.setdefault(p.get("project_id"), []).append(p)
    out = []
    for project_id, group in by_project.items():
        mat = await project_material_cost(tenant, org_id, project_id) if project_id else None
        lab = await package_labor_split(org_id, project_id) if project_id else {}
        for p in group:
            m = split_for_package(mat, p["id"])["total"] if mat is not None else 0.0
            l_ = (lab.get(p["id"]) or {}).get("cost", 0.0)
            sub = float(p.get("actual_subcontract_cost", 0) or 0)
            ovh = float(p.get("actual_overhead_cost", 0) or 0)
            out.append(dict(p, actual_material_cost=round(m, 2), actual_labor_cost=round(l_, 2),
                            actual_total_cost=round(m + l_ + sub + ovh, 2), actuals_at_read_time=True))
    order = {p["id"]: i for i, p in enumerate(pkgs)}
    return sorted(out, key=lambda x: order.get(x["id"], 0))


@router.get("/execution-packages")
async def list_execution_packages(
    _sec02: dict = Depends(require_finance_read(
        "finance.execution_package.read", module="M2", resource_type="execution_package")),  # SEC-02 (R20-1): before any read
    project_id: Optional[str] = None, offer_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    if offer_id:
        query["source_offer_id"] = offer_id
    pkgs = await tenant.execution_packages.find(query, {"_id": 0}).sort("created_at", 1).to_list(500)
    return await live_package_actuals(tenant, user["org_id"], pkgs)   # R62 (FG-420): no stale cache


@router.put("/execution-packages/{pkg_id}")
async def update_execution_package(
    pkg_id: str, data: dict,
    _sec02: dict = Depends(require_finance_read(
        "finance.execution_package.update", module="M2", resource_type="execution_package")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    pkg = await tenant.execution_packages.find_one({"id": pkg_id, "org_id": user["org_id"]})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    # R62: the labor actual of a package is THE labor cost (approved reports + Owner-approved
    # manual rows) — it is not typed in here; a manual labor row goes through
    # POST /labor-entries and the Owner's approval.
    if "actual_labor_cost" in (data or {}):
        raise HTTPException(status_code=422, detail=(
            "Трудът по пакета се изчислява от одобрените отчети и одобрените ръчни редове — не се въвежда тук"))
    allowed = ["progress_percent", "used_hours", "qty_executed", "status",
               "actual_material_cost", "actual_subcontract_cost", "actual_overhead_cost",
               "planned_hours", "planned_margin", "notes"]
    update = {k: v for k, v in data.items() if k in allowed}

    if any(k.startswith("actual_") for k in update):
        mat = float(update.get("actual_material_cost", pkg.get("actual_material_cost", 0)))
        from app.services.labor_cost import package_labor_actual
        lab = await package_labor_actual(user["org_id"], pkg)   # R62: THE labor cost
        sub = float(update.get("actual_subcontract_cost", pkg.get("actual_subcontract_cost", 0)))
        ovh = float(update.get("actual_overhead_cost", pkg.get("actual_overhead_cost", 0)))
        update["actual_total_cost"] = round(mat + lab + sub + ovh, 2)

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await tenant.execution_packages.update_one({"id": pkg_id}, {"$set": update})
    return await tenant.execution_packages.find_one({"id": pkg_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — PROJECT PROFIT SUMMARY (READ MODEL)
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-profit/{project_id}")
async def get_project_profit_summary(
    project_id: str,
    request: Request = None,                    # SUB-ADV-01 (FG-128); None = direct call
    _sec02: dict = Depends(require_finance_read(
        "finance.project_profit.read", module="M2", resource_type="project_profit")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Comprehensive project financial summary — revenue, costs, profit"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    project = await tenant.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # ── REVENUE ──
    # R1: Contracted (accepted offers)
    accepted_offers = await tenant.offers.find(
        {"project_id": project_id, "org_id": org_id, "status": "Accepted"},
        {"_id": 0, "total": 1, "subtotal": 1}
    ).to_list(100)
    contracted_revenue = sum(o.get("subtotal", 0) or o.get("total", 0) for o in accepted_offers)

    # R2: Earned (accepted client acts)
    accepted_acts = await tenant.client_acts.find(
        {"project_id": project_id, "org_id": org_id, "status": "Accepted"},
        {"_id": 0, "subtotal": 1}
    ).to_list(100)
    earned_revenue = sum(a.get("subtotal", 0) for a in accepted_acts)

    # R3: Billed (issued invoices) — R89 (Krum 14.11.2026, FG-696 — final): "фактурирано" =
    # final invoices − credit notes (Overdue included), net, no proforma; "получено" = the
    # payments received (FLOW-006 ledger), net — R90: paid proforma advances in, credit-note
    # refunds out — the one shared rule of the project report
    issued_invoices = await tenant.invoices.find(
        {"project_id": project_id, "org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled"]}},
        {"_id": 0, "id": 1, "subtotal": 1, "total": 1, "paid_amount": 1, "status": 1, "kind": 1,
         "advance_proforma_ids": 1}
    ).to_list(100)
    from app.services.project_pnl import received_revenue
    _rec = await received_revenue(tenant, org_id, [project_id], invoices=issued_invoices)
    billed_revenue = _rec["invoiced_net"]

    # R5: Collected — "получено" = THE revenue of "Печалба по обект" (R89)
    collected_revenue = _rec["received_net"]

    # ── EXPENSES ──
    # Material cost — 5C-C22: the ONE shared helper (canonical consumption
    # + „фира" + legacy issues dated before the tenant cutover, Р13). The
    # former private legacy issue/return sum is gone: legacy return rows
    # never carried a price, so they never changed the figure.
    from app.routes.material_smr import get_material_summary_for_project
    material_summary = await get_material_summary_for_project(org_id, project_id)
    net_material_cost = material_summary["total_cost"]
    # 5C-C21 F-12 — the „фира" share of that total, shown as its own line;
    # the total is still counted once.
    material_waste_cost = material_summary.get("waste_cost", 0.0) or 0.0

    # Labor cost — R62 (Krum 09.11.2026, FG-340): THE labor cost of the project, the same
    # number as the P&L and the net profit (approved reports, Owner-approved manual rows).
    # No fallback: drafts / unapproved work reports never count.
    from app.routes.labor_smr import get_labor_summary_for_project
    labor_summary = await get_labor_summary_for_project(org_id, project_id)
    labor_cost = labor_summary["total_cost"]
    labor_hours = labor_summary["total_hours"]

    # Subcontract cost: from subcontractor packages + acts + payments
    from app.routes.subcontractors import get_subcontract_metrics
    sub_metrics = await get_subcontract_metrics(org_id, project_id)
    
    from app.routes.subcontractors import advance_visible, get_advance_metrics
    subcontract_advances = (await get_advance_metrics(org_id, project_id)
                            if await advance_visible(request, user) else None)

    # Fallback to received invoices if no subcontractor packages
    if sub_metrics.get("available"):
        subcontract_cost = sub_metrics["certified"]  # certified = execution cost basis
    else:
        # F-81-01 / Р45: a supplier invoice reaches the project P&L only by the
        # part of its LINES allocated to the project (ex VAT) — never by the
        # header project_id / whole subtotal; the unallocated rest is in
        # „фактури за разпределяне", not in this project. FLOW-043 D-04 (one
        # classification): `invoice_lines` documents allocated to the project
        # are already in the material cost (Path B, FG-17), so only invoices
        # whose lines are EMBEDDED (FG-200) are read here.
        from app.services.invoice_allocation import RECEIVED_LINE_FIELDS, received_result
        received_invoices = await tenant.invoices.find(
            {"org_id": org_id, "direction": "Received", "status": {"$nin": ["Draft", "Cancelled"]},
             "$or": [{"project_id": project_id}, {"lines.project_id": project_id},
                     {"lines.allocations": {"$elemMatch": {"type": "project", "ref_id": project_id}}}]},
            {"_id": 0, **RECEIVED_LINE_FIELDS}
        ).to_list(500)
        _ids = [i["id"] for i in received_invoices if i.get("id")]
        _path_b = {ln.get("invoice_id") async for ln in tenant.invoice_lines.find(
            {"org_id": org_id, "invoice_id": {"$in": _ids}}, {"_id": 0, "invoice_id": 1})}
        received_invoices = [i for i in received_invoices if i.get("id") not in _path_b]
        subcontract_cost = round(sum((await received_result(
            tenant, org_id, received_invoices, dest_type="project", ref_id=project_id)).values()), 2)

    # Overhead: from allocations if exist
    # FG-89: the project's current OH-01 allocation — the single overhead source
    from app.services.overhead_lifecycle import project_overhead_current
    _oh = await project_overhead_current(tenant, project_id)
    overhead_cost, overhead_allocs = _oh["amount"], _oh["rows"]
    from app.services.overhead_lifecycle import recalculating_fields

    # ── PROFIT ──
    total_cost = round(net_material_cost + labor_cost + subcontract_cost + overhead_cost, 2)
    # R89 (Krum 14.11.2026): "приход" here is only the money received — the profit is
    # получено − разходи (contracted / earned stay as their own columns, never revenue)
    primary_revenue = collected_revenue
    gross_profit = round(primary_revenue - total_cost, 2)
    gross_margin = round(gross_profit / primary_revenue * 100, 1) if primary_revenue > 0 else 0

    receivables = round(billed_revenue - collected_revenue, 2)

    # ── EXECUTION PACKAGES BREAKDOWN ──
    exec_pkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0}
    ).to_list(200)
    exec_pkgs = await live_package_actuals(tenant, org_id, exec_pkgs)   # R62 (FG-420): no stale cache

    pkg_breakdown = []
    for p in exec_pkgs:
        sale = p.get("sale_total", 0)
        actual = p.get("actual_total_cost", 0)
        margin = round(sale - actual, 2) if actual > 0 else None
        pkg_breakdown.append({
            "id": p["id"],
            "activity_name": p.get("activity_name", ""),
            "unit": p.get("unit", ""),
            "qty": p.get("qty", 0),
            "sale_total": sale,
            "budget_total": p.get("budget_total", 0),
            "actual_total_cost": actual,
            "profit": margin,
            "progress_percent": p.get("progress_percent", 0),
            "status": p.get("status", ""),
        })

    # Determine data availability
    metrics_available = {
        "contracted_revenue": len(accepted_offers) > 0,
        "earned_revenue": len(accepted_acts) > 0,
        "billed_revenue": len(issued_invoices) > 0,
        "material_cost": material_summary["has_data"],
        "labor_cost": labor_summary["has_data"],
        "subcontract_cost": sub_metrics.get("available", False),
        "overhead_cost": len(overhead_allocs) > 0,
        "execution_packages": len(exec_pkgs) > 0,
    }

    return {
        "project_id": project_id,
        "project_code": project.get("code", ""),
        "project_name": project.get("name", ""),
        "currency": "EUR",

        "revenue": {
            "contracted": round(contracted_revenue, 2),
            "earned": round(earned_revenue, 2),
            "billed": round(billed_revenue, 2),
            "collected": round(collected_revenue, 2),
            "billed_label": "Фактурирано (без ДДС, без проформа)",
            "collected_label": "Получено (без ДДС)",
            "revenue_rule": _rec["revenue_basis"],
            "receivables": receivables,
        },

        # SUB-ADV-01-B (FG-128): subcontractor advances given / deducted / remaining — cash and
        # settlement, NOT an expense (FLOW-006): outside "expenses"; finance roles only (else None).
        "subcontract_advances": subcontract_advances,

        "expenses": {
            "material": round(net_material_cost - material_waste_cost, 2),
            "waste": round(material_waste_cost, 2),          # „фира" (5C-C21 F-12)
            "material_detail": material_summary if material_summary["has_data"] else None,
            # 5C-C22 / Р13 — the cutover split behind the material figure.
            "material_cost_basis": {k: material_summary.get(k) for k in (
                "source", "canonical_cost", "legacy_cost",
                "legacy_excluded_cost", "cutover_at")},
            "labor": labor_cost,
            "labor_hours": round(labor_hours, 1),
            "labor_detail": labor_summary,
            "subcontract": round(subcontract_cost, 2),
            "subcontract_detail": sub_metrics if sub_metrics.get("available") else None,
            "overhead": round(overhead_cost, 2),
            **recalculating_fields(_oh["recalculating"]),  # FG-116 (R38)
            "total": total_cost,
        },

        "profit": {
            "gross_profit": gross_profit,
            "gross_margin_percent": gross_margin,
            "revenue_basis": "received",          # R89: получено − разходи
            "revenue_label": "Приход = получено (без ДДС)",
        },

        "execution_packages": pkg_breakdown,
        "metrics_available": metrics_available,
    }



# ═══════════════════════════════════════════════════════════════════
# PROJECT MAIN OFFER + SMR OPERATIONAL VIEW
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-smr-view/{project_id}")
async def get_project_smr_view(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_smr_view.read", module="M2", resource_type="project_smr_view")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Operational SMR view for project — main offer + execution packages with labor focus"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    project = await tenant.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Main offer (accepted, non-extra, most recent)
    main_offer = await tenant.offers.find_one(
        {"org_id": org_id, "project_id": project_id, "status": "Accepted", "offer_type": {"$ne": "extra"}},
        {"_id": 0, "id": 1, "offer_no": 1, "title": 1, "status": 1, "total": 1, "subtotal": 1, "currency": 1, "accepted_at": 1, "lines": 1},
        sort=[("accepted_at", -1)]
    )
    if not main_offer:
        # Fallback to latest non-draft
        main_offer = await tenant.offers.find_one(
            {"org_id": org_id, "project_id": project_id, "offer_type": {"$ne": "extra"}, "status": {"$nin": ["Draft"]}},
            {"_id": 0, "id": 1, "offer_no": 1, "title": 1, "status": 1, "total": 1, "subtotal": 1, "currency": 1, "lines": 1},
            sort=[("created_at", -1)]
        )

    # Execution packages with progress + labor
    pkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    # Subcontract by package
    sub_lines = await tenant.subcontractor_package_lines.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "execution_package_id": 1, "subcontract_total": 1, "certified_total": 1, "assigned_qty": 1}
    ).to_list(500)
    sub_by_pkg = {}
    for sl in sub_lines:
        ep_id = sl.get("execution_package_id")
        if ep_id:
            if ep_id not in sub_by_pkg:
                sub_by_pkg[ep_id] = {"contract": 0, "certified": 0, "has_sub": True}
            sub_by_pkg[ep_id]["contract"] += sl.get("subcontract_total", 0)
            sub_by_pkg[ep_id]["certified"] += sl.get("certified_total", 0)

    # 5C-C22 — package material actual from the ONE shared helper (read
    # time), not the `actual_material_cost` cache that only a recompute fills.
    from app.services.canonical_material_cost import project_material_cost, split_for_package
    mat_cost = await project_material_cost(tenant, org_id, project_id)
    from app.services.labor_cost import package_labor_split
    labor_split = await package_labor_split(org_id, project_id)   # R62: THE labor cost, at read time

    rows = []
    for pkg in pkgs:
        pid = pkg["id"]
        sale = pkg.get("sale_total", 0)
        mat_split = split_for_package(mat_cost, pid)
        lab_budget = pkg.get("labor_budget_total", 0)
        lab_actual = (labor_split.get(pid) or {}).get("cost", 0.0)
        lab_remaining = round(lab_budget - lab_actual, 2) if lab_budget > 0 else None
        progress = pkg.get("progress_percent", 0) or 0
        has_progress = pkg.get("progress_last_updated_at") is not None
        sub = sub_by_pkg.get(pid)

        # Determine mode
        if sub and sub["has_sub"] and lab_actual > 0:
            mode = "mixed"
        elif sub and sub["has_sub"]:
            mode = "akord"
        else:
            mode = "internal"

        # Offer line price reference
        offer_labor_price = None
        if main_offer:
            for ol in main_offer.get("lines", []):
                if ol.get("id") == pkg.get("offer_line_id"):
                    offer_labor_price = ol.get("labor_unit_cost", 0)
                    break

        # Warning flags
        flags = []
        if not has_progress:
            flags.append("no_progress")
        if lab_budget > 0 and lab_actual > lab_budget:
            flags.append("labor_overrun")
        planned_h = pkg.get("planned_hours")
        used_h = pkg.get("used_hours", 0)
        if planned_h and used_h > planned_h:
            flags.append("hours_overrun")

        rows.append({
            "id": pid,
            "activity_name": pkg.get("activity_name", ""),
            "unit": pkg.get("unit", ""),
            "qty": pkg.get("qty", 0),
            "mode": mode,
            "sale_total": sale,
            "offer_labor_unit_price": offer_labor_price,
            "labor_budget": lab_budget,
            "labor_actual": lab_actual,
            "labor_remaining": lab_remaining,
            "planned_hours": planned_h,
            "used_hours": used_h,
            "remaining_hours": round(planned_h - used_h, 1) if planned_h else None,
            "progress_percent": progress,
            "has_progress": has_progress,
            "material_actual": mat_split["material"],
            "material_waste": mat_split["waste"],          # „фира"
            "subcontract": round(sub["certified"], 2) if sub else 0,
            "total_actual": round(lab_actual + mat_split["total"] + (sub["certified"] if sub else 0), 2),
            "flags": flags,
            "status": pkg.get("status", ""),
        })

    return {
        "project_id": project_id,
        "project_code": project.get("code", ""),
        "project_name": project.get("name", ""),
        "currency": "EUR",
        "main_offer": {
            "id": main_offer["id"],
            "offer_no": main_offer["offer_no"],
            "title": main_offer.get("title", ""),
            "status": main_offer["status"],
            "total": main_offer.get("total", 0),
            "subtotal": main_offer.get("subtotal", 0),
            "line_count": len(main_offer.get("lines", [])),
        } if main_offer else None,
        "rows": rows,
        "summary": {
            "total_packages": len(rows),
            "total_sale": round(sum(r["sale_total"] for r in rows), 2),
            "total_labor_budget": round(sum(r["labor_budget"] for r in rows), 2),
            "total_labor_actual": round(sum(r["labor_actual"] for r in rows), 2),
            "with_warnings": sum(1 for r in rows if r["flags"]),
        },
    }
