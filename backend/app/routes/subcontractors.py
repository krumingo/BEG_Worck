"""
Routes - Subcontractor Financial Flow.
Phase 1: Subcontractors + Packages
Phase 2: Package Lines from Offer/Execution
Phase 3: Subcontractor Acts (Certified Expense)
Phase 4: Subcontractor Payments
Phase 5: Profit Integration (extends revenue_expense)
"""
from fastapi import APIRouter, Body, Depends, Header, HTTPException
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
from app.services.bank_account_guard import check_payment_target, require_selectable_party
from app.permissions.money_write import require_money_write, require_finance_read, strip_money_for_non_finance
from app.permissions.money_input import MoneyWrite, money_value, project_in_tenant  # SEC-01-C03

router = APIRouter(tags=["Subcontractors"])


def _tenant(user: dict) -> TenantData:
    """W0-03E-A1: the session user's tenant view of the legacy database."""
    return TenantData.for_user(db, user)


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
async def list_packages(project_id: Optional[str] = None, subcontractor_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if subcontractor_id: q["subcontractor_id"] = subcontractor_id
    pkgs = await tenant.subcontractor_packages.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return pkgs


@router.get("/subcontractor-packages/{pkg_id}")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def get_package(pkg_id: str, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    pkg = await tenant.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    lines = await tenant.subcontractor_package_lines.find({"package_id": pkg_id}, {"_id": 0}).sort("sort_order", 1).to_list(200)
    pkg["lines"] = lines
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
    _sec02: dict = Depends(require_finance_read(
        "finance.subcontractor_act.read", module="M2", resource_type="subcontractor_act")),  # SEC-02 (R20-1): before any read
    project_id: Optional[str] = None, package_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if package_id: q["package_id"] = package_id
    return await tenant.subcontractor_acts.find(q, {"_id": 0}).sort("created_at", -1).to_list(100)


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
        "payable_total": round(total_cert - (await tenant.subcontractor_packages.find_one({"id": pkg_id})).get("paid_total", 0), 2),
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
    if act_id is not None:
        act = await tenant.subcontractor_acts.find_one({"id": act_id, "package_id": pkg_id},
                                                       {"_id": 0, "id": 1, "status": 1})
        if not act:
            raise HTTPException(status_code=404, detail="Act not found in this package")
        if act.get("status") != "confirmed":
            raise HTTPException(status_code=409, detail={
                "error_code": "PAYMENT_ACT_NOT_CONFIRMED",
                "message": "Плаща се само по потвърден акт"})

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
        return await tenant.subcontractor_payments.find_one({"id": mw.replay_id}, {"_id": 0})

    payment = {
        "id": mw.new_id("subcontractor_payment"), "org_id": org_id,
        "project_id": pkg["project_id"], "subcontractor_id": pkg["subcontractor_id"],
        **bank_stamp,
        "package_id": pkg_id, "act_id": data.get("act_id"),
        "payment_no": await _get_next_pay_no(org_id),
        "payment_date": data.get("payment_date", now[:10]),
        "amount": amount, "vat_amount": vat_amount, "currency": pkg.get("currency", "EUR"),
        "payment_type": data.get("payment_type", "partial"),
        "payment_method": data.get("payment_method", "bank"),
        "notes": data.get("notes", ""),
        "status": "completed",
        "account_id": account_id,
        "created_at": now,
    }

    # The ledger row first (FG-27): the cash outflow from the chosen account (Каса/Банка)
    # in finance_payments; the package's allocation record points to it.
    ledger_id = mw.new_id("finance_payment")
    payment["finance_payment_id"] = ledger_id
    async with mw:
        await _write_subcontractor_payment(mw, tenant, user, pkg, account, payment, ledger_id, now)
        mw.result_id = payment["id"]
    # F-69-01: the STORED allocation row — a concurrent retry of the same key that lost the
    # insert answers with the same payment (same payment_no) as the one that won it.
    return await tenant.subcontractor_payments.find_one({"id": payment["id"]}, {"_id": 0})


_COMMITTED = {"$ifNull": ["$committed_paid_total", {"$ifNull": ["$paid_total", 0]}]}
_RESERVED_IDS = {"$ifNull": ["$cap_reservations", []]}


async def _reserve_within_certified(tenant, pkg_id: str, amount: float, reservation_id: str) -> None:
    """Reserve ``amount`` of the package's ``certified_total`` for ONE payment, atomically.

    SEC-01-C03 addendum C (Codex F-69-03): the reservation carries the payment's key-derived
    id (``cap_reservations``). A retry of the same key after a crash between this update and
    the step bookkeeping finds its own id and changes nothing — it never reserves twice and is
    never refused by its own earlier reservation. One conditional update on one document: it
    matches when the id is already reserved, or when ``committed + amount <= certified``
    (cent tolerance). Otherwise 409 PAYMENT_EXCEEDS_CERTIFIED, nothing written."""
    already = {"$in": [reservation_id, _RESERVED_IDS]}
    res = await tenant.subcontractor_packages.update_one(
        {"id": pkg_id, "$or": [
            {"cap_reservations": reservation_id},
            {"$expr": {"$lte": [{"$add": [_COMMITTED, amount]},
                                {"$add": [{"$ifNull": ["$certified_total", 0]}, 0.005]}]}}]},
        [{"$set": {
            "committed_paid_total": {"$cond": [already, _COMMITTED,
                                               {"$round": [{"$add": [_COMMITTED, amount]}, 2]}]},
            "cap_reservations": {"$cond": [already, _RESERVED_IDS,
                                           {"$concatArrays": [_RESERVED_IDS, [reservation_id]]}]},
        }}])
    if res.matched_count == 0:
        raise HTTPException(status_code=409, detail={
            "error_code": "PAYMENT_EXCEEDS_CERTIFIED",
            "message": "Плащането надвишава актуваното (сертифицираното) по пакета; "
                       "над измереното се плаща само с одобрение (FLOW-021)"})


async def _write_subcontractor_payment(mw, tenant, user, pkg, account, payment, ledger_id, now):
    """The writes of one subcontractor payment; each one done once per Idempotency-Key."""
    org_id, pkg_id, amount = user["org_id"], payment["package_id"], payment["amount"]
    account_id = account["id"]
    # SEC-01-C03-D (FG-90): the FIRST write reserves the amount against the package's
    # certified total, atomically (one conditional update: two payments under different keys
    # cannot both pass). Over the cap -> 409, nothing written. FLOW-021 allows more only with
    # an Approval (W0-07), which does not exist yet -> refused. Done once per key.
    await mw.step("reserve", lambda: _reserve_within_certified(tenant, pkg_id, amount,
                                                             payment["id"]))
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
                               "account_id": account_id},
        entry_id=mw.new_id("audit_payment")))   # one audit row per payment, even after a crash

    # Update package paid totals
    # FG-105: summed in the database — a package with more than 200 payments is counted fully.
    paid = await tenant.subcontractor_payments.aggregate([
        {"$match": {"package_id": pkg_id, "status": "completed"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_paid = paid[0]["total"] if paid else 0
    certified = pkg.get("certified_total", 0)
    payable = round(certified - total_paid, 2)

    await tenant.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {
        "paid_total": round(total_paid, 2), "payable_total": max(0, payable), "updated_at": now,
    }})


@router.get("/subcontractor-payments")
async def list_subcontractor_payments(
    _sec02: dict = Depends(require_finance_read(
        "finance.subcontractor_payment.read", module="M2", resource_type="subcontractor_payment")),  # SEC-02 (R20-1): before any read
    project_id: Optional[str] = None, package_id: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if package_id: q["package_id"] = package_id
    return await tenant.subcontractor_payments.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROFIT INTEGRATION HELPER
# ═══════════════════════════════════════════════════════════════════

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
