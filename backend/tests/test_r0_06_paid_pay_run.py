"""
R0-06 — a paid Pay Run is not reopened and is not paid a second time (AUD-043).

The 11 cases of docs/architecture/tasks/R0-06_PAID_PAY_RUN_NO_REOPEN_NO_DOUBLE_PAY.md,
positive and forbidden:

1. normal ``create → mark-paid`` (as the UI does) → exactly one Outflow per employee with paid > 0;
2. ``mark-paid`` a second time → 409, nothing new in finance_payments / advances / payment_slips;
3. concurrent ``mark-paid`` → exactly one wins, one Outflow per employee, advances reduced once;
4. ``mark-paid`` of a cancelled run → 409, nothing written;
5. ``reopen`` of a paid run → 409, byte-equal state;
6. ``reopen`` of rows of a paid run → 409, byte-equal state;
7. ``reopen`` of confirmed / draft → as before;
8. ``PATCH`` of a paid run → 409, nothing written;
9. after a refused reopen a new ``mark-paid`` → 409, no second Outflow (also for a run a
   pre-R0-06 reopen left as ``reopened`` with ``paid_at`` set — money already out);
10. two tenants: B cannot mark-paid / reopen / PATCH a run of A (404) and A's payment
    does not touch B;
11. only Admin/Owner; other roles → 403.

R0-06-C01 (Codex F-01/F-02):

12–15. one operation per run (``op_lock``): reopen / PATCH / create still running their
       downstream effects block mark-paid, and a mark-paid in its effects blocks reopen /
       PATCH (fault-controlled interleavings, both orders); the end state is consistent;
16.    only a confirmed run is paid;
17.    a failure early / middle / late in the payment effects → ``payment_failed``: no
       paid consumer counts it, list / detail / audit-check show it, no second payment;
18.    a completed payment is still counted by the consumers;
19.    an operation that crashed keeps the run locked (fail closed) and is flagged.

Case 3 is meaningful on the REAL MongoDB only: mongomock_motor executes each call
synchronously, so its "concurrent" requests are effectively serial and prove nothing
about atomicity. It still runs there as a smoke test.

Runs in-process against ``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL``
names a disposable LOCAL MongoDB, again against it — one database per test,
dropped afterwards. Authentication is real (JWT + user loaded from the database).

    PYTHONPATH=. pytest tests/test_r0_06_paid_pay_run.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27018/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_r0_06_paid_pay_run.py -v --noconftest
"""
import asyncio

import pytest

from tests.test_r0_05_pay_run_selected_only import (
    H, ORG_A, ORG_B, P_END, P_START, _Db, _app, _real_refusal, _seed, body, row,
)

ADVANCE_A = "adv-a1"
STATE_COLLECTIONS = ("pay_runs", "payment_slips", "pay_run_allocations", "payroll_payment_allocations",
                     "finance_payments", "advances", "employee_daily_reports")
CONCURRENT = 8


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


async def _seed_money(op):
    await op.financial_accounts.insert_many([
        {"id": "acc-a-cash", "org_id": ORG_A, "type": "Cash", "name": "Каса A"},
        {"id": "acc-a-bank", "org_id": ORG_A, "type": "Bank", "name": "Банка A"},
        {"id": "acc-b-cash", "org_id": ORG_B, "type": "Cash", "name": "Каса B"},
    ])
    await op.advances.insert_many([
        {"id": ADVANCE_A, "org_id": ORG_A, "user_id": "emp-a1", "type": "advance",
         "amount": 200, "remaining_amount": 200, "status": "Open", "deductions": []},
        {"id": "adv-b1", "org_id": ORG_B, "user_id": "emp-b1", "type": "advance",
         "amount": 100, "remaining_amount": 100, "status": "Open", "deductions": []},
    ])


def run(monkeypatch, scenario, backend="mongomock"):
    import httpx

    async def go():
        async with _Db(backend) as op:
            await _seed(op)
            await _seed_money(op)
            app = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r006") as c:
                return await scenario(c, op)
    return asyncio.run(go())


def _rows():
    """Ivan (emp-a1) 500 earned − 50 advance → paid 450; Petar (emp-a2) paid 300 of 500."""
    a1 = row("emp-a1", paid=450)
    a1["adjustments"] = [{"type": "advance", "title": "Аванс", "amount": 50, "ref_id": ADVANCE_A}]
    return [a1, row("emp-a2", paid=300)]


EXPECTED_OUTFLOWS = {"emp-a1": 450, "emp-a2": 300}


