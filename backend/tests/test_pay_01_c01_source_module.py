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
