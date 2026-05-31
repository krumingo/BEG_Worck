"""
Routes — Employee Dossier (read-only aggregate view).
Central view of all labor, payroll, and payment data per worker.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.db import db
from app.deps.auth import get_current_user
from app.services.report_normalizer import fetch_normalized_report_lines, enrich_hours, enrich_hours_batch, NORMAL_DAY


router = APIRouter(tags=["Employee Dossier"])

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

    # 2) Reports — via unified normalizer
    raw_lines = await fetch_normalized_report_lines(
        org_id=org_id, date_from=date_from, date_to=date_to, worker_id=worker_id,
    )
    # Enrich and sort
    # P1-0.1: use batch enrichment so overtime is computed per-day (running total),
    # not per-line. A day with 3 reports of 3h each correctly becomes 8 normal + 1 overtime,
    # not 9 normal + 0 overtime.
    enrich_hours_batch(raw_lines)
    pids = set()
    for rl in raw_lines:
        if rl["project_id"]:
            pids.add(rl["project_id"])
    proj_map = {}
    if pids:
        projects = await db.projects.find(
            {"id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "name": 1}
        ).to_list(200)
        proj_map = {p["id"]: p.get("name", "") for p in projects}

    report_lines = []
    for rl in sorted(raw_lines, key=lambda x: x["date"], reverse=True):
        report_lines.append({
            "id": rl["id"],
            "date": rl["date"],
            "project_id": rl["project_id"],
            "project_name": proj_map.get(rl["project_id"], ""),
            "smr": rl["smr_type"],
            "hours": rl["hours"],
            "normal": rl["normal_hours"],
            "overtime": rl["overtime_hours"],
            "value": round(rl["hours"] * rate, 2),
            "status": rl["status"],
            "payroll_status": rl["payroll_status"],
        })

    total_hours = round(sum(r["hours"] for r in report_lines), 1)
    total_value = round(sum(r["value"] for r in report_lines), 2)

    # P1-0.1: split report totals by status bucket.
    # Lets the UI show clearly which reports are approved for payroll vs draft/rejected.
    # Legacy fields above (total_hours, total_value, count) stay as "all statuses combined"
    # to preserve backward compatibility for any other screen reading them.
    def _bucket(filter_fn):
        items = [r for r in report_lines if filter_fn(r)]
        return {
            "count": len(items),
            "hours": round(sum(r["hours"] for r in items), 1),
            "value": round(sum(r["value"] for r in items), 2),
        }

    def _is_approved(r):
        return (r.get("status") or "").upper() == "APPROVED"

    def _is_unpaid_approved(r):
        st = (r.get("status") or "").upper()
        ps = r.get("payroll_status") or "none"
        return st == "APPROVED" and ps in ("none", "", None)

    def _is_paid(r):
        return (r.get("payroll_status") or "") == "paid"

    def _is_batched(r):
        return (r.get("payroll_status") or "") == "batched"

    def _is_draft_submitted(r):
        st = (r.get("status") or "").upper()
        return st in ("DRAFT", "SUBMITTED")

    def _is_rejected(r):
        return (r.get("status") or "").upper() == "REJECTED"

    report_buckets = {
        "all":              _bucket(lambda r: True),
        "approved":         _bucket(_is_approved),
        "unpaid_approved":  _bucket(_is_unpaid_approved),
        "paid":             _bucket(_is_paid),
        "batched":          _bucket(_is_batched),
        "draft_submitted":  _bucket(_is_draft_submitted),
        "rejected":         _bucket(_is_rejected),
    }

    # 3) Pay runs containing this worker (v3 — source of truth)
    # P1-0.1: filter by archived + period overlap.
    # Period overlap: pay-run touches dossier window iff
    #   pay_run.period_end >= date_from AND pay_run.period_start <= date_to.
    # Before: no period filter (showed ALL pay-runs for worker) + no archived filter
    # → made "Платено" card and "Заплати" tab disagree silently.
    pay_runs = await db.pay_runs.find(
        {"org_id": org_id,
         "employee_rows.employee_id": worker_id,
         "archived": {"$ne": True},
         "period_end": {"$gte": date_from},
         "period_start": {"$lte": date_to}},
        {"_id": 0},
    ).sort("period_start", -1).to_list(100)

    payroll_weeks = []
    for pr in pay_runs:
        er = next((e for e in pr.get("employee_rows", []) if e.get("employee_id") == worker_id), None)
        if not er:
            continue
        if er.get("paid_now_amount", 0) == 0 and er.get("earned_amount", 0) == 0:
            continue
        day_cells = er.get("day_cells", [])
        normal_h = sum(dc.get("hours", 0) for dc in day_cells if not dc.get("is_overtime"))
        overtime_h = sum(dc.get("hours", 0) for dc in day_cells if dc.get("is_overtime"))
        total_h = er.get("approved_hours", normal_h + overtime_h)
        payroll_weeks.append({
            "batch_id": pr["id"],
            "week_start": pr.get("period_start", ""),
            "week_end": pr.get("period_end", ""),
            "status": pr.get("status", ""),
            "paid_at": pr.get("paid_at"),
            "days": len(day_cells),
            "hours": round(total_h, 2),
            "normal": round(normal_h, 2),
            "overtime": round(overtime_h, 2),
            "gross": round(er.get("earned_amount", 0), 2),
            "bonuses": round(er.get("bonuses_amount", 0), 2),
            "deductions": round(er.get("deductions_amount", 0), 2),
            "net": round(er.get("paid_now_amount", 0), 2),
            "adjustments": er.get("adjustments", []),
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
            # Legacy fields (kept for backward compat with other screens)
            "total_hours": total_hours,
            "total_value": total_value,
            "count": len(report_lines),
            # P1-0.1: explicit per-status breakdown
            "buckets": report_buckets,
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
