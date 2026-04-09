"""
Service - Real-time Overhead calculation.
Formula: overhead/person/day = fixed_monthly / working_days / avg_working_people
"""
from datetime import datetime, timezone, timedelta
from app.db import db

WORKING_STATUSES = {"working"}
PAID_NOT_WORKING = {"sick_paid", "vacation_paid"}
UNPAID_STATUSES = {"sick_unpaid", "vacation_unpaid", "absent_unauthorized"}
OFF_STATUSES = {"day_off", "holiday"}
SUBCONTRACTOR_OVERHEAD_FACTOR = 0.3


def get_working_days_in_month(year: int, month: int) -> int:
    """Count weekdays (Mon-Fri) in a month."""
    import calendar
    count = 0
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        if datetime(year, month, day).weekday() < 5:
            count += 1
    return count


async def compute_realtime_overhead(org_id: str, month: str = None) -> dict:
    now = datetime.now(timezone.utc)
    if not month:
        month = now.strftime("%Y-%m")

    year, mo = int(month[:4]), int(month[5:7])
    working_days = get_working_days_in_month(year, mo)

    # a. Fixed expenses
    fe = await db.fixed_expenses.find_one(
        {"org_id": org_id, "month": month}, {"_id": 0}
    )
    fixed_total = fe.get("total", 0) if fe else 0

    # b. Total employees
    total_employees = await db.employee_profiles.count_documents(
        {"org_id": org_id, "active": True}
    )
    if total_employees == 0:
        total_employees = await db.users.count_documents(
            {"org_id": org_id, "role": {"$nin": ["Admin"]}}
        )

    # c. Calendar data for the month
    cal_entries = await db.worker_calendar.find(
        {"org_id": org_id, "date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}},
        {"_id": 0},
    ).to_list(5000)

    # d. Daily breakdown
    from collections import defaultdict
    daily = defaultdict(lambda: {"working": 0, "sick_paid": 0, "sick_unpaid": 0, "vacation_paid": 0, "vacation_unpaid": 0, "absent": 0})
    by_worker_project = defaultdict(float)  # (project_id) -> worker_days

    for e in cal_entries:
        d = e["date"]
        s = e.get("status", "")
        if s == "working":
            daily[d]["working"] += 1
            sid = e.get("site_id")
            if sid:
                hours = e.get("hours", 8) or 8
                by_worker_project[sid] += hours / 8
        elif s == "sick_paid":
            daily[d]["sick_paid"] += 1
        elif s == "sick_unpaid":
            daily[d]["sick_unpaid"] += 1
        elif s == "vacation_paid":
            daily[d]["vacation_paid"] += 1
        elif s == "vacation_unpaid":
            daily[d]["vacation_unpaid"] += 1
        elif s == "absent_unauthorized":
            daily[d]["absent"] += 1

    # e. Average working per day
    working_counts = [v["working"] for v in daily.values()] if daily else [0]
    avg_working = sum(working_counts) / len(working_counts) if working_counts else 0

    # f. Subcontractor offset
    sub_acts = await db.subcontractor_acts.find(
        {"org_id": org_id, "status": {"$in": ["confirmed", "approved"]},
         "created_at": {"$gte": f"{month}-01", "$lte": f"{month}-31T23:59:59"}},
        {"_id": 0, "total_amount": 1},
    ).to_list(200)
    sub_revenue = sum(a.get("total_amount", 0) for a in sub_acts)
    sub_offset = round(sub_revenue * SUBCONTRACTOR_OVERHEAD_FACTOR, 2)
    effective_overhead = max(fixed_total - sub_offset, 0)

    # g. Per person per day
    oh_per_person_day = round(effective_overhead / working_days / max(avg_working, 1), 2) if working_days > 0 else 0
    oh_per_person_month = round(oh_per_person_day * working_days, 2)

    # h. By project
    projects_loaded = []
    for pid, worker_days in by_worker_project.items():
        proj = await db.projects.find_one({"id": pid, "org_id": org_id}, {"_id": 0, "name": 1, "code": 1})
        projects_loaded.append({
            "project_id": pid,
            "name": (proj or {}).get("name", pid[:8]),
            "code": (proj or {}).get("code", ""),
            "worker_days": round(worker_days, 2),
            "overhead_loaded": round(worker_days * oh_per_person_day, 2),
        })

    # i. Daily breakdown list
    daily_list = []
    import calendar
    for day in range(1, calendar.monthrange(year, mo)[1] + 1):
        dt = f"{month}-{day:02d}"
        if datetime(year, mo, day).weekday() >= 5:
            continue
        dd = daily.get(dt, {"working": 0, "sick_paid": 0, "sick_unpaid": 0, "vacation_paid": 0, "vacation_unpaid": 0, "absent": 0})
        w = dd["working"]
        oh = round(effective_overhead / working_days / max(w, 1), 2) if working_days > 0 and w > 0 else 0
        daily_list.append({"date": dt, **dd, "overhead_per_person": oh})

    # Alerts
    alerts = []
    today_str = now.strftime("%Y-%m-%d")
    today_data = daily.get(today_str)
    if today_data:
        sick_today = today_data["sick_paid"] + today_data["sick_unpaid"]
        if sick_today >= 2:
            working_today = today_data["working"] or 1
            normal_oh = round(effective_overhead / working_days / max(total_employees, 1), 2)
            actual_oh = round(effective_overhead / working_days / max(working_today, 1), 2)
            if normal_oh > 0:
                increase = round((actual_oh - normal_oh) / normal_oh * 100, 0)
                alerts.append(f"{sick_today} болни днес — режийните +{increase}%")

    return {
        "month": month,
        "fixed_total": fixed_total,
        "subcontractor_offset": sub_offset,
        "effective_overhead": effective_overhead,
        "total_employees": total_employees,
        "working_days": working_days,
        "avg_working_per_day": round(avg_working, 2),
        "overhead_per_person_day": oh_per_person_day,
        "overhead_per_person_month": oh_per_person_month,
        "daily_breakdown": daily_list,
        "by_project": projects_loaded,
        "alerts": alerts,
    }
