"""
Service - Project P&L (Profit & Loss) computation.
Aggregates data from ALL sources into a unified financial view.
"""
from app.db import db
from app.tenancy.data_access import TenantData
from app.services.labor_cost import project_labor_cost
from app.services.payment_state import active_payments


# FG-530: the statuses the P&L used for revenue / output VAT (kept for the VAT figure).
REVENUE_STATUSES = ("Sent", "Paid", "PartiallyPaid")
# FG-695 (R86): ISSUED = every issued, not cancelled status — Overdue included. Since R86 the
# issued amount is the INVOICED amount ("фактурирано"), shown apart, not the revenue.
NOT_ISSUED_STATUSES = ("Draft", "Cancelled")
PROFORMA = "Proforma"
CREDIT_NOTE = "CreditNote"


def _net(i) -> float:
    return float((i.get("subtotal") if i.get("subtotal") is not None else i.get("total", 0)) or 0)


def _kind(i) -> str:
    return i.get("kind") or "Invoice"


def _is_proforma(i) -> bool:
    return _kind(i) == PROFORMA


def is_issued(i) -> bool:
    """FG-695: an issued document — not a draft, not cancelled (Overdue included)."""
    return i.get("status") not in NOT_ISSUED_STATUSES


def issued_revenue_net(invoices) -> float:
    """Net INVOICED amount of Issued invoice rows (R86: invoiced, not revenue): every issued,
    not cancelled status (FG-695), never a proforma or a credit note."""
    return round(sum(_net(i) for i in invoices
                     if is_issued(i) and _kind(i) not in (PROFORMA, CREDIT_NOTE)), 2)


# R86 (Krum 14.11.2026, FG-565; changes R80): THE project revenue rule — "Приход" = only the
# payments RECEIVED (in full or in installments) against issued documents, net of VAT. The
# source is the FLOW-006 Payment ledger: active Inflow rows of finance_payments allocated
# (active payment_allocations) to an Issued, non-proforma invoice of the project. A proforma
# alone is never revenue. Issued but unpaid is "фактурирано, чака плащане", shown apart.
# The net share of a payment = allocated × invoice subtotal / invoice total.
#
# R90 (Krum 14.11.2026, FG-698 — final):
#  (a) the advance PAID on an issued proforma is revenue (the money received on it, net),
#      whether or not a final invoice names it yet. An unpaid proforma alone is never revenue
#      (R86). A final invoice that names the proforma (``advance_proforma_ids``) counts the
#      advance against its own "чака плащане" — the advance is never counted twice.
#  (b) the money returned on a credit note (an active Outflow payment allocated to an issued
#      CreditNote of the project) reduces the revenue. (The credit-note flow itself is #84.)
# R89 (Krum 14.11.2026, FG-696 — final): every reader that says "приход" reads THIS rule
# (project report, "Печалба по обект", "Пари срещу заработено"); the separate columns are
# named "фактурирано" and "получено".
REVENUE_BASIS = "received payments (FLOW-006 ledger), net of VAT"
INVOICE_REVENUE_FIELDS = {"_id": 0, "id": 1, "total": 1, "subtotal": 1, "status": 1, "kind": 1,
                          "advance_proforma_ids": 1}


def _ratio(inv) -> float:
    total = float(inv.get("total") or 0)
    return (_net(inv) / total) if total else 0.0


