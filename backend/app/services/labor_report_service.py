"""
Service — „Отчет на труда" (LAB-R96 step 2): the ONE write path for labor.

Decisions: Р96 (one labor logic: the daily report, FLOW-013/014), Р100 (approved map "Един
вход за труда": one service, one format, one line = person × day × project × activity, a
second entry is a visible conflict "Вече има отчет", another person approves), Р101 (the clock
"Започни / Приключи" is removed), Р102 (reported / approved / paid).

Design note
-----------
* ONE storage format: the flat line in ``employee_daily_reports`` — ``org_id, worker_id,
  worker_name, date, project_id, smr_type, hours, status`` (``Draft`` → ``Submitted`` →
  ``APPROVED`` | ``REJECTED``). It is the shape the technician path, the PWA-02 offline sync and
  payroll marking (``payroll_sync``) already use. Old-format rows (``employee_id /
  report_date / day_entries``) are NOT migrated or deleted (that is step 5, with Krum's "да");
  every reader keeps reading both formats (``report_normalizer``) and so does the conflict
  check below — an old row is an existing line.
* Every entry path calls this module: ``POST /technician/daily-report`` (+ offline sync),
  ``POST/PUT /daily-reports``, ``/daily-reports/batch-save``, ``/work-reports`` ("Моят ден"),
  ``/daily-logs`` ("Дневници"), the SMR group report. The old-format endpoints are adapters:
  same request bodies, write flat lines here, GET answers keep the shape the screens expect
  (``old_shape_day`` below).
* Uniqueness: ``labor_key = worker|date|project|activity`` (activity case/space-normalised),
  stamped on every line written here. Enforced (1) here, before any write, against flat AND
  old-format rows, and inside one request (two entries with the same key); (2) by a PARTIAL
  unique index ``(org_id, labor_key)`` (``offline_sync.UNIQUE_INDEXES``, same startup
  pattern / alarm as PWA-02). Historic rows carry no ``labor_key``, so the index builds over
  any data; a void moves the key to ``voided_labor_key`` so the slot is free again.
  An index over the historic rows themselves (duplicates may exist) is NOT built — follow-up
  that needs ОП-2 counts.
* Conflict = visible: ``LaborLineExists`` → 409 ``{"error_code": "LABOR_LINE_EXISTS",
  "message": "Вече има отчет за <човек> на <дата> по <обект> / <СМР> — отвори го.",
  "existing": {line_id, report_id, worker, date, project, activity, hours, status,
  entered_by}}``. Endpoints whose duplicate answer was already 400 (``POST /daily-reports``,
  ``POST /daily-logs``) keep 400 with the same body (their screens / tests read 400).
* Checks on every path, all before the first write, in this order: who may report for whom →
  project writable (PRJ-01) → backdate (FLOW-014) → presence (FLOW-013 / FG-641 — the
  technician path's check, moved here, not copied) → conflict.
  - Who: anyone for himself; Technician / SiteManager for people of a project they are an
    active member of (``project_team.is_member``) or its ``default_site_manager_id``;
    office roles (Admin, Owner, Accountant) for anyone.
  - Backdate: a date before the tenant's local day (and before the UTC day) only by
    Admin / Owner, with a reason. The offline sync is not re-checked: its date is the
    server-derived capture day, late records already need the PWA-02 late confirmation.
* Four-eyes: the approver is none of worker, creator, submitter, last editor, correctors
  (idea from #75 ``self_approval_ids``); checked inside ``approve_report_one`` so every
  approve endpoint (single, bulk, the day dialog, "Моят ден") gets it.
* Idempotency: an ``Idempotency-Key`` header is stamped as ``idempotency_key`` on the lines a
  request writes; the same key again returns those lines instead of a conflict. The offline
  sync keeps ``sync_local_id`` (+ its unique index) exactly as before.
* AuditEvent: ``labor_line.created / updated / submitted / approved / rejected / voided``
  through ``app.audit.store.record_event`` (W0-04 chain, FLOW-014, R1), after the write.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.db import db
from app.tenancy import project_team
from app.tenancy.data_access import TenantData

SOURCE_FLOW = "FLOW-014"
OFFICE_ROLES = ("Admin", "Owner", "Accountant")
FIELD_ROLES = ("SiteManager", "Technician")
BACKDATE_ROLES = ("Admin", "Owner")
APPROVER_ROLES = ("Admin", "Owner", "SiteManager")
EDITABLE = ("Draft", "Submitted", "REJECTED", "Rejected")
ERR_EXISTS = "LABOR_LINE_EXISTS"
ERR_FORBIDDEN = "LABOR_REPORT_FORBIDDEN"
ERR_BACKDATE = "LABOR_BACKDATE_FORBIDDEN"
ERR_SELF = "FOUR_EYES"
SELF_APPROVAL_MSG = "Не можете да одобрите отчет, който сте създали или поправили — одобрява друг човек."


def _tenant(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════ key
def norm_activity(activity: Any) -> str:
    return re.sub(r"\s+", " ", str(activity or "").strip()).lower()


def labor_key(worker_id: str, date: str, project_id: str, activity: Any) -> str:
    return "%s|%s|%s|%s" % (worker_id, date, project_id, norm_activity(activity))


# ═══════════════════════════════════════════════════════════════════ errors
class LaborLineExists(HTTPException):
    """409 "Вече има отчет" with the existing line (``existing``)."""

    def __init__(self, existing: Dict[str, Any], status_code: int = 409):
        self.existing = existing
        super().__init__(status_code=status_code, detail=conflict_detail(existing))


def conflict_detail(existing: Dict[str, Any]) -> Dict[str, Any]:
    who = existing.get("worker_name") or existing.get("worker_id") or ""
    where = existing.get("project_name") or existing.get("project_id") or ""
    what = existing.get("activity") or "—"
    return {
        "error_code": ERR_EXISTS,
        "message": "Вече има отчет за %s на %s по %s / %s — отвори го." % (who, existing.get("date"), where, what),
        "message_en": "A labor report already exists for this person, day, project and activity.",
        "existing": existing,
    }


def as_legacy_400(exc: LaborLineExists) -> HTTPException:
    """For endpoints whose duplicate answer was already 400 (their screens read it)."""
    return HTTPException(status_code=400, detail=exc.detail)


def _forbidden(message: str, code: str = ERR_FORBIDDEN) -> HTTPException:
    return HTTPException(status_code=403, detail={"error_code": code, "message": message})


# ═══════════════════════════════════════════════════════════════════ who for whom
async def check_may_report(tenant: TenantData, actor: dict, worker_id: str, project_id: str) -> None:
    if worker_id == actor.get("id") or actor.get("role") in OFFICE_ROLES:
        return
    if actor.get("role") in FIELD_ROLES and project_id:
        team = project_team.tenant_for(db, actor)
        if await project_team.is_member(team, actor["id"], project_id):
            return
        if await tenant.projects.find_one({"id": project_id, "org_id": actor["org_id"],
                                           "default_site_manager_id": actor["id"]}, {"_id": 0, "id": 1}):
            return
        raise _forbidden("Можете да отчитате хора само на обект, в чийто екип сте.")
    raise _forbidden("Можете да отчитате само собствения си труд.")


# ═══════════════════════════════════════════════════════════════════ backdate (FLOW-014)
async def local_today(actor: dict) -> str:
    """The earlier of the tenant's local day and the UTC day — a report for either is "today"."""
    from app.services.offline_sync import local_day, tenant_zone
    now = datetime.now(timezone.utc)
    try:
        local = local_day(now, await tenant_zone(actor))
    except Exception:                                          # noqa: BLE001 — no org row / tz
        local = now.strftime("%Y-%m-%d")
    return min(local, now.strftime("%Y-%m-%d"))


