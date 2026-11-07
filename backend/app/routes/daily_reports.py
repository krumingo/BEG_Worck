"""
Routes - Structured Employee Daily Report.
New model alongside existing attendance/work_reports (which remain untouched).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import math
import uuid

from app.db import db
from app.tenancy import project_team
from app.deps.auth import get_current_user
from app.deps.modules import require_m4
from app.tenancy.data_access import TenantData
from app.services.labor_cost import void_labor_approvals
from app.services.report_corrections import (CORRECTOR, audit_report_correction, authorize_report_edit,
                                             correction_fields, reopen_effects, self_approval_ids)


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

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
    tenant = TenantData.for_resolved_org(db, org_id)
    query = {
        "org_id": org_id,
        "$or": [
            {"employee_id": employee_id, "report_date": report_date},
            {"worker_id": employee_id, "date": report_date},
        ],
        "approval_status": {"$nin": ["REJECTED"]},
    }
    reports = await tenant.employee_daily_reports.find(query, {"_id": 0}).to_list(200)

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
        proj_docs = await tenant.projects.find(
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
    attendance = await tenant.attendance_entries.find_one(
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
    tenant = _tenant(user)
    org_id = user["org_id"]
    validate_report(data)

    # Check no duplicate for same employee+date
    existing = await tenant.employee_daily_reports.find_one({
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
    await tenant.employee_daily_reports.insert_one(report)
    clean = {k: v for k, v in report.items() if k != "_id"}

    # Hours check — add warnings to response (non-blocking)
    hours_info = await check_employee_hours(org_id, data.employee_id, data.report_date)
    clean["hours_warnings"] = hours_info
    return clean


# LAB-01-C (LAB01B-1 / FG-64): the fields a person may write on a report line — the same
# set POST /daily-reports (DayEntryInput) and the batch save store. Anything that would
# price or classify the line (SMR package, pay type, piece rate, approved quantity,
# DOWNTIME) is set only by an approver's record, never by the person who fills the line.
DAY_ENTRY_FIELDS = ("id", "project_id", "smr_id", "extra_work_id", "work_description",
                    "hours_worked", "note")
DAY_ENTRY_FORBIDDEN = ("execution_package_id", "pay_type", "piece_rate", "approved_quantity",
                       "labor_pay_type", "labor_piece_rate", "cost_type", "activity_type")


def _clean_day_entries(entries) -> list:
    """Validate and rebuild ``day_entries`` from the allowed fields only (400 on a pricing
    field, a non-list, a non-object entry or negative/non-numeric hours)."""
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="day_entries must be a list")
    clean = []
    seen_ids = set()
    for e in entries:
        if not isinstance(e, dict):
            raise HTTPException(status_code=400, detail="each day entry must be an object")
        bad = sorted(k for k in e if k in DAY_ENTRY_FORBIDDEN)
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"day_entries may not set {bad}: package, pay type, rate, quantity and "
                       f"DOWNTIME are set by the approver, not on the report line")
        try:
            hours = float(e.get("hours_worked", 0) or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="hours_worked must be a number")
        if not math.isfinite(hours) or hours < 0:
            raise HTTPException(status_code=400, detail="hours_worked cannot be negative")
        row = {k: e.get(k) for k in DAY_ENTRY_FIELDS if k in e}
        row["id"] = row.get("id") or str(uuid.uuid4())
        # LAB-01-D (FG-72): entry ids are unique per report
        if not isinstance(row["id"], str) or row["id"] in seen_ids:
            raise HTTPException(status_code=400, detail=f"duplicate day entry id: {row['id']}")
        seen_ids.add(row["id"])
        row["hours_worked"] = hours
        clean.append(row)
    return clean


@router.put("/daily-reports/{report_id}")
async def update_daily_report(report_id: str, data: dict, user: dict = Depends(require_m4)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": org_id})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    allowed = ["day_status", "leave_from", "leave_to", "notes", "day_entries"]
    update = {k: v for k, v in data.items() if k in allowed}

    if "day_entries" in update:
        update["day_entries"] = _clean_day_entries(update["day_entries"])
        update["total_hours"] = round(sum(float(e.get("hours_worked", 0)) for e in update["day_entries"]), 2)

    # LAB-01-H (R36): the author corrects their own DRAFT / returned report; Admin, Owner or
    # the project's SiteManager corrects ANY report (approved included) — with an AuditEvent.
    projects = [e.get("project_id") for e in (report.get("day_entries") or [])]
    projects += [e.get("project_id") for e in (update.get("day_entries") or [])]
    if report.get("project_id"):
        projects.append(report["project_id"])
    mode = await authorize_report_edit(
        user, report, projects=projects,
        author_ids=(report.get("employee_id"), report.get("created_by")),
        author_statuses=("DRAFT", "REJECTED"), tenant=tenant)

    now = datetime.now(timezone.utc).isoformat()
    update["updated_at"] = now
    # LAB-01-I (LAB01H-1): a corrected APPROVED report goes back to SUBMITTED
    set_fields, add = correction_fields(report, user, mode, now)
    update.update(set_fields)
    before = {k: report.get(k) for k in update if k not in ("updated_at", "corrected_by", "corrected_at", "reopened_by_correction")}
    # LAB-01-D (FG-72): bump the version and void the approvals BEFORE the content write
    await void_labor_approvals(tenant, org_id, report_id, user["id"],
                               "report_corrected" if mode == CORRECTOR else "report_edited")
    await tenant.employee_daily_reports.update_one(
        {"id": report_id}, {"$set": update, **({"$addToSet": add} if add else {})})
    await reopen_effects(tenant, org_id, report, user, now)
    await audit_report_correction(db, user=user, mode=mode, report=report, before=before,
                                  after={k: update[k] for k in before}, endpoint="PUT /daily-reports/{id}")
    return await tenant.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


@router.post("/daily-reports/{report_id}/submit")
async def submit_daily_report(report_id: str, user: dict = Depends(require_m4)):
    tenant = _tenant(user)
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report["approval_status"] not in ["DRAFT", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Only DRAFT/REJECTED can be submitted")

    now = datetime.now(timezone.utc).isoformat()
    await tenant.employee_daily_reports.update_one({"id": report_id}, {"$set": {
        "approval_status": "SUBMITTED", "submitted_by": user["id"], "updated_at": now,
    }})
    return await tenant.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


# ── Single-source-of-truth actions (P1-0.5) ────────────────────────
# approve_report_one / reject_report_one are the ONLY place approve/reject
# business logic lives. Single endpoints call them once; bulk endpoints call
# them in a loop — so single and bulk produce IDENTICAL data.

async def approve_report_one(report: dict, actor: dict, override: dict | None = None,
                             block_overtime_without_override: bool = False) -> dict:
    """
    Canonical approval for ONE report. Does NOT raise — returns:
      {"status": "ok"|"blocked"|"failed", "report_id": ..., ...}
    Canonical decisions (P1-0.5):
      - slip counter key: counter_type="slip_number"
      - work_session SMR field: smr_type_id (canonical) + smr_type (compat)
      - labor_cost = regular*rate + overtime*rate*coefficient
      - default overtime_coefficient = 1.0 (no auto-overpay), split always stored
    """
    tenant = _tenant(actor)
    org_id = actor["org_id"]
    rid = report["id"]
    now = datetime.now(timezone.utc).isoformat()

    status = report.get("approval_status") or report.get("status", "")
    if status == "APPROVED":
        return {"status": "failed", "report_id": rid, "reason": "already_approved"}
    # LAB-01-I (LAB01H-1, CLAUDE §8): nobody approves a report they authored or corrected
    if actor.get("id") in self_approval_ids(report):
        return {"status": "failed", "report_id": rid, "reason": "self_approval"}

    worker_id = report.get("worker_id", "")
    hours = float(report.get("hours") or report.get("hours_worked") or 0)
    report_date = report.get("date") or report.get("report_date") or now[:10]
    project_id = report.get("project_id", "")
    smr_type = report.get("smr_type") or report.get("activity_type", "")

    line_is_overtime = hours > 8

    # Overtime gate. Bulk path blocks >8h until admin supplies an override
    # (drives the override modal). Single path (B2) does NOT block — falls
    # through to the default split below.
    if line_is_overtime and override is None and block_overtime_without_override:
        from app.services.hours_validator import get_worker_hours_for_day
        day_total = await get_worker_hours_for_day(org_id, worker_id, report_date)
        proj_name = ""
        if project_id:
            proj_doc = await tenant.projects.find_one({"id": project_id}, {"_id": 0, "name": 1})
            if proj_doc:
                proj_name = proj_doc.get("name", "")
        return {
            "status": "blocked", "report_id": rid,
            "worker_name": report.get("worker_name", ""), "worker_id": worker_id,
            "current_hours": day_total, "report_hours": hours, "date": report_date,
            "project_id": project_id, "project_name": proj_name,
        }

    # Split + coefficient (default coef 1.0 = no overpay)
    coefficient = 1.0
    reason_text = ""
    if line_is_overtime and override:
        o_reg = float(override.get("regular_hours", 0))
        o_ot = float(override.get("overtime_hours", 0))
        o_coef = float(override.get("overtime_coefficient", 0))
        o_reason = (override.get("reason") or "").strip()
        if abs(o_reg + o_ot - hours) > 0.01:
            return {"status": "failed", "report_id": rid, "reason": "split_mismatch"}
        if o_reg < 0 or o_ot < 0:
            return {"status": "failed", "report_id": rid, "reason": "negative_split_value"}
        if o_coef < 1:
            return {"status": "failed", "report_id": rid, "reason": "coefficient_must_be_at_least_1"}
        if not o_reason:
            return {"status": "failed", "report_id": rid, "reason": "reason_required"}
        regular_hours, overtime_hours, coefficient, reason_text = o_reg, o_ot, o_coef, o_reason
    elif line_is_overtime:
        regular_hours = min(hours, 8)
        overtime_hours = max(0, hours - 8)
    else:
        regular_hours = hours
        overtime_hours = 0

    # A) Slip number — canonical counter_type sequence (shared by single + bulk)
    slip_number = report.get("slip_number")
    if not slip_number:
        counter = await tenant.org_counters.find_one_and_update(
            {"org_id": org_id, "counter_type": "slip_number"},
            {"$inc": {"value": 1}}, upsert=True, return_document=True,
        )
        slip_number = (counter or {}).get("value", 1)

    rate = await _get_hourly_rate_for_approval(org_id, worker_id)
    labor_cost = round(regular_hours * rate + overtime_hours * rate * coefficient, 2)

    # B) work_session (source of truth for labor cost) — dedup like single path
    sessions_created = 0
    if worker_id and hours and hours > 0 and project_id:
        existing_ws = await tenant.work_sessions.find_one({
            "org_id": org_id, "worker_id": worker_id, "site_id": project_id,
            "smr_type_id": smr_type,
            "started_at": {"$gte": f"{report_date}T00:00:00", "$lte": f"{report_date}T23:59:59"},
            "source_method": "APPROVED_REPORT",
        })
        if not existing_ws:
            project = await tenant.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "name": 1})
            session = {
                "id": str(uuid.uuid4()), "org_id": org_id,
                "worker_id": worker_id, "worker_name": report.get("worker_name", ""),
                "site_id": project_id, "site_name": (project or {}).get("name", ""),
                "smr_type_id": smr_type,   # canonical
                "smr_type": smr_type,      # compat (P1-0.5)
                "started_at": f"{report_date}T08:00:00",
                "ended_at": f"{report_date}T{8 + int(hours):02d}:{int((hours % 1) * 60):02d}:00",
                "source_method": "APPROVED_REPORT",
                "is_flagged": False, "flag_reason": None,
                "duration_hours": round(hours, 2),
                "is_overtime": line_is_overtime,
                "overtime_type": "over_8h" if line_is_overtime else None,
                "regular_hours": regular_hours, "overtime_hours": overtime_hours,
                "overtime_coefficient": coefficient,
                "overtime_reason": reason_text if line_is_overtime else None,
                "override_by_user_id": actor["id"] if (line_is_overtime and override) else None,
                "override_at": now if (line_is_overtime and override) else None,
                "hourly_rate_at_date": rate, "labor_cost": labor_cost,
                "notes": report.get("notes", ""),
                "approved_report_id": rid, "approved_by": actor["id"],
                "entered_by_admin": report.get("entered_by_admin", False),
                "entry_mode": report.get("entry_mode", "technician_portal"),
                "submitted_by": report.get("submitted_by"),
                "created_at": now, "updated_at": now,
            }
            await tenant.work_sessions.insert_one(session)
            sessions_created = 1

        # C2) activity_budget consumed
        if smr_type and project_id:
            budget = await tenant.activity_budgets.find_one({
                "org_id": org_id, "project_id": project_id, "smr_type_id": smr_type,
            })
            if budget:
                new_consumed = round((budget.get("consumed_hours", 0) or 0) + hours, 2)
                planned = budget.get("planned_hours", 0) or 1
                burn_pct = round((new_consumed / planned) * 100, 1)
                await tenant.activity_budgets.update_one(
                    {"id": budget["id"]},
                    {"$set": {"consumed_hours": new_consumed, "burn_percent": burn_pct, "last_updated": now}},
                )

        # C3) worker_calendar
        cal_existing = await tenant.worker_calendar.find_one(
            {"org_id": org_id, "worker_id": worker_id, "date": report_date}
        )
        cal_doc = {
            "org_id": org_id, "worker_id": worker_id, "date": report_date,
            "status": "working", "site_id": project_id,
            "hours": round(hours, 2), "source": "approved_report", "updated_at": now,
        }
        if cal_existing:
            await tenant.worker_calendar.update_one({"id": cal_existing["id"]}, {"$set": cal_doc})
        else:
            cal_doc["id"] = str(uuid.uuid4())
            cal_doc["created_at"] = now
            cal_doc["created_by"] = "system"
            await tenant.worker_calendar.insert_one(cal_doc)

    # D) Update report status + frozen split
    update = {
        "approval_status": "APPROVED", "status": "APPROVED",
        "approved_by": actor["id"], "approved_at": now, "updated_at": now,
        "slip_number": slip_number, "payroll_ready": True,
        "sessions_created": sessions_created,
        "regular_hours": regular_hours, "overtime_hours": overtime_hours,
        "overtime_coefficient": coefficient if line_is_overtime else None,
        "overtime_reason": reason_text if line_is_overtime else None,
        "labor_cost": labor_cost,
    }
    await tenant.employee_daily_reports.update_one({"id": rid}, {"$set": update})
    result = await tenant.employee_daily_reports.find_one({"id": rid}, {"_id": 0})

    # E) Hours warnings (informational)
    emp_id = report.get("employee_id") or worker_id
    r_date = report.get("report_date") or report.get("date", now[:10])
    warnings = []
    if emp_id and r_date:
        warnings = await check_employee_hours(org_id, emp_id, r_date)

    return {"status": "ok", "report_id": rid, "slip_number": slip_number,
            "overtime_applied": line_is_overtime, "report": result, "hours_warnings": warnings}


async def reject_report_one(report: dict, actor: dict, reason: str = "") -> dict:
    """
    Canonical rejection for ONE report. Does NOT raise — returns:
      {"status": "ok"|"skipped"|"failed", "report_id": ...}
    Decision A: APPROVED cannot be rejected directly (failed); already REJECTED is an
    idempotent skip; always writes rejected_by + reject_reason + updated_at.
    """
    tenant = _tenant(actor)
    rid = report["id"]
    now = datetime.now(timezone.utc).isoformat()
    status = report.get("approval_status") or report.get("status", "")
    if status == "APPROVED":
        return {"status": "failed", "report_id": rid, "reason": "cannot_reject_approved"}
    if status == "REJECTED":
        return {"status": "skipped", "report_id": rid, "reason": "already_rejected"}
    # LAB-01-D (FG-72): bump + void BEFORE the status write
    await void_labor_approvals(tenant, actor["org_id"], rid, actor["id"], "report_rejected")
    await tenant.employee_daily_reports.update_one({"id": rid}, {"$set": {
        "approval_status": "REJECTED", "status": "REJECTED",
        "reject_reason": reason, "rejected_by": actor["id"], "updated_at": now,
    }})
    return {"status": "ok", "report_id": rid}


_APPROVE_FAIL_MSG = {
    "already_approved": "Вече одобрен отчет не може да бъде одобрен повторно.",
    "split_mismatch": "Сборът нормални+извънредни часове не съвпада с часовете на отчета.",
    "negative_split_value": "Отрицателни часове в разделението.",
    "coefficient_must_be_at_least_1": "Коефициентът за извънреден труд трябва да е поне 1.",
    "reason_required": "Изисква се причина за override на извънреден труд.",
    "self_approval": "Не можете да одобрите отчет, който сте създали или поправили — одобрява друг човек.",
}


@router.post("/daily-reports/{report_id}/approve")
async def approve_daily_report(report_id: str, data: dict = {}, user: dict = Depends(require_m4)):
    """
    SOURCE OF TRUTH: the POSTING EVENT (creates work_sessions — see SOURCE_OF_TRUTH.md).
    P1-0.5: delegates to approve_report_one so single and bulk approve are identical.
    Single path does NOT block >8h (B2): default split with coefficient 1.0.
    Optional body: {"override": {regular_hours, overtime_hours, overtime_coefficient, reason}}.
    """
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can approve")
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    res = await approve_report_one(report, user, override=(data or {}).get("override"),
                                   block_overtime_without_override=False)
    if res["status"] == "failed":
        code = 403 if res["reason"] == "self_approval" else 400
        raise HTTPException(status_code=code, detail=_APPROVE_FAIL_MSG.get(res["reason"], res["reason"]))
    if res["status"] == "blocked":  # not expected on single path
        raise HTTPException(status_code=409, detail="overtime_requires_override")

    result = res["report"]
    result["hours_warnings"] = res.get("hours_warnings", [])
    return result


@router.post("/daily-reports/{report_id}/reject")
async def reject_daily_report(report_id: str, data: dict = {}, user: dict = Depends(require_m4)):
    """P1-0.5: delegates to reject_report_one (same logic as bulk)."""
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can reject")
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    res = await reject_report_one(report, user, (data or {}).get("reason", ""))
    if res["status"] == "failed":
        raise HTTPException(status_code=400, detail="Отчет със статус APPROVED не може да бъде отхвърлен.")
    # ok or skipped(already_rejected) → idempotent: return current report
    return await tenant.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


# R36 correctors: Admin, Owner, SiteManager (the project's — checked after the lookup)
RESET_ROLES = ("Admin", "Owner", "SiteManager")
# LAB-01-M (FG-112): every caller without the right to reset THIS report gets the same 403 —
# a missing report, another project's report, its payroll state are never revealed to them.
RESET_DENIED = "Нямате право да връщате този отчет"


async def _reset_status_field(report: dict):
    """(field, value) the report's approval is read from — the CAS compares exactly it."""
    if report.get("approval_status"):
        return "approval_status", report["approval_status"]
    return "status", report.get("status")


