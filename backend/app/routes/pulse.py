"""
Routes - Site Pulse (daily automated snapshots).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone

from app.db import db
from app.deps.auth import get_current_user
from app.permissions.money_write import (strip_money_for_non_finance, strip_pulse_for_non_finance,
                                         require_project_budget_read, require_finance_read)
from app.services.pulse_generator import generate_pulse, generate_all_pulses
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Site Pulse"])


@router.get("/sites/{site_id}/pulse")
@strip_pulse_for_non_finance   # SEC-02-C (R20-5B, R31; B-D2)
async def get_site_pulse(site_id: str, date: Optional[str] = None, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pulse = await tenant.site_pulses.find_one(
        {"org_id": user["org_id"], "site_id": site_id, "date": d}, {"_id": 0}
    )
    if not pulse:
        # Generate on-demand
        pulse = await generate_pulse(user["org_id"], site_id, d)
    return pulse


@router.get("/sites/{site_id}/pulse/range")
@strip_pulse_for_non_finance   # SEC-02-C (R20-5B, R31; B-D2)
async def get_pulse_range(site_id: str, date_from: str = "", date_to: str = "", user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    query = {"org_id": user["org_id"], "site_id": site_id}
    if date_from or date_to:
        query["date"] = {}
        if date_from: query["date"]["$gte"] = date_from
        if date_to: query["date"]["$lte"] = date_to
    items = await tenant.site_pulses.find(query, {"_id": 0}).sort("date", -1).to_list(60)
    return {"items": items, "total": len(items)}


@router.post("/sites/{site_id}/pulse/generate")
@strip_pulse_for_non_finance   # SEC-02-E (audit SEC02D-1): the answer is a pulse too
async def generate_site_pulse(
    site_id: str,
    # SEC-02-E (R20, R31): finance roles; the Technical Manager on his current member site.
    _sec02: dict = Depends(require_project_budget_read(
        "finance.site_pulse_generate.execute", module=None, resource_type="site_pulse",
        project_from="site")),
    date: Optional[str] = None, user: dict = Depends(get_current_user)):
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pulse = await generate_pulse(user["org_id"], site_id, d)
    return pulse


@router.get("/pulse/today")
@strip_pulse_for_non_finance   # SEC-02-C (R20-5B, R31; B-D2)
async def get_today_pulses(user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = await tenant.site_pulses.find(
        {"org_id": user["org_id"], "date": today}, {"_id": 0}
    ).to_list(100)
    # If no pulses yet, generate for all active projects
    if not items:
        items = await generate_all_pulses(user["org_id"], today)
    return {"items": items, "total": len(items), "date": today}


@router.post("/pulse/generate-all")
async def generate_all(
    # SEC-02-E (R20): regenerates every site's stored pulse (money) — finance roles only.
    _sec02: dict = Depends(require_finance_read(
        "finance.pulse_generate_all.execute", module=None, resource_type="site_pulse")),
    date: Optional[str] = None, user: dict = Depends(get_current_user)):
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = await generate_all_pulses(user["org_id"], d)
    return {"ok": True, "generated": len(results), "date": d}


@router.get("/pulse/summary")
@strip_money_for_non_finance   # SEC-02-B (R20-5M)
async def get_pulse_summary(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = await tenant.site_pulses.find(
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
