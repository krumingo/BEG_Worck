"""
Routes - Live Pricing Engine for construction materials.
3 AI agents: BG retail stores, online catalogs, internal historical database.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from pydantic import BaseModel

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m2
from app.services.pricing_engine import get_material_price, batch_get_prices
from app.routes.smr_analysis import calc_line, calc_totals

router = APIRouter(tags=["Pricing Engine"])


class BatchRequest(BaseModel):
    materials: List[str]


# ── Endpoints ──────────────────────────────────────────────────────

@router.get("/pricing/material")
async def get_single_price(name: str, force: bool = False, user: dict = Depends(require_m2)):
    result = await get_material_price(name, user["org_id"], force_refresh=force)
    return result


@router.post("/pricing/batch")
async def get_batch_prices(data: BatchRequest, user: dict = Depends(require_m2)):
    if not data.materials:
        raise HTTPException(status_code=400, detail="No materials provided")
    results = await batch_get_prices(data.materials, user["org_id"])
    return {"results": results, "total": len(results)}


@router.post("/pricing/refresh")
async def refresh_price(name: str, user: dict = Depends(require_m2)):
    result = await get_material_price(name, user["org_id"], force_refresh=True)
    return result


@router.get("/pricing/history")
async def get_price_history(name: str, user: dict = Depends(require_m2)):
    norm = name.lower().strip()
    doc = await db.material_prices.find_one(
        {"org_id": user["org_id"], "material_name_normalized": norm},
        {"_id": 0},
    )
    if not doc:
        return {"material_name": name, "history": [], "total": 0}
    return {
        "material_name": name,
        "current": doc,
        "history": doc.get("prices", []),
        "total": len(doc.get("prices", [])),
    }


@router.get("/pricing/catalog")
async def get_catalog(
    category: Optional[str] = None,
    user: dict = Depends(require_m2),
):
    query = {"org_id": user["org_id"]}
    if category:
        query["material_category"] = {"$regex": category, "$options": "i"}
    items = await db.material_prices.find(query, {"_id": 0}).sort("material_name", 1).to_list(500)
    return {"items": items, "total": len(items)}


# ── Integration with SMR Analysis ──────────────────────────────────

@router.post("/smr-analyses/{analysis_id}/lines/{line_id}/fetch-prices")
async def fetch_prices_for_line(analysis_id: str, line_id: str, user: dict = Depends(require_m2)):
    """Fetch live prices for all materials in a line and update unit_prices."""
    doc = await db.smr_analyses.find_one({"id": analysis_id, "org_id": user["org_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if doc["status"] == "locked":
        raise HTTPException(status_code=400, detail="Analysis is locked")

    lines = doc.get("lines", [])
    target = None
    for ln in lines:
        if ln["line_id"] == line_id:
            target = ln
            break
    if not target:
        raise HTTPException(status_code=404, detail="Line not found")

    materials = target.get("materials", [])
    if not materials:
        raise HTTPException(status_code=400, detail="Line has no materials")

    # Fetch prices for all materials in parallel
    mat_names = [m.get("name", "") for m in materials if m.get("name")]
    price_results = await batch_get_prices(mat_names, user["org_id"])

    # Map results back to materials
    price_map = {}
    for pr in price_results:
        if isinstance(pr, dict) and pr.get("median_price"):
            price_map[pr["material_name_normalized"]] = pr

    updated_materials = []
    pricing_details = []
    for m in materials:
        norm = m.get("name", "").lower().strip()
        pr = price_map.get(norm)
        if pr and pr.get("median_price"):
            m["unit_price"] = pr["median_price"]
            m["price_source"] = "live_pricing"
            m["price_confidence"] = pr.get("confidence", 0)
            m["price_fetched_at"] = pr.get("last_refreshed_at")
            pricing_details.append({
                "material": m["name"],
                "old_price": m.get("unit_price", 0),
                "new_price": pr["median_price"],
                "confidence": pr.get("confidence", 0),
                "agents": len(pr.get("prices", [])),
            })
        updated_materials.append(m)

    target["materials"] = updated_materials
    calc_line(target)
    totals = calc_totals(lines)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.smr_analyses.update_one(
        {"id": analysis_id},
        {"$set": {"lines": lines, "totals": totals, "updated_at": now}},
    )

    updated = await db.smr_analyses.find_one({"id": analysis_id}, {"_id": 0})
    return {
        "analysis": updated,
        "pricing_details": pricing_details,
        "materials_updated": len(pricing_details),
    }
