"""CLAUDE AUDIT probes for PR #55 5C-C26 (one path per lot, Path A / Path B). Real Mongo, real CommandService.
Invoice lines are built with origin/main's own compute_line_totals + compute_allocation_stats (real shape).

C26-1  line qty 10 @10 (100) split allocations[] p1 5 / p2 5 → p1 = 50, p2 = 50 (sum 100, never 200).
C26-2  line allocated 10 to p1, canonical receive_from_supplier 10 WITH invoice_line_id → dispatch/accept 10 at p1
       → p1 = 100 (one lot, not 200).
C26-3  partial link: line 10 to p1, canonical direct receipt to p1 of 4 with invoice_line_id → p1 = 100
       (40 canon + 60 line), not 140.
C26-4  pre-cutover legacy issue of the same material + Path B line → sum unchanged and a
       PATH_B_LEGACY_OVERLAP_UNPROVEN warning; tenant T2 never sees T's warning.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.services.warehouse_movements import LocationKey, LocationType as LT, MovementState as MS
from tests.test_probe_pr55_c19 import _svc, _item, _x, A, WH, PR, TR
from tests.test_probe_pr55_c25 import _cost, _accept

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]


def _line(project_allocs, line_id=None, qty=10.0, price=10.0, desc="Cement"):
    from app.routes.invoice_lines import compute_line_totals, compute_allocation_stats
    now = "2026-10-01T10:00:00+00:00"
    allocs = [{"type": "project", "ref_id": p, "qty": q, "note": None} for p, q in project_allocs]
    line = {"id": line_id or str(uuid.uuid4()), "org_id": "T", "invoice_id": "inv-1", "line_no": 1,
            "description": desc, "unit": "бр", "qty": qty, "unit_price": price, "vat_percent": 20.0,
            "purchased_by_user_id": None, "allocations": allocs,
            "allocation_type": "project", "allocation_ref_id": project_allocs[0][0],
            "cost_category": "materials", "scan_line_ref": None, "notes": None, "created_at": now, "updated_at": now}
    return compute_allocation_stats(compute_line_totals(line))


async def test_c26_1_split_line(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    await db["invoice_lines"].insert_one(_line([("p1", 5.0), ("p2", 5.0)]))
    a, b = await _cost(db, "p1"), await _cost(db, "p2")
    print("C26-1 p1", a, "p2", b)
    assert (a, b) == (Decimal("50"), Decimal("50")), (a, b)


async def test_c26_2_full_link_counted_once(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await db["invoice_lines"].insert_one(_line([("p1", 10.0)], line_id="IL-1"))
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("10"), unit_value=Decimal("10"),
             destination=WH, idempotency_key="r1", invoice_line_id="IL-1")
    d = await _x(svc, db, action=A.DISPATCH_WAREHOUSE_TO_PROJECT, quantity=Decimal("10"), source=WH,
                 destination=TR, project_id="p1", idempotency_key="d1")
    await _accept(svc, db, d, "10", PR, "a1")
    v = await _cost(db, "p1")
    print("C26-2 p1", v)
    assert v == Decimal("100"), v


async def test_c26_3_partial_link(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await db["invoice_lines"].insert_one(_line([("p1", 10.0)], line_id="IL-2"))
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER_TO_PROJECT, quantity=Decimal("4"), unit_value=Decimal("10"),
             destination=PR, project_id="p1", idempotency_key="rp1", invoice_line_id="IL-2")
    v = await _cost(db, "p1")
    print("C26-3 p1", v)
    assert v == Decimal("100"), v


async def test_c26_4_legacy_overlap_warning_tenant_scoped(canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await db["invoice_lines"].insert_one(_line([("p1", 10.0)]))
    await _x(svc, db, action=A.RECEIVE_FROM_SUPPLIER, quantity=Decimal("1"), unit_value=Decimal("1"),
             destination=WH, idempotency_key="cut")             # establishes the cutover
    from tests.test_probe_pr55_c24 import _main_issue_row
    row = _main_issue_row("T", "p1", 1, 10, 10); row["lines"][0]["material_name"] = "Cement"
    await db["warehouse_transactions"].insert_one(row)          # 2026-09-01, before the cutover
    v = await _cost(db, "p1")
    from app.services.canonical_material_cost import path_b_integrity_warnings
    from app.tenancy.data_access import TenantData
    wt = await path_b_integrity_warnings(TenantData.for_resolved_org(db, "T"), "T")
    wt2 = await path_b_integrity_warnings(TenantData.for_resolved_org(db, "T2"), "T2")
    codes = sorted({w.get("code") or w.get("warning") for w in wt})
    print("C26-4 p1 cost", v, "T warnings", codes, "T2 warnings", len(wt2))
    assert v == Decimal("200"), v                               # sum unchanged: 100 legacy + 100 Path B
    assert "PATH_B_LEGACY_OVERLAP_UNPROVEN" in codes, codes
    assert wt2 == [], wt2
