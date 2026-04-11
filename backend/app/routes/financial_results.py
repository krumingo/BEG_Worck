"""
Routes - Project Financial Results (Cash / Operating / Fully Loaded).
Read-only calculation layer.
"""
from fastapi import APIRouter, Depends

from app.deps.auth import get_current_user
from app.services.project_financial_results import compute_financial_results

router = APIRouter(tags=["Financial Results"])


@router.get("/projects/{project_id}/financial-results")
async def get_financial_results(project_id: str, user: dict = Depends(get_current_user)):
    """Three financial results: Cash, Operating, Fully Loaded."""
    return await compute_financial_results(user["org_id"], project_id)


@router.get("/projects/{project_id}/financial-results/breakdown")
async def get_breakdown(project_id: str, user: dict = Depends(get_current_user)):
    """Detailed breakdown of all cost components."""
    data = await compute_financial_results(user["org_id"], project_id)
    return {
        "cash_breakdown": data["cash"]["breakdown"],
        "operating_breakdown": {
            "revenue": data["operating"]["earned_revenue"],
            "revenue_mode": data["operating"]["revenue_mode"],
            "labor": data["operating"]["direct_labor"],
            "materials": data["operating"]["materials"],
            "subcontractors": data["operating"]["subcontractor_direct"],
            "contracts": data["operating"]["contract_direct"],
        },
        "loaded_breakdown": {
            "insurance": data["fully_loaded"]["insurance_burden"],
            "overhead_pools": data["fully_loaded"]["overhead_by_pool"],
            "sub_burden": data["fully_loaded"]["subcontractor_burden"],
            "contract_burden": data["fully_loaded"]["contract_burden"],
        },
        "warnings": data["warnings"],
    }
