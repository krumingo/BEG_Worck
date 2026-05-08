"""
Routes - Dashboard Stats + Overhead (M9) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone, date as date_type
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m9
from app.utils.audit import log_audit
from ..models.overhead import (
    OVERHEAD_FREQUENCIES, OVERHEAD_ALLOCATION_TYPES, OVERHEAD_METHODS,
    OverheadCategoryCreate, OverheadCategoryUpdate,
    OverheadCostCreate, OverheadCostUpdate,
    OverheadAssetCreate, OverheadAssetUpdate,
    OverheadSnapshotCompute, OverheadAllocateRequest
)

router = APIRouter(tags=["Dashboard / Overhead"])

# ── Helpers ────────────────────────────────────────────────────────

def today_str():
    """Return today's date as YYYY-MM-DD string in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_overhead_access(user: dict, write: bool = False) -> bool:
    """Check if user has access to overhead cost system"""
    if user["role"] in ["Admin", "Owner", "Accountant"]:
        return True
    if user["role"] == "SiteManager" and not write:
        return True
    return False


# ── Dashboard Stats ────────────────────────────────────────────────

@router.get("/dashboard/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    status_counts = {}
    async for doc in db.projects.aggregate([
        {"$match": {"org_id": org_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]):
        status_counts[doc["_id"]] = doc["count"]

    users_count = await db.users.count_documents({"org_id": org_id, "is_active": True})

    # Attendance stats for today
    date = today_str()
    today_marked = await db.attendance_entries.count_documents({"org_id": org_id, "date": date})
    today_present = await db.attendance_entries.count_documents({"org_id": org_id, "date": date, "status": {"$in": ["Present", "Late"]}})

    # Work report stats
    pending_reports = await db.work_reports.count_documents({"org_id": org_id, "date": date, "status": "Submitted"})

    return {
        "active_projects": status_counts.get("Active", 0),
        "paused_projects": status_counts.get("Paused", 0),
        "completed_projects": status_counts.get("Completed", 0),
        "draft_projects": status_counts.get("Draft", 0),
        "total_projects": sum(status_counts.values()),
        "users_count": users_count,
        "today_marked": today_marked,
        "today_present": today_present,
        "pending_reports": pending_reports,
    }


# ── Overhead Categories ────────────────────────────────────────────

@router.get("/overhead/categories")
async def list_overhead_categories(user: dict = Depends(require_m9)):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    cursor = db.overhead_categories.find({"org_id": user["org_id"]}, {"_id": 0})
    return await cursor.to_list(None)


@router.post("/overhead/categories")
async def create_overhead_category(data: OverheadCategoryCreate, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await db.overhead_categories.insert_one(doc)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "overhead_category", doc["id"], {"name": data.name})
    return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/overhead/categories/{cat_id}")
async def update_overhead_category(cat_id: str, data: OverheadCategoryUpdate, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await db.overhead_categories.find_one({"id": cat_id, "org_id": user["org_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.overhead_categories.update_one({"id": cat_id}, {"$set": updates})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "overhead_category", cat_id, updates)
    doc = await db.overhead_categories.find_one({"id": cat_id}, {"_id": 0})
    return doc


@router.delete("/overhead/categories/{cat_id}")
async def delete_overhead_category(cat_id: str, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.overhead_categories.delete_one({"id": cat_id, "org_id": user["org_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "overhead_category", cat_id, {})
    return {"deleted": True}


# ── Overhead Costs ─────────────────────────────────────────────────

@router.get("/overhead/costs")
async def list_overhead_costs(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category_id: Optional[str] = None,
    user: dict = Depends(require_m9)
):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if date_from and date_to:
        query["date_incurred"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date_incurred"] = {"$gte": date_from}
    elif date_to:
        query["date_incurred"] = {"$lte": date_to}
    if category_id:
        query["category_id"] = category_id
    cursor = db.overhead_costs.find(query, {"_id": 0}).sort("date_incurred", -1)
    costs = await cursor.to_list(None)
    # Enrich with category name
    cat_ids = list(set(c.get("category_id") for c in costs if c.get("category_id")))
    cats = {}
    if cat_ids:
        cat_cursor = db.overhead_categories.find({"id": {"$in": cat_ids}}, {"_id": 0})
        cat_list = await cat_cursor.to_list(None)
        cats = {c["id"]: c["name"] for c in cat_list}
    for c in costs:
        c["category_name"] = cats.get(c.get("category_id"), "")
    return costs


@router.post("/overhead/costs")
async def create_overhead_cost(data: OverheadCostCreate, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    if data.frequency not in OVERHEAD_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid frequency")
    if data.allocation_type not in OVERHEAD_ALLOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid allocation type")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "category_id": data.category_id,
        "name": data.name,
        "amount": data.amount,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "date_incurred": data.date_incurred,
        "frequency": data.frequency,
        "allocation_type": data.allocation_type,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await db.overhead_costs.insert_one(doc)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "overhead_cost", doc["id"], {"name": data.name, "amount": data.amount})
    return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/overhead/costs/{cost_id}")
async def update_overhead_cost(cost_id: str, data: OverheadCostUpdate, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await db.overhead_costs.find_one({"id": cost_id, "org_id": user["org_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Cost not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if "frequency" in updates and updates["frequency"] not in OVERHEAD_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid frequency")
    if "allocation_type" in updates and updates["allocation_type"] not in OVERHEAD_ALLOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid allocation type")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.overhead_costs.update_one({"id": cost_id}, {"$set": updates})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "overhead_cost", cost_id, updates)
    doc = await db.overhead_costs.find_one({"id": cost_id}, {"_id": 0})
    return doc


@router.delete("/overhead/costs/{cost_id}")
async def delete_overhead_cost(cost_id: str, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.overhead_costs.delete_one({"id": cost_id, "org_id": user["org_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Cost not found")
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "overhead_cost", cost_id, {})
    return {"deleted": True}


# ── Overhead Assets ────────────────────────────────────────────────

@router.get("/overhead/assets")
async def list_overhead_assets(active_only: bool = True, user: dict = Depends(require_m9)):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if active_only:
        query["active"] = True
    cursor = db.overhead_assets.find(query, {"_id": 0}).sort("purchase_date", -1)
    assets = await cursor.to_list(None)
    # Add computed daily amortization
    for asset in assets:
        life_days = asset.get("useful_life_months", 60) * 30.4375
        daily_amort = asset.get("purchase_cost", 0) / life_days if life_days > 0 else 0
        asset["daily_amortization"] = round(daily_amort, 4)
    return assets


@router.post("/overhead/assets")
async def create_overhead_asset(data: OverheadAssetCreate, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "purchase_cost": data.purchase_cost,
        "currency": data.currency,
        "purchase_date": data.purchase_date,
        "useful_life_months": data.useful_life_months,
        "assigned_to_user_id": data.assigned_to_user_id,
        "active": data.active,
        "note": data.note,
        "created_at": now,
        "updated_at": now,
    }
    await db.overhead_assets.insert_one(doc)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "overhead_asset", doc["id"], {"name": data.name, "purchase_cost": data.purchase_cost})
    # Add computed daily amortization
    result = {k: v for k, v in doc.items() if k != "_id"}
    life_days = data.useful_life_months * 30.4375
    result["daily_amortization"] = round(data.purchase_cost / life_days, 4) if life_days > 0 else 0
    return result


@router.put("/overhead/assets/{asset_id}")
async def update_overhead_asset(asset_id: str, data: OverheadAssetUpdate, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    existing = await db.overhead_assets.find_one({"id": asset_id, "org_id": user["org_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Asset not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.overhead_assets.update_one({"id": asset_id}, {"$set": updates})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "overhead_asset", asset_id, updates)
    doc = await db.overhead_assets.find_one({"id": asset_id}, {"_id": 0})
    return doc


@router.delete("/overhead/assets/{asset_id}")
async def delete_overhead_asset(asset_id: str, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    result = await db.overhead_assets.delete_one({"id": asset_id, "org_id": user["org_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Asset not found")
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "overhead_asset", asset_id, {})
    return {"deleted": True}


# ── Overhead Snapshots ─────────────────────────────────────────────

@router.post("/overhead/snapshots/compute")
async def compute_overhead_snapshot(data: OverheadSnapshotCompute, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    if data.method not in OVERHEAD_METHODS:
        raise HTTPException(status_code=400, detail="Invalid method")
    
    org_id = user["org_id"]
    period_start = data.period_start
    period_end = data.period_end
    
    # Calculate number of days in period
    d_start = date_type.fromisoformat(period_start)
    d_end = date_type.fromisoformat(period_end)
    num_days = (d_end - d_start).days + 1
    
    # 1. Sum overhead costs in period
    costs_cursor = db.overhead_costs.find({
        "org_id": org_id,
        "date_incurred": {"$gte": period_start, "$lte": period_end}
    }, {"_id": 0})
    costs = await costs_cursor.to_list(None)
    total_costs = sum(c.get("amount", 0) for c in costs)
    
    # 2. Calculate asset amortization for all active assets
    assets_cursor = db.overhead_assets.find({"org_id": org_id, "active": True}, {"_id": 0})
    assets = await assets_cursor.to_list(None)
    total_amortization = 0
    for asset in assets:
        life_days = asset.get("useful_life_months", 60) * 30.4375
        if life_days > 0:
            daily_amort = asset.get("purchase_cost", 0) / life_days
            total_amortization += daily_amort * num_days
    
    total_overhead = round(total_costs + total_amortization, 2)
    
    # 3. Count person-days (unique user+date with Present/Late)
    attendance_pipeline = [
        {"$match": {
            "org_id": org_id,
            "date": {"$gte": period_start, "$lte": period_end},
            "status": {"$in": ["Present", "Late"]}
        }},
        {"$group": {"_id": {"user_id": "$user_id", "date": "$date"}}},
        {"$count": "total"}
    ]
    att_result = await db.attendance_entries.aggregate(attendance_pipeline).to_list(None)
    total_person_days = att_result[0]["total"] if att_result else 0
    
    # 4. Sum work report hours (Submitted/Approved)
    hours_pipeline = [
        {"$match": {
            "org_id": org_id,
            "date": {"$gte": period_start, "$lte": period_end},
            "status": {"$in": ["Submitted", "Approved"]}
        }},
        {"$group": {"_id": None, "total_hours": {"$sum": "$total_hours"}}}
    ]
    hours_result = await db.work_reports.aggregate(hours_pipeline).to_list(None)
    total_hours = round(hours_result[0]["total_hours"], 2) if hours_result else 0
    
    # 5. Calculate rates
    rate_per_person_day = round(total_overhead / total_person_days, 2) if total_person_days > 0 else 0
    rate_per_hour = round(total_overhead / total_hours, 2) if total_hours > 0 else 0
    
    # 6. Create immutable snapshot
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "period_start": period_start,
        "period_end": period_end,
        "method": data.method,
        "total_overhead": total_overhead,
        "total_costs": round(total_costs, 2),
        "total_amortization": round(total_amortization, 2),
        "total_person_days": total_person_days,
        "total_hours": total_hours,
        "overhead_rate_per_person_day": rate_per_person_day,
        "overhead_rate_per_hour": rate_per_hour,
        "computed_at": now,
        "computed_by_user_id": user["id"],
        "computed_by_name": user.get("name", user.get("email", "")),
        "notes": data.notes,
    }
    await db.overhead_snapshots.insert_one(snapshot)
    await log_audit(user["org_id"], user["id"], user["email"], "computed", "overhead_snapshot", snapshot["id"], {
        "period": f"{period_start} - {period_end}",
        "total_overhead": total_overhead,
        "method": data.method
    })
    return {k: v for k, v in snapshot.items() if k != "_id"}


@router.get("/overhead/snapshots")
async def list_overhead_snapshots(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_m9)
):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if date_from and date_to:
        query["period_start"] = {"$gte": date_from}
        query["period_end"] = {"$lte": date_to}
    cursor = db.overhead_snapshots.find(query, {"_id": 0}).sort("computed_at", -1)
    return await cursor.to_list(None)


@router.get("/overhead/snapshots/{snapshot_id}")
async def get_overhead_snapshot(snapshot_id: str, user: dict = Depends(require_m9)):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    snapshot = await db.overhead_snapshots.find_one({"id": snapshot_id, "org_id": user["org_id"]}, {"_id": 0})
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    # Get allocations
    allocs = await db.project_overhead_allocations.find(
        {"overhead_snapshot_id": snapshot_id}, {"_id": 0}
    ).to_list(None)
    snapshot["allocations"] = allocs
    return snapshot


@router.post("/overhead/snapshots/{snapshot_id}/allocate")
async def allocate_overhead_to_projects(snapshot_id: str, data: OverheadAllocateRequest, user: dict = Depends(require_m9)):
    if not check_overhead_access(user, write=True):
        raise HTTPException(status_code=403, detail="Access denied")
    
    snapshot = await db.overhead_snapshots.find_one({"id": snapshot_id, "org_id": user["org_id"]}, {"_id": 0})
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    org_id = user["org_id"]
    period_start = snapshot["period_start"]
    period_end = snapshot["period_end"]
    total_overhead = snapshot["total_overhead"]
    method = data.method
    
    # Delete existing allocations for this snapshot
    await db.project_overhead_allocations.delete_many({"overhead_snapshot_id": snapshot_id})
    
    allocations = []
    now = datetime.now(timezone.utc).isoformat()
    
    if method == "PersonDays":
        total_person_days = snapshot["total_person_days"]
        if total_person_days == 0:
            raise HTTPException(status_code=400, detail="No person-days to allocate")
        
        pipeline = [
            {"$match": {
                "org_id": org_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Present", "Late"]},
                "project_id": {"$exists": True, "$ne": None}
            }},
            {"$group": {
                "_id": "$project_id",
                "person_days": {"$addToSet": {"user_id": "$user_id", "date": "$date"}}
            }},
            {"$project": {"project_id": "$_id", "count": {"$size": "$person_days"}}}
        ]
        result = await db.attendance_entries.aggregate(pipeline).to_list(None)
        
        project_ids = [r["project_id"] for r in result]
        projects = {}
        if project_ids:
            proj_cursor = db.projects.find({"id": {"$in": project_ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1})
            proj_list = await proj_cursor.to_list(None)
            projects = {p["id"]: p for p in proj_list}
        
        for r in result:
            proj_id = r["project_id"]
            proj_days = r["count"]
            allocated = round(total_overhead * (proj_days / total_person_days), 2)
            proj_info = projects.get(proj_id, {})
            alloc = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "overhead_snapshot_id": snapshot_id,
                "project_id": proj_id,
                "project_code": proj_info.get("code", ""),
                "project_name": proj_info.get("name", ""),
                "basis_person_days": proj_days,
                "basis_hours": 0,
                "allocated_amount": allocated,
                "created_at": now,
            }
            allocations.append(alloc)
    else:
        total_hours = snapshot["total_hours"]
        if total_hours == 0:
            raise HTTPException(status_code=400, detail="No hours to allocate")
        
        pipeline = [
            {"$match": {
                "org_id": org_id,
                "date": {"$gte": period_start, "$lte": period_end},
                "status": {"$in": ["Submitted", "Approved"]}
            }},
            {"$group": {
                "_id": "$project_id",
                "total_hours": {"$sum": "$total_hours"}
            }}
        ]
        result = await db.work_reports.aggregate(pipeline).to_list(None)
        
        project_ids = [r["_id"] for r in result if r["_id"]]
        projects = {}
        if project_ids:
            proj_cursor = db.projects.find({"id": {"$in": project_ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1})
            proj_list = await proj_cursor.to_list(None)
            projects = {p["id"]: p for p in proj_list}
        
        for r in result:
            proj_id = r["_id"]
            if not proj_id:
                continue
            proj_hours = r["total_hours"]
            allocated = round(total_overhead * (proj_hours / total_hours), 2)
            proj_info = projects.get(proj_id, {})
            alloc = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "overhead_snapshot_id": snapshot_id,
                "project_id": proj_id,
                "project_code": proj_info.get("code", ""),
                "project_name": proj_info.get("name", ""),
                "basis_person_days": 0,
                "basis_hours": round(proj_hours, 2),
                "allocated_amount": allocated,
                "created_at": now,
            }
            allocations.append(alloc)
    
    if allocations:
        await db.project_overhead_allocations.insert_many(allocations)
    
    await log_audit(user["org_id"], user["id"], user["email"], "allocated", "overhead_snapshot", snapshot_id, {
        "method": method,
        "project_count": len(allocations),
        "total_allocated": sum(a["allocated_amount"] for a in allocations)
    })
    
    return {"allocations": [{k: v for k, v in a.items() if k != "_id"} for a in allocations]}


@router.get("/overhead/allocations")
async def list_overhead_allocations(
    snapshot_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user: dict = Depends(require_m9)
):
    if not check_overhead_access(user):
        raise HTTPException(status_code=403, detail="Access denied")
    query = {"org_id": user["org_id"]}
    if snapshot_id:
        query["overhead_snapshot_id"] = snapshot_id
    if project_id:
        query["project_id"] = project_id
    cursor = db.project_overhead_allocations.find(query, {"_id": 0})
    return await cursor.to_list(None)


@router.get("/overhead/enums")
async def get_overhead_enums(user: dict = Depends(require_m9)):
    return {
        "frequencies": OVERHEAD_FREQUENCIES,
        "allocation_types": OVERHEAD_ALLOCATION_TYPES,
        "methods": OVERHEAD_METHODS
    }
