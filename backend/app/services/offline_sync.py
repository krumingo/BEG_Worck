"""PWA-02 (R61) — the server side of the offline queue.

A phone records field work without a connection and later sends the queued items to
``POST /api/sync/batch``. Each item carries an envelope (FLOW-037 §9): ``local_id``,
``idempotency_key``, ``op_type``, ``captured_at`` + ``captured_tz``,
``device_clock_offset_ms``, ``device_id``, ``tenant_id``, ``user_id``, ``base_version``
and the operation payload. This module decides, for every item and in this order:

1. the envelope is valid and belongs to the caller's tenant and user, else REJECTED;
2. the same (tenant, user, idempotency_key) was seen before → the stored answer, nothing
   written again (``sync_receipts``, unique index; kept, never expired → ≥ 30 days);
3. the device is blocked (R61-6) → QUARANTINED (``sync_quarantine``), never official;
4. the operation needs the internet (money, approvals, contracts, IBAN, roles…) or is not
   an offline type this build knows → REJECTED;
5. the record is late (R61-3: captured before today in the tenant's zone, or the phone's
   clock is more than 10 minutes off) → LATE (``sync_late``), not official until Owner or
   Admin confirms it;
6. the handler of the operation runs THE SAME domain path as the online endpoint. A
   field edit against a record that changed in the office, or that is approved or paid,
   raises :class:`SyncConflict` → CONFLICT (``sync_conflicts``, R61-2/R61-4); nothing is
   merged or overwritten.

The authoritative time of an item is the server's time of receipt; ``captured_at`` is kept
next to it and shown. The console (Owner/Admin) is a projection of these collections, not
a second source of truth.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.db import db
from app.tenancy.data_access import TenantData

logger = logging.getLogger(__name__)

try:  # Python 3.9+
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore

FLAG_CODE = "offline_queue"
DEFAULT_TZ = "Europe/Sofia"
#: R61-3 / PWA-02 default: a phone clock more than 10 minutes off makes the record late.
CLOCK_SKEW_LIMIT_MS = 10 * 60 * 1000
MAX_BATCH = 50
#: a receipt left "processing" this long (a crashed request) may be taken over.
PROCESSING_STALE = timedelta(minutes=2)

# item statuses (the client maps them to the FLOW-037 §9 words)
SYNCED = "synced"
CONFLICT = "conflict"
LATE = "late"
REJECTED = "rejected"
QUARANTINED = "quarantined"
PROCESSING = "processing"
#: AUDIT-2 PWA92-N1: an unexpected server error on ONE item — nothing official was kept, the
#: phone keeps the record and sends it again later (the receipt may be taken over at once).
RETRY = "retry"
#: a photo/video whose metadata and checksum arrived; the original stays on the phone until
#: a File Registry confirms the same checksum (FLOW-037 L192). Never final in this build.
WAITING_FILE = "waiting_file"

#: R61-1: these never go through the offline queue — money and approvals need the internet.
ONLINE_ONLY_PREFIXES = (
    "payment", "invoice", "notice", "act", "contract", "annex", "approval", "approve",
    "iban", "counterparty", "role", "permission", "master_data",
)

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

COLLECTIONS = ("sync_devices", "sync_receipts", "sync_conflicts", "sync_late", "sync_quarantine")


def refuse(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message,
                                                     **extra})


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _tenant(user: Dict[str, Any]) -> TenantData:
    return TenantData.for_user(db, user)


# ───────────────────────────────────────────────────────────────────── indexes
#: the unique indexes; a database that already holds duplicates of one of them gets an ALARM
#: and that index is skipped (FG-636) — never a crashed startup. Dry-run report:
#: ``scripts/pwa02_unique_index_dryrun.py`` (read-only; the fix needs a decision + Approval).
UNIQUE_INDEXES = (
    ("sync_devices", [("org_id", 1), ("id", 1)], "pwa02_device_unique", "id"),
    ("sync_receipts", [("org_id", 1), ("user_id", 1), ("idempotency_key", 1)],
     "pwa02_receipt_key_unique", "idempotency_key"),
    # AUDIT-2 PWA92-M1 backstop: one draft per offline record entry, ever. Partial — only
    # rows written by the offline path carry sync_local_id; online drafts are untouched.
    ("employee_daily_reports", [("org_id", 1), ("sync_local_id", 1), ("sync_entry_index", 1)],
     "pwa02_daily_report_sync_unique", "sync_local_id"),
    # FG-627/635: one attendance entry per worker and day (the writers stamp the key; older
    # rows without it are untouched by the partial index).
    ("attendance_entries", [("attendance_day_key", 1)], "pwa02_attendance_day_unique",
     "attendance_day_key"),
)


async def ensure_sync_indexes(database) -> List[str]:
    """Idempotent; at startup and for every tenant database (no request creates a
    collection). There is no migration runner in main — same pattern as OH-01.
    Returns the names of unique indexes that could NOT be created (duplicates)."""
    from pymongo.errors import OperationFailure
    skipped: List[str] = []
    # Unique only over rows that carry the key (partial index): a database that already
    # holds rows without these fields (an old backup) must not stop the index from being
    # created, and two real rows with the same key are still refused.
    for coll, keys, name, field in UNIQUE_INDEXES:
        try:
            await database[coll].create_index(keys, unique=True, name=name,
                                              partialFilterExpression={field: {"$type": "string"}})
        except (DuplicateKeyError, OperationFailure) as exc:
            if getattr(exc, "code", None) not in (11000, 11001) and "duplicate key" not in str(exc).lower():
                raise
            skipped.append(name)
            logger.critical("ALARM PWA-02: unique index %s on %s.%s NOT created — duplicate rows "
                            "exist; run scripts/pwa02_unique_index_dryrun.py (read-only) and decide",
                            name, getattr(database, "name", "?"), coll)
    await database["sync_receipts"].create_index([("org_id", 1), ("device_id", 1), ("received_at", -1)],
                                                 name="pwa02_receipt_device")
    for name in ("sync_conflicts", "sync_late", "sync_quarantine"):
        await database[name].create_index([("org_id", 1), ("status", 1), ("created_at", -1)],
                                          name="pwa02_%s_status" % name)
    return skipped


#: FG-642: unique indexes skipped at this process's startup (duplicates) — the health
#: endpoint exposes the flag; the record is kept in the system database (``ops_alarms``).
INDEX_ALARMS: List[Dict[str, Any]] = []


async def _audit_index_alarm(tenant_ids: List[str], database_name: str, index: str) -> None:
    """FG-642: a SYSTEM AuditEvent in every tenant's chain whose data lives in that database."""
    from app.audit.envelope import ACTOR_SYSTEM, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    for tid in tenant_ids:
        try:
            await record_event(db, build_event(
                tenant_id=tid, actor_type=ACTOR_SYSTEM, actor_id="startup", action="sync.index_skipped",
                source_flow="FLOW-037", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
                entity_type="index", entity_id=index, reason="duplicate rows exist",
                structured_diff={"index": index, "database": database_name},
                effective_role_assignments=[], idempotency_key=None, source_channel="startup"))
        except Exception:                                      # noqa: BLE001 — the alarm record stays
            logger.exception("ALARM PWA-02: could not write the index AuditEvent")


