"""
Routes - Warehouses (Inventory locations) with pagination and filters.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user
from app.utils.audit import log_audit
from ..models.warehouse import (
    WAREHOUSE_TYPES,
    WarehouseCreate, WarehouseUpdate
)

router = APIRouter(tags=["Warehouses"])


def warehouse_permission(user: dict) -> bool:
    """Check if user has warehouse management access"""
    return user["role"] in ["Admin", "Owner", "SiteManager", "Warehousekeeper"]


def parse_filters(filters: Optional[str]) -> dict:
    """Parse filter string"""
    if not filters:
        return {}
    result = {}
    for part in filters.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def build_mongo_query(org_id: str, filters: dict, base_query: dict = None) -> dict:
    """Build MongoDB query from parsed filters"""
    query = base_query or {"org_id": org_id}
    
    for key, value in filters.items():
        if "." in key:
            field, op = key.rsplit(".", 1)
        else:
            field, op = key, "equals"
        
        if op == "contains":
            query[field] = {"$regex": re.escape(value), "$options": "i"}
        elif op == "equals":
            query[field] = value
        elif op == "in":
            query[field] = {"$in": value.split("|")}
        elif op == "bool":
            query[field] = value.lower() == "true"
    
    return query


# ── Warehouses CRUD ────────────────────────────────────────────────

@router.get("/warehouses")
async def list_warehouses(
    user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("code"),
    sort_dir: str = Query("asc"),
    search: Optional[str] = None,
    filters: Optional[str] = None,
    type: Optional[str] = None,
    project_id: Optional[str] = None,
    active_only: bool = True,
):
    """List warehouses with pagination, sorting, and filters"""
    base_query = {"org_id": user["org_id"]}
    
    if type:
        base_query["type"] = type
    if project_id:
        base_query["project_id"] = project_id
    if active_only:
        base_query["active"] = True
    
    parsed_filters = parse_filters(filters)
    query = build_mongo_query(user["org_id"], parsed_filters, base_query)
    
    # Global search
    if search:
        query["$or"] = [
            {"code": {"$regex": re.escape(search), "$options": "i"}},
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"address": {"$regex": re.escape(search), "$options": "i"}},
        ]
    
    # Count total
    total = await db.warehouses.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    
    # Paginate
    skip = (page - 1) * page_size
    warehouses = await db.warehouses.find(query, {"_id": 0}).sort(sort_by, sort_direction).skip(skip).limit(page_size).to_list(page_size)
    
    # Enrich with reference names
    for wh in warehouses:
        if wh.get("project_id"):
            proj = await db.projects.find_one({"id": wh["project_id"]}, {"_id": 0, "code": 1, "name": 1})
            wh["project_code"] = proj["code"] if proj else ""
            wh["project_name"] = proj["name"] if proj else ""
        if wh.get("person_id"):
            person = await db.persons.find_one({"id": wh["person_id"]}, {"_id": 0, "first_name": 1, "last_name": 1})
            wh["person_name"] = f"{person['first_name']} {person['last_name']}" if person else ""
        if wh.get("vehicle_id"):
            # TODO: Add vehicle lookup when vehicle collection exists
            wh["vehicle_name"] = wh.get("vehicle_id", "")
    
    return warehouses


@router.post("/warehouses", status_code=201)
async def create_warehouse(data: WarehouseCreate, user: dict = Depends(get_current_user)):
    """Create a new warehouse"""
    if not warehouse_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Validate type-specific references
    if data.type == "project" and not data.project_id:
        raise HTTPException(status_code=400, detail="project_id required for project warehouse")
    if data.type == "vehicle" and not data.vehicle_id:
        raise HTTPException(status_code=400, detail="vehicle_id required for vehicle warehouse")
    if data.type == "person" and not data.person_id:
        raise HTTPException(status_code=400, detail="person_id required for person warehouse")
    
    # Check code uniqueness
    existing = await db.warehouses.find_one({
        "org_id": user["org_id"],
        "code": data.code.upper()
    })
    if existing:
        raise HTTPException(status_code=400, detail="Warehouse code already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    warehouse = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "code": data.code.upper(),
        "name": data.name,
        "type": data.type,
        "project_id": data.project_id if data.type == "project" else None,
        "vehicle_id": data.vehicle_id if data.type == "vehicle" else None,
        "person_id": data.person_id if data.type == "person" else None,
        "address": data.address,
        "notes": data.notes,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.warehouses.insert_one(warehouse)
    await log_audit(user["org_id"], user["id"], user["email"], "warehouse_created", "warehouse", warehouse["id"],
                    {"code": data.code, "type": data.type})
    
    return {k: v for k, v in warehouse.items() if k != "_id"}


@router.get("/warehouses/{warehouse_id}")
async def get_warehouse(warehouse_id: str, user: dict = Depends(get_current_user)):
    """Get warehouse details"""
    warehouse = await db.warehouses.find_one(
        {"id": warehouse_id, "org_id": user["org_id"]},
        {"_id": 0}
    )
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    
    # Enrich with reference names
    if warehouse.get("project_id"):
        proj = await db.projects.find_one({"id": warehouse["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        warehouse["project_code"] = proj["code"] if proj else ""
        warehouse["project_name"] = proj["name"] if proj else ""
    
    return warehouse


@router.put("/warehouses/{warehouse_id}")
async def update_warehouse(warehouse_id: str, data: WarehouseUpdate, user: dict = Depends(get_current_user)):
    """Update warehouse"""
    if not warehouse_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    warehouse = await db.warehouses.find_one({"id": warehouse_id, "org_id": user["org_id"]})
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    
    # Validate type change references
    new_type = update.get("type", warehouse["type"])
    if new_type == "project" and not (update.get("project_id") or warehouse.get("project_id")):
        raise HTTPException(status_code=400, detail="project_id required for project warehouse")
    if new_type == "vehicle" and not (update.get("vehicle_id") or warehouse.get("vehicle_id")):
        raise HTTPException(status_code=400, detail="vehicle_id required for vehicle warehouse")
    if new_type == "person" and not (update.get("person_id") or warehouse.get("person_id")):
        raise HTTPException(status_code=400, detail="person_id required for person warehouse")
    
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.warehouses.update_one({"id": warehouse_id}, {"$set": update})
    return await db.warehouses.find_one({"id": warehouse_id}, {"_id": 0})


@router.delete("/warehouses/{warehouse_id}")
async def delete_warehouse(warehouse_id: str, user: dict = Depends(get_current_user)):
    """Delete warehouse (soft delete by setting active=false)"""
    if not warehouse_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    warehouse = await db.warehouses.find_one({"id": warehouse_id, "org_id": user["org_id"]})
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    
    # Check if warehouse has inventory
    # TODO: Add inventory check when inventory module is implemented
    
    await db.warehouses.update_one(
        {"id": warehouse_id},
        {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"ok": True}


@router.get("/warehouses/enums/types")
async def get_warehouse_types():
    """Get available warehouse types"""
    return {"types": WAREHOUSE_TYPES}


# ── DEV-ONLY Endpoints ─────────────────────────────────────────────

@router.post("/dev/reset-warehouses")
async def dev_reset_warehouses(user: dict = Depends(get_current_user)):
    """
    DEV ONLY: Delete all warehouses for the current organization.
    Used for testing the "first warehouse" flow.
    Blocked in production.
    """
    import os
    
    # Block in production
    env = os.environ.get("ENVIRONMENT", "development")
    if env == "production":
        raise HTTPException(status_code=403, detail="This endpoint is not available in production")
    
    if not warehouse_permission(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Delete all warehouses for this org
    result = await db.warehouses.delete_many({"org_id": user["org_id"]})
    
    # Also clear any invoice line allocations pointing to warehouses
    # (optional: keep allocations but they will reference non-existent warehouses)
    
    return {
        "ok": True,
        "deleted_count": result.deleted_count,
        "message": f"Deleted {result.deleted_count} warehouses for org {user['org_id']}"
    }
