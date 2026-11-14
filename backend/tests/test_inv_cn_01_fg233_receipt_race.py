"""
INV-CN-01 FG-233 — a supplier receipt that names the INVOICE only (``invoice_id``, no
invoice line) and a cancel of that invoice are serialised through ONE lock document
(``invoice_lock:<org>:<invoice>``, written by both transactions): they can never both
commit; a receipt against an already cancelled invoice is refused (409 INVOICE_CANCELLED);
a cancel after such a receipt is 409 USE_CORRECTION. Real Mongo, off / shadow / enforce.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements import CanonicalAction
from app.services.warehouse_movements.errors import InvoiceCancelledError
from tests.test_warehouse_canonical_c22_all_reports_cutover import T, WH, _inp
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx
from tests.test_warehouse_canonical_c26l_l_all_paths_lock import MODES, OWNER, _prepare, _routes

pytest_plugins = ["tests.warehouse_canonical_conftest"]

INV = "inv-c26"
ACCOUNTANT = {**OWNER, "id": "u-fg233-acct", "role": "Accountant"}


async def _setup(canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.routes import finance
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    _routes(monkeypatch, client, db)
    monkeypatch.setattr(finance, "db", db)

    async def _no_audit(*a, **k):
        return None
    monkeypatch.setattr(finance, "log_audit", _no_audit)
    if "warehouse_ledger_counters" not in await db.list_collection_names():
        await db.create_collection("warehouse_ledger_counters")      # exists in every live tenant
    await db["invoices"].update_one({"id": INV}, {"$set": {
        "direction": "Received", "invoice_no": "INV-C26", "status": "Sent", "due_date": "2099-12-31",
        "currency": "EUR", "counterparty_eik": "175074752",
        "lines": [{"description": "Лепило", "line_total": 100}]}})
    return db, run, svc, finance


def _receipt_by_invoice(key):
    return _inp(CanonicalAction.RECEIVE_FROM_SUPPLIER, T, source=SUP, destination=WH,
                quantity=Decimal("2"), unit_value=Decimal("10"), invoice_id=INV, idempotency_key=key)


def _cancel(finance, key):
    return finance.cancel_invoice(INV, body={"reason": "въведена по грешка"}, reason=None,
                                  idempotency_key=key, user=ACCOUNTANT)


@pytest.mark.parametrize("mode", MODES)
async def test_fg233_receipt_after_cancel_is_refused(canonical_mongo_db, allow_always_gate,
                                                     monkeypatch, mode):
    db, run, svc, finance = await _setup(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    out = await _cancel(finance, "k-cancel-1")
    assert out["status"] == "Cancelled"
    with pytest.raises(InvoiceCancelledError):
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt_by_invoice("k-rcv-1"))
    assert await db["warehouse_transactions"].count_documents({"invoice_id": INV, "action": {"$exists": True}}) == 0


@pytest.mark.parametrize("mode", MODES)
async def test_fg233_cancel_after_receipt_by_invoice_id_is_409(canonical_mongo_db, allow_always_gate,
                                                              monkeypatch, mode):
    db, run, svc, finance = await _setup(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    await svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt_by_invoice("k-rcv-2"))
    lock = await db["warehouse_ledger_counters"].find_one({"_id": "invoice_lock:%s:%s" % (T, INV)})
    assert lock and lock["value"] >= 1                           # the receipt wrote the invoice lock
    with pytest.raises(HTTPException) as exc:
        await _cancel(finance, "k-cancel-2")
    assert (exc.value.status_code, exc.value.detail["error_code"]) == (409, "USE_CORRECTION")
    assert (await db["invoices"].find_one({"id": INV}))["status"] == "Sent"


@pytest.mark.parametrize("mode", MODES)
async def test_fg233_cancel_racing_a_receipt_never_both_commit(canonical_mongo_db, allow_always_gate,
                                                              monkeypatch, mode):
    db, run, svc, finance = await _setup(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    results = await asyncio.gather(
        _cancel(finance, "k-cancel-3"),
        svc.execute(_ctx(mode, "Owner"), db, run.coll, _receipt_by_invoice("k-rcv-3")),
        return_exceptions=True)
    cancelled = (await db["invoices"].find_one({"id": INV}))["status"] == "Cancelled"
    received = await db["warehouse_transactions"].count_documents(
        {"invoice_id": INV, "action": {"$exists": True}}) > 0
    assert cancelled != received, results                           # exactly one of the two
    loser = results[1] if cancelled else results[0]
    assert isinstance(loser, (InvoiceCancelledError, HTTPException)), results
