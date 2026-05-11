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


# ── Helpers ────────────────────────────────────────────────────────

async def _get_hourly_rate_for_approval(org_id: str, worker_id: str) -> float:
    """Get hourly rate from employee profile for work_session creation."""
    from app.services.resolve_hourly_rate import resolve_worker_hourly_rate
    result = await resolve_worker_hourly_rate(worker_id, org_id)
    if isinstance(result, dict):
        return float(result.get("rate", 0))
    return float(result or 0)


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


async def check_employee_hours(
    org_id: str,
    employee_id: str,
    report_date: str,
    exclude_report_id: str = None,
    exclude_project_id: str = None,
):
    """Check total hours for employee on a given date across ALL reports/projects.
    Supports BOTH old schema (worker_id/date/hours) and new schema (employee_id/report_date/day_entries)."""
    query = {
        "org_id": org_id,
        "$or": [
            {"employee_id": employee_id, "report_date": report_date},
            {"worker_id": employee_id, "date": report_date},
        ],
        "approval_status": {"$nin": ["REJECTED"]},
    }
    reports = await db.employee_daily_reports.find(query, {"_id": 0}).to_list(200)

    total_hours = 0
    project_hours = {}  # pid -> hours
    for r in reports:
        if exclude_report_id and r.get("id") == exclude_report_id:
            continue
        entries = r.get("day_entries") or []
        if entries:
            for e in entries:
                e_pid = e.get("project_id")
                if exclude_project_id and e_pid == exclude_project_id:
                    continue
                h = float(e.get("hours_worked", 0) or 0)
                total_hours += h
                if e_pid:
                    project_hours[e_pid] = project_hours.get(e_pid, 0) + h
        else:
            r_pid = r.get("project_id")
            if exclude_project_id and r_pid == exclude_project_id:
                continue
            h = float(r.get("hours") or r.get("hours_worked") or 0)
            if h:
                total_hours += h
                if r_pid:
                    project_hours[r_pid] = project_hours.get(r_pid, 0) + h

    # Build projects_breakdown with names
    projects_breakdown = []
    if project_hours:
        proj_docs = await db.projects.find(
            {"id": {"$in": list(project_hours.keys())}, "org_id": org_id},
            {"_id": 0, "id": 1, "name": 1, "code": 1},
        ).to_list(50)
        proj_by_id = {p["id"]: p for p in proj_docs}
        for pid, h in project_hours.items():
            p = proj_by_id.get(pid, {})
            projects_breakdown.append({
                "project_id": pid,
                "project_name": p.get("name", ""),
                "project_code": p.get("code", ""),
                "hours": round(h, 2),
            })
        projects_breakdown.sort(key=lambda x: x["hours"], reverse=True)

    # Check attendance conflict
    attendance = await db.attendance_entries.find_one(
        {"org_id": org_id, "user_id": employee_id, "date": report_date},
        {"_id": 0, "status": 1},
    )
    absence_conflict = False
    absence_status = None
    if attendance and attendance.get("status") in ["SickLeave", "Leave", "Excused", "Holiday"]:
        absence_conflict = True
        absence_status = attendance["status"]

    warnings = []
    level = "ok"
    if total_hours > 12:
        level = "critical"
        warnings.append(f"Служителят има общо {total_hours:.1f} часа за деня. Проверете дали това е грешка.")
    elif total_hours > 8:
        level = "warning"
        warnings.append(f"Служителят има общо {total_hours:.1f} часа за деня. Проверете дали е извънреден труд.")
    if len(project_hours) > 1:
        warnings.append(f"Работил е на {len(project_hours)} обекта в същия ден.")
    if absence_conflict:
        warnings.append(f"Конфликт: служителят е отбелязан като {absence_status} за деня.")

    return {
        "total_hours": round(total_hours, 2),
        "level": level,
        "warnings": warnings,
        "projects_count": len(project_hours),
        "projects_breakdown": projects_breakdown,
        "absence_conflict": absence_conflict,
        "absence_status": absence_status,
    }


