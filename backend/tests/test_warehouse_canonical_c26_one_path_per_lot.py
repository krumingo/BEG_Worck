"""
5C-C26 — FG-17 without double counting between Path A and Path B.

Package: ``docs/architecture/tasks/5C-C26_FG17_ONE_PATH_PER_BATCH.md``
(FLOW-043 D-04; FLOW-009 „Разход по обект — без двойно броене": one lot can
never become project cost along both paths; Р13, Р17, Р21).

Path A — supplier → warehouse → project, cost at ACCEPT (Р17).
Path B — the quantity of a supplier invoice line allocated DIRECTLY to the
project. Rule (``canonical_material_cost.path_b_split``):
  1. only the quantity allocated directly to the project is Path B; a
     quantity allocated to a warehouse is Path A;
  2. a canonical supplier receipt that carries the invoice line
     (``invoice_line_id``) is the same lot — the canon wins for the
     quantity it covers; no link → different lots, summed;
  3. an overlap the data cannot prove → integrity warning, the sum is NOT
     changed silently.

Real Mongo (replica set). Each test names what d8923d7 returned.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.canonical_material_cost import (
    path_b_integrity_warnings, path_b_split,
)
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    BEFORE, PRJ, PROJECT, T, T2, WH, _all_reports, _assert_all, _legacy_issue,
    _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP, _Run

pytest_plugins = ["tests.warehouse_canonical_conftest"]

IL = "il-c26"


async def _invoice_line(db, *, line_id=IL, qty=10, value=100.0, unit="bag",
                        description="Лепило", tenant=T, deprecated=True,
                        allocations=None):
    """A supplier invoice line exactly as routes/invoice_lines stores it:
    the deprecated single allocation and/or ``allocations[]``."""
    row = {"id": line_id, "org_id": tenant, "invoice_id": "inv-c26", "line_no": 1,
           "description": description, "unit": unit, "qty": qty,
           "unit_price": value / qty if qty else value,
           "line_total_ex_vat": value, "vat_amount": round(value * 0.2, 2),
           "created_at": "2026-11-01T10:00:00+00:00", "allocations": allocations or []}
    if deprecated:
        row.update(allocation_type="project", allocation_ref_id=PROJECT)
    await db["invoice_lines"].insert_one(row)


def _project_level(reports):
    from tests.test_warehouse_canonical_c22_all_reports_cutover import PACKAGE_LEVEL
    return {k: v[0] for k, v in reports.items() if k not in PACKAGE_LEVEL}


def _all_equal(reports, total):
    """Every project-level report (P&L, summary, breakdown, material summary,
    project-profit, net-profit, financial results, centralized, period,
    baseline) shows ``total``."""
    level = _project_level(reports)
    assert level == {k: pytest.approx(total) for k in level}, level
    assert reports["pnl"][0] == pytest.approx(total)
    assert reports["net_profit"] == reports["pnl"]


# ═══════════════════════════ single paths ═══════════════════════════

async def test_path_b_only_100(canonical_mongo_db, allow_always_gate, monkeypatch):
    """Path B only: invoice line 10 × 10 allocated to the project → 100."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db)
    run = _Run(client, allow_always_gate, db)
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(100.0)
    assert cost["invoice_cost"] == pytest.approx(100.0)
    assert cost["path_b_warnings"] == []
    _all_equal(await _all_reports(), 100.0)


async def test_path_b_from_allocations_list_is_counted(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """A line allocated with ``allocations[]`` only (no deprecated field):
    6 to the project directly, 4 to the warehouse → Path B = 6 × 10 = 60.
    d8923d7: 0 (it read only the deprecated ``allocation_type``)."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db, deprecated=False, allocations=[
        {"type": "project", "ref_id": PROJECT, "qty": 6},
        {"type": "warehouse", "ref_id": "wh_1", "qty": 4}])
    run = _Run(client, allow_always_gate, db)
    cost = await run.cost()
    assert cost["invoice_cost"] == pytest.approx(60.0)
    assert cost["invoice_path_a_cost"] == pytest.approx(40.0)
    _all_equal(await _all_reports(), 60.0)


async def test_path_a_only_accept_50(canonical_mongo_db, allow_always_gate, monkeypatch):
    """Path A only: receive 10 @10, dispatch 5, accept 5 → 50. An invoice
    line allocated to the WAREHOUSE is Path A: it is never project cost."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db, line_id="il-wh", deprecated=False, allocations=[
        {"type": "warehouse", "ref_id": "wh_1", "qty": 10}])
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("5")
    await run.accept(disp, "5")
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(50.0)
    assert cost["invoice_cost"] == 0
    _all_equal(await _all_reports(), 50.0)


