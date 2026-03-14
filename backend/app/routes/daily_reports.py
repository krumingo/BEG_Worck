"""
Routes - Structured Employee Daily Report.
New model alongside existing attendance/work_reports (which remain untouched).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.deps.modules import require_m4

router = APIRouter(tags=["Employee Daily Reports"])


# ── Models ─────────────────────────────────────────────────────────

class DayEntryInput(BaseModel):
    project_id: str
    smr_id: Optional[str] = None
    extra_work_id: Optional[str] = None
    work_description: str = ""
    hours_worked: float = 0
    note: Optional[str] = None

class DailyReportCreate(BaseModel):
    employee_id: str
    report_date: str  # YYYY-MM-DD
    day_status: str = "WORKING"  # WORKING | LEAVE | ABSENT_UNEXCUSED
    leave_from: Optional[str] = None
    leave_to: Optional[str] = None
    notes: Optional[str] = None
    day_entries: List[DayEntryInput] = []


# ── Validation ─────────────────────────────────────────────────────

def validate_report(data: DailyReportCreate):
    if data.day_status not in ["WORKING", "LEAVE", "ABSENT_UNEXCUSED", "SICK"]:
        raise HTTPException(status_code=400, detail="Invalid day_status")
    if data.day_status == "WORKING":
        for entry in data.day_entries:
            if entry.hours_worked < 0:
                raise HTTPException(status_code=400, detail="hours_worked cannot be negative")
            if entry.hours_worked == 0 and not entry.work_description:
                raise HTTPException(status_code=400, detail="Entry must have hours or description")
    if data.day_status == "LEAVE":
        if not data.leave_from or not data.leave_to:
            raise HTTPException(status_code=400, detail="Leave requires leave_from and leave_to")


# ── CRUD ───────────────────────────────────────────────────────────

@router.post("/daily-reports", status_code=201)
async def create_daily_report(data: DailyReportCreate, user: dict = Depends(require_m4)):
    org_id = user["org_id"]
    validate_report(data)

    # Check no duplicate for same employee+date
    existing = await db.employee_daily_reports.find_one({
        "org_id": org_id, "employee_id": data.employee_id, "report_date": data.report_date
    })
    if existing:
        raise HTTPException(status_code=400, detail="Report already exists for this employee and date. Use update instead.")

    now = datetime.now(timezone.utc).isoformat()
    entries = []
    for e in data.day_entries:
        entries.append({
            "id": str(uuid.uuid4()),
            "project_id": e.project_id,
            "smr_id": e.smr_id,
            "extra_work_id": e.extra_work_id,
            "work_description": e.work_description,
            "hours_worked": e.hours_worked,
            "note": e.note,
        })

    report = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "employee_id": data.employee_id,
        "report_date": data.report_date,
        "day_status": data.day_status,
        "leave_from": data.leave_from,
        "leave_to": data.leave_to,
        "notes": data.notes,
        "day_entries": entries,
        "total_hours": round(sum(e["hours_worked"] for e in entries), 2),
        "approval_status": "DRAFT",
        "created_by": user["id"],
        "submitted_by": None,
        "approved_by": None,
        "approved_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.employee_daily_reports.insert_one(report)
    return {k: v for k, v in report.items() if k != "_id"}


@router.put("/daily-reports/{report_id}")
async def update_daily_report(report_id: str, data: dict, user: dict = Depends(require_m4)):
    org_id = user["org_id"]
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": org_id})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["approval_status"] not in ["DRAFT", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Only DRAFT or REJECTED reports can be edited")

    allowed = ["day_status", "leave_from", "leave_to", "notes", "day_entries"]
    update = {k: v for k, v in data.items() if k in allowed}

    if "day_entries" in update:
        for e in update["day_entries"]:
            if not e.get("id"):
                e["id"] = str(uuid.uuid4())
            if float(e.get("hours_worked", 0)) < 0:
                raise HTTPException(status_code=400, detail="hours_worked cannot be negative")
        update["total_hours"] = round(sum(float(e.get("hours_worked", 0)) for e in update["day_entries"]), 2)

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.employee_daily_reports.update_one({"id": report_id}, {"$set": update})
    return await db.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


@router.post("/daily-reports/{report_id}/submit")
async def submit_daily_report(report_id: str, user: dict = Depends(require_m4)):
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["approval_status"] not in ["DRAFT", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Only DRAFT/REJECTED can be submitted")

    now = datetime.now(timezone.utc).isoformat()
    await db.employee_daily_reports.update_one({"id": report_id}, {"$set": {
        "approval_status": "SUBMITTED", "submitted_by": user["id"], "updated_at": now,
    }})
    return await db.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


@router.post("/daily-reports/{report_id}/approve")
async def approve_daily_report(report_id: str, user: dict = Depends(require_m4)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can approve")
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["approval_status"] != "SUBMITTED":
        raise HTTPException(status_code=400, detail="Only SUBMITTED reports can be approved")
    now = datetime.now(timezone.utc).isoformat()
    await db.employee_daily_reports.update_one({"id": report_id}, {"$set": {
        "approval_status": "APPROVED", "approved_by": user["id"], "approved_at": now, "updated_at": now,
    }})
    return await db.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


@router.post("/daily-reports/{report_id}/reject")
async def reject_daily_report(report_id: str, data: dict = {}, user: dict = Depends(require_m4)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can reject")
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["approval_status"] != "SUBMITTED":
        raise HTTPException(status_code=400, detail="Only SUBMITTED reports can be rejected")
    now = datetime.now(timezone.utc).isoformat()
    await db.employee_daily_reports.update_one({"id": report_id}, {"$set": {
        "approval_status": "REJECTED", "reject_reason": data.get("reason", ""), "updated_at": now,
    }})
    return await db.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════
# CENTRAL REPORTS MODULE — Table + Calendar
# ═══════════════════════════════════════════════════════════════════

@router.get("/daily-reports/reports-table")
async def get_reports_table(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    project_id: Optional[str] = None, employee_id: Optional[str] = None,
    approval_status: Optional[str] = None, day_status: Optional[str] = None,
    user: dict = Depends(require_m4),
):
    """Central reports table with cost estimate"""
    org_id = user["org_id"]
    q = {"org_id": org_id}
    if date_from or date_to:
        q["report_date"] = {}
        if date_from: q["report_date"]["$gte"] = date_from
        if date_to: q["report_date"]["$lte"] = date_to
    if project_id: q["day_entries.project_id"] = project_id
    if employee_id: q["employee_id"] = employee_id
    if approval_status: q["approval_status"] = approval_status
    if day_status: q["day_status"] = day_status

    reports = await db.employee_daily_reports.find(q, {"_id": 0}).sort("report_date", -1).to_list(500)

    # Load employee names + profiles
    emp_ids = list(set(r["employee_id"] for r in reports))
    users_data = await db.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(200)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users_data}

    profiles = await db.employee_profiles.find({"user_id": {"$in": emp_ids}}, {"_id": 0, "user_id": 1, "pay_type": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1, "working_days_per_month": 1, "standard_hours_per_day": 1}).to_list(200)
    profile_map = {p["user_id"]: p for p in profiles}

    # Load project codes
    proj_ids = set()
    for r in reports:
        for e in r.get("day_entries", []):
            if e.get("project_id"): proj_ids.add(e["project_id"])
    projects = await db.projects.find({"id": {"$in": list(proj_ids)}}, {"_id": 0, "id": 1, "code": 1}).to_list(100)
    proj_map = {p["id"]: p["code"] for p in projects}

    rows = []
    for r in reports:
        emp_id = r["employee_id"]
        prof = profile_map.get(emp_id, {})
        pay_type = prof.get("pay_type", "Monthly")

        # Compute hourly rate
        hr_rate = prof.get("hourly_rate") or 0
        if not hr_rate and prof.get("monthly_salary") and prof.get("working_days_per_month") and prof.get("standard_hours_per_day"):
            hr_rate = round(prof["monthly_salary"] / prof["working_days_per_month"] / prof["standard_hours_per_day"], 2)

        total_hours = r.get("total_hours", 0)
        cost_estimate = round(total_hours * hr_rate, 2) if hr_rate > 0 else None
        cost_basis = "hourly_rate" if hr_rate > 0 else "unavailable"

        # Project codes for this report
        pcodes = list(set(proj_map.get(e.get("project_id", ""), "") for e in r.get("day_entries", []) if e.get("project_id")))

        rows.append({
            "id": r["id"],
            "report_date": r["report_date"],
            "employee_id": emp_id,
            "employee_name": name_map.get(emp_id, ""),
            "day_status": r["day_status"],
            "approval_status": r["approval_status"],
            "project_codes": pcodes,
            "pay_type": pay_type,
            "total_hours": total_hours,
            "cost_estimate": cost_estimate,
            "hourly_rate": hr_rate,
            "cost_basis": cost_basis,
            "entries_count": len(r.get("day_entries", [])),
        })

    return {"rows": rows, "total": len(rows), "currency": "EUR"}


@router.get("/daily-reports/reports-calendar")
async def get_reports_calendar(
    month: Optional[str] = None,
    project_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    user: dict = Depends(require_m4),
):
    """Calendar view of daily reports for a month"""
    org_id = user["org_id"]
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    date_from = f"{month}-01"
    y, m = int(month[:4]), int(month[5:7])
    if m == 12:
        date_to = f"{y+1}-01-01"
    else:
        date_to = f"{y}-{m+1:02d}-01"

    q = {"org_id": org_id, "report_date": {"$gte": date_from, "$lt": date_to}}
    if project_id: q["day_entries.project_id"] = project_id
    if employee_id: q["employee_id"] = employee_id

    reports = await db.employee_daily_reports.find(q, {"_id": 0}).to_list(1000)

    # Load names
    emp_ids = list(set(r["employee_id"] for r in reports))
    users_data = await db.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(200)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users_data}

    # Group by date
    by_date = {}
    for r in reports:
        d = r["report_date"]
        if d not in by_date:
            by_date[d] = {"date": d, "working": 0, "leave": 0, "absent": 0, "sick": 0, "people": []}
        if r["day_status"] == "WORKING": by_date[d]["working"] += 1
        elif r["day_status"] == "LEAVE": by_date[d]["leave"] += 1
        elif r["day_status"] == "ABSENT_UNEXCUSED": by_date[d]["absent"] += 1
        elif r["day_status"] == "SICK": by_date[d]["sick"] += 1
        by_date[d]["people"].append({
            "employee_id": r["employee_id"],
            "name": name_map.get(r["employee_id"], ""),
            "day_status": r["day_status"],
            "hours": r.get("total_hours", 0),
            "approval_status": r["approval_status"],
        })

    return {"month": month, "days": sorted(by_date.values(), key=lambda x: x["date"]), "total_reports": len(reports)}


@router.get("/daily-reports/{report_id}")
async def get_daily_report(report_id: str, user: dict = Depends(require_m4)):
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/daily-reports")
async def list_daily_reports(
    employee_id: Optional[str] = None,
    project_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    report_date: Optional[str] = None,
    user: dict = Depends(require_m4),
):
    q = {"org_id": user["org_id"]}
    if employee_id: q["employee_id"] = employee_id
    if report_date: q["report_date"] = report_date
    if date_from or date_to:
        q["report_date"] = {}
        if date_from: q["report_date"]["$gte"] = date_from
        if date_to: q["report_date"]["$lte"] = date_to
    if project_id:
        q["day_entries.project_id"] = project_id

    reports = await db.employee_daily_reports.find(q, {"_id": 0}).sort("report_date", -1).to_list(500)
    return reports


# ── Project Day Status (for Personnel card) ───────────────────────

@router.get("/daily-reports/project-day-status/{project_id}")
async def get_project_day_status(project_id: str, date: Optional[str] = None, user: dict = Depends(require_m4)):
    """Get today's report status for all employees linked to a project"""
    org_id = user["org_id"]
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get team members
    team = await db.project_team.find({"project_id": project_id}, {"_id": 0, "user_id": 1}).to_list(100)
    team_ids = [t["user_id"] for t in team]

    # Also get employees who have reported on this project today
    reports_today = await db.employee_daily_reports.find(
        {"org_id": org_id, "report_date": target_date, "day_entries.project_id": project_id},
        {"_id": 0}
    ).to_list(200)
    report_emp_ids = [r["employee_id"] for r in reports_today]

    all_ids = list(set(team_ids + report_emp_ids))
    if not all_ids:
        return {"project_id": project_id, "date": target_date, "employees": []}

    # Load employee info
    users = await db.users.find(
        {"id": {"$in": all_ids}, "org_id": org_id},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1, "role": 1}
    ).to_list(100)
    user_map = {u["id"]: u for u in users}

    # Load all reports for these employees today
    all_reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": {"$in": all_ids}, "report_date": target_date},
        {"_id": 0}
    ).to_list(200)
    report_map = {r["employee_id"]: r for r in all_reports}

    result = []
    for uid in all_ids:
        u = user_map.get(uid, {})
        r = report_map.get(uid)
        hours_on_project = 0
        if r:
            for e in r.get("day_entries", []):
                if e.get("project_id") == project_id:
                    hours_on_project += float(e.get("hours_worked", 0))

        result.append({
            "employee_id": uid,
            "first_name": u.get("first_name", ""),
            "last_name": u.get("last_name", ""),
            "avatar_url": u.get("avatar_url"),
            "has_report": r is not None,
            "day_status": r["day_status"] if r else None,
            "approval_status": r["approval_status"] if r else None,
            "total_hours": r["total_hours"] if r else 0,
            "hours_on_project": round(hours_on_project, 2),
            "report_id": r["id"] if r else None,
        })

    return {"project_id": project_id, "date": target_date, "employees": result}


