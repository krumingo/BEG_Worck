"""CLAUDE AUDIT probe — #82 WH-REV-01 (ed8f9e7). Copy into backend/tests/; real Mongo RS
(MONGO_URL with replicaSet, WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1); off / shadow / enforce.
Reuses the PR's own harness (tests.test_wh_rev_01_receipt_reversal).
  R1 ×10  reversal ∥ reversal of ONE receipt (two keys) → exactly one 201, the other 409
          RECEIPT_ALREADY_REVERSED; one reversal row; WH free 0 live + rebuild ×2.
  R2 ×10  reversal of a linked direct delivery (line fully linked) ∥ a NEW linked delivery of
          10 into P → the live (not reversed) linked qty never exceeds the line (10) and P's
          canonical cost == 100 × live deliveries, live + rebuild ×2.
  R3 ×10  reversal ∥ reallocation P→Q → the reallocation only succeeds after the reversal;
          never Q allocated while a live link to P exists.
  R4      key K reverses receipt A; the same K on an identical receipt B → 409, B untouched.
  R5      exact values: direct 3 @ 3.3333 / 7 @ 0.0001 / 1.5 @ 12.345 → reversed → P canonical
          cost exactly 0 (Decimal Σ of material_entries) live + rebuild ×2.
  R6      reason "   " (blank) → observation only.
  R7      a warehouse lot moved whole to the project (dispatch + accept) → 409 naming both.
"""
import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements import CanonicalAction
from app.services.warehouse_movements.errors import WarehouseMovementError
from app.services.warehouse_movements.fifo import free_balance
from app.services.warehouse_movements.projections import rebuild_from_ledger
from app.services.warehouse_movements.reversal import without_reversed
from tests.test_wh_rev_01_receipt_reversal import (  # noqa: F401
    IL, ITEM, MODES, ONLY_P, PRJ, PROJECT, Q, T, WH, _SUP, _allocate_to, _book, _ctx, _inp,
    _prepare, _receipt, _reverse, _routes, _rows, _staff, _wc)

pytest_plugins = ["tests.warehouse_canonical_conftest"]


async def _rebuilds(db, check):
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        await check(i)


async def _live_linked(db):
    rows = [r async for r in db["warehouse_transactions"].find(
        {"tenant_id": T, "invoice_line_id": IL}, {"_id": 0, "movement_id": 1, "action": 1,
                                                    "quantity": 1})]
    rows = await without_reversed(db["warehouse_transactions"], rows)
    return sum(Decimal(str(r["quantity"])) for r in rows), len(rows)


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_r1_reversal_races_reversal(canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode,
                                          allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    a, b = await asyncio.gather(_reverse(wc, mode, receipt, key="k-a"),
                                _reverse(wc, mode, receipt, key="k-b"), return_exceptions=True)
    outs = [x for x in (a, b) if not isinstance(x, Exception)]
    errs = [x for x in (a, b) if isinstance(x, Exception)]
    codes = [(e.status_code, (e.detail.get("context") or {}).get("code")) if isinstance(e, HTTPException)
             else repr(e) for e in errs]
    print("R1 %s/%d: wins %d errs %s rows %d" % (mode, rep, len(outs), codes,
                                                 await _rows(db, action="reverse_supplier_receipt")))
    assert len(outs) == 1 and codes == [(409, "RECEIPT_ALREADY_REVERSED")], codes
    assert await _rows(db, action="reverse_supplier_receipt") == 1

    async def check(i):
        assert await free_balance(run.coll, tenant_id=T, item_id=ITEM, location=WH) == 0, i
    await _rebuilds(db, check)


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_r2_reversal_races_a_new_linked_delivery(canonical_mongo_db, allow_always_gate, monkeypatch,
                                                       mode, rep):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode,
                                          allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, PRJ)
    rev, new = await asyncio.gather(
        _reverse(wc, mode, receipt),
        svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt(PRJ, "10", "k-new")),
        return_exceptions=True)
    qty, n = await _live_linked(db)
    print("R2 %s/%d: rev %s new %s | live linked %s (%d rows)" % (
        mode, rep, getattr(rev, "status_code", "ok") if isinstance(rev, Exception) else "201",
        type(new).__name__ if isinstance(new, Exception) else "201", qty, n))
    assert not isinstance(rev, Exception), rev
    if isinstance(new, Exception):
        assert isinstance(new, WarehouseMovementError), new
    assert qty <= 10 and n == (0 if isinstance(new, Exception) else 1)

    async def check(i):
        c = await run.cost(PROJECT)
        assert c["canonical_cost"] == pytest.approx(100.0 * n), (i, c)
    await _rebuilds(db, check)


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_r3_reversal_races_reallocation(canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode,
                                          allocations=ONLY_P)
    routes, wc = _routes(monkeypatch, client, db), _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, PRJ)
    rev, alloc = await asyncio.gather(_reverse(wc, mode, receipt), _allocate_to(routes, Q),
                                      return_exceptions=True)
    line = await db["invoice_lines"].find_one({"id": IL}, {"_id": 0})
    refs = sorted(a.get("ref_id") for a in (line.get("allocations") or []))
    qty, n = await _live_linked(db)
    print("R3 %s/%d: rev %s alloc %s | allocations %s live links %d" % (
        mode, rep, "201" if not isinstance(rev, Exception) else rev,
        "ok" if not isinstance(alloc, Exception) else getattr(alloc, "status_code", alloc), refs, n))
    assert not isinstance(rev, Exception), rev
    if isinstance(alloc, Exception):
        assert isinstance(alloc, HTTPException) and alloc.status_code == 409, alloc
        assert refs == [PROJECT]
    else:
        assert refs == [Q]
    assert n == 0

    async def check(i):
        p, q = await run.cost(PROJECT), await run.cost(Q)
        assert p["canonical_cost"] == pytest.approx(0.0) and q["canonical_cost"] == pytest.approx(0.0), i
        want = (100.0, 0.0) if refs == [PROJECT] else (0.0, 100.0)
        assert (p["total_cost"], q["total_cost"]) == (pytest.approx(want[0]), pytest.approx(want[1])), (i, p, q)
    await _rebuilds(db, check)


