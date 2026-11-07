"""
5C-C26h — FLOW Guard pass 5 on 81e412c (Р28, FLOW-009, FLOW-002 scope, Р20).

  * FG-59 (HIGH): the project relation came from body.project_id — a
    SiteManager ran QUARANTINE_ENTRY at wh_1 with project_id=P1. The projects
    a command touches now come only from its locations (DB-resolved); a body
    project_id the locations do not name → 422.
  * FG-61: receive-to-project trusted body project_id — bound to the
    destination project now.
  * FG-60: an unfiltered balance / history / warnings list showed other
    projects' quantities to a project-bound reader — narrowed to its member
    projects (warehouse buckets only for warehouse / company roles).
  * FG-55: 422 vs 403 was a yes/no oracle — the rights check runs first; a
    refused binding answers 422 only to a caller with rights, and a denial
    never names the DB-resolved project.

Real Mongo (replica set); real company-scope grants (C26E-1).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.envelope import MovementState
from app.services.warehouse_movements.errors import (
    InvariantViolationError, PermissionDeniedError,
)
from app.services.warehouse_movements.service import CommandService
from app.tenancy.guard import LegacyCompatContext
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PRJ, PROJECT, T, WH, _inp, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP, _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    OTHER_PROJECT, USER, _UserCtx, _loader, _member,
)
from tests.test_warehouse_canonical_c26e_r28_all_modes import _count, _ctx, _real

pytest_plugins = ["tests.warehouse_canonical_conftest"]

MODES = ["off", "shadow", "enforce"]
P2_LOC = LocationKey(LocationType.PROJECT, OTHER_PROJECT)


async def _setup(client, gate, db, monkeypatch, role, mode, *, member=True):
    from app.permissions import service as perm
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_one({"id": OTHER_PROJECT, "org_id": T, "code": "P2",
                                     "name": "P2", "status": "Active"})
    run = _Run(client, gate, db)
    await run.receive("20", "10")
    d1 = await run.dispatch("5")
    await run.accept(d1, "5")
    d2 = await run.dispatch("4", project=OTHER_PROJECT)
    await run.accept(d2, "4", dest=P2_LOC, project=OTHER_PROJECT)
    if member:
        await _member(db)                                   # member of P1 only
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real(role)))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    return run


# ═══════════════════════════════ FG-59 ═══════════════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_fg59_body_project_id_grants_no_relation(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Member of P1, QUARANTINE_ENTRY at wh_1 with body project_id=P1.
    81e412c: ALLOWED. Now the command touches no project → 403
    R28_PROJECT_REQUIRED (rights first, FG-55), 0 rows."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, "site_manager", mode)
    before = await _count(db)
    with pytest.raises(PermissionDeniedError) as exc:
        await CommandService(client).execute(_ctx(mode, "SiteManager"), db, run.coll, _inp(
            CanonicalAction.QUARANTINE_ENTRY, T, quantity=Decimal("1"), source=WH,
            destination=LocationKey(WH.location_type, WH.location_id,
                                    state=MovementState.QUARANTINE),
            project_id=PROJECT))
    assert exc.value.context["reason_code"] == "R28_PROJECT_REQUIRED"
    assert await _count(db) == before


@pytest.mark.parametrize("mode", MODES)
async def test_fg59_project_id_that_no_location_names_is_422_for_a_rights_holder(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Owner (rights everywhere): quarantine at wh_1 with project_id=P1 → 422."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, "owner", mode,
                       member=False)
    before = await _count(db)
    with pytest.raises(InvariantViolationError):
        await CommandService(client).execute(_ctx(mode, "Owner"), db, run.coll, _inp(
            CanonicalAction.QUARANTINE_ENTRY, T, quantity=Decimal("1"), source=WH,
            destination=LocationKey(WH.location_type, WH.location_id,
                                    state=MovementState.QUARANTINE),
            project_id=PROJECT))
    assert await _count(db) == before


# ═══════════════════════════════ FG-61 ═══════════════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_fg61_receive_to_project_is_bound_to_the_destination(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Owner: receive to P1 with body project_id=P2 → 422; without it the
    movement carries P1 (the destination)."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, "owner", mode,
                       member=False)
    svc = CommandService(client)
    kw = dict(source=SUP, destination=PRJ, quantity=Decimal("2"), unit_value=Decimal("10"))
    with pytest.raises(InvariantViolationError):
        await svc.execute(_ctx(mode, "Owner"), db, run.coll, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, T, project_id=OTHER_PROJECT,
            **kw))
    res = await svc.execute(_ctx(mode, "Owner"), db, run.coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, T, **kw))
    assert res.envelope["project_id"] == PROJECT


# ═══════════════════════════════ FG-60 ═══════════════════════════════

async def _reads(q, mode, role, legacy_role):
    if mode == "enforce":
        ctx = _UserCtx()
        ctx.mode = "enforce"
    else:
        ctx = LegacyCompatContext({"id": USER, "org_id": T, "role": legacy_role}, mode=mode)
    bal = await q.read_balance_by_location(ITEM, ctx=ctx)
    hist = await q.read_history(item_id=ITEM, location_type=None, location_id=None,
                                project_id=None, since=None, until=None, limit=1000,
                                cursor_after=None, ctx=ctx)
    return bal, hist


def _projects_in(bal, hist):
    def _p(loc):
        return loc.get("location_id") if (loc or {}).get("location_type") == "project" else None
    in_bal = {b["location_id"] for b in bal["balances"] if b["location_type"] == "project"}
    in_hist = set()
    for r in hist["rows"]:
        for x in (r.get("project_id"), _p(r.get("source")), _p(r.get("destination"))):
            if x:
                in_hist.add(x)
    other = {b["location_type"] for b in bal["balances"]} - {"project"}
    return in_bal, in_hist, other


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("member", [True, False])
async def test_fg60_unfiltered_reads_show_only_member_projects(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, member):
    """SiteManager (member of P1 / of nothing): balance and an unfiltered
    history show P1 only / nothing — never P2, never the warehouse.
    81e412c: P1 + P2 + warehouse to everyone with read_stock."""
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, "site_manager", mode,
                 member=member)
    monkeypatch.setattr(q, "db", db)
    bal, hist = await _reads(q, mode, "site_manager", "SiteManager")
    in_bal, in_hist, other = _projects_in(bal, hist)
    want = {PROJECT} if member else set()
    # 5C-C26j — Р35: the central warehouse rows are readable too.
    assert in_bal == want and in_hist <= want and other <= {"central_warehouse"}
    if member:
        assert PROJECT in in_hist
    assert all(OTHER_PROJECT not in str(r) for r in hist["rows"])


@pytest.mark.parametrize("mode", MODES)
async def test_fg60_warehouse_and_company_roles_still_see_everything(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, "warehouse", mode,
                 member=False)
    monkeypatch.setattr(q, "db", db)
    bal, hist = await _reads(q, mode, "warehouse", "Warehousekeeper")
    in_bal, in_hist, other = _projects_in(bal, hist)
    assert in_bal == {PROJECT, OTHER_PROJECT} and "central_warehouse" in other


# ═══════════════════════════════ FG-55 ═══════════════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_fg55_no_oracle_without_rights(canonical_mongo_db, allow_always_gate,
                                            monkeypatch, mode):
    """A SiteManager who is NOT on P2: consume from P2 with a wrong body
    project_id, and an acceptance into an unknown subproject, both get the
    same 403 as a correct request would — never a 422 that confirms the
    relation, and the denial never names a DB-resolved project."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch, "site_manager", mode)
    svc = CommandService(client)
    ctx = _ctx(mode, "SiteManager")
    for kw in (dict(source=P2_LOC, project_id=PROJECT, smr_id="s"),
               dict(source=P2_LOC, smr_id="s")):
        with pytest.raises(PermissionDeniedError) as exc:
            await svc.execute(ctx, db, run.coll, _inp(
                CanonicalAction.CONSUME_TO_SMR, T, quantity=Decimal("1"), **kw))
        assert exc.value.context["reason_code"] in (
            "R28_PROJECT_RELATION_REQUIRED", "R28_LEGACY_ROLE_NOT_ALLOWED")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "enforce")   # setup (test harness ctx)
    disp = await run.dispatch("1")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    with pytest.raises(PermissionDeniedError) as exc:
        await svc.execute(ctx, db, run.coll, _inp(
            CanonicalAction.ACCEPT_PROJECT_DELIVERY, T, quantity=Decimal("1"),
            destination=LocationKey(LocationType.SUBPROJECT, "s-unknown"),
            accepted_quantity=Decimal("1"), dispatch_movement_id=disp.movement_id))
    assert "parent_project_id" not in exc.value.context
