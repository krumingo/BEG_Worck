"""
Service - Cash Flow Forecast v1 (rule-based).
30-day projection from invoices, payroll, fixed expenses, contract payments.
"""
from datetime import datetime, timezone, timedelta
from app.db import db


async def build_cashflow_forecast(org_id: str, days: int = 30, start_date: str = None) -> dict:
    now = datetime.now(timezone.utc)
    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else now
    start_str = start.strftime("%Y-%m-%d")
    end = start + timedelta(days=days)
    end_str = end.strftime("%Y-%m-%d")

    # ── A. Incoming (unpaid invoices) ───────────────────────────
    invoices = await db.invoices.find(
        {"org_id": org_id, "status": {"$in": ["Sent", "PartiallyPaid"]}},
        {"_id": 0, "id": 1, "invoice_number": 1, "counterparty_name": 1,
         "project_id": 1, "due_date": 1, "total": 1, "paid_amount": 1},
    ).to_list(500)

    incoming_items = []
    overdue_items = []
    incoming_by_date = {}

    for inv in invoices:
        unpaid = round((inv.get("total", 0) or 0) - (inv.get("paid_amount", 0) or 0), 2)
        if unpaid <= 0:
            continue
        due = inv.get("due_date", "")
        entry = {
            "source_type": "invoice", "source_id": inv["id"],
            "title": f"Фактура {inv.get('invoice_number', '')} — {inv.get('counterparty_name', '')}",
            "amount": unpaid, "due_date": due, "status": "overdue" if due < start_str else "expected",
        }
        if due and due < start_str:
            overdue_items.append(entry)
            entry["status"] = "overdue"
        else:
            incoming_items.append(entry)
        if due:
            target = due if due >= start_str else start_str
            if target <= end_str:
                incoming_by_date[target] = incoming_by_date.get(target, 0) + unpaid

    incoming_items.sort(key=lambda x: x.get("due_date", ""))

    # ── B. Outgoing ─────────────────────────────────────────────
    outgoing_items = []
    outgoing_by_date = {}

    # Fixed expenses (spread monthly)
    month = start.strftime("%Y-%m")
    fe = await db.fixed_expenses.find_one({"org_id": org_id, "month": month}, {"_id": 0})
    monthly_fixed = (fe.get("total", 0) if fe else 0)
    if monthly_fixed > 0:
        daily_fixed = round(monthly_fixed / 30, 2)
        outgoing_items.append({
            "source_type": "fixed_expenses", "source_id": "monthly",
            "title": f"Фиксирани разходи ({month})", "amount": monthly_fixed,
            "due_date": f"{month}-28", "status": "recurring",
        })
        # Spread across month-end
        pay_day = f"{month}-25"
        if start_str <= pay_day <= end_str:
            outgoing_by_date[pay_day] = outgoing_by_date.get(pay_day, 0) + monthly_fixed

    # Contract payment tranches
    contracts = await db.contract_payments.find(
        {"org_id": org_id, "status": "active"}, {"_id": 0}
    ).to_list(200)
    for c in contracts:
        for tr in c.get("tranches", []):
            if tr.get("status") != "pending":
                continue
            due = tr.get("due_date", "")
            amt = tr.get("amount", 0)
            if due and start_str <= due <= end_str and amt > 0:
                outgoing_items.append({
                    "source_type": "contract_payment", "source_id": c["id"],
                    "title": f"Договор: {c.get('worker_name', '')}",
                    "amount": amt, "due_date": due, "status": "pending",
                })
                outgoing_by_date[due] = outgoing_by_date.get(due, 0) + amt

    # Subcontractor confirmed payments
    sub_payments = await db.subcontractor_payments.find(
        {"org_id": org_id, "status": {"$in": ["confirmed", "pending"]}},
        {"_id": 0, "amount": 1, "created_at": 1, "id": 1},
    ).to_list(200)
    for sp in sub_payments:
        created = (sp.get("created_at") or "")[:10]
        amt = sp.get("amount", 0)
        if amt > 0:
            # Estimate payment within 7 days of confirmation
            est_date = created  # simplified
            if start_str <= est_date <= end_str:
                outgoing_items.append({
                    "source_type": "subcontractor", "source_id": sp.get("id", ""),
                    "title": "Подизпълнител", "amount": amt,
                    "due_date": est_date, "status": "confirmed",
                })
                outgoing_by_date[est_date] = outgoing_by_date.get(est_date, 0) + amt

    # Payroll estimate (weekly from recent)
    last_payroll = await db.payslips.find(
        {"org_id": org_id, "status": {"$in": ["Draft", "Approved"]}},
        {"_id": 0, "net_pay": 1},
    ).sort("created_at", -1).to_list(50)
    weekly_payroll = sum(p.get("net_pay", 0) for p in last_payroll[:20])
    if weekly_payroll > 0:
        # Spread across fridays in the period
        d = start
        while d <= end:
            if d.weekday() == 4:  # Friday
                ds = d.strftime("%Y-%m-%d")
                outgoing_by_date[ds] = outgoing_by_date.get(ds, 0) + round(weekly_payroll / 4, 2)
            d += timedelta(days=1)
        outgoing_items.append({
            "source_type": "payroll", "source_id": "estimate",
            "title": "Заплати (оценка)", "amount": round(weekly_payroll, 2),
            "due_date": "", "status": "estimate",
        })

    outgoing_items.sort(key=lambda x: x.get("due_date", ""))

    # ── C. Daily Timeline ───────────────────────────────────────
    timeline = []
    cumulative = 0
    lowest_cum = 0
    lowest_day = None
    highest_outflow = 0
    highest_outflow_day = None
    negative_days = 0

    d = start
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        inc = incoming_by_date.get(ds, 0)
        out = outgoing_by_date.get(ds, 0)
        net = round(inc - out, 2)
        cumulative = round(cumulative + net, 2)

        timeline.append({
            "date": ds, "incoming": round(inc, 2), "outgoing": round(out, 2),
            "net": net, "cumulative": cumulative,
        })

        if cumulative < lowest_cum:
            lowest_cum = cumulative
            lowest_day = ds
        if cumulative < 0:
            negative_days += 1
        if out > highest_outflow:
            highest_outflow = out
            highest_outflow_day = ds

        d += timedelta(days=1)

    # ── D. Summary ──────────────────────────────────────────────
    total_incoming = round(sum(incoming_by_date.values()), 2)
    total_outgoing = round(sum(outgoing_by_date.values()), 2)
    overdue_total = round(sum(o["amount"] for o in overdue_items), 2)

    # ── E. Warning Level ────────────────────────────────────────
    if negative_days == 0 and overdue_total < total_incoming * 0.3:
        warning = "ok"
    elif negative_days <= 2:
        warning = "watch"
    elif negative_days <= 7 or overdue_total > total_incoming * 0.5:
        warning = "risk"
    else:
        warning = "critical"

    headline = _build_headline(warning, total_incoming, total_outgoing, overdue_total, lowest_day, negative_days, days)

    summary = {
        "period_days": days,
        "total_incoming": total_incoming,
        "total_outgoing": total_outgoing,
        "net_forecast": round(total_incoming - total_outgoing, 2),
        "overdue_receivables": overdue_total,
        "highest_outflow_day": {"date": highest_outflow_day, "amount": round(highest_outflow, 2)} if highest_outflow_day else None,
        "lowest_cash_day": {"date": lowest_day, "cumulative": round(lowest_cum, 2)} if lowest_day else None,
        "warning_level": warning,
        "negative_days": negative_days,
    }

    return {
        "headline": headline,
        "summary": summary,
        "timeline": timeline,
        "incoming": incoming_items[:10],
        "outgoing": outgoing_items[:10],
        "overdue": overdue_items,
    }


def _build_headline(warning, inc, out, overdue, lowest_day, neg_days, period) -> str:
    if warning == "ok":
        return f"Очаква се положителен баланс за следващите {period} дни."
    if warning == "watch":
        if lowest_day:
            return f"Леко напрежение около {lowest_day}. Наблюдавайте."
        return "Леко напрежение в cash flow. Наблюдавайте."
    if warning == "risk":
        if overdue > 0:
            return f"Просрочени вземания {round(overdue)}лв повишават риска. {neg_days} дни с отрицателен баланс."
        return f"{neg_days} дни с отрицателен баланс в следващите {period} дни."
    return f"Критично: {neg_days} дни с недостиг. Просрочени вземания: {round(overdue)}лв."
