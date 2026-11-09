"""
Routes - Morning Briefing (rule-based v1).
"""
from fastapi import APIRouter, Depends, Request
from typing import Optional

from app.deps.auth import get_current_user
from app.permissions.money_write import strip_money_for_non_finance, money_values_visible
from app.services.morning_briefing import build_morning_briefing

router = APIRouter(tags=["Morning Briefing"])


async def _band_user(request: Request, user: dict):
    """SEC-02-G (audit SEC71-05; R31): the caller, when he has no finance right — then the
    briefing has no budget band of a single-paid-worker site."""
    return None if await money_values_visible(request, user) else user


@router.get("/morning-briefing")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def get_morning_briefing(request: Request, date: Optional[str] = None,
                               user: dict = Depends(get_current_user)):
    return await build_morning_briefing(user["org_id"], date, band_user=await _band_user(request, user))


@router.get("/morning-briefing/compact")
@strip_money_for_non_finance   # SEC-02-A (R20-5M, D1)
async def get_compact_briefing(request: Request, date: Optional[str] = None,
                               user: dict = Depends(get_current_user)):
    full = await build_morning_briefing(user["org_id"], date, band_user=await _band_user(request, user))
    return {
        "date": full["date"],
        "headline": full["headline"],
        "critical_count": full["summary"]["critical_alarms"],
        "warning_count": full["summary"]["warning_alarms"],
        "top_risks": full["top_risks"][:3],
        "payments": full["payments"][:3],
    }
