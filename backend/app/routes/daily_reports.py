"""
Routes - Structured Employee Daily Report.
New model alongside existing attendance/work_reports (which remain untouched).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.tenancy import project_team
from app.deps.auth import get_current_user
from app.deps.modules import require_m4
from app.tenancy.data_access import TenantData
from app.services import labor_report_service as labor


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Employee Daily Reports"])


# ── Helpers ────────────────────────────────────────────────────────

_get_hourly_rate_for_approval = labor._get_hourly_rate_for_approval


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
# LAB-R96 step 2 (Р100): this endpoint family is an ADAPTER over the "Отчет на труда" service.
# The request bodies are the old ones (employee_id / report_date / day_entries); a WORKING day
# is written as flat labor lines (one per entry) through labor_report_service, and the answers
# keep the old shape (labor.old_shape_day: the employee's day = all his live lines that date;
# any of its line ids is the day's handle). Old-format rows already stored are read and, if
# still DRAFT/REJECTED, edited in place as before — never migrated here (step 5).
# A non-WORKING day (leave / sick / absent) carries no hours and is kept as before.

def _is_old_format(doc: dict) -> bool:
    return bool(doc.get("employee_id")) and not doc.get("worker_id")


async def _activity_name(tenant, org_id: str, e: dict) -> str:
    """The activity of an old-format entry: the chosen SMR's name, else its description."""
    for coll, fid, field in (("execution_packages", e.get("smr_id"), "activity_name"),
                             ("extra_work_drafts", e.get("smr_id"), "title"),
                             ("extra_work_drafts", e.get("extra_work_id"), "title")):
        if fid:
            row = await tenant.collection(coll).find_one({"id": fid, "org_id": org_id}, {"_id": 0, field: 1})
            if row and row.get(field):
                return row[field]
    return (e.get("work_description") or "").strip()


async def _service_entries(tenant, org_id: str, worker_id: str, entries: List[dict], day_notes=None,
                           source: str = "daily_report_form") -> List[dict]:
    out = []
    for e in entries:
        out.append({"worker_id": worker_id, "project_id": e.get("project_id"),
                    "activity": await _activity_name(tenant, org_id, e),
                    "hours": max(0.0, float(e.get("hours_worked") or 0)), "notes": e.get("note") or "",
                    "line_id": e.get("line_id") or e.get("id"),
                    "extra": {"smr_id": e.get("smr_id"), "extra_work_id": e.get("extra_work_id"),
                              "work_description": e.get("work_description") or "",
                              "day_notes": day_notes, "report_source": source}})
    return out


async def _plan_by_project(user, date, entries, *, reason=None, ignore_ids=()):
    """plan_lines per project (one call per object), all before any write."""
    plans = []
    for pid in dict.fromkeys(e["project_id"] for e in entries):
        if not pid:
            raise HTTPException(status_code=400, detail="Всеки ред трябва да има обект.")
        plans.append((pid, await labor.plan_lines(user, pid, date, [e for e in entries if e["project_id"] == pid],
                                                  reason=reason, ignore_ids=ignore_ids)))
    return plans


async def _day_view(tenant, org_id, head_id, worker_id, date):
    return labor.old_shape_day(head_id, worker_id, date, await labor.day_lines(tenant, org_id, worker_id, date))


