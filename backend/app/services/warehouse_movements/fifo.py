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


async def _load_open_layers(
    tenant_collection,
    *,
    tenant_id: str,
    item_id: str,
    location: LocationKey,
    session=None,
) -> List[_OpenLayer]:
    """Rebuild open FIFO layers for one (item, source location, state).

    The projection is simple: every inbound to this bucket opens a layer,
    every outbound from this bucket drains layers in order. The projection
    is bounded to this bucket — no 1000-row cap, no truncation.
    """
    # Inbound: this location is the DESTINATION
    inbound_q = {
        "tenant_id": tenant_id,
        "item_id": item_id,
        "destination.location_type": location.location_type.value,
        "destination.location_id": location.location_id,
        "destination.state": location.state.value,
    }
    # Outbound: this location is the SOURCE
    outbound_q = {
        "tenant_id": tenant_id,
        "item_id": item_id,
        "source.location_type": location.location_type.value,
        "source.location_id": location.location_id,
        "source.state": location.state.value,
    }
    # Loaded fully, oldest first — the whole projection is for one bucket,
    # not the whole warehouse, so it is bounded by business volume rather
    # than by an arbitrary cap. CODEX test for >1000 verifies this.
    cursor_in = tenant_collection.find(
        inbound_q, {"movement_id": 1, "quantity": 1, "unit_value": 1,
                    "currency": 1, "recorded_at": 1, "_id": 0},
        session=session,
    ).sort("recorded_at", 1)
    inbound = [dict(doc) async for doc in cursor_in]

    cursor_out = tenant_collection.find(
        outbound_q, {"movement_id": 1, "layer_allocations": 1,
                     "recorded_at": 1, "_id": 0},
        session=session,
    ).sort("recorded_at", 1)
    outbound = [dict(doc) async for doc in cursor_out]

    # Open each inbound as a layer with its full quantity.
    layers: Dict[Tuple[str, int], _OpenLayer] = {}
    for seq, doc in enumerate(inbound, start=1):
        key = (str(doc["movement_id"]), seq)
        layers[key] = _OpenLayer(
            source_movement_id=key[0],
            layer_sequence=seq,
            remaining=Decimal(str(doc.get("quantity", "0"))),
            unit_value=Decimal(str(doc.get("unit_value", "0"))),
            currency=str(doc.get("currency", "BGN")),
        )

    # Drain layers in the order the outbound documents reference them.
    for doc in outbound:
        for alloc in doc.get("layer_allocations", []):
            key = (
                str(alloc["source_movement_id"]),
                int(alloc["layer_sequence"]),
            )
            if key not in layers:
                # Allocation referencing a layer we did not see is a
                # projection skew — skip rather than silently negative.
                continue
            layers[key].remaining -= Decimal(str(alloc.get("quantity", "0")))

    # Only keep positive-remaining layers, oldest first.
    sorted_keys = sorted(
        [k for k in layers if layers[k].remaining > 0],
        key=lambda k: (k[1], k[0]),
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
