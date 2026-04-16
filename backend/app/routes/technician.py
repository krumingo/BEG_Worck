"""
Routes - Technician Mobile View.
Aggregates data from existing modules for mobile-first daily reporting.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user

router = APIRouter(tags=["Technician"])


# ── Models ─────────────────────────────────────────────────────────

class DailyReportEntry(BaseModel):
    worker_id: Optional[str] = None
    worker_name: Optional[str] = None
    smr_type: str
    smr_subtype: Optional[str] = None
    hours: float
    notes: Optional[str] = None
    location_id: Optional[str] = None


class DailyReportSubmit(BaseModel):
    project_id: str
    date: Optional[str] = None
    entries: List[DailyReportEntry]
    general_notes: Optional[str] = None
    photos: List[str] = []


class QuickSMR(BaseModel):
    project_id: str
    smr_type: str
    description: Optional[str] = None
    qty: float = 1
    unit: str = "m2"
    location_id: Optional[str] = None
    photos: List[str] = []


class MaterialRequestItem(BaseModel):
    item_name: str
    qty: float
    unit: str = "бр"
    notes: Optional[str] = None


class MaterialRequestSubmit(BaseModel):
    project_id: str
    items: List[MaterialRequestItem]
    urgent: bool = False


class EquipmentRequest(BaseModel):
    project_id: str
    item_id: Optional[str] = None
    item_description: Optional[str] = None
    needed_from: str
    needed_to: Optional[str] = None
    notes: Optional[str] = None


# ── Helper: snapshot hourly rate ───────────────────────────────────

async def _get_hourly_rate(org_id: str, worker_id: str) -> float:
    profile = await db.employee_profiles.find_one(
        {"org_id": org_id, "user_id": worker_id}, {"_id": 0}
    )
    if not profile:
        return 0
    pay = (profile.get("pay_type") or "Monthly").strip()
    if pay == "Hourly":
        return float(profile.get("hourly_rate") or 0)
    elif pay == "Daily":
        return round(float(profile.get("daily_rate") or profile.get("base_salary") or 0) / 8, 2)
    else:
        ms = float(profile.get("monthly_salary") or profile.get("base_salary") or 0)
        days = int(profile.get("working_days_per_month") or 22)
        hours = int(profile.get("standard_hours_per_day") or 8)
        return round(ms / max(days * hours, 1), 2)


# ── My Sites ───────────────────────────────────────────────────────

@router.get("/technician/my-sites")
async def my_sites(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    uid = user["id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get assigned projects
    if user["role"] in ["Admin", "Owner", "SiteManager"]:
        projects = await db.projects.find(
            {"org_id": org_id, "status": {"$in": ["Active", "Draft"]}},
            {"_id": 0, "id": 1, "name": 1, "code": 1, "address_text": 1, "owner_id": 1},
        ).to_list(50)
    else:
        memberships = await db.project_team.find(
            {"user_id": uid, "active": True}, {"_id": 0, "project_id": 1}
        ).to_list(50)
        pids = [m["project_id"] for m in memberships]
        projects = await db.projects.find(
            {"org_id": org_id, "id": {"$in": pids}},
            {"_id": 0, "id": 1, "name": 1, "code": 1, "address_text": 1},
        ).to_list(50)

    result = []
    for p in projects:
        pid = p["id"]

        # Today sessions
        sessions = await db.work_sessions.find(
            {"org_id": org_id, "site_id": pid, "started_at": {"$gte": f"{today}T00:00:00", "$lte": f"{today}T23:59:59"}},
            {"_id": 0, "worker_name": 1, "duration_hours": 1, "smr_type_id": 1},
        ).to_list(100)
        today_sessions = [{"worker_name": s.get("worker_name", ""), "hours": round(s.get("duration_hours") or 0, 1), "smr_type": s.get("smr_type_id", "")} for s in sessions]

        # Pending material requests
        pending_reqs = await db.material_requests.count_documents(
            {"org_id": org_id, "project_id": pid, "status": {"$in": ["draft", "submitted"]}}
        )

        # Has report today
        report = await db.employee_daily_reports.find_one(
            {"org_id": org_id, "project_id": pid, "date": today}
        )
        if not report:
            report = await db.work_reports.find_one(
                {"org_id": org_id, "project_id": pid, "date": today}
            )

        # Daily reports for this project today
        drafts_today = await db.employee_daily_reports.find(
            {"org_id": org_id, "project_id": pid, "date": today, "worker_id": {"$exists": True}},
            {"_id": 0, "worker_id": 1, "status": 1, "hours": 1},
        ).to_list(100)
        reported_workers = len(set(d.get("worker_id") for d in drafts_today))
        reported_hours = round(sum(d.get("hours", 0) for d in drafts_today), 1)
        submitted_count = sum(1 for d in drafts_today if (d.get("status") or "").upper() == "SUBMITTED")
        approved_count = len(set(d.get("worker_id") for d in drafts_today if (d.get("status") or "").upper() == "APPROVED"))

        # Roster today
        roster = await db.site_daily_rosters.find_one(
            {"org_id": org_id, "project_id": pid, "date": today},
            {"_id": 0, "workers": 1},
        )
        roster_count = len(roster.get("workers", [])) if roster else 0

        result.append({
            "project_id": pid,
            "name": p.get("name", ""),
            "code": p.get("code", ""),
            "address_text": p.get("address_text", ""),
            "today_sessions": today_sessions,
            "today_hours": reported_hours if reported_hours > 0 else round(sum(s.get("duration_hours") or 0 for s in sessions), 1),
            "today_workers": reported_workers if reported_workers > 0 else len(set(s.get("worker_name") for s in sessions)),
            "roster_count": roster_count,
            "reported_workers": reported_workers,
            "reported_hours": reported_hours,
            "submitted_count": submitted_count,
            "approved_count": approved_count,
            "pending_requests": pending_reqs,
            "has_report_today": reported_workers > 0,
        })

    return {"sites": result, "total": len(result)}


# ── Object Detail ──────────────────────────────────────────────────

@router.get("/technician/site/{project_id}/detail")
async def get_site_detail(project_id: str, user: dict = Depends(get_current_user)):
    """Rich object detail for technician: info, contacts, counters, photos."""
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    project = await db.projects.find_one(
        {"id": project_id, "org_id": org_id},
        {"_id": 0, "id": 1, "name": 1, "code": 1, "address_text": 1,
         "structured_address": 1, "contacts": 1, "object_details": 1,
         "object_type": 1, "notes": 1},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sa = project.get("structured_address") or {}
    contacts = project.get("contacts") or {}
    od = project.get("object_details") or {}

    # Counters
    # "На обекта" from attendance_entries (source of truth)
    att_today = await db.attendance_entries.find(
        {"org_id": org_id, "project_id": project_id, "date": today,
         "status": {"$in": ["Present", "Late"]}},
        {"_id": 0, "user_id": 1},
    ).to_list(200)
    on_site_count = len(att_today)

    # Fallback to roster if no attendance_entries yet
    roster = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": today}, {"_id": 0, "workers": 1}
    )
    roster_count = len(roster.get("workers", [])) if roster else 0
    if on_site_count == 0 and roster_count > 0:
        on_site_count = roster_count

    drafts_today = await db.employee_daily_reports.find(
        {"org_id": org_id, "project_id": project_id, "date": today,
         "status": {"$in": ["Draft", "Submitted", "SUBMITTED", "APPROVED"]}},
        {"_id": 0, "worker_id": 1, "hours": 1},
    ).to_list(200)
    reported_workers = len(set(d.get("worker_id") for d in drafts_today))
    reported_hours = round(sum(d.get("hours", 0) for d in drafts_today), 1)

    # Guidance photos (from media linked to project context)
    photos = await db.media_files.find(
        {"org_id": org_id, "context_type": "project", "context_id": project_id},
        {"_id": 0, "id": 1, "url": 1, "filename": 1},
    ).sort("created_at", -1).to_list(6)

    return {
        "project_id": project_id,
        "name": project.get("name", ""),
        "code": project.get("code", ""),
        "address_text": project.get("address_text", ""),
        "address": {
            "city": sa.get("city", ""),
            "district": sa.get("district", ""),
            "street": sa.get("street", ""),
            "block": sa.get("block", ""),
            "entrance": sa.get("entrance", ""),
            "floor": sa.get("floor", ""),
            "apartment": sa.get("apartment", ""),
            "postal_code": sa.get("postal_code", ""),
            "notes": sa.get("notes", ""),
        },
        "contact_owner": contacts.get("owner") or {},
        "contact_responsible": contacts.get("responsible") or {},
        "object_type": project.get("object_type", ""),
        "object_details": {
            "floors_count": od.get("floors_count"),
            "is_inhabited": od.get("is_inhabited", False),
            "parking_available": od.get("parking_available", False),
            "elevator_available": od.get("elevator_available", False),
            "access_notes": od.get("access_notes", ""),
        },
        "counters": {
            "roster_count": on_site_count,
            "reported_workers": reported_workers,
            "reported_hours": reported_hours,
        },
        "guidance_photos": [{"id": p["id"], "url": p["url"], "filename": p.get("filename", "")} for p in photos],
    }


# ── Site Tasks ─────────────────────────────────────────────────────

@router.get("/technician/site/{project_id}/tasks")
async def site_tasks(project_id: str, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]

    # Priority order: 1=budget, 2=offer, 3=analysis, 4=missing_smr, 5=history
    SOURCE_PRIORITY = {"budget": 1, "offer_approved": 2, "offer": 3, "analysis": 4, "missing_smr": 5, "extra_draft": 6, "history": 7}

    # Dev/test noise patterns (case-insensitive prefix check)
    NOISE_PREFIXES = ("test_", "тест_", "dummy", "sample", "todo", "tmp_")

    seen = {}  # key(lower) → task dict
    primary_count = 0  # count from sources 1-4

    def _is_noise(name: str) -> bool:
        low = name.lower()
        return any(low.startswith(p) for p in NOISE_PREFIXES)

    def _add(smr_type, smr_subtype="", unit="m2", qty=0, source=""):
        name = (smr_type or "").strip()
        if not name:
            return
        if _is_noise(name):
            return
        key = name.lower()
        existing = seen.get(key)
        if existing:
            # Keep higher-priority source
            if SOURCE_PRIORITY.get(source, 9) < SOURCE_PRIORITY.get(existing["source"], 9):
                existing["smr_type"] = name
                existing["smr_subtype"] = smr_subtype
                existing["source"] = source
                if qty > 0:
                    existing["qty_total"] = qty
                if unit != "m2":
                    existing["unit"] = unit
            return
        seen[key] = {
            "smr_type": name, "smr_subtype": smr_subtype,
            "unit": unit, "qty_total": qty, "qty_completed": 0,
            "status": "active", "source": source,
        }

    # 1. Activity budgets (highest priority)
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "type": 1, "subtype": 1},
    ).to_list(100)
    for b in budgets:
        _add(b["type"], b.get("subtype", ""), source="budget")

    # 2. Offer lines — prioritize Accepted, then Sent, then Draft
    offers = await db.offers.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["Accepted", "Sent", "Draft"]}},
        {"_id": 0, "lines": 1, "status": 1, "offer_no": 1},
    ).to_list(50)
    # Sort: Accepted first
    offers.sort(key=lambda o: 0 if o.get("status") == "Accepted" else (1 if o.get("status") == "Sent" else 2))
    for o in offers:
        offer_status = o.get("status", "Draft")
        for ln in o.get("lines", []):
            t = ln.get("activity_type") or ln.get("activity_name") or ln.get("description", "")
            if t:
                source = "offer_approved" if offer_status == "Accepted" else "offer"
                _add(t, ln.get("activity_subtype", ""), ln.get("unit", "m2"), ln.get("qty", 0), source)

    # 3. SMR analysis lines
    analyses = await db.smr_analyses.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "lines": 1},
    ).to_list(50)
    for a in analyses:
        for ln in a.get("lines", []):
            if ln.get("smr_type"):
                _add(ln["smr_type"], ln.get("smr_subtype", ""), ln.get("unit", "m2"), ln.get("qty", 0), "analysis")

    # 4. Missing SMR records
    missing = await db.missing_smr.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$nin": ["closed", "rejected_by_client"]}},
        {"_id": 0, "smr_type": 1, "activity_type": 1, "unit": 1, "qty": 1},
    ).to_list(100)
    for m in missing:
        t = m.get("smr_type") or m.get("activity_type", "")
        if t:
            _add(t, "", m.get("unit", "m2"), m.get("qty", 0), "missing_smr")

    # 4b. Extra work drafts (user-created SMR entries)
    extra_drafts = await db.extra_work_drafts.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$nin": ["in_offer", "closed"]}},
        {"_id": 0, "title": 1, "unit": 1, "qty": 1},
    ).to_list(100)
    for ed in extra_drafts:
        t = ed.get("title", "")
        if t:
            _add(t, "", ed.get("unit", "m2"), ed.get("qty", 0), "extra_draft")

    primary_count = len(seen)

    # 5. History (only if primary sources yielded < 3 tasks)
    if primary_count < 3:
        distinct_types = await db.work_sessions.distinct(
            "smr_type_id", {"org_id": org_id, "site_id": project_id, "smr_type_id": {"$ne": None}}
        )
        for t in distinct_types:
            if t:
                _add(t, source="history")

    # Sort: by source priority, then alphabetically
    SOURCE_LABELS = {
        "budget": "Бюджет", "offer_approved": "Одобрена оферта", "offer": "Оферта",
        "analysis": "Анализ", "missing_smr": "Липсващо СМР", "extra_draft": "Допълнително",
        "history": "История",
    }
    tasks = sorted(seen.values(), key=lambda x: (SOURCE_PRIORITY.get(x["source"], 9), x["smr_type"]))
    for t in tasks:
        t["source_label"] = SOURCE_LABELS.get(t["source"], t["source"])

    return {"tasks": tasks, "total": len(tasks)}


# ── Roster (Присъстващи днес) ─────────────────────────────────────

class RosterSubmit(BaseModel):
    date: Optional[str] = None
    workers: list  # [{worker_id, worker_name, status?}]


class AttendanceRosterSubmit(BaseModel):
    date: Optional[str] = None
    workers: list  # [{worker_id, worker_name, status}]
    # status: Present, Leave, SickLeave, Absent, Other


@router.get("/technician/site/{project_id}/roster")
async def get_roster(project_id: str, date: Optional[str] = None, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": d}, {"_id": 0}
    )
    if not doc:
        return {"project_id": project_id, "date": d, "workers": [], "id": None}

    # Enrich with attendance status from attendance_entries
    worker_ids = [w.get("worker_id") for w in doc.get("workers", []) if w.get("worker_id")]
    att_entries = {}
    if worker_ids:
        entries = await db.attendance_entries.find(
            {"org_id": org_id, "date": d, "user_id": {"$in": worker_ids}},
            {"_id": 0, "user_id": 1, "status": 1},
        ).to_list(200)
        att_entries = {e["user_id"]: e["status"] for e in entries}

    for w in doc.get("workers", []):
        w["status"] = att_entries.get(w.get("worker_id"), w.get("status", "Present"))

    return doc


@router.post("/technician/site/{project_id}/attendance", status_code=200)
async def save_site_attendance(project_id: str, data: AttendanceRosterSubmit, user: dict = Depends(get_current_user)):
    """Save daily attendance for workers on a site. Creates attendance_entries (source of truth)."""
    org_id = user["org_id"]
    d = data.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()

    workers = []
    submitted_ids = set()
    for w in data.workers:
        wid = w.get("worker_id") or w.get("id", "")
        if not wid:
            continue
        wname = w.get("worker_name") or w.get("name", "")
        status = w.get("status") or "Present"
        if not status:
            status = "Present"
        workers.append({"worker_id": wid, "worker_name": wname, "status": status})
        submitted_ids.add(wid)

        # Upsert attendance_entry (source of truth)
        existing_att = await db.attendance_entries.find_one(
            {"org_id": org_id, "date": d, "user_id": wid}
        )
        if existing_att:
            await db.attendance_entries.update_one(
                {"id": existing_att["id"]},
                {"$set": {"status": status, "project_id": project_id, "updated_at": now, "note": ""}}
            )
        else:
            await db.attendance_entries.insert_one({
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "date": d,
                "project_id": project_id,
                "user_id": wid,
                "status": status,
                "note": "",
                "marked_at": now,
                "marked_by_user_id": user["id"],
                "source": "TechPortal",
            })

    # Remove attendance_entries for workers who were in previous roster but not in the new list
    prev_roster = await db.site_daily_rosters.find_one({"org_id": org_id, "project_id": project_id, "date": d})
    if prev_roster:
        prev_ids = set(w.get("worker_id") for w in prev_roster.get("workers", []))
        removed_ids = prev_ids - submitted_ids
        if removed_ids:
            await db.attendance_entries.delete_many(
                {"org_id": org_id, "date": d, "project_id": project_id, "user_id": {"$in": list(removed_ids)}}
            )

    # Also save/update roster
    existing_roster = await db.site_daily_rosters.find_one({"org_id": org_id, "project_id": project_id, "date": d})
    if existing_roster:
        await db.site_daily_rosters.update_one({"id": existing_roster["id"]}, {"$set": {
            "workers": workers, "updated_at": now,
        }})
    else:
        await db.site_daily_rosters.insert_one({
            "id": str(uuid.uuid4()), "org_id": org_id, "project_id": project_id,
            "date": d, "workers": workers,
            "created_by": user["id"], "created_at": now, "updated_at": now,
        })

    # Count present (Present/Late only)
    present_count = sum(1 for w in workers if w["status"] in ("Present", "Late"))

    return {
        "project_id": project_id,
        "date": d,
        "total": len(workers),
        "present": present_count,
        "workers": workers,
    }


@router.post("/technician/site/{project_id}/roster")
async def save_roster(project_id: str, data: RosterSubmit, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    d = data.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()

    workers = [{"worker_id": w.get("worker_id") or w.get("id", ""), "worker_name": w.get("worker_name") or w.get("name", "")} for w in data.workers if w.get("worker_id") or w.get("id")]

    existing = await db.site_daily_rosters.find_one({"org_id": org_id, "project_id": project_id, "date": d})
    if existing:
        await db.site_daily_rosters.update_one({"id": existing["id"]}, {"$set": {
            "workers": workers, "updated_at": now,
        }})
        return await db.site_daily_rosters.find_one({"id": existing["id"]}, {"_id": 0})

    doc = {
        "id": str(uuid.uuid4()), "org_id": org_id, "project_id": project_id,
        "date": d, "workers": workers,
        "created_by": user["id"], "created_at": now, "updated_at": now,
    }
    await db.site_daily_rosters.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/technician/site/{project_id}/roster/suggestions")
async def roster_suggestions(project_id: str, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    now = datetime.now(timezone.utc)
    cutoff = (now - __import__("datetime").timedelta(days=14)).isoformat()

    # Recent workers from work_sessions + rosters
    recent_ids = set()
    recent = []

    # From past rosters
    past_rosters = await db.site_daily_rosters.find(
        {"org_id": org_id, "project_id": project_id, "date": {"$gte": cutoff[:10]}},
        {"_id": 0, "workers": 1},
    ).to_list(30)
    for r in past_rosters:
        for w in r.get("workers", []):
            wid = w.get("worker_id")
            if wid and wid not in recent_ids:
                recent_ids.add(wid)
                recent.append({"worker_id": wid, "worker_name": w.get("worker_name", ""), "source": "recent"})

    # From work_sessions
    sessions = await db.work_sessions.find(
        {"org_id": org_id, "site_id": project_id, "started_at": {"$gte": cutoff}},
        {"_id": 0, "worker_id": 1, "worker_name": 1},
    ).to_list(500)
    for s in sessions:
        wid = s.get("worker_id")
        if wid and wid not in recent_ids:
            recent_ids.add(wid)
            recent.append({"worker_id": wid, "worker_name": s.get("worker_name", ""), "source": "recent"})

    # All active employees
    all_employees = []
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "active": True}, {"_id": 0, "user_id": 1}
    ).to_list(200)
    profile_ids = {p["user_id"] for p in profiles}

    users = await db.users.find(
        {"org_id": org_id, "id": {"$in": list(profile_ids)}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1},
    ).to_list(200)
    for u in users:
        name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
        all_employees.append({"worker_id": u["id"], "worker_name": name, "source": "all"})

    # If no profiles, fall back to all org users
    if not all_employees:
        all_users = await db.users.find(
            {"org_id": org_id},
            {"_id": 0, "id": 1, "first_name": 1, "last_name": 1},
        ).to_list(200)
        for u in all_users:
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            all_employees.append({"worker_id": u["id"], "worker_name": name, "source": "all"})

    return {"recent": recent, "all": all_employees}


@router.post("/technician/site/{project_id}/roster/copy-yesterday")
async def copy_yesterday_roster(project_id: str, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()

    # Find most recent roster before today
    prev = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": {"$lt": today}},
        {"_id": 0}, sort=[("date", -1)],
    )
    if not prev or not prev.get("workers"):
        raise HTTPException(status_code=404, detail="No previous roster found")

    existing = await db.site_daily_rosters.find_one({"org_id": org_id, "project_id": project_id, "date": today})
    if existing:
        await db.site_daily_rosters.update_one({"id": existing["id"]}, {"$set": {
            "workers": prev["workers"], "updated_at": now,
        }})
        return await db.site_daily_rosters.find_one({"id": existing["id"]}, {"_id": 0})

    doc = {
        "id": str(uuid.uuid4()), "org_id": org_id, "project_id": project_id,
        "date": today, "workers": prev["workers"],
        "created_by": user["id"], "created_at": now, "updated_at": now,
    }
    await db.site_daily_rosters.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


# ── Roster: Enriched + Available People ────────────────────────────

@router.get("/technician/site/{project_id}/roster/enriched")
async def get_enriched_roster(project_id: str, user: dict = Depends(get_current_user)):
    """Get today's roster with profile info (photo, position, daily hours)."""
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    doc = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": today}, {"_id": 0}
    )
    workers_raw = doc.get("workers", []) if doc else []

    # Get attendance status for all workers
    raw_ids = [w.get("worker_id", "") for w in workers_raw if w.get("worker_id")]
    att_map = {}
    if raw_ids:
        att_entries = await db.attendance_entries.find(
            {"org_id": org_id, "date": today, "user_id": {"$in": raw_ids}},
            {"_id": 0, "user_id": 1, "status": 1},
        ).to_list(200)
        att_map = {e["user_id"]: e["status"] for e in att_entries}

    workers = []
    for w in workers_raw:
        wid = w.get("worker_id", "")
        # Get profile
        profile = await db.employee_profiles.find_one(
            {"org_id": org_id, "user_id": wid},
            {"_id": 0, "avatar_url": 1, "position": 1, "role": 1},
        )
        # Get avatar from users collection (primary source)
        user_doc = await db.users.find_one(
            {"id": wid}, {"_id": 0, "avatar_url": 1}
        )
        avatar = (user_doc or {}).get("avatar_url") or (profile or {}).get("avatar_url")
        # Get today's hours: ALL projects for this worker (cross-project total)
        all_today = await db.employee_daily_reports.find(
            {"org_id": org_id, "worker_id": wid, "date": today},
            {"_id": 0, "hours": 1, "project_id": 1},
        ).to_list(50)
        day_total = round(sum(r.get("hours", 0) for r in all_today), 2)
        this_project_hours = round(sum(r.get("hours", 0) for r in all_today if r.get("project_id") == project_id), 2)
        normal_hours = min(day_total, 8)
        overtime_hours = round(max(day_total - 8, 0), 2)
        multi_project = len(set(r.get("project_id") for r in all_today if r.get("project_id"))) > 1

        workers.append({
            "worker_id": wid,
            "worker_name": w.get("worker_name", ""),
            "avatar_url": avatar,
            "position": (profile or {}).get("position") or (profile or {}).get("role", ""),
            "status": att_map.get(wid) or w.get("status", "Present"),
            "total_hours": day_total,
            "this_project_hours": this_project_hours,
            "normal_hours": normal_hours,
            "overtime_hours": overtime_hours,
            "has_overtime": overtime_hours > 0,
            "multi_project": multi_project,
        })

    return {"workers": workers, "total": len(workers), "date": today}


