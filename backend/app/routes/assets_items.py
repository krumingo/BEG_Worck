"""
Routes - Asset Items (артикули — каталог на машини/инструменти).
Нова колекция asset_items. НЕ пипа съществуващи колекции.
Моделът е Артикул (каталог) -> Активи (физически бройки, идват в Етап 1B).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user, require_admin

router = APIRouter(tags=["AssetItems"])

ASSET_ITEM_TYPES = ["machine", "tool"]


class AssetItemCreate(BaseModel):
    name: str
    type: str = "tool"            # machine | tool
    group: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    article_no: Optional[str] = None
    unit: str = "бр"
    purchase_price: Optional[float] = None
    purchase_currency: str = "EUR"
    purchase_date: Optional[str] = None
    warranty_months: Optional[int] = None
    activities: List[str] = []
    photo_url: Optional[str] = None


class AssetItemUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    group: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    article_no: Optional[str] = None
    unit: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_currency: Optional[str] = None
    purchase_date: Optional[str] = None
    warranty_months: Optional[int] = None
    activities: Optional[List[str]] = None
    photo_url: Optional[str] = None
    is_active: Optional[bool] = None


def _parse_filters(filters: Optional[str]) -> dict:
    if not filters:
        return {}
    result = {}
    for part in filters.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def _build_query(filters: dict, base_query: dict) -> dict:
    query = base_query
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


async def _count_units(org_id: str, item_id: str) -> int:
    # Units (asset_units) come in Етап 1B; collection may not exist yet -> 0.
    try:
        return await db.asset_units.count_documents({"org_id": org_id, "item_id": item_id})
    except Exception:
        return 0


@router.get("/assets/items")
async def list_asset_items(
    user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    search: Optional[str] = None,
    filters: Optional[str] = None,
    type: Optional[str] = None,
    active_only: bool = False,
):
    """List asset items (артикули) with pagination, sorting, search, filters."""
    base_query = {"org_id": user["org_id"]}
    if type:
        base_query["type"] = type
    if active_only:
        base_query["is_active"] = True

    query = _build_query(_parse_filters(filters), base_query)

    if search:
        query["$or"] = [
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"brand": {"$regex": re.escape(search), "$options": "i"}},
            {"model": {"$regex": re.escape(search), "$options": "i"}},
            {"article_no": {"$regex": re.escape(search), "$options": "i"}},
        ]

    total = await db.asset_items.count_documents(query)
    sort_direction = 1 if sort_dir == "asc" else -1
    skip = (page - 1) * page_size
    items = (
        await db.asset_items.find(query, {"_id": 0})
        .sort(sort_by, sort_direction)
        .skip(skip)
        .limit(page_size)
        .to_list(page_size)
    )
    for it in items:
        it["asset_count"] = await _count_units(user["org_id"], it["id"])

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/assets/items", status_code=201)
async def create_asset_item(data: AssetItemCreate, user: dict = Depends(require_admin)):
    if data.type not in ASSET_ITEM_TYPES:
        raise HTTPException(status_code=400, detail="Invalid type")
    item = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "name": data.name.strip(),
        "type": data.type,
        "group": (data.group or "").strip() or None,
        "brand": (data.brand or "").strip() or None,
        "model": (data.model or "").strip() or None,
        "article_no": (data.article_no or "").strip() or None,
        "unit": (data.unit or "бр").strip() or "бр",
        "purchase_price": data.purchase_price,
        "purchase_currency": data.purchase_currency or "EUR",
        "purchase_date": data.purchase_date,
        "warranty_months": data.warranty_months,
        "activities": data.activities or [],
        "photo_url": data.photo_url,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.asset_items.insert_one(item)
    item.pop("_id", None)
    item["asset_count"] = 0
    return item


@router.get("/assets/items/{item_id}")
async def get_asset_item(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.asset_items.find_one({"id": item_id, "org_id": user["org_id"]}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    item["asset_count"] = await _count_units(user["org_id"], item_id)
    return item


@router.put("/assets/items/{item_id}")
async def update_asset_item(item_id: str, data: AssetItemUpdate, user: dict = Depends(require_admin)):
    update = {k: v for k, v in data.dict(exclude_unset=True).items()}
    if "type" in update and update["type"] not in ASSET_ITEM_TYPES:
        raise HTTPException(status_code=400, detail="Invalid type")
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.asset_items.update_one(
        {"id": item_id, "org_id": user["org_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    item = await db.asset_items.find_one({"id": item_id, "org_id": user["org_id"]}, {"_id": 0})
    item["asset_count"] = await _count_units(user["org_id"], item_id)
    return item


@router.delete("/assets/items/{item_id}")
async def delete_asset_item(item_id: str, user: dict = Depends(require_admin)):
    # Safety: block delete if this артикул already has физически активи.
    if await _count_units(user["org_id"], item_id) > 0:
        raise HTTPException(status_code=400, detail="Има активи към този артикул")
    res = await db.asset_items.delete_one({"id": item_id, "org_id": user["org_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}