async def _raise_index_alarm(system_db, database_name: str, index: str) -> None:
    doc = {"id": str(uuid.uuid4()), "kind": "pwa02_unique_index_skipped", "status": "open",
           "database": database_name, "index": index, "raised_at": iso(now_utc()),
           "action": "scripts/pwa02_unique_index_dryrun.py (read-only), then a decision + Approval"}
    INDEX_ALARMS.append({k: doc[k] for k in ("kind", "index", "raised_at")})
    try:
        # one open alarm per database + index (a restart does not pile them up)
        await system_db["ops_alarms"].update_one(
            {"kind": doc["kind"], "database": database_name, "index": index, "status": "open"},
            {"$setOnInsert": doc, "$set": {"last_seen_at": doc["raised_at"]}}, upsert=True)
    except Exception:                                          # noqa: BLE001 — the log line stays
        logger.exception("ALARM PWA-02: could not record the index alarm")


def is_degraded() -> bool:
    """For the unauthenticated /api/health: a boolean only (FG-642) — no counts, no names."""
    return bool(INDEX_ALARMS)


async def ops_alarms(system_db) -> Dict[str, Any]:
    """For the authenticated ops endpoint (platform administrator)."""
    open_alarms = await system_db["ops_alarms"].find(
        {"kind": "pwa02_unique_index_skipped", "status": "open"}, {"_id": 0}).to_list(500)
    return {"this_process": len(INDEX_ALARMS), "open": len(open_alarms), "alarms": open_alarms}


async def ensure_sync_indexes_for_installation(op_db, system_db) -> List[str]:
    names = [op_db.name]
    records = await system_db["tenant_registry"].find(
        {}, {"_id": 0, "id": 1, "database_name": 1}).to_list(None)
    tenants_of: Dict[str, List[str]] = {}
    for r in records:
        name = r.get("database_name")
        if name and name not in names:
            names.append(name)
        if name and r.get("id"):
            tenants_of.setdefault(name, []).append(r["id"])
    for name in names:
        skipped = await ensure_sync_indexes(op_db if name == op_db.name else op_db.client[name])
        for index in skipped:
            await _raise_index_alarm(system_db, name, index)
            await _audit_index_alarm(tenants_of.get(name, []), name, index)
    return names


# ──────────────────────────────────────────────────────────────── feature flag
async def is_enabled(user: Dict[str, Any]) -> bool:
    row = await _tenant(user).feature_flags.find_one(
        {"org_id": user["org_id"], "module_code": FLAG_CODE}, {"_id": 0, "enabled": 1})
    return bool(row and row.get("enabled") is True)


async def require_enabled(user: Dict[str, Any]) -> None:
    if not await is_enabled(user):
        raise refuse(403, "OFFLINE_QUEUE_DISABLED", "Работата без интернет не е включена за фирмата")


async def set_enabled(user: Dict[str, Any], enabled: bool) -> Dict[str, Any]:
    stamp = iso(now_utc())
    await _tenant(user).feature_flags.update_one(
        {"org_id": user["org_id"], "module_code": FLAG_CODE},
        {"$set": {"enabled": bool(enabled), "updated_at": stamp, "updated_by": user["id"]},
         "$setOnInsert": {"created_at": stamp}},
        upsert=True)
    await audit(user, action="sync.flag_set", entity_type="feature_flag", entity_id=FLAG_CODE,
                diff={"enabled": bool(enabled)}, reason=None, key=None)
    return {"module_code": FLAG_CODE, "enabled": bool(enabled)}


# ──────────────────────────────────────────────────────────────────── audit
async def audit(user: Dict[str, Any], *, action: str, entity_type: str, entity_id: str,
                diff: Dict[str, Any], reason: Optional[str], key: Optional[str]) -> Dict[str, Any]:
    """The canonical W0-04 AuditEvent (FLOW-037 offline sync)."""
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=user["org_id"], actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow="FLOW-037", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type=entity_type, entity_id=entity_id, reason=reason, structured_diff=diff,
        effective_role_assignments=[user.get("role") or ""], idempotency_key=key,
        source_channel="offline_sync")
    return await record_event(db, event)


# ────────────────────────────────────────────────────────────────── devices
def valid_device_id(value: Any) -> str:
    if not isinstance(value, str) or not UUID_RE.match(value):
        raise refuse(422, "DEVICE_ID_INVALID", "Невалиден идентификатор на устройство")
    return value.lower()


