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
import asyncio
import hashlib
import json
import random
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


#: How many times one append may lose the race for its chain slot before it
#: gives up. Every lost round means another writer of the SAME tenant won a
#: slot, so N concurrent writers need at most N rounds; the bound only stops a
#: pathological loop from spinning forever.
MAX_APPEND_ATTEMPTS = 64


class AuditChainContention(RuntimeError):
    """An append could not win a chain slot within MAX_APPEND_ATTEMPTS."""


def chain_slot_id(tenant_id: str, sequence: int) -> str:
    """The primary key of the event at ``sequence`` in ``tenant_id``'s chain.

    W0-06B (W0-06A review finding 1). Two writers of one tenant that read the
    same predecessor compute the same next sequence; with a random ``_id`` both
    inserts succeeded and the chain forked into ``[1, 1, 2, 3]``. Making the
    slot itself the primary key turns that race into a duplicate-key refusal
    on MongoDB's built-in, always-present ``_id`` index — no optional index has
    to exist for the guarantee to hold. The length prefix keeps the key
    unambiguous for any tenant id, so two tenants can never share a slot.
    ``_id`` is excluded from the canonical hash, so the chain format is
    unchanged.
    """
    return "ae:%d:%s:%d" % (len(tenant_id), tenant_id, int(sequence))


def _is_duplicate_key(exc: BaseException) -> bool:
    return type(exc).__name__ == "DuplicateKeyError" or getattr(exc, "code", None) == 11000


async def _last_event(db, tenant_id: str) -> Optional[Dict[str, Any]]:
    return await db[AUDIT_COLLECTION].find_one(
        {"tenant_id": tenant_id}, {"_id": 0}, sort=[("sequence", -1)]
    )


async def record_event(db, event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append one validated event to the tenant's audit chain.

    The event must come from build_event(). Returns the stored event
    including its sequence and hashes.

    Concurrency (W0-06B). The append is optimistic: read the chain head,
    chain onto it, and insert into the slot :func:`chain_slot_id` names. A
    writer that lost the slot to a concurrent writer of the same tenant wrote
    NOTHING (the insert was refused), so it re-reads the new head and chains
    onto that. The chain therefore never forks and never has a gap, and the
    append-only rule holds: no event is ever rewritten or removed to resolve a
    race. Tenants never contend with each other — their slots differ.
    """
    validate_event(event)
    for attempt in range(MAX_APPEND_ATTEMPTS):
        previous = await _last_event(db, event["tenant_id"])
        chained = chain_hashes(event, previous)
        doc = dict(chained)
        doc["_id"] = chain_slot_id(event["tenant_id"], chained["sequence"])
        try:
            await db[AUDIT_COLLECTION].insert_one(doc)
        except Exception as exc:  # noqa: BLE001 — only a lost slot is retried
            if not _is_duplicate_key(exc):
                raise
            # Lost the slot. Back off a little (jittered, bounded) so N writers
            # do not re-read the same head in lock-step, then chain again.
            await asyncio.sleep(random.uniform(0, 0.002 * min(attempt + 1, 10)))
            continue
        chained.pop("_id", None)
        return chained
    raise AuditChainContention(
        "could not append to the audit chain of tenant %r after %d attempts"
        % (event["tenant_id"], MAX_APPEND_ATTEMPTS))


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
