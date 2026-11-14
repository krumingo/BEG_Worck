"""
W0-04 — Idempotency registry for consequential writes.

The problem this solves: a double click, a mobile retry after weak signal,
or a repeated webhook must NEVER create a second payment, a second Pay Run,
a second invoice (CLAUDE.md v15 §14: every consequential write carries an
idempotency key).

Contract for a write path:

    state = await begin_idempotent(db, tenant_id=..., key=..., action=...,
                                   request_fingerprint=fp)
    if state["status"] == IDEMPOTENCY_DUPLICATE:
        return state["result_reference"]        # replay: return, don't redo
    ... perform the write, record AuditEvent ...
    await complete_idempotent(db, tenant_id=..., key=..., action=...,
                              result_reference=...)

Same key + same action + DIFFERENT payload is a conflict, not a replay:
the caller sent two different requests under one key. That raises
IdempotencyConflict and must surface as an error, never guess.

Keys live per tenant in the tenant's own database (collection
`audit_idempotency`), reserved atomically via a unique index — two
concurrent requests with the same key cannot both win.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

IDEMPOTENCY_COLLECTION = "audit_idempotency"

IDEMPOTENCY_STARTED = "started"
IDEMPOTENCY_COMPLETED = "completed"
IDEMPOTENCY_FAILED = "failed"
IDEMPOTENCY_DUPLICATE = "duplicate"
# W0-04-C01 F-69-01 / RETAKE-1: the "detail" of a DUPLICATE result whose caller
# lost the FAILED -> STARTED retake to a concurrent retry that is performing the
# write right now. The top-level status stays DUPLICATE with prior_status
# STARTED, which every caller already refuses (409); callers that RESUME an
# interrupted STARTED attempt must check this detail and refuse instead.
IDEMPOTENCY_IN_PROGRESS = "in_progress"


class IdempotencyConflict(RuntimeError):
    """Same idempotency key reused for a different request payload.

    W0-04-C01 F-72-01: the message names the action only, with a typed ``code``
    and a diagnostic ``ref`` — never the raw key, the reservation id or the
    tenant, so it is safe in a log or a traceback.
    """

    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, action: str):
        self.ref = uuid.uuid4().hex[:12]
        self.action = action
        super().__init__("[%s ref=%s] the operation key for action '%s' was already used "
                         "with a different request payload" % (self.code, self.ref, action))


class IdempotencyUnprotected(RuntimeError):
    """audit_idempotency has no unique ``id`` index and it cannot be created.

    Without it two concurrent requests with one key can both insert their
    reservation and both perform the write (IDEM-IDX-1), so begin_idempotent
    refuses instead. Nothing is dropped or deleted; see
    scripts/w0_04_bootstrap_audit_indexes.py.
    """


IDEMPOTENCY_INDEX_KEYS = [("id", 1)]


async def ensure_idempotency_index(db) -> None:
    """Fail closed unless the reservation id is unique (W0-04-C01).

    Normally created at startup / onboarding; a database that missed both gets
    exactly the planned unique index before its first reservation.
    """
    from app.audit.indexes import require_unique_index
    await require_unique_index(db, IDEMPOTENCY_COLLECTION, IDEMPOTENCY_INDEX_KEYS,
                               IdempotencyUnprotected)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_fingerprint(payload: Any) -> str:
    """Stable fingerprint of a request body, used to tell replays apart
    from key-collisions with different content."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_id(tenant_id: str, action: str, key: str) -> str:
    return f"idem_{tenant_id}_{action}_{key}"