# ── Available SMR for reporting ────────────────────────────────────

@router.get("/daily-reports/available-smr/{project_id}")
async def get_available_smr(project_id: str, user: dict = Depends(require_m4)):
    """Get available SMR/activities for a project for time reporting"""
    org_id = user["org_id"]

    # Execution packages
    epkgs = await db.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "id": 1, "activity_name": 1, "unit": 1, "qty": 1, "status": 1}
    ).to_list(200)

    # Extra work drafts that are active
    extras = await db.extra_work_drafts.find(
        {"org_id": org_id, "project_id": project_id, "status": {"$in": ["draft", "converted"]}},
        {"_id": 0, "id": 1, "title": 1, "unit": 1, "qty": 1}
    ).to_list(200)

    smr_list = []
    for ep in epkgs:
        smr_list.append({
            "id": ep["id"], "name": ep["activity_name"],
            "unit": ep.get("unit", ""), "source": "execution_package",
        })
    for ex in extras:
        smr_list.append({
            "id": ex["id"], "name": ex["title"],
            "unit": ex.get("unit", ""), "source": "extra_work",
        })

    return {"project_id": project_id, "smr": smr_list}



# ── Batch save for object-level daily report ───────────────────────

@router.post("/daily-reports/batch-save")
async def batch_save_daily_entries(data: dict, user: dict = Depends(require_m4)):
    """Save multiple employee entries for a project+date in one call.
    Input: { project_id, report_date, entries: [{ employee_id, smr_id, work_description, hours_worked, note }] }
    Groups by employee, creates/updates one report per employee.
    """
    org_id = user["org_id"]
    project_id = data.get("project_id")
    report_date = data.get("report_date")
    entries = data.get("entries", [])

    if not project_id or not report_date:
        raise HTTPException(status_code=400, detail="project_id and report_date required")

    # Group entries by employee
    by_emp = {}
    for e in entries:
        eid = e.get("employee_id")
        if not eid:
            continue
        if eid not in by_emp:
            by_emp[eid] = []
        by_emp[eid].append({
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "smr_id": e.get("smr_id"),
            "extra_work_id": e.get("extra_work_id"),
            "work_description": e.get("work_description", ""),
            "hours_worked": max(0, float(e.get("hours_worked", 0))),
            "note": e.get("note", ""),
        })

    now = datetime.now(timezone.utc).isoformat()
    saved = 0

    for emp_id, emp_entries in by_emp.items():
        total_hours = round(sum(e["hours_worked"] for e in emp_entries), 2)

        # Check for existing report
        existing = await db.employee_daily_reports.find_one({
            "org_id": org_id, "employee_id": emp_id, "report_date": report_date
        })

        if existing:
            # Merge: add new entries to existing, avoid exact duplicates
            old_entries = existing.get("day_entries", [])
            # Keep old entries for OTHER projects, replace for THIS project
            kept = [e for e in old_entries if e.get("project_id") != project_id]
            merged = kept + emp_entries
            merged_total = round(sum(e["hours_worked"] for e in merged), 2)
            await db.employee_daily_reports.update_one({"id": existing["id"]}, {"$set": {
                "day_entries": merged, "total_hours": merged_total, "updated_at": now,
            }})
        else:
            report = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "employee_id": emp_id,
                "report_date": report_date,
                "day_status": "WORKING",
                "leave_from": None, "leave_to": None,
                "notes": None,
                "day_entries": emp_entries,
                "total_hours": total_hours,
                "approval_status": "DRAFT",
                "created_by": user["id"],
                "submitted_by": None, "approved_by": None, "approved_at": None,
                "created_at": now, "updated_at": now,
            }
            await db.employee_daily_reports.insert_one(report)
        saved += 1

    return {"ok": True, "employees_saved": saved, "total_entries": len(entries)}


