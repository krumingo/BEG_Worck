"""
Routes - Offer Execution Budget (per line).
Budget, Margin, Planned Materials tabs for Offer Editor.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2

router = APIRouter(tags=["Offer Execution Budget"])


@router.get("/offer-budgets/{offer_id}")
async def get_offer_budgets(offer_id: str, user: dict = Depends(require_m2)):
    """Get execution budget data for all lines of an offer"""
    org_id = user["org_id"]
    offer = await db.offers.find_one({"id": offer_id, "org_id": org_id}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    budgets = await db.offer_line_budgets.find(
        {"org_id": org_id, "offer_id": offer_id}, {"_id": 0}
    ).to_list(200)
    budget_map = {b["line_id"]: b for b in budgets}

    lines = []
    for ol in offer.get("lines", []):
        lid = ol.get("id", "")
        qty = ol.get("qty", 0)
        sale_mat = ol.get("material_unit_cost", 0)
        sale_lab = ol.get("labor_unit_cost", 0)
        sale_total = round(qty * (sale_mat + sale_lab), 2)

        b = budget_map.get(lid, {})
        bud_mat = b.get("budget_material_unit_cost", sale_mat)
        bud_lab = b.get("budget_labor_unit_cost", sale_lab)
        bud_mat_total = round(qty * bud_mat, 2)
        bud_lab_total = round(qty * bud_lab, 2)
        bud_total = round(bud_mat_total + bud_lab_total, 2)
        margin_val = round(sale_total - bud_total, 2)
        margin_pct = round(margin_val / sale_total * 100, 1) if sale_total > 0 else 0

        lines.append({
            "line_id": lid,
            "activity_name": ol.get("activity_name", ""),
            "unit": ol.get("unit", ""),
            "qty": qty,
            "sale_material_unit": sale_mat,
            "sale_labor_unit": sale_lab,
            "sale_total": sale_total,
            "budget_material_unit_cost": bud_mat,
            "budget_labor_unit_cost": bud_lab,
            "budget_material_total": bud_mat_total,
            "budget_labor_total": bud_lab_total,
            "budget_total": bud_total,
            "material_margin_percent": b.get("material_margin_percent", 0),
            "labor_margin_percent": b.get("labor_margin_percent", 0),
            "planned_labor_hours": b.get("planned_labor_hours"),
            "margin_value": margin_val,
            "margin_percent": margin_pct,
            "notes": b.get("notes", ""),
            "has_budget": lid in budget_map,
        })

    total_sale = sum(l["sale_total"] for l in lines)
    total_budget = sum(l["budget_total"] for l in lines)
    total_margin = round(total_sale - total_budget, 2)

    return {
        "offer_id": offer_id,
        "offer_no": offer.get("offer_no", ""),
        "currency": offer.get("currency", "EUR"),
        "lines": lines,
        "totals": {
            "sale": total_sale,
            "budget": total_budget,
            "margin_value": total_margin,
            "margin_percent": round(total_margin / total_sale * 100, 1) if total_sale > 0 else 0,
        },
    }


@router.put("/offer-budgets/{offer_id}")
async def save_offer_budgets(offer_id: str, data: dict, user: dict = Depends(require_m2)):
    """Save execution budget data for offer lines"""
    org_id = user["org_id"]
    offer = await db.offers.find_one({"id": offer_id, "org_id": org_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    lines_data = data.get("lines", [])
    now = datetime.now(timezone.utc).isoformat()
    saved = 0

    for ld in lines_data:
        lid = ld.get("line_id")
        if not lid:
            continue
        budget_doc = {
            "org_id": org_id,
            "offer_id": offer_id,
            "line_id": lid,
            "budget_material_unit_cost": float(ld.get("budget_material_unit_cost", 0)),
            "budget_labor_unit_cost": float(ld.get("budget_labor_unit_cost", 0)),
            "material_margin_percent": float(ld.get("material_margin_percent", 0)),
            "labor_margin_percent": float(ld.get("labor_margin_percent", 0)),
            "planned_labor_hours": float(ld["planned_labor_hours"]) if ld.get("planned_labor_hours") is not None else None,
            "notes": ld.get("notes", ""),
            "updated_at": now,
            "updated_by": user["id"],
        }
        await db.offer_line_budgets.update_one(
            {"org_id": org_id, "offer_id": offer_id, "line_id": lid},
            {"$set": budget_doc},
            upsert=True,
        )
        saved += 1

    return {"ok": True, "saved": saved}


@router.get("/offer-materials/{offer_id}")
async def get_offer_planned_materials(offer_id: str, user: dict = Depends(require_m2)):
    """Get planned material breakdown for an offer (from AI suggestions + planned_materials)"""
    org_id = user["org_id"]
    offer = await db.offers.find_one({"id": offer_id, "org_id": org_id}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    # From planned_materials collection
    planned = await db.planned_materials.find(
        {"org_id": org_id, "source_offer_id": offer_id, "status": "active"},
        {"_id": 0}
    ).to_list(500)

    # From extra work drafts linked to this offer
    ai_materials = []
    if offer.get("source_batch_id"):
        drafts = await db.extra_work_drafts.find(
            {"group_batch_id": offer["source_batch_id"]},
            {"_id": 0, "title": 1, "suggested_materials": 1}
        ).to_list(50)
        for draft in drafts:
            for mat in (draft.get("suggested_materials") or []):
                ai_materials.append({
                    "material_name": mat.get("name", ""),
                    "category": mat.get("category", "primary"),
                    "unit": mat.get("unit", ""),
                    "estimated_qty": mat.get("estimated_qty"),
                    "reason": mat.get("reason", ""),
                    "source": "ai_suggestion",
                    "source_smr": draft.get("title", ""),
                })

    # Group by material name
    grouped = {}
    for pm in planned:
        name = pm.get("material_name", "")
        if name not in grouped:
            grouped[name] = {"material_name": name, "category": pm.get("category", ""), "unit": pm.get("unit", ""), "total_qty": 0, "sources": [], "source_type": "planned"}
        grouped[name]["total_qty"] += pm.get("planned_qty_with_waste", 0)
        grouped[name]["sources"].append(pm.get("activity_name", ""))

    for am in ai_materials:
        name = am["material_name"]
        if name not in grouped:
            grouped[name] = {"material_name": name, "category": am["category"], "unit": am["unit"], "total_qty": 0, "sources": [], "source_type": "ai"}
        if am.get("estimated_qty"):
            grouped[name]["total_qty"] += am["estimated_qty"]
        grouped[name]["sources"].append(am.get("source_smr", ""))

    materials = sorted(grouped.values(), key=lambda x: (
        0 if x["category"] == "primary" else 1 if x["category"] == "secondary" else 2 if x["category"] == "consumable" else 3,
        x["material_name"]
    ))

    for m in materials:
        m["total_qty"] = round(m["total_qty"], 2)
        m["sources"] = list(set(s for s in m["sources"] if s))

    return {
        "offer_id": offer_id,
        "materials": materials,
        "total_unique": len(materials),
        "total_planned": len(planned),
        "total_ai": len(ai_materials),
    }
