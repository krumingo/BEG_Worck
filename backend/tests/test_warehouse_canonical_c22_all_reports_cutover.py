"""LIVE-OPS-01 / TASK 5C — 5C-C22: every finance report shows ONE material number.

Package: ``docs/architecture/tasks/5C-C22_ALL_FINANCE_REPORTS_CUTOVER.md``
(branch ``claude/happy-meitner-bmcnel``). Decisions Р9, Р13 (Крум, 06.11.2026)
in ``docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md``. Audit of
c0b3b4c: ``docs/audit/AUDIT_LOG.md`` @ ``claude/audit-log`` (C20-1, C20-2).

One shared helper (``canonical_material_cost.project_material_cost``) feeds
every report; Р13 splits a mixed history by the tenant cutover (the first
canonical ledger row): legacy issue rows BEFORE it count, after it only the
canonical rows count.

Scenario (real CommandService, no manual sync / recompute):
receive 10 @10 → dispatch 5 → accept 5 → consume 3   → canonical 30.

  * canonical only                     → 30 on every report;
  * + legacy issue 100 before cutover  → 130 on every report;
  * + legacy issue 70 AFTER cutover    → still 130 (70 reported excluded);
  * + write-off 2 @10 from the project → +20 „фира" (50 / 150) everywhere.

On df48d68: project_financial_results / centralized_reports /
profit-by-period / pulse / materials_baseline show 0 (canonical) or 100
(legacy only), the P&L drops the pre-cutover 100 (30, not 130).

Run (real Mongo, required):
    WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 PERMISSION_SERVICE_MODE=enforce \\
    MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \\
    PYTHONPATH=. pytest -q tests/test_warehouse_canonical_c22_all_reports_cutover.py
"""
from __future__ import annotations

import importlib
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.service import CommandInput, CommandService
from app.tenancy.data_access import TenantData


def _sec02_req(path="/api/sec02-direct-call"):
    """SEC-02-G (audit SEC71-M1): a real Request for a direct call of an R20-decorated
    handler — the role is the ``user=`` the test already passes (FastAPI injects this
    request in production; without one the decorator fails closed and strips money)."""
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": path, "headers": [],
                    "query_string": b"", "root_path": "", "scheme": "http",
                    "server": ("testserver", 80), "client": ("testclient", 50000)})


pytest_plugins = ["tests.warehouse_canonical_conftest"]

T = "org_c22"
T2 = "org_c22_other"
PROJECT = "p-c22"
PKG = "pkg-c22"
ITEM = "item_c22"
WH = LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1")
PRJ = LocationKey(LocationType.PROJECT, PROJECT)

BEFORE = "2026-01-15T09:00:00+00:00"     # long before any canonical row
AFTER = "2099-01-01T09:00:00+00:00"      # after the cutover


class _Ctx:
    def __init__(self, tenant_id: str = T):
        self.tenant_id = tenant_id
        self.org_id = tenant_id
        self.user_id = "u-c22"


def _user(org=T):
    return {"id": "u-" + org, "org_id": org, "role": "Owner", "email": org + "@x"}


def _inp(action, tenant=T, **kw):
    base = dict(
        action=action, tenant_id=tenant, actor_id="u-c22", item_id=ITEM, unit="bag",
        quantity=kw.pop("quantity", Decimal("10")),
        idempotency_key=f"k-{uuid.uuid4().hex[:8]}",
    )
    base.update(kw)
    return CommandInput(**base)


_DB_MODULES = (
    "app.routes.material_smr", "app.routes.full_cost", "app.routes.revenue_expense",
    "app.routes.labor_smr", "app.routes.subcontractors", "app.routes.procurement",
    "app.routes.project_pnl", "app.services.project_pnl",
    "app.services.project_financial_results", "app.services.paid_labor",
    "app.services.slip_payment_state", "app.services.centralized_reports",
    "app.routes.revenue_snapshot", "app.services.pulse_generator",
    "app.routes.materials_baseline", "app.routes.budget_progress",
    "app.services.resource_model", "app.services.resolve_hourly_rate",
    "app.services.budget_formula",
    # LAB-01: the labor calculation reads through these two
    "app.services.labor_cost", "app.services.report_normalizer",
)


