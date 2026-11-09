"""
Routes - Subcontractor Financial Flow.
Phase 1: Subcontractors + Packages
Phase 2: Package Lines from Offer/Execution
Phase 3: Subcontractor Acts (Certified Expense)
Phase 4: Subcontractor Payments
Phase 5: Profit Integration (extends revenue_expense)
"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from typing import Any, Dict, Optional, List
import logging

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.tenancy.data_access import TenantData
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.utils.audit import log_audit
from app.services import master_records as mr
from app.services.bank_account_guard import (check_payment_target, is_cash_account,
                                             require_selectable_party)
from app.permissions.money_write import require_money_write, require_finance_read, strip_money_for_non_finance
from app.permissions.money_input import MoneyWrite, money_value, project_in_tenant  # SEC-01-C03

router = APIRouter(tags=["Subcontractors"])


def _tenant(user: dict) -> TenantData:
    """W0-03E-A1: the session user's tenant view of the legacy database."""
    return TenantData.for_user(db, user)


# ── SUB-ADV-01-B (FG-128): the advance is shown to the finance roles only ─────────────
# FLOW-021: Krum sees "даден / прихванат / оставащ аванс"; FLOW-006: the outstanding advance is
# not a P&L line. The given / deducted / remaining advance (and the advance rows) are money:
# visible to Owner/Admin/Accountant only, hidden — never refused — for everyone else.
ADVANCE_PKG_FIELDS = frozenset({
    "advance_total", "advance_deducted_total", "advance_outstanding", "advance_pending_total",
    "advance_deduction_pending_total", "advance_deducted_by_act",
    "advance_deduction_pending_by_act", "advance_reservations", "advance_confirmed",
    "advance_deduction_confirmed", "cash_out_total"})
ADVANCE_ACT_FIELDS = frozenset({"advance_deducted", "advance_deductions"})


async def advance_visible(request: Request, user: dict) -> bool:
    """off/shadow: the legacy finance roles; enforce: the Permission Service on the finance
    action ``subcontract.advance_deduction.execute`` (Owner/Admin/Accountant hold it). The
    same pattern as ``money_input.labor_money_visible``; no denial audit (a hidden value is
    not a refused action)."""
    from app.permissions.deps import current_mode, MODE_ENFORCE
    from app.permissions.money_write import FINANCE_WRITE_ROLES
    if current_mode() != MODE_ENFORCE:
        return user.get("role") in FINANCE_WRITE_ROLES
    if request is None:     # a direct (non-HTTP) call in enforce: fail closed, as SEC71-M1
        return False
    from app.tenancy.guard import get_tenant_context
    from app.permissions.service import evaluate_permission
    ctx = await get_tenant_context(request, user)
    decision = await evaluate_permission(ctx, "subcontract.advance_deduction.execute",
                                         module=None, scope_type=None, scope_id=None)
    return bool(decision.allowed)


def _strip(row: Optional[dict], fields) -> Optional[dict]:
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in fields}


def advance_summary(pkg: dict) -> dict:
    """FLOW-021 "Аванс и плащания": given / deducted / remaining advance of one package."""
    return {"given": round(float(pkg.get("advance_total") or 0), 2),
            "deducted": round(float(pkg.get("advance_deducted_total") or 0), 2),
            "outstanding": round(float(pkg.get("advance_total") or 0)
                                 - float(pkg.get("advance_deducted_total") or 0), 2),
            "pending": round(float(pkg.get("advance_pending_total") or 0), 2)}


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — SUBCONTRACTORS + PACKAGES
# ═══════════════════════════════════════════════════════════════════

class SubcontractorCreate(BaseModel):
    name: str
    eik: Optional[str] = None
    vat_number: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None

class PackageCreate(BaseModel):
    project_id: str
    subcontractor_id: str
    title: str
    description: Optional[str] = None
    source_offer_id: Optional[str] = None
    currency: str = "EUR"
    notes: Optional[str] = None

PKG_STATUSES = ["draft", "confirmed", "in_progress", "partially_certified", "completed", "closed"]


