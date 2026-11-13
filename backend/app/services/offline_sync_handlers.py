"""PWA-02 — the three offline operations of this slice (orchestrator Q1, Krum 09.11.2026):
self attendance, the technician daily report, and a photo. Each handler calls THE SAME
domain function as the online endpoint; nothing bypasses its validation.

* ``attendance.mark`` — day = the tenant's local day of ``captured_at`` (Europe/Sofia).
  An identical self-mark (same day, site and status) is a silent idempotent "synced";
  any difference with the office's entry is a conflict, never merged (Krum + canon, Q3).
* ``technician.daily_report`` — the full report (not drafts only), through
  ``submit_daily_report`` with the captured local day.
* ``media.upload`` — metadata + SHA-256 only; without a File Registry the photo stops at
  „Чака качване на файл“ and is never final (Q1).

A day is CLOSED for a worker (Q4) when a paid / paying pay run covers that worker and day,
or an approved work report / approved, batched or paid daily report exists for them that
day; an offline write into a closed day is a conflict, settled only by correction /
reversal (R61-4).

Every record this module creates carries ``version`` (1), ``sync_local_id``,
``captured_at`` and ``device_id`` (additive; a missing ``version`` reads as 0).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.db import db
from app.services import offline_sync as sync
from app.tenancy.data_access import TenantData

PHOTO_MAX_BYTES = 25 * 1024 * 1024
VIDEO_MAX_BYTES = 200 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _tenant(user: Dict[str, Any]) -> TenantData:
    return TenantData.for_user(db, user)


def _stamp(env: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    extra = {"version": 1, "sync_local_id": env["local_id"], "captured_at": env["captured_at"],
             "captured_tz": env.get("captured_tz"), "device_id": ctx.get("device_id")}
    if ctx.get("confirmed_by"):
        extra.update({"late_confirmed_by": ctx["confirmed_by"], "late_confirmed_at": ctx["confirmed_at"]})
    return extra


async def closed_day(user: Dict[str, Any], worker_id: str, date: str) -> Optional[str]:
    """Q4: "paid" / "approved" when the worker's day is already closed by the office."""
    tenant = _tenant(user)
    org = user["org_id"]
    paid = await tenant.pay_runs.find_one(
        {"org_id": org, "status": {"$in": ["paid", "paying"]}, "period_start": {"$lte": date},
         "period_end": {"$gte": date}, "employee_rows.employee_id": worker_id}, {"_id": 0, "id": 1})
    if paid:
        return "paid"
    dr = await tenant.employee_daily_reports.find_one(
        {"org_id": org, "worker_id": worker_id, "date": date,
         "$or": [{"payroll_status": {"$in": ["batched", "paid"]}}]}, {"_id": 0, "payroll_status": 1})
    if dr:
        return "paid"
    approved = await tenant.employee_daily_reports.find_one(
        {"org_id": org, "worker_id": worker_id, "date": date,
         "$or": [{"approval_status": "APPROVED"}, {"status": "Approved"}]}, {"_id": 0, "id": 1})
    if approved:
        return "approved"
    wr = await tenant.work_reports.find_one(
        {"org_id": org, "user_id": worker_id, "date": date, "status": "Approved"}, {"_id": 0, "id": 1})
    if wr:
        return "approved"
    return None


# ─────────────────────────────────────────────────────────────── attendance
def _att_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {"date": doc.get("date"), "project_id": doc.get("project_id"), "status": doc.get("status"),
            "note": doc.get("note"), "version": doc.get("version", 0)}


