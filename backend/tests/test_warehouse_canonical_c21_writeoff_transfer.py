"""LIVE-OPS-01 / TASK 5C — 5C-C21: write-off from a project is project cost
(„фира", Р10) and Rule B for warehouse→warehouse transfers (Р11).

Package: ``docs/architecture/tasks/5C-C21_WRITEOFF_TRANSFER_RULES.md``
(branch ``claude/happy-meitner-bmcnel``). Decisions Р10 / Р11 (Крум,
06.11.2026) are recorded in ``docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md``.

  * F-12 — WRITE_OFF 2 @10 from a PROJECT bucket = +20 project cost, once,
           shown as the „фира" line in the P&L, the package reports and the
           profit reports. WRITE_OFF from the central warehouse = 0 on the
           project. On c0b3b4c every report showed 0 „фира" (no line at all).
  * F-13 — TRANSFER_WAREHOUSE_TO_WAREHOUSE goes to in_transit; the target
           warehouse is credited only by ACCEPT_PROJECT_DELIVERY; 10 → accept
           6 + 4 → 0 unresolved, value conserved; partial accept leaves a
           visible discrepancy; a direct transfer is refused server-side.
           On c0b3b4c a direct transfer credited wh_b immediately.

Run (real Mongo, required):
    WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 PERMISSION_SERVICE_MODE=enforce \\
    MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \\
    PYTHONPATH=. pytest -q tests/test_warehouse_canonical_c21_writeoff_transfer.py
"""
from __future__ import annotations

import importlib
import os
import uuid
from decimal import Decimal

import pytest

from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
)
from app.services.warehouse_movements.errors import (
    IdempotencyConflictError, InvariantViolationError, PermissionDeniedError,
)
from app.services.warehouse_movements.queries import stock_at
from app.services.warehouse_movements.service import CommandInput, CommandService
from app.tenancy.data_access import TenantData

pytest_plugins = ["tests.warehouse_canonical_conftest"]

T = "org_c21"
T2 = "org_c21_other"
PROJECT = "p-c21"
PKG = "pkg-c21"
ITEM = "item_c21"
WH = LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1")
WH_B = LocationKey(LocationType.SMALL_WAREHOUSE, "wh_b")
PRJ = LocationKey(LocationType.PROJECT, PROJECT)
PENDING = LocationKey(LocationType.IN_TRANSIT, "pending", state=MovementState.IN_TRANSIT)


class _Ctx:
    def __init__(self, tenant_id: str = T):
        self.tenant_id = tenant_id
        self.org_id = tenant_id
        self.user_id = "u-c21"


def _user(org=T):
    return {"id": "u-" + org, "org_id": org, "role": "Owner", "email": org + "@x"}


def _inp(action, tenant=T, **kw):
    base = dict(
        action=action, tenant_id=tenant, actor_id="u-c21", item_id=ITEM, unit="bag",
        quantity=kw.pop("quantity", Decimal("10")),
        idempotency_key=kw.pop("idempotency_key", f"k-{uuid.uuid4().hex[:8]}"),
    )
    base.update(kw)
    return CommandInput(**base)


def _patch_dbs(monkeypatch, db):
    for name in ("app.routes.material_smr", "app.routes.full_cost",
                 "app.routes.revenue_expense", "app.routes.labor_smr",
                 "app.routes.subcontractors", "app.routes.procurement",
                 "app.routes.project_pnl", "app.services.project_pnl"):
        monkeypatch.setattr(importlib.import_module(name), "db", db)


class _Env:
    def __init__(self, client, gate, db, tenant=T):
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        self.db = db
        self.tenant = tenant
        self.coll = TenantData.for_resolved_org(db, tenant).warehouse_transactions
        self.svc = CommandService(client, gate=gate)
        self.ctx = _Ctx(tenant)

    async def run(self, action, **kw):
        return await self.svc.execute(self.ctx, self.db, self.coll,
                                      _inp(action, self.tenant, **kw))

    async def receive(self, qty="10", value="10", at=WH):
        return await self.run(CanonicalAction.RECEIVE_FROM_SUPPLIER,
                              source=LocationKey(LocationType.SUPPLIER, "sup_1"),
                              destination=at, quantity=Decimal(qty),
                              unit_value=Decimal(value))

    async def write_off(self, source, qty="2", **kw):
        return await self.run(CanonicalAction.WRITE_OFF, source=source,
                              quantity=Decimal(qty), reason="брак", file_ids=["f-1"], **kw)

    async def stock(self, loc):
        return await stock_at(self.coll, tenant_id=self.tenant, item_id=ITEM, location=loc)


