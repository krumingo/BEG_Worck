"""
Work Logs & Change Orders Routes - "Дневник + Промени (СМР)"
Mobile-first module for daily work logs and change orders.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, date
import uuid

from app.db import db
from app.deps.auth import get_current_user, require_admin, can_access_project, get_user_project_ids
from app.utils.audit import log_audit

router = APIRouter(tags=["work-logs"])

# Constants
CHANGE_ORDER_KINDS = ["new", "modify", "cancel"]
CHANGE_ORDER_STATUSES = ["draft", "pending_approval", "approved", "rejected", "invoiced", "paid"]

# ─────────────────────────────────────────────────────────────────────────────
# WORK TYPES - Admin CRUD
# ─────────────────────────────────────────────────────────────────────────────

class WorkTypeCreate(BaseModel):
    name: str
    default_hourly_rate: Optional[float] = None
    is_active: bool = True

class WorkTypeUpdate(BaseModel):
    name: Optional[str] = None
    default_hourly_rate: Optional[float] = None
    is_active: Optional[bool] = None

@router.get("/work-types")
async def list_work_types(
    include_inactive: bool = False,
    user: dict = Depends(get_current_user)
):
    """List all work types for the organization."""
    query = {"org_id": user["org_id"]}
    if not include_inactive:
        query["is_active"] = True
    
    items = await db.work_types.find(query, {"_id": 0}).sort("name", 1).to_list(100)
    return {"items": items, "total": len(items)}

@router.post("/work-types", status_code=201)
async def create_work_type(data: WorkTypeCreate, user: dict = Depends(require_admin)):
    """Create a new work type (admin only)."""
    # Check for duplicates
    existing = await db.work_types.find_one({
        "org_id": user["org_id"],
        "name": {"$regex": f"^{data.name}$", "$options": "i"}
    })
    if existing:
        raise HTTPException(status_code=400, detail="Work type with this name already exists")
    
    work_type = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name,
        "default_hourly_rate": data.default_hourly_rate,
        "is_active": data.is_active,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.work_types.insert_one(work_type)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "work_type", work_type["id"], {"name": data.name})
    return {k: v for k, v in work_type.items() if k != "_id"}

@router.patch("/work-types/{work_type_id}")
async def update_work_type(work_type_id: str, data: WorkTypeUpdate, user: dict = Depends(require_admin)):
    """Update a work type (admin only)."""
    work_type = await db.work_types.find_one({"id": work_type_id, "org_id": user["org_id"]})
    if not work_type:
        raise HTTPException(status_code=404, detail="Work type not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        return {k: v for k, v in work_type.items() if k != "_id"}
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.work_types.update_one({"id": work_type_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "work_type", work_type_id, update)
    
    updated = await db.work_types.find_one({"id": work_type_id}, {"_id": 0})
    return updated

@router.delete("/work-types/{work_type_id}")
async def delete_work_type(work_type_id: str, user: dict = Depends(require_admin)):
    """Soft delete a work type (admin only)."""
    work_type = await db.work_types.find_one({"id": work_type_id, "org_id": user["org_id"]})
    if not work_type:
        raise HTTPException(status_code=404, detail="Work type not found")
    
    await db.work_types.update_one({"id": work_type_id}, {"$set": {"is_active": False}})
    await log_audit(user["org_id"], user["id"], user["email"], "deactivated", "work_type", work_type_id, {})
    return {"ok": True}

# ─────────────────────────────────────────────────────────────────────────────
# DAILY WORK LOGS
# ─────────────────────────────────────────────────────────────────────────────

class DailyLogEntry(BaseModel):
    user_id: str
    hours: float
    role: Optional[str] = None

class DailyLogCreate(BaseModel):
    site_id: str  # project_id
    date: str  # YYYY-MM-DD
    work_type_id: str
    entries: List[DailyLogEntry]
    notes: Optional[str] = None
    attachments: List[str] = []

class DailyLogUpdate(BaseModel):
    work_type_id: Optional[str] = None
    entries: Optional[List[DailyLogEntry]] = None
    notes: Optional[str] = None
    attachments: Optional[List[str]] = None

async def check_site_access(user: dict, site_id: str) -> bool:
    """Check if user has access to site (project)."""
    # Admin has access to all
    if user["role"] == "Admin":
        project = await db.projects.find_one({"id": site_id, "org_id": user["org_id"]})
        return project is not None
    
    # Check team membership
    member = await db.project_team.find_one({
        "project_id": site_id,
        "user_id": user["id"],
        "active": True
    })
    if member:
        return True
    
    # Check if user is default site manager
    project = await db.projects.find_one({
        "id": site_id,
        "org_id": user["org_id"],
        "default_site_manager_id": user["id"]
    })
    return project is not None

async def can_approve_site(user: dict, site_id: str) -> bool:
    """Check if user can approve change orders for site."""
    if user["role"] == "Admin":
        return True
    
    # Check if SiteManager on this project
    member = await db.project_team.find_one({
        "project_id": site_id,
        "user_id": user["id"],
        "role_in_project": "SiteManager",
        "active": True
    })
    if member:
        return True
    
    # Check if default site manager
    project = await db.projects.find_one({
        "id": site_id,
        "org_id": user["org_id"],
        "default_site_manager_id": user["id"]
    })
    return project is not None

@router.get("/daily-logs")
async def list_daily_logs(
    site_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user)
):
    """List daily work logs. Non-admins see only their accessible sites."""
    query = {"org_id": user["org_id"]}
    
    # Filter by site
    if site_id:
        if not await check_site_access(user, site_id):
            raise HTTPException(status_code=403, detail="Access denied to this site")
        query["site_id"] = site_id
    elif user["role"] != "Admin":
        # Non-admin: filter to accessible projects
        accessible_ids = await get_user_project_ids(user)
        query["site_id"] = {"$in": accessible_ids}
    
    # Date filters
    if date_from:
        query["date"] = {"$gte": date_from}
    if date_to:
        query.setdefault("date", {})["$lte"] = date_to
    
    total = await db.daily_work_logs.count_documents(query)
    skip = (page - 1) * page_size
    
    items = await db.daily_work_logs.find(query, {"_id": 0}).sort("date", -1).skip(skip).limit(page_size).to_list(page_size)
    
    # Enrich with site/work_type names
    for item in items:
        project = await db.projects.find_one({"id": item["site_id"]}, {"_id": 0, "name": 1, "code": 1})
        item["site_name"] = project["name"] if project else "Unknown"
        item["site_code"] = project["code"] if project else ""
        
        wt = await db.work_types.find_one({"id": item["work_type_id"]}, {"_id": 0, "name": 1})
        item["work_type_name"] = wt["name"] if wt else "Unknown"
        
        # Get user names for entries
        for entry in item.get("entries", []):
            u = await db.users.find_one({"id": entry["user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            entry["user_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }

@router.post("/daily-logs", status_code=201)
async def create_daily_log(data: DailyLogCreate, user: dict = Depends(get_current_user)):
    """Create a new daily work log."""
    # Check site access
    if not await check_site_access(user, data.site_id):
        raise HTTPException(status_code=403, detail="Access denied to this site")
    
    # Validate work type
    work_type = await db.work_types.find_one({"id": data.work_type_id, "org_id": user["org_id"], "is_active": True})
    if not work_type:
        raise HTTPException(status_code=400, detail="Invalid or inactive work type")
    
    # Check for duplicate (same site + date + work_type)
    existing = await db.daily_work_logs.find_one({
        "org_id": user["org_id"],
        "site_id": data.site_id,
        "date": data.date,
        "work_type_id": data.work_type_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="A log for this site, date, and work type already exists")
    
    # Calculate total hours
    total_hours = sum(e.hours for e in data.entries)
    
    log = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "site_id": data.site_id,
        "date": data.date,
        "work_type_id": data.work_type_id,
        "entries": [e.model_dump() for e in data.entries],
        "total_hours": total_hours,
        "notes": data.notes,
        "attachments": data.attachments,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.daily_work_logs.insert_one(log)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "daily_work_log", log["id"], {
        "site_id": data.site_id,
        "date": data.date,
        "total_hours": total_hours
    })
    
    return {k: v for k, v in log.items() if k != "_id"}

@router.get("/daily-logs/{log_id}")
async def get_daily_log(log_id: str, user: dict = Depends(get_current_user)):
    """Get a single daily log."""
    log = await db.daily_work_logs.find_one({"id": log_id, "org_id": user["org_id"]}, {"_id": 0})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    
    if not await check_site_access(user, log["site_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return log

@router.patch("/daily-logs/{log_id}")
async def update_daily_log(log_id: str, data: DailyLogUpdate, user: dict = Depends(get_current_user)):
    """Update a daily log."""
    log = await db.daily_work_logs.find_one({"id": log_id, "org_id": user["org_id"]})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    
    if not await check_site_access(user, log["site_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    update = {}
    if data.work_type_id:
        work_type = await db.work_types.find_one({"id": data.work_type_id, "org_id": user["org_id"], "is_active": True})
        if not work_type:
            raise HTTPException(status_code=400, detail="Invalid work type")
        update["work_type_id"] = data.work_type_id
    
    if data.entries is not None:
        update["entries"] = [e.model_dump() for e in data.entries]
        update["total_hours"] = sum(e.hours for e in data.entries)
    
    if data.notes is not None:
        update["notes"] = data.notes
    
    if data.attachments is not None:
        update["attachments"] = data.attachments
    
    if update:
        update["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.daily_work_logs.update_one({"id": log_id}, {"$set": update})
        await log_audit(user["org_id"], user["id"], user["email"], "updated", "daily_work_log", log_id, update)
    
    return await db.daily_work_logs.find_one({"id": log_id}, {"_id": 0})

@router.delete("/daily-logs/{log_id}")
async def delete_daily_log(log_id: str, user: dict = Depends(get_current_user)):
    """Delete a daily log."""
    log = await db.daily_work_logs.find_one({"id": log_id, "org_id": user["org_id"]})
    if not log:
        raise HTTPException(status_code=404, detail="Daily log not found")
    
    if not await check_site_access(user, log["site_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    await db.daily_work_logs.delete_one({"id": log_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "daily_work_log", log_id, {})
    return {"ok": True}

# ─────────────────────────────────────────────────────────────────────────────
# CHANGE ORDERS
# ─────────────────────────────────────────────────────────────────────────────

class ChangeOrderCreate(BaseModel):
    site_id: str
    work_type_id: Optional[str] = None
    kind: str  # new, modify, cancel
    target_boq_line_id: Optional[str] = None
    delta_qty: Optional[float] = None
    unit: Optional[str] = None
    labor_delta: float = 0
    material_delta: float = 0
    description: str
    needed_by_date: Optional[str] = None
    attachments: List[str] = []

class ChangeOrderUpdate(BaseModel):
    work_type_id: Optional[str] = None
    kind: Optional[str] = None
    delta_qty: Optional[float] = None
    unit: Optional[str] = None
    labor_delta: Optional[float] = None
    material_delta: Optional[float] = None
    description: Optional[str] = None
    needed_by_date: Optional[str] = None
    attachments: Optional[List[str]] = None

@router.get("/change-orders")
async def list_change_orders(
    site_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user)
):
    """List change orders. Non-admins see only their accessible sites."""
    query = {"org_id": user["org_id"]}
    
    # Filter by site
    if site_id:
        if not await check_site_access(user, site_id):
            raise HTTPException(status_code=403, detail="Access denied to this site")
        query["site_id"] = site_id
    elif user["role"] != "Admin":
        accessible_ids = await get_user_project_ids(user)
        query["site_id"] = {"$in": accessible_ids}
    
    # Status filter
    if status:
        query["status"] = status
    
    # Date filters
    if date_from:
        query["requested_at"] = {"$gte": date_from}
    if date_to:
        query.setdefault("requested_at", {})["$lte"] = date_to
    
    total = await db.change_orders.count_documents(query)
    skip = (page - 1) * page_size
    
    items = await db.change_orders.find(query, {"_id": 0}).sort("requested_at", -1).skip(skip).limit(page_size).to_list(page_size)
    
    # Enrich
    for item in items:
        project = await db.projects.find_one({"id": item["site_id"]}, {"_id": 0, "name": 1, "code": 1})
        item["site_name"] = project["name"] if project else "Unknown"
        item["site_code"] = project["code"] if project else ""
        
        if item.get("work_type_id"):
            wt = await db.work_types.find_one({"id": item["work_type_id"]}, {"_id": 0, "name": 1})
            item["work_type_name"] = wt["name"] if wt else ""
        
        creator = await db.users.find_one({"id": item["created_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
        item["created_by_name"] = f"{creator['first_name']} {creator['last_name']}" if creator else "Unknown"
        
        if item.get("approved_by"):
            approver = await db.users.find_one({"id": item["approved_by"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            item["approved_by_name"] = f"{approver['first_name']} {approver['last_name']}" if approver else ""
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }

@router.post("/change-orders", status_code=201)
async def create_change_order(data: ChangeOrderCreate, user: dict = Depends(get_current_user)):
    """Create a new change order (starts as draft)."""
    # Check site access
    if not await check_site_access(user, data.site_id):
        raise HTTPException(status_code=403, detail="Access denied to this site")
    
    if data.kind not in CHANGE_ORDER_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind. Must be: {', '.join(CHANGE_ORDER_KINDS)}")
    
    # Validate work type if provided
    if data.work_type_id:
        work_type = await db.work_types.find_one({"id": data.work_type_id, "org_id": user["org_id"]})
        if not work_type:
            raise HTTPException(status_code=400, detail="Invalid work type")
    
    order = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "site_id": data.site_id,
        "created_by": user["id"],
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "needed_by_date": data.needed_by_date,
        "work_type_id": data.work_type_id,
        "kind": data.kind,
        "target_boq_line_id": data.target_boq_line_id,
        "delta_qty": data.delta_qty,
        "unit": data.unit,
        "labor_delta": data.labor_delta,
        "material_delta": data.material_delta,
        "total_delta": data.labor_delta + data.material_delta,
        "description": data.description,
        "status": "draft",
        "attachments": data.attachments,
        "audit_trail": [{
            "action": "created",
            "by": user["id"],
            "at": datetime.now(timezone.utc).isoformat(),
        }],
    }
    await db.change_orders.insert_one(order)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "change_order", order["id"], {
        "site_id": data.site_id,
        "kind": data.kind,
        "total_delta": order["total_delta"]
    })
    
    return {k: v for k, v in order.items() if k != "_id"}

@router.get("/change-orders/{order_id}")
async def get_change_order(order_id: str, user: dict = Depends(get_current_user)):
    """Get a single change order."""
    order = await db.change_orders.find_one({"id": order_id, "org_id": user["org_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Change order not found")
    
    if not await check_site_access(user, order["site_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return order

@router.patch("/change-orders/{order_id}")
async def update_change_order(order_id: str, data: ChangeOrderUpdate, user: dict = Depends(get_current_user)):
    """Update a change order (only if in draft status)."""
    order = await db.change_orders.find_one({"id": order_id, "org_id": user["org_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Change order not found")
    
    if not await check_site_access(user, order["site_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if order["status"] != "draft":
        raise HTTPException(status_code=400, detail="Can only edit draft change orders")
    
    update = {}
    for field in ["work_type_id", "kind", "delta_qty", "unit", "labor_delta", "material_delta", "description", "needed_by_date", "attachments"]:
        value = getattr(data, field, None)
        if value is not None:
            update[field] = value
    
    if data.kind and data.kind not in CHANGE_ORDER_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind. Must be: {', '.join(CHANGE_ORDER_KINDS)}")
    
    # Recalculate total if needed
    labor = data.labor_delta if data.labor_delta is not None else order["labor_delta"]
    material = data.material_delta if data.material_delta is not None else order["material_delta"]
    update["total_delta"] = labor + material
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Add audit trail
    await db.change_orders.update_one(
        {"id": order_id},
        {
            "$set": update,
            "$push": {"audit_trail": {"action": "updated", "by": user["id"], "at": update["updated_at"]}}
        }
    )
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "change_order", order_id, update)
    
    return await db.change_orders.find_one({"id": order_id}, {"_id": 0})

@router.post("/change-orders/{order_id}/submit")
async def submit_change_order(order_id: str, user: dict = Depends(get_current_user)):
    """Submit a draft change order for approval."""
    order = await db.change_orders.find_one({"id": order_id, "org_id": user["org_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Change order not found")
    
    if not await check_site_access(user, order["site_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if order["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft orders can be submitted")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.change_orders.update_one(
        {"id": order_id},
        {
            "$set": {"status": "pending_approval", "submitted_at": now},
            "$push": {"audit_trail": {"action": "submitted", "by": user["id"], "at": now}}
        }
    )
    await log_audit(user["org_id"], user["id"], user["email"], "submitted", "change_order", order_id, {})
    
    return await db.change_orders.find_one({"id": order_id}, {"_id": 0})

@router.post("/change-orders/{order_id}/approve")
async def approve_change_order(order_id: str, user: dict = Depends(get_current_user)):
    """Approve a pending change order (admin or site manager only)."""
    order = await db.change_orders.find_one({"id": order_id, "org_id": user["org_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Change order not found")
    
    if not await can_approve_site(user, order["site_id"]):
        raise HTTPException(status_code=403, detail="Only admin or site manager can approve")
    
    if order["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Only pending orders can be approved")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.change_orders.update_one(
        {"id": order_id},
        {
            "$set": {"status": "approved", "approved_by": user["id"], "approved_at": now},
            "$push": {"audit_trail": {"action": "approved", "by": user["id"], "at": now}}
        }
    )
    await log_audit(user["org_id"], user["id"], user["email"], "approved", "change_order", order_id, {})
    
    return await db.change_orders.find_one({"id": order_id}, {"_id": 0})

@router.post("/change-orders/{order_id}/reject")
async def reject_change_order(
    order_id: str,
    reason: str = "",
    user: dict = Depends(get_current_user)
):
    """Reject a pending change order (admin or site manager only)."""
    order = await db.change_orders.find_one({"id": order_id, "org_id": user["org_id"]})
    if not order:
        raise HTTPException(status_code=404, detail="Change order not found")
    
    if not await can_approve_site(user, order["site_id"]):
        raise HTTPException(status_code=403, detail="Only admin or site manager can reject")
    
    if order["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Only pending orders can be rejected")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.change_orders.update_one(
        {"id": order_id},
        {
            "$set": {"status": "rejected", "rejected_by": user["id"], "rejected_at": now, "rejection_reason": reason},
            "$push": {"audit_trail": {"action": "rejected", "by": user["id"], "at": now, "reason": reason}}
        }
    )
    await log_audit(user["org_id"], user["id"], user["email"], "rejected", "change_order", order_id, {"reason": reason})
    
    return await db.change_orders.find_one({"id": order_id}, {"_id": 0})

# ─────────────────────────────────────────────────────────────────────────────
# MY SITES (for mobile dropdown)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/my-sites")
async def get_my_sites(user: dict = Depends(get_current_user)):
    """Get sites/projects the current user has access to."""
    if user["role"] == "Admin":
        # Admin sees all active projects
        projects = await db.projects.find(
            {"org_id": user["org_id"], "status": {"$in": ["Active", "Draft"]}},
            {"_id": 0, "id": 1, "code": 1, "name": 1, "status": 1}
        ).sort("code", 1).to_list(100)
    else:
        # Get projects where user is team member
        memberships = await db.project_team.find(
            {"user_id": user["id"], "active": True},
            {"_id": 0, "project_id": 1}
        ).to_list(100)
        project_ids = [m["project_id"] for m in memberships]
        
        # Also include projects where user is default manager
        manager_projects = await db.projects.find(
            {"org_id": user["org_id"], "default_site_manager_id": user["id"]},
            {"_id": 0, "id": 1}
        ).to_list(100)
        project_ids.extend([p["id"] for p in manager_projects])
        project_ids = list(set(project_ids))
        
        projects = await db.projects.find(
            {"id": {"$in": project_ids}, "status": {"$in": ["Active", "Draft"]}},
            {"_id": 0, "id": 1, "code": 1, "name": 1, "status": 1}
        ).sort("code", 1).to_list(100)
    
    return {"items": projects}

@router.get("/my-team/{site_id}")
async def get_site_team(site_id: str, user: dict = Depends(get_current_user)):
    """Get team members for a site (for multi-select in daily logs)."""
    if not await check_site_access(user, site_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get team members
    members = await db.project_team.find(
        {"project_id": site_id, "active": True},
        {"_id": 0, "user_id": 1, "role_in_project": 1}
    ).to_list(100)
    
    result = []
    for m in members:
        u = await db.users.find_one({"id": m["user_id"]}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "role": 1})
        if u:
            result.append({
                "id": u["id"],
                "name": f"{u['first_name']} {u['last_name']}",
                "role": m["role_in_project"],
                "system_role": u["role"]
            })
    
    return {"items": result}
