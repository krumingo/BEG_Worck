"""Real-Mongo concurrency tests for the canonical command service.

Two parallel issues of the LAST unit of stock must produce exactly one
winner. The loser raises NegativeStockError (inside its transaction,
cleanly rolled back) and the ledger holds exactly one outbound row.

TASK 5C: required runtime skips are failure. Suite enables itself on
`WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal

import pytest

from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
)
from app.services.warehouse_movements.service import (
    CommandService, CommandInput,
)
from app.services.warehouse_movements.errors import NegativeStockError

pytest_plugins = ["tests.warehouse_canonical_conftest"]


class _Ctx:
    def __init__(self, org_id: str):
        self.org_id = org_id


def _tenant_data(db, org_id="org_test"):
    from app.tenancy.data_access import TenantData
    return TenantData.for_resolved_org(db, org_id)


def _inp(action, tenant_id, **kw):
    base = dict(
        action=action,
        tenant_id=tenant_id,
        actor_id=kw.pop("actor_id", "u"),
        item_id=kw.pop("item_id", "it"),
        unit=kw.pop("unit", "bag"),
        quantity=kw.pop("quantity", Decimal("1")),
        idempotency_key=kw.pop("idempotency_key", f"k-{uuid.uuid4().hex[:8]}"),
    )
    base.update(kw)
    return CommandInput(**base)


async def test_two_concurrent_last_unit_dispatches_one_winner(canonical_mongo_db, allow_always_gate):
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    # One unit on hand.
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("1"), unit_value=Decimal("5"),
    ))

    async def dispatch(idx: int):
        return await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
            destination=LocationKey(LocationType.IN_TRANSIT, f"disp_{idx}",
                                    state=MovementState.IN_TRANSIT),
            quantity=Decimal("1"), project_id=f"proj_{idx}",
            idempotency_key=f"disp-{idx}-{uuid.uuid4().hex[:4]}",
        ))

    r = await asyncio.gather(dispatch(1), dispatch(2), return_exceptions=True)
    wins = [x for x in r if not isinstance(x, Exception)]
    losses = [x for x in r if isinstance(x, Exception)]
    assert len(wins) == 1, f"expected exactly one winner, got {len(wins)}: {r}"
    assert len(losses) == 1
    assert isinstance(losses[0], NegativeStockError)
    # Ledger holds the single outbound row.
    outbound_count = await db["warehouse_transactions"].count_documents({
        "tenant_id": "org_test",
        "action": "dispatch_warehouse_to_project",
    })
    assert outbound_count == 1


async def test_tenant_a_b_collision_does_not_cross_wires(canonical_mongo_db, allow_always_gate):
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    client, db = canonical_mongo_db
    svc = CommandService(client, gate=allow_always_gate)
    from app.tenancy.data_access import TenantData
    tenantA = TenantData.for_resolved_org(db, "org_A")
    tenantB = TenantData.for_resolved_org(db, "org_B")
    shared_key = "SAME-KEY-FOR-BOTH"
    rA = await svc.execute(_Ctx("org_A"), db, tenantA.warehouse_transactions, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_A",
        idempotency_key=shared_key,
        source=LocationKey(LocationType.SUPPLIER, "sup_X"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("3"), unit_value=Decimal("7"),
    ))
    rB = await svc.execute(_Ctx("org_B"), db, tenantB.warehouse_transactions, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_B",
        idempotency_key=shared_key,
        source=LocationKey(LocationType.SUPPLIER, "sup_X"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_c1"),
        quantity=Decimal("4"), unit_value=Decimal("9"),
    ))
    assert rA.movement_id != rB.movement_id
    rowA = await db["warehouse_transactions"].find_one({"movement_id": rA.movement_id})
    rowB = await db["warehouse_transactions"].find_one({"movement_id": rB.movement_id})
    assert rowA["tenant_id"] == "org_A"
    assert rowB["tenant_id"] == "org_B"
