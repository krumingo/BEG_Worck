"""LIVE-OPS-01 / TASK 5C — 5C-C23: profit-by-period and the waste card.

Package: ``docs/architecture/tasks/5C-C23_PROFIT_BY_PERIOD_WASTE.md``
(branch ``claude/happy-meitner-bmcnel``). Decisions Р9, Р10, Р13 (Крум,
06.11.2026). Bot evidence: ``docs/evidence/BOT/5C-a427923/README.md`` @
``claude/bot-evidence`` (F-14, C.7 → F-15).

Scenario (real CommandService, no manual sync / recompute), as the bot ran it:
legacy issue 100 dated before the cutover, then
receive 10 @10 → dispatch 5 → accept 5 → consume 3 → write-off 2 from the
project. Every report shows material 130, „фира" 20, total 150.

  * F-14 — ``/profit-by-period``: Σ periods.material + material_undated = 130,
    Σ periods.waste + waste_undated = 20, together = 150 = the shared helper
    total; material + waste never adds up to 170. On a427923 Σ material = 150.
  * F-15 — the „Материални отклонения" card (``/projects/{id}/material-waste``)
    shows the canonical write-off (2) beside the manual register entries,
    marked „отписване от склада", read through the same helper. On a427923
    it shows 0 write-offs.

Run (real Mongo, required):
    WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 PERMISSION_SERVICE_MODE=enforce \\
    MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \\
    PYTHONPATH=. pytest -q tests/test_warehouse_canonical_c23_profit_period_waste.py
"""
from __future__ import annotations

import importlib
import uuid
from datetime import datetime, timezone

import pytest

from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    BEFORE, PROJECT, T, T2, _all_reports, _legacy_issue, _patch_dbs, _scenario,
    _seed, _user,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]


def _patch_waste(monkeypatch, db):
    _patch_dbs(monkeypatch, db)
    for name in ("app.services.material_waste", "app.routes.material_waste"):
        mod = importlib.import_module(name)
        if hasattr(mod, "db"):
            monkeypatch.setattr(mod, "db", db)


async def _bot_stage_3(client, gate, db, tenant=T):
    await _seed(db, tenant)
    await _legacy_issue(db, tenant, value=100.0, created_at=BEFORE)
    await _scenario(client, gate, db, tenant, write_off=True)


async def _manual_waste(db, tenant=T, qty=1.5, date="2026-11-01"):
    await db["material_waste_entries"].insert_one({
        "id": f"mw-{uuid.uuid4().hex[:6]}", "org_id": tenant, "project_id": PROJECT,
        "material_name": "Лепило", "qty": qty, "unit": "bag", "waste_type": "damaged",
        "date": date, "created_at": date + "T10:00:00+00:00"})


def _period_sums(pbp):
    mat = round(sum(p["material"] for p in pbp["periods"]) + pbp.get("material_undated", 0), 2)
    waste = round(sum(p.get("waste", 0) for p in pbp["periods"]) + pbp.get("waste_undated", 0), 2)
    return mat, waste


# ═══════════════════════════════ F-14 ═══════════════════════════════

async def test_f14_profit_by_period_material_is_130_waste_20_total_150(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import revenue_snapshot
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)

    pbp = await revenue_snapshot.get_profit_by_period(PROJECT, user=_user())
    mat, waste = _period_sums(pbp)
    basis = pbp["material_cost_basis"]
    assert mat == pytest.approx(130.0)              # a427923: 150 (фира inside)
    assert waste == pytest.approx(20.0)
    assert mat + waste == pytest.approx(150.0)      # never 170
    assert basis["total_cost"] == pytest.approx(150.0)
    assert basis["consumption_cost"] == pytest.approx(mat)
    assert basis["waste_cost"] == pytest.approx(waste)


