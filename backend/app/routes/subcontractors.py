"""
Routes - Subcontractor Financial Flow.
Phase 1: Subcontractors + Packages
Phase 2: Package Lines from Offer/Execution
Phase 3: Subcontractor Acts (Certified Expense)
Phase 4: Subcontractor Payments
Phase 5: Profit Integration (extends revenue_expense)
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.utils.audit import log_audit

router = APIRouter(tags=["Subcontractors"])


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
async def create_subcontractor(data: SubcontractorCreate, user: dict = Depends(require_m2)):
    now = datetime.now(timezone.utc).isoformat()
    sub = {
        "id": str(uuid.uuid4()), "org_id": user["org_id"],
        "name": data.name, "eik": data.eik, "vat_number": data.vat_number,
        "contact_person": data.contact_person, "phone": data.phone,
        "email": data.email, "address": data.address, "notes": data.notes,
        "active": True, "created_at": now, "updated_at": now,
    }
    await db.subcontractors.insert_one(sub)
    return {k: v for k, v in sub.items() if k != "_id"}


@router.get("/subcontractors")
async def list_subcontractors(user: dict = Depends(require_m2)):
    subs = await db.subcontractors.find({"org_id": user["org_id"]}, {"_id": 0}).sort("name", 1).to_list(200)
    return subs


@router.get("/subcontractors/{sub_id}")
async def get_subcontractor(sub_id: str, user: dict = Depends(require_m2)):
    sub = await db.subcontractors.find_one({"id": sub_id, "org_id": user["org_id"]}, {"_id": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    return sub


async def _get_next_pkg_no(org_id):
    last = await db.subcontractor_packages.find_one({"org_id": org_id}, {"_id": 0, "package_no": 1}, sort=[("created_at", -1)])
    n = 1
    if last and last.get("package_no"):
        try: n = int(last["package_no"].split("-")[1]) + 1
        except Exception as e: logger.warning(f"subcontractors.py error: {e}")
    return f"SP-{n:04d}"


@router.post("/subcontractor-packages", status_code=201)
async def create_package(data: PackageCreate, user: dict = Depends(require_m2)):
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sub = await db.subcontractors.find_one({"id": data.subcontractor_id, "org_id": org_id})
    if not sub:
        raise HTTPException(status_code=404, detail="Subcontractor not found")

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
    await db.subcontractor_packages.insert_one(pkg)
    return {k: v for k, v in pkg.items() if k != "_id"}


@router.get("/subcontractor-packages")
async def list_packages(project_id: Optional[str] = None, subcontractor_id: Optional[str] = None, user: dict = Depends(require_m2)):
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if subcontractor_id: q["subcontractor_id"] = subcontractor_id
    pkgs = await db.subcontractor_packages.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return pkgs


@router.get("/subcontractor-packages/{pkg_id}")
async def get_package(pkg_id: str, user: dict = Depends(require_m2)):
    pkg = await db.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    lines = await db.subcontractor_package_lines.find({"package_id": pkg_id}, {"_id": 0}).sort("sort_order", 1).to_list(200)
    pkg["lines"] = lines
    return pkg


@router.post("/subcontractor-packages/{pkg_id}/confirm")
async def confirm_package(pkg_id: str, user: dict = Depends(require_m2)):
    pkg = await db.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft packages can be confirmed")
    lines = await db.subcontractor_package_lines.count_documents({"package_id": pkg_id})
    if lines == 0:
        raise HTTPException(status_code=400, detail="Package has no lines")

    all_lines = await db.subcontractor_package_lines.find({"package_id": pkg_id}, {"_id": 0}).to_list(200)
    contract_total = sum(l.get("subcontract_total", 0) for l in all_lines)
    sale_total = sum(l.get("sale_total_for_assigned_qty", 0) for l in all_lines)
    planned_margin = round(sale_total - contract_total, 2)

    now = datetime.now(timezone.utc).isoformat()
    await db.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {
        "status": "confirmed", "confirmed_at": now, "updated_at": now,
        "contract_total": round(contract_total, 2),
        "remaining_contract_total": round(contract_total, 2),
        "planned_margin": planned_margin,
    }})
    return await db.subcontractor_packages.find_one({"id": pkg_id}, {"_id": 0})


@router.post("/subcontractor-packages/{pkg_id}/close")
async def close_package(pkg_id: str, user: dict = Depends(require_m2)):
    pkg = await db.subcontractor_packages.find_one({"id": pkg_id, "org_id": user["org_id"]})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] in ["draft", "closed"]:
        raise HTTPException(status_code=400, detail=f"Cannot close package in {pkg['status']} status")
    now = datetime.now(timezone.utc).isoformat()
    await db.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {"status": "closed", "closed_at": now, "updated_at": now}})
    return await db.subcontractor_packages.find_one({"id": pkg_id}, {"_id": 0})


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


async def _get_assigned_qty(org_id: str, offer_line_id: str, exclude_pkg_id: str = None) -> float:
    """Get total already-assigned qty for an offer line across all packages"""
    q = {"org_id": org_id, "offer_line_id": offer_line_id}
    if exclude_pkg_id:
        q["package_id"] = {"$ne": exclude_pkg_id}
    lines = await db.subcontractor_package_lines.find(q, {"_id": 0, "assigned_qty": 1}).to_list(100)
    return sum(l.get("assigned_qty", 0) for l in lines)


@router.post("/subcontractor-packages/{pkg_id}/lines", status_code=201)
async def add_package_lines(pkg_id: str, data: dict, user: dict = Depends(require_m2)):
    org_id = user["org_id"]
    pkg = await db.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Can only add lines to draft packages")

    input_lines = data.get("lines", [])
    if not input_lines:
        raise HTTPException(status_code=400, detail="No lines provided")

    existing_count = await db.subcontractor_package_lines.count_documents({"package_id": pkg_id})
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
        sub_up = float(il.get("subcontract_unit_price", 0))

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
            "subcontract_unit_price": sub_up,
            "subcontract_total": round(assigned * sub_up, 2),
            "planned_margin": round(assigned * (sale_up - sub_up), 2),
            "certified_qty": 0, "certified_total": 0, "paid_total": 0,
            "remaining_qty": assigned, "remaining_value": round(assigned * sub_up, 2),
            "status": "active", "sort_order": existing_count + i,
            "created_at": now,
        }
        await db.subcontractor_package_lines.insert_one(line)
        created.append({k: v for k, v in line.items() if k != "_id"})

    return {"ok": True, "count": len(created), "lines": created}


@router.post("/subcontractor-packages/{pkg_id}/lines-from-offer/{offer_id}", status_code=201)
async def add_lines_from_offer(pkg_id: str, offer_id: str, user: dict = Depends(require_m2)):
    """Populate package lines from offer lines with availability check"""
    org_id = user["org_id"]
    pkg = await db.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg or pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Package must be draft")

    offer = await db.offers.find_one({"id": offer_id, "org_id": org_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    # Load execution packages for linkage
    epkgs = {}
    for ep in await db.execution_packages.find({"org_id": org_id, "source_offer_id": offer_id}, {"_id": 0, "id": 1, "offer_line_id": 1}).to_list(200):
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
    line = await db.subcontractor_package_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    if not line:
        raise HTTPException(status_code=404, detail="Line not found")
    pkg = await db.subcontractor_packages.find_one({"id": line["package_id"]})
    if not pkg or pkg["status"] != "draft":
        raise HTTPException(status_code=400, detail="Can only remove lines from draft packages")
    await db.subcontractor_package_lines.delete_one({"id": line_id})
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — SUBCONTRACTOR ACTS (CERTIFIED EXPENSE)
# ═══════════════════════════════════════════════════════════════════

async def _get_next_act_no(org_id):
    last = await db.subcontractor_acts.find_one({"org_id": org_id}, {"_id": 0, "act_no": 1}, sort=[("created_at", -1)])
    n = 1
    if last and last.get("act_no"):
        try: n = int(last["act_no"].split("-")[1]) + 1
        except Exception as e: logger.warning(f"subcontractors.py error: {e}")
    return f"SA-{n:04d}"


@router.post("/subcontractor-acts", status_code=201)
async def create_subcontractor_act(data: dict, user: dict = Depends(require_m2)):
    org_id = user["org_id"]
    pkg_id = data.get("package_id")
    pkg = await db.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    if pkg["status"] == "draft":
        raise HTTPException(status_code=400, detail="Package must be confirmed before creating acts")

    now = datetime.now(timezone.utc).isoformat()
    act_lines = []
    for al in data.get("lines", []):
        pl_id = al.get("package_line_id")
        pl = await db.subcontractor_package_lines.find_one({"id": pl_id}, {"_id": 0})
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
    await db.subcontractor_acts.insert_one(act)
    return {k: v for k, v in act.items() if k != "_id"}


@router.get("/subcontractor-acts")
async def list_subcontractor_acts(project_id: Optional[str] = None, package_id: Optional[str] = None, user: dict = Depends(require_m2)):
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if package_id: q["package_id"] = package_id
    return await db.subcontractor_acts.find(q, {"_id": 0}).sort("created_at", -1).to_list(100)


@router.post("/subcontractor-acts/{act_id}/confirm")
async def confirm_subcontractor_act(act_id: str, user: dict = Depends(require_m2)):
    act = await db.subcontractor_acts.find_one({"id": act_id, "org_id": user["org_id"]})
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
        await db.subcontractor_package_lines.update_one({"id": pl_id}, {"$set": {
            "certified_qty": new_cert, "certified_total": new_cert_total,
            "remaining_qty": new_remaining,
            "remaining_value": round(new_remaining * al["subcontract_unit_price"], 2),
        }})

    # Update package totals
    pkg_id = act["package_id"]
    all_pl = await db.subcontractor_package_lines.find({"package_id": pkg_id}, {"_id": 0}).to_list(200)
    total_cert = sum(l.get("certified_total", 0) for l in all_pl)
    contract_total = sum(l.get("subcontract_total", 0) for l in all_pl)
    total_remaining = sum(l.get("remaining_qty", 0) for l in all_pl)

    pkg_status = "in_progress"
    if total_remaining <= 0:
        pkg_status = "completed"
    elif total_cert > 0:
        pkg_status = "partially_certified"

    await db.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {
        "certified_total": round(total_cert, 2),
        "payable_total": round(total_cert - (await db.subcontractor_packages.find_one({"id": pkg_id})).get("paid_total", 0), 2),
        "remaining_contract_total": round(contract_total - total_cert, 2),
        "status": pkg_status, "updated_at": now,
    }})

    await db.subcontractor_acts.update_one({"id": act_id}, {"$set": {"status": "confirmed", "confirmed_at": now, "updated_at": now}})
    return await db.subcontractor_acts.find_one({"id": act_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — SUBCONTRACTOR PAYMENTS
# ═══════════════════════════════════════════════════════════════════

async def _get_next_pay_no(org_id):
    last = await db.subcontractor_payments.find_one({"org_id": org_id}, {"_id": 0, "payment_no": 1}, sort=[("created_at", -1)])
    n = 1
    if last and last.get("payment_no"):
        try: n = int(last["payment_no"].split("-")[1]) + 1
        except Exception as e: logger.warning(f"subcontractors.py error: {e}")
    return f"SPAY-{n:04d}"


@router.post("/subcontractor-payments", status_code=201)
async def create_subcontractor_payment(data: dict, user: dict = Depends(require_m2)):
    org_id = user["org_id"]
    pkg_id = data.get("package_id")
    pkg = await db.subcontractor_packages.find_one({"id": pkg_id, "org_id": org_id})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    amount = float(data.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    now = datetime.now(timezone.utc).isoformat()
    payment = {
        "id": str(uuid.uuid4()), "org_id": org_id,
        "project_id": pkg["project_id"], "subcontractor_id": pkg["subcontractor_id"],
        "package_id": pkg_id, "act_id": data.get("act_id"),
        "payment_no": await _get_next_pay_no(org_id),
        "payment_date": data.get("payment_date", now[:10]),
        "amount": amount, "currency": pkg.get("currency", "EUR"),
        "payment_type": data.get("payment_type", "partial"),
        "payment_method": data.get("payment_method", "bank"),
        "notes": data.get("notes", ""),
        "status": "completed",
        "created_at": now,
    }
    await db.subcontractor_payments.insert_one(payment)

    # Update package paid totals
    all_pays = await db.subcontractor_payments.find({"package_id": pkg_id, "status": "completed"}, {"_id": 0, "amount": 1}).to_list(200)
    total_paid = sum(p["amount"] for p in all_pays)
    certified = pkg.get("certified_total", 0)
    payable = round(certified - total_paid, 2)

    await db.subcontractor_packages.update_one({"id": pkg_id}, {"$set": {
        "paid_total": round(total_paid, 2), "payable_total": max(0, payable), "updated_at": now,
    }})

    return {k: v for k, v in payment.items() if k != "_id"}


@router.get("/subcontractor-payments")
async def list_subcontractor_payments(project_id: Optional[str] = None, package_id: Optional[str] = None, user: dict = Depends(require_m2)):
    q = {"org_id": user["org_id"]}
    if project_id: q["project_id"] = project_id
    if package_id: q["package_id"] = package_id
    return await db.subcontractor_payments.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROFIT INTEGRATION HELPER
# ═══════════════════════════════════════════════════════════════════

async def get_subcontract_metrics(org_id: str, project_id: str) -> dict:
    """Get aggregated subcontract metrics for a project"""
    pkgs = await db.subcontractor_packages.find(
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
