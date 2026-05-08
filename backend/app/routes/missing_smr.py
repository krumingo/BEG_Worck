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

VALID_STATUSES = ["draft", "reported", "reviewed", "analyzed", "offered", "closed",
                  "executed", "approved_by_client", "rejected_by_client"]
VALID_SOURCES = ["mobile", "web", "daily_report", "change_order"]
STATUS_TRANSITIONS = {
    "draft": ["reported", "closed"],
    "reported": ["reviewed", "executed", "closed"],
    "reviewed": ["analyzed", "approved_by_client", "rejected_by_client", "closed"],
    "executed": ["analyzed", "closed"],
    "approved_by_client": ["analyzed", "closed"],
    "rejected_by_client": ["closed"],
    "analyzed": ["offered", "closed"],
    "offered": ["closed"],
    "closed": [],
}
# Type-specific valid transitions
EMERGENCY_TRANSITIONS = {
    "draft": ["reported", "closed"],
    "reported": ["executed", "closed"],
    "executed": ["analyzed", "closed"],
    "analyzed": ["offered", "closed"],
    "offered": ["closed"],
    "closed": [],
}
PLANNED_TRANSITIONS = {
    "draft": ["reported", "closed"],
    "reported": ["reviewed", "closed"],
    "reviewed": ["approved_by_client", "rejected_by_client", "closed"],
    "approved_by_client": ["analyzed", "closed"],
    "rejected_by_client": ["closed", "reported"],
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
    urgency_type: str = "planned"
    emergency_reason: Optional[str] = None
    executed_date: Optional[str] = None
    executed_by: Optional[str] = None


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
        "urgency_type": data.urgency_type if data.urgency_type in ("emergency", "planned") else "planned",
        "emergency_reason": data.emergency_reason,
        "executed_date": data.executed_date,
        "executed_by": data.executed_by,
        "client_approval": None,
        "ai_estimated_price": None,
        "ai_price_breakdown": None,
        "offer_line_ids": [],
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
    urgency_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(require_m2),
):
    from app.utils.pagination import paginate_query
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    if status:
        query["status"] = status
    if floor:
        query["floor"] = floor
    if room:
        query["room"] = room
    if urgency_type:
        query["urgency_type"] = urgency_type
    if date_from:
        query.setdefault("created_at", {})["$gte"] = date_from
    if date_to:
        query.setdefault("created_at", {})["$lte"] = date_to + "T23:59:59"

    return await paginate_query(db.missing_smr, query, page, page_size, "created_at", -1)


