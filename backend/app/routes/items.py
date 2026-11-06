"""
Routes - Items/Materials CRUD with server-side pagination and filters.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Tuple
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user
from app.tenancy.data_access import TenantData
from app.utils.audit import log_audit
from ..models.items import ITEM_CATEGORIES, ItemCreate, ItemUpdate

router = APIRouter(tags=["Items"])


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (R0-02)."""
    return TenantData.for_user(db, user)


# R0-02 (AUD-026): the client filter names a field of the ItemCreate/ItemUpdate
# model and one operator the DataTable sends for it. Anything else — the tenant
# keys, ``_id``, a ``$`` operator, an unknown field or operator — is a 400 before
# the database is touched; nothing is ever copied from the request into a query key.
TEXT_OPS = frozenset({"contains", "equals"})
NUMBER_OPS = frozenset({"min", "max"})
DATE_OPS = frozenset({"from", "to"})
FILTER_FIELDS = {
    "sku": TEXT_OPS,
    "name": TEXT_OPS,
    "unit": TEXT_OPS,
    "category": TEXT_OPS | {"in"},
    "brand": TEXT_OPS,
    "description": TEXT_OPS,
    "default_price": NUMBER_OPS,
    "min_stock": NUMBER_OPS,
    "is_active": frozenset({"bool"}),
    "created_at": DATE_OPS,
    "updated_at": DATE_OPS,
}
SORT_FIELDS = frozenset({"sku", "name", "unit", "category", "brand", "default_price",
                         "min_stock", "is_active", "created_at", "updated_at"})
FORBIDDEN_FIELDS = frozenset({"org_id", "tenant_id", "_id"})


def _bad_filter(detail: str):
    raise HTTPException(status_code=400, detail="Invalid filter: %s" % detail)


def parse_filters(filters: Optional[str]) -> List[Tuple[str, str, str]]:
    """Parse 'name.contains=test,category.in=A|B' into checked (field, op, value).

    Raises 400 for a forbidden, unknown or malformed key.
    """
    if not filters:
        return []
    result = []
    for part in filters.split(","):
        if not part:
            continue
        if "=" not in part:
            _bad_filter("expected key=value")
        key, value = part.split("=", 1)
        if "$" in key:
            _bad_filter("operator keys are not allowed")
        if "." in key:
            field, op = key.rsplit(".", 1)
        else:
            field, op = key, "equals"
        if field in FORBIDDEN_FIELDS:
            _bad_filter("field %r cannot be filtered" % field)
        if field not in FILTER_FIELDS:
            _bad_filter("unknown field %r" % field)
        if op not in FILTER_FIELDS[field]:
            _bad_filter("operator %r is not allowed for %r" % (op, field))
        if op in NUMBER_OPS:
            try:
                float(value)
            except ValueError:
                _bad_filter("%r needs a number" % key)
        result.append((field, op, value))
    return result


def build_mongo_query(filters: List[Tuple[str, str, str]]) -> dict:
    """Build the MongoDB filter from checked filters. The tenant is added by TenantData."""
    query = {}

    for field, op, value in filters:
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
    if sort_by not in SORT_FIELDS:
        raise HTTPException(status_code=400, detail="Invalid sort_by: unknown field %r" % sort_by)
    query = build_mongo_query(parse_filters(filters))
    tenant = _tenant(user)
    
    # Global search
    if search:
        query["$or"] = [
            {"sku": {"$regex": re.escape(search), "$options": "i"}},
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"brand": {"$regex": re.escape(search), "$options": "i"}},
            {"description": {"$regex": re.escape(search), "$options": "i"}},
        ]
    
    # Count total
    total = await tenant.items.count_documents(query)
    
    # Sort
    sort_direction = 1 if sort_dir == "asc" else -1
    
    # Paginate
    skip = (page - 1) * page_size
    items = await tenant.items.find(query, {"_id": 0}).sort(sort_by, sort_direction).skip(skip).limit(page_size).to_list(page_size)
    
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
    
    tenant = _tenant(user)
    # Check SKU uniqueness
    existing = await tenant.items.find_one({"sku": data.sku.upper()})
    if existing:
        raise HTTPException(status_code=400, detail="Item with this SKU already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": str(uuid.uuid4()),
        "org_id": tenant.org_id,
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
    
    await tenant.items.insert_one(item)
    await log_audit(user["org_id"], user["id"], user["email"], "item_created", "item", item["id"],
                    {"sku": data.sku, "name": data.name})
    
    return {k: v for k, v in item.items() if k != "_id"}


@router.get("/items/{item_id}")
async def get_item(item_id: str, user: dict = Depends(get_current_user)):
    """Get item details"""
    item = await _tenant(user).items.require(item_id, {"_id": 0}, detail="Item not found")
    # W0-03E: in MASTER_DATA_MODE=enforce the legacy record also names its Master
    # record (master_ref); every legacy field and the old id stay as they are.
    from app.master_data.legacy_adapter import annotate
    return (await annotate(user, "items", [item]))[0]


@router.put("/items/{item_id}")
async def update_item(item_id: str, data: ItemUpdate, user: dict = Depends(get_current_user)):
    """Update item"""
    if user["role"] not in ["Admin", "Owner", "Accountant", "Warehousekeeper"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    tenant = _tenant(user)
    await tenant.items.require(item_id, detail="Item not found")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # W0-03E-A2B: this tenant's item only (ids collide across tenants).
    await tenant.items.update_one({"id": item_id}, {"$set": update})
    return await tenant.items.get(item_id, {"_id": 0})


@router.delete("/items/{item_id}")
async def delete_item(item_id: str, user: dict = Depends(get_current_user)):
    """Delete item (soft delete)"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    tenant = _tenant(user)
    await tenant.items.require(item_id, detail="Item not found")
    
    await tenant.items.update_one(
        {"id": item_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"ok": True}


@router.get("/items/enums/categories")
async def get_item_categories():
    """Get available item categories"""
    return {"categories": ITEM_CATEGORIES}
