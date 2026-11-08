"""CLAUDE AUDIT probe — #84 INV-CN-01 (7446d85). Copy into backend/tests/; real Mongo RS
(W0_03_REAL_MONGO_URL), off / shadow / enforce. Reuses the PR's own harness.
  V1  lock matrix: an ISSUED and a SENT invoice — PUT invoice_no / kind / issue_date / ЕИК / name / vat / project,
      (total / subtotal are not InvoiceUpdate fields — ignored, never written)
      PUT /lines, DELETE → 409; notes / due_date → 200 (EDITABLE_AFTER_ISSUE).
  V2  ×10 cancel ∥ send on one issued invoice → exactly one wins; never Cancelled AND sent.
  V3  ×10 cancel ∥ quick-pay on one issued invoice → never Cancelled with an active payment.
  V4  ×10 refund 36 ∥ offset-approve 36 on the same credit balance 36 → Σ applied ≤ 36.
  V5  6 concurrent registrations of the SAME incoming supplier note number → 1 created, 5 × 409.
"""
import asyncio
import uuid

import pytest

from tests.test_inv_cn_01_credit_notes import (  # noqa: F401
    BANK_A, approve, code, draft, get_inv, hdr, issued, mode, note, quick_pay, run, sent)


@pytest.mark.parametrize("state", ["issued", "sent"])
def test_v1_lock_matrix(monkeypatch, mode, state):
    async def scenario(c, op):
        inv = await (issued(c) if state == "issued" else sent(c))
        url = "/api/finance/invoices/" + inv["id"]
        out = {}
        for field, val in (("invoice_no", "INV-9999"), ("kind", "Proforma"), ("issue_date", "2020-01-01"),
                           ("counterparty_eik", "131468980"), ("counterparty_name", "Друг ООД"),
                           ("vat_percent", 9.0), ("project_id", "prj-2")):
            r = await c.put(url, headers=hdr("acct-a"), json={field: val})
            out[field] = r.status_code
        r = await c.put(url + "/lines", headers=hdr("acct-a"), json={"lines": [
            {"description": "X", "unit": "m2", "qty": 1, "unit_price": 1}]})
        out["lines"] = r.status_code
        out["delete"] = (await c.delete(url, headers=hdr("acct-a"))).status_code
        ok = {}
        for field, val in (("notes", "бележка"), ("due_date", "2099-01-01")):
            ok[field] = (await c.put(url, headers=hdr("acct-a"), json={field: val})).status_code
        after = await op.invoices.find_one({"id": inv["id"]})
        print("V1 %s/%s: money fields %s | allowed %s | total %s cp %s lines %d" % (
            mode, state, out, ok, after.get("total"), after.get("counterparty_name"), len(after.get("lines") or [])))
        assert all(s in (409, 400, 422) for s in out.values()), out
        assert out["delete"] == 409
        assert after["total"] == inv["total"] and after["counterparty_name"] == inv["counterparty_name"]
        assert after["invoice_no"] == inv["invoice_no"] and after.get("issue_date") == inv.get("issue_date")
        assert len(after["lines"]) == len(inv["lines"])
    run(monkeypatch, mode, scenario)


@pytest.mark.parametrize("rep", range(10))
def test_v2_cancel_races_send(monkeypatch, mode, rep):
    async def scenario(c, op):
        inv = await issued(c)
        u = "/api/finance/invoices/%s/" % inv["id"]
        a, b = await asyncio.gather(
            c.post(u + "cancel", headers=hdr("acct-a"), json={"reason": "грешка"}),
            c.post(u + "send", headers=hdr("acct-a")))
        doc = await op.invoices.find_one({"id": inv["id"]})
        appr = "-"
        req = doc.get("cancellation_request") or {}
        if req.get("status") == "pending_approval":          # Р51: the cancel is a proposal
            r = await c.post(u + "cancel/approve", headers=hdr("owner-a"), json={"version": req["version"]})
            appr = (r.status_code, code(r)) if r.status_code != 200 else 200
            doc = await op.invoices.find_one({"id": inv["id"]})
        print("V2 %s/%d: cancel %s send %s | approve-pending %s | status %s sent_at %s" % (
            mode, rep, a.status_code, b.status_code, appr, doc.get("status"), bool(doc.get("sent_at"))))
        assert not (doc["status"] == "Cancelled" and doc.get("sent_at"))
    run(monkeypatch, mode, scenario)


