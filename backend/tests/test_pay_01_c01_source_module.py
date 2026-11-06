"""
PAY-01-C01 Addendum A — FLOW Guard FG-45: a payment owned by another module is not
reversed in Finance.

A ``finance_payments`` row written by Pay Run (salary), hr (advance / loan / loan
repayment) or subcontractors must be reversed in that module, or the module's register
and the Payment ledger diverge (FLOW-006). Until the module has its own reversal:

  * ``DELETE /finance/payments/{id}`` → 409 ``SOURCE_MODULE_REVERSAL_REQUIRED``, nothing
    written (no row, no AuditEvent, no idempotency key);
  * cancelling the LAST active allocation of such a payment (which would reverse it)
    → the same 409, nothing written;
  * a manual (finance-owned) payment is reversed exactly as before.

The seeded rows copy the fields each module writes on this branch; ``test_markers_*``
fails if a module stops writing the field the rule reads.

Runs in PERMISSION_SERVICE_MODE off / shadow / enforce, on mongomock and, when
``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB, on it as well.
"""
from pathlib import Path

import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    BANK_A, CASH_A, ORG_A, backend, hdr, mode, pay, reverse, run, snap,
)

NOW = "2026-11-06T10:00:00+00:00"


def _row(pid, **extra):
    row = {"id": pid, "org_id": ORG_A, "direction": "Outflow", "amount": 120.0, "currency": "EUR",
           "date": "2026-11-06", "method": "Cash", "account_id": CASH_A, "counterparty_name": "X",
           "reference": "", "note": "", "created_at": NOW, "updated_at": NOW}
    row.update(extra)
    return row


# The exact shapes written by the source modules (see the module paths in each comment).
SOURCE_ROWS = {
    # app/routes/subcontractors.py — subcontractor payment → cash outflow
    "subcontractor": _row("fp-sub", reference="SP-0001", note="Подизпълнител/бригада плащане",
                          project_id="prj-1", subcontractor_payment_id="sp-1"),
    # app/routes/pay_runs.py _write_salary_outflows — one outflow per (run, employee)
    "pay_run": _row("fp-salary", reference="run-1", note="Заплата 7", category="Заплата",
                    user_id="emp-1"),
    # app/routes/hr.py create advance / loan
    "hr_advance": _row("fp-advance", note="Аванс · Иван", category="Аванс", user_id="emp-1"),
    "hr_loan": _row("fp-loan", note="Заем · Иван", category="Заем", user_id="emp-1"),
    # app/routes/hr.py loan repayment (Inflow)
    "hr_repayment": _row("fp-repay", direction="Inflow", note="Връщане на заем · Иван",
                         category="Връщане заем", user_id="emp-1"),
}
EXPECTED_MODULE = {"subcontractor": "subcontractor", "pay_run": "pay_run", "hr_advance": "hr_advance",
                   "hr_loan": "hr_advance", "hr_repayment": "hr_advance"}


@pytest.mark.parametrize("kind", sorted(SOURCE_ROWS))
def test_source_module_payment_reversal_is_409(monkeypatch, backend, mode, kind):
    async def scenario(c, op):
        row = dict(SOURCE_ROWS[kind])
        await op.finance_payments.insert_one(dict(row))
        before = await snap(op)
        for key in ("k-fg45-" + kind, None):
            r = await reverse(c, row["id"], key=key)
            assert r.status_code == 409, r.text
            d = r.json()["detail"]
            assert d["error_code"] == "SOURCE_MODULE_REVERSAL_REQUIRED"
            assert d["source_module"] == EXPECTED_MODULE[kind]
        assert await snap(op) == before                     # 0 rows, no audit, no key
        stored = await op.finance_payments.find_one({"id": row["id"]}, {"_id": 0})
        assert "status" not in stored                       # still active, untouched
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("kind", ["pay_run", "subcontractor", "hr_advance"])
def test_source_module_last_allocation_cancel_is_409(monkeypatch, backend, mode, kind):
    async def scenario(c, op):
        row = dict(SOURCE_ROWS[kind])
        await op.finance_payments.insert_one(dict(row))
        await op.payment_allocations.insert_one({
            "id": "al-" + kind, "org_id": ORG_A, "payment_id": row["id"], "invoice_id": "inv-a1",
            "amount_allocated": 50.0, "allocated_at": NOW})
        before = await snap(op)
        r = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/al-" + kind,
                            json={"reason": "грешка"}, headers=hdr("acct-a", "k-fg45a-" + kind))
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "SOURCE_MODULE_REVERSAL_REQUIRED"
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


