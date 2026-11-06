"""CLAUDE AUDIT probes on PR #55 5C-C19 head (d8ac3a9) — real Mongo only, real CommandService.

Copy into <worktree>/backend/tests/ and run:
  PERMISSION_SERVICE_MODE=enforce WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 \
  MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true&replicaSet=rs0' DB_NAME=probe \
  PYTHONPATH=. pytest --noconftest -q tests/test_probe_pr55_c19.py

C19-1  double count re-run with Rule-B dispatch (in_transit): receive 5@10 → dispatch → accept 5 →
       consume 3 → return 2 to warehouse; projector + sync + summary → 30, exactly one consume row.
C19-2  interleaved writers: W0-04 event → canonical → W0-04 → canonical → chain intact, no gap.
C19-3  concurrent writers: 6 canonical receives ‖ 6 W0-04 events → every success is in one intact chain;
       W0-04 failures (if any) counted and reported.
C19-4  legacy unique index warehouse_batches(org_id,batch_number) present → 3 receives + dispatch +
       accept + rebuild twice succeed.
C19-5  identical resend of consume after an unrelated consume → original movement_id, 1 ledger row;
       same key + different qty → conflict.
C19-6  dispatch to a project refused; T2 cannot accept T's dispatch.
C19-7  integrity_warnings (distinct with session) on a populated tenant does not raise.
"""
import asyncio
from decimal import Decimal

import pytest

from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
from app.audit.store import AUDIT_COLLECTION, record_event, verify_chain
from app.services.warehouse_movements import CanonicalAction as A, LocationKey, LocationType as LT, MovementState as MS
from app.services.warehouse_movements.service import CommandService, CommandInput
from tests.test_warehouse_canonical_c13_mongo import _TestCtx, _tenant_coll

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]

WH = LocationKey(LT.CENTRAL_WAREHOUSE, "wh-1", state=MS.FREE)
PR = LocationKey(LT.PROJECT, "p1", state=MS.FREE)
TR = LocationKey(LT.IN_TRANSIT, "pending", state=MS.IN_TRANSIT)


def _svc(client, gate):
    return CommandService(client, gate=gate)


async def _x(svc, db, t="T", **kw):
    return await svc.execute(_TestCtx(t), db, _tenant_coll(db, t),
                             CommandInput(tenant_id=t, actor_id="u", item_id="I", unit="бр",
                                          reason="r", file_ids=["f"], **kw))


async def _item(db, t="T"):
    await db["md_item"].insert_one({"tenant_id": t, "id": "I", "canonical_unit": "бр"})


async def _w0(db, t="T", n=0):
    ev = build_event(tenant_id=t, actor_type=ACTOR_HUMAN, actor_id="u", action="probe.w0_event",
                     source_flow="FLOW-040", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
                     entity_type="probe", entity_id="e%d" % n)
    return await record_event(db, ev)


async def _chain(db, t="T"):
    evs = await db[AUDIT_COLLECTION].find({"tenant_id": t}, {"_id": 0}).sort("sequence", 1).to_list(None)
    return evs, verify_chain(evs)


async def _receive(svc, db, key, qty="5", t="T"):
    return await _x(svc, db, t, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal(qty),
                    unit_value=Decimal("10"), destination=WH, idempotency_key=key)


async def _dispatch_accept(svc, db, qty="5", k="1"):
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal(qty), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d" + k)
    await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal(qty), accepted_quantity=Decimal(qty),
             requested_quantity=Decimal(qty), dispatch_movement_id=d.movement_id, project_id="p1",
             destination=PR, idempotency_key="a" + k)
    return d


