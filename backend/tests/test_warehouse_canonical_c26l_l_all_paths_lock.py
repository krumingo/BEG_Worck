"""
5C-C26l Addendum L — FLOW Guard pass 11 @ 43477d8 (FLOW-009 / FLOW-043 D-04:
material is cost by ONE path).

FG-108 (high, proven): line L (10 @10) received INTO THE WAREHOUSE with the
link → dispatched / accepted on P (100) → a linked direct delivery of 10
into P was accepted → P = 200, no warning. Fix: the line's covered quantity
is ALL linked paths (warehouse receipt + direct delivery), decided in the
movement transaction under the per-line lock (Addendum K): beyond the line's
quantity → 422 INVOICE_LINE_QTY_EXCEEDED, nothing written; legacy excess →
PATH_B_LINK_OVER_LINE, counted once.

FG-109 (proven, with FG-83): a line could be re-allocated after delivery →
P/Q 100/100. Fix: after the first linked movement the allocation (and the
qty / unit / price it is costed by) is locked — 409
INVOICE_LINE_ALLOCATION_LOCKED, nothing written; no delete of a linked line.

Real Mongo (replica set), off / shadow / enforce (production gates, Owner).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.canonical_material_cost import path_b_integrity_warnings
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import (
    InvoiceLineProjectMismatchError, InvoiceLineQuantityExceededError,
)
from app.services.warehouse_movements.projections import rebuild_from_ledger
from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import PRJ, PROJECT, T, WH, _inp
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import _loader
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx, _real
from tests.test_warehouse_canonical_c26l_cross_project_link import Q, _setup

pytest_plugins = ["tests.warehouse_canonical_conftest"]

MODES = ["off", "shadow", "enforce"]
ONLY_P = [{"type": "project", "ref_id": PROJECT, "qty": 10}]
LINKED = {"tenant_id": T, "invoice_line_id": IL,
          "action": {"$in": ["receive_from_supplier", "receive_from_supplier_to_project"]}}
OWNER = {"id": "u-c26l-owner", "org_id": T, "role": "Owner", "email": "o@x"}


async def _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode, allocations=ONLY_P):
    from app.permissions import service as perm
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, allocations)
    await db["invoices"].insert_one({"id": "inv-c26", "org_id": T, "status": "Draft",
                                     "type": "Received"})
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real("owner")))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    return client, db, run, CommandService(client)      # production gates


def _receipt(dest, qty, key=None):
    action = (CanonicalAction.RECEIVE_FROM_SUPPLIER if dest is WH
              else CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT)
    kw = {"idempotency_key": key} if key else {}
    return _inp(action, T, source=SUP, destination=dest, quantity=Decimal(qty),
                unit_value=Decimal("10"), invoice_line_id=IL, **kw)


async def _staff(mode, coro):
    """A setup step through the fixture's allow-all service (enforce)."""
    import os
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    try:
        return await coro
    finally:
        os.environ["PERMISSION_SERVICE_MODE"] = mode


async def _to_p(run, mode, qty):
    d = await _staff(mode, run.dispatch(qty))
    return await _staff(mode, run.accept(d, qty))


async def _linked(db):
    return await db["warehouse_transactions"].count_documents(LINKED)


async def _p_cost(db, run, want):
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        assert (await run.cost(PROJECT))["total_cost"] == pytest.approx(want), i


# ═══════════════════════════ FG-108 — refused up front ═══════════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_fg108_repro_direct_after_linked_warehouse_path_is_refused(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """43477d8: accepted, P = 200. Now 422, nothing written, P = 100."""
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(WH, "10"))
    await _to_p(run, mode, "10")
    before = await db["warehouse_transactions"].count_documents({"tenant_id": T})
    with pytest.raises(InvoiceLineQuantityExceededError):
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10"))
    assert await db["warehouse_transactions"].count_documents({"tenant_id": T}) == before
    await _p_cost(db, run, 100.0)
    # and a second linked warehouse receipt of the same lot too
    with pytest.raises(InvoiceLineQuantityExceededError):
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(WH, "1"))
    assert await _linked(db) == 1