async def check_backdate(actor: dict, date: str, reason: Optional[str]) -> None:
    if not date or date >= await local_today(actor):
        return
    if actor.get("role") not in BACKDATE_ROLES:
        raise HTTPException(status_code=400, detail={
            "error_code": ERR_BACKDATE,
            "message": "Отчет за минала дата (%s) може да въведе само администратор или собственик, "
                       "с причина." % date})
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail={
            "error_code": "LABOR_BACKDATE_REASON_REQUIRED",
            "message": "Отчет за минала дата изисква причина (бележка)."})


# ═══════════════════════════════════════════════════════════════════ presence (FLOW-013)
REPORT_AUTO_PRESENCE = "report_auto_presence"


async def report_auto_presence_enabled(tenant, org_id) -> bool:
    """FG-641: the tenant setting (default OFF) — Krum's answer to D21 only flips it."""
    flag = await tenant.feature_flags.find_one({"org_id": org_id, "module_code": REPORT_AUTO_PRESENCE},
                                               {"_id": 0, "enabled": 1})
    return bool(flag and flag.get("enabled") is True)


async def check_presence(tenant: TenantData, org_id: str, wid: str, worker_name: Optional[str],
                         date: str, project_id: str, allow_auto: bool = False) -> Optional[dict]:
    """FG-641 (FLOW-013 L89-90, literal reading until Krum decides — HANDOFF D21): a report for
    ANYONE on this object needs a presence (Present / Late) on THIS object that day. Only with the
    tenant setting ``report_auto_presence`` (default OFF) — and only on a path that writes the
    auto presence (``allow_auto``: the technician report) — does a presence on another object the
    same day let the report create this object's presence; that case returns the auto entry."""
    label = worker_name or wid
    day_flt = {"org_id": org_id, "date": date, "user_id": wid}
    att = await tenant.attendance_entries.find_one({**day_flt, "project_id": project_id},
                                                   {"_id": 0, "status": 1})
    auto = None
    if att is None:
        elsewhere = await tenant.attendance_entries.find_one(
            {**day_flt, "status": {"$in": ["Present", "Late"]}}, {"_id": 0, "project_id": 1})
        if elsewhere and allow_auto and await report_auto_presence_enabled(tenant, org_id):
            auto = {"worker_id": wid, "from_project_id": elsewhere.get("project_id")}
            att = {"status": "Present"}
        else:
            raise HTTPException(status_code=400, detail={
                "error_code": "PRESENCE_REQUIRED_ON_OBJECT",
                "message": f"Работникът {label} не е отбелязан като присъстващ "
                           f"на този обект за датата. Първо потвърдете присъствието в Хора."})
    cal = await tenant.worker_calendar.find_one(
        {"org_id": org_id, "date": date, "worker_id": wid, "status": {"$in": ["leave", "sick", "vacation"]}},
        {"_id": 0, "status": 1})
    if cal:
        raise HTTPException(status_code=400, detail=f"Работникът {label} е в {cal['status']}. Не може да бъде отчетен.")
    if att.get("status") in ("SickLeave", "Leave", "Vacation", "Excused"):
        raise HTTPException(status_code=400, detail=f"Работникът {label} е {att['status']}. Не може да бъде отчетен.")
    if att.get("status") not in ("Present", "Late"):
        raise HTTPException(status_code=400, detail=(
            f"Работникът {label} не е отбелязан като присъстващ за този обект и дата. "
            f"Първо потвърдете присъствието в Хора."))
    return auto