async def test_c19_1_cost_once_with_in_transit_dispatch(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _receive(svc, db, "r1")
    await _dispatch_accept(svc, db)
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("3"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    await _x(svc, db, action=A.TRANSFER_PROJECT_TO_WAREHOUSE, quantity=Decimal("2"), source=PR,
             destination=WH, project_id="p1", idempotency_key="t1")
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    before = await material_smr.get_material_summary_for_project("T", "p1")
    await material_smr.sync_material_entries("p1", user={"id": "u", "org_id": "T", "role": "Owner"})
    after = await material_smr.get_material_summary_for_project("T", "p1")
    consume_rows = await db["material_entries"].count_documents({"org_id": "T", "movement_kind": "consume"})
    assert (before["total_cost"], after["total_cost"], consume_rows) == (30.0, 30.0, 1), (before, after, consume_rows)


async def test_c19_2_interleaved_writers_one_chain(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _w0(db, n=1)
    await _receive(svc, db, "r1")
    await _w0(db, n=2)
    await _receive(svc, db, "r2")
    await _w0(db, n=3)
    evs, (ok, why) = await _chain(db)
    assert ok, why
    assert [e["sequence"] for e in evs] == list(range(1, len(evs) + 1))
    assert len(evs) >= 5


async def test_c19_3_concurrent_writers(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _w0(db, n=0)
    jobs = [_receive(svc, db, "cr%d" % i, qty="1") for i in range(6)] + [_w0(db, n=10 + i) for i in range(6)]
    res = await asyncio.gather(*jobs, return_exceptions=True)
    can_fail = [type(r).__name__ for r in res[:6] if isinstance(r, Exception)]
    w0_fail = [type(r).__name__ for r in res[6:] if isinstance(r, Exception)]
    evs, (ok, why) = await _chain(db)
    print("C19-3 canonical failures:", can_fail, "W0-04 failures:", w0_fail, "events:", len(evs))
    assert ok, why
    assert not can_fail, can_fail
    assert not w0_fail, "W0-04 audit writes lost under concurrency: %s" % w0_fail


async def test_c19_4_legacy_batch_unique_index(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    await db["warehouse_batches"].create_index([("org_id", 1), ("batch_number", 1)], unique=True)
    svc = _svc(client, allow_always_gate); await _item(db)
    for i in range(3):
        await _receive(svc, db, "r%d" % i, qty="2")
    await _dispatch_accept(svc, db, qty="5")
    from app.services.warehouse_movements.projections import rebuild_from_ledger
    await rebuild_from_ledger(db, tenant_id="T")
    await rebuild_from_ledger(db, tenant_id="T")
    assert await db["warehouse_batches"].count_documents({"batch_number": None}) == 0


async def test_c19_5_identical_resend_consume(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _receive(svc, db, "r1", qty="10")
    await _dispatch_accept(svc, db, qty="10")
    c = lambda key, q: _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal(q), source=PR,
                         project_id="p1", smr_id="s1", idempotency_key=key)
    first = await c("c1", "3")
    await c("c2", "1")
    again = await c("c1", "3")
    assert again.movement_id == first.movement_id
    assert await db["warehouse_transactions"].count_documents({"action": "consume_to_smr"}) == 2
    with pytest.raises(Exception):
        await c("c1", "4")


async def test_c19_6_rule_b_and_cross_tenant(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db); await _item(db, "T2")
    await _receive(svc, db, "r1")
    with pytest.raises(Exception):
        await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("5"), source=WH,
                 destination=PR, project_id="p1", idempotency_key="dbad")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("5"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    with pytest.raises(Exception):
        await _x(svc, db, "T2", action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal("5"),
                 accepted_quantity=Decimal("5"), requested_quantity=Decimal("5"),
                 dispatch_movement_id=d.movement_id, project_id="p1", destination=PR, idempotency_key="x1")
    assert await db["warehouse_transactions"].count_documents({"tenant_id": "T2"}) == 0


async def test_c19_7_integrity_warnings(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _receive(svc, db, "r1")
    await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("5"), source=WH,
             destination=TR, project_id="p1", idempotency_key="d1")
    from app.services.warehouse_movements.queries import integrity_warnings
    async with await client.start_session() as s:
        await integrity_warnings(_tenant_coll(db), tenant_id="T", session=s)
    await integrity_warnings(_tenant_coll(db), tenant_id="T")


async def test_c19_3_control_w0_only(canonical_mongo_db):
    """Control for C19-3: the same 6 concurrent W0-04 writers with NO canonical writer.
    If this also loses writes, the race is pre-existing in app.audit.store.record_event (main)."""
    client, db = canonical_mongo_db
    await _w0(db, n=0)
    res = await asyncio.gather(*[_w0(db, n=10 + i) for i in range(6)], return_exceptions=True)
    fails = [type(r).__name__ for r in res if isinstance(r, Exception)]
    print("C19-3 control W0-04-only failures:", fails)
    assert not fails, fails
