"""LIVE-OPS-01 / TASK 5C — 5C-C20: finance reports read the canonical material cost.

Package: ``docs/architecture/tasks/5C-C20_FINANCE_READS_CANONICAL.md``
(branch ``claude/happy-meitner-bmcnel``). Evidence:
``docs/evidence/BOT/5C-d8ac3a9/README.md`` (branch ``claude/bot-evidence``).

Bot scenario, no workaround: receive 10 @10 → dispatch 5 → accept 5 →
consume 3. Canonical project material cost = 30 (3 units), recognised once,
at consumption. On d8ac3a9:

  * F-9  — ``/projects/{id}/pnl``, ``/pnl/summary``, ``/pnl/breakdown`` showed
           material_cost 0 / total_expense 0 (read legacy issue lines only);
  * F-10 — the package reports (``/execution-packages/{id}/financial``,
           ``financial-breakdown``, ``net-financial``, by-execution-package)
           showed 0 until two manual POSTs (sync + recompute) were called;
  * F-11 — ``/project-material-ledger/{id}`` returned ``ledger: []``.

Every test here runs on a real replica set and calls NEITHER
``POST /material-entries/sync`` NOR ``POST /execution-packages/recompute-material``.

Run (real Mongo, required):
    WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 PERMISSION_SERVICE_MODE=enforce \\
    MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \\
    PYTHONPATH=. pytest -q tests/test_warehouse_canonical_c20_finance_reads.py
"""
from __future__ import annotations

import importlib
import os
import uuid
from decimal import Decimal

import pytest

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.service import CommandInput, CommandService
from app.tenancy.data_access import TenantData

pytest_plugins = ["tests.warehouse_canonical_conftest"]

T = "org_c20"
T2 = "org_c20_other"
PROJECT = "p-c20"
PKG = "pkg-c20"
ITEM = "item_c20"


class _Ctx:
    def __init__(self, tenant_id: str = T):
        self.tenant_id = tenant_id
        self.org_id = tenant_id
        self.user_id = "u-c20"


def _user(org=T):
    return {"id": "u-" + org, "org_id": org, "role": "Owner", "email": org + "@x"}


def _inp(action, tenant=T, **kw):
    base = dict(
        action=action, tenant_id=tenant, actor_id="u-c20", item_id=ITEM, unit="bag",
        quantity=kw.pop("quantity", Decimal("10")),
        idempotency_key=f"k-{uuid.uuid4().hex[:8]}",
    )
    base.update(kw)
    return CommandInput(**base)


def _patch_dbs(monkeypatch, db):
    """Point every module these readers use at the test database."""
    for name in ("app.routes.material_smr", "app.routes.full_cost",
                 "app.routes.revenue_expense", "app.routes.labor_smr",
                 "app.routes.subcontractors", "app.routes.procurement",
                 "app.routes.project_pnl", "app.services.project_pnl"):
        monkeypatch.setattr(importlib.import_module(name), "db", db)


async def _scenario(client, gate, db, tenant=T):
    """receive 10 @10 → dispatch 5 → accept 5 → consume 3 (the bot flow)."""
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    coll = TenantData.for_resolved_org(db, tenant).warehouse_transactions
    svc = CommandService(client, gate=gate)
    ctx = _Ctx(tenant)
    await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("10"), unit_value=Decimal("10")))
    disp = await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant,
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("5"), project_id=PROJECT))
    await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant,
        destination=LocationKey(LocationType.PROJECT, PROJECT),
        quantity=Decimal("5"), accepted_quantity=Decimal("5"),
        dispatch_movement_id=disp.movement_id, project_id=PROJECT))
    await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.CONSUME_TO_SMR, tenant,
        source=LocationKey(LocationType.PROJECT, PROJECT),
        quantity=Decimal("3"), project_id=PROJECT, smr_id="smr-1"))


async def _seed(db, tenant=T, *, mapped=True):
    await db["projects"].insert_one({"id": PROJECT, "org_id": tenant, "code": "P20",
                                     "name": "P20", "status": "Active"})
    await db["execution_packages"].insert_one({
        "id": PKG, "org_id": tenant, "project_id": PROJECT, "activity_name": "Мазилка",
        "sale_total": 100.0, "material_budget_total": 25.0, "budget_total": 60.0,
        # The stale cache a real install holds before anyone recomputes.
        "actual_material_cost": 0})
    if mapped:
        await db["planned_materials"].insert_one({
            "id": "pm-c20", "org_id": tenant, "project_id": PROJECT, "status": "active",
            "item_id": ITEM, "material_name": "Лепило", "execution_package_id": PKG,
            "planned_total_cost": 25.0})


