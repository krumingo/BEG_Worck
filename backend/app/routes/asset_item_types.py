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


async def all_type_keys(org_id: str) -> set:
    keys = {t["key"] for t in BUILTIN_TYPES}
    async for t in db.asset_item_types.find({"org_id": org_id}, {"_id": 0, "key": 1}):
        keys.add(t["key"])
    return keys


@router.get("/assets/item-types")
async def list_types(user: dict = Depends(get_current_user)):
    custom = await db.asset_item_types.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(200)
    return {"items": BUILTIN_TYPES + [{**t, "builtin": False} for t in custom]}


@router.post("/assets/item-types", status_code=201)
async def create_type(data: TypeCreate, user: dict = Depends(require_admin)):
    label = (data.label_bg or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label required")
    key = _slugify(data.key or label)
    existing = await all_type_keys(user["org_id"])
    if key in existing:
        return {"key": key, "label_bg": label, "builtin": key in {b["key"] for b in BUILTIN_TYPES}, "already": True}
    rec = {"id": str(uuid.uuid4()), "org_id": user["org_id"], "key": key,
           "label_bg": label, "created_by": user["id"]}
    await db.asset_item_types.insert_one(rec)
    rec.pop("_id", None)
    rec["builtin"] = False
    return rec