async def _return_budget_once(tenant, org_id: str, report: dict, reset_id: str, now: str,
                              session=None) -> bool:
    """LAB-01-M (FG-110): give the report's consumed hours back to its activity budget at most
    once per reset (keyed by ``reset_id`` in ``returned_resets``). Runs INSIDE the reset's
    transaction (``session``), so it commits together with the claim or not at all."""
    smr_type = report.get("smr_type") or report.get("activity_type") or ""
    hours = report.get("hours") or report.get("hours_worked") or 0
    if not (smr_type and report.get("project_id") and hours):
        return True
    budget = await tenant.activity_budgets.find_one({
        "org_id": org_id, "project_id": report["project_id"], "smr_type_id": smr_type}, session=session)
    if not budget:
        return True
    if reset_id in (budget.get("returned_resets") or []):
        return True
    new_consumed = max(0, round((budget.get("consumed_hours", 0) or 0) - float(hours), 2))
    planned = budget.get("planned_hours", 0) or 1
    res = await tenant.activity_budgets.update_one(
        {"id": budget["id"], "consumed_hours": budget.get("consumed_hours"),
         "returned_resets": {"$ne": reset_id}},
        {"$set": {"consumed_hours": new_consumed, "burn_percent": round(new_consumed / planned * 100, 1),
                  "last_updated": now},
         "$addToSet": {"returned_resets": reset_id}}, session=session)
    if not getattr(res, "modified_count", 0):
        # the budget changed under us: abort the whole transaction — nothing is written
        raise HTTPException(status_code=409, detail="Бюджетът на дейността току-що беше променен — опитайте пак")
    return True


