"""
Server-side FIFO allocator — reads the canonical ledger, never writes.

Rules (FLOW-009 §"Разход по обект", §"Прехвърляния" + FLOW_CODE_MAP_READY):
  - Outbound value is server-derived; the client cannot send `unit_price`
    on an issue, consume, transfer, return-to-supplier or write-off.
  - FIFO reads layers in `recorded_at` order, oldest first.
  - Each outbound records exact `layer_allocations` (source_movement_id,
    layer_sequence, quantity, unit_value), so transfers preserve original
    layers and reconciliation is deterministic.
  - Normal stock cannot silently become negative. Insufficient free stock
    at (item, location, state) raises NegativeStockError.
  - When operating inside a transaction, the session is honored so the
    scan sees committed inbound/outbound only (snapshot isolation).

This module computes layer plans; the service module decides how to
spend them — splitting across destinations, writing dispatch vs
acceptance, etc.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.services.warehouse_movements.envelope import (
    LayerAllocation,
    LocationKey,
    MovementState,
)
from app.services.warehouse_movements.errors import NegativeStockError


# Must match envelope.py's string normalization and indexes.py's compound
MOVEMENTS_COLLECTION = "warehouse_transactions"


@dataclass
class _OpenLayer:
    source_movement_id: str
    layer_sequence: int
    remaining: Decimal
    unit_value: Decimal
    currency: str


def inbound_layer_parts(doc: Dict[str, Any]) -> List[Tuple[int, Decimal, Decimal, str]]:
    """5C-C24 F-55-C23-01 — the FIFO layers ONE inbound ledger row opens.

    Returns `(part, quantity, unit_value, currency)` tuples; `part` is the
    stable 1-based layer number inside the row, so a layer's identity is
    `(movement_id, part)` — independent of any other row in the bucket and
    identical to the `warehouse_batches` key (`movement_id`,
    `layer_sequence`) the projector writes.

      * A row that carries traced `layer_allocations` (an acceptance — it
        lands the dispatched layers at the destination) opens ONE layer per
        allocation, at that allocation's exact unit value. Part numbers
        follow the allocation list, so they match the batch rows of
        `projections._open_destination_from_layers`; zero-quantity parts are
        skipped without renumbering.
      * Any other inbound (supplier receive, direct delivery) opens a single
        layer `(movement_id, 1)` at its own unit value.

    The row's rounded weighted-average `unit_value` is never used as a
    stock or cost basis when the exact allocations are present. If the
    allocations do not add up to the row quantity the row is malformed for
    expansion and is read as one layer (the pre-C24 reading).
    """
    qty = Decimal(str(doc.get("quantity", "0") or "0"))
    currency = str(doc.get("currency", "BGN") or "BGN")
    allocs = doc.get("layer_allocations") or []
    if allocs:
        parts = []
        total = Decimal("0")
        for part, a in enumerate(allocs, start=1):
            a_qty = Decimal(str(a.get("quantity", "0") or "0"))
            total += a_qty
            if a_qty <= 0:
                continue
            parts.append((part, a_qty,
                          Decimal(str(a.get("unit_value", "0") or "0")),
                          str(a.get("currency", currency) or currency)))
        if total == qty:
            return parts
    return [(1, qty, Decimal(str(doc.get("unit_value", "0") or "0")), currency)]


def allocations_value(layer_allocations, *, fallback_quantity=None,
                      fallback_unit_value=None) -> Decimal:
    """5C-C24 F-55-C23-01 — exact value of a movement: Σ qty × unit_value of
    its FIFO allocations (4 dp). Only when a row has no allocations does it
    fall back to `quantity × unit_value`. Every cost/write-off projection,
    the material sync and the stock reads use this, so ledger, stock,
    batches and reports carry the same exact FIFO sum — never the rounded
    weighted-average unit value × quantity.
    """
    allocs = list(layer_allocations or [])
    if allocs:
        total = Decimal("0")
        for a in allocs:
            if isinstance(a, LayerAllocation):
                total += a.quantity * a.unit_value
            else:
                total += (Decimal(str(a.get("quantity", "0") or "0"))
                          * Decimal(str(a.get("unit_value", "0") or "0")))
        return total.quantize(Decimal("0.0001"))
    q = Decimal(str(fallback_quantity or "0"))
    u = Decimal(str(fallback_unit_value or "0"))
    return (q * u).quantize(Decimal("0.0001"))


async def _load_open_layers(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: str,
    location: LocationKey,
    session=None,
) -> List[_OpenLayer]:
    """Rebuild open FIFO layers for one (item, source location, state).

    The projection is simple: every inbound to this bucket opens its
    layers (`inbound_layer_parts` — one per traced allocation for an
    acceptance, 5C-C24), every outbound from this bucket drains layers in
    order. The projection
    is bounded to this bucket — no 1000-row cap, no truncation.

    C09 — the order IS the ledger server-sequence, not wall-clock time
    (two inbounds in one millisecond would otherwise tie non-deterministically).
    Legacy rows without a `ledger_sequence` fall back to `recorded_at`
    + `movement_id` so historical rows still participate.
    """
    inbound_q = {
        "tenant_id": tenant_id,
        "item_id": item_id,
        "destination.location_type": location.location_type.value,
        "destination.location_id": location.location_id,
        "destination.state": location.state.value,
    }
    outbound_q = {
        "tenant_id": tenant_id,
        "item_id": item_id,
        "source.location_type": location.location_type.value,
        "source.location_id": location.location_id,
        "source.state": location.state.value,
    }
    cursor_in = tenant_collection.find(
        inbound_q, {"movement_id": 1, "quantity": 1, "unit_value": 1,
                    "currency": 1, "recorded_at": 1, "layer_allocations": 1,
                    "ledger_sequence": 1, "_id": 0},
        session=session,
    ).sort([("ledger_sequence", 1), ("recorded_at", 1), ("movement_id", 1)])
    inbound = [dict(doc) async for doc in cursor_in]

    cursor_out = tenant_collection.find(
        outbound_q, {"movement_id": 1, "layer_allocations": 1,
                     "recorded_at": 1,
                     "ledger_sequence": 1, "_id": 0},
        session=session,
    ).sort([("ledger_sequence", 1), ("recorded_at", 1), ("movement_id", 1)])
    outbound = [dict(doc) async for doc in cursor_out]

    # Open the layers of every inbound row (5C-C24 F-55-C23-01): stable
    # identity `(inbound movement_id, part)`, exact per-part unit value.
    layers: Dict[Tuple[str, int], _OpenLayer] = {}
    order: Dict[Tuple[str, int], Tuple[int, int]] = {}
    parts_of: Dict[str, List[Tuple[str, int]]] = {}
    for row_pos, doc in enumerate(inbound, start=1):
        mv_id = str(doc["movement_id"])
        for part, qty, unit_value, currency in inbound_layer_parts(doc):
            key = (mv_id, part)
            layers[key] = _OpenLayer(
                source_movement_id=mv_id,
                layer_sequence=part,
                remaining=qty,
                unit_value=unit_value,
                currency=currency,
            )
            order[key] = (row_pos, part)
            parts_of.setdefault(mv_id, []).append(key)

    # Drain layers in the order the outbound documents reference them.
    # C09 fail-closed: an allocation that references an unknown layer is
    # a projection skew that MUST block, not silently continue.
    for doc in outbound:
        for alloc in doc.get("layer_allocations", []):
            key = (
                str(alloc["source_movement_id"]),
                int(alloc["layer_sequence"]),
            )
            if key not in layers:
                # Pre-C24 allocations named a layer by its POSITION in the
                # bucket. That is unambiguous only when the named inbound
                # row opened exactly one layer — then its identity is
                # `(movement_id, 1)`. Anything else stays fail-closed.
                same_row = parts_of.get(key[0], [])
                if len(same_row) == 1:
                    key = same_row[0]
                else:
                    raise NegativeStockError(
                        "outbound allocation references an unknown source layer; "
                        "projection is skewed from the canonical ledger",
                        context={
                            "item_id": item_id,
                            "location": str(location),
                            "missing_source": key[0],
                            "missing_sequence": key[1],
                            "outbound_movement_id": doc.get("movement_id"),
                        },
                    )
            layers[key].remaining -= Decimal(str(alloc.get("quantity", "0")))

    # Only keep positive-remaining layers, oldest first (ledger order of
    # the inbound row, then the part inside it).
    sorted_keys = sorted(
        [k for k in layers if layers[k].remaining > 0],
        key=lambda k: order[k],
    )
    return [layers[k] for k in sorted_keys]


async def allocate_outbound(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: str,
    source: LocationKey,
    quantity: Decimal,
    session=None,
) -> Tuple[List[LayerAllocation], Decimal]:
    """Plan FIFO consumption of `quantity` from (item, source).

    Returns (`allocations`, `total_value`). On insufficient free stock the
    call raises NegativeStockError — the caller must abort the transaction
    without appending a movement.
    """
    layers = await _load_open_layers(
        tenant_collection,
        tenant_id=tenant_id,
        item_id=item_id,
        location=source,
        session=session,
    )

    allocations: List[LayerAllocation] = []
    remaining_to_consume = Decimal(str(quantity))
    total_value = Decimal("0")
    for layer in layers:
        if remaining_to_consume <= 0:
            break
        take = min(layer.remaining, remaining_to_consume)
        allocations.append(LayerAllocation(
            source_movement_id=layer.source_movement_id,
            layer_sequence=layer.layer_sequence,
            quantity=take,
            unit_value=layer.unit_value,
            currency=layer.currency,
        ))
        total_value += take * layer.unit_value
        remaining_to_consume -= take

    if remaining_to_consume > 0:
        raise NegativeStockError(
            "insufficient free stock to satisfy outbound",
            context={
                "item_id": item_id,
                "source": str(source),
                "requested": str(quantity),
                "available": str(quantity - remaining_to_consume),
                "shortfall": str(remaining_to_consume),
            },
        )
    return allocations, total_value.quantize(Decimal("0.0001"))


async def layers_at(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: str,
    location: LocationKey,
    session=None,
) -> List[LayerAllocation]:
    """Snapshot of open layers at one bucket. Read-only."""
    layers = await _load_open_layers(
        tenant_collection,
        tenant_id=tenant_id,
        item_id=item_id,
        location=location,
        session=session,
    )
    return [
        LayerAllocation(
            source_movement_id=l.source_movement_id,
            layer_sequence=l.layer_sequence,
            quantity=l.remaining,
            unit_value=l.unit_value,
            currency=l.currency,
        )
        for l in layers
    ]


async def free_balance(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: str,
    location: LocationKey,
    session=None,
) -> Decimal:
    """Sum of remaining qty across all open layers at one bucket."""
    layers = await _load_open_layers(
        tenant_collection,
        tenant_id=tenant_id,
        item_id=item_id,
        location=location,
        session=session,
    )
    return sum((l.remaining for l in layers), Decimal("0"))
