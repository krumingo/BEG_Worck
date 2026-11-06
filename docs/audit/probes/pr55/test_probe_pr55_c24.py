"""CLAUDE AUDIT probes for PR #55 5C-C24 — the two classes Codex found on 53dbd28 (my probes missed them).

Copy next to test_probe_pr55_c19.py and run with real Mongo (see c19 docstring).

L-1  REAL legacy shape (origin/main procurement.issue_to_project writer, copied field by field — no invented
     fields): two legacy issue rows in warehouse_transactions WITHOUT tenant_id / movement_id. Then the startup
     index hook must succeed, verify_required_indexes must pass, a canonical receive must succeed, and the
     legacy rows must be untouched.
F-1  mixed-price FIFO, value conservation to the cent: receive 10000@1 + 20000@2 (= 50000) → dispatch 30000
     in_transit → accept 30000 → project stock value == 50000 exactly; consume 30000 → project cost == 50000.
F-2  partial accepts 10000 + 20000 of the same dispatch → same 50000.
F-3  W2W transfer of the mixed layers, accept in two parts → target warehouse value 50000.
F-4  odd prices: 3 @ 0.3333 + 7 @ 0.1429 → dispatch/accept/consume 10 → cost == Σ layer values (no drift).
"""
import uuid
from decimal import Decimal

import pytest

from app.services.warehouse_movements import LocationKey, LocationType as LT, MovementState as MS
from app.services.warehouse_movements.queries import stock_at
from tests.test_probe_pr55_c19 import _svc, _item, _x, A, WH, PR, TR
from tests.test_warehouse_canonical_c13_mongo import _tenant_coll

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]
WH_B = LocationKey(LT.SMALL_WAREHOUSE, "wh_b", state=MS.FREE)


def _main_issue_row(org_id, project_id, n, qty, price):
    """origin/main backend/app/routes/procurement.py issue_to_project — same keys, same types."""
    now = "2026-09-0%dT10:00:00+00:00" % n
    return {
        "id": str(uuid.uuid4()), "org_id": org_id, "warehouse_id": None, "type": "issue",
        "issue_number": "ISS-%04d" % n, "project_id": project_id, "linked_request_id": None,
        "linked_offer_id": None, "stage_name": "", "issued_by": "u-legacy", "received_by": "",
        "issue_date": now[:10], "notes": "",
        "lines": [{"id": str(uuid.uuid4()), "material_name": "Legacy", "qty_issued": float(qty), "unit": "бр",
                   "dimension_spec": None, "unit_price": float(price),
                   "total_price": round(float(qty) * float(price), 2), "notes": ""}],
        "total": round(float(qty) * float(price), 2), "status": "posted", "created_at": now,
    }


async def _value(db, loc):
    st = await stock_at(_tenant_coll(db), tenant_id="T", item_id="I", location=loc)
    return st


def _val(st):
    if isinstance(st, dict):
        for k in ("value", "total_value", "stock_value"):
            if st.get(k) is not None:
                return Decimal(str(st[k]))
    return None


async def _mixed(svc, db):
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("10000"), unit_value=Decimal("1"),
             destination=WH, idempotency_key="m1")
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("20000"), unit_value=Decimal("2"),
             destination=WH, idempotency_key="m2")


async def _summary_cost(db, monkeypatch):
    from app.routes import material_smr
    monkeypatch.setattr(material_smr, "db", db)
    return (await material_smr.get_material_summary_for_project("T", "p1"))["total_cost"]


async def test_l1_real_legacy_rows_vs_startup_indexes(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db            # NB: fixture already ran ensure_required_indexes on an empty db
    for c in await db.list_collection_names():
        await db[c].drop()                      # start from a db that looks like production main: legacy rows first
    await db["warehouse_transactions"].insert_many([_main_issue_row("T", "p1", 1, 10, 10),
                                                    _main_issue_row("T", "p1", 2, 5, 4)])
    from app.services.warehouse_movements import indexes as ix
    hook = await ix.ensure_required_indexes_at_startup(db)
    print("L-1 startup hook:", hook)
    assert hook["ok"], hook
    await ix.verify_required_indexes(db)
    svc = _svc(client, allow_always_gate); await _item(db)
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("1"), unit_value=Decimal("1"),
             destination=WH, idempotency_key="after-legacy")
    legacy = await db["warehouse_transactions"].count_documents({"type": "issue", "action": {"$exists": False}})
    assert legacy == 2


async def test_f1_mixed_fifo_dispatch_accept_consume(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _mixed(svc, db)
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("30000"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal("30000"), accepted_quantity=Decimal("30000"),
             requested_quantity=Decimal("30000"), dispatch_movement_id=d.movement_id, project_id="p1",
             destination=PR, idempotency_key="a1")
    pv = _val(await _value(db, PR))
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("30000"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    cost = await _summary_cost(db, monkeypatch)
    print("F-1 project stock value after accept:", pv, "cost after consume:", cost)
    if pv is not None:
        assert pv == Decimal("50000"), pv
    assert Decimal(str(cost)) == Decimal("50000"), cost


async def test_f2_mixed_fifo_partial_accepts(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _mixed(svc, db)
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("30000"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    for i, q in enumerate(("10000", "20000")):
        await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal(q), accepted_quantity=Decimal(q),
                 requested_quantity=Decimal("30000"), dispatch_movement_id=d.movement_id, project_id="p1",
                 destination=PR, idempotency_key="a%d" % i)
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("30000"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    cost = await _summary_cost(db, monkeypatch)
    print("F-2 cost:", cost)
    assert Decimal(str(cost)) == Decimal("50000"), cost


async def test_f3_mixed_fifo_w2w(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _mixed(svc, db)
    tr = await _x(svc, db, action=A.TRANSFER_WAREHOUSE_TO_WAREHOUSE, quantity=Decimal("30000"), source=WH,
                  transfer_target=WH_B, idempotency_key="t1")
    for i, q in enumerate(("12345", "17655")):
        await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal(q), accepted_quantity=Decimal(q),
                 requested_quantity=Decimal("30000"), dispatch_movement_id=tr.movement_id, destination=WH_B,
                 idempotency_key="wa%d" % i)
    v = _val(await _value(db, WH_B))
    rows = await db["warehouse_batches"].find({"org_id": "T", "location_id": "wh_b"}, {"_id": 0}).to_list(None)
    tot = sum(Decimal(str(r.get("remaining_quantity") or r.get("quantity") or 0)) * Decimal(str(r.get("unit_value") or 0))
              for r in rows)
    print("F-3 wh_b value:", v, "Σ batch qty×unit:", tot)
    assert (v if v is not None else tot) == Decimal("50000")


async def test_f4_odd_prices_no_drift(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("3"), unit_value=Decimal("0.3333"),
             destination=WH, idempotency_key="o1")
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("7"), unit_value=Decimal("0.1429"),
             destination=WH, idempotency_key="o2")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("10"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    await _x(svc, db, action=A.ACCEPT_PROJECT_DELIVERY, quantity=Decimal("10"), accepted_quantity=Decimal("10"),
             requested_quantity=Decimal("10"), dispatch_movement_id=d.movement_id, project_id="p1",
             destination=PR, idempotency_key="a1")
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("10"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    cost = Decimal(str(await _summary_cost(db, monkeypatch)))
    expected = (Decimal("3") * Decimal("0.3333") + Decimal("7") * Decimal("0.1429")).quantize(Decimal("0.01"))
    print("F-4 cost:", cost, "expected:", expected)
    assert cost == expected, (cost, expected)
