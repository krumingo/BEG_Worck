"""
Routes - Centralized Reports Model.
Single source → three projections: Activities, Personnel, Finance.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps.auth import get_current_user
from app.permissions.money_write import require_finance_read, require_project_budget_read
from app.services.centralized_reports import build_centralized_reports

router = APIRouter(tags=["Centralized Reports"])


@router.get("/projects/{project_id}/centralized-reports")
async def get_centralized_reports(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_centralized_report.read", module=None, resource_type="project_centralized_report")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(get_current_user)):
    """Full centralized reports: activities + personnel + finance from one source."""
    return await build_centralized_reports(user["org_id"], project_id)


@router.get("/projects/{project_id}/centralized-reports/activities")
async def get_activities_projection(
    project_id: str,
    request: Request,
    _sec02: dict = Depends(require_project_budget_read(
        "finance.project_budget_burn.read", module=None, resource_type="project_budget_burn")),  # SEC-02 (R20-2B): before any read
    user: dict = Depends(get_current_user)):
    data = await build_centralized_reports(user["org_id"], project_id, with_entries=True)
    out = {"activities": data["activities"], "entries_count": data["entries_count"]}
    # SEC-02-D (R31, audit SEC02C-1): the Technical Manager's view gives no one's pay.
    from app.permissions.money_write import money_values_visible, r31_budget_view
    if not await money_values_visible(request, user):
        out = await r31_budget_view(user, project_id, out, source="centralized",  # FG-63
                                    entries=data["entries"])  # FG-74: the same pay
    return out


@router.get("/projects/{project_id}/centralized-reports/personnel")
async def get_personnel_projection(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_centralized_personnel.read", module=None, resource_type="project_centralized_personnel")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(get_current_user)):
    data = await build_centralized_reports(user["org_id"], project_id)
    return {"personnel": data["personnel"], "entries_count": data["entries_count"]}


@router.get("/projects/{project_id}/centralized-reports/finance")
async def get_finance_projection(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_centralized_finance.read", module=None, resource_type="project_centralized_finance")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(get_current_user)):
    data = await build_centralized_reports(user["org_id"], project_id)
    return {"finance": data["finance"], "entries_count": data["entries_count"]}