async def _attendance(user: Dict[str, Any], env: Dict[str, Any], ctx: Dict[str, Any],
                      marked_by: str) -> Dict[str, Any]:
    from app.routes.attendance import ATTENDANCE_STATUSES, create_attendance_entry
    from app.services.project_guards import check_project_writable
    p = env["payload"]
    status, project_id, note = p.get("status"), p.get("project_id"), p.get("note")
    if status not in ATTENDANCE_STATUSES:
        raise sync.SyncRejected("STATUS_INVALID", "Невалиден статус на присъствие")
    date = ctx["captured_date"]
    tenant = _tenant(user)
    org = user["org_id"]
    phone = {"date": date, "project_id": project_id, "status": status, "note": note,
             "version": env.get("base_version")}
    mine = await tenant.attendance_entries.find_one(
        {"org_id": org, "sync_local_id": env["local_id"]}, {"_id": 0})
    if mine:  # an interrupted earlier attempt already wrote it
        return {"entity_type": "attendance", "entity_id": mine["id"], "date": date, "already": True}
    existing = await tenant.attendance_entries.find_one(
        {"org_id": org, "date": date, "user_id": user["id"]}, {"_id": 0})
    if existing:
        if existing.get("project_id") == project_id and existing.get("status") == status:
            # Q3: identical → idempotent confirmation, nothing written
            return {"entity_type": "attendance", "entity_id": existing["id"], "date": date,
                    "identical": True}
        kind = await closed_day(user, user["id"], date) or "already_recorded"
        raise sync.SyncConflict(entity_type="attendance", entity_id=existing["id"],
                                office=_att_view(existing), field=phone, kind=kind)
    kind = await closed_day(user, user["id"], date)
    if kind:
        raise sync.SyncConflict(entity_type="attendance", entity_id="%s:%s" % (user["id"], date),
                                office={"date": date, "closed": kind}, field=phone, kind=kind)
    await check_project_writable(project_id, org, "присъствия")
    entry = await create_attendance_entry(org, date, project_id, user["id"], status, note,
                                          marked_by, "offline_sync", extra=_stamp(env, ctx))
    return {"entity_type": "attendance", "entity_id": entry["id"], "date": date,
            "status": entry["status"]}


async def attendance_mark(user, env, ctx):
    return await _attendance(user, env, ctx, marked_by=user["id"])


async def attendance_confirm(author, env, ctx):
    # the office confirms on the worker's behalf: marked_by = the confirming Owner/Admin
    return await _attendance(author, env, ctx, marked_by=ctx["confirmed_by"])


async def attendance_apply(user: Dict[str, Any], conflict: Dict[str, Any],
                           values: Dict[str, Any]) -> Dict[str, Any]:
    """Accept the phone's attendance over the office's (not approved / paid): CAS on version."""
    from app.routes.attendance import ATTENDANCE_STATUSES
    status = values.get("status")
    if status not in ATTENDANCE_STATUSES:
        raise sync.refuse(422, "STATUS_INVALID", "Невалиден статус на присъствие")
    tenant = _tenant(user)
    org = user["org_id"]
    current = await tenant.attendance_entries.find_one({"org_id": org, "id": conflict["entity_id"]},
                                                       {"_id": 0})
    if not current:
        raise sync.refuse(409, "RECORD_GONE", "Офисният запис вече не съществува")
    if (current.get("version", 0)) != (conflict["office_version"].get("version", 0)):
        raise sync.refuse(409, "OFFICE_CHANGED_AGAIN", "Офисът промени записа след конфликта — отворете го отново")
    kind = await closed_day(user, current["user_id"], current["date"])
    if kind:
        raise sync.refuse(409, "CORRECTION_OR_REVERSAL_REQUIRED",
                          "Записът е одобрен/платен — промяна само чрез корекция или сторно", kind=kind)
    version = current.get("version", 0)
    flt = {"org_id": org, "id": current["id"]}
    flt["$or"] = [{"version": version}] + ([{"version": {"$exists": False}}] if version == 0 else [])
    res = await tenant.attendance_entries.update_one(
        flt, {"$set": {"status": status, "project_id": values.get("project_id", current.get("project_id")),
                       "note": values.get("note", current.get("note")), "version": version + 1,
                       "updated_at": sync.iso(sync.now_utc()), "updated_by": user["id"],
                       "update_source": "offline_conflict_resolution"}})
    if res.modified_count != 1:
        raise sync.refuse(409, "OFFICE_CHANGED_AGAIN", "Офисът промени записа междувременно")
    return {"entity_type": "attendance", "entity_id": current["id"], "version": version + 1}


