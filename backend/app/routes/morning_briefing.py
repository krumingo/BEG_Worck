"""
Routes - Morning Briefing (rule-based v1).
"""
from fastapi import APIRouter, Depends
from typing import Optional

from app.deps.auth import get_current_user
from app.services.morning_briefing import build_morning_briefing

router = APIRouter(tags=["Morning Briefing"])


@router.get("/morning-briefing")
async def get_morning_briefing(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    return await build_morning_briefing(user["org_id"], date)


@router.get("/morning-briefing/compact")
async def get_compact_briefing(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    full = await build_morning_briefing(user["org_id"], date)
    return {
        "date": full["date"],
        "headline": full["headline"],
        "critical_count": full["summary"]["critical_alarms"],
        "warning_count": full["summary"]["warning_alarms"],
        "top_risks": full["top_risks"][:3],
        "payments": full["payments"][:3],
    }
