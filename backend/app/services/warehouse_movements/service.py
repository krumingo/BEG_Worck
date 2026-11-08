"""
ONE canonical warehouse movement command service.

This module is the ONLY writer to `warehouse_transactions` in the TASK 5C
world. Every physical fact passes through `execute()` and lands as a
single append-only row inside one Mongo replica-set transaction that
also covers idempotency, projection, and the AuditEvent chain.

Contract: v6 §4.3 "Atomicity, concurrency, and idempotency".

CODEX correction package C01–C10:
  * C01: no `LEGACY_WAREHOUSE_WRITERS_ENABLED` escape hatch (removed in
         `legacy_inventory.py`); every write path is this service only.
  * C03: Rule B / F-09 — dispatch costs nothing, acceptance costs the
         accepted qty only using server-derived proportional FIFO from
         the dispatch's recorded layers; multiple partial acceptances
         are permitted; unresolved remainder stays `in_transit/unresolved`.
  * C04: transfer dispatch creates traced in-transit remainder (no
         destination credit); acceptance opens destination layers at the
         same traced values. Project → warehouse returns land in
         quarantine first.
  * C05: `begin_idempotent` / `complete_idempotent` / `record_event` are
         all **session-aware** here. Transient transaction / audit
         sequence collisions get a bounded retry.
  * C06: permission is evaluated for every affected scope (source +
         destination + project); confirmer, pending-mapping and
         canonical identity are server-derived from storage, not from
         the request body.
  * C07: `warehouse_in_transit` is a disposable projection only; the
         acceptance invariant checks the LEDGER, never the projection.
  * C09: FIFO reads are ordered by `ledger_sequence` with a stable
         tie-break, not wall-clock `recorded_at`. Missing allocations
         fail closed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from app.audit.envelope import (
    build_event,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RETENTION_R1_CRITICAL_BUSINESS,
    ACTOR_HUMAN,
)
from app.audit.idempotency import (
    IdempotencyConflict,
    IDEMPOTENCY_COLLECTION,
    IDEMPOTENCY_COMPLETED,
    IDEMPOTENCY_DUPLICATE,
    IDEMPOTENCY_FAILED,
    IDEMPOTENCY_STARTED,
    _record_id as _idempotency_record_id,
    request_fingerprint,
)

from app.services.warehouse_movements.actions import (
    CanonicalAction,
    OUTBOUND_ACTIONS,
    INBOUND_ACTIONS,
    QUARANTINE_ACTIONS,
    EVIDENCE_REQUIRED_ACTIONS,
    permission_action_for,
    RULE_B_COSTING_ACTIONS,
    RULE_B_ZERO_COST_ACTIONS,
    REVERSAL_ACTIONS,
    REVERSAL_OF,
)
from app.services.warehouse_movements.envelope import (
    MovementEnvelope,
    LocationKey,
    LocationType,
    MovementState,
    build_envelope,
    envelope_fingerprint,
    validate_envelope,
    LayerAllocation,
)
from app.services.warehouse_movements.errors import (
    AuditChainWriteError,
    FileRegistryUnavailableError,
    FreeTextIntoActionableStockError,
    IdempotencyConflictError,
    IndexMissingError,
    InvariantViolationError,
    LegacyWriterRetiredError,
    MasterIdentityMissingError,
    NegativeStockError,
    OriginAcceptanceOverrunError,
    PermissionDeniedError,
    QuarantineStateViolationError,
    TransactionsNotSupportedError,
    UnknownActionError,
    ValueFromClientRefusedError,
    WarehouseMovementError,
)
from app.services.warehouse_movements.fifo import (
    allocate_outbound,
)
from app.services.warehouse_movements.indexes import (
    verify_required_indexes,
    MOVEMENTS_COLLECTION,
)

logger = logging.getLogger("warehouse.canonical")

# Transient / retryable errors — Mongo raises these when a write conflict
# aborts a tx. The service retries the whole transaction a bounded number
# of times before giving up (contract §4.3).
_MAX_RETRIES = 5


_SEQUENCE_INDEX_NAMES = {
    "wh_movements_unique_sequence",
    "wh_audit_unique_sequence",
    "wh_movements_unique_acceptance_line",
    "wh_movements_unique_movement_id",
    "wh_audit_unique_event_id",
    "wh_movements_unique_supplier_origin",
}


def _is_sequence_duplicate_error(exc: Exception) -> bool:
    """True iff `exc` is a Mongo duplicate-key error on a sequence-ish
    index that two concurrent writers would both allocate (read-max+1)."""
    name = type(exc).__name__
    if name not in {"DuplicateKeyError", "WriteError", "WriteFailure", "OperationFailure"}:
        return False
    msg = str(exc)
    if "duplicate key" not in msg.lower() and "E11000" not in msg:
        return False
    return any(idx in msg for idx in _SEQUENCE_INDEX_NAMES)


# -----------------------------------------------------------------------
# Public types
# -----------------------------------------------------------------------
@dataclass
class ExecuteResult:
    movement_id: str
    envelope: Dict[str, Any]
    audit_event_id: str
    idempotency_status: str
    replay: bool = False
    # When an acceptance generated an unresolved transit_discrepancy row,
    # its movement_id is reported so UI can surface the remainder.
    unresolved_discrepancy_movement_id: Optional[str] = None


@dataclass
class CommandInput:
    """Caller-supplied, server-validated inputs.

    No server-controlled fields are accepted here: `confirmed_by`,
    `confirmed_at`, `item_is_pending_mapping`, `unit_value` on outbound,
    `layer_allocations`, `ledger_sequence`, and `acceptance_line_id` are
    derived by the service from storage.

    C06: client cannot set confirmer / pending-mapping / layer values.
    """
    action: CanonicalAction
    tenant_id: str
    actor_id: str
    item_id: str
    unit: str
    quantity: Any
    source: Optional[LocationKey] = None
    destination: Optional[LocationKey] = None
    idempotency_key: str = ""
    # Supplier purchase price per unit — only honored for RECEIVE_*
    # actions; refused for every outbound action.
    unit_value: Any = Decimal("0")
    currency: str = "BGN"
    lot_id: Optional[str] = None
    request_id: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_line_id: Optional[str] = None
    delivery_id: Optional[str] = None
    # Dispatch linkage (acceptance) — points at a prior dispatch movement
    # or a canonical supplier_delivery_origin line.
    dispatch_movement_id: Optional[str] = None
    reservation_movement_id: Optional[str] = None
    project_id: Optional[str] = None
    subproject_id: Optional[str] = None
    smr_id: Optional[str] = None
    work_package_id: Optional[str] = None
    correlation_id: Optional[str] = None
    requested_quantity: Any = None
    accepted_quantity: Any = None
    file_ids: Optional[List[str]] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    corrects_movement_id: Optional[str] = None
    revision_evidence: Optional[Dict[str, Any]] = None
    occurred_at: Optional[str] = None
    # WH-REV-01 — the supplier receipt a reverse_supplier_receipt[_to_project]
    # reverses (everything else of the reversal is derived from that row).
    reverses_movement_id: Optional[str] = None
    # 5C-C21 F-13 (Р11) — the warehouse a TRANSFER_WAREHOUSE_TO_WAREHOUSE
    # is FOR. The transfer itself goes to in_transit; this warehouse is
    # credited only by an ACCEPT_PROJECT_DELIVERY against the transfer.
    transfer_target: Optional[LocationKey] = None


async def resolve_subproject_parent(tenant_db, org_id: str, subproject_id: str) -> str:
    """5C-C26d (FG-38) — the parent project of a subproject of THIS tenant
    (``projects.parent_project_id``). Unknown subproject, a top-level
    project, or a parent that is not a project of the tenant → 422."""
    from app.tenancy.data_access import TenantData
    tenant = TenantData.for_resolved_org(tenant_db, org_id)
    sub = await tenant.projects.find_one(
        {"id": subproject_id}, {"_id": 0, "id": 1, "parent_project_id": 1})
    parent = (sub or {}).get("parent_project_id")
    if not parent:
        raise InvariantViolationError(
            "unknown subproject (no parent project in this tenant)",
            context={"subproject_id": subproject_id})
    if not await tenant.projects.find_one({"id": parent}, {"_id": 0, "id": 1}):
        raise InvariantViolationError(
            "the subproject's parent is not a project of this tenant",
            context={"subproject_id": subproject_id})
    return parent


# -----------------------------------------------------------------------
# Permission adapter
# -----------------------------------------------------------------------
class PermissionGate:
    """Thin wrapper over the Permission Service that fails CLOSED.

    C06 — a transfer authorizes both the SOURCE and DESTINATION scopes.
    A caller permitted at only one end cannot move stock through the
    other.
    """

    def __init__(self, evaluate_fn=None, assignments_loader=None):
        from app.permissions.service import evaluate_permission
        self._evaluate = evaluate_fn or evaluate_permission
        # 5C-C26 Addendum A (Р27) — a write-off FROM A PROJECT is decided by
        # the Р27 role × membership table (write_off_policy), not by the
        # generic action grant. Production (no injected evaluator) always
        # applies Р27; a test gate with an injected evaluator applies it only
        # when it also injects the assignments loader.
        self._r27 = evaluate_fn is None or assignments_loader is not None
        self._assignments_loader = assignments_loader

    async def ensure_project_write_off(self, ctx, tenant_db, *, org_id: str,
                                       project_id: str) -> None:
        """Р27 (Крум 06.11.2026, FG-21) — who may write off from a project."""
        if not self._r27:
            return await self.ensure(
                ctx, action=CanonicalAction.WRITE_OFF, source=None,
                destination=None, project_id=project_id)
        from app.services.warehouse_movements.write_off_policy import (
            ensure_project_write_off,
        )
        await ensure_project_write_off(
            ctx, tenant_db, org_id=org_id, project_id=project_id,
            load_assignments=self._assignments_loader)

    async def ensure(
        self,
        ctx,
        *,
        action: CanonicalAction,
        source: Optional[LocationKey],
        destination: Optional[LocationKey],
        project_id: Optional[str],
    ) -> None:
        if ctx is None:
            raise PermissionDeniedError(
                "missing tenant context",
                context={"action": action.value},
            )
        permission_name = permission_action_for(action)
        scopes = self._affected_scopes(
            action=action, source=source, destination=destination,
            project_id=project_id,
        )
        if not scopes:
            # Reservation / release have no physical destination; fall
            # back to module-wide so the action is still evaluated.
            scopes = [(None, None)]
        for scope_type, scope_id in scopes:
            decision = await self._evaluate(
                ctx, permission_name, module="warehouse",
                scope_type=scope_type, scope_id=scope_id,
            )
            if not decision.allowed:
                raise PermissionDeniedError(
                    f"permission denied for {permission_name}",
                    context={"action": action.value,
                             "reason_code": getattr(decision, "reason_code", "DENY"),
                             "scope_type": scope_type, "scope_id": scope_id},
                )

    @staticmethod
    def _affected_scopes(
        *, action: CanonicalAction,
        source: Optional[LocationKey],
        destination: Optional[LocationKey],
        project_id: Optional[str],
    ) -> List:
        scopes: List = []
        # Project scope first when a project is in play (acceptance,
        # consume, project-side transfer).
        if project_id:
            scopes.append(("project", project_id))
        # Then physical origin + destination scopes. In-transit and
        # supplier states carry an inherently global id — they do not
        # add their own scope.
        for key in (source, destination):
            if key is None:
                continue
            if key.location_type in {LocationType.IN_TRANSIT,
                                     LocationType.UNRESOLVED,
                                     LocationType.SUPPLIER}:
                continue
            scopes.append(("location", key.location_id))
        # Deduplicate while preserving order so the strictest set runs.
        seen = set()
        unique = []
        for s in scopes:
            if s not in seen:
                unique.append(s)
                seen.add(s)
        return unique


# -----------------------------------------------------------------------
# Capability sentinels — fail-closed when W0 prerequisites are missing
# -----------------------------------------------------------------------
def file_registry_available() -> bool:
    return os.environ.get("FILE_REGISTRY_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def permission_mode_of(ctx) -> str:
    """The Permission Service mode of THIS operation: the one the route's
    dependency fixed on the context (PR-05), else the environment."""
    mode = getattr(ctx, "mode", None)
    if mode in ("off", "shadow", "enforce"):
        return mode
    from app.permissions.deps import current_mode
    return current_mode()


def permission_service_enforce() -> bool:
    return os.environ.get("PERMISSION_SERVICE_MODE", "").strip().lower() == "enforce"


# -----------------------------------------------------------------------
# Session-aware helpers (CODEX C05)
# -----------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _idem_begin_with_session(
    db, *, tenant_id: str, key: str, action: str,
    fingerprint: str, session,
) -> Dict[str, Any]:
    """Session-aware idempotency reservation.

    Mirrors `app.audit.idempotency.begin_idempotent` but routes every
    Mongo call through `session=session` so the reservation is part of
    the same transaction as the business write. A rollback drops the
    reservation.
    """
    if not key or not key.strip():
        raise ValueError("idempotency key must be non-empty")
    record_id = _idempotency_record_id(tenant_id, action, key)
    existing = await db[IDEMPOTENCY_COLLECTION].find_one(
        {"id": record_id, "tenant_id": tenant_id}, {"_id": 0}, session=session,
    )
    if existing is None:
        record = {
            "id": record_id,
            "tenant_id": tenant_id,
            "action": action,
            "key": key,
            "request_fingerprint": fingerprint,
            "status": IDEMPOTENCY_STARTED,
            "result_reference": None,
            "error_code": None,
            "reserved_at": _now_iso(),
            "completed_at": None,
        }
        try:
            await db[IDEMPOTENCY_COLLECTION].insert_one(dict(record), session=session)
            return {"status": IDEMPOTENCY_STARTED, "record": record}
        except Exception as exc:
            # Duplicate-key race from another concurrent transaction.
            if "duplicate" not in str(exc).lower() and type(exc).__name__ != "DuplicateKeyError":
                raise
            existing = await db[IDEMPOTENCY_COLLECTION].find_one(
                {"id": record_id, "tenant_id": tenant_id}, {"_id": 0}, session=session,
            )

    if (
        fingerprint is not None
        and existing.get("request_fingerprint") is not None
        and existing["request_fingerprint"] != fingerprint
    ):
        raise IdempotencyConflict(
            f"Idempotency key '{key}' for action '{action}' was already used "
            "with a different request payload"
        )

    if existing.get("status") == IDEMPOTENCY_FAILED:
        # Clean retry — reopen the reservation.
        await db[IDEMPOTENCY_COLLECTION].update_one(
            {"id": record_id, "tenant_id": tenant_id, "status": IDEMPOTENCY_FAILED},
            {"$set": {"status": IDEMPOTENCY_STARTED,
                      "reserved_at": _now_iso(),
                      "completed_at": None,
                      "error_code": None}},
            session=session,
        )
        refreshed = await db[IDEMPOTENCY_COLLECTION].find_one(
            {"id": record_id, "tenant_id": tenant_id}, {"_id": 0}, session=session,
        )
        return {"status": IDEMPOTENCY_STARTED, "record": refreshed,
                "retry_of_failed": True}

    return {
        "status": IDEMPOTENCY_DUPLICATE,
        "prior_status": existing.get("status"),
        "result_reference": existing.get("result_reference"),
        "record": existing,
    }


async def _idem_complete_with_session(
    db, *, tenant_id: str, key: str, action: str,
    result_reference: str, session,
) -> None:
    await db[IDEMPOTENCY_COLLECTION].update_one(
        {"id": _idempotency_record_id(tenant_id, action, key),
         "tenant_id": tenant_id,
         "status": IDEMPOTENCY_STARTED},
        {"$set": {
            "status": IDEMPOTENCY_COMPLETED,
            "result_reference": result_reference,
            "completed_at": _now_iso(),
        }},
        session=session,
    )


async def _record_event_in_session(tenant_db, event, *, session):
    """Append an AuditEvent inside the business transaction.

    CODEX C13.1 — audit sequence + hash chain are serialized through
    the per-tenant **chain-head CAS** on `audit_chain_head`. The
    atomic counter alone (C12.3) was not enough: a hash chain cannot
    be built in parallel because each event's `previous_hash` depends
    on the previous event's hash, and two concurrent writers that
    each read the tail at `seq=N-1` would both chain against `H_{N-1}`
    and produce a forked chain even though their counter values
    (seq=N and seq=N+1) differ.

    The new mechanism uses one pivot document per tenant:

        {tenant_id, sequence, integrity_hash, last_event_id,
         last_updated_at}

    Each write:
      1. Reads the current head inside the session (snapshot
         isolation — one consistent view of the chain's tail).
      2. Computes `sequence = head.sequence + 1` and
         `previous_hash = head.integrity_hash`.
      3. Inserts the new event with that sequence/previous_hash.
      4. CAS-updates the head to `(new_seq, new_hash)` iff the head is
         still at `(old_seq, old_hash)`. On replica-set transactions
         Mongo serializes updates to this single document; a
         conflicting update raises Mongo code 112 `WriteConflict`,
         which `session.with_transaction(...)` retries automatically
         with full business-op rollback — no partial state remains.

    The first write per tenant has no head yet. It inserts the head
    row atomically; a concurrent "first write" loses the insert on
    the unique `(tenant_id,)` index and is retried as above.
    """
    from app.audit.envelope import validate_event
    from app.audit.store import AUDIT_COLLECTION, chain_hashes, canonical_hash
    validate_event(event)

    # 5C-C18: `audit_chain_head` is a tenant_id-keyed audit store
    # (ownership.TENANT_ID_KEYED, next to audit_events/audit_counters);
    # every call names it directly with a literal `tenant_id` predicate.
    tenant_id = event["tenant_id"]

    # 1. Snapshot the chain head inside this session.
    head = await tenant_db["audit_chain_head"].find_one(
        {"tenant_id": tenant_id}, session=session,
    )
    if head is None:
        prev_sequence = 0
        prev_hash = None
    else:
        prev_sequence = int(head.get("sequence", 0))
        prev_hash = head.get("integrity_hash")

    # 5C-C19 F-1 — ONE append-only AuditEvent sequence per tenant
    # (CLAUDE.md §2.8). `audit_events` is shared with the W0-04 writer
    # (`app.audit.store.record_event`: permission grants, master data,
    # auth, ...), which appends after its own last event and never
    # touches `audit_chain_head`. The head is therefore only the CAS
    # pivot that serializes canonical writers; the true predecessor is
    # the tenant's last stored event. Continue from whichever is
    # further along (normally the tail), never from a fresh sequence 1
    # and never as a second chain.
    tail = await tenant_db[AUDIT_COLLECTION].find_one(
        {"tenant_id": tenant_id},
        {"_id": 0, "sequence": 1, "integrity_hash": 1},
        sort=[("sequence", -1)],
        session=session,
    )
    if tail is not None and int(tail.get("sequence") or 0) >= prev_sequence:
        chain_sequence = int(tail.get("sequence") or 0)
        chain_hash = tail.get("integrity_hash")
    else:
        chain_sequence = prev_sequence
        chain_hash = prev_hash
    # chain_hashes needs a minimal "previous event" shape.
    prev_event = (
        None if chain_sequence == 0
        else {"sequence": chain_sequence, "integrity_hash": chain_hash}
    )

    new_sequence = chain_sequence + 1

    # 2. Compute the chained envelope.
    chained = chain_hashes(event, prev_event)
    chained["sequence"] = new_sequence
    chained["integrity_hash"] = canonical_hash(chained)

    # 3. Append the event inside the business tx.
    await tenant_db[AUDIT_COLLECTION].insert_one(dict(chained), session=session)

    # 4. CAS the chain head. One of three paths:
    #    a) head existed → `update_one` with the exact (seq, hash)
    #       filter: Mongo serializes concurrent updates to this one
    #       document, and a concurrent writer that already advanced
    #       the head will cause this update to WriteConflict (code
    #       112) → `with_transaction` retries the whole operation.
    #    b) head did not exist → `insert_one` with upsert semantics.
    #       A concurrent first-write loses on the unique index and
    #       is retried the same way.
    new_head_doc = {
        "sequence": new_sequence,
        "integrity_hash": chained["integrity_hash"],
        "last_event_id": chained.get("event_id"),
        "last_updated_at": chained.get("recorded_at"),
    }
    if head is None:
        try:
            await tenant_db["audit_chain_head"].insert_one(
                {"tenant_id": tenant_id, **new_head_doc},
                session=session,
            )
        except Exception as exc:  # DuplicateKey + WriteConflict both retry
            # Re-raise so with_transaction retries from the top.
            raise
    else:
        res = await tenant_db["audit_chain_head"].update_one(
            {"tenant_id": tenant_id,
             "sequence": prev_sequence,
             "integrity_hash": prev_hash},
            {"$set": new_head_doc},
            session=session,
        )
        if res.matched_count == 0:
            # The head moved under us. Raise a WriteConflict-equivalent
            # so `with_transaction` rolls back and retries from scratch.
            from pymongo.errors import OperationFailure
            raise OperationFailure(
                "audit_chain_head CAS failed: head advanced; retrying",
                code=112,  # Mongo WriteConflict
                details={"tenant_id": tenant_id,
                         "expected_sequence": prev_sequence,
                         "expected_hash": prev_hash},
            )

    event.update(chained)
    return chained


# -----------------------------------------------------------------------
# Server-side identity + confirmer resolution (C06)
# -----------------------------------------------------------------------
async def _resolve_item_identity(
    tenant_db, *, tenant_id: str, item_id: str, session,
) -> Dict[str, Any]:
    """Return `{item_id, unit, pending}` as the server sees it.

    `pending=True` iff the id refers to a `md_pending_mapping` row and
    not a confirmed Master item. Pending items may only enter quarantine.
    """
    # Confirmed Master item in the per-tenant `md_item` collection.
    item = await tenant_db["md_item"].find_one(
        {"tenant_id": tenant_id, "id": item_id},
        {"id": 1, "canonical_unit": 1, "unit": 1, "_id": 0},
        session=session,
    )
    if item:
        unit = item.get("canonical_unit") or item.get("unit")
        return {"item_id": item_id, "unit": unit, "pending": False, "found": True}
    pending = await tenant_db["md_pending_mapping"].find_one(
        {"tenant_id": tenant_id, "id": item_id},
        {"id": 1, "unit": 1, "_id": 0},
        session=session,
    )
    if pending:
        return {"item_id": item_id, "unit": pending.get("unit"),
                "pending": True, "found": True}
    return {"item_id": item_id, "unit": None, "pending": False, "found": False}


def _action_or_none(value: Any) -> Optional[CanonicalAction]:
    try:
        return CanonicalAction(value)
    except ValueError:
        return None


# -----------------------------------------------------------------------
# Command service
# -----------------------------------------------------------------------
class CommandService:
    """The one write path onto `warehouse_transactions`."""

    def __init__(
        self,
        db_client,
        *,
        gate: Optional[PermissionGate] = None,
        verify_indexes_once: bool = True,
        strict_master_identity: Optional[bool] = None,
    ) -> None:
        self._client = db_client
        self._gate = gate or PermissionGate()
        self._verify_once = verify_indexes_once
        self._verified: set = set()
        # In environments where Master Data has not yet been migrated
        # (early tests, isolated review), the service may fall back to
        # TRUSTING client `item_id` and `unit` after validating shape.
        # The default is strict in production; tests pass
        # strict_master_identity=False to run without md_item seeded.
        if strict_master_identity is None:
            strict_master_identity = os.environ.get(
                "WAREHOUSE_STRICT_MASTER_IDENTITY", "0"
            ).strip().lower() in {"1", "true", "yes", "on"}
        self._strict_master = bool(strict_master_identity)

    # ------------------------------------------------- public entrypoint
    async def execute(
        self,
        ctx,
        tenant_db,
        tenant_collection,          # TenantCollection for warehouse_transactions
        inp: CommandInput,
    ) -> ExecuteResult:
        # 5C-C26e — Р28 (Крум 06.11.2026): the canonical warehouse writes in
        # off / shadow / enforce alike (replaces the TASK 5C "enforce only"
        # refusal). The mode only chooses WHO decides the rights: enforce →
        # RoleAssignments (PermissionGate / Р27); off / shadow → the legacy
        # session role with the same rules (legacy_gate); shadow also
        # computes the enforce decision and only logs a mismatch.
        mode = permission_mode_of(ctx)

        action = inp.action
        if action not in CanonicalAction:
            raise UnknownActionError(f"unknown action {action!r}")

        # 5C-C19 F-4 — Rule B: a dispatch never credits its target
        # directly. Normalized BEFORE the gate so the gate (and the
        # fingerprint) see the destination that is actually written.
        self._force_dispatch_into_transit(inp)
        # 5C-C21 F-13 (Р11) — the same Rule B for warehouse→warehouse.
        # 5C-C25 (Р18) — and for project→project / project→warehouse.
        self._force_transfer_into_transit(inp)
        # 5C-C25 (Р18) — quarantine is a STATE change at one location,
        # never a move between locations.
        self._refuse_quarantine_move(inp)
        # 5C-C25 (FG-19, Р18) — an acceptance always drains the in-transit
        # bucket of its own dispatch; for a transfer it lands exactly in the
        # transfer's target (a returned lot in quarantine).
        # 5C-C21 F-12 (Р10) — a write-off from a project is project cost;
        # the project scope is server-derived from the source bucket.
        # 5C-C26d (C26B-1 / FG-38) — a subproject's project is its parent.
        # 5C-C26h (FG-59 / FG-61) — the project is bound from the locations.
        # FG-55: a binding refusal (422) is held back until the rights check
        # has passed, so a caller without rights always gets 403 and learns
        # nothing about the project / subproject relations.
        binding_error = None
        try:
            # 5C-C25 (FG-19, Р18) / 5C-C26i (FG-70): an acceptance drains its
            # own dispatch's transit bucket and lands where that dispatch was
            # addressed — transfers AND warehouse → project dispatches.
            dispatch = await self._bind_acceptance_to_transit(tenant_collection, inp)
            await self._check_dispatch_acceptance(tenant_db, inp, dispatch)
            await self._bind_subproject_parent(tenant_db, inp)
            self._bind_write_off_project(inp)
            await self._bind_project_from_locations(tenant_db, inp)
            await self._check_invoice_line_delivery(tenant_db, tenant_collection, inp)
        except InvariantViolationError as exc:
            binding_error = exc
            inp.project_id = await self._location_project(tenant_db, inp)

        # Permission (C06 — both source + destination + project scopes).
        # A transfer's physical destination is the TARGET warehouse even
        # though the row goes to in_transit, so its scope is checked now.
        try:
            await self._decide_rights(ctx, tenant_db, inp, mode)
        except PermissionDeniedError as exc:
            subs = [k for k in (inp.source, inp.destination, inp.transfer_target)
                    if k is not None and k.location_type == LocationType.SUBPROJECT]
            if binding_error is not None or subs:
                # FG-55 / FG-69: a denial never names a DB-resolved project —
                # with a subproject it names only the subproject the caller
                # sent, the same shape whether or not the binding held.
                context = {"action": action.value,
                           "reason_code": exc.context.get("reason_code", "DENY")}
                if subs:
                    context.update(scope_type="subproject", scope_id=subs[0].location_id)
                raise PermissionDeniedError("permission denied", context=context) from None
            raise
        if binding_error is not None:
            raise binding_error

        # Shape rules evaluated outside the tx so a malformed envelope
        # cannot reach Mongo.
        self._refuse_client_value_on_outbound(inp)
        self._refuse_client_value_on_quarantine(inp)
        self._enforce_state_rule_outside_tx(inp)

        # Fail-closed when W0-06 File Registry evidence is required and
        # not configured. (Tests set FILE_REGISTRY_ENABLED=1.)
        if action in EVIDENCE_REQUIRED_ACTIONS:
            if not inp.file_ids:
                raise FileRegistryUnavailableError(
                    "evidence file_ids are required for this action",
                    context={"action": action.value},
                )
            if not file_registry_available():
                raise FileRegistryUnavailableError(
                    "File Registry (W0-06) must be enabled",
                    context={"action": action.value},
                )

        # Index verification once per db (fail-closed).
        await self._ensure_indexes(tenant_db)

        # 5C-C26l Addendum L — the per-line lock document exists BEFORE the
        # transaction (a $setOnInsert-only upsert, idempotent): a first
        # transaction must not create the collection / document while a
        # concurrent one does the same (MongoDB refuses that, not retried).
        if inp.invoice_line_id and inp.action in (
                CanonicalAction.RECEIVE_FROM_SUPPLIER,
                CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT):
            from app.services.invoice_line_lock import ensure_line_lock
            await ensure_line_lock(tenant_collection.tenant, inp.invoice_line_id)
        # WH-REV-01 — a reversal of a LINKED receipt takes the same line lock.
        if inp.action in REVERSAL_ACTIONS and inp.reverses_movement_id:
            original = await tenant_collection.find_one(
                {"movement_id": inp.reverses_movement_id}, {"_id": 0, "invoice_line_id": 1})
            if original and original.get("invoice_line_id"):
                from app.services.invoice_line_lock import ensure_line_lock
                await ensure_line_lock(tenant_collection.tenant, original["invoice_line_id"])

        # CODEX C14.1 — audit serialization under concurrent writes.
        # The previous service-level `_MAX_RETRIES=5` manual retry
        # exhausted under 10 concurrent cross-item writes because the
        # chain-head CAS forces WriteConflict on contention and the
        # manual loop had neither Mongo's exponential backoff nor its
        # 120-second transaction retry deadline.
        #
        # The fix is architectural, NOT a bigger retry count:
        # `session.with_transaction(callback)` delegates WriteConflict
        # retry to the MongoDB driver, which implements the canonical
        # Mongo pattern — exponential backoff with jitter, retry while
        # the server's `transactionLifetimeLimitSeconds` allows, and
        # strict respect for TransientTransactionError /
        # UnknownTransactionCommitResult labels. Ten concurrent writes
        # serialize fairly on the single chain-head doc without any
        # writer losing all of a small retry budget.
        #
        # The outer `_MAX_RETRIES` wrapper remains only for errors
        # that are NOT a transient tx error — a non-transient failure
        # here means a configuration or integrity problem, not a race.
        try:
            return await self._execute_one_attempt(
                ctx, tenant_db, tenant_collection, inp,
            )
        except (WarehouseMovementError, IdempotencyConflict) as exc:
            if isinstance(exc, IdempotencyConflict):
                raise IdempotencyConflictError(str(exc), context={
                    "action": action.value, "key": inp.idempotency_key}) from exc
            raise
        except Exception as exc:
            # `session.with_transaction` already drained the transient
            # retries; anything escaping here is a hard failure that
            # the retry loop cannot address.
            if _is_sequence_duplicate_error(exc):
                # Duplicate-key on `(tenant_id, ledger_sequence)` /
                # `(tenant_id, sequence)` can still appear if an
                # external writer touched the audit collection; retry
                # once at the service level before giving up.
                try:
                    return await self._execute_one_attempt(
                        ctx, tenant_db, tenant_collection, inp,
                    )
                except Exception as retry_exc:
                    raise AuditChainWriteError(
                        f"transaction failed after retry: {retry_exc}"
                    ) from retry_exc
            raise AuditChainWriteError(
                f"transaction failed: {exc}"
            ) from exc

    async def _execute_one_attempt(
        self, ctx, tenant_db, tenant_collection, inp,
    ) -> ExecuteResult:
        """One attempt of the business transaction, with WriteConflict
        retry delegated to MongoDB via `session.with_transaction`.

        CODEX C14.1 — `with_transaction` is the canonical Mongo pattern
        for callback-style transactions. The driver catches
        `TransientTransactionError` and `UnknownTransactionCommitResult`,
        applies exponential backoff with jitter, and keeps retrying
        until `transactionLifetimeLimitSeconds` (default 60s on 4.4+,
        120s on older servers) expires. The callback must be
        idempotent: our business tx is append-only + CAS-pivoted +
        idempotency-keyed, so a re-run from scratch is safe.
        """
        try:
            session_cm = await self._client.start_session()
        except Exception as exc:
            raise TransactionsNotSupportedError(
                f"replica-set session unavailable: {exc}"
            ) from exc

        async with session_cm as session:
            # Capture the inputs so the callback closure has them.
            captured_result: Dict[str, Any] = {}

            async def _tx_body(session_arg):
                captured_result["value"] = await self._execute_in_tx(
                    session=session_arg, tenant_db=tenant_db,
                    tenant_collection=tenant_collection, inp=inp,
                )
                # Return nothing to with_transaction; it only cares
                # that no exception propagates.
                return None

            # `session.with_transaction` runs the callback inside a
            # transaction and retries it on TransientTransactionError
            # (which includes WriteConflict / code 112). Each retry is
            # a FRESH transaction, so the chain-head CAS re-reads the
            # current head and recomputes the hash — never a forked
            # chain. Mongo's own backoff/jitter beats a service-level
            # fixed-count loop.
            await session.with_transaction(_tx_body)
            return captured_result["value"]

    async def _ensure_indexes(self, tenant_db) -> None:
        db_name = tenant_db.name
        if self._verify_once and db_name in self._verified:
            return
        await verify_required_indexes(tenant_db)
        self._verified.add(db_name)

    # ------------------------------------------------- in-tx body
    async def _execute_in_tx(
        self,
        *,
        session,
        tenant_db,
        tenant_collection,
        inp: CommandInput,
    ) -> ExecuteResult:
        action = inp.action
        tenant_id = inp.tenant_id

        # Server-derived identity (C06).
        identity = await _resolve_item_identity(
            tenant_db, tenant_id=tenant_id, item_id=inp.item_id, session=session,
        )
        pending = False
        unit = inp.unit
        if self._strict_master:
            if not identity["found"]:
                raise MasterIdentityMissingError(
                    "item_id is not registered in Master Data",
                    context={"item_id": inp.item_id},
                )
            pending = identity["pending"]
            unit = identity["unit"] or inp.unit
        else:
            # Non-strict mode: trust shape but refuse empty.
            if not inp.item_id or not inp.unit:
                raise MasterIdentityMissingError(
                    "item_id and unit are required",
                    context={"action": action.value},
                )
            unit = inp.unit

        # Pending-mapping items can only enter QUARANTINE (C06).
        if pending:
            dest = inp.destination
            if dest is None or dest.state != MovementState.QUARANTINE:
                raise FreeTextIntoActionableStockError(
                    "pending-mapping items may only enter quarantine",
                    context={"action": action.value, "item_id": inp.item_id},
                )

        # Server-derived confirmer: the authenticated actor is both the
        # author AND the confirmer unless an acceptance explicitly binds
        # a different recipient later (that recipient is also
        # authenticated — never a client-supplied name).
        confirmed_by = inp.actor_id
        confirmed_at = _now_iso() if action in {
            CanonicalAction.ACCEPT_PROJECT_DELIVERY,
            CanonicalAction.CONSUME_TO_SMR,
            CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE,
            CanonicalAction.TRANSFER_PROJECT_TO_PROJECT,
        } else None

        # Reserve ledger_sequence inside the tx (unique per tenant).
        ledger_sequence = await self._next_ledger_sequence(
            tenant_collection, tenant_id=tenant_id, session=session,
        )

        # CODEX C11.9: server-issued transit location_id. If the caller
        # sent `destination.location_id="pending"` with an in-transit
        # state, the server replaces it with the service-generated
        # movement_id. The caller never fabricates a transit ID.
        # Likewise for the `source.location_id` on
        # ACCEPT_PROJECT_DELIVERY — it must point at the real dispatch.
        if (
            inp.destination is not None
            and inp.destination.state == MovementState.IN_TRANSIT
            and inp.destination.location_id == "pending"
        ):
            # The destination's `location_id` becomes the dispatch's
            # own `movement_id` so later acceptance can resolve it.
            inp.destination = LocationKey(
                LocationType.IN_TRANSIT,
                location_id="__movement_self__",
                state=MovementState.IN_TRANSIT,
            )
            # Marker handled below after movement_id is assigned.

        # ------------------------------------------------------------
        # Pre-build the base envelope (identity + unit are server-derived).
        # ------------------------------------------------------------
        envelope_quantity = Decimal(str(inp.quantity))
        base_env = build_envelope(
            tenant_id=tenant_id,
            action=action.value,
            item_id=identity["item_id"],
            unit=unit,
            quantity=envelope_quantity,
            source=inp.source,
            destination=inp.destination,
            actor_id=inp.actor_id,
            idempotency_key=inp.idempotency_key,
            unit_value=inp.unit_value if action in INBOUND_ACTIONS else Decimal("0"),
            currency=inp.currency,
            lot_id=inp.lot_id,
            layer_allocations=[],
            request_id=inp.request_id,
            invoice_id=inp.invoice_id,
            invoice_line_id=inp.invoice_line_id,
            delivery_id=inp.delivery_id,
            dispatch_movement_id=inp.dispatch_movement_id,
            reservation_movement_id=inp.reservation_movement_id,
            project_id=inp.project_id,
            subproject_id=inp.subproject_id,
            smr_id=inp.smr_id,
            work_package_id=inp.work_package_id,
            confirmed_by=confirmed_by,
            confirmed_at=confirmed_at,
            correlation_id=inp.correlation_id,
            requested_quantity=inp.requested_quantity,
            accepted_quantity=inp.accepted_quantity,
            file_ids=inp.file_ids,
            reason=inp.reason,
            notes=inp.notes,
            corrects_movement_id=inp.corrects_movement_id,
            revision_evidence=inp.revision_evidence,
            occurred_at=inp.occurred_at,
            reverses_movement_id=inp.reverses_movement_id,
        )

        # Fingerprint ignores server-derived fields (envelope.py already
        # strips movement_id / recorded_at / occurred_at / audit_event_id)
        # — so a replay with identical client input matches.
        fp = envelope_fingerprint(
            base_env,
            transfer_target=(inp.transfer_target.to_dict()
                             if inp.transfer_target is not None else None),
        )

        # Idempotency reservation (SAME session as the business write).
        idem = await _idem_begin_with_session(
            tenant_db, tenant_id=tenant_id, action=action.value,
            key=inp.idempotency_key, fingerprint=fp, session=session,
        )

        if idem["status"] == IDEMPOTENCY_DUPLICATE:
            prior_ref = idem.get("result_reference")
            if prior_ref:
                prior_row = await tenant_collection.find_one(
                    {"movement_id": prior_ref}, session=session,
                )
                if prior_row:
                    prior_row.pop("_id", None)
                    return ExecuteResult(
                        movement_id=prior_ref, envelope=prior_row,
                        audit_event_id=prior_row.get("audit_event_id", ""),
                        idempotency_status=IDEMPOTENCY_DUPLICATE, replay=True,
                    )
            # No prior row — this was a FAILED attempt. Fall through to
            # re-execute inside the current tx.

        # 5C-C26l Addendum K (WH55-C26L-1) — the invoice-line decision of a
        # linked direct delivery is taken HERE, in the transaction, under the
        # line lock (the pre-check before the rights gate is not a guard).
        # 5C-C26l Addendum L (FG-108): EVERY linked supplier receipt —
        # warehouse or direct — takes the same line lock, and the line's
        # covered quantity counts all linked paths.
        if action in (CanonicalAction.RECEIVE_FROM_SUPPLIER,
                      CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT) \
                and inp.invoice_line_id:
            await self._lock_invoice_line(tenant_collection, session=session,
                                          invoice_line_id=inp.invoice_line_id)
            await self._check_invoice_line_delivery(tenant_db, tenant_collection, inp,
                                                    session=session)
            await self._check_invoice_line_total(tenant_collection, inp, session=session)

        # ------------------------------------------------------------
        # Resolve allocations + value per action type.
        # ------------------------------------------------------------
        allocations: List[LayerAllocation] = []
        outbound_value = Decimal("0")
        unresolved_mv_id: Optional[str] = None
        acceptance_line_id: Optional[str] = None
        unit_value: Any = base_env.unit_value

        # WH-REV-01 — a receipt reversal takes EXACTLY the receipt's own layer
        # back out of the bucket it opened, at the receipt's value (no FIFO
        # choice), and only while that whole layer is still there.
        reversed_invoice_line_id: Optional[str] = None
        if action in REVERSAL_ACTIONS:
            allocations, outbound_value, reversed_invoice_line_id = \
                await self._plan_receipt_reversal(tenant_collection, session=session,
                                                  tenant_id=tenant_id, inp=inp,
                                                  item_id=identity["item_id"])

        if action in OUTBOUND_ACTIONS:
            if inp.source is None:
                raise InvariantViolationError(
                    "outbound action requires a source",
                    context={"action": action.value})
            allocations, outbound_value = await allocate_outbound(
                tenant_collection, tenant_id=tenant_id,
                item_id=identity["item_id"], source=inp.source,
                quantity=envelope_quantity, session=session,
            )

        # 5C-C25 (Р18) — a quarantine entry / release with a source moves
        # traced FIFO layers between the free and the quarantine state of
        # ONE location: value and layers are conserved (server FIFO, never a
        # client value). Before C25 they carried no allocations, so a
        # released lot came back at value 0.
        if action in QUARANTINE_ACTIONS and inp.source is not None:
            allocations, outbound_value = await allocate_outbound(
                tenant_collection, tenant_id=tenant_id,
                item_id=identity["item_id"], source=inp.source,
                quantity=envelope_quantity, session=session,
            )

        if action == CanonicalAction.ACCEPT_PROJECT_DELIVERY:
            # Rule B (C03): accept X units from a dispatch. The
            # dispatch's recorded layer_allocations are split
            # proportionally: `accepted_units` (Р21: oldest first, each at its own price) → destination,
            # remainder stays in-transit.
            if not inp.dispatch_movement_id:
                raise InvariantViolationError(
                    "accept_project_delivery requires dispatch_movement_id",
                    context={"action": action.value})
            await self._enforce_transfer_acceptance_target(
                tenant_collection, session=session, inp=inp,
            )
            accepted_qty = Decimal(str(inp.accepted_quantity if inp.accepted_quantity is not None
                                        else inp.quantity))
            # Multi-partial acceptance uniqueness.
            acceptance_line_id = f"accept_{uuid.uuid4().hex}"

            allocations, outbound_value = await self._split_dispatch_for_acceptance(
                tenant_collection, session=session, tenant_id=tenant_id,
                dispatch_movement_id=inp.dispatch_movement_id,
                accepted_qty=accepted_qty,
            )

            # Rule B unit_value for acceptance is server-derived weighted
            # average of the split allocations.
            unit_value = (
                (outbound_value / accepted_qty).quantize(Decimal("0.0001"))
                if accepted_qty > 0 else Decimal("0")
            )

            # Envelope accepted / missing / unresolved fields.
            # requested_quantity comes from the dispatch if the caller
            # did not supply one.
            if inp.requested_quantity is None:
                dispatch_row = await tenant_collection.find_one(
                    {"movement_id": inp.dispatch_movement_id}, session=session,
                )
                requested_quantity = Decimal(str(dispatch_row.get("quantity", "0")))
            else:
                requested_quantity = Decimal(str(inp.requested_quantity))

            # CODEX C12.1 — missing_quantity is CUMULATIVE: requested
            # minus ALL accepted so far (including this acceptance).
            # The naive `requested - this_accept` opened a bogus second
            # discrepancy on 10→8 then 10→2 (final acceptance claims
            # remainder=8 because it thinks "I accepted 2 out of 10").
            prior_accepted = Decimal("0")
            prior_cursor = tenant_collection.find({
                "tenant_id": tenant_id,
                "dispatch_movement_id": inp.dispatch_movement_id,
                "action": CanonicalAction.ACCEPT_PROJECT_DELIVERY.value,
            }, session=session)
            async for d in prior_cursor:
                prior_accepted += Decimal(str(d.get("accepted_quantity")
                                              or d.get("quantity") or "0"))
            total_accepted = prior_accepted + accepted_qty
            missing_qty = max(requested_quantity - total_accepted, Decimal("0"))

            # CODEX C13.2 — When the cumulative acceptance CLOSES the
            # lot (missing_qty == 0) AND prior partial acceptances had
            # already opened unresolved discrepancies, collect those
            # discrepancy movement ids so an append-only resolution
            # fact can clear the in-transit projection without
            # mutating ledger history.
            discrepancies_to_resolve: List[str] = []
            if missing_qty == 0 and prior_accepted > 0:
                _disc_cursor = tenant_collection.find({
                    "tenant_id": tenant_id,
                    "dispatch_movement_id": inp.dispatch_movement_id,
                    "action": "transit_discrepancy",
                    "discrepancy_status": {"$ne": "resolved"},
                }, {"movement_id": 1, "_id": 0}, session=session)
                async for d in _disc_cursor:
                    discrepancies_to_resolve.append(d.get("movement_id"))

            base_env.requested_quantity = requested_quantity
            base_env.accepted_quantity = accepted_qty
            base_env.missing_quantity = missing_qty
            base_env.quantity = accepted_qty      # the ledger line is the ACCEPTED fact
            # Fill the acceptance_line_id on the acceptance line
            # (unique index catches a replay).
        elif action == CanonicalAction.CONSUME_TO_SMR:
            # C03: consume MUST NOT recognize cost a second time.
            # Enforced by requiring source=PROJECT bucket, i.e. the
            # acceptance has already deposited cost there.
            if inp.source is None or inp.source.location_type != LocationType.PROJECT:
                raise InvariantViolationError(
                    "consume_to_smr must source from a project bucket",
                    context={"source": None if inp.source is None else inp.source.to_dict()})

        # Server-side value: weighted-average unit_value for outbound.
        if (action in OUTBOUND_ACTIONS or action in QUARANTINE_ACTIONS
                or action in REVERSAL_ACTIONS) and allocations:
            qty = sum((a.quantity for a in allocations), Decimal("0"))
            unit_value = (outbound_value / qty).quantize(Decimal("0.0001")) if qty > 0 else Decimal("0")

        # Rebuild envelope with FIFO fields and server-derived values.
        env = build_envelope(
            tenant_id=tenant_id,
            action=action.value,
            item_id=identity["item_id"],
            unit=unit,
            quantity=base_env.quantity,
            source=inp.source,
            destination=inp.destination,
            actor_id=inp.actor_id,
            idempotency_key=inp.idempotency_key,
            unit_value=unit_value,
            currency=inp.currency,
            lot_id=inp.lot_id,
            layer_allocations=allocations,
            request_id=inp.request_id,
            invoice_id=inp.invoice_id,
            invoice_line_id=inp.invoice_line_id,
            delivery_id=inp.delivery_id,
            dispatch_movement_id=inp.dispatch_movement_id,
            reservation_movement_id=inp.reservation_movement_id,
            project_id=inp.project_id,
            subproject_id=inp.subproject_id,
            smr_id=inp.smr_id,
            work_package_id=inp.work_package_id,
            confirmed_by=confirmed_by,
            confirmed_at=confirmed_at,
            correlation_id=inp.correlation_id,
            requested_quantity=base_env.requested_quantity,
            accepted_quantity=base_env.accepted_quantity,
            missing_quantity=base_env.missing_quantity,
            file_ids=inp.file_ids,
            reason=inp.reason,
            notes=inp.notes,
            corrects_movement_id=inp.corrects_movement_id,
            revision_evidence=inp.revision_evidence,
            occurred_at=inp.occurred_at,
            reverses_movement_id=inp.reverses_movement_id,
        )
        validate_envelope(env)

        # CODEX C11.9: resolve server-issued transit location_id now
        # that movement_id is known. The marker `__movement_self__`
        # becomes the movement's own id so later acceptance resolves it
        # against the actual dispatch.
        if (
            env.destination
            and env.destination.get("location_id") == "__movement_self__"
        ):
            env.destination["location_id"] = env.movement_id

        # Append ledger row (append-only). ledger_sequence pins order.
        ledger_row = env.to_dict()
        ledger_row["ledger_sequence"] = ledger_sequence
        if reversed_invoice_line_id:
            # WH-REV-01 — trace only; deliberately NOT `invoice_line_id`, so a
            # reversal is never read as a link of the line.
            ledger_row["reversed_invoice_line_id"] = reversed_invoice_line_id
        if acceptance_line_id:
            ledger_row["acceptance_line_id"] = acceptance_line_id
        if inp.transfer_target is not None:
            ledger_row["transfer_target"] = inp.transfer_target.to_dict()
        # 5C-C25 (Р17) — where the accepted lot came from (server-derived
        # from the dispatch row). The projector moves project cost with it:
        # a lot that leaves a project stops being that project's cost when
        # it is accepted at its destination. Stored on the row so a rebuild
        # derives exactly the same cost rows.
        transit_origin = None
        if action == CanonicalAction.ACCEPT_PROJECT_DELIVERY:
            transit_origin = await self._transit_origin(
                tenant_collection, session=session,
                dispatch_movement_id=inp.dispatch_movement_id)
            ledger_row["transit_origin"] = transit_origin
        await tenant_collection.insert_one(ledger_row, session=session)

        # If this is a dispatch, open a mirrored IN_TRANSIT inbound row
        # that carries the SAME layer_allocations — so a later acceptance
        # can source traced layers (C04 conservation).
        if action == CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT \
                or action == CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE \
                or action == CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE \
                or action == CanonicalAction.TRANSFER_PROJECT_TO_PROJECT:
            await self._open_in_transit_inbound(
                tenant_collection, session=session,
                dispatch_env=env, dispatch_row=ledger_row,
                allocations=allocations,
            )

        # Rule B unresolved: if accepted < requested, append a separate
        # non-moving `transit_discrepancy` row referencing the dispatch.
        if action == CanonicalAction.ACCEPT_PROJECT_DELIVERY and base_env.missing_quantity > 0:
            unresolved_mv_id = await self._open_transit_discrepancy(
                tenant_collection, session=session, env=env,
                missing_quantity=base_env.missing_quantity,
                dispatch_movement_id=inp.dispatch_movement_id,
            )

        # CODEX C13.2 / C16 — Rule B RESOLUTION FACT (append-only).
        # When the cumulative acceptance closes the lot and prior
        # discrepancies exist, append one non-moving
        # `discrepancy_resolved` ledger row per open discrepancy. The
        # ledger stays append-only (no mutation of the original
        # discrepancy rows); the projector consumes these rows to
        # clear `warehouse_in_transit.unresolved_discrepancies` and
        # mark the discrepancy rows as resolved in the projection.
        #
        # Two distinct identities, both preserved on the ledger:
        #   * ``original_discrepancy_mv_id`` (``disc_mv_id``) — the
        #     id of the original ``transit_discrepancy`` row that
        #     opened the entry; THIS is also the key of the active
        #     ``warehouse_in_transit.unresolved_discrepancies`` map
        #     the projector must close, so it is also what the
        #     projection hint must carry to the projector.
        #   * ``new_resolution_mv_id`` (returned by
        #     ``_append_discrepancy_resolution``) — the id of the
        #     NEW ``discrepancy_resolved`` row; the ledger carries
        #     both ids on that row so a rebuild has them both.
        # CODEX C16 fix: previously the hint list carried the NEW
        # resolution mv_id, which never matched the map key — the
        # live projection kept the stale entry while rebuild closed
        # it from the ledger (live/rebuild divergence). Carry the
        # ORIGINAL disc_mv_id so live and rebuild converge to the
        # same empty map and the resolution fact (new mv_id) is also
        # exposed for audit/reporting.
        resolved_discrepancy_mv_ids: List[str] = []
        resolution_mv_ids: List[str] = []
        if (action == CanonicalAction.ACCEPT_PROJECT_DELIVERY
                and base_env.missing_quantity == 0
                and discrepancies_to_resolve):
            for disc_mv_id in discrepancies_to_resolve:
                if not disc_mv_id:
                    continue
                resolution_mv_id = await self._append_discrepancy_resolution(
                    tenant_collection, session=session, env=env,
                    dispatch_movement_id=inp.dispatch_movement_id,
                    resolved_discrepancy_movement_id=disc_mv_id,
                    resolving_acceptance_movement_id=env.movement_id,
                )
                resolved_discrepancy_mv_ids.append(disc_mv_id)
                resolution_mv_ids.append(resolution_mv_id)

        # AuditEvent inside the same tx.
        retention = (
            RETENTION_R1_CRITICAL_BUSINESS
            if action in {CanonicalAction.REVISION_ADJUSTMENT, CanonicalAction.WRITE_OFF}
            else RETENTION_R2_PROJECT_OPERATIONAL
        )
        audit_event = build_event(
            tenant_id=tenant_id, actor_type=ACTOR_HUMAN, actor_id=inp.actor_id,
            action=f"warehouse.{action.value}", source_flow="FLOW-009",
            retention_class=retention, entity_type="warehouse_movement",
            entity_id=env.movement_id,
            scope_type="project" if inp.project_id else "location",
            scope_id=inp.project_id or (inp.destination.location_id if inp.destination else None),
            reason=inp.reason, source_channel="canonical_warehouse_service",
            tool_or_endpoint="warehouse_movements.CommandService.execute",
            correlation_id=inp.correlation_id or env.movement_id,
            idempotency_key=inp.idempotency_key,
            related_file_ids=list(inp.file_ids or []),
            structured_diff={
                "action": action.value,
                # WH-REV-01: a reversal names the receipt it reverses.
                **({"reverses_movement_id": inp.reverses_movement_id}
                   if inp.reverses_movement_id else {}),
                "item_id": identity["item_id"],
                "quantity": str(env.quantity),
                "accepted_quantity": None if env.accepted_quantity is None else str(env.accepted_quantity),
                "missing_quantity": None if env.missing_quantity is None else str(env.missing_quantity),
                "source": inp.source.to_dict() if inp.source else None,
                "destination": inp.destination.to_dict() if inp.destination else None,
                "allocations": [a.to_dict() for a in allocations],
                "outbound_value": str(outbound_value),
                "ledger_sequence": ledger_sequence,
                "acceptance_line_id": acceptance_line_id,
                "unresolved_discrepancy_movement_id": unresolved_mv_id,
                "transfer_target": (inp.transfer_target.to_dict()
                                    if inp.transfer_target is not None else None),
            },
        )
        chained = await _record_event_in_session(tenant_db, audit_event, session=session)

        # Write audit_event_id back onto the ledger row for easy lookup.
        env.audit_event_id = chained.get("event_id")
        await tenant_collection.update_one(
            {"movement_id": env.movement_id},
            {"$set": {"audit_event_id": env.audit_event_id}},
            session=session,
        )

        # Projections (same session). The `warehouse_in_transit`
        # projection is advisory only — the ledger is the source of
        # truth (C07). The service passes original dispatch metadata so
        # the projector can close in-transit on acceptance correctly.
        from app.services.warehouse_movements.projections import apply_projection
        projection_hints: Dict[str, Any] = {}
        if unresolved_mv_id:
            projection_hints["unresolved_discrepancy_movement_id"] = unresolved_mv_id
            projection_hints["unresolved_layer_allocations"] = [
                a.to_dict() for a in allocations
            ]
        if acceptance_line_id:
            projection_hints["acceptance_line_id"] = acceptance_line_id
        if inp.transfer_target is not None:
            projection_hints["transfer_target"] = inp.transfer_target.to_dict()
        if transit_origin is not None:
            projection_hints["transit_origin"] = transit_origin
        # CODEX C13.2 / C16 — carry the resolution set so the projector
        # can clear the active in-transit `unresolved_discrepancies`
        # map for this dispatch. ``resolved_discrepancy_movement_ids``
        # must be the ORIGINAL discrepancy movement ids (the active
        # map's keys); ``resolution_movement_ids`` is the new
        # resolution rows' identities, exposed to the projector so
        # audit/reporting can access both without re-querying the
        # ledger. Preserves live/rebuild parity: the rebuild path
        # already keys off ``resolves_discrepancy_movement_id`` on
        # the ``discrepancy_resolved`` ledger row (the original id).
        if resolved_discrepancy_mv_ids:
            projection_hints["resolved_discrepancy_movement_ids"] = list(
                resolved_discrepancy_mv_ids,
            )
            projection_hints["resolution_movement_ids"] = list(
                resolution_mv_ids,
            )
            projection_hints["resolving_dispatch_movement_id"] = (
                inp.dispatch_movement_id
            )
        await apply_projection(
            tenant_db, env,
            session=session,
            hints=projection_hints or None,
        )

        # Complete idempotency (same session).
        await _idem_complete_with_session(
            tenant_db, tenant_id=tenant_id, action=action.value,
            key=inp.idempotency_key, result_reference=env.movement_id,
            session=session,
        )

        final = env.to_dict()
        final["ledger_sequence"] = ledger_sequence
        if inp.transfer_target is not None:
            final["transfer_target"] = inp.transfer_target.to_dict()
        if transit_origin is not None:
            final["transit_origin"] = transit_origin
        if acceptance_line_id:
            final["acceptance_line_id"] = acceptance_line_id
        return ExecuteResult(
            movement_id=env.movement_id, envelope=final,
            audit_event_id=env.audit_event_id or "",
            idempotency_status=IDEMPOTENCY_STARTED, replay=False,
            unresolved_discrepancy_movement_id=unresolved_mv_id,
        )

    # ------------------------------------------------- helpers
    def _refuse_client_value_on_outbound(self, inp: CommandInput) -> None:
        if inp.action in OUTBOUND_ACTIONS and inp.unit_value and Decimal(str(inp.unit_value)) > 0:
            raise ValueFromClientRefusedError(
                "unit_value is server-derived for outbound actions",
                context={"action": inp.action.value,
                         "supplied_unit_value": str(inp.unit_value)},
            )

    @staticmethod
    def _force_dispatch_into_transit(inp: CommandInput) -> None:
        """5C-C19 F-4 — every dispatch goes to `in_transit` / `pending`.

        Rule B (F-09=B): the project is credited only by
        ACCEPT_PROJECT_DELIVERY. A dispatch whose destination is a
        project (or any non-transit bucket) would put the stock on the
        project before acceptance, so it is REFUSED, never silently
        accepted. A missing destination, or an in-transit destination
        with any client state / id, is forced to the server-issued
        transit bucket (`pending` → the dispatch's own movement_id,
        C11.9): the client never chooses the transit state or id.
        """
        if inp.action != CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT:
            return
        dest = inp.destination
        if dest is not None and dest.location_type != LocationType.IN_TRANSIT:
            raise InvariantViolationError(
                "dispatch_warehouse_to_project must go to in_transit; "
                "the project is credited only by accept_project_delivery",
                context={"destination": dest.to_dict(),
                         "required": {"location_type": "in_transit",
                                      "location_id": "pending",
                                      "state": "in_transit"}},
            )
        inp.destination = LocationKey(
            LocationType.IN_TRANSIT,
            location_id="pending",
            state=MovementState.IN_TRANSIT,
        )

    # 5C-C25 (Р18) — every move between locations goes "в път" and lands
    # only on acceptance. Per transfer kind: the source location types it
    # may leave, the target location types it may be for, and the state the
    # target is credited in.
    _WAREHOUSES = frozenset({LocationType.CENTRAL_WAREHOUSE, LocationType.SMALL_WAREHOUSE})
    _PROJECTS = frozenset({LocationType.PROJECT, LocationType.SUBPROJECT})
    TRANSFER_RULES = {
        # Р11 / 5C-C21 F-13
        CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE: (_WAREHOUSES, _WAREHOUSES, MovementState.FREE),
        # Р18 — a return to a warehouse lands in quality quarantine first
        # (FLOW-009 „Връщане и карантина"); it is reused only after a
        # quarantine_release to free stock.
        CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE: (_PROJECTS, _WAREHOUSES, MovementState.QUARANTINE),
        # Р18 — project → project
        CanonicalAction.TRANSFER_PROJECT_TO_PROJECT: (_PROJECTS, _PROJECTS, MovementState.FREE),
    }

    @classmethod
    def _force_transfer_into_transit(cls, inp: CommandInput) -> None:
        """5C-C21 F-13 (Р11) + 5C-C25 (Р18) — Rule B for EVERY transfer
        (warehouse→warehouse, project→warehouse, project→project).

        A transfer never credits its receiving location directly: the stock
        is "в път" (in_transit) and lands in the target only through
        ACCEPT_PROJECT_DELIVERY against the transfer (partial acceptances
        and discrepancies work exactly as for a project dispatch). So:

          * a non-transit `destination` (the old direct transfer) is
            REFUSED — never silently converted;
          * the receiving location is named in `transfer_target`; its
            type and state are fixed per kind (`TRANSFER_RULES`): a
            project→warehouse return targets the warehouse's QUARANTINE
            state (Р18), the other two target free stock;
          * the target must differ from the source;
          * the row's destination is forced to the server-issued transit
            bucket (`pending` → the transfer's own movement_id, C11.9).
        """
        rule = cls.TRANSFER_RULES.get(inp.action)
        if rule is None:
            if inp.transfer_target is not None:
                raise InvariantViolationError(
                    "transfer_target is only valid on a transfer action",
                    context={"action": inp.action.value},
                )
            return
        sources, targets, target_state = rule
        dest = inp.destination
        if dest is not None and dest.location_type != LocationType.IN_TRANSIT:
            raise InvariantViolationError(
                f"direct {inp.action.value} is refused: the stock goes to "
                "in_transit and the target is credited only by "
                "accept_project_delivery (Rule B, Р11/Р18)",
                context={"destination": dest.to_dict(),
                         "required": {"destination": {"location_type": "in_transit",
                                                      "location_id": "pending",
                                                      "state": "in_transit"},
                                      "transfer_target": {
                                          "location_type": sorted(t.value for t in targets),
                                          "state": target_state.value}}},
            )
        target = inp.transfer_target
        if target is None or target.location_type not in targets \
                or not target.location_id:
            raise InvariantViolationError(
                f"{inp.action.value} requires transfer_target: one of "
                f"{sorted(t.value for t in targets)} in state {target_state.value}",
                context={"transfer_target": None if target is None else target.to_dict()},
            )
        if target.state != target_state:
            if target_state == MovementState.QUARANTINE:
                raise QuarantineStateViolationError(
                    "a return to a warehouse goes through quality quarantine "
                    "before reuse (Р18): transfer_target.state must be quarantine",
                    context={"transfer_target": target.to_dict(),
                             "required_state": target_state.value},
                )
            raise InvariantViolationError(
                f"{inp.action.value} transfer_target must be in state {target_state.value}",
                context={"transfer_target": target.to_dict()},
            )
        src = inp.source
        if src is None or src.location_type not in sources:
            raise InvariantViolationError(
                f"{inp.action.value} must source from one of "
                f"{sorted(t.value for t in sources)}",
                context={"source": None if src is None else src.to_dict()},
            )
        if src.state != MovementState.FREE:
            raise InvariantViolationError(
                f"{inp.action.value} moves free stock only",
                context={"source": src.to_dict()},
            )
        if (src.location_type, src.location_id) == (target.location_type, target.location_id):
            raise InvariantViolationError(
                "transfer_target must differ from the source",
                context={"source": src.to_dict(), "transfer_target": target.to_dict()},
            )
        inp.destination = LocationKey(
            LocationType.IN_TRANSIT,
            location_id="pending",
            state=MovementState.IN_TRANSIT,
        )

    @staticmethod
    def _refuse_quarantine_move(inp: CommandInput) -> None:
        """5C-C25 (Р18) — QUARANTINE_ENTRY / QUARANTINE_RELEASE change the
        STATE of stock at ONE location (FLOW-009: quarantine is a state,
        never another location). With a source at another location they
        would be a direct move that skips "в път" and acceptance, so they
        are refused. A returned lot reaches the warehouse quarantine only
        through transfer_project_to_warehouse + acceptance."""
        if inp.action not in QUARANTINE_ACTIONS:
            return
        src, dest = inp.source, inp.destination
        if src is None or dest is None:
            return
        if (src.location_type, src.location_id) != (dest.location_type, dest.location_id):
            raise InvariantViolationError(
                f"{inp.action.value} changes the state at one location; a move "
                "between locations goes through a transfer in transit (Р18)",
                context={"source": src.to_dict(), "destination": dest.to_dict()},
            )

    def _refuse_client_value_on_quarantine(self, inp: CommandInput) -> None:
        """5C-C25 — a quarantine move with a source carries server FIFO
        layers; a client value is refused like on any outbound."""
        if inp.action in QUARANTINE_ACTIONS and inp.source is not None \
                and inp.unit_value and Decimal(str(inp.unit_value)) > 0:
            raise ValueFromClientRefusedError(
                "unit_value is server-derived for quarantine moves",
                context={"action": inp.action.value,
                         "supplied_unit_value": str(inp.unit_value)},
            )

    async def _bind_acceptance_to_transit(self, tenant_collection, inp: CommandInput) -> None:
        """5C-C25 — server-side binding of an acceptance to its dispatch.

        * FG-19: the source is ALWAYS the in-transit bucket of the named
          dispatch (`in_transit/<dispatch movement_id>/in_transit`). Before
          C25 an acceptance without `source` credited the destination but
          never drained transit, so the location view showed phantom
          "в път" stock. A client source naming anything else is refused.
        * Р18: an acceptance of a TRANSFER must land in exactly the
          transfer's target (location and state — a return lands in
          quarantine). For a project→project transfer the acceptance's
          project is the target project; for a transfer into a warehouse
          it carries no project. Done BEFORE the permission gate so the
          gate checks the scopes that are actually written; re-checked in
          the transaction (`_enforce_transfer_acceptance_target`).
        """
        if inp.action != CanonicalAction.ACCEPT_PROJECT_DELIVERY:
            return
        if not inp.dispatch_movement_id:
            return  # refused later: acceptance requires dispatch_movement_id
        transit = LocationKey(LocationType.IN_TRANSIT,
                              location_id=inp.dispatch_movement_id,
                              state=MovementState.IN_TRANSIT)
        src = inp.source
        if src is not None and (src.location_type, src.location_id, src.state) != \
                (transit.location_type, transit.location_id, transit.state):
            raise InvariantViolationError(
                "an acceptance drains the in-transit bucket of its own dispatch",
                context={"source": src.to_dict(), "required": transit.to_dict()},
            )
        inp.source = transit
        dispatch = await tenant_collection.find_one(
            {"movement_id": inp.dispatch_movement_id},
            {"action": 1, "transfer_target": 1, "project_id": 1, "_id": 0},
        )
        if not dispatch:
            return None  # refused in the transaction (unknown dispatch)
        rule = self.TRANSFER_RULES.get(_action_or_none(dispatch.get("action")))
        if rule is None:
            return dispatch
        self._check_transfer_acceptance(inp, dispatch)
        return dispatch

    @staticmethod
    async def _check_dispatch_acceptance(tenant_db, inp: CommandInput,
                                         dispatch: Optional[Dict[str, Any]]) -> None:
        """5C-C26i — FG-70 (HIGH): an acceptance of a warehouse → project
        DISPATCH must land on the project the dispatch was addressed to (its
        project_id; a subproject counts by its DB parent). Before, only a
        TRANSFER's target was enforced, so a member of P1 could accept into
        P1 a lot dispatched to P2. Mismatch → 422, nothing written (held back
        until the rights check — FG-55)."""
        if not dispatch or dispatch.get("action") != \
                CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT.value:
            return
        target = dispatch.get("project_id")
        dest = inp.destination
        landed = None
        if dest is not None and dest.location_type == LocationType.PROJECT:
            landed = dest.location_id
        elif dest is not None and dest.location_type == LocationType.SUBPROJECT:
            try:
                landed = await resolve_subproject_parent(
                    tenant_db, inp.tenant_id, dest.location_id)
            except WarehouseMovementError:
                landed = None
        if not target or landed != target:
            raise InvariantViolationError(
                "an acceptance lands on the project the dispatch was addressed to",
                context={"dispatch_movement_id": inp.dispatch_movement_id})

    @staticmethod
    def _check_transfer_acceptance(inp: CommandInput, dispatch: Dict[str, Any]) -> None:
        target = dispatch.get("transfer_target") or {}
        dest = inp.destination
        if dest is None or dest.location_type.value != target.get("location_type") \
                or dest.location_id != target.get("location_id") \
                or dest.state.value != target.get("state"):
            if dest is not None and target.get("state") == MovementState.QUARANTINE.value \
                    and dest.location_id == target.get("location_id"):
                raise QuarantineStateViolationError(
                    "a returned lot is accepted into quarantine first (Р18)",
                    context={"transfer_target": target, "destination": dest.to_dict()},
                )
            raise InvariantViolationError(
                "acceptance of a transfer must land in its target",
                context={"transfer_target": target,
                         "destination": None if dest is None else dest.to_dict()},
            )
        if target.get("location_type") == LocationType.PROJECT.value:
            if inp.project_id and inp.project_id != target.get("location_id"):
                raise InvariantViolationError(
                    "acceptance of a project transfer carries the target project",
                    context={"project_id": inp.project_id, "transfer_target": target},
                )
            inp.project_id = target.get("location_id")
        elif target.get("location_type") == LocationType.SUBPROJECT.value:
            # 5C-C26d/e (FG-38, C26D-L1): the project is the subproject's
            # parent from the database — bound (or a mismatch refused, 422)
            # by _bind_subproject_parent right after this binding.
            pass
        elif inp.project_id:
            raise InvariantViolationError(
                "acceptance of a transfer into a warehouse cannot carry a project_id",
                context={"project_id": inp.project_id},
            )

    @staticmethod
    async def _transit_origin(tenant_collection, *, session,
                              dispatch_movement_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """5C-C25 (Р17) — the origin of the lot an acceptance lands:
        the dispatch/transfer action, its source location and project."""
        if not dispatch_movement_id:
            return None
        row = await tenant_collection.find_one(
            {"movement_id": dispatch_movement_id},
            {"action": 1, "source": 1, "project_id": 1, "_id": 0}, session=session,
        )
        if not row:
            return None
        return {"action": row.get("action"), "location": row.get("source"),
                "project_id": row.get("project_id"),
                "dispatch_movement_id": dispatch_movement_id}

    async def _decide_rights(self, ctx, tenant_db, inp: CommandInput, mode: str) -> None:
        """Р28 — the rights of one command: enforce → RoleAssignments;
        off / shadow → the legacy role (legacy_gate), shadow also computes the
        enforce decision and only logs a mismatch."""
        if mode == "enforce":
            await self._enforce_gate(ctx, tenant_db, inp)
            return
        from app.services.warehouse_movements.legacy_gate import ensure_legacy
        legacy_exc = None
        try:
            await ensure_legacy(ctx, tenant_db, inp)
        except PermissionDeniedError as exc:
            legacy_exc = exc
        if mode == "shadow":
            try:
                await self._enforce_gate(ctx, tenant_db, inp)
                new_allow = True
            except Exception:                  # unverified counts as deny
                new_allow = False
            if new_allow != (legacy_exc is None):
                logger.warning(
                    "PERMISSION_SHADOW_MISMATCH action=%s legacy_allow=%s "
                    "new_allow=%s project=%s", inp.action.value,
                    legacy_exc is None, new_allow, inp.project_id)
        if legacy_exc is not None:
            raise legacy_exc

    async def _enforce_gate(self, ctx, tenant_db, inp: CommandInput) -> None:
        """The RoleAssignment decision (enforce; observed in shadow)."""
        r27 = getattr(self._gate, "ensure_project_write_off", None)
        if inp.action == CanonicalAction.WRITE_OFF and inp.project_id and r27 is not None:
            # 5C-C26 Addendum A — Р27: write-off from a project (фира).
            await r27(ctx, tenant_db, org_id=inp.tenant_id, project_id=inp.project_id)
        else:
            await self._gate.ensure(
                ctx, action=inp.action, source=inp.source,
                destination=inp.transfer_target or inp.destination,
                project_id=inp.project_id,
            )
            # 5C-C26f — audit C26E-1 (HIGH): the real grant gives a
            # SiteManager a COMPANY-scope assignment, which the scope check
            # alone lets onto every project. When only project-bound roles
            # grant the action, the in-date project relation is required —
            # the same rule as off / shadow (legacy_gate). Production gates
            # only (a test gate with an injected evaluator has no registry).
            if getattr(self._gate, "_r27", False):
                from app.services.warehouse_movements.legacy_gate import (
                    ensure_enforce_project_relation,
                )
                await ensure_enforce_project_relation(
                    ctx, tenant_db, inp,
                    load_assignments=getattr(self._gate, "_assignments_loader", None))

    @staticmethod
    async def _check_invoice_line_delivery(tenant_db, tenant_collection,
                                           inp: CommandInput, *, session=None) -> None:
        """5C-C26l — Codex F-55-C26-02 (D-04: one lot is cost once).

        A direct delivery (RECEIVE_FROM_SUPPLIER_TO_PROJECT) that names
        invoice line L must go to a project L is allocated to — the
        DB-resolved destination project (subproject → parent). Otherwise L's
        allocated project would keep L as Path B while the destination
        recognises the same lot through the canon. Also refused: delivering
        more than L's allocation to that project still not delivered (when
        the units are comparable). 422 INVOICE_LINE_PROJECT_MISMATCH, nothing
        written (held back until the rights check — FG-55).

        5C-C26l Addendum K (WH55-C26L-1): called twice — before the rights
        check (no session: the FG-55 ordering) and AGAIN inside the movement
        transaction, after ``_lock_invoice_line`` (``session``), where it is
        the decision that counts: the reads see the transaction's snapshot
        and a concurrent delivery of the same line write-conflicts on the
        lock, so ``with_transaction`` re-runs it against the committed rows."""
        if inp.action != CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT \
                or not inp.invoice_line_id or not inp.project_id:
            return
        from app.services.canonical_material_cost import effective_allocations, _norm_unit
        from app.services.warehouse_movements.errors import InvoiceLineProjectMismatchError
        from app.tenancy.data_access import TenantData
        tenant = TenantData.for_resolved_org(tenant_db, inp.tenant_id)
        line = await tenant.invoice_lines.find_one(
            {"id": inp.invoice_line_id},
            {"_id": 0, "id": 1, "qty": 1, "unit": 1, "allocations": 1,
             "allocation_type": 1, "allocation_ref_id": 1}, session=session)
        mine = [a for a in effective_allocations(line or {})
                if a["type"] == "project" and a["ref_id"] == inp.project_id]
        if not mine:
            raise InvoiceLineProjectMismatchError(
                "the invoice line is not allocated to the delivery's project",
                context={"invoice_line_id": inp.invoice_line_id})
        if any(a["qty"] is None for a in mine) or \
                _norm_unit(line.get("unit")) not in ("", _norm_unit(inp.unit)):
            return            # quantity not comparable — the allocation check stands
        allocated = Decimal(str(sum(a["qty"] for a in mine)))
        delivered = Decimal("0")
        from app.services.warehouse_movements.reversal import without_reversed
        rows = [row async for row in tenant_collection.find(
            {"action": CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT.value,
             "invoice_line_id": inp.invoice_line_id, "project_id": inp.project_id},
            {"_id": 0, "movement_id": 1, "action": 1, "quantity": 1, "idempotency_key": 1},
            session=session)]
        # WH-REV-01: a reversed delivery no longer covers the line.
        for row in await without_reversed(tenant_collection, rows, session=session):
            if inp.idempotency_key and row.get("idempotency_key") == inp.idempotency_key:
                return        # a replay of this very delivery — idempotency answers
            delivered += Decimal(str(row.get("quantity") or "0"))
        if delivered + Decimal(str(inp.quantity)) > allocated:
            raise InvoiceLineProjectMismatchError(
                "the delivery exceeds the invoice line's allocation to the project",
                context={"invoice_line_id": inp.invoice_line_id,
                         "allocated": str(allocated), "delivered": str(delivered),
                         "quantity": str(inp.quantity)})

    @staticmethod
    async def _plan_receipt_reversal(tenant_collection, *, session, tenant_id: str,
                                     inp: CommandInput, item_id: str):
        """WH-REV-01 — decided IN the movement transaction (every canonical
        write of the tenant is serialized by the ledger-sequence counter and
        the audit chain head, so a concurrent issue of the same lot cannot
        slip between this check and the write):

          * the receipt exists in this tenant and is the receipt kind this
            reversal reverses; the request matches it (item, quantity,
            bucket) — else 422 RECEIPT_NOT_REVERSIBLE;
          * it is not already reversed — else 409 (RECEIPT_ALREADY_REVERSED);
          * its own FIFO layer ``(receipt, 1)`` is still WHOLE in the bucket
            the receipt opened — else 409 (RECEIPT_ALREADY_ISSUED) naming the
            movements that took it (they are reversed / returned first);
          * a linked receipt (``invoice_line_id``) takes the invoice line's
            lock (Addendum K), so its covered quantity — and the FG-109
            allocation lock — drop atomically with this write.

        Returns (allocations, value, the receipt's invoice line id)."""
        from app.services.warehouse_movements.errors import (
            ReceiptNotReversibleError, ReceiptReversalConflictError,
        )
        from app.services.warehouse_movements.fifo import layers_at
        from app.services.warehouse_movements.reversal import REVERSAL_ACTION_VALUES
        from app.services.warehouse_movements.errors import ReasonRequiredError
        if not (inp.reason or "").strip():
            raise ReasonRequiredError("a receipt reversal needs a reason",
                                      context={"reverses_movement_id": inp.reverses_movement_id})
        receipt_id = inp.reverses_movement_id
        original = await tenant_collection.find_one({"movement_id": receipt_id}, {"_id": 0},
                                                    session=session)
        expected = REVERSAL_OF[inp.action].value
        if not original or original.get("action") != expected:
            raise ReceiptNotReversibleError(
                "not a supplier receipt this reversal can reverse",
                context={"reverses_movement_id": receipt_id, "expected_action": expected,
                         "action": (original or {}).get("action")})
        qty = Decimal(str(original.get("quantity")))
        bucket = original.get("destination") or {}
        if (original.get("item_id") != item_id or Decimal(str(inp.quantity)) != qty
                or inp.source is None or inp.source.to_dict() != bucket):
            raise ReceiptNotReversibleError(
                "the reversal must take the receipt's whole lot from its bucket",
                context={"reverses_movement_id": receipt_id})
        done = await tenant_collection.find_one(
            {"action": {"$in": list(REVERSAL_ACTION_VALUES)},
             "reverses_movement_id": receipt_id},
            {"_id": 0, "movement_id": 1}, session=session)
        if done:
            raise ReceiptReversalConflictError(
                "the receipt is already reversed",
                context={"code": "RECEIPT_ALREADY_REVERSED",
                         "reverses_movement_id": receipt_id,
                         "reversal_movement_id": done.get("movement_id")})
        open_layers = await layers_at(tenant_collection, tenant_id=tenant_id, item_id=item_id,
                                      location=inp.source, session=session)
        own = [l for l in open_layers
               if l.source_movement_id == receipt_id and l.layer_sequence == 1]
        if not own or own[0].quantity != qty:
            takers = []
            async for row in tenant_collection.find(
                    {"layer_allocations.source_movement_id": receipt_id,
                     "movement_id": {"$ne": receipt_id}},
                    {"_id": 0, "movement_id": 1, "action": 1, "quantity": 1},
                    session=session).sort([("ledger_sequence", 1)]):
                takers.append({"movement_id": row.get("movement_id"),
                               "action": row.get("action"),
                               "quantity": str(row.get("quantity"))})
            raise ReceiptReversalConflictError(
                "the received lot was already issued or moved — reverse / return those "
                "movements first",
                context={"code": "RECEIPT_ALREADY_ISSUED", "reverses_movement_id": receipt_id,
                         "received": str(qty),
                         "still_in_bucket": str(own[0].quantity if own else Decimal("0")),
                         "taken_by": takers})
        layer = own[0]
        line_id = original.get("invoice_line_id")
        if line_id:
            await CommandService._lock_invoice_line(tenant_collection, session=session,
                                                    invoice_line_id=line_id)
        allocations = [LayerAllocation(
            source_movement_id=receipt_id, layer_sequence=1, quantity=qty,
            unit_value=layer.unit_value, currency=layer.currency)]
        return allocations, (qty * layer.unit_value).quantize(Decimal("0.0001")), line_id

    @staticmethod
    async def _lock_invoice_line(tenant_collection, *, session, invoice_line_id: str) -> None:
        """5C-C26l Addendum K (WH55-C26L-1) — the per-line lock of a linked
        direct delivery, written in the movement transaction: one counter
        document per (tenant, invoice line) with a deterministic ``_id``, in
        the tenant's ``warehouse_ledger_counters`` (org_id-keyed, reached
        through the same TenantData as the ledger). Two transactions that
        deliver against the same line both write it → MongoDB aborts one
        with a WriteConflict and ``with_transaction`` re-runs it, so the
        covered-quantity decision always sees the other's committed row."""
        from app.services.invoice_line_lock import bump_line_lock
        await bump_line_lock(tenant_collection.tenant, invoice_line_id, session=session)

    @staticmethod
    async def _check_invoice_line_total(tenant_collection, inp: CommandInput, *,
                                        session) -> None:
        """5C-C26l Addendum L — FG-108 (D-04): the quantity of an invoice
        line covered through the canon is ALL its linked receipts — the
        warehouse receipts (later dispatched / accepted on a project) AND
        the direct deliveries. In the transaction, under the line lock:

          * the comparable linked quantity (receipts in the line's unit)
            already reaches the line's quantity → ANY further linked
            receipt, in any unit, is the same lot again → 409
            INVOICE_LINE_FULLY_LINKED (audit WH55-L-1);
          * a receipt in a unit other than the line's (no unit conversion
            is defined) → 422 INVOICE_LINE_UNIT_MISMATCH, refused up front
            instead of only flagged (PATH_B_LINK_QTY_UNVERIFIED stays for
            legacy data);
          * the linked receipts would exceed the line's quantity → 422
            INVOICE_LINE_QTY_EXCEEDED.
        Nothing is written on a refusal. An unknown line is the FG-53 debt
        for a warehouse receipt (a direct delivery of an unknown line is
        already refused)."""
        from app.services.canonical_material_cost import _norm_unit
        from app.services.invoice_line_lock import LINKED_RECEIPT_ACTIONS
        from app.services.warehouse_movements.errors import (
            InvoiceLineFullyLinkedError, InvoiceLineQuantityExceededError,
            InvoiceLineUnitMismatchError,
        )
        tenant = tenant_collection.tenant
        line = await tenant.invoice_lines.find_one(
            {"id": inp.invoice_line_id}, {"_id": 0, "qty": 1, "unit": 1}, session=session)
        if not line:
            return
        try:
            line_qty = Decimal(str(line.get("qty"))) if line.get("qty") is not None else None
        except Exception:
            line_qty = None
        if line_qty is not None and line_qty <= 0:
            line_qty = None
        unit = _norm_unit(line.get("unit"))
        linked = Decimal("0")
        from app.services.warehouse_movements.reversal import without_reversed
        rows = [row async for row in tenant_collection.find(
            {"action": {"$in": list(LINKED_RECEIPT_ACTIONS)},
             "invoice_line_id": inp.invoice_line_id},
            {"_id": 0, "movement_id": 1, "action": 1, "quantity": 1, "unit": 1,
             "idempotency_key": 1},
            session=session)]
        # WH-REV-01: a reversed receipt no longer covers the line.
        for row in await without_reversed(tenant_collection, rows, session=session):
            if inp.idempotency_key and row.get("idempotency_key") == inp.idempotency_key:
                return        # a replay of this very receipt — idempotency answers
            if unit == "" or _norm_unit(row.get("unit")) in ("", unit):
                linked += Decimal(str(row.get("quantity") or "0"))
        context = {"invoice_line_id": inp.invoice_line_id,
                   "line_qty": None if line_qty is None else str(line_qty),
                   "line_unit": line.get("unit"), "linked": str(linked),
                   "quantity": str(inp.quantity), "unit": inp.unit}
        if line_qty is not None and linked >= line_qty:
            raise InvoiceLineFullyLinkedError(
                "the invoice line is already fully received through linked receipts",
                context=context)
        if unit and _norm_unit(inp.unit) != unit:
            raise InvoiceLineUnitMismatchError(
                "the receipt's unit differs from the invoice line's unit "
                "(no unit conversion is defined)", context=context)
        if line_qty is not None and linked + Decimal(str(inp.quantity)) > line_qty:
            raise InvoiceLineQuantityExceededError(
                "the linked receipts would exceed the invoice line's quantity",
                context=context)

    @staticmethod
    async def _location_project(tenant_db, inp: CommandInput) -> Optional[str]:
        """The project the command's locations name (source first), DB-
        resolved; None when it touches no project. Used for the rights check
        when a binding was refused (FG-55)."""
        from app.services.warehouse_movements.legacy_gate import PROJECT_BY_INTENT
        for key in (inp.source, inp.destination, inp.transfer_target):
            if key is None:
                continue
            if key.location_type == LocationType.PROJECT:
                return key.location_id
            if key.location_type == LocationType.SUBPROJECT:
                try:
                    return await resolve_subproject_parent(
                        tenant_db, inp.tenant_id, key.location_id)
                except WarehouseMovementError:
                    return key.location_id
        return inp.project_id if inp.action in PROJECT_BY_INTENT else None

    @staticmethod
    async def _bind_project_from_locations(tenant_db, inp: CommandInput) -> None:
        """5C-C26h — FG-59 / FG-61: a body project_id must name a project the
        command's locations touch; it is never a source of scope by itself.
          * a receive-to-project / an acceptance into a PROJECT bucket is
            bound to that destination project;
          * a project_id that none of the locations names → 422 — except for
            the PROJECT_BY_INTENT actions (dispatch / reserve / release),
            whose target project has no location in the command.
        """
        from app.services.warehouse_movements.legacy_gate import PROJECT_BY_INTENT
        dst = inp.destination
        if inp.action in (CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT,
                          CanonicalAction.ACCEPT_PROJECT_DELIVERY) \
                and dst is not None and dst.location_type == LocationType.PROJECT:
            if inp.project_id and inp.project_id != dst.location_id:
                raise InvariantViolationError(
                    "project_id must be the destination project",
                    context={"destination": dst.to_dict(), "project_id": inp.project_id})
            inp.project_id = dst.location_id
            return
        if not inp.project_id or inp.action in PROJECT_BY_INTENT:
            return
        named = set()
        for key in (inp.source, inp.destination, inp.transfer_target):
            if key is None:
                continue
            if key.location_type == LocationType.PROJECT:
                named.add(key.location_id)
            elif key.location_type == LocationType.SUBPROJECT:
                named.add(await resolve_subproject_parent(
                    tenant_db, inp.tenant_id, key.location_id))
        if inp.project_id not in named:
            raise InvariantViolationError(
                "project_id does not match the locations of the movement",
                context={"project_id": inp.project_id})

    @staticmethod
    async def _bind_subproject_parent(tenant_db, inp: CommandInput) -> None:
        """5C-C26d — audit C26B-1 / FLOW Guard FG-38 (HIGH).

        The project of an action that touches a SUBPROJECT bucket is the
        subproject's PARENT, read from the tenant's ``projects`` collection
        (``parent_project_id``) — never trusted from the body. A
        ``project_id`` that names another project is refused (422) before
        the permission gate and before any write; permissions (generic gate,
        Р27) are then decided against the real project. The subproject that
        decides is the source (an outbound move), else the destination /
        transfer target (an acceptance, a direct delivery).
        """
        # 5C-C26f — FG-53: a move FROM A PROJECT (consume, transfer, write-off,
        # quarantine, …) belongs to the source project bucket — never to a
        # body project_id; one naming another project → 422. (Whether a
        # project bucket names an existing project is not checked here — the
        # same as for a destination; recorded in HANDOFF 5C-C26f.)
        src0 = inp.source
        if src0 is not None and src0.location_type == LocationType.PROJECT:
            if inp.project_id and inp.project_id != src0.location_id:
                raise InvariantViolationError(
                    "project_id must be the source project",
                    context={"source": src0.to_dict(), "project_id": inp.project_id})
            inp.project_id = src0.location_id
        subs = [k for k in (inp.source, inp.destination, inp.transfer_target)
                if k is not None and k.location_type == LocationType.SUBPROJECT]
        if not subs:
            return
        parents = {}
        for key in subs:                      # every subproject must resolve
            parents[key.location_id] = await resolve_subproject_parent(
                tenant_db, inp.tenant_id, key.location_id)
        src = inp.source
        if src is not None and src.location_type == LocationType.PROJECT:
            # 5C-C26e (C26D-L1): the move LEAVES a project — its project is
            # the source; a subproject target (of any project) only has to
            # resolve in this tenant, it does not rebind project_id.
            return
        if src is not None and src.location_type == LocationType.SUBPROJECT:
            decider = src
        else:
            decider = subs[0]                 # acceptance / direct delivery
        parent = parents[decider.location_id]
        if inp.project_id and inp.project_id != parent:
            raise InvariantViolationError(
                "project_id must be the parent project of the subproject",
                # FG-55: the parent id is not disclosed (the rights check
                # has not run yet) — only what the caller sent.
                context={"subproject_id": decider.location_id,
                         "project_id": inp.project_id})
        inp.project_id = parent
        if not inp.subproject_id:
            inp.subproject_id = decider.location_id
        elif inp.subproject_id not in parents:
            raise InvariantViolationError(
                "subproject_id must be the subproject bucket of the movement",
                context={"subproject_id": inp.subproject_id,
                         "buckets": sorted(parents)})

    @staticmethod
    def _bind_write_off_project(inp: CommandInput) -> None:
        """5C-C21 F-12 (Р10) — a WRITE_OFF from a project bucket is project
        cost (ред „фира“). The project it belongs to is derived from the
        source bucket, never trusted from the body: for a PROJECT source
        `project_id` is the source id (a different one is refused); a
        SUBPROJECT source must name its project. A write-off from a
        warehouse is not project cost and may not carry a project_id
        (it would otherwise read as one).
        """
        if inp.action != CanonicalAction.WRITE_OFF:
            return
        src = inp.source
        if src is None:
            return  # refused later: outbound action requires a source
        if src.location_type == LocationType.PROJECT:
            if inp.project_id and inp.project_id != src.location_id:
                raise InvariantViolationError(
                    "write_off project_id must be the source project",
                    context={"source": src.to_dict(), "project_id": inp.project_id},
                )
            inp.project_id = src.location_id
        elif src.location_type == LocationType.SUBPROJECT:
            if not inp.project_id:
                raise InvariantViolationError(
                    "write_off from a subproject requires its project_id",
                    context={"source": src.to_dict()},
                )
        elif inp.project_id:
            raise InvariantViolationError(
                "a write_off from a non-project location is not project cost "
                "and cannot carry a project_id",
                context={"source": src.to_dict(), "project_id": inp.project_id},
            )

    async def _enforce_transfer_acceptance_target(
        self, tenant_collection, *, session, inp: CommandInput,
    ) -> None:
        """5C-C21 F-13 / 5C-C25 (Р18) — an acceptance against ANY transfer
        must land in exactly the transfer's target (location and state).
        Re-checked inside the transaction against the dispatch row read in
        the same session (the pre-gate binding read it outside)."""
        dispatch = await tenant_collection.find_one(
            {"movement_id": inp.dispatch_movement_id},
            {"action": 1, "transfer_target": 1, "project_id": 1, "_id": 0},
            session=session,
        )
        if not dispatch or self.TRANSFER_RULES.get(
                _action_or_none(dispatch.get("action"))) is None:
            return
        self._check_transfer_acceptance(inp, dispatch)

    def _enforce_state_rule_outside_tx(self, inp: CommandInput) -> None:
        action = inp.action
        dest = inp.destination
        src = inp.source
        if action == CanonicalAction.QUARANTINE_ENTRY:
            if dest is None or dest.state != MovementState.QUARANTINE:
                raise QuarantineStateViolationError(
                    "quarantine_entry must target state=quarantine",
                )
        if action == CanonicalAction.QUARANTINE_RELEASE:
            if src is None or src.state != MovementState.QUARANTINE:
                raise QuarantineStateViolationError(
                    "quarantine_release must source state=quarantine",
                )
            # CODEX C11.5 — release destination MUST be free (or
            # redirect to another non-quarantine state). Dropping back
            # into quarantine is a no-op; the resolver must pick a real
            # disposition.
            if dest is None or dest.state == MovementState.QUARANTINE:
                raise QuarantineStateViolationError(
                    "quarantine_release destination must leave quarantine",
                )
        # 5C-C25 (Р18) — project → warehouse returns go "в път" and are
        # accepted into the warehouse QUARANTINE state; the shape is
        # enforced by `_force_transfer_into_transit` / the acceptance
        # binding, before this point.

    async def _next_ledger_sequence(
        self, tenant_collection, *, tenant_id: str, session,
    ) -> int:
        """Monotonic per-tenant sequence for ledger ordering.

        CODEX C12.3 — switched from read-max+1 to an atomic counter
        via `find_one_and_update` on a per-tenant counter doc. Prior
        implementation raced under 10+ concurrent writes and exhausted
        `_MAX_RETRIES` (test_cross_item_audit_chain_integrity).

        The counter doc lives in a dedicated `warehouse_ledger_counters`
        collection. The `$inc` is atomic even inside a replica-set
        transaction: concurrent writers each see their own
        monotonically distinct value with no gaps and no duplicates.
        """
        from pymongo import ReturnDocument
        # 5C-C18 (A2C/A1): the counter is an org_id-keyed tenant collection;
        # it is reached through the SAME TenantData that scopes the ledger
        # collection (server-resolved tenant), so the filter and the upserted
        # document carry `org_id` — never a raw handle.
        tenant = tenant_collection.tenant
        if tenant.org_id != tenant_id:
            raise InvariantViolationError(
                "ledger counter tenant does not match the command tenant",
            )
        doc = await tenant.warehouse_ledger_counters.find_one_and_update(
            {"tenant_id": tenant_id, "name": "ledger_sequence"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        return int(doc["value"]) if doc else 1

    async def _split_dispatch_for_acceptance(
        self, tenant_collection, *, session, tenant_id: str,
        dispatch_movement_id: str, accepted_qty: Decimal,
    ):
        """Rule B / F-09=B — take the REMAINING dispatch layers oldest first
        (Р21, 5C-C25 Addendum A; CODEX C11.4 cumulative-partial correction).

        Semantics:
          * dispatch recorded N original layers summing to `dispatched_qty`;
          * prior partial acceptances against this dispatch consumed a
            subset of those layers (per their own `layer_allocations`);
          * this acceptance must take `accepted_qty` units from what is
            LEFT, oldest layer first, each at its own price (Р21).

        A naive "accepted_qty / dispatched_qty" fraction (the C01 code)
        broke the second partial — e.g. 10 dispatched, accept 8 then
        accept 2: the first takes 8/10 of each layer, the second would
        again take 2/10 of the ORIGINAL layers = wrong provenance.
        """
        dispatch = await tenant_collection.find_one(
            {"movement_id": dispatch_movement_id}, session=session,
        )
        if not dispatch:
            raise OriginAcceptanceOverrunError(
                "dispatch_movement_id does not point at a known dispatch",
                context={"dispatch_movement_id": dispatch_movement_id})
        dispatched = Decimal(str(dispatch.get("quantity", "0")))
        if dispatched <= 0:
            raise InvariantViolationError(
                "dispatch has zero quantity",
                context={"dispatch_movement_id": dispatch_movement_id})

        orig_layers = dispatch.get("layer_allocations", [])
        if not orig_layers:
            raise InvariantViolationError(
                "dispatch has no layer_allocations to split",
                context={"dispatch_movement_id": dispatch_movement_id})

        # Current per-layer remaining capacity: orig - sum(prior acceptances on it).
        remaining_per_layer: Dict = {}
        for layer in orig_layers:
            key = (str(layer["source_movement_id"]), int(layer["layer_sequence"]))
            remaining_per_layer[key] = {
                "remaining": Decimal(str(layer["quantity"])),
                "unit_value": Decimal(str(layer["unit_value"])),
                "currency": str(layer.get("currency", "BGN")),
                "source_movement_id": key[0],
                "layer_sequence": key[1],
            }

        # Scan prior acceptances for this dispatch and subtract their
        # per-layer consumption.
        prior_total = Decimal("0")
        cursor = tenant_collection.find({
            "tenant_id": tenant_id,
            "dispatch_movement_id": dispatch_movement_id,
            "action": CanonicalAction.ACCEPT_PROJECT_DELIVERY.value,
        }, session=session)
        async for d in cursor:
            prior_total += Decimal(str(d.get("accepted_quantity")
                                       or d.get("quantity") or "0"))
            for alloc in d.get("layer_allocations", []):
                k = (str(alloc["source_movement_id"]),
                     int(alloc["layer_sequence"]))
                if k in remaining_per_layer:
                    remaining_per_layer[k]["remaining"] -= Decimal(
                        str(alloc["quantity"]))

        if prior_total + accepted_qty > dispatched:
            raise OriginAcceptanceOverrunError(
                "accepted + resolutions exceed dispatched quantity",
                context={"dispatched": str(dispatched),
                         "already_resolved": str(prior_total),
                         "proposed_accept": str(accepted_qty)})

        # Available = Σ remaining across all layers.
        available = sum(
            (v["remaining"] for v in remaining_per_layer.values()
             if v["remaining"] > 0),
            Decimal("0"),
        )
        if accepted_qty > available:
            # Should be caught by prior_total guard, but defend
            # explicitly in case of projection skew.
            raise OriginAcceptanceOverrunError(
                "requested acceptance exceeds remaining dispatch capacity",
                context={"available": str(available),
                         "requested": str(accepted_qty)})

        # 5C-C25 Addendum A — Р21 (Крум 06.11.2026, D-55-PRORATA): no
        # averaging between batches. The accepted quantity takes the
        # REMAINING dispatched layers in their order, oldest first, each at
        # its own price; the unaccepted remainder keeps the leftover layers
        # (`_open_transit_discrepancy`). Before C25 the split was pro-rata
        # across all remaining layers. The total is conserved either way.
        # The dispatch's own allocation list is already in FIFO order
        # (5C-C24: never re-sort by `layer_sequence`).
        split: List[LayerAllocation] = []
        total_value = Decimal("0")
        total_qty = Decimal("0")
        for k in remaining_per_layer.keys():
            info = remaining_per_layer[k]
            rem = info["remaining"]
            need = accepted_qty - total_qty
            if need <= 0:
                break
            if rem <= 0:
                continue
            take = min(rem, need)
            split.append(LayerAllocation(
                source_movement_id=info["source_movement_id"],
                layer_sequence=info["layer_sequence"],
                quantity=take,
                unit_value=info["unit_value"],
                currency=info["currency"],
            ))
            total_value += take * info["unit_value"]
            total_qty += take

        if total_qty != accepted_qty:
            # Final safety: fail-closed on a split mismatch.
            raise InvariantViolationError(
                "Rule B split did not reconcile to accepted_qty",
                context={"accepted": str(accepted_qty),
                         "split_total": str(total_qty)})

        return split, total_value.quantize(Decimal("0.0001"))

    async def _open_in_transit_inbound(
        self, tenant_collection, *, session,
        dispatch_env: MovementEnvelope, dispatch_row: Dict[str, Any],
        allocations: Sequence[LayerAllocation],
    ) -> None:
        """Historical hook — no-op in C11+ (behavior moved).

        Prior to CODEX C11, this helper was intended to insert a
        mirrored IN_TRANSIT inbound row. That logic now lives in the
        projector (`projections._open_in_transit`) which reads
        `env.layer_allocations` directly from the dispatch envelope,
        and in `item_balance_by_location` which treats
        `destination=in_transit` as the credit side at projection
        time. The stub remains to document the migration — any new
        call site should use the projector path.
        """
        return None

    async def _open_transit_discrepancy(
        self, tenant_collection, *, session, env: MovementEnvelope,
        missing_quantity: Decimal, dispatch_movement_id: str,
    ) -> str:
        """Append a non-moving `transit_discrepancy` row for the
        unresolved remainder of a partial acceptance (contract §4.4).

        CODEX C11.4 — the row MUST carry proportional original
        value/layers so the unresolved value is traceable; a bare
        `unit_value=0` with empty allocations loses the layer provenance
        a later resolution needs. We compute remainder layers from the
        dispatch's recorded layer_allocations minus prior acceptances
        minus the current acceptance's share.
        """
        dispatch = await tenant_collection.find_one(
            {"movement_id": dispatch_movement_id}, session=session,
        )
        remainder_layers = []
        remainder_value = Decimal("0")
        if dispatch:
            # Remaining capacity per layer AFTER the just-written
            # acceptance has consumed its share.
            remaining_per_layer: Dict = {}
            for layer in dispatch.get("layer_allocations", []):
                key = (str(layer["source_movement_id"]),
                       int(layer["layer_sequence"]))
                remaining_per_layer[key] = {
                    "remaining": Decimal(str(layer["quantity"])),
                    "unit_value": Decimal(str(layer["unit_value"])),
                    "currency": str(layer.get("currency", "BGN")),
                    "source_movement_id": key[0],
                    "layer_sequence": key[1],
                }
            # Subtract every prior acceptance (including this one — it
            # has already been inserted in the same session).
            cursor = tenant_collection.find({
                "tenant_id": env.tenant_id,
                "dispatch_movement_id": dispatch_movement_id,
                "action": CanonicalAction.ACCEPT_PROJECT_DELIVERY.value,
            }, session=session)
            async for d in cursor:
                for alloc in d.get("layer_allocations", []):
                    k = (str(alloc["source_movement_id"]),
                         int(alloc["layer_sequence"]))
                    if k in remaining_per_layer:
                        remaining_per_layer[k]["remaining"] -= Decimal(
                            str(alloc["quantity"]))

            # 5C-C24: dispatch allocation order (FIFO), see the split.
            for key in remaining_per_layer.keys():
                info = remaining_per_layer[key]
                if info["remaining"] <= 0:
                    continue
                remainder_layers.append({
                    "source_movement_id": info["source_movement_id"],
                    "layer_sequence": info["layer_sequence"],
                    "quantity": str(info["remaining"]),
                    "unit_value": str(info["unit_value"]),
                    "currency": info["currency"],
                })
                remainder_value += info["remaining"] * info["unit_value"]

        # Weighted average remainder unit value (preserve `pending`
        # value_status for FLOW-009 Rule B when layers are also pending).
        unit_value = (
            (remainder_value / missing_quantity).quantize(Decimal("0.0001"))
            if missing_quantity > 0 else Decimal("0")
        )

        mv_id = f"mv_{uuid.uuid4().hex}"
        row = {
            "movement_id": mv_id,
            "tenant_id": env.tenant_id,
            "action": "transit_discrepancy",
            "recorded_at": _now_iso(),
            "occurred_at": _now_iso(),
            "item_id": env.item_id,
            "unit": env.unit,
            "quantity": str(missing_quantity),
            "unit_value": str(unit_value),
            "currency": env.currency,
            "source": {"location_type": LocationType.IN_TRANSIT.value,
                       "location_id": dispatch_movement_id,
                       "state": MovementState.UNRESOLVED.value},
            "destination": None,
            "dispatch_movement_id": dispatch_movement_id,
            "partial_resolution_of": dispatch_movement_id,
            "actor_id": env.actor_id,
            "idempotency_key": f"{env.idempotency_key}:unresolved",
            "project_id": env.project_id,
            "status": "under_investigation",
            # v6 §4.1: `pending_invoice` is for invoice-flow timing;
            # here we use `under_investigation` because the quantity is
            # physically unresolved — value provenance is preserved on
            # `layer_allocations`.
            "value_status": "under_investigation",
            "ledger_sequence": None,     # patched below
            "layer_allocations": remainder_layers,
            "total_value": str(remainder_value.quantize(Decimal("0.0001"))),
            "file_ids": [],
            "notes": "unresolved partial-acceptance remainder (Rule B)",
        }
        seq = await self._next_ledger_sequence(
            tenant_collection, tenant_id=env.tenant_id, session=session,
        )
        row["ledger_sequence"] = seq
        await tenant_collection.insert_one(row, session=session)
        return mv_id

    async def _append_discrepancy_resolution(
        self, tenant_collection, *, session, env: MovementEnvelope,
        dispatch_movement_id: str,
        resolved_discrepancy_movement_id: str,
        resolving_acceptance_movement_id: str,
    ) -> str:
        """CODEX C13.2 — Append-only Rule B resolution fact.

        When the cumulative acceptance of a dispatch has closed the
        lot (`missing_quantity == 0`), each previously open
        `transit_discrepancy` row for that dispatch is CLOSED by an
        append-only `discrepancy_resolved` ledger row.

        The ledger stays immutable — no update to the original
        discrepancy row. The projector observes `discrepancy_resolved`
        rows and:
          * removes the matching entry from
            `warehouse_in_transit.unresolved_discrepancies`;
          * flips the `discrepancy_status` field on the matching
            `transit_discrepancy` projection shim to `"resolved"`
            (projection-side flag only; the ledger row keeps
            `status="under_investigation"` as its historical fact).

        The row is itself part of the per-tenant hash chain via its
        own ledger_sequence; a replay sees acceptance → discrepancy →
        resolution in the same order and the active projection
        rebuilds correctly.
        """
        mv_id = f"mv_{uuid.uuid4().hex}"
        row = {
            "movement_id": mv_id,
            "tenant_id": env.tenant_id,
            "action": "discrepancy_resolved",
            "recorded_at": _now_iso(),
            "occurred_at": _now_iso(),
            "item_id": env.item_id,
            "unit": env.unit,
            "quantity": "0",
            "unit_value": "0",
            "currency": env.currency,
            "source": None,
            "destination": None,
            "dispatch_movement_id": dispatch_movement_id,
            "resolves_discrepancy_movement_id": resolved_discrepancy_movement_id,
            "resolved_by_acceptance_movement_id": resolving_acceptance_movement_id,
            "actor_id": env.actor_id,
            "idempotency_key": (
                f"{env.idempotency_key}:resolve:"
                f"{resolved_discrepancy_movement_id}"
            ),
            "project_id": env.project_id,
            "status": "resolved",
            "value_status": "resolved",
            "ledger_sequence": None,
            "layer_allocations": [],
            "total_value": "0",
            "file_ids": [],
            "notes": (
                f"Rule B closure: cumulative acceptance of dispatch "
                f"{dispatch_movement_id} reached requested quantity; "
                f"discrepancy {resolved_discrepancy_movement_id} is "
                f"resolved (append-only fact)."
            ),
        }
        seq = await self._next_ledger_sequence(
            tenant_collection, tenant_id=env.tenant_id, session=session,
        )
        row["ledger_sequence"] = seq
        await tenant_collection.insert_one(row, session=session)
        return mv_id
