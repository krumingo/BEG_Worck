"""
Projections over the canonical ledger.

Two authoritative projections live here:

  1. `warehouse_batches` — the batch/FIFO/cost view. In TASK 5C it is
     PROJECTOR-ONLY: `apply_projection` opens, drains and re-opens
     layer rows from the canonical ledger lines. Direct writes are
     retired (`legacy_inventory.py`).

  2. `warehouse_in_transit` — advisory in-transit position for a given
     dispatch. The acceptance invariant is still enforced against the
     LEDGER itself (C07); this projection is a convenience view only
     and can be rebuilt from the ledger at any time.

  3. `material_entries` — project cost projection (`material_cost_rows`,
     5C-C25 / Р17: cost at acceptance, consumption = allocation only).

The functions here never append to `warehouse_transactions` and never
accept a client-supplied unit value: they derive both from the ledger
row the service just wrote.

CODEX C11.1 — the service passes a `hints` dict so projections can
cross-reference an acceptance's unresolved remainder, the acceptance
line id, etc. without re-reading the ledger. The signature is
intentionally keyword-only so additions are forward-compatible.

CODEX C11.5 — every TRANSFER / RECEIVE / RETURN / QUARANTINE action
now produces complete projection effects (source drain + destination
credit + layer preservation):

  * dispatch_warehouse_to_project / transfer_* : source drain + mirror
    into warehouse_in_transit (destination credit happens on
    accept_project_delivery or transfer_accept_* using the same traced
    layers).
  * accept_project_delivery : destination credit at (project, free) and
    close in-transit; the layer_allocations ARE the credit layers.
  * quarantine_entry : source drain (if source=real), destination
    credit at (location, quarantine) with the traced layers.
  * quarantine_release : source drain (quarantine), destination credit
    at the authorised destination state with the traced layers.
  * return_to_supplier / write_off : source drain, no destination
    credit (material leaves the system).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from app.services.warehouse_movements.actions import (
    CanonicalAction,
    OUTBOUND_ACTIONS,
    INBOUND_ACTIONS,
    QUARANTINE_ACTIONS,
)
from app.services.warehouse_movements.envelope import (
    MovementEnvelope,
    LocationKey,
    MovementState,
    LocationType,
)
from app.services.warehouse_movements.fifo import allocations_value


BATCHES_COLLECTION = "warehouse_batches"


def canonical_batch_number(movement_id: str, layer_sequence: int) -> str:
    """5C-C19 F-2 — a non-null, per-layer-unique `batch_number`.

    `warehouse_batches` carries the legacy unique index
    `(org_id, batch_number)` (`fifo_service.ensure_indexes`). Canonical
    projection rows used to leave `batch_number` absent, which Mongo
    indexes as `null`, so the SECOND canonical layer of a tenant
    collided with the first. Each projection row is already keyed by
    `(movement_id, layer_sequence)`; deriving the batch number from
    that key makes it unique and deterministic (a replay or a rebuild
    writes the same value) without changing or dropping any index and
    without touching existing data.
    """
    return f"CWS-{movement_id}-{int(layer_sequence)}"



def movement_exact_value(env) -> Decimal:
    """5C-C24 F-55-C23-01 — exact value of one outbound movement: the sum
    of its FIFO `layer_allocations` (falls back to quantity × unit_value
    only for a row without allocations). Works for a `MovementEnvelope`
    (LayerAllocation objects or dicts) and for a rebuild `_RowShim`."""
    return allocations_value(
        getattr(env, "layer_allocations", None) or [],
        fallback_quantity=getattr(env, "quantity", None),
        fallback_unit_value=getattr(env, "unit_value", None),
    )

MATERIAL_ENTRIES_COLLECTION = "material_entries"
IN_TRANSIT_COLLECTION = "warehouse_in_transit"


async def apply_projection(
    tenant_db,
    env: MovementEnvelope,
    *,
    session=None,
    hints: Optional[Dict[str, Any]] = None,
) -> None:
    """Update projections from one canonical movement.

    Called inside the command service's transaction. A rollback reverses
    every projection update (same Mongo session throughout).

    Parameters
    ----------
    tenant_db : AsyncIOMotorDatabase
        The per-tenant Mongo database.
    env : MovementEnvelope
        The ledger line just written.
    session : AsyncIOMotorClientSession, optional
        The transaction session.
    hints : dict, optional
        Extra context from the service that the projector would
        otherwise have to re-derive. Known keys:
          * `unresolved_discrepancy_movement_id` (str): id of the
            `transit_discrepancy` row the service appended for the
            unresolved remainder of a partial acceptance;
          * `unresolved_layer_allocations` (list): the proportional
            layers that correspond to the unresolved remainder;
          * `acceptance_line_id` (str): per-acceptance identifier.
        Unknown keys are ignored — this is a forward-compatible channel.
    """
    hints = hints or {}
    act = env.action

    # 1. Source drain for every outbound (except quarantine_release and
    # write_off which are handled explicitly below).
    if act in {a.value for a in OUTBOUND_ACTIONS}:
        await _drain_batches(tenant_db, env, session=session)
    # 1b. 5C-C25 (Р18) — a quarantine entry / release with a source moves
    # traced FIFO layers between two states of one location: drain them.
    if act in {a.value for a in QUARANTINE_ACTIONS} and env.layer_allocations:
        await _drain_batches(tenant_db, env, session=session)

    # 2. Direct inbound (new layers from supplier etc.)
    if act in {a.value for a in INBOUND_ACTIONS}:
        if act == CanonicalAction.ACCEPT_PROJECT_DELIVERY.value:
            # Acceptance opens destination layers from the traced
            # dispatch layers rather than from a fresh unit_value, so
            # value is conserved.
            await _open_destination_from_layers(tenant_db, env, session=session)
        else:
            await _open_batch(tenant_db, env, session=session)

    # 3. 5C-C25 (Р17) — project material cost rows (`material_entries`).
    # Cost is recognised when material is ACCEPTED on a project (and on a
    # direct supplier delivery to a project); a lot that leaves a project
    # (return to a warehouse, transfer to another project) reduces that
    # project's cost when it is accepted at its destination. Consumption
    # per SMR and a project write-off („фира", Р10) are allocation rows
    # only — never a second cost. One builder for live, rebuild and sync.
    for row in material_cost_rows(
            env, transit_origin=hints.get("transit_origin")
            or getattr(env, "transit_origin", None)):
        await tenant_db[MATERIAL_ENTRIES_COLLECTION].update_one(
            {"tenant_id": env.tenant_id, "org_id": env.tenant_id, "id": row["id"]},
            {"$set": row},
            upsert=True,
            session=session,
        )

    # 4. Dispatch / transfer open an in-transit bucket mirroring the
    # dispatched layers so a later acceptance can split them.
    if act in {
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT.value,
        CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE.value,
        CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE.value,
        CanonicalAction.TRANSFER_PROJECT_TO_PROJECT.value,
    }:
        await _open_in_transit(tenant_db, env, session=session,
                               transfer_target=hints.get("transfer_target"))

    # 5. Acceptance closes in-transit (decrements unresolved).
    if act == CanonicalAction.ACCEPT_PROJECT_DELIVERY.value:
        await _close_in_transit(tenant_db, env, session=session)

    # 6. QUARANTINE_ENTRY: destination credit at state=quarantine with
    # the traced layers (quarantine is a state, not a location — the
    # location is a real warehouse).
    if act == CanonicalAction.QUARANTINE_ENTRY.value:
        await _open_destination_from_layers(tenant_db, env, session=session)

    # 7. QUARANTINE_RELEASE: destination credit at state=free (or
    # whatever the envelope says) using the traced layers from the
    # source quarantine bucket.
    if act == CanonicalAction.QUARANTINE_RELEASE.value:
        await _open_destination_from_layers(tenant_db, env, session=session)

    # 8. Side effect: if the acceptance generated an unresolved
    # discrepancy row, update the in-transit projection unresolved
    # layer provenance so a later resolution has the data it needs.
    unresolved_mv_id = hints.get("unresolved_discrepancy_movement_id")
    if unresolved_mv_id and act == CanonicalAction.ACCEPT_PROJECT_DELIVERY.value:
        await _record_unresolved_layers(
            tenant_db, env, session=session,
            unresolved_movement_id=unresolved_mv_id,
            layer_allocations=hints.get("unresolved_layer_allocations") or [],
        )

    # 9. CODEX C13.2 — Rule B resolution facts. When the acceptance
    # cumulatively closed the lot, the service appended
    # `discrepancy_resolved` ledger rows; the projector reflects them
    # by removing the matching entries from the active
    # `warehouse_in_transit.unresolved_discrepancies` map. This
    # satisfies the lifecycle requirement that `10→3→4→3` AND
    # `10→8→2` end with zero active unresolved quantity/value/layers
    # and no duplicate/open discrepancy on the projection.
    resolved_mv_ids = hints.get("resolved_discrepancy_movement_ids") or []
    resolving_dispatch_mv_id = hints.get("resolving_dispatch_movement_id")
    if (resolved_mv_ids
            and resolving_dispatch_mv_id
            and act == CanonicalAction.ACCEPT_PROJECT_DELIVERY.value):
        await _close_unresolved_discrepancies(
            tenant_db, env, session=session,
            dispatch_movement_id=resolving_dispatch_mv_id,
            resolved_discrepancy_movement_ids=list(resolved_mv_ids),
        )


async def _open_batch(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    """Open a single-layer batch row for a new inbound movement.

    Used for RECEIVE_FROM_SUPPLIER / RECEIVE_FROM_SUPPLIER_TO_PROJECT —
    the only canonical origin of a NEW stock layer.
    """
    doc = {
        "projection_source": "canonical_warehouse_service",
        "projection_version": 2,
        "tenant_id": env.tenant_id,
        "org_id": env.tenant_id,
        "movement_id": env.movement_id,
        "layer_source_movement_id": env.movement_id,
        "layer_sequence": 1,
        "batch_number": canonical_batch_number(env.movement_id, 1),
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
        {"tenant_id": env.tenant_id, "org_id": env.tenant_id, "movement_id": env.movement_id},
        {"$set": doc, "$setOnInsert": {"opened_from": env.movement_id}},
        upsert=True,
        session=session,
    )


async def _open_destination_from_layers(
    tenant_db, env: MovementEnvelope, *, session=None,
) -> None:
    """Open destination batch rows from traced `layer_allocations`.

    Used by acceptance / quarantine_entry / quarantine_release: each
    traced source layer becomes a destination layer at the acceptance
    location, preserving the ORIGINAL unit value. Quantity and value
    are conserved (C11.4 / C11.5).

    A destination row is keyed by (acceptance_movement_id, source_layer)
    so a replay of the same acceptance does not open duplicate rows.
    """
    allocations = env.layer_allocations or []
    # Fallback: if the envelope has no traced layers (e.g. acceptance of
    # a direct supplier delivery), credit a single layer at the carrier
    # unit_value.
    if not allocations:
        if env.destination is None:
            return
        qty = env.accepted_quantity if env.accepted_quantity is not None else env.quantity
        if qty is None or Decimal(str(qty)) == 0:
            return
        doc = {
            "projection_source": "canonical_warehouse_service",
            "projection_version": 2,
            "tenant_id": env.tenant_id,
            "org_id": env.tenant_id,
            "movement_id": env.movement_id,
            "layer_source_movement_id": env.movement_id,
            "layer_sequence": 1,
            "batch_number": canonical_batch_number(env.movement_id, 1),
            "item_id": env.item_id,
            "unit": env.unit,
            "quantity": str(qty),
            "remaining_quantity": str(qty),
            "unit_value": str(env.unit_value),
            "currency": env.currency,
            "location": env.destination,
            "project_id": env.project_id,
            "state": (env.destination or {}).get("state"),
            "received_at": env.recorded_at,
        }
        await tenant_db[BATCHES_COLLECTION].update_one(
            {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
             "movement_id": env.movement_id,
             "layer_sequence": 1},
            {"$set": doc},
            upsert=True,
            session=session,
        )
        return

    for seq, alloc in enumerate(allocations, start=1):
        qty = Decimal(str(alloc["quantity"]))
        unit_value = Decimal(str(alloc["unit_value"]))
        src_mv = str(alloc["source_movement_id"])
        doc = {
            "projection_source": "canonical_warehouse_service",
            "projection_version": 2,
            "tenant_id": env.tenant_id,
            "org_id": env.tenant_id,
            "movement_id": env.movement_id,
            "layer_source_movement_id": src_mv,
            "layer_sequence": seq,
            "batch_number": canonical_batch_number(env.movement_id, seq),
            "item_id": env.item_id,
            "unit": env.unit,
            "quantity": str(qty),
            "remaining_quantity": str(qty),
            "unit_value": str(unit_value),
            "currency": env.currency,
            "location": env.destination,
            "project_id": env.project_id,
            "state": (env.destination or {}).get("state") if env.destination else None,
            "received_at": env.recorded_at,
        }
        await tenant_db[BATCHES_COLLECTION].update_one(
            {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
             "movement_id": env.movement_id,
             "layer_sequence": seq},
            {"$set": doc},
            upsert=True,
            session=session,
        )


async def _drain_batches(tenant_db, env: MovementEnvelope, *, session=None) -> None:
    """Decrement `remaining_quantity` on every destination batch named
    by this outbound movement's allocations.

    `allocations` always comes from the server-side FIFO allocator and
    is deterministic; it names each origin (`source_movement_id`,
    `layer_sequence`) pair.
    """
    for alloc in env.layer_allocations:
        src_id = alloc["source_movement_id"]
        src_seq = int(alloc.get("layer_sequence") or 1)
        qty = Decimal(str(alloc["quantity"]))
        # The destination row of the layer is keyed by its
        # `layer_source_movement_id` + `layer_sequence`. Earlier
        # ingestions wrote `movement_id=src_id` so support both shapes
        # for compatibility with pre-C11 rows.
        # 5C-C24 F-55-C23-01 — the FIFO layer identity is exactly the
        # batch key (`movement_id`, `layer_sequence`), so that row is
        # looked up FIRST. The older shapes are only a fallback: with a
        # single `$or`, a warehouse allocation `(receive, 1)` could match a
        # PROJECT acceptance batch whose `layer_source_movement_id` is that
        # receive and drain the wrong bucket.
        proj = {"quantity": 1, "consumed_quantity": 1, "_id": 1}
        batch = await tenant_db[BATCHES_COLLECTION].find_one(
            {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
             "movement_id": src_id, "layer_sequence": src_seq},
            proj, session=session)
        if not batch:
            batch = await tenant_db[BATCHES_COLLECTION].find_one(
                {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
                 "movement_id": src_id, "layer_sequence": {"$exists": False}},
                proj, session=session)
        if not batch:
            batch = await tenant_db[BATCHES_COLLECTION].find_one(
                {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
                 "layer_source_movement_id": src_id, "layer_sequence": src_seq},
                proj, session=session)
        if not batch:
            continue
        prior_consumed = Decimal(str(batch.get("consumed_quantity") or "0"))
        total_qty = Decimal(str(batch.get("quantity") or "0"))
        new_consumed = prior_consumed + qty
        new_remaining = max(total_qty - new_consumed, Decimal("0"))
        await tenant_db[BATCHES_COLLECTION].update_one(
            {"_id": batch["_id"], "tenant_id": env.tenant_id, "org_id": env.tenant_id},
            {"$set": {
                "consumed_quantity": str(new_consumed),
                "remaining_quantity": str(new_remaining),
                "last_drained_at": env.recorded_at,
            }},
            session=session,
        )


PROJECT_LOCATION_TYPES = (LocationType.PROJECT.value, LocationType.SUBPROJECT.value)
WAREHOUSE_LOCATION_TYPES = (LocationType.CENTRAL_WAREHOUSE.value,
                            LocationType.SMALL_WAREHOUSE.value)

# 5C-C25 (Р17) — `movement_kind` of the rows that ARE project cost (signed
# `total_value`) and of the rows that only ALLOCATE it (value in
# `movement_value`, `total_value` 0).
COST_ROW_KINDS = ("accept", "return", "transfer_out")
ALLOCATION_ROW_KINDS = ("consume", "write_off")


def is_project_location(loc: Optional[Dict[str, Any]]) -> bool:
    """True when a ledger location dict is a project / subproject bucket."""
    return bool(loc) and _loc_type(loc) in PROJECT_LOCATION_TYPES


def _loc_type(loc: Any) -> Optional[str]:
    if loc is None:
        return None
    if isinstance(loc, dict):
        return loc.get("location_type")
    lt = getattr(loc, "location_type", None)
    return getattr(lt, "value", lt)


def _loc_id(loc: Any) -> Optional[str]:
    if loc is None:
        return None
    if isinstance(loc, dict):
        return loc.get("location_id")
    return getattr(loc, "location_id", None)


def _project_of(loc: Any, fallback_project_id: Optional[str]) -> Optional[str]:
    """The project a project/subproject bucket belongs to."""
    if _loc_type(loc) == LocationType.PROJECT.value:
        return _loc_id(loc)
    if _loc_type(loc) == LocationType.SUBPROJECT.value:
        return fallback_project_id
    return None


def material_cost_rows(env, *, transit_origin: Optional[Dict[str, Any]] = None) -> list:
    """5C-C25 (Р17, Крум 06.11.2026) — the `material_entries` rows one
    canonical movement produces. Deterministic: the same ledger row always
    yields the same rows (live projector, `rebuild_from_ledger` and
    `/material-entries/sync` all call this). Values are the EXACT FIFO sum
    of the movement's layer allocations (5C-C24), never client input.

      * ACCEPT_PROJECT_DELIVERY landing on a project / subproject →
        ``accept`` row, ``total_value = +V`` (cost of the whole accepted
        quantity, at the traced layers' values).
      * RECEIVE_FROM_SUPPLIER_TO_PROJECT (direct delivery) → ``accept`` row,
        ``direct_delivery = true``, ``+V``.
      * ACCEPT_PROJECT_DELIVERY of a lot whose transfer LEFT a project
        (``transit_origin`` = project) → ``return`` (into a warehouse) or
        ``transfer_out`` (into another project) row on the ORIGIN project,
        ``total_value = −V``. Cost moves with the lot when it is accepted
        (Р18: "кредитира се само при приемане"); an unaccepted remainder
        stays the origin project's cost.
      * CONSUME_TO_SMR → ``consume`` row: allocation per SMR / package only,
        ``total_value = 0``, the value in ``movement_value``.
      * WRITE_OFF from a project → ``write_off`` row („фира", Р10): the
        written-off value in ``movement_value``; it is already part of the
        accepted cost, so it is reported as its own line, never added.
    """
    act = env.action
    rows = []
    base = {
        "projection_source": "canonical_warehouse_service",
        "projection_version": 3,
        "tenant_id": env.tenant_id,
        "org_id": env.tenant_id,
        "movement_id": env.movement_id,
        "subproject_id": env.subproject_id,
        "smr_id": env.smr_id,
        "work_package_id": env.work_package_id,
        "item_id": env.item_id,
        "unit": env.unit,
        "currency": env.currency,
        "recorded_at": env.recorded_at,
        "ledger_sequence": None,
    }

    def _unit(v):
        return str(Decimal(str(v if v is not None else "0")))

    if act in (CanonicalAction.ACCEPT_PROJECT_DELIVERY.value,
               CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT.value):
        qty = Decimal(str(env.accepted_quantity if env.accepted_quantity is not None
                          else env.quantity))
        value = movement_exact_value(env)
        dest = env.destination
        dest_project = _project_of(dest, env.project_id)
        if dest_project:
            rows.append(dict(base, **{
                "id": f"me_{env.movement_id}",
                "project_id": dest_project,
                "movement_kind": "accept",
                "cost_recognized": True,
                "direct_delivery": act == CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT.value,
                "quantity": str(qty),
                "unit_value": _unit(env.unit_value),
                "total_value": str(value),
                "movement_value": str(value),
                "accepted_at": env.recorded_at,
            }))
        origin = transit_origin or {}
        origin_loc = origin.get("location")
        origin_project = _project_of(origin_loc, origin.get("project_id"))
        if act == CanonicalAction.ACCEPT_PROJECT_DELIVERY.value and origin_project:
            kind = "transfer_out" if dest_project else "return"
            rows.append(dict(base, **{
                "id": f"me_{env.movement_id}_out",
                "project_id": origin_project,
                "subproject_id": (_loc_id(origin_loc)
                                  if _loc_type(origin_loc) == LocationType.SUBPROJECT.value
                                  else None),
                "smr_id": None, "work_package_id": None,
                "movement_kind": kind,
                "cost_recognized": True,
                "quantity": str(-qty),
                "unit_value": _unit(env.unit_value),
                "total_value": str(-value),
                "movement_value": str(-value),
                "to_location": dest if isinstance(dest, dict) or dest is None
                else dest.to_dict(),
                "transfer_movement_id": origin.get("dispatch_movement_id"),
                "accepted_at": env.recorded_at,
            }))
        return rows

    if act == CanonicalAction.CONSUME_TO_SMR.value:
        value = movement_exact_value(env)
        rows.append(dict(base, **{
            "id": f"me_{env.movement_id}",
            "project_id": env.project_id or _project_of(env.source, env.project_id),
            "movement_kind": "consume",
            "cost_recognized": False,
            "allocation_only": True,
            "quantity": str(Decimal(str(env.quantity))),
            "unit_value": _unit(env.unit_value),
            "total_value": "0",
            "movement_value": str(value),
            "consumed_at": env.recorded_at,
        }))
        return rows

    if act == CanonicalAction.WRITE_OFF.value and is_project_location(env.source):
        value = movement_exact_value(env)
        rows.append(dict(base, **{
            "id": f"me_{env.movement_id}",
            "project_id": env.project_id or _project_of(env.source, env.project_id),
            "movement_kind": "write_off",
            "cost_recognized": False,
            "allocation_only": True,
            "waste": True,
            "quantity": str(Decimal(str(env.quantity))),
            "unit_value": _unit(env.unit_value),
            "total_value": "0",
            "movement_value": str(value),
            "written_off_at": env.recorded_at,
            "reason": env.reason,
        }))
        return rows
    return rows


async def _open_in_transit(
    tenant_db, env: MovementEnvelope, *, session=None,
    transfer_target: Optional[Dict[str, str]] = None,
) -> None:
    """Open an in-transit bucket keyed by dispatch_movement_id.

    Mirrors the dispatched layer_allocations so a later acceptance can
    split them proportionally. The in-transit row carries full value
    provenance and `source_location` for direct-URL audit.
    """
    row = {
        "projection_source": "canonical_warehouse_service",
        "projection_version": 2,
        "tenant_id": env.tenant_id,
        "org_id": env.tenant_id,
        "dispatch_movement_id": env.movement_id,
        "item_id": env.item_id,
        "unit": env.unit,
        "dispatched_quantity": str(env.quantity),
        "accepted_quantity": "0",
        "unresolved_quantity": str(env.quantity),
        "project_id": env.project_id,
        "source_location": env.source,
        "destination_location": env.destination,
        "layer_allocations": list(env.layer_allocations or []),
        "unit_value": str(env.unit_value),
        "currency": env.currency,
        "dispatched_at": env.recorded_at,
        # 5C-C21 F-13 — the warehouse a transfer is for (None for a
        # project dispatch). Live: from the service hint; rebuild: from
        # the ledger row.
        "transfer_target": transfer_target or getattr(env, "transfer_target", None),
    }
    await tenant_db[IN_TRANSIT_COLLECTION].update_one(
        {"tenant_id": env.tenant_id, "org_id": env.tenant_id, "dispatch_movement_id": env.movement_id},
        {"$set": row},
        upsert=True,
        session=session,
    )


async def _close_in_transit(
    tenant_db, env: MovementEnvelope, *, session=None,
) -> None:
    """Decrement unresolved on acceptance; leave the row until fully resolved."""
    dispatch_id = env.dispatch_movement_id
    if not dispatch_id:
        return
    accepted = Decimal(str(env.accepted_quantity or env.quantity or "0"))
    doc = await tenant_db[IN_TRANSIT_COLLECTION].find_one(
        {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
         "dispatch_movement_id": dispatch_id},
        session=session,
    )
    if not doc:
        # No projection row — compute dispatched from the LEDGER as the
        # authoritative source (C07/C11.8). This is a reconcile path.
        return
    prior_accepted = Decimal(str(doc.get("accepted_quantity") or "0"))
    dispatched = Decimal(str(doc.get("dispatched_quantity") or "0"))
    new_accepted = prior_accepted + accepted
    unresolved = max(dispatched - new_accepted, Decimal("0"))
    await tenant_db[IN_TRANSIT_COLLECTION].update_one(
        {"tenant_id": env.tenant_id, "org_id": env.tenant_id, "dispatch_movement_id": dispatch_id},
        {"$set": {"accepted_quantity": str(new_accepted),
                  "unresolved_quantity": str(unresolved),
                  "last_accepted_at": env.recorded_at}},
        session=session,
    )


async def _record_unresolved_layers(
    tenant_db, env: MovementEnvelope, *, session=None,
    unresolved_movement_id: str,
    layer_allocations: list,
) -> None:
    """Record the proportional layers that back an unresolved remainder.

    These are stored on the dedicated transit_discrepancy ledger row by
    the command service, but also surfaced on the in-transit projection
    so a resolution UI/report can see them without a second query.

    CODEX C13.2 — fixed to use `$set` with a dotted field path so
    adding a second discrepancy for the same dispatch APPENDS instead
    of overwriting the first entry; the active map now carries every
    open discrepancy keyed by its movement_id.
    """
    if not env.dispatch_movement_id:
        return
    # 5C-C25 — live/rebuild parity: the entry carries the DISCREPANCY row's
    # own `recorded_at` (the rebuild only has that row). Before C25 the live
    # path stamped the acceptance's time, so a rebuild changed the entry.
    disc_row = await tenant_db["warehouse_transactions"].find_one(
        {"tenant_id": env.tenant_id, "movement_id": unresolved_movement_id},
        {"recorded_at": 1, "_id": 0}, session=session)
    await tenant_db[IN_TRANSIT_COLLECTION].update_one(
        {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
         "dispatch_movement_id": env.dispatch_movement_id},
        {"$set": {
            f"unresolved_discrepancies.{unresolved_movement_id}": {
                "layer_allocations": list(layer_allocations or []),
                "recorded_at": (disc_row or {}).get("recorded_at") or env.recorded_at,
            },
        }},
        session=session,
    )


async def _close_unresolved_discrepancies(
    tenant_db, env: MovementEnvelope, *, session=None,
    dispatch_movement_id: str,
    resolved_discrepancy_movement_ids: list,
) -> None:
    """CODEX C13.2 — reflect append-only `discrepancy_resolved` ledger
    rows on the active `warehouse_in_transit` projection.

    For each resolved discrepancy movement_id, remove its entry from
    the `unresolved_discrepancies` map so the active projection
    returns zero open discrepancies when the cumulative acceptance
    closes the lot. The ledger row that originally opened the
    discrepancy is NOT mutated — the resolution is a new append-only
    fact; `rebuild_from_ledger` replays acceptance → discrepancy →
    resolution in sequence and reaches the same active state.
    """
    if not dispatch_movement_id or not resolved_discrepancy_movement_ids:
        return
    unset_doc = {
        f"unresolved_discrepancies.{mv_id}": ""
        for mv_id in resolved_discrepancy_movement_ids if mv_id
    }
    if not unset_doc:
        return
    await tenant_db[IN_TRANSIT_COLLECTION].update_one(
        {"tenant_id": env.tenant_id, "org_id": env.tenant_id,
         "dispatch_movement_id": dispatch_movement_id},
        {"$unset": unset_doc,
         "$set": {
             "last_resolved_at": env.recorded_at,
             "last_resolving_acceptance_movement_id": env.movement_id,
         }},
        session=session,
    )


# ----------------------------------------------------------------------
# Replay / reconciliation (C11.8)
# ----------------------------------------------------------------------
async def rebuild_from_ledger(tenant_db, *, tenant_id: str, session=None) -> Dict[str, Any]:
    """Rebuild `warehouse_batches`, `warehouse_in_transit`, and
    `material_entries` projection rows from the canonical ledger.

    Only rows tagged `projection_source=canonical_warehouse_service`
    are deleted first; historical rows (pre-TASK-5C) remain for
    reconciliation. Then every canonical ledger row is replayed in
    `ledger_sequence` order through `apply_projection`.

    Returns counts for parity assertion by tests.
    """
    for coll in (BATCHES_COLLECTION, IN_TRANSIT_COLLECTION, MATERIAL_ENTRIES_COLLECTION):
        await tenant_db[coll].delete_many(
            {"tenant_id": tenant_id,
             "projection_source": "canonical_warehouse_service"},
            session=session,
        )

    # CODEX C13.2 — rebuild processes:
    #   * canonical actions normally;
    #   * `transit_discrepancy` rows re-create the unresolved map
    #     entry on `warehouse_in_transit` (append-only replay);
    #   * `discrepancy_resolved` rows close the matching entry so
    #     the active projection converges to the exact post-ledger
    #     state (identical for any permutation that reaches full
    #     cumulative acceptance).
    cursor = tenant_db["warehouse_transactions"].find(
        {"tenant_id": tenant_id},
        {"_id": 0},
        session=session,
    ).sort([("ledger_sequence", 1), ("recorded_at", 1), ("movement_id", 1)])

    rebuilt = 0
    async for row in cursor:
        act = row.get("action")
        if act == "transit_discrepancy":
            # Shim path — rebuild the unresolved map entry.
            dispatch_mv_id = row.get("dispatch_movement_id")
            disc_mv_id = row.get("movement_id")
            if dispatch_mv_id and disc_mv_id:
                await tenant_db[IN_TRANSIT_COLLECTION].update_one(
                    {"tenant_id": tenant_id, "org_id": tenant_id,
                     "dispatch_movement_id": dispatch_mv_id},
                    {"$set": {
                        f"unresolved_discrepancies.{disc_mv_id}": {
                            "layer_allocations": row.get("layer_allocations") or [],
                            "recorded_at": row.get("recorded_at"),
                        },
                    }},
                    session=session,
                )
            rebuilt += 1
            continue
        if act == "discrepancy_resolved":
            dispatch_mv_id = row.get("dispatch_movement_id")
            resolved_mv_id = row.get("resolves_discrepancy_movement_id")
            if dispatch_mv_id and resolved_mv_id:
                await tenant_db[IN_TRANSIT_COLLECTION].update_one(
                    {"tenant_id": tenant_id, "org_id": tenant_id,
                     "dispatch_movement_id": dispatch_mv_id},
                    {"$unset": {
                        f"unresolved_discrepancies.{resolved_mv_id}": "",
                    }, "$set": {
                        "last_resolved_at": row.get("recorded_at"),
                        "last_resolving_acceptance_movement_id": (
                            row.get("resolved_by_acceptance_movement_id")
                        ),
                    }},
                    session=session,
                )
            rebuilt += 1
            continue
        # Reconstruct a minimal MovementEnvelope-shaped object so we can
        # reuse the regular projector. Use the row dict directly where
        # the projector accepts dot-attribute access via a tiny shim.
        env = _RowShim(row)
        hints: Dict[str, Any] = {}
        await apply_projection(tenant_db, env, session=session, hints=hints)
        rebuilt += 1
    return {"tenant_id": tenant_id, "projection_rows_rebuilt_from_ledger": rebuilt}


class _RowShim:
    """Light wrapper so `apply_projection` can accept a raw ledger dict
    during a projection rebuild."""
    def __init__(self, row: Dict[str, Any]):
        self._r = row

    def __getattr__(self, item):
        v = self._r.get(item)
        if item == "layer_allocations":
            return v or []
        if item in {"quantity", "accepted_quantity", "unit_value"}:
            return Decimal(str(v)) if v is not None else (Decimal("0") if item == "unit_value" else v)
        return v