async def _seed(db, tenant=T):
    await db["projects"].insert_one({"id": PROJECT, "org_id": tenant, "code": "P21",
                                     "name": "P21", "status": "Active"})
    await db["execution_packages"].insert_one({
        "id": PKG, "org_id": tenant, "project_id": PROJECT, "activity_name": "Мазилка",
        "sale_total": 100.0, "material_budget_total": 25.0, "budget_total": 60.0,
        "actual_material_cost": 0})
    await db["planned_materials"].insert_one({
        "id": "pm-c21", "org_id": tenant, "project_id": PROJECT, "status": "active",
        "item_id": ITEM, "material_name": "Лепило", "execution_package_id": PKG,
        "planned_total_cost": 25.0})


async def _project_with_stock(env):
    """receive 10 @10 → dispatch 5 → accept 5 → consume 3 (2 left on the project)."""
    await env.receive()
    disp = await env.run(CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, source=WH,
                         quantity=Decimal("5"), project_id=PROJECT)
    await env.run(CanonicalAction.ACCEPT_PROJECT_DELIVERY, destination=PRJ,
                  quantity=Decimal("5"), accepted_quantity=Decimal("5"),
                  dispatch_movement_id=disp.movement_id, project_id=PROJECT)
    await env.run(CanonicalAction.CONSUME_TO_SMR, source=PRJ, quantity=Decimal("3"),
                  project_id=PROJECT, smr_id="smr-1")


async def _all_reports(material_smr, full_cost, revenue_expense, project_pnl, user):
    """Every report Р10 names: P&L, package, profit."""
    return {
        "pnl": await project_pnl.get_project_pnl(PROJECT, user=user),
        "pnl_summary": await project_pnl.get_pnl_summary(PROJECT, user=user),
        "pkg_fin": await material_smr.get_package_financial_summary(PKG, user=user),
        "pkg_brk": await material_smr.get_project_package_breakdown(PROJECT, user=user),
        "pkg_net": await full_cost.get_package_net_financial(PKG, user=user),
        "by_pkg": await material_smr.get_material_cost_by_exec_pkg(PKG, user=user),
        "summary": await material_smr.get_material_summary_for_project(user["org_id"], PROJECT),
        "net_profit": await full_cost.get_project_net_profit(PROJECT, user=user),
        "profit": await revenue_expense.get_project_profit_summary(PROJECT, user=user),
    }


def _waste_lines(r):
    return {
        "pnl": r["pnl"]["expense"]["material_waste_cost"],
        "pnl_summary": r["pnl_summary"]["material_waste_cost"],
        "pkg_fin": r["pkg_fin"]["actual"]["waste"],
        "pkg_brk": r["pkg_brk"]["packages"][0]["material_waste"],
        "pkg_net": r["pkg_net"]["costs"]["waste"],
        "by_pkg": r["by_pkg"]["material_waste_cost"],
        "summary": r["summary"]["waste_cost"],
        "net_profit": r["net_profit"]["costs"]["waste"],
        "profit": r["profit"]["expenses"]["waste"],
    }


def _totals(r):
    return {
        "pnl": r["pnl"]["expense"]["total_expense"],
        "pnl_summary": r["pnl_summary"]["total_expense"],
        "pkg_fin": r["pkg_fin"]["actual"]["total"],
        "pkg_brk": r["pkg_brk"]["packages"][0]["total_actual"],
        "pkg_net": r["pkg_net"]["costs"]["gross_cost"],
        "by_pkg": r["by_pkg"]["material_total_cost"],
        "summary": r["summary"]["total_cost"],
        "net_profit": r["net_profit"]["costs"]["gross_cost"],
        "profit": r["profit"]["expenses"]["total"],
    }


# ═══════════════════════════════ F-12 (Р10) ═══════════════════════════════

