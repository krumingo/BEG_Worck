"""
Routes - Full Cost / Overhead / Net Margin / Financial Alerts.
Phase 1: Employee full cost model
Phase 2: Overhead categories + period snapshots
Phase 3: Overhead allocation
Phase 4: Execution package overhead + net margin
Phase 5: Profit by period + expected vs actual
Phase 6: Core financial alerts
Phase 7: Project risk summary
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Full Cost / Overhead / Margin"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — EMPLOYEE FULL COST MODEL
# ═══════════════════════════════════════════════════════════════════

@router.get("/employee-cost/{user_id}")
async def get_employee_cost_basis(user_id: str, user: dict = Depends(require_m2)):
    """Employee full cost model — net salary untouched, additional layers separate"""
    org_id = user["org_id"]
    profile = await db.employee_profiles.find_one({"org_id": org_id, "user_id": user_id}, {"_id": 0})

    if not profile:
        return {"user_id": user_id, "available": False, "reason": "no_profile"}

    ms = profile.get("monthly_salary") or 0
    days = profile.get("working_days_per_month") or 22
    hours = profile.get("standard_hours_per_day") or 8
    monthly_hours = days * hours

    net_salary = ms
    net_hour_cost = round(ms / monthly_hours, 2) if monthly_hours > 0 else None

    # Load org additional cost config (if set)
    cost_cfg = await db.settings.find_one({"_id": "employee_cost_config", "org_id": org_id})
    add_pct = (cost_cfg or {}).get("additional_cost_percent", 0)
    overhead_pct = (cost_cfg or {}).get("overhead_percent_per_hour", 0)

    additional_per_hour = round(net_hour_cost * add_pct / 100, 2) if net_hour_cost and add_pct else 0
    overhead_per_hour = round(net_hour_cost * overhead_pct / 100, 2) if net_hour_cost and overhead_pct else 0
    full_cost = round((net_hour_cost or 0) + additional_per_hour + overhead_per_hour, 2)

    return {
        "user_id": user_id,
        "available": net_hour_cost is not None,
        "currency": "EUR",
        "net_salary": net_salary,
        "net_hour_cost": net_hour_cost,
        "additional_company_cost_per_hour": additional_per_hour,
        "overhead_per_hour": overhead_per_hour,
        "full_company_hour_cost": full_cost,
        "config": {
            "additional_cost_percent": add_pct,
            "overhead_percent_per_hour": overhead_pct,
            "source": "organization" if cost_cfg else "default",
        },
    }


@router.put("/employee-cost-config")
async def update_employee_cost_config(data: dict, user: dict = Depends(require_m2)):
    """Set org-level additional cost % and overhead % for employee full cost"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    now = datetime.now(timezone.utc).isoformat()
    await db.settings.update_one(
        {"_id": "employee_cost_config", "org_id": user["org_id"]},
        {"$set": {
            "_id": "employee_cost_config", "org_id": user["org_id"],
            "additional_cost_percent": float(data.get("additional_cost_percent", 0)),
            "overhead_percent_per_hour": float(data.get("overhead_percent_per_hour", 0)),
            "updated_at": now, "updated_by": user["id"],
        }},
        upsert=True,
    )
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — OVERHEAD CATEGORIES + PERIOD SNAPSHOTS
# ═══════════════════════════════════════════════════════════════════

@router.post("/overhead-snapshots", status_code=201)
async def create_overhead_snapshot(data: dict, user: dict = Depends(require_m2)):
    """Create an overhead period snapshot entry"""
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "category_code": data.get("category_code", "general"),
        "category_name": data.get("category_name", ""),
        "period_key": data.get("period_key", datetime.now().strftime("%Y-%m")),
        "amount": float(data.get("amount", 0)),
        "currency": "EUR",
        "allocation_basis": data.get("allocation_basis", "labor_hours"),
        "notes": data.get("notes", ""),
        "status": "active",
        "created_at": now,
        "created_by": user["id"],
    }
    await db.overhead_snapshots.insert_one(entry)
    return {k: v for k, v in entry.items() if k != "_id"}