async def _create(c, status="confirmed", who="admin-a"):
    r = await c.post("/api/pay-runs", json=body(_rows(), status), headers=H[who]())
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _mark_paid(c, run_id, who="admin-a"):
    return await c.post("/api/pay-runs/%s/mark-paid" % run_id,
                        json={"payment_method": "cash", "payment_reference": "", "payment_note": ""},
                        headers=H[who]())


async def _reopen(c, run_id, employee_ids=(), who="admin-a"):
    return await c.post("/api/pay-runs/%s/reopen" % run_id,
                        json={"employee_ids": list(employee_ids), "reason": "r0-06"}, headers=H[who]())


async def _patch(c, run_id, status="confirmed", who="admin-a"):
    return await c.patch("/api/pay-runs/" + run_id, json=body(_rows(), status), headers=H[who]())


async def _paid_run(c):
    run_id = await _create(c)
    r = await _mark_paid(c, run_id)
    assert r.status_code == 200, r.text
    return run_id


async def _snapshot(op):
    """Byte-level snapshot of every collection a Pay Run (or its payment) writes."""
    import bson
    snap = {}
    for coll in STATE_COLLECTIONS:
        docs = await op[coll].find({}, {"_id": 0}).to_list(10000)
        snap[coll] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d)}) for d in docs)
    return snap


async def _assert_paid_once(op, run_id):
    """One Outflow per employee with paid > 0, the advance reduced once, one marked_paid entry."""
    pays = await op.finance_payments.find({"reference": run_id}, {"_id": 0}).to_list(100)
    assert sorted((p["user_id"], p["amount"]) for p in pays) == sorted(EXPECTED_OUTFLOWS.items()), pays
    assert all(p["direction"] == "Outflow" and p["org_id"] == ORG_A
               and p["account_id"] == "acc-a-cash" for p in pays)
    assert await op.finance_payments.count_documents({}) == len(EXPECTED_OUTFLOWS)
    adv = await op.advances.find_one({"id": ADVANCE_A}, {"_id": 0})
    assert adv["remaining_amount"] == 150 and adv["status"] == "Open", adv
    assert [d["amount"] for d in adv["deductions"]] == [50], adv
    pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
    assert pr["status"] == "paid" and pr["paid_at"]
    assert [h["action"] for h in pr["history"]].count("marked_paid") == 1
    slips = await op.payment_slips.find({"pay_run_id": run_id}, {"_id": 0}).to_list(100)
    assert len(slips) == 2 and all(s["status"] == "paid" for s in slips)
    # B is untouched by A's payment
    adv_b = await op.advances.find_one({"id": "adv-b1"}, {"_id": 0})
    assert adv_b["remaining_amount"] == 100 and adv_b["deductions"] == []
    assert await op.finance_payments.count_documents({"org_id": ORG_B}) == 0


