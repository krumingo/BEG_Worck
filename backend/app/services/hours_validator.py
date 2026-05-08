"""
Hours validation — checks worker daily hours across all projects.
"""
from app.db import db


async def get_worker_hours_for_day(org_id: str, worker_id: str, date: str) -> float:
    cursor = db.employee_daily_reports.find(
        {"org_id": org_id, "worker_id": worker_id, "date": date,
         "approval_status": {"$nin": ["REJECTED"]}},
        {"_id": 0, "hours": 1},
    )
    total = 0
    async for doc in cursor:
        total += float(doc.get("hours", 0))
    return round(total, 2)


async def check_hours_validation(org_id: str, worker_id: str, date: str, additional_hours: float = 0) -> dict:
    current = await get_worker_hours_for_day(org_id, worker_id, date)
    would_be = round(current + additional_hours, 2)

    # Projects today
    pipeline = [
        {"$match": {"org_id": org_id, "worker_id": worker_id, "date": date,
                     "approval_status": {"$nin": ["REJECTED"]}}},
        {"$group": {"_id": "$project_id", "hours": {"$sum": "$hours"}}},
    ]
    projects = []
    async for r in db.employee_daily_reports.aggregate(pipeline):
        pid = r["_id"]
        proj = await db.projects.find_one({"id": pid}, {"_id": 0, "name": 1})
        projects.append({"project_id": pid, "project_name": (proj or {}).get("name", ""), "hours": round(r["hours"], 2)})

    return {
        "current_hours": current,
        "would_be_total": would_be,
        "warning": would_be > 8,
        "block": would_be > 8,
        "projects_today": projects,
    }