@router.get("/overhead-snapshots")
async def list_overhead_snapshots(period_key: Optional[str] = None, user: dict = Depends(require_m2)):
    q = {"org_id": user["org_id"]}
    if period_key: q["period_key"] = period_key
    return await db.overhead_snapshots.find(q, {"_id": 0}).sort("period_key", -1).to_list(200)


@router.get("/overhead-snapshots/aggregate")
async def aggregate_overhead(period_key: Optional[str] = None, user: dict = Depends(require_m2)):
    """Aggregate overhead by period and category"""
    org_id = user["org_id"]
    match = {"org_id": org_id, "status": "active"}
    if period_key: match["period_key"] = period_key

    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"period": "$period_key", "category": "$category_code"},
                    "category_name": {"$first": "$category_name"},
                    "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"_id.period": -1, "total": -1}},
    ]
    results = await db.overhead_snapshots.aggregate(pipeline).to_list(200)

    # Also aggregate from legacy overhead_transactions
    legacy = await db.overhead_transactions.find({"org_id": org_id}, {"_id": 0, "date": 1, "amount": 1, "category": 1}).to_list(500)
    legacy_by_period = {}
    for lt in legacy:
        pk = (lt.get("date") or "")[:7]
        if period_key and pk != period_key:
            continue
        legacy_by_period[pk] = legacy_by_period.get(pk, 0) + float(lt.get("amount", 0))

    periods = {}
    for r in results:
        pk = r["_id"]["period"]
        if pk not in periods:
            periods[pk] = {"period": pk, "total": 0, "categories": []}
        periods[pk]["total"] += r["total"]
        periods[pk]["categories"].append({"code": r["_id"]["category"], "name": r.get("category_name", ""), "total": round(r["total"], 2)})

    for pk, total in legacy_by_period.items():
        if pk not in periods:
            periods[pk] = {"period": pk, "total": 0, "categories": [], "source": "legacy"}
        periods[pk]["total"] += total

    for v in periods.values():
        v["total"] = round(v["total"], 2)

    return sorted(periods.values(), key=lambda x: x["period"], reverse=True)


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — OVERHEAD ALLOCATION
# ═══════════════════════════════════════════════════════════════════

