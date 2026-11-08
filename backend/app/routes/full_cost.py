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
from fastapi import APIRouter, Depends, Header, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.tenancy.data_access import TenantData
from app.tenancy.settings_identity import EMPLOYEE_COST_CONFIG, settings_id
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.permissions.money_write import require_money_write, require_finance_read
from app.permissions.money_input import MoneyWrite, money_value  # SEC-01-C03
from app.routes.labor_smr import ACTIVE_LABOR_ROW

router = APIRouter(tags=["Full Cost / Overhead / Margin"])

def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)



# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — EMPLOYEE FULL COST MODEL
# ═══════════════════════════════════════════════════════════════════

@router.get("/employee-cost/{user_id}")
async def get_employee_cost_basis(
    user_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.employee_cost.read", module="M2", resource_type="employee_cost")),  # SEC-02 (R20-1): before any read
    user: dict = Depends(require_m2)):
    """Employee full cost model — net salary untouched, additional layers separate"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    profile = await tenant.employee_profiles.find_one({"org_id": org_id, "user_id": user_id}, {"_id": 0})

    if not profile:
        return {"user_id": user_id, "available": False, "reason": "no_profile"}

    ms = profile.get("monthly_salary") or 0
    days = profile.get("working_days_per_month") or 22
    hours = profile.get("standard_hours_per_day") or 8
    monthly_hours = days * hours

    net_salary = ms
    net_hour_cost = round(ms / monthly_hours, 2) if monthly_hours > 0 else None

    # Load org additional cost config (if set)
    # W0-03E-A2C: per-tenant settings row id + tenant-scoped read.
    cost_cfg = await TenantData.for_resolved_org(db, org_id).settings.find_one(
        {"_id": settings_id(EMPLOYEE_COST_CONFIG, org_id)})
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
    tenant = _tenant(user)
    row_id = settings_id(EMPLOYEE_COST_CONFIG, tenant.org_id)
    await tenant.settings.update_one(
        {"_id": row_id},
        {"$set": {
            "_id": row_id, "org_id": tenant.org_id,
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
async def create_overhead_snapshot(
    data: dict,
    _sec01: dict = Depends(require_money_write(
        "finance.overhead_snapshot.create", module="M2", resource_type="overhead_snapshot")),  # SEC-01: before any read/write
    user: dict = Depends(require_m2),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Create an overhead period snapshot entry"""
    tenant = _tenant(user)
    amount = money_value(data.get("amount"))  # SEC-01-C03: finite > 0, else 422 before any write
    mw = await MoneyWrite.begin(user, "finance.overhead_snapshot.create", idempotency_key, data)
    if mw.replay_id:
        return await tenant.overhead_snapshots.find_one({"id": mw.replay_id}, {"_id": 0})
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": mw.new_id("overhead_snapshot"),
        "org_id": user["org_id"],
        "category_code": data.get("category_code", "general"),
        "category_name": data.get("category_name", ""),
        "period_key": data.get("period_key", datetime.now().strftime("%Y-%m")),
        "amount": amount,
        "currency": "EUR",
        "allocation_basis": data.get("allocation_basis", "labor_hours"),
        "notes": data.get("notes", ""),
        "status": "active",
        "created_at": now,
        "created_by": user["id"],
    }
    async with mw:
        async with mw.insert_once():
            await tenant.overhead_snapshots.insert_one(mw.unique(entry))
        mw.result_id = entry["id"]
    return {k: v for k, v in entry.items() if k != "_id"}


@router.get("/overhead-snapshots")
async def list_overhead_snapshots(
    _sec02: dict = Depends(require_finance_read(
        "finance.overhead_snapshot.read", module="M2", resource_type="overhead_snapshot")),  # SEC-02 (R20-1): before any read
    period_key: Optional[str] = None, user: dict = Depends(require_m2)):
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if period_key: q["period_key"] = period_key
    return await tenant.overhead_snapshots.find(q, {"_id": 0}).sort("period_key", -1).to_list(200)