async def test_f12_project_write_off_is_project_cost_once_as_fira_in_every_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Write-off 2 @10 from the project → +20 „фира" in P&L, package and profit;
    material (consumption) stays 30; every total = 50, counted once."""
    from app.routes import full_cost, material_smr, project_pnl, revenue_expense
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    env = _Env(client, allow_always_gate, db)
    await _project_with_stock(env)
    wo = await env.write_off(PRJ, "2")
    # Server-derived project scope (not sent by the caller).
    assert wo.envelope["project_id"] == PROJECT

    r = await _all_reports(material_smr, full_cost, revenue_expense, project_pnl, _user())
    assert _waste_lines(r) == {k: pytest.approx(20.0) for k in _waste_lines(r)}   # c0b3b4c: no line
    assert _totals(r) == {k: pytest.approx(50.0) for k in _totals(r)}             # c0b3b4c: 30
    # Material stays the consumption only — „фира" is its own line, not added twice.
    assert r["pnl"]["expense"]["material_cost"] == pytest.approx(30.0)
    assert r["pkg_fin"]["actual"]["material"] == pytest.approx(30.0)
    assert r["pkg_net"]["costs"]["material"] == pytest.approx(30.0)
    assert r["net_profit"]["costs"]["material"] == pytest.approx(30.0)
    assert r["profit"]["expenses"]["material"] == pytest.approx(30.0)
    assert r["by_pkg"]["material_actual_cost"] == pytest.approx(30.0)
    assert r["pkg_brk"]["packages"][0]["material_actual"] == pytest.approx(30.0)
    assert r["pnl"]["warehouse_cost_basis"]["waste_qty"] == pytest.approx(2.0)
    assert r["pnl"]["profit"]["gross_profit"] == pytest.approx(-50.0)
    assert r["pkg_fin"]["margin"]["gross_margin"] == pytest.approx(50.0)
    # Exactly one cost row per movement: consume 30 + write_off 20.
    rows = await db["material_entries"].find(
        {"org_id": T, "projection_source": "canonical_warehouse_service"},
        {"_id": 0}).to_list(None)
    assert sorted((x["movement_kind"], float(x["total_value"])) for x in rows) == \
        [("consume", 30.0), ("write_off", 20.0)]
    # The project quantity trail: 5 in, 3 consumed, 2 written off, 0 left.
    from app.routes import procurement
    [row] = (await procurement.get_project_material_ledger(PROJECT, user=_user()))["ledger"]
    assert row["written_off"] == pytest.approx(2.0)
    assert row["remaining_on_project"] == pytest.approx(0.0)


async def test_f12_central_warehouse_write_off_is_not_project_cost(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Write-off 2 from the central warehouse → 0 on the project (no row)."""
    from app.routes import full_cost, material_smr, project_pnl, revenue_expense
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    env = _Env(client, allow_always_gate, db)
    await _project_with_stock(env)
    await env.write_off(WH, "2")
    assert (await env.stock(WH))["quantity"] == "3"         # 10 − 5 − 2

    r = await _all_reports(material_smr, full_cost, revenue_expense, project_pnl, _user())
    assert _waste_lines(r) == {k: 0 for k in _waste_lines(r)}
    assert _totals(r) == {k: pytest.approx(30.0) for k in _totals(r)}
    assert await db["material_entries"].count_documents(
        {"org_id": T, "movement_kind": "write_off"}) == 0


