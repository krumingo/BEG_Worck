"""CLAUDE AUDIT probes for PR #55 5C-C24 — harder cases of the two Codex classes.

L-2  ALL three legacy writers of origin/main procurement.py (intake :456-479, issue :646-661, return :769-782),
     two rows each, field shapes copied from main, inserted BEFORE indexes/startup → startup ok, verify ok,
     canonical receive ok, legacy rows untouched, cutover = the canonical row (legacy never counted as canon).
F-5  three prices, full lifecycle, value to the cent:
     receive 7000@1 + 11000@2.5 + 5000@3.33 (= 51150); dispatch 15000 (= 7000@1 + 8000@2.5 = 27000);
     accept 9000 + 6000; consume 10000 (= 7000@1 + 3000@2.5 = 14500); write-off 5000 from project (= 12500);
     project cost 27000 after projector, after rebuild ×2, after sync (split: see note in the test);
     warehouse value left 24150 (3000@2.5 + 5000@3.33).
"""
import uuid
from decimal import Decimal

import pytest

from tests.test_probe_pr55_c19 import _svc, _item, _x, A, WH, PR, TR
from tests.test_probe_pr55_c24 import _main_issue_row, _val
from app.services.warehouse_movements.queries import stock_at
from tests.test_warehouse_canonical_c13_mongo import _tenant_coll

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]
USER = {"id": "u", "org_id": "T", "role": "Owner", "email": "o@x"}


def _main_intake_row(n):
    now = "2026-08-1%dT09:00:00+00:00" % n
    return {"id": str(uuid.uuid4()), "org_id": "T", "warehouse_id": "wh-main", "type": "intake",
            "source_type": "supplier_invoice", "source_invoice_id": str(uuid.uuid4()), "supplier_id": None,
            "supplier_name": "S", "invoice_number": "INV-%d" % n, "invoice_date": now[:10],
            "digital_invoice_url": None, "project_id": "p1", "received_at": now, "received_by": "u-legacy",
            "purchased_by": None,
            "lines": [{"id": str(uuid.uuid4()), "material_name": "Legacy", "qty_received": 10.0, "unit": "бр",
                       "dimension_spec": None, "unit_price": 5.0, "discount_percent": 0.0, "final_unit_price": 5.0,
                       "total_price": 50.0, "project_id": "p1", "linked_request_id": None, "linked_offer_id": None}],
            "subtotal": 50.0, "vat_amount": 10.0, "total": 60.0, "created_at": now}


def _main_return_row(n):
    now = "2026-09-2%dT09:00:00+00:00" % n
    return {"id": str(uuid.uuid4()), "org_id": "T", "warehouse_id": "wh-main", "type": "return",
            "project_id": "p1", "returned_by": "u-legacy", "return_date": now[:10], "notes": "",
            "lines": [{"id": str(uuid.uuid4()), "material_name": "Legacy", "qty_returned": 1.0, "unit": "бр",
                       "notes": ""}],
            "status": "posted", "created_at": now}


async def test_l2_all_main_writer_shapes_before_startup(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    for c in await db.list_collection_names():
        await db[c].drop()
    rows = [_main_intake_row(1), _main_intake_row(2), _main_issue_row("T", "p1", 1, 10, 10),
            _main_issue_row("T", "p1", 2, 5, 4), _main_return_row(1), _main_return_row(2)]
    await db["warehouse_transactions"].insert_many([dict(r) for r in rows])
    from app.services.warehouse_movements import indexes as ix
    for _ in range(2):                                   # repeated startup
        hook = await ix.ensure_required_indexes_at_startup(db)
        assert hook["ok"], hook
    await ix.verify_required_indexes(db)
    svc = _svc(client, allow_always_gate); await _item(db)
    r = await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("1"), unit_value=Decimal("1"),
                 destination=WH, idempotency_key="after-legacy")
    after = await db["warehouse_transactions"].find({"action": {"$exists": False}}, {"_id": 0}).to_list(None)
    assert sorted(after, key=lambda d: d["id"]) == sorted(rows, key=lambda d: d["id"]), "legacy rows changed"
    from app.services.canonical_material_cost import tenant_cutover
    from app.tenancy.data_access import TenantData
    cut = await tenant_cutover(TenantData.for_resolved_org(db, "T"), "T")
    assert cut["cutover_movement_id"] == r.movement_id, cut


