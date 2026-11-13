"""AUDIT-2 probe (#83 FG-562 side effect): can an invoice's VAT number still be cleared with ""?"""
from tests.test_cp_01_counterparty_iban_egn import *  # noqa: F401,F403  (fixtures, run, hdr, rows)
from tests.test_cp_01_counterparty_iban_egn import run, hdr, rows


def test_probe_invoice_vat_cleared_with_empty_string(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.invoices.update_one({"id": "inv-r1"}, {"$set": {"counterparty_vat_no": "BG111111111"}})
        r = await c.put("/api/finance/invoices/inv-r1", headers=hdr("acct-a"),
                        json={"counterparty_vat_no": ""})
        stored = (await rows(op, "invoices", {"id": "inv-r1"}))[0].get("counterparty_vat_no")
        print("PROBE status=%s stored=%r" % (r.status_code, stored))
        assert r.status_code == 200, r.text
        assert stored in ("", None), stored
    run(monkeypatch, backend, mode, scenario)