@router.post("/overhead-allocation/compute/{project_id}")
async def compute_overhead_allocation(project_id: str, data: dict = {}, user: dict = Depends(require_m2)):
    """Compute overhead allocation for a project based on labor hours share"""
    org_id = user["org_id"]
    period_key = data.get("period_key", datetime.now().strftime("%Y-%m"))

    # Total overhead for period
    snapshots = await db.overhead_snapshots.find(
        {"org_id": org_id, "period_key": period_key, "status": "active"}, {"_id": 0, "amount": 1}
    ).to_list(100)
    total_overhead = sum(s.get("amount", 0) for s in snapshots)

    # Add legacy overhead for the period
    legacy = await db.overhead_transactions.find(
        {"org_id": org_id, "date": {"$regex": f"^{period_key}"}}, {"_id": 0, "amount": 1}
    ).to_list(500)
    total_overhead += sum(lt.get("amount", 0) for lt in legacy)

    if total_overhead <= 0:
        return {"ok": True, "allocated": 0, "reason": "no_overhead_data", "period": period_key}

    # Labor hours by project for allocation basis
    all_entries = await db.labor_entries.find(
        {"org_id": org_id, "date": {"$regex": f"^{period_key}"}}, {"_id": 0, "project_id": 1, "hours": 1}
    ).to_list(5000)
    total_hours = sum(float(e.get("hours", 0)) for e in all_entries)
    project_hours = sum(float(e.get("hours", 0)) for e in all_entries if e.get("project_id") == project_id)

    if total_hours <= 0:
        return {"ok": True, "allocated": 0, "reason": "no_labor_hours", "period": period_key}

    share = project_hours / total_hours
    allocated = round(total_overhead * share, 2)

    now = datetime.now(timezone.utc).isoformat()
    # Upsert allocation
    await db.project_overhead_alloc.update_one(
        {"org_id": org_id, "project_id": project_id, "period": period_key},
        {"$set": {
            "org_id": org_id, "project_id": project_id, "period": period_key,
            "allocated_amount": allocated, "total_overhead": round(total_overhead, 2),
            "allocation_basis": "labor_hours", "project_hours": round(project_hours, 1),
            "total_hours": round(total_hours, 1), "share_percent": round(share * 100, 1),
            "currency": "EUR", "updated_at": now,
        }},
        upsert=True,
    )

    # Also allocate to execution packages by their labor hours
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "id": 1, "used_hours": 1}
    ).to_list(200)
    pkg_total_hours = sum(p.get("used_hours", 0) for p in pkgs)

    for pkg in pkgs:
        pkg_hours = pkg.get("used_hours", 0)
        pkg_share = pkg_hours / pkg_total_hours if pkg_total_hours > 0 else 0
        pkg_alloc = round(allocated * pkg_share, 2)
        await db.execution_packages.update_one({"id": pkg["id"]}, {"$set": {
            "overhead_actual_allocated": pkg_alloc, "updated_at": now,
        }})

    return {"ok": True, "allocated": allocated, "period": period_key, "share_percent": round(share * 100, 1)}


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — EXECUTION PACKAGE NET MARGIN
# (extends material_smr.py financial endpoints)
# ═══════════════════════════════════════════════════════════════════