async def test_f14_each_period_counts_material_and_waste_once(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import revenue_snapshot
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)

    pbp = await revenue_snapshot.get_profit_by_period(PROJECT, user=_user())
    by = {p["period"]: p for p in pbp["periods"]}
    now = datetime.now(timezone.utc).strftime("%Y-%m")
    assert by["2026-01"]["material"] == pytest.approx(100.0)
    assert by["2026-01"]["waste"] == 0
    assert by[now]["material"] == pytest.approx(30.0)       # a427923: 50
    assert by[now]["waste"] == pytest.approx(20.0)
    for p in pbp["periods"]:
        # no labour / subcontract in the scenario: the period cost is the
        # material + фира, each exactly once.
        assert p["material_total"] == pytest.approx(p["material"] + p["waste"])
        assert p["gross_cost"] == pytest.approx(p["material"] + p["waste"])
        assert p["total_cost"] == pytest.approx(p["material"] + p["waste"])


async def test_f14_profit_by_period_agrees_with_every_other_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Same split (material, фира) as P&L, package and profit reports."""
    from app.routes import project_pnl, revenue_snapshot
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)

    pnl = await project_pnl.get_project_pnl(PROJECT, user=_user())
    pbp = await revenue_snapshot.get_profit_by_period(PROJECT, user=_user())
    mat, waste = _period_sums(pbp)
    assert mat == pytest.approx(pnl["expense"]["material_cost"])
    assert waste == pytest.approx(pnl["expense"]["material_waste_cost"])
    reports = await _all_reports()
    assert all(v[0] == pytest.approx(150.0) for v in reports.values()), reports


async def test_f14_undated_legacy_lands_in_material_undated_not_waste(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import revenue_snapshot
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await _legacy_issue(db, value=40.0, created_at=None)   # counted, flagged undated
    await _scenario(client, allow_always_gate, db, write_off=True)

    pbp = await revenue_snapshot.get_profit_by_period(PROJECT, user=_user())
    assert pbp["material_undated"] == pytest.approx(40.0)
    assert pbp["waste_undated"] == 0
    mat, waste = _period_sums(pbp)
    assert (mat, waste) == (pytest.approx(70.0), pytest.approx(20.0))
    assert mat + waste == pytest.approx(pbp["material_cost_basis"]["total_cost"])


# ═══════════════════════════════ F-15 ═══════════════════════════════

async def test_f15_waste_card_shows_the_canonical_write_off(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_waste
    client, db = canonical_mongo_db
    _patch_waste(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)

    card = await material_waste.get_material_waste(PROJECT, user=_user())
    s = card["summary"]
    assert s["writeoff_items"] == 1                  # a427923: KeyError / 0
    assert s["writeoff_qty"] == pytest.approx(2.0)
    assert s["writeoff_value"] == pytest.approx(20.0)
    assert s["total_waste_items"] == 1
    assert s["total_waste_qty"] == pytest.approx(2.0)
    assert s["manual_waste_items"] == 0
    [wo] = card["writeoffs"]
    assert wo["source"] == "warehouse_write_off"
    assert wo["source_label"] == "отписване от склада"
    assert wo["cost_label"] == "фира"
    assert wo["qty"] == pytest.approx(2.0) and wo["value"] == pytest.approx(20.0)
    assert wo["material_name"] == "Лепило" and wo["reason"] == "брак"
    assert wo["movement_id"] and wo["date"]
    [row] = [m for m in card["materials"] if m["material_name"] == "Лепило"]
    assert row["wasted_qty"] == pytest.approx(2.0)
    assert row["written_off_qty"] == pytest.approx(2.0)
    assert row["manual_wasted_qty"] == 0


async def test_f15_manual_entries_stay_beside_the_write_off(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_waste
    client, db = canonical_mongo_db
    _patch_waste(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)
    await _manual_waste(db, qty=1.5)

    card = await material_waste.get_material_waste(PROJECT, user=_user())
    s = card["summary"]
    assert (s["manual_waste_items"], s["manual_waste_qty"]) == (1, pytest.approx(1.5))
    assert (s["writeoff_items"], s["writeoff_qty"]) == (1, pytest.approx(2.0))
    assert s["total_waste_items"] == 2
    assert s["total_waste_qty"] == pytest.approx(3.5)
    [row] = [m for m in card["materials"] if m["material_name"] == "Лепило"]
    assert row["wasted_qty"] == pytest.approx(3.5)
    assert row["manual_wasted_qty"] == pytest.approx(1.5)
    assert row["written_off_qty"] == pytest.approx(2.0)
    # the manual register itself is untouched: the log lists only manual rows
    log = await material_waste.get_waste_log(PROJECT, user=_user())
    assert log["total"] == 1
    compact = await material_waste.get_compact_waste(PROJECT, user=_user())
    assert compact["summary"]["writeoff_items"] == 1


async def test_f15_no_second_register_is_written(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """Reading the card writes nothing; the write-off is one cost row only.
    5C-C25 (Р17): the write-off is one „фира" allocation row; the only cost
    row is the acceptance."""
    from app.routes import material_waste
    client, db = canonical_mongo_db
    _patch_waste(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)
    before_me = await db["material_entries"].count_documents({})
    await material_waste.get_material_waste(PROJECT, user=_user())
    await material_waste.get_material_waste(PROJECT, user=_user())
    assert await db["material_waste_entries"].count_documents({}) == 0
    assert await db["material_entries"].count_documents({}) == before_me
    assert await db["material_entries"].count_documents(
        {"org_id": T, "movement_kind": "write_off", "waste": True}) == 1
    assert await db["material_entries"].count_documents(
        {"org_id": T, "cost_recognized": True}) == 1


async def test_f15_date_filter_applies_to_write_offs(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_waste
    client, db = canonical_mongo_db
    _patch_waste(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    inside = await material_waste.get_material_waste(
        PROJECT, date_from=today, date_to=today, user=_user())
    assert inside["summary"]["writeoff_items"] == 1
    later = await material_waste.get_material_waste(
        PROJECT, date_from="2099-01-01", user=_user())
    assert later["summary"]["writeoff_items"] == 0
    earlier = await material_waste.get_material_waste(
        PROJECT, date_to="2026-01-01", user=_user())
    assert earlier["summary"]["writeoff_items"] == 0


async def test_f15_warehouse_write_off_is_not_on_the_project_card(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """A write-off from the central warehouse is not project waste (Р10)."""
    import os
    from decimal import Decimal
    from app.routes import material_waste
    from app.services.warehouse_movements import CanonicalAction
    from app.services.warehouse_movements.service import CommandService
    from app.tenancy.data_access import TenantData
    from tests.test_warehouse_canonical_c22_all_reports_cutover import WH, _Ctx, _inp
    client, db = canonical_mongo_db
    _patch_waste(monkeypatch, db)
    await _seed(db)
    await _scenario(client, allow_always_gate, db)          # 5 left in the warehouse
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    coll = TenantData.for_resolved_org(db, T).warehouse_transactions
    await CommandService(client, gate=allow_always_gate).execute(
        _Ctx(T), db, coll, _inp(CanonicalAction.WRITE_OFF, T, source=WH,
                                quantity=Decimal("1"), reason="брак", file_ids=["f-1"]))
    card = await material_waste.get_material_waste(PROJECT, user=_user())
    assert card["summary"]["writeoff_items"] == 0
    assert card["writeoffs"] == []


async def test_f15_write_offs_are_tenant_scoped(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_waste
    client, db = canonical_mongo_db
    _patch_waste(monkeypatch, db)
    await _bot_stage_3(client, allow_always_gate, db)
    await _seed(db, T2)
    await _scenario(client, allow_always_gate, db, T2)       # no write-off in B

    a = await material_waste.get_material_waste(PROJECT, user=_user())
    b = await material_waste.get_material_waste(PROJECT, user=_user(T2))
    assert a["summary"]["writeoff_items"] == 1
    assert b["summary"]["writeoff_items"] == 0 and b["writeoffs"] == []