@router.get("/missing-smr/pending-approval")
async def pending_approval(user: dict = Depends(require_m2)):
    items = await db.missing_smr.find(
        {"org_id": user["org_id"], "client_approval.status": "pending"}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
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
    # Use type-specific transitions
    urgency = item.get("urgency_type", "planned")
    trans = EMERGENCY_TRANSITIONS if urgency == "emergency" else PLANNED_TRANSITIONS
    allowed = trans.get(current, STATUS_TRANSITIONS.get(current, []))
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{current}' to '{target}' (type={urgency}). Allowed: {allowed}",
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
    if item["status"] not in ["reported", "reviewed", "executed", "approved_by_client"]:
        raise HTTPException(
            status_code=400,
            detail="Item must be in 'reported', 'reviewed', 'executed' or 'approved_by_client' status to send to analysis",
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
    if item["status"] not in ["reviewed", "analyzed", "executed", "approved_by_client"]:
        raise HTTPException(
            status_code=400,
            detail="Item must be in 'reviewed', 'analyzed', 'executed' or 'approved_by_client' status to create an offer",
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


# ═══════════════════════════════════════════════════════════════════
# TWO FLOWS: EMERGENCY vs PLANNED
# ═══════════════════════════════════════════════════════════════════

from app.services.ai_proposal import get_ai_proposal as hybrid_ai_proposal
from app.services.pricing_engine import batch_get_prices


class ExecuteRequest(BaseModel):
    executed_date: Optional[str] = None
    executed_by: Optional[str] = None
    notes: Optional[str] = None


class RequestApprovalBody(BaseModel):
    client_name: str
    client_notes: Optional[str] = None


class ClientDecisionBody(BaseModel):
    client_notes: Optional[str] = None
    signature_media_id: Optional[str] = None


class BatchToOfferBody(BaseModel):
    ids: List[str]
    offer_name: Optional[str] = None


# ── Execute (emergency only) ───────────────────────────────────────

@router.put("/missing-smr/{item_id}/execute")
async def execute_emergency(item_id: str, data: ExecuteRequest, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.get("urgency_type", "planned") != "emergency":
        raise HTTPException(status_code=400, detail="Only emergency items can be marked as executed")
    if item["status"] != "reported":
        raise HTTPException(status_code=400, detail="Item must be in 'reported' status")

    now = datetime.now(timezone.utc).isoformat()
    await db.missing_smr.update_one({"id": item_id}, {"$set": {
        "status": "executed",
        "executed_date": data.executed_date or now[:10],
        "executed_by": data.executed_by,
        "notes": data.notes or item.get("notes"),
        "updated_at": now,
    }})
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


# ── Request Approval (planned only) ───────────────────────────────

@router.post("/missing-smr/{item_id}/request-approval")
async def request_approval(item_id: str, data: RequestApprovalBody, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.get("urgency_type", "planned") != "planned":
        raise HTTPException(status_code=400, detail="Only planned items need client approval")
    if item["status"] not in ["reported", "reviewed"]:
        raise HTTPException(status_code=400, detail="Item must be in 'reported' or 'reviewed' status")

    now = datetime.now(timezone.utc).isoformat()
    approval = {
        "status": "pending",
        "requested_at": now,
        "decided_at": None,
        "decided_by": None,
        "client_name": data.client_name,
        "client_notes": data.client_notes,
        "signature_media_id": None,
    }
    await db.missing_smr.update_one({"id": item_id}, {"$set": {
        "status": "reviewed",
        "client_approval": approval,
        "updated_at": now,
    }})
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


# ── Client Approve ─────────────────────────────────────────────────

@router.put("/missing-smr/{item_id}/client-approve")
async def client_approve(item_id: str, data: ClientDecisionBody, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item["status"] != "reviewed" or not item.get("client_approval"):
        raise HTTPException(status_code=400, detail="Item must have pending client approval")

    now = datetime.now(timezone.utc).isoformat()
    approval = item["client_approval"]
    approval["status"] = "approved"
    approval["decided_at"] = now
    approval["decided_by"] = user["id"]
    approval["client_notes"] = data.client_notes or approval.get("client_notes")
    approval["signature_media_id"] = data.signature_media_id

    await db.missing_smr.update_one({"id": item_id}, {"$set": {
        "status": "approved_by_client",
        "client_approval": approval,
        "updated_at": now,
    }})
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


# ── Client Reject ──────────────────────────────────────────────────

@router.put("/missing-smr/{item_id}/client-reject")
async def client_reject(item_id: str, data: ClientDecisionBody, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item["status"] != "reviewed" or not item.get("client_approval"):
        raise HTTPException(status_code=400, detail="Item must have pending client approval")

    now = datetime.now(timezone.utc).isoformat()
    approval = item["client_approval"]
    approval["status"] = "rejected"
    approval["decided_at"] = now
    approval["decided_by"] = user["id"]
    approval["client_notes"] = data.client_notes or approval.get("client_notes")

    await db.missing_smr.update_one({"id": item_id}, {"$set": {
        "status": "rejected_by_client",
        "client_approval": approval,
        "updated_at": now,
    }})
    return await db.missing_smr.find_one({"id": item_id}, {"_id": 0})


# ── AI Estimate ────────────────────────────────────────────────────

@router.post("/missing-smr/{item_id}/ai-estimate")
async def ai_estimate(item_id: str, user: dict = Depends(require_m2)):
    item = await db.missing_smr.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    title = item.get("smr_type") or item.get("activity_type") or "СМР"
    unit = item.get("unit", "m2")
    qty = item.get("qty", 1)

    # Get AI proposal
    proposal = await hybrid_ai_proposal(title, unit, qty, None, user["org_id"])

    # Get live prices for materials
    mat_names = [m["name"] for m in proposal.get("materials", []) if m.get("name")]
    price_results = []
    if mat_names:
        price_results = await batch_get_prices(mat_names, user["org_id"])

    # Build breakdown
    materials_with_prices = []
    for m in proposal.get("materials", []):
        entry = {**m}
        for pr in price_results:
            if isinstance(pr, dict) and pr.get("material_name_normalized") == m.get("name", "").lower().strip():
                entry["live_price"] = pr.get("median_price")
                entry["price_confidence"] = pr.get("confidence")
        materials_with_prices.append(entry)

    estimated_price = round(proposal["pricing"]["total_price_per_unit"] * qty, 2)
    breakdown = {
        "material_per_unit": proposal["pricing"]["material_price_per_unit"],
        "labor_per_unit": proposal["pricing"]["labor_price_per_unit"],
        "total_per_unit": proposal["pricing"]["total_price_per_unit"],
        "total_estimated": estimated_price,
        "materials": materials_with_prices,
        "provider": proposal.get("provider", "rule-based"),
        "confidence": proposal.get("confidence", 0),
    }

    now = datetime.now(timezone.utc).isoformat()
    await db.missing_smr.update_one({"id": item_id}, {"$set": {
        "ai_estimated_price": estimated_price,
        "ai_price_breakdown": breakdown,
        "updated_at": now,
    }})

    return {
        "estimated_price": estimated_price,
        "breakdown": breakdown,
        "item": await db.missing_smr.find_one({"id": item_id}, {"_id": 0}),
    }


# ── Batch To Offer ─────────────────────────────────────────────────

@router.post("/missing-smr/batch-to-offer")
async def batch_to_offer(data: BatchToOfferBody, user: dict = Depends(require_m2)):
    if not data.ids:
        raise HTTPException(status_code=400, detail="No items provided")

    org_id = user["org_id"]
    items = await db.missing_smr.find(
        {"id": {"$in": data.ids}, "org_id": org_id}, {"_id": 0}
    ).to_list(100)
    if not items:
        raise HTTPException(status_code=404, detail="No valid items found")

    # Verify all are from same project
    project_ids = set(i["project_id"] for i in items)
    if len(project_ids) > 1:
        raise HTTPException(status_code=400, detail="All items must belong to the same project")

    project_id = items[0]["project_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "code": 1, "name": 1})

    # Generate offer number
    last = await db.offers.find_one({"org_id": org_id}, {"_id": 0, "offer_no": 1}, sort=[("created_at", -1)])
    num = 1
    if last and last.get("offer_no"):
        try:
            num = int(last["offer_no"].split("-")[1]) + 1
        except Exception:
            pass
    offer_no = f"OFF-{num:04d}"

    now = datetime.now(timezone.utc).isoformat()
    lines = []
    for i, item in enumerate(items):
        price = item.get("ai_estimated_price") or 0
        qty = item.get("qty", 1)
        per_unit = round(price / qty, 2) if qty > 0 else 0
        lines.append({
            "id": str(uuid.uuid4()),
            "activity_code": None,
            "activity_name": item.get("smr_type") or item.get("activity_type") or "Доп. СМР",
            "unit": item.get("unit", "m2"),
            "qty": qty,
            "material_unit_cost": 0,
            "labor_unit_cost": per_unit,
            "labor_hours_per_unit": None,
            "line_material_cost": 0,
            "line_labor_cost": price,
            "line_total": price,
            "note": item.get("notes") or "",
            "sort_order": i,
            "activity_type": item.get("activity_type") or "Общо",
            "activity_subtype": item.get("activity_subtype") or "",
        })

    subtotal = sum(l["line_total"] for l in lines)
    vat = round(subtotal * 0.2, 2)
    title = data.offer_name or f"Допълнителни СМР ({len(items)} бр.) — {project.get('code', '')}"

    offer = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": project_id,
        "offer_no": offer_no,
        "title": title,
        "offer_type": "missing_smr_batch",
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": "EUR",
        "vat_percent": 20.0,
        "lines": lines,
        "notes": f"Генерирана от {len(items)} допълнителни СМР записа",
        "subtotal": round(subtotal, 2),
        "vat_amount": vat,
        "total": round(subtotal + vat, 2),
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
    }
    await db.offers.insert_one(offer)

    # Update items
    line_ids = [l["id"] for l in lines]
    for item in items:
        await db.missing_smr.update_one({"id": item["id"]}, {"$set": {
            "status": "offered",
            "linked_offer_id": offer["id"],
            "offer_line_ids": line_ids,
            "updated_at": now,
        }})

    return {"ok": True, "offer_id": offer["id"], "offer_no": offer_no, "items_count": len(items)}


# (pending-approval endpoint moved before {item_id} to avoid route conflict)
