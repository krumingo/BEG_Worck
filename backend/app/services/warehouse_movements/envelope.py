"""
Canonical movement envelope — the frozen §4.1 schema.

Every row written to `warehouse_transactions` by the canonical command
service carries exactly these fields. Writers may add nothing; readers
may assume everything.

FLOW-009 §"Данни на движение" + FLOW_CODE_MAP_READY requirement:
  "item, qty/unit, values, source/destination, lot/layers, request/invoice/
   delivery, project/subproject/SMR, actor/confirmer, timestamps,
   correlation/idempotency"

The envelope is open to serialization (dict) but closed to free-text drift:
field names, types and value spaces are fixed, and `validate_envelope` is
run before every append.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import uuid

# -----------------------------------------------------------------------
# Location
# -----------------------------------------------------------------------


class LocationType(str, Enum):
    """Where a material can physically be (FLOW-009 §"Основни правила")."""
    CENTRAL_WAREHOUSE = "central_warehouse"
    SMALL_WAREHOUSE = "small_warehouse"
    PROJECT = "project"
    SUBPROJECT = "subproject"
    PERSON = "person"
    VEHICLE = "vehicle"
    SUPPLIER = "supplier"               # external origin / destination
    IN_TRANSIT = "in_transit"           # dispatch-in-flight (Rule B)
    UNRESOLVED = "unresolved"           # partial / missing remainder


class MovementState(str, Enum):
    """State at a location (quarantine is a STATE, never a location)."""
    FREE = "free"
    RESERVED = "reserved"
    QUARANTINE = "quarantine"
    IN_TRANSIT = "in_transit"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class LocationKey:
    """Stock key for `(location_type, location_id, state)`.

    `location_id` is the Master id of the warehouse, project, person,
    vehicle etc. For `SUPPLIER` origin the id is a counterparty_id; for
    `IN_TRANSIT` / `UNRESOLVED` it is the dispatch_movement_id so the
    remainder stays traceable.
    """
    location_type: LocationType
    location_id: str
    state: MovementState = MovementState.FREE

    def to_dict(self) -> Dict[str, str]:
        return {
            "location_type": self.location_type.value,
            "location_id": self.location_id,
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocationKey":
        return cls(
            location_type=LocationType(data["location_type"]),
            location_id=str(data["location_id"]),
            state=MovementState(data.get("state", MovementState.FREE.value)),
        )

    def __str__(self) -> str:
        return f"{self.location_type.value}:{self.location_id}:{self.state.value}"


# -----------------------------------------------------------------------
# Layer allocation (FIFO)
# -----------------------------------------------------------------------
@dataclass(frozen=True)
class LayerAllocation:
    """One FIFO layer consumed by an outbound movement.

    Preserving layer identity (source movement + original unit value) is
    what makes transfers conserve both qty and value.
    """
    source_movement_id: str
    layer_sequence: int
    quantity: Decimal
    unit_value: Decimal          # per base unit, from the source layer
    currency: str = "BGN"

    def total_value(self) -> Decimal:
        return (self.quantity * self.unit_value).quantize(Decimal("0.0001"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_movement_id": self.source_movement_id,
            "layer_sequence": self.layer_sequence,
            "quantity": str(self.quantity),
            "unit_value": str(self.unit_value),
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LayerAllocation":
        return cls(
            source_movement_id=str(data["source_movement_id"]),
            layer_sequence=int(data["layer_sequence"]),
            quantity=Decimal(str(data["quantity"])),
            unit_value=Decimal(str(data["unit_value"])),
            currency=str(data.get("currency", "BGN")),
        )


# -----------------------------------------------------------------------
# Envelope §4.1
# -----------------------------------------------------------------------
@dataclass
class MovementEnvelope:
    """One row of `warehouse_transactions`.

    Required: `movement_id`, `tenant_id`, `action`, `item_id`, `unit`,
    `quantity`, `source`, `destination`, timestamps and `idempotency_key`.
    Optional: lot/batch, source document references, project/SMR links,
    FIFO layer allocations, confirmer, pictures.
    """
    # Identity
    movement_id: str
    tenant_id: str
    action: str                         # CanonicalAction.value
    recorded_at: str                    # ISO-8601
    occurred_at: str                    # business time

    # Item identity (FLOW-032)
    item_id: str                        # Master item_id — ALWAYS required
    unit: str                           # canonical unit (e.g. "bag", "kg")

    # Quantities & value
    quantity: Decimal
    unit_value: Decimal = Decimal("0")  # server-derived for outbound
    currency: str = "BGN"

    # Location envelope
    source: Optional[Dict[str, str]] = None       # LocationKey.to_dict
    destination: Optional[Dict[str, str]] = None  # LocationKey.to_dict

    # Lot / batch / FIFO allocations
    lot_id: Optional[str] = None
    layer_allocations: List[Dict[str, Any]] = field(default_factory=list)

    # Source documents (FLOW-020 §"Класификация" / FLOW-012)
    request_id: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_line_id: Optional[str] = None
    delivery_id: Optional[str] = None
    dispatch_movement_id: Optional[str] = None     # link acceptance <-> dispatch
    reservation_movement_id: Optional[str] = None  # link release <-> reserve

    # Project / SMR
    project_id: Optional[str] = None
    subproject_id: Optional[str] = None
    smr_id: Optional[str] = None
    work_package_id: Optional[str] = None

    # People
    actor_id: str = ""                    # who issued the command
    confirmed_by: Optional[str] = None    # who physically confirmed
    confirmed_at: Optional[str] = None

    # Correlation / idempotency / audit
    correlation_id: Optional[str] = None
    idempotency_key: str = ""
    audit_event_id: Optional[str] = None  # set after chain append

    # Rule B tracking
    requested_quantity: Optional[Decimal] = None   # on acceptance
    accepted_quantity: Optional[Decimal] = None    # on acceptance
    missing_quantity: Optional[Decimal] = None     # requested - accepted
    partial_resolution_of: Optional[str] = None    # dispatch_movement_id if remainder

    # Evidence
    file_ids: List[str] = field(default_factory=list)

    # Reason / notes (free text — not identity)
    reason: Optional[str] = None
    notes: Optional[str] = None

    # Reversal / correction linkage (FLOW-040 §2 corrections create new events)
    corrects_movement_id: Optional[str] = None
    revision_evidence: Optional[Dict[str, Any]] = None

    # Legacy source trace (migration-readiness tooling only — never set
    # by the canonical writer; present so projections can inspect it on
    # historical rows preserved from pre-TASK-5C ledger).
    legacy_source: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return _normalize_decimals(asdict(self))


# -----------------------------------------------------------------------
# Builders & validators
# -----------------------------------------------------------------------
_ISO_MIN = "0001-01-01T00:00:00+00:00"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any) -> Decimal:
    """Parse a Decimal without `.normalize()` — normalize turns "40" into
    "4E+1", which breaks both human reading and the hash fingerprint."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def _normalize_decimals(obj: Any) -> Any:
    """Recursively turn Decimals into strings for Mongo-safe storage.

    FLOW-040 §9: canonical, deterministic, safe for hash chain.
    Mongo's BSON Decimal128 is also valid but strings keep hashing
    identical across environments (test, prod) with no precision drift.
    """
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _normalize_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_decimals(v) for v in obj]
    return obj


