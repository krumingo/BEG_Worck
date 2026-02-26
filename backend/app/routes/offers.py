"""
Routes - Offers / BOQ (M2) Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user, can_access_project, can_manage_project, get_user_project_ids
from app.deps.modules import require_m2
from app.utils.audit import log_audit
from ..models.offers import (
    OFFER_STATUSES, OFFER_UNITS,
    OfferCreate, OfferUpdate, OfferLinesUpdate, OfferReject,
    ActivityCatalogCreate, ActivityCatalogUpdate
)

router = APIRouter(tags=["Offers / BOQ"])

# ── Helpers ────────────────────────────────────────────────────────

async def get_next_offer_no(org_id: str) -> str:
    """Generate sequential offer number like OFF-0001"""
    last = await db.offers.find_one(
        {"org_id": org_id},
        {"_id": 0, "offer_no": 1},
        sort=[("created_at", -1)]
    )
    if last and last.get("offer_no"):
        try:
            num = int(last["offer_no"].split("-")[1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"OFF-{num:04d}"


def compute_offer_line(line: dict) -> dict:
    """Compute line totals"""
    qty = line.get("qty", 0)
    material = line.get("material_unit_cost", 0)
    labor = line.get("labor_unit_cost", 0)
    line["line_material_cost"] = round(qty * material, 2)
    line["line_labor_cost"] = round(qty * labor, 2)
    line["line_total"] = round(line["line_material_cost"] + line["line_labor_cost"], 2)
    return line


def compute_offer_totals(offer: dict) -> dict:
    """Compute offer subtotal, vat, total"""
    lines = offer.get("lines", [])
    subtotal = sum(l.get("line_total", 0) for l in lines)
    vat_percent = offer.get("vat_percent", 0)
    vat_amount = round(subtotal * vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    offer["subtotal"] = round(subtotal, 2)
    offer["vat_amount"] = vat_amount
    offer["total"] = total
    return offer


async def can_edit_offer(user: dict, offer: dict) -> bool:
    """Check if user can edit offer (must be Draft and have project access)"""
    if offer["status"] != "Draft":
        return False
    return await can_manage_project(user, offer["project_id"])


# ── Offer CRUD ─────────────────────────────────────────────────────

@router.post("/offers", status_code=201)
async def create_offer(data: OfferCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, data.project_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    
    now = datetime.now(timezone.utc).isoformat()
    offer_no = await get_next_offer_no(user["org_id"])
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "activity_code": line.activity_code,
            "activity_name": line.activity_name,
            "unit": line.unit,
            "qty": line.qty,
            "material_unit_cost": line.material_unit_cost,
            "labor_unit_cost": line.labor_unit_cost,
            "labor_hours_per_unit": line.labor_hours_per_unit,
            "note": line.note,
            "sort_order": line.sort_order or i,
            "activity_type": line.activity_type or "Общо",
            "activity_subtype": line.activity_subtype or "",
        }
        lines.append(compute_offer_line(l))
    
    offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "offer_no": offer_no,
        "title": data.title,
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "lines": lines,
        "notes": data.notes,
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
    }
    offer = compute_offer_totals(offer)
    
    await db.offers.insert_one(offer)
    await log_audit(user["org_id"], user["id"], user["email"], "offer_created", "offer", offer["id"], 
                    {"offer_no": offer_no, "title": data.title, "project_id": data.project_id})
    
    return {k: v for k, v in offer.items() if k != "_id"}


@router.get("/offers")
async def list_offers(
    user: dict = Depends(require_m2),
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    query = {"org_id": user["org_id"]}
    
    if project_id:
        if not await can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied to project")
        query["project_id"] = project_id
    elif user["role"] not in ["Admin", "Owner", "Accountant"]:
        # Limit to assigned projects
        assigned = await get_user_project_ids(user["id"])
        query["project_id"] = {"$in": assigned}
    
    if status:
        query["status"] = status
    
    offers = await db.offers.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    
    if search:
        s = search.lower()
        offers = [o for o in offers if s in o.get("offer_no", "").lower() or s in o.get("title", "").lower()]
    
    # Enrich with project info
    for o in offers:
        p = await db.projects.find_one({"id": o["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        o["project_code"] = p["code"] if p else ""
        o["project_name"] = p["name"] if p else ""
        o["line_count"] = len(o.get("lines", []))
    
    return offers


@router.get("/offers/{offer_id}")
async def get_offer(offer_id: str, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_access_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Enrich
    p = await db.projects.find_one({"id": offer["project_id"]}, {"_id": 0, "code": 1, "name": 1})
    offer["project_code"] = p["code"] if p else ""
    offer["project_name"] = p["name"] if p else ""
    
    return offer


@router.put("/offers/{offer_id}")
async def update_offer(offer_id: str, data: OfferUpdate, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_edit_offer(user, offer):
        raise HTTPException(status_code=403, detail="Can only edit Draft offers you manage")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.offers.update_one({"id": offer_id}, {"$set": update})
    
    # Recompute if vat changed
    if "vat_percent" in update:
        updated = await db.offers.find_one({"id": offer_id})
        updated = compute_offer_totals({k: v for k, v in updated.items() if k != "_id"})
        await db.offers.update_one({"id": offer_id}, {"$set": {
            "subtotal": updated["subtotal"],
            "vat_amount": updated["vat_amount"],
            "total": updated["total"],
        }})
    
    await log_audit(user["org_id"], user["id"], user["email"], "offer_updated", "offer", offer_id, update)
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})


@router.put("/offers/{offer_id}/lines")
async def update_offer_lines(offer_id: str, data: OfferLinesUpdate, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_edit_offer(user, offer):
        raise HTTPException(status_code=403, detail="Can only edit Draft offers you manage")
    
    lines = []
    for i, line in enumerate(data.lines):
        l = {
            "id": str(uuid.uuid4()),
            "activity_code": line.activity_code,
            "activity_name": line.activity_name,
            "unit": line.unit,
            "qty": line.qty,
            "material_unit_cost": line.material_unit_cost,
            "labor_unit_cost": line.labor_unit_cost,
            "labor_hours_per_unit": line.labor_hours_per_unit,
            "note": line.note,
            "sort_order": line.sort_order or i,
            "activity_type": line.activity_type or "Общо",
            "activity_subtype": line.activity_subtype or "",
        }
        lines.append(compute_offer_line(l))
    
    now = datetime.now(timezone.utc).isoformat()
    updated = {
        "lines": lines,
        "updated_at": now,
    }
    
    # Compute totals
    offer["lines"] = lines
    offer["vat_percent"] = offer.get("vat_percent", 0)
    offer = compute_offer_totals(offer)
    updated["subtotal"] = offer["subtotal"]
    updated["vat_amount"] = offer["vat_amount"]
    updated["total"] = offer["total"]
    
    await db.offers.update_one({"id": offer_id}, {"$set": updated})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_lines_updated", "offer", offer_id, 
                    {"line_count": len(lines)})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})


@router.post("/offers/{offer_id}/send")
async def send_offer(offer_id: str, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if offer["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Only Draft offers can be sent")
    if len(offer.get("lines", [])) == 0:
        raise HTTPException(status_code=400, detail="Offer must have at least one line")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.offers.update_one({"id": offer_id}, {"$set": {
        "status": "Sent",
        "sent_at": now,
        "updated_at": now,
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_sent", "offer", offer_id, 
                    {"offer_no": offer["offer_no"]})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})


@router.post("/offers/{offer_id}/accept")
async def accept_offer(offer_id: str, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can accept offers")
    if offer["status"] != "Sent":
        raise HTTPException(status_code=400, detail="Only Sent offers can be accepted")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.offers.update_one({"id": offer_id}, {"$set": {
        "status": "Accepted",
        "accepted_at": now,
        "updated_at": now,
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_accepted", "offer", offer_id,
                    {"offer_no": offer["offer_no"], "total": offer.get("total", 0)})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})


@router.post("/offers/{offer_id}/reject")
async def reject_offer(offer_id: str, data: OfferReject, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can reject offers")
    if offer["status"] != "Sent":
        raise HTTPException(status_code=400, detail="Only Sent offers can be rejected")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.offers.update_one({"id": offer_id}, {"$set": {
        "status": "Rejected",
        "reject_reason": data.reason,
        "updated_at": now,
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_rejected", "offer", offer_id,
                    {"offer_no": offer["offer_no"], "reason": data.reason})
    
    return await db.offers.find_one({"id": offer_id}, {"_id": 0})


@router.post("/offers/{offer_id}/new-version")
async def create_offer_version(offer_id: str, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not await can_manage_project(user, offer["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if offer["status"] not in ["Sent", "Accepted", "Rejected"]:
        raise HTTPException(status_code=400, detail="Can only version non-Draft offers")
    
    now = datetime.now(timezone.utc).isoformat()
    new_version = offer.get("version", 1) + 1
    
    # Clone lines with new IDs
    new_lines = []
    for line in offer.get("lines", []):
        l = {k: v for k, v in line.items() if k != "_id"}
        l["id"] = str(uuid.uuid4())
        new_lines.append(l)
    
    new_offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": offer["project_id"],
        "offer_no": offer["offer_no"],  # Keep same offer_no
        "title": offer["title"],
        "status": "Draft",
        "version": new_version,
        "parent_offer_id": offer["id"],
        "currency": offer["currency"],
        "vat_percent": offer["vat_percent"],
        "lines": new_lines,
        "subtotal": offer["subtotal"],
        "vat_amount": offer["vat_amount"],
        "total": offer["total"],
        "notes": offer.get("notes", ""),
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
    }
    
    await db.offers.insert_one(new_offer)
    await log_audit(user["org_id"], user["id"], user["email"], "offer_versioned", "offer", new_offer["id"],
                    {"offer_no": offer["offer_no"], "version": new_version, "from_version": offer.get("version", 1)})
    
    return {k: v for k, v in new_offer.items() if k != "_id"}


@router.delete("/offers/{offer_id}")
async def delete_offer(offer_id: str, user: dict = Depends(require_m2)):
    offer = await db.offers.find_one({"id": offer_id, "org_id": user["org_id"]})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can delete offers")
    if offer["status"] == "Accepted":
        raise HTTPException(status_code=400, detail="Cannot delete accepted offers")
    
    await db.offers.delete_one({"id": offer_id})
    await log_audit(user["org_id"], user["id"], user["email"], "offer_deleted", "offer", offer_id,
                    {"offer_no": offer["offer_no"]})
    return {"ok": True}


# ── Activity Catalog CRUD ──────────────────────────────────────────

@router.get("/activity-catalog")
async def list_activity_catalog(
    user: dict = Depends(require_m2),
    project_id: Optional[str] = None,
    active_only: bool = True,
):
    query = {"org_id": user["org_id"]}
    if project_id:
        if not await can_access_project(user, project_id):
            raise HTTPException(status_code=403, detail="Access denied")
        query["project_id"] = project_id
    if active_only:
        query["active"] = True
    
    items = await db.activity_catalog.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    return items


@router.post("/activity-catalog", status_code=201)
async def create_activity(data: ActivityCatalogCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await can_manage_project(user, data.project_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "code": data.code,
        "name": data.name,
        "default_unit": data.default_unit,
        "default_material_unit_cost": data.default_material_unit_cost,
        "default_labor_unit_cost": data.default_labor_unit_cost,
        "default_labor_hours_per_unit": data.default_labor_hours_per_unit,
        "active": data.active,
        "created_at": now,
        "updated_at": now,
    }
    await db.activity_catalog.insert_one(item)
    return {k: v for k, v in item.items() if k != "_id"}


@router.put("/activity-catalog/{item_id}")
async def update_activity(item_id: str, data: ActivityCatalogUpdate, user: dict = Depends(require_m2)):
    item = await db.activity_catalog.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Activity not found")
    if not await can_manage_project(user, item["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.activity_catalog.update_one({"id": item_id}, {"$set": update})
    return await db.activity_catalog.find_one({"id": item_id}, {"_id": 0})


@router.delete("/activity-catalog/{item_id}")
async def delete_activity(item_id: str, user: dict = Depends(require_m2)):
    item = await db.activity_catalog.find_one({"id": item_id, "org_id": user["org_id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Activity not found")
    if not await can_manage_project(user, item["project_id"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    await db.activity_catalog.delete_one({"id": item_id})
    return {"ok": True}


@router.get("/offer-enums")
async def get_offer_enums():
    return {
        "statuses": OFFER_STATUSES,
        "units": OFFER_UNITS,
    }