@router.post("/daily-reports", status_code=201)
async def create_daily_report(data: DailyReportCreate, request: Request, user: dict = Depends(require_m4)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    validate_report(data)

    # Check no duplicate for same employee+date (old-format day report)
    existing = await tenant.employee_daily_reports.find_one({
        "org_id": org_id, "employee_id": data.employee_id, "report_date": data.report_date
    })
    if existing:
        raise HTTPException(status_code=400, detail="Report already exists for this employee and date. Use update instead.")

    if data.day_status == "WORKING":
        idem = request.headers.get("Idempotency-Key")
        prev = await labor.lines_by_idempotency(tenant, org_id, user["id"], idem)
        if prev:
            return {**labor.old_shape_day(prev[0]["id"], data.employee_id, data.report_date, prev),
                    "idempotent_replay": True}
        if not data.day_entries:
            raise HTTPException(status_code=400, detail="Добавете поне един ред (обект, дейност, часове).")
        entries = await _service_entries(tenant, org_id, data.employee_id,
                                         [e.model_dump() for e in data.day_entries], data.notes)
        try:
            plans = await _plan_by_project(user, data.report_date, entries, reason=data.notes)
        except labor.LaborLineExists as exc:
            raise labor.as_legacy_400(exc)        # this endpoint answered duplicates with 400
        written = []
        for pid, pl in plans:
            written += await labor.write_lines(user, pl, pid, data.report_date,
                                               entry_mode="daily_report_form", idempotency_key=idem)
        clean = labor.old_shape_day(written[0]["id"], data.employee_id, data.report_date, written)
        clean["hours_warnings"] = await check_employee_hours(org_id, data.employee_id, data.report_date)
        return clean

    # non-WORKING day: no hours, no labor line — the old day-status record, as before
    if any(e.hours_worked for e in data.day_entries):
        raise HTTPException(status_code=400, detail="Ден без работа (отпуск / болничен / отсъствие) не може да има часове.")
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "employee_id": data.employee_id,
        "report_date": data.report_date,
        "day_status": data.day_status,
        "leave_from": data.leave_from,
        "leave_to": data.leave_to,
        "notes": data.notes,
        "day_entries": [],
        "total_hours": 0,
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


async def _update_old_format(tenant, report: dict, data: dict, user: dict):
    """A stored OLD-format row (not migrated): edited in place as before, the editor kept."""
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
    now = datetime.now(timezone.utc).isoformat()
    changed = [k for k in update if k in allowed]
    update.update({"updated_at": now, "last_edited_by": user["id"], "last_edited_at": now})
    await tenant.employee_daily_reports.update_one(
        {"id": report["id"]}, {"$inc": {"version": 1}, "$set": update, "$addToSet": {"correctors": user["id"]}})
    await labor.audit(user, "labor_line.updated", report, {"before": {k: report.get(k) for k in changed},
                                                            "after": {k: update[k] for k in changed},
                                                            "format": "old"})
    return await tenant.employee_daily_reports.find_one({"id": report["id"]}, {"_id": 0})


@router.put("/daily-reports/{report_id}")
async def update_daily_report(report_id: str, data: dict, user: dict = Depends(require_m4)):
    tenant = _tenant(user)
    org_id = user["org_id"]
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": org_id})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if _is_old_format(report):
        return await _update_old_format(tenant, report, data, user)

    # the employee's day of flat lines: same ids → update, new rows → new lines (checked),
    # rows left out → voided with a reason (history kept). Approved lines are locked.
    worker_id, date = report["worker_id"], report["date"]
    if (data.get("day_status") or "WORKING") != "WORKING":
        raise HTTPException(status_code=400, detail="Ден с отчетени часове не може да стане отпуск / отсъствие — "
                                                    "първо премахнете редовете.")
    day = await labor.day_lines(tenant, org_id, worker_id, date)
    by_id = {ln["id"]: ln for ln in day}
    incoming = await _service_entries(tenant, org_id, worker_id, data.get("day_entries") or [], data.get("notes"))
    keep = [e for e in incoming if e.get("line_id") in by_id]
    new = [e for e in incoming if e.get("line_id") not in by_id]
    kept_ids = {e["line_id"] for e in keep}
    removed = [ln for ln in day if ln["id"] not in kept_ids]
    locked = [ln for ln in removed if ln.get("status") not in labor.EDITABLE]
    for e in keep:
        ln = by_id[e["line_id"]]
        if ln.get("project_id") != e["project_id"]:
            raise HTTPException(status_code=400, detail="Редът не може да смени обекта — премахнете го и добавете нов.")
        e["changed"] = (float(ln.get("hours") or 0) != e["hours"]
                        or labor.norm_activity(ln.get("smr_type")) != labor.norm_activity(e["activity"])
                        or (ln.get("notes") or "") != (e["notes"] or ""))
        if e["changed"] and ln.get("status") not in labor.EDITABLE:
            locked.append(ln)
    if locked:
        raise HTTPException(status_code=400, detail="Одобрен ред е заключен — поправката е с история.")
    for ln in removed:
        await labor.check_may_report(tenant, user, worker_id, ln.get("project_id"))
    plans = await _plan_by_project(user, date, new, reason=data.get("notes"),
                                   ignore_ids=[ln["id"] for ln in removed]) if new else []
    if removed:
        await labor.void_lines(user, removed, "Премахнат от дневния отчет")
    for e in keep:
        if e["changed"]:
            await labor.update_line(user, by_id[e["line_id"]], {"hours": e["hours"], "smr_type": e["activity"],
                                                               "notes": e["notes"]}, reason=data.get("notes"))
    for pid, pl in plans:
        await labor.write_lines(user, pl, pid, date, entry_mode="daily_report_form")
    return await _day_view(tenant, org_id, report_id, worker_id, date)


@router.post("/daily-reports/{report_id}/submit")
async def submit_daily_report(report_id: str, user: dict = Depends(require_m4)):
    tenant = _tenant(user)
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not _is_old_format(report):
        day = await labor.day_lines(tenant, user["org_id"], report["worker_id"], report["date"])
        if not any(ln.get("status") in ("Draft", "REJECTED", "Rejected") for ln in day):
            raise HTTPException(status_code=400, detail="Only DRAFT/REJECTED can be submitted")
        for ln in day:
            await labor.check_may_report(tenant, user, ln["worker_id"], ln.get("project_id"))
        await labor.submit_lines(user, day)
        return await _day_view(tenant, user["org_id"], report_id, report["worker_id"], report["date"])
    if report["approval_status"] not in ["DRAFT", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Only DRAFT/REJECTED can be submitted")

    now = datetime.now(timezone.utc).isoformat()
    await tenant.employee_daily_reports.update_one({"id": report_id}, {"$inc": {"version": 1}, "$set": {
        "approval_status": "SUBMITTED", "submitted_by": user["id"], "updated_at": now,
    }})
    await labor.audit(user, "labor_line.submitted", report, {"before": {"status": report["approval_status"]},
                                                             "after": {"status": "SUBMITTED"}, "format": "old"})
    return await tenant.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


# ── Single-source-of-truth actions (P1-0.5) ────────────────────────
# approve_report_one / reject_report_one are the ONLY place approve/reject business logic
# lives — since LAB-R96 step 2 inside the "Отчет на труда" service (four-eyes + AuditEvent
# added there). Single endpoints call them once; bulk endpoints in a loop.
from app.services.labor_report_service import approve_report_one, reject_report_one  # noqa: E402


_APPROVE_FAIL_MSG = {
    "already_approved": "Вече одобрен отчет не може да бъде одобрен повторно.",
    "split_mismatch": "Сборът нормални+извънредни часове не съвпада с часовете на отчета.",
    "negative_split_value": "Отрицателни часове в разделението.",
    "coefficient_must_be_at_least_1": "Коефициентът за извънреден труд трябва да е поне 1.",
    "reason_required": "Изисква се причина за override на извънреден труд.",
    "self_approval": labor.SELF_APPROVAL_MSG,
}


@router.post("/daily-reports/{report_id}/approve")
async def approve_daily_report(report_id: str, data: dict = {}, user: dict = Depends(require_m4)):
    """
    SOURCE OF TRUTH: the POSTING EVENT (creates work_sessions — see SOURCE_OF_TRUTH.md).
    P1-0.5: delegates to approve_report_one so single and bulk approve are identical.
    Single path does NOT block >8h (B2): default split with coefficient 1.0.
    Optional body: {"override": {regular_hours, overtime_hours, overtime_coefficient, reason}}.
    LAB-R96: four-eyes (Р100 "Одобрява друг човек") → 403 FOUR_EYES. ``{"scope": "day"}``
    (the day dialog) approves every not-yet-approved line of the employee's day.
    """
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can approve")
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if (data or {}).get("scope") == "day" and not _is_old_format(report):
        day = [ln for ln in await labor.day_lines(tenant, user["org_id"], report["worker_id"], report["date"])
               if (ln.get("status") or "").upper() != "APPROVED"]
        if any(labor.is_self_approval(ln, user) for ln in day):
            raise labor.four_eyes_http()
        warnings = []
        for ln in day:
            res = await approve_report_one(ln, user, block_overtime_without_override=False)
            if res["status"] == "failed":
                raise HTTPException(status_code=400, detail=_APPROVE_FAIL_MSG.get(res["reason"], res["reason"]))
            warnings = res.get("hours_warnings", warnings)
        result = await _day_view(tenant, user["org_id"], report_id, report["worker_id"], report["date"])
        result["hours_warnings"] = warnings
        return result

    res = await approve_report_one(report, user, override=(data or {}).get("override"),
                                   block_overtime_without_override=False)
    if res["status"] == "failed":
        if res["reason"] == "self_approval":
            raise labor.four_eyes_http()
        raise HTTPException(status_code=400, detail=_APPROVE_FAIL_MSG.get(res["reason"], res["reason"]))
    if res["status"] == "blocked":  # not expected on single path
        raise HTTPException(status_code=409, detail="overtime_requires_override")

    result = res["report"]
    result["hours_warnings"] = res.get("hours_warnings", [])
    return result


@router.post("/daily-reports/{report_id}/reject")
async def reject_daily_report(report_id: str, data: dict = {}, user: dict = Depends(require_m4)):
    """P1-0.5: delegates to reject_report_one (same logic as bulk). ``{"scope": "day"}``: the
    employee's whole day of flat lines (LAB-R96 day dialog)."""
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner", "SiteManager"]:
        raise HTTPException(status_code=403, detail="Only SiteManager/Admin can reject")
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if (data or {}).get("scope") == "day" and not _is_old_format(report):
        day = await labor.day_lines(tenant, user["org_id"], report["worker_id"], report["date"])
        if any((ln.get("status") or "").upper() == "APPROVED" for ln in day):
            raise HTTPException(status_code=400, detail="Отчет със статус APPROVED не може да бъде отхвърлен.")
        for ln in day:
            await reject_report_one(ln, user, (data or {}).get("reason", ""))
        return await _day_view(tenant, user["org_id"], report_id, report["worker_id"], report["date"])
    res = await reject_report_one(report, user, (data or {}).get("reason", ""))
    if res["status"] == "failed":
        raise HTTPException(status_code=400, detail="Отчет със статус APPROVED не може да бъде отхвърлен.")
    # ok or skipped(already_rejected) → idempotent: return current report
    return await tenant.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})


