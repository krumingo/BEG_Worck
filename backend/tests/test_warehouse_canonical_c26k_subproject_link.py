"""
5C-C26k — Codex F-55-C26-01 [P1] (#55 comment 6705319837): a direct delivery
into a SUBPROJECT that carries its invoice line was counted twice (canonical
100 + the whole linked line 100 = 200) on 10 project reports, live and after
rebuild ×2, because path_b_split compared the subproject's id with the
project's id. The link now matches on the movement's server-bound parent
project (FG-38).

Codex's exact reproduction, plus unlinked (two lots, summed) and partial
(the canon covers only its quantity) direct-to-subproject cases, each on all
project-level reports, live and after rebuild ×2. Real Mongo (replica set).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    PROJECT, T, _all_reports, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP, _Run
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL, _invoice_line, _project_level

pytest_plugins = ["tests.warehouse_canonical_conftest"]

SUB = "codex-sub"


async def _numbers(run):
    c = await run.cost()
    return (c["total_cost"], c["invoice_cost"], c["invoice_linked_excluded_cost"],
            _project_level(await _all_reports()))


@pytest.mark.parametrize("case,qty,linked,total,invoice,excluded", [
    # Codex's reproduction: L 10@10 to P; 10@10 into S with invoice_line_id=L.
    ("linked_full", "10", True, 100.0, 0.0, 100.0),
    # Partial: only 4 of L came through the canon into S; 6 stay Path B.
    ("linked_partial", "4", True, 100.0, 60.0, 40.0),
    # No link: two different lots, summed (FG-17).
    ("unlinked", "10", False, 200.0, 100.0, 0.0),
])
@pytest.mark.parametrize("subproject", [True, False])
async def test_f55_c26_01_direct_delivery_into_a_subproject_counts_once(
        canonical_mongo_db, allow_always_gate, monkeypatch,
        case, qty, linked, total, invoice, excluded, subproject):
    """1b3f182 (subproject, linked_full): 200 / invoice 100 / excluded 0 on
    10 reports, before and after rebuild ×2. The project/P control already
    gave 100."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["invoices"].insert_one({"id": "inv-c26", "org_id": T, "direction": "Expense",
                                     "status": "Approved", "issue_date": "2026-11-01",
                                     "counterparty_name": "Review supplier"})
    await _invoice_line(db)                                   # L: 10 @10 → P
    run = _Run(client, allow_always_gate, db)
    dest = LocationKey(LocationType.PROJECT, PROJECT)
    if subproject:
        await db["projects"].insert_one({"id": SUB, "org_id": T, "parent_project_id": PROJECT,
                                         "status": "Active"})
        dest = LocationKey(LocationType.SUBPROJECT, SUB)
    kw = {"invoice_line_id": IL} if linked else {}
    res = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP,
                    destination=dest, quantity=Decimal(qty), unit_value=Decimal("10"), **kw)
    assert res.envelope["project_id"] == PROJECT
    want_total = total if qty == "10" or not linked else total
    seen = []
    for i in range(3):                                         # live, rebuild ×2
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        got_total, got_invoice, got_excluded, reports = await _numbers(run)
        assert got_total == pytest.approx(want_total), (case, i)
        assert got_invoice == pytest.approx(invoice), (case, i)
        assert got_excluded == pytest.approx(excluded), (case, i)
        assert len(reports) == 10
        assert reports == {k: pytest.approx(want_total) for k in reports}, (case, i, reports)
        seen.append((got_total, got_invoice, got_excluded))
    assert seen[0] == seen[1] == seen[2]
