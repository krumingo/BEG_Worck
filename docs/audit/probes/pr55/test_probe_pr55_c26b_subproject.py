"""CLAUDE AUDIT probe — #55 C26b / Р27: the project write-off endpoint checks Р27 on
body.project_id, but the stock source is body.subproject_id. Is the subproject verified
to belong to that project? Member of PROJECT writes off from a subproject of OTHER_PROJECT."""
from decimal import Decimal
import pytest
from fastapi import HTTPException
from app.services.warehouse_movements.envelope import LocationKey, LocationType
from tests.test_warehouse_canonical_c22_all_reports_cutover import ITEM, PROJECT, T
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import (
    OTHER_PROJECT, _UserCtx, _assignment, _member)
from tests.test_warehouse_canonical_c26b_project_writeoff_endpoint import _setup, _user
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run

pytest_plugins = ["tests.warehouse_canonical_conftest"]
SP_O = "sp-of-other-project"


async def test_member_of_p1_writes_off_from_subproject_of_p2(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    route, audits = await _setup(client, allow_always_gate, db, monkeypatch,
                                 [_assignment("LEGACY_TECHNICIAN")])
    await _member(db)                              # member of PROJECT only
    # C26d: the subproject is a real projects row whose parent is OTHER_PROJECT
    await db["projects"].insert_one({"id": SP_O, "org_id": T, "code": "SPO", "name": "SPO",
                                     "status": "Active", "parent_project_id": OTHER_PROJECT})
    run = _Run(client, allow_always_gate, db)
    await run.receive("5", "10")
    d = await run.dispatch("5", project=OTHER_PROJECT)
    await run.accept(d, "5", dest=LocationKey(LocationType.SUBPROJECT, SP_O), project=OTHER_PROJECT)
    sp = LocationKey(LocationType.SUBPROJECT, SP_O)
    before = await run.stock(sp)
    print("stock in SP of OTHER_PROJECT before:", before)
    body = route.ProjectWriteOffBody(project_id=PROJECT, subproject_id=SP_O, item_id=ITEM,
                                     unit="bag", quantity="2", idempotency_key="probe-sp",
                                     reason="брак", file_ids=["f"])
    ctx = _UserCtx(); ctx.mode = "enforce"
    try:
        res = await route.post_project_writeoff(body, request=None, user=_user(), ctx=ctx)
        status = 201
    except HTTPException as e:
        status = e.status_code
    after = await run.stock(sp)
    print("status:", status, "stock after:", after, "cost PROJECT:", await run.cost(PROJECT),
          "cost OTHER:", await run.cost(OTHER_PROJECT))
    assert status in (403, 409, 400, 422), "Р27 bypass: member of P1 wrote off stock of a subproject of P2"