@router.get("/execution-packages/{pkg_id}/net-financial")
async def get_package_net_financial(pkg_id: str, user: dict = Depends(require_m2)):
    """Package net financial with overhead and net margin"""
    org_id = user["org_id"]
    pkg = await db.execution_packages.find_one({"id": pkg_id, "org_id": org_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    sale = pkg.get("sale_total", 0)
    mat = pkg.get("actual_material_cost", 0)
    lab = pkg.get("actual_labor_cost", 0)
    overhead = pkg.get("overhead_actual_allocated", 0)

    sub_lines = await db.subcontractor_package_lines.find(
        {"org_id": org_id, "execution_package_id": pkg_id}, {"_id": 0, "certified_total": 1}
    ).to_list(50)
    sub = sum(l.get("certified_total", 0) for l in sub_lines)

    gross_cost = round(mat + lab + sub, 2)
    total_cost = round(gross_cost + overhead, 2)
    has_actuals = gross_cost > 0
    gross_margin = round(sale - gross_cost, 2) if has_actuals else None
    net_margin = round(sale - total_cost, 2) if has_actuals else None
    gross_pct = round(gross_margin / sale * 100, 1) if sale > 0 and gross_margin is not None else None
    net_pct = round(net_margin / sale * 100, 1) if sale > 0 and net_margin is not None else None

    budget = pkg.get("budget_total", 0)
    expected = round(sale - budget, 2) if budget > 0 else None

    return {
        "execution_package_id": pkg_id,
        "activity_name": pkg.get("activity_name", ""),
        "currency": "EUR",
        "sale_total": sale,
        "costs": {
            "material": mat, "labor": lab, "subcontract": round(sub, 2),
            "gross_cost": gross_cost, "overhead": overhead, "total_cost": total_cost,
        },
        "margin": {
            "gross_margin": gross_margin, "gross_margin_percent": gross_pct,
            "net_margin": net_margin, "net_margin_percent": net_pct,
            "expected_margin": expected,
            "margin_variance": round(net_margin - expected, 2) if net_margin is not None and expected is not None else None,
        },
        "metrics_partial": not has_actuals or overhead == 0,
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — PROFIT BY PERIOD + EXPECTED VS ACTUAL
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-net-profit/{project_id}")
async def get_project_net_profit(project_id: str, user: dict = Depends(require_m2)):
    """Extended project profit with overhead, gross vs net margin, expected vs actual"""
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Revenue
    accepted_offers = await db.offers.find({"project_id": project_id, "org_id": org_id, "status": "Accepted"}, {"_id": 0, "subtotal": 1}).to_list(100)
    contracted = sum(o.get("subtotal", 0) for o in accepted_offers)

    accepted_acts = await db.client_acts.find({"project_id": project_id, "org_id": org_id, "status": "Accepted"}, {"_id": 0, "subtotal": 1}).to_list(100)
    earned = sum(a.get("subtotal", 0) for a in accepted_acts)

    invoices = await db.invoices.find({"project_id": project_id, "org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled"]}}, {"_id": 0, "subtotal": 1, "paid_amount": 1}).to_list(100)
    billed = sum(i.get("subtotal", 0) for i in invoices)
    collected = sum(i.get("paid_amount", 0) for i in invoices)

    # Material
    from app.routes.material_smr import get_material_summary_for_project
    mat_summary = await get_material_summary_for_project(org_id, project_id)
    mat_cost = mat_summary["total_cost"]

    # Labor
    from app.routes.labor_smr import get_labor_summary_for_project
    lab_summary = await get_labor_summary_for_project(org_id, project_id)
    lab_cost = lab_summary["total_cost"]

    # Subcontract
    from app.routes.subcontractors import get_subcontract_metrics
    sub_metrics = await get_subcontract_metrics(org_id, project_id)
    sub_certified = sub_metrics.get("certified", 0) if sub_metrics.get("available") else 0

    # Overhead
    allocs = await db.project_overhead_alloc.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "allocated_amount": 1}).to_list(50)
    overhead = sum(a.get("allocated_amount", 0) for a in allocs)

    # Budget from execution packages
    pkgs = await db.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "budget_total": 1}).to_list(200)
    budget_total = sum(p.get("budget_total", 0) for p in pkgs)

    gross_cost = round(mat_cost + lab_cost + sub_certified, 2)
    total_cost = round(gross_cost + overhead, 2)
    revenue_basis = earned if earned > 0 else contracted
    basis_label = "earned" if earned > 0 else "contracted"

    gross_profit = round(revenue_basis - gross_cost, 2) if revenue_basis > 0 else None
    net_profit = round(revenue_basis - total_cost, 2) if revenue_basis > 0 else None
    gross_pct = round(gross_profit / revenue_basis * 100, 1) if revenue_basis > 0 and gross_profit is not None else None
    net_pct = round(net_profit / revenue_basis * 100, 1) if revenue_basis > 0 and net_profit is not None else None

    expected_profit = round(revenue_basis - budget_total, 2) if budget_total > 0 else None
    expected_pct = round(expected_profit / revenue_basis * 100, 1) if revenue_basis > 0 and expected_profit is not None else None
    actual_vs_expected = round(net_profit - expected_profit, 2) if net_profit is not None and expected_profit is not None else None

    return {
        "project_id": project_id,
        "project_code": project.get("code", ""), "project_name": project.get("name", ""),
        "currency": "EUR",
        "revenue": {"contracted": round(contracted, 2), "earned": round(earned, 2), "billed": round(billed, 2), "collected": round(collected, 2), "receivables": round(billed - collected, 2), "basis": basis_label},
        "costs": {"material": mat_cost, "labor": lab_cost, "subcontract": round(sub_certified, 2), "gross_cost": gross_cost, "overhead": round(overhead, 2), "total_cost": total_cost},
        "profit": {
            "gross_profit": gross_profit, "gross_margin_percent": gross_pct,
            "net_profit": net_profit, "net_margin_percent": net_pct,
            "expected_profit": expected_profit, "expected_margin_percent": expected_pct,
            "actual_vs_expected_variance": actual_vs_expected,
        },
        "detail": {"material": mat_summary, "labor": lab_summary, "subcontract": sub_metrics if sub_metrics.get("available") else None},
        "metrics_available": {
            "revenue": len(accepted_offers) > 0, "earned": len(accepted_acts) > 0,
            "material": mat_summary["has_data"], "labor": lab_summary["has_data"],
            "subcontract": sub_metrics.get("available", False), "overhead": len(allocs) > 0,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 6 — CORE FINANCIAL ALERTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/financial-alerts/{project_id}")
async def get_financial_alerts(project_id: str, user: dict = Depends(require_m2)):
    """Core financial alerts for a project"""
    org_id = user["org_id"]
    alerts = []

    # Overhead
    allocs = await db.project_overhead_alloc.count_documents({"org_id": org_id, "project_id": project_id})
    if allocs == 0:
        alerts.append({"type": "overhead_not_allocated", "severity": "warning", "message": "Режийни разходи не са разпределени към проекта"})

    # Subcontract payable
    from app.routes.subcontractors import get_subcontract_metrics
    sub = await get_subcontract_metrics(org_id, project_id)
    if sub.get("available") and sub.get("payable", 0) > 0:
        alerts.append({"type": "subcontract_payable", "severity": "info", "amount": sub["payable"], "message": f"Дължимо към подизпълнители: {sub['payable']} EUR"})

    # Client receivable
    invoices = await db.invoices.find(
        {"project_id": project_id, "org_id": org_id, "direction": "Issued", "status": {"$in": ["Sent", "PartiallyPaid", "Overdue"]}},
        {"_id": 0, "remaining_amount": 1}
    ).to_list(100)
    receivable = sum(i.get("remaining_amount", 0) for i in invoices)
    if receivable > 0:
        overdue = await db.invoices.count_documents({"project_id": project_id, "org_id": org_id, "status": "Overdue"})
        sev = "critical" if overdue > 0 else "info"
        alerts.append({"type": "client_receivable", "severity": sev, "amount": round(receivable, 2), "overdue_count": overdue, "message": f"Вземания: {round(receivable, 2)} EUR ({overdue} просрочени)"})

    # Material warnings
    mat_warn = await db.material_entries.count_documents({"org_id": org_id, "project_id": project_id, "execution_package_id": None})
    if mat_warn > 0:
        alerts.append({"type": "unmapped_material", "severity": "warning", "count": mat_warn, "message": f"{mat_warn} материални записа без връзка към СМР"})

    # Labor warnings
    lab_unmapped = await db.labor_entries.count_documents({"org_id": org_id, "project_id": project_id, "execution_package_id": None})
    if lab_unmapped > 0:
        alerts.append({"type": "unmapped_labor", "severity": "warning", "count": lab_unmapped, "message": f"{lab_unmapped} записа за труд без връзка към СМР"})

    # Margin drop check
    pkgs = await db.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "id": 1, "sale_total": 1, "actual_material_cost": 1, "actual_labor_cost": 1, "activity_name": 1}).to_list(200)
    for pkg in pkgs:
        sale = pkg.get("sale_total", 0)
        actual = (pkg.get("actual_material_cost", 0) or 0) + (pkg.get("actual_labor_cost", 0) or 0)
        if sale > 0 and actual > sale * 0.9:
            alerts.append({"type": "margin_drop", "severity": "critical", "package_id": pkg["id"], "message": f"{pkg.get('activity_name', '')}: разходи {round(actual, 2)} / продажба {sale} EUR"})

    return {"project_id": project_id, "alerts": alerts, "total": len(alerts)}


