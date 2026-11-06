"""CLAUDE AUDIT probe — #55 C26d (FG-38): subproject parent binding on TRANSFERS.
_bind_subproject_parent takes parents[0] (source first) and checks only that one against
project_id. What happens for (D1) PROJECT P1 -> SUBPROJECT of P2 and (D2) SUB of P1 -> SUB of P2?
Records the scopes the permission gate is asked for, and the cost per project."""
from decimal import Decimal
import pytest
from app.services.warehouse_movements.envelope import LocationKey, LocationType
from app.services.warehouse_movements.service import CanonicalAction
from tests.test_warehouse_canonical_c22_all_reports_cutover import PROJECT, T
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run, _accepted_10

pytest_plugins = ["tests.warehouse_canonical_conftest"]
P2 = "p-probe-c26d-2"; S1 = "sp-probe-of-p1"; S2 = "sp-probe-of-p2"


async def _setup(client, gate, db):
    from tests.test_warehouse_canonical_c22_all_reports_cutover import _seed
    await _seed(db)
    for d in ({"id": P2, "code": "P2"}, {"id": S1, "code": "S1", "parent_project_id": PROJECT},
              {"id": S2, "code": "S2", "parent_project_id": P2}):
        await db["projects"].insert_one(dict(d, org_id=T, name=d["code"], status="Active"))
    run = _Run(client, gate, db)
    calls = []
    orig = gate.ensure
    async def rec(ctx, **kw):
        calls.append({k: (v.to_dict() if hasattr(v, "to_dict") else getattr(v, "value", v)) for k, v in kw.items()})
        return await orig(ctx, **kw)
    gate.ensure = rec
    return run, calls


async def _try(run, **kw):
    try:
        await run(CanonicalAction.TRANSFER_PROJECT_TO_PROJECT, quantity=Decimal("2"), **kw)
        return "OK"
    except Exception as e:
        return "%s %s" % (type(e).__name__, str(e)[:90])


async def test_d1_project_p1_to_subproject_of_p2(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run, calls = await _setup(client, allow_always_gate, db)
    await _accepted_10(run)
    prj = LocationKey(LocationType.PROJECT, PROJECT)
    r1 = await _try(run, source=prj, transfer_target=LocationKey(LocationType.SUBPROJECT, S2), project_id=PROJECT)
    r2 = await _try(run, source=prj, transfer_target=LocationKey(LocationType.SUBPROJECT, S2))
    print("\nD1 with project_id=P1:", r1, "\nD1 without project_id:", r2, "\ngate calls:", calls[-1:] if calls else None)


async def test_d2_sub_of_p1_to_sub_of_p2(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run, calls = await _setup(client, allow_always_gate, db)
    r0 = await run.receive("10", "10")
    d = await run.dispatch("5")
    await run.accept(d, "5", dest=LocationKey(LocationType.SUBPROJECT, S1), project=PROJECT)
    n = len(calls)
    r = await _try(run, source=LocationKey(LocationType.SUBPROJECT, S1),
                   transfer_target=LocationKey(LocationType.SUBPROJECT, S2))
    print("\nD2 sub(P1)->sub(P2):", r, "\ngate scopes asked:", calls[n:])


async def _cost_after(run, db, target, **kw):
    from app.services.warehouse_movements.service import CanonicalAction as A
    await _accepted_10(run)
    prj = LocationKey(LocationType.PROJECT, PROJECT)
    tr = await run(A.TRANSFER_PROJECT_TO_PROJECT, source=prj, transfer_target=target,
                   quantity=Decimal("2"), **kw)
    acc = await run(A.ACCEPT_PROJECT_DELIVERY, destination=target, quantity=Decimal("2"),
                    accepted_quantity=Decimal("2"), dispatch_movement_id=tr.movement_id, project_id=P2)
    c1 = (await run.cost(PROJECT))["total_cost"]; c2 = (await run.cost(P2))["total_cost"]
    return c1, c2, tr


async def test_d3_cost_project_to_project_baseline(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run, calls = await _setup(client, allow_always_gate, db)
    c1, c2, tr = await _cost_after(run, db, LocationKey(LocationType.PROJECT, P2), project_id=PROJECT)
    print("\nD3 P1->P2(project): cost P1=%s P2=%s sum=%s" % (c1, c2, c1 + c2))


async def test_d4_cost_project_to_subproject_of_p2(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run, calls = await _setup(client, allow_always_gate, db)
    c1, c2, tr = await _cost_after(run, db, LocationKey(LocationType.SUBPROJECT, S2))
    row = await run.coll.find_one({"movement_id": tr.movement_id}, {"_id": 0, "project_id": 1, "subproject_id": 1})
    print("\nD4 P1->sub(P2), no project_id: cost P1=%s P2=%s sum=%s; transfer row project=%s" % (c1, c2, c1 + c2, row))
