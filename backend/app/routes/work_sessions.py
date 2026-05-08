"""
Routes - Work Sessions (BEG SiteClock).
Interval-based time tracking: start/end sessions per worker per site.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["Work Sessions"])

DEFAULT_OT = {"over_8h": 1.5, "after_20": 1.5, "weekend": 2.0}
DEFAULT_MAX_SESSION = 12
DEFAULT_WORK_HOURS = 8


# ── Pydantic Models ────────────────────────────────────────────────

class SessionStart(BaseModel):
    site_id: str
    smr_type_id: Optional[str] = None
    source_method: str = "SELF_REPORT"
    notes: Optional[str] = None


class SessionEnd(BaseModel):
    notes: Optional[str] = None


class SessionUpdate(BaseModel):
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    smr_type_id: Optional[str] = None
    notes: Optional[str] = None


class SessionSplit(BaseModel):
    splits: list  # [{ smr_type_id: str, hours: float }]


# ── Helpers ────────────────────────────────────────────────────────

async def get_ot_coefficients(org_id: str) -> dict:
    doc = await db.settings.find_one({"_id": "overtime_config", "org_id": org_id})
    if doc and doc.get("coefficients"):
        return doc["coefficients"]
    return DEFAULT_OT


async def snapshot_hourly_rate(org_id: str, worker_id: str) -> float:
    profile = await db.employee_profiles.find_one(
        {"org_id": org_id, "user_id": worker_id}, {"_id": 0}
    )
    if not profile:
        return 0
    pay_type = (profile.get("pay_type") or "Monthly").strip()
    if pay_type == "Hourly":
        return float(profile.get("hourly_rate") or 0)
    elif pay_type == "Daily":
        daily = float(profile.get("daily_rate") or profile.get("base_salary") or 0)
        return round(daily / 8, 2)
    else:  # Monthly
        monthly = float(profile.get("monthly_salary") or profile.get("base_salary") or 0)
        days = int(profile.get("working_days_per_month") or 22)
        hours = int(profile.get("standard_hours_per_day") or 8)
        total_h = days * hours
        return round(monthly / total_h, 2) if total_h > 0 else 0


def compute_duration(started: str, ended: str) -> float:
    s = datetime.fromisoformat(started.replace("Z", "+00:00"))
    e = datetime.fromisoformat(ended.replace("Z", "+00:00"))
    return round(max((e - s).total_seconds() / 3600, 0), 4)


async def detect_overtime(org_id: str, worker_id: str, date_str: str, session_ended: str, ot_cfg: dict) -> dict:
    """Detect overtime for the session based on total daily hours and time of day."""
    # Get all closed sessions for this worker today
    day_start = f"{date_str}T00:00:00"
    day_end = f"{date_str}T23:59:59"
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "worker_id": worker_id, "started_at": {"$gte": day_start, "$lte": day_end}, "ended_at": {"$ne": None}},
        {"_id": 0, "duration_hours": 1},
    ).to_list(50)
    total_hours = sum(s.get("duration_hours", 0) for s in sessions)

    result = {"is_overtime": False, "overtime_type": None, "coefficient": 1.0}

    # Check weekend
    try:
        dt = datetime.fromisoformat(session_ended.replace("Z", "+00:00"))
        weekday = dt.weekday()  # 5=Sat, 6=Sun
        if weekday >= 5:
            result = {"is_overtime": True, "overtime_type": "weekend", "coefficient": ot_cfg.get("weekend", 2.0)}
            return result
        # Check after 20:00
        if dt.hour >= 20:
            result = {"is_overtime": True, "overtime_type": "after_20", "coefficient": ot_cfg.get("after_20", 1.5)}
            return result
    except (ValueError, TypeError):
        pass

    # Check >8h total
    if total_hours > DEFAULT_WORK_HOURS:
        result = {"is_overtime": True, "overtime_type": "over_8h", "coefficient": ot_cfg.get("over_8h", 1.5)}

    return result


# ── Start Session ──────────────────────────────────────────────────

@router.post("/work-sessions/start", status_code=201)
async def start_session(data: SessionStart, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    worker_id = user["id"]
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Validate site
    project = await db.projects.find_one({"id": data.site_id, "org_id": org_id}, {"_id": 0, "id": 1, "name": 1, "status": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Site/project not found")

    from app.services.project_guards import check_project_writable
    await check_project_writable(data.site_id, org_id, "работни сесии")

    # Auto-close existing open session
    open_session = await db.work_sessions.find_one(
        {"org_id": org_id, "worker_id": worker_id, "ended_at": None}
    )
    if open_session:
        duration = compute_duration(open_session["started_at"], now_iso)
        ot_cfg = await get_ot_coefficients(org_id)
        date_str = open_session["started_at"][:10]
        ot = await detect_overtime(org_id, worker_id, date_str, now_iso, ot_cfg)
        rate = open_session.get("hourly_rate_at_date", 0)
        cost = round(duration * rate * ot["coefficient"], 2)

        await db.work_sessions.update_one(
            {"id": open_session["id"]},
            {"$set": {
                "ended_at": now_iso,
                "duration_hours": round(duration, 2),
                "is_flagged": True,
                "flag_reason": "auto_closed",
                "is_overtime": ot["is_overtime"],
                "overtime_type": ot["overtime_type"],
                "overtime_coefficient": ot["coefficient"],
                "labor_cost": cost,
                "updated_at": now_iso,
            }},
        )

    # Snapshot hourly rate
    rate = await snapshot_hourly_rate(org_id, worker_id)

    session = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "worker_id": worker_id,
        "worker_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        "site_id": data.site_id,
        "site_name": project.get("name", ""),
        "smr_type_id": data.smr_type_id,
        "started_at": now_iso,
        "ended_at": None,
        "source_method": data.source_method,
        "is_flagged": False,
        "flag_reason": None,
        "duration_hours": None,
        "is_overtime": False,
        "overtime_type": None,
        "overtime_coefficient": 1.0,
        "hourly_rate_at_date": rate,
        "labor_cost": None,
        "notes": data.notes,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    await db.work_sessions.insert_one(session)
    result = {k: v for k, v in session.items() if k != "_id"}
    if open_session:
        result["auto_closed_session_id"] = open_session["id"]
    return result


# ── End Session ────────────────────────────────────────────────────

@router.post("/work-sessions/end")
async def end_session(data: SessionEnd, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    worker_id = user["id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    open_session = await db.work_sessions.find_one(
        {"org_id": org_id, "worker_id": worker_id, "ended_at": None}
    )
    if not open_session:
        raise HTTPException(status_code=404, detail="No open session found")

    duration = compute_duration(open_session["started_at"], now_iso)
    ot_cfg = await get_ot_coefficients(org_id)
    date_str = open_session["started_at"][:10]
    ot = await detect_overtime(org_id, worker_id, date_str, now_iso, ot_cfg)
    rate = open_session.get("hourly_rate_at_date", 0)
    cost = round(duration * rate * ot["coefficient"], 2)

    notes = data.notes or open_session.get("notes")

    await db.work_sessions.update_one(
        {"id": open_session["id"]},
        {"$set": {
            "ended_at": now_iso,
            "duration_hours": round(duration, 2),
            "is_overtime": ot["is_overtime"],
            "overtime_type": ot["overtime_type"],
            "overtime_coefficient": ot["coefficient"],
            "labor_cost": cost,
            "notes": notes,
            "updated_at": now_iso,
        }},
    )
    return await db.work_sessions.find_one({"id": open_session["id"]}, {"_id": 0})


# ── List / Query ───────────────────────────────────────────────────

@router.get("/work-sessions")
async def list_sessions(
    worker_id: Optional[str] = None,
    site_id: Optional[str] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    is_flagged: Optional[bool] = None,
    is_overtime: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    from app.utils.pagination import paginate_query
    query = {"org_id": user["org_id"]}
    if worker_id:
        query["worker_id"] = worker_id
    if site_id:
        query["site_id"] = site_id
    if date:
        query["started_at"] = {"$gte": f"{date}T00:00:00", "$lte": f"{date}T23:59:59"}
    else:
        if date_from:
            query.setdefault("started_at", {})["$gte"] = f"{date_from}T00:00:00"
        if date_to:
            query.setdefault("started_at", {})["$lte"] = f"{date_to}T23:59:59"
    if is_flagged is not None:
        query["is_flagged"] = is_flagged
    if is_overtime is not None:
        query["is_overtime"] = is_overtime

    return await paginate_query(db.work_sessions, query, page, page_size, "started_at", -1)


# ── Active Sessions ────────────────────────────────────────────────

@router.get("/work-sessions/active")
async def get_active_sessions(
    site_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query = {"org_id": user["org_id"], "ended_at": None}
    if site_id:
        query["site_id"] = site_id
    items = await db.work_sessions.find(query, {"_id": 0}).sort("started_at", 1).to_list(200)
    now = datetime.now(timezone.utc).isoformat()
    for s in items:
        s["elapsed_hours"] = round(compute_duration(s["started_at"], now), 2)
    return {"items": items, "total": len(items)}


# ── My Today ───────────────────────────────────────────────────────

@router.get("/work-sessions/my-today")
async def get_my_today(user: dict = Depends(get_current_user)):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    query = {
        "org_id": user["org_id"],
        "worker_id": user["id"],
        "started_at": {"$gte": f"{today}T00:00:00", "$lte": f"{today}T23:59:59"},
    }
    items = await db.work_sessions.find(query, {"_id": 0}).sort("started_at", 1).to_list(50)

    now_iso = datetime.now(timezone.utc).isoformat()
    total_hours = 0
    total_cost = 0
    has_open = False
    for s in items:
        if s.get("ended_at"):
            total_hours += s.get("duration_hours", 0)
            total_cost += s.get("labor_cost", 0)
        else:
            elapsed = compute_duration(s["started_at"], now_iso)
            s["elapsed_hours"] = round(elapsed, 2)
            total_hours += elapsed
            has_open = True

    return {
        "items": items,
        "total_sessions": len(items),
        "total_hours": round(total_hours, 2),
        "total_cost": round(total_cost, 2),
        "has_open_session": has_open,
        "is_overtime": total_hours > DEFAULT_WORK_HOURS,
    }


# ── Summary ────────────────────────────────────────────────────────

@router.get("/work-sessions/summary")
async def get_summary(
    site_id: Optional[str] = None,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query = {"org_id": user["org_id"], "ended_at": {"$ne": None}}
    if site_id:
        query["site_id"] = site_id
    if date:
        query["started_at"] = {"$gte": f"{date}T00:00:00", "$lte": f"{date}T23:59:59"}
    elif date_from or date_to:
        query["started_at"] = {}
        if date_from:
            query["started_at"]["$gte"] = f"{date_from}T00:00:00"
        if date_to:
            query["started_at"]["$lte"] = f"{date_to}T23:59:59"

    items = await db.work_sessions.find(query, {"_id": 0}).to_list(1000)
    total_hours = sum(s.get("duration_hours", 0) for s in items)
    total_cost = sum(s.get("labor_cost", 0) for s in items)
    overtime_hours = sum(s.get("duration_hours", 0) for s in items if s.get("is_overtime"))
    workers = set(s["worker_id"] for s in items)

    return {
        "total_hours": round(total_hours, 2),
        "total_cost": round(total_cost, 2),
        "workers_count": len(workers),
        "overtime_hours": round(overtime_hours, 2),
        "sessions_count": len(items),
    }


# ── Split Session ──────────────────────────────────────────────────

@router.post("/work-sessions/{session_id}/split")
async def split_session(session_id: str, data: SessionSplit, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    session = await db.work_sessions.find_one({"id": session_id, "org_id": user["org_id"]})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.get("ended_at"):
        raise HTTPException(status_code=400, detail="Cannot split open session")

    total_split_hours = sum(s.get("hours", 0) for s in data.splits)
    if total_split_hours <= 0:
        raise HTTPException(status_code=400, detail="Split hours must be > 0")

    now_iso = datetime.now(timezone.utc).isoformat()
    rate = session.get("hourly_rate_at_date", 0)
    coeff = session.get("overtime_coefficient", 1.0)
    start_dt = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))

    new_sessions = []
    cursor = start_dt
    for sp in data.splits:
        hours = sp.get("hours", 0)
        end_dt = cursor + timedelta(hours=hours)
        ns = {
            "id": str(uuid.uuid4()),
            "org_id": session["org_id"],
            "worker_id": session["worker_id"],
            "worker_name": session.get("worker_name", ""),
            "site_id": session["site_id"],
            "site_name": session.get("site_name", ""),
            "smr_type_id": sp.get("smr_type_id"),
            "started_at": cursor.isoformat(),
            "ended_at": end_dt.isoformat(),
            "source_method": "MANUAL",
            "is_flagged": False,
            "flag_reason": None,
            "duration_hours": round(hours, 2),
            "is_overtime": session.get("is_overtime", False),
            "overtime_type": session.get("overtime_type"),
            "overtime_coefficient": coeff,
            "hourly_rate_at_date": rate,
            "labor_cost": round(hours * rate * coeff, 2),
            "notes": f"Split from {session_id[:8]}",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        new_sessions.append(ns)
        cursor = end_dt

    # Mark original as split
    await db.work_sessions.update_one(
        {"id": session_id},
        {"$set": {"is_flagged": True, "flag_reason": "split", "updated_at": now_iso}},
    )
    if new_sessions:
        await db.work_sessions.insert_many(new_sessions)

    return {
        "ok": True,
        "original_id": session_id,
        "new_sessions": [{k: v for k, v in ns.items() if k != "_id"} for ns in new_sessions],
    }


# ── Overtime Report ────────────────────────────────────────────────

@router.get("/work-sessions/overtime")
async def get_overtime_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    worker_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query = {"org_id": user["org_id"], "ended_at": {"$ne": None}}
    if worker_id:
        query["worker_id"] = worker_id
    if date_from or date_to:
        query["started_at"] = {}
        if date_from:
            query["started_at"]["$gte"] = f"{date_from}T00:00:00"
        if date_to:
            query["started_at"]["$lte"] = f"{date_to}T23:59:59"

    items = await db.work_sessions.find(query, {"_id": 0}).to_list(2000)

    workers = {}
    for s in items:
        wid = s["worker_id"]
        if wid not in workers:
            workers[wid] = {"name": s.get("worker_name", ""), "regular_hours": 0, "overtime_hours": 0, "overtime_cost": 0, "total_cost": 0}
        cost = s.get("labor_cost", 0)
        hours = s.get("duration_hours", 0)
        workers[wid]["total_cost"] += cost
        if s.get("is_overtime"):
            workers[wid]["overtime_hours"] += hours
            workers[wid]["overtime_cost"] += cost
        else:
            workers[wid]["regular_hours"] += hours

    result = []
    for wid, w in workers.items():
        w["worker_id"] = wid
        w["regular_hours"] = round(w["regular_hours"], 2)
        w["overtime_hours"] = round(w["overtime_hours"], 2)
        w["overtime_cost"] = round(w["overtime_cost"], 2)
        w["total_cost"] = round(w["total_cost"], 2)
        result.append(w)

    return {"workers": result, "total": len(result)}


# ── Update (Admin/Manager) ────────────────────────────────────────

@router.put("/work-sessions/{session_id}")
async def update_session(session_id: str, data: SessionUpdate, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    session = await db.work_sessions.find_one({"id": session_id, "org_id": user["org_id"]})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    update = {}
    if data.started_at is not None:
        update["started_at"] = data.started_at
    if data.ended_at is not None:
        update["ended_at"] = data.ended_at
    if data.smr_type_id is not None:
        update["smr_type_id"] = data.smr_type_id
    if data.notes is not None:
        update["notes"] = data.notes

    # Recalculate if times changed
    started = update.get("started_at", session["started_at"])
    ended = update.get("ended_at", session.get("ended_at"))
    if ended:
        duration = compute_duration(started, ended)
        update["duration_hours"] = round(duration, 2)
        rate = session.get("hourly_rate_at_date", 0)
        ot_cfg = await get_ot_coefficients(user["org_id"])
        ot = await detect_overtime(user["org_id"], session["worker_id"], started[:10], ended, ot_cfg)
        update["is_overtime"] = ot["is_overtime"]
        update["overtime_type"] = ot["overtime_type"]
        update["overtime_coefficient"] = ot["coefficient"]
        update["labor_cost"] = round(duration * rate * ot["coefficient"], 2)

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.work_sessions.update_one({"id": session_id}, {"$set": update})
    return await db.work_sessions.find_one({"id": session_id}, {"_id": 0})


# ── Delete (Admin only, flagged only) ──────────────────────────────

@router.delete("/work-sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin only")

    session = await db.work_sessions.find_one({"id": session_id, "org_id": user["org_id"]})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.get("is_flagged"):
        raise HTTPException(status_code=400, detail="Can only delete flagged sessions")

    await db.work_sessions.delete_one({"id": session_id})
    return {"ok": True}