def _patch_dbs(monkeypatch, db):
    # The write-off needs evidence file_ids → File Registry on (as in C21).
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    from tests.warehouse_canonical_conftest import sec02_owner_in_enforce
    sec02_owner_in_enforce(monkeypatch, T, T2)        # SEC-02-G (SEC71-M1): R20 reads
    for name in _DB_MODULES:
        mod = importlib.import_module(name)
        if hasattr(mod, "db"):
            monkeypatch.setattr(mod, "db", db)


async def _scenario(client, gate, db, tenant=T, *, write_off=False):
    """receive 10 @10 → dispatch 5 → accept 5 → consume 3 (→ write-off 2)."""
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    coll = TenantData.for_resolved_org(db, tenant).warehouse_transactions
    svc = CommandService(client, gate=gate)
    ctx = _Ctx(tenant)
    await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant,
        source=LocationKey(LocationType.SUPPLIER, "sup_1"), destination=WH,
        quantity=Decimal("10"), unit_value=Decimal("10")))
    disp = await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant, source=WH,
        quantity=Decimal("5"), project_id=PROJECT))
    await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant, destination=PRJ,
        quantity=Decimal("5"), accepted_quantity=Decimal("5"),
        dispatch_movement_id=disp.movement_id, project_id=PROJECT))
    await svc.execute(ctx, db, coll, _inp(
        CanonicalAction.CONSUME_TO_SMR, tenant, source=PRJ,
        quantity=Decimal("3"), project_id=PROJECT, smr_id="smr-1"))
    if write_off:
        await svc.execute(ctx, db, coll, _inp(
            CanonicalAction.WRITE_OFF, tenant, source=PRJ, quantity=Decimal("2"),
            reason="брак", file_ids=["f-1"]))


async def _seed(db, tenant=T):
    await db["projects"].insert_one({"id": PROJECT, "org_id": tenant, "code": "P22",
                                     "name": "P22", "status": "Active"})
    await db["execution_packages"].insert_one({
        "id": PKG, "org_id": tenant, "project_id": PROJECT, "activity_name": "Мазилка",
        "sale_total": 1000.0, "material_budget_total": 25.0, "budget_total": 60.0,
        "progress_percent": 50, "progress_last_updated_at": "2026-11-01",
        # The stale cache a real install holds before anyone recomputes.
        "actual_material_cost": 0})
    await db["planned_materials"].insert_one({
        "id": "pm-c22", "org_id": tenant, "project_id": PROJECT, "status": "active",
        "item_id": ITEM, "material_name": "Лепило", "execution_package_id": PKG,
        "planned_total_cost": 25.0})


async def _legacy_issue(db, tenant=T, *, value=100.0, created_at=BEFORE,
                        issue_date=None, txn_id=None, shape="total_price"):
    """A legacy (pre-canon) issue row exactly as the retired writer stored it."""
    line = {"material_name": "Лепило", "unit": "bag", "qty_issued": 10}
    if shape == "total_price":
        line.update(unit_price=value / 10, total_price=value)
    else:                                   # older rows: unit_cost × qty
        line.update(unit_cost=value / 10)
    txn_id = txn_id or f"legacy-{uuid.uuid4().hex[:6]}"
    # The test DB carries the canonical unique (tenant_id, movement_id)
    # index, so each legacy fixture row gets its own inert movement_id
    # (no ``action`` — it stays a legacy row for every reader).
    row = {"id": txn_id, "movement_id": f"legacy:{txn_id}", "org_id": tenant,
           "project_id": PROJECT, "type": "issue", "status": "posted",
           "lines": [line], "total": value}
    if created_at is not None:
        row["created_at"] = created_at
    if issue_date is not None:
        row["issue_date"] = issue_date
    await db["warehouse_transactions"].insert_one(row)


