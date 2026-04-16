"""
Attendance, Work Reports, Reminders & Notifications routes.
/api/attendance/*, /api/work-reports/*, /api/reminders/*, /api/notifications/*
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.utils.audit import log_audit

router = APIRouter(tags=["attendance"])

# Constants
ATTENDANCE_STATUSES = ["Present", "Absent", "Late", "SickLeave", "Vacation"]
REPORT_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]
REMINDER_TYPES = ["MissingAttendance", "MissingWorkReport"]

# Models
class AttendanceMarkSelf(BaseModel):
    project_id: Optional[str] = None
    status: str = "Present"
    note: str = ""
    source: str = "Web"

class AttendanceMarkForUser(BaseModel):
    user_id: str
    project_id: Optional[str] = None
    status: str = "Present"
    note: str = ""
    source: str = "Web"

class WorkReportLineInput(BaseModel):
    activity_name: str
    hours: float
    note: str = ""

class WorkReportDraftCreate(BaseModel):
    project_id: str
    date: Optional[str] = None

class WorkReportUpdate(BaseModel):
    summary_note: Optional[str] = None
    lines: Optional[List[WorkReportLineInput]] = None

class WorkReportReject(BaseModel):
    reason: str

class SendReminderRequest(BaseModel):
    type: str
    date: Optional[str] = None
    user_ids: List[str]
    project_id: Optional[str] = None

class ExcuseRequest(BaseModel):
    type: str
    date: str
    user_id: str
    project_id: Optional[str] = None
    reason: str

# ── Helpers ──
def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def now_hour():
    return datetime.now(timezone.utc).hour

async def get_org_attendance_window(org_id: str):
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0, "attendance_start": 1, "attendance_end": 1})
    start = org.get("attendance_start", "06:00") if org else "06:00"
    end = org.get("attendance_end", "10:00") if org else "10:00"
    return start, end

async def get_user_active_project_ids(user_id: str):
    members = await db.project_team.find({"user_id": user_id, "active": True}, {"_id": 0, "project_id": 1}).to_list(100)
    pids = [m["project_id"] for m in members]
    if not pids:
        return []
    active = await db.projects.find({"id": {"$in": pids}, "status": "Active"}, {"_id": 0, "id": 1}).to_list(100)
    return [p["id"] for p in active]

async def is_past_deadline(org_id: str):
    _, end = await get_org_attendance_window(org_id)
    end_hour = int(end.split(":")[0])
    return now_hour() >= end_hour

async def create_attendance_entry(org_id, date, project_id, user_id, status, note, marked_by, source):
    existing = await db.attendance_entries.find_one({"org_id": org_id, "date": date, "user_id": user_id})
    if existing:
        raise HTTPException(status_code=400, detail="Attendance already marked for this user today")
    if status not in ATTENDANCE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be: {', '.join(ATTENDANCE_STATUSES)}")
    if status == "Present" and await is_past_deadline(org_id) and marked_by == user_id:
        status = "Late"
    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "date": date,
        "project_id": project_id,
        "user_id": user_id,
        "status": status,
        "note": note,
        "marked_at": datetime.now(timezone.utc).isoformat(),
        "marked_by_user_id": marked_by,
        "source": source,
    }
    await db.attendance_entries.insert_one(entry)
    await auto_resolve_reminders(org_id, "MissingAttendance", date, user_id, user_id)
    return {k: v for k, v in entry.items() if k != "_id"}

# Work Report helpers
async def can_access_report(user: dict, report: dict) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    if report["user_id"] == user["id"]:
        return True
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find_one({
            "project_id": report["project_id"], "user_id": user["id"],
            "active": True, "role_in_project": "SiteManager"
        })
        return mgr is not None
    return False

async def can_review_report(user: dict, report: dict) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find_one({
            "project_id": report["project_id"], "user_id": user["id"],
            "active": True, "role_in_project": "SiteManager"
        })
        return mgr is not None
    return False

def enrich_report(report: dict) -> dict:
    r = {k: v for k, v in report.items() if k != "_id"}
    r["total_hours"] = sum(line.get("hours", 0) for line in r.get("lines", []))
    return r

# Reminder helpers
async def get_org_reminder_policy(org_id: str):
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0})
    return {
        "attendance_deadline": org.get("attendance_end", "10:00") if org else "10:00",
        "work_report_deadline": org.get("work_report_deadline", "18:30") if org else "18:30",
        "max_reminders_per_day": org.get("max_reminders_per_day", 2) if org else 2,
        "escalation_after_days": org.get("escalation_after_days", 2) if org else 2,
        "timezone": org.get("org_timezone", "Europe/Sofia") if org else "Europe/Sofia",
    }

def get_local_now(tz_name: str):
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/Sofia")
    return datetime.now(tz)

async def compute_missing_attendance(org_id: str, date: str, scoped_project_ids=None):
    if scoped_project_ids:
        pids = scoped_project_ids
    else:
        active = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(200)
        pids = [p["id"] for p in active]
    if not pids:
        return []
    members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(1000)
    seen = set()
    unique_uids = []
    for m in members:
        if m["user_id"] not in seen:
            seen.add(m["user_id"])
            unique_uids.append(m["user_id"])
    if not unique_uids:
        return []
    marked = await db.attendance_entries.find(
        {"org_id": org_id, "date": date, "user_id": {"$in": unique_uids}}, {"_id": 0, "user_id": 1}
    ).to_list(1000)
    marked_set = {e["user_id"] for e in marked}
    missing = []
    for uid in unique_uids:
        if uid not in marked_set:
            u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "role": 1})
            if u and u.get("role") not in ["Admin", "Owner"]:
                missing.append({"user_id": uid, "user_name": f"{u['first_name']} {u['last_name']}", "user_email": u["email"], "user_role": u.get("role", "")})
    return missing

async def compute_missing_work_reports(org_id: str, date: str, scoped_project_ids=None):
    present = await db.attendance_entries.find(
        {"org_id": org_id, "date": date, "status": {"$in": ["Present", "Late"]}}, {"_id": 0, "user_id": 1}
    ).to_list(1000)
    present_uids = list({e["user_id"] for e in present})
    if not present_uids:
        return []
    if scoped_project_ids:
        pids = scoped_project_ids
    else:
        active = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(200)
        pids = [p["id"] for p in active]
    members = await db.project_team.find({"project_id": {"$in": pids}, "active": True, "user_id": {"$in": present_uids}}, {"_id": 0}).to_list(1000)
    user_projects = {}
    for m in members:
        user_projects.setdefault(m["user_id"], []).append(m["project_id"])
    submitted = await db.work_reports.find(
        {"org_id": org_id, "date": date, "status": {"$in": ["Submitted", "Approved"]}}, {"_id": 0, "user_id": 1, "project_id": 1}
    ).to_list(1000)
    submitted_keys = {(r["user_id"], r["project_id"]) for r in submitted}
    missing = []
    for uid, proj_ids in user_projects.items():
        for pid in proj_ids:
            if (uid, pid) not in submitted_keys:
                u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1})
                p = await db.projects.find_one({"id": pid}, {"_id": 0, "code": 1, "name": 1})
                if u:
                    missing.append({
                        "user_id": uid, "project_id": pid,
                        "user_name": f"{u['first_name']} {u['last_name']}", "user_email": u["email"],
                        "project_code": p["code"] if p else "", "project_name": p["name"] if p else "",
                    })
    return missing

async def create_notification(org_id, user_id, ntype, title, message, data=None):
    notif = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "type": ntype,
        "title": title,
        "message": message,
        "data": data or {},
        "is_read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.notifications.insert_one(notif)
    return {k: v for k, v in notif.items() if k != "_id"}

async def send_reminder_for_user(org_id, rtype, date, user_id, project_id, policy, triggered_by="system"):
    key = {"org_id": org_id, "type": rtype, "date": date, "user_id": user_id}
    if project_id:
        key["project_id"] = project_id
    existing = await db.reminder_logs.find_one(key)
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        if existing["status"] in ["Resolved", "Excused"]:
            return None
        if existing["reminder_count"] >= policy["max_reminders_per_day"]:
            return None
        if existing.get("last_reminded_at"):
            last = datetime.fromisoformat(existing["last_reminded_at"])
            if (datetime.now(timezone.utc) - last).total_seconds() < 3600:
                return None
        await db.reminder_logs.update_one({"id": existing["id"]}, {"$set": {
            "status": "Reminded", "reminder_count": existing["reminder_count"] + 1,
            "last_reminded_at": now, "updated_at": now,
        }})
        reminder_id = existing["id"]
    else:
        reminder_id = str(uuid.uuid4())
        log_entry = {
            "id": reminder_id, "org_id": org_id, "type": rtype, "date": date,
            "user_id": user_id, "project_id": project_id, "status": "Reminded",
            "reminder_count": 1, "last_reminded_at": now, "resolved_at": None,
            "resolved_by_user_id": None, "excused_reason": None,
            "created_at": now, "updated_at": now,
        }
        await db.reminder_logs.insert_one(log_entry)
    if rtype == "MissingAttendance":
        title = "Attendance Reminder"
        message = f"You haven't marked attendance for {date}. Please mark now."
    else:
        title = "Work Report Reminder"
        message = f"You haven't submitted your work report for {date}. Please fill it now."
    await create_notification(org_id, user_id, rtype, title, message, {"date": date, "project_id": project_id})
    return reminder_id

async def auto_resolve_reminders(org_id, rtype, date, user_id, resolved_by=None):
    query = {"org_id": org_id, "type": rtype, "date": date, "user_id": user_id, "status": {"$in": ["Open", "Reminded"]}}
    now = datetime.now(timezone.utc).isoformat()
    result = await db.reminder_logs.update_many(query, {"$set": {
        "status": "Resolved", "resolved_at": now, "resolved_by_user_id": resolved_by, "updated_at": now,
    }})
    return result.modified_count

async def run_reminder_jobs():
    orgs = await db.organizations.find({}, {"_id": 0, "id": 1}).to_list(100)
    for org in orgs:
        org_id = org["id"]
        policy = await get_org_reminder_policy(org_id)
        local_now = get_local_now(policy["timezone"])
        date = local_now.strftime("%Y-%m-%d")
        current_time = local_now.strftime("%H:%M")
        if current_time >= policy["attendance_deadline"]:
            missing_att = await compute_missing_attendance(org_id, date)
            for m in missing_att:
                await send_reminder_for_user(org_id, "MissingAttendance", date, m["user_id"], None, policy)
        if current_time >= policy["work_report_deadline"]:
            missing_rep = await compute_missing_work_reports(org_id, date)
            for m in missing_rep:
                await send_reminder_for_user(org_id, "MissingWorkReport", date, m["user_id"], m["project_id"], policy)
        open_reminders = await db.reminder_logs.find(
            {"org_id": org_id, "date": date, "status": {"$in": ["Open", "Reminded"]}}, {"_id": 0}
        ).to_list(1000)
        for rl in open_reminders:
            if rl["type"] == "MissingAttendance":
                att = await db.attendance_entries.find_one({"org_id": org_id, "date": date, "user_id": rl["user_id"]})
                if att:
                    await auto_resolve_reminders(org_id, "MissingAttendance", date, rl["user_id"])
            elif rl["type"] == "MissingWorkReport":
                rep = await db.work_reports.find_one({
                    "org_id": org_id, "date": date, "user_id": rl["user_id"],
                    "project_id": rl.get("project_id"), "status": {"$in": ["Submitted", "Approved"]}
                })
                if rep:
                    await auto_resolve_reminders(org_id, "MissingWorkReport", date, rl["user_id"])

# ══════════════════════════════════════════════════════════════════
# ATTENDANCE ROUTES
# ══════════════════════════════════════════════════════════════════

@router.post("/attendance/mark", status_code=201)
async def mark_attendance_self(data: AttendanceMarkSelf, user: dict = Depends(get_current_user)):
    from app.services.project_guards import check_project_writable
    await check_project_writable(data.project_id, user["org_id"], "присъствия")
    date = today_str()
    entry = await create_attendance_entry(
        user["org_id"], date, data.project_id, user["id"],
        data.status, data.note, user["id"], data.source
    )
    await log_audit(user["org_id"], user["id"], user["email"], "attendance_marked", "attendance", entry["id"],
                    {"status": entry["status"], "date": date})
    return entry

@router.post("/attendance/mark-for-user", status_code=201)
async def mark_attendance_for_user(data: AttendanceMarkForUser, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only managers/admins can mark for others")
    target = await db.users.find_one({"id": data.user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user["role"] == "SiteManager":
        mgr_projects = await db.project_team.find(
            {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
        ).to_list(100)
        mgr_pids = {m["project_id"] for m in mgr_projects}
        target_projects = await db.project_team.find(
            {"user_id": data.user_id, "active": True}, {"_id": 0, "project_id": 1}
        ).to_list(100)
        target_pids = {m["project_id"] for m in target_projects}
        if not mgr_pids & target_pids:
            raise HTTPException(status_code=403, detail="User not in any of your managed projects")
    date = today_str()
    entry = await create_attendance_entry(
        user["org_id"], date, data.project_id, data.user_id,
        data.status, data.note, user["id"], data.source
    )
    await log_audit(user["org_id"], user["id"], user["email"], "attendance_overridden", "attendance", entry["id"],
                    {"for_user": data.user_id, "status": entry["status"], "date": date})
    return entry

@router.get("/attendance/my-today")
async def get_my_attendance_today(user: dict = Depends(get_current_user)):
    date = today_str()
    entry = await db.attendance_entries.find_one({"org_id": user["org_id"], "date": date, "user_id": user["id"]}, {"_id": 0})
    past_deadline = await is_past_deadline(user["org_id"])
    active_pids = await get_user_active_project_ids(user["id"])
    projects = []
    if active_pids:
        projs = await db.projects.find({"id": {"$in": active_pids}}, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(100)
        projects = projs
    _, end = await get_org_attendance_window(user["org_id"])
    return {"entry": entry, "date": date, "past_deadline": past_deadline, "deadline": end, "active_projects": projects}

@router.get("/attendance/my-range")
async def get_my_attendance_range(user: dict = Depends(get_current_user), from_date: str = "", to_date: str = ""):
    if not from_date:
        from_date = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = today_str()
    entries = await db.attendance_entries.find(
        {"org_id": user["org_id"], "user_id": user["id"], "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0}
    ).sort("date", -1).to_list(100)
    return entries

@router.get("/attendance/site-today")
async def get_site_attendance_today(user: dict = Depends(get_current_user), project_id: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    date = today_str()
    org_id = user["org_id"]
    if project_id:
        if user["role"] == "SiteManager":
            mgr = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"})
            if not mgr:
                raise HTTPException(status_code=403, detail="Not managing this project")
        members = await db.project_team.find({"project_id": project_id, "active": True}, {"_id": 0}).to_list(100)

        # Include workers with attendance_entries for this project today (source of truth from TechPortal → Хора)
        att_entries = await db.attendance_entries.find(
            {"org_id": org_id, "project_id": project_id, "date": date},
            {"_id": 0, "user_id": 1},
        ).to_list(200)
        for ae in att_entries:
            uid = ae.get("user_id")
            if uid and not any(m.get("user_id") == uid for m in members):
                members.append({"user_id": uid})

        # Also include workers who reported on this project today
        old_reports = await db.employee_daily_reports.find(
            {"org_id": org_id, "project_id": project_id, "date": date, "worker_id": {"$exists": True}},
            {"_id": 0, "worker_id": 1},
        ).to_list(200)
        new_reports = await db.employee_daily_reports.find(
            {"org_id": org_id, "report_date": date, "day_entries.project_id": project_id},
            {"_id": 0, "employee_id": 1},
        ).to_list(200)
        reported_ids = set(r["worker_id"] for r in old_reports if r.get("worker_id"))
        reported_ids |= set(r["employee_id"] for r in new_reports if r.get("employee_id"))
        for rid in reported_ids:
            if not any(m.get("user_id") == rid for m in members):
                members.append({"user_id": rid})
    else:
        if user["role"] == "SiteManager":
            mgr_projects = await db.project_team.find(
                {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
            ).to_list(100)
            pids = [m["project_id"] for m in mgr_projects]
            members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(500)
        else:
            active_projs = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(100)
            pids = [p["id"] for p in active_projs]
            members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(500)
    seen = set()
    unique_user_ids = []
    for m in members:
        if m["user_id"] not in seen:
            seen.add(m["user_id"])
            unique_user_ids.append(m["user_id"])
    entries_map = {}
    if unique_user_ids:
        entries = await db.attendance_entries.find(
            {"org_id": org_id, "date": date, "user_id": {"$in": unique_user_ids}}, {"_id": 0}
        ).to_list(500)
        entries_map = {e["user_id"]: e for e in entries}
    result = []
    for uid in unique_user_ids:
        u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1, "role": 1})
        if not u:
            continue
        entry = entries_map.get(uid)
        result.append({
            "user_id": uid, "user_name": f"{u['first_name']} {u['last_name']}",
            "user_email": u["email"], "user_role": u["role"],
            "attendance": entry, "marked": entry is not None,
        })
    missing_count = sum(1 for r in result if not r["marked"])
    return {"users": result, "missing_count": missing_count, "date": date}

@router.get("/attendance/missing-today")
async def get_missing_attendance_today(user: dict = Depends(get_current_user), project_id: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    date = today_str()
    org_id = user["org_id"]
    if project_id:
        if user["role"] == "SiteManager":
            mgr = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"})
            if not mgr:
                raise HTTPException(status_code=403, detail="Not managing this project")
        proj = await db.projects.find_one({"id": project_id, "org_id": org_id, "status": "Active"})
        if not proj:
            return {"missing": [], "count": 0}
        members = await db.project_team.find({"project_id": project_id, "active": True}, {"_id": 0}).to_list(100)
    else:
        if user["role"] == "SiteManager":
            mgr_projects = await db.project_team.find(
                {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
            ).to_list(100)
            pids = [m["project_id"] for m in mgr_projects]
        else:
            active_projs = await db.projects.find({"org_id": org_id, "status": "Active"}, {"_id": 0, "id": 1}).to_list(100)
            pids = [p["id"] for p in active_projs]
        members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0}).to_list(500)
    seen = set()
    unique_uids = []
    for m in members:
        if m["user_id"] not in seen:
            seen.add(m["user_id"])
            unique_uids.append(m["user_id"])
    marked_uids = set()
    if unique_uids:
        entries = await db.attendance_entries.find(
            {"org_id": org_id, "date": date, "user_id": {"$in": unique_uids}}, {"_id": 0, "user_id": 1}
        ).to_list(500)
        marked_uids = {e["user_id"] for e in entries}
    missing = []
    for uid in unique_uids:
        if uid not in marked_uids:
            u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1})
            if u:
                missing.append({"user_id": uid, "user_name": f"{u['first_name']} {u['last_name']}", "user_email": u["email"]})
    return {"missing": missing, "count": len(missing), "date": date}

@router.get("/attendance/statuses")
async def get_attendance_statuses():
    return ATTENDANCE_STATUSES

# ══════════════════════════════════════════════════════════════════
# WORK REPORT ROUTES
# ══════════════════════════════════════════════════════════════════

@router.post("/work-reports/draft", status_code=201)
async def create_or_get_draft(data: WorkReportDraftCreate, user: dict = Depends(get_current_user)):
    date = data.date or today_str()
    org_id = user["org_id"]
    att = await db.attendance_entries.find_one({
        "org_id": org_id, "date": date, "user_id": user["id"],
        "status": {"$in": ["Present", "Late"]}
    })
    if not att:
        raise HTTPException(status_code=400, detail="Attendance must be marked as Present or Late before creating a work report")
    project = await db.projects.find_one({"id": data.project_id, "org_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    existing = await db.work_reports.find_one({
        "org_id": org_id, "date": date, "user_id": user["id"], "project_id": data.project_id
    }, {"_id": 0})
    if existing:
        return enrich_report(existing)
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "id": str(uuid.uuid4()), "org_id": org_id, "date": date,
        "project_id": data.project_id, "user_id": user["id"],
        "attendance_entry_id": att["id"], "status": "Draft",
        "summary_note": "", "lines": [], "submitted_at": None,
        "approved_at": None, "approved_by_user_id": None,
        "reject_reason": None, "created_at": now, "updated_at": now,
    }
    await db.work_reports.insert_one(report)
    await log_audit(org_id, user["id"], user["email"], "report_draft_created", "work_report", report["id"], {"date": date, "project": data.project_id})
    return enrich_report(report)

@router.put("/work-reports/{report_id}")
async def update_work_report(report_id: str, data: WorkReportUpdate, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Can only edit your own reports")
    if report["status"] not in ["Draft", "Rejected"]:
        raise HTTPException(status_code=400, detail="Can only edit Draft or Rejected reports")
    update = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if data.summary_note is not None:
        update["summary_note"] = data.summary_note
    if data.lines is not None:
        update["lines"] = [
            {"id": str(uuid.uuid4()), "activity_name": l.activity_name, "hours": l.hours, "note": l.note}
            for l in data.lines
        ]
    if report["status"] == "Rejected":
        update["status"] = "Draft"
        update["reject_reason"] = None
    await db.work_reports.update_one({"id": report_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "report_edited", "work_report", report_id)
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@router.post("/work-reports/{report_id}/submit")
async def submit_work_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Can only submit your own reports")
    if report["status"] not in ["Draft", "Rejected"]:
        raise HTTPException(status_code=400, detail="Report already submitted")
    if not report.get("lines") or len(report["lines"]) == 0:
        raise HTTPException(status_code=400, detail="Report must have at least one activity line")
    now = datetime.now(timezone.utc).isoformat()
    await db.work_reports.update_one({"id": report_id}, {"$set": {
        "status": "Submitted", "submitted_at": now, "reject_reason": None, "updated_at": now
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "report_submitted", "work_report", report_id, {"date": report["date"]})
    await auto_resolve_reminders(user["org_id"], "MissingWorkReport", report["date"], user["id"], user["id"])
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@router.post("/work-reports/{report_id}/approve")
async def approve_work_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not await can_review_report(user, report):
        raise HTTPException(status_code=403, detail="Insufficient permissions to approve")
    if report["status"] != "Submitted":
        raise HTTPException(status_code=400, detail="Only submitted reports can be approved")
    now = datetime.now(timezone.utc).isoformat()
    await db.work_reports.update_one({"id": report_id}, {"$set": {
        "status": "Approved", "approved_at": now, "approved_by_user_id": user["id"], "updated_at": now
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "report_approved", "work_report", report_id, {"date": report["date"]})
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@router.post("/work-reports/{report_id}/reject")
async def reject_work_report(report_id: str, data: WorkReportReject, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not await can_review_report(user, report):
        raise HTTPException(status_code=403, detail="Insufficient permissions to reject")
    if report["status"] != "Submitted":
        raise HTTPException(status_code=400, detail="Only submitted reports can be rejected")
    now = datetime.now(timezone.utc).isoformat()
    await db.work_reports.update_one({"id": report_id}, {"$set": {
        "status": "Rejected", "reject_reason": data.reason, "updated_at": now
    }})
    await log_audit(user["org_id"], user["id"], user["email"], "report_rejected", "work_report", report_id, {"reason": data.reason})
    updated = await db.work_reports.find_one({"id": report_id}, {"_id": 0})
    return enrich_report(updated)

@router.get("/work-reports/my-today")
async def get_my_work_reports_today(user: dict = Depends(get_current_user)):
    date = today_str()
    reports = await db.work_reports.find(
        {"org_id": user["org_id"], "date": date, "user_id": user["id"]}, {"_id": 0}
    ).to_list(50)
    return [enrich_report(r) for r in reports]

@router.get("/work-reports/my-range")
async def get_my_work_reports_range(user: dict = Depends(get_current_user), from_date: str = "", to_date: str = ""):
    if not from_date:
        from_date = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = today_str()
    reports = await db.work_reports.find(
        {"org_id": user["org_id"], "user_id": user["id"], "date": {"$gte": from_date, "$lte": to_date}},
        {"_id": 0}
    ).sort("date", -1).to_list(200)
    return [enrich_report(r) for r in reports]

@router.get("/work-reports/project-day")
async def get_project_day_reports(user: dict = Depends(get_current_user), project_id: str = "", date: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()
    query = {"org_id": user["org_id"], "date": date}
    if project_id:
        if user["role"] == "SiteManager":
            mgr = await db.project_team.find_one({
                "project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"
            })
            if not mgr:
                raise HTTPException(status_code=403, detail="Not managing this project")
        query["project_id"] = project_id
    elif user["role"] == "SiteManager":
        mgr_projects = await db.project_team.find(
            {"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}
        ).to_list(100)
        pids = [m["project_id"] for m in mgr_projects]
        query["project_id"] = {"$in": pids}
    reports = await db.work_reports.find(query, {"_id": 0}).to_list(200)
    enriched = []
    for r in reports:
        er = enrich_report(r)
        u = await db.users.find_one({"id": r["user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1})
        er["user_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
        er["user_email"] = u["email"] if u else ""
        p = await db.projects.find_one({"id": r["project_id"]}, {"_id": 0, "code": 1, "name": 1})
        er["project_code"] = p["code"] if p else ""
        er["project_name"] = p["name"] if p else ""
        enriched.append(er)
    return enriched

@router.get("/work-reports/{report_id}")
async def get_work_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.work_reports.find_one({"id": report_id, "org_id": user["org_id"]}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not await can_access_report(user, report):
        raise HTTPException(status_code=403, detail="Access denied")
    er = enrich_report(report)
    p = await db.projects.find_one({"id": report["project_id"]}, {"_id": 0, "code": 1, "name": 1})
    er["project_code"] = p["code"] if p else ""
    er["project_name"] = p["name"] if p else ""
    return er

# ══════════════════════════════════════════════════════════════════
# REMINDER ROUTES
# ══════════════════════════════════════════════════════════════════

@router.get("/reminders/policy")
async def get_reminder_policy_route(user: dict = Depends(get_current_user)):
    return await get_org_reminder_policy(user["org_id"])

@router.get("/reminders/missing-attendance")
async def api_missing_attendance(user: dict = Depends(get_current_user), date: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()
    scoped = None
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find({"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}).to_list(100)
        scoped = [m["project_id"] for m in mgr]
    return await compute_missing_attendance(user["org_id"], date, scoped)

@router.get("/reminders/missing-work-reports")
async def api_missing_work_reports(user: dict = Depends(get_current_user), date: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()
    scoped = None
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find({"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}).to_list(100)
        scoped = [m["project_id"] for m in mgr]
    return await compute_missing_work_reports(user["org_id"], date, scoped)

@router.get("/reminders/logs")
async def get_reminder_logs(user: dict = Depends(get_current_user), date: str = "", rtype: str = ""):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if not date:
        date = today_str()
    query = {"org_id": user["org_id"], "date": date}
    if rtype:
        query["type"] = rtype
    if user["role"] == "SiteManager":
        mgr = await db.project_team.find({"user_id": user["id"], "active": True, "role_in_project": "SiteManager"}, {"_id": 0, "project_id": 1}).to_list(100)
        pids = [m["project_id"] for m in mgr]
        members = await db.project_team.find({"project_id": {"$in": pids}, "active": True}, {"_id": 0, "user_id": 1}).to_list(500)
        uids = list({m["user_id"] for m in members})
        query["user_id"] = {"$in": uids}
    logs = await db.reminder_logs.find(query, {"_id": 0}).sort("updated_at", -1).to_list(500)
    for rl in logs:
        u = await db.users.find_one({"id": rl["user_id"]}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1})
        rl["user_name"] = f"{u['first_name']} {u['last_name']}" if u else "Unknown"
        rl["user_email"] = u["email"] if u else ""
        if rl.get("project_id"):
            p = await db.projects.find_one({"id": rl["project_id"]}, {"_id": 0, "code": 1, "name": 1})
            rl["project_code"] = p["code"] if p else ""
        else:
            rl["project_code"] = ""
    return logs

@router.post("/reminders/send")
async def send_reminders_manual(data: SendReminderRequest, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    if data.type not in REMINDER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be: {', '.join(REMINDER_TYPES)}")
    date = data.date or today_str()
    policy = await get_org_reminder_policy(user["org_id"])
    sent = 0
    for uid in data.user_ids:
        result = await send_reminder_for_user(user["org_id"], data.type, date, uid, data.project_id, policy, user["id"])
        if result:
            sent += 1
    await log_audit(user["org_id"], user["id"], user["email"], "reminder_sent", "reminder", "", {"type": data.type, "count": sent, "date": date})
    return {"sent": sent, "total": len(data.user_ids)}

@router.post("/reminders/excuse")
async def excuse_reminder(data: ExcuseRequest, user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Manager access required")
    query = {"org_id": user["org_id"], "type": data.type, "date": data.date, "user_id": data.user_id}
    if data.project_id:
        query["project_id"] = data.project_id
    existing = await db.reminder_logs.find_one(query)
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        await db.reminder_logs.update_one({"id": existing["id"]}, {"$set": {
            "status": "Excused", "excused_reason": data.reason, "resolved_by_user_id": user["id"], "updated_at": now,
        }})
    else:
        await db.reminder_logs.insert_one({
            "id": str(uuid.uuid4()), "org_id": user["org_id"], "type": data.type, "date": data.date,
            "user_id": data.user_id, "project_id": data.project_id, "status": "Excused",
            "reminder_count": 0, "last_reminded_at": None, "resolved_at": None,
            "resolved_by_user_id": user["id"], "excused_reason": data.reason,
            "created_at": now, "updated_at": now,
        })
    await log_audit(user["org_id"], user["id"], user["email"], "reminder_excused", "reminder", "", {"type": data.type, "user_id": data.user_id, "reason": data.reason})
    return {"ok": True}

@router.post("/internal/run-reminder-jobs")
async def trigger_reminder_jobs():
    await run_reminder_jobs()
    return {"ok": True, "ran_at": datetime.now(timezone.utc).isoformat()}

# ══════════════════════════════════════════════════════════════════
# NOTIFICATION ROUTES
# ══════════════════════════════════════════════════════════════════

@router.get("/notifications/my")
async def get_my_notifications(user: dict = Depends(get_current_user), limit: int = 30):
    notifs = await db.notifications.find(
        {"org_id": user["org_id"], "user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    unread = await db.notifications.count_documents({"org_id": user["org_id"], "user_id": user["id"], "is_read": False})
    return {"notifications": notifs, "unread_count": unread}

@router.post("/notifications/mark-read")
async def mark_notifications_read(user: dict = Depends(get_current_user)):
    await db.notifications.update_many(
        {"org_id": user["org_id"], "user_id": user["id"], "is_read": False},
        {"$set": {"is_read": True}}
    )
    return {"ok": True}
