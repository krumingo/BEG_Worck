"""
5C-C26i — FLOW Guard pass 6 on 518aab4 (Р18, Р28).

  * FG-70 (HIGH): an acceptance of a warehouse → project DISPATCH was not
    bound to the dispatch's project (only a transfer's target was) — a member
    of P1 accepted into P1 a lot dispatched to P2. Every acceptance now lands
    where its dispatch was addressed; mismatch → refused, nothing written.
  * FG-69: POST /movements from a subproject named the parent project in the
    denial and so answered a yes/no question about it. A denial on a command
    that touches a subproject names only that subproject, in one shape.

All three modes, real company grants. Real Mongo (replica set).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import (
    InvariantViolationError, PermissionDeniedError,
)
from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PRJ, PROJECT, T, _inp, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    OTHER_PROJECT, USER, _loader, _member,
)
from tests.test_warehouse_canonical_c26e_r28_all_modes import _count, _ctx, _real

pytest_plugins = ["tests.warehouse_canonical_conftest"]

MODES = ["off", "shadow", "enforce"]
P2_LOC = LocationKey(LocationType.PROJECT, OTHER_PROJECT)
S2 = "s-c26i-2"
S1 = "s-c26i-1"


async def _setup(client, gate, db, monkeypatch, role, mode, *, member=True):
    from app.permissions import service as perm
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_many([
        {"id": OTHER_PROJECT, "org_id": T, "code": "P2", "name": "P2", "status": "Active"},
        {"id": S1, "org_id": T, "code": "S1", "name": "S1", "status": "Active",
         "parent_project_id": PROJECT},
        {"id": S2, "org_id": T, "code": "S2", "name": "S2", "status": "Active",
         "parent_project_id": OTHER_PROJECT}])
    run = _Run(client, gate, db)
    await run.receive("20", "10")
    to_p2 = await run.dispatch("3", project=OTHER_PROJECT)
    to_p1 = await run.dispatch("3", project=PROJECT)
    s2_acc = await run.dispatch("4", project=OTHER_PROJECT)
    await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY,
              destination=LocationKey(LocationType.SUBPROJECT, S2),
              quantity=Decimal("4"), accepted_quantity=Decimal("4"),
              dispatch_movement_id=s2_acc.movement_id)
    if member:
        await _member(db)                                   # member of P1 only
    monkeypatch.setattr(perm, "_load_assignments", _loader(_real(role)))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    return run, to_p2, to_p1


def _accept(dispatch, dest, **kw):
    return _inp(CanonicalAction.ACCEPT_PROJECT_DELIVERY, T, quantity=Decimal("3"),
                accepted_quantity=Decimal("3"), destination=dest,
                dispatch_movement_id=dispatch.movement_id, **kw)


# ═══════════════════════════════ FG-70 ═══════════════════════════════

@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("role,legacy", [("site_manager", "SiteManager"), ("owner", "Owner")])
async def test_fg70_a_dispatch_to_p2_cannot_be_accepted_into_p1(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode, role, legacy):
    """518aab4: a member of P1 (and the owner) accepted into P1 a lot
    dispatched to P2. Now refused (422 — the caller has rights on P1, so the
    rights check passes first), nothing written; with and without a body
    project_id, and into P1's subproject too."""
    client, db = canonical_mongo_db
    run, to_p2, _ = await _setup(client, allow_always_gate, db, monkeypatch, role, mode)
    svc = CommandService(client)
    before = await _count(db)
    for dest, kw in ((PRJ, {}), (PRJ, {"project_id": PROJECT}),
                     (LocationKey(LocationType.SUBPROJECT, S1), {})):
        with pytest.raises(InvariantViolationError):
            await svc.execute(_ctx(mode, legacy), db, run.coll, _accept(to_p2, dest, **kw))
    assert await _count(db) == before


@pytest.mark.parametrize("mode", MODES)
async def test_fg70_the_addressed_project_still_accepts(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """The dispatch to P1 is accepted on P1 (and into P1's subproject)."""
    client, db = canonical_mongo_db
    run, _, to_p1 = await _setup(client, allow_always_gate, db, monkeypatch,
                                 "site_manager", mode)
    res = await CommandService(client).execute(
        _ctx(mode, "SiteManager"), db, run.coll, _accept(to_p1, PRJ))
    assert res.envelope["project_id"] == PROJECT


@pytest.mark.parametrize("mode", MODES)
async def test_fg70_without_rights_on_the_landing_project_it_is_403(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """A SiteManager on no project: the same 403 for the wrong and the right
    target (rights first, FG-55) — never a 422 about the dispatch."""
    client, db = canonical_mongo_db
    run, to_p2, to_p1 = await _setup(client, allow_always_gate, db, monkeypatch,
                                     "site_manager", mode, member=False)
    svc = CommandService(client)
    reasons = []
    for disp in (to_p2, to_p1):
        with pytest.raises(PermissionDeniedError) as exc:
            await svc.execute(_ctx(mode, "SiteManager"), db, run.coll, _accept(disp, PRJ))
        reasons.append(exc.value.context.get("reason_code"))
    assert reasons[0] == reasons[1]


# ═══════════════════════════════ FG-69 ═══════════════════════════════

@pytest.mark.parametrize("mode", MODES)
async def test_fg69_movements_from_a_subproject_is_no_oracle(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """A SiteManager member of P1 only consumes over HTTP from S2 (subproject
    of P2) with body project_id = P2 (right parent), P1 (wrong) or none:
    the SAME 403 every time, naming only S2 — never P2."""
    from app.routes import warehouse_canonical as route
    from app.tenancy.guard import LegacyCompatContext
    from tests.test_warehouse_canonical_c26a_writeoff_rights_values import _UserCtx
    client, db = canonical_mongo_db
    await _setup(client, allow_always_gate, db, monkeypatch, "site_manager", mode)
    monkeypatch.setattr(route, "db", db)
    monkeypatch.setattr(route, "_service", lambda: CommandService(client))
    user = {"id": USER, "org_id": T, "role": "SiteManager", "email": "s@x"}
    if mode == "enforce":
        ctx = _UserCtx()
        ctx.mode = "enforce"
    else:
        ctx = LegacyCompatContext(user, mode=mode)
    before = await _count(db)
    details = []
    for i, project_id in enumerate((OTHER_PROJECT, PROJECT, None)):
        body = route.MovementCommandBody(
            action="consume_to_smr", item_id=ITEM, unit="bag", quantity="1",
            source={"location_type": "subproject", "location_id": S2},
            project_id=project_id, smr_id="smr", idempotency_key=f"fg69-{mode}-{i}")
        with pytest.raises(HTTPException) as exc:
            await route.post_movement(body, request=None, user=user, ctx=ctx)
        assert exc.value.status_code == 403
        details.append(exc.value.detail)
    assert details[0] == details[1] == details[2]
    assert details[0]["context"]["scope_id"] == S2
    assert OTHER_PROJECT not in str(details)
    assert await _count(db) == before
