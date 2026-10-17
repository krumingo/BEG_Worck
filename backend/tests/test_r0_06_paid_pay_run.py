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

Plus: a failure in the side effects after the transition leaves the run paid with
``paid_effects="failed"`` and a retry is refused — never a second payment.

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


# ═══════════════════════════════════════════════════════════════════ failure after the transition
def test_12_failed_side_effects_never_pay_twice(monkeypatch, backend):
    from app.routes import pay_runs

    async def boom(*a, **kw):
        raise RuntimeError("downstream sync down")

    async def scenario(c, op):
        run_id = await _create(c)
        monkeypatch.setattr(pay_runs, "sync_on_paid", boom)
        with pytest.raises(RuntimeError):
            await _mark_paid(c, run_id)
        pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
        assert pr["status"] == "paid" and pr["paid_effects"] == "failed"
        assert pr["paid_effects_error"] == "RuntimeError"
        before = await _snapshot(op)
        r = await _mark_paid(c, run_id)
        assert r.status_code == 409, r.text
        assert (await _reopen(c, run_id)).status_code == 409
        assert await _snapshot(op) == before
        assert await op.finance_payments.count_documents({}) == len(EXPECTED_OUTFLOWS)
    run(monkeypatch, scenario, backend)
