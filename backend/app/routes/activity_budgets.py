"""
Activity Budgets Routes - Per-project budget tracking by activity type/subtype.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from app.db import db
from app.services.labor_cost import project_labor_cost
from app.tenancy import project_team
from app.deps.auth import get_current_user, can_access_project, can_manage_project
from app.permissions.money_write import (strip_for_budget_view, strip_money_for_non_finance,
                                         FINANCE_WRITE_ROLES)
from app.utils.audit import log_audit
from app.tenancy.guard import TenantContext
from app.permissions.deps import require_permission

router = APIRouter(tags=["Activity Budgets"])

# Activity type options (UI dropdown)
ACTIVITY_TYPES = [
    "Общо",
    "Земни",
    "Кофраж",
    "Арматура",
    "Бетон",
    "Зидария",
    "Покрив",
    "Изолации",
    "Фасада",
    "Инсталации",
    "Довършителни",
    "Други",
]

# ── Models ──────────────────────────────────────────────────────────

class ActivityBudgetCreate(BaseModel):
    type: str
    subtype: str = ""
    labor_budget: float = 0
    materials_budget: float = 0
    coefficient: float = 1.0
    planned_people_per_day: Optional[int] = None
    planned_target_days: Optional[int] = None
    notes: Optional[str] = None

class ActivityBudgetUpdate(BaseModel):
    labor_budget: Optional[float] = None
    materials_budget: Optional[float] = None
    coefficient: Optional[float] = None
    planned_people_per_day: Optional[int] = None
    planned_target_days: Optional[int] = None
    notes: Optional[str] = None

# ── Endpoints ───────────────────────────────────────────────────────

@router.get("/activity-types")
async def get_activity_types(user: dict = Depends(get_current_user)):
    """Get list of standard activity types for dropdown."""
    return {"types": ACTIVITY_TYPES}


@router.get("/projects/{project_id}/activity-budgets")
@strip_for_budget_view   # SEC-02-B (R20-5B)
async def list_activity_budgets(
    project_id: str,
    ctx: TenantContext = Depends(require_permission(
        "budget.read", module="M2", scope="project",
        scope_id_param="project_id", resource_type="activity_budget",
        # Legacy behavior (used in off/shadow): project_team membership.
        # SEC-02-C (R20, B-D1): the finance roles read every project's budget.
        legacy_check=lambda user, request: (user.get("role") in FINANCE_WRITE_ROLES
                                            or can_access_project(user, request.path_params["project_id"])),
    )),
):
    """Get all activity budgets for a project."""
    # W0-02 PR-04: read from the SAME tenant the request was authorized for
    # (legacy compat context in off/shadow == user["org_id"] + global db).
    tdb = await ctx.db()
    budgets = await tdb.activity_budgets.find(
        {**ctx.owner_filter(), "project_id": project_id},
        {"_id": 0}
    ).sort([("type", 1), ("subtype", 1)]).to_list(100)

    return {"items": budgets}


@router.post("/projects/{project_id}/activity-budgets", status_code=201)
async def upsert_activity_budget(
    project_id: str,
    data: ActivityBudgetCreate,
    user: dict = Depends(get_current_user)
):
    """Create or update activity budget (upsert by type+subtype)."""
    tenant = _tenant(user)
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    project = await tenant.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if exists (upsert key: org_id, project_id, type, subtype)
    existing = await tenant.activity_budgets.find_one({
        "org_id": user["org_id"],
        "project_id": project_id,
        "type": data.type,
        "subtype": data.subtype or "",
    })
    
    if existing:
        # Update
        update = {
            "labor_budget": data.labor_budget,
            "materials_budget": data.materials_budget,
            "coefficient": data.coefficient,
            "planned_people_per_day": data.planned_people_per_day,
            "planned_target_days": data.planned_target_days,
            "notes": data.notes,
            "updated_at": now,
        }
        await tenant.activity_budgets.update_one({"id": existing["id"]}, {"$set": update})
        await log_audit(user["org_id"], user["id"], user["email"], "updated", "activity_budget", existing["id"], update)
        return await tenant.activity_budgets.find_one({"id": existing["id"]}, {"_id": 0})
    else:
        # Create
        budget = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "project_id": project_id,
            "type": data.type,
            "subtype": data.subtype or "",
            "labor_budget": data.labor_budget,
            "materials_budget": data.materials_budget,
            "coefficient": data.coefficient,
            "planned_people_per_day": data.planned_people_per_day,
            "planned_target_days": data.planned_target_days,
            "notes": data.notes,
            "created_at": now,
            "updated_at": now,
        }
        await tenant.activity_budgets.insert_one(budget)
        await log_audit(user["org_id"], user["id"], user["email"], "created", "activity_budget", budget["id"], {
            "type": data.type, "subtype": data.subtype
        })
        return {k: v for k, v in budget.items() if k != "_id"}


@router.delete("/projects/{project_id}/activity-budgets/{budget_id}")
async def delete_activity_budget(project_id: str, budget_id: str, user: dict = Depends(get_current_user)):
    """Delete an activity budget."""
    tenant = _tenant(user)
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    budget = await tenant.activity_budgets.find_one({
        "id": budget_id,
        "org_id": user["org_id"],
        "project_id": project_id,
    })
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    
    await tenant.activity_budgets.delete_one({"id": budget_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "activity_budget", budget_id, {})
    return {"ok": True}


@router.get("/projects/{project_id}/activity-budget-summary")
@strip_for_budget_view(labor_source="daily_logs")   # FG-63: spent = daily work log hours   # SEC-02-B (R20-5B, FG-43)
async def get_activity_budget_summary(project_id: str, user: dict = Depends(get_current_user)):
    """
    Get budget vs spent summary grouped by type/subtype.
    
    Returns for each (type, subtype):
    - laborBudget, materialsBudget
    - laborSpent, materialsSpent
    - laborRemaining, materialsRemaining
    - percentLaborUsed, percentMaterialsUsed
    """
    tenant = _tenant(user)
    # SEC-02-B (FG-43, R20): the finance roles read the budget screen of every project.
    if user.get("role") not in FINANCE_WRITE_ROLES and not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    org_id = user["org_id"]
    
    # 1. Get all budgets for project
    budgets = await tenant.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0}
    ).to_list(100)
    
    budget_map = {}
    for b in budgets:
        key = (b["type"], b.get("subtype", ""))
        budget_map[key] = {
            "type": b["type"],
            "subtype": b.get("subtype", ""),
            "labor_budget": b.get("labor_budget", 0),
            "materials_budget": b.get("materials_budget", 0),
        }
    
    # 2. Calculate spent from approved offer lines
    # Get all offers for this project
    offers = await tenant.offers.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["Accepted", "Sent"]}},
        {"_id": 0, "lines": 1}
    ).to_list(100)
    
    # Group by type/subtype
    spent_map = {}
    for offer in offers:
        for line in offer.get("lines", []):
            act_type = line.get("activity_type", "Общо")
            act_subtype = line.get("activity_subtype", "")
            key = (act_type, act_subtype)
            
            if key not in spent_map:
                spent_map[key] = {"labor": 0, "materials": 0}
            
            # LAB-01 / R31: an offer line's labor is the BUDGET, never labor spent.
            spent_map[key]["materials"] += line.get("line_material_cost", 0)
    
    # 3. LAB-01 / R31 (FLOW-019): labor spent = real labor cost from APPROVED report lines
    # (one labor calculation), keyed by the SMR the report names. No default rate 25 —
    # a missing rate is a DQ warning with 0. DOWNTIME is its own row, not inside an SMR.
    labor = await project_labor_cost(org_id, project_id)
    for smr, v in labor["by_smr"].items():
        if not (v["labor"] or v["hours"] or v["downtime"] or v["downtime_hours"]):
            continue
        key = (smr, "")
        if key not in spent_map:
            spent_map[key] = {"labor": 0, "materials": 0}
        spent_map[key]["labor"] += v["labor"] + v["downtime"]   # R62 / FG-422: one figure
    
    # 4. Combine budgets and spent
    all_keys = set(budget_map.keys()) | set(spent_map.keys())
    
    result = []
    totals = {
        "labor_budget": 0,
        "materials_budget": 0,
        "labor_spent": 0,
        "materials_spent": 0,
    }
    
    for key in sorted(all_keys):
        act_type, act_subtype = key
        
        budget = budget_map.get(key, {})
        spent = spent_map.get(key, {"labor": 0, "materials": 0})
        
        labor_budget = budget.get("labor_budget", 0)
        materials_budget = budget.get("materials_budget", 0)
        labor_spent = round(spent["labor"], 2)
        materials_spent = round(spent["materials"], 2)
        
        labor_remaining = round(labor_budget - labor_spent, 2)
        materials_remaining = round(materials_budget - materials_spent, 2)
        
        percent_labor = round((labor_spent / labor_budget * 100), 1) if labor_budget > 0 else 0
        percent_materials = round((materials_spent / materials_budget * 100), 1) if materials_budget > 0 else 0
        
        row = {
            "type": act_type,
            "subtype": act_subtype,
            "labor_budget": labor_budget,
            "materials_budget": materials_budget,
            "labor_spent": labor_spent,
            "materials_spent": materials_spent,
            "labor_remaining": labor_remaining,
            "materials_remaining": materials_remaining,
            "percent_labor_used": percent_labor,
            "percent_materials_used": percent_materials,
            "has_budget": key in budget_map,
        }
        result.append(row)
        
        totals["labor_budget"] += labor_budget
        totals["materials_budget"] += materials_budget
        totals["labor_spent"] += labor_spent
        totals["materials_spent"] += materials_spent
    
    totals["labor_remaining"] = round(totals["labor_budget"] - totals["labor_spent"], 2)
    totals["materials_remaining"] = round(totals["materials_budget"] - totals["materials_spent"], 2)
    totals["percent_labor_used"] = round((totals["labor_spent"] / totals["labor_budget"] * 100), 1) if totals["labor_budget"] > 0 else 0
    totals["percent_materials_used"] = round((totals["materials_spent"] / totals["materials_budget"] * 100), 1) if totals["materials_budget"] > 0 else 0
    
    totals["downtime_spent"] = labor["downtime_total"]  # R62: of which downtime (inside labor_spent)
    totals["labor_dq_warning_count"] = len(labor["dq_warnings"])
    return {
        "items": result,
        "totals": totals,
    }


import math
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

# ── Helpers ─────────────────────────────────────────────────────────

DEFAULT_DAILY_WAGE = 200  # BGN fallback

async def compute_avg_daily_wage(org_id: str, project_id: str) -> float:
    """Compute average daily wage from project team's employee profiles."""
    tenant = TenantData.for_resolved_org(db, org_id)
    # W0-03E-A2: one relation accessor; the tenant predicate is applied last.
    team = await project_team.project_rows(
        project_team.tenant_for_org(db, org_id), [project_id], {"_id": 0, "user_id": 1},
        limit=100)
    if not team:
        return DEFAULT_DAILY_WAGE

    rates = []
    for m in team:
        profile = await tenant.employee_profiles.find_one(
            {"org_id": org_id, "user_id": m["user_id"]}, {"_id": 0}
        )
        if not profile:
            continue
        pay = (profile.get("pay_type") or "Monthly").strip()
        if pay == "Hourly":
            hr = float(profile.get("hourly_rate") or 0)
        elif pay == "Daily":
            hr = float(profile.get("daily_rate") or profile.get("base_salary") or 0) / 8
        else:
            ms = float(profile.get("monthly_salary") or profile.get("base_salary") or 0)
            days = int(profile.get("working_days_per_month") or 22)
            hours = int(profile.get("standard_hours_per_day") or 8)
            hr = ms / (days * hours) if days * hours > 0 else 0
        if hr > 0:
            rates.append(hr)

    if not rates:
        return DEFAULT_DAILY_WAGE
    avg_hourly = sum(rates) / len(rates)
    return round(avg_hourly * 8, 2)


