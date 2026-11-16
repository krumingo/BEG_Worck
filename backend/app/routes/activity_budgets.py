"""
Activity Budgets Routes - Per-project budget tracking by activity type/subtype.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from app.db import db
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
@strip_for_budget_view(labor_source="lines")   # FG-63: spent = the approved labor lines (LAB-R96 step 3)   # SEC-02-B (R20-5B, FG-43)
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
    
    # 2. Spent. Materials: from the offer lines (unchanged). Labor — LAB-R96 step 3 (Р100
    # "бюджет по дейност чете едните одобрени редове"): the APPROVED labor lines of the
    # project (labor_cost_reader, pay run formula), by activity. The former mix — offer
    # line_labor_cost (a plan, not spent) + daily_work_logs × work type default 25 €/h — is gone.
    offers = await tenant.offers.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["Accepted", "Sent"]}},
        {"_id": 0, "lines": 1}
    ).to_list(100)

    spent_map = {}
    for offer in offers:
        for line in offer.get("lines", []):
            act_type = line.get("activity_type", "Общо")
            act_subtype = line.get("activity_subtype", "")
            key = (act_type, act_subtype)
            if key not in spent_map:
                spent_map[key] = {"labor": 0, "materials": 0}
            spent_map[key]["materials"] += line.get("line_material_cost", 0)

    # 3. Labor spent per activity → the budget row whose (subtype or type) names it
    from app.services.labor_cost_reader import labor_lines
    key_of = {}
    for (t_, st_) in list(budget_map.keys()) + list(spent_map.keys()):
        key_of.setdefault(norm_activity(st_ or t_), (t_, st_))
    for ln in await labor_lines(org_id, project_id=project_id, include_reported=False):
        key = key_of.get(ln["activity_key"]) or key_of.get(ln["activity_key"].split(" / ")[0])
        if key is None:
            key = (ln["activity"] or "Общо", "")
            key_of[ln["activity_key"]] = key
        spent_map.setdefault(key, {"labor": 0, "materials": 0})["labor"] += ln["cost"]

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
    
    return {
        "items": result,
        "totals": totals,
    }


import math
from app.tenancy.data_access import TenantData
from app.services.labor_report_service import norm_activity


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
    """Actual labor cost/hours of a project (and optional activity).

    LAB-R96 step 3 (Р100): the APPROVED labor lines of both stored formats, costed with the
    pay run's formula (labor_cost_reader) — approval work_sessions are not added on top. Old
    clock sessions (Р101) still count as before, visibly, in ``clock_legacy``."""
    from app.services.labor_cost_reader import clock_sessions, labor_lines, summarize
    lines = await labor_lines(org_id, project_id=project_id, activity=activity_type)
    clock = await clock_sessions(org_id, project_id=project_id, activity=activity_type)
    t = summarize(lines, clock)
    return {"actual_hours": round(t["hours"] + t["clock"]["hours"], 2),
            "actual_cost": round(t["cost"] + t["clock"]["cost"], 2),
            "approved_lines": {"hours": t["hours"], "cost": t["cost"],
                               "unpaid_cost": t["unpaid_cost"], "paid_cost": t["paid_cost"]},
            "forecast_cost": t["forecast_cost"],
            "clock_legacy": t["clock"]}


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
        total_spent += spent
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

    # 2. Actual hours/cost per activity — LAB-R96 step 3: the approved labor lines
    # (labor_cost_reader, pay run formula) + the old clock sessions as before (Р101, counted as before, not split out here: SEC-02 evidence pins
    # in the money keys of this screen — the clock component is visible on /burn and in P&L); approval sessions are not added on top.
    from app.services.labor_cost_reader import clock_sessions, labor_lines
    actuals_by_type = {}
    for ln in await labor_lines(org_id, project_id=project_id, include_reported=False):
        key = ln["activity_key"]
        if not key:
            continue
        a = actuals_by_type.setdefault(key, {"hours": 0, "cost": 0, "clock_hours": 0, "clock_cost": 0})
        a["hours"] += ln["hours"]
        a["cost"] += ln["cost"]
    for cs in await clock_sessions(org_id, project_id=project_id):
        key = cs["activity_key"]
        if not key:
            continue
        a = actuals_by_type.setdefault(key, {"hours": 0, "cost": 0, "clock_hours": 0, "clock_cost": 0})
        a["hours"] += cs["hours"]
        a["cost"] += cs["cost"]
        a["clock_hours"] += cs["hours"]
        a["clock_cost"] += cs["cost"]

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
        key = norm_activity(name)
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
            actual = actuals_by_type.get(norm_activity(btype), {"hours": 0, "cost": 0})

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
        key = norm_activity(name)
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

    # LAB-R96 step 3b (Р100 "едно четене", Р102): the labor LINES of this project + activity
    # through the one reader (both stored formats, the pay run's formula) — one row per line,
    # with its state (reported = forecast, not counted / approved_unpaid / batched / paid) —
    # and the old clock sessions (Р101) as before, one row per worker-day, marked
    # ``clock_legacy``. The approval work_sessions are the same approved lines: not listed.
    # ``session_ids`` keeps its meaning for the frontend: the ids /work-sessions/{id}/detail
    # opens (a labor line id, or an old clock session id).
    from collections import defaultdict
    from app.services.labor_cost_reader import CLOCK_LABEL, clock_sessions, labor_lines
    lines = await labor_lines(org_id, project_id=project_id, activity=smr_type,
                              date_from=date_from, date_to=date_to)
    clock = await clock_sessions(
        org_id, project_id=project_id, activity=smr_type,
        started_from=f"{date_from}T00:00:00" if date_from else None,
        started_before=f"{date_to}T23:59:59.999" if date_to else None)
    names = await _worker_names(tenant, org_id, {ln["worker_id"] for ln in lines if not ln["worker_name"]})

    rows = []
    for ln in lines:
        counted_ = ln["state"] != "reported"
        h = ln["hours"]
        rows.append({
            "worker_id": ln["worker_id"],
            "worker_name": ln["worker_name"] or names.get(ln["worker_id"], ""),
            "date": ln["date"],
            "total_hours": round(h, 2),
            "total_cost": round(ln["cost"], 2),
            "hourly_rate": round(ln["cost"] / h, 2) if h > 0 else 0.0,
            "status": ln["status"],
            "state": ln["state"],                     # Р102
            "counted": counted_,                      # a reported line is a forecast only
            "slip_number": ln.get("slip_number"),
            "created_by": ln.get("submitted_by"),
            "approved_by": ln.get("approved_by") if counted_ else None,
            "source_report_id": ln["report_id"],
            "line_ids": [ln["line_id"]],
            "session_ids": [ln["line_id"]],
            "source_method": "labor_line",
            "payroll_status": ln["payroll_status"],
            "pay_run_number": ln.get("pay_run_number"),
        })

    grouped = defaultdict(lambda: {"hours": 0, "cost": 0, "sessions": [], "rate": 0})
    for s in clock:
        g = grouped["%s|%s" % (s["worker_id"], s["date"])]
        g["hours"] += s["hours"]
        g["cost"] += s["cost"]
        g["rate"] = s["hourly_rate_at_date"]
        g["sessions"].append(s)
        g.update(worker_id=s["worker_id"], worker_name=s["worker_name"], date=s["date"],
                 source_method=s["source_method"] or "")
    for g in grouped.values():
        rows.append({
            "worker_id": g["worker_id"], "worker_name": g["worker_name"], "date": g["date"],
            "total_hours": round(g["hours"], 2), "total_cost": round(g["cost"], 2),
            "hourly_rate": round(g["rate"] or 0, 2),
            "status": "Unknown",                      # a clock record has no report (as before)
            "state": "clock_legacy", "clock_label": CLOCK_LABEL, "counted": True,
            "slip_number": None, "created_by": None, "approved_by": None,
            "source_report_id": None, "line_ids": [],
            "session_ids": [s["session_id"] for s in g["sessions"]],
            "source_method": g["source_method"],
        })

    if status:
        rows = [r for r in rows if (r["status"] or "").lower() == status.lower()]
    reports = sorted(rows, key=lambda x: x["date"], reverse=True)

    # Paginate
    total = len(reports)
    start = (page - 1) * page_size
    paged = reports[start:start + page_size]

    counted_rows = [r for r in reports if r["counted"]]
    clock_rows = [r for r in reports if r["state"] == "clock_legacy"]
    line_rows = [r for r in counted_rows if r["state"] != "clock_legacy"]
    return {
        "project_id": project_id,
        "smr_type": smr_type,
        "reports": paged,
        "totals": {
            # approved lines + old clock (as before); a reported line is not counted
            "total_hours": round(sum(r["total_hours"] for r in counted_rows), 2),
            "total_cost": round(sum(r["total_cost"] for r in counted_rows), 2),
            "reports_count": total,
            # LAB-R96 step 3b: the parts (finance view; the decorator strips the money)
            "approved_lines": {"hours": round(sum(r["total_hours"] for r in line_rows), 2),
                               "cost": round(sum(r["total_cost"] for r in line_rows), 2)},
            "clock_legacy": {"label": CLOCK_LABEL, "sessions": sum(len(r["session_ids"]) for r in clock_rows),
                             "hours": round(sum(r["total_hours"] for r in clock_rows), 2),
                             "cost": round(sum(r["total_cost"] for r in clock_rows), 2)},
            "forecast_cost": round(sum(r["total_cost"] for r in reports if not r["counted"]), 2),
        },
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


async def _worker_names(tenant, org_id: str, ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    users = await tenant.users.find({"org_id": org_id, "id": {"$in": ids}},
                                    {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(len(ids) + 10)
    return {u["id"]: ("%s %s" % (u.get("first_name", ""), u.get("last_name", ""))).strip() for u in users}


async def _user_name(tenant, uid):
    if not uid:
        return None
    u = await tenant.users.find_one({"id": uid}, {"_id": 0, "first_name": 1, "last_name": 1})
    return ("%s %s" % (u.get("first_name", ""), u.get("last_name", ""))).strip() if u else None


# ═══════════════════════════════════════════════════════════════════
# LEVEL 3: WORKER-DAY DETAIL (Фаза 4.2)
# ═══════════════════════════════════════════════════════════════════

@router.get("/work-sessions/{session_id}/detail")
@strip_money_for_non_finance   # SEC-02-B (R20-5M)
async def get_session_detail(session_id: str, user: dict = Depends(get_current_user)):
    """Level 3 drill-down: one worker-day line.

    LAB-R96 step 3b (Р100): ``session_id`` is what Level 2 lists — a labor line id (its
    hours / cost / state from the one reader, the pay run's formula), an approval
    work_session (shown as the labor line it was written from), or an old clock session
    (Р101, its stored figures as before, marked ``clock_legacy``)."""
    from app.services.labor_cost_reader import (APPROVED_SESSION, CLOCK_LABEL, labor_lines,
                                                line_by_id)
    tenant = _tenant(user)
    org_id = user["org_id"]
    session = await tenant.work_sessions.find_one(
        {"id": session_id, "org_id": org_id}, {"_id": 0}
    )
    line = None
    if session is None:
        line = await line_by_id(org_id, session_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Session not found")
    elif session.get("source_method") == APPROVED_SESSION and session.get("approved_report_id"):
        d = (session.get("started_at") or "")[:10]
        cands = [ln for ln in await labor_lines(org_id, worker_id=session.get("worker_id"),
                                                date_from=d, date_to=d)
                 if ln["report_id"] == session["approved_report_id"]
                 and ln["project_id"] == session.get("site_id")]
        key = norm_activity(session.get("smr_type_id"))
        line = next((ln for ln in cands if ln["activity_key"] == key),
                    cands[0] if len(cands) == 1 else None)

    wid = line["worker_id"] if line else session.get("worker_id", "")

    # Worker profile
    profile = await tenant.employee_profiles.find_one(
        {"org_id": org_id, "user_id": wid}, {"_id": 0, "pay_type": 1, "base_salary": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1}
    )
    pay_type_raw = (profile.get("pay_type", "Monthly") if profile else "Monthly").strip()
    pay_type_display = {"Hourly": "Почасово", "Daily": "Дневно", "Monthly": "Месечно"}.get(pay_type_raw, pay_type_raw)

    if line is not None:
        rep = await tenant.employee_daily_reports.find_one(
            {"org_id": org_id, "id": line["report_id"]}, {"_id": 0, "updated_at": 1})
        project = await tenant.projects.find_one({"id": line["project_id"]}, {"_id": 0, "name": 1})
        h = line["hours"]
        name = line["worker_name"] or (await _worker_names(tenant, org_id, [wid])).get(wid, "")
        return {
            "session_id": session_id,
            "line_id": line["line_id"],
            "worker_name": name or (session or {}).get("worker_name", ""),
            "worker_id": wid,
            "date": line["date"],
            "project_name": (project or {}).get("name", ""),
            "project_id": line["project_id"],
            "smr_type": line["activity"],
            "pay_type": pay_type_display,
            "hourly_rate": round(line["cost"] / h, 2) if h > 0 else 0.0,
            "hours": h,
            "normal_hours": line["normal_hours"],
            "overtime_hours": line["overtime_hours"],
            "total_cost": line["cost"],
            "cost_basis": line.get("cost_basis"),
            "slip_number": line.get("slip_number"),
            "status": line["status"],
            "state": line["state"],                                   # Р102
            "counted": line["state"] != "reported",
            "payroll_status": line["payroll_status"],
            "pay_run_number": line.get("pay_run_number"),
            "approved_by_name": await _user_name(tenant, line.get("approved_by")),
            "approved_at": line.get("approved_at"),
            "created_by_name": await _user_name(tenant, line.get("submitted_by")),
            "created_at": line.get("created_at") or None,
            "updated_at": (rep or {}).get("updated_at"),
            "is_paid": line["state"] == "paid",
            "is_overtime": line["overtime_hours"] > 0,
            "overtime_type": (session or {}).get("overtime_type"),
            "source_method": "labor_line",
        }

    # An old clock session (Р101) — or an approval session whose line is gone (reset / voided):
    # its stored figures as before; only a clock record is counted.
    is_clock = session.get("source_method") != APPROVED_SESSION
    rid = session.get("approved_report_id")
    report_status = "Unknown"
    slip = approved_by_name = approved_at = created_by_name = None
    is_paid = None
    if rid:
        rep = await tenant.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        if rep:
            report_status = rep.get("status") or rep.get("approval_status", "Unknown")
            slip = rep.get("slip_number")
            approved_at = rep.get("approved_at")
            approved_by_name = await _user_name(tenant, rep.get("approved_by"))
            created_by_name = await _user_name(tenant, rep.get("submitted_by"))
            is_paid = rep.get("payroll_ready", False) and report_status == "APPROVED"
    project = await tenant.projects.find_one({"id": session.get("site_id")}, {"_id": 0, "name": 1})
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
        "total_cost": session.get("labor_cost", 0),
        "slip_number": slip,
        "status": report_status,
        "state": "clock_legacy" if is_clock else "approval_session_without_line",
        "clock_label": CLOCK_LABEL if is_clock else None,
        "counted": is_clock,
        "approved_by_name": approved_by_name,
        "approved_at": approved_at,
        "created_by_name": created_by_name,
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "is_paid": is_paid,
        "is_overtime": session.get("is_overtime", False),
        "overtime_type": session.get("overtime_type"),
        "source_method": session.get("source_method", ""),
    }
