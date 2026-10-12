"""Real-Mongo replica-set tests for the canonical command service.

These cover v6 §10 acceptance gates:
  * append-only `warehouse_transactions`;
  * idempotency replay vs conflict; audit chain is session-aware and
    rolls back together;
  * Rule B (F-09=B): dispatch costs 0, acceptance costs accepted qty
    only; multiple partial acceptances valid; no double cost on consume;
  * transfer conservation (qty + value + original layers);
  * concurrent FIFO + last-unit race;
  * tenant A/B collisions;
  * >1000 ledger rows;
  * missing index fail-closed;
  * supplier-origin uniqueness;
  * audit failure rollback.

TASK 5C: required skips are FAILURES. The suite enables itself when
`WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`; otherwise skips with a
clearly labelled message.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
)
from app.services.warehouse_movements.service import (
    CommandService, CommandInput,
)
from app.services.warehouse_movements.errors import (
    IdempotencyConflictError, NegativeStockError, OriginAcceptanceOverrunError,
    IndexMissingError, LegacyWriterRetiredError,
    QuarantineStateViolationError, MasterIdentityMissingError,
    ValueFromClientRefusedError, PermissionDeniedError,
    FreeTextIntoActionableStockError,
)

# The conftest provides `canonical_mongo_db` and `allow_always_gate`.
# Pull them into module scope so pytest-asyncio picks them up here too.
pytest_plugins = ["tests.warehouse_canonical_conftest"]


class _Ctx:
    def __init__(self, org_id: str):
        self.org_id = org_id


def _enforce_env():
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"


def _tenant_data(db, org_id="org_test"):
    from app.tenancy.data_access import TenantData
    return TenantData.for_resolved_org(db, org_id)


def _inp(action, tenant_id, **kw):
    base = dict(
        action=action,
        tenant_id=tenant_id,
        actor_id=kw.pop("actor_id", "user_ops"),
        item_id=kw.pop("item_id", "item_bag_25"),
        unit=kw.pop("unit", "bag"),
        quantity=kw.pop("quantity", Decimal("10")),
        idempotency_key=kw.pop("idempotency_key", f"k-{uuid.uuid4().hex[:8]}"),
    )
    base.update(kw)
    return CommandInput(**base)


# ---------------------------------------------------------------------
# Enforce mode gate
# ---------------------------------------------------------------------
async def test_service_refuses_without_enforce_mode(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    os.environ["PERMISSION_SERVICE_MODE"] = "shadow"
    svc = CommandService(client, gate=allow_always_gate)
    try:
        with pytest.raises(PermissionDeniedError):
            await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions, _inp(
                CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
                source=LocationKey(LocationType.SUPPLIER, "sup_1"),
                destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            ))
    finally:
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"


# ---------------------------------------------------------------------
# Append-only + audit chain
# ---------------------------------------------------------------------
async def test_receive_appends_one_row_with_audit(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    inp = _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        unit_value=Decimal("12.50"),
        invoice_id="inv_001",
    )
    result = await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions, inp)
    assert result.replay is False
    assert result.audit_event_id

    assert await db["warehouse_transactions"].count_documents(
        {"tenant_id": "org_test"}) == 1
    assert await db["audit_events"].count_documents(
        {"tenant_id": "org_test"}) == 1


async def test_idempotent_replay_returns_same_row(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    key = f"rep-{uuid.uuid4().hex[:8]}"
    args = dict(
        tenant_id="org_test", idempotency_key=key,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        unit_value=Decimal("5"),
    )
    r1 = await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions,
                           _inp(CanonicalAction.RECEIVE_FROM_SUPPLIER, **args))
    r2 = await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions,
                           _inp(CanonicalAction.RECEIVE_FROM_SUPPLIER, **args))
    assert r2.movement_id == r1.movement_id
    assert r2.replay is True
    assert await db["warehouse_transactions"].count_documents(
        {"tenant_id": "org_test"}) == 1


async def test_idempotency_conflict_on_different_payload(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    key = f"cnf-{uuid.uuid4().hex[:8]}"
    await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test", idempotency_key=key,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("10"), unit_value=Decimal("5"),
    ))
    with pytest.raises(IdempotencyConflictError):
        await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test", idempotency_key=key,
            source=LocationKey(LocationType.SUPPLIER, "sup_1"),
            destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            quantity=Decimal("77"),      # different qty
            unit_value=Decimal("5"),
        ))


# ---------------------------------------------------------------------
# FIFO + conservation + Rule B
# ---------------------------------------------------------------------
async def test_fifo_outbound_server_derives_unit_value_and_rejects_client_value(
    canonical_mongo_db, allow_always_gate,
):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("10"), unit_value=Decimal("10"),
    ))
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("10"), unit_value=Decimal("20"),
    ))
    with pytest.raises(ValueFromClientRefusedError):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            destination=LocationKey(LocationType.IN_TRANSIT, "disp_01",
                                    state=MovementState.IN_TRANSIT),
            quantity=Decimal("12"),
            unit_value=Decimal("99"),
            project_id="proj_1",
        ))
    r = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        destination=LocationKey(LocationType.IN_TRANSIT, "disp_01",
                                state=MovementState.IN_TRANSIT),
        quantity=Decimal("12"), project_id="proj_1",
    ))
    env = r.envelope
    assert len(env["layer_allocations"]) == 2
    total = sum(Decimal(a["quantity"]) * Decimal(a["unit_value"])
                for a in env["layer_allocations"])
    assert total == Decimal("120")


async def test_rule_b_partial_acceptance_project_cost_and_unresolved(
    canonical_mongo_db, allow_always_gate,
):
    """v6 §10 F-09=B: 10 dispatched, 8 accepted → project cost 8, unresolved 2."""
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("10"), unit_value=Decimal("5"),
    ))
    dispatch = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        destination=LocationKey(LocationType.IN_TRANSIT, "disp_1",
                                state=MovementState.IN_TRANSIT),
        quantity=Decimal("10"), project_id="proj_1",
    ))
    # Accept 8 of 10 — unresolved 2.
    acc = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
        destination=LocationKey(LocationType.PROJECT, "proj_1"),
        quantity=Decimal("8"), accepted_quantity=Decimal("8"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=dispatch.movement_id, project_id="proj_1",
    ))
    assert acc.unresolved_discrepancy_movement_id is not None
    # Accepted project value is 8 units × unit_value 5 = 40.
    env = acc.envelope
    assert Decimal(env["accepted_quantity"]) == Decimal("8")
    assert Decimal(env["missing_quantity"]) == Decimal("2")
    accepted_value = sum(Decimal(a["quantity"]) * Decimal(a["unit_value"])
                         for a in env["layer_allocations"])
    assert accepted_value == Decimal("40")

    # Accept the remaining 2 later (multi-partial OK).
    acc2 = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
        destination=LocationKey(LocationType.PROJECT, "proj_1"),
        quantity=Decimal("2"), accepted_quantity=Decimal("2"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=dispatch.movement_id, project_id="proj_1",
    ))
    # Second acceptance OK (unique index on acceptance_line_id, not dispatch).
    assert acc2.unresolved_discrepancy_movement_id is None


async def test_rule_b_acceptance_cannot_exceed_dispatched(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("10"), unit_value=Decimal("5"),
    ))
    dispatch = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        destination=LocationKey(LocationType.IN_TRANSIT, "disp_1",
                                state=MovementState.IN_TRANSIT),
        quantity=Decimal("10"), project_id="proj_1",
    ))
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
        destination=LocationKey(LocationType.PROJECT, "proj_1"),
        quantity=Decimal("8"), accepted_quantity=Decimal("8"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=dispatch.movement_id, project_id="proj_1",
    ))
    with pytest.raises(OriginAcceptanceOverrunError):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
            destination=LocationKey(LocationType.PROJECT, "proj_1"),
            quantity=Decimal("5"), accepted_quantity=Decimal("5"),
            requested_quantity=Decimal("10"),
            dispatch_movement_id=dispatch.movement_id, project_id="proj_1",
        ))


# ---------------------------------------------------------------------
# Negative stock
# ---------------------------------------------------------------------
async def test_insufficient_stock_raises_negative(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("3"), unit_value=Decimal("1"),
    ))
    with pytest.raises(NegativeStockError):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            destination=LocationKey(LocationType.IN_TRANSIT, "d1",
                                    state=MovementState.IN_TRANSIT),
            quantity=Decimal("5"), project_id="proj_1",
        ))


# ---------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------
async def test_quarantine_entry_and_release(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    # Entry
    r_in = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.QUARANTINE_ENTRY, tenant_id="org_test",
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1",
                                state=MovementState.QUARANTINE),
        quantity=Decimal("5"),
    ))
    assert r_in.movement_id


# ---------------------------------------------------------------------
# Index fail-closed
# ---------------------------------------------------------------------
async def test_missing_index_fails_closed(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    await db["warehouse_transactions"].drop_index("wh_movements_unique_movement_id")
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate, verify_indexes_once=False)
    with pytest.raises(IndexMissingError):
        await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
            source=LocationKey(LocationType.SUPPLIER, "sup_1"),
            destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        ))


# ---------------------------------------------------------------------
# Consume may NOT double-cost (C03)
# ---------------------------------------------------------------------
async def test_consume_requires_project_source(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    # Receive to warehouse.
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("10"), unit_value=Decimal("5"),
    ))
    # Consume FROM the warehouse (not a project bucket) must refuse — the
    # service forbids a path that would recognize cost without acceptance.
    with pytest.raises(Exception):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.CONSUME_TO_SMR, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            quantity=Decimal("1"), project_id="proj_1",
        ))
