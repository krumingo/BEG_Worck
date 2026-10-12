"""
ONE canonical warehouse movement command service.

This module is the ONLY writer to `warehouse_transactions` in the TASK 5C
world. Every physical fact — a receive, a dispatch, an acceptance, a
quarantine entry, a revision — passes through `execute()` and lands as a
single append-only row inside one Mongo replica-set transaction with:

  1. permission check     (deny-by-default, enforce mode required)
  2. envelope validation  (§4.1 schema)
  3. index verification   (fail-closed on missing index)
  4. idempotency claim    (atomic reservation, replay vs conflict)
  5. invariant guard      (negative stock, origin acceptance overrun,
                           quarantine state violation, Rule B conservation)
  6. FIFO allocation      (outbound: server-only unit value, exact layers)
  7. ledger append        (`warehouse_transactions.insert_one`, session)
  8. projection update    (warehouse_batches as a projector)
  9. canonical AuditEvent (`audit_events` chain append; failure rolls back)
 10. idempotency complete (`audit_idempotency` state → completed)

If any step fails, the whole transaction aborts and nothing is left behind
(the audit chain, the ledger row, the projection and the idempotency state
are all inside the same session).

Legacy writers never reach this module; they are refused at their own
route by `legacy_inventory.LegacyWriterGuard`.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.audit.envelope import (
    build_event,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RETENTION_R1_CRITICAL_BUSINESS,
    ACTOR_HUMAN,
)
from app.audit.store import record_event
from app.audit.idempotency import (
    begin_idempotent,
    complete_idempotent,
    IdempotencyConflict,
    IDEMPOTENCY_DUPLICATE,
    IDEMPOTENCY_STARTED,
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


@dataclass
class CommandInput:
    """What a caller hands to the service — minimal, no server-controlled
    fields. The service builds the envelope itself.

    `item_id`, `unit` and `tenant_id` are required.
    `quantity` must be positive.
    For outbound actions, `unit_value` and `layer_allocations` are
    IGNORED on input and derived server-side.
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
    unit_value: Any = Decimal("0")      # inbound only (client-supplied purchase price)
    currency: str = "BGN"
    lot_id: Optional[str] = None
    request_id: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_line_id: Optional[str] = None
    delivery_id: Optional[str] = None
    dispatch_movement_id: Optional[str] = None
    reservation_movement_id: Optional[str] = None
    project_id: Optional[str] = None
    subproject_id: Optional[str] = None
    smr_id: Optional[str] = None
    work_package_id: Optional[str] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[str] = None
    correlation_id: Optional[str] = None
    requested_quantity: Any = None      # on acceptance
    accepted_quantity: Any = None       # on acceptance
    file_ids: Optional[List[str]] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    corrects_movement_id: Optional[str] = None
    revision_evidence: Optional[Dict[str, Any]] = None
    occurred_at: Optional[str] = None
    item_is_pending_mapping: bool = False   # FLOW-032: free-text still


# -----------------------------------------------------------------------
# Permission adapter — small, swappable for tests
# -----------------------------------------------------------------------
class PermissionGate:
    """Thin wrapper over the Permission Service that fails CLOSED.

    Enforce mode is the only one in which this service writes: `shadow`
    and `off` block the write at the route layer, so by the time the
    service is reached the caller must already be in enforce.
    """

    def __init__(self, evaluate_fn=None):
        from app.permissions.service import evaluate_permission
        self._evaluate = evaluate_fn or evaluate_permission

    async def ensure(
        self,
        ctx,
        *,
        action: CanonicalAction,
        location: Optional[LocationKey],
        project_id: Optional[str],
    ) -> None:
        if ctx is None:
            raise PermissionDeniedError("missing tenant context",
                                        context={"action": action.value})
        permission_name = permission_action_for(action)
        # Prefer project scope when a project id is present; otherwise
        # fall back to location scope (warehouse id). Deny-by-default:
        # a role without this exact action on this exact scope is refused.
        scope_type = None
        scope_id = None
        if project_id:
            scope_type, scope_id = "project", project_id
        elif location is not None:
            scope_type, scope_id = "location", location.location_id
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


