"""AUDIT-2 probe (#73 FG-718 scope): the advance link from the PROFORMA side.
A final invoice names an issued, unpaid proforma as its advance; then the PROFORMA is
cancelled. Expected: refused (it backs a final invoice) or the link released — never a final
invoice that keeps counting the advance of a cancelled proforma. Copy into backend/tests."""
import pytest
from tests.test_lab_01_r86_received_revenue import (  # noqa: F401
    ORG, PF, _final, _revenue, _token, backend, run)


@pytest.mark.parametrize("_", [0])
def test_probe_cancel_a_proforma_that_backs_a_final_invoice(monkeypatch, backend, _):
    async def scenario(c, op):
        await op.invoices.insert_one({"id": "pf-1", **PF, "invoice_no": "PF-1"})
        owner = _token("owner")
        r = await c.post("/api/finance/invoices", json=_final(advance_proforma_ids=["pf-1"]), headers=owner)
        assert r.status_code == 201, r.text
        fin = r.json()
        await op.invoices.update_one({"id": fin["id"]}, {"$set": {"status": "Sent"}})
        b, _ = await _revenue(c)
        print("PROBE before-cancel", {k: b.get("pnl", {}).get(k) for k in ("revenue", "awaiting_payment_net", "invoiced_net")})
        r = await c.post("/api/finance/invoices/pf-1/cancel", headers=owner)
        pf = await op.invoices.find_one({"id": "pf-1"}, {"_id": 0})
        f = await op.invoices.find_one({"id": fin["id"]}, {"_id": 0})
        a, _pnl = await _revenue(c)
        print("PROBE cancel-proforma status=%s pf.status=%s pf.used_by=%s final.advance=%s revenue=%s" % (
            r.status_code, pf.get("status"), pf.get("advance_used_by_invoice_id"),
            f.get("advance_proforma_ids"), {k: a.get("pnl", {}).get(k) for k in ("revenue", "awaiting_payment_net", "invoiced_net")}))
        stale = pf.get("status") == "Cancelled" and pf.get("advance_proforma_ids") is None \
            and "pf-1" in (f.get("advance_proforma_ids") or [])
        assert not stale, "a cancelled proforma still backs the final invoice"
    run(monkeypatch, scenario, backend)