async def get_device(user: Dict[str, Any], device_id: str) -> Optional[Dict[str, Any]]:
    return await _tenant(user).sync_devices.find_one(
        {"org_id": user["org_id"], "id": device_id}, {"_id": 0})


async def register_device(user: Dict[str, Any], device_id: str, label: str,
                          user_agent: str) -> Dict[str, Any]:
    """Registered at login (and on every app start); a blocked device stays blocked."""
    device_id = valid_device_id(device_id)
    existing = await get_device(user, device_id)
    if existing and existing.get("revoked_at"):
        raise refuse(403, "DEVICE_REVOKED", "Устройството е блокирано", device_id=device_id)
    stamp = iso(now_utc())
    await _tenant(user).sync_devices.update_one(
        {"org_id": user["org_id"], "id": device_id},
        {"$set": {"last_user_id": user["id"], "last_user_name": _user_name(user),
                  "label": (label or "")[:80], "user_agent": (user_agent or "")[:200],
                  "last_seen_at": stamp},
         "$setOnInsert": {"created_at": stamp, "registered_by": user["id"],
                          "revoked_at": None}},
        upsert=True)
    if not existing:
        await audit(user, action="sync.device_registered", entity_type="sync_device",
                    entity_id=device_id, diff={"label": (label or "")[:80]}, reason=None, key=None)
    return await get_device(user, device_id)


async def revoke_device(user: Dict[str, Any], device_id: str, reason: str, key: str) -> Dict[str, Any]:
    """R61-6: Owner/Admin blocks a lost or stolen phone. Idempotent per key."""
    device_id = valid_device_id(device_id)
    device = await get_device(user, device_id)
    if not device:
        raise refuse(404, "DEVICE_NOT_FOUND", "Няма такова устройство")
    if device.get("revoked_at"):
        return device
    stamp = iso(now_utc())
    await _tenant(user).sync_devices.update_one(
        {"org_id": user["org_id"], "id": device_id, "revoked_at": None},
        {"$set": {"revoked_at": stamp, "revoked_by": user["id"],
                  "revoked_by_name": _user_name(user), "revoke_reason": reason}})
    await audit(user, action="sync.device_revoked", entity_type="sync_device", entity_id=device_id,
                diff={"before": {"revoked_at": None}, "after": {"revoked_at": stamp}},
                reason=reason, key=key)
    return await get_device(user, device_id)


def _user_name(user: Dict[str, Any]) -> str:
    name = ("%s %s" % (user.get("first_name") or "", user.get("last_name") or "")).strip()
    return name or user.get("name") or user.get("email") or user.get("id") or ""


# ─────────────────────────────────────────────────────────────── envelope
class EnvelopeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _parse_iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise EnvelopeError("CAPTURED_AT_INVALID", "Липсва или е невалиден час на записа")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EnvelopeError("CAPTURED_AT_INVALID", "Липсва или е невалиден час на записа")
    if dt.tzinfo is None:
        raise EnvelopeError("CAPTURED_AT_INVALID", "Часът на записа трябва да е с часова зона (UTC)")
    return dt.astimezone(timezone.utc)


def zone(name: Optional[str]):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def validate_envelope(user: Dict[str, Any], item: Any, device_id: str) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise EnvelopeError("ENVELOPE_INVALID", "Невалиден запис")
    for field in ("local_id", "idempotency_key"):
        if not isinstance(item.get(field), str) or not UUID_RE.match(item[field]):
            raise EnvelopeError("ENVELOPE_INVALID", "Невалидно поле %s" % field)
    op = item.get("op_type")
    if not isinstance(op, str) or not re.match(r"^[a-z][a-z0-9_.]{1,60}$", op):
        raise EnvelopeError("ENVELOPE_INVALID", "Невалиден тип на записа")
    # Tenant isolation: the tenant comes from the session only; an envelope written for
    # another tenant (or user) is refused, never re-targeted.
    if item.get("tenant_id") != user["org_id"]:
        raise EnvelopeError("TENANT_MISMATCH", "Записът е за друга фирма")
    if item.get("user_id") != user["id"]:
        raise EnvelopeError("USER_MISMATCH", "Записът е на друг потребител")
    if item.get("device_id") and str(item["device_id"]).lower() != device_id:
        raise EnvelopeError("DEVICE_MISMATCH", "Записът е от друго устройство")
    captured = _parse_iso(item.get("captured_at"))
    tz = item.get("captured_tz") if isinstance(item.get("captured_tz"), str) else DEFAULT_TZ
    offset = item.get("device_clock_offset_ms", 0)
    if not isinstance(offset, (int, float)) or isinstance(offset, bool):
        offset = 0
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    base_version = item.get("base_version")
    if base_version is not None and not isinstance(base_version, str):
        raise EnvelopeError("ENVELOPE_INVALID", "Невалидна версия")
    return {"local_id": item["local_id"].lower(), "idempotency_key": item["idempotency_key"].lower(),
            "op_type": op, "captured_at": iso(captured), "captured_dt": captured,
            "captured_tz": tz[:64], "device_clock_offset_ms": int(offset),
            "payload": payload, "base_version": base_version,
            "project_id": item.get("project_id") if isinstance(item.get("project_id"), str) else None}


