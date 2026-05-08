"""
Routes — Weekly Matrix (Sat→Fri payroll week view).
Uses unified report normalizer.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.db import db
from app.deps.auth import get_current_user
from app.services.report_normalizer import fetch_worker_day_map, NORMAL_DAY

router = APIRouter(tags=["Weekly Matrix"])


def _get_payroll_week(ref_date: str) -> tuple:
    d = datetime.strptime(ref_date, "%Y-%m-%d")
    weekday = d.weekday()
    days_since_sat = (weekday - 5) % 7
    sat = d - timedelta(days=days_since_sat)
    fri = sat + timedelta(days=6)
    return sat.strftime("%Y-%m-%d"), fri.strftime("%Y-%m-%d")


def _week_dates(sat_str: str) -> list:
    sat = datetime.strptime(sat_str, "%Y-%m-%d")
    return [(sat + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


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


@router.get("/weekly-matrix")
async def get_weekly_matrix(
    user: dict = Depends(get_current_user),
    week_of: Optional[str] = None,
):
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref = week_of or today
    sat, fri = _get_payroll_week(ref)
    dates = _week_dates(sat)

    # Active employees (filter test accounts)
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

    # Profiles
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "user_id": {"$in": emp_ids}},
        {"_id": 0, "user_id": 1, "position": 1, "pay_type": 1,
         "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1,
         "working_days_per_month": 1, "standard_hours_per_day": 1},
    ).to_list(200)
    prof_map = {p["user_id"]: p for p in profiles}

    # ── Use unified normalizer ─────────────────────────────────
    wd_map, _ = await fetch_worker_day_map(org_id, sat, fri)

    # Build rows
    rows = []
    for emp in employees:
        uid = emp["id"]
        prof = prof_map.get(uid, {})
        rate = _calc_rate(prof)
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

    rows.sort(key=lambda r: (0 if r["total_hours"] > 0 else 1, r["last_name"], r["first_name"]))

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
