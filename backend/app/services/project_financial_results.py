"""
Service - Project Financial Results.
Three distinct results: Cash, Operating, Fully Loaded.

Cash = money in - money out (liquidity)
Operating = earned revenue - direct costs (no overhead)
Fully Loaded = operating - allocated overhead - insurance burden (real profit)
"""
from app.db import db
from app.services.resource_model import (
    get_resource_config, classify_worker, compute_subcontractor_burden,
    DEFAULT_INSURANCE_RATE, DEFAULT_BURDEN_WEIGHTS,
)
from app.services.resolve_hourly_rate import resolve_worker_hourly_rate


async def compute_financial_results(org_id: str, project_id: str) -> dict:
    config = await get_resource_config(org_id)
    insurance_rate = config.get("insurance_rate", DEFAULT_INSURANCE_RATE)
    warnings = []

    # ══════════════════════════════════════════════════════════════
    # A) CASH RESULT
    # ══════════════════════════════════════════════════════════════

    # Cash in: actual payments received
    invoices = await db.invoices.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "total": 1, "paid_amount": 1, "status": 1},
    ).to_list(500)
    cash_in = round(sum(i.get("paid_amount") or 0 for i in invoices), 2)

    # Cash out: actual payments made (payroll paid + supplier paid + contract paid)
    # Payroll: sum labor_cost from approved work_sessions (reported/operational)
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "site_id": project_id, "ended_at": {"$ne": None}, "is_flagged": {"$ne": True}},
        {"_id": 0, "labor_cost": 1, "duration_hours": 1, "hourly_rate_at_date": 1, "worker_id": 1},
    ).to_list(5000)
    reported_labor = round(sum(s.get("labor_cost", 0) for s in sessions), 2)

    # ── PAID LABOR LAYER (from payroll_payment_allocations) ──
    paid_allocs = await db.payroll_payment_allocations.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "allocated_gross_labor": 1, "allocated_hours": 1,
         "worker_id": 1, "worker_name": 1, "week_start": 1, "week_end": 1,
         "payroll_batch_id": 1},
    ).to_list(500)
    paid_labor_expense = round(sum(a.get("allocated_gross_labor", 0) for a in paid_allocs), 2)
    paid_labor_hours = round(sum(a.get("allocated_hours", 0) for a in paid_allocs), 1)

    # Determine labor_expense_basis
    if paid_labor_expense > 0 and reported_labor > 0:
        labor_expense_basis = "mixed"
    elif paid_labor_expense > 0:
        labor_expense_basis = "paid"
    else:
        labor_expense_basis = "reported"

    # Cash result uses ONLY paid labor — no fallback to reported
    # reported labor is operational value, NOT cash out
    effective_cash_labor = paid_labor_expense

    # Supplier/material payments
    issues = await db.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"},
        {"_id": 0, "lines": 1},
    ).to_list(500)
    paid_materials = 0
    for t in issues:
        for ln in t.get("lines", []):
            paid_materials += float(ln.get("unit_cost", 0)) * float(ln.get("qty_issued", 0))
    paid_materials = round(paid_materials, 2)

    # Subcontractor payments
    sub_payments = await db.subcontractor_payments.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["confirmed", "paid"]}},
        {"_id": 0, "amount": 1},
    ).to_list(200)
    paid_subcontractors = round(sum(p.get("amount", 0) for p in sub_payments), 2)

    # Contract payments (external workers)
    contract_docs = await db.contract_payments.find(
        {"org_id": org_id, "site_id": project_id}, {"_id": 0, "tranches": 1}
    ).to_list(200)
    paid_contracts = 0
    for cd in contract_docs:
        for tr in cd.get("tranches", []):
            if tr.get("status") == "paid":
                paid_contracts += tr.get("amount", 0)
    paid_contracts = round(paid_contracts, 2)

    cash_out = round(effective_cash_labor + paid_materials + paid_subcontractors + paid_contracts, 2)

    # Unpaid approved labor
    unpaid_approved = round(max(0, reported_labor - paid_labor_expense), 2) if reported_labor > paid_labor_expense else 0

    cash_result = {
        "cash_in": cash_in,
        "cash_out": cash_out,
        "cash_balance": round(cash_in - cash_out, 2),
        "breakdown": {
            "paid_labor": effective_cash_labor,
            "paid_materials": paid_materials,
            "paid_subcontractors": paid_subcontractors,
            "paid_contracts": paid_contracts,
        },
    }

    # ── LABOR SUMMARY ──
    labor_summary = {
        "reported_labor_value": reported_labor,
        "paid_labor_expense": paid_labor_expense,
        "paid_labor_hours": paid_labor_hours,
        "unpaid_approved_labor": unpaid_approved,
        "labor_expense_basis": labor_expense_basis,
        "allocation_count": len(paid_allocs),
    }
    if unpaid_approved > 0:
        warnings.append(f"Одобрен, но неплатен труд: {unpaid_approved} EUR")
    if paid_labor_expense > 0 and reported_labor == 0:
        warnings.append("Има платен труд, но няма отчетен труд от work_sessions")
    if reported_labor > 0 and paid_labor_expense == 0:
        warnings.append(f"Има отчетен труд ({reported_labor} EUR), който още не е платен — не е включен в cash out")

    # ══════════════════════════════════════════════════════════════
    # B) OPERATING RESULT
    # ══════════════════════════════════════════════════════════════

    # Earned revenue: invoiced (not just advances/payments)
    earned_revenue = round(sum(
        i.get("total", 0) for i in invoices
        if i.get("status") in ["Sent", "Paid", "PartiallyPaid"]
    ), 2)
    revenue_mode = "invoiced"
    if earned_revenue == 0 and cash_in > 0:
        earned_revenue = cash_in
        revenue_mode = "cash"
        warnings.append("Няма фактурирани суми — използва се cash basis")

    # Direct labor: clean labor (hours × rate) from approved sessions
    # Resolve rates for workers with 0 stored rate
    rate_cache = {}
    direct_labor = 0
    direct_labor_insurance = 0
    missing_rate_workers = []

    for s in sessions:
        wid = s.get("worker_id", "")
        hours = s.get("duration_hours", 0)
        rate = s.get("hourly_rate_at_date", 0)

        if rate == 0 and wid:
            if wid not in rate_cache:
                rate_cache[wid] = await resolve_worker_hourly_rate(wid, org_id)
            resolved = rate_cache[wid]
            rate = resolved["rate"]
            if resolved["missing_rate"]:
                missing_rate_workers.append(wid)

        clean = round(hours * rate, 2)
        ins = round(clean * insurance_rate, 2)
        direct_labor += clean
        direct_labor_insurance += ins

    direct_labor = round(direct_labor, 2)
    direct_labor_insurance = round(direct_labor_insurance, 2)

    operating_cost = round(direct_labor + paid_materials + paid_subcontractors + paid_contracts, 2)
    operating_result_val = round(earned_revenue - operating_cost, 2)
    operating_margin = round(operating_result_val / earned_revenue * 100, 1) if earned_revenue > 0 else 0

    operating_result = {
        "earned_revenue": earned_revenue,
        "revenue_mode": revenue_mode,
        "direct_labor": direct_labor,
        "materials": paid_materials,
        "subcontractor_direct": paid_subcontractors,
        "contract_direct": paid_contracts,
        "operating_cost": operating_cost,
        "operating_result": operating_result_val,
        "operating_margin_pct": operating_margin,
    }

    # ══════════════════════════════════════════════════════════════
    # C) FULLY LOADED RESULT
    # ══════════════════════════════════════════════════════════════

    # Insurance burden on direct labor
    insurance_burden = direct_labor_insurance

    # Overhead allocation from pools
    allocs = await db.project_overhead_allocations.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "allocated_amount": 1, "pool": 1},
    ).to_list(50)
    overhead_by_pool = {"administration": 0, "base_warehouse": 0, "transport": 0, "general": 0}
    for a in allocs:
        pool = a.get("pool", "general")
        overhead_by_pool[pool] = overhead_by_pool.get(pool, 0) + a.get("allocated_amount", 0)
    total_overhead_alloc = round(sum(overhead_by_pool.values()), 2)

    # If no formal allocations, estimate from realtime overhead
    if total_overhead_alloc == 0:
        try:
            from app.services.overhead_realtime import compute_realtime_overhead
            from datetime import datetime, timezone
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            oh_data = await compute_realtime_overhead(org_id, month)
            for bp in oh_data.get("by_project", []):
                if bp.get("project_id") == project_id:
                    total_overhead_alloc = bp.get("overhead_loaded", 0)
                    overhead_by_pool["general"] = total_overhead_alloc
                    break
        except Exception:
            pass

    # Subcontractor burden
    weights = config.get("burden_weights", DEFAULT_BURDEN_WEIGHTS)
    sub_burden = round(paid_subcontractors * weights.get("subcontractor_company", 0.3), 2)
    contract_burden = round(paid_contracts * weights.get("subcontractor_crew", 0.6), 2)

    fully_loaded_cost = round(
        operating_cost + insurance_burden + total_overhead_alloc + sub_burden + contract_burden, 2
    )
    fully_loaded_result_val = round(earned_revenue - fully_loaded_cost, 2)
    fully_loaded_margin = round(fully_loaded_result_val / earned_revenue * 100, 1) if earned_revenue > 0 else 0

    fully_loaded_result = {
        "operating_result": operating_result_val,
        "insurance_burden": insurance_burden,
        "overhead_allocation": total_overhead_alloc,
        "overhead_by_pool": {k: round(v, 2) for k, v in overhead_by_pool.items()},
        "subcontractor_burden": sub_burden,
        "contract_burden": contract_burden,
        "fully_loaded_cost": fully_loaded_cost,
        "fully_loaded_result": fully_loaded_result_val,
        "fully_loaded_margin_pct": fully_loaded_margin,
    }

    # Warnings
    if missing_rate_workers:
        unique = set(missing_rate_workers)
        warnings.append(f"{len(unique)} работник(а) без ставка — труд = 0 за тях")
    if total_overhead_alloc == 0:
        warnings.append("Няма формални overhead allocations — fully loaded може да е непълен")

    return {
        "project_id": project_id,
        "cash": cash_result,
        "operating": operating_result,
        "fully_loaded": fully_loaded_result,
        "labor": labor_summary,
        "warnings": warnings,
    }
