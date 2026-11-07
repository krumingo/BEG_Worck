"""
5C-C26d — audit C26B-1 / FLOW Guard FG-38 (HIGH): the project of any action
on a SUBPROJECT bucket is the subproject's parent from the database
(``projects.parent_project_id``); a body project_id naming another project
→ 422, nothing written; permissions (generic gate, Р27) are decided against
the real project — on POST /project-writeoff, on the generic /movements
(write-off from a subproject) and on an acceptance into a subproject.
FG-39: Р20 value hiding uses the legacy role in off / shadow.

Real Mongo (replica set).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import InvariantViolationError
from app.services.warehouse_movements.service import CommandService
from app.tenancy.guard import LegacyCompatContext
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    ITEM, PROJECT, T, WH, _inp, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    USER, _UserCtx, _assignment, _ledger_count, _loader, _member,
)
from tests.test_warehouse_canonical_c26b_project_writeoff_endpoint import _setup

pytest_plugins = ["tests.warehouse_canonical_conftest"]

P2 = "p-c26d-2"
S1 = "s-c26d-1"          # subproject of PROJECT (P1)
S2 = "s-c26d-2"          # subproject of P2


async def _subprojects(db):
    await db["projects"].insert_many([
        {"id": P2, "org_id": T, "code": "P2", "name": "P2", "status": "Active"},
        {"id": S1, "org_id": T, "code": "S1", "name": "S1", "status": "Active",
         "parent_project_id": PROJECT},
        {"id": S2, "org_id": T, "code": "S2", "name": "S2", "status": "Active",
         "parent_project_id": P2},
    ])


class _RecordingGate:
    """Records the project scope every permission decision sees."""
    def __init__(self):
        self.seen = []

    async def ensure(self, ctx, *, action, source, destination, project_id):
        self.seen.append((action.value, project_id))

    async def ensure_project_write_off(self, ctx, tenant_db, *, org_id, project_id):
        self.seen.append(("r27", project_id))


async def _stock_in(run, sub):
    """receive 10 → dispatch to the subproject's parent → accept INTO `sub`."""
    await run.receive("10", "10")
    disp = await run.dispatch("10", project=PROJECT if sub == S1 else P2)
    return await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY,
                     destination=LocationKey(LocationType.SUBPROJECT, sub),
                     quantity=Decimal("10"), accepted_quantity=Decimal("10"),
                     dispatch_movement_id=disp.movement_id)


# ═══════════════════════ POST /project-writeoff ═══════════════════════

def _body(route, project_id, sub, key):
    return route.ProjectWriteOffBody(
        project_id=project_id, subproject_id=sub, item_id=ITEM, unit="bag",
        quantity="1", idempotency_key=f"c26d-{key}", reason="брак", file_ids=["f"])


def _ctx(mode, user):
    if mode == "enforce":
        c = _UserCtx()
        c.mode = "enforce"
        return c
    return LegacyCompatContext(user, mode=mode)


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
async def test_member_of_p1_cannot_write_off_a_p2_subproject(
        canonical_mongo_db, allow_always_gate, monkeypatch, mode):
    """Member (SiteManager) of P1; source = subproject S2 of P2.
    body project_id=P1 → 422 (parent mismatch); body project_id=P2 → 403
    (Р27 against the real project, not a member of P2). 0 movements.
    64418eb: the first call wrote a write-off under P1's rights."""
    client, db = canonical_mongo_db
    route, _ = await _setup(client, allow_always_gate, db, monkeypatch,
                            [_assignment("site_manager")])
    await _subprojects(db)
    run = _Run(client, allow_always_gate, db)
    await _stock_in(run, S2)
    await _member(db)                                # member of P1 only
    user = {"id": USER, "org_id": T, "role": "SiteManager", "email": "s@x"}
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    before = await _ledger_count(db)
    # 5C-C26h (FG-55): the rights check (Р27 against the REAL project P2)
    # runs first — this caller has none there, so 403, not the 422 that
    # would confirm the subproject's parent.
    with pytest.raises(HTTPException) as exc:
        await route.post_project_writeoff(_body(route, PROJECT, S2, "mismatch-" + mode),
                                          request=None, user=user, ctx=_ctx(mode, user))
    assert exc.value.status_code == 403
    assert "parent_project_id" not in exc.value.detail["context"]
    with pytest.raises(HTTPException) as exc:
        await route.post_project_writeoff(_body(route, P2, S2, "real-" + mode),
                                          request=None, user=user, ctx=_ctx(mode, user))
    assert exc.value.status_code == 403
    # 5C-C26h (FG-55): the denial names the subproject the caller sent.
    assert exc.value.detail["context"]["scope_id"] == S2
    assert P2 not in str(exc.value.detail)
    assert await _ledger_count(db) == before