@pytest.mark.parametrize("rep", range(10))
def test_v3_cancel_races_payment(monkeypatch, mode, rep):
    async def scenario(c, op):
        inv = await issued(c)
        a, b = await asyncio.gather(
            c.post("/api/finance/invoices/%s/cancel" % inv["id"], headers=hdr("acct-a"), json={"reason": "грешка"}),
            quick_pay(c, inv["id"], 10.0))
        doc = await op.invoices.find_one({"id": inv["id"]})
        appr = "-"
        req = doc.get("cancellation_request") or {}
        if req.get("status") == "pending_approval":
            r = await c.post("/api/finance/invoices/%s/cancel/approve" % inv["id"], headers=hdr("owner-a"),
                             json={"version": req["version"]})
            appr = (r.status_code, code(r)) if r.status_code != 200 else 200
            doc = await op.invoices.find_one({"id": inv["id"]})
        active = await op.payment_allocations.count_documents(
            {"invoice_id": inv["id"], "status": {"$nin": ["cancelled", "reversed"]}})
        print("V3 %s/%d: cancel %s pay %s | approve-pending %s | status %s active allocations %d" % (
            mode, rep, a.status_code, b.status_code, appr, doc.get("status"), active))
        assert not (doc["status"] == "Cancelled" and active)
    run(monkeypatch, mode, scenario)


@pytest.mark.parametrize("rep", range(10))
def test_v4_refund_races_offset_approval(monkeypatch, mode, rep):
    async def scenario(c, op):
        a = await sent(c)
        assert (await quick_pay(c, a["id"], 240.0)).status_code == 201
        n = (await note(c, a)).json()
        assert (await approve(c, n["id"])).status_code == 200            # credit balance 36
        b = await sent(c)
        off = (await c.post("/api/finance/offsets", headers=hdr("acct-a"), json={
            "source_invoice_id": a["id"], "target_invoice_id": b["id"], "amount": 36, "reason": "прихващане",
            # Р51 / FG-222 (71957db): legal basis + document + the source credit note
            "legal_basis": "чл. 103 ЗЗД", "file_id": "file_offset_1", "source_credit_note_id": n["id"]})).json()
        ref, app_ = await asyncio.gather(
            c.post("/api/finance/invoices/%s/refund" % a["id"], headers=hdr("acct-a"), json={
                "amount": 36.0, "reason": "връщане", "account_id": BANK_A, "method": "BankTransfer"}),
            c.post("/api/finance/offsets/%s/approve" % off["id"], headers=hdr("owner-a"), json={"version": 1}))
        refunded = sum(p["amount"] for p in await op.finance_payments.find({"refund_invoice_id": a["id"]}).to_list(None))
        offset = sum(o["amount"] for o in await op.invoice_offsets.find({"status": "approved"}).to_list(None))
        after = await get_inv(c, a["id"])
        print("V4 %s/%d: refund %s offset %s | refunded %s offset %s | credit_balance %s" % (
            mode, rep, ref.status_code, app_.status_code, refunded, offset, after.get("credit_balance")))
        assert refunded + offset <= 36.0 + 1e-9 and (after.get("credit_balance") or 0) >= -1e-9
    run(monkeypatch, mode, scenario)


def test_v5_duplicate_incoming_number_concurrent(monkeypatch, mode):
    async def scenario(c, op):
        bill = await sent(c, direction="Received")
        rs = await asyncio.gather(*(note(c, bill, number="CN-DUP",
                                          lines=[{"original_line_id": bill["lines"][0]["id"], "qty": 1}])
                                     for _ in range(6)))
        codes = sorted(r.status_code for r in rs)
        rows = await op.credit_debit_notes.count_documents({"number": "CN-DUP"})
        print("V5 %s: %s | rows %d" % (mode, codes, rows))
        assert rows == 1 and codes.count(201) == 1
    run(monkeypatch, mode, scenario)