async def _no_manual_sync_was_needed(db):
    """The only canonical material_entries row is the projector's own one."""
    rows = await db["material_entries"].find({"org_id": T}, {"_id": 0}).to_list(None)
    assert [r["movement_kind"] for r in rows] == ["consume"]
    assert "execution_package_id" not in rows[0]          # no sync ran
    pkg = await db["execution_packages"].find_one({"id": PKG})
    assert pkg["actual_material_cost"] == 0               # no recompute ran


# ═══════════════════════════════ F-9 ═══════════════════════════════

async def test_f9_project_pnl_summary_breakdown_show_canonical_30(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import project_pnl
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)
    await _no_manual_sync_was_needed(db)

    pnl = await project_pnl.get_project_pnl(PROJECT, user=_user())
    assert pnl["expense"]["material_cost"] == pytest.approx(30.0)      # d8ac3a9: 0
    assert pnl["expense"]["total_expense"] == pytest.approx(30.0)      # d8ac3a9: 0
    basis = pnl["warehouse_cost_basis"]
    assert basis["warehouse"] == "canonical"
    assert basis["consumed_qty"] == pytest.approx(3.0)
    assert basis["legacy_excluded_cost"] == 0

    summary = await project_pnl.get_pnl_summary(PROJECT, user=_user())
    assert summary["total_expense"] == pytest.approx(30.0)
    assert summary["material_cost"] == pytest.approx(30.0)
    assert summary["gross_profit"] == pytest.approx(-30.0)

    brk = await project_pnl.get_pnl_breakdown(PROJECT, user=_user())
    assert brk["expense"]["material_cost"] == pytest.approx(30.0)
    assert brk["expense"]["total_expense"] == pytest.approx(30.0)


async def test_f9_legacy_issue_rows_are_not_added_on_top_of_the_canon(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Legacy issue 5 @10 (=50) + canonical consume 3 @10 (=30) → 30, not 80/50.

    5C-C22 / Р13: the legacy row is dated AFTER the tenant cutover (the first
    canonical ledger row), so it is never added on top of the canon. (A
    legacy row dated BEFORE the cutover counts — 100 + 30 = 130 — see
    test_warehouse_canonical_c22_all_reports_cutover.py.)"""
    from app.routes import project_pnl
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)
    await db["warehouse_transactions"].insert_one({
        "id": "legacy-issue-1", "org_id": T, "project_id": PROJECT, "type": "issue",
        "created_at": "2099-01-01T00:00:00+00:00",
        "lines": [{"material_name": "Лепило", "unit": "bag",
                   "qty_issued": 5, "unit_cost": 10}]})

    pnl = await project_pnl.get_project_pnl(PROJECT, user=_user())
    assert pnl["expense"]["material_cost"] == pytest.approx(30.0)
    assert pnl["warehouse_cost_basis"]["warehouse"] == "canonical"
    assert pnl["warehouse_cost_basis"]["legacy_excluded_cost"] == pytest.approx(50.0)
    # And the other project profit report gives the same single number.
    from app.routes import revenue_expense
    profit = await revenue_expense.get_project_profit_summary(PROJECT, user=_user())
    assert profit["expenses"]["material"] == pytest.approx(30.0)


async def test_f9_pre_canon_project_keeps_its_legacy_figure(
        canonical_mongo_db, monkeypatch):
    """No canonical row on the project → historical legacy issue cost stays."""
    from app.routes import project_pnl
    _, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["warehouse_transactions"].insert_one({
        "id": "legacy-issue-1", "org_id": T, "project_id": PROJECT, "type": "issue",
        "lines": [{"material_name": "Лепило", "unit": "bag",
                   "qty_issued": 5, "unit_cost": 10}]})
    pnl = await project_pnl.get_project_pnl(PROJECT, user=_user())
    assert pnl["expense"]["material_cost"] == pytest.approx(50.0)
    assert pnl["warehouse_cost_basis"]["warehouse"] == "legacy"


async def test_f9_accept_without_consume_is_not_cost(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Stock accepted on the project but not consumed is not project cost (F-7 rule)."""
    from app.routes import project_pnl
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = CommandService(client, gate=allow_always_gate)
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("10"), unit_value=Decimal("10")))
    disp = await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("5"), project_id=PROJECT))
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        destination=LocationKey(LocationType.PROJECT, PROJECT),
        quantity=Decimal("5"), accepted_quantity=Decimal("5"),
        dispatch_movement_id=disp.movement_id, project_id=PROJECT))
    pnl = await project_pnl.get_project_pnl(PROJECT, user=_user())
    assert pnl["expense"]["material_cost"] == 0