def build_envelope(
    *,
    tenant_id: str,
    action: str,
    item_id: str,
    unit: str,
    quantity: Any,
    source: Optional[LocationKey],
    destination: Optional[LocationKey],
    actor_id: str,
    idempotency_key: str,
    unit_value: Any = Decimal("0"),
    currency: str = "BGN",
    lot_id: Optional[str] = None,
    layer_allocations: Optional[List[LayerAllocation]] = None,
    request_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
    invoice_line_id: Optional[str] = None,
    delivery_id: Optional[str] = None,
    dispatch_movement_id: Optional[str] = None,
    reservation_movement_id: Optional[str] = None,
    project_id: Optional[str] = None,
    subproject_id: Optional[str] = None,
    smr_id: Optional[str] = None,
    work_package_id: Optional[str] = None,
    confirmed_by: Optional[str] = None,
    confirmed_at: Optional[str] = None,
    correlation_id: Optional[str] = None,
    requested_quantity: Any = None,
    accepted_quantity: Any = None,
    missing_quantity: Any = None,
    partial_resolution_of: Optional[str] = None,
    file_ids: Optional[List[str]] = None,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
    corrects_movement_id: Optional[str] = None,
    revision_evidence: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
    movement_id: Optional[str] = None,
) -> MovementEnvelope:
    env = MovementEnvelope(
        movement_id=movement_id or f"mv_{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        action=action,
        recorded_at=_now_iso(),
        occurred_at=occurred_at or _now_iso(),
        item_id=item_id,
        unit=unit,
        quantity=_to_decimal(quantity),
        unit_value=_to_decimal(unit_value),
        currency=currency,
        source=source.to_dict() if source is not None else None,
        destination=destination.to_dict() if destination is not None else None,
        lot_id=lot_id,
        layer_allocations=[la.to_dict() for la in (layer_allocations or [])],
        request_id=request_id,
        invoice_id=invoice_id,
        invoice_line_id=invoice_line_id,
        delivery_id=delivery_id,
        dispatch_movement_id=dispatch_movement_id,
        reservation_movement_id=reservation_movement_id,
        project_id=project_id,
        subproject_id=subproject_id,
        smr_id=smr_id,
        work_package_id=work_package_id,
        actor_id=actor_id,
        confirmed_by=confirmed_by,
        confirmed_at=confirmed_at,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        requested_quantity=_to_decimal(requested_quantity) if requested_quantity is not None else None,
        accepted_quantity=_to_decimal(accepted_quantity) if accepted_quantity is not None else None,
        missing_quantity=_to_decimal(missing_quantity) if missing_quantity is not None else None,
        partial_resolution_of=partial_resolution_of,
        file_ids=list(file_ids or []),
        reason=reason,
        notes=notes,
        corrects_movement_id=corrects_movement_id,
        revision_evidence=revision_evidence,
    )
    return env


