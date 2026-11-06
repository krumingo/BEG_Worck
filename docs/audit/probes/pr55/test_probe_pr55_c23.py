"""CLAUDE AUDIT probe on PR #55 5C-C23 (53dbd28): profit-by-period material vs фира (F-14).

C23-1  receive 10@10 → project 10 → consume 3 → write-off 2 from project (+ legacy 100 before cutover):
       Σ period material + material_undated == 130 (30 consumption + 100 legacy),
       Σ period waste + waste_undated == 20, and period gross cost counts material+waste once
       (Σ material_total == 150 == material summary total).
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.test_probe_pr55_c19 import _svc, _item, _receive, _dispatch_accept, _x, A, PR
from tests.test_probe_pr55_c22 import _first_canonical_at, _legacy

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]
USER = {"id": "u", "org_id": "T", "role": "Owner", "email": "o@x"}


async def test_c23_1_period_material_waste_split(canonical_mongo_db, allow_always_gate, monkeypatch):
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate); await _item(db)
    await db["projects"].insert_one({"id": "p1", "org_id": "T", "name": "P"})
    await _receive(svc, db, "r1", qty="10")
    await _dispatch_accept(svc, db, qty="10")
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("3"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")
    await _x(svc, db, action=A.WRITE_OFF, quantity=Decimal("2"), source=PR, project_id="p1", idempotency_key="w1")
    await _legacy(db, await _first_canonical_at(db) - timedelta(days=40))
    import importlib
    for m in ("app.routes.revenue_snapshot", "app.routes.material_smr"):
        monkeypatch.setattr(importlib.import_module(m), "db", db)
    from app.routes import revenue_snapshot, material_smr
    r = await revenue_snapshot.get_profit_by_period("p1", user=USER)
    periods = r.get("periods") or r.get("months") or []
    meta = {k: v for k, v in r.items() if k not in ("periods", "months")}
    mat = sum(p.get("material", 0) for p in periods) + (meta.get("totals", meta).get("material_undated", 0) or 0)
    waste = sum(p.get("waste", 0) for p in periods) + (meta.get("totals", meta).get("waste_undated", 0) or 0)
    mtot = sum(p.get("material_total", 0) for p in periods)
    summ = await material_smr.get_material_summary_for_project("T", "p1")
    print("C23-1 material", mat, "waste", waste, "material_total", mtot, "summary", summ["total_cost"])
    assert (round(mat, 2), round(waste, 2), round(mtot, 2), summ["total_cost"]) == (130.0, 20.0, 150.0, 150.0)
