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


#: FG-658: who may correct or void, from the console, a presence that came from the phone or a
#: late confirmation — ONE place, Krum confirms the roles.
CONSOLE_CORRECTION_ROLES = ("Owner", "Admin")
#: FG-656: who sees the history of voided presence / reports.
VOIDED_HISTORY_ROLES = ("Owner", "Admin")


async def _audit(user: Dict[str, Any], action: str, entity_type: str, entity_id: str,
                 reason: str, diff: Dict[str, Any], key: Optional[str] = None) -> Dict[str, Any]:
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    return await record_event(db, build_event(
        tenant_id=user["org_id"], actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow="FLOW-013", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=entity_type, entity_id=entity_id, reason=reason, structured_diff=diff,
        effective_role_assignments=[user.get("role") or ""], idempotency_key=key,
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


#: FG-659 (R61-4, FLOW-014): pay-run states that close the worker's day for any edit
CLOSED_PAY_RUN_STATES = ("confirmed", "paying", "paid", "payment_failed")


async def correction_locked(tenant, entry: Dict[str, Any]) -> Optional[str]:
    """FG-659/664 — THE one definition of a closed day, used by every path (console correct /
    void, site list, removal, offline mark, conflict accept, late confirm / correct): a pay run
    in ``CLOSED_PAY_RUN_STATES`` covers the worker's day, or a SUBMITTED / APPROVED report (or one
    already in payroll) — of that object, when the entry names one — relies on it."""
    worker, date = entry.get("user_id"), entry.get("date")
    run = await tenant.pay_runs.find_one(
        {"status": {"$in": list(CLOSED_PAY_RUN_STATES)}, "period_start": {"$lte": date},
         "period_end": {"$gte": date}, "employee_rows.employee_id": worker}, {"_id": 0, "status": 1})
    if run:
        return "pay_run_%s" % run.get("status")
    where = {"date": date}
    if entry.get("project_id"):
        where["project_id"] = entry.get("project_id")
    rep = await tenant.employee_daily_reports.find_one(
        {**where, "worker_id": worker,
         "$or": [{"approval_status": {"$in": ["APPROVED", "SUBMITTED"]}},
                 {"status": {"$in": ["Approved", "APPROVED", "Submitted", "SUBMITTED"]}},
                 {"payroll_status": {"$in": ["batched", "paid"]}}]},
        {"_id": 0, "approval_status": 1, "status": 1, "payroll_status": 1})
    if rep:
        if rep.get("payroll_status") in ("batched", "paid"):
            return "report_in_payroll"
        st = (rep.get("approval_status") or rep.get("status") or "").upper()
        return "report_approved" if st == "APPROVED" else "report_submitted"
    wr = await tenant.work_reports.find_one(
        {**where, "user_id": worker, "status": {"$in": ["Approved", "Submitted"]}}, {"_id": 0, "status": 1})
    if wr:
        return "report_approved" if wr.get("status") == "Approved" else "report_submitted"
    return None


#: the conflict kind a closed-day reason shows as (R61-4: all of them → correction / reversal)
LOCK_KIND = {"pay_run_paid": "paid", "pay_run_paying": "paid", "report_in_payroll": "paid",
             "report_approved": "approved"}


def lock_kind(reason: Optional[str]) -> Optional[str]:
    return None if not reason else LOCK_KIND.get(reason, "closed")


def refuse_locked(entry: Dict[str, Any], why: str) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "error_code": "CORRECTION_OR_REVERSAL_REQUIRED", "closed_by": why, "entry_id": entry.get("id"),
        "message": "Денят е затворен (%s) — само корекция или сторно през отчета/заплатите" % why})


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
            ev = await _audit(user, "attendance.voided", "attendance", e["id"], reason,
                              {"user_id": e.get("user_id"), "project_id": e.get("project_id"),
                               "date": e.get("date"), "status_before": e.get("status")})
            await _link_event(tenant, "attendance_entries", e, ev)
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
            ev = await _audit(user, "daily_report.voided", "daily_report", r["id"], reason,
                              {"worker_id": r.get("worker_id"), "project_id": r.get("project_id"),
                               "date": r.get("date"), "hours": r.get("hours"), "status_before": r.get("status")})
            await _link_event(tenant, "employee_daily_reports", r, ev)
    return done