async def get_work_session_burn(org_id: str, project_id: str, activity_type: str = None) -> dict:
    """Get actual labor cost/hours from work_sessions for a project (and optional activity filter)."""
    # LAB-01 / R31: real labor from APPROVED report lines via the one labor calculation
    # (was work_sessions incl. unapproved time). DOWNTIME is not burn of an SMR budget;
    # it is returned apart as downtime_cost (project level only).
    # R62 / FG-422: ONE figure — THE labor cost "total" (labor + downtime) for the project,
    # and labor + downtime of the SMR for an SMR, so the SMR rows add up to the total.
    labor = await project_labor_cost(org_id, project_id)
    if activity_type:
        v = labor["by_smr"].get(activity_type) or {}
        return {"actual_hours": round(v.get("hours", 0) + v.get("downtime_hours", 0), 2),
                "actual_cost": round(v.get("labor", 0) + v.get("downtime", 0), 2),
                "downtime_cost": round(v.get("downtime", 0), 2)}
    return {"actual_hours": round(labor["approved_hours"] + labor.get("downtime_hours", 0), 2),
            "actual_cost": labor["total"], "downtime_cost": labor["downtime_total"]}


# ── Forecast Endpoint ──────────────────────────────────────────────

@router.get("/activity-budgets/{budget_id}/forecast")
async def get_forecast(budget_id: str, user: dict = Depends(get_current_user)):
    """Compute man_days, min_days, min_people, avg_daily_wage for an activity budget."""
    tenant = _tenant(user)
    budget = await tenant.activity_budgets.find_one(
        {"id": budget_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    labor_budget = budget.get("labor_budget", 0)
    coefficient = budget.get("coefficient", 1.0) or 1.0
    ppd = budget.get("planned_people_per_day")
    ptd = budget.get("planned_target_days")

    from app.services.budget_formula import calculate_budget_formula
    result = await calculate_budget_formula(
        labor_budget, coefficient, org_id=user["org_id"], project_id=budget["project_id"]
    )
    man_days = result["planned_man_days"]
    avg_daily = result["avg_daily_wage_used"]
    min_days = math.ceil(man_days / ppd) if ppd and ppd > 0 else None
    min_people = math.ceil(man_days / ptd) if ptd and ptd > 0 else None

    return {
        "budget_id": budget_id,
        "labor_budget": labor_budget,
        "avg_daily_wage": avg_daily,
        "coefficient": coefficient,
        "man_days": man_days,
        "planned_people_per_day": ppd,
        "min_days": min_days,
        "planned_target_days": ptd,
        "min_people": min_people,
    }


# ── Snapshot Calculation ───────────────────────────────────────────

@router.post("/projects/{project_id}/activity-budgets/{budget_id}/calculate-snapshot")
@strip_money_for_non_finance   # SEC-02-E (R20-5M, sweep)
async def calculate_snapshot(project_id: str, budget_id: str, user: dict = Depends(get_current_user)):
    """Calculate and persist man-hours/man-days snapshot for a budget line."""
    tenant = _tenant(user)
    budget = await tenant.activity_budgets.find_one(
        {"id": budget_id, "org_id": user["org_id"], "project_id": project_id}, {"_id": 0}
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    from app.services.budget_formula import calculate_budget_formula
    result = await calculate_budget_formula(
        budget.get("labor_budget", 0),
        budget.get("coefficient", 1.0),
        org_id=user["org_id"], project_id=project_id,
    )

    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "planned_man_hours": result["planned_man_hours"],
        "planned_man_days": result["planned_man_days"],
        "akord": result["akord"],
        "avg_daily_wage_at_calc": result["avg_daily_wage_used"],
        "hours_per_day_at_calc": result["hours_per_day_used"],
        "coefficient_at_calc": result["coefficient_used"],
        "currency_at_calc": "EUR",
        "snapshot_calculated_at": now,
        "updated_at": now,
    }
    await tenant.activity_budgets.update_one({"id": budget_id}, {"$set": snapshot})
    return await tenant.activity_budgets.find_one({"id": budget_id}, {"_id": 0})


@router.post("/projects/{project_id}/activity-budgets/calculate-all-snapshots")
@strip_money_for_non_finance   # SEC-02-E (R20-5M, sweep)
async def calculate_all_snapshots(project_id: str, user: dict = Depends(get_current_user)):
    """Calculate snapshots for ALL budget lines in a project."""
    tenant = _tenant(user)
    from app.services.budget_formula import calculate_budget_formula_sync
    org_id = user["org_id"]
    budgets = await tenant.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    # Compute wage once for the project
    avg_daily = await compute_avg_daily_wage(org_id, project_id)
    now = datetime.now(timezone.utc).isoformat()
    updated = 0

    for b in budgets:
        r = calculate_budget_formula_sync(
            b.get("labor_budget", 0), b.get("coefficient", 1.0), avg_daily
        )
        await tenant.activity_budgets.update_one({"id": b["id"]}, {"$set": {
            "planned_man_hours": r["planned_man_hours"],
            "planned_man_days": r["planned_man_days"],
            "akord": r["akord"],
            "avg_daily_wage_at_calc": r["avg_daily_wage_used"],
            "hours_per_day_at_calc": r["hours_per_day_used"],
            "coefficient_at_calc": r["coefficient_used"],
            "currency_at_calc": "EUR",
            "snapshot_calculated_at": now,
            "updated_at": now,
        }})
        updated += 1

    return {"ok": True, "updated": updated, "avg_daily_wage": avg_daily}


# ── Burn Tracking Endpoint ─────────────────────────────────────────

@router.get("/activity-budgets/{budget_id}/burn")
async def get_burn(budget_id: str, user: dict = Depends(get_current_user)):
    """Burn tracking: actual vs budget from work_sessions. Uses snapshot if available."""
    tenant = _tenant(user)
    budget = await tenant.activity_budgets.find_one(
        {"id": budget_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    labor_budget = budget.get("labor_budget", 0)
    burn = await get_work_session_burn(user["org_id"], budget["project_id"], budget.get("type"))

    burn_pct = round(burn["actual_cost"] / labor_budget * 100, 1) if labor_budget > 0 else 0
    remaining = round(labor_budget - burn["actual_cost"], 2)
    on_track = burn_pct <= 100

    # Use snapshot for planned hours if available, else on-the-fly via budget_formula
    planned_man_hours = budget.get("planned_man_hours")
    if planned_man_hours is None:
        from app.services.budget_formula import calculate_budget_formula
        r = await calculate_budget_formula(
            labor_budget, budget.get("coefficient", 1.0),
            org_id=user["org_id"], project_id=budget["project_id"],
        )
        planned_man_hours = r["planned_man_hours"]

    burn_hours_pct = round(burn["actual_hours"] / planned_man_hours * 100, 1) if planned_man_hours > 0 else 0

    return {
        "budget_id": budget_id,
        "labor_budget": labor_budget,
        "actual_cost": burn["actual_cost"],
        "actual_hours": burn["actual_hours"],
        "actual_man_days": round(burn["actual_hours"] / 8, 2),
        "planned_man_hours": round(planned_man_hours, 2),
        "budget_remaining": remaining,
        "burn_pct": burn_pct,
        "burn_hours_pct": burn_hours_pct,
        "on_track": on_track,
        "snapshot_used": budget.get("planned_man_hours") is not None,
    }


# ── Project Budget Health ──────────────────────────────────────────

@router.get("/projects/{project_id}/budget-health")
@strip_for_budget_view   # SEC-02-B (R20-5B)
async def get_budget_health(project_id: str, user: dict = Depends(get_current_user)):
    """Aggregated burn for entire project across all activity budgets."""
    tenant = _tenant(user)
    # SEC-02-C (R20, B-D1): the finance roles read every project's budget.
    if user.get("role") not in FINANCE_WRITE_ROLES and not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")

    org_id = user["org_id"]
    budgets = await tenant.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(100)

    total_budget = 0
    total_spent = 0
    activities = []

    # Get all work session costs for the project
    all_burn = await get_work_session_burn(org_id, project_id)

    for b in budgets:
        lb = b.get("labor_budget", 0)
        total_budget += lb
        burn = await get_work_session_burn(org_id, project_id, b.get("type"))
        spent = burn["actual_cost"]
        bp = round(spent / lb * 100, 1) if lb > 0 else 0
        status = "on_track" if bp <= 80 else ("warning" if bp <= 100 else "over_budget")
        activities.append({
            "type": b["type"],
            "subtype": b.get("subtype", ""),
            "budget": lb,
            "spent": spent,
            "burn_pct": bp,
            "status": status,
        })

    # R62 / FG-422: the project's "spent" is THE labor cost total (also labor of an SMR
    # without a budget line), the same number as the alarm and every other reader
    total_spent = all_burn["actual_cost"]
    total_remaining = round(total_budget - total_spent, 2)
    total_burn = round(total_spent / total_budget * 100, 1) if total_budget > 0 else 0

    return {
        "project_id": project_id,
        "total_budget": round(total_budget, 2),
        "total_spent": round(total_spent, 2),
        "total_remaining": total_remaining,
        "burn_pct": total_burn,
        "activities": activities,
    }


# ── Earned Value Analysis ──────────────────────────────────────────

@router.get("/projects/{project_id}/earned-value")
async def get_earned_value(project_id: str, user: dict = Depends(get_current_user)):
    """Earned Value Analysis: BAC, EV, AC, PV, CPI, SPI, EAC, ETC, VAC."""
    tenant = _tenant(user)
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")

    org_id = user["org_id"]

    # BAC = total labor_budget
    budgets = await tenant.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(100)
    bac = sum(b.get("labor_budget", 0) for b in budgets)

    # AC = actual labor cost from work_sessions
    burn = await get_work_session_burn(org_id, project_id)
    ac = burn["actual_cost"]

    # Progress from execution packages or budget_progress
    pkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "progress_percent": 1}
    ).to_list(200)
    if pkgs:
        progress_pct = sum(p.get("progress_percent", 0) for p in pkgs) / len(pkgs) / 100
    else:
        progress_pct = 0

    # EV = BAC × progress_pct
    ev = round(bac * progress_pct, 2)

    # PV = BAC × (elapsed / planned) — linear
    project = await tenant.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "start_date": 1, "end_date": 1})
    now = datetime.now(timezone.utc)
    pv = 0
    if project and project.get("start_date") and project.get("end_date"):
        try:
            sd = datetime.fromisoformat(project["start_date"].replace("Z", "+00:00")) if isinstance(project["start_date"], str) else project["start_date"]
            ed = datetime.fromisoformat(project["end_date"].replace("Z", "+00:00")) if isinstance(project["end_date"], str) else project["end_date"]
            if hasattr(sd, 'tzinfo') and sd.tzinfo is None:
                from datetime import timezone as tz
                sd = sd.replace(tzinfo=tz.utc)
            if hasattr(ed, 'tzinfo') and ed.tzinfo is None:
                from datetime import timezone as tz
                ed = ed.replace(tzinfo=tz.utc)
            total_days = max((ed - sd).days, 1)
            elapsed_days = max((now - sd).days, 0)
            elapsed_ratio = min(elapsed_days / total_days, 1.0)
            pv = round(bac * elapsed_ratio, 2)
        except Exception:
            pv = 0

    # Indices
    cpi = round(ev / ac, 2) if ac > 0 else 0
    spi = round(ev / pv, 2) if pv > 0 else 0
    eac = round(bac / cpi, 2) if cpi > 0 else 0
    etc = round(eac - ac, 2) if eac > 0 else 0
    vac = round(bac - eac, 2)

    status = "on_track"
    if cpi < 0.8 or spi < 0.8:
        status = "at_risk"
    if ac > bac:
        status = "over_budget"

    return {
        "project_id": project_id,
        "BAC": round(bac, 2),
        "EV": ev,
        "AC": round(ac, 2),
        "PV": pv,
        "CPI": cpi,
        "SPI": spi,
        "EAC": eac,
        "ETC": etc,
        "VAC": vac,
        "progress_pct": round(progress_pct * 100, 1),
        "status": status,
    }


