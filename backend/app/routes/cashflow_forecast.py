"""
Routes - Cash Flow Forecast v1.
"""
from fastapi import APIRouter, Depends
from typing import Optional

from app.deps.auth import get_current_user
from app.permissions.money_write import require_finance_read
from app.services.cashflow_forecast import build_cashflow_forecast

router = APIRouter(tags=["Cash Flow"])


@router.get("/cashflow/forecast")
async def get_cashflow_forecast(
    _sec02: dict = Depends(require_finance_read(
        "finance.cashflow_forecast.read", module=None, resource_type="cashflow_forecast")),  # SEC-02 (R20-1): before any read
    days: int = 30, start_date: Optional[str] = None, user: dict = Depends(get_current_user)):
    return await build_cashflow_forecast(user["org_id"], days, start_date)


@router.get("/cashflow/forecast/compact")
async def get_compact_forecast(
    _sec02: dict = Depends(require_finance_read(
        "finance.cashflow_forecast_compact.read", module=None, resource_type="cashflow_forecast_compact")),  # SEC-02 (R20-1): before any read
    days: int = 30, user: dict = Depends(get_current_user)):
    full = await build_cashflow_forecast(user["org_id"], days)
    return {
        "warning_level": full["summary"]["warning_level"],
        "headline": full["headline"],
        "net_forecast": full["summary"]["net_forecast"],
        "total_incoming": full["summary"]["total_incoming"],
        "total_outgoing": full["summary"]["total_outgoing"],
        "overdue_receivables": full["summary"]["overdue_receivables"],
        "lowest_cash_day": full["summary"]["lowest_cash_day"],
        "top_incoming": full["incoming"][:3],
        "top_outgoing": full["outgoing"][:3],
    }