@router.get("/technician/site/{project_id}/roster/available")
async def get_available_people(project_id: str, user: dict = Depends(get_current_user)):
    """Get all active employees NOT already in today's roster for this site."""
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Current roster IDs
    doc = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": today}, {"_id": 0, "workers": 1}
    )
    existing_ids = {w.get("worker_id") for w in (doc or {}).get("workers", [])}

    # Recent workers on this site (last 14 days)
    cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=14)).strftime("%Y-%m-%d")
    recent_ids = set()
    past_rosters = await db.site_daily_rosters.find(
        {"org_id": org_id, "project_id": project_id, "date": {"$gte": cutoff}},
        {"_id": 0, "workers": 1},
    ).to_list(30)
    for r in past_rosters:
        for w in r.get("workers", []):
            recent_ids.add(w.get("worker_id"))

    # All active profiles
    profiles = await db.employee_profiles.find(
        {"org_id": org_id, "active": True},
        {"_id": 0, "user_id": 1, "avatar_url": 1, "position": 1, "role": 1},
    ).to_list(200)
    profile_map = {p["user_id"]: p for p in profiles}
    profile_ids = set(profile_map.keys())
    positions_set = set()

    # All org users (with avatar from users collection)
    all_users = await db.users.find(
        {"org_id": org_id},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1},
    ).to_list(200)

    available = []
    for u in all_users:
        uid = u["id"]
        if uid in existing_ids:
            continue
        p = profile_map.get(uid, {})
        name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
        pos = p.get("position") or p.get("role", "")
        if pos:
            positions_set.add(pos)
        available.append({
            "worker_id": uid,
            "worker_name": name,
            "avatar_url": u.get("avatar_url") or p.get("avatar_url"),
            "position": pos,
            "has_profile": uid in profile_ids,
            "recent_on_site": uid in recent_ids,
        })

    available.sort(key=lambda x: (0 if x["recent_on_site"] else 1, x["worker_name"]))
    return {"available": available, "total": len(available), "positions": sorted(positions_set)}


