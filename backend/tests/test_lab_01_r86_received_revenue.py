"""R86 (Krum 14.11.2026, FG-565; changes R80 / FG-530): "Приход" on the project = only the
payments RECEIVED (in full or in installments) against issued documents, net of VAT. The
issued but unpaid amount is shown apart as "фактурирано, чака плащане". A proforma alone is
never revenue.

The source is the FLOW-006 Payment ledger: payments are made through the real quick-pay
endpoint (POST /api/finance/invoices/{id}/payments). The project aggregate, the project
P&L report, its monthly trend and the centralized project report read the one shared rule
(app.services.project_pnl.received_revenue).

Reuses the R62 harness (tests/test_lab_01_s_r62_one_labor_cost.py): the approved labor is 180.
"""
import pytest

from tests.test_lab_01_s_r62_one_labor_cost import ORG, P, _token, backend, run  # noqa: F401

INV = {"org_id": ORG, "project_id": P, "direction": "Issued", "kind": "Invoice", "currency": "EUR",
       "status": "Sent", "subtotal": 1000.0, "vat_amount": 200.0, "total": 1200.0, "paid_amount": 0,
       "invoice_no": "R86-1", "due_date": "2099-01-01"}


async def _pay(c, inv_id, amount, key, date="2026-11-10"):
    r = await c.post(f"/api/finance/invoices/{inv_id}/payments",
                     json={"amount": amount, "method": "BankTransfer", "date": date},
                     headers={**_token("acct"), "Idempotency-Key": key})
    assert r.status_code == 201, r.text
    return r.json()


async def _revenue(c):
    """The revenue as every project reader shows it (R86: one rule)."""
    from app.services.project_pnl import compute_project_pnl
    a = (await c.get(f"/api/projects/{P}/aggregate", headers=_token("owner"))).json()
    pnl = (await compute_project_pnl(ORG, P))["revenue"]
    return a, pnl


@pytest.mark.parametrize("_", [0])
def test_r86_issued_1000_paid_400_then_an_installment_to_700(monkeypatch, backend, _):
    """issued 1000 (net), paid 400 net → revenue 400, invoiced 1000; an installment → 700."""
    async def scenario(c, op):
        await op.invoices.insert_one({"id": "inv-r86", **INV})
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 0.0 == pnl["total_revenue"], (a["pnl"], pnl)   # issued, not paid
        assert a["pnl"]["invoiced_net"] == 1000.0 == pnl["invoiced_net"]
        assert a["pnl"]["awaiting_payment_net"] == 1000.0 == pnl["awaiting_payment_net"]

        await _pay(c, "inv-r86", 480.0, "r86-a")              # 480 gross = 400 net
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 400.0 == pnl["total_revenue"], (a["pnl"], pnl)
        assert a["pnl"]["invoiced_net"] == 1000.0 == pnl["invoiced_net"]
        assert a["pnl"]["awaiting_payment_net"] == 600.0 == pnl["awaiting_payment_net"]
        assert a["pnl"]["awaiting_payment_label"] == "Фактурирано, чака плащане"
        assert a["invoices"]["total"]["invoiced"] == 1200.0                         # issued, gross
        mat = a["materials"]["total"]["ex_vat"]
        assert a["pnl"]["profit"] == round(400.0 - 180.0 - mat, 2)

        await _pay(c, "inv-r86", 360.0, "r86-b")              # an installment: +300 net
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 700.0 == pnl["total_revenue"], (a["pnl"], pnl)
        assert a["pnl"]["awaiting_payment_net"] == 300.0
        # forbidden: the same payment retried (same key) is not received twice
        await _pay(c, "inv-r86", 360.0, "r86-b")
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 700.0 == pnl["total_revenue"]
        # the centralized project report reads the same rule
        cent = await c.get(f"/api/projects/{P}/centralized-reports/finance", headers=_token("owner"))
        assert cent.status_code == 200, cent.text
        assert cent.json()["finance"]["total_revenue"] == 700.0
        assert cent.json()["finance"]["invoiced_net"] == 1000.0
    run(monkeypatch, scenario, backend)


