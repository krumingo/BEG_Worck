"""
Routes - Site Pulse (daily automated snapshots).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone

from app.db import db
from app.deps.auth import get_current_user
from app.services.pulse_generator import generate_pulse, generate_all_pulses

router = APIRouter(tags=["Site Pulse"])


@router.get("/sites/{site_id}/pulse")
async def get_site_pulse(site_id: str, date: Optional[str] = None, user: dict = Depends(get_current_user)):
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pulse = await db.site_pulses.find_one(
        {"org_id": user["org_id"], "site_id": site_id, "date": d}, {"_id": 0}
    )
    if not pulse:
        # Generate on-demand
        pulse = await generate_pulse(user["org_id"], site_id, d)
    return pulse


@router.get("/sites/{site_id}/pulse/range")
async def get_pulse_range(site_id: str, date_from: str = "", date_to: str = "", user: dict = Depends(get_current_user)):
    query = {"org_id": user["org_id"], "site_id": site_id}
    if date_from or date_to:
        query["date"] = {}
        if date_from: query["date"]["$gte"] = date_from
        if date_to: query["date"]["$lte"] = date_to
    items = await db.site_pulses.find(query, {"_id": 0}).sort("date", -1).to_list(60)
    return {"items": items, "total": len(items)}


@router.post("/sites/{site_id}/pulse/generate")
async def generate_site_pulse(site_id: str, date: Optional[str] = None, user: dict = Depends(get_current_user)):
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pulse = await generate_pulse(user["org_id"], site_id, d)
    return pulse


@router.get("/pulse/today")
async def get_today_pulses(user: dict = Depends(get_current_user)):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = await db.site_pulses.find(
        {"org_id": user["org_id"], "date": today}, {"_id": 0}
    ).to_list(100)
    # If no pulses yet, generate for all active projects
    if not items:
        items = await generate_all_pulses(user["org_id"], today)
    return {"items": items, "total": len(items), "date": today}


@router.post("/pulse/generate-all")
async def generate_all(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = await generate_all_pulses(user["org_id"], d)
    return {"ok": True, "generated": len(results), "date": d}


@router.get("/pulse/summary")
async def get_pulse_summary(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = await db.site_pulses.find(
        {"org_id": user["org_id"], "date": d}, {"_id": 0}
    ).to_list(100)

    total_workers = sum(p.get("total_workers", 0) for p in items)
    total_hours = round(sum(p.get("total_hours", 0) for p in items), 2)
    total_labor = round(sum(p.get("total_labor_cost", 0) for p in items), 2)
    total_material = round(sum(p.get("total_material_cost", 0) for p in items), 2)
    all_alerts = []
    for p in items:
        for a in p.get("alerts", []):
            all_alerts.append({**a, "site_name": p.get("site_name", ""), "site_id": p.get("site_id")})

    return {
        "date": d, "sites_count": len(items),
        "total_workers": total_workers, "total_hours": total_hours,
        "total_labor_cost": total_labor, "total_material_cost": total_material,
        "alerts_count": len(all_alerts),
        "alerts": all_alerts[:20],
    }
