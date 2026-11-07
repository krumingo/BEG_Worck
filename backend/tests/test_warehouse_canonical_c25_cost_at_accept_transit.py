"""LIVE-OPS-01 / TASK 5C — 5C-C25: cost at acceptance (Р17), every move in
transit and returns through quarantine (Р18), FLOW Guard FG-17 / FG-19.

Package: ``docs/architecture/tasks/5C-C25_COST_AT_ACCEPT_AND_FLOW_GUARD.md``
(branch ``claude/happy-meitner-bmcnel``). Decisions Р9, Р17, Р18 (Крум,
06.11.2026) in ``docs/architecture/RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md``.
FLOW Guard: ``docs/flow-guard/DIVERGENCES.md`` @ ``claude/flow-guard``.

  * Р17 — project material cost is recognised at ACCEPT, for the whole
    accepted quantity, at the exact FIFO layers of 5C-C24. A return to a
    warehouse reduces it. CONSUME_TO_SMR only allocates it (packages,
    budgets) — never a second cost. „фира" (Р10) stays its own line.
  * Р18 — project→project, project→warehouse (and warehouse→warehouse,
    Р11) go "в път" and land only on acceptance; a direct move is refused
    by the server; a return lands in the warehouse QUARANTINE first and is
    reusable only after a quarantine release.
  * FG-17 — the P&L reads only the shared helper (no max(invoice, warehouse)).
  * FG-19 — an acceptance always drains its own in-transit bucket.

Real MongoDB replica set, real CommandService, PERMISSION_SERVICE_MODE=enforce.
Run:
    WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 PERMISSION_SERVICE_MODE=enforce \\
    MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \\
    PYTHONPATH=. pytest -q tests/test_warehouse_canonical_c25_cost_at_accept_transit.py
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.canonical_material_cost import project_material_cost
from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
)
from app.services.warehouse_movements.errors import (
    InvariantViolationError, NegativeStockError, QuarantineStateViolationError,
)
from app.services.warehouse_movements.projections import rebuild_from_ledger
from app.services.warehouse_movements.queries import item_balance_by_location, stock_at
from app.services.warehouse_movements.service import CommandService
from app.tenancy.data_access import TenantData
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PACKAGE_LEVEL, PKG, PRJ, PROJECT, T, T2, WH, _all_reports, _assert_all,
    _Ctx, _inp, _patch_dbs, _seed, _user,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]

SUP = LocationKey(LocationType.SUPPLIER, "sup_c25")
WH_Q = LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1", state=MovementState.QUARANTINE)
WH_B = LocationKey(LocationType.SMALL_WAREHOUSE, "wh_b")
PROJECT_B = "p-c25-b"
PRJ_B = LocationKey(LocationType.PROJECT, PROJECT_B)
PENDING = LocationKey(LocationType.IN_TRANSIT, "pending", state=MovementState.IN_TRANSIT)


class _Run:
    def __init__(self, client, gate, db, tenant=T):
        import os
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        self.db = db
        self.tenant = tenant
        self.tenant_data = TenantData.for_resolved_org(db, tenant)
        self.coll = self.tenant_data.warehouse_transactions
        self.svc = CommandService(client, gate=gate)
        self.ctx = _Ctx(tenant)

    async def __call__(self, action, **kw):
        return await self.svc.execute(self.ctx, self.db, self.coll,
                                      _inp(action, self.tenant, **kw))

    async def receive(self, qty="10", price="10", at=WH):
        return await self(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP,
                          destination=at, quantity=Decimal(qty), unit_value=Decimal(price))

    async def dispatch(self, qty, project=PROJECT):
        return await self(CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, source=WH,
                          quantity=Decimal(qty), project_id=project)

    async def accept(self, dispatch, qty, dest=PRJ, project=PROJECT, **kw):
        return await self(CanonicalAction.ACCEPT_PROJECT_DELIVERY, destination=dest,
                          quantity=Decimal(qty), accepted_quantity=Decimal(qty),
                          dispatch_movement_id=dispatch.movement_id,
                          project_id=project, **kw)

    async def consume(self, qty, source=PRJ, project=PROJECT):
        return await self(CanonicalAction.CONSUME_TO_SMR, source=source,
                          quantity=Decimal(qty), project_id=project, smr_id="smr-c25")

    async def write_off(self, qty):
        return await self(CanonicalAction.WRITE_OFF, source=PRJ, quantity=Decimal(qty),
                          reason="брак", file_ids=["f-c25"])

    async def return_to_warehouse(self, qty, target=WH_Q, **kw):
        return await self(CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE, source=PRJ,
                          transfer_target=target, quantity=Decimal(qty),
                          project_id=PROJECT, **kw)

    async def transfer_to_project(self, qty, target=PRJ_B, **kw):
        return await self(CanonicalAction.TRANSFER_PROJECT_TO_PROJECT, source=PRJ,
                          transfer_target=target, quantity=Decimal(qty),
                          project_id=PROJECT, **kw)

    async def stock(self, loc):
        return await stock_at(self.coll, tenant_id=self.tenant, item_id=ITEM, location=loc)

    async def cost(self, project=PROJECT):
        return await project_material_cost(self.tenant_data, self.tenant, project)

    async def balances(self):
        rows = await item_balance_by_location(self.coll, tenant_id=self.tenant, item_id=ITEM)
        return {(r["location_type"], r["location_id"], r["state"]): Decimal(r["quantity"])
                for r in rows}


async def _accepted_10(run):
    """receive 10 @10 → dispatch 10 → accept 10 on the project (= 100)."""
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    return await run.accept(disp, "10")


def _project_totals(reports):
    return {k: v[0] for k, v in reports.items() if k not in PACKAGE_LEVEL}


# ═════════════════════════════ Р17 — cost at ACCEPT ═════════════════════════════

async def test_r17_accept_10_return_3_costs_7_times_price_on_every_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Accept 10 @10 = 100 → return 3 → 70 everywhere (dbda909: 0, consumption-only)."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    _assert_all(await _all_reports(), 100.0, 0.0, package_total=0.0)

    ret = await run.return_to_warehouse("3")
    # In transit: the project still carries the lot (credited only on accept).
    assert (await run.cost())["total_cost"] == pytest.approx(100.0)
    await run.accept(ret, "3", dest=WH_Q, project=None)
    reports = await _all_reports()
    _assert_all(reports, 70.0, 0.0, package_total=0.0)
    assert len(reports) == 16

    cost = await run.cost()
    assert cost["accepted_cost"] == pytest.approx(100.0)
    assert cost["returned_cost"] == pytest.approx(30.0)
    assert cost["total_cost"] == pytest.approx(7 * 10.0)
    assert cost["cost_rule"] == "R17_cost_at_acceptance"
    rows = await db["material_entries"].find(
        {"org_id": T, "cost_recognized": True}, {"_id": 0}).to_list(None)
    assert sorted((r["movement_kind"], float(r["total_value"])) for r in rows) == \
        [("accept", 100.0), ("return", -30.0)]
    # The physical side agrees: 7 on the project, 3 in warehouse quarantine.
    assert Decimal((await run.stock(PRJ))["total_value"]) == Decimal("70")
    assert Decimal((await run.stock(WH_Q))["total_value"]) == Decimal("30")


async def test_r17_consumption_adds_no_cost(canonical_mongo_db, allow_always_gate, monkeypatch):
    """Accept 5 @10 → 50; consume 3 → still 50 on every project report; the
    packages show the 30 allocated (allocation only) and 20 is unallocated."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("5")
    await run.accept(disp, "5")
    before = _project_totals(await _all_reports())
    assert before == {k: pytest.approx(50.0) for k in before}       # dbda909: 0
    await run.consume("3")
    reports = await _all_reports()
    assert _project_totals(reports) == before                       # dbda909: 30
    _assert_all(reports, 50.0, 0.0, package_total=30.0)
    cost = await run.cost()
    assert cost["consumed_value"] == pytest.approx(30.0)
    assert cost["allocated_cost"] + cost["unallocated_cost"] == pytest.approx(50.0)
    consume_rows = await db["material_entries"].find(
        {"org_id": T, "movement_kind": "consume"}, {"_id": 0}).to_list(None)
    assert len(consume_rows) == 1
    assert consume_rows[0]["cost_recognized"] is False
    assert float(consume_rows[0]["total_value"]) == 0.0
    assert float(consume_rows[0]["movement_value"]) == pytest.approx(30.0)
    # Consuming everything changes no project number either.
    await run.consume("2")
    _assert_all(await _all_reports(), 50.0, 0.0)