async def test_member_of_the_real_parent_writes_off_from_its_subproject(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    route, _ = await _setup(client, allow_always_gate, db, monkeypatch,
                            [_assignment("site_manager")])
    await _subprojects(db)
    run = _Run(client, allow_always_gate, db)
    await _stock_in(run, S1)
    await _member(db)                                # member of P1, S1's parent
    user = {"id": USER, "org_id": T, "role": "SiteManager", "email": "s@x"}
    before = await _ledger_count(db)
    res = await route.post_project_writeoff(_body(route, PROJECT, S1, "ok"),
                                            request=None, user=user, ctx=_ctx("enforce", user))
    assert res.envelope["project_id"] == PROJECT
    assert res.envelope["source"]["location_id"] == S1
    assert await _ledger_count(db) == before + 1


async def test_unknown_subproject_is_422(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    route, _ = await _setup(client, allow_always_gate, db, monkeypatch, [_assignment("owner")])
    user = {"id": USER, "org_id": T, "role": "Owner", "email": "o@x"}
    with pytest.raises(HTTPException) as exc:
        await route.post_project_writeoff(_body(route, PROJECT, "s-nope", "nope"),
                                          request=None, user=user, ctx=_ctx("enforce", user))
    assert exc.value.status_code == 422


# ═══════════════════ generic /movements (CommandService) ═══════════════════

async def test_generic_write_off_from_a_subproject_binds_the_parent(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _subprojects(db)
    run = _Run(client, allow_always_gate, db)
    await _stock_in(run, S2)
    gate = _RecordingGate()
    svc = CommandService(client, gate=gate)
    src = LocationKey(LocationType.SUBPROJECT, S2)
    before = await _ledger_count(db)
    with pytest.raises(InvariantViolationError):            # body names P1
        await svc.execute(_UserCtx(), db, run.coll, _inp(
            CanonicalAction.WRITE_OFF, T, source=src, quantity=Decimal("1"),
            project_id=PROJECT, reason="брак", file_ids=["f"]))
    # 5C-C26h (FG-55): rights first (against the real parent P2), then 422.
    assert gate.seen == [("r27", P2)] and await _ledger_count(db) == before
    res = await svc.execute(_UserCtx(), db, run.coll, _inp(  # no project_id → bound
        CanonicalAction.WRITE_OFF, T, source=src, quantity=Decimal("1"),
        reason="брак", file_ids=["f"]))
    assert gate.seen == [("r27", P2), ("r27", P2)]
    assert res.envelope["project_id"] == P2 and res.envelope["subproject_id"] == S2


async def test_accept_into_a_subproject_of_another_project_is_422(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Dispatch for P1, accept into S2 (parent P2) with project_id P1 → 422,
    nothing written; into S1 (parent P1) → accepted, cost on P1."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _subprojects(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10", project=PROJECT)
    count = await db["warehouse_transactions"].count_documents({"tenant_id": T})
    with pytest.raises(InvariantViolationError):
        await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY,
                  destination=LocationKey(LocationType.SUBPROJECT, S2),
                  quantity=Decimal("10"), accepted_quantity=Decimal("10"),
                  dispatch_movement_id=disp.movement_id, project_id=PROJECT)
    assert await db["warehouse_transactions"].count_documents({"tenant_id": T}) == count
    acc = await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY,
                    destination=LocationKey(LocationType.SUBPROJECT, S1),
                    quantity=Decimal("10"), accepted_quantity=Decimal("10"),
                    dispatch_movement_id=disp.movement_id, project_id=PROJECT)
    assert acc.envelope["project_id"] == PROJECT
    assert (await run.cost(PROJECT))["total_cost"] == pytest.approx(100.0)
    assert (await run.cost(P2))["total_cost"] == 0


async def test_foreign_tenant_subproject_has_no_parent_here(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_one({"id": "s-foreign", "org_id": "org_other",
                                     "parent_project_id": PROJECT})
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("10")
    with pytest.raises(InvariantViolationError):
        await run(CanonicalAction.ACCEPT_PROJECT_DELIVERY,
                  destination=LocationKey(LocationType.SUBPROJECT, "s-foreign"),
                  quantity=Decimal("10"), accepted_quantity=Decimal("10"),
                  dispatch_movement_id=disp.movement_id)


# ═══════════════════ FG-39 — Р20 by legacy role in off / shadow ═══════════════════

@pytest.mark.parametrize("mode", ["off", "shadow"])
@pytest.mark.parametrize("legacy_role,sees", [
    ("Owner", True), ("Admin", True), ("Accountant", True),
    ("Warehousekeeper", True),  # Р32 (5C-C26f): warehouse values
    ("SiteManager", False), ("Technician", False),
    ("Viewer", False), ("Driver", False)])
async def test_fg39_values_by_legacy_role(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, mode, legacy_role, sees):
    from app.routes import warehouse_canonical_queries as q
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("4", "1")
    monkeypatch.setattr(q, "db", db)
    # A RoleAssignment that disagrees must not decide in off / shadow.
    from app.permissions import service as perm
    monkeypatch.setattr(perm, "_load_assignments",
                        _loader([_assignment("warehouse" if sees else "owner")]))

    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(q, "_authorize_resource_scope", _ok)
    ctx = LegacyCompatContext({"id": USER, "org_id": T, "role": legacy_role}, mode=mode)
    stock = await q.read_stock(ITEM, location_type="central_warehouse",
                               location_id="wh_1", state="free", ctx=ctx)
    if sees:
        assert stock["total_value"] == "4.0000" and "values_hidden" not in stock
    else:
        assert "total_value" not in stock and stock["values_hidden"] is True
