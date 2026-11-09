"""CLAUDE AUDIT probe — #82 WH-REV-01 after the merge of main 1525a1e (#81), head e07320d.
Copy into backend/tests/; real Mongo RS (MONGO_URL with replicaSet,
WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1); off / shadow / enforce. Reuses the PR's harness.
  L1  A procurement supplier invoice holds line IL. A canonical receipt names IL, so #81's
      FG-157 lock refuses an edit of the invoice lines (409 SUPPLIER_INVOICE_LINKED). The
      receipt is then REVERSED (WH-REV-01). Does the supplier invoice unlock (the open
      condition from the #81 / #82 audits: procurement._supplier_invoice_link must skip
      reversed receipts)?
"""
import pytest
from fastapi import HTTPException

from tests.test_wh_rev_01_receipt_reversal import (  # noqa: F401
    IL, MODES, ONLY_P, T, WH, _book, _prepare, _reverse, _wc)
from tests.test_wh_fix_01_post_55 import _patch_all, _user

pytest_plugins = ["tests.warehouse_canonical_conftest"]


@pytest.mark.parametrize("mode", MODES)
async def test_l1_reversed_receipt_unlocks_the_supplier_invoice(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    client, db, run, svc = await _prepare(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, allocations=ONLY_P)
    wc = _wc(monkeypatch, client, db)
    _patch_all(monkeypatch, db)
    await db["supplier_invoices"].insert_one({
        "id": "si-rev", "org_id": T, "status": "reviewed", "vat_percent": 20,
        "updated_at": "2026-11-01T00:00:00+00:00",
        "lines": [{"id": IL, "material_name": "Лепило", "qty": 10, "unit_price": 10,
                   "total_price": 100}], "subtotal": 100, "total": 120})
    from app.routes import procurement

    async def edit(price):
        try:
            await procurement.update_supplier_invoice("si-rev", {"lines": [
                {"id": IL, "material_name": "Лепило", "qty": 10, "unit_price": price}]}, user=_user())
            return 200, None
        except HTTPException as exc:
            return exc.status_code, (exc.detail or {}).get("error_code") if isinstance(exc.detail, dict) else exc.detail

    receipt = await _book(svc, mode, db, run, WH)
    before = await edit(7)
    out = await _reverse(wc, mode, receipt)
    after = await edit(8)
    inv = await db["supplier_invoices"].find_one({"id": "si-rev"}, {"_id": 0})
    print("L1 %s: before reversal %s | reversal %s | after reversal %s | stored unit_price %s" % (
        mode, before, out.envelope["action"], after, inv["lines"][0]["unit_price"]))
    assert before[0] == 409, before                     # the #81 lock works
    assert after[0] == 200, "the supplier invoice stays locked after its receipt was reversed: %s" % (after,)
