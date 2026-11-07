"""
PAY-01-C01-E — Codex review of #70 @ 31ed258 (CHANGES_REQUESTED), both P1:

  F-70-01  reversal and allocate were not serialised: with the reversal paused after its
           "no allocations" check, an allocate of 80 finished (200), then the reversal
           finished (200) → a REVERSED payment with an ACTIVE allocation of 80 (the invoice
           still paid 80). Now reversal, allocation-cancel, allocate and quick-pay share the
           payment lock (a transfer locks both legs, sorted); the loser gets 409 PAYMENT_BUSY.
  F-70-02  an interrupted reversal retried with the same key returned 200 with the reversal
           row repaired but NO ``finance.payment.reversed`` AuditEvent. Now recovery completes
           the canonical event too, exactly once (event identity = action + entity id),
           whatever step was interrupted. The same holds for ``finance.allocation.cancelled``.

The interleavings are real: one HTTP request is paused at a precise point (an asyncio.Event)
while the other runs to completion — no financial logic is replaced. Runs in
PERMISSION_SERVICE_MODE off / shadow / enforce, on mongomock and real MongoDB (replica set).
"""
import asyncio

import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    BANK_A, CASH_A, ORG_A, backend, hdr, mode, pay, quick_pay, reverse, run, snap,
)


def _pause(monkeypatch, module, name, *, times=1):
    """Pause the first ``times`` calls of module.name until ``proceed`` is set."""
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = getattr(module, name)
    left = {"n": times}

    async def paused(*args, **kwargs):
        if left["n"] > 0:
            left["n"] -= 1
            reached.set()
            await asyncio.wait_for(proceed.wait(), 10)
        return await original(*args, **kwargs)
    monkeypatch.setattr(module, name, paused)
    return reached, proceed


async def _active_allocs(op, pid):
    return await op.payment_allocations.find(
        {"payment_id": pid, "status": {"$ne": "cancelled"}}, {"_id": 0}).to_list(None)


async def _invariant(op, pid):
    """A reversed payment never keeps an active allocation; invoices agree with allocations."""
    payment = await op.finance_payments.find_one({"id": pid}, {"_id": 0})
    rows = await _active_allocs(op, pid)
    assert not (payment.get("status") == "reversed" and rows), (payment, rows)
    assert "allocation_lock" not in payment
    for inv in await op.invoices.find({}, {"_id": 0}).to_list(None):
        allocs = await op.payment_allocations.find(
            {"invoice_id": inv["id"], "status": {"$ne": "cancelled"}}, {"_id": 0}).to_list(None)
        assert round(inv.get("paid_amount", 0), 2) == round(sum(a["amount_allocated"] for a in allocs), 2), inv
        assert "allocation_lock" not in inv
    return payment, rows


# ═══════════════════════════════════════════════════════════ F-70-01: serialisation
def test_f70_01_reverse_paused_then_allocate_is_refused(monkeypatch, backend, mode):
    """The Codex probe: reversal paused right before it reverses; an allocate arrives."""
    async def scenario(c, op):
        from app.routes import finance
        pid = await pay(c, 100)
        reached, proceed = _pause(monkeypatch, finance, "_reverse_one")
        task = asyncio.create_task(reverse(c, pid, key="rev-race"))
        await asyncio.wait_for(reached.wait(), 10)
        alloc = await c.post("/api/finance/payments/%s/allocate" % pid, headers=hdr("acct-a", "alloc-race"),
                             json={"allocations": [{"invoice_id": "inv-a1", "amount": 80}]})
        proceed.set()
        rev = await task
        assert alloc.status_code == 409, alloc.text
        assert alloc.json()["detail"]["error_code"] == "PAYMENT_BUSY"
        assert rev.status_code == 200, rev.text
        payment, rows = await _invariant(op, pid)
        assert payment["status"] == "reversed" and rows == []
    run(monkeypatch, backend, mode, scenario)