# -----------------------------------------------------------------------
# Capability sentinels — fail-closed when W0 prerequisites are missing
# -----------------------------------------------------------------------
def file_registry_available() -> bool:
    """Return True iff W0-06 File Registry is available for this process."""
    return os.environ.get("FILE_REGISTRY_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def approval_runtime_available() -> bool:
    """Return True iff W0-07 Approval runtime is available for this process."""
    return os.environ.get("APPROVAL_RUNTIME_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def permission_service_enforce() -> bool:
    """TASK 5C: all consequential writes require enforce mode."""
    return os.environ.get("PERMISSION_SERVICE_MODE", "").strip().lower() == "enforce"


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
    ) -> None:
        """
        `db_client` is a Motor client (not a database). We open sessions on
        the client so a single transaction can span the operational db
        (ledger, projection, idempotency) and the audit db — in BEG_Work
        those are the same database per tenant, which keeps the whole
        operation atomic.

        `verify_indexes_once`: when True (default) the service remembers
        the first successful verification per db-name so repeated calls do
        not pay the cost; tests can set False to re-verify every call.
        """
        self._client = db_client
        self._gate = gate or PermissionGate()
        self._verify_once = verify_indexes_once
        self._verified: set = set()

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

        # 1. Permission (per-action, per-scope)
        await self._gate.ensure(
            ctx, action=action,
            location=inp.destination or inp.source,
            project_id=inp.project_id,
        )

        # 2. Identity (FLOW-032): no actionable stock without item_id/unit;
        # pending-mapping may only enter quarantine.
        self._enforce_identity(inp)

        # 3. Evidence prerequisites (W0-06 File Registry)
        if action in EVIDENCE_REQUIRED_ACTIONS and not inp.file_ids:
            raise FileRegistryUnavailableError(
                "evidence file_ids are required for this action; "
                "File Registry (W0-06) is not available",
                context={"action": action.value},
            )
        if action in EVIDENCE_REQUIRED_ACTIONS and not file_registry_available():
            raise FileRegistryUnavailableError(
                "File Registry (W0-06) must be enabled before evidence-mandatory writes",
                context={"action": action.value},
            )

        # 4. Server-only value: refuse client-supplied unit_value on outbound
        if action in OUTBOUND_ACTIONS and inp.unit_value and Decimal(str(inp.unit_value)) > 0:
            raise ValueFromClientRefusedError(
                "unit_value is server-derived for outbound actions",
                context={"action": action.value,
                         "supplied_unit_value": str(inp.unit_value)},
            )

        # 5. Quarantine state rule (FLOW-009): returns do not land directly
        # in free stock. Any destination state must match the action's
        # permitted set (checked per-action below).
        self._enforce_state_rule(inp)

        # 6. Verify indexes (fail-closed)
        await self._ensure_indexes(tenant_db)

        # 7. Build envelope (sans FIFO; FIFO is filled inside the tx)
        env = self._build_envelope(inp, outbound_value=Decimal("0"), allocations=[])
        validate_envelope(env)
        fp = envelope_fingerprint(env)

        # 8. Open session + transaction
        try:
            session_cm = await self._client.start_session()
        except Exception as exc:
            raise TransactionsNotSupportedError(
                f"replica-set session unavailable: {exc}"
            ) from exc

        async with session_cm as session:
            try:
                async with session.start_transaction():
                    return await self._execute_in_tx(
                        session=session,
                        tenant_db=tenant_db,
                        tenant_collection=tenant_collection,
                        inp=inp,
                        env=env,
                        fingerprint=fp,
                    )
            except (NegativeStockError, OriginAcceptanceOverrunError,
                    InvariantViolationError, IdempotencyConflict,
                    WarehouseMovementError):
                raise
            except Exception as exc:
                logger.exception("canonical movement failed; tx rolled back")
                raise AuditChainWriteError(
                    f"transaction rolled back: {exc}"
                ) from exc

    # ------------------------------------------------- internals
    def _enforce_identity(self, inp: CommandInput) -> None:
        if not inp.item_id or not inp.unit:
            raise MasterIdentityMissingError(
                "every canonical movement requires item_id and unit (FLOW-032)",
                context={"action": inp.action.value},
            )
        if inp.item_is_pending_mapping:
            # Allowed destination state: quarantine ONLY (FLOW-009).
            dest = inp.destination
            if dest is None or dest.state != MovementState.QUARANTINE:
                raise FreeTextIntoActionableStockError(
                    "pending-mapping items may only enter quarantine",
                    context={"action": inp.action.value},
                )

    def _enforce_state_rule(self, inp: CommandInput) -> None:
        action = inp.action
        dest = inp.destination
        src = inp.source
        # QUARANTINE_ENTRY must target a quarantine state.
        if action == CanonicalAction.QUARANTINE_ENTRY:
            if dest is None or dest.state != MovementState.QUARANTINE:
                raise QuarantineStateViolationError(
                    "quarantine_entry must target state=quarantine",
                )
        # QUARANTINE_RELEASE must source from quarantine, and must
        # name a non-quarantine destination (free / return / scrap).
        if action == CanonicalAction.QUARANTINE_RELEASE:
            if src is None or src.state != MovementState.QUARANTINE:
                raise QuarantineStateViolationError(
                    "quarantine_release must source state=quarantine",
                )
        # Return path: supplier return and warehouse return never land
        # in free stock directly — they require their own canonical
        # action. A warehouse->warehouse / project->warehouse transfer
        # DOES land in free (that is the acceptance side), which is OK.
        if action == CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE:
            if dest is None or dest.state == MovementState.QUARANTINE:
                # A legitimate transfer must have a free destination.
                raise QuarantineStateViolationError(
                    "transfer_project_to_warehouse must have free destination; "
                    "use quarantine_entry if the material needs inspection first",
                )

    async def _ensure_indexes(self, tenant_db) -> None:
        db_name = tenant_db.name
        if self._verify_once and db_name in self._verified:
            return
        await verify_required_indexes(tenant_db)
        self._verified.add(db_name)

    def _build_envelope(
        self,
        inp: CommandInput,
        *,
        outbound_value: Decimal,
        allocations: List,
    ) -> MovementEnvelope:
        # For outbound actions the unit_value is derived (0 when there are
        # no allocations because stock was 0 on write-off of a zero line
        # — which conservation guards reject anyway in `_execute_in_tx`).
        unit_value: Any = inp.unit_value
        if inp.action in OUTBOUND_ACTIONS:
            if allocations:
                # weighted-average unit value across the allocation
                qty = sum((a.quantity for a in allocations), Decimal("0"))
                unit_value = (outbound_value / qty).quantize(Decimal("0.0001")) if qty > 0 else Decimal("0")
            else:
                unit_value = Decimal("0")
        env = build_envelope(
            tenant_id=inp.tenant_id,
            action=inp.action.value,
            item_id=inp.item_id,
            unit=inp.unit,
            quantity=inp.quantity,
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
            confirmed_by=inp.confirmed_by,
            confirmed_at=inp.confirmed_at,
            correlation_id=inp.correlation_id,
            requested_quantity=inp.requested_quantity,
            accepted_quantity=inp.accepted_quantity,
            missing_quantity=(
                Decimal(str(inp.requested_quantity)) - Decimal(str(inp.accepted_quantity))
                if (inp.requested_quantity is not None and inp.accepted_quantity is not None)
                else None
            ),
            file_ids=inp.file_ids,
            reason=inp.reason,
            notes=inp.notes,
            corrects_movement_id=inp.corrects_movement_id,
            revision_evidence=inp.revision_evidence,
            occurred_at=inp.occurred_at,
        )
        return env

    async def _execute_in_tx(
        self,
        *,
        session,
        tenant_db,
        tenant_collection,
        inp: CommandInput,
        env: MovementEnvelope,
        fingerprint: str,
    ) -> ExecuteResult:
        action = inp.action
        tenant_id = inp.tenant_id

        # Idempotency claim (inside the tx so a rollback drops the reservation).
        try:
            idem = await begin_idempotent(
                tenant_db, tenant_id=tenant_id,
                key=inp.idempotency_key, action=action.value,
                request_fingerprint=fingerprint,
            )
        except IdempotencyConflict as exc:
            raise IdempotencyConflictError(str(exc), context={
                "action": action.value, "key": inp.idempotency_key}) from exc

        if idem["status"] == IDEMPOTENCY_DUPLICATE:
            # Same key + same payload — return the original result (replay).
            prior_ref = idem.get("result_reference")
            if prior_ref:
                prior_row = await tenant_collection.find_one(
                    {"movement_id": prior_ref}, session=session)
                if prior_row:
                    prior_row.pop("_id", None)
                    return ExecuteResult(
                        movement_id=prior_ref,
                        envelope=prior_row,
                        audit_event_id=prior_row.get("audit_event_id", ""),
                        idempotency_status=IDEMPOTENCY_DUPLICATE,
                        replay=True,
                    )
            # No prior result → re-run inside this tx (previous attempt failed).

        # FIFO + conservation
        allocations = []
        outbound_value = Decimal("0")
        if action in OUTBOUND_ACTIONS:
            if inp.source is None:
                raise InvariantViolationError(
                    "outbound action requires a source", context={"action": action.value})
            allocations, outbound_value = await allocate_outbound(
                tenant_collection,
                tenant_id=tenant_id,
                item_id=inp.item_id,
                source=inp.source,
                quantity=Decimal(str(inp.quantity)),
                session=session,
            )

        # Rule B: acceptance conservation. Accepted + prior resolutions
        # cannot exceed dispatched quantity.
        if action == CanonicalAction.ACCEPT_PROJECT_DELIVERY:
            await self._enforce_acceptance_conservation(
                tenant_collection, session=session, inp=inp)

        # Rebuild the envelope with FIFO fields filled, re-validate.
        env = self._build_envelope(inp, outbound_value=outbound_value, allocations=allocations)
        validate_envelope(env)

        # Append ledger row (inside tx)
        ledger_row = env.to_dict()
        try:
            await tenant_collection.insert_one(ledger_row, session=session)
        except Exception as exc:
            raise InvariantViolationError(
                f"ledger insert failed: {exc}",
                context={"movement_id": env.movement_id},
            ) from exc

        # Projection: open an in-transit row for dispatch so acceptance
        # can locate it; close the in-transit on acceptance. The
        # `warehouse_batches` physical projection is updated by the
        # dedicated projector module elsewhere (projections.py) — the
        # ledger row IS the source of truth, so projection skew is
        # recoverable from here. Projection runs under the same session.
        from app.services.warehouse_movements.projections import apply_projection
        await apply_projection(tenant_db, env, session=session)

        # Audit event (R2 for operational movements; R1 for revisions)
        retention = (
            RETENTION_R1_CRITICAL_BUSINESS
            if action == CanonicalAction.REVISION_ADJUSTMENT
            else RETENTION_R2_PROJECT_OPERATIONAL
        )
        audit_event = build_event(
            tenant_id=tenant_id,
            actor_type=ACTOR_HUMAN,
            actor_id=inp.actor_id,
            action=f"warehouse.{action.value}",
            source_flow="FLOW-009",
            retention_class=retention,
            entity_type="warehouse_movement",
            entity_id=env.movement_id,
            scope_type="project" if inp.project_id else "location",
            scope_id=inp.project_id or (inp.destination.location_id if inp.destination else None),
            reason=inp.reason,
            source_channel="canonical_warehouse_service",
            tool_or_endpoint="warehouse_movements.CommandService.execute",
            correlation_id=inp.correlation_id or env.movement_id,
            idempotency_key=inp.idempotency_key,
            related_file_ids=list(inp.file_ids or []),
            structured_diff={
                "action": action.value,
                "item_id": inp.item_id,
                "quantity": str(inp.quantity),
                "source": inp.source.to_dict() if inp.source else None,
                "destination": inp.destination.to_dict() if inp.destination else None,
                "allocations": [a.to_dict() for a in allocations],
                "outbound_value": str(outbound_value),
            },
        )

        try:
            # record_event is session-naive today; store the event on the
            # same db so a tx abort rolls back the entire write set.
            # NOTE: `record_event` uses `insert_one` without session; we
            # pass session through here when the signature allows.
            await _record_event_session(tenant_db, audit_event, session=session)
        except Exception as exc:
            # Audit failure MUST roll back the business row (FLOW-040 §4.3
            # requires every stock move to be audited).
            raise AuditChainWriteError(
                f"audit chain append failed: {exc}",
                context={"movement_id": env.movement_id},
            ) from exc

        # Update the ledger row with its audit_event_id, so downstream
        # reads surface the audit linkage without a second query.
        env.audit_event_id = audit_event.get("event_id")
        await tenant_collection.update_one(
            {"movement_id": env.movement_id},
            {"$set": {"audit_event_id": env.audit_event_id}},
            session=session,
        )

        # Mark idempotency COMPLETED (business reference = movement_id)
        await complete_idempotent(
            tenant_db, tenant_id=tenant_id,
            key=inp.idempotency_key, action=action.value,
            result_reference=env.movement_id,
        )

        return ExecuteResult(
            movement_id=env.movement_id,
            envelope=env.to_dict(),
            audit_event_id=env.audit_event_id or "",
            idempotency_status=IDEMPOTENCY_STARTED,
            replay=False,
        )

    async def _enforce_acceptance_conservation(
        self, tenant_collection, *, session, inp: CommandInput
    ) -> None:
        """accepted + prior_resolutions must not exceed dispatched qty."""
        dispatch_id = inp.dispatch_movement_id
        dispatch = await tenant_collection.find_one(
            {"movement_id": dispatch_id, "action": CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT.value},
            session=session,
        )
        if not dispatch:
            raise OriginAcceptanceOverrunError(
                "dispatch_movement_id does not point at a known dispatch",
                context={"dispatch_movement_id": dispatch_id})
        dispatched = Decimal(str(dispatch.get("quantity", "0")))
        # Any prior resolutions (acceptance, unresolved writes) point back
        # here via partial_resolution_of or dispatch_movement_id.
        cursor = tenant_collection.find({
            "dispatch_movement_id": dispatch_id,
            "action": {"$in": [
                CanonicalAction.ACCEPT_PROJECT_DELIVERY.value,
            ]},
        }, session=session)
        already = sum(
            (Decimal(str(d.get("accepted_quantity") or d.get("quantity") or "0"))
             async for d in cursor),
            Decimal("0"),
        )
        proposed = Decimal(str(inp.accepted_quantity))
        if already + proposed > dispatched:
            raise OriginAcceptanceOverrunError(
                "accepted + resolutions exceed dispatched quantity",
                context={"dispatched": str(dispatched),
                         "already_resolved": str(already),
                         "proposed_accept": str(proposed)},
            )


# -----------------------------------------------------------------------
# Session-aware audit append (small wrapper over record_event)
# -----------------------------------------------------------------------
async def _record_event_session(tenant_db, event, *, session=None):
    """Append an event in the SAME session as the business write.

    `app.audit.store.record_event` is session-agnostic; we re-implement the
    tiny insertion wrapper here so the operation is atomic. The hash chain
    logic (previous_hash / sequence) is identical.
    """
    from app.audit.envelope import validate_event
    from app.audit.store import (
        AUDIT_COLLECTION,
        chain_hashes,
    )
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
