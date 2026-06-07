"""
Routes - Assets module / Етап 0: Universal QR base.

A single QR identity (qr_id) per entity that POINTS to existing records
(projects/employees/warehouses) without duplicating them. Guests and repair
locations are lightweight entities owned by this module (name stored locally).

Multi-tenant: everything is scoped by user["org_id"].
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
from pymongo import ReturnDocument
import uuid
import re

from app.db import db
from app.deps.auth import get_current_user, require_admin

router = APIRouter(tags=["Assets QR"])

# Entity types a QR can point to.
REFERENCED_TYPES = ["project", "employee", "warehouse"]   # point to existing records
OWNED_TYPES = ["guest", "repair"]                         # lightweight, name stored here
VALID_TYPES = REFERENCED_TYPES + OWNED_TYPES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _next_qr_id(org_id: str) -> str:
    """Sequential, human-friendly QR id per organization (QR-000001)."""
    doc = await db.asset_counters.find_one_and_update(
        {"org_id": org_id, "name": "qr"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"QR-{doc['seq']:06d}"


async def _resolve_name(org_id: str, entity_type: str, entity_id: Optional[str], name: Optional[str]):
    """Return (name, code) for the entity, validating it exists for referenced types."""
    if entity_type == "project":
        p = await db.projects.find_one({"id": entity_id, "org_id": org_id}, {"_id": 0, "name": 1, "code": 1})
        if not p:
            raise HTTPException(status_code=404, detail="Project not found")
        return p.get("name", ""), p.get("code", "")
    if entity_type == "employee":
        u = await db.users.find_one(
            {"id": entity_id, "org_id": org_id},
            {"_id": 0, "name": 1, "first_name": 1, "last_name": 1, "email": 1},
        )
        if not u:
            raise HTTPException(status_code=404, detail="Employee not found")
        nm = (u.get("name")
              or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
              or (u.get("email", "").split("@")[0] if u.get("email") else ""))
        return nm, ""
    if entity_type == "warehouse":
        w = await db.warehouses.find_one({"id": entity_id, "org_id": org_id}, {"_id": 0, "name": 1})
        if not w:
            raise HTTPException(status_code=404, detail="Warehouse not found")
        return w.get("name", ""), ""
    if entity_type in OWNED_TYPES:
        if not name or not name.strip():
            raise HTTPException(status_code=400, detail="Name is required for guest/repair")
        return name.strip(), ""
    raise HTTPException(status_code=400, detail="Invalid entity_type")


async def _make_qr(org_id: str, created_by: str, entity_type: str, entity_id: str, name: str, code: str) -> dict:
    qr_id = await _next_qr_id(org_id)
    doc = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "qr_id": qr_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "name": name,
        "code": code,
        "status": "active",
        "created_at": _now(),
        "created_by": created_by,
        "last_used_at": None,
    }
    await db.asset_qr_codes.insert_one(doc)
    doc.pop("_id", None)
    return doc


class QRGenerate(BaseModel):
    entity_type: str
    entity_id: Optional[str] = None   # required for project/employee/warehouse
    name: Optional[str] = None        # required for guest/repair


class QRBulk(BaseModel):
    types: Optional[List[str]] = None  # defaults to all referenced types


class QRStatus(BaseModel):
    status: str  # active | inactive


@router.get("/assets/qr")
async def list_qr(
    type: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    org_id = user["org_id"]
    query: dict = {"org_id": org_id}
    if type and type != "all":
        query["entity_type"] = type
    if status:
        query["status"] = status
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"name": rx}, {"qr_id": rx}, {"code": rx}]
    total = await db.asset_qr_codes.count_documents(query)
    skip = (page - 1) * page_size
    items = await (
        db.asset_qr_codes.find(query, {"_id": 0})
        .sort("qr_id", 1)
        .skip(skip)
        .limit(page_size)
        .to_list(page_size)
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/assets/qr/generate")
async def generate_qr(data: QRGenerate, user: dict = Depends(require_admin)):
    org_id = user["org_id"]
    et = data.entity_type
    if et not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="Invalid entity_type")

    if et in REFERENCED_TYPES:
        if not data.entity_id:
            raise HTTPException(status_code=400, detail="entity_id is required")
        entity_id = data.entity_id
        # Idempotent: one QR per referenced entity
        existing = await db.asset_qr_codes.find_one(
            {"org_id": org_id, "entity_type": et, "entity_id": entity_id}, {"_id": 0}
        )
        if existing:
            return existing
    else:
        entity_id = str(uuid.uuid4())  # guest/repair get their own generated id

    name, code = await _resolve_name(org_id, et, data.entity_id, data.name)
    return await _make_qr(org_id, user["id"], et, entity_id, name, code)


@router.post("/assets/qr/generate-bulk")
async def generate_bulk(data: QRBulk, user: dict = Depends(require_admin)):
    org_id = user["org_id"]
    types = [t for t in (data.types or REFERENCED_TYPES) if t in REFERENCED_TYPES]
    created = {"project": 0, "employee": 0, "warehouse": 0}

    if "project" in types:
        async for p in db.projects.find({"org_id": org_id}, {"_id": 0, "id": 1, "name": 1, "code": 1}):
            if await db.asset_qr_codes.find_one({"org_id": org_id, "entity_type": "project", "entity_id": p["id"]}):
                continue
            await _make_qr(org_id, user["id"], "project", p["id"], p.get("name", ""), p.get("code", ""))
            created["project"] += 1

    if "employee" in types:
        async for u in db.users.find(
            {"org_id": org_id, "is_active": True},
            {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1, "email": 1},
        ):
            if await db.asset_qr_codes.find_one({"org_id": org_id, "entity_type": "employee", "entity_id": u["id"]}):
                continue
            nm = (u.get("name")
                  or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                  or (u.get("email", "").split("@")[0] if u.get("email") else ""))
            await _make_qr(org_id, user["id"], "employee", u["id"], nm, "")
            created["employee"] += 1

    if "warehouse" in types:
        async for w in db.warehouses.find({"org_id": org_id}, {"_id": 0, "id": 1, "name": 1}):
            if await db.asset_qr_codes.find_one({"org_id": org_id, "entity_type": "warehouse", "entity_id": w["id"]}):
                continue
            await _make_qr(org_id, user["id"], "warehouse", w["id"], w.get("name", ""), "")
            created["warehouse"] += 1

    return {"created": created, "total": sum(created.values())}


@router.get("/assets/qr/resolve/{qr_id}")
async def resolve_qr(qr_id: str, user: dict = Depends(get_current_user)):
    """Universal scan endpoint: returns what this QR points to and stamps last_used_at."""
    org_id = user["org_id"]
    doc = await db.asset_qr_codes.find_one({"org_id": org_id, "qr_id": qr_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="QR not found")
    now = _now()
    await db.asset_qr_codes.update_one(
        {"org_id": org_id, "qr_id": qr_id}, {"$set": {"last_used_at": now}}
    )
    doc["last_used_at"] = now
    return doc


@router.patch("/assets/qr/{qr_id}/status")
async def set_qr_status(qr_id: str, data: QRStatus, user: dict = Depends(require_admin)):
    if data.status not in ("active", "inactive"):
        raise HTTPException(status_code=400, detail="status must be active or inactive")
    org_id = user["org_id"]
    res = await db.asset_qr_codes.update_one(
        {"org_id": org_id, "qr_id": qr_id}, {"$set": {"status": data.status}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="QR not found")
    return {"qr_id": qr_id, "status": data.status}
