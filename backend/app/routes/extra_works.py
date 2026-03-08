"""
Routes - Extra Works Draft + AI Proposal (M2 extension).
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
    currency: str = "BGN"
    vat_percent: float = 20.0


class AIProposalRequest(BaseModel):
    title: str
    unit: str = "m2"
    qty: float = 1


# ── AI Proposal Service (Rule-Based MVP) ───────────────────────────

# Construction knowledge base for Bulgarian SMR pricing
ACTIVITY_KNOWLEDGE = {
    "мазилка": {
        "type": "Мокри процеси", "subtype": "Мазилка",
        "unit": "m2",
        "material_price": 8.50, "labor_price": 12.00,
        "small_qty_threshold": 5, "small_qty_multiplier": 1.35,
        "related": ["Грундиране преди мазилка", "Шпакловка", "Шлайфане", "Боядисване", "Ъглови профили"],
        "materials": {
            "primary": [
                {"name": "Гипсова мазилка", "unit": "кг", "qty_per_unit": 1.2, "category": "primary"},
                {"name": "Грунд", "unit": "л", "qty_per_unit": 0.15, "category": "primary"},
            ],
            "secondary": [
                {"name": "Ъглови профили PVC", "unit": "бр", "qty_per_unit": 0.3, "category": "secondary"},
                {"name": "Мрежа за мазилка", "unit": "м", "qty_per_unit": 0.5, "category": "secondary"},
                {"name": "Щифтове / дюбели", "unit": "бр", "qty_per_unit": 2, "category": "secondary"},
            ],
            "consumables": [
                {"name": "Шкурка P120", "unit": "бр", "qty_per_unit": 0.1, "category": "consumable"},
                {"name": "Тиксо хартиено", "unit": "бр", "qty_per_unit": 0.05, "category": "consumable"},
                {"name": "Найлон покривен", "unit": "м", "qty_per_unit": 0.3, "category": "consumable"},
            ],
        },
    },
    "боядисване": {
        "type": "Довършителни", "subtype": "Боядисване",
        "unit": "m2",
        "material_price": 4.50, "labor_price": 6.00,
        "small_qty_threshold": 10, "small_qty_multiplier": 1.30,
        "related": ["Шпакловка", "Шлайфане", "Грундиране", "Мазилка", "Тапети"],
        "materials": {
            "primary": [
                {"name": "Латекс интериорен", "unit": "л", "qty_per_unit": 0.25, "category": "primary"},
                {"name": "Грунд дълбокопроникващ", "unit": "л", "qty_per_unit": 0.12, "category": "primary"},
            ],
            "secondary": [
                {"name": "Шпакловка финишна", "unit": "кг", "qty_per_unit": 0.3, "category": "secondary"},
            ],
            "consumables": [
                {"name": "Четка плоска", "unit": "бр", "qty_per_unit": 0.02, "category": "consumable"},
                {"name": "Валяк / мече", "unit": "бр", "qty_per_unit": 0.03, "category": "consumable"},
                {"name": "Тиксо хартиено", "unit": "бр", "qty_per_unit": 0.05, "category": "consumable"},
                {"name": "Найлон покривен", "unit": "м", "qty_per_unit": 0.4, "category": "consumable"},
                {"name": "Вана за боя", "unit": "бр", "qty_per_unit": 0.02, "category": "consumable"},
                {"name": "Шкурка P180", "unit": "бр", "qty_per_unit": 0.08, "category": "consumable"},
            ],
        },
    },
    "шпакловка": {
        "type": "Довършителни", "subtype": "Шпакловка",
        "unit": "m2",
        "material_price": 5.00, "labor_price": 8.00,
        "small_qty_threshold": 5, "small_qty_multiplier": 1.35,
        "related": ["Грундиране", "Боядисване", "Мазилка", "Шлайфане", "Тапети"],
        "materials": {
            "primary": [
                {"name": "Шпакловка финишна", "unit": "кг", "qty_per_unit": 1.0, "category": "primary"},
                {"name": "Грунд", "unit": "л", "qty_per_unit": 0.12, "category": "primary"},
            ],
            "secondary": [
                {"name": "Бандажна лента", "unit": "м", "qty_per_unit": 0.3, "category": "secondary"},
            ],
            "consumables": [
                {"name": "Шкурка P120/P180", "unit": "бр", "qty_per_unit": 0.15, "category": "consumable"},
                {"name": "Шпакла 30см", "unit": "бр", "qty_per_unit": 0.01, "category": "consumable"},
                {"name": "Найлон покривен", "unit": "м", "qty_per_unit": 0.3, "category": "consumable"},
            ],
        },
    },
    "плочки": {
        "type": "Довършителни", "subtype": "Облицовка",
        "unit": "m2",
        "material_price": 25.00, "labor_price": 22.00,
        "small_qty_threshold": 3, "small_qty_multiplier": 1.40,
        "related": ["Хидроизолация", "Фугиране", "Нивелация на основа", "Силиконова фуга", "Ъглови лайсни"],
        "materials": {
            "primary": [
                {"name": "Плочки", "unit": "м2", "qty_per_unit": 1.1, "category": "primary"},
                {"name": "Лепило за плочки", "unit": "кг", "qty_per_unit": 4.0, "category": "primary"},
                {"name": "Фугираща смес", "unit": "кг", "qty_per_unit": 0.5, "category": "primary"},
            ],
            "secondary": [
                {"name": "Хидроизолация", "unit": "кг", "qty_per_unit": 0.8, "category": "secondary"},
                {"name": "Грунд", "unit": "л", "qty_per_unit": 0.15, "category": "secondary"},
                {"name": "Кръстчета за фуги", "unit": "бр", "qty_per_unit": 15, "category": "secondary"},
            ],
            "consumables": [
                {"name": "Силикон санитарен", "unit": "бр", "qty_per_unit": 0.05, "category": "consumable"},
                {"name": "Ъглови лайсни PVC", "unit": "м", "qty_per_unit": 0.3, "category": "consumable"},
            ],
        },
    },
    "гипсокартон": {
        "type": "Сухо строителство", "subtype": "Гипсокартон",
        "unit": "m2",
        "material_price": 15.00, "labor_price": 16.00,
        "small_qty_threshold": 5, "small_qty_multiplier": 1.30,
        "related": ["Шпакловка на ГК", "Бандажиране", "Боядисване", "Звукоизолация", "Термоизолация"],
        "materials": {
            "primary": [
                {"name": "Гипсокартон 12.5мм", "unit": "м2", "qty_per_unit": 1.1, "category": "primary"},
                {"name": "Профили CD/UD", "unit": "м", "qty_per_unit": 2.5, "category": "primary"},
            ],
            "secondary": [
                {"name": "Каменна вата 5см", "unit": "м2", "qty_per_unit": 1.0, "category": "secondary"},
                {"name": "Винтове за ГК", "unit": "бр", "qty_per_unit": 20, "category": "secondary"},
                {"name": "Дюбели", "unit": "бр", "qty_per_unit": 5, "category": "secondary"},
            ],
            "consumables": [
                {"name": "Бандажна лента", "unit": "м", "qty_per_unit": 1.5, "category": "consumable"},
                {"name": "Шпакловка за ГК", "unit": "кг", "qty_per_unit": 0.5, "category": "consumable"},
            ],
        },
    },
    "електро": {
        "type": "Инсталации", "subtype": "Електро",
        "unit": "pcs",
        "material_price": 35.00, "labor_price": 25.00,
        "small_qty_threshold": 3, "small_qty_multiplier": 1.25,
        "related": ["Окабеляване", "Пробиване на канали", "Мазилка след канали", "Монтаж табло", "Заземяване"],
        "materials": {
            "primary": [
                {"name": "Кабел NYM 3x2.5", "unit": "м", "qty_per_unit": 5.0, "category": "primary"},
                {"name": "Кутия конзола", "unit": "бр", "qty_per_unit": 1.0, "category": "primary"},
                {"name": "Ключ/контакт", "unit": "бр", "qty_per_unit": 1.0, "category": "primary"},
            ],
            "secondary": [
                {"name": "Гофрирана тръба", "unit": "м", "qty_per_unit": 5.0, "category": "secondary"},
                {"name": "Клеми", "unit": "бр", "qty_per_unit": 3, "category": "secondary"},
            ],
            "consumables": [
                {"name": "Тиксо изолирбанд", "unit": "бр", "qty_per_unit": 0.1, "category": "consumable"},
            ],
        },
    },
    "ВиК": {
        "type": "Инсталации", "subtype": "ВиК",
        "unit": "pcs",
        "material_price": 45.00, "labor_price": 30.00,
        "small_qty_threshold": 2, "small_qty_multiplier": 1.30,
        "related": ["Пробиване на канали", "Хидроизолация", "Мазилка", "Плочки", "Монтаж санитария"],
        "materials": {
            "primary": [
                {"name": "PPR тръба 20мм", "unit": "м", "qty_per_unit": 3.0, "category": "primary"},
                {"name": "Фитинги PPR", "unit": "бр", "qty_per_unit": 4, "category": "primary"},
            ],
            "secondary": [
                {"name": "Скоби", "unit": "бр", "qty_per_unit": 3, "category": "secondary"},
                {"name": "Тефлонова лента", "unit": "бр", "qty_per_unit": 0.2, "category": "secondary"},
            ],
            "consumables": [],
        },
    },
}

# Default fallback
DEFAULT_KNOWLEDGE = {
    "type": "Общо", "subtype": "СМР",
    "unit": "pcs",
    "material_price": 10.00, "labor_price": 15.00,
    "small_qty_threshold": 5, "small_qty_multiplier": 1.25,
    "related": ["Подготовка на основа", "Почистване", "Измерване"],
    "materials": {
        "primary": [],
        "secondary": [],
        "consumables": [
            {"name": "Общи консумативи", "unit": "к-т", "qty_per_unit": 0.1, "category": "consumable"},
        ],
    },
}


def find_matching_knowledge(title: str) -> dict:
    """Match input text to knowledge base using keyword matching"""
    title_lower = title.lower()
    for keyword, data in ACTIVITY_KNOWLEDGE.items():
        if keyword.lower() in title_lower:
            return data
    # Check for common synonyms
    synonyms = {
        "мазилк": "мазилка", "оштукатурване": "мазилка", "щукатур": "мазилка",
        "боя": "боядисване", "латекс": "боядисване", "пребоядисва": "боядисване",
        "шпакл": "шпакловка",
        "плоч": "плочки", "фаянс": "плочки", "теракот": "плочки", "облицов": "плочки",
        "гипсокарт": "гипсокартон", "ГК": "гипсокартон", "сух монтаж": "гипсокартон",
        "ел.": "електро", "електрич": "електро", "окабеля": "електро", "контакт": "електро", "ключ": "електро",
        "водопров": "ВиК", "канализ": "ВиК", "тръб": "ВиК", "сифон": "ВиК",
    }
    for syn, key in synonyms.items():
        if syn in title_lower:
            return ACTIVITY_KNOWLEDGE.get(key, DEFAULT_KNOWLEDGE)
    return DEFAULT_KNOWLEDGE


def generate_ai_proposal(title: str, unit: str, qty: float) -> dict:
    """Generate AI proposal based on rule-based knowledge"""
    knowledge = find_matching_knowledge(title)
    
    material_price = knowledge["material_price"]
    labor_price = knowledge["labor_price"]
    total_price = material_price + labor_price
    
    # Small quantity adjustment
    small_qty_adj = 0
    if qty <= knowledge["small_qty_threshold"]:
        multiplier = knowledge["small_qty_multiplier"]
        small_qty_adj = round((multiplier - 1) * 100, 0)
        material_price = round(material_price * multiplier, 2)
        labor_price = round(labor_price * multiplier, 2)
        total_price = material_price + labor_price
    
    # Build material lists with qty estimates
    materials = []
    for cat_key in ["primary", "secondary", "consumables"]:
        for mat in knowledge["materials"].get(cat_key, []):
            est_qty = round(mat.get("qty_per_unit", 0) * qty, 2) if mat.get("qty_per_unit") else None
            materials.append({
                "name": mat["name"],
                "unit": mat.get("unit", ""),
                "estimated_qty": est_qty,
                "category": mat.get("category", cat_key),
            })
    
    return {
        "recognized": {
            "activity_type": knowledge["type"],
            "activity_subtype": knowledge["subtype"],
            "suggested_unit": knowledge["unit"],
        },
        "pricing": {
            "material_price_per_unit": material_price,
            "labor_price_per_unit": labor_price,
            "total_price_per_unit": total_price,
            "small_qty_adjustment_percent": small_qty_adj,
            "total_estimated": round(total_price * qty, 2),
        },
        "related_smr": knowledge["related"][:5],
        "materials": materials,
        "confidence": 0.85 if knowledge != DEFAULT_KNOWLEDGE else 0.3,
    }


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
        "ai_material_price_per_unit": None,
        "ai_labor_price_per_unit": None,
        "ai_total_price_per_unit": None,
        "ai_small_qty_adjustment": None,
        "ai_confidence": None,
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


# ── AI Proposal Endpoint ───────────────────────────────────────────

@router.post("/extra-works/ai-proposal")
async def get_ai_proposal(data: AIProposalRequest, user: dict = Depends(require_m2)):
    """Generate AI proposal for a work description"""
    proposal = generate_ai_proposal(data.title, data.unit, data.qty)
    return proposal


@router.post("/extra-works/{draft_id}/apply-ai")
async def apply_ai_to_draft(draft_id: str, user: dict = Depends(require_m2)):
    """Generate and apply AI proposal to an existing draft"""
    draft = await db.extra_work_drafts.find_one({"id": draft_id, "org_id": user["org_id"]})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    proposal = generate_ai_proposal(draft["title"], draft["unit"], draft["qty"])
    
    update = {
        "normalized_activity_type": proposal["recognized"]["activity_type"],
        "normalized_activity_subtype": proposal["recognized"]["activity_subtype"],
        "ai_material_price_per_unit": proposal["pricing"]["material_price_per_unit"],
        "ai_labor_price_per_unit": proposal["pricing"]["labor_price_per_unit"],
        "ai_total_price_per_unit": proposal["pricing"]["total_price_per_unit"],
        "ai_small_qty_adjustment": proposal["pricing"]["small_qty_adjustment_percent"],
        "ai_confidence": proposal["confidence"],
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
    
    # Fetch all selected drafts
    drafts = await db.extra_work_drafts.find(
        {"id": {"$in": data.draft_ids}, "org_id": user["org_id"], "status": "draft"},
        {"_id": 0}
    ).to_list(100)
    
    if not drafts:
        raise HTTPException(status_code=404, detail="No valid draft rows found")
    
    # All drafts must belong to same project
    project_ids = set(d["project_id"] for d in drafts)
    if len(project_ids) > 1:
        raise HTTPException(status_code=400, detail="All draft rows must belong to the same project")
    
    project_id = drafts[0]["project_id"]
    project = await db.projects.find_one({"id": project_id, "org_id": user["org_id"]}, {"_id": 0, "code": 1, "name": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Generate offer number
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
    
    # Convert drafts to offer lines
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
    
    # Update draft rows status
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