# ──────────────────────────────────────────────────────── technician daily report
async def _daily_report(user: Dict[str, Any], env: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.routes.technician import DailyReportSubmit, submit_daily_report_core
    p = dict(env["payload"])
    date = ctx["captured_date"]
    tenant = _tenant(user)
    org = user["org_id"]
    async def already() -> Optional[Dict[str, Any]]:
        # an earlier attempt (crashed, slow or taken over) already wrote it — the drafts carry
        # sync_local_id from the insert itself, in one transaction (AUDIT-2 PWA92-M1)
        mine = await tenant.employee_daily_reports.find(
            {"org_id": org, "sync_local_id": env["local_id"]},
            {"_id": 0, "id": 1, "sync_entry_index": 1}).to_list(100)
        if not mine:
            return None
        mine.sort(key=lambda m: m.get("sync_entry_index") or 0)
        return {"entity_type": "daily_report", "entity_id": mine[0]["id"],
                "draft_report_ids": [m["id"] for m in mine], "date": date, "already": True}

    done = await already()
    if done:
        return done
    try:
        data = DailyReportSubmit(**{**p, "date": date})
    except Exception as exc:                                   # noqa: BLE001 — pydantic
        raise sync.SyncRejected("PAYLOAD_INVALID", "Невалиден отчет: %s" % str(exc)[:200])
    for entry in data.entries:
        wid = entry.worker_id or user["id"]
        kind = await closed_day(user, wid, date)
        if kind:
            raise sync.SyncConflict(entity_type="daily_report", entity_id="%s:%s" % (wid, date),
                                    office={"date": date, "worker_id": wid, "closed": kind},
                                    field={"date": date, "worker_id": wid, "hours": entry.hours,
                                           "smr_type": entry.smr_type}, kind=kind)
    try:
        result = await submit_daily_report_core(data, user, sync_stamp=_stamp(env, ctx))
    except DuplicateKeyError:
        # backstop: a concurrent attempt committed the same record first (unique
        # org_id + sync_local_id + sync_entry_index) — answer with what it wrote
        done = await already()
        if done:
            return done
        raise
    ids = list(result.get("draft_report_ids") or [])
    return {"entity_type": "daily_report", "entity_id": ids[0] if ids else env["local_id"],
            "draft_report_ids": ids, "date": date}


async def daily_report(user, env, ctx):
    return await _daily_report(user, env, ctx)


async def daily_report_confirm(author, env, ctx):
    return await _daily_report(author, env, ctx)


# ─────────────────────────────────────────────────────────────────── photo
async def media_upload(user: Dict[str, Any], env: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    p = env["payload"]
    sha = str(p.get("sha256") or "").lower()
    if not SHA256_RE.match(sha):
        raise sync.SyncRejected("CHECKSUM_INVALID", "Невалидна контролна сума на файла")
    mime = str(p.get("mime") or "")
    size = p.get("size")
    if not isinstance(size, int) or size <= 0:
        raise sync.SyncRejected("SIZE_INVALID", "Невалиден размер на файла")
    if mime.startswith("image/"):
        limit = PHOTO_MAX_BYTES
    elif mime.startswith("video/"):
        limit = VIDEO_MAX_BYTES
    else:
        raise sync.SyncRejected("TYPE_INVALID", "Само снимка или видео")
    if size > limit:
        raise sync.SyncRejected("FILE_TOO_LARGE", "Файлът е твърде голям")
    # Q1: no File Registry → the original stays on the phone; never final here.
    raise sync.SyncWaitingFile({"sha256": sha, "size": size, "mime": mime,
                                "context_type": p.get("context_type"), "context_id": p.get("context_id"),
                                "file_registry": "unavailable"})


def register_all() -> None:
    sync.register("attendance.mark", attendance_mark, confirm=attendance_confirm)
    sync.register("technician.daily_report", daily_report, confirm=daily_report_confirm)
    sync.register("media.upload", media_upload, confirm=media_upload)
    sync.APPLIERS["attendance.mark"] = attendance_apply


register_all()
