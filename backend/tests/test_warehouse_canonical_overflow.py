"""Pagination/overflow correctness.

FLOW-009 "Complete projections; response pagination must not truncate
calculations". When more than 1000 ledger rows exist, the balance
projection must still be exact — not capped at 1000.

TASK 5C: this test exercises >1000 inbound rows into one bucket and
verifies the free balance equals the sum. Required real-Mongo.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

from .warehouse_canonical_conftest import (
    canonical_mongo_db, allow_always_gate, require_replica_set_or_fail,
)
from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType,
)
from app.services.warehouse_movements.queries import (
    item_balance_by_location, free_balance as svc_free_balance,
)
from app.services.warehouse_movements.service import (
    CommandService, CommandInput,
)


class _Ctx:
    def __init__(self, org_id: str):
        self.org_id = org_id


def _tenant_data(db, org_id="org_test"):
    from app.tenancy.data_access import TenantData
    return TenantData.for_resolved_org(db, org_id)


@pytest.mark.asyncio
async def test_balance_scan_over_1200_inbound_rows_is_complete(
    canonical_mongo_db, allow_always_gate,
):
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    dest = LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_bulk")
    src = LocationKey(LocationType.SUPPLIER, "sup_bulk")

    # 1200 inbound rows of 1 unit each
    N = 1200
    for i in range(N):
        await svc.execute(_Ctx("org_test"), db, coll, CommandInput(
            action=CanonicalAction.RECEIVE_FROM_SUPPLIER,
            tenant_id="org_test",
            actor_id="u",
            item_id="it",
            unit="bag",
            quantity=Decimal("1"),
            idempotency_key=f"bulk-{i}-{uuid.uuid4().hex[:4]}",
            source=src, destination=dest,
            unit_value=Decimal("1"),
        ))

    bal = await svc_free_balance(
        coll, tenant_id="org_test", item_id="it", location=dest,
    )
    assert bal == Decimal(str(N)), f"expected {N}, got {bal}"

    rows = await item_balance_by_location(
        coll, tenant_id="org_test", item_id="it",
    )
    total = sum(Decimal(r["quantity"]) for r in rows)
    assert total == Decimal(str(N))
