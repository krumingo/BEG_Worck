"""
Routes - Asset Units (активи — физически бройки на артикул).
Нова колекция asset_units. Всяка бройка сочи към:
  - item_id  -> asset_items.id (артикулът)
  - location_id -> съществуващите warehouses / projects / users (по location_type)
Всяка бройка получава свой QR автоматично при създаване (през QR модула).
Материали НЕ влизат тук — те си остават в склада (FIFO).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user, require_admin
from app.routes.assets_qr import _make_qr
from app.routes.assets_custody import custody_after_move

router = APIRouter(tags=["AssetUnits"])

STATUSES = ["available", "in_use", "repair", "written_off"]
LOCATION_TYPES = ["warehouse", "project", "employee"]


class AssetUnitCreate(BaseModel):
    item_id: str
    serial_no: Optional[str] = None
    inventory_no: Optional[str] = None
    status: str = "available"
    location_type: Optional[str] = "warehouse"   # warehouse | project | employee
    location_id: Optional[str] = None            # home location (usually a warehouse)
    notes: Optional[str] = None


class AssetUnitUpdate(BaseModel):
    serial_no: Optional[str] = None
    inventory_no: Optional[str] = None
    status: Optional[str] = None
    location_type: Optional[str] = None
    location_id: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


async def _location_name(org_id: str, ltype: Optional[str], lid: Optional[str]) -> str:
    if not ltype or not lid:
        return ""
    try:
        if ltype == "warehouse":
            w = await db.warehouses.find_one({"id": lid, "org_id": org_id}, {"_id": 0, "name": 1})
            return w.get("name", "") if w else ""
        if ltype == "project":
            p = await db.projects.find_one({"id": lid, "org_id": org_id}, {"_id": 0, "name": 1})
            return p.get("name", "") if p else ""
        if ltype == "employee":
            u = await db.users.find_one({"id": lid, "org_id": org_id}, {"_id": 0, "first_name": 1, "last_name": 1, "name": 1})
            if not u:
                return ""
            return u.get("name") or f"{u.get('first_name','')} {u.get('last_name','')}".strip()
    except Exception:
        return ""
    return ""


async def _enrich(org_id: str, unit: dict) -> dict:
    item = await db.asset_items.find_one(
        {"id": unit.get("item_id"), "org_id": org_id},
        {"_id": 0, "name": 1, "type": 1, "brand": 1, "model": 1, "photo_url": 1, "purchase_date": 1, "warranty_months": 1},
    )
    unit["item_name"] = item.get("name", "") if item else ""
    unit["item_type"] = item.get("type", "") if item else ""
    unit["brand"] = item.get("brand") if item else None
    unit["model"] = item.get("model") if item else None
    unit["photo_url"] = item.get("photo_url") if item else None
    unit["purchase_date"] = item.get("purchase_date") if item else None
    unit["warranty_months"] = item.get("warranty_months") if item else None
    unit["location_name"] = await _location_name(org_id, unit.get("location_type"), unit.get("location_id"))
    # кой е въвел бройката (име)
    cb = unit.get("created_by")
    if cb:
        u = await db.users.find_one({"id": cb, "org_id": org_id}, {"_id": 0, "name": 1, "first_name": 1, "last_name": 1, "email": 1})
        if u:
            unit["created_by_name"] = u.get("name") or f"{u.get('first_name','')} {u.get('last_name','')}".strip() or u.get("email") or ""
        else:
            unit["created_by_name"] = ""
    else:
        unit["created_by_name"] = ""
    return unit


@router.get("/assets/units")
async def list_asset_units(
    user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    item_id: Optional[str] = None,
    status: Optional[str] = None,
    location_type: Optional[str] = None,
    location_id: Optional[str] = None,
    search: Optional[str] = None,
):
    org = user["org_id"]
    query = {"org_id": org}
    if item_id:
        query["item_id"] = item_id
    if status:
        query["status"] = status
    if location_type:
        query["location_type"] = location_type
    if location_id:
        query["location_id"] = location_id
    if search:
        rx = {"$regex": re.escape(search), "$options": "i"}
        query["$or"] = [{"qr_id": rx}, {"serial_no": rx}, {"inventory_no": rx}]

    total = await db.asset_units.count_documents(query)
    skip = (page - 1) * page_size
    units = (
        await db.asset_units.find(query, {"_id": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(page_size)
        .to_list(page_size)
    )
    for u in units:
        await _enrich(org, u)

    return {"items": units, "total": total, "page": page, "page_size": page_size}


@router.post("/assets/units", status_code=201)
async def create_asset_unit(data: AssetUnitCreate, user: dict = Depends(require_admin)):
    org = user["org_id"]
    if data.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if data.location_type and data.location_type not in LOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid location_type")

    item = await db.asset_items.find_one({"id": data.item_id, "org_id": org}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Артикулът не е намерен")

    unit_id = str(uuid.uuid4())
    code = (data.serial_no or data.inventory_no or "").strip()
    qr = await _make_qr(org, user["id"], "asset_unit", unit_id, item.get("name", ""), code)

    doc = {
        "id": unit_id,
        "org_id": org,
        "item_id": data.item_id,
        "qr_id": qr["qr_id"],
        "serial_no": (data.serial_no or "").strip() or None,
        "inventory_no": (data.inventory_no or "").strip() or None,
        "status": data.status,
        "location_type": data.location_type if data.location_id else None,
        "location_id": data.location_id or None,
        "notes": (data.notes or "").strip() or None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.asset_units.insert_one(doc)
    doc.pop("_id", None)
    await _enrich(org, doc)
    return doc


@router.get("/assets/units/{unit_id}")
async def get_asset_unit(unit_id: str, user: dict = Depends(get_current_user)):
    unit = await db.asset_units.find_one({"id": unit_id, "org_id": user["org_id"]}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")
    await _enrich(user["org_id"], unit)
    return unit


@router.put("/assets/units/{unit_id}")
async def update_asset_unit(unit_id: str, data: AssetUnitUpdate, user: dict = Depends(require_admin)):
    org = user["org_id"]
    update = {k: v for k, v in data.dict(exclude_unset=True).items()}
    if "status" in update and update["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if "location_type" in update and update["location_type"] and update["location_type"] not in LOCATION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid location_type")
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.asset_units.update_one({"id": unit_id, "org_id": org}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    unit = await db.asset_units.find_one({"id": unit_id, "org_id": org}, {"_id": 0})
    await _enrich(org, unit)
    return unit


@router.delete("/assets/units/{unit_id}")
async def delete_asset_unit(unit_id: str, user: dict = Depends(require_admin)):
    res = await db.asset_units.delete_one({"id": unit_id, "org_id": user["org_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


# ── Movement / custody (Етап 2) ────────────────────────────────────

ACTIONS = ["take", "handover", "drop", "repair", "return"]


class MoveAction(BaseModel):
    action: str                       # take | handover | drop | repair | return
    to_type: Optional[str] = None     # employee | project | warehouse
    to_id: Optional[str] = None
    note: Optional[str] = None


def _user_name(user: dict) -> str:
    return (user.get("name")
            or f"{user.get('first_name','')} {user.get('last_name','')}".strip()
            or (user.get("email", "").split("@")[0] if user.get("email") else ""))


@router.post("/assets/units/{unit_id}/move")
async def move_unit(unit_id: str, data: MoveAction, user: dict = Depends(get_current_user)):
    """Record a custody movement (scan-driven). Any logged-in user can act."""
    org = user["org_id"]
    if data.action not in ACTIONS:
        raise HTTPException(status_code=400, detail="Invalid action")
    unit = await db.asset_units.find_one({"id": unit_id, "org_id": org}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")

    from_type = unit.get("location_type")
    from_id = unit.get("location_id")
    act = data.action

    if act == "take":
        to_type, to_id, status = "employee", (data.to_id or user["id"]), "in_use"
    elif act == "handover":
        if not data.to_id:
            raise HTTPException(status_code=400, detail="to_id required")
        to_type, to_id, status = "employee", data.to_id, "in_use"
    elif act == "drop":
        if not data.to_id:
            raise HTTPException(status_code=400, detail="to_id required")
        to_type, to_id, status = "project", data.to_id, "in_use"
    elif act == "repair":
        to_type, to_id, status = from_type, from_id, "repair"
    else:  # return
        if not data.to_id:
            raise HTTPException(status_code=400, detail="to_id required")
        to_type, to_id, status = "warehouse", data.to_id, "available"

    mv = {
        "id": str(uuid.uuid4()),
        "org_id": org,
        "unit_id": unit_id,
        "action": act,
        "from_type": from_type, "from_id": from_id,
        "to_type": to_type, "to_id": to_id,
        "by_user": user["id"], "by_name": _user_name(user),
        "note": (data.note or "").strip() or None,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    await db.asset_movements.insert_one(mv)
    await custody_after_move(org, unit_id, act, data.to_id, user)
    await db.asset_units.update_one(
        {"id": unit_id, "org_id": org},
        {"$set": {"location_type": to_type, "location_id": to_id, "status": status}},
    )
    unit = await db.asset_units.find_one({"id": unit_id, "org_id": org}, {"_id": 0})
    await _enrich(org, unit)
    return unit


@router.get("/assets/units/{unit_id}/movements")
async def list_movements(unit_id: str, user: dict = Depends(get_current_user)):
    org = user["org_id"]
    movements = (
        await db.asset_movements.find({"org_id": org, "unit_id": unit_id}, {"_id": 0})
        .sort("at", -1)
        .to_list(200)
    )
    for m in movements:
        m["from_name"] = await _location_name(org, m.get("from_type"), m.get("from_id"))
        m["to_name"] = await _location_name(org, m.get("to_type"), m.get("to_id"))
    return {"items": movements}
