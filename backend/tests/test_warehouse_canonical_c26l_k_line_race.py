"""
5C-C26l Addendum K — audit WH55-C26L-1 (BLOCKING) @ c31c09a: the covered-
quantity decision of a linked direct delivery raced. L 10 @10 allocated
5 → P and 5 → Q; 6 concurrent linked deliveries of 5 (distinct keys):
  * 6 → P: all accepted (30 linked against an allocation of 5), P/Q 300/50;
  * 3 → P + 3 → Q: all accepted, 150/150.
Sequentially only 1 (or 1 + 1) is accepted.

Fix: the decision is taken INSIDE the movement transaction under a per-line
lock (``_lock_invoice_line``); the pre-check before the rights gate is not a
guard. Here, ×10, in off / shadow / enforce (production gates, Owner):
exactly the allowed quantity is linked, P/Q 50/50, every refusal writes
nothing, a replay of the accepted delivery answers the same movement, and
the costs hold after rebuild ×2. Real Mongo (replica set).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import InvoiceLineProjectMismatchError
from app.services.warehouse_movements.projections import rebuild_from_ledger
from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import PROJECT, T, _inp
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import _loader
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx, _real
from tests.test_warehouse_canonical_c26l_cross_project_link import Q, _setup

pytest_plugins = ["tests.warehouse_canonical_conftest"]

SPLIT = [{"type": "project", "ref_id": PROJECT, "qty": 5},
         {"type": "project", "ref_id": Q, "qty": 5}]
P_LOC = LocationKey(LocationType.PROJECT, PROJECT)
Q_LOC = LocationKey(LocationType.PROJECT, Q)
LINKED = {"tenant_id": T, "action": "receive_from_supplier_to_project",
          "invoice_line_id": IL}


async def _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.permissions import service as perm
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, SPLIT)
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real("owner")))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    return db, run, CommandService(client)             # production gates


def _delivery(dest, key):
    return _inp(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, T, source=SUP,
                destination=dest, quantity=Decimal("5"), unit_value=Decimal("10"),
                invoice_line_id=IL, idempotency_key=key)


async def _race(svc, mode, run, dests):
    inps = [_delivery(d, f"k-race-{i}") for i, d in enumerate(dests)]
    out = await asyncio.gather(
        *(svc.execute(_ctx(mode, "Owner"), run.db, run.coll, i) for i in inps),
        return_exceptions=True)
    for r in out:
        assert not isinstance(r, Exception) or isinstance(r, InvoiceLineProjectMismatchError), r
    return inps, out


async def _assert_costs(db, run):
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        p, q = await run.cost(PROJECT), await run.cost(Q)
        assert (p["total_cost"], q["total_cost"]) == (pytest.approx(50.0),
                                                      pytest.approx(50.0)), i


MODES = ["off", "shadow", "enforce"]
REPEAT = range(10)


@pytest.mark.parametrize("rep", REPEAT)
@pytest.mark.parametrize("mode", MODES)
async def test_six_concurrent_deliveries_into_p_link_exactly_the_allocation(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    inps, out = await _race(svc, mode, run, [P_LOC] * 6)
    ok = [(i, r) for i, r in zip(inps, out) if not isinstance(r, Exception)]
    assert len(ok) == 1
    assert await db["warehouse_transactions"].count_documents(LINKED) == 1   # refusals: nothing
    await _assert_costs(db, run)
    inp, first = ok[0]
    again = await svc.execute(_ctx(mode, "Owner"), db, run.coll, _delivery(P_LOC, inp.idempotency_key))
    assert again.replay is True and again.movement_id == first.movement_id
    assert await db["warehouse_transactions"].count_documents(LINKED) == 1


@pytest.mark.parametrize("rep", REPEAT)
@pytest.mark.parametrize("mode", MODES)
async def test_three_into_p_and_three_into_q_link_one_each(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    inps, out = await _race(svc, mode, run, [P_LOC, Q_LOC] * 3)
    ok = [(i, r) for i, r in zip(inps, out) if not isinstance(r, Exception)]
    assert sorted(i.destination.location_id for i, _ in ok) == sorted([PROJECT, Q])
    assert await db["warehouse_transactions"].count_documents(LINKED) == 2
    await _assert_costs(db, run)
    for inp, first in ok:
        again = await svc.execute(_ctx(mode, "Owner"), db, run.coll,
                                  _delivery(inp.destination, inp.idempotency_key))
        assert again.replay is True and again.movement_id == first.movement_id
    assert await db["warehouse_transactions"].count_documents(LINKED) == 2


@pytest.mark.parametrize("mode", MODES)
async def test_the_in_transaction_decision_is_the_guard(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """With the pre-rights pre-check switched off, the transaction alone
    still refuses the second delivery into P (and writes nothing)."""
    db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    real = CommandService._check_invoice_line_delivery

    async def only_in_tx(tenant_db, tenant_collection, inp, *, session=None):
        if session is not None:
            await real(tenant_db, tenant_collection, inp, session=session)
    monkeypatch.setattr(CommandService, "_check_invoice_line_delivery",
                        staticmethod(only_in_tx))
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _delivery(P_LOC, "k-seq-1"))
    with pytest.raises(InvoiceLineProjectMismatchError):
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, _delivery(P_LOC, "k-seq-2"))
    assert await db["warehouse_transactions"].count_documents(LINKED) == 1
    await _assert_costs(db, run)