# ═══════════════════════════════════════════════════════════════════ existing lines
async def _names(tenant: TenantData, user_ids: Iterable[str]) -> Dict[str, str]:
    ids = [i for i in set(user_ids) if i]
    if not ids:
        return {}
    rows = await tenant.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "first_name": 1,
                                                          "last_name": 1}).to_list(len(ids))
    return {u["id"]: ("%s %s" % (u.get("first_name", ""), u.get("last_name", ""))).strip() for u in rows}


async def existing_view(tenant: TenantData, org_id: str, doc: dict, entry: Optional[dict] = None) -> dict:
    """What the conflict shows about an existing line (flat row, or one old-format entry)."""
    if entry is None:
        worker, date, pid = doc.get("worker_id"), doc.get("date"), doc.get("project_id")
        activity, hours = doc.get("smr_type"), doc.get("hours")
        status, by, fmt, line_id = doc.get("status"), doc.get("submitted_by") or doc.get("created_by"), "line", doc.get("id")
        report_id = doc.get("work_report_id") or doc.get("daily_log_id") or doc.get("id")
    else:
        worker, date, pid = doc.get("employee_id"), doc.get("report_date"), entry.get("project_id")
        activity, hours = entry.get("work_description") or entry.get("smr_id"), entry.get("hours_worked")
        status, by, fmt, line_id = doc.get("approval_status"), doc.get("created_by"), "old", entry.get("id")
        report_id = doc.get("id")
    names = await _names(tenant, [worker, by])
    proj = await tenant.projects.find_one({"id": pid, "org_id": org_id}, {"_id": 0, "name": 1}) if pid else None
    return {"line_id": line_id, "report_id": report_id, "format": fmt,
            "worker_id": worker, "worker_name": doc.get("worker_name") or names.get(worker, ""),
            "date": date, "project_id": pid, "project_name": (proj or {}).get("name", ""),
            "activity": activity, "hours": hours, "status": status,
            "entered_by": by, "entered_by_name": names.get(by, ""),
            "work_report_id": doc.get("work_report_id"), "daily_log_id": doc.get("daily_log_id")}