@router.get("/daily-reports/hours-check")
async def get_hours_check(
    employee_id: str,
    date: str,
    exclude_report_id: str = "",
    exclude_project_id: str = "",
    user: dict = Depends(require_m4),
):
    """Check total hours for an employee on a date. Returns warnings."""
    return await check_employee_hours(
        user["org_id"], employee_id, date,
        exclude_report_id or None,
        exclude_project_id or None,
    )


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
    clean = {k: v for k, v in report.items() if k != "_id"}

    # Hours check — add warnings to response (non-blocking)
    hours_info = await check_employee_hours(org_id, data.employee_id, data.report_date)
    clean["hours_warnings"] = hours_info
    return clean


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
    """
    SOURCE OF TRUTH: This is the POSTING EVENT.
    Approve creates work_sessions (the only source of truth for labor cost).
    See /app/memory/SOURCE_OF_TRUTH.md for full policy.
    """
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can approve")
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Support both old (approval_status) and new (status) naming
    current_status = report.get("approval_status") or report.get("status", "")
    if current_status in ("APPROVED",):
        raise HTTPException(status_code=400, detail=f"Вече одобрен отчет не може да бъде одобрен повторно. Статус: {current_status}")

    now = datetime.now(timezone.utc).isoformat()
    org_id = user["org_id"]

    # A) Generate slip number (per-org auto-increment)
    counter = await db.org_counters.find_one_and_update(
        {"org_id": org_id, "counter_type": "slip_number"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True,
    )
    slip_number = counter["value"] if counter and "_id" in counter else 1
    # Handle case where find_one_and_update returns the pre-update doc
    if isinstance(counter, dict) and "value" in counter:
        slip_number = counter["value"]

    # B) Create work_session from this entry (if it has worker_id + hours)
    worker_id = report.get("worker_id")
    hours = report.get("hours") or report.get("hours_worked", 0)
    project_id = report.get("project_id")
    smr_type = report.get("smr_type") or report.get("activity_type", "")
    report_date = report.get("date", now[:10])

    sessions_created = 0
    if worker_id and hours and hours > 0 and project_id:
        # Check for existing session (avoid duplicate)
        existing_ws = await db.work_sessions.find_one({
            "org_id": org_id, "worker_id": worker_id, "site_id": project_id,
            "smr_type_id": smr_type,
            "started_at": {"$gte": f"{report_date}T00:00:00", "$lte": f"{report_date}T23:59:59"},
            "source_method": "APPROVED_REPORT",
        })
        if not existing_ws:
            # Get hourly rate
            rate = await _get_hourly_rate_for_approval(org_id, worker_id)

            project = await db.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "name": 1})
            session = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "worker_id": worker_id,
                "worker_name": report.get("worker_name", ""),
                "site_id": project_id,
                "site_name": (project or {}).get("name", ""),
                "smr_type_id": smr_type,
                "started_at": f"{report_date}T08:00:00",
                "ended_at": f"{report_date}T{8 + int(hours):02d}:{int((hours % 1) * 60):02d}:00",
                "source_method": "APPROVED_REPORT",
                "is_flagged": False,
                "flag_reason": None,
                "duration_hours": round(hours, 2),
                "is_overtime": hours > 8,
                "overtime_type": "over_8h" if hours > 8 else None,
                "overtime_coefficient": 1.0,
                "hourly_rate_at_date": rate,
                "labor_cost": round(hours * rate, 2),
                "notes": report.get("notes", ""),
                "approved_report_id": report_id,
                "entered_by_admin": report.get("entered_by_admin", False),
                "entry_mode": report.get("entry_mode", "technician_portal"),
                "submitted_by": report.get("submitted_by"),
                "created_at": now,
                "updated_at": now,
            }
            await db.work_sessions.insert_one(session)
            sessions_created = 1

        # C2) Update activity budget consumed hours/quantity
        if smr_type and project_id:
            budget = await db.activity_budgets.find_one({
                "org_id": org_id,
                "project_id": project_id,
                "smr_type_id": smr_type,
            })
            if budget:
                new_consumed = round((budget.get("consumed_hours", 0) or 0) + hours, 2)
                planned = budget.get("planned_hours", 0) or 1
                burn_pct = round((new_consumed / planned) * 100, 1)
                await db.activity_budgets.update_one(
                    {"id": budget["id"]},
                    {"$set": {
                        "consumed_hours": new_consumed,
                        "burn_percent": burn_pct,
                        "last_updated": now,
                    }}
                )

        # C3) Update worker_calendar
        cal_existing = await db.worker_calendar.find_one(
            {"org_id": org_id, "worker_id": worker_id, "date": report_date}
        )
        cal_doc = {
            "org_id": org_id, "worker_id": worker_id, "date": report_date,
            "status": "working", "site_id": project_id,
            "hours": round(hours, 2), "source": "approved_report",
            "updated_at": now,
        }
        if cal_existing:
            await db.worker_calendar.update_one({"id": cal_existing["id"]}, {"$set": cal_doc})
        else:
            cal_doc["id"] = str(uuid.uuid4())
            cal_doc["created_at"] = now
            cal_doc["created_by"] = "system"
            await db.worker_calendar.insert_one(cal_doc)

    # D) Update report status + metadata
    update = {
        "approval_status": "APPROVED",
        "status": "APPROVED",
        "approved_by": user["id"],
        "approved_at": now,
        "updated_at": now,
        "slip_number": slip_number,
        "payroll_ready": True,
        "sessions_created": sessions_created,
    }
    await db.employee_daily_reports.update_one({"id": report_id}, {"$set": update})
    result = await db.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})

    # E) Hours check at approval — return warnings to UI
    emp_id = report.get("employee_id") or worker_id
    r_date = report.get("report_date") or report.get("date", now[:10])
    if emp_id and r_date:
        result["hours_warnings"] = await check_employee_hours(org_id, emp_id, r_date)

    return result


