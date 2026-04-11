"""
Routes — Employee Dossier (read-only aggregate view).
Central view of all labor, payroll, and payment data per worker.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["Employee Dossier"])

NORMAL_DAY = 8


def _calc_rate(profile: dict) -> float:
    pay = (profile.get("pay_type") or "Monthly").strip()
    if pay == "Hourly":
        return float(profile.get("hourly_rate") or 0)
    elif pay == "Daily":
        return round(float(profile.get("daily_rate") or 0) / 8, 2)
    else:
        ms = float(profile.get("monthly_salary") or 0)
        days = int(profile.get("working_days_per_month") or 22)
        hrs = int(profile.get("standard_hours_per_day") or 8)
        return round(ms / max(days * hrs, 1), 2)


@router.get("/employee-dossier/{worker_id}")
async def get_employee_dossier(
    worker_id: str,
    user: dict = Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    org_id = user["org_id"]
    if not date_from:
        date_from = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1) Employee basic info
    emp = await db.users.find_one(
        {"id": worker_id, "org_id": org_id},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1,
         "role": 1, "avatar_url": 1, "phone": 1, "is_active": 1},
    )
    if not emp:
        return {"error": "Employee not found"}

    prof = await db.employee_profiles.find_one(
        {"org_id": org_id, "user_id": worker_id},
        {"_id": 0, "position": 1, "pay_type": 1, "hourly_rate": 1, "daily_rate": 1,
         "monthly_salary": 1, "working_days_per_month": 1, "standard_hours_per_day": 1,
         "akord_note": 1, "start_date": 1},
    ) or {}

    rate = _calc_rate(prof)

    header = {
        "id": emp["id"],
        "first_name": emp.get("first_name", ""),
        "last_name": emp.get("last_name", ""),
        "email": emp.get("email", ""),
        "phone": emp.get("phone", ""),
        "role": emp.get("role", ""),
        "avatar_url": emp.get("avatar_url"),
        "is_active": emp.get("is_active", True),
        "position": prof.get("position", ""),
        "pay_type": prof.get("pay_type", ""),
        "hourly_rate": rate,
        "monthly_salary": float(prof.get("monthly_salary") or 0),
        "start_date": prof.get("start_date"),
    }

    # 2) Reports (new-style)
    new_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "worker_id": worker_id,
         "date": {"$gte": date_from, "$lte": date_to}},
        {"_id": 0},
    ).sort("date", -1).to_list(500)

    # Also old-style
    old_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": worker_id,
         "report_date": {"$gte": date_from, "$lte": date_to}},
        {"_id": 0},
    ).sort("report_date", -1).to_list(500)

    # Project names
    pids = set()
    for r in new_reports:
        if r.get("project_id"):
            pids.add(r["project_id"])
    for r in old_reports:
        for e in r.get("day_entries", []):
            if e.get("project_id"):
                pids.add(e["project_id"])
    proj_map = {}
    if pids:
        projects = await db.projects.find(
            {"id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "name": 1}
        ).to_list(200)
        proj_map = {p["id"]: p.get("name", "") for p in projects}

    # Flatten reports
    report_lines = []
    for r in new_reports:
        hours = float(r.get("hours") or 0)
        report_lines.append({
            "id": r["id"],
            "date": r.get("date", ""),
            "project_id": r.get("project_id", ""),
            "project_name": proj_map.get(r.get("project_id", ""), ""),
            "smr": r.get("smr_type", ""),
            "hours": hours,
            "normal": min(hours, NORMAL_DAY),
            "overtime": max(0, hours - NORMAL_DAY),
            "value": round(hours * rate, 2),
            "status": (r.get("status") or "").upper(),
            "payroll_status": r.get("payroll_status", "none"),
        })
    for r in old_reports:
        for e in r.get("day_entries", []):
            hours = float(e.get("hours_worked") or 0)
            report_lines.append({
                "id": r["id"],
                "date": r.get("report_date", ""),
                "project_id": e.get("project_id", ""),
                "project_name": proj_map.get(e.get("project_id", ""), ""),
                "smr": e.get("work_description", ""),
                "hours": hours,
                "normal": min(hours, NORMAL_DAY),
                "overtime": max(0, hours - NORMAL_DAY),
                "value": round(hours * rate, 2),
                "status": (r.get("approval_status") or "").upper(),
                "payroll_status": r.get("payroll_status", "none"),
            })

    total_hours = round(sum(r["hours"] for r in report_lines), 1)
    total_value = round(sum(r["value"] for r in report_lines), 2)

    # 3) Payroll batches containing this worker
    batches = await db.payroll_batches.find(
        {"org_id": org_id, "employee_summaries.worker_id": worker_id},
        {"_id": 0},
    ).sort("week_start", -1).to_list(100)

    payroll_weeks = []
    for b in batches:
        ws = next((s for s in b.get("employee_summaries", []) if s.get("worker_id") == worker_id), None)
        if ws:
            payroll_weeks.append({
                "batch_id": b["id"],
                "week_start": b.get("week_start", ""),
                "week_end": b.get("week_end", ""),
                "status": b.get("status", ""),
                "paid_at": b.get("paid_at"),
                "days": ws.get("included_days", 0),
                "hours": ws.get("total_hours", 0),
                "normal": ws.get("normal_hours", 0),
                "overtime": ws.get("overtime_hours", 0),
                "gross": ws.get("gross", 0),
                "bonuses": ws.get("bonuses", 0),
                "deductions": ws.get("deductions", 0),
                "net": ws.get("net", 0),
                "adjustments": ws.get("adjustments", []),
            })

    total_gross = round(sum(w["gross"] for w in payroll_weeks), 2)
    total_net = round(sum(w["net"] for w in payroll_weeks), 2)
    total_paid = round(sum(w["net"] for w in payroll_weeks if w["status"] == "paid"), 2)

    # 4) Advances / loans
    advances = await db.advances.find(
        {"org_id": org_id, "user_id": worker_id},
        {"_id": 0},
    ).sort("issued_date", -1).to_list(100)

    advance_items = []
    for a in advances:
        advance_items.append({
            "id": a.get("id", ""),
            "type": a.get("type", "advance"),
            "amount": float(a.get("amount") or 0),
            "remaining": float(a.get("remaining_amount") or 0),
            "status": a.get("status", ""),
            "date": a.get("issued_date", ""),
            "note": a.get("note", ""),
        })

    # 5) Calendar (last 30 days)
    cal_from = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    cal_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    calendar_entries = await db.worker_calendar.find(
        {"org_id": org_id, "worker_id": worker_id,
         "date": {"$gte": cal_from, "$lte": cal_to}},
        {"_id": 0, "date": 1, "status": 1, "site_id": 1, "hours": 1},
    ).sort("date", -1).to_list(60)

    # Also check rosters
    roster_dates = set()
    rosters = await db.site_daily_rosters.find(
        {"org_id": org_id, "date": {"$gte": cal_from, "$lte": cal_to},
         "workers.worker_id": worker_id},
        {"_id": 0, "date": 1, "project_id": 1},
    ).to_list(60)
    roster_map = {}
    for r in rosters:
        roster_dates.add(r["date"])
        roster_map[r["date"]] = r.get("project_id", "")

    # Reports by date for calendar
    report_by_date = {}
    for rl in report_lines:
        d = rl["date"]
        if d not in report_by_date:
            report_by_date[d] = {"hours": 0, "has_report": True}
        report_by_date[d]["hours"] += rl["hours"]

    cal_map = {c["date"]: c for c in calendar_entries}

    calendar = []
    d = datetime.strptime(cal_from, "%Y-%m-%d")
    end = datetime.strptime(cal_to, "%Y-%m-%d")
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        cal = cal_map.get(ds, {})
        rpt = report_by_date.get(ds, {})
        in_roster = ds in roster_dates
        hours = rpt.get("hours", 0) or float(cal.get("hours") or 0)
        status = cal.get("status", "")
        if not status and (in_roster or rpt.get("has_report")):
            status = "working"
        calendar.append({
            "date": ds,
            "weekday": d.weekday(),
            "status": status,
            "hours": round(hours, 1),
            "has_report": rpt.get("has_report", False),
            "overtime": max(0, hours - NORMAL_DAY) if hours > 0 else 0,
            "site_id": roster_map.get(ds) or cal.get("site_id", ""),
            "site_name": proj_map.get(roster_map.get(ds, "") or cal.get("site_id", ""), ""),
        })
        d += timedelta(days=1)
    calendar.reverse()

    # 6) Warnings
    warnings = []
    unpaid_weeks = sum(1 for w in payroll_weeks if w["status"] != "paid")
    if unpaid_weeks > 0:
        warnings.append({"type": "unpaid", "text": f"{unpaid_weeks} неплатени седмици"})
    active_loans = sum(1 for a in advance_items if a["remaining"] > 0 and a["status"] in ("active", "approved"))
    if active_loans > 0:
        total_remaining = round(sum(a["remaining"] for a in advance_items if a["remaining"] > 0), 2)
        warnings.append({"type": "loan", "text": f"{active_loans} активни заема ({total_remaining} EUR)"})
    if rate == 0:
        warnings.append({"type": "rate", "text": "Липсва ставка"})
    no_payroll = sum(1 for r in report_lines if r["status"] == "APPROVED" and r["payroll_status"] in ("none", None, ""))
    if no_payroll > 0:
        warnings.append({"type": "no_payroll", "text": f"{no_payroll} одобрени отчета без payroll статус"})

    return {
        "header": header,
        "reports": {
            "lines": report_lines,
            "total_hours": total_hours,
            "total_value": total_value,
            "count": len(report_lines),
        },
        "payroll": {
            "weeks": payroll_weeks,
            "total_gross": total_gross,
            "total_net": total_net,
            "total_paid": total_paid,
        },
        "advances": advance_items,
        "calendar": calendar,
        "warnings": warnings,
        "period": {"date_from": date_from, "date_to": date_to},
    }
