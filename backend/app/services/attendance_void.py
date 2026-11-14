"""FG-650 — presence and daily-report drafts are VOIDED, never hard deleted.

CLAUDE.md §2.9 and FLOW-037 §12.3: presence and work hours are critical records — corrected
or voided with a reason, never a hidden delete. A void keeps the row (``status: voided`` plus
the status it had, who / when / why), bumps ``version`` and writes an AuditEvent. The data
layer (``data_access.HIDDEN_STATUS``) then hides it from every read and update, and the
attendance day key is cleared so the worker can be marked again.

An entry other records rely on is refused (409 ``ENTRY_IN_USE``): a daily report on that
object and day, a late confirmation, or an offline-sync record. The correction then goes
through the report / the console.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from app.db import db
from app.tenancy.data_access import VOIDED_STATUS

DEFAULT_ROSTER_REASON = "Премахнат от списъка за деня"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _audit(user: Dict[str, Any], action: str, entity_type: str, entity_id: str,
                 reason: str, diff: Dict[str, Any]) -> None:
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    await record_event(db, build_event(
        tenant_id=user["org_id"], actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow="FLOW-013", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=entity_type, entity_id=entity_id, reason=reason, structured_diff=diff,
        effective_role_assignments=[user.get("role") or ""], idempotency_key=None,
        source_channel="field_portal"))


async def attendance_in_use(tenant, entry: Dict[str, Any],
                            ignore_report_ids: Iterable[str] = ()) -> Optional[str]:
    """What relies on this presence, or None."""
    if entry.get("late_confirmed_by"):
        return "late_confirmation"
    if entry.get("sync_local_id"):
        return "offline_sync"
    flt = {"org_id": entry["org_id"], "worker_id": entry["user_id"], "date": entry["date"],
           "project_id": entry.get("project_id")}
    ignore = list(ignore_report_ids)
    if ignore:
        flt["id"] = {"$nin": ignore}
    if await tenant.employee_daily_reports.find_one(flt, {"_id": 0, "id": 1}):
        return "daily_report"
    return None


def refuse_in_use(entry: Dict[str, Any], why: str) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "error_code": "ENTRY_IN_USE", "relies_on": why, "entry_id": entry.get("id"),
        "message": "Присъствието се ползва (%s) — корекцията минава през отчета/конзолата" % why})


async def void_attendance(tenant, user: Dict[str, Any], entries: List[Dict[str, Any]], reason: str) -> List[str]:
    """Void these presence entries (already checked with :func:`attendance_in_use`)."""
    done = []
    for e in entries:
        res = await tenant.attendance_entries.update_one(
            {"org_id": e["org_id"], "id": e["id"]},
            {"$set": {"status": VOIDED_STATUS, "voided_status": e.get("status"), "voided_by": user["id"],
                      "voided_at": _now(), "void_reason": reason,
                      "voided_day_key": e.get("attendance_day_key")},
             "$inc": {"version": 1},
             # the unique day key must not block marking the worker again after a void
             "$unset": {"attendance_day_key": ""}})
        if res.modified_count == 1:
            done.append(e["id"])
            await _audit(user, "attendance.voided", "attendance", e["id"], reason,
                         {"user_id": e.get("user_id"), "project_id": e.get("project_id"),
                          "date": e.get("date"), "status_before": e.get("status")})
    return done


async def void_reports(tenant, user: Dict[str, Any], reports: List[Dict[str, Any]], reason: str) -> List[str]:
    done = []
    for r in reports:
        res = await tenant.employee_daily_reports.update_one(
            {"org_id": r["org_id"], "id": r["id"]},
            {"$set": {"status": VOIDED_STATUS, "voided_status": r.get("status"), "voided_by": user["id"],
                      "voided_at": _now(), "void_reason": reason},
             "$inc": {"version": 1}})
        if res.modified_count == 1:
            done.append(r["id"])
            await _audit(user, "daily_report.voided", "daily_report", r["id"], reason,
                         {"worker_id": r.get("worker_id"), "project_id": r.get("project_id"),
                          "date": r.get("date"), "hours": r.get("hours"), "status_before": r.get("status")})
    return done