async def received_revenue(tenant, org_id: str, project_ids, *, date_from: str = None,
                           date_to: str = None, invoices=None) -> dict:
    """R86: the received revenue of ``project_ids`` (``date_from`` ≤ payment date < ``date_to``).

    Returns ``received_net`` (THE revenue, R89), ``received_by_month_net`` ({YYYY-MM: net}
    by payment date), ``received_gross``, ``invoiced_net``,
    ``invoiced_gross``, ``awaiting_payment_net`` / ``_gross`` (invoiced, not yet received),
    ``advance_net`` (FG-698a) and ``refunded_net`` (FG-698b). The invoiced / awaiting amounts
    are not limited by the payment dates. ``invoices`` must carry INVOICE_REVENUE_FIELDS."""
    from app.services.payment_state import active_allocations
    project_ids = list(project_ids)
    if invoices is None:
        invoices = await tenant.invoices.find(
            {"org_id": org_id, "project_id": {"$in": project_ids}, "direction": "Issued"},
            INVOICE_REVENUE_FIELDS).to_list(5000)
    issued = [i for i in invoices if i.get("id") and is_issued(i)]
    finals = {i["id"]: i for i in issued if _kind(i) not in (PROFORMA, CREDIT_NOTE)}
    credits = {i["id"]: i for i in issued if _kind(i) == CREDIT_NOTE}
    profs = {i["id"]: i for i in issued if _kind(i) == PROFORMA}
    # R90 (a): the proformas a final invoice names, in final-invoice order (their advance
    # reduces that invoice's "чака плащане"); EVERY issued proforma's receipts are revenue
    named = []
    for f in finals.values():
        for pid in f.get("advance_proforma_ids") or []:
            if pid in profs and pid not in named:
                named.append(pid)
    # FG-712: an issued credit note lowers the invoiced amount (always, by its absolute amount —
    # a note may be stored with negative or positive lines), refunded or not
    cn_gross = sum(abs(float(i.get("total") or 0)) for i in credits.values())
    cn_net = sum(abs(_net(i)) for i in credits.values())
    out = {"invoiced_gross": round(sum(float(i.get("total") or 0) for i in finals.values()) - cn_gross, 2),
           "invoiced_net": round(issued_revenue_net(finals.values()) - cn_net, 2),
           "credit_notes_net": round(cn_net, 2),
           "received_gross": 0.0, "received_net": 0.0, "advance_net": 0.0, "refunded_net": 0.0,
           "received_by_month_net": {}, "revenue_basis": REVENUE_BASIS}
    paid_on = {k: 0.0 for k in list(finals) + list(profs) + list(credits)}   # gross received / refunded per document
    docs = {**finals, **profs, **credits}
    if docs:
        allocs = await tenant.payment_allocations.find(
            active_allocations({"invoice_id": {"$in": list(docs)}}),
            {"_id": 0, "payment_id": 1, "invoice_id": 1, "amount_allocated": 1},
        ).to_list(20000)
        pay_ids = list({a.get("payment_id") for a in allocs if a.get("payment_id")})
        pays = {}
        if pay_ids:
            for p in await tenant.finance_payments.find(
                    active_payments({"id": {"$in": pay_ids}}),
                    {"_id": 0, "id": 1, "date": 1, "direction": 1}).to_list(20000):
                pays[p["id"]] = p
        for a in allocs:
            pay = pays.get(a.get("payment_id"))
            inv = docs.get(a.get("invoice_id"))
            if not pay or not inv:
                continue                      # reversed: not money received
            refund = a["invoice_id"] in credits
            if pay.get("direction") != ("Outflow" if refund else "Inflow"):
                continue
            gross = abs(float(a.get("amount_allocated") or 0))
            net = gross * abs(_ratio(inv))
            paid_on[a["invoice_id"]] += gross
            d = (pay.get("date") or "")[:10]
            if (date_from and d < date_from) or (date_to and d >= date_to):
                continue
            sign = -1.0 if refund else 1.0
            out["received_gross"] += sign * gross
            out["received_net"] += sign * net
            month = d[:7]
            out["received_by_month_net"][month] = out["received_by_month_net"].get(month, 0.0) + sign * net
            if refund:
                out["refunded_net"] += net
            elif a["invoice_id"] in profs:
                out["advance_net"] += net
    # "чака плащане" per final invoice: its total − what was received on it − the advance of
    # the proformas it names (FG-698a), never below 0
    advance_left = {k: paid_on[k] for k in named}
    await_gross = await_net = 0.0
    for f in finals.values():
        left = max(0.0, float(f.get("total") or 0) - paid_on[f["id"]])
        for pid in f.get("advance_proforma_ids") or []:
            if pid in advance_left and left > 0:
                take = min(left, advance_left[pid])
                advance_left[pid] -= take
                left -= take
        await_gross += left
        await_net += left * _ratio(f)
    # FG-712: a credit note not (yet) refunded lowers what the client still owes; a refunded
    # one is settled by the money paid back (and lowers the revenue instead, FG-698b)
    for cn in credits.values():
        open_g = max(0.0, abs(float(cn.get("total") or 0)) - paid_on[cn["id"]])
        await_gross -= open_g
        await_net -= open_g * abs(_ratio(cn))
    await_gross, await_net = max(0.0, await_gross), max(0.0, await_net)
    for k in ("received_gross", "received_net", "advance_net", "refunded_net"):
        out[k] = round(out[k], 2)
    out["received_by_month_net"] = {m: round(v, 2) for m, v in sorted(out["received_by_month_net"].items())}
    out["awaiting_payment_gross"] = round(await_gross, 2)
    out["awaiting_payment_net"] = round(await_net, 2)
    return out