@router.post("/technician/site/{project_id}/roster/remove-worker")
async def remove_worker_from_roster(project_id: str, data: dict, user: dict = Depends(get_current_user)):
    """Remove a single worker from today's roster."""
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    worker_id = data.get("worker_id")
    if not worker_id:
        raise HTTPException(status_code=400, detail="worker_id required")

    doc = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": today}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="No roster for today")

    now = datetime.now(timezone.utc).isoformat()
    new_workers = [w for w in doc.get("workers", []) if w.get("worker_id") != worker_id]
    await db.site_daily_rosters.update_one({"id": doc["id"]}, {"$set": {"workers": new_workers, "updated_at": now}})
    return {"ok": True, "remaining": len(new_workers)}


@router.post("/technician/site/{project_id}/roster/add-workers")
async def add_workers_to_roster(project_id: str, data: dict, user: dict = Depends(get_current_user)):
    """Add workers to today's roster (without replacing existing ones)."""
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_workers = data.get("workers", [])
    if not new_workers:
        raise HTTPException(status_code=400, detail="workers list required")

    now = datetime.now(timezone.utc).isoformat()
    doc = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": today}
    )

    if doc:
        existing = doc.get("workers", [])
        existing_ids = {w.get("worker_id") for w in existing}
        for nw in new_workers:
            if nw.get("worker_id") not in existing_ids:
                existing.append({"worker_id": nw["worker_id"], "worker_name": nw.get("worker_name", "")})
        await db.site_daily_rosters.update_one({"id": doc["id"]}, {"$set": {"workers": existing, "updated_at": now}})
    else:
        import uuid as _uuid
        doc = {
            "id": str(_uuid.uuid4()), "org_id": org_id, "project_id": project_id,
            "date": today, "workers": [{"worker_id": w["worker_id"], "worker_name": w.get("worker_name", "")} for w in new_workers],
            "created_by": user["id"], "created_at": now, "updated_at": now,
        }
        await db.site_daily_rosters.insert_one(doc)

    result = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": project_id, "date": today}, {"_id": 0}
    )
    return {k: v for k, v in result.items() if k != "_id"}


