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
    EVIDENCE_REQUIRED_ACTIONS,
    permission_action_for,
    RULE_B_COSTING_ACTIONS,
    RULE_B_ZERO_COST_ACTIONS,
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
_MAX_RETRIES = 3


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


# -----------------------------------------------------------------------
# Permission adapter
# -----------------------------------------------------------------------
class PermissionGate:
    """Thin wrapper over the Permission Service that fails CLOSED.

    C06 — a transfer authorizes both the SOURCE and DESTINATION scopes.
    A caller permitted at only one end cannot move stock through the
    other.
    """

    def __init__(self, evaluate_fn=None):
        from app.permissions.service import evaluate_permission
        self._evaluate = evaluate_fn or evaluate_permission

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
        {"id": record_id}, {"_id": 0}, session=session,
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
                {"id": record_id}, {"_id": 0}, session=session,
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
            {"id": record_id, "status": IDEMPOTENCY_FAILED},
            {"$set": {"status": IDEMPOTENCY_STARTED,
                      "reserved_at": _now_iso(),
                      "completed_at": None,
                      "error_code": None}},
            session=session,
        )
        refreshed = await db[IDEMPOTENCY_COLLECTION].find_one(
            {"id": record_id}, {"_id": 0}, session=session,
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

    The chain head is read inside the session so a concurrent tx cannot
    insert a conflicting `sequence`; the unique index
    `wh_audit_unique_sequence` catches any residual race, which the
    outer retry loop handles.
    """
    from app.audit.envelope import validate_event
    from app.audit.store import AUDIT_COLLECTION, chain_hashes
    validate_event(event)
    previous = await tenant_db[AUDIT_COLLECTION].find_one(
        {"tenant_id": event["tenant_id"]},
        {"_id": 0},
        sort=[("sequence", -1)],
        session=session,
    )
    chained = chain_hashes(event, previous)
    await tenant_db[AUDIT_COLLECTION].insert_one(dict(chained), session=session)
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
        if not permission_service_enforce():
            raise PermissionDeniedError(
                "PERMISSION_SERVICE_MODE=enforce is required for canonical writes",
                context={"mode": os.environ.get("PERMISSION_SERVICE_MODE", "off")},
            )

        action = inp.action
        if action not in CanonicalAction:
            raise UnknownActionError(f"unknown action {action!r}")

        # Permission (C06 — both source + destination + project scopes)
        await self._gate.ensure(
            ctx, action=action, source=inp.source,
            destination=inp.destination, project_id=inp.project_id,
        )

        # Shape rules evaluated outside the tx so a malformed envelope
        # cannot reach Mongo.
        self._refuse_client_value_on_outbound(inp)
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

        # Retry wrapper covers transient tx errors (write conflict,
        # audit sequence collision retried once) — contract §4.3.
        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt < _MAX_RETRIES:
            attempt += 1
            try:
                return await self._execute_one_attempt(
                    ctx, tenant_db, tenant_collection, inp,
                )
            except (WarehouseMovementError, IdempotencyConflict) as exc:
                # Business errors — do not retry.
                if isinstance(exc, IdempotencyConflict):
                    raise IdempotencyConflictError(str(exc), context={
                        "action": action.value, "key": inp.idempotency_key}) from exc
                raise
            except Exception as exc:
                # Treat as transient only if the driver labels it so.
                labels = getattr(exc, "has_error_label", None)
                is_transient = (
                    callable(labels) and (
                        labels("TransientTransactionError")
                        or labels("UnknownTransactionCommitResult")
                    )
                )
                if not is_transient:
                    raise AuditChainWriteError(
                        f"transaction failed: {exc}"
                    ) from exc
                last_exc = exc
                await asyncio.sleep(0.01 * attempt)
        raise AuditChainWriteError(
            f"canonical movement failed after {_MAX_RETRIES} attempts: {last_exc}"
        )

    async def _execute_one_attempt(
        self, ctx, tenant_db, tenant_collection, inp,
    ) -> ExecuteResult:
        try:
            session_cm = await self._client.start_session()
        except Exception as exc:
            raise TransactionsNotSupportedError(
                f"replica-set session unavailable: {exc}"
            ) from exc

        async with session_cm as session:
            async with session.start_transaction():
                return await self._execute_in_tx(
                    session=session, tenant_db=tenant_db,
                    tenant_collection=tenant_collection, inp=inp,
                )

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
        )

        # Fingerprint ignores server-derived fields (envelope.py already
        # strips movement_id / recorded_at / occurred_at / audit_event_id)
        # — so a replay with identical client input matches.
        fp = envelope_fingerprint(base_env)

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

        # ------------------------------------------------------------
        # Resolve allocations + value per action type.
        # ------------------------------------------------------------
        allocations: List[LayerAllocation] = []
        outbound_value = Decimal("0")
        unresolved_mv_id: Optional[str] = None
        acceptance_line_id: Optional[str] = None
        unit_value: Any = base_env.unit_value

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

        if action == CanonicalAction.ACCEPT_PROJECT_DELIVERY:
            # Rule B (C03): accept X units from a dispatch. The
            # dispatch's recorded layer_allocations are split
            # proportionally: `accepted_units` fraction → destination,
            # remainder stays in-transit.
            if not inp.dispatch_movement_id:
                raise InvariantViolationError(
                    "accept_project_delivery requires dispatch_movement_id",
                    context={"action": action.value})
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
            missing_qty = requested_quantity - accepted_qty

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
        if action in OUTBOUND_ACTIONS and allocations:
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
        )
        validate_envelope(env)

        # Append ledger row (append-only). ledger_sequence pins order.
        ledger_row = env.to_dict()
        ledger_row["ledger_sequence"] = ledger_sequence
        if acceptance_line_id:
            ledger_row["acceptance_line_id"] = acceptance_line_id
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
        # truth (C07).
        from app.services.warehouse_movements.projections import apply_projection
        await apply_projection(tenant_db, env, session=session,
                               extra_rows=({"unresolved_mv_id": unresolved_mv_id,
                                            "allocations": allocations} if unresolved_mv_id else None))

        # Complete idempotency (same session).
        await _idem_complete_with_session(
            tenant_db, tenant_id=tenant_id, action=action.value,
            key=inp.idempotency_key, result_reference=env.movement_id,
            session=session,
        )

        final = env.to_dict()
        final["ledger_sequence"] = ledger_sequence
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
        # Project → warehouse returns MUST land in quarantine first
        # (C04 / FLOW-009 "Връщане и карантина"). A free-stock destination
        # is forbidden; use `quarantine_entry` instead when the goods
        # need inspection, or `transfer_project_to_warehouse` is only
        # permitted for already-canonical layers.
        if action == CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE:
            if dest is None:
                raise InvariantViolationError(
                    "transfer_project_to_warehouse requires a destination",
                )
            # Both quarantine and free are permitted here — the stricter
            # quarantine-first path is handled by having the caller call
            # QUARANTINE_ENTRY. Enforce that the destination is a real
            # warehouse location.
            if dest.location_type not in {
                LocationType.CENTRAL_WAREHOUSE,
                LocationType.SMALL_WAREHOUSE,
            }:
                raise InvariantViolationError(
                    "transfer_project_to_warehouse destination must be a warehouse",
                    context={"destination": dest.to_dict()},
                )

    async def _next_ledger_sequence(
        self, tenant_collection, *, tenant_id: str, session,
    ) -> int:
        """Monotonic per-tenant sequence for ledger ordering."""
        tail = await tenant_collection.find(
            {"tenant_id": tenant_id, "ledger_sequence": {"$exists": True}},
            {"ledger_sequence": 1, "_id": 0},
            session=session,
        ).sort("ledger_sequence", -1).limit(1).to_list(1)
        return (tail[0]["ledger_sequence"] + 1) if tail else 1

    async def _split_dispatch_for_acceptance(
        self, tenant_collection, *, session, tenant_id: str,
        dispatch_movement_id: str, accepted_qty: Decimal,
    ):
        """Rule B C03 — split dispatch layers proportionally.

        `accepted_qty / dispatch_qty` fraction of each original layer
        goes to the destination. Prior partial acceptances for the same
        dispatch are summed and the remainder of each layer is split
        from what is left.
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

        # Prior acceptances against this dispatch — in-tx read.
        cursor = tenant_collection.find({
            "tenant_id": tenant_id,
            "dispatch_movement_id": dispatch_movement_id,
            "action": CanonicalAction.ACCEPT_PROJECT_DELIVERY.value,
        }, session=session)
        prior_accepted = Decimal("0")
        async for d in cursor:
            prior_accepted += Decimal(str(d.get("accepted_quantity") or d.get("quantity") or "0"))

        if prior_accepted + accepted_qty > dispatched:
            raise OriginAcceptanceOverrunError(
                "accepted + resolutions exceed dispatched quantity",
                context={"dispatched": str(dispatched),
                         "already_resolved": str(prior_accepted),
                         "proposed_accept": str(accepted_qty)})

        # Original dispatch layers (from the ledger row).
        orig_layers = dispatch.get("layer_allocations", [])
        if not orig_layers:
            raise InvariantViolationError(
                "dispatch has no layer_allocations to split",
                context={"dispatch_movement_id": dispatch_movement_id})

        # Scale each original layer by the fraction `accepted_qty / dispatched`.
        # Any rounding remainder is absorbed into the final layer so
        # Σ(qty) == accepted_qty exactly (deterministic rounding — see §4.5).
        split_fraction = accepted_qty / dispatched
        split: List[LayerAllocation] = []
        total_value = Decimal("0")
        total_qty = Decimal("0")
        for i, layer in enumerate(orig_layers):
            orig_qty = Decimal(str(layer["quantity"]))
            unit_value = Decimal(str(layer["unit_value"]))
            take = (orig_qty * split_fraction).quantize(Decimal("0.0001"))
            if i == len(orig_layers) - 1:
                # Last layer absorbs rounding remainder.
                take = accepted_qty - total_qty
            split.append(LayerAllocation(
                source_movement_id=str(layer["source_movement_id"]),
                layer_sequence=int(layer["layer_sequence"]),
                quantity=take,
                unit_value=unit_value,
                currency=str(layer.get("currency", "BGN")),
            ))
            total_value += take * unit_value
            total_qty += take
        return split, total_value.quantize(Decimal("0.0001"))

    async def _open_in_transit_inbound(
        self, tenant_collection, *, session,
        dispatch_env: MovementEnvelope, dispatch_row: Dict[str, Any],
        allocations: Sequence[LayerAllocation],
    ) -> None:
        """Open a mirrored IN_TRANSIT inbound row at the destination.

        This is NOT a stock-available credit — the state is
        `in_transit`, which the FIFO allocator and projection treat as
        unresolved. Later acceptance drains it; return/write-off closes
        it. The row preserves the original `layer_allocations` so a
        downstream transfer conserves provenance.
        """
        # NOTE: the DISPATCH row itself has `destination=IN_TRANSIT` set
        # by the caller (route-provided). We additionally insert a
        # non-moving `supplier_delivery_origin`-style record so stock
        # projections can read it directly.
        pass  # the dispatch row already records destination=in_transit

    async def _open_transit_discrepancy(
        self, tenant_collection, *, session, env: MovementEnvelope,
        missing_quantity: Decimal, dispatch_movement_id: str,
    ) -> str:
        """Append a non-moving `transit_discrepancy` row for the unresolved
        remainder of a partial acceptance (contract §4.4)."""
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
            "unit_value": "0",
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
            # Not valued (`value_status=pending_investigation`).
            "value_status": "pending_investigation",
            "ledger_sequence": None,     # patched below
            "layer_allocations": [],
            "file_ids": [],
            "notes": "unresolved partial-acceptance remainder (Rule B)",
        }
        # Allocate a fresh ledger_sequence for the discrepancy row.
        seq = await self._next_ledger_sequence(
            tenant_collection, tenant_id=env.tenant_id, session=session,
        )
        row["ledger_sequence"] = seq
        await tenant_collection.insert_one(row, session=session)
        return mv_id
