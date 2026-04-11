"""
Routes — Weekly Matrix (Sat→Fri payroll week view).
Read-only projection for admin/office use.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["Weekly Matrix"])

NORMAL_DAY = 8
DAY_NAMES = ["Пон", "Вт", "Ср", "Чет", "Пет", "Съб", "Нед"]


def _get_payroll_week(ref_date: str) -> tuple:
    """Return (saturday, friday) for the payroll week containing ref_date.
    Payroll week = Saturday → Friday."""
    d = datetime.strptime(ref_date, "%Y-%m-%d")
    weekday = d.weekday()  # Mon=0 .. Sun=6
    # Saturday = weekday 5
    days_since_sat = (weekday - 5) % 7
    sat = d - timedelta(days=days_since_sat)
    fri = sat + timedelta(days=6)
    return sat.strftime("%Y-%m-%d"), fri.strftime("%Y-%m-%d")


def _week_dates(sat_str: str) -> list:
    """Return list of 7 date strings starting from Saturday."""
    sat = datetime.strptime(sat_str, "%Y-%m-%d")
    return [(sat + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


@router.get("/weekly-matrix")
async def get_weekly_matrix(
    user: dict = Depends(get_current_user),
    week_of: Optional[str] = None,
):
    """
    Weekly payroll matrix: rows=workers, cols=Sat→Fri.
    `week_of` is any date; the endpoint finds the containing Sat→Fri week.
    """
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref = week_of or today
    sat, fri = _get_payroll_week(ref)
    dates = _week_dates(sat)

    # 1) All active employees (filter test accounts)
    employees = await db.users.find(
        {"org_id": org_id, "is_active": True},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1, "email": 1, "role": 1},
    ).to_list(200)
    employees = [e for e in employees if not (
        e.get("email", "").startswith("test_")
        or e.get("email", "").startswith("fullflow_")
        or e.get("email", "").startswith("ui_fixed_")
    )]
    emp_ids = [e["id"] for e in employees]

    # 2) Profiles
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids}},
        {"_id": 0, "user_id": 1, "position": 1, "pay_type": 1,
         "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1,
         "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(200)
    prof_map = {p["user_id"]: p for p in profiles}

    # 3) Reports for the week (new-style: flat with worker_id)
    new_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "worker_id": {"$exists": True},
         "date": {"$gte": sat, "$lte": fri}},
        {"_id": 0, "id": 1, "worker_id": 1, "date": 1, "hours": 1,
         "smr_type": 1, "project_id": 1, "status": 1, "notes": 1},
    ).to_list(5000)

    # 4) Old-style reports for the week
    old_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": {"$exists": True},
         "report_date": {"$gte": sat, "$lte": fri}},
        {"_id": 0, "id": 1, "employee_id": 1, "report_date": 1,
         "day_entries": 1, "approval_status": 1, "notes": 1},
    ).to_list(5000)

    # 5) Project names
    project_ids = set()
    for r in new_reports:
        if r.get("project_id"):
            project_ids.add(r["project_id"])
    for r in old_reports:
        for e in r.get("day_entries", []):
            if e.get("project_id"):
                project_ids.add(e["project_id"])
    proj_map = {}
    if project_ids:
        projects = await db.projects.find(
            {"id": {"$in": list(project_ids)}},
            {"_id": 0, "id": 1, "name": 1, "code": 1},
        ).to_list(200)
        proj_map = {p["id"]: p.get("name") or p.get("code", "") for p in projects}

    # 6) Build worker→date→entries map
    # worker_id → date → [entries]
    wd_map = {}

    for r in new_reports:
        wid = r.get("worker_id")
        d = r.get("date", "")
        if wid not in wd_map:
            wd_map[wid] = {}
        if d not in wd_map[wid]:
            wd_map[wid][d] = []
        wd_map[wid][d].append({
            "id": r["id"],
            "smr": r.get("smr_type", ""),
            "hours": float(r.get("hours") or 0),
            "project_id": r.get("project_id", ""),
            "project_name": proj_map.get(r.get("project_id", ""), ""),
            "status": (r.get("status") or "").upper(),
            "notes": r.get("notes", ""),
        })

    for r in old_reports:
        wid = r.get("employee_id")
        d = r.get("report_date", "")
        if wid not in wd_map:
            wd_map[wid] = {}
        for e in r.get("day_entries", []):
            if d not in wd_map[wid]:
                wd_map[wid][d] = []
            wd_map[wid][d].append({
                "id": r["id"],
                "smr": e.get("work_description", ""),
                "hours": float(e.get("hours_worked") or 0),
                "project_id": e.get("project_id", ""),
                "project_name": proj_map.get(e.get("project_id", ""), ""),
                "status": (r.get("approval_status") or "").upper(),
                "notes": r.get("notes", ""),
            })

    # 7) Calc hourly rate
    def _calc_rate(uid):
        p = prof_map.get(uid)
        if not p:
            return 0
        pay = (p.get("pay_type") or "Monthly").strip()
        if pay == "Hourly":
            return float(p.get("hourly_rate") or 0)
        elif pay == "Daily":
            return round(float(p.get("daily_rate") or 0) / 8, 2)
        else:
            ms = float(p.get("monthly_salary") or 0)
            days = int(p.get("working_days_per_month") or 22)
            hrs = int(p.get("standard_hours_per_day") or 8)
            return round(ms / max(days * hrs, 1), 2)

    # 8) Build rows
    rows = []
    for emp in employees:
        uid = emp["id"]
        prof = prof_map.get(uid, {})
        rate = _calc_rate(uid)
        days_data = []
        total_hours = 0
        total_normal = 0
        total_overtime = 0
        worked_days = 0

        for d in dates:
            entries = wd_map.get(uid, {}).get(d, [])
            day_hours = sum(e["hours"] for e in entries)
            day_normal = min(day_hours, NORMAL_DAY) if day_hours > 0 else 0
            day_ot = max(0, day_hours - NORMAL_DAY)
            has_data = len(entries) > 0

            days_data.append({
                "date": d,
                "hours": round(day_hours, 1),
                "normal": round(day_normal, 1),
                "overtime": round(day_ot, 1),
                "entries": entries,
                "has_data": has_data,
            })

            total_hours += day_hours
            total_normal += day_normal
            total_overtime += day_ot
            if has_data:
                worked_days += 1

        labor_value = round(total_hours * rate, 2)

        rows.append({
            "worker_id": uid,
            "first_name": emp.get("first_name", ""),
            "last_name": emp.get("last_name", ""),
            "avatar_url": emp.get("avatar_url"),
            "position": prof.get("position", ""),
            "pay_type": prof.get("pay_type", ""),
            "hourly_rate": rate,
            "days": days_data,
            "total_hours": round(total_hours, 1),
            "total_normal": round(total_normal, 1),
            "total_overtime": round(total_overtime, 1),
            "worked_days": worked_days,
            "labor_value": labor_value,
            "bonuses": 0,
            "deductions": 0,
            "net_pay": labor_value,
        })

    # Sort: workers with data first, then by name
    rows.sort(key=lambda r: (0 if r["total_hours"] > 0 else 1, r["last_name"], r["first_name"]))

    # Grand totals
    grand_hours = round(sum(r["total_hours"] for r in rows), 1)
    grand_normal = round(sum(r["total_normal"] for r in rows), 1)
    grand_overtime = round(sum(r["total_overtime"] for r in rows), 1)
    grand_value = round(sum(r["labor_value"] for r in rows), 2)
    workers_with_data = sum(1 for r in rows if r["total_hours"] > 0)

    return {
        "week_start": sat,
        "week_end": fri,
        "dates": dates,
        "rows": rows,
        "totals": {
            "hours": grand_hours,
            "normal": grand_normal,
            "overtime": grand_overtime,
            "value": grand_value,
            "workers": len(rows),
            "workers_with_data": workers_with_data,
        },
    }