async def find_existing(tenant: TenantData, org_id: str, worker_id: str, date: str, project_id: str,
                        activity: Any, ignore_ids: Iterable[str] = (), session=None) -> Optional[dict]:
    """The live line already holding (worker, date, project, activity) — flat or old format."""
    kw = {} if session is None else {"session": session}
    key, ignore = norm_activity(activity), set(ignore_ids or ())
    flat = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "worker_id": worker_id, "date": date, "project_id": project_id},
        {"_id": 0}, **kw).to_list(500)
    for d in flat:
        if d.get("id") not in ignore and norm_activity(d.get("smr_type")) == key:
            return await existing_view(tenant, org_id, d)
    olds = await tenant.employee_daily_reports.find(
        {"org_id": org_id, "employee_id": worker_id, "report_date": date}, {"_id": 0}, **kw).to_list(50)
    for d in olds:
        if d.get("id") in ignore:
            continue
        for e in d.get("day_entries") or []:
            if e.get("project_id") != project_id or e.get("id") in ignore:
                continue
            names = {norm_activity(e.get("work_description")), norm_activity(e.get("smr_id"))}
            if key in names or (not key and not any(names)):
                return await existing_view(tenant, org_id, d, e)
    return None


async def lines_by_idempotency(tenant: TenantData, org_id: str, actor_id: str, key: Optional[str]) -> List[dict]:
    if not key:
        return []
    return await tenant.employee_daily_reports.find(
        {"org_id": org_id, "idempotency_key": key, "created_by": actor_id}, {"_id": 0}).sort(
        "created_at", 1).to_list(500)


# ═══════════════════════════════════════════════════════════════════ plan + write
class LinePlan(dict):
    """One validated line, ready to insert (all checks passed for the whole request)."""


async def plan_lines(actor: dict, project_id: str, date: str, entries: List[dict], *,
                     reason: Optional[str] = None, sync: bool = False, allow_auto_presence: bool = False,
                     ignore_ids: Iterable[str] = (), skip_presence_for: Iterable[str] = ()) -> List[LinePlan]:
    """Run every check for every entry BEFORE anything is written (all or nothing).

    ``entries``: ``{"worker_id", "worker_name", "activity", "hours", ...extra}``.
    ``ignore_ids``: lines this request replaces (they do not conflict with themselves).
    """
    from app.services.project_guards import check_project_writable
    tenant, org_id = _tenant(actor), actor["org_id"]
    project = await tenant.projects.find_one({"id": project_id, "org_id": org_id}, {"_id": 0, "id": 1, "name": 1})
    if not project:
        await check_project_writable(project_id, org_id, "отчети")    # tombstoned → 409
        raise HTTPException(status_code=404, detail="Project not found")
    await check_project_writable(project_id, org_id, "отчети")
    if not sync:
        await check_backdate(actor, date, reason)
    plans, seen = [], {}
    for e in entries:
        wid = e["worker_id"]
        await check_may_report(tenant, actor, wid, project_id)
    missing = await _names(tenant, [e["worker_id"] for e in entries if not e.get("worker_name")])
    for e in entries:
        if not e.get("worker_name"):
            e["worker_name"] = missing.get(e["worker_id"], "")
    for e in entries:
        wid = e["worker_id"]
        auto = None
        if wid not in set(skip_presence_for):
            auto = await check_presence(tenant, org_id, wid, e.get("worker_name"), date, project_id,
                                        allow_auto=allow_auto_presence)
        k = labor_key(wid, date, project_id, e.get("activity"))
        if k in seen:
            raise LaborLineExists({**seen[k], "same_request": True})
        found = await find_existing(tenant, org_id, wid, date, project_id, e.get("activity"), ignore_ids)
        if found:
            raise LaborLineExists(found)
        seen[k] = {"worker_id": wid, "worker_name": e.get("worker_name") or wid, "date": date,
                   "project_id": project_id, "project_name": project.get("name", ""),
                   "activity": e.get("activity"), "hours": e.get("hours"), "status": "Draft",
                   "entered_by": actor["id"]}
        plans.append(LinePlan(entry=e, key=k, auto_presence=auto))
    return plans


