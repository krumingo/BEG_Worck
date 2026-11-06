"""CLAUDE AUDIT probes on PR #55 (5C-C18 head) — project material cost, real Mongo only.

Copy into <worktree>/backend/tests/ and run:
  PERMISSION_SERVICE_MODE=enforce WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 \
  MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true&replicaSet=rs0' DB_NAME=probe \
  PYTHONPATH=. pytest --noconftest -q tests/test_probe_pr55_material_cost.py

P55-1  cost recognised once: receive 5 @10 -> dispatch 5 -> accept 5 -> consume 3.
       CLAUDE.md §7 and the C18 decision say project cost = 3 x 10 = 30. Sum the canonical
       material_entries rows the cost readers use, after POST /material-entries/sync.
P55-2  get_material_summary_for_project (used by revenue_expense) must not raise.
P55-3  the sync of tenant T2 for the same project id must not see tenant T's ledger.
"""
from decimal import Decimal

import pytest

from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType, MovementState
from app.services.warehouse_movements.service import CommandService, CommandInput
from tests.test_warehouse_canonical_c13_mongo import _TestCtx, _tenant_coll

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]

COST_KINDS = ["accept", "transfer_out", "write_off", "transfer", "consume"]  # material_smr readers


async def _flow(svc, db):
    await db["md_item"].insert_one({"tenant_id": "T", "id": "I", "canonical_unit": "бр"})
    wh = LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh-1", state=MovementState.FREE)
    pr = LocationKey(LocationType.PROJECT, "p1", state=MovementState.FREE)
    run = lambda inp: svc.execute(_TestCtx("T"), db, _tenant_coll(db), inp)
    await run(CommandInput(action=CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="T", actor_id="u",
              item_id="I", unit="бр", quantity=Decimal("5"), unit_value=Decimal("10"), destination=wh,
              idempotency_key="r1", reason="r", file_ids=["f"]))
    d = await run(CommandInput(action=CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="T",
                  actor_id="u", item_id="I", unit="бр", quantity=Decimal("5"), source=wh, destination=pr,
                  project_id="p1", idempotency_key="d1", reason="d", file_ids=["f"]))
    await run(CommandInput(action=CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="T", actor_id="u",
              item_id="I", unit="бр", quantity=Decimal("5"), accepted_quantity=Decimal("5"),
              requested_quantity=Decimal("5"), dispatch_movement_id=d.movement_id, project_id="p1",
              destination=pr, idempotency_key="a1", reason="a", file_ids=["f"]))
    await run(CommandInput(action=CanonicalAction.CONSUME_TO_SMR, tenant_id="T", actor_id="u", item_id="I",
              unit="бр", quantity=Decimal("3"), source=pr, project_id="p1", smr_id="smr-1",
              idempotency_key="c1", reason="c", file_ids=["f"]))


def _user(org):
    return {"id": "u-" + org, "org_id": org, "role": "Owner", "email": org + "@x"}


async def test_p55_1_project_material_cost_counted_once(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(CommandService(client, gate=allow_always_gate), db)
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    await material_smr.sync_material_entries("p1", user=_user("T"))
    rows = await db["material_entries"].find(
        {"org_id": "T", "project_id": "p1", "projection_source": "canonical_warehouse_service",
         "movement_kind": {"$in": COST_KINDS}}, {"_id": 0}).to_list(None)
    total = sum(float(r["total_value"]) for r in rows if r.get("total_value") is not None)
    kinds = sorted(r.get("movement_kind") for r in rows)
    assert total == pytest.approx(30.0), f"project material cost {total} (kinds={kinds}); expected 30 = 3x10 consumed"


async def test_p55_2_material_summary_does_not_crash(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    await material_smr.get_material_summary_for_project("T", "p1")


async def test_p55_3_sync_is_tenant_scoped(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(CommandService(client, gate=allow_always_gate), db)
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    out = await material_smr.sync_material_entries("p1", user=_user("T2"))
    assert out["synced"] == 0
    assert await db["material_entries"].count_documents({"org_id": "T2"}) == 0