def test_r86_a_proforma_alone_is_never_revenue(monkeypatch, backend):
    async def scenario(c, op):
        await op.invoices.insert_one({"id": "pf-r86", **INV, "kind": "Proforma", "invoice_no": "PF-1"})
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 0.0 == pnl["total_revenue"], (a["pnl"], pnl)
        assert a["pnl"]["invoiced_net"] == 0.0 == pnl["invoiced_net"]
        assert a["pnl"]["awaiting_payment_net"] == 0.0
        assert a["invoices"]["total"]["proforma_future"] == 1200.0                   # shown apart
    run(monkeypatch, scenario, backend)


def test_r86_a_reversed_payment_is_no_longer_revenue_and_a_draft_or_a_supplier_invoice_never(
        monkeypatch, backend):
    """A payment reversed in the ledger (FLOW-006 §Корекции) drops out; a draft and a
    supplier (Received) invoice are never revenue, whatever their paid amount."""
    async def scenario(c, op):
        await op.invoices.insert_many([
            {"id": "inv-r86", **INV},
            {"id": "inv-d", **INV, "status": "Draft", "invoice_no": "D"},
            {"id": "inv-s", **INV, "direction": "Received", "status": "Paid", "paid_amount": 1200.0,
             "invoice_no": "S"}])
        paid = await _pay(c, "inv-r86", 600.0, "r86-r")
        a, _ = await _revenue(c)
        assert a["pnl"]["revenue"] == 500.0
        await op.finance_payments.update_one({"id": paid["payment_id"]}, {"$set": {"status": "reversed"}})
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 0.0 == pnl["total_revenue"], (a["pnl"], pnl)
        assert a["pnl"]["invoiced_net"] == 1000.0
    run(monkeypatch, scenario, backend)


def test_r86_the_monthly_trend_counts_the_payment_in_the_month_it_was_received(monkeypatch):
    from datetime import datetime, timezone

    async def scenario(c, op):
        from app.services.project_pnl import compute_pnl_trend
        await op.invoices.insert_one({"id": "inv-r86", **INV, "created_at": "2020-01-01T00:00:00"})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await _pay(c, "inv-r86", 480.0, "r86-t", date=today)
        trend = await compute_pnl_trend(ORG, P, months=2)
        assert trend[-1]["month"] == today[:7] and trend[-1]["revenue"] == 400.0, trend
        assert trend[0]["revenue"] == 0.0, trend
    run(monkeypatch, scenario)


# ═══════════════════════════════════════════════ FLOW Guard pass 67 (FG-695 / FG-696 / FG-698)

def test_fg695_an_overdue_invoice_is_issued_and_waits_for_payment(monkeypatch, backend):
    """FG-695: issued = every issued, not cancelled status — Overdue included."""
    async def scenario(c, op):
        await op.invoices.insert_many([
            {"id": "inv-s", **INV},
            {"id": "inv-o", **INV, "status": "Overdue", "subtotal": 100.0, "vat_amount": 20.0, "total": 120.0,
             "invoice_no": "R86-O", "due_date": "2020-01-01"},
            {"id": "inv-c", **INV, "status": "Cancelled", "invoice_no": "R86-C"}])
        a, pnl = await _revenue(c)
        assert a["pnl"]["invoiced_net"] == 1100.0 == pnl["invoiced_net"], (a["pnl"], pnl)
        assert a["pnl"]["awaiting_payment_net"] == 1100.0 == pnl["awaiting_payment_net"]
        assert a["invoices"]["total"]["unpaid"] == 1320.0                          # "чака плащане", gross
        assert a["pnl"]["revenue"] == 0.0
    run(monkeypatch, scenario, backend)