@pytest.mark.parametrize("mode", MODES)
async def test_fg108_partial_paths_sum_to_the_line(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """6 through the warehouse + 4 direct = the line; 1 more direct → 422."""
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(WH, "6"))
    await _to_p(run, mode, "6")
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "4"))
    with pytest.raises(InvoiceLineQuantityExceededError):
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "1"))
    await _p_cost(db, run, 100.0)


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_fg108_concurrent_mix_of_both_paths(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    """3 linked warehouse receipts of 5 + 3 linked direct deliveries of 5,
    concurrently: exactly 10 linked; after the warehouse part is accepted on
    P, P = 100 (live + rebuild ×2); refusals write nothing; replay = same."""
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    inps = [_receipt(dest, "5", f"k-mix-{i}") for i, dest in enumerate([WH, PRJ] * 3)]
    out = await asyncio.gather(
        *(svc.execute(_ctx(mode, "Owner"), db, run.coll, i) for i in inps),
        return_exceptions=True)
    for r in out:
        assert not isinstance(r, Exception) or isinstance(
            r, (InvoiceLineQuantityExceededError, InvoiceLineProjectMismatchError)), r
    ok = [(i, r) for i, r in zip(inps, out) if not isinstance(r, Exception)]
    assert len(ok) == 2 and await _linked(db) == 2
    wh_qty = sum(5 for i, _ in ok if i.destination is WH)
    if wh_qty:
        await _to_p(run, mode, str(wh_qty))
    await _p_cost(db, run, 100.0)
    inp, first = ok[0]
    again = await svc.execute(_ctx(mode, "Owner"), db, run.coll,
                              _receipt(inp.destination, "5", inp.idempotency_key))
    assert again.replay is True and again.movement_id == first.movement_id


# ═══════════════════════════ FG-108 — legacy excess ═══════════════════════════

async def test_fg108_legacy_over_link_counts_once_and_warns(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Data written before the fix (check bypassed): P counts the lot once
    (the direct delivery's over-linked part is excluded), PATH_B_LINK_OVER_LINE
    on P and on the integrity screen; live and after rebuild ×2."""
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, "enforce")

    async def _no_total(*a, **k):
        return None
    monkeypatch.setattr(CommandService, "_check_invoice_line_total", staticmethod(_no_total))
    await svc.execute(_ctx("enforce", "Owner"), db, run.coll, _receipt(WH, "10"))
    await _to_p(run, "enforce", "10")
    await svc.execute(_ctx("enforce", "Owner"), db, run.coll, _receipt(PRJ, "10"))
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        cost = await run.cost(PROJECT)
        assert cost["total_cost"] == pytest.approx(100.0), i
        assert cost["over_link_excluded_cost"] == pytest.approx(100.0)
        assert [w["code"] for w in cost["path_b_warnings"]] == ["PATH_B_LINK_OVER_LINE"]
    warnings = await path_b_integrity_warnings(run.tenant_data, T)
    assert [(w["code"], w["project_id"]) for w in warnings] == [
        ("PATH_B_LINK_OVER_LINE", PROJECT)]


async def test_fg108_warehouse_only_excess_is_warned_on_the_integrity_screen(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, "enforce")

    async def _no_total(*a, **k):
        return None
    monkeypatch.setattr(CommandService, "_check_invoice_line_total", staticmethod(_no_total))
    for _ in range(2):
        await svc.execute(_ctx("enforce", "Owner"), db, run.coll, _receipt(WH, "10"))
    warnings = await path_b_integrity_warnings(run.tenant_data, T)
    assert ("PATH_B_LINK_OVER_LINE", IL) in {(w["code"], w["invoice_line_id"]) for w in warnings}


# ═══════════════════════════ FG-109 — allocation lock ═══════════════════════════

def _routes(monkeypatch, client, db):
    from app.routes import invoice_lines as routes
    monkeypatch.setattr(routes, "db", db)
    monkeypatch.setattr(routes, "mongo_client", client)
    routes.audit_calls = []

    async def _audit(*args, **kw):                 # the legacy audit log (global db)
        routes.audit_calls.append(args)
    monkeypatch.setattr(routes, "log_audit", _audit)
    return routes


async def _line(db):
    return await db["invoice_lines"].find_one({"id": IL}, {"_id": 0})


@pytest.mark.parametrize("mode", MODES)
async def test_fg109_linked_line_allocation_is_locked(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate, InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10"))
    before = await _line(db)
    calls = [
        routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
            allocations=[{"type": "project", "ref_id": Q, "qty": 10}]), user=OWNER),
        routes.update_invoice_line(IL, InvoiceLineUpdate(
            allocations=[{"type": "project", "ref_id": Q, "qty": 10}]), user=OWNER),
        routes.update_invoice_line(IL, InvoiceLineUpdate(qty=20), user=OWNER),
        routes.update_invoice_line(IL, InvoiceLineUpdate(unit_price=5), user=OWNER),
        routes.delete_invoice_line(IL, user=OWNER),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "INVOICE_LINE_ALLOCATION_LOCKED"
        assert await _line(db) == before                       # nothing written
    assert routes.audit_calls == []
    await _p_cost(db, run, 100.0)
    assert (await run.cost(Q))["total_cost"] == 0


async def test_fg109_unlinked_line_still_reallocates(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch,
                                          "enforce")
    routes = _routes(monkeypatch, client, db)
    await routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
        allocations=[{"type": "project", "ref_id": Q, "qty": 10}]), user=OWNER)
    assert (await _line(db))["allocations"][0]["ref_id"] == Q
    assert [c[3] for c in routes.audit_calls] == ["invoice_line_allocated"]


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_fg109_reallocation_racing_a_delivery_never_counts_twice(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    """Concurrently: reallocate L P → Q, and deliver L into P. One wins:
    delivery first → 409 (P = 100); reallocation first → 422 (Q = 100)."""
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    realloc, delivery = await asyncio.gather(
        routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
            allocations=[{"type": "project", "ref_id": Q, "qty": 10}]), user=OWNER),
        svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10")),
        return_exceptions=True)
    if isinstance(delivery, Exception):
        assert isinstance(delivery, InvoiceLineProjectMismatchError), delivery
        assert not isinstance(realloc, Exception), realloc
        want = (0.0, 100.0)
    else:
        assert isinstance(realloc, HTTPException) and realloc.status_code == 409, realloc
        want = (100.0, 0.0)
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        got = ((await run.cost(PROJECT))["total_cost"], (await run.cost(Q))["total_cost"])
        assert got == (pytest.approx(want[0]), pytest.approx(want[1])), i