@pytest.mark.parametrize("mode", MODES)
async def test_r4_one_key_two_receipts(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode,
                                          allocations=[])
    wc = _wc(monkeypatch, client, db)
    mk = lambda k: _inp(CanonicalAction.RECEIVE_FROM_SUPPLIER, T, source=_SUP, destination=WH,
                        quantity=Decimal("10"), unit_value=Decimal("10"), idempotency_key=k)
    a = (await svc.execute(_ctx(mode, "Owner"), db, run.coll, mk("rc-a"))).movement_id
    b = (await svc.execute(_ctx(mode, "Owner"), db, run.coll, mk("rc-b"))).movement_id
    first = await _reverse(wc, mode, a, key="K")
    try:
        second = await _reverse(wc, mode, b, key="K")
        res = ("201", getattr(second, "replay", None), second.movement_id == first.movement_id)
    except HTTPException as exc:
        res = (exc.status_code, (exc.detail or {}).get("error_code"))
    rows = [r["reverses_movement_id"] async for r in db["warehouse_transactions"].find(
        {"action": "reverse_supplier_receipt"}, {"_id": 0, "reverses_movement_id": 1})]
    free = await free_balance(run.coll, tenant_id=T, item_id=ITEM, location=WH)
    print("R4 %s: second reversal with the same key on B -> %s | reversed %s | WH free %s" % (
        mode, res, ["A" if x == a else "B" for x in rows], free))
    assert res[0] == 409 and rows == [a] and free == 10


@pytest.mark.parametrize("case", [("3", "3.3333"), ("7", "0.0001"), ("1.5", "12.345"), ("0.001", "99999.9999")])
@pytest.mark.parametrize("mode", MODES)
async def test_r5_exact_zero_after_reversal(canonical_mongo_db, allow_always_gate, monkeypatch, mode, case):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode,
                                          allocations=[])
    wc = _wc(monkeypatch, client, db)
    qty, uv = case
    mid = (await svc.execute(_ctx(mode, "Owner"), db, run.coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, T, source=_SUP, destination=PRJ,
        quantity=Decimal(qty), unit_value=Decimal(uv), project_id=PROJECT,
        idempotency_key="r5"))).movement_id
    await _reverse(wc, mode, mid)

    async def check(i):
        rows = await db["material_entries"].find({"org_id": T, "project_id": PROJECT}).to_list(None)
        s = sum(Decimal(str(r.get("total_value") or "0")) for r in rows)
        kinds = sorted(r["movement_kind"] for r in rows)
        c = await run.cost(PROJECT)
        print("R5 %s %s@%s rebuild %d: kinds %s Σ %s canonical %s" % (mode, qty, uv, i, kinds, s,
                                                                      c["canonical_cost"]))
        assert s == 0 and kinds == ["accept", "receipt_reversal"] and c["canonical_cost"] == 0, (i, s)
    await _rebuilds(db, check)