# ═══════════════════════════════ F-10 ═══════════════════════════════

async def test_f10_package_reports_show_30_without_sync_or_recompute(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import full_cost, material_smr
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)
    await _no_manual_sync_was_needed(db)

    fin = await material_smr.get_package_financial_summary(PKG, user=_user())
    assert fin["actual"]["material"] == pytest.approx(30.0)            # d8ac3a9: 0
    assert fin["actual"]["total"] == pytest.approx(30.0)
    assert fin["margin"]["gross_margin"] == pytest.approx(70.0)

    brk = await material_smr.get_project_package_breakdown(PROJECT, user=_user())
    assert [p["material_actual"] for p in brk["packages"]] == [pytest.approx(30.0)]
    assert brk["packages"][0]["material_variance"] == pytest.approx(5.0)
    assert brk["packages"][0]["gross_margin"] == pytest.approx(70.0)

    net = await full_cost.get_package_net_financial(PKG, user=_user())
    assert net["costs"]["material"] == pytest.approx(30.0)              # d8ac3a9: 0
    assert net["costs"]["gross_cost"] == pytest.approx(30.0)

    by_pkg = await material_smr.get_material_cost_by_exec_pkg(PKG, user=_user())
    assert by_pkg["material_actual_cost"] == pytest.approx(30.0)        # d8ac3a9: 0
    assert by_pkg["material_variance"] == pytest.approx(5.0)
    assert by_pkg["total_issued_qty"] == pytest.approx(5.0)
    assert by_pkg["by_material"][0]["consumed_qty"] == pytest.approx(3.0)
    assert by_pkg["by_material"][0]["net_cost"] == pytest.approx(30.0)

    summary = await material_smr.get_material_summary_for_project(T, PROJECT)
    assert summary["total_cost"] == pytest.approx(30.0)
    assert summary["mapped_cost"] == pytest.approx(30.0)               # d8ac3a9: 0 (unmapped)
    assert summary["unmapped_cost"] == 0

    warn = await material_smr.get_material_warnings(PROJECT, user=_user())
    over = [w for w in warn["warnings"] if w["type"] == "over_material_budget"]
    assert len(over) == 1 and "30" in over[0]["message"]

    proj_net = await full_cost.get_project_net_profit(PROJECT, user=_user())
    assert proj_net["costs"]["material"] == pytest.approx(30.0)
    from app.routes import revenue_expense
    profit = await revenue_expense.get_project_profit_summary(PROJECT, user=_user())
    assert profit["expenses"]["material"] == pytest.approx(30.0)


async def test_f10_reports_unchanged_after_sync_and_recompute(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """The manual endpoints stay replayable and change no number (no double count)."""
    from app.routes import full_cost, material_smr, project_pnl
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)

    async def _numbers():
        return (
            (await project_pnl.get_project_pnl(PROJECT, user=_user()))["expense"]["material_cost"],
            (await material_smr.get_package_financial_summary(PKG, user=_user()))["actual"]["material"],
            (await full_cost.get_package_net_financial(PKG, user=_user()))["costs"]["material"],
            [p["material_actual"] for p in
             (await material_smr.get_project_package_breakdown(PROJECT, user=_user()))["packages"]],
            (await material_smr.get_material_cost_by_exec_pkg(PKG, user=_user()))["material_actual_cost"],
            (await material_smr.get_material_summary_for_project(T, PROJECT))["total_cost"],
        )

    before = await _numbers()
    assert before == (pytest.approx(30.0), pytest.approx(30.0), pytest.approx(30.0),
                      [pytest.approx(30.0)], pytest.approx(30.0), pytest.approx(30.0))
    await material_smr.sync_material_entries(PROJECT, user=_user())
    await material_smr.recompute_execution_package_material(PROJECT, user=_user())
    await material_smr.sync_material_entries(PROJECT, user=_user())
    assert await _numbers() == before
    pkg = await db["execution_packages"].find_one({"id": PKG})
    assert pkg["actual_material_cost"] == pytest.approx(30.0)   # cache == the read


