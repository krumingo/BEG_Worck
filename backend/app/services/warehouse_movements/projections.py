"""
Projections over the canonical ledger.

Two projections live here:

  1. `warehouse_batches` — the batch/FIFO/cost view that was formerly a
     parallel writer. In TASK 5C it is PROJECTOR-ONLY: `apply_projection`
     opens / drains batch rows from inbound / outbound movements written
     by the command service. Direct `POST /warehouse/batches` and
     `/warehouse/consume` writes are retired (see `legacy_inventory.py`).

  2. `material_entries` — projection used by SMR/project cost views.
     Rebuildable, never a physical writer.

The functions here never append to `warehouse_transactions` and never
accept a client-supplied unit value: they derive both from the ledger
row the service just wrote.

Historical rows (pre-TASK-5C) remain in `warehouse_batches` and
`material_entries` untouched. Readers must treat the projection as
rebuildable from the canonical ledger: when `rebuild_batches_from_ledger`
is used, it generates NEW projection rows but does NOT delete historical
ones that cannot be mapped — they stay as read-only reconciliation input.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from app.services.warehouse_movements.actions import (
    CanonicalAction,
    OUTBOUND_ACTIONS,
    INBOUND_ACTIONS,
)
from app.services.warehouse_movements.envelope import (
    MovementEnvelope,
    LocationKey,
    MovementState,
    LocationType,
)


BATCHES_COLLECTION = "warehouse_batches"
MATERIAL_ENTRIES_COLLECTION = "material_entries"


async def apply_projection(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    """Update projections from one canonical movement.

    This is called inside the command service's transaction, so a rollback
    reverses the projection update too. The projections only accept rows
    emitted by the command service; the `source=canonical_warehouse_service`
    marker on each projection row makes the provenance explicit and lets
    reconciliation separate projection rows from historical rows.
    """
    act = env.action
    if act in {a.value for a in INBOUND_ACTIONS}:
        await _open_batch(tenant_db, env, session=session)
    if act in {a.value for a in OUTBOUND_ACTIONS}:
        await _drain_batches(tenant_db, env, session=session)
    if act == CanonicalAction.CONSUME_TO_SMR.value:
        await _project_consumption(tenant_db, env, session=session)
    if act == CanonicalAction.ACCEPT_PROJECT_DELIVERY.value:
        # Rule B: at acceptance, the accepted qty becomes free at
        # destination; the unresolved remainder stays as `in_transit`.
        await _close_in_transit(tenant_db, env, session=session)
    if act == CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT.value:
        await _open_in_transit(tenant_db, env, session=session)


async def _open_batch(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    doc = {
        "projection_source": "canonical_warehouse_service",
        "projection_version": 1,
        "tenant_id": env.tenant_id,
        "movement_id": env.movement_id,
        "item_id": env.item_id,
        "unit": env.unit,
        "quantity": str(env.quantity),
        "remaining_quantity": str(env.quantity),
        "unit_value": str(env.unit_value),
        "currency": env.currency,
        "location": env.destination,
        "lot_id": env.lot_id,
        "project_id": env.project_id,
        "received_at": env.recorded_at,
        "state": (env.destination or {}).get("state") if env.destination else None,
    }
    await tenant_db[BATCHES_COLLECTION].update_one(
        {"tenant_id": env.tenant_id, "movement_id": env.movement_id},
        {"$set": doc, "$setOnInsert": {"opened_from": env.movement_id}},
        upsert=True,
        session=session,
    )


async def _drain_batches(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    """Decrement `remaining_quantity` on each batch named by allocations.

    `allocations` always comes from the server-side FIFO allocator and
    is deterministic; it names each source movement + layer.
    """
    for alloc in env.layer_allocations:
        src_id = alloc["source_movement_id"]
        qty = Decimal(str(alloc["quantity"]))
        # Decrement remaining; keep the batch row even at zero so audits
        # can trace the full life cycle.
        await tenant_db[BATCHES_COLLECTION].update_one(
            {"tenant_id": env.tenant_id, "movement_id": src_id},
            {
                "$inc": {"consumed_quantity": float(qty)},
                "$set": {"last_drained_at": env.recorded_at},
            },
            session=session,
        )
        # Rebuild remaining_quantity from quantity - consumed_quantity:
        # we read-back and write to keep the invariant visible in a scan.
        batch = await tenant_db[BATCHES_COLLECTION].find_one(
            {"tenant_id": env.tenant_id, "movement_id": src_id},
            {"quantity": 1, "consumed_quantity": 1, "_id": 0},
            session=session,
        )
        if batch:
            q = Decimal(str(batch.get("quantity") or "0"))
            c = Decimal(str(batch.get("consumed_quantity") or "0"))
            await tenant_db[BATCHES_COLLECTION].update_one(
                {"tenant_id": env.tenant_id, "movement_id": src_id},
                {"$set": {"remaining_quantity": str(max(q - c, Decimal("0")))}},
                session=session,
            )


async def _project_consumption(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    """Rebuildable `material_entries` row for one consumption.

    Nothing here is a source of truth. `material_entries` is a projection
    whose contents may be regenerated from the canonical ledger at any
    time. We tag the row with `projection_source` so the rebuild tool can
    identify its own rows and leave legacy ones alone.
    """
    row = {
        "projection_source": "canonical_warehouse_service",
        "projection_version": 1,
        "tenant_id": env.tenant_id,
        "movement_id": env.movement_id,
        "project_id": env.project_id,
        "subproject_id": env.subproject_id,
        "smr_id": env.smr_id,
        "work_package_id": env.work_package_id,
        "item_id": env.item_id,
        "unit": env.unit,
        "quantity": str(env.quantity),
        "unit_value": str(env.unit_value),
        "total_value": str((Decimal(str(env.quantity)) * Decimal(str(env.unit_value))).quantize(Decimal("0.0001"))),
        "currency": env.currency,
        "consumed_at": env.recorded_at,
    }
    await tenant_db[MATERIAL_ENTRIES_COLLECTION].update_one(
        {"tenant_id": env.tenant_id, "movement_id": env.movement_id},
        {"$set": row},
        upsert=True,
        session=session,
    )


async def _open_in_transit(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    """Open an in-transit bucket keyed by dispatch_movement_id."""
    row = {
        "projection_source": "canonical_warehouse_service",
        "tenant_id": env.tenant_id,
        "dispatch_movement_id": env.movement_id,
        "item_id": env.item_id,
        "unit": env.unit,
        "dispatched_quantity": str(env.quantity),
        "accepted_quantity": "0",
        "unresolved_quantity": str(env.quantity),
        "project_id": env.project_id,
        "dispatched_at": env.recorded_at,
    }
    await tenant_db["warehouse_in_transit"].update_one(
        {"tenant_id": env.tenant_id, "dispatch_movement_id": env.movement_id},
        {"$set": row},
        upsert=True,
        session=session,
    )


async def _close_in_transit(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    """Decrement unresolved on acceptance; leave the row until fully resolved."""
    dispatch_id = env.dispatch_movement_id
    if not dispatch_id:
        return
    accepted = Decimal(str(env.accepted_quantity or "0"))
    doc = await tenant_db["warehouse_in_transit"].find_one(
        {"tenant_id": env.tenant_id, "dispatch_movement_id": dispatch_id},
        session=session,
    )
    if not doc:
        return
    prior_accepted = Decimal(str(doc.get("accepted_quantity") or "0"))
    dispatched = Decimal(str(doc.get("dispatched_quantity") or "0"))
    new_accepted = prior_accepted + accepted
    unresolved = max(dispatched - new_accepted, Decimal("0"))
    await tenant_db["warehouse_in_transit"].update_one(
        {"tenant_id": env.tenant_id, "dispatch_movement_id": dispatch_id},
        {"$set": {"accepted_quantity": str(new_accepted),
                  "unresolved_quantity": str(unresolved),
                  "last_accepted_at": env.recorded_at}},
        session=session,
    )
