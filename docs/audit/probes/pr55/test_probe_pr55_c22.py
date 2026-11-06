"""CLAUDE AUDIT probes on PR #55 5C-C22 (a427923) — one material-cost helper, Р13 cutover split.

Copy next to test_probe_pr55_c19.py / test_probe_pr55_c20_reports.py and run with real Mongo.

C22-1  every report (C20 probe set) = 30 for canonical only.
C22-2  legacy issue 100 dated BEFORE the tenant cutover + canonical 30 → 130 on every report.
C22-3  legacy issue 100 dated AFTER the cutover → excluded → 30 on every report.
C22-4  cutover is PER TENANT: tenant T2 moved to the canon first (early canonical row); tenant T's legacy
       issue dated after T2's cutover but before T's own → still counted for T (130).
C22-5  profit_by_period: the sum of monthly material equals the project total (130).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.test_probe_pr55_c19 import _svc, _item, _receive, _x, A, PR
from tests.test_probe_pr55_c20_reports import _flow, _reports, _num

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.warehouse_canonical_conftest"]


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


async def _first_canonical_at(db, t="T"):
    row = await db["warehouse_transactions"].find_one({"org_id": t, "action": {"$exists": True}},
                                                      sort=[("recorded_at", 1)])
    return datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))


async def _legacy(db, at, t="T", ident="legacy-1"):
    await db["warehouse_transactions"].insert_one({
        "id": ident, "org_id": t, "project_id": "p1", "type": "issue", "created_at": _iso(at),
        "lines": [{"material_name": "Old", "unit_cost": 10, "qty_issued": 10}]})


def _agree(out, expected):
    vals = {k: _num(v) for k, v in out.items()}
    bad = {k: v for k, v in vals.items() if v != expected}
    assert not bad, "expected %s on every report, got %s" % (expected, vals)


async def test_c22_1_canonical_only(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(client, db, allow_always_gate)
    print("\nC22-1:"); _agree(await _reports(db, monkeypatch), 30.0)


async def test_c22_2_legacy_before_cutover(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(client, db, allow_always_gate)
    await _legacy(db, await _first_canonical_at(db) - timedelta(days=40))
    print("\nC22-2:"); _agree(await _reports(db, monkeypatch), 130.0)


async def test_c22_3_legacy_after_cutover(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(client, db, allow_always_gate)
    await _legacy(db, await _first_canonical_at(db) + timedelta(seconds=5))
    print("\nC22-3:"); _agree(await _reports(db, monkeypatch), 30.0)


async def test_c22_4_cutover_is_per_tenant(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    svc = _svc(client, allow_always_gate)
    await _item(db, "T2")
    await _receive(svc, db, "t2r", t="T2")                     # T2 cutover = now
    t2_cut = await _first_canonical_at(db, "T2")
    await db["warehouse_transactions"].update_many({"org_id": "T2"},
        {"$set": {"recorded_at": _iso(t2_cut - timedelta(days=30))}})   # T2 moved 30 days ago
    await _flow(client, db, allow_always_gate)                  # T cutover = now
    await _legacy(db, t2_cut - timedelta(days=10))              # after T2's cutover, before T's
    print("\nC22-4:"); _agree(await _reports(db, monkeypatch), 130.0)


async def test_c22_5_periods_sum_to_total(canonical_mongo_db, allow_always_gate, monkeypatch):
    client, db = canonical_mongo_db
    await _flow(client, db, allow_always_gate)
    await _legacy(db, await _first_canonical_at(db) - timedelta(days=40))
    out = await _reports(db, monkeypatch)
    assert _num(out["revenue_snapshot.profit_by_period.material"]) == 130.0, out