@router.get("/daily-reports/project-entries/{project_id}")
async def get_project_daily_entries(project_id: str, date: Optional[str] = None, user: dict = Depends(require_m4)):
    """Get all daily entries for a project on a date, grouped by employee and by SMR"""
    org_id = user["org_id"]
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    reports = await db.employee_daily_reports.find(
        {"org_id": org_id, "report_date": target_date, "day_entries.project_id": project_id},
        {"_id": 0}
    ).to_list(200)

    # Load names
    emp_ids = list(set(r["employee_id"] for r in reports))
    users_data = await db.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(100)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users_data}

    # Flatten by employee
    by_employee = []
    for r in reports:
        entries_for_project = [e for e in r.get("day_entries", []) if e.get("project_id") == project_id]
        if entries_for_project:
            by_employee.append({
                "employee_id": r["employee_id"],
                "employee_name": name_map.get(r["employee_id"], ""),
                "report_id": r["id"],
                "approval_status": r["approval_status"],
                "entries": entries_for_project,
                "total_hours": round(sum(e["hours_worked"] for e in entries_for_project), 2),
            })

    # Flatten by SMR
    by_smr = {}
    for r in reports:
        for e in r.get("day_entries", []):
            if e.get("project_id") != project_id:
                continue
            smr_key = e.get("smr_id") or "unassigned"
            if smr_key not in by_smr:
                by_smr[smr_key] = {"smr_id": e.get("smr_id"), "work_description": e.get("work_description", ""), "employees": [], "total_hours": 0}
            by_smr[smr_key]["employees"].append({
                "employee_id": r["employee_id"],
                "employee_name": name_map.get(r["employee_id"], ""),
                "hours_worked": e["hours_worked"],
                "note": e.get("note", ""),
            })
            by_smr[smr_key]["total_hours"] += e["hours_worked"]

    for v in by_smr.values():
        v["total_hours"] = round(v["total_hours"], 2)

    return {
        "project_id": project_id,
        "date": target_date,
        "by_employee": by_employee,
        "by_smr": list(by_smr.values()),
    }



