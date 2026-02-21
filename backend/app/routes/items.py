"""
Routes - Items/Materials CRUD with server-side pagination and filters.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user
from app.utils.audit import log_audit
from ..models.items import ITEM_CATEGORIES, ItemCreate, ItemUpdate

router = APIRouter(tags=["Items"])


def parse_filters(filters: Optional[str]) -> dict:
    """Parse filter string like 'name.contains=test,category.equals=Materials'"""
    if not filters:
        return {}
    result = {}
    for part in filters.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def build_mongo_query(org_id: str, filters: dict) -> dict:
    """Build MongoDB query from parsed filters"""
    query = {"org_id": org_id}
    
    for key, value in filters.items():
        if "." in key:
            field, op = key.rsplit(".", 1)
        else:
            field, op = key, "equals"
        
        if op == "contains":
            query[field] = {"$regex": re.escape(value), "$options": "i"}
        elif op == "equals":
            query[field] = value
        elif op == "min":
            query[field] = query.get(field, {})
            query[field]["$gte"] = float(value)
        elif op == "max":
            query[field] = query.get(field, {})
            query[field]["$lte"] = float(value)
        elif op == "from":
            query[field] = query.get(field, {})
            query[field]["$gte"] = value
        elif op == "to":
            query[field] = query.get(field, {})
            query[field]["$lte"] = value
        elif op == "in":
            query[field] = {"$in": value.split("|")}
        elif op == "bool":
            query[field] = value.lower() == "true"
    
    return query


@router.get("/items")
async def list_items(
    user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("sku"),
    sort_dir: str = Query("asc"),
    search: Optional[str] = None,
    filters: Optional[str] = None,
):
    """List items with pagination, sorting, and filters"""
    parsed_filters = parse_filters(filters)
    query = build_mongo_query(user["org_id"], parsed_filters)
    
    # Global search
    if search:
        query["$or"] = [
            {"sku": {"$regex": re.escape(search), "$options": "i"}},
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"brand": {"$regex": re.escape(search), "$options": "i"}},
            {"description": {"$regex": re.escape(search), "$options": "i"}},
        ]
    
    # Count total
    total = await db.items.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    
    # Paginate
    skip = (page - 1) * page_size
    items = await db.items.find(query, {"_id": 0}).sort(sort_by, sort_direction).skip(skip).limit(page_size).to_list(page_size)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/items", status_code=201)
async def create_item(data: ItemCreate, user: dict = Depends(get_current_user)):
    """Create a new item"""
    if user["role"] not in ["Admin", "Owner", "Accountant", "Warehousekeeper"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Check SKU uniqueness
    existing = await db.items.find_one({"org_id": user["org_id"], "sku": data.sku.upper()})
    if existing:
        raise HTTPException(status_code=400, detail="Item with this SKU already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "sku": data.sku.upper(),
        "name": data.name,
        "unit": data.unit,
        "category": data.category,
        "brand": data.brand,
        "description": data.description,
        "default_price": data.default_price,
        "min_stock": data.min_stock,
        "is_active": data.is_active,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.items.insert_one(item)
    await log_audit(user["org_id"], user["id"], user["email"], "item_created", "item", item["id"],
                    {"sku": data.sku, "name": data.name})
    
    return {k: v for k, v in item.items() if k != "_id"}


@router.get("/items/{item_id}")
async def get_item(item_id: str, user: dict = Depends(get_current_user)):
    """Get item details"""
    item = await db.items.find_one({"id": item_id, "org_id": user["org_id"]}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.put("/items/{item_id}")
async def update_item(item_id: str, data: ItemUpdate, user: dict = Depends(get_current_user)):
    """Update item"""
    if user["role"] not in ["Admin", "Owner", "Accountant", "Warehousekeeper"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    item = await db.items.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.items.update_one({"id": item_id}, {"$set": update})
    return await db.items.find_one({"id": item_id}, {"_id": 0})


@router.delete("/items/{item_id}")
async def delete_item(item_id: str, user: dict = Depends(get_current_user)):
    """Delete item (soft delete)"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    item = await db.items.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    await db.items.update_one(
        {"id": item_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"ok": True}


@router.get("/items/enums/categories")
async def get_item_categories():
    """Get available item categories"""
    return {"categories": ITEM_CATEGORIES}