def test_source_module_non_last_allocation_can_still_be_cancelled(monkeypatch, backend, mode):
    """Cancelling one of two allocations does not reverse the payment, so it is allowed."""
    async def scenario(c, op):
        row = dict(SOURCE_ROWS["pay_run"])
        await op.finance_payments.insert_one(dict(row))
        for al, inv in (("al-1", "inv-a1"), ("al-2", "inv-a2")):
            await op.payment_allocations.insert_one({
                "id": al, "org_id": ORG_A, "payment_id": row["id"], "invoice_id": inv,
                "amount_allocated": 50.0, "allocated_at": NOW})
        r = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/al-1",
                            json={"reason": "грешка"}, headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        assert r.json()["reversal"] is None
        stored = await op.finance_payments.find_one({"id": row["id"]}, {"_id": 0})
        assert "status" not in stored                       # the salary payment is not reversed
        r = await c.request("DELETE", "/api/finance/invoices/inv-a2/payments/al-2",
                            json={"reason": "грешка"}, headers=hdr("acct-a"))
        assert r.status_code == 409, r.text                 # now it would be the last one
    run(monkeypatch, backend, mode, scenario)


def test_manual_payment_is_still_reversed(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 80.0)
        r = await reverse(c, pid, key="k-fg45-manual")
        assert r.status_code == 200, r.text
        orig = await op.finance_payments.find_one({"id": pid}, {"_id": 0})
        assert orig["status"] == "reversed"
        assert await op.finance_payments.count_documents({"reverses_payment_id": pid}) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ pure rule
def test_source_module_rule():
    from app.services.payment_state import source_module
    for kind, row in SOURCE_ROWS.items():
        assert source_module(row) == EXPECTED_MODULE[kind], kind
    assert source_module({"pay_run_id": "r"}) == "pay_run"
    assert source_module({"advance_id": "a"}) == "hr_advance"
    for finance_owned in ({}, None, {"category": "Други", "is_expense": True},
                          {"category": "Други приход"}, {"is_funding": True},
                          {"transfer_id": "t", "method": "Transfer"}):
        assert source_module(finance_owned) is None, finance_owned


# ═══════════════════════════════════════════════════════════ module markers (static)
ROUTES = Path(__file__).resolve().parent.parent / "app" / "routes"


def test_markers_written_by_source_modules():
    sub = (ROUTES / "subcontractors.py").read_text(encoding="utf-8")
    assert '"subcontractor_payment_id": payment["id"]' in sub
    pr = (ROUTES / "pay_runs.py").read_text(encoding="utf-8")
    assert '"category": "Заплата"' in pr
    hr = (ROUTES / "hr.py").read_text(encoding="utf-8")
    assert '"category": type_label' in hr and 'type_label = "Заем" if is_loan else "Аванс"' in hr
    assert '"category": "Връщане заем"' in hr


# ═══════════════════════════════════════════════════════════ C01A-1: concurrency
RACE_ROUNDS = 10


