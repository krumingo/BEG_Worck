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
    InvoiceLineFullyLinkedError, InvoiceLineProjectMismatchError,
    InvoiceLineQuantityExceededError, InvoiceLineUnitMismatchError,
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


# ═══════════════════ audit WH55-L-1 — another unit after a full line ═══════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_wh55_l1_fully_linked_line_refuses_any_unit_409(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """L 10 bag fully received (warehouse, linked) and accepted on P; a
    linked direct delivery of 10 „pcs" was accepted at e4d131e (P = 200,
    only PATH_B_LINK_QTY_UNVERIFIED). Now 409 INVOICE_LINE_FULLY_LINKED in
    any unit, nothing written; P = 100 live + rebuild ×2."""
    from app.routes.warehouse_canonical import _render_error
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(WH, "10"))
    await _to_p(run, mode, "10")
    before = await db["warehouse_transactions"].count_documents({"tenant_id": T})
    for unit in ("pcs", "bag"):
        inp = _receipt(PRJ, "10")
        inp.unit = unit
        with pytest.raises(InvoiceLineFullyLinkedError) as exc:
            await svc.execute(_ctx(mode, "Owner"), db, run.coll, inp)
        assert _render_error(exc.value).status_code == 409
    assert await db["warehouse_transactions"].count_documents({"tenant_id": T}) == before
    await _p_cost(db, run, 100.0)
    assert (await run.cost(PROJECT))["path_b_warnings"] == []


@pytest.mark.parametrize("mode", MODES)
async def test_wh55_l1_partial_in_another_unit_is_refused_up_front(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """L 10 bag, 4 bag linked through the warehouse: a linked receipt of 2
    „pcs" (warehouse or direct) cannot be checked against the line — no unit
    conversion is defined → 422 INVOICE_LINE_UNIT_MISMATCH, nothing written.
    The rest in „bag" is still accepted; P = 100."""
    from app.routes.warehouse_canonical import _render_error
    _, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(WH, "4"))
    await _to_p(run, mode, "4")
    for dest in (WH, PRJ):
        inp = _receipt(dest, "2")
        inp.unit = "pcs"
        with pytest.raises(InvoiceLineUnitMismatchError) as exc:
            await svc.execute(_ctx(mode, "Owner"), db, run.coll, inp)
        assert _render_error(exc.value).status_code == 422
    assert await _linked(db) == 1
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "6"))
    await _p_cost(db, run, 100.0)


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


# ═══════════════════ Addendum M — FG-124: the deprecated allocation path ═══════════════════

DEPRECATED_P = {"allocation_type": "project", "allocation_ref_id": PROJECT}


async def _deprecated_line(db):
    """L carried ONLY by the deprecated single allocation (allocations [])."""
    await db["invoice_lines"].update_one({"id": IL}, {"$set": {**DEPRECATED_P,
                                                                "allocations": []}})


