"""CLAUDE AUDIT probes on PR #55 5C-C21 (df48d68) — write-off as фира (Р10), Rule B for W2W transfers (Р11).

Copy next to test_probe_pr55_c19.py in <worktree>/backend/tests/ and run with real Mongo (see c19 docstring).

C21-1  receive 10@10 → project 10 → consume 3 → write-off 2 from project: summary total 50 (30+20 фира),
       still 50 after sync, after rebuild_from_ledger ×2, after recompute; exactly one write_off cost row.
C21-2  write-off from project of more than is there (9 > 5 left) → refused, no ledger row.
C21-3  W2W transfer 10 (layers 5@10 + 5@20): accept 6 then 5 → second refused (over-accept);
       accept 4 → wh_b holds 10 worth 150; no project cost row, no material_entries at all.
C21-4  accept of a W2W transfer into a project bucket (not the target) → refused.
C21-5  T2 cannot accept T's W2W transfer.
"""
from decimal import Decimal

import pytest

from app.services.warehouse_movements import LocationKey, LocationType as LT, MovementState as MS
from app.services.warehouse_movements.queries import stock_at
from tests.test_probe_pr55_c19 import _svc, _item, _x, _receive, _dispatch_accept, A, WH, PR, TR
from tests.test_warehouse_canonical_c13_mongo import _tenant_coll

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]

WH_B = LocationKey(LT.SMALL_WAREHOUSE, "wh_b", state=MS.FREE)
USER = {"id": "u", "org_id": "T", "role": "Owner", "email": "o@x"}


def _patch(monkeypatch, db):
    import importlib
    for m in ("app.routes.material_smr",):
        monkeypatch.setattr(importlib.import_module(m), "db", db)
    from app.routes import material_smr
    return material_smr


async def test_c21_1_writeoff_recognised_once_everywhere(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await db["projects"].insert_one({"id": "p1", "org_id": "T", "name": "P"})
    await _receive(svc, db, "r1", qty="10")
    await _dispatch_accept(svc, db, qty="10")
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("3"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    await _x(svc, db, action=A.WRITE_OFF, quantity=Decimal("2"), source=PR, project_id="p1",
             idempotency_key="w1")
    ms = _patch(monkeypatch, db)
    seen = {}
    seen["projector"] = (await ms.get_material_summary_for_project("T", "p1"))
    await ms.sync_material_entries("p1", user=USER)
    seen["after_sync"] = (await ms.get_material_summary_for_project("T", "p1"))
    from app.services.warehouse_movements.projections import rebuild_from_ledger
    await rebuild_from_ledger(db, tenant_id="T"); await rebuild_from_ledger(db, tenant_id="T")
    seen["after_rebuild2"] = (await ms.get_material_summary_for_project("T", "p1"))
    await ms.sync_material_entries("p1", user=USER)
    await ms.recompute_execution_package_material("p1", user=USER)
    seen["after_resync_recompute"] = (await ms.get_material_summary_for_project("T", "p1"))
    rows = await db["material_entries"].count_documents({"org_id": "T", "movement_kind": "write_off",
                                                         "cost_recognized": True})
    got = {k: (v["total_cost"], v.get("waste_cost")) for k, v in seen.items()}
    print("C21-1", got, "write_off cost rows:", rows)
    assert all(v == (50.0, 20.0) for v in got.values()), got
    assert rows == 1


async def test_c21_2_writeoff_overdraw_refused(canonical_mongo_db, allow_always_gate, monkeypatch):
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _receive(svc, db, "r1", qty="5")
    await _dispatch_accept(svc, db, qty="5")
    before = await db["warehouse_transactions"].count_documents({})
    with pytest.raises(Exception):
        await _x(svc, db, action=A.WRITE_OFF, quantity=Decimal("9"), source=PR, project_id="p1",
                 idempotency_key="wbig")
    assert await db["warehouse_transactions"].count_documents({}) == before


async def _two_layers(svc, db):
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("5"), unit_value=Decimal("10"),
             destination=WH, idempotency_key="l1")
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("5"), unit_value=Decimal("20"),
             destination=WH, idempotency_key="l2")


async def _w2w(svc, db, key="t1", qty="10", t="T"):
    return await _x(svc, db, t, action=A.TRANSFER_WAREHOUSE_TO_WAREHOUSE, quantity=Decimal(qty), source=WH,
                    transfer_target=WH_B, idempotency_key=key)


async def _acc(svc, db, tr, qty, key, dest=WH_B, t="T"):
    return await _x(svc, db, t, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal(qty),
                    accepted_quantity=Decimal(qty), requested_quantity=Decimal("10"),
                    dispatch_movement_id=tr.movement_id, destination=dest, idempotency_key=key)


async def test_c21_3_w2w_partial_overaccept_value(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _two_layers(svc, db)
    tr = await _w2w(svc, db)
    await _acc(svc, db, tr, "6", "a1")
    over_refused = False
    try:
        await _acc(svc, db, tr, "5", "a2")
    except Exception:
        over_refused = True
    await _acc(svc, db, tr, "4", "a3")
    st = await stock_at(_tenant_coll(db), tenant_id="T", item_id="I", location=WH_B)
    print("C21-3 over-accept refused:", over_refused, "wh_b stock:", st)
    me = await db["material_entries"].count_documents({})
    assert over_refused, "accepting 6+5 of a 10 transfer was allowed"
    qty = Decimal(str(st.get("quantity") if isinstance(st, dict) else st))
    assert qty == Decimal("10"), st
    if isinstance(st, dict) and st.get("value") is not None:
        assert Decimal(str(st["value"])) == Decimal("150"), st
    assert me == 0, "a W2W transfer created %d material_entries rows" % me


async def test_c21_4_w2w_accept_into_project_refused(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _two_layers(svc, db)
    tr = await _w2w(svc, db)
    with pytest.raises(Exception):
        await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal("10"),
                 accepted_quantity=Decimal("10"), requested_quantity=Decimal("10"),
                 dispatch_movement_id=tr.movement_id, project_id="p1", destination=PR, idempotency_key="ap")


async def test_c21_5_w2w_cross_tenant_accept_refused(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db); await _item(db, "T2")
    await _two_layers(svc, db)
    tr = await _w2w(svc, db)
    with pytest.raises(Exception):
        await _acc(svc, db, tr, "10", "x", t="T2")
    assert await db["warehouse_transactions"].count_documents({"tenant_id": "T2"}) == 0