@router.get("/overhead-snapshots/aggregate")
async def aggregate_overhead(
    _sec02: dict = Depends(require_finance_read(
        "finance.overhead_snapshot_aggregate.read", module="M2", resource_type="overhead_snapshot_aggregate")),  # SEC-02 (R20-1): before any read
    period_key: Optional[str] = None, user: dict = Depends(require_m2)):
    """Aggregate overhead by period and category"""
    tenant = _tenant(user)
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
    results = await tenant.overhead_snapshots.aggregate(pipeline).to_list(200)

    # Also aggregate from legacy overhead_transactions
    legacy = await tenant.overhead_transactions.find({"org_id": org_id}, {"_id": 0, "date": 1, "amount": 1, "category": 1}).to_list(500)
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
async def compute_overhead_allocation(
    project_id: str,
    data: dict = {},
    _sec01: dict = Depends(require_money_write(
        "finance.overhead_allocation.execute", module='M2',
        resource_type="project_overhead_alloc")),  # SEC-01-C02 (R14, FG-30): before any read
    user: dict = Depends(require_m2),
):
    """Compute overhead allocation for a project based on labor hours share"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    period_key = data.get("period_key", datetime.now().strftime("%Y-%m"))

    # FG-89 (CLAUDE.md §16: no second source of truth): this route no longer computes or
    # stores its own allocation. Overhead is allocated ONLY by FLOW-024 / OH-01
    # (/overhead/snapshots/{id}/allocate: versioned, keyed, audited); this answer is a
    # read-only projection of the project's current (published) OH-01 allocation.
    from app.services.overhead_lifecycle import project_overhead_current, recalculating_fields
    cur = await project_overhead_current(tenant, project_id)
    return {"ok": True, "allocated": cur["amount"], "period": period_key,
            "source": "overhead_allocation_oh01", "recalculating": cur["recalculating"],
            **recalculating_fields(cur["recalculating"]),  # FG-116 (R38)
            "read_only": True,
            "message": "Режийните се разпределят от модул Режийни (snapshot → разпределение)"}


# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — EXECUTION PACKAGE NET MARGIN
# (extends material_smr.py financial endpoints)
# ═══════════════════════════════════════════════════════════════════

@router.get("/execution-packages/{pkg_id}/net-financial")
async def get_package_net_financial(
    pkg_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.package_net_financial.read", module="M2", resource_type="package_net_financial")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Package net financial with overhead and net margin"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    pkg = await tenant.execution_packages.find_one({"id": pkg_id, "org_id": org_id}, {"_id": 0})
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    sale = pkg.get("sale_total", 0)
    # 5C-C20 F-10 — canonical material actual at read time (no recompute).
    from app.services.canonical_material_cost import package_material_split
    split = await package_material_split(tenant, org_id, pkg)
    mat = split["total"]          # consumption + фира, once
    lab = pkg.get("actual_labor_cost", 0)
    # FG-89: the package's share of the project's CURRENT OH-01 allocation, by used hours,
    # computed on read (no stored second figure)
    from app.services.overhead_lifecycle import project_overhead_current, recalculating_fields
    _cur = (await project_overhead_current(tenant, pkg.get("project_id"))) \
        if pkg.get("project_id") else {"amount": 0, "recalculating": False}
    project_oh = _cur["amount"]
    siblings = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": pkg.get("project_id")}, {"_id": 0, "used_hours": 1}
    ).to_list(200) if pkg.get("project_id") else []
    sib_hours = sum(p.get("used_hours", 0) or 0 for p in siblings)
    overhead = round(project_oh * (pkg.get("used_hours", 0) or 0) / sib_hours, 2) if sib_hours > 0 else 0

    sub_lines = await tenant.subcontractor_package_lines.find(
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
            "material": split["material"], "waste": split["waste"],
            "labor": lab, "subcontract": round(sub, 2),
            "gross_cost": gross_cost, "overhead": overhead, "total_cost": total_cost,
            **recalculating_fields(_cur["recalculating"]),  # FG-116 (R38)
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
async def get_project_net_profit(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_net_profit.read", module="M2", resource_type="project_net_profit")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Extended project profit with overhead, gross vs net margin, expected vs actual"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    project = await tenant.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Revenue
    accepted_offers = await tenant.offers.find({"project_id": project_id, "org_id": org_id, "status": "Accepted"}, {"_id": 0, "subtotal": 1}).to_list(100)
    contracted = sum(o.get("subtotal", 0) for o in accepted_offers)

    accepted_acts = await tenant.client_acts.find({"project_id": project_id, "org_id": org_id, "status": "Accepted"}, {"_id": 0, "subtotal": 1}).to_list(100)
    earned = sum(a.get("subtotal", 0) for a in accepted_acts)

    invoices = await tenant.invoices.find({"project_id": project_id, "org_id": org_id, "direction": "Issued", "status": {"$nin": ["Draft", "Cancelled"]}}, {"_id": 0, "subtotal": 1, "paid_amount": 1}).to_list(100)
    billed = sum(i.get("subtotal", 0) for i in invoices)
    collected = sum(i.get("paid_amount", 0) for i in invoices)

    # Material
    from app.routes.material_smr import get_material_summary_for_project
    mat_summary = await get_material_summary_for_project(org_id, project_id)
    mat_cost = mat_summary["total_cost"]                 # consumption + фира, once
    mat_waste = mat_summary.get("waste_cost", 0.0) or 0.0  # 5C-C21 F-12

    # Labor
    from app.routes.labor_smr import get_labor_summary_for_project
    lab_summary = await get_labor_summary_for_project(org_id, project_id)
    lab_cost = lab_summary["total_cost"]

    # Subcontract
    from app.routes.subcontractors import get_subcontract_metrics
    sub_metrics = await get_subcontract_metrics(org_id, project_id)
    sub_certified = sub_metrics.get("certified", 0) if sub_metrics.get("available") else 0

    # Overhead
    # FG-89: the project's current OH-01 allocation — the single overhead source
    from app.services.overhead_lifecycle import project_overhead_current
    _oh = await project_overhead_current(tenant, project_id)
    overhead, allocs = _oh["amount"], _oh["rows"]
    from app.services.overhead_lifecycle import recalculating_fields

    # Budget from execution packages
    pkgs = await tenant.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "budget_total": 1}).to_list(200)
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
        "costs": {"material": round(mat_cost - mat_waste, 2), "waste": round(mat_waste, 2), "labor": lab_cost, "subcontract": round(sub_certified, 2), "gross_cost": gross_cost, "overhead": round(overhead, 2), "total_cost": total_cost,
                  **recalculating_fields(_oh["recalculating"])},  # FG-116 (R38)
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
async def get_financial_alerts(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_financial_alert.read", module="M2", resource_type="project_financial_alert")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Core financial alerts for a project"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    alerts = []

    # Overhead
    from app.services.overhead_lifecycle import project_overhead_current  # FG-89
    allocs = len((await project_overhead_current(tenant, project_id))["rows"])
    if allocs == 0:
        alerts.append({"type": "overhead_not_allocated", "severity": "warning", "message": "Режийни разходи не са разпределени към проекта"})

    # Subcontract payable
    from app.routes.subcontractors import get_subcontract_metrics
    sub = await get_subcontract_metrics(org_id, project_id)
    if sub.get("available") and sub.get("payable", 0) > 0:
        alerts.append({"type": "subcontract_payable", "severity": "info", "amount": sub["payable"], "message": f"Дължимо към подизпълнители: {sub['payable']} EUR"})

    # Client receivable
    invoices = await tenant.invoices.find(
        {"project_id": project_id, "org_id": org_id, "direction": "Issued", "status": {"$in": ["Sent", "PartiallyPaid", "Overdue"]}},
        {"_id": 0, "remaining_amount": 1}
    ).to_list(100)
    receivable = sum(i.get("remaining_amount", 0) for i in invoices)
    if receivable > 0:
        overdue = await tenant.invoices.count_documents({"project_id": project_id, "org_id": org_id, "status": "Overdue"})
        sev = "critical" if overdue > 0 else "info"
        alerts.append({"type": "client_receivable", "severity": sev, "amount": round(receivable, 2), "overdue_count": overdue, "message": f"Вземания: {round(receivable, 2)} EUR ({overdue} просрочени)"})

    # Material warnings
    mat_warn = await tenant.material_entries.count_documents({"org_id": org_id, "project_id": project_id, "execution_package_id": None})
    if mat_warn > 0:
        alerts.append({"type": "unmapped_material", "severity": "warning", "count": mat_warn, "message": f"{mat_warn} материални записа без връзка към СМР"})

    # Labor warnings
    lab_unmapped = await tenant.labor_entries.count_documents({"org_id": org_id, "project_id": project_id, "execution_package_id": None, **ACTIVE_LABOR_ROW})
    if lab_unmapped > 0:
        alerts.append({"type": "unmapped_labor", "severity": "warning", "count": lab_unmapped, "message": f"{lab_unmapped} записа за труд без връзка към СМР"})

    # Margin drop check
    # 5C-C22 — package material actual from the ONE shared helper (read
    # time), not the `actual_material_cost` cache.
    from app.services.canonical_material_cost import project_material_cost, split_for_package
    mat_cost = await project_material_cost(tenant, org_id, project_id)
    pkgs = await tenant.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "id": 1, "sale_total": 1, "actual_labor_cost": 1, "activity_name": 1}).to_list(200)
    for pkg in pkgs:
        sale = pkg.get("sale_total", 0)
        actual = split_for_package(mat_cost, pkg["id"])["total"] + (pkg.get("actual_labor_cost", 0) or 0)
        if sale > 0 and actual > sale * 0.9:
            alerts.append({"type": "margin_drop", "severity": "critical", "package_id": pkg["id"], "message": f"{pkg.get('activity_name', '')}: разходи {round(actual, 2)} / продажба {sale} EUR"})

    return {"project_id": project_id, "alerts": alerts, "total": len(alerts)}


# ═══════════════════════════════════════════════════════════════════
# PHASE 7 — PROJECT RISK SUMMARY
# ═══════════════════════════════════════════════════════════════════

@router.get("/project-risk/{project_id}")
async def get_project_risk(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_risk.read", module="M2", resource_type="project_risk")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(require_m2)):
    """Consolidated project risk summary"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    flags = []
    explanations = []

    # Revenue risk
    accepted = await tenant.offers.count_documents({"project_id": project_id, "org_id": org_id, "status": "Accepted"})
    acts = await tenant.client_acts.count_documents({"project_id": project_id, "org_id": org_id, "status": "Accepted"})
    overdue = await tenant.invoices.count_documents({"project_id": project_id, "org_id": org_id, "status": "Overdue"})
    if accepted == 0:
        flags.append("no_accepted_offers")
        explanations.append("Няма одобрени оферти")
    if overdue > 0:
        flags.append("overdue_invoices")
        explanations.append(f"{overdue} просрочени фактури")

    # Labor risk
    pkgs = await tenant.execution_packages.find({"org_id": org_id, "project_id": project_id}, {"_id": 0, "planned_hours": 1, "used_hours": 1, "labor_budget_total": 1, "actual_labor_cost": 1}).to_list(200)
    over_hours = any(p.get("used_hours", 0) > (p.get("planned_hours") or 99999) for p in pkgs if p.get("planned_hours"))
    over_budget = any((p.get("actual_labor_cost", 0) or 0) > p.get("labor_budget_total", 0) > 0 for p in pkgs)
    if over_hours:
        flags.append("labor_over_hours")
        explanations.append("Надвишени планирани часове")
    if over_budget:
        flags.append("labor_over_budget")
        explanations.append("Надвишен бюджет за труд")

    # Material risk
    unmapped_mat = await tenant.material_entries.count_documents({"org_id": org_id, "project_id": project_id, "execution_package_id": None})
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
    from app.services.overhead_lifecycle import project_overhead_current  # FG-89
    allocs = len((await project_overhead_current(tenant, project_id))["rows"])
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