def test_fg696_every_reader_labelled_revenue_follows_r86(monkeypatch, backend):
    """FG-696 (interim default, Krum to confirm): "оперативен приход", /project-profit and
    /cash-vs-earned — фактурирано = issued, net, no proforma; получено = received, net."""
    from app.services.project_financial_results import compute_financial_results

    async def scenario(c, op):
        await op.invoices.insert_many([
            {"id": "inv-r86", **INV},
            {"id": "inv-o", **INV, "status": "Overdue", "subtotal": 100.0, "vat_amount": 20.0, "total": 120.0,
             "invoice_no": "R86-O"},
            {"id": "pf-r86", **INV, "kind": "Proforma", "invoice_no": "PF-1"}])
        await _pay(c, "inv-r86", 480.0, "fg696-a")                  # 400 net received
        await _pay(c, "pf-r86", 600.0, "fg696-p")                   # a proforma alone: never revenue
        fr = await compute_financial_results(ORG, P)
        assert fr["operating"]["earned_revenue"] == 400.0, fr["operating"]
        assert fr["operating"]["invoiced_revenue"] == 1100.0
        prof = await c.get(f"/api/project-profit/{P}", headers=_token("owner"))
        assert prof.status_code == 200, prof.text
        rv = prof.json()["revenue"]
        assert (rv["billed"], rv["collected"]) == (1100.0, 400.0), rv
        assert rv["billed_label"].startswith("Фактурирано") and rv["collected_label"].startswith("Получено")
        cve = await c.get(f"/api/cash-vs-earned/{P}", headers=_token("owner"))
        assert cve.status_code == 200, cve.text
        cv = cve.json()
        assert (cv["billed_revenue"], cv["collected_cash"]) == (1100.0, 400.0), cv
        assert cv["labels"] == {"billed": "Фактурирано (без ДДС, без проформа)",
                                "collected": "Получено (без ДДС, без проформа)"}
    run(monkeypatch, scenario, backend)


def test_fg698a_a_final_invoice_against_a_proforma_advance_counts_the_advance(monkeypatch, backend):
    """FG-698(a) (interim default, Krum to confirm): the advance received on a proforma
    counts as revenue once a final invoice names it, and reduces its "чака плащане"."""
    async def scenario(c, op):
        await op.invoices.insert_one({"id": "pf-r86", **INV, "kind": "Proforma", "invoice_no": "PF-1",
                                      "subtotal": 500.0, "vat_amount": 100.0, "total": 600.0})
        await _pay(c, "pf-r86", 600.0, "fg698-p")
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 0.0 == pnl["total_revenue"]              # a proforma alone
        await op.invoices.insert_one({"id": "inv-fin", **INV, "invoice_no": "R86-F",
                                      "advance_proforma_ids": ["pf-r86"]})
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 500.0 == pnl["total_revenue"], (a["pnl"], pnl)
        assert a["pnl"]["invoiced_net"] == 1000.0                              # the final invoice
        assert a["pnl"]["awaiting_payment_net"] == 500.0 == pnl["awaiting_payment_net"]
        await _pay(c, "inv-fin", 600.0, "fg698-f")                            # the rest
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 1000.0 and a["pnl"]["awaiting_payment_net"] == 0.0
    run(monkeypatch, scenario, backend)


def test_fg698b_an_outgoing_credit_note_refund_reduces_the_revenue(monkeypatch, backend):
    """FG-698(b) (interim default, Krum to confirm; the credit-note flow is #84): an active
    Outflow payment allocated to an issued CreditNote of the project reduces the revenue."""
    async def scenario(c, op):
        await op.invoices.insert_many([
            {"id": "inv-r86", **INV},
            {"id": "cn-1", **INV, "kind": "CreditNote", "invoice_no": "CN-1",
             "subtotal": 200.0, "vat_amount": 40.0, "total": 240.0}])
        await _pay(c, "inv-r86", 1200.0, "fg698-b")
        a, _ = await _revenue(c)
        assert a["pnl"]["revenue"] == 1000.0 and a["pnl"]["invoiced_net"] == 1000.0
        # the seeded refund (the #84 hook): a ledger Outflow allocated to the credit note
        await op.finance_payments.insert_one({"id": "pay-ref", "org_id": ORG, "direction": "Outflow",
                                              "amount": 240.0, "date": "2026-11-12", "account_id": "acc"})
        await op.payment_allocations.insert_one({"id": "al-ref", "org_id": ORG, "payment_id": "pay-ref",
                                                 "invoice_id": "cn-1", "amount_allocated": 240.0})
        a, pnl = await _revenue(c)
        assert a["pnl"]["revenue"] == 800.0 == pnl["total_revenue"], (a["pnl"], pnl)
        assert a["pnl"]["invoiced_net"] == 1000.0                              # a credit note is not invoiced
        # a reversed refund no longer reduces it
        await op.finance_payments.update_one({"id": "pay-ref"}, {"$set": {"status": "reversed"}})
        a, _ = await _revenue(c)
        assert a["pnl"]["revenue"] == 1000.0
    run(monkeypatch, scenario, backend)
