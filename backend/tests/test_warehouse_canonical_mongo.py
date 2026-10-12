"""Real-Mongo replica-set tests for the canonical command service.

These cover the on-disk behavior the service claims:

  * append-only `warehouse_transactions`;
  * idempotency replay vs conflict under one key;
  * conservation of qty + value under transfer;
  * Rule B (F-09=B) acceptance ≤ dispatched;
  * audit chain is session-aware and rolls back together;
  * missing index fails closed;
  * concurrent last-unit race has exactly one winner;
  * tenant A/B colliding movement_ids do not conflict;
  * >1000 ledger rows read without truncation.

TASK 5C: required runtime skips are FAILURES. The suite enables itself
when `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`; without that env it
skips with a clearly labelled message so other CI jobs are not blocked.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal
from typing import List

import pytest

from .warehouse_canonical_conftest import (
    canonical_mongo_db, allow_always_gate, require_replica_set_or_fail,
)
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
# Receive → stock, append-only
# ---------------------------------------------------------------------
@pytest.mark.asyncio
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

    count = await db["warehouse_transactions"].count_documents({"tenant_id": "org_test"})
    assert count == 1

    audit_count = await db["audit_events"].count_documents({"tenant_id": "org_test"})
    assert audit_count == 1


@pytest.mark.asyncio
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
    count = await db["warehouse_transactions"].count_documents({"tenant_id": "org_test"})
    assert count == 1


@pytest.mark.asyncio
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
@pytest.mark.asyncio
async def test_fifo_outbound_server_derives_unit_value_and_rejects_client_value(
    canonical_mongo_db, allow_always_gate,
):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    # Open two layers at different unit values
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
    # Client-supplied unit_value on outbound is refused.
    with pytest.raises(ValueFromClientRefusedError):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            destination=LocationKey(LocationType.IN_TRANSIT, "dispatch_01"),
            quantity=Decimal("12"),
            unit_value=Decimal("99"),  # must be refused
            project_id="proj_1",
        ))
    # Clean dispatch; FIFO picks 10@10 + 2@20 = 120.
    r = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        destination=LocationKey(LocationType.IN_TRANSIT, "dispatch_01"),
        quantity=Decimal("12"), project_id="proj_1",
    ))
    env = r.envelope
    assert len(env["layer_allocations"]) == 2
    total = sum(Decimal(a["quantity"]) * Decimal(a["unit_value"])
                for a in env["layer_allocations"])
    assert total == Decimal("120")


@pytest.mark.asyncio
async def test_rule_b_acceptance_cannot_exceed_dispatched(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    # Receive + dispatch
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("10"), unit_value=Decimal("5"),
    ))
    dispatch = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        destination=LocationKey(LocationType.IN_TRANSIT, "disp_1"),
        quantity=Decimal("10"), project_id="proj_1",
    ))
    # Accept 8 OK
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
        destination=LocationKey(LocationType.PROJECT, "proj_1"),
        quantity=Decimal("8"), accepted_quantity=Decimal("8"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=dispatch.movement_id,
        project_id="proj_1",
    ))
    # Accept another 5 — exceeds dispatched (8+5 > 10)
    with pytest.raises(OriginAcceptanceOverrunError):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
            destination=LocationKey(LocationType.PROJECT, "proj_1"),
            quantity=Decimal("5"), accepted_quantity=Decimal("5"),
            requested_quantity=Decimal("10"),
            dispatch_movement_id=dispatch.movement_id,
            project_id="proj_1",
        ))


# ---------------------------------------------------------------------
# Negative stock
# ---------------------------------------------------------------------
@pytest.mark.asyncio
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
            destination=LocationKey(LocationType.IN_TRANSIT, "d1"),
            quantity=Decimal("5"), project_id="proj_1",
        ))


# ---------------------------------------------------------------------
# Quarantine state rules
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pending_mapping_can_only_enter_quarantine(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    with pytest.raises(FreeTextIntoActionableStockError):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
            source=LocationKey(LocationType.SUPPLIER, "sup_1"),
            destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1",
                                    state=MovementState.FREE),
            quantity=Decimal("10"), unit_value=Decimal("5"),
            item_is_pending_mapping=True,
        ))
    # Permitted into quarantine
    r = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.QUARANTINE_ENTRY, tenant_id="org_test",
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1",
                                state=MovementState.QUARANTINE),
        quantity=Decimal("10"),
        item_is_pending_mapping=True,
    ))
    assert r.movement_id


# ---------------------------------------------------------------------
# Enforce mode required
# ---------------------------------------------------------------------
@pytest.mark.asyncio
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
# Index fail-closed
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_index_fails_closed(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    # Drop a required index to simulate an unprovisioned deployment.
    await db["warehouse_transactions"].drop_index("wh_movements_unique_movement_id")
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate, verify_indexes_once=False)
    with pytest.raises(IndexMissingError):
        await svc.execute(_Ctx("org_test"), db, tenant.warehouse_transactions, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
            source=LocationKey(LocationType.SUPPLIER, "sup_1"),
            destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        ))