# ── Daily Report (DRAFT — NO work_sessions) ───────────────────────

@router.post("/technician/daily-report")
async def submit_daily_report(data: DailyReportSubmit, user: dict = Depends(get_current_user)):
    """
    DRAFT ONLY: Saves to employee_daily_reports with status=Draft.
    work_sessions are created on APPROVE, not here.
    See /app/memory/SOURCE_OF_TRUTH.md for full policy.
    """
    org_id = user["org_id"]
    today = data.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()

    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get roster for validation
    roster = await db.site_daily_rosters.find_one(
        {"org_id": org_id, "project_id": data.project_id, "date": today}, {"_id": 0}
    )

    # Check project status — block if Completed/Cancelled/Archived
    from app.services.project_guards import check_project_writable
    await check_project_writable(data.project_id, org_id, "отчети")

    roster_ids = set()
    if roster:
        roster_ids = {w.get("worker_id") for w in roster.get("workers", [])}

    # Get known SMR types
    known_types = set()
    budgets = await db.activity_budgets.find(
        {"org_id": org_id, "project_id": data.project_id}, {"_id": 0, "type": 1}
    ).to_list(100)
    for b in budgets:
        known_types.add(b["type"].lower())
    offers = await db.offers.find(
        {"org_id": org_id, "project_id": data.project_id}, {"_id": 0, "lines": 1}
    ).to_list(50)
    for o in offers:
        for ln in o.get("lines", []):
            t = ln.get("activity_type") or ln.get("activity_name", "")
            if t:
                known_types.add(t.lower())
    analyses = await db.smr_analyses.find(
        {"org_id": org_id, "project_id": data.project_id}, {"_id": 0, "lines": 1}
    ).to_list(50)
    for a in analyses:
        for ln in a.get("lines", []):
            if ln.get("smr_type"):
                known_types.add(ln["smr_type"].lower())

    missing_smr_created = []
    draft_ids = []

    for entry in data.entries:
        wid = entry.worker_id or user["id"]

        # Validate worker is in roster (if roster exists)
        if roster_ids and wid not in roster_ids and wid != user["id"]:
            raise HTTPException(status_code=400, detail=f"Worker {wid} not in today's roster")

        # Get worker name
        worker_name = entry.worker_name
        if not worker_name and roster:
            for rw in roster.get("workers", []):
                if rw.get("worker_id") == wid:
                    worker_name = rw.get("worker_name", "")
                    break
        if not worker_name:
            worker_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()

        # Determine SMR source
        smr_source = "known" if entry.smr_type.lower() in known_types else "manual"

        # Create DRAFT in employee_daily_reports
        is_admin_entry = user["role"] in ["Admin", "Owner", "SiteManager"]
        draft = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "project_id": data.project_id,
            "date": today,
            "worker_id": wid,
            "worker_name": worker_name,
            "smr_type": entry.smr_type,
            "smr_subtype": entry.smr_subtype or "",
            "hours": round(entry.hours, 2),
            "notes": entry.notes or "",
            "location_id": entry.location_id,
            "smr_source": smr_source,
            "status": "Draft",
            "submitted_by": user["id"],
            "entered_by_admin": is_admin_entry,
            "entry_mode": "admin_field_portal" if is_admin_entry else "technician_portal",
            "created_at": now,
            "updated_at": now,
        }
        await db.employee_daily_reports.insert_one(draft)
        draft_ids.append(draft["id"])

        # Check if SMR type is unknown → create missing_smr
        if smr_source == "manual":
            ms = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "project_id": data.project_id,
                "project_name": project.get("name", ""),
                "smr_type": entry.smr_type,
                "activity_type": entry.smr_type,
                "activity_subtype": entry.smr_subtype or "",
                "qty": entry.hours,
                "unit": "часа",
                "source": "mobile",
                "status": "reported",
                "urgency_type": "emergency",
                "emergency_reason": "Въведено от терена",
                "notes": entry.notes,
                "created_at": now,
                "updated_at": now,
                "created_by": user["id"],
                "created_by_name": worker_name,
                "attachments": [],
                "client_approval": None,
                "ai_estimated_price": None,
                "ai_price_breakdown": None,
                "offer_line_ids": [],
                "linked_extra_work_id": None,
                "linked_offer_id": None,
                "linked_change_order_id": None,
            }
            await db.missing_smr.insert_one(ms)
            missing_smr_created.append(ms["id"])

    # Create/update work_report summary
    total_hours = round(sum(e.hours for e in data.entries), 2)
    report = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.project_id,
        "user_id": user["id"],
        "date": today,
        "submitted_by": user["id"],
        "submitted_at": now,
        "entries_count": len(data.entries),
        "total_hours": total_hours,
        "general_notes": data.general_notes,
        "photos": data.photos,
        "source": "technician_mobile",
        "status": "Draft",
    }
    existing_report = await db.work_reports.find_one(
        {"org_id": org_id, "project_id": data.project_id, "user_id": user["id"], "date": today}
    )
    if existing_report:
        await db.work_reports.update_one({"id": existing_report["id"]}, {"$set": {
            "entries_count": report["entries_count"], "total_hours": total_hours,
            "general_notes": report["general_notes"], "photos": report["photos"],
            "submitted_at": now, "status": "Draft",
        }})
        report["id"] = existing_report["id"]
    else:
        await db.work_reports.insert_one(report)

    # Hours warnings per unique worker
    hours_warnings = []
    try:
        from app.routes.daily_reports import check_employee_hours
        seen_workers = set()
        for entry in data.entries:
            wid = entry.worker_id or user["id"]
            if wid not in seen_workers:
                seen_workers.add(wid)
                hw = await check_employee_hours(org_id, wid, today)
                if hw["level"] != "ok":
                    hw["worker_name"] = entry.worker_name or wid
                    hours_warnings.append(hw)
    except Exception:
        pass

    return {
        "report_id": report["id"],
        "draft_report_ids": draft_ids,
        "roster_id": roster["id"] if roster else None,
        "missing_smr_created": missing_smr_created,
        "total_hours": total_hours,
        "hours_warnings": hours_warnings,
    }


