"""CLAUDE AUDIT probes on PR #55 5C-C20 (c0b3b4c) — every project finance report, one canonical flow.

Copy into <worktree>/backend/tests/ next to test_probe_pr55_c19.py and run (real Mongo):
  PERMISSION_SERVICE_MODE=enforce WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 \
  MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true&replicaSet=rs0' DB_NAME=probe \
  PYTHONPATH=. pytest --noconftest -q -s tests/test_probe_pr55_c20_reports.py

Flow (no manual sync, no recompute): receive 5@10 → dispatch in_transit → accept 5 → consume 3.
Canonical project material cost = 30 (CLAUDE.md §7). Each report's material figure is printed;
C20-A asserts every report agrees on 30. C20-B adds one legacy issue (pre-canon, 100) and shows what
each report does with the mixed history.
"""
import pytest
from decimal import Decimal

from tests.test_probe_pr55_c19 import _svc, _item, _receive, _dispatch_accept, _x, A, PR

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]

USER = {"id": "u", "org_id": "T", "role": "Owner", "email": "o@x"}


async def _flow(client, db, gate):
    svc = _svc(client, gate); await _item(db)
    await db["projects"].insert_one({"id": "p1", "org_id": "T", "name": "P1", "status": "Active"})
    await _receive(svc, db, "r1")
    await _dispatch_accept(svc, db)
    await _x(svc, db, action=A.CONSUME_TO_SMR, quantity=Decimal("3"), source=PR, project_id="p1",
             smr_id="s1", idempotency_key="c1")


async def _reports(db, monkeypatch):
    import importlib
    mods = ["app.routes.material_smr", "app.services.project_pnl", "app.services.project_financial_results",
            "app.services.centralized_reports", "app.routes.revenue_snapshot", "app.services.resource_model"]
    for m in mods:
        monkeypatch.setattr(importlib.import_module(m), "db", db)
    from app.routes import material_smr, revenue_snapshot
    from app.services import project_pnl, project_financial_results, centralized_reports
    out = {}
    async def grab(name, coro, pick):
        try:
            out[name] = pick(await coro)
        except Exception as e:  # report the failure itself
            out[name] = "ERROR %s: %s" % (type(e).__name__, str(e)[:120])
    await grab("material_smr.summary", material_smr.get_material_summary_for_project("T", "p1"),
               lambda r: r["total_cost"])
    await grab("project_pnl.compute_project_pnl", project_pnl.compute_project_pnl("T", "p1"),
               lambda r: {k: v for k, v in (r.get("expense") or r).items() if "material" in k.lower()} or r)
    await grab("project_financial_results.paid_materials",
               project_financial_results.compute_financial_results("T", "p1"),
               lambda r: r["cash"]["breakdown"]["paid_materials"])
    await grab("centralized_reports.total_materials", centralized_reports.build_centralized_reports("T", "p1"),
               lambda r: next((v["total_materials"] for v in r.values() if isinstance(v, dict) and "total_materials" in v),
                              r.get("total_materials")))
    await grab("revenue_snapshot.profit_by_period.material",
               revenue_snapshot.get_profit_by_period("p1", user=USER),
               lambda r: sum(p.get("material", 0) for p in (r.get("periods") or r.get("months") or [])
                             if isinstance(p, dict)))
    for k, v in out.items():
        print("   %-48s %s" % (k, v))
    return out


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("material_cost", "warehouse_material_cost", "materials", "material"):
            if isinstance(v.get(k), (int, float)):
                return float(v[k])
    return v


async def test_c20_a_all_reports_agree_canonical_only(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(client, db, allow_always_gate)
    print("\nC20-A canonical only (expected 30 everywhere):")
    out = await _reports(db, monkeypatch)
    bad = {k: v for k, v in out.items() if _num(v) != 30.0}
    assert not bad, "reports disagree with the canonical 30: %s" % bad


async def test_c20_b_mixed_legacy_and_canonical(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(client, db, allow_always_gate)
    await db["warehouse_transactions"].insert_one({
        "id": "legacy-1", "org_id": "T", "project_id": "p1", "type": "issue",
        "lines": [{"material_name": "Old", "unit_cost": 10, "qty_issued": 10}]})
    print("\nC20-B legacy issue 100 + canonical consume 30:")
    out = await _reports(db, monkeypatch)
    vals = {k: _num(v) for k, v in out.items()}
    assert len({v for v in vals.values() if isinstance(v, float)}) == 1, "reports disagree: %s" % vals