async def test_different_lots_a_plus_b_is_150(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Path B line 100 (no canonical receipt carries it) + Path A accept 50
    → two different lots, summed: 150; no warning."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("5")
    await run.accept(disp, "5")
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(150.0)
    assert cost["invoice_linked_excluded_cost"] == 0
    assert cost["path_b_warnings"] == []
    _all_equal(await _all_reports(), 150.0)


# ═══════════════════════════ overlap — one lot ═══════════════════════════

async def test_overlap_line_to_project_and_issue_from_the_same_line_is_100(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Legacy line (deprecated allocation to the project, 10 × 10) whose goods
    were received into the warehouse WITH the line (``invoice_line_id``) and
    then dispatched + accepted on the same project → ONE lot: 100, not 200.
    Rebuild ×2 changes nothing."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db)
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
              quantity=Decimal("10"), unit_value=Decimal("10"), invoice_line_id=IL)
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(100.0)
    assert cost["invoice_cost"] == 0
    assert cost["invoice_linked_excluded_cost"] == pytest.approx(100.0)
    assert cost["path_b_warnings"] == []
    before = await _all_reports()
    _all_equal(before, 100.0)
    await rebuild_from_ledger(db, tenant_id=T)
    await rebuild_from_ledger(db, tenant_id=T)
    assert await _all_reports() == before


async def test_overlap_stale_project_field_on_a_warehouse_allocated_line_is_100(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Legacy line first allocated to the project (deprecated field), then
    re-allocated to the warehouse with POST /invoice-lines/{id}/allocate —
    which replaces ``allocations[]`` only, the deprecated field stays. The
    goods went warehouse → project (Path A, accept 10 @10).
    d8923d7: 200 (the stale field made the whole line Path B too)."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db, allocations=[{"type": "warehouse", "ref_id": "wh_1", "qty": 10}])
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(100.0)
    assert cost["invoice_cost"] == 0
    assert cost["invoice_path_a_cost"] == pytest.approx(100.0)
    _all_equal(await _all_reports(), 100.0)


async def test_canon_wins_only_the_quantity_it_covers(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Line 10 × 10 allocated to the project; only 4 of it were received into
    the warehouse with the line (and accepted on the project); the other 6
    came straight to site. 40 (canon) + 60 (Path B) = 100.
    d8923d7: 40 (any reference excluded the whole line)."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db)
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
              quantity=Decimal("4"), unit_value=Decimal("10"), invoice_line_id=IL)
    disp = await run.dispatch("4")
    await run.accept(disp, "4")
    cost = await run.cost()
    assert cost["accepted_cost"] == pytest.approx(40.0)
    assert cost["invoice_cost"] == pytest.approx(60.0)
    assert cost["invoice_linked_excluded_cost"] == pytest.approx(40.0)
    assert cost["total_cost"] == pytest.approx(100.0)
    _all_equal(await _all_reports(), 100.0)


async def test_direct_delivery_of_the_line_counts_once(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Direct supplier delivery to the project that carries the line, 10 × 10:
    one lot, 100 (C25 probe kept, now quantity-exact)."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db)
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP,
              destination=PRJ, quantity=Decimal("10"), unit_value=Decimal("10"),
              project_id=PROJECT, invoice_line_id=IL)
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(100.0)
    assert cost["invoice_cost"] == 0
    _all_equal(await _all_reports(), 100.0)


async def test_link_is_tenant_scoped(canonical_mongo_db, allow_always_gate, monkeypatch):
    """Another tenant's receipt that names the same invoice line id proves
    nothing for this tenant: Path B stays 100."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db)
    other = _Run(client, allow_always_gate, db, tenant=T2)
    await other(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
                quantity=Decimal("10"), unit_value=Decimal("10"), invoice_line_id=IL)
    run = _Run(client, allow_always_gate, db)
    assert (await run.cost())["invoice_cost"] == pytest.approx(100.0)


# ═══════════════════ no provable link → warning, sum unchanged ═══════════════════

async def test_unprovable_legacy_overlap_warns_and_keeps_the_sum(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Pre-cutover legacy issue „Лепило" 100 + Path B line „Лепило" 100 on the
    same project. Legacy issues carry no invoice-line / lot reference, so the
    overlap cannot be proven: both stay counted (200 — what d8923d7 showed)
    and PATH_B_LEGACY_OVERLAP_UNPROVEN appears on the integrity-warnings
    screen (filtered by project scope)."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=100.0, created_at=BEFORE, txn_id="legacy-c26")
    await _invoice_line(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("1", "1")                 # the tenant cutover (Р13)
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(200.0)
    assert cost["legacy_cost"] == pytest.approx(100.0)
    assert cost["invoice_cost"] == pytest.approx(100.0)
    [w] = cost["path_b_warnings"]
    assert w["code"] == "PATH_B_LEGACY_OVERLAP_UNPROVEN"
    assert w["project_id"] == PROJECT and w["invoice_line_id"] == IL
    assert w["legacy_issue_ids"] == ["legacy-c26"]
    _all_equal(await _all_reports(), 200.0)

    # Visible on the existing integrity-warnings screen.
    from app.routes import warehouse_canonical_queries as q
    monkeypatch.setattr(q, "db", db)

    class _C:
        tenant_id = org_id = T
        user_id = "u-c26"

    async def _all_scope(ctx, user):
        return None
    monkeypatch.setattr(q, "_authorized_scope_locations", _all_scope)
    data = await q.read_integrity_warnings(ctx=_C())
    codes = [x["code"] for x in data["warnings"]]
    assert "PATH_B_LEGACY_OVERLAP_UNPROVEN" in codes

    async def _other_project(ctx, user):
        return [("project", "p-someone-else")]
    monkeypatch.setattr(q, "_authorized_scope_locations", _other_project)
    data = await q.read_integrity_warnings(ctx=_C())
    assert "PATH_B_LEGACY_OVERLAP_UNPROVEN" not in [x["code"] for x in data["warnings"]]
    # Tenant-wide helper (the same rows) and tenant isolation.
    assert [x["code"] for x in await path_b_integrity_warnings(run.tenant_data, T)] == \
        ["PATH_B_LEGACY_OVERLAP_UNPROVEN"]
    other = _Run(client, allow_always_gate, db, tenant=T2)
    assert await path_b_integrity_warnings(other.tenant_data, T2) == []


async def test_link_with_incomparable_unit_goes_to_the_canon_and_warns(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """The line is in „бр", the receipt in the master unit „bag": the link is
    proven but the quantities cannot be compared → the canon wins the whole
    project part (no double count) and PATH_B_LINK_QTY_UNVERIFIED says a
    remainder may be missing."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _invoice_line(db, unit="бр")
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP, destination=WH,
              quantity=Decimal("4"), unit_value=Decimal("10"), invoice_line_id=IL)
    disp = await run.dispatch("4")
    await run.accept(disp, "4")
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(40.0)
    assert [w["code"] for w in cost["path_b_warnings"]] == ["PATH_B_LINK_QTY_UNVERIFIED"]
    _all_equal(await _all_reports(), 40.0)


def test_path_b_split_rule_table():
    """The pure rule, case by case (no database)."""
    line = {"id": "L", "qty": 10, "unit": "bag", "line_total_ex_vat": 100.0,
            "allocations": [{"type": "project", "ref_id": "P", "qty": 6},
                            {"type": "project", "ref_id": "Q", "qty": 4}]}
    wh = {"action": "receive_from_supplier", "quantity": "10", "unit": "bag",
          "destination": {"location_type": "central_warehouse", "location_id": "w"}}
    # No link: P's 6 counted.
    assert path_b_split(line, "P", [])["counted_value"] == pytest.approx(60.0)
    # Warehouse receipts beyond the (zero) warehouse allocation, but the line
    # is split over two projects → ambiguous: unchanged + warning.
    s = path_b_split(line, "P", [wh])
    assert s["counted_value"] == pytest.approx(60.0)
    assert s["warning"] == "PATH_B_LINK_AMBIGUOUS"
    # Direct delivery of the line to P covers P exactly.
    direct = {"action": "receive_from_supplier_to_project", "quantity": "6",
              "unit": "bag", "destination": {"location_type": "project", "location_id": "P"}}
    assert path_b_split(line, "P", [direct])["counted_value"] == 0
    assert path_b_split(line, "Q", [direct])["counted_value"] == pytest.approx(40.0)
    # A non-receipt reference proves the link but not the quantity.
    disp = {"action": "dispatch_warehouse_to_project", "quantity": "1", "unit": "bag"}
    s = path_b_split(line, "P", [disp])
    assert s["counted_value"] == 0 and s["warning"] == "PATH_B_LINK_QTY_UNVERIFIED"
    # A project not in the allocations gets nothing.
    assert path_b_split(line, "Z", [])["counted_value"] == 0
