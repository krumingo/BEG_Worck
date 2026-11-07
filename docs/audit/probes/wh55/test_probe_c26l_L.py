"""CLAUDE AUDIT probe — #55 e4d131e (5C-C26l Addendum L, FG-108 / FG-109).
  M1  6 concurrent FULL receipts of L (10 @10): 3 into the warehouse + 3 direct into P,
      different keys, ×5 → exactly ONE linked receipt; after the warehouse part (if it won)
      is accepted on P, P = 100 live and after rebuild ×2.
  U1  unit bypass: L is 10 "bag". Linked warehouse receipt of 10 bag → accepted on P (100).
      Then a linked DIRECT delivery of 10 with unit "pcs" (not comparable) into P —
      refused? And what is P's cost?  (FG-108 skips the qty check for another unit.)
Copy into backend/tests/ (next to the c26l_l test) and run on real Mongo RS.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import PRJ, PROJECT, T, WH
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx
from tests.test_warehouse_canonical_c26l_l_all_paths_lock import (
    LINKED, _prepare, _receipt, _to_p)

pytest_plugins = ["tests.warehouse_canonical_conftest"]


@pytest.mark.parametrize("rep", range(5))
async def test_m1_six_full_receipts_both_paths(canonical_mongo_db, allow_always_gate, monkeypatch, rep):
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, "enforce")
    inps = [_receipt(d, "10", "m1-%d-%d" % (rep, i)) for i, d in enumerate([WH, PRJ] * 3)]
    out = await asyncio.gather(*(svc.execute(_ctx("enforce", "Owner"), db, run.coll, i) for i in inps),
                               return_exceptions=True)
    ok = [i for i, o in zip(inps, out) if not isinstance(o, Exception)]
    linked = await db["warehouse_transactions"].count_documents(LINKED)
    wh_won = any(i.destination is WH for i in ok)
    if wh_won:
        await _to_p(run, "enforce", "10")
    costs = []
    for k in range(3):
        if k:
            await rebuild_from_ledger(db, tenant_id=T)
        costs.append((await run.cost(PROJECT))["total_cost"])
    print("M1 rep %d: accepted %d (%s) linked rows %d cost P %s errors %s" % (
        rep, len(ok), "warehouse" if wh_won else "direct", linked, costs,
        sorted({type(o).__name__ for o in out if isinstance(o, Exception)})))
    assert len(ok) == 1 and linked == 1 and all(c == pytest.approx(100.0) for c in costs)


async def test_u1_other_unit_direct_after_warehouse_path(canonical_mongo_db, allow_always_gate, monkeypatch):
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, "enforce")
    await svc.execute(_ctx("enforce", "Owner"), db, run.coll, _receipt(WH, "10"))
    await _to_p(run, "enforce", "10")
    before = (await run.cost(PROJECT))["total_cost"]
    inp = _receipt(PRJ, "10", "u1-pcs")
    inp.unit = "pcs"
    try:
        await svc.execute(_ctx("enforce", "Owner"), db, run.coll, inp)
        res = "accepted"
    except Exception as exc:  # noqa: BLE001
        res = type(exc).__name__
    linked = await db["warehouse_transactions"].count_documents(LINKED)
    costs = []
    for k in range(3):
        if k:
            await rebuild_from_ledger(db, tenant_id=T)
        c = await run.cost(PROJECT)
        costs.append((c["total_cost"], sorted(w["code"] for w in c["path_b_warnings"])))
    print("U1: before %s | direct 10 'pcs' linked to a 10 'bag' line → %s | linked rows %d | P %s" % (
        before, res, linked, costs))
    assert res != "accepted" and all(t == pytest.approx(100.0) for t, _ in costs), \
        "U1: the same lot counted again through another unit: %s" % costs