def line_doc(actor: dict, plan: LinePlan, project_id: str, date: str, now: str,
             entry_mode: str, idempotency_key: Optional[str] = None) -> dict:
    """The ONE flat line format (the technician shape + key / creator / idempotency)."""
    e = plan["entry"]
    is_admin_entry = actor["role"] in ("Admin", "Owner", "SiteManager")
    doc = {
        "id": str(uuid.uuid4()), "org_id": actor["org_id"], "project_id": project_id, "date": date,
        "worker_id": e["worker_id"], "worker_name": e.get("worker_name") or "",
        "smr_type": e.get("activity") or "", "smr_subtype": e.get("smr_subtype") or "",
        "hours": round(float(e.get("hours") or 0), 2), "notes": e.get("notes") or "",
        "status": "Draft", "submitted_by": actor["id"], "created_by": actor["id"],
        "entered_by_admin": is_admin_entry, "entry_mode": entry_mode,
        "labor_key": plan["key"], "created_at": now, "updated_at": now,
    }
    if idempotency_key:
        doc["idempotency_key"] = idempotency_key
    for k, v in (e.get("extra") or {}).items():
        doc[k] = v
    return doc


async def insert_line(tenant: TenantData, doc: dict, session=None) -> None:
    kw = {} if session is None else {"session": session}
    try:
        await tenant.employee_daily_reports.insert_one(doc, **kw)
    except DuplicateKeyError as exc:
        if "labor_key" not in str(exc):
            raise
        # the partial unique index: a concurrent request committed the same line first
        raise LaborLineExists({"worker_id": doc["worker_id"], "worker_name": doc.get("worker_name"),
                               "date": doc["date"], "project_id": doc["project_id"],
                               "activity": doc.get("smr_type"), "concurrent": True})


async def write_lines(actor: dict, plans: List[LinePlan], project_id: str, date: str, *,
                      entry_mode: str, idempotency_key: Optional[str] = None,
                      source_channel: str = "api") -> List[dict]:
    """Insert planned lines (no transaction — callers that need one use ``insert_line``)."""
    tenant, now, docs = _tenant(actor), _now(), []
    for p in plans:
        doc = line_doc(actor, p, project_id, date, now, entry_mode, idempotency_key)
        await insert_line(tenant, doc)
        docs.append(doc)
    for doc in docs:
        await audit(actor, "labor_line.created", doc, {"after": line_summary(doc)},
                    idempotency_key=idempotency_key, source_channel=source_channel)
    return [{k: v for k, v in d.items() if k != "_id"} for d in docs]


def line_summary(doc: dict) -> dict:
    return {k: doc.get(k) for k in ("worker_id", "date", "project_id", "smr_type", "hours", "status",
                                    "entry_mode")}


# ═══════════════════════════════════════════════════════════════════ update / submit / void
async def update_line(actor: dict, line: dict, changes: Dict[str, Any], reason: Optional[str] = None) -> dict:
    """Edit a Draft / Submitted / Rejected line. A new activity is a new key → conflict check.
    The editor is recorded (``last_edited_by``, ``correctors``) for four-eyes."""
    tenant, org_id = _tenant(actor), actor["org_id"]
    if line.get("status") not in EDITABLE:
        raise HTTPException(status_code=400, detail="Cannot edit approved/rejected reports")
    await check_may_report(tenant, actor, line.get("worker_id"), line.get("project_id"))
    upd = {k: v for k, v in changes.items() if v is not None}
    if "hours" in upd:
        upd["hours"] = round(float(upd["hours"]), 2)
    if "smr_type" in upd and norm_activity(upd["smr_type"]) != norm_activity(line.get("smr_type")):
        found = await find_existing(tenant, org_id, line["worker_id"], line["date"], line["project_id"],
                                    upd["smr_type"], ignore_ids=[line["id"]])
        if found:
            raise LaborLineExists(found)
        upd["labor_key"] = labor_key(line["worker_id"], line["date"], line["project_id"], upd["smr_type"])
    before = {k: line.get(k) for k in upd}
    if line.get("status") in ("REJECTED", "Rejected"):
        upd["status"] = "Draft"
    now = _now()
    upd.update({"updated_at": now, "last_edited_by": actor["id"], "last_edited_at": now})
    await tenant.employee_daily_reports.update_one(
        {"id": line["id"], "org_id": org_id},
        {"$inc": {"version": 1}, "$set": upd, "$addToSet": {"correctors": actor["id"]}})
    after = await tenant.employee_daily_reports.find_one({"id": line["id"], "org_id": org_id}, {"_id": 0})
    await audit(actor, "labor_line.updated", after, {"before": before, "after": {k: after.get(k) for k in before}},
                reason=reason)
    return after


