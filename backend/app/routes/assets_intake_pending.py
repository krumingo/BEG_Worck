"""
Routes - Asset Intake Pending (заскладяване с одобрение).

Поток: всеки (с право) подава заскладяване → запис в asset_intake_pending (status=pending).
Админ преглежда → одобри (поединично или накуп) → ЧАК ТОГАВА се създава реален
артикул + бройка + QR на избраното място. Или отхвърля.
Едно правило за всички: и админ минава през pending.
Нищо съществуващо не се променя — само нова колекция + reuse на създаването.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user, require_admin
from app.routes.asset_item_types import all_type_keys, BUILTIN_TYPES
from app.routes.assets_qr import _make_qr

router = APIRouter(tags=["AssetIntakePending"])

REVIEW_ROLES = ["Admin", "Owner"]


class IntakeSubmit(BaseModel):
    location_type: str          # warehouse | project | employee | guest
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    suggestion: dict            # name, type_label, type_key, brand, model, serial_no, ...
    matched_item_id: Optional[str] = None
    photo_b64: Optional[str] = None     # умалена снимка за преглед


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _can_submit(user: dict) -> bool:
    """Админ/Owner винаги. Техник/SiteManager — само ако е включено във фирмените настройки."""
    if user["role"] in ["Admin", "Owner"]:
        return True
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0, "asset_intake_roles": 1}) or {}
    intake = org.get("asset_intake_roles", {})
    if user["role"] == "SiteManager":
        return bool(intake.get("site_manager"))
    if user["role"] in ["Technician", "Worker", "Warehousekeeper"]:
        return bool(intake.get("technician"))
    return False


@router.get("/assets/intake/can-submit")
async def can_submit(user: dict = Depends(get_current_user)):
    return {"allowed": await _can_submit(user)}


@router.post("/assets/intake/submit", status_code=201)
async def submit_intake(data: IntakeSubmit, user: dict = Depends(get_current_user)):
    if not await _can_submit(user):
        raise HTTPException(status_code=403, detail="Нямате право да заскладявате")
    rec = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "status": "pending",
        "location_type": data.location_type,
        "location_id": data.location_id,
        "location_name": data.location_name,
        "suggestion": data.suggestion or {},
        "matched_item_id": data.matched_item_id,
        "photo_b64": data.photo_b64,
        "submitted_by": user["id"],
        "submitted_by_name": user.get("name") or user.get("email") or user["id"],
        "submitted_at": _now(),
        "reviewed_by": None,
        "reviewed_at": None,
    }
    await db.asset_intake_pending.insert_one(rec)
    return {"id": rec["id"], "status": "pending"}


@router.get("/assets/intake/pending")
async def list_pending(user: dict = Depends(require_admin)):
    recs = await db.asset_intake_pending.find(
        {"org_id": user["org_id"], "status": "pending"}, {"_id": 0}
    ).sort("submitted_at", 1).to_list(500)
    return {"items": recs, "count": len(recs)}


async def _materialize(org: str, rec: dict, reviewer: dict):
    """Създава реалния артикул + бройка + QR от одобрен pending запис."""
    s = rec.get("suggestion", {})
    # тип
    type_key = s.get("type_key")
    if not type_key and s.get("type_label"):
        label = s["type_label"].strip()
        keys = await all_type_keys(org)
        # съпоставяне по label
        label_map = {b["label_bg"].lower(): b["key"] for b in BUILTIN_TYPES}
        async for t in db.asset_item_types.find({"org_id": org}, {"_id": 0, "key": 1, "label_bg": 1}):
            label_map[(t["label_bg"] or "").lower()] = t["key"]
        type_key = label_map.get(label.lower())
        if not type_key:
            import re
            type_key = re.sub(r"[^a-z0-9а-я]+", "_", label.lower()).strip("_") or "tool"
            await db.asset_item_types.insert_one({
                "id": str(uuid.uuid4()), "org_id": org, "key": type_key,
                "label_bg": label, "created_by": reviewer["id"],
            })
    if not type_key:
        type_key = "tool"

    # артикул — съществуващ или нов
    item_id = rec.get("matched_item_id")
    if not item_id:
        item_id = str(uuid.uuid4())
        await db.asset_items.insert_one({
            "id": item_id, "org_id": org, "name": (s.get("name") or "").strip() or "Без име",
            "type": type_key, "group": s.get("group"), "brand": s.get("brand"), "model": s.get("model"),
            "article_no": s.get("article_no"), "unit": "бр",
            "purchase_price": s.get("estimated_price_eur"), "purchase_currency": "EUR",
            "purchase_date": datetime.now(timezone.utc).date().isoformat(),
            "warranty_months": s.get("warranty_months"), "activities": s.get("activities") or [],
            "is_active": True, "created_at": _now(), "created_by": reviewer["id"],
        })

    # бройка + QR
    unit_id = str(uuid.uuid4())
    item = await db.asset_items.find_one({"id": item_id, "org_id": org}, {"_id": 0})
    code = (s.get("serial_no") or "").strip()
    qr = await _make_qr(org, reviewer["id"], "asset_unit", unit_id, (item or {}).get("name", ""), code)
    loc_type = rec.get("location_type")
    loc_id = rec.get("location_id")
    # guest локация се пази като тип guest с името
    await db.asset_units.insert_one({
        "id": unit_id, "org_id": org, "item_id": item_id, "qr_id": qr["qr_id"],
        "serial_no": code or None, "inventory_no": None, "status": "available",
        "location_type": loc_type if loc_id or loc_type == "guest" else None,
        "location_id": loc_id, "location_name_cached": rec.get("location_name"),
        "notes": None, "is_active": True, "created_at": _now(), "created_by": reviewer["id"],
        "from_intake": rec["id"],
    })
    return {"item_id": item_id, "unit_id": unit_id, "qr_id": qr["qr_id"]}


@router.post("/assets/intake/{intake_id}/approve")
async def approve_intake(intake_id: str, user: dict = Depends(require_admin)):
    org = user["org_id"]
    rec = await db.asset_intake_pending.find_one({"id": intake_id, "org_id": org}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    if rec["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already reviewed")
    created = await _materialize(org, rec, user)
    await db.asset_intake_pending.update_one(
        {"id": intake_id, "org_id": org},
        {"$set": {"status": "approved", "reviewed_by": user["id"], "reviewed_at": _now(), "created_refs": created}},
    )
    return {"ok": True, **created}


class BulkApprove(BaseModel):
    ids: List[str]


@router.post("/assets/intake/approve-bulk")
async def approve_bulk(data: BulkApprove, user: dict = Depends(require_admin)):
    org = user["org_id"]
    done, failed = [], []
    for iid in data.ids:
        rec = await db.asset_intake_pending.find_one({"id": iid, "org_id": org, "status": "pending"}, {"_id": 0})
        if not rec:
            failed.append(iid); continue
        try:
            created = await _materialize(org, rec, user)
            await db.asset_intake_pending.update_one(
                {"id": iid, "org_id": org},
                {"$set": {"status": "approved", "reviewed_by": user["id"], "reviewed_at": _now(), "created_refs": created}},
            )
            done.append(iid)
        except Exception:
            failed.append(iid)
    return {"approved": done, "failed": failed}


@router.get("/assets/intake/locations")
async def intake_locations(type: str, user: dict = Depends(get_current_user)):
    """Леки списъци за избор на локация при заскладяване. Достъпно за всеки с право да заскладява.
    type: warehouse | project | employee"""
    if not await _can_submit(user):
        raise HTTPException(status_code=403, detail="Нямате право да заскладявате")
    org = user["org_id"]
    if type == "warehouse":
        rows = await db.warehouses.find({"org_id": org}, {"_id": 0, "id": 1, "name": 1}).to_list(300)
        return {"items": [{"id": w["id"], "name": w.get("name") or w["id"]} for w in rows]}
    if type == "project":
        rows = await db.projects.find(
            {"org_id": org, "status": {"$in": ["Active", "Draft"]}},
            {"_id": 0, "id": 1, "name": 1, "code": 1},
        ).to_list(500)
        return {"items": [{"id": p["id"], "name": p.get("name") or p.get("code") or p["id"]} for p in rows]}
    if type == "employee":
        rows = await db.users.find(
            {"org_id": org}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "name": 1, "email": 1, "role": 1, "avatar_url": 1}
        ).to_list(500)
        items = []
        for u in rows:
            nm = u.get("name") or f"{u.get('first_name','')} {u.get('last_name','')}".strip() or u.get("email") or u["id"]
            items.append({"id": u["id"], "name": nm, "role": u.get("role"), "avatar_url": u.get("avatar_url")})
        return {"items": items}
    raise HTTPException(status_code=400, detail="Invalid type")


@router.post("/assets/intake/{intake_id}/reject")
async def reject_intake(intake_id: str, user: dict = Depends(require_admin)):
    org = user["org_id"]
    rec = await db.asset_intake_pending.find_one({"id": intake_id, "org_id": org, "status": "pending"}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    await db.asset_intake_pending.update_one(
        {"id": intake_id, "org_id": org},
        {"$set": {"status": "rejected", "reviewed_by": user["id"], "reviewed_at": _now()}},
    )
    return {"ok": True}
