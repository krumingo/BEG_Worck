"""CLAUDE AUDIT probe — #55 C26i FG-70: an acceptance of a warehouse→project dispatch lands only on the
addressed project. Dispatch → OTHER_PROJECT (P2). Accept by a SiteManager (real company grant) who is a member
of PROJECT (P1) — and by an Admin — into: P1 bucket, a subproject of P1, a subproject of P2, P2 bucket.
Expect 422 + nothing written for P1 / sub-of-P1 (Admin) and a refusal for the SM; OK into P2 / sub-of-P2 (Admin).
Off and enforce."""
from decimal import Decimal
import pytest
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import PermissionDeniedError, WarehouseMovementError
from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import PROJECT, T, _inp, _patch_dbs, _seed
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import OTHER_PROJECT, _assignment, _loader, _member
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx, _count
from tests.test_probe_pr55_c26e_real_assignments import REAL_SM

pytest_plugins = ["tests.warehouse_canonical_conftest"]
S1, S2 = "sp-i-of-p1", "sp-i-of-p2"
DESTS = {"P1": LocationKey(LocationType.PROJECT, PROJECT), "subP1": LocationKey(LocationType.SUBPROJECT, S1),
         "subP2": LocationKey(LocationType.SUBPROJECT, S2), "P2": LocationKey(LocationType.PROJECT, OTHER_PROJECT)}


@pytest.mark.parametrize("dest", list(DESTS))
@pytest.mark.parametrize("who", ["SiteManager-member-P1", "Admin"])
@pytest.mark.parametrize("mode", ["off", "enforce"])
async def test_accept_lands_on_addressed_project(canonical_mongo_db, allow_always_gate, monkeypatch, mode, who, dest):
    from app.permissions import service as perm
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db); await _seed(db)
    for d in ({"id": OTHER_PROJECT, "code": "P2"}, {"id": S1, "code": "S1", "parent_project_id": PROJECT},
              {"id": S2, "code": "S2", "parent_project_id": OTHER_PROJECT}):
        await db["projects"].insert_one(dict(d, org_id=T, name=d["code"], status="Active"))
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("3", project=OTHER_PROJECT)
    if who.startswith("SiteManager"):
        await _member(db)
        assignments, legacy = REAL_SM, "SiteManager"
    else:
        assignments, legacy = [_assignment("admin")], "Admin"
    monkeypatch.setattr(perm, "_load_assignments", _loader(assignments))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    before = await _count(db)
    try:
        await CommandService(client).execute(_ctx(mode, legacy), db, run.coll, _inp(
            CanonicalAction.ACCEPT_PROJECT_DELIVERY, T, destination=DESTS[dest], quantity=Decimal("3"),
            accepted_quantity=Decimal("3"), dispatch_movement_id=disp.movement_id))
        out = "ALLOWED (+%d)" % (await _count(db) - before)
    except PermissionDeniedError as e:
        out = "DENIED %s %s" % (e.context.get("reason_code"), {k: e.context.get(k) for k in ("scope_type", "scope_id")})
    except WarehouseMovementError as e:
        out = "REFUSED %s (+%d) ctx=%s" % (type(e).__name__, await _count(db) - before, getattr(e, "context", None))
    print("\nRESULT mode=%s who=%s dest=%s → %s" % (mode, who, dest, out))
