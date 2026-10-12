"""
Typed errors for the canonical warehouse movement service.

Every write-time rejection raises one of these — they map cleanly to HTTP
error codes in the route layer, and tests assert on the error class rather
than on error strings.
"""


class WarehouseMovementError(Exception):
    """Base error for the canonical movement service."""

    error_code: str = "WAREHOUSE_MOVEMENT_ERROR"

    def __init__(self, message: str, *, context: dict | None = None):
        super().__init__(message)
        self.message = message
        self.context = dict(context) if context else {}


# -----------------------------------------------------------------------
# Permissions / tenant
# -----------------------------------------------------------------------
class PermissionDeniedError(WarehouseMovementError):
    error_code = "PERMISSION_DENIED"


class CrossTenantError(WarehouseMovementError):
    error_code = "CROSS_TENANT"


# -----------------------------------------------------------------------
# Idempotency / replay
# -----------------------------------------------------------------------
class IdempotencyConflictError(WarehouseMovementError):
    """Same idempotency key reused for a different payload."""
    error_code = "IDEMPOTENCY_CONFLICT"


# -----------------------------------------------------------------------
# Invariants
# -----------------------------------------------------------------------
class InvariantViolationError(WarehouseMovementError):
    """A conservation / layer / state invariant failed inside the transaction."""
    error_code = "INVARIANT_VIOLATION"


class NegativeStockError(InvariantViolationError):
    """Normal stock cannot silently become negative (FLOW-009)."""
    error_code = "NEGATIVE_STOCK"


class OriginAcceptanceOverrunError(InvariantViolationError):
    """Accepted + resolutions exceed origin (FLOW-009 partial/missing)."""
    error_code = "ORIGIN_ACCEPTANCE_OVERRUN"


class QuarantineStateViolationError(InvariantViolationError):
    """Returned material cannot land directly in free stock (FLOW-009)."""
    error_code = "QUARANTINE_STATE_VIOLATION"


# -----------------------------------------------------------------------
# Identity / mapping (FLOW-032)
# -----------------------------------------------------------------------
class MasterIdentityMissingError(WarehouseMovementError):
    """A canonical movement requires a confirmed `item_id` and canonical unit."""
    error_code = "MASTER_IDENTITY_MISSING"


class FreeTextIntoActionableStockError(WarehouseMovementError):
    """Pending-mapping (free-text only) material may enter quarantine only."""
    error_code = "FREE_TEXT_INTO_ACTIONABLE_STOCK"


# -----------------------------------------------------------------------
# Server-side only values (FLOW-009)
# -----------------------------------------------------------------------
class ValueFromClientRefusedError(WarehouseMovementError):
    """Outbound unit value is server-derived FIFO — client values are refused."""
    error_code = "VALUE_FROM_CLIENT_REFUSED"


# -----------------------------------------------------------------------
# Index / infra prerequisites — fail-closed per TASK 5C
# -----------------------------------------------------------------------
class IndexMissingError(WarehouseMovementError):
    """A required unique/compound index is absent; the service refuses to write."""
    error_code = "INDEX_MISSING"


class TransactionsNotSupportedError(WarehouseMovementError):
    """Mongo deployment is not a replica set / shard; txns required."""
    error_code = "TRANSACTIONS_NOT_SUPPORTED"


class AuditChainWriteError(WarehouseMovementError):
    """The audit event could not be chained; the business write is rolled back."""
    error_code = "AUDIT_CHAIN_WRITE_FAILED"


class FileRegistryUnavailableError(WarehouseMovementError):
    """Evidence-mandatory command refused because File Registry (W0-06) is absent."""
    error_code = "FILE_REGISTRY_UNAVAILABLE"


class ApprovalRuntimeUnavailableError(WarehouseMovementError):
    """Approval-mandatory command refused because W0-07 runtime is absent."""
    error_code = "APPROVAL_RUNTIME_UNAVAILABLE"


# -----------------------------------------------------------------------
# Legacy writer retirement — a legacy stock writer still being exercised
# at runtime (FLOW_CODE_MAP_READY "Legacy writer retirement inventory").
# -----------------------------------------------------------------------
class LegacyWriterRetiredError(WarehouseMovementError):
    """A legacy warehouse writer has been retired; use the canonical command."""
    error_code = "LEGACY_WRITER_RETIRED"


# -----------------------------------------------------------------------
# Dispatcher
# -----------------------------------------------------------------------
class UnknownActionError(WarehouseMovementError):
    error_code = "UNKNOWN_ACTION"


# -----------------------------------------------------------------------
# Migration readiness
# -----------------------------------------------------------------------
class MigrationExecutionRefusedError(WarehouseMovementError):
    """Migration tooling is DRY-RUN ONLY (TASK 5C hard boundary)."""
    error_code = "MIGRATION_EXECUTION_REFUSED"
