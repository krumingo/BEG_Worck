"""
Routes - SMR Analysis (Анализ на СМР).
Full cost analysis with materials, labor, logistics, markup, risk.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid
import copy

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.services.ai_proposal import rule_based_proposal, get_ai_proposal

router = APIRouter(tags=["SMR Analysis"])


# ── Pydantic Models ────────────────────────────────────────────────

class AnalysisCreate(BaseModel):
    project_id: str
    name: str
    created_from: Optional[str] = None
    created_from_type: Optional[str] = None  # missing_smr | offer


class AnalysisUpdate(BaseModel):
    name: Optional[str] = None


class LineCreate(BaseModel):
    smr_type: str
    smr_subtype: Optional[str] = None
    unit: str = "m2"
    qty: float = 1
    materials: Optional[list] = None
    labor_price_per_unit: float = 0
    logistics_pct: float = 10
    markup_pct: float = 15
    risk_pct: float = 5


class LineUpdate(BaseModel):
    smr_type: Optional[str] = None
    smr_subtype: Optional[str] = None
    unit: Optional[str] = None
    qty: Optional[float] = None
    materials: Optional[list] = None
    labor_price_per_unit: Optional[float] = None
    logistics_pct: Optional[float] = None
    markup_pct: Optional[float] = None
    risk_pct: Optional[float] = None


class AISuggestRequest(BaseModel):
    line_id: str
    city: Optional[str] = None


# ── Calculation Logic ──────────────────────────────────────────────

def calc_material_cost(materials: list) -> float:
    """Σ(unit_price × qty_per_unit × (1 + waste%) × (1 + logistics%))"""
    total = 0
    for m in (materials or []):
        up = m.get("unit_price", 0) or 0
        qpu = m.get("qty_per_unit", 0) or 0
        waste = m.get("waste_pct", 0) or 0
        raw = up * qpu * (1 + waste / 100)
        total += raw
    return round(total, 4)


def calc_line(line: dict) -> dict:
    """Recalculate all derived fields for a single line."""
    materials = line.get("materials", [])
    qty = line.get("qty", 1) or 1
    logistics_pct = line.get("logistics_pct", 10) or 0
    markup_pct = line.get("markup_pct", 15) or 0
    risk_pct = line.get("risk_pct", 5) or 0
    labor = line.get("labor_price_per_unit", 0) or 0

    mat_raw = calc_material_cost(materials)
    mat_with_logistics = round(mat_raw * (1 + logistics_pct / 100), 4)

    total_cost = round(mat_with_logistics + labor, 4)
    final_price = round(total_cost * (1 + markup_pct / 100) * (1 + risk_pct / 100), 2)
    final_total = round(final_price * qty, 2)

    line["material_cost_per_unit"] = round(mat_raw, 2)
    line["total_cost_per_unit"] = round(total_cost, 2)
    line["final_price_per_unit"] = final_price
    line["final_total"] = final_total
    return line


def calc_totals(lines: list) -> dict:
    """Compute analysis-level totals from all lines."""
    material_total = 0
    labor_total = 0
    logistics_total = 0
    cost_total = 0
    markup_total = 0
    risk_total = 0
    grand_total = 0

    for ln in lines:
        qty = ln.get("qty", 1) or 1
        mat_raw = ln.get("material_cost_per_unit", 0) or 0
        labor = ln.get("labor_price_per_unit", 0) or 0
        logistics_pct = ln.get("logistics_pct", 10) or 0
        markup_pct = ln.get("markup_pct", 15) or 0
        risk_pct = ln.get("risk_pct", 5) or 0

        mat_total_line = mat_raw * qty
        lab_total_line = labor * qty
        logistics_line = mat_raw * (logistics_pct / 100) * qty
        cost_line = (mat_raw * (1 + logistics_pct / 100) + labor) * qty
        cost_with_markup = cost_line * (1 + markup_pct / 100)
        cost_full = cost_with_markup * (1 + risk_pct / 100)

        material_total += mat_total_line
        labor_total += lab_total_line
        logistics_total += logistics_line
        cost_total += cost_line
        markup_total += cost_with_markup - cost_line
        risk_total += cost_full - cost_with_markup
        grand_total += cost_full

    return {
        "material_total": round(material_total, 2),
        "labor_total": round(labor_total, 2),
        "logistics_total": round(logistics_total, 2),
        "cost_total": round(cost_total, 2),
        "markup_total": round(markup_total, 2),
        "risk_total": round(risk_total, 2),
        "grand_total": round(grand_total, 2),
    }


# ── CRUD ───────────────────────────────────────────────────────────

@router.post("/smr-analyses", status_code=201)
async def create_analysis(data: AnalysisCreate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await db.projects.find_one({"id": data.project_id, "org_id": user["org_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Auto-increment version within project
    last = await db.smr_analyses.find_one(
        {"org_id": user["org_id"], "project_id": data.project_id},
        {"_id": 0, "version": 1},
        sort=[("version", -1)],
    )
    version = (last["version"] + 1) if last else 1

    now = datetime.now(timezone.utc).isoformat()
    analysis = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "project_name": project.get("name", ""),
        "name": data.name,
        "version": version,
        "status": "draft",
        "lines": [],
        "totals": calc_totals([]),
        "created_from": data.created_from,
        "created_from_type": data.created_from_type,
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "created_by_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        "approved_by": None,
        "approved_at": None,
    }

    # Pre-populate lines from source
    if data.created_from and data.created_from_type == "missing_smr":
        src = await db.missing_smr.find_one({"id": data.created_from, "org_id": user["org_id"]}, {"_id": 0})
        if src:
            line = {
                "line_id": str(uuid.uuid4()),
                "smr_type": src.get("smr_type") or src.get("activity_type") or "",
                "smr_subtype": src.get("activity_subtype") or "",
                "unit": src.get("unit", "m2"),
                "qty": src.get("qty", 1),
                "materials": [],
                "material_cost_per_unit": 0,
                "labor_price_per_unit": 0,
                "logistics_pct": 10,
                "markup_pct": 15,
                "risk_pct": 5,
                "total_cost_per_unit": 0,
                "final_price_per_unit": 0,
                "final_total": 0,
            }
            analysis["lines"] = [calc_line(line)]
            analysis["totals"] = calc_totals(analysis["lines"])

    await db.smr_analyses.insert_one(analysis)
    return {k: v for k, v in analysis.items() if k != "_id"}


@router.get("/smr-analyses")
async def list_analyses(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    query = {"org_id": user["org_id"]}
    if project_id:
        query["project_id"] = project_id
    if status:
        query["status"] = status
    items = await db.smr_analyses.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.get("/smr-analyses/{analysis_id}")
async def get_analysis(analysis_id: str, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return doc


@router.put("/smr-analyses/{analysis_id}")
async def update_analysis(analysis_id: str, data: AnalysisUpdate, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] == "locked":
        raise HTTPException(status_code=400, detail="Analysis is locked")
    update = {}
    if data.name is not None:
        update["name"] = data.name
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one({"id": analysis_id}, {"$set": update})
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


# ── Line Management ────────────────────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/lines")
async def add_line(analysis_id: str, data: LineCreate, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] == "locked":
        raise HTTPException(status_code=400, detail="Analysis is locked")

    line = {
        "line_id": str(uuid.uuid4()),
        "smr_type": data.smr_type,
        "smr_subtype": data.smr_subtype or "",
        "unit": data.unit,
        "qty": data.qty,
        "materials": data.materials or [],
        "material_cost_per_unit": 0,
        "labor_price_per_unit": data.labor_price_per_unit,
        "logistics_pct": data.logistics_pct,
        "markup_pct": data.markup_pct,
        "risk_pct": data.risk_pct,
        "total_cost_per_unit": 0,
        "final_price_per_unit": 0,
        "final_total": 0,
    }
    line = calc_line(line)
    lines = doc.get("lines", []) + [line]
    totals = calc_totals(lines)
    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"lines": lines, "totals": totals, "updated_at": now}},
    )
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


@router.put("/smr-analyses/{analysis_id}/lines/{line_id}")
async def update_line(analysis_id: str, line_id: str, data: LineUpdate, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] == "locked":
        raise HTTPException(status_code=400, detail="Analysis is locked")

    lines = doc.get("lines", [])
    found = False
    for ln in lines:
        if ln["line_id"] == line_id:
            for k, v in data.model_dump().items():
                if v is not None:
                    ln[k] = v
            calc_line(ln)
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Line not found")

    totals = calc_totals(lines)
    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"lines": lines, "totals": totals, "updated_at": now}},
    )
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


@router.delete("/smr-analyses/{analysis_id}/lines/{line_id}")
async def delete_line(analysis_id: str, line_id: str, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] == "locked":
        raise HTTPException(status_code=400, detail="Analysis is locked")

    lines = [ln for ln in doc.get("lines", []) if ln["line_id"] != line_id]
    if len(lines) == len(doc.get("lines", [])):
        raise HTTPException(status_code=404, detail="Line not found")

    totals = calc_totals(lines)
    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"lines": lines, "totals": totals, "updated_at": now}},
    )
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


# ── Recalculate ────────────────────────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/recalculate")
async def recalculate(analysis_id: str, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")

    lines = doc.get("lines", [])
    for ln in lines:
        calc_line(ln)
    totals = calc_totals(lines)
    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"lines": lines, "totals": totals, "updated_at": now}},
    )
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


# ── AI Suggest ─────────────────────────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/ai-suggest")
async def ai_suggest(analysis_id: str, data: AISuggestRequest, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] == "locked":
        raise HTTPException(status_code=400, detail="Analysis is locked")

    lines = doc.get("lines", [])
    target = None
    for ln in lines:
        if ln["line_id"] == data.line_id:
            target = ln
            break
    if not target:
        raise HTTPException(status_code=404, detail="Line not found")

    title = target["smr_type"]
    unit = target.get("unit", "m2")
    qty = target.get("qty", 1)

    proposal = await get_ai_proposal(title, unit, qty, data.city, user["org_id"])

    # Map AI materials to analysis format
    ai_materials = []
    for mat in proposal.get("materials", []):
        ai_materials.append({
            "name": mat.get("name", ""),
            "unit": mat.get("unit", ""),
            "qty_per_unit": mat.get("qty_per_unit") or mat.get("estimated_qty", 0) / max(qty, 1) if mat.get("estimated_qty") else 0,
            "unit_price": 0,
            "waste_pct": 5,
            "source": "ai",
        })

    target["materials"] = ai_materials
    target["labor_price_per_unit"] = proposal["pricing"]["labor_price_per_unit"]
    # Set material unit prices from AI total
    if ai_materials:
        mat_per_unit = proposal["pricing"]["material_price_per_unit"]
        # Distribute across materials proportionally
        for m in ai_materials:
            if m["qty_per_unit"] > 0:
                m["unit_price"] = round(mat_per_unit / len(ai_materials), 2)

    calc_line(target)
    totals = calc_totals(lines)
    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"lines": lines, "totals": totals, "updated_at": now}},
    )
    updated = await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})
    return {"analysis": updated, "proposal": proposal}


# ── Approve / Lock ─────────────────────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/approve")
async def approve_analysis(analysis_id: str, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] not in ["draft"]:
        raise HTTPException(status_code=400, detail="Only draft analyses can be approved")

    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {
            "status": "approved",
            "approved_by": user["id"],
            "approved_by_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            "approved_at": now,
            "updated_at": now,
        }},
    )
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


@router.post("/smr-analyses/{analysis_id}/lock")
async def lock_analysis(analysis_id: str, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] not in ["draft", "approved"]:
        raise HTTPException(status_code=400, detail="Cannot lock from current status")

    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"status": "locked", "updated_at": now}},
    )
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


# ── Snapshot (version+1 copy) ──────────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/snapshot")
async def snapshot_analysis(analysis_id: str, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")

    last = await db.smr_analyses.find_one(
        {"org_id": user["org_id"], "project_id": doc["project_id"]},
        {"_id": 0, "version": 1},
        sort=[("version", -1)],
    )
    new_version = (last["version"] + 1) if last else 1

    now = datetime.now(timezone.utc).isoformat()
    new_doc = copy.deepcopy(doc)
    new_doc["id"] = str(uuid.uuid4())
    new_doc["version"] = new_version
    new_doc["status"] = "draft"
    new_doc["name"] = f"{doc['name']} (v{new_version})"
    new_doc["created_at"] = now
    new_doc["updated_at"] = now
    new_doc["created_by"] = user["id"]
    new_doc["approved_by"] = None
    new_doc["approved_at"] = None
    # Give new line_ids
    for ln in new_doc.get("lines", []):
        ln["line_id"] = str(uuid.uuid4())

    await db.smr_analyses.insert_one(new_doc)
    return {k: v for k, v in new_doc.items() if k != "_id"}


# ── Compare Versions ───────────────────────────────────────────────

@router.get("/smr-analyses/{analysis_id}/compare/{version}")
async def compare_versions(analysis_id: str, version: int, user: dict = Depends(require_m2)):
    current = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]}, {"_id": 0})
    if not current:
        raise HTTPException(status_code=404, detail="Analysis not found")

    other = await db.smr_analyses.find_one(
        {"org_id": user["org_id"], "project_id": current["project_id"], "version": version},
        {"_id": 0},
    )
    if not other:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    return {
        "current": current,
        "compare": other,
        "diff": {
            "grand_total_diff": round(
                (current.get("totals", {}).get("grand_total", 0) or 0)
                - (other.get("totals", {}).get("grand_total", 0) or 0), 2
            ),
            "lines_current": len(current.get("lines", [])),
            "lines_compare": len(other.get("lines", [])),
        },
    }


# ── To Offer Bridge ───────────────────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/to-offer")
async def to_offer(analysis_id: str, user: dict = Depends(require_m2)):
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")

    project = await db.projects.find_one(
        {"id": doc["project_id"], "org_id": user["org_id"]},
        {"_id": 0, "code": 1, "name": 1},
    )
    last_offer = await db.offers.find_one(
        {"org_id": user["org_id"]}, {"_id": 0, "offer_no": 1}, sort=[("created_at", -1)]
    )
    num = 1
    if last_offer and last_offer.get("offer_no"):
        try:
            num = int(last_offer["offer_no"].split("-")[1]) + 1
        except Exception:
            pass
    offer_no = f"OFF-{num:04d}"

    now = datetime.now(timezone.utc).isoformat()
    offer_lines = []
    for i, ln in enumerate(doc.get("lines", [])):
        offer_lines.append({
            "id": str(uuid.uuid4()),
            "activity_code": None,
            "activity_name": ln.get("smr_type", ""),
            "unit": ln.get("unit", "m2"),
            "qty": ln.get("qty", 1),
            "material_unit_cost": ln.get("material_cost_per_unit", 0),
            "labor_unit_cost": ln.get("labor_price_per_unit", 0),
            "labor_hours_per_unit": None,
            "line_material_cost": round((ln.get("material_cost_per_unit", 0) or 0) * (ln.get("qty", 1) or 1), 2),
            "line_labor_cost": round((ln.get("labor_price_per_unit", 0) or 0) * (ln.get("qty", 1) or 1), 2),
            "line_total": ln.get("final_total", 0),
            "note": f"Markup {ln.get('markup_pct', 15)}%, Risk {ln.get('risk_pct', 5)}%",
            "sort_order": i,
            "activity_type": ln.get("smr_type", "Общо"),
            "activity_subtype": ln.get("smr_subtype", ""),
        })

    subtotal = sum(l["line_total"] for l in offer_lines)
    vat = round(subtotal * 0.2, 2)

    offer = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": doc["project_id"],
        "offer_no": offer_no,
        "title": f"От анализ: {doc['name']}",
        "offer_type": "smr_analysis",
        "status": "Draft",
        "version": 1,
        "parent_offer_id": None,
        "currency": "EUR",
        "vat_percent": 20.0,
        "lines": offer_lines,
        "notes": f"Генерирана от Анализ на СМР v{doc['version']}",
        "subtotal": round(subtotal, 2),
        "vat_amount": vat,
        "total": round(subtotal + vat, 2),
        "created_at": now,
        "updated_at": now,
        "sent_at": None,
        "accepted_at": None,
        "source_analysis_id": analysis_id,
    }
    await db.offers.insert_one(offer)

    return {"ok": True, "offer_id": offer["id"], "offer_no": offer_no}
