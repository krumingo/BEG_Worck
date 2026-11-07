"""CLAUDE AUDIT probe — #55 C26f: the C26e rule "no warehouse location for project-bound roles" was dropped;
the project relation is checked only on the projects a command TOUCHES. A command that touches NO project
needs no relation at all. SiteManager (real company-scope grant; member of nothing) on warehouse-only commands
whose permission the site_manager catalog holds: quarantine_entry at the central warehouse; accept of a
warehouse→warehouse transfer. Off and enforce."""
from decimal import Decimal
import pytest
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.envelope import MovementState
from app.services.warehouse_movements.errors import PermissionDeniedError, WarehouseMovementError
from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import T, WH, _inp, _patch_dbs, _seed
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import _loader
from tests.test_warehouse_canonical_c26e_r28_all_modes import _ctx, _count, WH_B
from tests.test_probe_pr55_c26e_real_assignments import REAL_SM

pytest_plugins = ["tests.warehouse_canonical_conftest"]
WH_QUAR = LocationKey(WH.location_type, WH.location_id, state=MovementState.QUARANTINE)


@pytest.mark.parametrize("command", ["quarantine_entry_wh", "accept_w2w"])
@pytest.mark.parametrize("mode", ["off", "enforce"])
async def test_sm_warehouse_only(canonical_mongo_db, allow_always_gate, monkeypatch, mode, command):
    from app.permissions import service as perm
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db); await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    tr = await run(CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE, source=WH, transfer_target=WH_B, quantity=Decimal("2"))
    monkeypatch.setattr(perm, "_load_assignments", _loader(REAL_SM))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    if command == "quarantine_entry_wh":
        action, kw = CanonicalAction.QUARANTINE_ENTRY, dict(source=WH, destination=WH_QUAR)
    else:
        action, kw = CanonicalAction.ACCEPT_PROJECT_DELIVERY, dict(destination=WH_B, accepted_quantity=Decimal("2"),
                                                                    dispatch_movement_id=tr.movement_id)
    before = await _count(db)
    try:
        await CommandService(client).execute(_ctx(mode, "SiteManager"), db, run.coll, _inp(action, T, quantity=Decimal("2"), **kw))
        outcome = "ALLOWED (+%d rows)" % (await _count(db) - before)
    except PermissionDeniedError as e:
        outcome = "DENIED (%s)" % e.context.get("reason_code")
    except WarehouseMovementError as e:
        outcome = "REFUSED %s: %s" % (type(e).__name__, str(e)[:80])
    print("\nRESULT mode=%s %s by non-member SiteManager → %s" % (mode, command, outcome))