@router.post("/daily-reports/{report_id}/reset")
async def reset_daily_report(report_id: str, user: dict = Depends(require_m4)):
    """Reset an APPROVED report back to SUBMITTED. Voids created work_sessions."""
    tenant = _tenant(user)
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Only Admin/Owner can reset")
    report = await tenant.employee_daily_reports.find_one({"id": report_id, "org_id": user["org_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    current_status = report.get("approval_status") or report.get("status", "")
    if current_status != "APPROVED":
        raise HTTPException(status_code=400, detail="Only APPROVED reports can be reset")

    # Check payroll not finalized for this period
    report_date = report.get("date", "")
    if report_date:
        # R0-06-C01: a payment in progress or failed may already have moved money — locked too.
        finalized = await tenant.pay_runs.find_one({
            "org_id": user["org_id"],
            "status": {"$in": ["paid", "paying", "payment_failed"]},
            "period_start": {"$lte": report_date},
            "period_end": {"$gte": report_date},
        })
        if finalized:
            raise HTTPException(status_code=400, detail="Cannot reset: payroll for this period is paid")

    now = datetime.now(timezone.utc).isoformat()

    # Void work_sessions created by this report
    await tenant.work_sessions.update_many(
        {"approved_report_id": report_id, "org_id": user["org_id"]},
        {"$set": {"is_flagged": True, "flag_reason": "voided_by_reset", "updated_at": now}},
    )

    # Reverse budget consumed on void
    if report.get("smr_type") or report.get("activity_type"):
        smr_type = report.get("smr_type") or report.get("activity_type", "")
        hours = report.get("hours") or report.get("hours_worked", 0)
        if smr_type and report.get("project_id") and hours:
            budget = await tenant.activity_budgets.find_one({
                "org_id": user["org_id"],
                "project_id": report["project_id"],
                "smr_type_id": smr_type,
            })
            if budget:
                new_consumed = max(0, round((budget.get("consumed_hours", 0) or 0) - hours, 2))
                planned = budget.get("planned_hours", 0) or 1
                burn_pct = round((new_consumed / planned) * 100, 1)
                await tenant.activity_budgets.update_one(
                    {"id": budget["id"]},
                    {"$set": {
                        "consumed_hours": new_consumed,
                        "burn_percent": burn_pct,
                        "last_updated": now,
                    }}
                )

    # Reset report
    await tenant.employee_daily_reports.update_one({"id": report_id}, {"$inc": {"version": 1}, "$set": {
        "approval_status": "SUBMITTED", "status": "SUBMITTED",
        "approved_by": None, "approved_at": None,
        "payroll_ready": False, "sessions_created": 0,
        "updated_at": now,
    }})
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
    if _is_old_format(report):
        return report
    # LAB-R96: a flat line answers with its fields AND the employee's day in the old shape
    day = await _day_view(tenant, user["org_id"], report_id, report["worker_id"], report["date"])
    return {**report, **day}


def _flat_days(lines: List[dict]) -> List[dict]:
    """Flat lines grouped as old-shape day reports (one per employee and date)."""
    days: dict = {}
    for ln in lines:
        days.setdefault((ln.get("worker_id"), ln.get("date")), []).append(ln)
    return [labor.old_shape_day(v[0]["id"], k[0], k[1], v) for k, v in days.items()]


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
    # LAB-R96: the flat lines (the one format) as old-shape day reports, so the screen keeps working
    qf = {"org_id": user["org_id"], "worker_id": {"$exists": True}}
    if employee_id: qf["worker_id"] = employee_id
    if report_date: qf["date"] = report_date
    if date_from or date_to:
        qf["date"] = {}
        if date_from: qf["date"]["$gte"] = date_from
        if date_to: qf["date"]["$lte"] = date_to
    if project_id:
        qf["project_id"] = project_id
    flat = await tenant.employee_daily_reports.find(qf, {"_id": 0}).sort("created_at", 1).to_list(2000)
    reports += _flat_days(flat)
    reports.sort(key=lambda r: r.get("report_date") or "", reverse=True)
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
    # LAB-R96: and the flat lines (the one format) on this project today
    flat_today = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "date": target_date, "project_id": project_id, "worker_id": {"$exists": True}},
        {"_id": 0, "worker_id": 1}).to_list(500)
    report_emp_ids += [r["worker_id"] for r in flat_today if r.get("worker_id")]

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
    flat_all = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "worker_id": {"$in": all_ids}, "date": target_date}, {"_id": 0}
    ).sort("created_at", 1).to_list(1000)
    for d in _flat_days(flat_all):
        report_map.setdefault(d["employee_id"], d)

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
    Input: { project_id, report_date, entries: [{ employee_id, smr_id, work_description, hours_worked, note, line_id? }] }
    LAB-R96 adapter (Р100): every entry is a flat labor line written through the "Отчет на труда"
    service. An entry carrying ``line_id`` (the screen loaded it) updates that line; an entry
    without one is a NEW line — if the person already has a line for that day / project /
    activity from any path, the whole save is refused with 409 "Вече има отчет". Lines this
    screen wrote earlier and the save leaves out are voided with a reason (the old "replace
    for THIS project"). All checks run for all employees before anything is written.
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
        by_emp.setdefault(eid, []).append({**e, "project_id": project_id})

    steps = []
    for emp_id, emp_entries in by_emp.items():
        mine = [ln for ln in await labor.day_lines(tenant, org_id, emp_id, report_date)
                if ln.get("project_id") == project_id]
        by_id = {ln["id"]: ln for ln in mine}
        svc = await _service_entries(tenant, org_id, emp_id, emp_entries, source="object_daily_report")
        keep = [e for e in svc if e.get("line_id") in by_id]
        new = [e for e in svc if e.get("line_id") not in by_id]
        kept = {e["line_id"] for e in keep}
        removed = [ln for ln in mine if ln["id"] not in kept and ln.get("entry_mode") == "object_daily_report"
                   and ln.get("status") in labor.EDITABLE]
        for e in keep:
            ln = by_id[e["line_id"]]
            e["changed"] = (float(ln.get("hours") or 0) != e["hours"]
                            or labor.norm_activity(ln.get("smr_type")) != labor.norm_activity(e["activity"])
                            or (ln.get("notes") or "") != (e["notes"] or ""))
            if e["changed"] and ln.get("status") not in labor.EDITABLE:
                raise HTTPException(status_code=400, detail="Одобрен ред е заключен — поправката е с история.")
        for ln in removed:
            await labor.check_may_report(tenant, user, emp_id, project_id)
        plans = await labor.plan_lines(user, project_id, report_date, new,
                                       ignore_ids=[ln["id"] for ln in removed]) if new else []
        steps.append((emp_id, by_id, keep, removed, plans))

    saved = 0
    for emp_id, by_id, keep, removed, plans in steps:
        if removed:
            await labor.void_lines(user, removed, "Премахнат от дневния отчет на обекта")
        for e in keep:
            if e["changed"]:
                await labor.update_line(user, by_id[e["line_id"]], {"hours": e["hours"], "smr_type": e["activity"],
                                                                   "notes": e["notes"]})
        if plans:
            await labor.write_lines(user, plans, project_id, report_date, entry_mode="object_daily_report")
        saved += 1

    return {"ok": True, "employees_saved": saved, "total_entries": len(entries)}


@router.get("/daily-reports/project-entries/{project_id}")
async def get_project_daily_entries(project_id: str, date: Optional[str] = None, user: dict = Depends(require_m4)):
    """Get all daily entries for a project on a date, grouped by employee and by SMR.
    LAB-R96: reads BOTH stored formats — old-format day reports and flat labor lines (each
    flat entry carries ``line_id`` so the screen can save it back as the same line)."""
    tenant = _tenant(user)
    org_id = user["org_id"]
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    reports = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "report_date": target_date, "day_entries.project_id": project_id},
        {"_id": 0}
    ).to_list(200)
    flat = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "date": target_date, "project_id": project_id, "worker_id": {"$exists": True}},
        {"_id": 0}).sort("created_at", 1).to_list(1000)
    reports += [d for d in _flat_days(flat)]

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
            smr_key = e.get("smr_id") or ("act:" + labor.norm_activity(e.get("work_description"))
                                          if e.get("line_id") else "unassigned")
            if smr_key not in by_smr:
                by_smr[smr_key] = {"smr_id": e.get("smr_id"), "work_description": e.get("work_description", ""), "employees": [], "total_hours": 0}
            by_smr[smr_key]["employees"].append({
                "employee_id": r["employee_id"],
                "employee_name": name_map.get(r["employee_id"], ""),
                "hours_worked": e["hours_worked"],
                "note": e.get("note", ""),
                "line_id": e.get("line_id"),
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

