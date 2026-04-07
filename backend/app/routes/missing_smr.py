"""
Routes - Missing / Additional SMR (Липсващи / Допълнителни СМР).
Unified operational flow for tracking missing or additional construction works.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Missing SMR"])

VALID_STATUSES = ["draft", "reported", "reviewed", "analyzed", "offered", "closed"]
VALID_SOURCES = ["mobile", "web", "daily_report", "change_order"]
STATUS_TRANSITIONS = {
    "draft": ["reported", "closed"],
    "reported": ["reviewed", "closed"],
    "reviewed": ["analyzed", "closed"],
    "analyzed": ["offered", "closed"],
    "offered": ["closed"],
    "closed": [],
}


# ── Pydantic Models ────────────────────────────────────────────────

class MissingSMRCreate(BaseModel):
    project_id: str
    floor: Optional[str] = None
    room: Optional[str] = None
    zone: Optional[str] = None
    notes: Optional[str] = None
    smr_type: Optional[str] = None
    activity_type: Optional[str] = None
    activity_subtype: Optional[str] = None
    qty: float = 1
    unit: str = "m2"
    labor_hours_est: Optional[float] = None
    material_notes: Optional[str] = None
    source: str = "web"


class MissingSMRUpdate(BaseModel):
    floor: Optional[str] = None
    room: Optional[str] = None
    zone: Optional[str] = None
    notes: Optional[str] = None
    smr_type: Optional[str] = None
    activity_type: Optional[str] = None
    activity_subtype: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    labor_hours_est: Optional[float] = None
    material_notes: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str


class AttachmentAdd(BaseModel):
    media_id: str
    url: str
    filename: Optional[str] = None


# ── CRUD ───────────────────────────────────────────────────────────

@router.post("/missing-smr", status_code=201)
async def create_missing_smr(data: MissingSMRCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if data.source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source. Valid: {VALID_SOURCES}")

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "project_name": project.get("name", ""),
        "floor": data.floor,
        "room": data.room,
        "zone": data.zone,
        "notes": data.notes,
        "smr_type": data.smr_type,
        "activity_type": data.activity_type,
        "activity_subtype": data.activity_subtype,
        "qty": data.qty,
        "unit": data.unit,
        "labor_hours_est": data.labor_hours_est,
        "material_notes": data.material_notes,
        "attachments": [],
        "source": data.source,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "created_by_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        "linked_extra_work_id": None,
        "linked_offer_id": None,
        "linked_change_order_id": None,
    }
    await db.missing_smr.insert_one(item)
    return {k: v for k, v in item.items() if k != "_id"}


@router.get("/missing-smr")
async def list_missing_smr(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    floor: Optional[str] = None,
    room: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    if status:
        query["status"] = status
    if floor:
        query["floor"] = floor
    if room:
        query["room"] = room
    if date_from:
        query.setdefault("created_at", {})["$gte"] = date_from
    if date_to:
        query.setdefault("created_at", {})["$lte"] = date_to + "T23:59:59"

    items = await db.missing_smr.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@router.get("/missing-smr/{item_id}")
async def get_missing_smr(item_id: str, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one(
        {"id": item_id, "org_id": user["org_id"]}, {"_id": 0}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")
    return item


@router.put("/missing-smr/{item_id}")
async def update_missing_smr(
    item_id: str, data: MissingSMRUpdate, user: dict = Depends(require_m2)
):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")
    if item["status"] not in ["draft", "reported"]:
        raise HTTPException(status_code=400, detail="Can only edit draft or reported items")

    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.missing_smr.update_one({"id": item_id}, {"$set": update})
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


@router.delete("/missing-smr/{item_id}")
async def delete_missing_smr(item_id: str, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")
    if item["status"] not in ["draft"]:
        raise HTTPException(status_code=400, detail="Can only delete draft items")
    await db.missing_smr.delete_one({"id": item_id})
    return {"ok": True}


# ── Status Transitions ─────────────────────────────────────────────

@router.put("/missing-smr/{item_id}/status")
async def update_status(
    item_id: str, data: StatusUpdate, user: dict = Depends(require_m2)
):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")

    current = item["status"]
    target = data.status
    if target not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {VALID_STATUSES}")
    if target not in STATUS_TRANSITIONS.get(current, []):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{current}' to '{target}'. Allowed: {STATUS_TRANSITIONS[current]}",
        )

    now = datetime.now(timezone.utc).isoformat()
    await db.missing_smr.update_one(
        {"id": item_id},
        {"$set": {"status": target, "updated_at": now}},
    )
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


# ── Attachment Management ──────────────────────────────────────────

@router.post("/missing-smr/{item_id}/attachments")
async def add_attachment(
    item_id: str, data: AttachmentAdd, user: dict = Depends(require_m2)
):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")

    attachment = {
        "media_id": data.media_id,
        "url": data.url,
        "filename": data.filename,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "added_by": user["id"],
    }
    await db.missing_smr.update_one(
        {"id": item_id},
        {
            "$push": {"attachments": attachment},
            "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


@router.delete("/missing-smr/{item_id}/attachments/{media_id}")
async def remove_attachment(
    item_id: str, media_id: str, user: dict = Depends(require_m2)
):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")

    await db.missing_smr.update_one(
        {"id": item_id},
        {
            "$pull": {"attachments": {"media_id": media_id}},
            "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


# ── Bridge: To Analysis (creates extra_work_draft) ────────────────

@router.post("/missing-smr/{item_id}/to-analysis")
async def bridge_to_analysis(item_id: str, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")
    if item["status"] not in ["reported", "reviewed"]:
        raise HTTPException(
            status_code=400,
            detail="Item must be in 'reported' or 'reviewed' status to send to analysis",
        )

    now = datetime.now(timezone.utc).isoformat()
    location_parts = []
    if item.get("floor"):
        location_parts.append(f"Ет.{item['floor']}")
    if item.get("room"):
        location_parts.append(item["room"])
    if item.get("zone"):
        location_parts.append(item["zone"])

    draft = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": item["project_id"],
        "source_type": "missing_smr",
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "work_date": now[:10],
        "status": "draft",
        "title": item.get("smr_type") or item.get("activity_type") or "Липсващо СМР",
        "normalized_activity_type": item.get("activity_type"),
        "normalized_activity_subtype": item.get("activity_subtype"),
        "unit": item.get("unit", "m2"),
        "qty": item.get("qty", 1),
        "ai_provider_used": None,
        "ai_material_price_per_unit": None,
        "ai_labor_price_per_unit": None,
        "ai_total_price_per_unit": None,
        "ai_small_qty_adjustment": None,
        "ai_confidence": None,
        "ai_raw_response_summary": None,
        "ai_price_before_manual_edit": None,
        "final_user_accepted_price": None,
        "location_floor": item.get("floor"),
        "location_room": item.get("room"),
        "location_zone": item.get("zone"),
        "location_notes": ", ".join(location_parts) if location_parts else None,
        "notes": item.get("notes"),
        "photos": [a.get("media_id") for a in item.get("attachments", []) if a.get("media_id")],
        "suggested_related_smr": [],
        "suggested_materials": [],
        "target_offer_id": None,
        "group_batch_id": None,
        "source_missing_smr_id": item_id,
    }
    await db.extra_work_drafts.insert_one(draft)

    await db.missing_smr.update_one(
        {"id": item_id},
        {"$set": {
            "status": "analyzed",
            "linked_extra_work_id": draft["id"],
            "updated_at": now,
        }},
    )

    updated = await db.missing_smr.find_one({"id": item_id}, {"_id": 0})
    return {
        "ok": True,
        "missing_smr": updated,
        "extra_work_draft_id": draft["id"],
    }


# ── Bridge: To Offer ──────────────────────────────────────────────

@router.post("/missing-smr/{item_id}/to-offer")
async def bridge_to_offer(item_id: str, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Missing SMR item not found")
    if item["status"] not in ["reviewed", "analyzed"]:
        raise HTTPException(
            status_code=400,
            detail="Item must be in 'reviewed' or 'analyzed' status to create an offer",
        )

    now = datetime.now(timezone.utc).isoformat()
    project = await db.projects.find_one(
        {"id": item["project_id"], "org_id": user["org_id"]},
        {"_id": 0, "code": 1, "name": 1},
    )

    last = await db.offers.find_one(
        {"org_id": user["org_id"]}, {"_id": 0, "offer_no": 1}, sort=[("created_at", -1)]
    )
    if last and last.get("offer_no"):
        try:
            num = int(last["offer_no"].split("-")[1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    offer_no = f"OFF-{num:04d}"

    location_parts = []
    if item.get("floor"):
        location_parts.append(f"Ет.{item['floor']}")
    if item.get("room"):
        location_parts.append(item["room"])
    if item.get("zone"):
        location_parts.append(item["zone"])
    location_str = ", ".join(location_parts)

    note_parts = []
    if location_str:
        note_parts.append(f"Локация: {location_str}")
    if item.get("notes"):
        note_parts.append(item["notes"])
    if item.get("material_notes"):
        note_parts.append(f"Материали: {item['material_notes']}")

    line = {
        "id": str(uuid.uuid4()),
        "activity_code": None,
        "activity_name": item.get("smr_type") or item.get("activity_type") or "Липсващо СМР",
        "unit": item.get("unit", "m2"),
        "qty": item.get("qty", 1),
        "material_unit_cost": 0,
        "labor_unit_cost": 0,
        "labor_hours_per_unit": item.get("labor_hours_est"),
        "line_material_cost": 0,
        "line_labor_cost": 0,
        "line_total": 0,
        "note": "; ".join(note_parts) if note_parts else None,
        "sort_order": 0,
        "activity_type": item.get("activity_type") or "Общо",
        "activity_subtype": item.get("activity_subtype") or "",
    }

    title = f"Допълнително СМР - {project.get('code', '')} ({datetime.now().strftime('%d.%m.%Y')})"

    offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": item["project_id"],
        "offer_no": offer_no,
        "title": title,
        "offer_type": "missing_smr",
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": "EUR",
        "vat_percent": 20.0,
        "lines": [line],
        "notes": f"Създадена от Липсващо СМР #{item_id[:8]}",
        "subtotal": 0,
        "vat_amount": 0,
        "total": 0,
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
        "source_missing_smr_id": item_id,
    }
    await db.offers.insert_one(offer)

    await db.missing_smr.update_one(
        {"id": item_id},
        {"$set": {
            "status": "offered",
            "linked_offer_id": offer["id"],
            "updated_at": now,
        }},
    )

    updated = await db.missing_smr.find_one({"id": item_id}, {"_id": 0})
    return {
        "ok": True,
        "missing_smr": updated,
        "offer_id": offer["id"],
        "offer_no": offer_no,
    }
