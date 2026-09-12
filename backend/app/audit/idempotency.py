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
from datetime import datetime, timezone
from typing import Dict, Any, Optional

IDEMPOTENCY_COLLECTION = "audit_idempotency"

IDEMPOTENCY_STARTED = "started"
IDEMPOTENCY_COMPLETED = "completed"
IDEMPOTENCY_FAILED = "failed"
IDEMPOTENCY_DUPLICATE = "duplicate"


class IdempotencyConflict(RuntimeError):
    """Same idempotency key reused for a different request payload."""


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
        "result_reference" carries the original result when completed.

    Raises IdempotencyConflict when the key exists with a different
    request fingerprint.
    """
    if not key or not key.strip():
        raise ValueError("idempotency key must be non-empty")

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
        raise IdempotencyConflict(
            f"Idempotency key '{key}' for action '{action}' was already used "
            "with a different request payload"
        )

    # A FAILED attempt may be retried under the same key: the reservation
    # returns to STARTED and the caller performs the write again.
    if existing.get("status") == IDEMPOTENCY_FAILED:
        await db[IDEMPOTENCY_COLLECTION].update_one(
            {"id": record["id"], "status": IDEMPOTENCY_FAILED},
            {"$set": {
                "status": IDEMPOTENCY_STARTED,
                "reserved_at": _now_iso(),
                "completed_at": None,
                "error_code": None,
            }},
        )
        refreshed = await db[IDEMPOTENCY_COLLECTION].find_one({"id": record["id"]}, {"_id": 0})
        return {"status": IDEMPOTENCY_STARTED, "record": refreshed, "retry_of_failed": True}

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