def test_c01a1_concurrent_cancels_never_reverse_a_module_payment(monkeypatch, backend, mode):
    """Audit C01A-1: two CONCURRENT cancels of the two allocations of a "Заплата" payment.
    Before the fix both returned 200 and the salary payment ended up REVERSED. Now at most
    one cancel wins; the other gets 409 (SOURCE_MODULE_REVERSAL_REQUIRED or PAYMENT_BUSY);
    the payment is never reversed and keeps an active allocation."""
    import asyncio

    async def scenario(c, op):
        async def cancel(inv, al, key):
            return await c.request("DELETE", "/api/finance/invoices/%s/payments/%s" % (inv, al),
                                   json={"reason": "грешка"}, headers=hdr("acct-a", key))

        for i in range(RACE_ROUNDS):
            pid = "fp-race-%d" % i
            await op.finance_payments.insert_one(dict(SOURCE_ROWS["pay_run"], id=pid))
            for n, inv in ((1, "inv-a1"), (2, "inv-a2")):
                await op.payment_allocations.insert_one({
                    "id": "al-%d-%d" % (i, n), "org_id": ORG_A, "payment_id": pid, "invoice_id": inv,
                    "amount_allocated": 5.0, "allocated_at": NOW})
            r1, r2 = await asyncio.gather(cancel("inv-a1", "al-%d-1" % i, "k-race-%d-1" % i),
                                          cancel("inv-a2", "al-%d-2" % i, "k-race-%d-2" % i))
            codes = [r1.status_code, r2.status_code]
            assert codes.count(200) <= 1, (i, r1.text, r2.text)
            for r in (r1, r2):
                if r.status_code != 200:
                    assert r.status_code == 409, r.text
                    assert r.json()["detail"]["error_code"] in (
                        "SOURCE_MODULE_REVERSAL_REQUIRED", "PAYMENT_BUSY"), r.text
            stored = await op.finance_payments.find_one({"id": pid}, {"_id": 0})
            assert "status" not in stored, (i, stored)              # never reversed
            assert "allocation_lock" not in stored                  # the lock is always released
            assert await op.finance_payments.count_documents({"reverses_payment_id": pid}) == 0
            active = await op.payment_allocations.count_documents(
                {"payment_id": pid, "status": {"$ne": "cancelled"}})
            assert active >= 1, i
    run(monkeypatch, backend, mode, scenario)


def test_c01a1_reverse_one_refuses_a_module_payment_for_any_caller(monkeypatch, backend, mode):
    """The guard sits in the reversal path itself: calling it directly is refused too."""
    async def scenario(c, op):
        from fastapi import HTTPException
        from app.routes import finance as r_finance
        await op.finance_payments.insert_one(dict(SOURCE_ROWS["subcontractor"]))
        user = {"id": "acct-a", "org_id": ORG_A, "role": "Accountant", "email": "acct-a@pay01.example"}
        before = await snap(op)
        with pytest.raises(HTTPException) as e:
            await r_finance._reverse_one(r_finance._tenant(user), user, "fp-sub", "грешка", "k-direct")
        assert e.value.status_code == 409
        assert e.value.detail["error_code"] == "SOURCE_MODULE_REVERSAL_REQUIRED"
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


def test_c01a1_stale_lock_is_taken_over(monkeypatch, backend, mode):
    """A lock left by a crashed request (older than the stale limit) does not block forever."""
    async def scenario(c, op):
        row = dict(SOURCE_ROWS["pay_run"], allocation_lock={"token": "dead", "at": "2020-01-01T00:00:00+00:00"})
        await op.finance_payments.insert_one(row)
        for al, inv in (("al-s1", "inv-a1"), ("al-s2", "inv-a2")):
            await op.payment_allocations.insert_one({
                "id": al, "org_id": ORG_A, "payment_id": row["id"], "invoice_id": inv,
                "amount_allocated": 5.0, "allocated_at": NOW})
        r = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/al-s1",
                            json={"reason": "грешка"}, headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        stored = await op.finance_payments.find_one({"id": row["id"]}, {"_id": 0})
        assert "allocation_lock" not in stored and "status" not in stored
    run(monkeypatch, backend, mode, scenario)
