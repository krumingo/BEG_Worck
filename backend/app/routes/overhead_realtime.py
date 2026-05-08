"""
Routes - Real-time Overhead (Worker Calendar + Fixed Expenses + Overhead Calc).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m4
from app.services.overhead_realtime import compute_realtime_overhead

router = APIRouter(tags=["Overhead Realtime"])

VALID_STATUSES = ["working", "sick_paid", "sick_unpaid", "vacation_paid", "vacation_unpaid", "absent_unauthorized", "day_off", "holiday"]


class CalendarEntry(BaseModel):
    worker_id: str
    date: str
    status: str
    site_id: Optional[str] = None
    hours: Optional[float] = 8
    notes: Optional[str] = None


class CalendarBulk(BaseModel):
    entries: List[CalendarEntry]


class FixedExpensesUpdate(BaseModel):
    month: str
    categories: list


# ── Worker Calendar ────────────────────────────────────────────────

@router.get("/worker-calendar")
async def get_worker_calendar(
    worker_id: Optional[str] = None,
    month: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query = {"org_id": user["org_id"]}
    if worker_id:
        query["worker_id"] = worker_id
    if month:
        query["date"] = {"$gte": f"{month}-01", "$lte": f"{month}-31"}
    items = await db.worker_calendar.find(query, {"_id": 0}).sort("date", 1).to_list(2000)
    return {"items": items, "total": len(items)}


@router.post("/worker-calendar", status_code=201)
async def create_calendar_entry(data: CalendarEntry, user: dict = Depends(get_current_user)):
    if data.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {VALID_STATUSES}")

    now = datetime.now(timezone.utc).isoformat()

    # Upsert by worker_id + date
    existing = await db.worker_calendar.find_one(
        {"org_id": user["org_id"], "worker_id": data.worker_id, "date": data.date}
    )
    doc = {
        "org_id": user["org_id"],
        "worker_id": data.worker_id,
        "date": data.date,
        "status": data.status,
        "site_id": data.site_id,
        "hours": data.hours or 8,
        "notes": data.notes,
        "source": "manual",
        "updated_at": now,
        "updated_by": user["id"],
    }
    if existing:
        await db.worker_calendar.update_one({"id": existing["id"]}, {"$set": doc})
        return await db.worker_calendar.find_one({"id": existing["id"]}, {"_id": 0})
    else:
        doc["id"] = str(uuid.uuid4())
        doc["created_at"] = now
        doc["created_by"] = user["id"]
        await db.worker_calendar.insert_one(doc)
        return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/worker-calendar/{entry_id}")
async def update_calendar_entry(entry_id: str, data: CalendarEntry, user: dict = Depends(get_current_user)):
    entry = await db.worker_calendar.find_one({"id": entry_id, "org_id": user["org_id"]})
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if data.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    now = datetime.now(timezone.utc).isoformat()
    await db.worker_calendar.update_one({"id": entry_id}, {"$set": {
        "status": data.status, "site_id": data.site_id, "hours": data.hours or 8,
        "notes": data.notes, "updated_at": now, "updated_by": user["id"],
    }})
    return await db.worker_calendar.find_one({"id": entry_id}, {"_id": 0})


@router.post("/worker-calendar/bulk", status_code=201)
async def bulk_calendar(data: CalendarBulk, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    created = 0
    updated = 0
    for e in data.entries:
        if e.status not in VALID_STATUSES:
            continue
        existing = await db.worker_calendar.find_one(
            {"org_id": user["org_id"], "worker_id": e.worker_id, "date": e.date}
        )
        doc = {
            "org_id": user["org_id"], "worker_id": e.worker_id, "date": e.date,
            "status": e.status, "site_id": e.site_id, "hours": e.hours or 8,
            "notes": e.notes, "source": "manual", "updated_at": now, "updated_by": user["id"],
        }
        if existing:
            await db.worker_calendar.update_one({"id": existing["id"]}, {"$set": doc})
            updated += 1
        else:
            doc["id"] = str(uuid.uuid4())
            doc["created_at"] = now
            doc["created_by"] = user["id"]
            await db.worker_calendar.insert_one(doc)
            created += 1
    return {"ok": True, "created": created, "updated": updated}


@router.post("/worker-calendar/sync-from-sessions")
async def sync_from_sessions(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    """Auto-sync calendar from work_sessions for a given date."""
    org_id = user["org_id"]
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()

    sessions = await db.work_sessions.find(
        {"org_id": org_id, "ended_at": {"$ne": None},
         "started_at": {"$gte": f"{target_date}T00:00:00", "$lte": f"{target_date}T23:59:59"}},
        {"_id": 0, "worker_id": 1, "site_id": 1, "duration_hours": 1},
    ).to_list(1000)

    from collections import defaultdict
    by_worker = defaultdict(lambda: {"hours": 0, "site_id": None})
    for s in sessions:
        wid = s["worker_id"]
        by_worker[wid]["hours"] += s.get("duration_hours", 0)
        if s.get("site_id"):
            by_worker[wid]["site_id"] = s["site_id"]

    synced = 0
    for wid, data in by_worker.items():
        existing = await db.worker_calendar.find_one(
            {"org_id": org_id, "worker_id": wid, "date": target_date}
        )
        doc = {
            "org_id": org_id, "worker_id": wid, "date": target_date,
            "status": "working", "site_id": data["site_id"],
            "hours": round(data["hours"], 2), "source": "auto_from_sessions",
            "updated_at": now,
        }
        if existing:
            if existing.get("source") != "manual":
                await db.worker_calendar.update_one({"id": existing["id"]}, {"$set": doc})
                synced += 1
        else:
            doc["id"] = str(uuid.uuid4())
            doc["created_at"] = now
            doc["created_by"] = "system"
            await db.worker_calendar.insert_one(doc)
            synced += 1

    return {"ok": True, "synced": synced, "date": target_date}


# ── Fixed Expenses ─────────────────────────────────────────────────

@router.get("/fixed-expenses")
async def get_fixed_expenses(month: Optional[str] = None, user: dict = Depends(get_current_user)):
    m = month or datetime.now(timezone.utc).strftime("%Y-%m")
    doc = await db.fixed_expenses.find_one({"org_id": user["org_id"], "month": m}, {"_id": 0})
    return doc or {"month": m, "categories": [], "total": 0}


@router.put("/fixed-expenses")
async def update_fixed_expenses(data: FixedExpensesUpdate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "Accountant"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    total = sum(c.get("amount", 0) for c in data.categories)
    now = datetime.now(timezone.utc).isoformat()

    await db.fixed_expenses.update_one(
        {"org_id": user["org_id"], "month": data.month},
        {"$set": {
            "categories": data.categories, "total": round(total, 2),
            "updated_at": now, "updated_by": user["id"],
        }, "$setOnInsert": {
            "id": str(uuid.uuid4()), "org_id": user["org_id"], "month": data.month, "created_at": now,
        }},
        upsert=True,
    )
    return await db.fixed_expenses.find_one({"org_id": user["org_id"], "month": data.month}, {"_id": 0})


# ── Realtime Overhead ──────────────────────────────────────────────

@router.get("/overhead/realtime")
async def get_realtime_overhead(month: Optional[str] = None, user: dict = Depends(get_current_user)):
    return await compute_realtime_overhead(user["org_id"], month)


@router.get("/overhead/realtime/daily")
async def get_daily_breakdown(month: Optional[str] = None, user: dict = Depends(get_current_user)):
    result = await compute_realtime_overhead(user["org_id"], month)
    return {"month": result["month"], "daily": result["daily_breakdown"]}


@router.get("/overhead/realtime/by-project")
async def get_by_project(month: Optional[str] = None, user: dict = Depends(get_current_user)):
    result = await compute_realtime_overhead(user["org_id"], month)
    return {"month": result["month"], "projects": result["by_project"]}


@router.get("/overhead/realtime/trend")
async def get_overhead_trend(months: int = 6, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    now = datetime.now(timezone.utc)
    trend = []
    for i in range(months - 1, -1, -1):
        dt = now - __import__("datetime").timedelta(days=30 * i)
        m = dt.strftime("%Y-%m")
        result = await compute_realtime_overhead(org_id, m)
        trend.append({
            "month": m,
            "fixed_total": result["fixed_total"],
            "effective_overhead": result["effective_overhead"],
            "overhead_per_person_day": result["overhead_per_person_day"],
            "avg_working": result["avg_working_per_day"],
        })
    return {"trend": trend}
