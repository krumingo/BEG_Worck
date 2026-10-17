"""
LIVE-OPS-01 / TASK 5C — Canonical Warehouse / Stock Core (FLOW-009).

ONE append-only command service for every physical material movement. The
rest of the system — projections, read models, UI, migration readiness —
is derived from `warehouse_transactions` written by this service alone.

Canon:
  - FLOW-009 (warehouse / movements / quarantine / revision / Rule B)
  - FLOW-032 (Master item_id + canonical unit required for actionable stock)
  - FLOW-002 (deny-by-default Permission Service + object scope)
  - FLOW-040 (append-only AuditEvent envelope §3; retention R2 for operational,
              R1 for audit-of-audit / corrections)
  - FLOW-020 (invoice-line destinations, acceptance states)
  - FLOW-012 (dispatch ≠ acceptance; QR custody chain)

Hard boundaries honored by this package (CLAUDE.md v15 §16):
  - no second ledger / registry / source of truth,
  - no hard-delete of consequential records,
  - every consequential write passes permission check + idempotency + tenant
    guard + AuditEvent inside one real Mongo replica-set transaction,
  - legacy writers fail CLOSED; historical rows are preserved read-only,
  - migration tooling is DRY-RUN ONLY; it never mutates customer data.

Nothing in this package writes to `warehouse_transactions` outside
`service.CommandService.execute()`.
"""
from app.services.warehouse_movements.actions import (
    CanonicalAction,
    ALL_ACTIONS,
    OUTBOUND_ACTIONS,
    INBOUND_ACTIONS,
    QUARANTINE_ACTIONS,
)
from app.services.warehouse_movements.errors import (
    WarehouseMovementError,
    PermissionDeniedError,
    IdempotencyConflictError,
    InvariantViolationError,
    IndexMissingError,
    MasterIdentityMissingError,
    FreeTextIntoActionableStockError,
    NegativeStockError,
    OriginAcceptanceOverrunError,
    ValueFromClientRefusedError,
    LegacyWriterRetiredError,
    QuarantineStateViolationError,
    UnknownActionError,
)
from app.services.warehouse_movements.envelope import (
    MovementEnvelope,
    LayerAllocation,
    LocationKey,
    LocationType,
    MovementState,
    build_envelope,
    validate_envelope,
    envelope_fingerprint,
)

__all__ = [
    "CanonicalAction",
    "ALL_ACTIONS",
    "OUTBOUND_ACTIONS",
    "INBOUND_ACTIONS",
    "QUARANTINE_ACTIONS",
    "WarehouseMovementError",
    "PermissionDeniedError",
    "IdempotencyConflictError",
    "InvariantViolationError",
    "IndexMissingError",
    "MasterIdentityMissingError",
    "FreeTextIntoActionableStockError",
    "NegativeStockError",
    "OriginAcceptanceOverrunError",
    "ValueFromClientRefusedError",
    "LegacyWriterRetiredError",
    "QuarantineStateViolationError",
    "UnknownActionError",
    "MovementEnvelope",
    "LayerAllocation",
    "LocationKey",
    "LocationType",
    "MovementState",
    "build_envelope",
    "validate_envelope",
    "envelope_fingerprint",
]
