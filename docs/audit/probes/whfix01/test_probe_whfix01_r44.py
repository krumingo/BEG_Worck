"""CLAUDE AUDIT probe — #81 WH-FIX-01 A3 / Р44 (78c249d). Copy into backend/tests/; PAY-01
harness (mongomock, and real Mongo with W0_03_REAL_MONGO_URL), off / shadow / enforce.
  X5  sequence: line 100 % allocated → quick-pay 1200 → 201; THEN reallocate the line to 60 %
      → is the allocation of a paid supplier invoice still editable (Р44 bypass by order)?
  X6  race, deterministic: quick-pay reads "100 % allocated" (ensure_payable), the line is
      reallocated to 60 % and commits, then the payment writes → does the payment go through?
"""
from tests.test_wh_fix_01_a3_r44_allocation import INV, LINE, run  # noqa: F401
from tests.test_pay_01_payment_reversal import backend, hdr, mode  # noqa: F401
import tests.test_pay_01_payment_reversal as h


def _qp(c):
    return c.post(f"/api/finance/invoices/{INV}/payments", headers=hdr("acct-a"),
                  json={"amount": 1200.0, "method": "BankTransfer", "account_id": h.BANK_A})


def _realloc(c, qty=60):
    return c.post(f"/api/invoice-lines/{LINE}/allocate", headers=hdr("acct-a"), json={
        "allocations": [{"type": "project", "ref_id": "prj-1", "qty": qty}]})


def test_x5_pay_then_deallocate(monkeypatch, backend, mode):
    async def scenario(c, op):
        p = await _qp(c)
        r = await _realloc(c)
        line = await op.invoice_lines.find_one({"id": LINE})
        inv = await op.invoices.find_one({"id": INV})
        dq = await op.dq_issues.count_documents({"entity_id": INV, "status": "open"})
        ev = await op.audit_events.count_documents({"entity_id": LINE})
        print("X5 %s: quick-pay %s | reallocate to 60 after payment -> %s | DQ open %d, line AuditEvents %d | invoice status %s paid %s | line %s" % (
            mode, p.status_code, r.status_code, dq, ev, inv.get("status"), inv.get("paid_amount"),
            [(a.get("ref_id"), a.get("qty")) for a in line.get("allocations") or []]))
        assert p.status_code == 201
    run(monkeypatch, backend, mode, scenario, allocated=100)


def test_x6_payment_decided_on_a_stale_allocation(monkeypatch, backend, mode):
    from app.services import invoice_allocation as ia
    real = ia.ensure_payable
    box = {}

    async def scenario(c, op):
        async def paused(tenant, invoice, *a, **k):
            await real(tenant, invoice, *a, **k)            # passes: 100 %
            if "r" not in box:
                box["r"] = await _realloc(c)                 # the line drops to 60 % and commits
        monkeypatch.setattr(ia, "ensure_payable", paused)
        p = await _qp(c)
        line = await op.invoice_lines.find_one({"id": LINE})
        pays = await op.payment_allocations.count_documents({"invoice_id": INV})
        print("X6 %s: realloc during payment %s | payment %s %s | payment allocations %d | line %s" % (
            mode, box["r"].status_code, p.status_code, p.text[:100], pays,
            [(a.get("ref_id"), a.get("qty")) for a in line.get("allocations") or []]))
        paid_partial = p.status_code == 201 and box["r"].status_code == 200
        assert not paid_partial, "payment committed against an allocation that was no longer 100 %"
    run(monkeypatch, backend, mode, scenario, allocated=100)
