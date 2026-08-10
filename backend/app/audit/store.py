"""
W0-04 — Append-only AuditEvent store with per-tenant hash chain.

Iron rules (FLOW-040 §2, §8):
  - events are INSERTED, never updated, never deleted from application code;
  - a mistake in an old event is explained by a NEW correction / reversal /
    annotation event pointing at the original;
  - every event carries integrity_hash + previous_hash forming a per-tenant
    chain, so silent tampering or a missing event is detectable;
  - this module deliberately exports no update or delete helper.

Events live in the TENANT's own operational database (collection
`audit_events`), consistent with database-per-tenant (D-15) and the
per-tenant AuditEvent requirement of W0-01.

This module is additive: nothing existing is imported from it yet.
"""
import hashlib
import json
from typing import Dict, Any, Optional, List, Tuple

from app.audit.envelope import (
    build_event,
    validate_event,
    RETENTION_R1_CRITICAL_BUSINESS,
)

AUDIT_COLLECTION = "audit_events"
COUNTER_COLLECTION = "audit_counters"

# Fields excluded from the canonical hash: Mongo's own id and the
# integrity fields themselves.
_HASH_EXCLUDED = {"_id", "integrity_hash"}

GENESIS_HASH = "0" * 64


class AuditAppendOnlyViolation(RuntimeError):
    """Raised when code attempts to mutate an existing audit event."""


def canonical_hash(event: Dict[str, Any]) -> str:
    """
    Deterministic SHA-256 over the event's canonical JSON form.

    previous_hash IS included, which is what links the chain: changing any
    historical event changes its hash and breaks every later link.
    """
    payload = {k: v for k, v in event.items() if k not in _HASH_EXCLUDED}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def chain_hashes(event: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Pure function: return the event with sequence / previous_hash /
    integrity_hash filled in, given the previous event in the chain
    (None for the first event of a tenant).
    """
    chained = dict(event)
    if previous is None:
        chained["sequence"] = 1
        chained["previous_hash"] = GENESIS_HASH
    else:
        chained["sequence"] = int(previous["sequence"]) + 1
        chained["previous_hash"] = previous["integrity_hash"]
    chained["integrity_hash"] = canonical_hash(chained)
    return chained


def verify_chain(events: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """
    Verify an ordered list of one tenant's events.

    Returns (True, None) when intact, otherwise (False, reason).
    Detects: recomputed-hash mismatch (tampered content), broken links
    (deleted / reordered events) and sequence gaps (missing events).
    """
    expected_seq: Optional[int] = None
    previous_hash: Optional[str] = None
    for i, e in enumerate(events):
        seq = e.get("sequence")
        if i == 0:
            expected_seq = seq
            # A chain starting at sequence 1 must anchor on the genesis
            # hash. A suffix (archive verification) starts mid-chain and
            # its first link cannot be checked locally.
            previous_hash = GENESIS_HASH if seq == 1 else e.get("previous_hash")
        if seq != expected_seq:
            return False, f"sequence gap: expected {expected_seq}, found {seq}"
        if e.get("previous_hash") != previous_hash:
            return False, f"broken link at sequence {seq}"
        recomputed = canonical_hash(e)
        if recomputed != e.get("integrity_hash"):
            return False, f"hash mismatch at sequence {seq} (event tampered)"
        previous_hash = e["integrity_hash"]
        expected_seq = seq + 1
    return True, None


async def _last_event(db, tenant_id: str) -> Optional[Dict[str, Any]]:
    return await db[AUDIT_COLLECTION].find_one(
        {"tenant_id": tenant_id}, {"_id": 0}, sort=[("sequence", -1)]
    )


async def record_event(db, event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append one validated event to the tenant's audit chain.

    The event must come from build_event(). Returns the stored event
    including its sequence and hashes.
    """
    validate_event(event)
    previous = await _last_event(db, event["tenant_id"])
    chained = chain_hashes(event, previous)
    await db[AUDIT_COLLECTION].insert_one(dict(chained))
    chained.pop("_id", None)
    return chained


# ---------------------------------------------------------------------------
# Correction / reversal / annotation — the ONLY legal answers to a wrong
# event (FLOW-040 §2). Each is a new event referencing the original.
# ---------------------------------------------------------------------------

async def _record_linked(
    db,
    original: Dict[str, Any],
    *,
    action: str,
    actor_type: str,
    actor_id: str,
    reason: str,
    structured_diff: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not reason or not reason.strip():
        raise ValueError(f"{action} requires an explicit reason")
    event = build_event(
        tenant_id=original["tenant_id"],
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        source_flow=original.get("source_flow", "FLOW-040"),
        # A correction of an event inherits at least the original's
        # evidential weight; corrections are critical by default.
        retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="audit_event",
        entity_id=original["event_id"],
        reason=reason.strip(),
        structured_diff=structured_diff,
        correlation_id=original.get("correlation_id") or original["event_id"],
    )
    return await record_event(db, event)


async def record_correction(db, original, *, actor_type, actor_id, reason,
                            structured_diff=None) -> Dict[str, Any]:
    """A new event stating what the original SHOULD have said."""
    return await _record_linked(
        db, original, action="audit.correction", actor_type=actor_type,
        actor_id=actor_id, reason=reason, structured_diff=structured_diff,
    )


async def record_reversal(db, original, *, actor_type, actor_id, reason) -> Dict[str, Any]:
    """A new event stating the original action was undone."""
    return await _record_linked(
        db, original, action="audit.reversal", actor_type=actor_type,
        actor_id=actor_id, reason=reason,
    )


async def record_annotation(db, original, *, actor_type, actor_id, reason) -> Dict[str, Any]:
    """A new event adding context to the original, changing nothing."""
    return await _record_linked(
        db, original, action="audit.annotation", actor_type=actor_type,
        actor_id=actor_id, reason=reason,
    )


async def verify_tenant_chain(db, tenant_id: str) -> Tuple[bool, Optional[str]]:
    """Load and verify the full chain of one tenant from the database."""
    events = await db[AUDIT_COLLECTION].find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ).sort("sequence", 1).to_list(1_000_000)
    if not events:
        return True, None
    return verify_chain(events)
