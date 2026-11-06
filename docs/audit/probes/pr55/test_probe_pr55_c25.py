"""CLAUDE AUDIT probes for PR #55 5C-C25 (Р17 cost at accept, Р18 every move in transit / returns via
quarantine, FG-17 Path B). Real Mongo, real CommandService. Copy next to test_probe_pr55_c19.py.

C25-1  mixed prices + return via quarantine: receive 10000@1 + 20000@2; dispatch/accept 30000 → project cost
       50000; return 15000 to warehouse quarantine, accept there → project cost + quarantine value == 50000
       (to the cent); release quarantine → free value == quarantine value.
C25-2  project→project transfer of 12345 (mixed layers), accepted 5000 + 7345 at p2:
       p1 + p2 cost == 50000 after the dispatch, after each partial accept.
C25-3  same goods back and forth: accept 10@10 (100) → return 4 (60) → release → dispatch 4 → accept 4 → 100
       (not 140); consume 3 + write-off 2 add nothing; rebuild ×2 + sync → still 100.
C25-4  Р13 + Р17 reports agree: legacy issue 100 (before cutover, main shape) + accept 5@10 + consume 3 → 150
       on summary / pnl / financial_results / centralized / profit_by_period (run one test per process).
C25-5  FG-17 vs main's max(invoice, warehouse): a main-shape invoice line allocated to the project (100, built
       with main's compute_line_totals) + canonical accept 5@10 → helper total printed (main P&L: max = 100).
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.services.warehouse_movements import LocationKey, LocationType as LT, MovementState as MS
from app.services.warehouse_movements.queries import stock_at
from tests.test_probe_pr55_c19 import _svc, _item, _x, _receive, A, WH, PR, TR
from tests.test_probe_pr55_c20_reports import _reports, _num
from tests.test_probe_pr55_c22 import _first_canonical_at, _legacy
from tests.test_warehouse_canonical_c13_mongo import _tenant_coll

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]

WH_Q = LocationKey(LT.CENTRAL_WAREHOUSE, "wh-1", state=MS.QUARANTINE)
PR2 = LocationKey(LT.PROJECT, "p2", state=MS.FREE)
USER = {"id": "u", "org_id": "T", "role": "Owner", "email": "o@x"}


async def _cost(db, p="p1"):
    from app.services.canonical_material_cost import project_material_cost
    from app.tenancy.data_access import TenantData
    return Decimal(str((await project_material_cost(TenantData.for_resolved_org(db, "T"), "T", p))["total_cost"]))


async def _val(db, loc):
    st = await stock_at(_tenant_coll(db), tenant_id="T", item_id="I", location=loc)
    return Decimal(str(st.get("total_value") or st.get("value") or 0)), Decimal(str(st.get("quantity") or 0))


async def _accept(svc, db, mv, qty, dest, key, project="p1", requested=None):
    return await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal(qty), accepted_quantity=Decimal(qty),
                    requested_quantity=Decimal(requested or qty), dispatch_movement_id=mv.movement_id,
                    project_id=project, destination=dest, idempotency_key=key)


async def _mixed_on_project(svc, db):
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("10000"), unit_value=Decimal("1"),
             destination=WH, idempotency_key="m1")
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("20000"), unit_value=Decimal("2"),
             destination=WH, idempotency_key="m2")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("30000"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    await _accept(svc, db, d, "30000", PR, "a1")


async def test_c25_1_mixed_return_via_quarantine(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _mixed_on_project(svc, db)
    c0 = await _cost(db)
    ret = await _x(svc, db, action=A.TRANSFER_PROJECT_TO_WAREHOUSE, quantity=Decimal("15000"), source=PR,
                   transfer_target=WH_Q, project_id="p1", idempotency_key="ret1")
    await _accept(svc, db, ret, "15000", WH_Q, "ra1", project=None)
    c1 = await _cost(db); qv, qq = await _val(db, WH_Q)
    await _x(svc, db, action=A.QUARANTINE_RELEASE, quantity=Decimal("15000"), source=WH_Q, destination=WH,
             idempotency_key="rel1")
    fv, fq = await _val(db, WH)
    print("C25-1 cost before", c0, "after return", c1, "quarantine", qv, qq, "free after release", fv, fq)
    assert c0 == Decimal("50000")
    assert c1 + qv == Decimal("50000"), (c1, qv)
    assert fv == qv and fq == Decimal("15000"), (fv, qv)


async def test_c25_2_project_to_project_mixed(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _mixed_on_project(svc, db)
    tr = await _x(svc, db, action=A.TRANSFER_PROJECT_TO_PROJECT, quantity=Decimal("12345"), source=PR,
                  transfer_target=PR2, project_id="p1", idempotency_key="pp1")
    steps = [("after dispatch", await _cost(db), await _cost(db, "p2"))]
    await _accept(svc, db, tr, "5000", PR2, "pa1", project="p2", requested="12345")
    steps.append(("after 5000", await _cost(db), await _cost(db, "p2")))
    await _accept(svc, db, tr, "7345", PR2, "pa2", project="p2", requested="12345")
    steps.append(("after 7345", await _cost(db), await _cost(db, "p2")))
    print("C25-2", [(s, str(a), str(b), str(a + b)) for s, a, b in steps])
    assert all(a + b == Decimal("50000") for _, a, b in steps), steps


async def test_c25_3_back_and_forth_no_double(canonical_mongo_db, allow_always_gate, monkeypatch):
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _receive(svc, db, "r1", qty="10")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("10"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    await _accept(svc, db, d, "10", PR, "a1")
    seen = [("accept 10", await _cost(db))]
    ret = await _x(svc, db, action=A.TRANSFER_PROJECT_TO_WAREHOUSE, quantity=Decimal("4"), source=PR,
                   transfer_target=WH_Q, project_id="p1", idempotency_key="ret1")
    await _accept(svc, db, ret, "4", WH_Q, "ra1", project=None)
    seen.append(("return 4", await _cost(db)))
    await _x(svc, db, action=A.QUARANTINE_RELEASE, quantity=Decimal("4"), source=WH_Q, destination=WH,
             idempotency_key="rel1")
    d2 = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("4"), source=WH,
                  destination=TR, project_id="p1", idempotency_key="d2")
    await _accept(svc, db, d2, "4", PR, "a2")
    seen.append(("re-accept 4", await _cost(db)))
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("3"), source=PR, project_id="p1", smr_id="s1",
             idempotency_key="c1")
    await _x(svc, db, action=A.WRITE_OFF, quantity=Decimal("2"), source=PR, project_id="p1", idempotency_key="w1")
    seen.append(("consume+writeoff", await _cost(db)))
    from app.services.warehouse_movements.projections import rebuild_from_ledger
    await rebuild_from_ledger(db, tenant_id="T"); await rebuild_from_ledger(db, tenant_id="T")
    seen.append(("rebuild2", await _cost(db)))
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    await material_smr.sync_material_entries("p1", user=USER)
    seen.append(("sync", await _cost(db)))
    print("C25-3", [(s, str(v)) for s, v in seen])
    assert [v for _, v in seen] == [Decimal(x) for x in ("100", "60", "100", "100", "100", "100")], seen


async def test_c25_4_reports_agree_cutover(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await db["projects"].insert_one({"id": "p1", "org_id": "T", "name": "P1", "status": "Active"})
    await _receive(svc, db, "r1")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("5"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    await _accept(svc, db, d, "5", PR, "a1")
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("3"), source=PR, project_id="p1", smr_id="s1",
             idempotency_key="c1")
    await _legacy(db, await _first_canonical_at(db) - timedelta(days=40))
    out = await _reports(db, monkeypatch)
    vals = {k: _num(v) for k, v in out.items()}
    print("C25-4", vals)
    assert all(v == 150.0 for v in vals.values()), vals


async def test_c25_5_path_b_invoice_line_vs_main_max(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    import uuid
    from app.routes.invoice_lines import compute_line_totals
    now = "2026-10-01T10:00:00+00:00"
    line = {"id": str(uuid.uuid4()), "org_id": "T", "invoice_id": "inv-1", "line_no": 1, "description": "Cement",
            "unit": "бр", "qty": 10.0, "unit_price": 10.0, "vat_percent": 20.0, "purchased_by_user_id": None,
            "allocations": [{"type": "project", "ref_id": "p1", "qty": 10.0, "note": None}],
            "allocation_type": "project", "allocation_ref_id": "p1", "cost_category": "materials",
            "scan_line_ref": None, "notes": None, "created_at": now, "updated_at": now}
    line = compute_line_totals(line)
    await db["invoice_lines"].insert_one(dict(line))
    await _receive(svc, db, "r1")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("5"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    await _accept(svc, db, d, "5", PR, "a1")
    total = await _cost(db)
    print("C25-5 invoice line_total_ex_vat", line.get("line_total_ex_vat"), "canonical accept 50 → helper total",
          total, "(main P&L would show max(100, 50) = 100)")
    assert total == Decimal("150"), total     # FG-17 design: separate lots are summed
