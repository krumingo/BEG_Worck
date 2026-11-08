"""
Routes - Expected vs Actual comparison.
"""
from fastapi import APIRouter, Depends, Request
from typing import Optional

from app.deps.auth import get_current_user
from app.permissions.money_write import (require_project_budget_read, money_values_visible,
                                         without_keys)
from app.permissions.finance_read import EXPECTED_ACTUAL_CLIENT_PRICE_FIELDS
from app.services.expected_actual import build_expected_actual

router = APIRouter(tags=["Expected vs Actual"])


async def _budget_view(request: Request, user: dict, full: dict, project_id: str,
                       date_from: Optional[str] = None, date_to: Optional[str] = None) -> dict:
    """SEC-02 (R20-2B). The Technical Manager sees budget + spent + remaining per SMR
    (activity_budgets.labor_budget vs the work-session cost) — never client prices. The
    SMR-group and location amounts are sums of smr_analyses final_total (the price to
    the client, with markup and risk), so for a caller without the finance right they
    are removed; hours and missing-SMR counts stay."""
    if await money_values_visible(request, user):
        return full
    out = dict(full)
    out["groups"] = without_keys(full["groups"], EXPECTED_ACTUAL_CLIENT_PRICE_FIELDS)
    out["locations"] = without_keys(full["locations"], EXPECTED_ACTUAL_CLIENT_PRICE_FIELDS)
    out["summary"] = dict(full["summary"], biggest_overrun_group=None)
    out["client_price_fields_hidden"] = True
    # SEC-02-D (R31, audit SEC02C-1): nothing that gives one worker's pay.
    from app.permissions.money_write import r31_budget_view
    # FG-63: workers counted from the same source (ended work sessions) and window.
    return await r31_budget_view(user, project_id, out, source="sessions",
                                 date_from=date_from, date_to=date_to)


@router.get("/projects/{project_id}/expected-actual")
async def get_expected_actual(
    project_id: str,
    request: Request,
    _sec02: dict = Depends(require_project_budget_read(
        "finance.project_budget_vs_actual.read", module=None, resource_type="project_budget_vs_actual")),  # SEC-02 (R20-2B): before any read
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    # SEC-02-E (audit SEC02D-1 b; R31): a date window lets two calls differ by one day's
    # labor — one worker's pay. Without the finance right the view is the whole project.
    if not await money_values_visible(request, user):
        date_from = date_to = None
    full = await build_expected_actual(user["org_id"], project_id, date_from, date_to)
    return await _budget_view(request, user, full, project_id, date_from, date_to)


@router.get("/projects/{project_id}/expected-actual/compact")
async def get_compact_expected_actual(
    project_id: str,
    request: Request,
    _sec02: dict = Depends(require_project_budget_read(
        "finance.project_budget_vs_actual_compact.read", module=None, resource_type="project_budget_vs_actual_compact")),  # SEC-02 (R20-2B): before any read
    user: dict = Depends(get_current_user)):
    full = await build_expected_actual(user["org_id"], project_id)
    groups = sorted(full["groups"], key=lambda x: x.get("variance_cost", 0), reverse=True)[:3]
    acts = sorted(full["activities"], key=lambda x: x["variance_cost"], reverse=True)[:3]
    view = await _budget_view(request, user, dict(full, groups=groups, activities=acts,
                                                  locations=full["locations"][:3]), project_id)
    return {
        "summary": view["summary"],
        "top_overruns": {
            "activities": view["activities"],   # SEC-02-D: the view, not the full rows
            "groups": view["groups"],
            "locations": view["locations"],
        },
    }
