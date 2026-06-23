"""
Routes - Brigades (groups of akord workers).

A brigade groups akord (piece-rate) employee dossiers so their output can be
measured and settled together via a brigade slip (фиш). A person keeps a single
dossier and may also be paid on salary in other periods; the brigade only groups
them for akord work.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.modules import require_m4
from app.utils.audit import log_audit
from pydantic import BaseModel

router = APIRouter(tags=["Brigades"])


class BrigadeCreate(BaseModel):
    name: str
    leader_user_id: Optional[str] = None
    notes: Optional[str] = None


class BrigadeUpdate(BaseModel):
    name: Optional[str] = None
    leader_user_id: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class BrigadeMember(BaseModel):
    user_id: str


async def _member_names(org_id: str, ids: List[str]) -> dict:
    """Return {user_id: full name} for the given ids."""
    if not ids:
        return {}
    users = await db.users.find(
        {"org_id": org_id, "id": {"$in": ids}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1},
    ).to_list(200)
    return {u["id"]: f"{u.get('first_name','')} {u.get('last_name','')}".strip() for u in users}


@router.post("/brigades")
async def create_brigade(data: BrigadeCreate, user: dict = Depends(require_m4)):
    now = datetime.now(timezone.utc).isoformat()
    brigade = {
        "id": str(uuid.uuid4()), "org_id": user["org_id"],
        "name": data.name.strip(),
        "leader_user_id": data.leader_user_id,
        "member_ids": [data.leader_user_id] if data.leader_user_id else [],
        "notes": data.notes,
        "active": True,
        "created_at": now, "updated_at": now,
    }
    await db.brigades.insert_one(brigade)
    await log_audit(user["org_id"], user["id"], user["email"], "brigade_created", "brigade", brigade["id"], {"name": brigade["name"]})
    return {k: v for k, v in brigade.items() if k != "_id"}


@router.get("/brigades")
async def list_brigades(active: Optional[bool] = None, user: dict = Depends(require_m4)):
    q = {"org_id": user["org_id"]}
    if active is not None:
        q["active"] = active
    brigades = await db.brigades.find(q, {"_id": 0}).sort("name", 1).to_list(500)
    return brigades


@router.get("/brigades/{brigade_id}")
async def get_brigade(brigade_id: str, user: dict = Depends(require_m4)):
    b = await db.brigades.find_one({"org_id": user["org_id"], "id": brigade_id}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Brigade not found")
    names = await _member_names(user["org_id"], b.get("member_ids", []))
    b["members"] = [{"user_id": uid, "name": names.get(uid, "")} for uid in b.get("member_ids", [])]
    return b


@router.put("/brigades/{brigade_id}")
async def update_brigade(brigade_id: str, data: BrigadeUpdate, user: dict = Depends(require_m4)):
    b = await db.brigades.find_one({"org_id": user["org_id"], "id": brigade_id})
    if not b:
        raise HTTPException(status_code=404, detail="Brigade not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.brigades.update_one({"id": brigade_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "brigade_updated", "brigade", brigade_id, update)
    return {**{k: v for k, v in b.items() if k != "_id"}, **update}


@router.post("/brigades/{brigade_id}/members")
async def add_brigade_member(brigade_id: str, data: BrigadeMember, user: dict = Depends(require_m4)):
    b = await db.brigades.find_one({"org_id": user["org_id"], "id": brigade_id})
    if not b:
        raise HTTPException(status_code=404, detail="Brigade not found")
    target = await db.users.find_one({"org_id": user["org_id"], "id": data.user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.brigades.update_one(
        {"id": brigade_id},
        {"$addToSet": {"member_ids": data.user_id}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_audit(user["org_id"], user["id"], user["email"], "brigade_member_added", "brigade", brigade_id, {"user_id": data.user_id})
    return await get_brigade(brigade_id, user)


@router.delete("/brigades/{brigade_id}/members/{user_id}")
async def remove_brigade_member(brigade_id: str, user_id: str, user: dict = Depends(require_m4)):
    b = await db.brigades.find_one({"org_id": user["org_id"], "id": brigade_id})
    if not b:
        raise HTTPException(status_code=404, detail="Brigade not found")
    await db.brigades.update_one(
        {"id": brigade_id},
        {"$pull": {"member_ids": user_id}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_audit(user["org_id"], user["id"], user["email"], "brigade_member_removed", "brigade", brigade_id, {"user_id": user_id})
    return await get_brigade(brigade_id, user)


@router.delete("/brigades/{brigade_id}")
async def delete_brigade(brigade_id: str, user: dict = Depends(require_m4)):
    b = await db.brigades.find_one({"org_id": user["org_id"], "id": brigade_id})
    if not b:
        raise HTTPException(status_code=404, detail="Brigade not found")
    await db.brigades.update_one({"id": brigade_id}, {"$set": {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}})
    await log_audit(user["org_id"], user["id"], user["email"], "brigade_archived", "brigade", brigade_id, {})
    return {"ok": True, "archived": True}