# ── Quick SMR ──────────────────────────────────────────────────────

@router.post("/technician/quick-smr", status_code=201)
async def quick_smr(data: QuickSMR, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.now(timezone.utc).isoformat()
    ms = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.project_id,
        "project_name": project.get("name", ""),
        "smr_type": data.smr_type,
        "activity_type": data.smr_type,
        "notes": data.description,
        "qty": data.qty,
        "unit": data.unit,
        "source": "mobile",
        "status": "reported",
        "urgency_type": "emergency",
        "emergency_reason": "Ново от терена",
        "location_id": data.location_id,
        "attachments": [{"media_id": p, "url": f"/api/media/file/{p}", "filename": ""} for p in data.photos],
        "created_at": now,
        "updated_at": now,
        "created_by": user["id"],
        "created_by_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        "client_approval": None,
        "ai_estimated_price": None,
        "ai_price_breakdown": None,
        "offer_line_ids": [],
        "linked_extra_work_id": None,
        "linked_offer_id": None,
        "linked_change_order_id": None,
    }
    await db.missing_smr.insert_one(ms)
    return {"missing_smr_id": ms["id"]}


# ── Material Request ───────────────────────────────────────────────

@router.post("/technician/material-request", status_code=201)
async def material_request(data: MaterialRequestSubmit, user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    lines = [{"material_name": i.item_name, "qty_requested": i.qty, "unit": i.unit, "notes": i.notes or ""} for i in data.items]
    req = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": data.project_id,
        "requested_by": user["id"],
        "requested_at": now,
        "status": "submitted" if data.urgent else "draft",
        "is_urgent": data.urgent,
        "lines": lines,
        "notes": "Заявка от терена" if data.urgent else "",
        "created_at": now,
        "updated_at": now,
    }
    await db.material_requests.insert_one(req)
    return {"request_id": req["id"]}