@pytest.mark.parametrize("mode", MODES)
async def test_r6_blank_reason_observation(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode,
                                          allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    try:
        out = await _reverse(wc, mode, receipt, reason="   ")
        print("R6 %s: blank reason ACCEPTED (201), stored reason %r" % (mode, out.envelope.get("reason")))
    except HTTPException as exc:
        print("R6 %s: blank reason -> %s" % (mode, exc.status_code))


@pytest.mark.parametrize("mode", MODES)
async def test_r7_lot_moved_whole_to_the_project(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode,
                                          allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH)
    d = await _staff(mode, run.dispatch("10"))
    acc = await _staff(mode, run.accept(d, "10"))
    before = await _rows(db)
    with pytest.raises(HTTPException) as exc:
        await _reverse(wc, mode, receipt)
    ctx = exc.value.detail.get("context") or {}
    takers = [t["movement_id"] for t in ctx.get("taken_by", [])]
    print("R7 %s: %s %s still %s takers %s (dispatch %s, accept %s)" % (
        mode, exc.value.status_code, ctx.get("code"), ctx.get("still_in_bucket"), len(takers),
        d.movement_id in takers, acc.movement_id in takers))
    assert exc.value.status_code == 409 and ctx.get("code") == "RECEIPT_ALREADY_ISSUED"
    assert d.movement_id in takers and await _rows(db) == before


# ═════ 1622f62 (Addendum A): Р47 under concurrency ═════
from tests.test_wh_rev_01_receipt_reversal import _pay, _sent_invoice  # noqa: E402


async def _r47_setup(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    db, finance = await _sent_invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    client = db.client
    from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
    from app.services.warehouse_movements.service import CommandService
    run = _Run(client, allow_always_gate, db)
    svc = CommandService(client)
    wc = _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH, qty="4")
    return db, finance, wc, receipt


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_r8_reversal_races_full_payment(canonical_mongo_db, allow_always_gate, monkeypatch, mode, rep):
    """Invoice 120 (L 10 @10 +20 %); 4 linked received. Concurrently: reverse the 4 (credit 48)
    ∥ quick-pay 120. Allowed: payment first (paid 120; reversal then 201 or 409 INVOICE_BUSY) or
    reversal first (payment 409 INVOICE_AWAITS_CREDIT_NOTE). Never: payment 201 decided while an
    open credit already existed (paid > 72 with the ECN created BEFORE the payment's allocation)."""
    db, finance, wc, receipt = await _r47_setup(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    rev, pay = await asyncio.gather(_reverse(wc, mode, receipt), _pay(finance, 120.0, "k-full"),
                                    return_exceptions=True)
    ecn = await db["expected_credit_notes"].find_one({}) or {}
    alloc = await db["payment_allocations"].find_one({"invoice_id": "inv-c26"}) or {}
    def st(x):
        if isinstance(x, HTTPException):
            return (x.status_code, (x.detail or {}).get("error_code"))
        return "ok" if not isinstance(x, Exception) else type(x).__name__
    order = None
    if ecn and alloc:
        order = "credit-first" if str(ecn.get("created_at")) < str(alloc.get("allocated_at") or alloc.get("created_at")) else "pay-first"
    print("R8 %s/%d: reversal %s | payment %s | ECN %s | paid alloc %s | order %s" % (
        mode, rep, st(rev), st(pay), ecn.get("amount"), alloc.get("amount_allocated"), order))
    assert not (st(pay) == "ok" and st(rev) == "ok" and order == "credit-first"), \
        "a full payment committed after the invoice started awaiting a credit"
    if st(rev) != "ok":
        assert st(rev) == (409, "INVOICE_BUSY") and not ecn
    if st(pay) != "ok":
        assert st(pay) == (409, "INVOICE_AWAITS_CREDIT_NOTE") and not alloc


@pytest.mark.parametrize("mode", MODES)
async def test_r9_reversal_while_payment_holds_the_lock(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Deterministic: the payment pauses inside its credit read (row lock held) while the
    reversal runs → the reversal must be 409 INVOICE_BUSY, and the payment then goes through."""
    db, finance, wc, receipt = await _r47_setup(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    real = finance._awaited_credit
    box = {}

    async def paused(tenant, invoice_id):
        if "rev" not in box:
            try:
                box["rev"] = await _reverse(wc, mode, receipt)
            except HTTPException as exc:
                box["rev"] = (exc.status_code, (exc.detail or {}).get("error_code"))
        return await real(tenant, invoice_id)
    monkeypatch.setattr(finance, "_awaited_credit", paused)
    pay = await _pay(finance, 120.0, "k-full")
    ecn = await db["expected_credit_notes"].count_documents({})
    print("R9 %s: reversal during the payment -> %s | payment %s | ECN rows %d" % (
        mode, box["rev"] if isinstance(box["rev"], tuple) else "201", "ok" if pay else pay, ecn))
    assert box["rev"] == (409, "INVOICE_BUSY") and ecn == 0