async def test_f5_three_price_lifecycle(canonical_mongo_db, allow_always_gate, monkeypatch):
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    for i, (q, v) in enumerate((("7000", "1"), ("11000", "2.5"), ("5000", "3.33"))):
        await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal(q), unit_value=Decimal(v),
                 destination=WH, idempotency_key="r%d" % i)
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("15000"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    for i, q in enumerate(("9000", "6000")):
        await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal(q), accepted_quantity=Decimal(q),
                 requested_quantity=Decimal("15000"), dispatch_movement_id=d.movement_id, project_id="p1",
                 destination=PR, idempotency_key="a%d" % i)
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("10000"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    await _x(svc, db, action=A.WRITE_OFF, quantity=Decimal("5000"), source=PR, project_id="p1", idempotency_key="w1")
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    seen = {}
    s = await material_smr.get_material_summary_for_project("T", "p1"); seen["projector"] = (s["total_cost"], s["waste_cost"])
    from app.services.warehouse_movements.projections import rebuild_from_ledger
    await rebuild_from_ledger(db, tenant_id="T"); await rebuild_from_ledger(db, tenant_id="T")
    s = await material_smr.get_material_summary_for_project("T", "p1"); seen["rebuild2"] = (s["total_cost"], s["waste_cost"])
    await material_smr.sync_material_entries("p1", user=USER)
    s = await material_smr.get_material_summary_for_project("T", "p1"); seen["sync"] = (s["total_cost"], s["waste_cost"])
    wh = _val(await stock_at(_tenant_coll(db), tenant_id="T", item_id="I", location=WH))
    print("F-5", seen, "warehouse value left:", wh)
    # Total is conserved (27000). The consumption/фира split depends on how a PARTIAL acceptance values the
    # accepted part: the implementation splits dispatched layers PRO-RATA (9000/15000 → 4200@1 + 4800@2.5),
    # not in FIFO order (7000@1 + 2000@2.5) → фира 9800, not 12500. Recorded as a decision for Krum.
    # Р21 (Krum, D-55-PRORATA resolved): a partial acceptance takes layers OLDEST FIRST at their own price,
    # so accept 9000 = 7000@1 + 2000@2.5, consumption 14500, фира 12500, total 27000.
    assert all(v == (27000.0, 12500.0) for v in seen.values()), seen
    if wh is not None:
        assert wh == Decimal("24150"), wh


async def test_f6_prorata_rounding_prime_split(canonical_mongo_db, allow_always_gate, monkeypatch):
    """dispatch 7 = 3@1 + 4@2 (= 11) accepted 3 + 2 + 2; pro-rata quantities are non-terminating
    (3/7 of 3 = 1.2857…). After consuming all 7 the project cost must be exactly 11.00 and Σ accepted
    allocation quantities per source layer must equal what was dispatched from it."""
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("3"), unit_value=Decimal("1"),
             destination=WH, idempotency_key="r1")
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("4"), unit_value=Decimal("2"),
             destination=WH, idempotency_key="r2")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("7"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    for i, q in enumerate(("3", "2", "2")):
        await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal(q), accepted_quantity=Decimal(q),
                 requested_quantity=Decimal("7"), dispatch_movement_id=d.movement_id, project_id="p1",
                 destination=PR, idempotency_key="a%d" % i)
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("7"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    acc = await db["warehouse_transactions"].find({"action": "accept_project_delivery"}, {"_id": 0}).to_list(None)
    per_layer = {}
    for r in acc:
        for a in r.get("layer_allocations") or []:
            k = a.get("unit_value")
            per_layer[k] = per_layer.get(k, Decimal(0)) + Decimal(str(a["quantity"]))
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    cost = (await material_smr.get_material_summary_for_project("T", "p1"))["total_cost"]
    print("F-6 accepted per source layer:", {k: str(v) for k, v in per_layer.items()}, "cost:", cost)
    assert per_layer == {"1": Decimal("3"), "2": Decimal("4")}, per_layer
    assert Decimal(str(cost)) == Decimal("11"), cost
