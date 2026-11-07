"""CLAUDE AUDIT probe — #55 cba5306 (Codex F-55-C26-04 + header recalc).
Variants of Codex's interleaving that the PR's own tests do not cover:
  F1  the DERIVED-input PUT path paused before its transaction ({"vat_percent": 9}),
      then PUT unit_price 20, then a linked delivery 5 @20 into P, then resume →
      line 20 / 200 / VAT 18, P = 200 live + rebuild ×2.
  F2  a paused allocations PUT (10 to P) while qty drops to 5 → resume must be 400,
      nothing written by it.
  F3  a paused qty PUT (qty 12) while /allocate sets P 4 → qty_allocated 4,
      qty_unallocated 8 (from the CURRENT allocations).
  F4  ×10: four concurrent derived PUTs on two lines (IL price 20, IL vat 9,
      IL2 price 30, IL2 qty 7) → no lost update on either line, header = Σ lines.
  F5  metadata PUT on a LINKED line → 200, every derived field byte-equal.
Copy into backend/tests/ and run on a real Mongo RS (WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import PROJECT, PRJ, T, _inp
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx
from tests.test_warehouse_canonical_c26l_l_all_paths_lock import (
    IL, IL2, MODES, OWNER, _line, _prepare, _receipt, _routes, _two_lines)
from app.services.warehouse_movements import CanonicalAction

pytest_plugins = ["tests.warehouse_canonical_conftest"]
DERIVED = ("line_total_ex_vat", "vat_amount", "line_total_inc_vat", "qty_allocated",
           "qty_unallocated", "is_fully_allocated", "unit_price", "qty", "allocations")


def _pause_require_full(monkeypatch, routes):
    """Pause the FIRST task that reaches get_org_require_full_allocation (pre-transaction)."""
    real = routes.get_org_require_full_allocation
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused(tenant):
        v = await real(tenant)
        if getattr(asyncio.current_task(), "pause_me", False) and not release.is_set():
            reached.set()
            await release.wait()
        return v
    monkeypatch.setattr(routes, "get_org_require_full_allocation", paused)
    return reached, release


def _paused_task(coro_fn):
    async def run():
        asyncio.current_task().pause_me = True
        return await coro_fn()
    return asyncio.create_task(run())


async def _p(db, run, want):
    got = []
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        got.append((await run.cost(PROJECT))["total_cost"])
    assert all(g == pytest.approx(want) for g in got), got
    return got


@pytest.mark.parametrize("mode", MODES)
async def test_f1_paused_derived_put(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    reached, release = _pause_require_full(monkeypatch, routes)
    vat = _paused_task(lambda: routes.update_invoice_line(IL, InvoiceLineUpdate(vat_percent=9), user=OWNER))
    await asyncio.wait_for(reached.wait(), 10)
    await routes.update_invoice_line(IL, InvoiceLineUpdate(unit_price=20), user=OWNER)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, T, source=SUP, destination=PRJ,
        quantity=Decimal("5"), unit_value=Decimal("20"), invoice_line_id=IL))
    release.set()
    try:
        await vat
        res = "200"
    except HTTPException as exc:
        res = exc.status_code
    line = await _line(db)
    got = await _p(db, run, 200.0)
    print("F1 %s: vat PUT → %s | line %s | P %s" % (mode, res, (line["unit_price"], line["line_total_ex_vat"],
          line.get("vat_percent"), line["vat_amount"]), got))
    assert (line["unit_price"], line["line_total_ex_vat"]) == (20, 200)
    # either outcome is acceptable for the vat edit itself, but the totals must match the stored vat
    assert line["vat_amount"] == round(200 * (line.get("vat_percent", 20) or 0) / 100, 2)


@pytest.mark.parametrize("mode", MODES)
async def test_f2_paused_allocations_put_vs_qty_drop(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    reached, release = _pause_require_full(monkeypatch, routes)
    t = _paused_task(lambda: routes.update_invoice_line(IL, InvoiceLineUpdate(
        allocations=[{"type": "project", "ref_id": PROJECT, "qty": 10}]), user=OWNER))
    await asyncio.wait_for(reached.wait(), 10)
    await routes.update_invoice_line(IL, InvoiceLineUpdate(qty=5), user=OWNER)
    mid = await _line(db)
    release.set()
    try:
        await t
        res = 200
    except HTTPException as exc:
        res = exc.status_code
    line = await _line(db)
    print("F2 %s: allocations 10 after qty→5 → %s | qty %s alloc %s" % (mode, res, line["qty"], line["allocations"]))
    assert res == 400 and {k: line.get(k) for k in DERIVED} == {k: mid.get(k) for k in DERIVED}


@pytest.mark.parametrize("mode", MODES)
async def test_f3_paused_qty_put_vs_allocate(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate, InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    reached, release = _pause_require_full(monkeypatch, routes)
    t = _paused_task(lambda: routes.update_invoice_line(IL, InvoiceLineUpdate(qty=12), user=OWNER))
    await asyncio.wait_for(reached.wait(), 10)
    await routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
        allocations=[{"type": "project", "ref_id": PROJECT, "qty": 4}]), user=OWNER)
    release.set()
    await t
    line = await _line(db)
    print("F3 %s: qty %s allocs %s qa %s qu %s full %s total %s" % (mode, line["qty"], line["allocations"],
          line["qty_allocated"], line["qty_unallocated"], line["is_fully_allocated"], line["line_total_ex_vat"]))
    assert (line["qty"], line["qty_allocated"], line["qty_unallocated"], line["is_fully_allocated"]) == (12, 4, 8, False)
    assert line["line_total_ex_vat"] == round(12 * line["unit_price"], 2)


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_f4_four_concurrent_derived_puts(canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await _two_lines(db)
    routes = _routes(monkeypatch, client, db)
    out = await asyncio.gather(
        routes.update_invoice_line(IL, InvoiceLineUpdate(unit_price=20), user=OWNER),
        routes.update_invoice_line(IL, InvoiceLineUpdate(vat_percent=9), user=OWNER),
        routes.update_invoice_line(IL2, InvoiceLineUpdate(unit_price=30), user=OWNER),
        routes.update_invoice_line(IL2, InvoiceLineUpdate(qty=7), user=OWNER),
        return_exceptions=True)
    errs = [o for o in out if isinstance(o, Exception)]
    a, b = await _line(db), await db["invoice_lines"].find_one({"id": IL2}, {"_id": 0})
    lines = await db["invoice_lines"].find({"invoice_id": "inv-c26"}).to_list(None)
    inv = await db["invoices"].find_one({"id": "inv-c26"})
    sub = round(sum(ln["line_total_ex_vat"] for ln in lines), 2)
    vat = round(sum(ln["vat_amount"] for ln in lines), 2)
    print("F4 %s/%d: errs %s | IL %s | IL2 %s | header %s / Σ %s %s" % (
        mode, rep, errs, (a["unit_price"], a["vat_percent"], a["line_total_ex_vat"], a["vat_amount"]),
        (b["qty"], b["unit_price"], b["line_total_ex_vat"]), (inv["subtotal"], inv["vat_amount"], inv["total"]), sub, vat))
    assert not errs
    assert (a["unit_price"], a["vat_percent"], a["line_total_ex_vat"], a["vat_amount"]) == (20, 9, 200, 18)
    assert (b["qty"], b["unit_price"], b["line_total_ex_vat"]) == (7, 30, 210)
    assert (inv["subtotal"], inv["vat_amount"], inv["total"], inv["lines_count"]) == (sub, vat, round(sub + vat, 2), len(lines))


@pytest.mark.parametrize("mode", MODES)
async def test_f5_metadata_put_on_linked_line(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10"))
    before = await _line(db)
    await routes.update_invoice_line(IL, InvoiceLineUpdate(notes="ok"), user=OWNER)
    after = await _line(db)
    print("F5 %s: notes %s, derived equal %s" % (mode, after.get("notes"),
          {k: after.get(k) for k in DERIVED} == {k: before.get(k) for k in DERIVED}))
    assert after["notes"] == "ok" and {k: after.get(k) for k in DERIVED} == {k: before.get(k) for k in DERIVED}
    await _p(db, run, 100.0)