async def _run_reset_transaction(raw_db, body):
    """LAB-01-N: the reset's writes run in ONE MongoDB transaction (auth_tx.run_in_transaction):
    all commit together or none. A deployment without transactions is refused (503, nothing
    written) — there is no non-transactional path here. (The DB-free tests replace this
    function explicitly with a session-less runner: tests/test_lab_01_l_reset.py.)"""
    from app.services.auth_tx import TransactionsUnavailable, run_in_transaction
    try:
        return await run_in_transaction(raw_db, body)
    except TransactionsUnavailable:
        raise HTTPException(status_code=503, detail=(
            "Базата данни не поддържа транзакции — връщането на отчета не е изпълнено"))


@router.post("/daily-reports/{report_id}/reset")
async def reset_daily_report(report_id: str, user: dict = Depends(require_m4)):
    """Reset an APPROVED report back to SUBMITTED. Voids created work_sessions."""
    from app.deps.auth import can_manage_project
    tenant = _tenant(user)
    org_id = user["org_id"]
    # PM73-01: deny by default BEFORE the lookup.
    if user.get("role") not in RESET_ROLES:
        raise HTTPException(status_code=403, detail=RESET_DENIED)
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": org_id})
    privileged = user.get("role") in ("Admin", "Owner")
    if not report:
        if not privileged:
            raise HTTPException(status_code=403, detail=RESET_DENIED)
        raise HTTPException(status_code=404, detail="Report not found")
    projects = [e.get("project_id") for e in (report.get("day_entries") or []) if isinstance(e, dict)]
    if report.get("project_id"):
        projects.append(report["project_id"])
    if not privileged:
        # LAB-01-M (FG-112): the SiteManager's project right is decided FIRST, so a SiteManager
        # of another project learns neither the payroll state nor the status of the report.
        project_ids = sorted({p for p in projects if p})
        if not project_ids:
            raise HTTPException(status_code=403, detail=RESET_DENIED)
        for pid in project_ids:
            if not await can_manage_project(user, pid):
                raise HTTPException(status_code=403, detail=RESET_DENIED)
    # LAB-01-L (FG-99): R36 role rule + the LAB-01-J payroll lock (Pay Run lines, both
    # formats, confirmed runs included) — 409 when the report is in payroll. A caller who may
    # reset the report gets the details.
    await authorize_report_edit(user, report, projects=projects, author_ids=(),
                                author_statuses=(), tenant=tenant)
    current_status = (report.get("approval_status") or report.get("status") or "").upper()
    if current_status != "APPROVED":
        # LAB-01-M (FG-110): not (or no longer) approved — e.g. a concurrent reset won — 409
        raise HTTPException(status_code=409, detail="Само одобрен отчет може да бъде върнат (вече е върнат или не е одобрен) — презаредете")

    # Check payroll not finalized for this period (both formats: date / report_date)
    report_date = report.get("date") or report.get("report_date") or ""
    if report_date:
        # R0-06-C01: a payment in progress or failed may already have moved money — locked too.
        finalized = await tenant.pay_runs.find_one({
            "org_id": org_id,
            "status": {"$in": ["paid", "paying", "payment_failed"]},
            "period_start": {"$lte": report_date},
            "period_end": {"$gte": report_date},
        })
        if finalized:
            raise HTTPException(status_code=400, detail="Cannot reset: payroll for this period is paid")

    now = datetime.now(timezone.utc).isoformat()
    reset_id = str(uuid.uuid4())
    reset_fields = {
        "approval_status": "SUBMITTED", "status": "SUBMITTED",
        "approved_by": None, "approved_at": None,
        "payroll_ready": False, "sessions_created": 0,
    }

    async def body(session):
        # LAB-01-M/N (FG-110): ONE transaction — the compare-and-set claim of the report
        # (status APPROVED → SUBMITTED, report_version bump, last_reset), the voided work
        # sessions and quantity approvals and the budget return commit together or not at
        # all. Everything is re-read inside (the driver may retry the body): a concurrent
        # winner makes this claim find nothing → 409, nothing written.
        current = await tenant.employee_daily_reports.find_one(
            {"id": report_id, "org_id": org_id}, session=session)
        if not current:
            raise HTTPException(status_code=409, detail="Отчетът вече не съществува — презаредете")
        field, value = await _reset_status_field(current)
        if (value or "").upper() != "APPROVED":
            raise HTTPException(status_code=409, detail=(
                "Отчетът току-що беше върнат или променен от друг човек — презаредете"))
        won = await tenant.employee_daily_reports.find_one_and_update(
            {"id": report_id, "org_id": org_id, field: value},
            {"$set": dict(reset_fields, updated_at=now,
                          last_reset={"id": reset_id, "by": user["id"], "at": now,
                                      "budget_returned": True, "audit_written": True}),
             "$inc": {"report_version": 1}}, session=session)
        if not won:
            raise HTTPException(status_code=409, detail=(
                "Отчетът току-що беше върнат или променен от друг човек — презаредете"))
        await tenant.work_sessions.update_many(
            {"approved_report_id": report_id, "org_id": org_id},
            {"$set": {"is_flagged": True, "flag_reason": "voided_by_reset", "updated_at": now}},
            session=session)
        await void_labor_approvals(tenant, org_id, report_id, user["id"], "report_reset",
                                   bump=False, session=session)
        await _return_budget_once(tenant, org_id, current, reset_id, now, session=session)
        # LAB-01-L (FG-99) / LAB-01-O: the canonical chained AuditEvent (who, when, before /
        # after) is written INSIDE the same transaction — it commits with the reset or not at all
        before = {k: current.get(k) for k in reset_fields}
        await audit_report_correction(db, user=user, mode=CORRECTOR, report=current, before=before,
                                      after=dict(reset_fields, reset_id=reset_id, budget_returned=True),
                                      endpoint="POST /daily-reports/{id}/reset",
                                      action="daily_report.reset", session=session)
        return current

    await _run_reset_transaction(db, body)
    return await tenant.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


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
    tenant = _tenant(user)
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

    reports = await tenant.employee_daily_reports.find(q, {"_id": 0}).sort([("report_date", -1), ("date", -1), ("created_at", -1)]).to_list(500)

    # Normalize: extract emp_id from either schema
    emp_ids = list(set(r.get("employee_id") or r.get("worker_id", "") for r in reports if r.get("employee_id") or r.get("worker_id")))
    users_data = await tenant.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(200)
    name_map = {u["id"]: f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() for u in users_data}

    profiles = await tenant.employee_profiles.find({"user_id": {"$in": emp_ids}}, {"_id": 0, "user_id": 1, "pay_type": 1, "hourly_rate": 1, "daily_rate": 1, "monthly_salary": 1, "working_days_per_month": 1, "standard_hours_per_day": 1}).to_list(200)
    profile_map = {p["user_id"]: p for p in profiles}

    # Load project codes from both schemas
    proj_ids = set()
    for r in reports:
        for e in r.get("day_entries", []):
            if e.get("project_id"):
                proj_ids.add(e["project_id"])
        if r.get("project_id"):
            proj_ids.add(r["project_id"])
    projects = await tenant.projects.find({"id": {"$in": list(proj_ids)}}, {"_id": 0, "id": 1, "code": 1}).to_list(100)
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
    tenant = _tenant(user)
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

    reports = await tenant.employee_daily_reports.find(q, {"_id": 0}).to_list(1000)

    # Load names
    emp_ids = list(set(r["employee_id"] for r in reports))
    users_data = await tenant.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(200)
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
    tenant = _tenant(user)
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]}, {"_id": 0})
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
    tenant = _tenant(user)
    q = {"org_id": user["org_id"]}
    if employee_id: q["employee_id"] = employee_id
    if report_date: q["report_date"] = report_date
    if date_from or date_to:
        q["report_date"] = {}
        if date_from: q["report_date"]["$gte"] = date_from
        if date_to: q["report_date"]["$lte"] = date_to
    if project_id:
        q["day_entries.project_id"] = project_id

    reports = await tenant.employee_daily_reports.find(q, {"_id": 0}).sort("report_date", -1).to_list(500)
    return reports


