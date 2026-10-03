"""
Routes - Asset Item Types (динамични типове артикули).
Вградените machine/tool остават; новите се трупат в нова колекция asset_item_types.
Никоя съществуваща колекция не се променя.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
import uuid, re

from app.db import db
from app.deps.auth import get_current_user, require_admin
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["AssetItemTypes"])

BUILTIN_TYPES = [
    {"key": "machine", "label_bg": "Машина", "builtin": True},
    {"key": "tool", "label_bg": "Ръчен инструмент", "builtin": True},
]


class TypeCreate(BaseModel):
    label_bg: str
    key: Optional[str] = None


def _slugify(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^a-z0-9а-я]+", "_", t)
    return t.strip("_") or f"type_{uuid.uuid4().hex[:6]}"


async def all_type_keys(org_id: str, db_handle=None) -> set:
    _db = db if db_handle is None else db_handle
    # W0-03E-A2C + W0-02 PR-04: the tenant view is bound to the handle this
    # caller gave us, so the read and the write stay in the SAME tenant database.
    tenant = TenantData.for_resolved_org(_db, org_id)
    keys = {t["key"] for t in BUILTIN_TYPES}
    async for t in tenant.asset_item_types.find({"org_id": org_id}, {"_id": 0, "key": 1}):
        keys.add(t["key"])
    return keys


@router.get("/assets/item-types")
async def list_types(user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    custom = await tenant.asset_item_types.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(200)
    return {"items": BUILTIN_TYPES + [{**t, "builtin": False} for t in custom]}


@router.post("/assets/item-types", status_code=201)
async def create_type(data: TypeCreate, user: dict = Depends(require_admin)):
    tenant = _tenant(user)
    label = (data.label_bg or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label required")
    key = _slugify(data.key or label)
    existing = await all_type_keys(user["org_id"])
    if key in existing:
        return {"key": key, "label_bg": label, "builtin": key in {b["key"] for b in BUILTIN_TYPES}, "already": True}
    rec = {"id": str(uuid.uuid4()), "org_id": user["org_id"], "key": key,
           "label_bg": label, "created_by": user["id"]}
    await tenant.asset_item_types.insert_one(rec)
    rec.pop("_id", None)
    rec["builtin"] = False
    return rec