def test_f70_01_allocate_paused_then_reverse_is_refused(monkeypatch, backend, mode):
    """The other order: allocate holds the lock (paused inside); the reversal is refused,
    the allocation lands; a later reversal is refused because the payment is allocated."""
    async def scenario(c, op):
        from app.routes import finance
        pid = await pay(c, 100)
        reached, proceed = _pause(monkeypatch, finance, "_invoice_remaining")
        task = asyncio.create_task(c.post("/api/finance/payments/%s/allocate" % pid,
                                          headers=hdr("acct-a", "alloc-first"),
                                          json={"allocations": [{"invoice_id": "inv-a1", "amount": 80}]}))
        await asyncio.wait_for(reached.wait(), 10)
        rev = await reverse(c, pid, key="rev-second")
        proceed.set()
        alloc = await task
        assert rev.status_code == 409 and rev.json()["detail"]["error_code"] == "PAYMENT_BUSY", rev.text
        assert alloc.status_code == 200, alloc.text
        rev2 = await reverse(c, pid, key="rev-third")
        assert rev2.status_code == 400, rev2.text               # unchanged rule: has allocations
        payment, rows = await _invariant(op, pid)
        assert payment.get("status") is None and [r["amount_allocated"] for r in rows] == [80]
    run(monkeypatch, backend, mode, scenario)


def test_f70_01_cancel_reversing_the_payment_vs_allocate(monkeypatch, backend, mode):
    """Cancelling the LAST allocation of a manual payment reverses it — paused right before
    that reversal, an allocate of the same payment to another invoice must be refused."""
    async def scenario(c, op):
        from app.routes import finance
        pid = await pay(c, 100)
        r = await c.post("/api/finance/payments/%s/allocate" % pid, headers=hdr("acct-a"),
                         json={"allocations": [{"invoice_id": "inv-a1", "amount": 30}]})
        assert r.status_code == 200, r.text
        al = r.json()["allocations"][0]["id"]
        reached, proceed = _pause(monkeypatch, finance, "_reverse_one")
        task = asyncio.create_task(c.request(
            "DELETE", "/api/finance/invoices/inv-a1/payments/" + al,
            json={"reason": "грешка"}, headers=hdr("acct-a", "cancel-race")))
        await asyncio.wait_for(reached.wait(), 10)
        alloc = await c.post("/api/finance/payments/%s/allocate" % pid, headers=hdr("acct-a", "alloc-race2"),
                             json={"allocations": [{"invoice_id": "inv-a2", "amount": 50}]})
        proceed.set()
        cancel = await task
        assert alloc.status_code == 409 and alloc.json()["detail"]["error_code"] == "PAYMENT_BUSY", alloc.text
        assert cancel.status_code == 200, cancel.text
        payment, rows = await _invariant(op, pid)
        assert payment["status"] == "reversed" and rows == []
    run(monkeypatch, backend, mode, scenario)


