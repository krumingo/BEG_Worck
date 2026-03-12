"""
Routes - Revenue & Expense Core.
Phase 1: Client Acts (earned revenue)
Phase 2: Labor Cost Aggregation
Phase 3: Execution Packages
Phase 4: Project Profit Summary
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.utils.audit import log_audit

router = APIRouter(tags=["Revenue & Expense"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — CLIENT ACTS (EARNED REVENUE)
# ═══════════════════════════════════════════════════════════════════

class ActLineInput(BaseModel):
    offer_line_id: Optional[str] = None
    activity_name: str
    unit: str = "m2"
    contracted_qty: float = 0
    executed_qty: float = 0
    unit_price: float = 0
    note: Optional[str] = None

class ClientActCreate(BaseModel):
    project_id: str
    source_offer_id: Optional[str] = None
    act_number: Optional[str] = None
    act_date: Optional[str] = None
    period_from: Optional[str] = None
    period_to: Optional[str] = None
    notes: Optional[str] = None
    lines: List[ActLineInput] = []


async def get_next_act_number(org_id: str) -> str:
    last = await db.client_acts.find_one({"org_id": org_id}, {"_id": 0, "act_number": 1}, sort=[("created_at", -1)])
    num = 1
    if last and last.get("act_number"):
        try: num = int(last["act_number"].split("-")[1]) + 1
        except: pass
    return f"ACT-{num:04d}"


@router.post("/client-acts", status_code=201)
async def create_client_act(data: ClientActCreate, user: dict = Depends(require_m2)):
    """Create a draft client act for executed works"""
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.now(timezone.utc).isoformat()
    act_no = data.act_number or await get_next_act_number(org_id)

    lines = []
    for i, l in enumerate(data.lines):
        executed_total = round(l.executed_qty * l.unit_price, 2)
        lines.append({
            "id": str(uuid.uuid4()),
            "offer_line_id": l.offer_line_id,
            "activity_name": l.activity_name,
            "unit": l.unit,
            "contracted_qty": l.contracted_qty,
            "executed_qty": l.executed_qty,
            "executed_percent": round(l.executed_qty / l.contracted_qty * 100, 1) if l.contracted_qty > 0 else 0,
            "unit_price": l.unit_price,
            "line_total": executed_total,
            "note": l.note,
            "sort_order": i,
        })

    subtotal = sum(l["line_total"] for l in lines)
    act = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.project_id,
        "source_offer_id": data.source_offer_id,
        "act_number": act_no,
        "act_date": data.act_date or now[:10],
        "period_from": data.period_from,
        "period_to": data.period_to,
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "vat_percent": 20,
        "vat_amount": round(subtotal * 0.2, 2),
        "total": round(subtotal * 1.2, 2),
        "currency": "EUR",
        "notes": data.notes,
        "status": "Draft",
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await db.client_acts.insert_one(act)
    return {k: v for k, v in act.items() if k != "_id"}


@router.get("/client-acts")
async def list_client_acts(project_id: Optional[str] = None, user: dict = Depends(require_m2)):
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    acts = await db.client_acts.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return acts


@router.get("/client-acts/{act_id}")
async def get_client_act(act_id: str, user: dict = Depends(require_m2)):
    act = await db.client_acts.find_one({"id": act_id, "org_id": user["org_id"]}, {"_id": 0})
    if not act:
        raise HTTPException(status_code=404, detail="Act not found")
    return act


@router.put("/client-acts/{act_id}")
async def update_client_act(act_id: str, data: dict, user: dict = Depends(require_m2)):
    act = await db.client_acts.find_one({"id": act_id, "org_id": user["org_id"]})
    if not act:
        raise HTTPException(status_code=404, detail="Act not found")
    if act["status"] not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Only draft acts can be edited")

    allowed = ["act_date", "period_from", "period_to", "notes", "lines"]
    update = {k: v for k, v in data.items() if k in allowed}

    if "lines" in update:
        for l in update["lines"]:
            if not l.get("id"):
                l["id"] = str(uuid.uuid4())
            l["line_total"] = round(float(l.get("executed_qty", 0)) * float(l.get("unit_price", 0)), 2)
            l["executed_percent"] = round(float(l.get("executed_qty", 0)) / float(l.get("contracted_qty", 1)) * 100, 1) if float(l.get("contracted_qty", 0)) > 0 else 0
        subtotal = sum(l["line_total"] for l in update["lines"])
        update["subtotal"] = round(subtotal, 2)
        update["vat_amount"] = round(subtotal * 0.2, 2)
        update["total"] = round(subtotal * 1.2, 2)

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.client_acts.update_one({"id": act_id}, {"$set": update})
    return await db.client_acts.find_one({"id": act_id}, {"_id": 0})


@router.post("/client-acts/{act_id}/confirm")
async def confirm_client_act(act_id: str, user: dict = Depends(require_m2)):
    """Confirm act → status=Accepted → earned revenue"""
    act = await db.client_acts.find_one({"id": act_id, "org_id": user["org_id"]})
    if not act:
        raise HTTPException(status_code=404, detail="Act not found")
    if act["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Only draft acts can be confirmed")
    if not act.get("lines"):
        raise HTTPException(status_code=400, detail="Act has no lines")

    now = datetime.now(timezone.utc).isoformat()
    await db.client_acts.update_one({"id": act_id}, {"$set": {
        "status": "Accepted", "accepted_at": now, "accepted_by": user["id"], "updated_at": now,
    }})
    await log_audit(user["org_id"], user["id"], user.get("email", ""), "client_act_confirmed", "client_act", act_id,
                    {"act_number": act["act_number"], "total": act["total"]})
    return await db.client_acts.find_one({"id": act_id}, {"_id": 0})


@router.post("/client-acts/from-offer/{offer_id}", status_code=201)
async def create_act_from_offer(offer_id: str, data: dict, user: dict = Depends(require_m2)):
    """Generate client act lines from accepted offer"""
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    now = datetime.now(timezone.utc).isoformat()
    act_no = await get_next_act_number(user["org_id"])
    percent = float(data.get("percent", 100))

    lines = []
    for i, ol in enumerate(offer.get("lines", [])):
        qty = ol.get("qty", 0)
        price = round(ol.get("material_unit_cost", 0) + ol.get("labor_unit_cost", 0), 2)
        exec_qty = round(qty * percent / 100, 2)
        lines.append({
            "id": str(uuid.uuid4()),
            "offer_line_id": ol.get("id"),
            "activity_name": ol.get("activity_name", ""),
            "unit": ol.get("unit", "m2"),
            "contracted_qty": qty,
            "executed_qty": exec_qty,
            "executed_percent": percent,
            "unit_price": price,
            "line_total": round(exec_qty * price, 2),
            "note": None,
            "sort_order": i,
        })

    subtotal = sum(l["line_total"] for l in lines)
    act = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": offer["project_id"],
        "source_offer_id": offer_id,
        "act_number": act_no,
        "act_date": now[:10],
        "period_from": data.get("period_from"),
        "period_to": data.get("period_to"),
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "vat_percent": 20,
        "vat_amount": round(subtotal * 0.2, 2),
        "total": round(subtotal * 1.2, 2),
        "currency": offer.get("currency", "EUR"),
        "notes": f"От оферта {offer.get('offer_no', '')}",
        "status": "Draft",
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
    }
    await db.client_acts.insert_one(act)
    return {k: v for k, v in act.items() if k != "_id"}


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — LABOR COST AGGREGATION
# ═══════════════════════════════════════════════════════════════════

@router.get("/labor-cost/by-project/{project_id}")
async def get_labor_cost_by_project(project_id: str, date_from: Optional[str] = None, date_to: Optional[str] = None, user: dict = Depends(require_m2)):
    """Aggregate labor cost by project from work reports × employee rates"""
    org_id = user["org_id"]

    # Load employee rates
    profiles = await db.employee_profiles.find({"org_id": org_id}, {"_id": 0, "user_id": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1, "working_days_per_month": 1, "standard_hours_per_day": 1}).to_list(200)
    rate_map = {}
    for p in profiles:
        hr = p.get("hourly_rate") or 0
        if not hr and p.get("monthly_salary") and p.get("working_days_per_month") and p.get("standard_hours_per_day"):
            hr = round(p["monthly_salary"] / p["working_days_per_month"] / p["standard_hours_per_day"], 2)
        rate_map[p["user_id"]] = hr

    # Load user names
    users = await db.users.find({"org_id": org_id}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(200)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users}

    # Query work reports
    wr_query = {"org_id": org_id, "project_id": project_id}
    if date_from:
        wr_query["date"] = {"$gte": date_from}
    if date_to:
        wr_query.setdefault("date", {})["$lte"] = date_to

    reports = await db.work_reports.find(wr_query, {"_id": 0}).to_list(1000)

    # Aggregate
    by_employee = {}
    by_activity = {}
    total_hours = 0
    total_cost = 0

    for wr in reports:
        uid = wr["user_id"]
        rate = rate_map.get(uid, 0)
        for line in wr.get("lines", []):
            hours = float(line.get("hours", 0))
            cost = round(hours * rate, 2)
            total_hours += hours
            total_cost += cost

            if uid not in by_employee:
                by_employee[uid] = {"user_id": uid, "name": name_map.get(uid, ""), "hourly_rate": rate, "hours": 0, "cost": 0}
            by_employee[uid]["hours"] += hours
            by_employee[uid]["cost"] += cost

            act_name = line.get("activity_name", "Общо")
            if act_name not in by_activity:
                by_activity[act_name] = {"activity_name": act_name, "hours": 0, "cost": 0}
            by_activity[act_name]["hours"] += hours
            by_activity[act_name]["cost"] += cost

    for v in by_employee.values():
        v["hours"] = round(v["hours"], 1)
        v["cost"] = round(v["cost"], 2)
    for v in by_activity.values():
        v["hours"] = round(v["hours"], 1)
        v["cost"] = round(v["cost"], 2)

    return {
        "project_id": project_id,
        "total_hours": round(total_hours, 1),
        "total_cost": round(total_cost, 2),
        "currency": "EUR",
        "by_employee": sorted(by_employee.values(), key=lambda x: x["cost"], reverse=True),
        "by_activity": sorted(by_activity.values(), key=lambda x: x["cost"], reverse=True),
        "data_source": "work_reports × employee_profiles.hourly_rate",
        "reports_count": len(reports),
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — EXECUTION PACKAGES
# ═══════════════════════════════════════════════════════════════════

@router.post("/execution-packages/from-offer/{offer_id}", status_code=201)
async def generate_execution_packages(offer_id: str, user: dict = Depends(require_m2)):
    """Generate execution packages from accepted offer lines"""
    org_id = user["org_id"]
    offer = await db.offers.find_one({"id": offer_id, "org_id": org_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    existing = await db.execution_packages.count_documents({"org_id": org_id, "source_offer_id": offer_id})
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
        await db.execution_packages.insert_many(packages)

    return {"ok": True, "count": len(packages), "offer_id": offer_id, "project_id": offer["project_id"]}


@router.get("/execution-packages")
async def list_execution_packages(project_id: Optional[str] = None, offer_id: Optional[str] = None, user: dict = Depends(require_m2)):
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    if offer_id:
        query["source_offer_id"] = offer_id
    pkgs = await db.execution_packages.find(query, {"_id": 0}).sort("created_at", 1).to_list(500)
    return pkgs


@router.put("/execution-packages/{pkg_id}")
async def update_execution_package(pkg_id: str, data: dict, user: dict = Depends(require_m2)):
    pkg = await db.execution_packages.find_one({"id": pkg_id, "org_id": user["org_id"]})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    allowed = ["progress_percent", "used_hours", "qty_executed", "status",
               "actual_material_cost", "actual_labor_cost", "actual_subcontract_cost", "actual_overhead_cost",
               "planned_hours", "planned_margin", "notes"]
    update = {k: v for k, v in data.items() if k in allowed}

    if any(k.startswith("actual_") for k in update):
        mat = float(update.get("actual_material_cost", pkg.get("actual_material_cost", 0)))
        lab = float(update.get("actual_labor_cost", pkg.get("actual_labor_cost", 0)))
        sub = float(update.get("actual_subcontract_cost", pkg.get("actual_subcontract_cost", 0)))
        ovh = float(update.get("actual_overhead_cost", pkg.get("actual_overhead_cost", 0)))
        update["actual_total_cost"] = round(mat + lab + sub + ovh, 2)

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.execution_packages.update_one({"id": pkg_id}, {"$set": update})
    return await db.execution_packages.find_one({"id": pkg_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — PROJECT PROFIT SUMMARY (READ MODEL)
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-profit/{project_id}")
async def get_project_profit_summary(project_id: str, user: dict = Depends(require_m2)):
    """Comprehensive project financial summary — revenue, costs, profit"""
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # ── REVENUE ──
    # R1: Contracted (accepted offers)
    accepted_offers = await db.offers.find(
        {"project_id": project_id, "org_id": org_id, "status": "Accepted"},
        {"_id": 0, "total": 1, "subtotal": 1}
    ).to_list(100)
    contracted_revenue = sum(o.get("subtotal", 0) or o.get("total", 0) for o in accepted_offers)

    # R2: Earned (accepted client acts)
    accepted_acts = await db.client_acts.find(
        {"project_id": project_id, "org_id": org_id, "status": "Accepted"},
        {"_id": 0, "subtotal": 1}
    ).to_list(100)
    earned_revenue = sum(a.get("subtotal", 0) for a in accepted_acts)

    # R3: Billed (issued invoices)
    issued_invoices = await db.invoices.find(
        {"project_id": project_id, "org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled"]}},
        {"_id": 0, "subtotal": 1, "total": 1, "paid_amount": 1}
    ).to_list(100)
    billed_revenue = sum(i.get("subtotal", 0) or i.get("total", 0) for i in issued_invoices)

    # R5: Collected
    collected_revenue = sum(i.get("paid_amount", 0) for i in issued_invoices)

    # ── EXPENSES ──
    # Material cost: from warehouse issues to this project
    wh_issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"},
        {"_id": 0, "total": 1, "lines": 1}
    ).to_list(100)
    material_cost = sum(t.get("total", 0) or sum(l.get("total_price", 0) for l in t.get("lines", [])) for t in wh_issues)

    # Returns reduce material cost
    wh_returns = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "return"},
        {"_id": 0, "lines": 1}
    ).to_list(100)
    material_returns = sum(sum(l.get("total_price", 0) or 0 for l in t.get("lines", [])) for t in wh_returns)
    net_material_cost = round(material_cost - material_returns, 2)

    # Labor cost: from labor_entries (mapped + unmapped) with fallback to work_reports
    from app.routes.labor_smr import get_labor_summary_for_project
    labor_summary = await get_labor_summary_for_project(org_id, project_id)
    
    if labor_summary["has_data"]:
        labor_cost = labor_summary["total_cost"]
        labor_hours = labor_summary["total_hours"]
    else:
        # Fallback to old work_reports aggregation
        profiles = await db.employee_profiles.find({"org_id": org_id}, {"_id": 0, "user_id": 1, "hourly_rate": 1}).to_list(200)
        rate_map = {p["user_id"]: p.get("hourly_rate", 0) or 0 for p in profiles}
        reports = await db.work_reports.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "user_id": 1, "lines": 1}).to_list(1000)
        labor_cost = 0
        labor_hours = 0
        for wr in reports:
            rate = rate_map.get(wr["user_id"], 0)
            for line in wr.get("lines", []):
                h = float(line.get("hours", 0))
                labor_hours += h
                labor_cost += h * rate
        labor_cost = round(labor_cost, 2)
        labor_summary = None

    # Subcontract cost: from subcontractor packages + acts + payments
    from app.routes.subcontractors import get_subcontract_metrics
    sub_metrics = await get_subcontract_metrics(org_id, project_id)
    
    # Fallback to received invoices if no subcontractor packages
    if sub_metrics.get("available"):
        subcontract_cost = sub_metrics["certified"]  # certified = execution cost basis
    else:
        received_invoices = await db.invoices.find(
            {"project_id": project_id, "org_id": org_id, "direction": "Received", "status": {"$nin": ["Draft", "Cancelled"]}},
            {"_id": 0, "subtotal": 1, "total": 1}
        ).to_list(100)
        subcontract_cost = sum(i.get("subtotal", 0) or i.get("total", 0) for i in received_invoices)

    # Overhead: from allocations if exist
    overhead_allocs = await db.project_overhead_alloc.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "allocated_amount": 1}
    ).to_list(50)
    overhead_cost = sum(a.get("allocated_amount", 0) for a in overhead_allocs)

    # ── PROFIT ──
    total_cost = round(net_material_cost + labor_cost + subcontract_cost + overhead_cost, 2)
    primary_revenue = earned_revenue if earned_revenue > 0 else contracted_revenue
    gross_profit = round(primary_revenue - total_cost, 2)
    gross_margin = round(gross_profit / primary_revenue * 100, 1) if primary_revenue > 0 else 0

    receivables = round(billed_revenue - collected_revenue, 2)

    # ── EXECUTION PACKAGES BREAKDOWN ──
    exec_pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0}
    ).to_list(200)

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
        "material_cost": len(wh_issues) > 0,
        "labor_cost": labor_summary["has_data"] if labor_summary else len(reports) > 0,
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
            "receivables": receivables,
        },

        "expenses": {
            "material": net_material_cost,
            "labor": labor_cost,
            "labor_hours": round(labor_hours, 1),
            "labor_detail": labor_summary if labor_summary else None,
            "subcontract": round(subcontract_cost, 2),
            "subcontract_detail": sub_metrics if sub_metrics.get("available") else None,
            "overhead": round(overhead_cost, 2),
            "total": total_cost,
        },

        "profit": {
            "gross_profit": gross_profit,
            "gross_margin_percent": gross_margin,
            "revenue_basis": "earned" if earned_revenue > 0 else "contracted",
        },

        "execution_packages": pkg_breakdown,
        "metrics_available": metrics_available,
    }