async def _link_event(tenant, coll: str, row: Dict[str, Any], event: Dict[str, Any]) -> None:
    """The voided row points at its AuditEvent (the history's link). Written through the raw
    collection: the row is already hidden from the data layer's updates."""
    if event and event.get("event_id"):
        await tenant.collection(coll)._raw.update_one(
            {"org_id": row["org_id"], "id": row["id"]}, {"$set": {"void_event_id": event["event_id"]}})


# ──────────────────────────────────────────────── FG-656: history of what was voided
async def voided_history(tenant, user: Dict[str, Any], date: str) -> Dict[str, Any]:
    """Read-only: the presence and report rows voided for that day, with reason, actor, time
    and the AuditEvent id. The include-voided read itself is audited."""
    if user.get("role") not in VOIDED_HISTORY_ROLES:
        raise HTTPException(status_code=403, detail={"error_code": "FORBIDDEN", "message": "Само собственик/администратор"})
    att = await tenant.attendance_entries.voided({"date": date}, {"_id": 0}).to_list(500)
    reps = await tenant.employee_daily_reports.voided({"date": date}, {"_id": 0}).to_list(500)
    ids = list({r.get("voided_by") for r in att + reps if r.get("voided_by")}
               | {r.get("user_id") for r in att} | {r.get("worker_id") for r in reps})
    people = {u["id"]: ("%s %s" % (u.get("first_name", ""), u.get("last_name", ""))).strip()
              for u in await tenant.users.find({"id": {"$in": [i for i in ids if i]}},
                                               {"_id": 0, "id": 1, "first_name": 1, "last_name": 1}).to_list(500)}

    def view(r, kind):
        who = r.get("user_id") if kind == "attendance" else r.get("worker_id")
        return {"kind": kind, "id": r.get("id"), "date": r.get("date"), "project_id": r.get("project_id"),
                "worker_id": who, "worker_name": people.get(who) or r.get("worker_name") or "",
                "status_before": r.get("voided_status"), "hours": r.get("hours"),
                "reason": r.get("void_reason"), "voided_by": r.get("voided_by"),
                "voided_by_name": people.get(r.get("voided_by"), ""), "voided_at": r.get("voided_at"),
                "audit_event_id": r.get("void_event_id")}
    items = [view(r, "attendance") for r in att] + [view(r, "daily_report") for r in reps]
    items.sort(key=lambda x: x.get("voided_at") or "", reverse=True)
    await _audit(user, "history.voided_read", "history", date, None, {"date": date, "rows": len(items)})
    return {"date": date, "items": items}


# ──────────────────────── FG-658: console correction / void of phone / late-confirmed presence
async def console_presence(tenant, date: str) -> List[Dict[str, Any]]:
    rows = await tenant.attendance_entries.find(
        {"date": date, "$or": [{"sync_local_id": {"$exists": True}}, {"late_confirmed_by": {"$exists": True}}]},
        {"_id": 0}).to_list(500)
    return [{k: r.get(k) for k in ("id", "date", "project_id", "user_id", "status", "note", "version",
                                   "source", "late_confirmed_by", "captured_at")} for r in rows]


