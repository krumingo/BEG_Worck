"""
Service — R36 (LAB-01 Addendum A, Krum 07.11.2026): who may correct a daily report.

* The AUTHOR (the worker the report is for, or who entered it) corrects only their own
  draft or returned (rejected) report.
* A CORRECTOR — Admin, Owner, or the SiteManager of the report's project(s)
  (``can_manage_project``) — may correct ANY report, an approved one included.
* Every correction writes a canonical AuditEvent (FLOW-040): who, when, before / after.
* Correcting an approved report bumps its version and voids its quantity approvals
  (FG-72) — done by the route BEFORE the content write (``void_labor_approvals``).
* A report that payroll already batched or paid is NOT edited in place by anyone
  (FLOW-028 "Корекции след плащане: няма тихо редактиране"): 409, correction / reversal
  path instead.

Applies to PUT /daily-reports/{id}, PUT /technician/draft/{id} and
POST /daily-reports/batch-save.
"""
from typing import Iterable, Optional

from fastapi import HTTPException

AUTHOR = "author"
CORRECTOR = "corrector"
CORRECTOR_ROLES = ("Admin", "Owner")
PAYROLL_LOCKED = ("paid", "batched")
# LAB-01-J (FG-91): a Pay Run in any of these states holds its lines (paid or on the way)
LOCKING_RUN_STATUSES = ("confirmed", "paid", "paying", "payment_failed", "reopened")


def report_line_ids(report: dict) -> list:
    """The ids a Pay Run uses for this report's lines: the report id (new format) and
    ``<report id>_<entry id>`` per entry (old format — report_normalizer)."""
    rid = report.get("id")
    ids = [rid] if rid else []
    for e in report.get("day_entries") or []:
        if isinstance(e, dict) and e.get("id") and rid:
            ids.append(f"{rid}_{e['id']}")
    return ids


async def report_in_payroll(tenant, org_id: str, report: dict) -> Optional[str]:
    """LAB-01-J (FG-91): is the report already in payroll? Decided from the PAY RUN LINES
    that reference it or its entries — not only from ``payroll_status``, which the payroll
    sync never stamps on the old (employee_id / report_date) format. Returns the reason."""
    if (report.get("payroll_status") or "").lower() in PAYROLL_LOCKED:
        return f"payroll_status={report.get('payroll_status')}"
    ids = report_line_ids(report)
    if not ids or tenant is None:
        return None
    run = await tenant.pay_runs.find_one(
        {"org_id": org_id,
         "$and": [
             {"$or": [{"status": {"$in": list(LOCKING_RUN_STATUSES)}}, {"paid_at": {"$ne": None}}]},
             {"$or": [{"employee_rows.selected_report_ids": {"$in": ids}},
                      {"employee_rows.day_cells.reports.report_id": {"$in": ids}},
                      {"employee_rows.day_cells.report_ids": {"$in": ids}}]},
         ]},
        {"_id": 0, "id": 1, "number": 1, "status": 1})
    if run:
        return f"pay_run {run.get('number') or run.get('id')} ({run.get('status')})"
    return None


async def refuse_if_in_payroll(tenant, org_id: str, report: dict) -> None:
    reason = await report_in_payroll(tenant, org_id, report)
    if reason:
        raise HTTPException(status_code=409, detail=(
            "Отчетът вече е в заплати (в пакет или платен) — не се редактира и не се одобрява наново; "
            f"поправката става с корекция / сторно [{reason}]"))


async def authorize_report_edit(user: dict, report: dict, *, projects: Iterable[str],
                                author_ids: Iterable[Optional[str]],
                                author_statuses: Iterable[str], tenant=None) -> str:
    """Return AUTHOR or CORRECTOR, or raise 403 / 400 / 409 (R36). With ``tenant`` the
    payroll lock is decided from the Pay Run lines too (LAB-01-J, FG-91)."""
    from app.deps.auth import can_manage_project

    if tenant is not None:
        await refuse_if_in_payroll(tenant, report.get("org_id") or user.get("org_id"), report)
    if (report.get("payroll_status") or "").lower() in PAYROLL_LOCKED:
        raise HTTPException(status_code=409, detail=(
            "The report is already in payroll (batched/paid); it is corrected only through "
            "the FLOW-028 correction / reversal path, not edited"))
    if user.get("role") in CORRECTOR_ROLES:
        return CORRECTOR
    project_ids = sorted({p for p in projects if p})
    if user.get("role") == "SiteManager" and project_ids:
        allowed = True
        for pid in project_ids:
            if not await can_manage_project(user, pid):
                allowed = False
                break
        if allowed:
            return CORRECTOR
    if user.get("id") and user.get("id") in {a for a in author_ids if a}:
        status = (report.get("approval_status") or report.get("status") or "").upper()
        if status in {s.upper() for s in author_statuses}:
            return AUTHOR
        raise HTTPException(status_code=400, detail=(
            "The author corrects only their own draft or returned report; an approver "
            "(Admin / Owner / SiteManager of the project) corrects the others"))
    raise HTTPException(status_code=403, detail=(
        "Only the report's author (own draft / returned) or an approver "
        "(Admin / Owner / SiteManager of the project) may correct this report"))