# ═══════════════════════════════════════════════════════════════════ 1
def test_01_create_then_mark_paid_one_outflow_per_employee(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _paid_run(c)
        await _assert_paid_once(op, run_id)
        pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert pr.get("paid_effects", "done") == "done"   # R0-06 marker; absent on main
        reports = await op.employee_daily_reports.find(
            {"payroll_source": "pay_run:" + run_id}, {"_id": 0}).to_list(100)
        assert reports and all(r["payroll_status"] == "paid" for r in reports)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 2
def test_02_second_mark_paid_refused_nothing_written(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _paid_run(c)
        before = await _snapshot(op)
        r = await _mark_paid(c, run_id)
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == "Already paid"
        assert await _snapshot(op) == before
        await _assert_paid_once(op, run_id)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 3
def test_03_concurrent_mark_paid_exactly_one_wins(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _create(c)
        results = await asyncio.gather(*[_mark_paid(c, run_id) for _ in range(CONCURRENT)])
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * (CONCURRENT - 1), [(r.status_code, r.text) for r in results]
        await _assert_paid_once(op, run_id)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 4
def test_04_mark_paid_of_cancelled_refused(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _create(c)
        await op.pay_runs.update_one({"id": run_id}, {"$set": {"status": "cancelled"}})
        before = await _snapshot(op)
        r = await _mark_paid(c, run_id)
        assert r.status_code == 409, r.text
        assert await _snapshot(op) == before
        assert await op.finance_payments.count_documents({}) == 0
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 5
def test_05_reopen_of_paid_run_refused_byte_equal(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _paid_run(c)
        before = await _snapshot(op)
        r = await _reopen(c, run_id)
        assert r.status_code == 409, r.text
        assert "reversal" in r.json()["detail"]
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 6
def test_06_reopen_of_rows_of_paid_run_refused_byte_equal(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _paid_run(c)
        before = await _snapshot(op)
        for ids in (["emp-a1"], ["emp-a1", "emp-a2"], ["emp-a3"]):
            r = await _reopen(c, run_id, ids)
            assert r.status_code == 409, (ids, r.text)
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 7
def test_07_reopen_of_confirmed_and_draft_as_before(monkeypatch, backend):
    async def confirmed_all(c, op):
        run_id = await _create(c, "confirmed")
        r = await _reopen(c, run_id)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "reopened" and r.json()["reopened_count"] == 2
        slips = await op.payment_slips.find({"pay_run_id": run_id}, {"_id": 0}).to_list(100)
        assert slips and all(s["status"] == "superseded" for s in slips)
        # a reopened, never paid run is edited and paid as before — once
        r = await _patch(c, run_id)
        assert r.status_code == 200, r.text
        assert (await _mark_paid(c, run_id)).status_code == 200
        await _assert_paid_once(op, run_id)

    async def confirmed_rows(c, op):
        run_id = await _create(c, "confirmed")
        r = await _reopen(c, run_id, ["emp-a2"])
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "confirmed" and r.json()["reopened_count"] == 1
        slips = {s["employee_id"]: s["status"] for s in
                 await op.payment_slips.find({"pay_run_id": run_id}, {"_id": 0}).to_list(100)}
        assert slips == {"emp-a1": "confirmed", "emp-a2": "superseded"}

    async def draft(c, op):
        run_id = await _create(c, "draft")
        r = await _reopen(c, run_id)
        assert r.status_code == 200 and r.json()["status"] == "reopened", r.text

    for scenario in (confirmed_all, confirmed_rows, draft):
        run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 8
def test_08_patch_of_paid_run_refused_nothing_written(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _paid_run(c)
        before = await _snapshot(op)
        for status in ("confirmed", "draft"):
            r = await _patch(c, run_id, status)
            assert r.status_code == 409, r.text
            assert "reversal" in r.json()["detail"]
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 9
def test_09_after_refused_reopen_mark_paid_refused_no_second_outflow(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _paid_run(c)
        before = await _snapshot(op)
        assert (await _reopen(c, run_id)).status_code == 409
        assert (await _patch(c, run_id)).status_code == 409
        r = await _mark_paid(c, run_id)
        assert r.status_code == 409, r.text
        assert await _snapshot(op) == before
        await _assert_paid_once(op, run_id)
    run(monkeypatch, scenario, backend)


def test_09b_legacy_reopened_after_paid_cannot_be_paid_again(monkeypatch, backend):
    """A run a pre-R0-06 reopen left as ``reopened`` with ``paid_at`` set (money already out)."""
    async def scenario(c, op):
        run_id = await _paid_run(c)
        await op.pay_runs.update_one({"id": run_id}, {"$set": {"status": "reopened"}})
        await op.payment_slips.update_many({"pay_run_id": run_id}, {"$set": {"status": "superseded"}})
        before = await _snapshot(op)
        assert (await _patch(c, run_id)).status_code == 409
        assert (await _reopen(c, run_id)).status_code == 409
        assert (await _mark_paid(c, run_id)).status_code == 409
        assert await _snapshot(op) == before
        assert await op.finance_payments.count_documents({}) == len(EXPECTED_OUTFLOWS)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 10
def test_10_other_tenant_gets_404_and_is_untouched(monkeypatch, backend):
    async def scenario(c, op):
        unpaid = await _create(c)
        before = await _snapshot(op)
        assert (await _mark_paid(c, unpaid, who="admin-b")).status_code == 404
        assert (await _reopen(c, unpaid, who="admin-b")).status_code == 404
        r = await c.patch("/api/pay-runs/" + unpaid, json=body([row("emp-b1", paid=0)]),
                          headers=H["admin-b"]())
        assert r.status_code == 404, r.text
        assert await _snapshot(op) == before
        assert (await _mark_paid(c, unpaid)).status_code == 200
        await _assert_paid_once(op, unpaid)
        before = await _snapshot(op)
        assert (await _reopen(c, unpaid, who="admin-b")).status_code == 404
        assert (await _mark_paid(c, unpaid, who="admin-b")).status_code == 404
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 11
def test_11_only_admin_owner(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _create(c)
        before = await _snapshot(op)
        for who in ("tech-a", "acct-a"):
            assert (await _mark_paid(c, run_id, who=who)).status_code == 403
            assert (await _reopen(c, run_id, who=who)).status_code == 403
            assert (await _patch(c, run_id, who=who)).status_code == 403
        assert await _snapshot(op) == before
        assert (await _mark_paid(c, run_id, who="owner-a")).status_code == 200
        await _assert_paid_once(op, run_id)
        assert (await _reopen(c, run_id, who="owner-a")).status_code == 409
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ R0-06-C01
# F-01: one operation per run (op_lock) — fault-controlled interleavings, both orders.
# F-02: paying → paid | payment_failed; an unfinished payment is never "paid".

def _pause(monkeypatch, name):
    """Replace pay_runs.<name> by a wrapper that parks its FIRST call until ``resume``."""
    from app.routes import pay_runs
    orig = getattr(pay_runs, name)
    state = {"entered": asyncio.Event(), "resume": asyncio.Event(), "first": True}

    async def wrapped(*a, **kw):
        if state["first"]:
            state["first"] = False
            state["entered"].set()
            await state["resume"].wait()
        return await orig(*a, **kw)
    monkeypatch.setattr(pay_runs, name, wrapped)
    return state


def _fail(monkeypatch, name, exc=RuntimeError):
    from app.routes import pay_runs

    async def boom(*a, **kw):
        raise exc("injected failure in %s" % name)
    monkeypatch.setattr(pay_runs, name, boom)


async def _assert_paid_consistent(op, run_id):
    """A completed payment: money once AND every downstream record says paid/active."""
    await _assert_paid_once(op, run_id)
    pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
    assert pr["paid_effects"] == "done" and pr.get("op_lock") is None, pr.get("op_lock")
    allocs = await op.payroll_payment_allocations.find({"source_pay_run_id": run_id}, {"_id": 0}).to_list(100)
    live = [a for a in allocs if a["status"] != "reversed"]
    assert live and all(a["status"] == "active" for a in live), [a["status"] for a in allocs]
    reports = await op.employee_daily_reports.find({"payroll_source": "pay_run:" + run_id},
                                                   {"_id": 0}).to_list(100)
    assert reports and all(r["payroll_status"] == "paid" for r in reports)
    slips = await op.payment_slips.find({"pay_run_id": run_id}, {"_id": 0}).to_list(100)
    assert slips and all(sl["status"] == "paid" for sl in slips)


async def _start(coro):
    return asyncio.ensure_future(coro)


def test_12_reopen_in_flight_blocks_mark_paid_then_consistent(monkeypatch, backend):
    """Codex F-01 order 1: reopen won its write and is inside sync_on_reopen → mark-paid 409."""
    async def scenario(c, op):
        run_id = await _create(c)
        gate = _pause(monkeypatch, "sync_on_reopen")
        task = await _start(_reopen(c, run_id))
        await gate["entered"].wait()
        r = await _mark_paid(c, run_id)
        assert r.status_code == 409, r.text
        assert "в ход" in r.json()["detail"]
        held = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert held["op_lock"]["op"] == "reopen"
        assert await op.finance_payments.count_documents({}) == 0
        gate["resume"].set()
        assert (await task).status_code == 200
        pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert pr["status"] == "reopened" and pr.get("op_lock") is None and not pr.get("paid_at")
        allocs = await op.payroll_payment_allocations.find({"source_pay_run_id": run_id}).to_list(100)
        assert allocs and all(a["status"] == "reversed" for a in allocs)
        # a reopened run is not paid as it is (C01) — re-confirm first, then pay once
        assert (await _mark_paid(c, run_id)).status_code == 409
        assert (await _patch(c, run_id, "confirmed")).status_code == 200
        assert (await _mark_paid(c, run_id)).status_code == 200
        await _assert_paid_consistent(op, run_id)
    run(monkeypatch, scenario, backend)


def test_13_patch_in_flight_blocks_mark_paid_then_consistent(monkeypatch, backend):
    """Codex F-01 order 1 for PATCH: PATCH draft→confirmed is inside sync_on_confirm → mark-paid 409."""
    async def scenario(c, op):
        run_id = await _create(c, "draft")
        gate = _pause(monkeypatch, "sync_on_confirm")
        task = await _start(_patch(c, run_id, "confirmed"))
        await gate["entered"].wait()
        r = await _mark_paid(c, run_id)
        assert r.status_code == 409, r.text
        held = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert held["status"] == "confirmed" and held["op_lock"]["op"] == "update"
        assert await op.finance_payments.count_documents({}) == 0
        gate["resume"].set()
        assert (await task).status_code == 200
        assert (await _mark_paid(c, run_id)).status_code == 200
        await _assert_paid_consistent(op, run_id)
    run(monkeypatch, scenario, backend)


def test_14_mark_paid_in_flight_blocks_reopen_and_patch(monkeypatch, backend):
    """Order 2: mark-paid claimed and is inside its effects → reopen / PATCH 409, nothing written."""
    async def scenario(c, op):
        run_id = await _create(c)
        gate = _pause(monkeypatch, "sync_on_paid")
        task = await _start(_mark_paid(c, run_id))
        await gate["entered"].wait()
        held = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert held["status"] == "paying" and held["op_lock"]["op"] == "mark_paid"
        before = await _snapshot(op)
        for ids in ([], ["emp-a1"]):
            assert (await _reopen(c, run_id, ids)).status_code == 409
        assert (await _patch(c, run_id)).status_code == 409
        assert (await _mark_paid(c, run_id)).status_code == 409
        assert await _snapshot(op) == before
        # while paying it is not paid for any consumer
        r = await c.get("/api/pay-runs", headers=H["admin-a"]())
        item = next(i for i in r.json()["items"] if i["id"] == run_id)
        assert item["status"] == "paying" and item["paid_effects"] == "pending"
        gate["resume"].set()
        assert (await task).status_code == 200
        await _assert_paid_consistent(op, run_id)
    run(monkeypatch, scenario, backend)


def test_15_create_in_flight_blocks_mark_paid(monkeypatch, backend):
    """create holds the lock until its allocations/sync exist — a mark-paid in between → 409."""
    async def scenario(c, op):
        gate = _pause(monkeypatch, "sync_on_confirm")
        task = await _start(_create(c))
        await gate["entered"].wait()
        held = await op.pay_runs.find_one({}, {"_id": 0})
        assert (await _mark_paid(c, held["id"])).status_code == 409
        assert held["op_lock"]["op"] == "create"
        gate["resume"].set()
        run_id = await task
        assert (await op.pay_runs.find_one({"id": run_id}, {"_id": 0})).get("op_lock") is None
        assert (await _mark_paid(c, run_id)).status_code == 200
        await _assert_paid_consistent(op, run_id)
    run(monkeypatch, scenario, backend)


def test_16_only_confirmed_is_paid(monkeypatch, backend):
    async def scenario(c, op):
        draft = await _create(c, "draft")
        before = await _snapshot(op)
        r = await _mark_paid(c, draft)
        assert r.status_code == 409 and "confirmed" in r.json()["detail"], r.text
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


async def _paid_consumers(monkeypatch, op, c):
    """What every paid-run consumer reports for tenant A."""
    from app.services import paid_labor
    monkeypatch.setattr(paid_labor, "db", op)
    return {
        "paid_labor_v3": await paid_labor.paid_labor_v3(ORG_A, "2026-01-01", "2026-12-31"),
        "paid_alloc_rows": await paid_labor._paid_alloc_rows(ORG_A),
        "list_status_paid": (await c.get("/api/pay-runs", params={"status": "paid"},
                                         headers=H["admin-a"]())).json()["items"],
    }


@pytest.mark.parametrize("stage", ["early:_reduce_advances", "middle:sync_on_paid", "late:_mark_slips_paid"])
def test_17_failed_payment_is_never_paid(monkeypatch, backend, stage):
    """F-02: a failure early / middle / late in the effects → payment_failed, excluded from
    every paid consumer, flagged to the operator, no second payment, lock kept."""
    target = stage.split(":")[1]

    async def scenario(c, op):
        run_id = await _create(c)
        _fail(monkeypatch, target)
        with pytest.raises(RuntimeError):
            await _mark_paid(c, run_id)
        pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert pr["status"] == "payment_failed" and pr["paid_effects"] == "failed", pr["status"]
        assert pr["paid_effects_error"] == "RuntimeError" and pr["op_lock"]["op"] == "mark_paid"
        assert [h["action"] for h in pr["history"]].count("payment_failed") == 1
        assert "marked_paid" not in [h["action"] for h in pr["history"]]
        # consumers: nothing counted as paid
        got = await _paid_consumers(monkeypatch, op, c)
        assert got == {"paid_labor_v3": [], "paid_alloc_rows": [], "list_status_paid": []}, got
        assert await op.pay_runs.count_documents({"status": "paid"}) == 0
        # operator sees it: list, detail, audit-check
        item = (await c.get("/api/pay-runs", headers=H["admin-a"]())).json()["items"][0]
        assert item["status"] == "payment_failed" and item["paid_effects"] == "failed"
        detail = (await c.get("/api/pay-runs/" + run_id, headers=H["admin-a"]())).json()
        assert detail["status"] == "payment_failed" and "token" not in detail["op_lock"]
        audit = (await c.get("/api/pay-runs/audit-check", headers=H["admin-a"]())).json()
        assert any(i["type"] == "payment_incomplete" and i["severity"] == "critical"
                   for i in audit["issues"]), audit
        # no second payment, no edit, no reopen — nothing written
        before = await _snapshot(op)
        assert (await _mark_paid(c, run_id)).status_code == 409
        assert (await _reopen(c, run_id)).status_code == 409
        assert (await _patch(c, run_id)).status_code == 409
        assert await _snapshot(op) == before
        assert await op.finance_payments.count_documents({}) <= len(EXPECTED_OUTFLOWS)
    run(monkeypatch, scenario, backend)


def test_18_completed_payment_is_counted(monkeypatch, backend):
    """The consumer filter is not over-strict: a completed payment is paid labor."""
    async def scenario(c, op):
        run_id = await _paid_run(c)
        got = await _paid_consumers(monkeypatch, op, c)
        assert sorted(r["net_salary"] for r in got["paid_labor_v3"]) == [300, 450]
        assert sorted({r["worker_id"] for r in got["paid_alloc_rows"]}) == ["emp-a1", "emp-a2"]
        assert [i["id"] for i in got["list_status_paid"]] == [run_id]
        audit = (await c.get("/api/pay-runs/audit-check", headers=H["admin-a"]())).json()
        assert not [i for i in audit["issues"] if i["type"] in ("payment_incomplete", "operation_stuck")]
    run(monkeypatch, scenario, backend)


def test_19_crashed_reopen_keeps_run_locked(monkeypatch, backend):
    """Fail closed: an operation that dies mid-way keeps its lock; nothing else runs on the run."""
    async def scenario(c, op):
        run_id = await _create(c)
        _fail(monkeypatch, "sync_on_reopen")
        with pytest.raises(RuntimeError):
            await _reopen(c, run_id)
        before = await _snapshot(op)
        for call in (_mark_paid(c, run_id), _reopen(c, run_id), _patch(c, run_id)):
            r = await call
            assert r.status_code == 409 and "в ход или е прекъсната" in r.json()["detail"], r.text
        assert await _snapshot(op) == before
        audit = (await c.get("/api/pay-runs/audit-check", headers=H["admin-a"]())).json()
        assert any(i["type"] == "operation_stuck" for i in audit["issues"]), audit
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ R0-06-C02
# F-02a: a slip counts / shows as paid only when its parent Pay Run is "paid".

def _fail_after_slips(monkeypatch):
    """The real slip update commits, THEN the payment breaks (Codex F-02a)."""
    from app.routes import pay_runs
    orig = pay_runs._mark_slips_paid

    async def after(*a, **kw):
        await orig(*a, **kw)
        raise RuntimeError("injected failure after the slip update")
    monkeypatch.setattr(pay_runs, "_mark_slips_paid", after)


def run_c02(monkeypatch, scenario, backend="mongomock"):
    """``run`` plus the settings router and every module that reads payment_slips."""
    import httpx
    from app.routes import settings as settings_routes
    from app.services import cashflow_forecast, legacy_payslips, paid_labor

    async def go():
        async with _Db(backend) as op:
            await _seed(op)
            await _seed_money(op)
            await op.organizations.update_one({"id": ORG_A}, {"$set": {"workers_see_pay": True}})
            app = _app(monkeypatch, op)
            for module in (settings_routes, cashflow_forecast, legacy_payslips, paid_labor):
                monkeypatch.setattr(module, "db", op)
            app.include_router(settings_routes.router, prefix="/api")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r006") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def _slip_views(c, op, run_id):
    """What every payment_slips reader reports for tenant A."""
    from app.deps.auth import create_token
    from app.services import cashflow_forecast, legacy_payslips, paid_labor
    worker = {"Authorization": "Bearer " + create_token(
        {"user_id": "emp-a1", "org_id": ORG_A, "role": "Worker"})}
    slip_ids = [s["id"] for s in await op.payment_slips.find({"pay_run_id": run_id}).to_list(10)]
    forecast = await cashflow_forecast.build_cashflow_forecast(ORG_A, days=30, start_date="2026-10-12")
    weeks = (await c.get("/api/payroll-weeks", headers=H["admin-a"]())).json()
    return {
        "legacy": await legacy_payslips.legacy_payslips(ORG_A),
        "legacy_paid": await legacy_payslips.legacy_payslips(ORG_A, v1_statuses=["Paid"]),
        "legacy_generated": await legacy_payslips.legacy_payslips(ORG_A, v1_statuses=["Generated"]),
        "legacy_one": [await legacy_payslips.legacy_payslip_one(ORG_A, i) for i in slip_ids],
        "api_list": (await c.get("/api/payment-slips", headers=H["admin-a"]())).json(),
        "api_paid": (await c.get("/api/payment-slips", params={"status": "paid"}, headers=H["admin-a"]())).json(),
        "api_confirmed": (await c.get("/api/payment-slips", params={"status": "confirmed"},
                                      headers=H["admin-a"]())).json(),
        "api_one": [(await c.get("/api/payment-slips/" + i, headers=H["admin-a"]())).json() for i in slip_ids],
        "my_pay": (await c.get("/api/my-pay-summary", headers=worker)).json(),
        "payroll_items": [i for i in forecast["outgoing"] if i["source_type"] == "payroll"],
        "week_slip_statuses": sorted({r.get("slip_status") for r in weeks["items"] if r.get("slip_id")}),
        "paid_labor_v3": await paid_labor.paid_labor_v3(ORG_A, "2026-01-01", "2026-12-31"),
        "paid_alloc_rows": await paid_labor._paid_alloc_rows(ORG_A),
    }


def test_20_failure_after_slip_update_is_not_paid_anywhere(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _create(c)
        _fail_after_slips(monkeypatch)
        with pytest.raises(RuntimeError):
            await _mark_paid(c, run_id)
        # 1. the run is payment_failed, although the slips were really written "paid"
        pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert pr["status"] == "payment_failed" and pr["op_lock"]["op"] == "mark_paid"
        raw = await op.payment_slips.find({"pay_run_id": run_id}, {"_id": 0}).to_list(10)
        assert len(raw) == 2 and all(s["status"] == "paid" and s["paid_at"] for s in raw)
        v = await _slip_views(c, op, run_id)
        # 2. legacy / HR payslips: never "Paid"; owed ("Generated") and flagged
        assert [p["status"] for p in v["legacy"]] == ["Generated", "Generated"]
        assert all(p["payment_incomplete"] and p["paid_at"] is None for p in v["legacy"])
        assert v["legacy_paid"] == []
        assert [p["status"] for p in v["legacy_one"]] == ["Generated", "Generated"]
        # the slip API (list, ?status=, one) — same rule
        assert v["api_paid"]["total"] == 0 and v["api_paid"]["items"] == []
        assert v["api_confirmed"]["total"] == 2
        for s in v["api_list"]["items"] + v["api_one"]:
            assert s["status"] == "confirmed" and s["paid_at"] is None, s
            assert s["payment_incomplete"] and s["recorded_status"] == "paid" and s["recorded_paid_at"]
            assert s["pay_run_status"] == "payment_failed"
        assert v["week_slip_statuses"] == ["confirmed"]
        # 3. /my-pay-summary: still owed (500 earned − 50 advance), not paid
        assert v["my_pay"]["owed"] == 450, v["my_pay"]
        assert [s["status"] for s in v["my_pay"]["slips"]] == ["confirmed"]
        assert v["my_pay"]["slips"][0]["payment_incomplete"] is True
        # 4. cashflow: the unresolved salary is NOT silently dropped (net 450 + 500)
        assert [i["amount"] for i in v["payroll_items"]] == [950], v["payroll_items"]
        # 5. paid labor: excluded
        assert v["paid_labor_v3"] == [] and v["paid_alloc_rows"] == []
        # 6. no second payment
        before = await _snapshot(op)
        assert (await _mark_paid(c, run_id)).status_code == 409
        assert await _snapshot(op) == before
        assert await op.finance_payments.count_documents({}) == len(EXPECTED_OUTFLOWS)
    run_c02(monkeypatch, scenario, backend)


def test_21_completed_payment_is_paid_everywhere(monkeypatch, backend):
    """Positive: a completed payment reads as paid in every slip reader, as before."""
    async def scenario(c, op):
        run_id = await _paid_run(c)
        v = await _slip_views(c, op, run_id)
        assert [p["status"] for p in v["legacy"]] == ["Paid", "Paid"]
        assert not any(p.get("payment_incomplete") for p in v["legacy"])
        assert len(v["legacy_paid"]) == 2 and v["legacy_generated"] == []
        assert [p["status"] for p in v["legacy_one"]] == ["Paid", "Paid"]
        assert v["api_paid"]["total"] == 2 and v["api_confirmed"]["total"] == 0
        for s in v["api_list"]["items"] + v["api_one"]:
            assert s["status"] == "paid" and s["paid_at"] and "payment_incomplete" not in s, s
        assert v["week_slip_statuses"] == ["paid"]
        assert v["my_pay"]["owed"] == 0 and [s["status"] for s in v["my_pay"]["slips"]] == ["paid"]
        assert v["payroll_items"] == []
        assert sorted(r["net_salary"] for r in v["paid_labor_v3"]) == [300, 450]
        assert sorted({r["worker_id"] for r in v["paid_alloc_rows"]}) == ["emp-a1", "emp-a2"]
    run_c02(monkeypatch, scenario, backend)


def test_22_slip_of_another_tenant_never_resolves_a_run(monkeypatch, backend):
    """The parent run is looked up in the slip's own tenant only."""
    async def scenario(c, op):
        from app.services.slip_payment_state import effective_slips, paid_run_ids
        from app.tenancy.data_access import TenantData
        run_id = await _paid_run(c)
        tb = TenantData.for_resolved_org(op, ORG_B)
        assert await paid_run_ids(tb) == set()
        forged = [{"id": "x", "org_id": ORG_B, "pay_run_id": run_id, "status": "paid", "paid_at": "t"}]
        assert (await effective_slips(tb, forged))[0]["status"] == "confirmed"
    run_c02(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ R0-06-C03
# F-03: the A1 tenant-access guard covers slip_payment_state.py (it reads pay_runs).
# DB-free; modelled on tests/test_w0_03e_a1_static_guard.py.

SLIP_STATE = "app/services/slip_payment_state.py"
SLIP_ANCHOR = '    return set(await tenant.pay_runs.distinct("id", flt))'
BARE_READS = (
    '    leaked = await db.pay_runs.find({"status": "paid"}).to_list(None)\n',
    '    leaked = await db.pay_runs.distinct("id", {"status": "paid"})\n',
    '    leaked = await db["pay_runs"].find_one({"id": "x"})\n',
)


def _a1_guard():
    import sys
    from tests.test_r0_05_pay_run_selected_only import BACKEND
    sys.path.insert(0, str(BACKEND / "scripts"))
    import w0_03e_a1_tenant_access_guard as guard
    return guard, BACKEND


def _inject_bare(src, snippet):
    assert src.count(SLIP_ANCHOR) == 1
    return src.replace(SLIP_ANCHOR, snippet + SLIP_ANCHOR)


def test_23_a1_guard_covers_slip_payment_state():
    guard, backend = _a1_guard()
    assert SLIP_STATE in guard.HELPER_MODULES
    src = (backend / SLIP_STATE).read_text(encoding="utf-8")
    assert guard.check_source(src, SLIP_STATE, helper=SLIP_STATE in guard.HELPER_MODULES) == []


@pytest.mark.parametrize("snippet", BARE_READS)
def test_24_a1_guard_rejects_a_bare_pay_runs_read_in_slip_payment_state(snippet):
    guard, backend = _a1_guard()
    bad = _inject_bare((backend / SLIP_STATE).read_text(encoding="utf-8"), snippet)
    found = guard.check_source(bad, SLIP_STATE, helper=SLIP_STATE in guard.HELPER_MODULES)
    assert "A1-UNSCOPED" in {v[2] for v in found}, found


def test_25_a1_surface_scan_fails_on_the_injected_module(monkeypatch):
    """End to end: the whole-surface scan (what the script runs) reports the injected read."""
    from pathlib import Path
    guard, backend = _a1_guard()
    target = (backend / SLIP_STATE).resolve()
    bad = _inject_bare(target.read_text(encoding="utf-8"), BARE_READS[1])
    real_read = Path.read_text

    def read_text(self, *a, **kw):
        return bad if Path(self).resolve() == target else real_read(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", read_text)
    units, violations = guard.check_protected_surface()
    hits = [v for v in violations if v[0] == SLIP_STATE]
    assert hits and {v[2] for v in hits} == {"A1-UNSCOPED"}, violations


def test_26_a1_inventory_lists_both_slip_state_reads():
    _, backend = _a1_guard()
    doc = (backend.parent / "docs" / "architecture" / "W0-03E-A1_INVENTORY.md").read_text(encoding="utf-8")
    rows = [line for line in doc.splitlines() if line.startswith("| " + SLIP_STATE)]
    assert any("paid_run_ids" in r and "distinct" in r for r in rows), rows
    assert any("_run_statuses" in r and "find" in r for r in rows), rows