def test_f70_01_transfer_reversal_locks_both_legs(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.routes import finance
        r = await c.post("/api/finance/transfers", headers=hdr("acct-a"),
                         json={"from_account_id": BANK_A, "to_account_id": CASH_A, "amount": 50})
        assert r.status_code == 201, r.text
        legs = await op.finance_payments.find({"transfer_id": r.json()["transfer_id"]}, {"_id": 0}).to_list(None)
        assert len(legs) == 2
        reached, proceed = _pause(monkeypatch, finance, "_reverse_one")
        task = asyncio.create_task(reverse(c, legs[0]["id"], key="rev-transfer"))
        await asyncio.wait_for(reached.wait(), 10)
        for leg in legs:                                       # both legs are held
            row = await op.finance_payments.find_one({"id": leg["id"]}, {"_id": 0})
            assert "allocation_lock" in row, row
        other = await reverse(c, legs[1]["id"], key="rev-transfer-other")
        assert other.status_code == 409 and other.json()["detail"]["error_code"] == "PAYMENT_BUSY", other.text
        proceed.set()
        rev = await task
        assert rev.status_code == 200, rev.text
        for leg in legs:
            row = await op.finance_payments.find_one({"id": leg["id"]}, {"_id": 0})
            assert row["status"] == "reversed" and "allocation_lock" not in row
        assert await op.finance_payments.count_documents({"status": "reversal"}) == 2
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ F-70-02: recovery + audit
def _fail_once(monkeypatch, module, name):
    original = getattr(module, name)
    state = {"armed": True}

    async def flaky(*args, **kwargs):
        if state["armed"]:
            state["armed"] = False
            raise RuntimeError("synthetic interruption in %s" % name)
        return await original(*args, **kwargs)
    monkeypatch.setattr(module, name, flaky)


def _fail_after(monkeypatch, module, name):
    """The step itself completes, then the request is interrupted."""
    original = getattr(module, name)
    state = {"armed": True}

    async def flaky(*args, **kwargs):
        result = await original(*args, **kwargs)
        if state["armed"]:
            state["armed"] = False
            raise RuntimeError("synthetic interruption after %s" % name)
        return result
    monkeypatch.setattr(module, name, flaky)


# where the first attempt is interrupted
INTERRUPTIONS = {
    "before_reversal_row": ("_ensure_reversal_row", _fail_once),
    "after_reversal_row": ("_ensure_reversal_row", _fail_after),
    "before_audit": ("_reversal_audit", _fail_once),
    "after_audit": ("_reversal_audit", _fail_after),
    "before_key_complete": ("_complete", _fail_once),
}


@pytest.mark.parametrize("point", sorted(INTERRUPTIONS))
def test_f70_02_interrupted_reversal_recovers_row_and_audit_exactly_once(monkeypatch, backend, mode, point):
    async def scenario(c, op):
        from app.routes import finance
        pid = await pay(c, 100)
        name, how = INTERRUPTIONS[point]
        how(monkeypatch, finance, name)
        with pytest.raises(RuntimeError):
            await reverse(c, pid, key="crash-" + point)
        r = await reverse(c, pid, key="crash-" + point)          # the client retries the same request
        assert r.status_code == 200, r.text
        assert await op.finance_payments.count_documents({"reverses_payment_id": pid}) == 1
        assert await op.audit_events.count_documents(
            {"action": "finance.payment.reversed", "entity_id": pid}) == 1, point
        orig = await op.finance_payments.find_one({"id": pid}, {"_id": 0})
        assert orig["status"] == "reversed" and "allocation_lock" not in orig
        # and a replay of the now completed key changes nothing
        before = await snap(op)
        r2 = await reverse(c, pid, key="crash-" + point)
        assert r2.status_code == 200 and r2.json() == r.json()
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("point", ["before_cancel_audit", "after_cancel_audit"])
def test_f70_02_interrupted_allocation_cancel_records_its_audit_exactly_once(monkeypatch, backend, mode, point):
    """The same rule for ``finance.allocation.cancelled`` (and the reversal it triggers)."""
    async def scenario(c, op):
        from app.routes import finance
        res = await quick_pay(c, "inv-a1", 30.0)
        al, pid = res["allocation_id"], res["payment_id"]
        original = finance._audit_once
        state = {"armed": True}

        async def flaky(user, action, *args, **kwargs):
            if state["armed"] and action == "finance.allocation.cancelled":
                state["armed"] = False
                if point == "after_cancel_audit":
                    await original(user, action, *args, **kwargs)
                raise RuntimeError("synthetic interruption around the cancel audit")
            return await original(user, action, *args, **kwargs)
        monkeypatch.setattr(finance, "_audit_once", flaky)
        url = "/api/finance/invoices/inv-a1/payments/" + al
        with pytest.raises(RuntimeError):
            await c.request("DELETE", url, json={"reason": "грешка"}, headers=hdr("acct-a", "crash-c-" + point))
        r = await c.request("DELETE", url, json={"reason": "грешка"}, headers=hdr("acct-a", "crash-c-" + point))
        assert r.status_code == 200, r.text
        assert await op.audit_events.count_documents(
            {"action": "finance.allocation.cancelled", "entity_id": al}) == 1
        assert await op.audit_events.count_documents(
            {"action": "finance.payment.reversed", "entity_id": pid}) == 1
        assert await op.finance_payments.count_documents({"reverses_payment_id": pid}) == 1
        await _invariant(op, pid)
    run(monkeypatch, backend, mode, scenario)
