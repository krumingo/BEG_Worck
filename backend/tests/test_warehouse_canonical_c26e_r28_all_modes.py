"""
5C-C26e — Р28 (Крум 06.11.2026): the canonical warehouse writes in off /
shadow / enforce, and every command's rights are decided the same way in
all three (off / shadow: legacy session role → same catalog rules,
legacy_gate; enforce: RoleAssignments). Р30: a PM's own project is one where
the team row names them the manager. C26D-L1: a project → subproject-of-
another-project transfer with project_id = the source project is accepted.

Full matrix: 9 role cases × 9 warehouse commands × 3 modes. The expected
outcome per role is written out below by hand (from the catalog and Р27),
NOT computed by the code under test. Every refusal writes nothing.
Real Mongo (replica set).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.envelope import MovementState
from app.services.warehouse_movements.errors import PermissionDeniedError
from app.services.warehouse_movements.service import CommandService
from app.tenancy.guard import LegacyCompatContext
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    PRJ, PROJECT, T, WH, _inp, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP, _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    OTHER_PROJECT, USER, _UserCtx, _assignment, _loader, _member,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]

WH_Q = LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh_1", state=MovementState.QUARANTINE)
WH_B = LocationKey(LocationType.SMALL_WAREHOUSE, "wh_b")

COMMANDS = ["receive", "receive_to_project", "dispatch", "accept", "consume",
            "write_off_warehouse", "write_off_project", "return_to_warehouse",
            "transfer_w2w"]
ALL = set(COMMANDS)
WK = {"receive", "dispatch", "accept", "return_to_warehouse", "transfer_w2w"}
SM_MEMBER = {"accept", "consume", "write_off_project"}

# legacy role, enforce assignments, member of P1?, allowed commands
ROLES = {
    "Owner": ("Owner", [_assignment("owner")], False, ALL),
    "Admin": ("Admin", [_assignment("admin")], False, ALL),
    "Accountant": ("Accountant", [_assignment("accountant")], False, {"write_off_project"}),
    "Warehousekeeper": ("Warehousekeeper", [_assignment("warehouse")], False, WK),
    "SiteManager-member": ("SiteManager",
                           [_assignment("site_manager", "project", PROJECT),
                            dict(_assignment("site_manager", "location", PROJECT), id="ra-sm-loc")],
                           True, SM_MEMBER),
    "SiteManager-non-member": ("SiteManager",
                               [_assignment("site_manager", "project", OTHER_PROJECT),
                                dict(_assignment("site_manager", "location", OTHER_PROJECT),
                                     id="ra-sm-loc")],
                               False, set()),
    "Technician-member": ("Technician", [_assignment("LEGACY_TECHNICIAN")], True,
                          {"write_off_project"}),
    "Viewer": ("Viewer", [_assignment("LEGACY_VIEWER")], True, set()),
    "Driver": ("Driver", [_assignment("driver")], True, set()),
}


async def _prepare(run):
    """Stock in the warehouse (10 @10), 5 accepted on P1, one open dispatch."""
    await run.receive("20", "10")
    d1 = await run.dispatch("5")
    await run.accept(d1, "5")
    return await run.dispatch("3")


def _command(name, pending):
    c = CanonicalAction
    return {
        "receive": (c.RECEIVE_FROM_SUPPLIER, dict(source=SUP, destination=WH,
                                                  unit_value=Decimal("10"))),
        "receive_to_project": (c.RECEIVE_FROM_SUPPLIER_TO_PROJECT, dict(
            source=SUP, destination=PRJ, project_id=PROJECT, unit_value=Decimal("10"))),
        "dispatch": (c.DISPATCH_WAREHOUSE_TO_PROJECT, dict(source=WH, project_id=PROJECT)),
        "accept": (c.ACCEPT_PROJECT_DELIVERY, dict(
            destination=PRJ, accepted_quantity=Decimal("1"),
            dispatch_movement_id=pending.movement_id, project_id=PROJECT)),
        "consume": (c.CONSUME_TO_SMR, dict(source=PRJ, project_id=PROJECT, smr_id="smr-e")),
        "write_off_warehouse": (c.WRITE_OFF, dict(source=WH, reason="брак", file_ids=["f"])),
        "write_off_project": (c.WRITE_OFF, dict(source=PRJ, reason="брак", file_ids=["f"])),
        "return_to_warehouse": (c.TRANSFER_PROJECT_TO_WAREHOUSE, dict(
            source=PRJ, transfer_target=WH_Q, project_id=PROJECT)),
        "transfer_w2w": (c.TRANSFER_WAREHOUSE_TO_WAREHOUSE, dict(source=WH, transfer_target=WH_B)),
    }[name]


def _ctx(mode, legacy_role):
    user = {"id": USER, "org_id": T, "role": legacy_role, "email": "e@x"}
    if mode == "enforce":
        c = _UserCtx()
        c.mode = "enforce"
        return c
    return LegacyCompatContext(user, mode=mode)


async def _count(db):
    return await db["warehouse_transactions"].count_documents({"tenant_id": T})


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("role", list(ROLES))
@pytest.mark.parametrize("command", COMMANDS)
async def test_r28_role_matrix(canonical_mongo_db, allow_always_gate, monkeypatch,
                               mode, role, command):
    from app.permissions import service as perm
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    pending = await _prepare(run)
    legacy_role, assignments, member, allowed = ROLES[role]
    if member:
        await _member(db)
    monkeypatch.setattr(perm, "_load_assignments", _loader(assignments))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    svc = CommandService(client)                     # production gates
    action, kw = _command(command, pending)
    inp = _inp(action, T, quantity=Decimal("1"), **kw)
    before = await _count(db)
    if command in allowed:
        res = await svc.execute(_ctx(mode, legacy_role), db, run.coll, inp)
        assert res.movement_id
        assert await _count(db) > before
    else:
        with pytest.raises(PermissionDeniedError):
            await svc.execute(_ctx(mode, legacy_role), db, run.coll, inp)
        assert await _count(db) == before                       # nothing written


async def test_r30_pm_own_project_is_the_manager_team_row(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Р30: project_manager writes off on a project only as the team's
    manager (role_in_project SiteManager); a Technician team row is not "own"."""
    from app.permissions import service as perm
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_one({"id": OTHER_PROJECT, "org_id": T, "code": "PO",
                                     "name": "PO", "status": "Active"})
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    monkeypatch.setattr(perm, "_load_assignments", _loader([_assignment("project_manager")]))
    svc = CommandService(client)
    ctx = _UserCtx()
    ctx.mode = "enforce"
    wo = lambda key: _inp(CanonicalAction.WRITE_OFF, T, source=PRJ,  # noqa: E731
                          quantity=Decimal("1"), reason="брак", file_ids=["f"],
                          idempotency_key=key)
    await _member(db, role_in_project="Technician")
    with pytest.raises(PermissionDeniedError):
        await svc.execute(ctx, db, run.coll, wo("pm-tech"))
    await _member(db, role_in_project="SiteManager")
    assert (await svc.execute(ctx, db, run.coll, wo("pm-mgr"))).movement_id


