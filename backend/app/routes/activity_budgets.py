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
    notes: Optional[str] = None

class ActivityBudgetUpdate(BaseModel):
    labor_budget: Optional[float] = None
    materials_budget: Optional[float] = None
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
