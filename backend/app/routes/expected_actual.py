"""
Routes - Expected vs Actual comparison.
"""
from fastapi import APIRouter, Depends
from typing import Optional

from app.deps.auth import get_current_user
from app.services.expected_actual import build_expected_actual

router = APIRouter(tags=["Expected vs Actual"])


@router.get("/projects/{project_id}/expected-actual")
async def get_expected_actual(
    project_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    return await build_expected_actual(user["org_id"], project_id, date_from, date_to)


@router.get("/projects/{project_id}/expected-actual/compact")
async def get_compact_expected_actual(project_id: str, user: dict = Depends(get_current_user)):
    full = await build_expected_actual(user["org_id"], project_id)
    return {
        "summary": full["summary"],
        "top_overruns": {
            "activities": sorted(full["activities"], key=lambda x: x["variance_cost"], reverse=True)[:3],
            "groups": sorted(full["groups"], key=lambda x: x.get("variance_cost", 0), reverse=True)[:3],
            "locations": full["locations"][:3],
        },
    }