# ── Project Day Status (for Personnel card) ───────────────────────

@router.get("/daily-reports/project-day-status/{project_id}")
async def get_project_day_status(project_id: str, date: Optional[str] = None, user: dict = Depends(require_m4)):
    """Get today's report status for all employees linked to a project"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get team members
    team_ids = await project_team.project_member_ids(
        project_team.tenant_for_org(db, org_id), project_id, active_only=False, limit=100)

    # Also get employees who have reported on this project today
    reports_today = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "report_date": target_date, "day_entries.project_id": project_id},
        {"_id": 0}
    ).to_list(200)
    report_emp_ids = [r["employee_id"] for r in reports_today]

    all_ids = list(set(team_ids + report_emp_ids))
    if not all_ids:
        return {"project_id": project_id, "date": target_date, "employees": []}

    # Load employee info
    users = await tenant.users.find(
        {"id": {"$in": all_ids}, "org_id": org_id},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "avatar_url": 1, "role": 1}
    ).to_list(100)
    user_map = {u["id"]: u for u in users}

    # Load all reports for these employees today
    all_reports = await tenant.employee_daily_reports.find(
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
    tenant = _tenant(user)
    org_id = user["org_id"]

    # Execution packages
    epkgs = await tenant.execution_packages.find(
        {"org_id": org_id, "project_id": project_id},
        {"_id": 0, "id": 1, "activity_name": 1, "unit": 1, "qty": 1, "status": 1}
    ).to_list(200)

    # Extra work drafts that are active
    extras = await tenant.extra_work_drafts.find(
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
    tenant = _tenant(user)
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

    # LAB-01-E (FG-79) + LAB-01-H (R36): every existing report this batch would change is
    # checked BEFORE any write — the author (the worker, or who created it) only on their own
    # DRAFT / returned report; Admin, Owner or the SiteManager of the batch's project on ANY
    # report (approved included), audited. One refusal → nothing written.
    existing_by_emp, modes, refused = {}, {}, []
    for emp_id in by_emp:
        existing = await tenant.employee_daily_reports.find_one({
            "org_id": org_id, "employee_id": emp_id, "report_date": report_date
        })
        if not existing:
            continue
        try:
            modes[emp_id] = await authorize_report_edit(
                user, existing, projects=[project_id],
                author_ids=(existing.get("employee_id"), existing.get("created_by")),
                author_statuses=("DRAFT", "REJECTED"), tenant=tenant)
        except HTTPException as exc:
            refused.append({"employee_id": emp_id, "report_id": existing["id"],
                            "status_code": exc.status_code, "reason": exc.detail})
        existing_by_emp[emp_id] = existing
    if refused:
        code = max(r["status_code"] for r in refused)  # 409 (payroll) > 403 > 400
        raise HTTPException(status_code=code, detail={"message": "batch-save refused; nothing written",
                                                      "refused": refused})

    for emp_id, emp_entries in by_emp.items():
        total_hours = round(sum(e["hours_worked"] for e in emp_entries), 2)

        existing = existing_by_emp.get(emp_id)

        if existing:
            # Merge: add new entries to existing, avoid exact duplicates
            old_entries = existing.get("day_entries", [])
            # Keep old entries for OTHER projects, replace for THIS project
            kept = [e for e in old_entries if e.get("project_id") != project_id]
            merged = kept + emp_entries
            merged_total = round(sum(e["hours_worked"] for e in merged), 2)
            mode = modes[emp_id]
            change = {"day_entries": merged, "total_hours": merged_total, "updated_at": now}
            set_fields, add = correction_fields(existing, user, mode, now)  # LAB-01-I
            change.update(set_fields)
            # LAB-01-D (FG-72): bump + void BEFORE the content write
            await void_labor_approvals(tenant, org_id, existing["id"], user["id"],
                                       "report_corrected" if mode == CORRECTOR else "batch_saved")
            await tenant.employee_daily_reports.update_one(
                {"id": existing["id"]}, {"$set": change, **({"$addToSet": add} if add else {})})
            await reopen_effects(tenant, org_id, existing, user, now)
            await audit_report_correction(
                db, user=user, mode=mode, report=existing,
                before={"day_entries": old_entries, "total_hours": existing.get("total_hours")},
                after={"day_entries": merged, "total_hours": merged_total},
                endpoint="POST /daily-reports/batch-save")
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
            await tenant.employee_daily_reports.insert_one(report)
        saved += 1

    return {"ok": True, "employees_saved": saved, "total_entries": len(entries)}


@router.get("/daily-reports/project-entries/{project_id}")
async def get_project_daily_entries(project_id: str, date: Optional[str] = None, user: dict = Depends(require_m4)):
    """Get all daily entries for a project on a date, grouped by employee and by SMR"""
    tenant = _tenant(user)
    org_id = user["org_id"]
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    reports = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "report_date": target_date, "day_entries.project_id": project_id},
        {"_id": 0}
    ).to_list(200)

    # Load names
    emp_ids = list(set(r["employee_id"] for r in reports))
    users_data = await tenant.users.find({"id": {"$in": emp_ids}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(100)
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
    """
    Bulk approve = UI convenience only. Backend runs approve_report_one per report,
    so single and bulk produce identical data. >8h lines are blocked for override
    (block_overtime_without_override=True) unless an override is supplied.
    """
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner/SiteManager")

    org_id = user["org_id"]
    report_ids = data.get("report_ids", [])
    overrides = data.get("overrides", {})

    succeeded, blocked, failed = [], [], []
    for rid in report_ids:
        report = await tenant.employee_daily_reports.find_one({"id": rid, "org_id": org_id}, {"_id": 0})
        if not report:
            failed.append({"id": rid, "reason": "not_found"})
            continue
        try:
            res = await approve_report_one(report, user, override=overrides.get(rid),
                                           block_overtime_without_override=True)
        except Exception as e:
            failed.append({"id": rid, "reason": str(e)})
            continue
        if res["status"] == "ok":
            succeeded.append({"id": rid, "slip_number": res["slip_number"],
                              "overtime_applied": res["overtime_applied"]})
        elif res["status"] == "blocked":
            blocked.append({
                "id": rid, "worker_name": res.get("worker_name", ""),
                "worker_id": res.get("worker_id", ""),
                "current_hours": res.get("current_hours", 0),
                "report_hours": res.get("report_hours", 0),
                "date": res.get("date", ""), "project_id": res.get("project_id", ""),
                "project_name": res.get("project_name", ""),
            })
        else:
            failed.append({"id": rid, "reason": res.get("reason", "failed")})

    return {"succeeded": succeeded, "blocked_for_override": blocked, "failed": failed}


@router.post("/daily-reports/bulk-reject")
async def bulk_reject(data: dict, user: dict = Depends(require_m4)):
    """Bulk reject = UI convenience. Backend runs reject_report_one per report."""
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner/SiteManager")

    org_id = user["org_id"]
    report_ids = data.get("report_ids", [])
    reason = data.get("reason", "")

    succeeded, failed = [], []
    for rid in report_ids:
        report = await tenant.employee_daily_reports.find_one({"id": rid, "org_id": org_id})
        if not report:
            failed.append({"id": rid, "reason": "not_found"})
            continue
        res = await reject_report_one(report, user, reason)
        if res["status"] in ("ok", "skipped"):  # already_rejected is idempotent success
            succeeded.append({"id": rid})
        else:
            failed.append({"id": rid, "reason": res.get("reason", "failed")})

    return {"succeeded": succeeded, "failed": failed}

