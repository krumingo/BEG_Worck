"""AUDIT-2 probe (#82 R84): two successive returns on one paid supplier invoice open two
claims whose sum is the overpaid total — the second claims only the increment, and a
replay of either adds nothing. Copy into backend/tests (warehouse env, real Mongo)."""
import pytest
from tests.test_wh_rev_01_receipt_reversal import (  # noqa: F401
    MODES, WH, _book, _reverse, _pay, _sent_invoice, _claims, _claim_events)

pytest_plugins = ["tests.warehouse_canonical_conftest"]


@pytest.mark.parametrize("mode", MODES)
async def test_probe_r84_two_returns_claim_the_increment(canonical_mongo_db, allow_always_gate,
                                                        monkeypatch, mode):
    from tests.test_wh_rev_01_receipt_reversal import _wc
    from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
    from app.services.warehouse_movements.service import CommandService
    db, finance = await _sent_invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    client = db.client
    run, svc, wc = _Run(client, allow_always_gate, db), CommandService(client), _wc(monkeypatch, client, db)
    r1 = await _book(svc, mode, db, run, WH, qty="2", key="k-b1")
    r2 = await _book(svc, mode, db, run, WH, qty="2", key="k-b2")
    await _pay(finance, 120.0, "k-pay-full")          # invoice 120 fully paid
    await _reverse(wc, mode, r1, key="k-r1")          # credit 24 → overpaid 24
    await _reverse(wc, mode, r2, key="k-r2")          # credit 48 → overpaid 48, claimed 24 → +24
    await _reverse(wc, mode, r2, key="k-r2")          # replay
    amounts = sorted(c["amount"] for c in await _claims(db))
    print("PROBE R84-two", mode, amounts, await _claim_events(db))
    assert amounts == [24.0, 24.0], amounts
    assert await _claim_events(db) == 2
