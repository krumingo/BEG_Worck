"""
Service - Morning Briefing (rule-based, v1).
Aggregates critical data from existing modules into a management summary.
"""
from datetime import datetime, timezone, timedelta
from app.db import db


async def build_morning_briefing(org_id: str, date: str = None) -> dict:
    now = datetime.now(timezone.utc)
    today = date or now.strftime("%Y-%m-%d")

    # ── A. Critical Alarms ──────────────────────────────────────
    critical = await db.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "critical"})
    warning = await db.alarm_events.count_documents({"org_id": org_id, "status": "active", "severity": "warning"})
    top_alarms = await db.alarm_events.find(
        {"org_id": org_id, "status": "active"},
        {"_id": 0, "id": 1, "message": 1, "severity": 1, "site_name": 1, "triggered_at": 1},
    ).sort([("severity", -1), ("triggered_at", -1)]).limit(3).to_list(3)

    # ── B. Risky Projects ───────────────────────────────────────
    projects = await db.projects.find(
        {"org_id": org_id, "status": {"$in": ["Active", "Draft"]}},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(100)

    top_risks = []
    for p in projects:
        pid = p["id"]
        reasons = []
        severity = "info"

        # Budget burn
        budgets = await db.activity_budgets.find({"org_id": org_id, "project_id": pid}, {"_id": 0, "labor_budget": 1}).to_list(50)
        total_budget = sum(b.get("labor_budget", 0) for b in budgets)
        if total_budget > 0:
            sessions_cost = 0
            async for s in db.work_sessions.find({"org_id": org_id, "site_id": pid, "ended_at": {"$ne": None}}, {"_id": 0, "labor_cost": 1}):
                sessions_cost += s.get("labor_cost", 0)
            burn = sessions_cost / total_budget * 100
            if burn > 100:
                reasons.append("Бюджетът е надхвърлен")
                severity = "critical"
            elif burn > 80:
                reasons.append(f"Бюджет {round(burn)}% изхарчен")
                severity = "warning"

        # Pulse check (no workers, missing report)
        pulse = await db.site_pulses.find_one(
            {"org_id": org_id, "site_id": pid, "date": today}, {"_id": 0, "total_workers": 1, "daily_report_submitted": 1}
        )
        if pulse:
            if pulse.get("total_workers", 0) == 0:
                reasons.append("Без работници")
                severity = max(severity, "warning", key=lambda x: {"info": 0, "warning": 1, "critical": 2}[x])
            if not pulse.get("daily_report_submitted"):
                reasons.append("Липсва отчет")

        # Site alarms
        site_critical = await db.alarm_events.count_documents({"org_id": org_id, "site_id": pid, "status": "active", "severity": "critical"})
        if site_critical > 0:
            reasons.append(f"{site_critical} критични аларми")
            severity = "critical"

        if reasons:
            top_risks.append({"project_id": pid, "project_name": p["name"], "reasons": reasons, "severity": severity})

    top_risks.sort(key=lambda x: {"critical": 0, "warning": 1, "info": 2}[x["severity"]])
    top_risks = top_risks[:3]

    # ── C. Payment Priorities ───────────────────────────────────
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    soon = (today_dt + timedelta(days=3)).strftime("%Y-%m-%d")

    invoices = await db.invoices.find(
        {"org_id": org_id, "status": {"$in": ["Sent", "PartiallyPaid"]}},
        {"_id": 0, "id": 1, "invoice_number": 1, "counterparty_name": 1, "project_id": 1, "due_date": 1, "total": 1, "paid_amount": 1},
    ).to_list(200)

    payments = []
    for inv in invoices:
        due = inv.get("due_date", "")
        unpaid = round((inv.get("total", 0) or 0) - (inv.get("paid_amount", 0) or 0), 2)
        if unpaid <= 0:
            continue
        if due and due < today:
            payments.append({**inv, "unpaid": unpaid, "urgency": "overdue"})
        elif due and due <= soon:
            payments.append({**inv, "unpaid": unpaid, "urgency": "due_soon"})

    payments.sort(key=lambda x: (0 if x["urgency"] == "overdue" else 1, x.get("due_date", "")))
    payments = payments[:3]

    # ── D. Missing Reports / Approvals ──────────────────────────
    missing = []
    for p in projects[:10]:
        pulse = await db.site_pulses.find_one(
            {"org_id": org_id, "site_id": p["id"], "date": today}, {"_id": 0, "daily_report_submitted": 1}
        )
        if pulse and not pulse.get("daily_report_submitted"):
            missing.append({"project": p["name"], "issue_type": "missing_report", "reason": "Липсва дневен отчет"})

    pending_expenses = await db.pending_expenses.count_documents({"org_id": org_id, "status": "pending_approval"})
    if pending_expenses > 0:
        missing.append({"project": "Фирма", "issue_type": "pending_approval", "reason": f"{pending_expenses} разхода чакат одобрение"})

    pending_smr = await db.missing_smr.count_documents({"org_id": org_id, "client_approval.status": "pending"})
    if pending_smr > 0:
        missing.append({"project": "Клиенти", "issue_type": "pending_approval", "reason": f"{pending_smr} СМР чакат одобрение от клиент"})

    missing = missing[:5]

    # ── E. Overhead Pressure ────────────────────────────────────
    overhead = {"overhead_per_person_day": 0, "working_today": 0, "total_employees": 0, "sick_today": 0, "alert": None}
    try:
        from app.services.overhead_realtime import compute_realtime_overhead
        month = today[:7]
        oh = await compute_realtime_overhead(org_id, month)
        overhead["overhead_per_person_day"] = oh.get("overhead_per_person_day", 0)
        overhead["working_today"] = round(oh.get("avg_working_per_day", 0))
        overhead["total_employees"] = oh.get("total_employees", 0)
        # Count sick from calendar for today
        sick = await db.worker_calendar.count_documents(
            {"org_id": org_id, "date": today, "status": {"$in": ["sick_paid", "sick_unpaid"]}}
        )
        overhead["sick_today"] = sick
        if oh.get("alerts"):
            overhead["alert"] = oh["alerts"][0]
    except Exception:
        pass

    # ── F. Quick Totals ─────────────────────────────────────────
    active_projects = len(projects)
    workers_today = 0
    today_sessions = await db.work_sessions.count_documents(
        {"org_id": org_id, "started_at": {"$gte": f"{today}T00:00:00", "$lte": f"{today}T23:59:59"}}
    )
    workers_today = await db.work_sessions.distinct(
        "worker_id", {"org_id": org_id, "started_at": {"$gte": f"{today}T00:00:00", "$lte": f"{today}T23:59:59"}}
    )

    summary = {
        "active_projects": active_projects,
        "workers_today": len(workers_today) if isinstance(workers_today, list) else 0,
        "critical_alarms": critical,
        "warning_alarms": warning,
        "due_payments_count": len(payments),
        "overdue_count": len([p for p in payments if p["urgency"] == "overdue"]),
        "missing_reports_count": len([m for m in missing if m["issue_type"] == "missing_report"]),
    }

    # ── Headline ────────────────────────────────────────────────
    headline = _build_headline(critical, warning, len(top_risks), len(payments), len(missing))

    return {
        "date": today,
        "headline": headline,
        "summary": summary,
        "top_alarms": top_alarms,
        "top_risks": top_risks,
        "payments": [{k: v for k, v in p.items() if k != "_id"} for p in payments],
        "missing_reports": missing,
        "overhead": overhead,
    }


def _build_headline(critical: int, warning: int, risks: int, payments: int, missing: int) -> str:
    parts = []
    if critical > 0:
        parts.append(f"{critical} критичн{'а' if critical == 1 else 'и'} аларм{'а' if critical == 1 else 'и'}")
    if risks > 0:
        parts.append(f"{risks} обект{'а' if risks < 5 else 'а'} с висок риск")
    if payments > 0:
        parts.append(f"{payments} важн{'о' if payments == 1 else 'и'} плащан{'е' if payments == 1 else 'ия'}")
    if missing > 0:
        parts.append(f"{missing} липсващ{'ия' if missing < 5 else 'и'} елемент{'а' if missing < 5 else 'а'}")

    if not parts:
        return "Няма важни сигнали за днес."
    if critical > 0:
        return "Внимание: " + " и ".join(parts[:2]) + "."
    return "Днес: " + ", ".join(parts) + "."