@router.post("/subcontractors", status_code=201)
async def create_subcontractor(data: SubcontractorCreate, user: dict = Depends(require_m2),
                               idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    """CP-01 (R48.5): a subcontractor is a counterparty — Accountant/Admin/Owner, key, AuditEvent.
    FG-229 (R48.6): an ЕИК already held by a subcontractor OR a counterparty → 409 + DQ."""
    from app.services import counterparty_rules as cr
    from app.services.master_write import conflict, dq_issue
    mr.require_writer(user)
    eik = cr.normalize_eik(data.eik) if data.eik and data.eik.strip() else None
    if data.eik and data.eik.strip() and not eik:
        raise HTTPException(status_code=422, detail={"error_code": "EIK_INVALID",
                                                     "message": "ЕИК съдържа само цифри"})
    sub = {
        "name": data.name, "eik": eik, "vat_number": data.vat_number,
        "contact_person": data.contact_person, "phone": data.phone,
        "email": data.email, "address": data.address, "notes": data.notes,
        "active": True,
    }
    tenant = _tenant(user)

    async def check(tenant_, session):
        await mr.claim_eik(tenant_, session, eik)
        if await mr.eik_holder(tenant_, eik, session=session):
            raise conflict("EIK_ALREADY_EXISTS", "Контрагент/подизпълнител с този ЕИК вече съществува")

    try:
        return await mr.create(db, user, idempotency_key, collection="subcontractors", doc=sub,
                               fingerprint=data.model_dump(), check=check)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if exc.status_code == 409 and detail.get("error_code") == "EIK_ALREADY_EXISTS":
            holder = await mr.eik_holder(tenant, eik)
            await dq_issue(tenant, None, code="DUPLICATE_EIK", severity="critical",
                           entity_type=mr.ENTITIES[holder[0]][0] if holder else "subcontractor",
                           entity_id=holder[1]["id"] if holder else None,
                           message="Опит за втори запис със същия ЕИК (подизпълнител)",
                           data={"eik": eik}, created_by=user["id"])
        raise


@router.get("/subcontractors")
async def list_subcontractors(user: dict = Depends(require_m2), include_archived: bool = False):
    tenant = _tenant(user)
    subs = await tenant.subcontractors.find(mr.hide_archived({"org_id": user["org_id"]}, include_archived),
                                            {"_id": 0}).sort("name", 1).to_list(200)
    from app.services import counterparty_rules as cr
    subs = cr.mask_iban_fields(subs, await cr.full_iban_allowed(user))       # CP-01 FG-245
    return subs


def _sub_lifecycle(action: str):
    """FG-244 (R48.4): a subcontractor is a counterparty — never deleted; „неактивен“
    (Accountant / Admin / Owner, reversible) or „архивиран“ (Admin / Owner); reason + AuditEvent;
    back from the archive its IBANs return to „за проверка“ (R50.3)."""
    async def handler(sub_id: str, body: Dict[str, Any] = Body(default={}),
                      user: dict = Depends(require_m2),
                      idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
        return await mr.lifecycle(db, user, idempotency_key, collection="subcontractors",
                                  record_id=sub_id, action=action, body=body)
    handler.__name__ = "%s_subcontractor" % action
    return handler


for _action in mr.LIFECYCLE_ACTIONS:
    router.add_api_route("/subcontractors/{sub_id}/%s" % _action, _sub_lifecycle(_action),
                         methods=["POST"])


@router.get("/subcontractors/{sub_id}")
async def get_subcontractor(sub_id: str, user: dict = Depends(require_m2)):
    sub = await _tenant(user).subcontractors.get(sub_id, {"_id": 0})
    from app.services import counterparty_rules as cr
    sub = cr.mask_iban_fields(sub, await cr.full_iban_allowed(user))         # CP-01 FG-245
    if not sub:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    # W0-03E: additive master_ref in MASTER_DATA_MODE=enforce only.
    from app.master_data.legacy_adapter import annotate
    return (await annotate(user, "subcontractors", [sub]))[0]


async def _get_next_pkg_no(org_id):
    tenant = TenantData.for_resolved_org(db, org_id)
    last = await tenant.subcontractor_packages.find_one({"org_id": org_id}, {"_id": 0, "package_no": 1}, sort=[("created_at", -1)])
    n = 1
    if last and last.get("package_no"):
        try: n = int(last["package_no"].split("-")[1]) + 1
        except Exception as e: logger.warning(f"subcontractors.py error: {e}")
    return f"SP-{n:04d}"


@router.post("/subcontractor-packages", status_code=201)
async def create_package(data: PackageCreate, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    project = await tenant.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sub = await tenant.subcontractors.find_one({"id": data.subcontractor_id, "org_id": org_id})
    if not sub:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    await require_selectable_party(tenant, "subcontractor", data.subcontractor_id)  # R48.4

    now = datetime.now(timezone.utc).isoformat()
    pkg = {
        "id": str(uuid.uuid4()), "org_id": org_id,
        "project_id": data.project_id, "subcontractor_id": data.subcontractor_id,
        "package_no": await _get_next_pkg_no(org_id),
        "title": data.title, "description": data.description,
        "source_offer_id": data.source_offer_id, "currency": data.currency,
        "contract_total": 0, "certified_total": 0, "paid_total": 0,
        "payable_total": 0, "remaining_contract_total": 0,
        "planned_margin": 0, "realized_margin": 0,
        "notes": data.notes, "status": "draft",
        "created_at": now, "updated_at": now,
    }
    await tenant.subcontractor_packages.insert_one(pkg)
    return {k: v for k, v in pkg.items() if k != "_id"}


@router.get("/subcontractor-packages")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def list_packages(request: Request = None, project_id: Optional[str] = None, subcontractor_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if subcontractor_id: q["subcontractor_id"] = subcontractor_id
    pkgs = await tenant.subcontractor_packages.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    if not await advance_visible(request, user):          # FG-128
        return [_strip(p, ADVANCE_PKG_FIELDS) for p in pkgs]
    for p in pkgs:
        p["advance"] = advance_summary(p)                 # given / deducted / remaining
    return pkgs


@router.get("/subcontractor-packages/{pkg_id}")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def get_package(pkg_id: str, request: Request = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    lines = await tenant.subcontractor_package_lines.find({"package_id": pkg_id}, {"_id": 0}).sort("sort_order", 1).to_list(200)
    pkg["lines"] = lines
    if not await advance_visible(request, user):          # FG-128
        return _strip(pkg, ADVANCE_PKG_FIELDS)
    pkg["advance"] = advance_summary(pkg)                 # given / deducted / remaining
    return pkg


@router.post("/subcontractor-packages/{pkg_id}/confirm")
async def confirm_package(pkg_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft packages can be confirmed")
    lines = await tenant.subcontractor_package_lines.count_documents({"package_id": pkg_id})
    if lines == 0:
        raise HTTPException(status_code=400, detail="Package has no lines")

    all_lines = await tenant.subcontractor_package_lines.find({"package_id": pkg_id}, {"_id": 0}).to_list(200)
    contract_total = sum(l.get("subcontract_total", 0) for l in all_lines)
    sale_total = sum(l.get("sale_total_for_assigned_qty", 0) for l in all_lines)
    planned_margin = round(sale_total - contract_total, 2)

    now = datetime.now(timezone.utc).isoformat()
    await tenant.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {
        "status": "confirmed", "confirmed_at": now, "updated_at": now,
        "contract_total": round(contract_total, 2),
        "remaining_contract_total": round(contract_total, 2),
        "planned_margin": planned_margin,
    }})
    return await tenant.subcontractor_packages.find_one({"id": pkg_id}, {"_id": 0})


@router.post("/subcontractor-packages/{pkg_id}/close")
async def close_package(pkg_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] in ["draft", "closed"]:
        raise HTTPException(status_code=400, detail=f"Cannot close package in {pkg['status']} status")
    now = datetime.now(timezone.utc).isoformat()
    await tenant.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {"status": "closed", "closed_at": now, "updated_at": now}})
    return await tenant.subcontractor_packages.find_one({"id": pkg_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — PACKAGE LINES
# ═══════════════════════════════════════════════════════════════════

class PackageLineInput(BaseModel):
    offer_line_id: Optional[str] = None
    execution_package_id: Optional[str] = None
    activity_name: str
    unit: str = "m2"
    source_qty: float = 0
    assigned_qty: float = 0
    sale_unit_price: float = 0
    subcontract_unit_price: float = 0
    labor_unit_price: float = 0
    material_unit_price: float = 0
    material_by: str = "them"          # me | them | split — who buys the material
    material_my_share: float = 0       # 0..1, my share of the material cost


async def _get_assigned_qty(org_id: str, offer_line_id: str, exclude_pkg_id: str = None) -> float:
    """Get total already-assigned qty for an offer line across all packages"""
    tenant = TenantData.for_resolved_org(db, org_id)
    q = {"org_id": org_id, "offer_line_id": offer_line_id}
    if exclude_pkg_id:
        q["package_id"] = {"$ne": exclude_pkg_id}
    lines = await tenant.subcontractor_package_lines.find(q, {"_id": 0, "assigned_qty": 1}).to_list(100)
    return sum(l.get("assigned_qty", 0) for l in lines)


@router.post("/subcontractor-packages/{pkg_id}/lines", status_code=201)
async def add_package_lines(pkg_id: str, data: dict, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Can only add lines to draft packages")

    input_lines = data.get("lines", [])
    if not input_lines:
        raise HTTPException(status_code=400, detail="No lines provided")

    existing_count = await tenant.subcontractor_package_lines.count_documents({"package_id": pkg_id})
    now = datetime.now(timezone.utc).isoformat()
    created = []

    for i, il in enumerate(input_lines):
        assigned = float(il.get("assigned_qty", 0))
        source_qty = float(il.get("source_qty", 0))
        offer_line_id = il.get("offer_line_id")

        # Over-allocation check
        if offer_line_id and source_qty > 0:
            already = await _get_assigned_qty(org_id, offer_line_id, pkg_id)
            free = source_qty - already
            if assigned > free + 0.01:
                raise HTTPException(status_code=400, detail=f"Over-allocation: {il.get('activity_name','')} — free={free:.2f}, requested={assigned:.2f}")

        sale_up = float(il.get("sale_unit_price", 0))
        # Separated labour + material (труд и материал разделени)
        labor_up = float(il.get("labor_unit_price", 0) or 0)
        material_up = float(il.get("material_unit_price", 0) or 0)
        material_by = il.get("material_by", "them")
        if material_by == "me":
            my_share = 1.0
        elif material_by == "them":
            my_share = 0.0
        else:
            my_share = float(il.get("material_my_share", 0.5) or 0)
        # What I pay the brigade = labour + the part of the material they cover
        if labor_up or material_up:
            sub_up = round(labor_up + material_up * (1 - my_share), 2)
            cost_up = round(labor_up + material_up, 2)   # full cost (труд + целия материал)
        else:
            sub_up = float(il.get("subcontract_unit_price", 0))
            cost_up = sub_up

        line = {
            "id": str(uuid.uuid4()), "org_id": org_id,
            "package_id": pkg_id, "project_id": pkg["project_id"],
            "offer_line_id": offer_line_id,
            "execution_package_id": il.get("execution_package_id"),
            "activity_type": il.get("activity_type", ""),
            "activity_subtype": il.get("activity_subtype", ""),
            "activity_name": il.get("activity_name", ""),
            "unit": il.get("unit", "m2"),
            "source_qty": source_qty, "assigned_qty": assigned,
            "sale_unit_price": sale_up,
            "sale_total_for_assigned_qty": round(assigned * sale_up, 2),
            "labor_unit_price": labor_up,
            "material_unit_price": material_up,
            "material_by": material_by,
            "material_my_share": my_share,
            "cost_unit_price": cost_up,
            "subcontract_unit_price": sub_up,
            "subcontract_total": round(assigned * sub_up, 2),
            "planned_margin": round(assigned * (sale_up - cost_up), 2),
            "certified_qty": 0, "certified_total": 0, "paid_total": 0,
            "remaining_qty": assigned, "remaining_value": round(assigned * sub_up, 2),
            "status": "active", "sort_order": existing_count + i,
            "created_at": now,
        }
        await tenant.subcontractor_package_lines.insert_one(line)
        created.append({k: v for k, v in line.items() if k != "_id"})

    return {"ok": True, "count": len(created), "lines": created}


@router.post("/subcontractor-packages/{pkg_id}/lines-from-offer/{offer_id}", status_code=201)
async def add_lines_from_offer(pkg_id: str, offer_id: str, user: dict = Depends(require_m2)):
    """Populate package lines from offer lines with availability check"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg or pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Package must be draft")

    offer = await tenant.offers.find_one({"id": offer_id, "org_id": org_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    # Load execution packages for linkage
    epkgs = {}
    for ep in await tenant.execution_packages.find({"org_id": org_id, "source_offer_id": offer_id}, {"_id": 0, "id": 1, "offer_line_id": 1}).to_list(200):
        if ep.get("offer_line_id"): epkgs[ep["offer_line_id"]] = ep["id"]

    lines_input = []
    for ol in offer.get("lines", []):
        qty = ol.get("qty", 0)
        mat_cost = ol.get("material_unit_cost", 0)
        lab_cost = ol.get("labor_unit_cost", 0)
        sale_up = round(mat_cost + lab_cost, 2)

        already = await _get_assigned_qty(org_id, ol["id"], pkg_id)
        free = qty - already
        if free <= 0:
            continue

        lines_input.append({
            "offer_line_id": ol["id"],
            "execution_package_id": epkgs.get(ol["id"]),
            "activity_type": ol.get("activity_type", ""),
            "activity_subtype": ol.get("activity_subtype", ""),
            "activity_name": ol.get("activity_name", ""),
            "unit": ol.get("unit", "m2"),
            "source_qty": qty, "assigned_qty": free,
            "sale_unit_price": sale_up, "subcontract_unit_price": 0,
        })

    return await add_package_lines(pkg_id, {"lines": lines_input}, user)


@router.delete("/subcontractor-package-lines/{line_id}")
async def remove_package_line(line_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    line = await tenant.subcontractor_package_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Line not found")
    pkg = await tenant.subcontractor_packages.find_one({"id": line["package_id"]})
    if not pkg or pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Can only remove lines from draft packages")
    await tenant.subcontractor_package_lines.delete_one({"id": line_id})
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — SUBCONTRACTOR ACTS (CERTIFIED EXPENSE)
# ═══════════════════════════════════════════════════════════════════

async def _get_next_act_no(org_id):
    tenant = TenantData.for_resolved_org(db, org_id)
    last = await tenant.subcontractor_acts.find_one({"org_id": org_id}, {"_id": 0, "act_no": 1}, sort=[("created_at", -1)])
    n = 1
    if last and last.get("act_no"):
        try: n = int(last["act_no"].split("-")[1]) + 1
        except Exception as e: logger.warning(f"subcontractors.py error: {e}")
    return f"SA-{n:04d}"


@router.post("/subcontractor-acts", status_code=201)
async def create_subcontractor_act(data: dict, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkg_id = data.get("package_id")
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] == "draft":
        raise HTTPException(status_code=400, detail="Package must be confirmed before creating acts")

    now = datetime.now(timezone.utc).isoformat()
    act_lines = []
    for al in data.get("lines", []):
        pl_id = al.get("package_line_id")
        pl = await tenant.subcontractor_package_lines.find_one({"id": pl_id}, {"_id": 0})
        if not pl:
            continue
        current_qty = float(al.get("current_certified_qty", 0))
        remaining = pl.get("remaining_qty", 0)
        if current_qty > remaining + 0.01:
            raise HTTPException(status_code=400, detail=f"Certification exceeds remaining: {pl.get('activity_name','')} remaining={remaining}, requested={current_qty}")

        act_lines.append({
            "id": str(uuid.uuid4()),
            "package_line_id": pl_id,
            "activity_name": pl.get("activity_name", ""),
            "unit": pl.get("unit", ""),
            "assigned_qty": pl.get("assigned_qty", 0),
            "previously_certified_qty": pl.get("certified_qty", 0),
            "current_certified_qty": current_qty,
            "total_certified_qty": round(pl.get("certified_qty", 0) + current_qty, 2),
            "subcontract_unit_price": pl.get("subcontract_unit_price", 0),
            "current_certified_total": round(current_qty * pl.get("subcontract_unit_price", 0), 2),
            "remaining_qty": round(remaining - current_qty, 2),
        })

    certified_total = sum(al["current_certified_total"] for al in act_lines)
    act = {
        "id": str(uuid.uuid4()), "org_id": org_id,
        "package_id": pkg_id, "subcontractor_id": pkg["subcontractor_id"],
        "project_id": pkg["project_id"],
        "act_no": await _get_next_act_no(org_id),
        "act_date": data.get("act_date", now[:10]),
        "lines": act_lines,
        "certified_total": round(certified_total, 2),
        "notes": data.get("notes", ""),
        "status": "draft",
        "created_at": now, "updated_at": now,
    }
    await tenant.subcontractor_acts.insert_one(act)
    return {k: v for k, v in act.items() if k != "_id"}


@router.get("/subcontractor-acts")
async def list_subcontractor_acts(
    request: Request = None,                    # SUB-ADV-01 (FG-128); None = direct call
    _sec02: dict = Depends(require_finance_read(
        "finance.subcontractor_act.read", module="M2", resource_type="subcontractor_act")),  # SEC-02 (R20-1): before any read
    project_id: Optional[str] = None, package_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if package_id: q["package_id"] = package_id
    acts = await tenant.subcontractor_acts.find(q, {"_id": 0}).sort("created_at", -1).to_list(100)
    if not await advance_visible(request, user):          # FG-128
        return [_strip(a, ADVANCE_ACT_FIELDS) for a in acts]
    return acts


@router.post("/subcontractor-acts/{act_id}/confirm")
async def confirm_subcontractor_act(
    act_id: str,
    _sec01: dict = Depends(require_money_write(
        "subcontract.act_confirm.execute", module="M2",
        resource_type="subcontractor_act")),  # SEC-01-C02 (R14, FG-30): before any read
    user: dict = Depends(require_m2),
):
    tenant = _tenant(user)
    act = await tenant.subcontractor_acts.find_one({"id": act_id, "org_id": user["org_id"]})
    if not act:
        raise HTTPException(status_code=404, detail="Act not found")
    if act["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft acts can be confirmed")

    now = datetime.now(timezone.utc).isoformat()

    # Update package lines
    for al in act.get("lines", []):
        pl_id = al["package_line_id"]
        new_cert = al["total_certified_qty"]
        new_cert_total = round(new_cert * al["subcontract_unit_price"], 2)
        new_remaining = round(al["assigned_qty"] - new_cert, 2)
        await tenant.subcontractor_package_lines.update_one({"id": pl_id}, {"$set": {
            "certified_qty": new_cert, "certified_total": new_cert_total,
            "remaining_qty": new_remaining,
            "remaining_value": round(new_remaining * al["subcontract_unit_price"], 2),
        }})

    # Update package totals
    pkg_id = act["package_id"]
    all_pl = await tenant.subcontractor_package_lines.find({"package_id": pkg_id}, {"_id": 0}).to_list(200)
    total_cert = sum(l.get("certified_total", 0) for l in all_pl)
    contract_total = sum(l.get("subcontract_total", 0) for l in all_pl)
    total_remaining = sum(l.get("remaining_qty", 0) for l in all_pl)

    pkg_status = "in_progress"
    if total_remaining <= 0:
        pkg_status = "completed"
    elif total_cert > 0:
        pkg_status = "partially_certified"

    await tenant.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {
        "certified_total": round(total_cert, 2),
        # SUB-ADV-01: what is still owed = certified - paid - advance already deducted.
        "payable_total": _payable(total_cert, await tenant.subcontractor_packages.find_one({"id": pkg_id})),
        "remaining_contract_total": round(contract_total - total_cert, 2),
        "status": pkg_status, "updated_at": now,
    }})

    await tenant.subcontractor_acts.update_one({"id": act_id}, {"$set": {"status": "confirmed", "confirmed_at": now, "updated_at": now}})
    return await tenant.subcontractor_acts.find_one({"id": act_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — SUBCONTRACTOR PAYMENTS
# ═══════════════════════════════════════════════════════════════════

async def _get_next_pay_no(org_id):
    tenant = TenantData.for_resolved_org(db, org_id)
    last = await tenant.subcontractor_payments.find_one({"org_id": org_id}, {"_id": 0, "payment_no": 1}, sort=[("created_at", -1)])
    n = 1
    if last and last.get("payment_no"):
        try: n = int(last["payment_no"].split("-")[1]) + 1
        except Exception as e: logger.warning(f"subcontractors.py error: {e}")
    return f"SPAY-{n:04d}"


@router.post("/subcontractor-payments", status_code=201)
async def create_subcontractor_payment(
    data: dict,
    _sec01: dict = Depends(require_money_write(
        "finance.subcontractor_payment.create", module="M2",
        resource_type="subcontractor_payment")),  # SEC-01-C02 (R14, FG-27): before any read
    user: dict = Depends(require_m2),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """A real payment to a subcontractor (SEC-01-C02, FG-27).

    CLAUDE.md §2.5/§7: every real money movement is in the ONE payment ledger
    (FLOW-006). Until W0-05 builds the Payment Core, that ledger is ``finance_payments``
    (IMPLEMENTATION_WAVES.md W0-05: "един finance_payments write service"). So a payment
    is accepted ONLY when its cash/bank account resolves and the Outflow row is written
    to ``finance_payments``; otherwise 409 BEFORE any write — never a payment that
    exists only in ``subcontractor_payments``. ``subcontractor_payments`` stays the
    package's allocation record (the row points to its ledger row), not a second ledger.
    SEC-01-C03: ``amount`` must be a finite number > 0 and ``vat_amount`` finite >= 0
    (422 before any read or write); an ``Idempotency-Key`` replays the original payment
    instead of writing a second Outflow (``app/permissions/money_input.py``).
    Debt SEC-01-C02-D1 (remaining): not yet through a W0-05 write service, no Approval,
    no reversal API (W0-05 / R1 Payment).
    """
    amount = money_value(data.get("amount"))
    vat_raw = data.get("vat_amount")
    vat_amount = round(money_value(vat_raw, "vat_amount", allow_zero=True), 2) \
        if vat_raw is not None else 0.0  # input VAT (без ДДС amount stays in `amount`)
    # SUB-ADV-01 (R39): the advance is its own record (POST .../advances, Owner/Accountant);
    # an ordinary payment can never be booked as one.
    if data.get("payment_type") == ADVANCE_KIND:
        raise HTTPException(status_code=422, detail={
            "error_code": "ADVANCE_NOT_A_PAYMENT",
            "message": "Авансът се дава с отделния запис „Аванс към подизпълнител“"})
    # SUB-ADV-01 (FLOW-021, CLAUDE §7): the part of the act settled by an earlier advance is
    # deducted EXPLICITLY (``advance_deducted``), on a named act — never silently netted.
    ded_raw = data.get("advance_deducted")
    advance_deducted = round(money_value(ded_raw, "advance_deducted", allow_zero=True), 2) \
        if ded_raw is not None else 0.0
    if advance_deducted > 0 and data.get("act_id") is None:
        raise HTTPException(status_code=422, detail={
            "error_code": "ADVANCE_DEDUCTION_NEEDS_ACT",
            "message": "Авансът се приспада по конкретен потвърден акт (act_id)"})

    # CP-01 FG-481 / CP83-M3 (R29): order = role check (dependency) → pure body validation
    # (above, no read) → the idempotency replay → the state guards. A replay of a completed
    # key answers with the stored payment BEFORE any state check (an archived payee, a
    # changed IBAN never turns the original 201 into a refusal); the same key with a
    # different body → 409.
    replay = await MoneyWrite.completed_replay(user, "finance.subcontractor_payment.create",
                                               idempotency_key, data)
    if replay:
        # FG-511: the ORIGINAL response stored with the key; an older key → the row
        stored = MoneyWrite.stored_response(replay)
        if stored is None:
            stored = await _tenant(user).subcontractor_payments.find_one({"id": replay}, {"_id": 0})
        if stored:
            return stored

    tenant = _tenant(user)
    org_id = user["org_id"]
    pkg_id = data.get("package_id")
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    await project_in_tenant(tenant, pkg.get("project_id"))  # SEC-01-C03-B (FG-29)

    now = datetime.now(timezone.utc).isoformat()

    # Resolve cash/bank account for the outflow (default = first Cash account = Каса)
    req_account_id = data.get("account_id")
    if req_account_id:
        account = await tenant.financial_accounts.find_one({"id": req_account_id, "org_id": org_id})
        if not account:
            raise HTTPException(status_code=404, detail="Сметката не е намерена")
    else:
        account = await tenant.financial_accounts.find_one({"org_id": org_id, "account_type": "Cash"})
    if not account:
        # FG-27: no account -> no ledger row -> no payment (nothing is written).
        raise HTTPException(status_code=409, detail={
            "error_code": "PAYMENT_LEDGER_ACCOUNT_REQUIRED",
            "message": "Плащането трябва да мине през платежния регистър: изберете "
                       "сметка (Каса/Банка)"})
    account_id = account["id"]

    # SEC-01-C03-D (FG-90, FLOW-021 "плащане над измереното без Approval"): a named act must
    # be a CONFIRMED act of this package; the cap itself is reserved atomically below.
    act_id = data.get("act_id")
    act = None
    if act_id is not None:
        act = await _confirmed_act(tenant, act_id, pkg_id)

    # CP-01 §1 (FLOW-006 / FLOW-010 §8.1): executed only to a verified bank account of the
    # subcontractor; an inactive / archived subcontractor is not paid (422). Checked before the key is
    # reserved, so a refusal writes nothing (no row, no key).
    # FG-225 (b): the ACCOUNT decides the method — "cash" on a Bank account is a bank
    # transfer (IBAN check); only a real Cash account is cash (receipt, R50.1).
    await require_selectable_party(tenant, "subcontractor", pkg["subcontractor_id"])
    bank_stamp = await check_payment_target(
        tenant, user, direction="Outflow", method=data.get("payment_method", "bank"),
        account=account, party_type="subcontractor",
        party_id=pkg["subcontractor_id"], bank_account_id=data.get("bank_account_id"),
        cash_receipt_file_id=data.get("cash_receipt_file_id"),
        cash_recipient_name=data.get("cash_recipient_name"),
        path="/subcontractor-payments") or {}

    mw = await MoneyWrite.begin(user, "finance.subcontractor_payment.create", idempotency_key, data)
    if mw.replay_id:            # the same request again: the original payment, no new row
        stored = MoneyWrite.stored_response(mw.replay_id)          # FG-511
        return stored if stored is not None else \
            await tenant.subcontractor_payments.find_one({"id": mw.replay_id}, {"_id": 0})

    payment = {
        "id": mw.new_id("subcontractor_payment"), "org_id": org_id,
        "project_id": pkg["project_id"], "subcontractor_id": pkg["subcontractor_id"],
        **bank_stamp,
        "package_id": pkg_id, "act_id": data.get("act_id"),
        "payment_no": await _get_next_pay_no(org_id),
        "payment_date": data.get("payment_date", now[:10]),
        "amount": amount, "vat_amount": vat_amount, "currency": pkg.get("currency", "EUR"),
        "payment_type": data.get("payment_type", "partial"),
        # CP-01 FG-480 / FG-225: the account decides the method, as for the ledger row
        "payment_method": "cash" if is_cash_account(account) else "bank",
        "notes": data.get("notes", ""),
        "status": "completed",
        "kind": PAYMENT_KIND,
        "advance_deducted": advance_deducted,
        "account_id": account_id,
        "created_at": now,
    }

    # The ledger row first (FG-27): the cash outflow from the chosen account (Каса/Банка)
    # in finance_payments; the package's allocation record points to it.
    ledger_id = mw.new_id("finance_payment")
    payment["finance_payment_id"] = ledger_id
    async with mw:
        await _write_subcontractor_payment(mw, tenant, user, pkg, account, payment, ledger_id, now,
                                           act=act)
        mw.result_id = payment["id"]
        # F-69-01: the STORED allocation row — a concurrent retry of the same key that lost
        # the insert answers with the same payment (same payment_no) as the one that won it.
        # FG-511 (R29): that response is stored with the key; every replay returns it as is.
        mw.result_payload = await tenant.subcontractor_payments.find_one({"id": payment["id"]},
                                                                         {"_id": 0})
    return MoneyWrite.as_stored(mw.result_payload)


_COMMITTED = {"$ifNull": ["$committed_paid_total", {"$ifNull": ["$paid_total", 0]}]}
_RESERVED_IDS = {"$ifNull": ["$cap_reservations", []]}   # F-69-03 (#69)
_ADV_TOTAL = {"$ifNull": ["$advance_total", 0]}
_ADV_DEDUCTED = {"$ifNull": ["$advance_deducted_total", 0]}
# SUB-ADV-01-B (FG-103): two phases. A reservation is PENDING until the rows it stands for
# exist; only then is it confirmed into the counters above (each confirmation recognised by
# its durable, key-derived id, so a retry never confirms twice). A crash in between leaves a
# pending amount — it holds headroom (cap) but is never deductible, never cost, never paid.
_ADV_PENDING = {"$ifNull": ["$advance_pending_total", 0]}
_DED_PENDING = {"$ifNull": ["$advance_deduction_pending_total", 0]}
_ADV_CONFIRMED_IDS = {"$ifNull": ["$advance_confirmed", []]}
_DED_CONFIRMED_IDS = {"$ifNull": ["$advance_deduction_confirmed", []]}
# F-76-01: the money already taken on for the package, counted once:
#   advances given or reserved, not yet deducted  (advance_total + pending - deducted - deduction pending)
# + committed_paid_total                          (ordinary payments + every deduction, pending or not)
# A deduction moves an amount from the first term to the second: the sum does not change.
_TAKEN = {"$add": [{"$subtract": [{"$add": [_ADV_TOTAL, _ADV_PENDING]},
                                  {"$add": [_ADV_DEDUCTED, _DED_PENDING]}]}, _COMMITTED]}
_CONTRACT = {"$ifNull": ["$contract_total", 0]}


def _within_contract(extra) -> dict:
    """``_TAKEN + extra <= contract_total``; a package without a contract value has no
    advances (FG-114 refuses them) and keeps the certified cap only."""
    return {"$or": [{"$lte": [_CONTRACT, 0]},
                    {"$lte": [{"$add": [_TAKEN, extra]}, {"$add": [_CONTRACT, _CENT]}]}]}
_CENT = 0.005

# SUB-ADV-01 — kinds of rows in ``subcontractor_payments`` (the package's allocation record;
# the cash itself is ONE row in ``finance_payments``, FLOW-006). A row without ``kind`` is
# a legacy ordinary payment.
PAYMENT_KIND = "payment"
ADVANCE_KIND = "advance"
NOT_ADVANCE = {"kind": {"$ne": ADVANCE_KIND}}


def _payable(certified: float, pkg: Optional[dict]) -> float:
    """What is still owed on the package: certified - paid - advance deducted (>= 0)."""
    pkg = pkg or {}
    return max(0.0, round(float(certified or 0) - float(pkg.get("paid_total") or 0)
                          - float(pkg.get("advance_deducted_total") or 0), 2))


async def _confirmed_act(tenant, act_id: str, pkg_id: str) -> dict:
    act = await tenant.subcontractor_acts.find_one(
        {"id": act_id, "package_id": pkg_id},
        {"_id": 0, "id": 1, "status": 1, "certified_total": 1, "act_no": 1, "package_id": 1})
    if not act:
        raise HTTPException(status_code=404, detail="Act not found in this package")
    if act.get("status") != "confirmed":
        raise HTTPException(status_code=409, detail={
            "error_code": "PAYMENT_ACT_NOT_CONFIRMED",
            "message": "Плаща се само по потвърден акт"})
    return act


async def _reserve_within_certified(tenant, pkg_id: str, amount: float, reservation_id: str,
                                    deducted: float = 0.0, act: Optional[dict] = None) -> None:
    """One atomic, conditional update of the package (R40: the cap is per package).

    ``committed_paid_total`` = ordinary payments + advance deducted on acts. It grows by
    ``amount + deducted`` only if ALL hold, in the same update (two requests under different
    keys can never both pass):

      * committed + amount + deducted <= certified_total   (FG-90, PAYMENT_EXCEEDS_CERTIFIED)
      * deducted <= advance_total (confirmed) - deducted - deductions pending
                                                         (ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING)
      * deducted + pending on this act + deducted <= the act's certified total
                                                         (ADVANCE_DEDUCTION_EXCEEDS_ACT)
      * F-76-01: outstanding advance (incl. pending) + committed + amount <= contract_total
                                                         (PAYMENT_EXCEEDS_PACKAGE_VALUE)

    FG-103: the deduction is reserved as PENDING (``advance_deduction_pending_total`` and
    ``advance_deduction_pending_by_act``); ``_confirm_deduction`` moves it into
    ``advance_deducted_total`` once it is written on the act. Only a CONFIRMED advance can be
    deducted (``advance_total``; a pending advance never).

    The advance itself never enters ``committed_paid_total``: it is not a payment for a
    measured quantity (R39) and is not an overpayment under FG-90.

    SEC-01-C03 addendum C (Codex F-69-03, #69): the reservation carries ``reservation_id``
    (``cap_reservations``); a retry of the same key that finds its id changes nothing."""
    already = {"$in": [reservation_id, _RESERVED_IDS]}

    def once(field_expr, new_value):        # unchanged when this id is already reserved
        return {"$cond": [already, field_expr, new_value]}
    conds = [{"$lte": [{"$add": [_COMMITTED, amount + deducted]},
                       {"$add": [{"$ifNull": ["$certified_total", 0]}, _CENT]}]},
             # F-76-01: the contract headroom holds for an ordinary payment too (the deducted
             # part only moves from the outstanding advance into committed).
             _within_contract(amount)]
    sets = {"committed_paid_total": once(_COMMITTED, {"$round": [
                {"$add": [_COMMITTED, amount + deducted]}, 2]}),
            "cap_reservations": once(_RESERVED_IDS, {"$concatArrays": [_RESERVED_IDS,
                                                                       [reservation_id]]})}
    if deducted > 0:
        by_act = {"$ifNull": ["$advance_deducted_by_act.%s" % act["id"], 0]}
        ppath = "advance_deduction_pending_by_act.%s" % act["id"]
        pend_act = {"$ifNull": ["$" + ppath, 0]}
        conds.append({"$lte": [deducted, {"$add": [{"$subtract": [
            {"$subtract": [_ADV_TOTAL, _ADV_DEDUCTED]}, _DED_PENDING]}, _CENT]}]})
        conds.append({"$lte": [{"$add": [by_act, pend_act, deducted]},
                               float(act.get("certified_total") or 0) + _CENT]})
        sets["advance_deduction_pending_total"] = once(_DED_PENDING, {"$round": [
            {"$add": [_DED_PENDING, deducted]}, 2]})
        sets[ppath] = once(pend_act, {"$round": [{"$add": [pend_act, deducted]}, 2]})
    res = await tenant.subcontractor_packages.update_one(
        {"id": pkg_id, "$or": [{"cap_reservations": reservation_id},
                               {"$expr": {"$and": conds}}]}, [{"$set": sets}])
    if res.matched_count:
        return
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id}, {"_id": 0}) or {}
    if deducted > 0:
        outstanding = (float(pkg.get("advance_total") or 0)
                       - float(pkg.get("advance_deducted_total") or 0)
                       - float(pkg.get("advance_deduction_pending_total") or 0))
        if deducted > outstanding + _CENT:
            raise HTTPException(status_code=409, detail={
                "error_code": "ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING",
                "message": "Приспаднатият аванс надвишава неприспаднатия остатък на аванса "
                           "(остатък %.2f)" % max(0.0, outstanding)})
        done = float((pkg.get("advance_deducted_by_act") or {}).get(act["id"]) or 0) \
            + float((pkg.get("advance_deduction_pending_by_act") or {}).get(act["id"]) or 0)
        if done + deducted > float(act.get("certified_total") or 0) + _CENT:
            raise HTTPException(status_code=409, detail={
                "error_code": "ADVANCE_DEDUCTION_EXCEEDS_ACT",
                "message": "Приспаднатият аванс надвишава удостовереното по акта"})
    taken = (float(pkg.get("advance_total") or 0) + float(pkg.get("advance_pending_total") or 0)
             - float(pkg.get("advance_deducted_total") or 0)
             - float(pkg.get("advance_deduction_pending_total") or 0)
             + float(pkg.get("committed_paid_total") or pkg.get("paid_total") or 0))
    contract = float(pkg.get("contract_total") or 0)
    committed = float(pkg.get("committed_paid_total") or pkg.get("paid_total") or 0)
    over_certified = committed + amount + deducted > float(pkg.get("certified_total") or 0) + _CENT
    if contract > 0 and taken + amount > contract + _CENT and not over_certified:
        raise HTTPException(status_code=409, detail={
            "error_code": "PAYMENT_EXCEEDS_PACKAGE_VALUE",
            "message": "Плащането заедно с неприспаднатия аванс надвишава договорната стойност "
                       "на пакета; приспаднете аванса изрично по акта"})
    raise HTTPException(status_code=409, detail={
        "error_code": "PAYMENT_EXCEEDS_CERTIFIED",
        "message": "Плащането надвишава актуваното (сертифицираното) по пакета; "
                   "над измереното се плаща само с одобрение (FLOW-021)"})


async def _confirm_deduction(tenant, pkg_id: str, act_id: str, deducted: float,
                             deduction_id: str) -> None:
    """FG-103 phase 2: the deduction is on the act -> move it from pending into
    ``advance_deducted_total`` / ``advance_deducted_by_act``. One conditional update keyed by
    the deduction's durable id (``advance_deduction_confirmed``): never twice."""
    path = "advance_deducted_by_act.%s" % act_id
    ppath = "advance_deduction_pending_by_act.%s" % act_id
    await tenant.subcontractor_packages.update_one(
        {"id": pkg_id, "advance_deduction_confirmed": {"$ne": deduction_id}},
        [{"$set": {
            "advance_deduction_pending_total": {"$round": [
                {"$max": [0, {"$subtract": [_DED_PENDING, deducted]}]}, 2]},
            ppath: {"$round": [{"$max": [0, {"$subtract": [
                {"$ifNull": ["$" + ppath, 0]}, deducted]}]}, 2]},
            "advance_deducted_total": {"$round": [{"$add": [_ADV_DEDUCTED, deducted]}, 2]},
            path: {"$round": [{"$add": [{"$ifNull": ["$" + path, 0]}, deducted]}, 2]},
            "advance_deduction_confirmed": {"$concatArrays": [_DED_CONFIRMED_IDS,
                                                              [deduction_id]]},
        }}])


async def _confirm_advance(tenant, pkg_id: str, amount: float, advance_id: str) -> None:
    """FG-103 phase 2: the ledger row, the advance row and the AuditEvent exist -> the advance
    becomes deductible (pending -> ``advance_total``). Keyed by the advance's durable id
    (``advance_confirmed``): never twice."""
    await tenant.subcontractor_packages.update_one(
        {"id": pkg_id, "advance_confirmed": {"$ne": advance_id}},
        [{"$set": {
            "advance_pending_total": {"$round": [
                {"$max": [0, {"$subtract": [_ADV_PENDING, amount]}]}, 2]},
            "advance_total": {"$round": [{"$add": [_ADV_TOTAL, amount]}, 2]},
            "advance_confirmed": {"$concatArrays": [_ADV_CONFIRMED_IDS, [advance_id]]},
        }}])


async def _refresh_package_totals(tenant, pkg_id: str, now: str) -> None:
    """The package's visible totals (SUB-ADV-01 §4) from its rows and its counters.

    paid_total        ordinary payments (cash), advances excluded;
    advance_total     advances given (cash) — counter, CONFIRMED advances only (FG-103);
    advance_deducted_total  advance deducted on acts — counter, CONFIRMED deductions only;
    advance_pending_total / advance_deduction_pending_total  reserved, not yet confirmed
                      (an interrupted request; its retry with the same key confirms it);
    advance_outstanding     advance_total - advance_deducted_total;
    payable_total     certified - paid - advance deducted (>= 0);
    cash_out_total    the whole cash flow to the package: advances + ordinary payments
                      (= аванс + плащания по актове бруто − приспаднато)."""
    # FG-105 (#69): summed in the database — every payment of the package is counted.
    agg = await tenant.subcontractor_payments.aggregate([
        {"$match": {"package_id": pkg_id, "status": "completed", **NOT_ADVANCE}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    paid = round(float(agg[0]["total"]) if agg else 0.0, 2)
    await tenant.subcontractor_packages.update_one({"id": pkg_id}, [{"$set": {
        "paid_total": paid,
        "advance_total": {"$round": [_ADV_TOTAL, 2]},
        "advance_deducted_total": {"$round": [_ADV_DEDUCTED, 2]},
        "advance_pending_total": {"$round": [_ADV_PENDING, 2]},
        "advance_deduction_pending_total": {"$round": [_DED_PENDING, 2]},
        "advance_outstanding": {"$round": [{"$subtract": [_ADV_TOTAL, _ADV_DEDUCTED]}, 2]},
        "payable_total": {"$max": [0, {"$round": [{"$subtract": [
            {"$subtract": [{"$ifNull": ["$certified_total", 0]}, paid]}, _ADV_DEDUCTED]}, 2]}]},
        "cash_out_total": {"$round": [{"$add": [_ADV_TOTAL, paid]}, 2]},
        "updated_at": now,
    }}])


async def _record_act_deduction(mw, tenant, user, act: dict, deducted: float,
                                payment_id: Optional[str], now: str, reason: str = "", *,
                                reservation_id: str) -> None:
    """The deduction, visible ON the act (``advance_deducted`` + one entry in
    ``advance_deductions``) and as an AuditEvent; each done once per Idempotency-Key."""
    entry = {"id": mw.new_id("advance_deduction"), "amount": deducted,
             "subcontractor_payment_id": payment_id, "reason": reason,
             "by_user_id": user["id"], "at": now}
    # FG-103: conditional on the entry's durable id — a retry after a crash between this
    # update and its step bookkeeping never adds the deduction to the act twice.
    await mw.step("act_deduction", lambda: tenant.subcontractor_acts.update_one(
        {"id": act["id"], "advance_deductions.id": {"$ne": entry["id"]}},
        {"$inc": {"advance_deducted": deducted}, "$push": {"advance_deductions": entry},
         "$set": {"updated_at": now}}))
    await mw.step("audit_deduction", lambda: log_audit(
        user["org_id"], user["id"], user.get("email", ""), "subcontractor_advance_deducted",
        "subcontractor_act", act["id"], {"amount": deducted, "deduction_id": entry["id"],
                                         "subcontractor_payment_id": payment_id,
                                         "reason": reason},
        entry_id=mw.new_id("audit_advance_deduction")))      # F-76-02: exactly one row
    await mw.step("confirm_deduction", lambda: _confirm_deduction(
        tenant, act["package_id"], act["id"], deducted, reservation_id))


async def _write_subcontractor_payment(mw, tenant, user, pkg, account, payment, ledger_id, now,
                                       act: Optional[dict] = None):
    """The writes of one subcontractor payment; each one done once per Idempotency-Key."""
    org_id, pkg_id, amount = user["org_id"], payment["package_id"], payment["amount"]
    deducted = float(payment.get("advance_deducted") or 0)
    account_id = account["id"]
    # SEC-01-C03-D (FG-90): the FIRST write reserves the amount against the package's
    # certified total, atomically (one conditional update: two payments under different keys
    # cannot both pass). Over the cap -> 409, nothing written. FLOW-021 allows more only with
    # an Approval (W0-07), which does not exist yet -> refused. Done once per key.
    # SUB-ADV-01: the advance deducted on the act is reserved in the SAME update; F-69-03: the
    # reservation carries the payment's key-derived id (a retry never reserves twice).
    await mw.step("reserve", lambda: _reserve_within_certified(tenant, pkg_id, amount,
                                                               payment["id"], deducted, act))
    async with mw.insert_once():   # SEC-01-C03-C (F-69-01): atomic, _id = key-derived id
        await tenant.finance_payments.insert_one(mw.unique({
            "id": ledger_id, "org_id": org_id,
            "direction": "Outflow", "amount": amount,
            "currency": pkg.get("currency", "EUR"),
            "date": payment["payment_date"],
            "method": account.get("account_type", "Cash"),
            "account_id": account_id,
            "counterparty_name": pkg.get("subcontractor_name") or "Подизпълнител",
            "reference": payment["payment_no"],
            "note": "Подизпълнител/бригада плащане",
            "project_id": pkg["project_id"],
            "subcontractor_payment_id": payment["id"],
            **{k: payment[k] for k in ("bank_account_id", "bank_account_iban_masked",
                                       "cash_receipt_file_id", "cash_recipient_name") if k in payment},
            "created_at": now, "updated_at": now,
        }))
    async with mw.insert_once():
        await tenant.subcontractor_payments.insert_one(mw.unique(payment))
    await mw.step("audit", lambda: log_audit(
        org_id, user["id"], user.get("email", ""), "subcontractor_payment_created",
        "payment", ledger_id, {"amount": amount, "package_id": pkg_id,
                               "subcontractor_payment_id": payment["id"],
                               "account_id": account_id,
                               "advance_deducted": deducted},
        entry_id=mw.new_id("audit_payment")))      # F-76-02: exactly one row (as #69)
    if deducted > 0:
        await _record_act_deduction(mw, tenant, user, act, deducted, payment["id"], now,
                                    reservation_id=payment["id"])

    # Package totals (SUB-ADV-01: advances are not counted in paid_total)
    await _refresh_package_totals(tenant, pkg_id, now)


@router.get("/subcontractor-payments")
async def list_subcontractor_payments(
    request: Request = None,                    # SUB-ADV-01 (FG-128); None = direct call
    _sec02: dict = Depends(require_finance_read(
        "finance.subcontractor_payment.read", module="M2", resource_type="subcontractor_payment")),  # SEC-02 (R20-1): before any read
    project_id: Optional[str] = None, package_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if package_id: q["package_id"] = package_id
    if not await advance_visible(request, user):          # FG-128: no advance rows
        q.update(NOT_ADVANCE)
        rows = await tenant.subcontractor_payments.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
        return [_strip(r, {"advance_deducted"}) for r in rows]
    return await tenant.subcontractor_payments.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


# ═══════════════════════════════════════════════════════════════════
# SUB-ADV-01 — ADVANCE TO A SUBCONTRACTOR, DEDUCTED EXPLICITLY ON ACTS
# ═══════════════════════════════════════════════════════════════════
# R39 (Krum 07.11.2026): an advance is its own record, through the ONE payment ledger
# (FLOW-006), deducted from the following acts, its remainder tracked; only Owner or
# Accountant give it. R40: the payment cap is per package. FLOW-021 forbids "аванс без
# прихващане/остатък"; CLAUDE §7 forbids automatic netting — the deduction is an explicit
# action on an act (``advance_deducted`` on a payment, or the deduction endpoint below).

ADVANCE_ROLES = ("Owner", "Accountant")          # R39 — legacy role strings (off/shadow)
_REASON_MAX = 500
_FORBIDDEN_CHARS = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u061c",
                    "\u200e", "\u200f", *[chr(c) for c in range(0x202a, 0x202f)],
                    *[chr(c) for c in range(0x2066, 0x206a)]}


def _reason(value, field: str = "reason", required: bool = True) -> str:
    """A short human reason: text, at most 500 characters, no control/bidi/zero-width
    characters (the PAY-01 rule for reasons); else 422 before any write."""
    if value is None and not required:
        return ""
    text = value.strip() if isinstance(value, str) else None
    bad = (text is None or (required and not text) or len(text) > _REASON_MAX
           or any((ord(ch) < 32 and ch not in "\t") or ord(ch) == 127 or ch in _FORBIDDEN_CHARS
                  for ch in text))
    if bad:
        raise HTTPException(status_code=422, detail={
            "error_code": "REASON_INVALID",
            "message": "Причината е задължителна: текст до %d знака без контролни знаци"
                       % _REASON_MAX})
    return text


_ADV_RESERVED_IDS = {"$ifNull": ["$advance_reservations", []]}


async def _reserve_advance(tenant, pkg_id: str, amount: float, advance_id: str) -> None:
    """FG-114: add ``amount`` to ``advance_total`` only if, in the same update,

        (advance_total - advance_deducted_total)   advance not yet deducted
      + advance_pending_total                      advances reserved, not yet confirmed
      + committed_paid_total                       ordinary payments + advance deducted
      + amount                                     <= contract_total (cent tolerance).

    The deducted part of the advance is counted once (inside committed), so the left side is
    the whole money already taken on for the package. The reservation carries the advance's
    key-derived id (``advance_reservations``, as F-69-03): a retry of the same key that finds
    it changes nothing. Over the cap -> 409 ADVANCE_EXCEEDS_PACKAGE_VALUE, nothing written."""
    already = {"$in": [advance_id, _ADV_RESERVED_IDS]}
    taken = {"$add": [_TAKEN, amount]}        # F-76-01: the same headroom as the payments
    res = await tenant.subcontractor_packages.update_one(
        {"id": pkg_id, "$or": [
            {"advance_reservations": advance_id},
            {"$expr": {"$lte": [taken, {"$add": [{"$ifNull": ["$contract_total", 0]}, _CENT]}]}}]},
        [{"$set": {
            # FG-103: PENDING until the rows exist (``_confirm_advance``)
            "advance_pending_total": {"$cond": [already, _ADV_PENDING,
                                                {"$round": [{"$add": [_ADV_PENDING, amount]}, 2]}]},
            "advance_reservations": {"$cond": [already, _ADV_RESERVED_IDS, {"$concatArrays": [
                _ADV_RESERVED_IDS, [advance_id]]}]},
        }}])
    if res.matched_count == 0:
        raise HTTPException(status_code=409, detail={
            "error_code": "ADVANCE_EXCEEDS_PACKAGE_VALUE",
            "message": "Авансът заедно с поетите задължения по пакета надвишава договорната "
                       "стойност на пакета"})


@router.post("/subcontractor-packages/{pkg_id}/advances", status_code=201)
async def create_subcontractor_advance(
    pkg_id: str,
    data: dict,
    _adv: dict = Depends(require_money_write(
        "finance.subcontractor_advance.create", module="M2",
        resource_type="subcontractor_advance", roles=ADVANCE_ROLES)),  # R39: before any read
    user: dict = Depends(require_m2),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """An advance to the subcontractor of a package (SUB-ADV-01, R39).

    Body: ``amount`` (finite > 0), ``reason`` (required), ``advance_date``, ``account_id``
    (default: the first Cash account), ``notes``. The cash is ONE Outflow row in
    ``finance_payments`` (FLOW-006); the package's record is a ``subcontractor_payments`` row
    with ``kind = "advance"`` that points to it (``finance_payment_id``) and the ledger row
    points back (``subcontractor_payment_id``) — so a finance reversal of it is refused with
    409 SOURCE_MODULE_REVERSAL_REQUIRED (FG-45, PR #70) until the module reverses it.
    FG-114: the advance is first reserved against the package's contract value (atomic,
    ``_reserve_advance``); a package without a contract value -> 422. The advance is not
    an ordinary payment: it is not capped by the certified total (FG-90) and does not enter
    ``committed_paid_total``; it is deducted later, explicitly, on acts.
    Idempotency-Key required (R29); AuditEvent ``subcontractor_advance_created``.
    """
    amount = round(money_value(data.get("amount")), 2)
    reason = _reason(data.get("reason"))
    # CP-01 FG-481 / CP83-M3 (R29): role check → pure validation (above) → the replay → the
    # state guards. A completed key → the stored advance; the same key with another body → 409.
    replay = await MoneyWrite.completed_replay(user, "finance.subcontractor_advance.create",
                                               idempotency_key, {**data, "package_id": pkg_id})
    if replay:
        # FG-511: the ORIGINAL response stored with the key; an older key → the row
        stored = MoneyWrite.stored_response(replay)
        if stored is None:
            stored = await _tenant(user).subcontractor_payments.find_one({"id": replay}, {"_id": 0})
        if stored:
            return stored
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    await project_in_tenant(tenant, pkg.get("project_id"))
    if pkg.get("status") in ("draft", "closed"):
        raise HTTPException(status_code=409, detail={
            "error_code": "ADVANCE_PACKAGE_NOT_ACTIVE",
            "message": "Аванс се дава само по потвърден, незатворен пакет"})
    contract_total = pkg.get("contract_total")
    if not isinstance(contract_total, (int, float)) or isinstance(contract_total, bool) \
            or not contract_total > 0:
        # FG-114: an advance is tied to a contract/scope (FLOW-006); with no contract value
        # there is nothing to deduct it from (FLOW-021) -> refused before any write.
        raise HTTPException(status_code=422, detail={
            "error_code": "ADVANCE_PACKAGE_VALUE_REQUIRED",
            "message": "Пакетът няма договорна стойност — авансът няма към какво да се прихване"})
    req_account_id = data.get("account_id")
    if req_account_id:
        account = await tenant.financial_accounts.find_one({"id": req_account_id, "org_id": org_id})
        if not account:
            raise HTTPException(status_code=404, detail="Сметката не е намерена")
    else:
        account = await tenant.financial_accounts.find_one({"org_id": org_id, "account_type": "Cash"})
    if not account:
        raise HTTPException(status_code=409, detail={
            "error_code": "PAYMENT_LEDGER_ACCOUNT_REQUIRED",
            "message": "Авансът трябва да мине през платежния регистър: изберете "
                       "сметка (Каса/Банка)"})

    # CP-01 FG-427 (R71): an advance is a payment to the subcontractor — the SAME guards as
    # every payment, before the key is reserved (a refusal writes nothing): an inactive /
    # archived subcontractor → 422; the account decides cash vs bank (FG-225); bank only to
    # a VERIFIED account; cash only with a registered receipt + recipient (R59), and blocked
    # while the subcontractor has an unverified IBAN (R50.1).
    await require_selectable_party(tenant, "subcontractor", pkg["subcontractor_id"])
    bank_stamp = await check_payment_target(
        tenant, user, direction="Outflow", method=data.get("payment_method", "bank"),
        account=account, party_type="subcontractor",
        party_id=pkg["subcontractor_id"], bank_account_id=data.get("bank_account_id"),
        cash_receipt_file_id=data.get("cash_receipt_file_id"),
        cash_recipient_name=data.get("cash_recipient_name"),
        path="/subcontractor-packages/{id}/advances") or {}

    mw = await MoneyWrite.begin(user, "finance.subcontractor_advance.create", idempotency_key,
                                {**data, "package_id": pkg_id})
    if mw.replay_id:
        stored = MoneyWrite.stored_response(mw.replay_id)          # FG-511
        return stored if stored is not None else \
            await tenant.subcontractor_payments.find_one({"id": mw.replay_id}, {"_id": 0})

    now = datetime.now(timezone.utc).isoformat()
    advance = {
        "id": mw.new_id("subcontractor_advance"), "org_id": org_id,
        "project_id": pkg["project_id"], "subcontractor_id": pkg["subcontractor_id"],
        "package_id": pkg_id, "act_id": None,
        "kind": ADVANCE_KIND, "payment_type": ADVANCE_KIND,
        "payment_no": await _get_next_pay_no(org_id),
        "payment_date": data.get("advance_date") or now[:10],
        "amount": amount, "vat_amount": 0.0, "currency": pkg.get("currency", "EUR"),
        # CP-01 FG-480: the ACCOUNT decides the method (FG-225), as for the ledger row —
        # never the request's word
        "payment_method": "cash" if is_cash_account(account) else "bank",
        "reason": reason, "notes": data.get("notes", ""),
        "status": "completed", "account_id": account["id"],
        "created_by": user["id"], "created_at": now,
        **bank_stamp,                                         # CP-01 FG-427
    }
    ledger_id = mw.new_id("finance_payment")
    advance["finance_payment_id"] = ledger_id
    async with mw:
        # FG-114: the FIRST write reserves the advance against the package's contract value,
        # atomically (one conditional update; concurrent advances under different keys can
        # never together pass the cap). Over it -> 409, nothing written.
        await mw.step("advance_reserve", lambda: _reserve_advance(tenant, pkg_id, amount,
                                                                  advance["id"]))
        async with mw.insert_once():
            await tenant.finance_payments.insert_one(mw.unique({
                "id": ledger_id, "org_id": org_id,
                "direction": "Outflow", "amount": amount,
                "currency": pkg.get("currency", "EUR"),
                "date": advance["payment_date"],
                "method": account.get("account_type", "Cash"),
                "account_id": account["id"],
                "counterparty_name": pkg.get("subcontractor_name") or "Подизпълнител",
                "reference": advance["payment_no"],
                "note": "Аванс към подизпълнител: %s" % reason,
                "project_id": pkg["project_id"],
                "subcontractor_payment_id": advance["id"],   # FG-45 origin (PR #70)
                "subcontractor_advance": True,
                **bank_stamp,                                 # CP-01 FG-427: the proof
                "created_at": now, "updated_at": now,
            }))
        async with mw.insert_once():
            await tenant.subcontractor_payments.insert_one(mw.unique(advance))
        await mw.step("audit", lambda: log_audit(
            org_id, user["id"], user.get("email", ""), "subcontractor_advance_created",
            "payment", ledger_id, {"amount": amount, "package_id": pkg_id, "reason": reason,
                                   "subcontractor_payment_id": advance["id"],
                                   "account_id": account["id"]},
            entry_id=mw.new_id("audit_advance_created")))       # F-76-02: exactly one row
        # FG-103: only now — ledger row, advance row and AuditEvent exist — is it deductible
        await mw.step("advance_confirm", lambda: _confirm_advance(tenant, pkg_id, amount,
                                                                  advance["id"]))
        await _refresh_package_totals(tenant, pkg_id, now)
        mw.result_id = advance["id"]
        # FG-511 (R29): the response is stored with the key; every replay returns it as is
        mw.result_payload = await tenant.subcontractor_payments.find_one({"id": advance["id"]},
                                                                         {"_id": 0})
    return MoneyWrite.as_stored(mw.result_payload)


@router.post("/subcontractor-acts/{act_id}/advance-deduction", status_code=201)
async def deduct_advance_on_act(
    act_id: str,
    data: dict,
    _ded: dict = Depends(require_money_write(
        "subcontract.advance_deduction.execute", module="M2",
        resource_type="subcontractor_act")),     # Owner/Admin/Accountant: before any read
    user: dict = Depends(require_m2),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Deduct advance on a confirmed act WITHOUT a cash payment (SUB-ADV-01 §2) — e.g. an
    act fully covered by the advance. Body: ``amount`` (finite > 0), ``reason`` (optional).
    The same atomic package reservation as a payment with ``advance_deducted`` (the deducted
    part settles the act and counts against the certified total, R40); written on the act
    and as an AuditEvent. No ledger row: no money moves. Idempotency-Key required (R29)."""
    amount = round(money_value(data.get("amount")), 2)
    reason = _reason(data.get("reason"), required=False)
    # CP-01 FG-499 (R29, CP83-M3 order): role check → pure validation (above) → the replay →
    # the state guards (act confirmed, package). A completed key → the stored act; the same
    # key with another body → 409.
    replay = await MoneyWrite.completed_replay(user, "subcontract.advance_deduction.execute",
                                               idempotency_key, {**data, "act_id": act_id})
    if replay:
        # FG-511: the ORIGINAL response stored with the key; an older key → the row
        stored = MoneyWrite.stored_response(replay)
        if stored is None:
            stored = await _tenant(user).subcontractor_acts.find_one({"id": replay}, {"_id": 0})
        if stored:
            return stored
    tenant = _tenant(user)
    act_row = await tenant.subcontractor_acts.find_one({"id": act_id, "org_id": user["org_id"]},
                                                       {"_id": 0, "package_id": 1})
    if not act_row:
        raise HTTPException(status_code=404, detail="Act not found")
    pkg_id = act_row["package_id"]
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]},
                                                       {"_id": 0, "project_id": 1})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    await project_in_tenant(tenant, pkg.get("project_id"))
    act = await _confirmed_act(tenant, act_id, pkg_id)

    mw = await MoneyWrite.begin(user, "subcontract.advance_deduction.execute", idempotency_key,
                                {**data, "act_id": act_id})
    if mw.replay_id:
        stored = MoneyWrite.stored_response(mw.replay_id)          # FG-511
        return stored if stored is not None else \
            await tenant.subcontractor_acts.find_one({"id": mw.replay_id}, {"_id": 0})
    now = datetime.now(timezone.utc).isoformat()
    async with mw:
        reservation_id = mw.new_id("advance_deduction_reservation")
        await mw.step("reserve", lambda: _reserve_within_certified(
            tenant, pkg_id, 0.0, reservation_id, amount, act))
        await _record_act_deduction(mw, tenant, user, act, amount, None, now, reason,
                                    reservation_id=reservation_id)
        await _refresh_package_totals(tenant, pkg_id, now)
        mw.result_id = act_id
        # FG-511 (R29): the response is stored with the key; every replay returns it as is
        mw.result_payload = await tenant.subcontractor_acts.find_one({"id": act_id}, {"_id": 0})
    return MoneyWrite.as_stored(mw.result_payload)


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROFIT INTEGRATION HELPER
# ═══════════════════════════════════════════════════════════════════

async def get_advance_metrics(org_id: str, project_id: str) -> dict:
    """SUB-ADV-01-B (FG-128): given / deducted / remaining advance over the project's packages
    — a cash/settlement view, NOT a P&L line (FLOW-006). Callers show it to finance roles only."""
    tenant = TenantData.for_resolved_org(db, org_id)
    pkgs = await tenant.subcontractor_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "advance_total": 1, "advance_deducted_total": 1,
         "advance_pending_total": 1}).to_list(1000)
    sums = [advance_summary(p) for p in pkgs]
    return {k: round(sum(x[k] for x in sums), 2)
            for k in ("given", "deducted", "outstanding", "pending")}


async def get_subcontract_metrics(org_id: str, project_id: str) -> dict:
    """Get aggregated subcontract metrics for a project"""
    tenant = TenantData.for_resolved_org(db, org_id)
    pkgs = await tenant.subcontractor_packages.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$ne": "draft"}},
        {"_id": 0, "contract_total": 1, "certified_total": 1, "paid_total": 1, "payable_total": 1, "remaining_contract_total": 1}
    ).to_list(100)

    if not pkgs:
        return {"available": False}

    return {
        "available": True,
        "committed": round(sum(p.get("contract_total", 0) for p in pkgs), 2),
        "certified": round(sum(p.get("certified_total", 0) for p in pkgs), 2),
        "paid": round(sum(p.get("paid_total", 0) for p in pkgs), 2),
        "payable": round(sum(p.get("payable_total", 0) for p in pkgs), 2),
        "remaining_contract": round(sum(p.get("remaining_contract_total", 0) for p in pkgs), 2),
        "packages_count": len(pkgs),
    }
