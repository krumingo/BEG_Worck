# INV-CN-01 — trial merge of this branch (Addendum D head 07323a7) + PR #82 @ 1622f62 (WH-REV-01)
# conflicts: finance.py (Р51(2) unapproved-debit check + #82 _awaited_credit cap: KEEP BOTH), service.py (FG-233 _lock_invoice + #82 _expect_credit_note: KEEP BOTH, each with its own @staticmethod), ownership.py (expected_credit_notes: one entry), generated files (regenerate)
# real Mongo mongo:7.0 rs0, WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1
PYTHONPATH=. pytest --noconftest -q -p no:cacheprovider tests/test_inv_cn_01_credit_notes.py tests/test_inv_cn_01_fg233_receipt_race.py tests/test_wh_rev_01_receipt_reversal.py tests/test_inv_cn_01_r52_d8_trial_merge_pr82.py -rs
239 passed, 5 warnings in 120.06s (0:02:00)

# the trial-merge-only test (needs #82's canonical reversal; the registrant is the Accountant, Р55(2)) — commit it with whichever of #82 / #84 merges second:
```python
"""
INV-CN-01 Addendum B / Р52(1) (D8) — on the TRIAL MERGE with PR #82 only (it needs #82's
canonical receipt reversal). A real receipt is reversed by #82 → the invoice awaits a
credit; the supplier's credit note LINKED to that reversal reduces the payable (the cap
is lifted) and has NO second effect on the project's cost; a credit WITHOUT a reversal
(defect) reduces the project cost once. Real Mongo, off / shadow / enforce.
"""
from __future__ import annotations

import pytest

from tests.test_warehouse_canonical_c22_all_reports_cutover import PROJECT, T, WH
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL
from tests.test_warehouse_canonical_c26l_l_all_paths_lock import MODES, OWNER
from tests.test_wh_rev_01_receipt_reversal import _book, _pay, _reverse, _sent_invoice, _wc

pytest_plugins = ["tests.warehouse_canonical_conftest"]

ACCOUNTANT = {**OWNER, "id": "u-d8-acct", "role": "Accountant"}       # Р55(2): the registrant


@pytest.mark.parametrize("mode", MODES)
async def test_r52_d8_linked_credit_after_a_real_reversal_has_no_second_cost_effect(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.routes import invoice_corrections as corr
    from app.services import project_pnl
    from app.services.warehouse_movements.service import CommandService
    from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
    db, finance = await _sent_invoice(canonical_mongo_db, allow_always_gate, monkeypatch, mode)
    monkeypatch.setattr(project_pnl, "db", db)
    client = db.client
    run, svc, wc = _Run(client, allow_always_gate, db), CommandService(client), _wc(monkeypatch, client, db)
    receipt = await _book(svc, mode, db, run, WH, qty="4")
    await _reverse(wc, mode, receipt)                                   # #82: awaits a credit of 48
    ecn = (await finance.list_expected_credit_notes(user=OWNER))[0]
    assert ecn["amount"] == 48.0
    before = await project_pnl.compute_project_pnl(T, PROJECT)
    note = await corr.create_note(body={
        "kind": "credit", "original_invoice_id": "inv-c26", "number": "CN-REV-1",
        "expected_credit_note_ids": [ecn["id"]], "reason": "сторно на доставка",
        "lines": [{"original_line_id": IL, "qty": 4}]}, user=ACCOUNTANT, idempotency_key="k-cn-1")
    assert (note["gross"], note["applied"], note["expected_link"]["matched"]) == (48.0, True, True)
    linked = await project_pnl.compute_project_pnl(T, PROJECT)
    assert linked["expense"]["material_cost"] == before["expense"]["material_cost"]   # no 2nd effect
    assert linked["expense"]["supplier_notes_cost_reduction"] == 0.0
    inv = await db["invoices"].find_one({"id": "inv-c26"})
    assert (inv["remaining_amount"], inv["awaiting_credit_note"]) == (72.0, False)
    await _pay(finance, 72.0, "k-pay-72")                               # the #82 cap is lifted
    # a defect credit WITHOUT a reversal → the original line's project cost, once
    await corr.create_note(body={
        "kind": "credit", "original_invoice_id": "inv-c26", "number": "CN-DEF-1",
        "reason": "дефект", "lines": [{"original_line_id": IL, "qty": 1}]},
        user=ACCOUNTANT, idempotency_key="k-cn-2")
    defect = await project_pnl.compute_project_pnl(T, PROJECT)
    assert round(linked["expense"]["material_cost"] - defect["expense"]["material_cost"], 2) == 10.0
    assert defect["expense"]["supplier_notes_cost_reduction"] == 10.0
```