# ═══════════════════════════════════════════════════════════════════
# ACTIVITIES OVERVIEW (Фаза 3.1)
# ═══════════════════════════════════════════════════════════════════

@router.get("/projects/{project_id}/activities-overview")
@strip_for_budget_view   # SEC-02-B (R20-5B, FG-43)
async def get_activities_overview(project_id: str, user: dict = Depends(get_current_user)):
    """Full activities table: budget + actuals + extras + status."""
    tenant = _tenant(user)
    # SEC-02-B (FG-43, R20): the finance roles read the budget screen of every project.
    if user.get("role") not in FINANCE_WRITE_ROLES and not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")

    org_id = user["org_id"]
    from app.services.budget_formula import calculate_budget_formula_sync

    # 1. Budget lines
    budgets = await tenant.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(200)

    # 2. Actual hours/cost per SMR — R62 (FG-421): THE labor cost (approved reports +
    # Owner-approved manual rows; labor + downtime), not the work_sessions
    labor = await project_labor_cost(org_id, project_id)
    actuals_by_type = {}
    for smr, v in labor["by_smr"].items():
        key = (smr or "").lower().strip()
        if not key:
            continue
        a_ = actuals_by_type.setdefault(key, {"hours": 0, "cost": 0})
        a_["hours"] += v["hours"] + v["downtime_hours"]
        a_["cost"] += v["labor"] + v["downtime"]

    # 3. Extra work (missing_smr + extra_work_drafts)
    missing = await tenant.missing_smr.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$nin": ["closed", "rejected_by_client"]}},
        {"_id": 0, "id": 1, "smr_type": 1, "activity_type": 1, "qty": 1, "unit": 1, "notes": 1},
    ).to_list(200)

    # 4. Build activities list
    activities = []
    seen_types = set()

    # A) From budget lines
    for b in budgets:
        btype = b.get("type", "")
        bsub = b.get("subtype", "")
        name = bsub if bsub else btype
        key = name.lower().strip()
        seen_types.add(key)

        lb = b.get("labor_budget", 0)
        mb = b.get("materials_budget", 0)
        planned_mh = b.get("planned_man_hours")
        if planned_mh is None:
            coeff = b.get("coefficient", 1.0) or 1.0
            wage = b.get("avg_daily_wage_at_calc") or 200
            r = calculate_budget_formula_sync(lb, coeff, wage)
            planned_mh = r["planned_man_hours"]

        actual = actuals_by_type.get(key, {"hours": 0, "cost": 0})
        # Also check by type key
        if actual["hours"] == 0:
            actual = actuals_by_type.get(btype.lower().strip(), {"hours": 0, "cost": 0})

        ah = round(actual["hours"], 1)
        ac = round(actual["cost"], 2)
        burn = round(ah / planned_mh * 100, 1) if planned_mh > 0 else 0
        status = "green" if burn < 80 else ("yellow" if burn <= 100 else "red")

        activities.append({
            "budget_id": b.get("id"),
            "category": btype,
            "activity_name": name,
            "unit": "m2",
            "qty": 0,
            "material_budget": round(mb, 2),
            "labor_budget": round(lb, 2),
            "total_budget": round(mb + lb, 2),
            "planned_man_hours": round(planned_mh, 1),
            "actual_hours": ah,
            "actual_cost": ac,
            "burn_pct": burn,
            "status": status,
            "subcontractor_price": None,
            "is_extra": False,
            "source": "budget",
            "notes": b.get("notes", ""),
        })

    # B) From extra works (missing_smr not already in budget)
    for m in missing:
        name = m.get("smr_type") or m.get("activity_type", "")
        key = name.lower().strip()
        if key in seen_types:
            continue
        seen_types.add(key)

        actual = actuals_by_type.get(key, {"hours": 0, "cost": 0})
        ah = round(actual["hours"], 1)

        activities.append({
            "budget_id": None,
            "category": "Допълнителни",
            "activity_name": name,
            "unit": m.get("unit", ""),
            "qty": m.get("qty", 0),
            "material_budget": 0,
            "labor_budget": 0,
            "total_budget": 0,
            "planned_man_hours": 0,
            "actual_hours": ah,
            "actual_cost": round(actual["cost"], 2),
            "burn_pct": 0,
            "status": "green" if ah == 0 else "yellow",
            "subcontractor_price": None,
            "is_extra": True,
            "source": "missing_smr",
            "notes": m.get("notes", ""),
        })

    # C) R62 (one number): approved labor of an SMR without a budget line / extra work is shown
    # too, so the table's total is THE labor cost of the project
    for key, actual in actuals_by_type.items():
        if key in seen_types or not (actual["cost"] or actual["hours"]):
            continue
        seen_types.add(key)
        activities.append({
            "budget_id": None, "category": "Без бюджет", "activity_name": key, "unit": "", "qty": 0,
            "material_budget": 0, "labor_budget": 0, "total_budget": 0, "planned_man_hours": 0,
            "actual_hours": round(actual["hours"], 1), "actual_cost": round(actual["cost"], 2),
            "burn_pct": 0, "status": "yellow", "subcontractor_price": None, "is_extra": False,
            "source": "labor_without_budget", "notes": "",
        })

    # 5. Totals
    total_planned = round(sum(a["planned_man_hours"] for a in activities), 1)
    total_actual = round(sum(a["actual_hours"] for a in activities), 1)
    total_lb = round(sum(a["labor_budget"] for a in activities), 2)
    total_ac = round(sum(a["actual_cost"] for a in activities), 2)
    total_burn = round(total_actual / total_planned * 100, 1) if total_planned > 0 else 0

    return {
        "project_id": project_id,
        "activities": activities,
        "totals": {
            "total_planned_hours": total_planned,
            "total_actual_hours": total_actual,
            "total_burn_pct": total_burn,
            "total_labor_budget": total_lb,
            "total_actual_cost": total_ac,
            "activities_count": len(activities),
            "extra_count": sum(1 for a in activities if a["is_extra"]),
            "red_count": sum(1 for a in activities if a["status"] == "red"),
            "yellow_count": sum(1 for a in activities if a["status"] == "yellow"),
            "green_count": sum(1 for a in activities if a["status"] == "green"),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# LEVEL 2: ACTIVITY REPORTS LIST (Фаза 4.1)
# ═══════════════════════════════════════════════════════════════════

@router.get("/projects/{project_id}/activity-reports/{smr_type}")
@strip_money_for_non_finance   # SEC-02-B (R20-5M)
async def get_activity_reports(
    project_id: str, smr_type: str,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1, page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    """Level 2 drill-down: list reports for a specific activity/smr_type."""
    tenant = _tenant(user)
    org_id = user["org_id"]

    # Find work_sessions matching this project + smr_type
    ws_query = {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None}}
    smr_lower = smr_type.lower().strip()
    # Match by case-insensitive smr_type_id
    ws_query["$or"] = [
        {"smr_type_id": smr_type},
        {"smr_type_id": {"$regex": f"^{smr_lower}$", "$options": "i"}},
    ]
    if date_from:
        ws_query.setdefault("started_at", {})["$gte"] = f"{date_from}T00:00:00"
    if date_to:
        ws_query.setdefault("started_at", {})["$lte"] = f"{date_to}T23:59:59"

    sessions = await tenant.work_sessions.find(ws_query, {"_id": 0}).sort("started_at", -1).to_list(2000)

    # R62 (FG-421): the money of a worker-day is THE labor cost of that SMR (approved report
    # lines + Owner-approved manual rows); the sessions are only the time records
    labor = await project_labor_cost(org_id, project_id, date_from, date_to)
    canon = {}
    for rec in labor["lines"]:
        if (rec.get("smr_type") or "").lower().strip() != smr_lower:
            continue
        c = canon.setdefault(f"{rec.get('worker_id')}|{rec.get('date')}", {"cost": 0.0, "rate": rec.get("rate")})
        c["cost"] += float(rec.get("amount") or 0)

    # Group by worker_id + date
    from collections import defaultdict
    grouped = defaultdict(lambda: {"hours": 0, "cost": 0, "sessions": [], "rate": 0})
    for s in sessions:
        wid = s.get("worker_id", "")
        d = s.get("started_at", "")[:10]
        key = f"{wid}|{d}"
        grouped[key]["hours"] += s.get("duration_hours", 0)
        grouped[key]["cost"] += s.get("labor_cost", 0)
        grouped[key]["rate"] = s.get("hourly_rate_at_date", 0)
        grouped[key]["sessions"].append(s)
        grouped[key]["worker_id"] = wid
        grouped[key]["worker_name"] = s.get("worker_name", "")
        grouped[key]["date"] = d
        grouped[key]["source_method"] = s.get("source_method", "")
        grouped[key]["approved_report_id"] = s.get("approved_report_id")

    # Enrich with report info
    reports = []
    for key, g in grouped.items():
        report_status = "Approved" if g.get("approved_report_id") else "Unknown"
        slip = None
        created_by = None
        approved_by = None

        # Try to find the linked report
        rid = g.get("approved_report_id")
        if rid:
            rep = await tenant.employee_daily_reports.find_one({"id": rid}, {"_id": 0, "approval_status": 1, "status": 1, "slip_number": 1, "submitted_by": 1, "approved_by": 1})
            if rep:
                report_status = rep.get("status") or rep.get("approval_status", "Unknown")
                slip = rep.get("slip_number")
                approved_by = rep.get("approved_by")
                created_by = rep.get("submitted_by")

        # Status filter
        if status and report_status.lower() != status.lower():
            continue

        reports.append({
            "worker_id": g["worker_id"],
            "worker_name": g["worker_name"],
            "date": g["date"],
            "total_hours": round(g["hours"], 2),
            "total_cost": round((canon.get(key) or {}).get("cost", 0.0), 2),     # R62
            "hourly_rate": (canon.get(key) or {}).get("rate"),
            "status": report_status,
            "slip_number": slip,
            "created_by": created_by,
            "approved_by": approved_by,
            "source_report_id": rid,
            "session_ids": [s["id"] for s in g["sessions"]],
            "source_method": g["source_method"],
        })

    reports.sort(key=lambda x: x["date"], reverse=True)

    # Paginate
    total = len(reports)
    start = (page - 1) * page_size
    paged = reports[start:start + page_size]

    return {
        "project_id": project_id,
        "smr_type": smr_type,
        "reports": paged,
        "totals": {
            "total_hours": round(sum(r["total_hours"] for r in reports), 2),
            # R62: the SMR's whole labor cost (also worker-days without a session)
            "total_cost": round(sum(c["cost"] for c in canon.values()), 2),
            "reports_count": total,
        },
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


# ═══════════════════════════════════════════════════════════════════
# LEVEL 3: WORKER-DAY DETAIL (Фаза 4.2)
# ═══════════════════════════════════════════════════════════════════

@router.get("/work-sessions/{session_id}/detail")
@strip_money_for_non_finance   # SEC-02-B (R20-5M)
async def get_session_detail(session_id: str, user: dict = Depends(get_current_user)):
    """Level 3 drill-down: detailed view of a work session / worker-day."""
    tenant = _tenant(user)
    session = await tenant.work_sessions.find_one(
        {"id": session_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    org_id = user["org_id"]
    wid = session.get("worker_id", "")

    # Worker profile
    profile = await tenant.employee_profiles.find_one(
        {"org_id": org_id, "user_id": wid}, {"_id": 0, "pay_type": 1, "base_salary": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1}
    )
    pay_type_raw = (profile.get("pay_type", "Monthly") if profile else "Monthly").strip()
    pay_type_display = {"Hourly": "Почасово", "Daily": "Дневно", "Monthly": "Месечно"}.get(pay_type_raw, pay_type_raw)

    # Report info
    rid = session.get("approved_report_id")
    report_status = "Unknown"
    slip = None
    approved_by_name = None
    approved_at = None
    created_by_name = None
    created_at = session.get("created_at")
    is_paid = None

    if rid:
        rep = await tenant.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        if rep:
            report_status = rep.get("status") or rep.get("approval_status", "Unknown")
            slip = rep.get("slip_number")
            approved_at = rep.get("approved_at")
            # Get approver name
            if rep.get("approved_by"):
                approver = await tenant.users.find_one({"id": rep["approved_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
                if approver:
                    approved_by_name = f"{approver.get('first_name', '')} {approver.get('last_name', '')}".strip()
            if rep.get("submitted_by"):
                creator = await tenant.users.find_one({"id": rep["submitted_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
                if creator:
                    created_by_name = f"{creator.get('first_name', '')} {creator.get('last_name', '')}".strip()
            is_paid = rep.get("payroll_ready", False) and report_status == "APPROVED"

    # Project name
    project = await tenant.projects.find_one({"id": session.get("site_id")}, {"_id": 0, "name": 1})
    # R62 (FG-421): the money of this worker-day is THE labor cost (approved lines), not the session's
    day = session.get("started_at", "")[:10]
    day_cost = 0.0
    if session.get("site_id") and day:
        lc = await project_labor_cost(org_id, session["site_id"], day, day)
        day_cost = round(sum(float(r.get("amount") or 0) for r in lc["lines"]
                             if r.get("worker_id") == wid
                             and (r.get("smr_type") or "").lower() == (session.get("smr_type_id") or "").lower()), 2)

    return {
        "session_id": session_id,
        "worker_name": session.get("worker_name", ""),
        "worker_id": wid,
        "date": session.get("started_at", "")[:10],
        "project_name": (project or {}).get("name", ""),
        "project_id": session.get("site_id", ""),
        "smr_type": session.get("smr_type_id", ""),
        "pay_type": pay_type_display,
        "hourly_rate": session.get("hourly_rate_at_date", 0),
        "hours": session.get("duration_hours", 0),
        "total_cost": day_cost,          # R62: approved worker-day cost of this SMR
        "slip_number": slip,
        "status": report_status,
        "approved_by_name": approved_by_name,
        "approved_at": approved_at,
        "created_by_name": created_by_name,
        "created_at": created_at,
        "updated_at": session.get("updated_at"),
        "is_paid": is_paid,
        "is_overtime": session.get("is_overtime", False),
        "overtime_type": session.get("overtime_type"),
        "source_method": session.get("source_method", ""),
    }
