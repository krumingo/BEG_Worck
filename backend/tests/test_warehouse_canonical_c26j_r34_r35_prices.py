"""
5C-C26j — Р34 / Р35 (Крум 07.11.2026), package addendum J.

  * Р34: the warehousekeeper sees no money on rows towards projects
    (consumption, „фира", issue / acceptance to a project) — quantities only;
    the warehouse's own unit prices (Р32) stay.
  * Р35: SiteManager and Technician read the central warehouse — stock AND
    prices (no movements there, Р28): GET /central-stock in every mode.
  * Р35: per project and article bought 2+ times, the purchase price history
    (unit price, supplier, date), a FLAG for the same supplier at different
    prices and the best price — from the canonical receipts and the Path B
    invoice lines (no new registry). Finance roles everywhere; SiteManager /
    Technician on their in-date member projects; the keeper → 403.

Real Mongo (replica set); real company-scope grants.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.envelope import MovementState
from app.services.warehouse_movements.errors import PermissionDeniedError
from app.services.warehouse_movements.service import CommandService
from app.tenancy.guard import LegacyCompatContext
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PRJ, PROJECT, T, WH, _inp, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    OTHER_PROJECT, USER, _UserCtx, _loader, _member,
)
from tests.test_warehouse_canonical_c26e_r28_all_modes import _count, _ctx, _real

pytest_plugins = ["tests.warehouse_canonical_conftest"]

MODES = ["off", "shadow", "enforce"]
SUP_A = LocationKey(LocationType.SUPPLIER, "sup_a")
SUP_B = LocationKey(LocationType.SUPPLIER, "sup_b")
ROLE = {"site_manager": "SiteManager", "LEGACY_TECHNICIAN": "Technician",
        "warehouse": "Warehousekeeper", "owner": "Owner", "accountant": "Accountant",
        "LEGACY_VIEWER": "Viewer", "driver": "Driver"}


def _rctx(mode, role_id):
    if mode == "enforce":
        c = _UserCtx()
        c.mode = "enforce"
        return c
    return LegacyCompatContext({"id": USER, "org_id": T, "role": ROLE[role_id]}, mode=mode)


async def _setup(client, gate, db, monkeypatch, role_id, mode, *, member=True):
    from app.permissions import service as perm
    from app.routes import warehouse_canonical as cmd
    from app.routes import warehouse_canonical_queries as q
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, gate, db)
    # Article ITEM: sup_a @10 and @12 through the warehouse, sup_b @9 direct.
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP_A, destination=WH,
              quantity=Decimal("5"), unit_value=Decimal("10"))
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP_A, destination=WH,
              quantity=Decimal("5"), unit_value=Decimal("12"))
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP_B,
              destination=PRJ, quantity=Decimal("3"), unit_value=Decimal("9"))
    await run.consume("2")
    if member:
        await _member(db)
    monkeypatch.setattr(q, "db", db)
    monkeypatch.setattr(cmd, "db", db)
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real(role_id)))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    return run


# ═══════════════════════════════ Р34 ═══════════════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_r34_keeper_sees_no_money_on_project_rows(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, "warehouse", mode, member=False)
    ctx = _rctx(mode, "warehouse")
    hist = await q.read_history(item_id=ITEM, location_type=None, location_id=None,
                                project_id=None, since=None, until=None, limit=1000,
                                cursor_after=None, ctx=ctx)
    by_action = {}
    for r in hist["rows"]:
        by_action.setdefault(r["action"], []).append(r)
    # Warehouse receipts keep their prices (Р32) …
    assert all("unit_value" in r for r in by_action["receive_from_supplier"])
    # … every row towards a project shows quantities only (Р34).
    for action in ("dispatch_warehouse_to_project", "accept_project_delivery",
                   "receive_from_supplier_to_project", "consume_to_smr"):
        for r in by_action[action]:
            assert "unit_value" not in r and "layer_allocations" in r, action
            assert all("unit_value" not in la for la in r["layer_allocations"]), action
    assert hist["values_hidden"] is True
    project_stock = await q.read_stock(ITEM, location_type="project", location_id=PROJECT,
                                       state="free", ctx=ctx)
    assert "total_value" not in project_stock and project_stock["values_hidden"] is True
    wh = await q.read_stock(ITEM, location_type="central_warehouse", location_id="wh_1",
                            state="free", ctx=ctx)
    assert "values_hidden" not in wh


# ═══════════════════════════════ Р35 — central warehouse ═══════════════════════════════

@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("role_id,allowed", [
    ("site_manager", True), ("LEGACY_TECHNICIAN", True), ("warehouse", True),
    ("accountant", True), ("LEGACY_VIEWER", False), ("driver", False)])
async def test_r35_central_stock_with_prices(canonical_mongo_db, allow_always_gate,
                                             monkeypatch, mode, role_id, allowed):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, role_id, mode, member=False)
    if not allowed:
        with pytest.raises(HTTPException) as exc:
            await q.read_central_stock(ITEM, location_id="wh_1", state="free",
                                       ctx=_rctx(mode, role_id))
        assert exc.value.status_code == 403
        return
    stock = await q.read_central_stock(ITEM, location_id="wh_1", state="free",
                                       ctx=_rctx(mode, role_id))
    assert "values_hidden" not in stock
    assert Decimal(stock["quantity"]) == Decimal("0")      # all 10 went to the project


@pytest.mark.parametrize("mode", MODES)
async def test_r35_technician_reads_prices_but_cannot_move_in_the_warehouse(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, "LEGACY_TECHNICIAN", mode)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "enforce")
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP_A, destination=WH,
              quantity=Decimal("4"), unit_value=Decimal("7"))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    stock = await q.read_central_stock(ITEM, location_id="wh_1", state="free",
                                       ctx=_rctx(mode, "LEGACY_TECHNICIAN"))
    assert Decimal(stock["total_value"]) == Decimal("28")
    assert [l["unit_value"] for l in stock["layers"]] == ["7"]
    before = await _count(db)
    with pytest.raises(PermissionDeniedError):
        await CommandService(client).execute(
            _ctx(mode, "Technician"), db, run.coll, _inp(
                CanonicalAction.QUARANTINE_ENTRY, T, quantity=Decimal("1"), source=WH,
                destination=LocationKey(WH.location_type, WH.location_id,
                                        state=MovementState.QUARANTINE)))
    assert await _count(db) == before


# ═══════════════════════════════ Р35 — price history ═══════════════════════════════

async def _invoice(db, *, line_id, desc, qty, price, supplier, issue_date, linked=None):
    await db["invoices"].update_one(
        {"id": "inv-" + line_id},
        {"$set": {"id": "inv-" + line_id, "org_id": T, "direction": "Expense",
                  "counterparty_name": supplier, "issue_date": issue_date}},
        upsert=True)
    await db["invoice_lines"].insert_one({
        "id": line_id, "org_id": T, "invoice_id": "inv-" + line_id, "description": desc,
        "unit": "бр", "qty": qty, "unit_price": price, "line_total_ex_vat": qty * price,
        "allocations": [{"type": "project", "ref_id": PROJECT, "qty": qty}],
        "created_at": issue_date})


@pytest.mark.parametrize("mode", MODES)
async def test_r35_price_history_flags_same_supplier_different_prices(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, "owner", mode, member=False)
    # Path B: „Шпакловка" twice from „Строймаг" at 4 and 4.5; „Лепило" once.
    await _invoice(db, line_id="il-1", desc="Шпакловка", qty=2, price=4.0,
                   supplier="Строймаг", issue_date="2026-11-01")
    await _invoice(db, line_id="il-2", desc="шпакловка ", qty=1, price=4.5,
                   supplier="Строймаг", issue_date="2026-11-03")
    await _invoice(db, line_id="il-3", desc="Лепило", qty=1, price=9.0,
                   supplier="Строймаг", issue_date="2026-11-02")
    data = await q.read_price_history(project_id=PROJECT, ctx=_rctx(mode, "owner"))
    arts = {a["article"]: a for a in data["articles"]}
    item = arts[ITEM]
    assert sorted((p["supplier"], p["unit_price"]) for p in item["purchases"]) == \
        [("sup_a", "10"), ("sup_a", "12"), ("sup_b", "9")]
    assert item["flagged"] is True
    assert item["flags"] == [{"code": "SAME_SUPPLIER_DIFFERENT_PRICE", "supplier": "sup_a",
                              "prices": ["10", "12"], "min_price": "10", "max_price": "12"}]
    assert item["best_price"]["unit_price"] == "9" and item["best_price"]["supplier"] == "sup_b"
    sp = arts["desc:шпакловка"]
    assert sp["flagged"] is True and sp["best_price"]["unit_price"] == "4.0"
    assert "desc:лепило" not in arts                       # bought once
    assert data["flagged_articles"] == 2


@pytest.mark.parametrize("mode", MODES)
async def test_r35_price_history_counts_a_linked_invoice_line_once(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """A receipt that carries its invoice line is ONE purchase (FG-17)."""
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, "owner", mode, member=False)
    await _invoice(db, line_id="il-x", desc="Цимент", qty=3, price=9.0,
                   supplier="sup_b", issue_date="2026-11-04")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "enforce")
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP_B,
              destination=PRJ, quantity=Decimal("3"), unit_value=Decimal("9"),
              invoice_line_id="il-x")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    data = await q.read_price_history(project_id=PROJECT, ctx=_rctx(mode, "owner"))
    item = {a["article"]: a for a in data["articles"]}[ITEM]
    assert [p["source"] for p in item["purchases"]].count("invoice_line") == 0
    assert "desc:цимент" not in {a["article"] for a in data["articles"]}
    assert item["purchase_count"] == 4                    # 10, 12, 9, 9 (linked)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("role_id,member,allowed", [
    ("owner", False, True), ("accountant", False, True),
    ("site_manager", True, True), ("site_manager", False, False),
    ("LEGACY_TECHNICIAN", True, True), ("LEGACY_TECHNICIAN", False, False),
    ("warehouse", False, False), ("LEGACY_VIEWER", True, False)])
async def test_r35_price_history_rights(canonical_mongo_db, allow_always_gate, monkeypatch,
                                        mode, role_id, member, allowed):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, role_id, mode, member=member)
    if allowed:
        data = await q.read_price_history(project_id=PROJECT, ctx=_rctx(mode, role_id))
        assert data["articles"]
    else:
        with pytest.raises(HTTPException) as exc:
            await q.read_price_history(project_id=PROJECT, ctx=_rctx(mode, role_id))
        assert exc.value.status_code == 403


async def test_r35_price_history_is_tenant_scoped(canonical_mongo_db, allow_always_gate,
                                                  monkeypatch):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, "owner", "enforce", member=False)

    class _Other:
        tenant_id = org_id = "org_c22_other"
        user_id = USER
        mode = "enforce"
    from app.permissions import service as perm

    async def _owner(user_id, tenant_id):
        return _real("owner")
    monkeypatch.setattr(perm, "_load_assignments", _owner)
    data = await q.read_price_history(project_id=PROJECT, ctx=_Other())
    assert data["articles"] == [] and data["purchases_considered"] == 0
