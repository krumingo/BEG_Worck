"""
Hours validation — checks worker daily hours across all projects.
Supports BOTH old schema (worker_id/date/hours) and new schema (employee_id/report_date/day_entries).
"""
from app.db import db


async def get_worker_hours_for_day(org_id: str, worker_id: str, date: str) -> float:
    """Total hours for worker on date, summing BOTH schemas."""
    query = {
        "org_id": org_id,
        "$or": [
            {"employee_id": worker_id, "report_date": date},
            {"worker_id": worker_id, "date": date},
        ],
        "approval_status": {"$nin": ["REJECTED"]},
    }
    cursor = db.employee_daily_reports.find(
        query, {"_id": 0, "hours": 1, "hours_worked": 1, "day_entries": 1},
    )
    total = 0.0
    async for doc in cursor:
        entries = doc.get("day_entries") or []
        if entries:
            for e in entries:
                total += float(e.get("hours_worked", 0) or 0)
        else:
            total += float(doc.get("hours") or doc.get("hours_worked") or 0)
    return round(total, 2)
