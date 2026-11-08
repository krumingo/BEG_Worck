"""
5C-C26l Addendum N — FLOW Guard FG-140 (high, proven) @ cba5306. FLOW-006 /
CLAUDE §7: an official invoice is not edited — corrections go through
correction / reversal.

invoice_lines.py checked Draft OUTSIDE the transaction and the line / header
writes carried no status condition: an edit racing send changed a Sent
invoice 120 → 240, and a Paid one 120 → 240 with remaining 0 → 120.

Fix (app/services/invoice_state.claim_invoice): every writer decides the
status IN its transaction and writes the invoice document with that status
as a CAS condition; send / delete are conditional updates. The loser gets 409
(INVOICE_NOT_DRAFT for a Draft-only writer), nothing written.

Here (real Mongo rs, off / shadow / enforce): edit ∥ send ×10, edit ∥ send
→ pay ×10, and the deterministic interleavings (the edit paused right after
its pre-transaction Draft check while the invoice is sent / paid).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import T
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL
from tests.test_warehouse_canonical_c26l_l_all_paths_lock import (
    MODES, OWNER, _prepare, _routes,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]

INV = "inv-c26"


async def _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """A Draft received invoice with line L (10 @10, VAT 20 %): total 120."""
    from app.models.invoice_lines import InvoiceLineUpdate  # noqa: F401
    from app.routes import finance
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    lines = _routes(monkeypatch, client, db)
    monkeypatch.setattr(finance, "db", db)

    async def _no_audit(*a, **k):
        return None
    monkeypatch.setattr(finance, "log_audit", _no_audit)
    await db["invoices"].update_one({"id": INV}, {"$set": {
        "direction": "Received", "invoice_no": "INV-C26", "due_date": "2099-12-31",
        "currency": "EUR", "lines": [{"description": "Лепило", "line_total": 100}]}})
    await db["financial_accounts"].insert_one({"id": "acc-c26", "org_id": T, "type": "Bank",
                                               "name": "Банка", "is_default": True})
    from app.tenancy.data_access import TenantData
    await lines.recalculate_invoice_totals(TenantData.for_resolved_org(db, T), INV)
    inv = await db["invoices"].find_one({"id": INV})
    assert (inv["status"], inv["total"]) == ("Draft", 120.0)
    return db, lines, finance


def _edit(lines, price=20):
    from app.models.invoice_lines import InvoiceLineUpdate
    return lines.update_invoice_line(IL, InvoiceLineUpdate(unit_price=price), user=OWNER)


def _pay(finance, amount):
    import uuid
    return finance.add_invoice_payment(INV, {"amount": amount, "method": "BankTransfer",
                                             "account_id": "acc-c26"}, user=OWNER,
                                       idempotency_key="k-" + uuid.uuid4().hex)   # PAY-01 (#70)


async def _header(db):
    return await db["invoices"].find_one({"id": INV}, {"_id": 0})


async def _assert_header_is_lines(db):
    rows = await db["invoice_lines"].find({"invoice_id": INV}).to_list(None)
    inv = await _header(db)
    sub = round(sum(r["line_total_ex_vat"] for r in rows), 2)
    vat = round(sum(r["vat_amount"] for r in rows), 2)
    assert (inv["subtotal"], inv["total"]) == (sub, round(sub + vat, 2)), inv


def _refused(r):
    return isinstance(r, HTTPException) and r.status_code in (400, 409)


# ═══════════════════════════ concurrent ═══════════════════════════

@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_fg140_edit_racing_send(canonical_mongo_db, allow_always_gate, monkeypatch,
                                      mode, rep):
    """Either the edit commits while Draft (sent at 240) or it is refused
    (sent at 120) — the invoice never changes after it was sent."""
    db, lines, finance = await _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    edit, sent = await asyncio.gather(_edit(lines), finance.send_invoice(INV, user=OWNER),
                                      return_exceptions=True)
    assert not isinstance(sent, Exception), sent
    assert not isinstance(edit, Exception) or _refused(edit), edit
    final = await _header(db)
    assert final["total"] == sent["total"]                  # unchanged after send
    assert final["total"] == (120.0 if isinstance(edit, Exception) else 240.0)
    await _assert_header_is_lines(db)
    await rebuild_from_ledger(db, tenant_id=T)
    assert (await _header(db))["total"] == sent["total"]


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
async def test_fg140_edit_racing_send_and_pay(canonical_mongo_db, allow_always_gate,
                                              monkeypatch, mode, rep):
    """Edit ∥ (send → pay the whole remaining): a paid invoice keeps the
    total it was paid at and remaining 0."""
    db, lines, finance = await _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)

    async def _send_and_pay():
        sent = await finance.send_invoice(INV, user=OWNER)
        paid = await _pay(finance, sent["remaining_amount"])
        return paid["invoice"]
    edit, paid = await asyncio.gather(_edit(lines), _send_and_pay(), return_exceptions=True)
    assert not isinstance(paid, Exception), paid
    assert not isinstance(edit, Exception) or _refused(edit), edit
    for i in range(2):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        final = await _header(db)
        assert (final["status"], final["remaining_amount"]) == ("Paid", 0), final
        assert final["total"] == paid["total"] == final["paid_amount"]
        await _assert_header_is_lines(db)


# ═══════════════════════════ deterministic interleavings ═══════════════════════════

def _pause_edit_after_its_draft_check(monkeypatch):
    """The edit task pauses right after its pre-transaction Draft check
    (its first invoices.find_one) — the window FG-140 proved."""
    from app.tenancy.data_access import TenantCollection
    reached, release = asyncio.Event(), asyncio.Event()
    real = TenantCollection.find_one
    done = set()

    async def find_one(self, *a, **kw):
        out = await real(self, *a, **kw)
        task = asyncio.current_task()
        if self.name == "invoices" and getattr(task, "pause_me", False) and task not in done:
            done.add(task)
            reached.set()
            await release.wait()
        return out
    monkeypatch.setattr(TenantCollection, "find_one", find_one)
    return reached, release


async def _paused_edit(lines):
    asyncio.current_task().pause_me = True
    return await _edit(lines)


@pytest.mark.parametrize("mode", MODES)
async def test_fg140_paused_edit_after_send_is_409(canonical_mongo_db, allow_always_gate,
                                                   monkeypatch, mode):
    db, lines, finance = await _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    reached, release = _pause_edit_after_its_draft_check(monkeypatch)
    edit = asyncio.create_task(_paused_edit(lines))
    await asyncio.wait_for(reached.wait(), 10)
    sent = await finance.send_invoice(INV, user=OWNER)
    release.set()
    with pytest.raises(HTTPException) as exc:
        await edit
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "INVOICE_NOT_DRAFT"
    final = await _header(db)
    assert (final["status"], final["total"]) == (sent["status"], 120.0)
    line = await db["invoice_lines"].find_one({"id": IL})
    assert (line["unit_price"], line["line_total_ex_vat"]) == (10.0, 100.0)


@pytest.mark.parametrize("mode", MODES)
async def test_fg140_paused_edit_after_payment_is_409(canonical_mongo_db, allow_always_gate,
                                                      monkeypatch, mode):
    """The proven repro: the paid invoice stays 120 / remaining 0 / Paid."""
    db, lines, finance = await _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    reached, release = _pause_edit_after_its_draft_check(monkeypatch)
    edit = asyncio.create_task(_paused_edit(lines))
    await asyncio.wait_for(reached.wait(), 10)
    await finance.send_invoice(INV, user=OWNER)
    await _pay(finance, 120.0)
    release.set()
    with pytest.raises(HTTPException) as exc:
        await edit
    assert exc.value.status_code == 409
    for i in range(2):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        final = await _header(db)
        assert (final["status"], final["total"], final["remaining_amount"],
                final["paid_amount"]) == ("Paid", 120.0, 0, 120.0), final


@pytest.mark.parametrize("mode", MODES)
async def test_fg140_send_and_delete_are_conditional(canonical_mongo_db, allow_always_gate,
                                                     monkeypatch, mode):
    """send / delete of an invoice that is no longer Draft → 409 at the
    write (the pre-check passed on a stale read), nothing written."""
    db, lines, finance = await _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    from app.tenancy.data_access import TenantCollection
    real_get = TenantCollection.get
    stale = await db["invoices"].find_one({"id": INV}, {"_id": 0})

    async def stale_get(self, record_id, *a, **kw):        # the pre-check sees Draft
        if self.name == "invoices" and not kw.get("session"):
            return dict(stale)
        return await real_get(self, record_id, *a, **kw)
    await finance.send_invoice(INV, user=OWNER)
    monkeypatch.setattr(TenantCollection, "get", stale_get)
    before = await _header(db)
    for call in (finance.send_invoice(INV, user=OWNER), finance.delete_invoice(INV, user=OWNER)):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "INVOICE_NOT_DRAFT"
    monkeypatch.setattr(TenantCollection, "get", real_get)
    assert await _header(db) == before


@pytest.mark.parametrize("mode", MODES)
async def test_fg140_claim_honours_the_pay01_invoice_lock(canonical_mongo_db, allow_always_gate,
                                                          monkeypatch, mode):
    """While a PAY-01 payment / allocation holds the invoice row lock
    (finance._invoice_lock), a claiming writer (here: cancel) gets 409
    INVOICE_BUSY and writes nothing; once released it proceeds."""
    from datetime import datetime, timezone
    from app.services.invoice_state import ROW_LOCK_FIELD
    db, lines, finance = await _invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await db["invoices"].update_one({"id": INV}, {"$set": {ROW_LOCK_FIELD: {
        "token": "t", "at": datetime.now(timezone.utc).isoformat()}}})
    before = await _header(db)
    with pytest.raises(HTTPException) as exc:
        await finance.cancel_invoice(INV, user=OWNER)
    assert exc.value.status_code == 409 and exc.value.detail["error_code"] == "INVOICE_BUSY"
    with pytest.raises(HTTPException) as exc:
        await _edit(lines)
    assert exc.value.status_code == 409 and exc.value.detail["error_code"] == "INVOICE_BUSY"
    assert await _header(db) == before
    await db["invoices"].update_one({"id": INV}, {"$unset": {ROW_LOCK_FIELD: ""}})
    out = await finance.cancel_invoice(INV, user=OWNER)
    assert out["status"] == "Cancelled"
