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


async def authorize_report_edit(user: dict, report: dict, *, projects: Iterable[str],
                                author_ids: Iterable[Optional[str]],
                                author_statuses: Iterable[str]) -> str:
    """Return AUTHOR or CORRECTOR, or raise 403 / 400 / 409 (R36)."""
    from app.deps.auth import can_manage_project

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
