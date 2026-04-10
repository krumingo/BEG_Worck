"""
Service - Project P&L (Profit & Loss) computation.
Aggregates data from ALL sources into a unified financial view.
"""
from app.db import db


async def compute_project_pnl(org_id: str, project_id: str) -> dict:
    """Compute complete P&L for a single project."""

    # ── a. BUDGET (planned) ────────────────────────────────────────
    offers = await db.offers.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["Accepted", "Sent", "Draft"]}},
        {"_id": 0, "total": 1, "subtotal": 1, "status": 1},
    ).to_list(100)
    offer_total = sum(o.get("subtotal") or o.get("total") or 0 for o in offers)

    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "labor_budget": 1, "materials_budget": 1}
    ).to_list(100)
    labor_budget = sum(b.get("labor_budget", 0) for b in budgets)
    materials_budget = sum(b.get("materials_budget", 0) for b in budgets)
    total_budget = offer_total if offer_total > 0 else (labor_budget + materials_budget)

    # ── b. REVENUE ─────────────────────────────────────────────────
    invoices = await db.invoices.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "total": 1, "status": 1, "paid_amount": 1}
    ).to_list(200)
    invoiced_total = sum(i.get("total", 0) for i in invoices if i.get("status") in ["Sent", "Paid", "PartiallyPaid"])
    paid_total = sum(i.get("paid_amount", 0) or 0 for i in invoices)

    # Client acts revenue
    acts = await db.client_acts.find(
        {"org_id": org_id, "project_id": project_id, "status": "confirmed"},
        {"_id": 0, "total_amount": 1},
    ).to_list(100)
    acts_total = sum(a.get("total_amount", 0) for a in acts)

    # Additional SMR offered
    additional = await db.missing_smr.find(
        {"org_id": org_id, "project_id": project_id, "status": "offered"},
        {"_id": 0, "ai_estimated_price": 1},
    ).to_list(200)
    additional_offered = sum(m.get("ai_estimated_price") or 0 for m in additional)

    total_revenue = max(paid_total, invoiced_total)

    # ── c. LABOR COST (from work_sessions) ─────────────────────────
    # READS FROM: work_sessions — the source of truth for labor cost.
    # See /app/memory/SOURCE_OF_TRUTH.md
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None}},
        {"_id": 0, "labor_cost": 1, "duration_hours": 1, "is_overtime": 1},
    ).to_list(5000)
    labor_cost = round(sum(s.get("labor_cost", 0) for s in sessions), 2)
    labor_hours = round(sum(s.get("duration_hours", 0) for s in sessions), 2)
    overtime_cost = round(sum(s.get("labor_cost", 0) for s in sessions if s.get("is_overtime")), 2)

    # ── d. MATERIAL COST ───────────────────────────────────────────
    # From supplier invoices allocated to project
    inv_lines = await db.invoice_lines.find(
        {"org_id": org_id, "allocation_type": "project", "allocation_ref_id": project_id},
        {"_id": 0, "total_amount": 1},
    ).to_list(500)
    material_cost_invoices = round(sum(l.get("total_amount", 0) for l in inv_lines), 2)

    # From warehouse issue transactions
    issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"},
        {"_id": 0, "lines": 1},
    ).to_list(200)
    material_cost_warehouse = 0
    for txn in issues:
        for line in txn.get("lines", []):
            material_cost_warehouse += float(line.get("unit_cost", 0)) * float(line.get("qty_issued", 0))
    material_cost_warehouse = round(material_cost_warehouse, 2)

    material_cost = max(material_cost_invoices, material_cost_warehouse)

    # ── e. SUBCONTRACTOR COST ──────────────────────────────────────
    sub_payments = await db.subcontractor_payments.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["confirmed", "paid"]}},
        {"_id": 0, "amount": 1},
    ).to_list(200)
    subcontractor_cost = round(sum(p.get("amount", 0) for p in sub_payments), 2)

    # Contract payments (external workers)
    contract_docs = await db.contract_payments.find(
        {"org_id": org_id, "site_id": project_id}, {"_id": 0, "tranches": 1}
    ).to_list(200)
    contract_cost = 0
    for cd in contract_docs:
        for tr in cd.get("tranches", []):
            if tr.get("status") == "paid":
                contract_cost += tr.get("amount", 0)
    contract_cost = round(contract_cost, 2)

    # ── f. OVERHEAD ────────────────────────────────────────────────
    allocs = await db.project_overhead_allocations.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "allocated_amount": 1}
    ).to_list(50)
    overhead = round(sum(a.get("allocated_amount", 0) for a in allocs), 2)

    # ── g. TOTALS ──────────────────────────────────────────────────
    total_expense = round(labor_cost + material_cost + subcontractor_cost + contract_cost + overhead, 2)
    gross_profit = round(total_revenue - total_expense, 2)
    margin_pct = round(gross_profit / total_revenue * 100, 1) if total_revenue > 0 else 0
    budget_vs_actual = round(total_budget - total_expense, 2)

    status = "profitable" if gross_profit > 0 else ("break_even" if gross_profit == 0 else "loss")

    return {
        "project_id": project_id,
        "budget": {
            "offer_total": round(offer_total, 2),
            "labor_budget": round(labor_budget, 2),
            "materials_budget": round(materials_budget, 2),
            "total_budget": round(total_budget, 2),
        },
        "revenue": {
            "invoiced_total": round(invoiced_total, 2),
            "paid_total": round(paid_total, 2),
            "acts_total": round(acts_total, 2),
            "additional_offered": round(additional_offered, 2),
            "total_revenue": round(total_revenue, 2),
        },
        "expense": {
            "labor_cost": labor_cost,
            "labor_hours": labor_hours,
            "overtime_cost": overtime_cost,
            "material_cost": material_cost,
            "subcontractor_cost": subcontractor_cost,
            "contract_cost": contract_cost,
            "overhead": overhead,
            "total_expense": total_expense,
        },
        "profit": {
            "gross_profit": gross_profit,
            "margin_pct": margin_pct,
            "budget_vs_actual": budget_vs_actual,
            "status": status,
        },
    }


async def compute_pnl_trend(org_id: str, project_id: str, months: int = 6) -> list:
    """Monthly P&L trend for the last N months."""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    trend = []

    for i in range(months - 1, -1, -1):
        dt = now - timedelta(days=30 * i)
        m_start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if m_start.month == 12:
            m_end = m_start.replace(year=m_start.year + 1, month=1)
        else:
            m_end = m_start.replace(month=m_start.month + 1)

        ms = m_start.isoformat()
        me = m_end.isoformat()
        label = m_start.strftime("%Y-%m")

        # Revenue (invoices issued in this month)
        inv = await db.invoices.find(
            {"org_id": org_id, "project_id": project_id,
             "created_at": {"$gte": ms, "$lt": me}},
            {"_id": 0, "total": 1, "status": 1},
        ).to_list(100)
        revenue = round(sum(i.get("total", 0) for i in inv if i.get("status") in ["Sent", "Paid", "PartiallyPaid"]), 2)

        # Expense (work sessions in this month)
        sess = await db.work_sessions.find(
            {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None},
             "started_at": {"$gte": ms, "$lt": me}},
            {"_id": 0, "labor_cost": 1},
        ).to_list(1000)
        expense = round(sum(s.get("labor_cost", 0) for s in sess), 2)

        profit = round(revenue - expense, 2)
        trend.append({"month": label, "revenue": revenue, "expense": expense, "profit": profit})

    return trend
