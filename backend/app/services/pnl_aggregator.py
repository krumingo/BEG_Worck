"""
P&L Aggregator — Aggregates P&L across parent+children projects and computes profit attribution.
"""
from app.db import db
from app.services.project_pnl import compute_project_pnl
import logging

logger = logging.getLogger(__name__)


async def compute_aggregated_pnl(org_id: str, parent_project_id: str) -> dict:
    """Sum P&L across parent + all children."""
    children = await db.projects.find(
        {"org_id": org_id, "parent_project_id": parent_project_id},
        {"_id": 0, "id": 1, "name": 1, "code": 1},
    ).sort("code", 1).to_list(50)

    all_ids = [parent_project_id] + [c["id"] for c in children]
    pnl_results = {}
    for pid in all_ids:
        try:
            pnl_results[pid] = await compute_project_pnl(org_id, pid)
        except Exception as e:
            logger.warning(f"PnL calc failed for {pid}: {e}")
            pnl_results[pid] = _empty_pnl()

    parent_pnl = pnl_results.get(parent_project_id, _empty_pnl())

    # Build children list with contribution
    children_data = []
    for c in children:
        cpnl = pnl_results.get(c["id"], _empty_pnl())
        children_data.append({
            "id": c["id"], "name": c["name"], "code": c.get("code", ""),
            "pnl": _extract_summary(cpnl),
        })

    # Aggregate totals
    agg_budget = sum(_safe(pnl_results[pid], "budget", "total_budget") for pid in all_ids)
    agg_revenue = sum(_safe(pnl_results[pid], "revenue", "total_revenue") for pid in all_ids)
    agg_expense = sum(_safe(pnl_results[pid], "expense", "total_expense") for pid in all_ids)
    agg_profit = agg_revenue - agg_expense
    agg_margin = round(agg_profit / agg_revenue * 100, 1) if agg_revenue else 0

    # Expense breakdown
    labor = sum(_safe_exp(pnl_results[pid], "labor") for pid in all_ids)
    materials = sum(_safe_exp(pnl_results[pid], "materials") for pid in all_ids)
    overhead = sum(_safe_exp(pnl_results[pid], "overhead") for pid in all_ids)
    subcontractor = sum(_safe_exp(pnl_results[pid], "subcontractor") for pid in all_ids)

    # Add contribution_pct to children
    for cd in children_data:
        cd["contribution_pct"] = round(cd["pnl"]["gross_profit"] / agg_profit * 100, 1) if agg_profit else 0

    return {
        "parent": _extract_summary(parent_pnl),
        "children": children_data,
        "aggregated": {
            "total_budget": round(agg_budget, 2),
            "total_revenue": round(agg_revenue, 2),
            "total_expense": round(agg_expense, 2),
            "total_profit": round(agg_profit, 2),
            "margin_pct": agg_margin,
            "expense_breakdown": {
                "labor": round(labor, 2),
                "materials": round(materials, 2),
                "overhead": round(overhead, 2),
                "subcontractor": round(subcontractor, 2),
            },
        },
    }


async def compute_org_profit_attribution(org_id: str) -> dict:
    """Identifies WHY org is in profit/loss — top contributors and detractors."""
    projects = await db.projects.find(
        {"org_id": org_id, "parent_project_id": {"$in": [None, ""]}},
        {"_id": 0, "id": 1, "name": 1, "code": 1},
    ).to_list(200)

    project_pnls = []
    total_labor = total_materials = total_overhead = total_subcontractor = 0

    for p in projects:
        try:
            pnl = await compute_project_pnl(org_id, p["id"])
            summary = _extract_summary(pnl)
            summary["id"] = p["id"]
            summary["name"] = p["name"]
            summary["code"] = p.get("code", "")

            # Loss reason
            if summary["gross_profit"] < 0:
                summary["reason"] = _determine_loss_reason(pnl)
            else:
                summary["reason"] = ""

            project_pnls.append(summary)
            total_labor += _safe_exp(pnl, "labor")
            total_materials += _safe_exp(pnl, "materials")
            total_overhead += _safe_exp(pnl, "overhead")
            total_subcontractor += _safe_exp(pnl, "subcontractor")
        except Exception:
            continue

    total_revenue = sum(p["total_revenue"] for p in project_pnls)
    total_expense = sum(p["total_expense"] for p in project_pnls)
    total_profit = total_revenue - total_expense
    total_all_exp = total_labor + total_materials + total_overhead + total_subcontractor or 1

    sorted_by_profit = sorted(project_pnls, key=lambda x: x["gross_profit"], reverse=True)
    winners = [p for p in sorted_by_profit if p["gross_profit"] > 0][:3]
    losers = [p for p in reversed(sorted_by_profit) if p["gross_profit"] < 0][:3]

    return {
        "totals": {
            "revenue": round(total_revenue, 2),
            "expense": round(total_expense, 2),
            "profit": round(total_profit, 2),
            "margin_pct": round(total_profit / total_revenue * 100, 1) if total_revenue else 0,
        },
        "top_winners": winners,
        "top_losers": losers,
        "expense_breakdown": {
            "labor": {"amount": round(total_labor, 2), "pct": round(total_labor / total_all_exp * 100, 1)},
            "materials": {"amount": round(total_materials, 2), "pct": round(total_materials / total_all_exp * 100, 1)},
            "overhead": {"amount": round(total_overhead, 2), "pct": round(total_overhead / total_all_exp * 100, 1)},
            "subcontractor": {"amount": round(total_subcontractor, 2), "pct": round(total_subcontractor / total_all_exp * 100, 1)},
        },
    }


def _empty_pnl():
    return {"budget": {}, "revenue": {}, "expense": {}, "profit": {}}


def _extract_summary(pnl):
    b = pnl.get("budget", {})
    r = pnl.get("revenue", {})
    e = pnl.get("expense", {})
    p = pnl.get("profit", {})
    return {
        "total_budget": b.get("total_budget", 0) if isinstance(b, dict) else 0,
        "total_revenue": r.get("total_revenue", 0) if isinstance(r, dict) else 0,
        "total_expense": e.get("total_expense", 0) if isinstance(e, dict) else 0,
        "gross_profit": p.get("gross_profit", 0) if isinstance(p, dict) else 0,
        "margin_pct": p.get("margin_pct", 0) if isinstance(p, dict) else 0,
    }


def _safe(pnl, section, field):
    s = pnl.get(section, {})
    return s.get(field, 0) if isinstance(s, dict) else 0


def _safe_exp(pnl, category):
    """Map logical category to actual field name in compute_project_pnl response."""
    e = pnl.get("expense", {})
    if not isinstance(e, dict):
        return 0
    field_map = {
        "labor": "labor_cost",
        "materials": "material_cost",
        "subcontractor": "subcontractor_cost",
        "overhead": "overhead",
        "contract": "contract_cost",
    }
    field = field_map.get(category, category)
    return e.get(field, 0)


def _determine_loss_reason(pnl):
    e = pnl.get("expense", {})
    b = pnl.get("budget", {})
    if not isinstance(e, dict) or not isinstance(b, dict):
        return "unknown"
    labor = e.get("labor_cost", 0)
    materials = e.get("material_cost", 0)
    labor_budget = b.get("labor_budget", 0)
    materials_budget = b.get("materials_budget", 0)
    if labor_budget > 0 and labor > labor_budget * 1.2:
        return "labor_over_budget"
    if materials_budget > 0 and materials > materials_budget * 1.2:
        return "materials_over_budget"
    return "low_margin"