async def submit_lines(actor: dict, lines: List[dict]) -> List[str]:
    tenant, now, done = _tenant(actor), _now(), []
    for ln in lines:
        if ln.get("status") not in ("Draft", "REJECTED", "Rejected"):
            continue
        await tenant.employee_daily_reports.update_one(
            {"id": ln["id"], "org_id": actor["org_id"]},
            {"$inc": {"version": 1}, "$set": {"status": "Submitted", "submitted_at": now, "updated_at": now}})
        done.append(ln["id"])
        await audit(actor, "labor_line.submitted", ln, {"before": {"status": ln.get("status")},
                                                        "after": {"status": "Submitted"}})
    return done


async def void_lines(actor: dict, lines: List[dict], reason: str) -> List[str]:
    """Remove a line from a draft: voided with a reason and an AuditEvent (FG-650) — the row
    stays in history; its key is released."""
    from app.services import attendance_void
    tenant = _tenant(actor)
    for ln in lines:
        if ln.get("status") not in ("Draft", "Submitted", "REJECTED", "Rejected"):
            raise HTTPException(status_code=400, detail="Одобрен ред е заключен — поправката е с история.")
    return await attendance_void.void_reports(tenant, actor, lines, reason)


# ═══════════════════════════════════════════════════════════════════ four-eyes
def self_approval_ids(report: dict) -> set:
    """Everyone who may NOT approve this line: its worker, authors and correctors (#75)."""
    ids = {report.get(k) for k in ("worker_id", "employee_id", "submitted_by", "created_by",
                                   "last_edited_by", "corrected_by")}
    ids |= set(report.get("correctors") or [])
    return {i for i in ids if i}


def is_self_approval(report: dict, actor: dict) -> bool:
    return actor.get("id") in self_approval_ids(report)


def four_eyes_http() -> HTTPException:
    return _forbidden(SELF_APPROVAL_MSG, ERR_SELF)


# ═══════════════════════════════════════════════════════════════════ approve / reject
async def _get_hourly_rate_for_approval(org_id: str, worker_id: str) -> float:
    """Get hourly rate from employee profile for work_session creation."""
    from app.services.resolve_hourly_rate import resolve_worker_hourly_rate
    result = await resolve_worker_hourly_rate(worker_id, org_id)
    if isinstance(result, dict):
        return float(result.get("rate", 0))
    return float(result or 0)


