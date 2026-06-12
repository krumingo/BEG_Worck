"""
Routes - Asset Custody (Вълна B1: кой пази вещта + приемане).

Нова колекция asset_custody. Никоя съществуваща колекция не се променя.
Всеки запис сочи към:
  - unit_id           -> asset_units.id (вещта)
  - custodian_user_id -> users.id (пазителят)
  - given_by_user_id  -> users.id (кой я е дал)

Статуси: given (дадена, неприета) | accepted (приета) | declined (отказана) | released (върната/освободена)
Активен запис за вещ = status in [given, accepted]. Максимум един активен запис на вещ.
Полетата локация (в asset_units) и пазител са независими — вещ може да има само
локация, само пазител, или и двете (решение на Крум, 12.06.2026).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import uuid

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["AssetCustody"])

ADMIN_ROLES = ["Admin", "Owner", "SiteManager"]
ACTIVE_STATUSES = ["given", "accepted"]
PENDING_ALERT_HOURS = 24


class CustodyGive(BaseModel):
    unit_id: str
    custodian_user_id: str
    note: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _close_active(org: str, unit_id: str, status: str = "released"):
    await db.asset_custody.update_many(
        {"org_id": org, "unit_id": unit_id, "status": {"$in": ACTIVE_STATUSES}},
        {"$set": {"status": status, "released_at": _now()}},
    )


async def _enrich(org: str, rec: dict) -> dict:
    unit = await db.asset_units.find_one({"id": rec.get("unit_id"), "org_id": org}, {"_id": 0})
    item = None
    if unit and unit.get("item_id"):
        item = await db.asset_items.find_one({"id": unit["item_id"], "org_id": org}, {"_id": 0})
    rec["unit_name"] = (item or {}).get("name") or (unit or {}).get("qr_id") or rec.get("unit_id")
    for fld, out in [("custodian_user_id", "custodian_name"), ("given_by_user_id", "given_by_name")]:
        uid = rec.get(fld)
        if uid:
            u = await db.users.find_one({"id": uid, "org_id": org}, {"_id": 0, "first_name": 1, "last_name": 1, "name": 1})
            rec[out] = (u or {}).get("name") or f"{(u or {}).get('first_name', '')} {(u or {}).get('last_name', '')}".strip() or uid
        else:
            rec[out] = None
    return rec


async def custody_after_move(org: str, unit_id: str, action: str, to_id: Optional[str], user: dict):
    """Кукичка от move_unit: take = самоприемане; handover = дадена, чака приемане; return = освобождаване."""
    if action == "take":
        target = to_id or user["id"]
        await _close_active(org, unit_id)
        await db.asset_custody.insert_one({
            "id": str(uuid.uuid4()), "org_id": org, "unit_id": unit_id,
            "custodian_user_id": target, "status": "accepted",
            "given_by_user_id": user["id"],
            "given_at": _now(), "accepted_at": _now(), "released_at": None,
            "note": None,
        })
    elif action == "handover":
        await _close_active(org, unit_id)
        await db.asset_custody.insert_one({
            "id": str(uuid.uuid4()), "org_id": org, "unit_id": unit_id,
            "custodian_user_id": to_id, "status": "given",
            "given_by_user_id": user["id"],
            "given_at": _now(), "accepted_at": None, "released_at": None,
            "note": None,
        })
    elif action == "return":
        await _close_active(org, unit_id)
    # drop / repair: локацията се мени, пазителят остава непокътнат


@router.post("/assets/custody/give")
async def give_custody(data: CustodyGive, user: dict = Depends(get_current_user)):
    org = user["org_id"]
    unit = await db.asset_units.find_one({"id": data.unit_id, "org_id": org}, {"_id": 0})
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    target = await db.users.find_one({"id": data.custodian_user_id, "org_id": org}, {"_id": 0, "id": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await _close_active(org, data.unit_id)
    rec = {
        "id": str(uuid.uuid4()), "org_id": org, "unit_id": data.unit_id,
        "custodian_user_id": data.custodian_user_id,
        "status": "accepted" if data.custodian_user_id == user["id"] else "given",
        "given_by_user_id": user["id"],
        "given_at": _now(),
        "accepted_at": _now() if data.custodian_user_id == user["id"] else None,
        "released_at": None,
        "note": (data.note or "").strip() or None,
    }
    await db.asset_custody.insert_one(rec)
    rec.pop("_id", None)
    return await _enrich(org, rec)


@router.post("/assets/custody/{custody_id}/accept")
async def accept_custody(custody_id: str, user: dict = Depends(get_current_user)):
    org = user["org_id"]
    rec = await db.asset_custody.find_one({"id": custody_id, "org_id": org}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    if rec["custodian_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the custodian can accept")
    if rec["status"] != "given":
        raise HTTPException(status_code=400, detail="Not pending")
    await db.asset_custody.update_one(
        {"id": custody_id, "org_id": org},
        {"$set": {"status": "accepted", "accepted_at": _now()}},
    )
    rec = await db.asset_custody.find_one({"id": custody_id, "org_id": org}, {"_id": 0})
    return await _enrich(org, rec)


@router.post("/assets/custody/{custody_id}/decline")
async def decline_custody(custody_id: str, user: dict = Depends(get_current_user)):
    org = user["org_id"]
    rec = await db.asset_custody.find_one({"id": custody_id, "org_id": org}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    if rec["custodian_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the custodian can decline")
    if rec["status"] != "given":
        raise HTTPException(status_code=400, detail="Not pending")
    await db.asset_custody.update_one(
        {"id": custody_id, "org_id": org},
        {"$set": {"status": "declined", "released_at": _now()}},
    )
    return {"ok": True}


@router.post("/assets/custody/{custody_id}/release")
async def release_custody(custody_id: str, user: dict = Depends(get_current_user)):
    org = user["org_id"]
    rec = await db.asset_custody.find_one({"id": custody_id, "org_id": org}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    if rec["custodian_user_id"] != user["id"] and user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only the custodian or an admin can release")
    if rec["status"] not in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Not active")
    await db.asset_custody.update_one(
        {"id": custody_id, "org_id": org},
        {"$set": {"status": "released", "released_at": _now()}},
    )
    return {"ok": True}


@router.get("/assets/custody/my-pending")
async def my_pending_custody(user: dict = Depends(get_current_user)):
    org = user["org_id"]
    recs = await db.asset_custody.find(
        {"org_id": org, "custodian_user_id": user["id"], "status": "given"}, {"_id": 0}
    ).sort("given_at", -1).to_list(50)
    return {"items": [await _enrich(org, r) for r in recs]}


@router.get("/assets/custody/unit/{unit_id}")
async def unit_custody(unit_id: str, user: dict = Depends(get_current_user)):
    org = user["org_id"]
    rec = await db.asset_custody.find_one(
        {"org_id": org, "unit_id": unit_id, "status": {"$in": ACTIVE_STATUSES}}, {"_id": 0}
    )
    return {"custody": await _enrich(org, rec) if rec else None}


@router.get("/assets/custody/alerts")
async def custody_alerts(user: dict = Depends(get_current_user)):
    org = user["org_id"]
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    threshold = (datetime.now(timezone.utc) - timedelta(hours=PENDING_ALERT_HOURS)).isoformat()
    pending = await db.asset_custody.find(
        {"org_id": org, "status": "given", "given_at": {"$lte": threshold}}, {"_id": 0}
    ).sort("given_at", 1).to_list(100)
    pending = [await _enrich(org, r) for r in pending]

    units_on_projects = await db.asset_units.find(
        {"org_id": org, "location_type": "project"}, {"_id": 0, "id": 1, "item_id": 1, "qr_id": 1, "location_id": 1}
    ).to_list(500)
    unit_ids = [u["id"] for u in units_on_projects]
    covered = set()
    if unit_ids:
        async for c in db.asset_custody.find(
            {"org_id": org, "unit_id": {"$in": unit_ids}, "status": {"$in": ACTIVE_STATUSES}}, {"_id": 0, "unit_id": 1}
        ):
            covered.add(c["unit_id"])
    no_custodian = []
    for u in units_on_projects:
        if u["id"] in covered:
            continue
        item = await db.asset_items.find_one({"id": u.get("item_id"), "org_id": org}, {"_id": 0, "name": 1})
        proj = await db.projects.find_one({"id": u.get("location_id"), "org_id": org}, {"_id": 0, "name": 1})
        no_custodian.append({
            "unit_id": u["id"],
            "unit_name": (item or {}).get("name") or u.get("qr_id") or u["id"],
            "project_name": (proj or {}).get("name") or u.get("location_id"),
        })
    return {"pending_old": pending, "no_custodian": no_custodian, "pending_hours": PENDING_ALERT_HOURS}