# ── Photo Invoice ──────────────────────────────────────────────────

@router.post("/technician/photo-invoice", status_code=201)
async def photo_invoice(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    description: str = Form(""),
    amount: float = Form(0),
    user: dict = Depends(get_current_user),
):
    org_id = user["org_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Upload file
    content = await file.read()
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    media_id = str(uuid.uuid4())
    filename = f"{media_id}.{ext}"

    from pathlib import Path
    upload_dir = Path("/app/backend/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    with open(upload_dir / filename, "wb") as f:
        f.write(content)

    media = {
        "id": media_id, "org_id": org_id, "owner_user_id": user["id"],
        "filename": file.filename, "stored_filename": filename,
        "url": f"/api/media/file/{filename}", "content_type": file.content_type or "image/jpeg",
        "file_size": len(content), "context_type": "project", "context_id": project_id,
        "created_at": now,
    }
    await db.media_files.insert_one(media)

    # Create pending expense
    expense = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "project_id": project_id,
        "submitted_by": user["id"],
        "submitted_by_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        "submitted_at": now,
        "media_id": media_id,
        "media_url": media["url"],
        "description": description,
        "amount": amount,
        "currency": "BGN",
        "status": "pending_approval",
        "approved_by": None,
        "approved_at": None,
        "rejection_reason": None,
        "expense_id": None,
        "created_at": now,
    }
    await db.pending_expenses.insert_one(expense)
    return {"expense_id": expense["id"], "media_id": media_id}


# ── Pending Expenses (Admin) ───────────────────────────────────────

@router.get("/pending-expenses")
async def list_pending_expenses(status: str = "pending_approval", user: dict = Depends(get_current_user)):
    items = await db.pending_expenses.find(
        {"org_id": user["org_id"], "status": status}, {"_id": 0}
    ).sort("submitted_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.put("/pending-expenses/{expense_id}/approve")
async def approve_expense(expense_id: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ex = await db.pending_expenses.find_one({"id": expense_id, "org_id": user["org_id"]})
    if not ex:
        raise HTTPException(status_code=404, detail="Expense not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.pending_expenses.update_one({"id": expense_id}, {"$set": {
        "status": "approved", "approved_by": user["id"], "approved_at": now,
    }})
    return await db.pending_expenses.find_one({"id": expense_id}, {"_id": 0})


@router.put("/pending-expenses/{expense_id}/reject")
async def reject_expense(expense_id: str, reason: str = "", user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ex = await db.pending_expenses.find_one({"id": expense_id, "org_id": user["org_id"]})
    if not ex:
        raise HTTPException(status_code=404, detail="Expense not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.pending_expenses.update_one({"id": expense_id}, {"$set": {
        "status": "rejected", "approved_by": user["id"], "approved_at": now, "rejection_reason": reason,
    }})
    return await db.pending_expenses.find_one({"id": expense_id}, {"_id": 0})