REQUIRED_FIELDS: Tuple[str, ...] = (
    "movement_id",
    "tenant_id",
    "action",
    "item_id",
    "unit",
    "quantity",
    "recorded_at",
    "occurred_at",
    "actor_id",
    "idempotency_key",
)


def validate_envelope(env: MovementEnvelope) -> None:
    """Raise ValueError on any §4.1 violation. Pure, cheap, synchronous.

    This is the first gate: the command service runs it BEFORE any
    database contact so a malformed envelope cannot reach the tx body.
    """
    missing = [f for f in REQUIRED_FIELDS if not getattr(env, f, None)]
    if missing:
        raise ValueError(f"envelope missing required fields: {sorted(missing)}")

    if env.quantity <= 0:
        raise ValueError(f"quantity must be positive (got {env.quantity})")

    if env.unit_value is not None and env.unit_value < 0:
        raise ValueError(f"unit_value cannot be negative (got {env.unit_value})")

    if env.source is None and env.destination is None:
        raise ValueError("envelope requires at least one of source or destination")

    # Reservation / release link each other
    if env.action in {"release_reservation"} and not env.reservation_movement_id:
        raise ValueError("release_reservation requires reservation_movement_id")

    # Acceptance must reference its dispatch; conservation cannot be checked
    # otherwise and the unresolved remainder has nowhere to be anchored.
    if env.action == "accept_project_delivery":
        if not env.dispatch_movement_id:
            raise ValueError("accept_project_delivery requires dispatch_movement_id")
        if env.accepted_quantity is None:
            raise ValueError("accept_project_delivery requires accepted_quantity")

    # Correction references its original row.
    if env.corrects_movement_id and env.action != "revision_adjustment":
        raise ValueError("only revision_adjustment may set corrects_movement_id")


def envelope_fingerprint(env: MovementEnvelope) -> str:
    """Deterministic SHA-256 over the canonical envelope.

    Used as `request_fingerprint` in the idempotency registry: same
    business payload + same key = replay; different business payload +
    same key = conflict.

    Fields that are set per-build (not supplied by the caller) are
    EXCLUDED: `movement_id` is a fresh uuid4 per build, `recorded_at` is
    the build wall-clock, `audit_event_id` is filled after append.
    `occurred_at` defaults to wall-clock too when the caller does not
    pin it, and is therefore excluded by default. If the caller supplied
    an explicit `occurred_at`, it reaches the ledger row intact — the
    fingerprint just does not count it toward replay detection.
    """
    payload = env.to_dict()
    for key in ("movement_id", "recorded_at", "occurred_at", "audit_event_id"):
        payload.pop(key, None)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
