"""
Routes - Extra Works Draft + AI Proposal (M2 extension).
Uses hybrid AI service (LLM + rule-based fallback).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.utils.audit import log_audit
from app.services.ai_proposal import get_ai_proposal as hybrid_ai_proposal

router = APIRouter(tags=["Extra Works / AI Offers"])


# ── Pydantic Models ────────────────────────────────────────────────

class ExtraWorkCreate(BaseModel):
    project_id: str
    work_date: Optional[str] = None
    title: str
    unit: str = "m2"
    qty: float = 1
    location_floor: Optional[str] = None
    location_room: Optional[str] = None
    location_zone: Optional[str] = None
    location_notes: Optional[str] = None
    notes: Optional[str] = None


class ExtraWorkUpdate(BaseModel):
    title: Optional[str] = None
    unit: Optional[str] = None
    qty: Optional[float] = None
    location_floor: Optional[str] = None
    location_room: Optional[str] = None
    location_zone: Optional[str] = None
    location_notes: Optional[str] = None
    notes: Optional[str] = None
    ai_material_price_per_unit: Optional[float] = None
    ai_labor_price_per_unit: Optional[float] = None
    ai_total_price_per_unit: Optional[float] = None
    ai_small_qty_adjustment: Optional[float] = None
    ai_confidence: Optional[float] = None
    normalized_activity_type: Optional[str] = None
    normalized_activity_subtype: Optional[str] = None
    suggested_materials: Optional[list] = None
    suggested_related_smr: Optional[list] = None
    status: Optional[str] = None


class CreateOfferFromDrafts(BaseModel):
    draft_ids: List[str]
    title: Optional[str] = None
    currency: str = "EUR"
    vat_percent: float = 20.0


class AIProposalRequest(BaseModel):
    title: str
    unit: str = "m2"
    qty: float = 1
    city: Optional[str] = None


class BatchLineInput(BaseModel):
    title: str
    unit: str = "m2"
    qty: float = 1
    location_floor: Optional[str] = None
    location_room: Optional[str] = None
    location_zone: Optional[str] = None

class BatchAIRequest(BaseModel):
    lines: List[BatchLineInput]
    city: Optional[str] = None
    project_id: Optional[str] = None


# ── Hourly Rate Configuration ──────────────────────────────────────

# DEMO defaults — used ONLY when org has no configured rates
DEMO_WORKER_RATES = {
    "общ работник": {"hourly_rate": 15, "min_hours": 2, "min_job_price": 40},
    "майстор": {"hourly_rate": 22, "min_hours": 2, "min_job_price": 60},
    "бояджия": {"hourly_rate": 18, "min_hours": 2, "min_job_price": 50},
    "шпакловчик": {"hourly_rate": 20, "min_hours": 2, "min_job_price": 55},
    "електротехник": {"hourly_rate": 28, "min_hours": 1, "min_job_price": 50},
    "вик": {"hourly_rate": 26, "min_hours": 1, "min_job_price": 50},
    "монтажник": {"hourly_rate": 20, "min_hours": 2, "min_job_price": 50},
    "плочкаджия": {"hourly_rate": 25, "min_hours": 3, "min_job_price": 80},
}

ACTIVITY_TO_WORKER = {
    "Мокри процеси": "майстор", "Довършителни": "майстор",
    "Боядисване": "бояджия", "Шпакловка": "шпакловчик",
    "Облицовка": "плочкаджия", "Инсталации": "електротехник",
    "Електро": "електротехник", "ВиК": "вик",
    "Сухо строителство": "монтажник",
}

async def get_org_worker_rates(org_id: str) -> dict:
    """Load org-configured worker rates from DB, fallback to DEMO"""
    settings = await db.settings.find_one({"_id": "worker_rates", "org_id": org_id})
    if settings and settings.get("rates"):
        return settings["rates"]
    return None  # None means use DEMO

def get_worker_rate_sync(activity_type: str, activity_subtype: str, org_rates: dict = None) -> dict:
    """Get worker hourly rate — uses org rates if available, DEMO otherwise"""
    worker = ACTIVITY_TO_WORKER.get(activity_subtype) or ACTIVITY_TO_WORKER.get(activity_type) or "майстор"
    source_rates = org_rates if org_rates else DEMO_WORKER_RATES
    rate = source_rates.get(worker, source_rates.get("майстор", DEMO_WORKER_RATES["майстор"]))
    is_demo = org_rates is None
    return {"worker_type": worker, "is_demo": is_demo, **rate}


def apply_hourly_pricing(proposal: dict, qty: float, org_rates: dict = None) -> dict:
    """Apply hourly rate logic to proposal for small quantities"""
    rec = proposal.get("recognized", {})
    worker = get_worker_rate_sync(rec.get("activity_type", ""), rec.get("activity_subtype", ""), org_rates)
    
    labor_price = proposal["pricing"]["labor_price_per_unit"]
    estimated_labor_total = labor_price * qty
    min_job = worker["min_job_price"]
    
    hourly_info = {
        "worker_type": worker["worker_type"],
        "hourly_rate": worker["hourly_rate"],
        "min_hours": worker["min_hours"],
        "min_job_price": min_job,
        "estimated_labor_total": round(estimated_labor_total, 2),
        "is_demo": worker.get("is_demo", False),
        "currency": "EUR",
    }
    
    # If estimated labor is below minimum, apply minimum
    if estimated_labor_total < min_job and qty <= 10:
        adjusted_labor_per_unit = round(min_job / qty, 2) if qty > 0 else labor_price
        proposal["pricing"]["labor_price_per_unit"] = adjusted_labor_per_unit
        proposal["pricing"]["total_price_per_unit"] = round(
            proposal["pricing"]["material_price_per_unit"] + adjusted_labor_per_unit, 2)
        proposal["pricing"]["total_estimated"] = round(
            proposal["pricing"]["total_price_per_unit"] * qty, 2)
        hourly_info["min_applied"] = True
        hourly_info["adjusted_labor_per_unit"] = adjusted_labor_per_unit
    else:
        hourly_info["min_applied"] = False
    
    proposal["hourly_info"] = hourly_info
    return proposal


# ── Extra Work Draft CRUD ──────────────────────────────────────────

@router.post("/extra-works", status_code=201)
async def create_extra_work(data: ExtraWorkCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    now = datetime.now(timezone.utc).isoformat()
    draft = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "source_type": "extra_work",
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "work_date": data.work_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "status": "draft",
        "title": data.title,
        "normalized_activity_type": None,
        "normalized_activity_subtype": None,
        "unit": data.unit,
        "qty": data.qty,
        "ai_provider_used": None,
        "ai_material_price_per_unit": None,
        "ai_labor_price_per_unit": None,
        "ai_total_price_per_unit": None,
        "ai_small_qty_adjustment": None,
        "ai_confidence": None,
        "ai_raw_response_summary": None,
        "ai_price_before_manual_edit": None,
        "final_user_accepted_price": None,
        "location_floor": data.location_floor,
        "location_room": data.location_room,
        "location_zone": data.location_zone,
        "location_notes": data.location_notes,
        "notes": data.notes,
        "photos": [],
        "suggested_related_smr": [],
        "suggested_materials": [],
        "target_offer_id": None,
        "group_batch_id": None,
    }
    await db.extra_work_drafts.insert_one(draft)
    return {k: v for k, v in draft.items() if k != "_id"}


@router.get("/extra-works")
async def list_extra_works(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    if status:
        query["status"] = status
    
    drafts = await db.extra_work_drafts.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return drafts


@router.get("/extra-works/{draft_id}")
async def get_extra_work(draft_id: str, user: dict = Depends(require_m2)):
    draft = await db.extra_work_drafts.find_one({"id": draft_id, "org_id": user["org_id"]}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.put("/extra-works/{draft_id}")
async def update_extra_work(draft_id: str, data: ExtraWorkUpdate, user: dict = Depends(require_m2)):
    draft = await db.extra_work_drafts.find_one({"id": draft_id, "org_id": user["org_id"]})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft["status"] not in ["draft"]:
        raise HTTPException(status_code=400, detail="Can only edit draft items")
    
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.extra_work_drafts.update_one({"id": draft_id}, {"$set": update})
    return await db.extra_work_drafts.find_one({"id": draft_id}, {"_id": 0})


@router.delete("/extra-works/{draft_id}")
async def delete_extra_work(draft_id: str, user: dict = Depends(require_m2)):
    draft = await db.extra_work_drafts.find_one({"id": draft_id, "org_id": user["org_id"]})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft["status"] not in ["draft"]:
        raise HTTPException(status_code=400, detail="Can only delete draft items")
    await db.extra_work_drafts.delete_one({"id": draft_id})
    return {"ok": True}


# ── AI Proposal Endpoint (Hybrid) ──────────────────────────────────

@router.post("/extra-works/ai-proposal")
async def get_ai_proposal_endpoint(data: AIProposalRequest, user: dict = Depends(require_m2)):
    """Generate AI proposal using hybrid provider (LLM → rule-based fallback)"""
    org_rates = await get_org_worker_rates(user["org_id"])
    proposal = await hybrid_ai_proposal(data.title, data.unit, data.qty, data.city, user["org_id"])
    proposal = apply_hourly_pricing(proposal, data.qty, org_rates)
    return proposal


@router.post("/extra-works/ai-batch")
async def batch_ai_proposal(data: BatchAIRequest, user: dict = Depends(require_m2)):
    """Batch AI proposal for multiple lines at once"""
    org_rates = await get_org_worker_rates(user["org_id"])
    results = []
    combined_materials = {}
    
    for line in data.lines:
        proposal = await hybrid_ai_proposal(line.title, line.unit, line.qty, data.city, user["org_id"])
        proposal = apply_hourly_pricing(proposal, line.qty, org_rates)
        proposal["_input"] = {"title": line.title, "unit": line.unit, "qty": line.qty,
                              "location_floor": line.location_floor, "location_room": line.location_room,
                              "location_zone": line.location_zone}
        results.append(proposal)
        
        # Aggregate materials
        for mat in proposal.get("materials", []):
            key = mat["name"]
            if key not in combined_materials:
                combined_materials[key] = {**mat, "sources": [line.title]}
            else:
                if mat.get("estimated_qty"):
                    combined_materials[key]["estimated_qty"] = round(
                        (combined_materials[key].get("estimated_qty") or 0) + mat["estimated_qty"], 2)
                combined_materials[key]["sources"].append(line.title)
    
    # Deduplicate combined materials
    combined_list = sorted(combined_materials.values(), key=lambda x: (
        0 if x["category"] == "primary" else 1 if x["category"] == "secondary" else 2, x["name"]))
    
    grand_total = sum(r["pricing"]["total_estimated"] for r in results)
    
    return {
        "results": results,
        "combined_materials": combined_list,
        "grand_total": round(grand_total, 2),
        "line_count": len(results),
    }


# ── Two-Stage AI Endpoints ─────────────────────────────────────────

from app.services.ai_proposal import rule_based_proposal

@router.post("/extra-works/ai-fast")
async def fast_ai_proposal(data: BatchAIRequest, user: dict = Depends(require_m2)):
    """Stage A: Fast rule-based proposals for all lines (instant, no LLM)"""
    org_rates = await get_org_worker_rates(user["org_id"])
    results = []
    combined_materials = {}
    
    for line in data.lines:
        proposal = rule_based_proposal(line.title, line.unit, line.qty, data.city)
        proposal = apply_hourly_pricing(proposal, line.qty, org_rates)
        proposal["_input"] = {"title": line.title, "unit": line.unit, "qty": line.qty,
                              "location_floor": line.location_floor, "location_room": line.location_room,
                              "location_zone": line.location_zone}
        proposal["stage"] = "fast"
        results.append(proposal)
        
        for mat in proposal.get("materials", []):
            key = mat["name"]
            if key not in combined_materials:
                combined_materials[key] = {**mat, "sources": [line.title]}
            else:
                if mat.get("estimated_qty"):
                    combined_materials[key]["estimated_qty"] = round(
                        (combined_materials[key].get("estimated_qty") or 0) + mat["estimated_qty"], 2)
                combined_materials[key]["sources"].append(line.title)
    
    combined_list = sorted(combined_materials.values(), key=lambda x: (
        0 if x["category"] == "primary" else 1 if x["category"] == "secondary" else 2, x["name"]))
    
    return {
        "results": results,
        "combined_materials": combined_list,
        "grand_total": round(sum(r["pricing"]["total_estimated"] for r in results), 2),
        "line_count": len(results),
        "stage": "fast",
    }


@router.post("/extra-works/ai-refine")
async def refine_ai_proposal(data: BatchAIRequest, user: dict = Depends(require_m2)):
    """Stage B: LLM refinement for all lines (slower, richer results)"""
    org_rates = await get_org_worker_rates(user["org_id"])
    results = []
    combined_materials = {}
    
    for line in data.lines:
        proposal = await hybrid_ai_proposal(line.title, line.unit, line.qty, data.city, user["org_id"])
        proposal = apply_hourly_pricing(proposal, line.qty, org_rates)
        proposal["_input"] = {"title": line.title, "unit": line.unit, "qty": line.qty,
                              "location_floor": line.location_floor, "location_room": line.location_room,
                              "location_zone": line.location_zone}
        proposal["stage"] = "refined"
        results.append(proposal)
        
        for mat in proposal.get("materials", []):
            key = mat["name"]
            if key not in combined_materials:
                combined_materials[key] = {**mat, "sources": [line.title]}
            else:
                if mat.get("estimated_qty"):
                    combined_materials[key]["estimated_qty"] = round(
                        (combined_materials[key].get("estimated_qty") or 0) + mat["estimated_qty"], 2)
                combined_materials[key]["sources"].append(line.title)
    
    combined_list = sorted(combined_materials.values(), key=lambda x: (
        0 if x["category"] == "primary" else 1 if x["category"] == "secondary" else 2, x["name"]))
    
    return {
        "results": results,
        "combined_materials": combined_list,
        "grand_total": round(sum(r["pricing"]["total_estimated"] for r in results), 2),
        "line_count": len(results),
        "stage": "refined",
    }


@router.post("/extra-works/{draft_id}/apply-ai")
async def apply_ai_to_draft(draft_id: str, city: Optional[str] = None, user: dict = Depends(require_m2)):
    """Generate and apply AI proposal to an existing draft"""
    draft = await db.extra_work_drafts.find_one({"id": draft_id, "org_id": user["org_id"]})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    proposal = await hybrid_ai_proposal(draft["title"], draft["unit"], draft["qty"], city, user["org_id"])
    
    update = {
        "normalized_activity_type": proposal["recognized"]["activity_type"],
        "normalized_activity_subtype": proposal["recognized"]["activity_subtype"],
        "ai_provider_used": proposal.get("provider", "unknown"),
        "ai_material_price_per_unit": proposal["pricing"]["material_price_per_unit"],
        "ai_labor_price_per_unit": proposal["pricing"]["labor_price_per_unit"],
        "ai_total_price_per_unit": proposal["pricing"]["total_price_per_unit"],
        "ai_small_qty_adjustment": proposal["pricing"]["small_qty_adjustment_percent"],
        "ai_confidence": proposal["confidence"],
        "ai_raw_response_summary": proposal.get("explanation", ""),
        "ai_price_before_manual_edit": proposal["pricing"]["total_price_per_unit"],
        "suggested_related_smr": proposal["related_smr"],
        "suggested_materials": proposal["materials"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.extra_work_drafts.update_one({"id": draft_id}, {"$set": update})
    
    updated = await db.extra_work_drafts.find_one({"id": draft_id}, {"_id": 0})
    return {"draft": updated, "proposal": proposal}


# ── Create Offer from Draft Rows ───────────────────────────────────

@router.post("/extra-works/create-offer", status_code=201)
async def create_offer_from_drafts(data: CreateOfferFromDrafts, user: dict = Depends(require_m2)):
    """Create a new offer from selected draft extra work rows"""
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if not data.draft_ids:
        raise HTTPException(status_code=400, detail="No draft rows selected")
    
    drafts = await db.extra_work_drafts.find(
        {"id": {"$in": data.draft_ids}, "org_id": user["org_id"], "status": "draft"},
        {"_id": 0}
    ).to_list(100)
    
    if not drafts:
        raise HTTPException(status_code=404, detail="No valid draft rows found")
    
    project_ids = set(d["project_id"] for d in drafts)
    if len(project_ids) > 1:
        raise HTTPException(status_code=400, detail="All draft rows must belong to the same project")
    
    project_id = drafts[0]["project_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    last = await db.offers.find_one({"org_id": user["org_id"]}, {"_id": 0, "offer_no": 1}, sort=[("created_at", -1)])
    if last and last.get("offer_no"):
        try:
            num = int(last["offer_no"].split("-")[1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    offer_no = f"OFF-{num:04d}"
    
    now = datetime.now(timezone.utc).isoformat()
    batch_id = str(uuid.uuid4())
    
    lines = []
    for i, draft in enumerate(drafts):
        material = draft.get("ai_material_price_per_unit") or 0
        labor = draft.get("ai_labor_price_per_unit") or 0
        qty = draft.get("qty", 1)
        line_material = round(qty * material, 2)
        line_labor = round(qty * labor, 2)
        
        location_parts = []
        if draft.get("location_floor"):
            location_parts.append(f"Ет.{draft['location_floor']}")
        if draft.get("location_room"):
            location_parts.append(draft["location_room"])
        if draft.get("location_zone"):
            location_parts.append(draft["location_zone"])
        location_str = ", ".join(location_parts)
        
        note_parts = []
        if location_str:
            note_parts.append(f"Локация: {location_str}")
        if draft.get("location_notes"):
            note_parts.append(draft["location_notes"])
        if draft.get("notes"):
            note_parts.append(draft["notes"])
        
        lines.append({
            "id": str(uuid.uuid4()),
            "activity_code": None,
            "activity_name": draft["title"],
            "unit": draft.get("unit", "m2"),
            "qty": qty,
            "material_unit_cost": material,
            "labor_unit_cost": labor,
            "labor_hours_per_unit": None,
            "line_material_cost": line_material,
            "line_labor_cost": line_labor,
            "line_total": round(line_material + line_labor, 2),
            "note": "; ".join(note_parts) if note_parts else None,
            "sort_order": i,
            "activity_type": draft.get("normalized_activity_type") or "Общо",
            "activity_subtype": draft.get("normalized_activity_subtype") or "",
        })
    
    subtotal = sum(l["line_total"] for l in lines)
    vat_amount = round(subtotal * data.vat_percent / 100, 2)
    total = round(subtotal + vat_amount, 2)
    
    title = data.title or f"Допълнителни СМР - {project.get('code', '')} ({datetime.now().strftime('%d.%m.%Y')})"
    
    offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": project_id,
        "offer_no": offer_no,
        "title": title,
        "offer_type": "extra",
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": data.currency,
        "vat_percent": data.vat_percent,
        "lines": lines,
        "notes": f"Създадена от {len(drafts)} допълнителни СМР",
        "subtotal": round(subtotal, 2),
        "vat_amount": vat_amount,
        "total": total,
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
        "source_batch_id": batch_id,
    }
    
    await db.offers.insert_one(offer)
    
    await db.extra_work_drafts.update_many(
        {"id": {"$in": data.draft_ids}},
        {"$set": {
            "status": "converted",
            "target_offer_id": offer["id"],
            "group_batch_id": batch_id,
            "updated_at": now,
        }}
    )
    
    await log_audit(user["org_id"], user["id"], user["email"], "extra_offer_created", "offer", offer["id"],
                    {"offer_no": offer_no, "drafts_count": len(drafts)})
    
    return {k: v for k, v in offer.items() if k != "_id"}



# ── Batch Save Drafts ──────────────────────────────────────────────

@router.post("/extra-works/batch-save", status_code=201)
async def batch_save_drafts(data: dict, user: dict = Depends(require_m2)):
    """Save multiple extra work drafts with AI data in one call"""
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    project_id = data.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    lines = data.get("lines", [])
    if not lines:
        raise HTTPException(status_code=400, detail="No lines to save")
    
    now = datetime.now(timezone.utc).isoformat()
    batch_id = str(uuid.uuid4())
    saved = []
    
    for line in lines:
        draft = {
            "id": str(uuid.uuid4()),
            "org_id": user["org_id"],
            "project_id": project_id,
            "source_type": "extra_work",
            "created_at": now,
            "updated_at": now,
            "created_by": user["id"],
            "work_date": data.get("work_date", now[:10]),
            "status": "draft",
            "title": line.get("title", ""),
            "normalized_activity_type": line.get("activity_type"),
            "normalized_activity_subtype": line.get("activity_subtype"),
            "unit": line.get("unit", "m2"),
            "qty": float(line.get("qty", 1)),
            "ai_provider_used": line.get("provider"),
            "ai_material_price_per_unit": line.get("material_price"),
            "ai_labor_price_per_unit": line.get("labor_price"),
            "ai_total_price_per_unit": line.get("total_price"),
            "ai_small_qty_adjustment": line.get("small_qty_adj"),
            "ai_confidence": line.get("confidence"),
            "ai_raw_response_summary": line.get("explanation"),
            "ai_price_before_manual_edit": line.get("original_total_price"),
            "final_user_accepted_price": line.get("total_price"),
            "location_floor": line.get("location_floor"),
            "location_room": line.get("location_room"),
            "location_zone": line.get("location_zone"),
            "location_notes": line.get("location_notes"),
            "notes": line.get("notes"),
            "photos": [],
            "suggested_related_smr": line.get("related_smr", []),
            "suggested_materials": line.get("materials", []),
            "target_offer_id": None,
            "group_batch_id": batch_id,
        }
        await db.extra_work_drafts.insert_one(draft)
        saved.append(draft["id"])
    
    return {"ok": True, "saved_count": len(saved), "batch_id": batch_id, "draft_ids": saved}


# ── Hourly Rates Config ────────────────────────────────────────────

@router.get("/ai-config/hourly-rates")
async def get_hourly_rates(user: dict = Depends(require_m2)):
    """Get worker hourly rate configuration (org-specific or DEMO)"""
    org_rates = await get_org_worker_rates(user["org_id"])
    if org_rates:
        return {"source": "organization", "currency": "EUR", "rates": org_rates}
    return {"source": "demo", "currency": "EUR", "rates": DEMO_WORKER_RATES}


@router.put("/ai-config/hourly-rates")
async def save_hourly_rates(data: dict, user: dict = Depends(require_m2)):
    """Save org-specific worker hourly rates"""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    
    rates = data.get("rates", {})
    now = datetime.now(timezone.utc).isoformat()
    
    await db.settings.update_one(
        {"_id": "worker_rates", "org_id": user["org_id"]},
        {"$set": {"_id": "worker_rates", "org_id": user["org_id"], "rates": rates, "updated_at": now, "updated_by": user["id"]}},
        upsert=True,
    )
    return {"ok": True, "source": "organization", "rates": rates}
