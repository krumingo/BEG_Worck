"""
Routes - Price Modifiers (Ценови модификатори).
Cascade: org_default → project override → line override.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.services.price_modifiers import (
    get_effective_modifiers, apply_modifiers_to_price,
    DEFAULT_MODIFIERS, DEFAULT_AUTO_RULES, MODIFIER_KEYS,
)

router = APIRouter(tags=["Price Modifiers"])


class ModifiersUpdate(BaseModel):
    modifiers: Optional[dict] = None
    auto_rules: Optional[dict] = None


class CalculateRequest(BaseModel):
    base_cost: float
    project_id: Optional[str] = None


# ── Org Defaults ───────────────────────────────────────────────────

@router.get("/price-modifiers/org")
async def get_org_modifiers(user: dict = Depends(require_m2)):
    doc = await db.price_modifiers_config.find_one(
        {"org_id": user["org_id"], "scope": "org_default"}, {"_id": 0}
    )
    if not doc:
        return {"scope": "org_default", "modifiers": DEFAULT_MODIFIERS, "auto_rules": DEFAULT_AUTO_RULES, "is_default": True}
    return doc


@router.put("/price-modifiers/org")
async def update_org_modifiers(data: ModifiersUpdate, user: dict = Depends(require_m2)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")

    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now, "updated_by": user["id"]}
    if data.modifiers:
        for k in MODIFIER_KEYS:
            if k in data.modifiers:
                update[f"modifiers.{k}"] = data.modifiers[k]
    if data.auto_rules:
        for k in DEFAULT_AUTO_RULES:
            if k in data.auto_rules:
                update[f"auto_rules.{k}"] = data.auto_rules[k]

    await db.price_modifiers_config.update_one(
        {"org_id": user["org_id"], "scope": "org_default"},
        {"$set": update, "$setOnInsert": {
            "id": str(uuid.uuid4()), "org_id": user["org_id"], "scope": "org_default",
            "project_id": None, "line_id": None, "created_at": now,
        }},
        upsert=True,
    )
    return await db.price_modifiers_config.find_one(
        {"org_id": user["org_id"], "scope": "org_default"}, {"_id": 0}
    )


# ── Project Override ───────────────────────────────────────────────

@router.get("/price-modifiers/project/{project_id}")
async def get_project_modifiers(project_id: str, user: dict = Depends(require_m2)):
    doc = await db.price_modifiers_config.find_one(
        {"org_id": user["org_id"], "scope": "project", "project_id": project_id}, {"_id": 0}
    )
    return doc or {"scope": "project", "project_id": project_id, "modifiers": {}, "auto_rules": {}, "has_override": False}


@router.put("/price-modifiers/project/{project_id}")
async def update_project_modifiers(project_id: str, data: ModifiersUpdate, user: dict = Depends(require_m2)):
    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now, "updated_by": user["id"]}
    if data.modifiers:
        for k in MODIFIER_KEYS:
            if k in data.modifiers:
                update[f"modifiers.{k}"] = data.modifiers[k]
    if data.auto_rules:
        for k in DEFAULT_AUTO_RULES:
            if k in data.auto_rules:
                update[f"auto_rules.{k}"] = data.auto_rules[k]

    await db.price_modifiers_config.update_one(
        {"org_id": user["org_id"], "scope": "project", "project_id": project_id},
        {"$set": update, "$setOnInsert": {
            "id": str(uuid.uuid4()), "org_id": user["org_id"], "scope": "project",
            "project_id": project_id, "line_id": None, "created_at": now,
        }},
        upsert=True,
    )
    return await db.price_modifiers_config.find_one(
        {"org_id": user["org_id"], "scope": "project", "project_id": project_id}, {"_id": 0}
    )


@router.delete("/price-modifiers/project/{project_id}")
async def delete_project_modifiers(project_id: str, user: dict = Depends(require_m2)):
    await db.price_modifiers_config.delete_one(
        {"org_id": user["org_id"], "scope": "project", "project_id": project_id}
    )
    return {"ok": True}


# ── Effective (merged with auto-rules) ─────────────────────────────

@router.get("/price-modifiers/effective/{project_id}")
async def get_effective(project_id: str, user: dict = Depends(require_m2)):
    result = await get_effective_modifiers(user["org_id"], project_id)
    return {"project_id": project_id, **result}


# ── Calculate ──────────────────────────────────────────────────────

@router.post("/price-modifiers/calculate")
async def calculate_price(data: CalculateRequest, user: dict = Depends(require_m2)):
    eff = await get_effective_modifiers(user["org_id"], data.project_id)
    result = apply_modifiers_to_price(data.base_cost, eff["modifiers"])
    return result


# ── SMR Analysis Integration ──────────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/recalculate-with-modifiers")
async def recalculate_with_modifiers(analysis_id: str, user: dict = Depends(require_m2)):
    """Recalculate all lines using project-level price modifiers."""
    from app.routes.smr_analysis import calc_line, calc_totals

    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")

    project_id = doc["project_id"]
    eff = await get_effective_modifiers(user["org_id"], project_id)
    mods = eff["modifiers"]

    lines = doc.get("lines", [])
    for ln in lines:
        # Check for line-level override
        line_eff = await get_effective_modifiers(user["org_id"], project_id, ln.get("line_id"))
        line_mods = line_eff["modifiers"]

        # Apply modifiers: replace markup/risk with full chain
        # Base cost = material + labor (without old markup/risk)
        materials = ln.get("materials", [])
        labor = ln.get("labor_price_per_unit", 0) or 0
        mat_raw = 0
        for m in materials:
            up = m.get("unit_price", 0) or 0
            qpu = m.get("qty_per_unit", 0) or 0
            mat_raw += up * qpu
        base = round(mat_raw + labor, 4)

        # Apply full modifier chain
        result = apply_modifiers_to_price(base, line_mods)
        ln["final_price_per_unit"] = result["final_price"]
        ln["final_total"] = round(result["final_price"] * (ln.get("qty", 1) or 1), 2)
        ln["material_cost_per_unit"] = round(mat_raw, 2)
        ln["total_cost_per_unit"] = round(base, 2)
        ln["modifiers_applied"] = line_mods

    totals = calc_totals(lines)
    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"lines": lines, "totals": totals, "updated_at": now}},
    )
    return await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})


@router.get("/smr-analyses/{analysis_id}/lines/{line_id}/modifier-breakdown")
async def get_line_modifier_breakdown(analysis_id: str, line_id: str, user: dict = Depends(require_m2)):
    """Show step-by-step modifier breakdown for a specific line."""
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")

    target = None
    for ln in doc.get("lines", []):
        if ln["line_id"] == line_id:
            target = ln
            break
    if not target:
        raise HTTPException(status_code=404, detail="Line not found")

    project_id = doc["project_id"]
    eff = await get_effective_modifiers(user["org_id"], project_id, line_id)

    base = target.get("total_cost_per_unit", 0) or 0
    result = apply_modifiers_to_price(base, eff["modifiers"])
    result["line_id"] = line_id
    result["smr_type"] = target.get("smr_type", "")
    result["qty"] = target.get("qty", 1)
    result["line_total"] = round(result["final_price"] * (target.get("qty", 1) or 1), 2)

    return result