@router.post("/daily-reports/{report_id}/reject")
async def reject_daily_report(report_id: str, data: dict = {}, user: dict = Depends(require_m4)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can reject")
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    current_status = report.get("approval_status") or report.get("status", "")
    if current_status in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=400, detail=f"Отчет със статус {current_status} не може да бъде отхвърлен.")
    now = datetime.now(timezone.utc).isoformat()
    await db.employee_daily_reports.update_one({"id": report_id}, {"$set": {
        "approval_status": "REJECTED", "status": "REJECTED",
        "reject_reason": data.get("reason", ""), "updated_at": now,
    }})
    return await db.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


@router.post("/daily-reports/{report_id}/reset")
async def reset_daily_report(report_id: str, user: dict = Depends(require_m4)):
    """Reset an APPROVED report back to SUBMITTED. Voids created work_sessions."""
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can reset")
    report = await db.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    current_status = report.get("approval_status") or report.get("status", "")
    if current_status != "APPROVED":
        raise HTTPException(status_code=400, detail="Only APPROVED reports can be reset")

    # Check payroll not finalized for this period
    report_date = report.get("date", "")
    if report_date:
        finalized = await db.pay_runs.find_one({
            "org_id": user["org_id"],
            "status": "paid",
            "period_start": {"$lte": report_date},
            "period_end": {"$gte": report_date},
        })
        if finalized:
            raise HTTPException(status_code=400, detail="Cannot reset: payroll for this period is paid")

    now = datetime.now(timezone.utc).isoformat()

    # Void work_sessions created by this report
    await db.work_sessions.update_many(
        {"approved_report_id": report_id, "org_id": user["org_id"]},
        {"$set": {"is_flagged": True, "flag_reason": "voided_by_reset", "updated_at": now}},
    )

    # Reverse budget consumed on void
    if report.get("smr_type") or report.get("activity_type"):
        smr_type = report.get("smr_type") or report.get("activity_type", "")
        hours = report.get("hours") or report.get("hours_worked", 0)
        if smr_type and report.get("project_id") and hours:
            budget = await db.activity_budgets.find_one({
                "org_id": user["org_id"],
                "project_id": report["project_id"],
                "smr_type_id": smr_type,
            })
            if budget:
                new_consumed = max(0, round((budget.get("consumed_hours", 0) or 0) - hours, 2))
                planned = budget.get("planned_hours", 0) or 1
                burn_pct = round((new_consumed / planned) * 100, 1)
                await db.activity_budgets.update_one(
                    {"id": budget["id"]},
                    {"$set": {
                        "consumed_hours": new_consumed,
                        "burn_percent": burn_pct,
                        "last_updated": now,
                    }}
                )

    # Reset report
    await db.employee_daily_reports.update_one({"id": report_id}, {"$set": {
        "approval_status": "SUBMITTED", "status": "SUBMITTED",
        "approved_by": None, "approved_at": None,
        "payroll_ready": False, "sessions_created": 0,
        "updated_at": now,
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
    """Central reports table with cost estimate — supports BOTH old and new schema"""
    org_id = user["org_id"]
    q = {"org_id": org_id}

    # Date filter: match both report_date (new) and date (old)
    if date_from or date_to:
        date_q_new = {}
        date_q_old = {}
        if date_from:
            date_q_new["$gte"] = date_from
            date_q_old["$gte"] = date_from
        if date_to:
            date_q_new["$lte"] = date_to
            date_q_old["$lte"] = date_to
        q["$or"] = [{"report_date": date_q_new}, {"date": date_q_old}]

    # Project filter: match both day_entries.project_id (new) and project_id (old)
    if project_id:
        proj_or = [{"day_entries.project_id": project_id}, {"project_id": project_id}]
        if "$or" in q:
            q = {"$and": [{"org_id": org_id}, {"$or": q["$or"]}, {"$or": proj_or}]}
        else:
            q["$or"] = proj_or

    # Employee filter: match both employee_id (new) and worker_id (old)
    if employee_id:
        emp_or = [{"employee_id": employee_id}, {"worker_id": employee_id}]
        if "$and" in q:
            q["$and"].append({"$or": emp_or})
        elif "$or" in q:
            q = {"$and": [{"org_id": org_id}, {"$or": q.pop("$or")}, {"$or": emp_or}]}
        else:
            q["$or"] = emp_or

    if approval_status:
        if "$and" in q:
            q["$and"].append({"approval_status": approval_status})
        else:
            q["approval_status"] = approval_status
    if day_status:
        if "$and" in q:
            q["$and"].append({"day_status": day_status})
        else:
            q["day_status"] = day_status

    reports = await db.employee_daily_reports.find(q, {"_id": 0}).sort([("report_date", -1), ("date", -1), ("created_at", -1)]).to_list(500)

    # Normalize: extract emp_id from either schema
    emp_ids = list(set(r.get("employee_id") or r.get("worker_id", "") for r in reports if r.get("employee_id") or r.get("worker_id")))
    users_data = await db.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(200)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users_data}

    profiles = await db.employee_profiles.find({"user_id": {"$in": emp_ids}}, {"_id": 0, "user_id": 1, "pay_type": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1, "working_days_per_month": 1, "standard_hours_per_day": 1}).to_list(200)
    profile_map = {p["user_id"]: p for p in profiles}

    # Load project codes from both schemas
    proj_ids = set()
    for r in reports:
        for e in r.get("day_entries", []):
            if e.get("project_id"):
                proj_ids.add(e["project_id"])
        if r.get("project_id"):
            proj_ids.add(r["project_id"])
    projects = await db.projects.find({"id": {"$in": list(proj_ids)}}, {"_id": 0, "id": 1, "code": 1}).to_list(100)
    proj_map = {p["id"]: p["code"] for p in projects}

    rows = []
    for r in reports:
        # Normalize fields from either schema
        emp_id = r.get("employee_id") or r.get("worker_id", "")
        if not emp_id:
            continue
        rep_date = r.get("report_date") or r.get("date", "")
        total_hours = r.get("total_hours") if r.get("total_hours") is not None else float(r.get("hours", 0) or 0)
        day_entries = r.get("day_entries", [])
        if not day_entries and r.get("project_id"):
            day_entries = [{"project_id": r["project_id"], "smr_type": r.get("smr_type", ""), "hours_worked": total_hours}]
        day_status_val = r.get("day_status", "WORKING" if total_hours > 0 else "")
        approval_status_val = r.get("approval_status") or r.get("status", "Draft")

        prof = profile_map.get(emp_id, {})
        pay_type = prof.get("pay_type", "Monthly")
        hr_rate = prof.get("hourly_rate") or 0
        if not hr_rate and prof.get("monthly_salary") and prof.get("working_days_per_month") and prof.get("standard_hours_per_day"):
            hr_rate = round(prof["monthly_salary"] / prof["working_days_per_month"] / prof["standard_hours_per_day"], 2)

        if pay_type == "Akord":
            cost_estimate = None
            cost_basis = "akord"
        elif hr_rate > 0:
            cost_estimate = round(total_hours * hr_rate, 2)
            cost_basis = "derived_hourly" if not prof.get("hourly_rate") else "hourly_rate"
        else:
            cost_estimate = None
            cost_basis = "unavailable"

        pcodes = list(set(proj_map.get(e.get("project_id", ""), "") for e in day_entries if e.get("project_id")))

        rows.append({
            "id": r["id"],
            "report_date": rep_date,
            "employee_id": emp_id,
            "employee_name": name_map.get(emp_id, r.get("worker_name", "")),
            "day_status": day_status_val,
            "approval_status": approval_status_val,
            "project_codes": pcodes,
            "pay_type": pay_type,
            "total_hours": total_hours,
            "cost_estimate": cost_estimate,
            "hourly_rate": hr_rate,
            "cost_basis": cost_basis,
            "entries_count": len(day_entries),
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





# ── Bulk Approve/Reject ─────────────────────────────

@router.post("/daily-reports/bulk-approve")
async def bulk_approve(data: dict, user: dict = Depends(require_m4)):
    """Bulk approve reports with overtime override support."""
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner/SiteManager")

    org_id = user["org_id"]
    report_ids = data.get("report_ids", [])
    overrides = data.get("overrides", {})
    now = datetime.now(timezone.utc).isoformat()

    succeeded = []
    blocked = []
    failed = []

    from app.services.hours_validator import get_worker_hours_for_day

    for rid in report_ids:
        report = await db.employee_daily_reports.find_one({"id": rid, "org_id": org_id}, {"_id": 0})
        if not report:
            failed.append({"id": rid, "reason": "not_found"})
            continue

        status = report.get("approval_status") or report.get("status", "")
        if status == "APPROVED":
            failed.append({"id": rid, "reason": "already_approved"})
            continue

        worker_id = report.get("worker_id", "")
        date = report.get("date", "")
        hours = float(report.get("hours", 0))

        # Day total — informational only (for warnings + future group-level UI)
        day_total = await get_worker_hours_for_day(org_id, worker_id, date)

        # Per-line decision
        line_is_overtime = hours > 8

        if line_is_overtime and rid not in overrides:
            proj_name = ""
            pid = report.get("project_id", "")
            if pid:
                proj_doc = await db.projects.find_one({"id": pid}, {"_id": 0, "name": 1})
                if proj_doc:
                    proj_name = proj_doc.get("name", "")
            blocked.append({
                "id": rid,
                "worker_name": report.get("worker_name", ""),
                "worker_id": worker_id,
                "current_hours": day_total,
                "report_hours": hours,
                "date": date,
                "project_id": pid,
                "project_name": proj_name,
            })
            continue

        override = overrides.get(rid, {})
        coefficient = 1.0
        reason_text = ""

        if line_is_overtime and rid in overrides:
            o_reg = float(override.get("regular_hours", 0))
            o_ot = float(override.get("overtime_hours", 0))
            o_coef = float(override.get("overtime_coefficient", 0))
            o_reason = (override.get("reason") or "").strip()
            if abs(o_reg + o_ot - hours) > 0.01:
                failed.append({"id": rid, "reason": "split_mismatch"})
                continue
            if o_reg < 0 or o_ot < 0:
                failed.append({"id": rid, "reason": "negative_split_value"})
                continue
            # Coefficient must be >= 1 (B8 fix: was > 1)
            if o_coef < 1:
                failed.append({"id": rid, "reason": "coefficient_must_be_at_least_1"})
                continue
            if not o_reason:
                failed.append({"id": rid, "reason": "reason_required"})
                continue
            regular_hours = o_reg
            overtime_hours = o_ot
            coefficient = o_coef
            reason_text = o_reason
        elif line_is_overtime:
            regular_hours = min(hours, 8)
            overtime_hours = max(0, hours - 8)
        else:
            regular_hours = hours
            overtime_hours = 0

        try:
            smr_type = report.get("smr_type") or report.get("activity_type", "")
            project_id = report.get("project_id", "")
            rate = await _get_hourly_rate_for_approval(org_id, worker_id)
            # B5 fix: labor_cost now applies coefficient on overtime portion
            labor_cost = round(regular_hours * rate + overtime_hours * rate * coefficient, 2)

            slip_number = report.get("slip_number")
            if not slip_number:
                counter = await db.org_counters.find_one_and_update(
                    {"org_id": org_id, "type": "slip_number"},
                    {"$inc": {"value": 1}},
                    upsert=True, return_document=True,
                )
                slip_number = counter.get("value", 1)

            session = {
                "id": str(uuid.uuid4()), "org_id": org_id,
                "worker_id": worker_id, "worker_name": report.get("worker_name", ""),
                "site_id": project_id, "smr_type": smr_type,
                "started_at": f"{date}T08:00:00", "ended_at": f"{date}T{8+int(hours):02d}:00:00",
                "duration_hours": hours, "hourly_rate": rate, "labor_cost": labor_cost,
                "approved_report_id": rid, "approved_by": user["id"],
                "is_overtime": line_is_overtime,
                "regular_hours": regular_hours,
                "overtime_hours": overtime_hours,
                "overtime_coefficient": coefficient if line_is_overtime else None,
                "overtime_reason": reason_text if line_is_overtime else None,
                "override_by_user_id": user["id"] if line_is_overtime and rid in overrides else None,
                "override_at": now if line_is_overtime and rid in overrides else None,
                "created_at": now,
            }
            await db.work_sessions.insert_one(session)

            # B6 fix: freeze split on the report document itself
            await db.employee_daily_reports.update_one({"id": rid}, {"$set": {
                "approval_status": "APPROVED", "status": "APPROVED",
                "approved_by": user["id"], "approved_at": now,
                "slip_number": slip_number, "payroll_ready": True,
                "regular_hours": regular_hours,
                "overtime_hours": overtime_hours,
                "overtime_coefficient": coefficient if line_is_overtime else None,
                "overtime_reason": reason_text if line_is_overtime else None,
                "labor_cost": labor_cost,
                "updated_at": now,
            }})

            succeeded.append({"id": rid, "slip_number": slip_number, "overtime_applied": line_is_overtime})
        except Exception as e:
            failed.append({"id": rid, "reason": str(e)})

    return {"succeeded": succeeded, "blocked_for_override": blocked, "failed": failed}


@router.post("/daily-reports/bulk-reject")
async def bulk_reject(data: dict, user: dict = Depends(require_m4)):
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner/SiteManager")

    org_id = user["org_id"]
    report_ids = data.get("report_ids", [])
    reason = data.get("reason", "")
    now = datetime.now(timezone.utc).isoformat()

    succeeded = []
    failed = []

    for rid in report_ids:
        report = await db.employee_daily_reports.find_one({"id": rid, "org_id": org_id})
        if not report:
            failed.append({"id": rid, "reason": "not_found"})
            continue
        status = report.get("approval_status") or report.get("status", "")
        if status in ("APPROVED",):
            failed.append({"id": rid, "reason": "already_approved"})
            continue

        await db.employee_daily_reports.update_one({"id": rid}, {"$set": {
            "approval_status": "REJECTED", "status": "REJECTED",
            "reject_reason": reason, "rejected_by": user["id"],
            "updated_at": now,
        }})
        succeeded.append({"id": rid})

    return {"succeeded": succeeded, "failed": failed}