@pytest.mark.parametrize("mode", MODES)
async def test_fg124_deprecated_allocation_inputs_are_locked_too(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """d98cead: PUT allocation_type / allocation_ref_id moved a linked line
    to Q (P/Q 100/100). Now every allocation input → 409, nothing written."""
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch,
                                          mode, allocations=None)
    await _deprecated_line(db)
    routes = _routes(monkeypatch, client, db)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10"))
    before = await _line(db)
    for body in ({"allocation_ref_id": Q},
                 {"allocation_type": "warehouse", "allocation_ref_id": "wh_1"},
                 {"allocation_type": "client"},
                 {"allocations": []}):
        with pytest.raises(HTTPException) as exc:
            await routes.update_invoice_line(IL, InvoiceLineUpdate(**body), user=OWNER)
        assert exc.value.status_code == 409, body
        assert exc.value.detail["error_code"] == "INVOICE_LINE_ALLOCATION_LOCKED"
        assert await _line(db) == before, body
    # a field the line is not costed by still saves
    await routes.update_invoice_line(IL, InvoiceLineUpdate(notes="бележка"), user=OWNER)
    assert (await _line(db))["notes"] == "бележка"
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        got = ((await run.cost(PROJECT))["total_cost"], (await run.cost(Q))["total_cost"])
        assert got == (pytest.approx(100.0), 0), i


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_fg124_deprecated_reallocation_racing_a_delivery(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    """Concurrently: PUT allocation_ref_id P → Q, and deliver L into P.
    Exactly one wins; never P/Q 100/100 (live + rebuild ×2)."""
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch,
                                          mode, allocations=None)
    await _deprecated_line(db)
    routes = _routes(monkeypatch, client, db)

    async def _put():
        # odd runs: the delivery gets a head start, so both orders are hit
        await asyncio.sleep(0.2 if rep % 2 else 0)
        return await routes.update_invoice_line(IL, InvoiceLineUpdate(allocation_ref_id=Q),
                                                user=OWNER)
    realloc, delivery = await asyncio.gather(
        _put(), svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10")),
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


@pytest.mark.parametrize("mode", MODES)
async def test_f55_c26_03_http_put_of_the_legacy_allocation_is_409(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Codex F-55-C26-03 (= FG-124), its exact repro over HTTP: a legacy line
    (allocations [], allocation_type=project, allocation_ref_id=P) in a
    Draft invoice, a linked direct delivery of 10 into P, then as Owner
    PUT /api/invoice-lines/{L} {"allocation_type":"project",
    "allocation_ref_id":"Q"} → was 200 (P → Q); now 409
    INVOICE_LINE_ALLOCATION_LOCKED, the line byte-equal, P/Q 100/0."""
    import httpx
    from fastapi import FastAPI
    from app.deps.modules import require_m5
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch,
                                          mode, allocations=None)
    await _deprecated_line(db)
    routes = _routes(monkeypatch, client, db)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10"))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[require_m5] = lambda: OWNER
    before = await _line(db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as http:
        r = await http.put(f"/api/invoice-lines/{IL}",
                           json={"allocation_type": "project", "allocation_ref_id": Q})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "INVOICE_LINE_ALLOCATION_LOCKED"
    assert await _line(db) == before
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        got = ((await run.cost(PROJECT))["total_cost"], (await run.cost(Q))["total_cost"])
        assert got == (pytest.approx(100.0), 0), i



# ═══════════════════ Codex F-55-C26-04 — stale derived values ═══════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_f55_c26_04_a_paused_notes_put_never_writes_stale_money(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Codex's interleaving over HTTP: L (Draft, 10 @10, allocated P);
    PUT {"notes"} pauses right before its write (after reading the row);
    PUT {"unit_price": 20} completes (line total 200); a linked direct
    delivery of 5 @20 into P is accepted; the notes PUT resumes. 94c0571:
    the notes PUT wrote the stale line_total_ex_vat 100 → P = 150. Now the
    line keeps unit_price 20 / total 200 and P = 200, live + rebuild ×2."""
    import httpx
    from fastapi import FastAPI
    from app.deps.modules import require_m5
    from app.tenancy.data_access import TenantCollection
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[require_m5] = lambda: OWNER

    reached, release = asyncio.Event(), asyncio.Event()
    real_update_one = TenantCollection.update_one

    async def paused_update_one(self, flt, update, **kw):
        if "notes" in (update.get("$set") or {}) and not release.is_set():
            reached.set()
            await release.wait()                  # the notes PUT, right before its write
        return await real_update_one(self, flt, update, **kw)
    monkeypatch.setattr(TenantCollection, "update_one", paused_update_one)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as http:
        notes = asyncio.create_task(
            http.put(f"/api/invoice-lines/{IL}", json={"notes": "review-paused"}))
        await asyncio.wait_for(reached.wait(), 10)
        r = await http.put(f"/api/invoice-lines/{IL}", json={"unit_price": 20})
        assert r.status_code == 200, r.text
        delivery = _inp(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, T, source=SUP,
                        destination=PRJ, quantity=Decimal("5"), unit_value=Decimal("20"),
                        invoice_line_id=IL)
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, delivery)
        release.set()
        r = await notes
        assert r.status_code == 200, r.text
    line = await _line(db)
    assert line["notes"] == "review-paused"
    assert (line["unit_price"], line["line_total_ex_vat"]) == (20, 200)
    await _p_cost(db, run, 200.0)


@pytest.mark.parametrize("mode", MODES)
async def test_f55_c26_04_a_paused_allocate_reads_the_current_qty(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """The same pattern for /allocate: its qty_unallocated is computed from
    the qty read IN the lock transaction, not from a row read before it."""
    from app.models.invoice_lines import InvoiceLineAllocationsUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    routes = _routes(monkeypatch, client, db)
    real_get = routes.validate_allocation_refs
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused_validate(tenant, allocs):
        await real_get(tenant, allocs)
        if not release.is_set():
            reached.set()
            await release.wait()          # after the pre-transaction read
    monkeypatch.setattr(routes, "validate_allocation_refs", paused_validate)
    alloc = asyncio.create_task(routes.allocate_invoice_line(IL, InvoiceLineAllocationsUpdate(
        allocations=[{"type": "project", "ref_id": PROJECT, "qty": 10}]), user=OWNER))
    await asyncio.wait_for(reached.wait(), 10)
    # a qty change lands after the pre-transaction read, before the write
    await db["invoice_lines"].update_one({"id": IL}, {"$set": {"qty": 20}})
    release.set()
    await alloc
    line = await _line(db)
    assert (line["qty_allocated"], line["qty_unallocated"]) == (10, 10)


# ═══════════ debt after F-55-C26-04 — the invoice header totals ═══════════

IL2 = "il-c26-2"


async def _two_lines(db):
    from tests.test_warehouse_canonical_c26_one_path_per_lot import _invoice_line
    await _invoice_line(db, line_id=IL2, deprecated=False, description="Пясък",
                        allocations=[{"type": "project", "ref_id": PROJECT, "qty": 10}])


async def _assert_header_is_sum(db):
    lines = await db["invoice_lines"].find({"invoice_id": "inv-c26"}).to_list(None)
    inv = await db["invoices"].find_one({"id": "inv-c26"})
    sub = round(sum(ln.get("line_total_ex_vat", 0) for ln in lines), 2)
    vat = round(sum(ln.get("vat_amount", 0) for ln in lines), 2)
    assert (inv["subtotal"], inv["vat_amount"], inv["total"], inv["lines_count"]) == (
        sub, vat, round(sub + vat, 2), len(lines)), (inv, sub, vat)


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_invoice_header_total_is_the_sum_after_concurrent_line_edits(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    """Two different lines of one invoice edited concurrently: the stored
    header total = Σ lines (live and after rebuild)."""
    from app.models.invoice_lines import InvoiceLineUpdate
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await _two_lines(db)
    routes = _routes(monkeypatch, client, db)
    out = await asyncio.gather(
        routes.update_invoice_line(IL, InvoiceLineUpdate(unit_price=20), user=OWNER),
        routes.update_invoice_line(IL2, InvoiceLineUpdate(unit_price=30), user=OWNER),
        return_exceptions=True)
    assert not any(isinstance(r, Exception) for r in out), out
    await _assert_header_is_sum(db)
    await rebuild_from_ledger(db, tenant_id=T)
    await _assert_header_is_sum(db)
    inv = await db["invoices"].find_one({"id": "inv-c26"})
    assert inv["subtotal"] == 500.0                        # 10 × 20 + 10 × 30


@pytest.mark.parametrize("mode", MODES)
async def test_invoice_header_recalc_paused_after_its_read_is_never_stale(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """The interleaving: edit A's header recalculation pauses after reading
    the lines; edit B (another line) completes, header included; A resumes.
    94c0571+: A wrote the header from the line set it read (B's edit lost
    from the total). Now the header is Σ the current lines."""
    from app.models.invoice_lines import InvoiceLineUpdate
    from app.tenancy.data_access import TenantCollection
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await _two_lines(db)
    routes = _routes(monkeypatch, client, db)
    reached, release = asyncio.Event(), asyncio.Event()
    seen = {}
    real_get, real_find_one = TenantCollection.get, TenantCollection.find_one

    async def _maybe_pause(coll):
        task = asyncio.current_task()
        if coll.name == "invoices" and getattr(task, "pause_me", False):
            seen[task] = seen.get(task, 0) + 1
            if seen[task] == 2 and not release.is_set():   # 1: Draft check, 2: header recalc
                reached.set()
                await release.wait()

    async def get(self, *a, **kw):
        await _maybe_pause(self)
        return await real_get(self, *a, **kw)

    async def find_one(self, *a, **kw):
        await _maybe_pause(self)
        return await real_find_one(self, *a, **kw)
    monkeypatch.setattr(TenantCollection, "get", get)
    monkeypatch.setattr(TenantCollection, "find_one", find_one)

    async def _edit_a():
        asyncio.current_task().pause_me = True
        return await routes.update_invoice_line(IL, InvoiceLineUpdate(unit_price=20), user=OWNER)
    a = asyncio.create_task(_edit_a())
    await asyncio.wait_for(reached.wait(), 10)
    await routes.update_invoice_line(IL2, InvoiceLineUpdate(unit_price=30), user=OWNER)
    release.set()
    await a
    await _assert_header_is_sum(db)
    await rebuild_from_ledger(db, tenant_id=T)
    await _assert_header_is_sum(db)
    assert (await db["invoices"].find_one({"id": "inv-c26"}))["subtotal"] == 500.0