# ═══════════════════════════════════════════════════════════════════
# PHASE 7 — PROJECT RISK SUMMARY
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-risk/{project_id}")
async def get_project_risk(project_id: str, user: dict = Depends(require_m2)):
    """Consolidated project risk summary"""
    org_id = user["org_id"]
    flags = []
    explanations = []

    # Revenue risk
    accepted = await db.offers.count_documents({"project_id": project_id, "org_id": org_id, "status": "Accepted"})
    acts = await db.client_acts.count_documents({"project_id": project_id, "org_id": org_id, "status": "Accepted"})
    overdue = await db.invoices.count_documents({"project_id": project_id, "org_id": org_id, "status": "Overdue"})
    if accepted == 0:
        flags.append("no_accepted_offers")
        explanations.append("Няма одобрени оферти")
    if overdue > 0:
        flags.append("overdue_invoices")
        explanations.append(f"{overdue} просрочени фактури")

    # Labor risk
    pkgs = await db.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "planned_hours": 1, "used_hours": 1, "labor_budget_total": 1, "actual_labor_cost": 1}).to_list(200)
    over_hours = any(p.get("used_hours", 0) > (p.get("planned_hours") or 99999) for p in pkgs if p.get("planned_hours"))
    over_budget = any((p.get("actual_labor_cost", 0) or 0) > p.get("labor_budget_total", 0) > 0 for p in pkgs)
    if over_hours:
        flags.append("labor_over_hours")
        explanations.append("Надвишени планирани часове")
    if over_budget:
        flags.append("labor_over_budget")
        explanations.append("Надвишен бюджет за труд")

    # Material risk
    unmapped_mat = await db.material_entries.count_documents({"org_id": org_id, "project_id": project_id, "execution_package_id": None})
    if unmapped_mat > 5:
        flags.append("material_tracking_gaps")
        explanations.append(f"{unmapped_mat} нерпроследени материални движения")

    # Subcontract risk
    from app.routes.subcontractors import get_subcontract_metrics
    sub = await get_subcontract_metrics(org_id, project_id)
    if sub.get("available") and sub.get("payable", 0) > sub.get("certified", 1) * 0.5:
        flags.append("subcontract_payment_delayed")
        explanations.append("Забавено плащане към подизпълнители")

    # Overhead risk
    allocs = await db.project_overhead_alloc.count_documents({"org_id": org_id, "project_id": project_id})
    if allocs == 0:
        flags.append("overhead_not_allocated")
        explanations.append("Режийни не са разпределени")

    # Procurement risk
    from app.routes.revenue_snapshot import get_procurement_risk
    proc_risk = await get_procurement_risk(org_id, project_id)
    if proc_risk.get("available"):
        for pf in proc_risk.get("flags", []):
            flags.append(pf)
            if pf == "high_unrequested_materials":
                explanations.append(f"Висок дял незаявени материали ({proc_risk['not_requested_count']} от {proc_risk['planned_count']})")
            elif pf == "some_unrequested_materials":
                explanations.append(f"{proc_risk['not_requested_count']} материала не са заявени")

    # Progress risk
    from app.routes.budget_progress import get_progress_risk
    prog_risk = await get_progress_risk(org_id, project_id)
    if prog_risk.get("available"):
        for pf in prog_risk.get("flags", []):
            flags.append(pf)
            if pf == "no_progress_data":
                explanations.append("Няма въведен прогрес по пакети")
            elif pf == "insufficient_progress_data":
                explanations.append(f"Прогрес въведен за {prog_risk['with_progress']} от {prog_risk['total']} пакета")
            elif pf == "critical_progress_lag":
                explanations.append("Критично изоставане: нисък прогрес при висок разход")

    # Risk level
    critical = sum(1 for f in flags if f in ["overdue_invoices", "labor_over_budget", "margin_drop"])
    if critical >= 2:
        level = "high"
    elif len(flags) >= 3:
        level = "medium"
    elif len(flags) > 0:
        level = "low"
    else:
        level = "ok"

    return {
        "project_id": project_id,
        "risk_level": level,
        "risk_flags": flags,
        "explanations": explanations,
        "flag_count": len(flags),
    }