async def approve_report_one(report: dict, actor: dict, override: dict | None = None,
                             block_overtime_without_override: bool = False) -> dict:
    """
    Canonical approval for ONE report (moved here from daily_reports.py, logic unchanged
    except the four-eyes gate and the AuditEvent). Does NOT raise — returns:
      {"status": "ok"|"blocked"|"failed", "report_id": ..., ...}
    Canonical decisions (P1-0.5):
      - slip counter key: counter_type="slip_number"
      - work_session SMR field: smr_type_id (canonical) + smr_type (compat)
      - labor_cost = regular*rate + overtime*rate*coefficient
      - default overtime_coefficient = 1.0 (no auto-overpay), split always stored
    """
    from app.routes.daily_reports import check_employee_hours
    tenant = _tenant(actor)
    org_id = actor["org_id"]
    rid = report["id"]
    now = _now()

    status = report.get("approval_status") or report.get("status", "")
    if status == "APPROVED":
        return {"status": "failed", "report_id": rid, "reason": "already_approved"}
    if is_self_approval(report, actor):                         # Р100 four-eyes
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
    await tenant.employee_daily_reports.update_one({"id": rid}, {"$inc": {"version": 1}, "$set": update})
    result = await tenant.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
    await audit(actor, "labor_line.approved", result, {
        "before": {"status": status}, "after": {"status": "APPROVED", "hours": hours,
                                                "labor_cost": labor_cost, "slip_number": slip_number}})

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
    now = _now()
    status = report.get("approval_status") or report.get("status", "")
    if status == "APPROVED":
        return {"status": "failed", "report_id": rid, "reason": "cannot_reject_approved"}
    if status == "REJECTED":
        return {"status": "skipped", "report_id": rid, "reason": "already_rejected"}
    await tenant.employee_daily_reports.update_one({"id": rid}, {"$inc": {"version": 1}, "$set": {
        "approval_status": "REJECTED", "status": "REJECTED",
        "reject_reason": reason, "rejected_by": actor["id"], "updated_at": now,
    }})
    await audit(actor, "labor_line.rejected", report, {"before": {"status": status},
                                                       "after": {"status": "REJECTED"}}, reason=reason or None)
    return {"status": "ok", "report_id": rid}


# ═══════════════════════════════════════════════════════════════════ old shape (adapters)
def _approval_of(lines: List[dict]) -> str:
    st = [(ln.get("approval_status") or ln.get("status") or "").upper() for ln in lines]
    if st and all(s == "APPROVED" for s in st):
        return "APPROVED"
    if any(s == "REJECTED" for s in st):
        return "REJECTED"
    if st and all(s in ("SUBMITTED", "APPROVED") for s in st):
        return "SUBMITTED"
    return "DRAFT"


def entry_of(line: dict) -> dict:
    """A flat line as an old-format ``day_entries`` item (the id IS the line id)."""
    return {"id": line["id"], "line_id": line["id"], "project_id": line.get("project_id"),
            "smr_id": line.get("smr_id"), "extra_work_id": line.get("extra_work_id"),
            "work_description": line.get("work_description") or line.get("smr_type") or "",
            "hours_worked": float(line.get("hours") or 0), "note": line.get("notes") or "",
            "status": line.get("status"), "smr_type": line.get("smr_type")}


async def day_lines(tenant: TenantData, org_id: str, worker_id: str, date: str) -> List[dict]:
    return await tenant.employee_daily_reports.find(
        {"org_id": org_id, "worker_id": worker_id, "date": date}, {"_id": 0}).sort("created_at", 1).to_list(500)


def old_shape_day(head_id: str, worker_id: str, date: str, lines: List[dict]) -> dict:
    """The employee's day (all live flat lines) in the shape ``DailyReportDialog`` and the
    personnel card read: ``employee_id / report_date / day_entries / approval_status``."""
    first = lines[0] if lines else {}
    return {
        "id": head_id, "org_id": first.get("org_id"), "storage": "labor_lines",
        "employee_id": worker_id, "report_date": date, "day_status": "WORKING",
        "leave_from": None, "leave_to": None, "notes": first.get("day_notes") or None,
        "day_entries": [entry_of(ln) for ln in lines],
        "total_hours": round(sum(float(ln.get("hours") or 0) for ln in lines), 2),
        "approval_status": _approval_of(lines), "line_ids": [ln["id"] for ln in lines],
        "created_by": first.get("created_by") or first.get("submitted_by"),
        "submitted_by": first.get("submitted_by"),
        "approved_by": first.get("approved_by"), "approved_at": first.get("approved_at"),
        "created_at": first.get("created_at"), "updated_at": first.get("updated_at"),
    }


# ═══════════════════════════════════════════════════════════════════ AuditEvent
async def audit(actor: dict, action: str, line: dict, diff: dict, *, reason: Optional[str] = None,
                idempotency_key: Optional[str] = None, source_channel: str = "api") -> None:
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    await record_event(db, build_event(
        tenant_id=actor["org_id"], actor_type=ACTOR_HUMAN, actor_id=actor["id"],
        action=action, source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="labor_line", entity_id=line.get("id"),
        scope_type="project", scope_id=line.get("project_id"), structured_diff=diff,
        reason=reason, effective_role_assignments=[actor.get("role") or ""],
        idempotency_key=idempotency_key, source_channel=source_channel))