async def test_f10_stale_manual_cache_is_not_read_by_the_package_reports(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """A cached `actual_material_cost` (e.g. 999 from an old recompute or a
    manual edit) is no second source: the reports show the canon."""
    from app.routes import full_cost, material_smr
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)
    await db["execution_packages"].update_one({"id": PKG}, {"$set": {"actual_material_cost": 999}})
    fin = await material_smr.get_package_financial_summary(PKG, user=_user())
    assert fin["actual"]["material"] == pytest.approx(30.0)
    net = await full_cost.get_package_net_financial(PKG, user=_user())
    assert net["costs"]["material"] == pytest.approx(30.0)
    brk = await material_smr.get_project_package_breakdown(PROJECT, user=_user())
    assert brk["packages"][0]["material_actual"] == pytest.approx(30.0)


# ═══════════════════════════════ F-11 ═══════════════════════════════

async def test_f11_project_material_ledger_reads_the_canonical_ledger(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import procurement
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)

    out = await procurement.get_project_material_ledger(PROJECT, user=_user())
    assert len(out["ledger"]) == 1                                      # d8ac3a9: []
    row = out["ledger"][0]
    assert row["material_name"] == "Лепило"
    assert row["item_id"] == ITEM
    assert row["source"] == "canonical"
    assert row["dispatched_to_project"] == pytest.approx(5.0)
    assert row["issued_to_project"] == pytest.approx(5.0)
    assert row["consumed"] == pytest.approx(3.0)
    assert row["returned"] == 0 and row["written_off"] == 0
    assert row["remaining_on_project"] == pytest.approx(2.0)


async def test_f11_ledger_shows_canonical_stock_before_acceptance_as_in_transit_only(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Rule B: a dispatched-not-accepted lot is not on the project yet."""
    from app.routes import procurement
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db, mapped=False)
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    svc = CommandService(client, gate=allow_always_gate)
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("10"), unit_value=Decimal("10")))
    await svc.execute(_Ctx(), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1"),
        quantity=Decimal("5"), project_id=PROJECT))
    out = await procurement.get_project_material_ledger(PROJECT, user=_user())
    [row] = out["ledger"]
    assert row["material_name"] == ITEM                    # no planned name → item id
    assert row["dispatched_to_project"] == pytest.approx(5.0)
    assert row["issued_to_project"] == 0
    assert row["remaining_on_project"] == 0


# ═══════════════════════════ tenant isolation ═══════════════════════════

async def test_c20_reads_are_tenant_scoped(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Tenant A's canonical movements never appear in tenant B's reports,
    even for the same project / package ids."""
    from app.routes import full_cost, material_smr, procurement, project_pnl
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)
    # Tenant B: same ids, no movements.
    await db["projects"].insert_one({"id": PROJECT, "org_id": T2, "code": "B", "name": "B"})
    await db["execution_packages"].insert_one({
        "id": PKG + "-b", "org_id": T2, "project_id": PROJECT, "sale_total": 100.0,
        "material_budget_total": 25.0})
    await db["planned_materials"].insert_one({
        "id": "pm-b", "org_id": T2, "project_id": PROJECT, "status": "active",
        "item_id": ITEM, "material_name": "Лепило", "execution_package_id": PKG + "-b"})

    b = _user(T2)
    assert (await project_pnl.get_project_pnl(PROJECT, user=b))["expense"]["material_cost"] == 0
    assert (await material_smr.get_package_financial_summary(PKG + "-b", user=b))["actual"]["material"] == 0
    assert (await full_cost.get_package_net_financial(PKG + "-b", user=b))["costs"]["material"] == 0
    assert (await material_smr.get_material_summary_for_project(T2, PROJECT))["total_cost"] == 0
    assert (await procurement.get_project_material_ledger(PROJECT, user=b))["ledger"] == []
    # And tenant A still sees its own 30.
    assert (await project_pnl.get_project_pnl(PROJECT, user=_user()))["expense"]["material_cost"] \
        == pytest.approx(30.0)


def test_c20_no_report_reads_the_cached_package_material_actual():
    """Static guard: the three package reports no longer read the stored
    `actual_material_cost` cache (F-10: one screen, one number)."""
    import inspect
    from app.routes import full_cost, material_smr
    for fn in (material_smr.get_package_financial_summary,
               material_smr.get_project_package_breakdown,
               material_smr.get_material_warnings,
               full_cost.get_package_net_financial):
        assert 'pkg.get("actual_material_cost"' not in inspect.getsource(fn), fn.__name__