def fingerprint(env: Dict[str, Any]) -> str:
    body = {k: env[k] for k in ("local_id", "op_type", "captured_at", "payload", "base_version",
                                "project_id")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def is_online_only(op_type: str) -> bool:
    head = op_type.split(".", 1)[0]
    return any(head.startswith(p) for p in ONLINE_ONLY_PREFIXES) or ".approve" in op_type


async def tenant_zone(user: Dict[str, Any]):
    org = await _tenant(user).own_organization({"_id": 0, "org_timezone": 1})
    return zone((org or {}).get("org_timezone") or DEFAULT_TZ)


def local_day(dt: datetime, tz) -> str:
    """Krum (09.11.2026): the attendance / report day is the TENANT's local day
    (Europe/Sofia), not the UTC day — DST-aware through zoneinfo."""
    return dt.astimezone(tz).date().isoformat()


def capture_on_server_clock(env: Dict[str, Any], received: datetime) -> datetime:
    """FG-634: the capture moment on the SERVER clock — the phone's time corrected by the
    offset it measured against the server (device − server), never later than the receipt."""
    corrected = env["captured_dt"] - timedelta(milliseconds=int(env.get("device_clock_offset_ms") or 0))
    return min(corrected, received)


def capture_day(env: Dict[str, Any], received: datetime, tz) -> str:
    """The tenant-local day a record belongs to: never "tomorrow" relative to the receipt."""
    return local_day(capture_on_server_clock(env, received), tz)


def late_reason(env: Dict[str, Any], received: datetime, tz) -> Optional[str]:
    """R61-3: before today (tenant zone, server clock) or a phone clock off by > 10 min.
    FG-634: a capture time in the future beyond the tolerance goes to the console."""
    if abs(env["device_clock_offset_ms"]) > CLOCK_SKEW_LIMIT_MS:
        return "clock_skew"
    corrected = env["captured_dt"] - timedelta(milliseconds=int(env.get("device_clock_offset_ms") or 0))
    if env["captured_dt"] > received + timedelta(milliseconds=CLOCK_SKEW_LIMIT_MS) \
            or corrected > received + timedelta(milliseconds=CLOCK_SKEW_LIMIT_MS):
        return "clock_skew"  # captured "in the future"
    if capture_day(env, received, tz) < local_day(received, tz):
        return "previous_day"
    return None


# ───────────────────────────────────────────────────────────────── handlers
class SyncConflict(Exception):
    """Raised by a handler: the office record differs from what the phone edited, or is
    approved / paid (R61-2, R61-4). Nothing has been written."""

    def __init__(self, *, entity_type: str, entity_id: str, office: Dict[str, Any],
                 field: Dict[str, Any], kind: str = "version"):
        super().__init__(kind)
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.office = office
        self.field = field
        self.kind = kind  # version | approved | paid | already_recorded


class SyncWaitingFile(Exception):
    """Raised by a file handler: accepted as metadata only, the file itself is not taken."""

    def __init__(self, result: Dict[str, Any]):
        super().__init__("waiting_file")
        self.result = result


class SyncRejected(Exception):
    """Raised by a handler: the server refused the item (validation / permission). The
    phone shows „Изисква проверка“; no retry."""

    def __init__(self, code: str, message: str, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


#: op_type -> handler(user, env, ctx) -> result dict. Handlers call the SAME domain path
#: as the online endpoint and tag what they create with ``sync_local_id`` so that a
#: request interrupted after the write is not written twice.
Handler = Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]
HANDLERS: Dict[str, Handler] = {}
#: op_type -> handler used when Owner/Admin CONFIRMS a late record (the captured date).
CONFIRM_HANDLERS: Dict[str, Handler] = {}


def register(op_type: str, handler: Handler, confirm: Optional[Handler] = None) -> None:
    HANDLERS[op_type] = handler
    if confirm is not None:
        CONFIRM_HANDLERS[op_type] = confirm


def diff_versions(office: Dict[str, Any], field: Dict[str, Any]) -> List[Dict[str, Any]]:
    keys = sorted(set(office) | set(field))
    return [{"field": k, "office": office.get(k), "phone": field.get(k)}
            for k in keys if office.get(k) != field.get(k)]


# ──────────────────────────────────────────────────────────────── receipts
async def _claim(user: Dict[str, Any], env: Dict[str, Any], device_id: str,
                 received: datetime) -> Dict[str, Any]:
    """Insert the receipt (unique key). Returns {"replay": receipt} when the key was seen."""
    tenant = _tenant(user)
    fp = fingerprint(env)
    doc = {"id": str(uuid.uuid4()), "org_id": user["org_id"], "user_id": user["id"],
           "idempotency_key": env["idempotency_key"], "local_id": env["local_id"],
           "op_type": env["op_type"], "device_id": device_id, "fingerprint": fp,
           "captured_at": env["captured_at"], "captured_tz": env["captured_tz"],
           "device_clock_offset_ms": env["device_clock_offset_ms"],
           "received_at": iso(received), "status": PROCESSING, "result": None}
    try:
        await tenant.sync_receipts.insert_one(dict(doc))
        return {"claimed": doc}
    except DuplicateKeyError:
        pass
    prior = await tenant.sync_receipts.find_one(
        {"org_id": user["org_id"], "user_id": user["id"],
         "idempotency_key": env["idempotency_key"]}, {"_id": 0})
    if not prior:  # pragma: no cover — vanished between insert and read
        raise EnvelopeError("RETRY", "Опитайте отново")
    if prior.get("fingerprint") != fp:
        raise EnvelopeError("IDEMPOTENCY_KEY_REUSED", "Ключът вече е използван за друг запис")
    if prior.get("status") == RETRY:
        took = await tenant.sync_receipts.update_one(
            {"org_id": user["org_id"], "id": prior["id"], "status": RETRY},
            {"$set": {"status": PROCESSING, "received_at": iso(received), "result": None}})
        if took.modified_count == 1:
            return {"claimed": {**prior, "status": PROCESSING, "received_at": iso(received)}}
        return {"replay": {**prior, "status": PROCESSING}}
    if prior.get("status") == PROCESSING:
        started = datetime.fromisoformat(prior["received_at"])
        if received - started < PROCESSING_STALE:
            return {"replay": {**prior, "status": PROCESSING}}
        # a crashed request: take it over (compare-and-set on the stamp it left)
        took = await tenant.sync_receipts.update_one(
            {"org_id": user["org_id"], "id": prior["id"], "status": PROCESSING,
             "received_at": prior["received_at"]},
            {"$set": {"received_at": iso(received)}})
        if took.modified_count == 1:
            return {"claimed": {**prior, "received_at": iso(received)}}
        return {"replay": {**prior, "status": PROCESSING}}
    return {"replay": prior}


async def _finish(user: Dict[str, Any], receipt: Dict[str, Any], status: str,
                  result: Dict[str, Any]) -> Dict[str, Any]:
    await _tenant(user).sync_receipts.update_one(
        {"org_id": user["org_id"], "id": receipt["id"]},
        {"$set": {"status": status, "result": result, "finished_at": iso(now_utc())}})
    return _answer(receipt, status, result, replay=False)


def _answer(receipt: Dict[str, Any], status: str, result: Optional[Dict[str, Any]],
            replay: bool) -> Dict[str, Any]:
    return {"local_id": receipt["local_id"], "idempotency_key": receipt["idempotency_key"],
            "status": status, "result": result or {}, "replay": replay,
            "received_at": receipt.get("received_at"), "captured_at": receipt.get("captured_at")}


def _side_doc(user: Dict[str, Any], env: Dict[str, Any], device_id: str, received: datetime,
              **extra) -> Dict[str, Any]:
    return {"id": str(uuid.uuid4()), "org_id": user["org_id"], "status": "open",
            "op_type": env["op_type"], "local_id": env["local_id"],
            "idempotency_key": env["idempotency_key"], "device_id": device_id,
            "author_id": user["id"], "author_name": _user_name(user),
            "author_role": user.get("role"), "project_id": env.get("project_id"),
            "captured_at": env["captured_at"], "captured_tz": env["captured_tz"],
            "device_clock_offset_ms": env["device_clock_offset_ms"],
            "received_at": iso(received), "created_at": iso(received),
            "payload": env["payload"], "base_version": env.get("base_version"), **extra}


# ─────────────────────────────────────────────────────────────────── batch
def _retry_answer(raw: Any, receipt: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = receipt or (raw if isinstance(raw, dict) else {})
    return {"local_id": src.get("local_id"), "idempotency_key": src.get("idempotency_key"),
            "status": RETRY, "result": {"error_code": "SERVER_ERROR_RETRY",
                                        "message": "Временна грешка — ще се изпрати отново"},
            "replay": False}


async def process_item(user: Dict[str, Any], raw: Any, device_id: str, revoked: bool,
                       received: datetime, tz) -> Dict[str, Any]:
    """One item; AUDIT-2 PWA92-N1: an unexpected error stays with THIS item (retryable,
    a safe code, no internals), the rest of the batch goes on, never a 500 for the batch."""
    holder: Dict[str, Any] = {}
    try:
        return await _process_item(user, raw, device_id, revoked, received, tz, holder)
    except Exception:                                          # noqa: BLE001 — per-item isolation
        logger.exception("PWA-02 sync item failed (op=%s)",
                         (raw or {}).get("op_type") if isinstance(raw, dict) else None)
        receipt = holder.get("receipt")
        if receipt:
            try:
                await _tenant(user).sync_receipts.update_one(
                    {"org_id": user["org_id"], "id": receipt["id"], "status": PROCESSING},
                    {"$set": {"status": RETRY, "result": {"error_code": "SERVER_ERROR_RETRY"},
                              "finished_at": iso(now_utc())}})
            except Exception:                                  # noqa: BLE001 — stays processing → stale takeover
                logger.exception("PWA-02 could not mark the receipt retryable")
        return _retry_answer(raw, receipt)


async def _process_item(user: Dict[str, Any], raw: Any, device_id: str, revoked: bool,
                        received: datetime, tz, holder: Dict[str, Any]) -> Dict[str, Any]:
    try:
        env = validate_envelope(user, raw, device_id)
    except EnvelopeError as e:
        return {"local_id": (raw or {}).get("local_id") if isinstance(raw, dict) else None,
                "idempotency_key": (raw or {}).get("idempotency_key") if isinstance(raw, dict) else None,
                "status": REJECTED, "result": {"error_code": e.code, "message": e.message},
                "replay": False}
    try:
        claim = await _claim(user, env, device_id, received)
    except EnvelopeError as e:
        return {"local_id": env["local_id"], "idempotency_key": env["idempotency_key"],
                "status": REJECTED, "result": {"error_code": e.code, "message": e.message},
                "replay": False}
    if "replay" in claim:
        prior = claim["replay"]
        return _answer(prior, prior.get("status"), prior.get("result"), replay=True)
    receipt = claim["claimed"]
    holder["receipt"] = receipt
    tenant = _tenant(user)

    if revoked:  # R61-6: kept for the console, never official
        doc = _side_doc(user, env, device_id, received, reason="device_revoked")
        await tenant.sync_quarantine.insert_one(doc)
        await audit(user, action="sync.item_quarantined", entity_type="sync_quarantine",
                    entity_id=doc["id"], diff={"op_type": env["op_type"], "device_id": device_id},
                    reason="device_revoked", key=env["idempotency_key"])
        return await _finish(user, receipt, QUARANTINED, {"quarantine_id": doc["id"]})

    if is_online_only(env["op_type"]):
        return await _finish(user, receipt, REJECTED, {
            "error_code": "ONLINE_ONLY", "message": "Това изисква интернет"})
    handler = HANDLERS.get(env["op_type"])
    if handler is None:
        return await _finish(user, receipt, REJECTED, {
            "error_code": "UNSUPPORTED_OP", "message": "Този запис не може да се прави без интернет"})

    why_late = late_reason(env, received, tz)
    if why_late:
        doc = _side_doc(user, env, device_id, received, reason=why_late)
        await tenant.sync_late.insert_one(doc)
        await audit(user, action="sync.item_late", entity_type="sync_late", entity_id=doc["id"],
                    diff={"op_type": env["op_type"], "captured_at": env["captured_at"],
                          "received_at": iso(received)},
                    reason=why_late, key=env["idempotency_key"])
        return await _finish(user, receipt, LATE, {"late_id": doc["id"], "reason": why_late})

    ctx = {"device_id": device_id, "received_at": iso(received), "tz": tz,
           "captured_date": capture_day(env, received, tz)}
    try:
        result = await handler(user, env, ctx)
    except SyncConflict as c:
        doc = _side_doc(user, env, device_id, received, kind=c.kind, entity_type=c.entity_type,
                        entity_id=c.entity_id, office_version=c.office, field_version=c.field,
                        diff=diff_versions(c.office, c.field))
        await tenant.sync_conflicts.insert_one(doc)
        await audit(user, action="sync.item_conflict", entity_type=c.entity_type,
                    entity_id=c.entity_id, diff={"conflict_id": doc["id"], "kind": c.kind},
                    reason=None, key=env["idempotency_key"])
        return await _finish(user, receipt, CONFLICT, {"conflict_id": doc["id"], "kind": c.kind})
    except SyncRejected as r:
        return await _finish(user, receipt, REJECTED, {"error_code": r.code, "message": r.message})
    except SyncWaitingFile as w:
        await audit(user, action="sync.item_waiting_file", entity_type="sync_file",
                    entity_id=env["local_id"], diff={"op_type": env["op_type"], **w.result},
                    reason=None, key=env["idempotency_key"])
        return await _finish(user, receipt, WAITING_FILE, w.result)
    except HTTPException as h:
        detail = h.detail if isinstance(h.detail, dict) else {"message": str(h.detail)}
        return await _finish(user, receipt, REJECTED, {
            "error_code": detail.get("error_code") or "HTTP_%d" % h.status_code,
            "message": detail.get("message") or str(h.detail), "http_status": h.status_code})
    await audit(user, action="sync.item_synced", entity_type=result.get("entity_type") or env["op_type"],
                entity_id=str(result.get("entity_id") or env["local_id"]),
                diff={"op_type": env["op_type"], "device_id": device_id,
                      "captured_at": env["captured_at"], "received_at": iso(received)},
                reason=None, key=env["idempotency_key"])
    return await _finish(user, receipt, SYNCED, result)


async def process_batch(user: Dict[str, Any], device_id: str, items: Any) -> Dict[str, Any]:
    device_id = valid_device_id(device_id)
    if not isinstance(items, list) or not items:
        raise refuse(422, "BATCH_EMPTY", "Няма записи за изпращане")
    if len(items) > MAX_BATCH:
        raise refuse(413, "BATCH_TOO_LARGE", "Твърде много записи наведнъж", max=MAX_BATCH)
    device = await get_device(user, device_id)
    if not device:
        raise refuse(409, "DEVICE_NOT_REGISTERED", "Устройството не е регистрирано")
    revoked = bool(device.get("revoked_at"))
    received = now_utc()
    tz = await tenant_zone(user)
    results = [await process_item(user, item, device_id, revoked, received, tz) for item in items]
    if revoked:
        # R61-6: stop accepting; the phone wipes its local data on this answer.
        raise refuse(403, "DEVICE_REVOKED", "Устройството е блокирано", results=results)
    await _tenant(user).sync_devices.update_one(
        {"org_id": user["org_id"], "id": device_id},
        {"$set": {"last_sync_at": iso(received), "last_user_id": user["id"],
                  "last_user_name": _user_name(user)}})
    return {"server_time": iso(received), "results": results}


# ──────────────────────────────────────────────────────────────── console
async def console(user: Dict[str, Any]) -> Dict[str, Any]:
    """FLOW-037 §14 — a projection for Owner/Admin, never a second source of truth."""
    tenant = _tenant(user)
    org = user["org_id"]
    devices = await tenant.sync_devices.find({"org_id": org}, {"_id": 0}).sort(
        "last_seen_at", -1).to_list(500)
    proj = {"_id": 0}
    conflicts = await tenant.sync_conflicts.find({"org_id": org, "status": "open"}, proj).sort(
        "created_at", -1).to_list(200)
    late = await tenant.sync_late.find({"org_id": org, "status": "open"}, proj).sort(
        "created_at", -1).to_list(200)
    quarantine = await tenant.sync_quarantine.find({"org_id": org, "status": "open"}, proj).sort(
        "created_at", -1).to_list(200)
    since = iso(now_utc() - timedelta(days=30))
    pipeline = [{"$match": {"org_id": org, "received_at": {"$gte": since}}},
                {"$group": {"_id": {"device_id": "$device_id", "status": "$status"},
                            "n": {"$sum": 1}}}]
    per_device: Dict[str, Dict[str, int]] = {}
    async for row in tenant.sync_receipts.aggregate(pipeline):
        per_device.setdefault(row["_id"]["device_id"], {})[row["_id"]["status"]] = row["n"]
    for d in devices:
        d["receipts_30d"] = per_device.get(d["id"], {})
    return {"enabled": await is_enabled(user), "server_time": iso(now_utc()),
            "devices": devices, "conflicts": conflicts, "late": late, "quarantine": quarantine,
            "counts": {"devices": len(devices),
                       "revoked": sum(1 for d in devices if d.get("revoked_at")),
                       "conflicts": len(conflicts), "late": len(late),
                       "quarantine": len(quarantine)}}


async def my_receipts(user: Dict[str, Any], device_id: str) -> List[Dict[str, Any]]:
    """The phone asks what the server holds for its keys (e.g. after reinstalling)."""
    device_id = valid_device_id(device_id)
    rows = await _tenant(user).sync_receipts.find(
        {"org_id": user["org_id"], "user_id": user["id"], "device_id": device_id},
        {"_id": 0, "fingerprint": 0}).sort("received_at", -1).to_list(200)
    return rows


# ───────────────────────────────────────────── office decisions (Owner/Admin)
LATE_DECISIONS = ("confirm", "correct", "reject")
CONFLICT_DECISIONS = ("keep_office", "accept_field", "correct")
#: R61-4: an approved / paid / closed record is never edited directly.
CORRECTION_ONLY_KINDS = ("approved", "paid", "closed")


async def _settle_receipt(user: Dict[str, Any], doc: Dict[str, Any], status: str,
                          result: Dict[str, Any]) -> None:
    """The author's receipt follows the office decision, so the phone shows it."""
    await _tenant(user).sync_receipts.update_one(
        {"org_id": user["org_id"], "user_id": doc["author_id"],
         "idempotency_key": doc["idempotency_key"]},
        {"$set": {"status": status, "result": result, "settled_at": iso(now_utc()),
                  "settled_by": user["id"]}})


async def _author(user: Dict[str, Any], author_id: str) -> Dict[str, Any]:
    author = await _tenant(user).users.find_one({"org_id": user["org_id"], "id": author_id},
                                                {"_id": 0, "password_hash": 0})
    if not author:
        raise refuse(409, "AUTHOR_NOT_FOUND", "Авторът на записа не е намерен")
    return author


async def _claim_decision(user: Dict[str, Any], coll: str, item_id: str, key: str) -> Dict[str, Any]:
    """Compare-and-set open → deciding, so two people cannot decide the same item; the same
    Idempotency-Key again returns the decision already made."""
    tenant = _tenant(user)
    at = now_utc()
    claim = {"status": "deciding", "decision_key": key, "decided_by": user["id"], "deciding_at": iso(at)}
    doc = await tenant.collection(coll).find_one_and_update(
        {"org_id": user["org_id"], "id": item_id, "status": "open"},
        {"$set": claim}, projection={"_id": 0})
    if doc:
        return {"doc": doc}
    current = await tenant.collection(coll).find_one({"org_id": user["org_id"], "id": item_id},
                                                     {"_id": 0})
    if not current:
        raise refuse(404, "NOT_FOUND", "Няма такъв запис")
    if current.get("decision_key") == key and current.get("status") != "deciding":
        return {"replay": current}
    if current.get("status") == "deciding":
        # AUDIT-2: a decision that crashed half-way must not stay stuck — after the same
        # stale window as a receipt it may be taken over (compare-and-set on the stamp it left;
        # the domain handlers find what an earlier attempt already wrote by sync_local_id).
        since = current.get("deciding_at")
        stale = True
        if since:
            try:
                stale = at - datetime.fromisoformat(since) >= PROCESSING_STALE
            except ValueError:
                stale = True
        if stale:
            took = await tenant.collection(coll).find_one_and_update(
                {"org_id": user["org_id"], "id": item_id, "status": "deciding", "deciding_at": since},
                {"$set": claim}, projection={"_id": 0})
            if took:
                await audit(user, action="sync.decision_taken_over", entity_type=coll, entity_id=item_id,
                            diff={"previous_decided_by": current.get("decided_by"),
                                  "previous_deciding_at": since}, reason="stale", key="%s:takeover" % key)
                return {"doc": took}
    raise refuse(409, "ALREADY_DECIDED", "Записът вече е решен", current_status=current.get("status"))


async def _reopen(user: Dict[str, Any], coll: str, item_id: str) -> None:
    await _tenant(user).collection(coll).update_one(
        {"org_id": user["org_id"], "id": item_id, "status": "deciding"},
        {"$set": {"status": "open"}, "$unset": {"decision_key": "", "decided_by": "", "deciding_at": ""}})


def _env_of(doc: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    captured = datetime.fromisoformat(doc["captured_at"])
    return {"local_id": doc["local_id"], "idempotency_key": doc["idempotency_key"],
            "op_type": doc["op_type"], "captured_at": doc["captured_at"], "captured_dt": captured,
            "captured_tz": doc.get("captured_tz"), "device_clock_offset_ms": doc.get("device_clock_offset_ms", 0),
            "payload": payload, "base_version": doc.get("base_version"),
            "project_id": doc.get("project_id")}


async def decide_late(user: Dict[str, Any], late_id: str, decision: str, reason: str,
                      payload: Optional[Dict[str, Any]], key: str) -> Dict[str, Any]:
    """R61-3: Owner/Admin confirms, corrects or refuses a late record. Confirm/correct write
    through the domain with the CAPTURED date (the only path that may)."""
    if decision not in LATE_DECISIONS:
        raise refuse(422, "DECISION_INVALID", "Невалидно решение")
    if decision == "correct" and not isinstance(payload, dict):
        raise refuse(422, "CORRECTION_REQUIRED", "Липсва коригираният запис")
    claim = await _claim_decision(user, "sync_late", late_id, key)
    if "replay" in claim:
        return claim["replay"]
    doc = claim["doc"]
    tenant = _tenant(user)
    stamp = iso(now_utc())
    if decision == "reject":
        await tenant.sync_late.update_one(
            {"org_id": user["org_id"], "id": late_id},
            {"$set": {"status": "rejected", "decision": "reject", "reason": reason, "decided_at": stamp}})
        await _settle_receipt(user, doc, REJECTED, {"error_code": "LATE_REFUSED", "message": reason})
        await audit(user, action="sync.late_rejected", entity_type="sync_late", entity_id=late_id,
                    diff={"op_type": doc["op_type"], "author_id": doc["author_id"],
                          "captured_at": doc["captured_at"]}, reason=reason, key=key)
        return await tenant.sync_late.find_one({"org_id": user["org_id"], "id": late_id}, {"_id": 0})
    confirm = CONFIRM_HANDLERS.get(doc["op_type"])
    if confirm is None:
        await _reopen(user, "sync_late", late_id)
        raise refuse(409, "NO_CONFIRM_PATH", "Този тип запис не може да се потвърди")
    used = payload if decision == "correct" else doc["payload"]
    tz = await tenant_zone(user)
    env = _env_of(doc, used)
    ctx = {"confirmed_by": user["id"], "confirmed_at": stamp, "tz": tz,
           "captured_date": capture_day(env, datetime.fromisoformat(doc["received_at"]), tz)}
    try:
        author = await _author(user, doc["author_id"])
        result = await confirm(author, env, ctx)
    except SyncConflict as c:
        await _reopen(user, "sync_late", late_id)
        raise refuse(409, "LATE_CONFLICT", "Записът е в конфликт с офиса (%s)" % c.kind, kind=c.kind,
                     diff=diff_versions(c.office, c.field))
    except SyncWaitingFile as w:
        result = {**w.result, "waiting_file": True}
    except (SyncRejected, HTTPException) as e:
        await _reopen(user, "sync_late", late_id)
        if isinstance(e, HTTPException):
            raise
        raise refuse(e.http_status, e.code, e.message)
    except Exception:
        await _reopen(user, "sync_late", late_id)
        raise
    status = "corrected" if decision == "correct" else "confirmed"
    await tenant.sync_late.update_one(
        {"org_id": user["org_id"], "id": late_id},
        {"$set": {"status": status, "decision": decision, "reason": reason, "decided_at": stamp,
                  "result": result, **({"corrected_payload": payload} if decision == "correct" else {})}})
    await _settle_receipt(user, doc, WAITING_FILE if result.get("waiting_file") else SYNCED, result)
    await audit(user, action="sync.late_%s" % status, entity_type=result.get("entity_type") or "sync_late",
                entity_id=str(result.get("entity_id") or late_id),
                diff={"late_id": late_id, "op_type": doc["op_type"], "author_id": doc["author_id"],
                      "captured_at": doc["captured_at"], "received_at": doc["received_at"],
                      "before": doc["payload"], "after": used},
                reason=reason, key=key)
    return await tenant.sync_late.find_one({"org_id": user["org_id"], "id": late_id}, {"_id": 0})


#: op_type -> applier(user, conflict_doc, field_values) used when the office ACCEPTS the
#: phone's version of a record that is neither approved nor paid (CAS on ``version``).
APPLIERS: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {}


async def resolve_conflict(user: Dict[str, Any], conflict_id: str, decision: str, reason: str,
                           payload: Optional[Dict[str, Any]], key: str) -> Dict[str, Any]:
    """R61-2: the owner decides — keep the office version, accept the phone's, or correct.
    R61-4: approved / paid / closed → only a domain correction or reversal, never an edit."""
    if decision not in CONFLICT_DECISIONS:
        raise refuse(422, "DECISION_INVALID", "Невалидно решение")
    if decision == "correct" and not isinstance(payload, dict):
        raise refuse(422, "CORRECTION_REQUIRED", "Липсва коригираният запис")
    tenant = _tenant(user)
    pre = await tenant.sync_conflicts.find_one({"org_id": user["org_id"], "id": conflict_id}, {"_id": 0})
    if pre and pre.get("status") == "open" and decision != "keep_office" \
            and pre.get("kind") in CORRECTION_ONLY_KINDS:
        raise refuse(409, "CORRECTION_OR_REVERSAL_REQUIRED",
                     "Записът е одобрен/платен — промяна само чрез корекция или сторно", kind=pre["kind"])
    claim = await _claim_decision(user, "sync_conflicts", conflict_id, key)
    if "replay" in claim:
        return claim["replay"]
    doc = claim["doc"]
    stamp = iso(now_utc())
    if decision == "keep_office":
        # FG-657: "keep the office's" needs the office record to still exist (a voided one is
        # gone for every read) — otherwise the conflict stays open
        if doc.get("entity_type") == "attendance" and doc.get("kind") not in CORRECTION_ONLY_KINDS \
                and not await tenant.attendance_entries.find_one(
                    {"org_id": user["org_id"], "id": doc.get("entity_id")}, {"_id": 0, "id": 1}):
            await _reopen(user, "sync_conflicts", conflict_id)
            raise refuse(409, "RECORD_GONE", "Офисният запис вече не съществува (анулиран) — решете отново")
        result = {"error_code": "CONFLICT_KEPT_OFFICE", "message": reason}
        status = "kept_office"
        await _settle_receipt(user, doc, REJECTED, result)
    else:
        applier = APPLIERS.get(doc["op_type"])
        if applier is None:
            await _reopen(user, "sync_conflicts", conflict_id)
            raise refuse(409, "NO_APPLY_PATH", "Този тип конфликт се решава само с „Остави офисната“")
        values = payload if decision == "correct" else doc["field_version"]
        try:
            result = await applier(user, doc, values)
        except Exception:
            await _reopen(user, "sync_conflicts", conflict_id)
            raise
        status = "corrected" if decision == "correct" else "accepted_field"
        await _settle_receipt(user, doc, SYNCED, result)
    await tenant.sync_conflicts.update_one(
        {"org_id": user["org_id"], "id": conflict_id},
        {"$set": {"status": status, "decision": decision, "reason": reason, "decided_at": stamp,
                  "result": result, **({"corrected_payload": payload} if decision == "correct" else {})}})
    await audit(user, action="sync.conflict_%s" % status, entity_type=doc.get("entity_type") or "sync_conflict",
                entity_id=str(doc.get("entity_id") or conflict_id),
                diff={"conflict_id": conflict_id, "kind": doc.get("kind"), "office": doc.get("office_version"),
                      "phone": doc.get("field_version"), "applied": payload if decision == "correct"
                      else (doc.get("field_version") if decision == "accept_field" else None)},
                reason=reason, key=key)
    return await tenant.sync_conflicts.find_one({"org_id": user["org_id"], "id": conflict_id}, {"_id": 0})
