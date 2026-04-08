"""
Routes - Project P&L (Profit & Loss).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from app.db import db
from app.deps.auth import get_current_user, can_access_project
from app.services.project_pnl import compute_project_pnl, compute_pnl_trend

router = APIRouter(tags=["Project P&L"])


@router.get("/projects/{project_id}/pnl")
async def get_project_pnl(project_id: str, user: dict = Depends(get_current_user)):
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return await compute_project_pnl(user["org_id"], project_id)


@router.get("/projects/{project_id}/pnl/summary")
async def get_pnl_summary(project_id: str, user: dict = Depends(get_current_user)):
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    pnl = await compute_project_pnl(user["org_id"], project_id)
    return {
        "project_id": project_id,
        "total_budget": pnl["budget"]["total_budget"],
        "total_revenue": pnl["revenue"]["total_revenue"],
        "total_expense": pnl["expense"]["total_expense"],
        "gross_profit": pnl["profit"]["gross_profit"],
        "margin_pct": pnl["profit"]["margin_pct"],
        "status": pnl["profit"]["status"],
    }


@router.get("/projects/{project_id}/pnl/breakdown")
async def get_pnl_breakdown(project_id: str, user: dict = Depends(get_current_user)):
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    pnl = await compute_project_pnl(user["org_id"], project_id)
    return {"budget": pnl["budget"], "revenue": pnl["revenue"], "expense": pnl["expense"], "profit": pnl["profit"]}


@router.get("/projects/{project_id}/pnl/trend")
async def get_pnl_trend(project_id: str, months: int = 6, user: dict = Depends(get_current_user)):
    if not await can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return {"months": await compute_pnl_trend(user["org_id"], project_id, months)}


@router.get("/org/pnl-overview")
async def get_org_pnl_overview(user: dict = Depends(get_current_user)):
    """P&L overview for all projects in the organization."""
    org_id = user["org_id"]
    projects = await db.projects.find(
        {"org_id": org_id, "status": {"$in": ["Active", "Draft", "Paused"]}},
        {"_id": 0, "id": 1, "name": 1, "code": 1, "status": 1},
    ).to_list(100)

    results = []
    totals = {"budget": 0, "revenue": 0, "expense": 0, "profit": 0}

    for p in projects:
        pnl = await compute_project_pnl(org_id, p["id"])
        entry = {
            "id": p["id"],
            "name": p["name"],
            "code": p.get("code", ""),
            "project_status": p.get("status", ""),
            "budget": pnl["budget"]["total_budget"],
            "revenue": pnl["revenue"]["total_revenue"],
            "expense": pnl["expense"]["total_expense"],
            "profit": pnl["profit"]["gross_profit"],
            "margin_pct": pnl["profit"]["margin_pct"],
            "status": pnl["profit"]["status"],
        }
        results.append(entry)
        totals["budget"] += entry["budget"]
        totals["revenue"] += entry["revenue"]
        totals["expense"] += entry["expense"]
        totals["profit"] += entry["profit"]

    totals = {k: round(v, 2) for k, v in totals.items()}
    totals["margin_pct"] = round(totals["profit"] / totals["revenue"] * 100, 1) if totals["revenue"] > 0 else 0

    return {"projects": results, "totals": totals}