async def test_r17_every_report_shows_one_number_with_fira_return_and_invoice(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """accept 10 (100) → consume 3 → write-off 2 („фира" 20) → return 3 (−30)
    + a Path B invoice line 40 → 110 on every project report, „фира" 20;
    package = consumed 30 + фира 20 = 50; FG-17: the P&L is the same 110."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    await _seed(db)
    await db["invoice_lines"].insert_one({
        "id": "il-c25", "org_id": T, "allocation_type": "project",
        "allocation_ref_id": PROJECT, "line_total_ex_vat": 40.0, "vat_amount": 8.0,
        "description": "Лепило (директно)", "qty": 4, "created_at": "2026-11-01T10:00:00+00:00"})
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    await run.consume("3")
    await run.write_off("2")
    ret = await run.return_to_warehouse("3")
    await run.accept(ret, "3", dest=WH_Q, project=None)
    reports = await _all_reports()
    _assert_all(reports, 110.0, 20.0, package_total=50.0)
    from app.routes import project_pnl
    pnl = await project_pnl.get_project_pnl(PROJECT, user=_user())
    assert pnl["expense"]["material_cost"] == pytest.approx(90.0)
    assert pnl["expense"]["material_waste_cost"] == pytest.approx(20.0)
    basis = pnl["warehouse_cost_basis"]
    assert basis["invoice_cost"] == pytest.approx(40.0)
    assert basis["warehouse_material_cost"] == pytest.approx(110.0)
    assert basis["accepted_cost"] == pytest.approx(100.0)
    assert basis["returned_cost"] == pytest.approx(30.0)
    assert pnl["vat"]["input_vat"] == pytest.approx(8.0)
    # The helper invariant behind all of them.
    cost = await run.cost()
    assert cost["allocated_cost"] + cost["unallocated_cost"] == pytest.approx(cost["total_cost"])
    assert cost["unallocated_cost"] == pytest.approx(60.0)   # 2 on site + the invoice 40


async def test_fg17_pnl_has_no_max_and_matches_net_profit(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """FG-17 probe data: invoice line 100 + consume 30 + write-off 20.
    53dbd28/dbda909: P&L max(100, 50) → 100 vs net-profit 50. Now one sum:
    invoice 100 + accepted 50 = 150 everywhere, „фира" 20."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    await _seed(db)
    await db["invoice_lines"].insert_one({
        "id": "il-fg17", "org_id": T, "allocation_type": "project",
        "allocation_ref_id": PROJECT, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
        "description": "фактурен ред", "created_at": "2026-11-01T10:00:00+00:00"})
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("5")
    await run.accept(disp, "5")
    await run.consume("3")
    await run.write_off("2")
    reports = await _all_reports()
    project_level = _project_totals(reports)
    assert project_level == {k: pytest.approx(150.0) for k in project_level}
    assert reports["pnl"] == (pytest.approx(150.0), pytest.approx(20.0))
    assert reports["net_profit"] == reports["pnl"]
    src = __import__("inspect").getsource(
        __import__("app.services.project_pnl", fromlist=["x"]).compute_project_pnl)
    assert "max(material_cost_invoices" not in src


async def test_fg17_invoice_line_linked_to_a_canonical_receipt_is_counted_once(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """A direct delivery that carries its invoice line (invoice_line_id) is the
    same lot: counted once, through the canon; the invoice line is reported
    as linked-excluded."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["invoice_lines"].insert_one({
        "id": "il-linked", "org_id": T, "allocation_type": "project",
        "allocation_ref_id": PROJECT, "line_total_ex_vat": 30.0,
        "created_at": "2026-11-01T10:00:00+00:00"})
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP,
              destination=PRJ, quantity=Decimal("3"), unit_value=Decimal("10"),
              project_id=PROJECT, invoice_line_id="il-linked")
    cost = await run.cost()
    assert cost["total_cost"] == pytest.approx(30.0)
    assert cost["invoice_cost"] == 0
    assert cost["invoice_linked_excluded_cost"] == pytest.approx(30.0)
    project_level = _project_totals(await _all_reports())
    assert project_level == {k: pytest.approx(30.0) for k in project_level}


# ═══════════════════ Р18 — every move in transit, returns in quarantine ═══════════════════

async def test_r18_return_goes_through_transit_and_quarantine_before_reuse(
        canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    ret = await run.return_to_warehouse("3")
    assert ret.envelope["destination"]["location_type"] == "in_transit"
    assert ret.envelope["transfer_target"] == WH_Q.to_dict()
    # Not in the warehouse yet — neither free nor quarantine.
    assert (await run.stock(WH))["quantity"] == "0"
    assert (await run.stock(WH_Q))["quantity"] == "0"
    bal = await run.balances()
    assert bal[("in_transit", ret.movement_id, "in_transit")] == Decimal("3")

    # It cannot be accepted into free stock — quarantine first (Р18).
    with pytest.raises(QuarantineStateViolationError):
        await run.accept(ret, "3", dest=WH, project=None)
    acc = await run.accept(ret, "3", dest=WH_Q, project=None)
    assert acc.envelope["source"] == {"location_type": "in_transit",
                                      "location_id": ret.movement_id,
                                      "state": "in_transit"}
    assert Decimal((await run.stock(WH_Q))["quantity"]) == Decimal("3")
    assert (await run.stock(WH))["quantity"] == "0"
    # Quarantined stock cannot be reused: a dispatch from free stock fails.
    with pytest.raises(NegativeStockError):
        await run.dispatch("1")
    # Release after the quality check: value and layers are conserved.
    rel = await run(CanonicalAction.QUARANTINE_RELEASE, source=WH_Q, destination=WH,
                    quantity=Decimal("3"))
    assert Decimal(rel.envelope["unit_value"]) == Decimal("10")
    free = await run.stock(WH)
    assert Decimal(free["quantity"]) == Decimal("3")
    assert Decimal(free["total_value"]) == Decimal("30")       # dbda909: released at 0
    assert (await run.stock(WH_Q))["quantity"] == "0"
    disp = await run.dispatch("1")                              # reusable now
    assert disp.movement_id
    # Batches agree with the ledger after the whole cycle and after a rebuild.
    live = await _batches(db)
    await rebuild_from_ledger(db, tenant_id=T)
    assert await _batches(db) == live


async def test_r18_direct_return_and_target_states_are_refused(
        canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    # The old direct return: destination = the warehouse (free or quarantine).
    for dest in (WH, WH_Q):
        with pytest.raises(InvariantViolationError):
            await run(CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE, source=PRJ,
                      destination=dest, quantity=Decimal("3"), project_id=PROJECT)
    # A return into free stock (skipping quarantine) is refused.
    with pytest.raises(QuarantineStateViolationError):
        await run.return_to_warehouse("3", target=WH)
    # No target / a project as target.
    for target in (None, PRJ_B):
        with pytest.raises(InvariantViolationError):
            await run.return_to_warehouse("3", target=target)
    # A quarantine entry may not move stock from the project to a warehouse.
    with pytest.raises(InvariantViolationError):
        await run(CanonicalAction.QUARANTINE_ENTRY, source=PRJ, destination=WH_Q,
                  quantity=Decimal("3"), project_id=PROJECT)
    # Nor may a release move it to another location.
    with pytest.raises(InvariantViolationError):
        await run(CanonicalAction.QUARANTINE_RELEASE, source=WH_Q, destination=WH_B,
                  quantity=Decimal("1"))
    assert await run.coll.count_documents(
        {"tenant_id": T, "action": {"$in": ["transfer_project_to_warehouse",
                                            "quarantine_entry", "quarantine_release"]}}) == 0
    assert (await run.stock(PRJ))["quantity"] == "10"


async def test_r18_project_to_project_goes_in_transit_and_moves_cost_on_accept(
        canonical_mongo_db, allow_always_gate):
    """Transfer 4 from A to B: B gets nothing and A keeps the cost until B
    accepts; B accepts 3 → A 70, B 30; the 1 unit still in transit stays A's
    cost (an open discrepancy is visible)."""
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    with pytest.raises(InvariantViolationError):           # dbda909: direct credit
        await run(CanonicalAction.TRANSFER_PROJECT_TO_PROJECT, source=PRJ,
                  destination=PRJ_B, quantity=Decimal("4"), project_id=PROJECT)
    tr = await run.transfer_to_project("4")
    assert tr.envelope["destination"]["location_type"] == "in_transit"
    assert (await run.stock(PRJ_B))["quantity"] == "0"
    assert (await run.cost(PROJECT_B))["total_cost"] == 0
    assert (await run.cost())["total_cost"] == pytest.approx(100.0)

    # It must land in exactly its target, and it carries that project.
    with pytest.raises(InvariantViolationError):
        await run.accept(tr, "3", dest=PRJ, project=PROJECT)
    acc = await run.accept(tr, "3", dest=PRJ_B, project=None)
    assert acc.envelope["project_id"] == PROJECT_B
    assert acc.unresolved_discrepancy_movement_id
    assert (await run.cost())["total_cost"] == pytest.approx(70.0)
    assert (await run.cost(PROJECT_B))["total_cost"] == pytest.approx(30.0)
    assert Decimal((await run.stock(PRJ_B))["total_value"]) == Decimal("30")
    bal = await run.balances()
    assert bal[("in_transit", tr.movement_id, "in_transit")] == Decimal("1")
    # B uses it: no new cost on B.
    await run.consume("2", source=PRJ_B, project=PROJECT_B)
    assert (await run.cost(PROJECT_B))["total_cost"] == pytest.approx(30.0)
    # The last unit arrives: A 60, B 40; nothing left in transit.
    await run.accept(tr, "1", dest=PRJ_B, project=PROJECT_B)
    assert (await run.cost())["total_cost"] == pytest.approx(60.0)
    assert (await run.cost(PROJECT_B))["total_cost"] == pytest.approx(40.0)
    assert ("in_transit", tr.movement_id, "in_transit") not in await run.balances()


async def test_r18_every_transfer_kind_goes_in_transit(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    await run.receive("5", "10")
    kinds = {
        CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE: dict(source=WH, transfer_target=WH_B),
        CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE: dict(source=PRJ, transfer_target=WH_Q,
                                                            project_id=PROJECT),
        CanonicalAction.TRANSFER_PROJECT_TO_PROJECT: dict(source=PRJ, transfer_target=PRJ_B,
                                                          project_id=PROJECT),
    }
    for action, kw in kinds.items():
        target = kw["transfer_target"]
        before = Decimal((await run.stock(target))["quantity"])
        res = await run(action, quantity=Decimal("1"), **kw)
        assert res.envelope["destination"]["location_type"] == "in_transit", action
        assert res.envelope["destination"]["location_id"] == res.movement_id, action
        assert Decimal((await run.stock(target))["quantity"]) == before, action
        # A direct destination is refused for every kind (server side).
        with pytest.raises(InvariantViolationError):
            await run(action, quantity=Decimal("1"),
                      destination=target, **{k: v for k, v in kw.items()
                                             if k != "transfer_target"})
        acc = await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY, destination=target,
                        quantity=Decimal("1"), accepted_quantity=Decimal("1"),
                        dispatch_movement_id=res.movement_id)
        assert acc.envelope["source"]["location_id"] == res.movement_id
        assert Decimal((await run.stock(target))["quantity"]) == before + 1, action
    assert not [k for k in await run.balances() if k[0] == "in_transit"]


async def test_r18_direct_return_is_refused_over_http(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from fastapi import HTTPException
    from app.routes import warehouse_canonical as route
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    monkeypatch.setattr(route, "db", db)
    monkeypatch.setattr(route, "_service",
                        lambda: CommandService(client, gate=allow_always_gate))
    common = dict(item_id=ITEM, unit="bag", quantity="3",
                  source={"location_type": "project", "location_id": PROJECT},
                  project_id=PROJECT)
    for key, extra, code in (
        ("http-direct", {"destination": {"location_type": "central_warehouse",
                                         "location_id": "wh_1"}}, "INVARIANT_VIOLATION"),
        ("http-free", {"transfer_target": {"location_type": "central_warehouse",
                                           "location_id": "wh_1"}},
         "QUARANTINE_STATE_VIOLATION"),
    ):
        body = route.MovementCommandBody(action="transfer_project_to_warehouse",
                                         idempotency_key=key, **common, **extra)
        with pytest.raises(HTTPException) as exc:
            await route.post_movement(body, request=None, user=_user(), ctx=_Ctx())
        assert exc.value.status_code == 422
        assert exc.value.detail["error_code"] == code
    body = route.MovementCommandBody(
        action="transfer_project_to_warehouse", idempotency_key="http-ok",
        transfer_target={"location_type": "central_warehouse", "location_id": "wh_1",
                         "state": "quarantine"}, **common)
    res = await route.post_movement(body, request=None, user=_user(), ctx=_Ctx())
    assert res.envelope["destination"]["location_type"] == "in_transit"


async def test_r18_transfer_gate_sees_the_target_scope(canonical_mongo_db, allow_always_gate):
    """The permission gate checks the TARGET location of a project transfer
    (the row itself goes to in_transit)."""
    from app.services.warehouse_movements.errors import PermissionDeniedError
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    seen = []

    class _DenyB:
        async def ensure(self, ctx, *, action, source, destination, project_id):
            seen.append((action.value, destination.location_id if destination else None))
            if destination is not None and destination.location_id == PROJECT_B:
                raise PermissionDeniedError("no scope on B", context={})

    run.svc = CommandService(client, gate=_DenyB())
    with pytest.raises(PermissionDeniedError):
        await run.transfer_to_project("1")
    assert seen == [("transfer_project_to_project", PROJECT_B)]


# ═══════════════════════════ FG-19 — no phantom "в път" ═══════════════════════════

async def test_fg19_acceptance_without_source_drains_transit(
        canonical_mongo_db, allow_always_gate):
    """FG-19 probe: accept 10, send 5, accept 5 (no source), consume 3 →
    warehouse 5 + project 2 = 7, nothing in transit (dbda909: 12)."""
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("5")
    await run.accept(disp, "5")                       # no source given
    await run.consume("3")
    bal = await run.balances()
    assert bal == {("central_warehouse", "wh_1", "free"): Decimal("5"),
                   ("project", PROJECT, "free"): Decimal("2")}
    assert sum(bal.values()) == Decimal("7")
    # A client source naming anything but the dispatch's transit is refused.
    disp2 = await run.dispatch("1")
    with pytest.raises(InvariantViolationError):
        await run.accept(disp2, "1", source=WH)


# ═══════════════════════════ rebuild ×2 / sync parity ═══════════════════════════

async def _batches(db):
    return sorted([(b["movement_id"], b["layer_sequence"], str(b["quantity"]),
                    str(b["remaining_quantity"]), str(b["unit_value"]),
                    (b.get("location") or {}).get("state"))
                   async for b in db["warehouse_batches"].find(
                       {"tenant_id": T, "projection_source": "canonical_warehouse_service"})])


async def _entries(db):
    return await db["material_entries"].find(
        {"tenant_id": T, "projection_source": "canonical_warehouse_service"},
        {"_id": 0, "execution_package_id": 0, "planned_material_id": 0,
         "offer_line_id": 0, "material_name": 0, "mapped": 0, "ledger_sequence": 0},
    ).sort("id", 1).to_list(None)


async def _transit(db):
    return await db["warehouse_in_transit"].find(
        {"tenant_id": T}, {"_id": 0}).sort("dispatch_movement_id", 1).to_list(None)


async def test_rebuild_twice_and_sync_keep_the_r17_r18_numbers(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_smr
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("4", "1")
    await run.receive("6", "3")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")                        # 4@1 + 6@3 = 22
    await run.consume("3")                              # 3@1 = 3 (allocation)
    await run.write_off("2")                            # 1@1 + 1@3 = 4 („фира")
    ret = await run.return_to_warehouse("2")            # 2@3 = 6
    await run.accept(ret, "2", dest=WH_Q, project=None)
    tr = await run.transfer_to_project("2")             # 2@3 = 6
    await run.accept(tr, "1", dest=PRJ_B, project=PROJECT_B)
    await run(CanonicalAction.QUARANTINE_RELEASE, source=WH_Q, destination=WH,
              quantity=Decimal("2"))

    async def _numbers():
        a, b = await run.cost(), await run.cost(PROJECT_B)
        return (a["total_cost"], a["waste_cost"], a["returned_cost"],
                b["total_cost"], (await run.stock(WH))["total_value"],
                (await run.stock(PRJ))["total_value"], await _all_reports())

    before = await _numbers()
    # 22 accepted − 6 returned − 3 accepted on B = 13 (фира 4); B: 3.
    # returned_cost = every lot accepted away from A (6 + 3).
    assert before[:5] == (pytest.approx(13.0), pytest.approx(4.0), pytest.approx(9.0),
                          pytest.approx(3.0), "6.0000")
    # A holds 1@3 = 3; A's cost 13 = 3 on site + 7 allocated (3 consumed +
    # фира 4) + 3 still in transit to B (stays A's until B accepts it).
    assert Decimal(before[5]) == Decimal("3")
    live = (await _batches(db), await _entries(db), await _transit(db))
    await rebuild_from_ledger(db, tenant_id=T)
    first = (await _batches(db), await _entries(db), await _transit(db))
    await rebuild_from_ledger(db, tenant_id=T)
    second = (await _batches(db), await _entries(db), await _transit(db))
    assert live == first == second
    assert await _numbers() == before
    await material_smr.sync_material_entries(PROJECT, user=_user())
    await material_smr.sync_material_entries(PROJECT_B, user=_user())
    assert await _numbers() == before
    await material_smr.recompute_execution_package_material(PROJECT, user=_user())
    assert await _numbers() == before


async def test_r17_r18_are_tenant_scoped(canonical_mongo_db, allow_always_gate, monkeypatch):
    """Tenant B cannot accept tenant A's transfer, and sees none of A's cost."""
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await _accepted_10(run)
    tr = await run.transfer_to_project("2")
    other = _Run(client, allow_always_gate, db, tenant=T2)
    with pytest.raises(Exception):
        await other.accept(tr, "2", dest=PRJ_B, project=PROJECT_B)
    assert (await other.cost(PROJECT_B))["total_cost"] == 0
    assert (await other.cost())["total_cost"] == 0
    assert (await run.cost())["total_cost"] == pytest.approx(100.0)


# ═══════════════ Addendum A — Р21: partial accept per batch price ═══════════════

async def test_r21_partial_accept_takes_dispatched_layers_oldest_first_f5(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Audit probe F-5 (three prices). receive 7000@1 + 11000@2.5 + 5000@3.33;
    dispatch 15000 (= 7000@1 + 8000@2.5 = 27000); accept 9000 + 6000; consume
    10000; write-off 5000 from the project.
    Р21: accept 9000 = 7000@1 + 2000@2.5 (dbda909 pro-rata: 4200@1 + 4800@2.5);
    consume = 7000@1 + 3000@2.5 = 14500; „фира" = 5000@2.5 = 12500 (pro-rata:
    9800); project cost 27000 unchanged; rebuild ×2 and sync stable."""
    from app.routes import material_smr
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("7000", "1")
    await run.receive("11000", "2.5")
    await run.receive("5000", "3.33")
    disp = await run.dispatch("15000")
    a1 = await run.accept(disp, "9000", requested_quantity=Decimal("15000"))
    assert [(Decimal(a["quantity"]), Decimal(a["unit_value"]))
            for a in a1.envelope["layer_allocations"]] == \
        [(Decimal("7000"), Decimal("1")), (Decimal("2000"), Decimal("2.5"))]
    # The unresolved remainder keeps the leftover layer: 6000@2.5.
    disc = await db["warehouse_transactions"].find_one(
        {"movement_id": a1.unresolved_discrepancy_movement_id}, {"_id": 0})
    assert [(Decimal(a["quantity"]), Decimal(a["unit_value"]))
            for a in disc["layer_allocations"]] == [(Decimal("6000"), Decimal("2.5"))]
    assert Decimal(disc["total_value"]) == Decimal("15000")
    a2 = await run.accept(disp, "6000", requested_quantity=Decimal("15000"))
    assert [(Decimal(a["quantity"]), Decimal(a["unit_value"]))
            for a in a2.envelope["layer_allocations"]] == [(Decimal("6000"), Decimal("2.5"))]
    c = await run.consume("10000")
    w = await run.write_off("5000")
    from app.services.warehouse_movements.fifo import allocations_value
    assert allocations_value(c.envelope["layer_allocations"]) == Decimal("14500")
    assert allocations_value(w.envelope["layer_allocations"]) == Decimal("12500")

    async def _numbers():
        cost = await run.cost()
        return (cost["total_cost"], cost["waste_cost"], cost["consumed_value"],
                (await run.stock(WH))["total_value"], await _all_reports())

    before = await _numbers()
    assert before[:4] == (pytest.approx(27000.0), pytest.approx(12500.0),
                          pytest.approx(14500.0), "24150.0000")
    _assert_all(before[4], 27000.0, 12500.0)
    live = (await _batches(db), await _entries(db), await _transit(db))
    await rebuild_from_ledger(db, tenant_id=T)
    first = (await _batches(db), await _entries(db), await _transit(db))
    await rebuild_from_ledger(db, tenant_id=T)
    second = (await _batches(db), await _entries(db), await _transit(db))
    assert live == first == second
    await material_smr.sync_material_entries(PROJECT, user=_user())
    assert await _numbers() == before


async def test_r21_simple_divisible_partials_do_not_drift(
        canonical_mongo_db, allow_always_gate):
    """dispatch 10 = 6@10 + 4@20; accept 5 + 3 + 2 → 5@10 | 1@10 + 2@20 | 2@20:
    exact per batch price, 140 in total, no rounding drift; every layer used
    exactly up to its dispatched quantity."""
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await run.receive("6", "10")
    await run.receive("4", "20")
    disp = await run.dispatch("10")
    got = []
    for q in ("5", "3", "2"):
        acc = await run.accept(disp, q, requested_quantity=Decimal("10"))
        got.append([(Decimal(a["quantity"]), Decimal(a["unit_value"]))
                    for a in acc.envelope["layer_allocations"]])
    assert got == [[(Decimal("5"), Decimal("10"))],
                   [(Decimal("1"), Decimal("10")), (Decimal("2"), Decimal("20"))],
                   [(Decimal("2"), Decimal("20"))]]
    assert (await run.cost())["total_cost"] == pytest.approx(140.0)
    assert Decimal((await run.stock(PRJ))["total_value"]) == Decimal("140")
    assert not [k for k in await run.balances() if k[0] == "in_transit"]
