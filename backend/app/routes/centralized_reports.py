"""
Routes - Centralized Reports Model.
Single source → three projections: Activities, Personnel, Finance.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.deps.auth import get_current_user
from app.services.centralized_reports import build_centralized_reports

router = APIRouter(tags=["Centralized Reports"])


@router.get("/projects/{project_id}/centralized-reports")
async def get_centralized_reports(project_id: str, user: dict = Depends(get_current_user)):
    """Full centralized reports: activities + personnel + finance from one source."""
    return await build_centralized_reports(user["org_id"], project_id)


@router.get("/projects/{project_id}/centralized-reports/activities")
async def get_activities_projection(project_id: str, user: dict = Depends(get_current_user)):
    data = await build_centralized_reports(user["org_id"], project_id)
    return {"activities": data["activities"], "entries_count": data["entries_count"]}


@router.get("/projects/{project_id}/centralized-reports/personnel")
async def get_personnel_projection(project_id: str, user: dict = Depends(get_current_user)):
    data = await build_centralized_reports(user["org_id"], project_id)
    return {"personnel": data["personnel"], "entries_count": data["entries_count"]}


@router.get("/projects/{project_id}/centralized-reports/finance")
async def get_finance_projection(project_id: str, user: dict = Depends(get_current_user)):
    data = await build_centralized_reports(user["org_id"], project_id)
    return {"finance": data["finance"], "entries_count": data["entries_count"]}