async def test_f12_warehouse_write_off_cannot_be_booked_to_a_project(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """A warehouse write-off carrying a project_id is refused (it is not project
    cost); a project write-off naming another project is refused."""
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await _project_with_stock(env)
    with pytest.raises(InvariantViolationError):
        await env.write_off(WH, "1", project_id=PROJECT)
    with pytest.raises(InvariantViolationError):
        await env.write_off(PRJ, "1", project_id="p-other")
    assert await env.coll.count_documents({"tenant_id": T, "action": "write_off"}) == 0


async def test_f12_project_write_off_checks_the_project_scope(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """The derived project scope reaches the permission gate even when the
    caller omits project_id (existing canonical gate, no bypass)."""
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await _project_with_stock(env)
    seen = []

    class _DenyProject:
        async def ensure(self, ctx, *, action, source, destination, project_id):
            seen.append(project_id)
            if project_id:
                raise PermissionDeniedError("denied project scope",
                                            context={"project_id": project_id})

    env.svc = CommandService(client, gate=_DenyProject())
    with pytest.raises(PermissionDeniedError):
        await env.write_off(PRJ, "1")
    assert seen == [PROJECT]


async def test_f12_sync_rebuild_and_recompute_keep_fira_once(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """The manual sync, recompute and a full projection rebuild change no number."""
    from app.routes import full_cost, material_smr, project_pnl, revenue_expense
    from app.services.warehouse_movements.projections import rebuild_from_ledger
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    env = _Env(client, allow_always_gate, db)
    await _project_with_stock(env)
    await env.write_off(PRJ, "2")
    await env.write_off(WH, "1")

    async def _numbers():
        r = await _all_reports(material_smr, full_cost, revenue_expense, project_pnl, _user())
        return _waste_lines(r), _totals(r)

    before = await _numbers()
    assert before[0]["pnl"] == pytest.approx(20.0) and before[1]["pnl"] == pytest.approx(50.0)
    await material_smr.sync_material_entries(PROJECT, user=_user())
    await material_smr.recompute_execution_package_material(PROJECT, user=_user())
    assert await _numbers() == before
    await rebuild_from_ledger(db, tenant_id=T)
    assert await _numbers() == before
    await material_smr.sync_material_entries(PROJECT, user=_user())
    assert await _numbers() == before
    pkg = await db["execution_packages"].find_one({"id": PKG})
    assert pkg["actual_material_cost"] == pytest.approx(30.0)
    assert pkg["actual_material_waste_cost"] == pytest.approx(20.0)
    rows = await db["material_entries"].find(
        {"org_id": T, "movement_kind": "write_off"}, {"_id": 0}).to_list(None)
    assert len(rows) == 1 and rows[0]["cost_recognized"] is True
    assert float(rows[0]["total_value"]) == pytest.approx(20.0)


async def test_f12_fira_is_tenant_scoped(canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_smr, project_pnl
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _seed(db, tenant=T2)
    env = _Env(client, allow_always_gate, db)
    await _project_with_stock(env)
    await env.write_off(PRJ, "2")
    b = _user(T2)
    assert (await project_pnl.get_project_pnl(PROJECT, user=b))["expense"]["material_waste_cost"] == 0
    assert (await material_smr.get_material_summary_for_project(T2, PROJECT))["waste_cost"] == 0
    assert (await project_pnl.get_project_pnl(PROJECT, user=_user()))["expense"][
        "material_waste_cost"] == pytest.approx(20.0)


# ═══════════════════════════════ F-13 (Р11) ═══════════════════════════════

async def _transfer(env, qty="10", **kw):
    return await env.run(CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE, source=WH,
                         transfer_target=WH_B, quantity=Decimal(qty), **kw)


async def _accept(env, transfer, qty, **kw):
    return await env.run(CanonicalAction.ACCEPT_PROJECT_DELIVERY,
                         destination=kw.pop("destination", WH_B),
                         quantity=Decimal(qty), accepted_quantity=Decimal(qty),
                         dispatch_movement_id=transfer.movement_id, **kw)


async def test_f13_transfer_is_in_transit_and_credited_only_on_accept_6_plus_4(
        canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "12")
    tr = await _transfer(env)
    # The row went to in_transit (server-issued id), with the target beside it.
    assert tr.envelope["destination"]["location_type"] == "in_transit"
    assert tr.envelope["destination"]["location_id"] == tr.movement_id
    assert tr.envelope["transfer_target"] == WH_B.to_dict()
    assert (await env.stock(WH))["quantity"] == "0"
    assert (await env.stock(WH_B))["quantity"] == "0"          # c0b3b4c: not in transit
    transit = await db["warehouse_in_transit"].find_one({"dispatch_movement_id": tr.movement_id})
    assert transit["unresolved_quantity"] == "10"
    assert transit["transfer_target"] == WH_B.to_dict()

    a1 = await _accept(env, tr, "6")
    assert a1.unresolved_discrepancy_movement_id                 # 4 still in transit, visible
    assert (await env.stock(WH_B))["quantity"] == "6"
    assert Decimal((await env.stock(WH_B))["total_value"]) == Decimal("72")
    transit = await db["warehouse_in_transit"].find_one({"dispatch_movement_id": tr.movement_id})
    assert transit["unresolved_quantity"] == "4"
    assert len(transit.get("unresolved_discrepancies") or {}) == 1

    await _accept(env, tr, "4")
    b = await env.stock(WH_B)
    assert b["quantity"] == "10"
    assert Decimal(b["total_value"]) == Decimal("120")          # value conserved 10 × 12
    transit = await db["warehouse_in_transit"].find_one({"dispatch_movement_id": tr.movement_id})
    assert transit["unresolved_quantity"] == "0"
    assert (transit.get("unresolved_discrepancies") or {}) == {}  # 0 unresolved
    assert await env.coll.count_documents(
        {"tenant_id": T, "action": "discrepancy_resolved",
         "dispatch_movement_id": tr.movement_id}) == 1
    # Over-acceptance is refused.
    from app.services.warehouse_movements.errors import OriginAcceptanceOverrunError
    with pytest.raises(OriginAcceptanceOverrunError):
        await _accept(env, tr, "1")


async def test_f13_partial_accept_leaves_a_visible_discrepancy(
        canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "10")
    tr = await _transfer(env)
    await _accept(env, tr, "6")
    await _accept(env, tr, "3")
    assert (await env.stock(WH_B))["quantity"] == "9"
    discs = await env.coll.find(
        {"tenant_id": T, "action": "transit_discrepancy",
         "dispatch_movement_id": tr.movement_id}, {"_id": 0}).sort(
        "ledger_sequence", 1).to_list(None)
    assert [d["quantity"] for d in discs] == ["4", "1"]
    assert discs[-1]["total_value"] == "10.0000"
    transit = await db["warehouse_in_transit"].find_one({"dispatch_movement_id": tr.movement_id})
    assert transit["unresolved_quantity"] == "1"


async def test_f13_direct_transfer_is_refused_server_side(
        canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "10")
    # The old direct transfer: destination = the receiving warehouse.
    with pytest.raises(InvariantViolationError):
        await env.run(CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE, source=WH,
                      destination=WH_B, quantity=Decimal("4"))
    # Also with a target named: a non-transit destination is never accepted.
    with pytest.raises(InvariantViolationError):
        await env.run(CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE, source=WH,
                      destination=WH_B, transfer_target=WH_B, quantity=Decimal("4"))
    # No target / a non-warehouse target / the source itself.
    for target in (None, PRJ, WH,
                   LocationKey(LocationType.SMALL_WAREHOUSE, "wh_b",
                               state=MovementState.QUARANTINE)):
        with pytest.raises(InvariantViolationError):
            await env.run(CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE, source=WH,
                          transfer_target=target, quantity=Decimal("4"))
    assert await env.coll.count_documents(
        {"tenant_id": T, "action": "transfer_warehouse_to_warehouse"}) == 0
    assert (await env.stock(WH))["quantity"] == "10"
    assert (await env.stock(WH_B))["quantity"] == "0"


async def test_f13_direct_transfer_is_refused_over_http(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """The route maps the refusal to 422 INVARIANT_VIOLATION."""
    from fastapi import HTTPException
    from app.routes import warehouse_canonical as route
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "10")
    monkeypatch.setattr(route, "db", db)
    monkeypatch.setattr(route, "_service",
                        lambda: CommandService(client, gate=allow_always_gate))
    body = route.MovementCommandBody(
        action="transfer_warehouse_to_warehouse", item_id=ITEM, unit="bag",
        quantity="4", idempotency_key="http-direct",
        source={"location_type": "central_warehouse", "location_id": "wh_1"},
        destination={"location_type": "small_warehouse", "location_id": "wh_b"})
    with pytest.raises(HTTPException) as exc:
        await route.post_movement(body, request=None, user=_user(), ctx=_Ctx())
    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == "INVARIANT_VIOLATION"
    # And the Rule B shape goes through the same endpoint.
    body = route.MovementCommandBody(
        action="transfer_warehouse_to_warehouse", item_id=ITEM, unit="bag",
        quantity="4", idempotency_key="http-rule-b",
        source={"location_type": "central_warehouse", "location_id": "wh_1"},
        transfer_target={"location_type": "small_warehouse", "location_id": "wh_b"})
    res = await route.post_movement(body, request=None, user=_user(), ctx=_Ctx())
    assert res.envelope["destination"]["location_type"] == "in_transit"
    assert res.envelope["transfer_target"]["location_id"] == "wh_b"


async def test_f13_accept_must_land_in_the_transfer_target(
        canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "10")
    tr = await _transfer(env)
    for wrong in (LocationKey(LocationType.SMALL_WAREHOUSE, "wh_c"), PRJ, WH,
                  LocationKey(LocationType.SMALL_WAREHOUSE, "wh_b",
                              state=MovementState.QUARANTINE)):
        with pytest.raises(InvariantViolationError):
            await _accept(env, tr, "5", destination=wrong)
    with pytest.raises(InvariantViolationError):
        await _accept(env, tr, "5", project_id=PROJECT)
    assert await env.coll.count_documents(
        {"tenant_id": T, "action": "accept_project_delivery"}) == 0


async def test_f13_transfer_gate_sees_the_target_warehouse_scope(
        canonical_mongo_db, allow_always_gate):
    """Permission (C06) is evaluated on the target warehouse, not only on
    the in_transit bucket that carries no scope."""
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "10")
    seen = []

    class _DenyWhB:
        async def ensure(self, ctx, *, action, source, destination, project_id):
            seen.append(None if destination is None else destination.location_id)
            if destination is not None and destination.location_id == "wh_b":
                raise PermissionDeniedError("denied wh_b", context={})

    env.svc = CommandService(client, gate=_DenyWhB())
    with pytest.raises(PermissionDeniedError):
        await _transfer(env)
    assert seen == ["wh_b"]


async def test_f13_transfer_replay_and_target_conflict(
        canonical_mongo_db, allow_always_gate):
    """Same key + same target = replay; same key + another target = conflict."""
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "10")
    first = await _transfer(env, "4", idempotency_key="tr-1")
    again = await _transfer(env, "4", idempotency_key="tr-1")
    assert again.replay and again.movement_id == first.movement_id
    with pytest.raises(IdempotencyConflictError):
        await env.run(CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE, source=WH,
                      transfer_target=LocationKey(LocationType.SMALL_WAREHOUSE, "wh_c"),
                      quantity=Decimal("4"), idempotency_key="tr-1")
    assert await env.coll.count_documents(
        {"tenant_id": T, "action": "transfer_warehouse_to_warehouse"}) == 1


async def test_f13_rebuild_keeps_transfer_state(canonical_mongo_db, allow_always_gate):
    from app.services.warehouse_movements.projections import rebuild_from_ledger
    client, db = canonical_mongo_db
    env = _Env(client, allow_always_gate, db)
    await env.receive("10", "10")
    tr = await _transfer(env)
    await _accept(env, tr, "6")
    live = await db["warehouse_in_transit"].find_one(
        {"dispatch_movement_id": tr.movement_id}, {"_id": 0})
    await rebuild_from_ledger(db, tenant_id=T)
    rebuilt = await db["warehouse_in_transit"].find_one(
        {"dispatch_movement_id": tr.movement_id}, {"_id": 0})
    for k in ("unresolved_quantity", "accepted_quantity", "transfer_target"):
        assert rebuilt[k] == live[k], k
    assert set(rebuilt["unresolved_discrepancies"]) == set(live["unresolved_discrepancies"])


def test_f13_transfer_target_only_on_warehouse_transfers():
    from app.services.warehouse_movements.service import CommandService as S
    inp = _inp(CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, source=WH,
               transfer_target=WH_B)
    with pytest.raises(InvariantViolationError):
        S._force_transfer_into_transit(inp)


def test_f13_fingerprint_unchanged_without_transfer_target():
    """Every fingerprint without a target is byte-identical to before C21."""
    import hashlib
    import json
    from app.services.warehouse_movements.envelope import build_envelope, envelope_fingerprint
    env = build_envelope(
        tenant_id=T, action="receive_from_supplier", item_id="i", unit="bag",
        quantity=Decimal("1"), source=None, destination=WH, actor_id="u",
        idempotency_key="k", unit_value=Decimal("1"), currency="BGN", layer_allocations=[])
    payload = env.to_dict()
    for k in ("movement_id", "recorded_at", "occurred_at", "audit_event_id"):
        payload.pop(k, None)
    payload["confirmed_at"] = None
    legacy = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()
    assert envelope_fingerprint(env) == legacy
    assert envelope_fingerprint(env, transfer_target=WH_B.to_dict()) != legacy
