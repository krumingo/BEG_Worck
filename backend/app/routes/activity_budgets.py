"""
Activity Budgets Routes - Per-project budget tracking by activity type/subtype.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user, can_access_project, can_manage_project
from app.utils.audit import log_audit

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
async def list_activity_budgets(project_id: str, user: dict = Depends(get_current_user)):
    """Get all activity budgets for a project."""
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    budgets = await db.activity_budgets.find(
        {"org_id": user["org_id"], "project_id": project_id},
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
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if exists (upsert key: org_id, project_id, type, subtype)
    existing = await db.activity_budgets.find_one({
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
        await db.activity_budgets.update_one({"id": existing["id"]}, {"$set": update})
        await log_audit(user["org_id"], user["id"], user["email"], "updated", "activity_budget", existing["id"], update)
        return await db.activity_budgets.find_one({"id": existing["id"]}, {"_id": 0})
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
        await db.activity_budgets.insert_one(budget)
        await log_audit(user["org_id"], user["id"], user["email"], "created", "activity_budget", budget["id"], {
            "type": data.type, "subtype": data.subtype
        })
        return {k: v for k, v in budget.items() if k != "_id"}


@router.delete("/projects/{project_id}/activity-budgets/{budget_id}")
async def delete_activity_budget(project_id: str, budget_id: str, user: dict = Depends(get_current_user)):
    """Delete an activity budget."""
    if not await can_manage_project(user, project_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    budget = await db.activity_budgets.find_one({
        "id": budget_id,
        "org_id": user["org_id"],
        "project_id": project_id,
    })
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    
    await db.activity_budgets.delete_one({"id": budget_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "activity_budget", budget_id, {})
    return {"ok": True}


@router.get("/projects/{project_id}/activity-budget-summary")
async def get_activity_budget_summary(project_id: str, user: dict = Depends(get_current_user)):
    """
    Get budget vs spent summary grouped by type/subtype.
    
    Returns for each (type, subtype):
    - laborBudget, materialsBudget
    - laborSpent, materialsSpent
    - laborRemaining, materialsRemaining
    - percentLaborUsed, percentMaterialsUsed
    """
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    org_id = user["org_id"]
    
    # 1. Get all budgets for project
    budgets = await db.activity_budgets.find(
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
    offers = await db.offers.find(
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
            
            spent_map[key]["labor"] += line.get("line_labor_cost", 0)
            spent_map[key]["materials"] += line.get("line_material_cost", 0)
    
    # 3. Also get labor spent from daily work logs if they have activity type
    daily_logs = await db.daily_work_logs.find(
        {"org_id": org_id, "site_id": project_id},
        {"_id": 0, "entries": 1, "work_type_id": 1}
    ).to_list(500)
    
    # Get work type -> activity type mapping if available
    work_types = await db.work_types.find({"org_id": org_id}, {"_id": 0}).to_list(100)
    work_type_map = {wt["id"]: wt for wt in work_types}
    
    for log in daily_logs:
        # Map work_type to activity_type (use work type name as activity type)
        wt = work_type_map.get(log.get("work_type_id"), {})
        act_type = wt.get("activity_type", wt.get("name", "Общо"))
        act_subtype = wt.get("activity_subtype", "")
        key = (act_type, act_subtype)
        
        if key not in spent_map:
            spent_map[key] = {"labor": 0, "materials": 0}
        
        # Calculate labor cost from hours * hourly rate
        hourly_rate = wt.get("default_hourly_rate", 25)
        total_hours = sum(e.get("hours", 0) for e in log.get("entries", []))
        spent_map[key]["labor"] += total_hours * hourly_rate
    
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

# ── Helpers ─────────────────────────────────────────────────────────

DEFAULT_DAILY_WAGE = 200  # BGN fallback

async def compute_avg_daily_wage(org_id: str, project_id: str) -> float:
    """Compute average daily wage from project team's employee profiles."""
    team = await db.project_team.find(
        {"project_id": project_id, "org_id": org_id, "active": True},
        {"_id": 0, "user_id": 1},
    ).to_list(100)
    if not team:
        return DEFAULT_DAILY_WAGE

    rates = []
    for m in team:
        profile = await db.employee_profiles.find_one(
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
    query = {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None}}
    if activity_type:
        query["smr_type_id"] = activity_type
    sessions = await db.work_sessions.find(query, {"_id": 0, "duration_hours": 1, "labor_cost": 1}).to_list(5000)
    total_hours = sum(s.get("duration_hours", 0) for s in sessions)
    total_cost = sum(s.get("labor_cost", 0) for s in sessions)
    return {"actual_hours": round(total_hours, 2), "actual_cost": round(total_cost, 2)}


# ── Forecast Endpoint ──────────────────────────────────────────────

@router.get("/activity-budgets/{budget_id}/forecast")
async def get_forecast(budget_id: str, user: dict = Depends(get_current_user)):
    """Compute man_days, min_days, min_people, avg_daily_wage for an activity budget."""
    budget = await db.activity_budgets.find_one(
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
async def calculate_snapshot(project_id: str, budget_id: str, user: dict = Depends(get_current_user)):
    """Calculate and persist man-hours/man-days snapshot for a budget line."""
    budget = await db.activity_budgets.find_one(
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
    await db.activity_budgets.update_one({"id": budget_id}, {"$set": snapshot})
    return await db.activity_budgets.find_one({"id": budget_id}, {"_id": 0})


@router.post("/projects/{project_id}/activity-budgets/calculate-all-snapshots")
async def calculate_all_snapshots(project_id: str, user: dict = Depends(get_current_user)):
    """Calculate snapshots for ALL budget lines in a project."""
    from app.services.budget_formula import calculate_budget_formula_sync
    org_id = user["org_id"]
    budgets = await db.activity_budgets.find(
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
        await db.activity_budgets.update_one({"id": b["id"]}, {"$set": {
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
    budget = await db.activity_budgets.find_one(
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
async def get_budget_health(project_id: str, user: dict = Depends(get_current_user)):
    """Aggregated burn for entire project across all activity budgets."""
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")

    org_id = user["org_id"]
    budgets = await db.activity_budgets.find(
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
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")

    org_id = user["org_id"]

    # BAC = total labor_budget
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0}
    ).to_list(100)
    bac = sum(b.get("labor_budget", 0) for b in budgets)

    # AC = actual labor cost from work_sessions
    burn = await get_work_session_burn(org_id, project_id)
    ac = burn["actual_cost"]

    # Progress from execution packages or budget_progress
    pkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "progress_percent": 1}
    ).to_list(200)
    if pkgs:
        progress_pct = sum(p.get("progress_percent", 0) for p in pkgs) / len(pkgs) / 100
    else:
        progress_pct = 0

    # EV = BAC × progress_pct
    ev = round(bac * progress_pct, 2)

    # PV = BAC × (elapsed / planned) — linear
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "start_date": 1, "end_date": 1})
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