async def begin_idempotent(
    db,
    *,
    tenant_id: str,
    key: str,
    action: str,
    request_fingerprint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reserve an idempotency key, or report the existing reservation.

    Returns a dict with "status":
      - IDEMPOTENCY_STARTED   — key is new, caller must perform the write;
      - IDEMPOTENCY_DUPLICATE — key was seen before; "prior_status" tells
        whether the original completed, failed or is still running, and
        "result_reference" carries the original result when completed;
        when the key had FAILED and a concurrent retry won the retake, the
        DUPLICATE carries prior_status STARTED and detail
        IDEMPOTENCY_IN_PROGRESS: refuse (409), never resume, never write.

    Raises IdempotencyConflict when the key exists with a different
    request fingerprint.
    """
    if not key or not key.strip():
        raise ValueError("idempotency key must be non-empty")
    await ensure_idempotency_index(db)

    record = {
        "id": _record_id(tenant_id, action, key),
        "tenant_id": tenant_id,
        "action": action,
        "key": key,
        "request_fingerprint": request_fingerprint,
        "status": IDEMPOTENCY_STARTED,
        "result_reference": None,
        "error_code": None,
        "reserved_at": _now_iso(),
        "completed_at": None,
    }

    existing = await db[IDEMPOTENCY_COLLECTION].find_one({"id": record["id"]}, {"_id": 0})
    if existing is None:
        try:
            await db[IDEMPOTENCY_COLLECTION].insert_one(dict(record))
            record.pop("_id", None)
            return {"status": IDEMPOTENCY_STARTED, "record": record}
        except Exception as exc:  # duplicate-key race: someone else won
            if "duplicate" not in str(exc).lower() and type(exc).__name__ != "DuplicateKeyError":
                raise
            existing = await db[IDEMPOTENCY_COLLECTION].find_one(
                {"id": record["id"]}, {"_id": 0}
            )

    if (
        request_fingerprint is not None
        and existing.get("request_fingerprint") is not None
        and existing["request_fingerprint"] != request_fingerprint
    ):
        raise IdempotencyConflict(action)

    # A FAILED attempt may be retried under the same key: the reservation
    # returns to STARTED and the caller performs the write again.
    # F-69-01: the retake is a compare-and-set on status == FAILED that also
    # writes this attempt's token. Of N concurrent retries exactly one update
    # matches; the caller whose token is in the record afterwards is the single
    # winner. Every other caller gets DUPLICATE / prior_status STARTED with
    # detail IDEMPOTENCY_IN_PROGRESS and must refuse.
    if existing.get("status") == IDEMPOTENCY_FAILED:
        attempt_token = uuid.uuid4().hex
        await db[IDEMPOTENCY_COLLECTION].update_one(
            {"id": record["id"], "status": IDEMPOTENCY_FAILED},
            {"$set": {
                "status": IDEMPOTENCY_STARTED,
                "attempt_token": attempt_token,
                "reserved_at": _now_iso(),
                "completed_at": None,
                "error_code": None,
            }},
        )
        refreshed = await db[IDEMPOTENCY_COLLECTION].find_one({"id": record["id"]}, {"_id": 0})
        if refreshed is not None and refreshed.get("attempt_token") == attempt_token:
            return {"status": IDEMPOTENCY_STARTED, "record": refreshed, "retry_of_failed": True}
        existing = refreshed or existing
        if existing.get("status") in (IDEMPOTENCY_STARTED, IDEMPOTENCY_FAILED):
            # Lost the retake: another retry owns the write (or already failed
            # it again) — never a second writer.
            return {
                "status": IDEMPOTENCY_DUPLICATE,
                "prior_status": IDEMPOTENCY_STARTED,
                "detail": IDEMPOTENCY_IN_PROGRESS,
                "result_reference": None,
                "record": existing,
            }
        # The winner already completed: fall through to an ordinary replay.

    return {
        "status": IDEMPOTENCY_DUPLICATE,
        "prior_status": existing.get("status"),
        "result_reference": existing.get("result_reference"),
        "record": existing,
    }


async def mark_idempotent_step(
    db, *, tenant_id: str, key: str, action: str, step: str, reference: Optional[str] = None
) -> None:
    """Record that one step of a multi-step write has been performed.

    Bookkeeping for recoverable workflows (W0-02 PR-05): a retry of the same
    key reads `steps_done` and skips what already happened instead of
    performing it twice. `reference` (e.g. the id the step created) is kept
    under `step_refs.<step>` so the retry can address the same record.
    """
    update: Dict[str, Any] = {"$addToSet": {"steps_done": step}}
    if reference is not None:
        update["$set"] = {f"step_refs.{step}": reference}
    await db[IDEMPOTENCY_COLLECTION].update_one(
        {"id": _record_id(tenant_id, action, key)}, update)


async def complete_idempotent(
    db, *, tenant_id: str, key: str, action: str, result_reference: str
) -> None:
    """Mark a reserved key as successfully completed.

    Note: this updates the idempotency REGISTRY, which is bookkeeping —
    the append-only rule protects audit_events, not this collection.
    """
    await db[IDEMPOTENCY_COLLECTION].update_one(
        {"id": _record_id(tenant_id, action, key), "status": IDEMPOTENCY_STARTED},
        {"$set": {
            "status": IDEMPOTENCY_COMPLETED,
            "result_reference": result_reference,
            "completed_at": _now_iso(),
        }},
    )


async def fail_idempotent(
    db, *, tenant_id: str, key: str, action: str, error_code: str
) -> None:
    """Mark a reserved key as failed.

    A failed attempt stays recorded (error_code + timestamp). The next
    begin_idempotent() with the same key and fingerprint re-opens the
    reservation (status returns to STARTED), so a clean retry is possible
    while a completed write can never run twice.
    """
    await db[IDEMPOTENCY_COLLECTION].update_one(
        {"id": _record_id(tenant_id, action, key)},
        {"$set": {
            "status": IDEMPOTENCY_FAILED,
            "error_code": error_code,
            "completed_at": _now_iso(),
        }},
    )


# ── F-73-01 (Codex, R29): the key reserved and completed IN the caller's transaction ─────
# A write that must be exactly-once together with its key (the key record and the business
# write commit or roll back together) reserves the key with ``session``, does its write,
# and completes the key with the SAME ``session``. Outside a transaction (session None) a
# failed write marks the key failed, so a clean retry may run it again.
IDEMPOTENCY_REPLAY = "replay"


class IdempotencyInProgress(Exception):
    """The key is STARTED by an attempt that has not finished (only seen outside a
    transaction — inside one an unfinished attempt is invisible)."""


async def peek_idempotent(db, *, tenant_id: str, key: str, action: str,
                          request_fingerprint: Optional[str]) -> Optional[Dict[str, Any]]:
    """Read-only look-up before any write: None (unknown key), or the record. Raises
    IdempotencyConflict when the key exists with another request fingerprint."""
    rec = await db[IDEMPOTENCY_COLLECTION].find_one(
        {"tenant_id": tenant_id, "id": _record_id(tenant_id, action, key)}, {"_id": 0})
    if rec is not None and rec.get("request_fingerprint") != request_fingerprint:
        raise IdempotencyConflict(f"Idempotency key '{key}' for action '{action}' was already used "
                                  "with a different request payload")
    return rec


async def reserve_idempotent_in_session(db, *, tenant_id: str, key: str, action: str,
                                        request_fingerprint: Optional[str], session) -> Dict[str, Any]:
    """In the caller's transaction: {"status": STARTED} (the caller performs the write) or
    {"status": REPLAY, "result_reference"} (completed before — return it, write nothing).
    Raises IdempotencyConflict (another payload) or IdempotencyInProgress."""
    if not key or not key.strip():
        raise ValueError("idempotency key must be non-empty")
    rid = _record_id(tenant_id, action, key)
    flt = {"tenant_id": tenant_id, "id": rid}
    rec = await db[IDEMPOTENCY_COLLECTION].find_one(flt, {"_id": 0}, session=session)
    if rec is not None and rec.get("request_fingerprint") != request_fingerprint:
        raise IdempotencyConflict(f"Idempotency key '{key}' for action '{action}' was already used "
                                  "with a different request payload")
    if rec is not None and rec.get("status") == IDEMPOTENCY_COMPLETED:
        return {"status": IDEMPOTENCY_REPLAY, "result_reference": rec.get("result_reference")}
    if rec is not None and rec.get("status") == IDEMPOTENCY_STARTED:
        raise IdempotencyInProgress(key)
    now = _now_iso()
    if rec is None:
        await db[IDEMPOTENCY_COLLECTION].insert_one({
            "id": rid, "tenant_id": tenant_id, "action": action, "key": key,
            "request_fingerprint": request_fingerprint, "status": IDEMPOTENCY_STARTED,
            "result_reference": None, "error_code": None, "reserved_at": now, "completed_at": None},
            session=session)
    else:                                                   # a FAILED attempt: a clean retry
        await db[IDEMPOTENCY_COLLECTION].update_one(
            {**flt, "status": IDEMPOTENCY_FAILED},
            {"$set": {"status": IDEMPOTENCY_STARTED, "reserved_at": now, "error_code": None,
                      "completed_at": None}}, session=session)
    return {"status": IDEMPOTENCY_STARTED}


async def complete_idempotent_in_session(db, *, tenant_id: str, key: str, action: str,
                                         result_reference: str, session) -> None:
    """Complete the key in the SAME transaction as the write it guards."""
    await db[IDEMPOTENCY_COLLECTION].update_one(
        {"tenant_id": tenant_id, "id": _record_id(tenant_id, action, key), "status": IDEMPOTENCY_STARTED},
        {"$set": {"status": IDEMPOTENCY_COMPLETED, "result_reference": result_reference,
                  "completed_at": _now_iso()}}, session=session)