async def audit_report_correction(raw_db, *, user: dict, mode: str, report: dict, before: dict,
                                  after: dict, endpoint: str, collection: str = "employee_daily_reports"):
    """One canonical AuditEvent per correction: who, when (occurred_at), before / after."""
    from app.audit.envelope import build_event, RETENTION_R1_CRITICAL_BUSINESS
    from app.audit.store import record_event
    status = (report.get("approval_status") or report.get("status") or "").upper()
    event = build_event(
        tenant_id=report.get("org_id") or user.get("org_id"), actor_type="human",
        actor_id=user.get("id") or "unknown",
        action="daily_report.corrected" if mode == CORRECTOR else "daily_report.edited",
        source_flow="FLOW-014", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=collection, entity_id=report.get("id"),
        entity_version=str(int(report.get("report_version") or 0) + 1),
        structured_diff={"before": before, "after": after},
        reason=f"R36 {mode} correction of a {status or 'UNKNOWN'} report (role {user.get('role')})",
        tool_or_endpoint=endpoint)
    return await record_event(raw_db, event)


# ═══════════════════════════════════════════════════ LAB-01-I (LAB01H-1, CLAUDE §8/§16)
# A correction of an APPROVED report never keeps it approved: the report goes back to
# SUBMITTED (approved_by / approved_at cleared, payroll_ready off), the work sessions its
# approval created are flagged void (as POST /daily-reports/{id}/reset does), its budget
# hours are given back, the quantity approvals are voided (void_labor_approvals) and a DQ
# alert asks for a new approval. That approval must come from someone who neither authored
# nor corrected the report (``approve_report_one`` four-eyes check).

DQ_CORRECTED_AFTER_APPROVAL = "DAILY_REPORT_CORRECTED_AFTER_APPROVAL"


def is_approved(report: dict) -> bool:
    return (report.get("approval_status") or report.get("status") or "").upper() == "APPROVED"


def correction_fields(report: dict, user: dict, mode: str, now: str):
    """($set fields, $addToSet fields) every correction adds to its content write."""
    set_fields, add = {}, {}
    if mode == CORRECTOR:
        set_fields.update({"corrected_by": user["id"], "corrected_at": now})
        add["correctors"] = user["id"]
    if is_approved(report):
        set_fields.update({
            "approval_status": "SUBMITTED", "status": "SUBMITTED",
            "approved_by": None, "approved_at": None, "payroll_ready": False, "sessions_created": 0,
            "reopened_by_correction": {"by": user["id"], "at": now,
                                       "previous_approved_by": report.get("approved_by")},
        })
    return set_fields, add


async def reopen_effects(tenant, org_id: str, report: dict, user: dict, now: str) -> None:
    """Side effects of sending an APPROVED report back to SUBMITTED (see above)."""
    if not is_approved(report):
        return
    rid = report["id"]
    await tenant.work_sessions.update_many(
        {"approved_report_id": rid, "org_id": org_id},
        {"$set": {"is_flagged": True, "flag_reason": "voided_by_correction", "updated_at": now}})
    smr_type = report.get("smr_type") or report.get("activity_type")
    hours = report.get("hours") or report.get("hours_worked") or 0
    if smr_type and report.get("project_id") and hours:
        budget = await tenant.activity_budgets.find_one(
            {"org_id": org_id, "project_id": report["project_id"], "smr_type_id": smr_type})
        if budget:
            consumed = max(0, round((budget.get("consumed_hours", 0) or 0) - float(hours), 2))
            planned = budget.get("planned_hours", 0) or 1
            await tenant.activity_budgets.update_one({"id": budget["id"]}, {"$set": {
                "consumed_hours": consumed, "burn_percent": round(consumed / planned * 100, 1),
                "last_updated": now}})
    import uuid as _uuid
    await tenant.dq_alerts.update_one(
        {"org_id": org_id, "entity_type": "daily_report", "entity_id": rid,
         "code": DQ_CORRECTED_AFTER_APPROVAL, "status": "open"},
        {"$set": {"org_id": org_id, "code": DQ_CORRECTED_AFTER_APPROVAL, "severity": "high",
                  "status": "open", "entity_type": "daily_report", "entity_id": rid,
                  "corrected_by": user["id"], "previous_approved_by": report.get("approved_by"),
                  "message": ("Одобрен отчет е поправен и е върнат за ново одобрение; "
                              "одобрява друг човек, не авторът или поправилият."),
                  "updated_at": now},
         "$setOnInsert": {"id": str(_uuid.uuid4()), "created_at": now}},
        upsert=True)


def self_approval_ids(report: dict) -> set:
    """Everyone who may NOT approve this report: its authors and its correctors."""
    ids = {report.get(k) for k in ("worker_id", "employee_id", "submitted_by", "created_by")}
    ids |= set(report.get("correctors") or [])
    if report.get("corrected_by"):
        ids.add(report["corrected_by"])
    return {i for i in ids if i}