async def _all_reports(tenant=T) -> dict:
    """Every finance report / screen of the C22 package → its material total
    (consumption + „фира" + pre-cutover legacy) and its „фира" share."""
    from app.routes import (budget_progress, full_cost, material_smr,
                            materials_baseline, project_pnl, revenue_expense,
                            revenue_snapshot)
    from app.services import centralized_reports, project_financial_results
    u = _user(tenant)
    out = {}

    pnl = await project_pnl.get_project_pnl(PROJECT, user=u)
    out["pnl"] = (pnl["expense"]["material_cost"] + pnl["expense"]["material_waste_cost"],
                  pnl["expense"]["material_waste_cost"])
    s = await project_pnl.get_pnl_summary(PROJECT, user=u)
    out["pnl_summary"] = (s["material_cost"] + s["material_waste_cost"], s["material_waste_cost"])
    b = await project_pnl.get_pnl_breakdown(PROJECT, user=u)
    out["pnl_breakdown"] = (b["expense"]["material_cost"] + b["expense"]["material_waste_cost"],
                            b["expense"]["material_waste_cost"])

    m = await material_smr.get_material_summary_for_project(tenant, PROJECT)
    out["material_summary"] = (m["total_cost"], m["waste_cost"])

    pf = await material_smr.get_package_financial_summary(PKG, user=u)
    out["package_financial"] = (pf["actual"]["material"] + pf["actual"]["waste"],
                                pf["actual"]["waste"])
    br = await material_smr.get_project_package_breakdown(PROJECT, user=u)
    row = br["packages"][0]
    out["package_breakdown"] = (row["material_actual"] + row["material_waste"],
                                row["material_waste"])
    bx = await material_smr.get_material_cost_by_exec_pkg(PKG, user=u)
    out["by_execution_package"] = (bx["material_total_cost"], bx["material_waste_cost"])
    net = await full_cost.get_package_net_financial(PKG, user=u)
    out["package_net"] = (net["costs"]["material"] + net["costs"]["waste"], net["costs"]["waste"])

    pp = await revenue_expense.get_project_profit_summary(PROJECT, user=u)
    out["project_profit"] = (pp["expenses"]["material"] + pp["expenses"]["waste"],
                             pp["expenses"]["waste"])
    sv = await revenue_expense.get_project_smr_view(PROJECT, user=u)
    srow = sv["rows"][0]
    out["smr_view"] = (srow["material_actual"] + srow["material_waste"], srow["material_waste"])
    npf = await full_cost.get_project_net_profit(PROJECT, user=u)
    out["net_profit"] = (npf["costs"]["material"] + npf["costs"]["waste"], npf["costs"]["waste"])

    fr = await project_financial_results.compute_financial_results(tenant, PROJECT)
    out["financial_results"] = (fr["cash"]["breakdown"]["paid_materials"],
                                fr["cash"]["material_cost_basis"]["waste_cost"])
    cr = await centralized_reports.build_centralized_reports(tenant, PROJECT)
    out["centralized_reports"] = (cr["finance"]["total_materials"], cr["finance"]["material_waste"])

    pbp = await revenue_snapshot.get_profit_by_period(PROJECT, user=u)
    # 5C-C23 F-14: ``material`` is consumption only, ``waste`` is „фира".
    out["profit_by_period"] = (
        round(sum(p["material"] + p["waste"] for p in pbp["periods"])
              + pbp["material_undated"] + pbp["waste_undated"], 2),
        round(sum(p["waste"] for p in pbp["periods"]) + pbp["waste_undated"], 2))

    mb = await materials_baseline.get_project_material_summary(PROJECT, user=u, _sec02_request=_sec02_req())
    out["materials_baseline"] = (mb["actual"]["net_material_cost"], mb["actual"]["waste_value"])

    cmp_ = await budget_progress.get_progress_vs_cost(PKG, user=u, _sec02_request=_sec02_req())
    out["progress_vs_cost"] = (cmp_["raw"]["material_actual"], None)
    return out


# 5C-C25 (Р17, Крум 06.11.2026): the PROJECT cost is the accepted lot; the
# PACKAGE / SMR reports show the part of it ALLOCATED to the package by
# consumption („фира" and pre-cutover legacy included). The two differ only
# by the unallocated stock still on site (helper ``unallocated_cost``).
PACKAGE_LEVEL = frozenset({"package_financial", "package_breakdown",
                           "by_execution_package", "package_net", "smr_view",
                           "progress_vs_cost"})


