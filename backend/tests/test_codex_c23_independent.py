"""Independent PR55 review probes; synthetic local replica set only."""
from decimal import Decimal
import uuid
import pytest
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.service import CommandInput, CommandService
from app.services.warehouse_movements.indexes import ensure_required_indexes_at_startup, verify_required_indexes
from app.services.warehouse_movements.errors import IndexMissingError
from app.services.warehouse_movements.queries import stock_at
from app.services.canonical_material_cost import project_material_cost
from app.tenancy.data_access import TenantData

pytest_plugins = ["tests.warehouse_canonical_conftest"]
T = "codex55"
WH = LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh")
PRJ = LocationKey(LocationType.PROJECT, "p")

class Ctx:
    tenant_id = org_id = T
    user_id = "reviewer"

async def run(svc, db, action, **kw):
    inp = CommandInput(action=action, tenant_id=T, actor_id="reviewer",
        item_id="item", unit="kg", idempotency_key=uuid.uuid4().hex, **kw)
    return await svc.execute(Ctx(), db, TenantData.for_resolved_org(db, T).warehouse_transactions, inp)

async def test_legacy_rows_allow_startup_without_rewriting_history(canonical_mongo_db):
    client, _ = canonical_mongo_db
    name = "codex55_legacy_" + uuid.uuid4().hex[:8]
    db = client[name]
    # Shape emitted by main's procurement.issue_to_project: no canonical IDs.
    rows = [{"id": f"issue-{i}", "org_id": T, "project_id": "p", "type": "issue",
             "status": "posted", "created_at": "2026-01-15T09:00:00+00:00",
             "lines": [{"material_name": "cement", "qty_issued": 10,
                        "unit_price": 10, "total_price": 100}]} for i in range(2)]
    try:
        await db.warehouse_transactions.insert_many(rows)
        before = await db.warehouse_transactions.find({}, {"_id": 0}).to_list(None)
        result = await ensure_required_indexes_at_startup(db)
        print("legacy startup:", result)
        assert await db.warehouse_transactions.find({}, {"_id": 0}).to_list(None) == before
        if not result["ok"]:
            with pytest.raises(IndexMissingError):
                await verify_required_indexes(db)
        assert result["ok"], result
    finally:
        await client.drop_database(name)

async def mixed_delivery(client, db, gate):
    svc = CommandService(client, gate=gate)
    for qty, price in [("10000", "1"), ("20000", "2")]:
        await run(svc, db, CanonicalAction.RECEIVE_FROM_SUPPLIER,
            source=LocationKey(LocationType.SUPPLIER, "supplier"), destination=WH,
            quantity=Decimal(qty), unit_value=Decimal(price))
    dispatch = await run(svc, db, CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
        source=WH, quantity=Decimal("30000"), project_id="p")
    accepted = await run(svc, db, CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        destination=PRJ, quantity=Decimal("30000"), accepted_quantity=Decimal("30000"),
        dispatch_movement_id=dispatch.movement_id, project_id="p")
    return svc, accepted

async def test_mixed_price_delivery_conserves_value_and_layers(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    _, accepted = await mixed_delivery(client, db, allow_always_gate)
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    stock = await stock_at(coll, tenant_id=T, item_id="item", location=PRJ)
    allocated_value = sum(Decimal(a["quantity"]) * Decimal(a["unit_value"])
                          for a in accepted.envelope["layer_allocations"])
    print("accepted allocations value:", allocated_value, "project stock:", stock)
    assert allocated_value == Decimal("50000")
    assert Decimal(stock["total_value"]) == allocated_value
    assert stock["layer_count"] == 2

async def test_mixed_price_consumption_recognizes_exact_fifo_cost(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc, _ = await mixed_delivery(client, db, allow_always_gate)
    await run(svc, db, CanonicalAction.CONSUME_TO_SMR, source=PRJ,
        quantity=Decimal("30000"), project_id="p", smr_id="smr")
    cost = await project_material_cost(TenantData.for_resolved_org(db, T), T, "p")
    print("recognized project cost:", cost["total_cost"])
    assert cost["total_cost"] == 50000.0