async def console_fix(tenant, user: Dict[str, Any], entry_id: str, action: str, reason: str,
                      base_version: Any, key: str, status: Optional[str] = None) -> Dict[str, Any]:
    if user.get("role") not in CONSOLE_CORRECTION_ROLES:
        raise HTTPException(status_code=403, detail={"error_code": "FORBIDDEN", "message": "Само собственик/администратор"})
    if action not in ("void", "correct"):
        raise HTTPException(status_code=422, detail={"error_code": "ACTION_INVALID", "message": "void или correct"})
    entry = await tenant.attendance_entries.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        done = await tenant.attendance_entries.voided({"id": entry_id, "console_fix_key": key}, {"_id": 0}).to_list(1)
        if done and done[0].get("console_fix_answer"):           # FG-660: the first answer, as it was
            return done[0]["console_fix_answer"]
        raise HTTPException(status_code=404, detail={"error_code": "NOT_FOUND", "message": "Няма такова присъствие"})
    if entry.get("console_fix_key") == key and entry.get("console_fix_answer"):
        return entry["console_fix_answer"]
    if not (entry.get("sync_local_id") or entry.get("late_confirmed_by")):
        raise HTTPException(status_code=409, detail={
            "error_code": "NOT_FROM_PHONE", "message": "Това присъствие се коригира от обекта/офиса"})
    # FG-659: a closed day (pay run / approved or submitted report) — never edited here
    locked = await correction_locked(tenant, entry)
    if locked:
        raise refuse_locked(entry, locked)
    version = entry.get("version", 0)
    if base_version is None or int(base_version) != int(version):
        raise HTTPException(status_code=409, detail={"error_code": "CONFLICT_STALE", "version": version,
                                                     "message": "Записът е променен — отворете го отново"})
    flt = {"org_id": entry["org_id"], "id": entry_id, "version": version} if version else \
        {"org_id": entry["org_id"], "id": entry_id, "$or": [{"version": 0}, {"version": {"$exists": False}}]}
    stamp = _now()
    if action == "void":
        # a report on this object and day still relies on it → correct the report first
        why = await attendance_in_use(tenant, {**entry, "sync_local_id": None, "late_confirmed_by": None})
        if why:
            raise refuse_in_use(entry, why)
        upd = {"$set": {"status": VOIDED_STATUS, "voided_status": entry.get("status"), "voided_by": user["id"],
                        "voided_at": stamp, "void_reason": reason, "voided_day_key": entry.get("attendance_day_key"),
                        "console_fix_key": key},
               "$inc": {"version": 1}, "$unset": {"attendance_day_key": ""}}
        act = "attendance.voided"
    else:
        from app.routes.attendance import ATTENDANCE_STATUSES
        if status not in ATTENDANCE_STATUSES:
            raise HTTPException(status_code=422, detail={"error_code": "STATUS_INVALID", "message": "Невалиден статус"})
        upd = {"$set": {"status": status, "corrected_by": user["id"], "corrected_at": stamp,
                        "correction_reason": reason, "console_fix_key": key,
                        "update_source": "console_correction"}, "$inc": {"version": 1}}
        act = "attendance.corrected"
    res = await tenant.attendance_entries.update_one(flt, upd)
    if res.modified_count != 1:
        raise HTTPException(status_code=409, detail={"error_code": "CONFLICT_STALE",
                                                     "message": "Записът е променен междувременно"})
    ev = await _audit(user, act, "attendance", entry_id, reason,
                      {"before": {"status": entry.get("status"), "version": version},
                       "after": {"status": VOIDED_STATUS if action == "void" else status, "version": version + 1},
                       "user_id": entry.get("user_id"), "project_id": entry.get("project_id"),
                       "date": entry.get("date")}, key=key)
    if action == "void":
        await _link_event(tenant, "attendance_entries", entry, ev)
    answer = {"replay": False, "action": action, "entry_id": entry_id, "version": version + 1,
              "audit_event_id": (ev or {}).get("event_id")}
    # FG-660: the first answer is stored; the same Idempotency-Key gets exactly this back
    await tenant.collection("attendance_entries")._raw.update_one(
        {"org_id": entry["org_id"], "id": entry_id}, {"$set": {"console_fix_answer": answer}})
    return answer


async def audit_refusal(user: Dict[str, Any], refusal: Dict[str, Any], project_id: str, date: str) -> None:
    """FG-661: every per-worker refusal of the site list is an AuditEvent."""
    await _audit(user, "attendance.void_refused", "attendance", refusal.get("entry_id") or "",
                 None, {"worker_id": refusal.get("worker_id"), "project_id": project_id, "date": date,
                        "error_code": refusal.get("error_code"), "reason": refusal.get("relies_on")})