def _assert_all(reports: dict, total: float, waste: float, package_total: float = None):
    package_total = total if package_total is None else package_total

    def _want(k):
        return package_total if k in PACKAGE_LEVEL else total
    bad = {k: v for k, v in reports.items()
           if v[0] != pytest.approx(_want(k))
           or (v[1] is not None and v[1] != pytest.approx(waste))}
    assert not bad, (f"expected {total} / package {package_total} (фира {waste}) "
                     f"on every report, got {bad}")


# ═══════════════════════════════ tests ═══════════════════════════════

async def test_canonical_only_is_30_on_every_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)
    reports = await _all_reports()
    assert len(reports) == 16
    # 5C-C25 (Р17): project 50 (accepted 5 × 10), package 30 (consumed 3).
    _assert_all(reports, 50.0, 0.0, package_total=30.0)   # df48d68: financial_results/centralized/... 0


async def test_mixed_history_is_130_on_every_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Р13: 100 legacy BEFORE the cutover + 30 canonical after = 130.
    5C-C25 (Р17): the canonical part is the accepted lot, 50 → 150; the
    package allocation is 100 + 30 = 130."""
    from app.services.canonical_material_cost import project_material_cost
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=100.0, created_at=BEFORE)
    await _scenario(client, allow_always_gate, db)
    _assert_all(await _all_reports(), 150.0, 0.0, package_total=130.0)   # df48d68: P&L 30, centralized 100, ...

    cost = await project_material_cost(TenantData.for_resolved_org(db, T), T, PROJECT)
    assert cost["source"] == "mixed"
    assert cost["legacy_cost"] == pytest.approx(100.0)
    assert cost["canonical_cost"] == pytest.approx(50.0)
    assert cost["unallocated_cost"] == pytest.approx(20.0)
    assert cost["legacy_excluded_cost"] == 0
    # The cutover is the tenant's first canonical ledger row (receive).
    first = await db["warehouse_transactions"].find(
        {"org_id": T, "action": {"$exists": True}}).sort("recorded_at", 1).to_list(1)
    assert cost["cutover_at"] == first[0]["recorded_at"]
    assert cost["cutover_movement_id"] == first[0]["movement_id"]
    assert first[0]["action"] == "receive_from_supplier"
    assert cost["cutover_source"] == "first_canonical_ledger_row"


async def test_legacy_row_after_the_cutover_is_never_counted(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """A legacy row dated after the cutover is not counted twice: 100 + 30 = 130,
    the 70 after the cutover is reported as excluded.
    5C-C25 (Р17): 100 + 50 accepted = 150 (package 130); 70 still excluded."""
    from app.routes import project_pnl
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=100.0, created_at=BEFORE)
    await _scenario(client, allow_always_gate, db)
    await _legacy_issue(db, value=70.0, created_at=AFTER)
    _assert_all(await _all_reports(), 150.0, 0.0, package_total=130.0)
    pnl = await project_pnl.get_project_pnl(PROJECT, user=_user())
    basis = pnl["warehouse_cost_basis"]
    assert basis["warehouse"] == "mixed"
    assert basis["legacy_cost"] == pytest.approx(100.0)
    assert basis["legacy_excluded_cost"] == pytest.approx(70.0)
    assert basis["canonical_cost"] == pytest.approx(50.0)


async def test_write_off_fira_is_included_on_every_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Р10 + C21: consume 30 + „фира" 20 = 50, and with the mixed history 150."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db, write_off=True)
    _assert_all(await _all_reports(), 50.0, 20.0)


async def test_mixed_history_with_fira_is_150_on_every_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=100.0, created_at=BEFORE)
    await _scenario(client, allow_always_gate, db, write_off=True)
    await _legacy_issue(db, value=70.0, created_at=AFTER)
    _assert_all(await _all_reports(), 150.0, 20.0)


async def test_profit_by_period_splits_the_same_total_by_month(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """2026-01: legacy 100; the current month: canonical 30 + фира 20."""
    from app.routes import revenue_snapshot
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=100.0, created_at=BEFORE)
    await _scenario(client, allow_always_gate, db, write_off=True)
    pbp = await revenue_snapshot.get_profit_by_period(PROJECT, user=_user())
    by = {p["period"]: p for p in pbp["periods"]}
    now = datetime.now(timezone.utc).strftime("%Y-%m")
    assert by["2026-01"]["material"] == pytest.approx(100.0)       # df48d68: no period
    # 5C-C23 F-14: material = consumption 30, „фира" 20 beside it, 50 together.
    assert by[now]["material"] == pytest.approx(30.0)
    assert by[now]["waste"] == pytest.approx(20.0)
    assert by[now]["material_total"] == pytest.approx(50.0)
    assert pbp["material_undated"] == 0


async def test_pulse_shows_the_material_cost_of_its_day(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.services import pulse_generator
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=100.0, created_at=BEFORE)
    await _scenario(client, allow_always_gate, db, write_off=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p_today = await pulse_generator.generate_pulse(T, PROJECT, today)
    assert p_today["total_material_cost"] == pytest.approx(50.0)  # df48d68: 0
    # 5C-C25 (Р17): the day's cost lines are the acceptance (+50) and the
    # „фира" reclassification (+20 фира / −20 material, net 0); consumption
    # is allocation, not a cost line.
    assert sorted(m["kind"] for m in p_today["materials_used"]) == \
        ["accept", "write_off_reclass", "фира"]
    p_legacy = await pulse_generator.generate_pulse(T, PROJECT, BEFORE[:10])
    assert p_legacy["total_material_cost"] == pytest.approx(100.0)


async def test_cutover_is_per_tenant(canonical_mongo_db, allow_always_gate, monkeypatch):
    """Tenant B's canonical rows do not move tenant A's cutover: A (legacy
    only, dated after B's first row) keeps its whole legacy figure."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db, tenant=T)
    await _seed(db, tenant=T2)
    await _scenario(client, allow_always_gate, db, tenant=T2)
    await _legacy_issue(db, tenant=T, value=100.0, created_at=AFTER)
    _assert_all(await _all_reports(T), 100.0, 0.0)
    # 5C-C25 (Р17): accepted 50 on the project, 30 allocated to the package.
    _assert_all(await _all_reports(T2), 50.0, 0.0, package_total=30.0)


async def test_legacy_dates_and_value_shapes(canonical_mongo_db, allow_always_gate, monkeypatch):
    """issue_date only (no created_at) is placed by its day; the older
    unit_cost × qty shape values the same as the writer's total_price; an
    undated legacy row counts (pre-canon) and is flagged."""
    from app.services.canonical_material_cost import project_material_cost
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=40.0, created_at=None, issue_date="2026-02-01",
                        shape="unit_cost")
    await _legacy_issue(db, value=60.0, created_at=None)          # undated
    await _scenario(client, allow_always_gate, db)
    await _legacy_issue(db, value=70.0, created_at=None, issue_date="2099-01-01")
    # 5C-C25 (Р17): 100 legacy + 50 accepted = 150; package 100 + 30 = 130.
    _assert_all(await _all_reports(), 150.0, 0.0, package_total=130.0)
    cost = await project_material_cost(TenantData.for_resolved_org(db, T), T, PROJECT)
    assert cost["legacy_cost"] == pytest.approx(100.0)
    assert cost["legacy_undated_cost"] == pytest.approx(60.0)
    assert cost["legacy_excluded_cost"] == pytest.approx(70.0)


async def test_sync_and_recompute_change_no_number(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_smr
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=100.0, created_at=BEFORE)
    await _scenario(client, allow_always_gate, db, write_off=True)
    before = await _all_reports()
    await material_smr.sync_material_entries(PROJECT, user=_user())
    await material_smr.recompute_execution_package_material(PROJECT, user=_user())
    after = await _all_reports()
    assert before == after
    _assert_all(after, 150.0, 20.0)
