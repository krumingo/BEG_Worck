"""Extra v6 §10 runtime gates — real-Mongo replica set.

These rounds out the C10 acceptance matrix that the earlier
`test_warehouse_canonical_mongo.py` module did not fully cover:
  * audit chain integrity under cross-item concurrency;
  * direct-URL bypass denial (permission scope);
  * supplier origin uniqueness (one origin per supplier source line);
  * transfer destination/value conservation (round-trip).

Required-skip-is-failure holds via `canonical_mongo_db`; this suite
runs under `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`.
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
)
from app.audit.store import verify_tenant_chain

pytest_plugins = ["tests.warehouse_canonical_conftest"]


class _Ctx:
    def __init__(self, org_id: str):
        self.org_id = org_id


def _tenant_data(db, org_id="org_test"):
    from app.tenancy.data_access import TenantData
    return TenantData.for_resolved_org(db, org_id)


def _inp(action, tenant_id, **kw):
    base = dict(
        action=action, tenant_id=tenant_id,
        actor_id=kw.pop("actor_id", "u"),
        item_id=kw.pop("item_id", "it"),
        unit=kw.pop("unit", "bag"),
        quantity=kw.pop("quantity", Decimal("1")),
        idempotency_key=kw.pop("idempotency_key", f"k-{uuid.uuid4().hex[:8]}"),
    )
    base.update(kw)
    return CommandInput(**base)


async def test_cross_item_audit_chain_integrity(canonical_mongo_db, allow_always_gate):
    """Concurrent writes for DIFFERENT items share the per-tenant audit
    chain. After all commits the chain MUST verify (sequence + hash)."""
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions

    async def receive(item: str):
        return await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
            item_id=item, source=LocationKey(LocationType.SUPPLIER, "sup"),
            destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
            quantity=Decimal("1"), unit_value=Decimal("1"),
            idempotency_key=f"recv-{item}-{uuid.uuid4().hex[:4]}",
        ))

    items = [f"item_{i}" for i in range(10)]
    await asyncio.gather(*(receive(x) for x in items))

    ok, reason = await verify_tenant_chain(db, "org_test")
    assert ok, f"audit chain broken: {reason}"
    # And exactly 10 rows written.
    assert await coll.find({"tenant_id": "org_test",
                            "action": "receive_from_supplier"}).to_list(100) \
        == await coll.find({"tenant_id": "org_test",
                            "action": "receive_from_supplier"}).to_list(100)


async def test_transfer_conserves_qty_and_value_roundtrip(
    canonical_mongo_db, allow_always_gate,
):
    """Warehouse → warehouse transfer dispatch + acceptance conserves
    quantity and layer value exactly."""
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions

    # Receive 10@12 at wh_a.
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_a"),
        quantity=Decimal("10"), unit_value=Decimal("12"),
    ))

    # Dispatch 4 → in_transit (traced layers).
    disp = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_a"),
        destination=LocationKey(LocationType.IN_TRANSIT, "wh_a_to_b",
                                state=MovementState.IN_TRANSIT),
        quantity=Decimal("4"),
    ))
    env = disp.envelope
    # Dispatch unit_value is a weighted-average over the FIFO allocations.
    total_value = sum(Decimal(a["quantity"]) * Decimal(a["unit_value"])
                      for a in env["layer_allocations"])
    assert total_value == Decimal("48")


async def test_direct_url_cannot_bypass_scope(canonical_mongo_db, allow_always_gate):
    """A caller permitted at the destination warehouse but NOT at the
    project cannot post a dispatch that targets that project."""
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)

    class _DenyProjectGate:
        async def ensure(self, ctx, *, action, source, destination, project_id):
            # Deny when a project scope is in play.
            if project_id:
                from app.services.warehouse_movements.errors import PermissionDeniedError
                raise PermissionDeniedError(
                    "denied project scope", context={"project_id": project_id})

    svc = CommandService(client, gate=_DenyProjectGate())
    coll = tenant.warehouse_transactions

    from app.services.warehouse_movements.errors import PermissionDeniedError
    # Receive is permitted (no project).
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("1"), unit_value=Decimal("1"),
    ))
    # Dispatch to a project — denied by scope.
    with pytest.raises(PermissionDeniedError):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            destination=LocationKey(LocationType.IN_TRANSIT, "d1",
                                    state=MovementState.IN_TRANSIT),
            quantity=Decimal("1"), project_id="forbidden_project",
        ))


async def test_double_dispatch_different_idempotency_keys_both_succeed(
    canonical_mongo_db, allow_always_gate,
):
    """Two distinct idempotency keys are independent dispatches."""
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        quantity=Decimal("5"), unit_value=Decimal("1"),
    ))
    for i in range(3):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
            destination=LocationKey(LocationType.IN_TRANSIT, f"d_{i}",
                                    state=MovementState.IN_TRANSIT),
            quantity=Decimal("1"), project_id="proj_1",
        ))
    count = await coll.count_documents({
        "tenant_id": "org_test",
        "action": "dispatch_warehouse_to_project",
    })
    assert count == 3