# ── Equipment ──────────────────────────────────────────────────────

@router.get("/technician/my-equipment")
async def my_equipment(user: dict = Depends(get_current_user)):
    items = await db.equipment_assignments.find(
        {"org_id": user["org_id"], "assigned_to": user["id"], "status": "active"},
        {"_id": 0},
    ).to_list(100)
    return {"items": items, "total": len(items)}


@router.post("/technician/request-equipment", status_code=201)
async def request_equipment(data: EquipmentRequest, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    req = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "project_id": data.project_id,
        "requested_by": user["id"],
        "item_id": data.item_id,
        "item_description": data.item_description,
        "needed_from": data.needed_from,
        "needed_to": data.needed_to,
        "notes": data.notes,
        "status": "pending",
        "created_at": now,
    }
    await db.equipment_requests.insert_one(req)
    return {"request_id": req["id"]}


# ── Draft Editing ──────────────────────────────────────────────────

class DraftLineUpdate(BaseModel):
    smr_type: Optional[str] = None
    hours: Optional[float] = None
    notes: Optional[str] = None


@router.get("/technician/site/{project_id}/my-drafts")
async def get_my_drafts(project_id: str, user: dict = Depends(get_current_user)):
    """Get current user's draft report entries for a project today."""
    org_id = user["org_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    drafts = await db.employee_daily_reports.find(
        {"org_id": org_id, "project_id": project_id, "date": today,
         "status": {"$in": ["Draft", "Submitted"]},
         "submitted_by": user["id"]},
        {"_id": 0},
    ).sort("created_at", 1).to_list(200)
    return {"items": drafts, "total": len(drafts), "date": today}


