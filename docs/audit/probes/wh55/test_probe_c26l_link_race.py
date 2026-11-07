"""CLAUDE AUDIT probe — #55 c31c09a (5C-C26l). _check_invoice_line_delivery sums the already
delivered quantity BEFORE the movement transaction. Six concurrent linked direct deliveries
(different idempotency keys) of invoice line L (10 @10 = 100; allocated 5 to P and 5 to Q):
  RACE-P:  6 × 5 into P            → sequentially only 1 is accepted
  RACE-PQ: 3 × 5 into P + 3 × 5 into Q → sequentially 1 + 1
Over-linking = more than L's allocation delivered against L on a project; cost above the
invoice total = the lot counted more than once (D-04). Live and after rebuild ×2.
Copy into backend/tests/ and run on real Mongo (RS) with the warehouse canonical env.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import PROJECT, T
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP
from tests.test_warehouse_canonical_c26l_cross_project_link import Q, _setup
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL

pytest_plugins = ["tests.warehouse_canonical_conftest"]

P_LOC = LocationKey(LocationType.PROJECT, PROJECT)
Q_LOC = LocationKey(LocationType.PROJECT, Q)


async def _one(run, dest, i):
    try:
        await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP, destination=dest,
                  quantity=Decimal("5"), unit_value=Decimal("10"), invoice_line_id=IL,
                  idempotency_key="race-%d" % i)
        return "ok"
    except Exception as exc:                         # noqa: BLE001
        return type(exc).__name__


@pytest.mark.parametrize("shape", ["P", "PQ"])
@pytest.mark.parametrize("rnd", range(int(os.environ.get("ROUNDS", "3"))))
async def test_concurrent_linked_deliveries(canonical_mongo_db, allow_always_gate, monkeypatch, shape, rnd):
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": PROJECT, "qty": 5},
                        {"type": "project", "ref_id": Q, "qty": 5}])
    dests = [P_LOC] * 6 if shape == "P" else [P_LOC] * 3 + [Q_LOC] * 3
    res = await asyncio.gather(*[_one(run, d, i) for i, d in enumerate(dests)])
    linked = {}
    async for r in db["warehouse_transactions"].find(
            {"action": "receive_from_supplier_to_project", "invoice_line_id": IL}, {"_id": 0}):
        linked[r.get("project_id")] = linked.get(r.get("project_id"), 0) + float(str(r["quantity"]))
    totals = []
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        p, q = await run.cost(PROJECT), await run.cost(Q)
        totals.append((p["total_cost"], q["total_cost"]))
    print("RACE-%s rnd %d: results %s linked qty %s cost P/Q %s" % (shape, rnd, sorted(res), linked, totals))
    assert all(v <= 5 for v in linked.values()), "OVER-LINKED: %s (allocation 5 each)" % linked
    assert all(p + q <= 100.0 + 1e-6 for p, q in totals), "COST ABOVE INVOICE 100: %s" % totals
    assert sorted(res).count("ok") == (1 if shape == "P" else 2), res
    assert all(t == (50.0, 50.0) for t in totals), totals


# ── 43477d8 (Addendum K): a crash inside the movement transaction, after the line lock
async def test_crash_after_lock_leaves_nothing(canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.services.warehouse_movements.service import CommandService
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": PROJECT, "qty": 5},
                        {"type": "project", "ref_id": Q, "qty": 5}])
    orig = CommandService._check_invoice_line_delivery
    state = {"armed": True}

    async def crash(tenant_db, tenant_collection, inp, *, session=None):
        if session is not None and state["armed"]:
            state["armed"] = False
            raise RuntimeError("synthetic crash inside the transaction, after the lock write")
        return await orig(tenant_db, tenant_collection, inp, session=session)
    monkeypatch.setattr(CommandService, "_check_invoice_line_delivery", staticmethod(crash))
    r1 = await _one(run, P_LOC, 100)
    # since Addendum L the lock document is pre-created OUTSIDE the transaction (value 0):
    # what must roll back is the in-transaction bump
    locks = sum(int(d.get("value") or 0) for d in await db["warehouse_ledger_counters"].find(
        {"name": "invoice_line_lock"}, {"_id": 0, "value": 1}).to_list(None))
    rows = await db["warehouse_transactions"].count_documents({"invoice_line_id": IL})
    print("CRASH →", r1, "lock bumps kept", locks, "linked rows", rows)
    assert r1 != "ok" and locks == 0 and rows == 0
    r2 = await _one(run, P_LOC, 101)
    rows = await db["warehouse_transactions"].count_documents({"invoice_line_id": IL})
    lock = await db["warehouse_ledger_counters"].find_one({"name": "invoice_line_lock"}, {"_id": 1, "tenant_id": 1})
    print("AFTER →", r2, "linked rows", rows, "lock", lock)
    assert r2 == "ok" and rows == 1 and lock and lock["tenant_id"] == T
    assert (await run.cost(PROJECT))["total_cost"] == 50.0