async def compute_project_pnl(org_id: str, project_id: str) -> dict:
    """Compute complete P&L for a single project."""
    tenant = TenantData.for_resolved_org(db, org_id)

    # ── a. BUDGET (planned) ────────────────────────────────────────
    offers = await tenant.offers.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["Accepted", "Sent", "Draft"]}},
        {"_id": 0, "total": 1, "subtotal": 1, "status": 1},
    ).to_list(100)
    offer_total = sum(o.get("subtotal") or o.get("total") or 0 for o in offers)

    budgets = await tenant.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id}, {"_id": 0, "labor_budget": 1, "materials_budget": 1}
    ).to_list(100)
    labor_budget = sum(b.get("labor_budget", 0) for b in budgets)
    materials_budget = sum(b.get("materials_budget", 0) for b in budgets)
    total_budget = offer_total if offer_total > 0 else (labor_budget + materials_budget)

    # ── b. REVENUE ─────────────────────────────────────────────────
    invoices = await tenant.invoices.find(
        {"org_id": org_id, "project_id": project_id, "direction": "Issued"},  # WH81-03: revenue = Issued only (a supplier invoice is a cost, not revenue)
        {"_id": 0, "total": 1, "subtotal": 1, "vat_amount": 1, "status": 1, "paid_amount": 1,
         "id": 1, "kind": 1, "advance_proforma_ids": 1},
    ).to_list(5000)
    _rev_statuses = list(REVENUE_STATUSES)   # FG-530: the one revenue rule
    # Gross (с ДДС) — invoiced / received, the cash view
    invoiced_total = sum(i.get("total", 0) for i in invoices if i.get("status") in _rev_statuses)
    # Net (без ДДС) — management revenue basis
    invoiced_net = issued_revenue_net(invoices)
    # Output VAT collected on sales invoices
    output_vat = sum(i.get("vat_amount", 0) or 0 for i in invoices if i.get("status") in _rev_statuses)
    paid_total = sum(i.get("paid_amount", 0) or 0 for i in invoices)

    # Client acts revenue
    acts = await tenant.client_acts.find(
        {"org_id": org_id, "project_id": project_id, "status": "confirmed"},
        {"_id": 0, "total_amount": 1},
    ).to_list(100)
    acts_total = sum(a.get("total_amount", 0) for a in acts)

    # Additional SMR offered
    additional = await tenant.missing_smr.find(
        {"org_id": org_id, "project_id": project_id, "status": "offered"},
        {"_id": 0, "ai_estimated_price": 1},
    ).to_list(200)
    additional_offered = sum(m.get("ai_estimated_price") or 0 for m in additional)

    # R86: revenue = the payments RECEIVED (FLOW-006 ledger), net — not the invoiced amount
    received = await received_revenue(tenant, org_id, [project_id], invoices=invoices)
    total_revenue = received["received_net"]
    # R86: the invoiced amount by the same rule (a proforma is not an issued document)
    invoiced_total = received["invoiced_gross"]
    invoiced_net = received["invoiced_net"]

    # ── c. LABOR COST (LAB-01: approved report lines, one labor calculation) ──
    # FLOW-019/028 + R31: real labor = approved daily-report lines priced by
    # app.services.labor_cost (salary → approved hours × rate, akord → approved
    # quantity × piece rate). DOWNTIME is a real cost: inside labor_cost, shown apart.
    # (Before LAB-01: work_sessions incl. unapproved time.)
    labor = await project_labor_cost(org_id, project_id)
    labor_cost = labor["total"]
    labor_hours = round(labor["approved_hours"] + labor.get("downtime_hours", 0), 2)
    downtime_cost = labor["downtime_total"]
    # overtime premium is not a separate cost line in approved reports (debt, HANDOFF LAB-01)
    overtime_cost = 0.0

    # ── d. MATERIAL COST ───────────────────────────────────────────
    # 5C-C25 / FG-17 — ONE source: the shared helper
    # (app/services/canonical_material_cost.project_material_cost). It
    # already sums Path A (canonical: cost at acceptance, Р17; pre-cutover
    # legacy issues, Р13) and Path B (invoice lines allocated to the project)
    # as separate lots. The old `max(invoice, warehouse)` is gone: it made
    # the P&L disagree with every other report (FG-17: 100 vs 50).
    from app.services.canonical_material_cost import project_warehouse_material_cost
    wh = await project_warehouse_material_cost(tenant, org_id, project_id)
    material_cost_invoices = wh["invoice_cost"]
    material_total = wh["material_cost"]

    # Input VAT on the supplier invoice lines allocated to the project (VAT
    # only — the cost of those lines is inside the helper's total). 5C-C26
    # Addendum B: selected by the same allocation rule as Path B
    # (allocations[] share; deprecated single allocation as a fallback).
    from app.services.canonical_material_cost import project_input_vat
    input_vat = await project_input_vat(tenant, org_id, project_id)

    # 5C-C21 F-12 (Р10) — „фира" is part of the total and is shown as its own
    # line: material_cost + material_waste_cost == the helper's total.
    material_waste_cost = round(wh.get("waste_cost", 0.0) or 0.0, 2)
    material_cost = round(material_total - material_waste_cost, 2)

    # ── e. SUBCONTRACTOR COST ──────────────────────────────────────
    # SUB-ADV-01-A (FG-115, FLOW-006): an advance is cash, not cost — the cost is recognised
    # when the advance is deducted on an act (ordinary payments + advance deducted).
    from app.services.subcontract_cost import subcontractor_cost_recognized
    subcontractor_cost = await subcontractor_cost_recognized(tenant, org_id, project_id)

    # Contract payments (external workers)
    contract_docs = await tenant.contract_payments.find(
        {"org_id": org_id, "site_id": project_id}, {"_id": 0, "tranches": 1}
    ).to_list(200)
    contract_cost = 0
    for cd in contract_docs:
        for tr in cd.get("tranches", []):
            if tr.get("status") == "paid":
                contract_cost += tr.get("amount", 0)
    contract_cost = round(contract_cost, 2)

    # ── f. OVERHEAD ────────────────────────────────────────────────
    # OH74-03: the published (current) version of each period — never 0, never both
    # FG-127: the ONE project-overhead helper every reader uses (same legacy fallback, label)
    from app.services.overhead_lifecycle import project_overhead_current, recalculating_fields
    _oh = await project_overhead_current(tenant, project_id)
    allocs = _oh["rows"]
    overhead = _oh["amount"]
    # R38: the old allocation still counts while its period is recomputed — say so
    overhead_recalculating = any(a.get("recalculating") for a in allocs)

    # ── f2. OTHER — documentless cash expenses booked straight to the project ──
    other_docs = await tenant.finance_payments.find(  # PAY-01: a reversed pair counts 0
        active_payments({"org_id": org_id, "project_id": project_id, "direction": "Outflow", "category": "Други"}),
        {"_id": 0, "amount": 1},
    ).to_list(500)
    other_cost = round(sum(p.get("amount", 0) for p in other_docs), 2)

    # ── g. TOTALS ──────────────────────────────────────────────────
    total_expense = round(labor_cost + material_cost + material_waste_cost + subcontractor_cost + contract_cost + overhead + other_cost, 2)
    gross_profit = round(total_revenue - total_expense, 2)
    margin_pct = round(gross_profit / total_revenue * 100, 1) if total_revenue > 0 else 0
    budget_vs_actual = round(total_budget - total_expense, 2)
    vat_payable = round(output_vat - input_vat, 2)  # ДДС за внасяне = изходящ − входящ

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
            "invoiced_net": round(invoiced_net, 2),
            "paid_total": round(paid_total, 2),
            "acts_total": round(acts_total, 2),
            "additional_offered": round(additional_offered, 2),
            "total_revenue": round(total_revenue, 2),
            "received_net": received["received_net"],
            "received_gross": received["received_gross"],
            "awaiting_payment_net": received["awaiting_payment_net"],
            "awaiting_payment_gross": received["awaiting_payment_gross"],
            "awaiting_payment_label": "Фактурирано, чака плащане",
            "revenue_basis": REVENUE_BASIS,
        },
        "vat": {
            "output_vat": round(output_vat, 2),
            "input_vat": round(input_vat, 2),
            "vat_payable": vat_payable,
        },
        "expense": {
            "labor_cost": labor_cost,
            "labor_hours": labor_hours,
            "overtime_cost": overtime_cost,
            "downtime_cost": downtime_cost,
            "labor_source": "approved_daily_reports (LAB-01)",
            "material_cost": material_cost,
            "material_waste_cost": material_waste_cost,   # „фира" (5C-C21 F-12)
            "subcontractor_cost": subcontractor_cost,
            "contract_cost": contract_cost,
            "overhead": overhead,
            **recalculating_fields(overhead_recalculating),  # FG-127: same fields everywhere
            "other_cost": other_cost,
            "total_expense": total_expense,
        },
        # 5C-C20 F-9 — where expense.material_cost came from (read-only provenance).
        "warehouse_cost_basis": {
            "warehouse": wh["source"],
            "warehouse_material_cost": material_total,
            "invoice_cost": material_cost_invoices,
            # 5C-C25 (Р17 / FG-17) — no max(): one helper total.
            "cost_rule": wh["cost_rule"],
            "accepted_cost": wh["accepted_cost"],
            "returned_cost": wh["returned_cost"],
            "invoice_linked_excluded_cost": wh["invoice_linked_excluded_cost"],
            "allocated_cost": wh["allocated_cost"],
            "unallocated_cost": wh["unallocated_cost"],
            "legacy_excluded_cost": wh["legacy_excluded_cost"],
            "consumed_qty": wh["consumed_qty"],
            "waste_cost": material_waste_cost,
            "waste_qty": wh.get("waste_qty", 0.0),
            "partial_cost_data": wh["partial_cost_data"],
            # 5C-C22 / Р13 — the cutover split behind the warehouse figure.
            "canonical_cost": wh["canonical_cost"],
            "legacy_cost": wh["legacy_cost"],
            "legacy_undated_cost": wh["legacy_undated_cost"],
            "cutover_at": wh["cutover_at"],
            "cutover_source": wh["cutover_source"],
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
    tenant = TenantData.for_resolved_org(db, org_id)
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    trend = []
    project_invoices = await tenant.invoices.find(
        {"org_id": org_id, "project_id": project_id, "direction": "Issued"},
        INVOICE_REVENUE_FIELDS).to_list(5000)

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

        # R86: revenue = the payments RECEIVED in this month (payment date), net
        revenue = (await received_revenue(tenant, org_id, [project_id], date_from=ms[:10],
                                          date_to=me[:10], invoices=project_invoices))["received_net"]

        # Expense (LAB-01: labor of approved report lines dated in this month)
        month_labor = await project_labor_cost(
            org_id, project_id, m_start.strftime("%Y-%m-%d"),
            (m_end - timedelta(days=1)).strftime("%Y-%m-%d"))
        expense = month_labor["total"]

        profit = round(revenue - expense, 2)
        trend.append({"month": label, "revenue": revenue, "expense": expense, "profit": profit})

    return trend
