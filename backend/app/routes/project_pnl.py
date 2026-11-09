"""
Routes - Project P&L (Profit & Loss).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from app.db import db
from app.deps.auth import get_current_user
from app.permissions.money_write import require_finance_read
from app.services.project_pnl import compute_project_pnl, compute_pnl_trend
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Project P&L"])


@router.get("/projects/{project_id}/pnl")
async def get_project_pnl(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_pnl.read", module=None, resource_type="project_pnl")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(get_current_user)):
    # SEC-02 (R20-2): the finance roles read every project; the former project_team
    # check (can_access_project) only ever let a MEMBER of any role through.
    return await compute_project_pnl(user["org_id"], project_id)


@router.get("/projects/{project_id}/pnl/summary")
async def get_pnl_summary(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_pnl_summary.read", module=None, resource_type="project_pnl_summary")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(get_current_user)):
    # SEC-02 (R20-2): the finance roles read every project; the former project_team
    # check (can_access_project) only ever let a MEMBER of any role through.
    pnl = await compute_project_pnl(user["org_id"], project_id)
    return {
        "project_id": project_id,
        "total_budget": pnl["budget"]["total_budget"],
        "total_revenue": pnl["revenue"]["total_revenue"],
        "total_invoiced": pnl["revenue"]["invoiced_total"],
        "total_invoiced_net": pnl["revenue"]["invoiced_net"],
        "total_received": pnl["revenue"]["paid_total"],
        "output_vat": pnl["vat"]["output_vat"],
        "input_vat": pnl["vat"]["input_vat"],
        "vat_payable": pnl["vat"]["vat_payable"],
        "total_expense": pnl["expense"]["total_expense"],
        "material_cost": pnl["expense"]["material_cost"],
        # 5C-C21 F-12 — project write-off, its own „фира" line (in total_expense once).
        "material_waste_cost": pnl["expense"]["material_waste_cost"],
        "gross_profit": pnl["profit"]["gross_profit"],
        "margin_pct": pnl["profit"]["margin_pct"],
        "status": pnl["profit"]["status"],
    }


@router.get("/projects/{project_id}/pnl/breakdown")
async def get_pnl_breakdown(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_pnl_breakdown.read", module=None, resource_type="project_pnl_breakdown")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(get_current_user)):
    # SEC-02 (R20-2): the finance roles read every project; the former project_team
    # check (can_access_project) only ever let a MEMBER of any role through.
    pnl = await compute_project_pnl(user["org_id"], project_id)
    return {"budget": pnl["budget"], "revenue": pnl["revenue"], "expense": pnl["expense"],
            "profit": pnl["profit"], "warehouse_cost_basis": pnl["warehouse_cost_basis"]}


@router.get("/projects/{project_id}/pnl/trend")
async def get_pnl_trend(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_pnl_trend.read", module=None, resource_type="project_pnl_trend")),  # SEC-02 (R20-2): before any read
    months: int = 6, user: dict = Depends(get_current_user)):
    # SEC-02 (R20-2): see get_project_pnl.
    return {"months": await compute_pnl_trend(user["org_id"], project_id, months)}


@router.get("/org/pnl-overview")
async def get_org_pnl_overview(
    _sec02: dict = Depends(require_finance_read(
        "finance.org_pnl_overview.read", module=None, resource_type="org_pnl_overview")),  # SEC-02 (R20-1): before any read
    user: dict = Depends(get_current_user)):
    """P&L overview for all projects in the organization."""
    tenant = _tenant(user)
    org_id = user["org_id"]
    # FG-278: the SAME project scope as every company-result reader (every project,
    # every status) — so totals, company losses and final_profit agree with /org/pnl-attribution
    from app.services.pnl_aggregator import COMPANY_RESULT_SCOPE, company_result_projects
    projects = await company_result_projects(
        tenant, org_id, {"_id": 0, "id": 1, "name": 1, "code": 1, "status": 1})

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
    # Q007 / FG-271: company losses — a separate line of the company result, never a project's
    from app.services.invoice_corrections import company_losses_block
    losses = await company_losses_block(tenant)
    totals["company_losses"] = losses["amount"]
    totals["final_profit"] = round(totals["profit"] - losses["amount"], 2)

    return {"projects": results, "totals": totals, "company_losses": losses, "scope": COMPANY_RESULT_SCOPE}


# ── Aggregated PnL + Profit Attribution ──

@router.get("/projects/{project_id}/pnl/aggregated")
async def get_aggregated_pnl(
    project_id: str,
    _sec02: dict = Depends(require_finance_read(
        "finance.project_pnl_aggregated.read", module=None, resource_type="project_pnl_aggregated")),  # SEC-02 (R20-2): before any read
    user: dict = Depends(get_current_user)):
    from app.services.pnl_aggregator import compute_aggregated_pnl
    return await compute_aggregated_pnl(user["org_id"], project_id)


@router.get("/org/pnl-attribution")
async def get_pnl_attribution(user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "Accountant"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin/Owner/Accountant only")
    from app.services.pnl_aggregator import compute_org_profit_attribution
    return await compute_org_profit_attribution(user["org_id"])