async def test_c26d_l1_project_to_subproject_of_another_project(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """P1 → subproject S2 of P2 with project_id = P1: the move leaves P1, so
    P1 is its project (103ecdc: 422). The target subproject must still exist
    in this tenant; on acceptance the lot lands on S2 → cost moves to P2."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_many([
        {"id": OTHER_PROJECT, "org_id": T, "code": "P2", "name": "P2", "status": "Active"},
        {"id": "s-e-2", "org_id": T, "code": "S2", "name": "S2", "status": "Active",
         "parent_project_id": OTHER_PROJECT}])
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")
    s2 = LocationKey(LocationType.SUBPROJECT, "s-e-2")
    tr = await run(CanonicalAction.TRANSFER_PROJECT_TO_PROJECT, source=PRJ,
                   transfer_target=s2, quantity=Decimal("4"), project_id=PROJECT)
    assert tr.envelope["project_id"] == PROJECT
    await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY, destination=s2,
              quantity=Decimal("4"), accepted_quantity=Decimal("4"),
              dispatch_movement_id=tr.movement_id)
    assert (await run.cost(PROJECT))["total_cost"] == pytest.approx(60.0)
    assert (await run.cost(OTHER_PROJECT))["total_cost"] == pytest.approx(40.0)
    with pytest.raises(Exception):                       # unknown target subproject
        await run(CanonicalAction.TRANSFER_PROJECT_TO_PROJECT, source=PRJ,
                  transfer_target=LocationKey(LocationType.SUBPROJECT, "s-none"),
                  quantity=Decimal("1"), project_id=PROJECT)