@router.put("/technician/draft/{draft_id}")
async def update_draft(draft_id: str, data: DraftLineUpdate, user: dict = Depends(get_current_user)):
    """Edit a draft report line (only if still Draft status)."""
    doc = await db.employee_daily_reports.find_one(
        {"id": draft_id, "org_id": user["org_id"]}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Draft not found")
    if doc.get("status") not in ["Draft", "Submitted"]:
        raise HTTPException(status_code=400, detail="Cannot edit approved/rejected reports")

    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now}
    if data.smr_type is not None:
        update["smr_type"] = data.smr_type
    if data.hours is not None:
        update["hours"] = round(data.hours, 2)
    if data.notes is not None:
        update["notes"] = data.notes

    await db.employee_daily_reports.update_one({"id": draft_id}, {"$set": update})
    return await db.employee_daily_reports.find_one({"id": draft_id}, {"_id": 0})


@router.delete("/technician/draft/{draft_id}")
async def delete_draft(draft_id: str, user: dict = Depends(get_current_user)):
    """Delete a draft report line (only if still Draft)."""
    doc = await db.employee_daily_reports.find_one(
        {"id": draft_id, "org_id": user["org_id"]}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Draft not found")
    if doc.get("status") not in ["Draft"]:
        raise HTTPException(status_code=400, detail="Can only delete Draft entries")
    await db.employee_daily_reports.delete_one({"id": draft_id})
    return {"ok": True}
