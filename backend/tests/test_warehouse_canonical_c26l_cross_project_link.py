"""
5C-C26l — Codex F-55-C26-02 [P1] (#55 comment 6706399138): invoice line L
(10 @10 = 100) allocated to project P, a direct delivery of the same 10 @10
into project Q (or a subproject of Q) with invoice_line_id=L → P 100 + Q 100
= 200, no warning, live and after rebuild ×2.

D-04 (one lot is cost once), fail-closed:
  1. up front: such a delivery → 422 INVOICE_LINE_PROJECT_MISMATCH, nothing
     written; a delivery beyond L's remaining allocation to its project too;
  2. legacy data already in conflict: the lot counts once, on the canonical
     destination; the covered quantity leaves P's Path B;
     PATH_B_LINK_PROJECT_CONFLICT on both P and Q (integrity screen);
  3. true separate lots (no link) still sum to 200.
Real Mongo (replica set).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.canonical_material_cost import path_b_integrity_warnings
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import InvoiceLineProjectMismatchError
from app.services.warehouse_movements.projections import rebuild_from_ledger
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    PROJECT, T, _patch_dbs, _seed,
)
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import SUP, _Run
from tests.test_warehouse_canonical_c26_one_path_per_lot import IL, _invoice_line

pytest_plugins = ["tests.warehouse_canonical_conftest"]

Q = "p-c26l-q"
QS = "s-c26l-q"


async def _setup(client, gate, db, monkeypatch, allocations):
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    await db["projects"].insert_many([
        {"id": Q, "org_id": T, "code": "Q", "name": "Q", "status": "Active"},
        {"id": QS, "org_id": T, "code": "QS", "name": "QS", "status": "Active",
         "parent_project_id": Q}])
    await _invoice_line(db, deprecated=False, allocations=allocations)   # L: 10 @10
    return _Run(client, gate, db)


def _deliver(run, dest, qty, linked=True):
    kw = {"invoice_line_id": IL} if linked else {}
    return run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP,
               destination=dest, quantity=Decimal(qty), unit_value=Decimal("10"), **kw)


async def _costs(run):
    p, q = await run.cost(PROJECT), await run.cost(Q)
    return (p["total_cost"], q["total_cost"],
            sorted(w["code"] for w in p["path_b_warnings"]),
            sorted(w["code"] for w in q["path_b_warnings"]))


Q_LOC = LocationKey(LocationType.PROJECT, Q)
QS_LOC = LocationKey(LocationType.SUBPROJECT, QS)


# ═══════════════════════════ 1. refused up front ═══════════════════════════

@pytest.mark.parametrize("dest", [Q_LOC, QS_LOC], ids=["project-Q", "subproject-of-Q"])
async def test_exact_repro_delivery_into_another_project_is_refused(
        canonical_mongo_db, allow_always_gate, monkeypatch, dest):
    """4ed6077: accepted, P 100 + Q 100 = 200. Now 422, nothing written."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": PROJECT, "qty": 10}])
    before = await db["warehouse_transactions"].count_documents({"tenant_id": T})
    with pytest.raises(InvoiceLineProjectMismatchError):
        await _deliver(run, dest, "10")
    assert await db["warehouse_transactions"].count_documents({"tenant_id": T}) == before
    assert await _costs(run) == (pytest.approx(100.0), 0, [], [])


async def test_delivery_beyond_the_remaining_allocation_is_refused(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """L allocated 10 to P: 6 then 5 more → 422; 4 more → accepted (10)."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": PROJECT, "qty": 10}])
    prj = LocationKey(LocationType.PROJECT, PROJECT)
    await _deliver(run, prj, "6")
    with pytest.raises(InvoiceLineProjectMismatchError):
        await _deliver(run, prj, "5")
    await _deliver(run, prj, "4")
    assert (await run.cost(PROJECT))["total_cost"] == pytest.approx(100.0)


async def test_replay_of_a_full_delivery_is_a_duplicate_not_a_422(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """An offline retry (same idempotency key) of the delivery that used up
    the allocation answers as the idempotent duplicate, writes nothing."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": PROJECT, "qty": 10}])
    prj = LocationKey(LocationType.PROJECT, PROJECT)
    kw = dict(source=SUP, destination=prj, quantity=Decimal("10"),
              unit_value=Decimal("10"), invoice_line_id=IL, idempotency_key="k-c26l")
    first = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, **kw)
    again = await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, **kw)
    assert again.replay is True and not first.replay
    assert await db["warehouse_transactions"].count_documents(
        {"tenant_id": T, "action": "receive_from_supplier_to_project"}) == 1
    assert (await run.cost(PROJECT))["total_cost"] == pytest.approx(100.0)


async def test_split_line_delivers_each_part_to_its_project(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """L: 6 to P, 4 to Q. 6 into P and 4 into Q's subproject are both
    accepted; 1 more into Q is refused. P 60 + Q 40 = 100."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": PROJECT, "qty": 6},
                        {"type": "project", "ref_id": Q, "qty": 4}])
    await _deliver(run, LocationKey(LocationType.PROJECT, PROJECT), "6")
    await _deliver(run, QS_LOC, "4")
    with pytest.raises(InvoiceLineProjectMismatchError):
        await _deliver(run, Q_LOC, "1")
    p, q, pw, qw = await _costs(run)
    assert (p, q) == (pytest.approx(60.0), pytest.approx(40.0))
    assert pw == [] and qw == []


# ═══════════════════════════ 2. legacy conflicts ═══════════════════════════

@pytest.mark.parametrize("dest", [Q_LOC, QS_LOC], ids=["project-Q", "subproject-of-Q"])
@pytest.mark.parametrize("qty,want_p,want_q", [("10", 0.0, 100.0), ("4", 60.0, 40.0)],
                         ids=["full", "partial"])
async def test_legacy_cross_project_link_counts_the_lot_once_and_warns_on_both(
        canonical_mongo_db, allow_always_gate, monkeypatch, dest, qty, want_p, want_q):
    """A delivery made while L was allocated to Q, then L re-allocated to P
    (POST /allocate) — the conflicting state Codex reproduced. The lot counts
    once, on Q; only the covered quantity leaves P's Path B; both projects
    show PATH_B_LINK_PROJECT_CONFLICT. Live and after rebuild ×2."""
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": Q, "qty": 10}])
    await _deliver(run, dest, qty)
    await db["invoice_lines"].update_one(
        {"id": IL}, {"$set": {"allocations": [{"type": "project", "ref_id": PROJECT,
                                                "qty": 10}]}})
    seen = []
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        p, q, pw, qw = await _costs(run)
        assert (p, q) == (pytest.approx(want_p), pytest.approx(want_q)), i
        assert p + q == pytest.approx(100.0)
        assert pw == ["PATH_B_LINK_PROJECT_CONFLICT"]
        assert qw == ["PATH_B_LINK_PROJECT_CONFLICT"]
        seen.append((p, q))
    assert seen[0] == seen[1] == seen[2]
    run_warnings = await path_b_integrity_warnings(run.tenant_data, T)
    assert sorted((w["code"], w["project_id"]) for w in run_warnings) == sorted(
        [("PATH_B_LINK_PROJECT_CONFLICT", PROJECT), ("PATH_B_LINK_PROJECT_CONFLICT", Q)])


# ═══════════════════════════ 3. separate lots ═══════════════════════════

@pytest.mark.parametrize("dest", [Q_LOC, QS_LOC], ids=["project-Q", "subproject-of-Q"])
async def test_no_link_two_lots_still_sum(canonical_mongo_db, allow_always_gate,
                                          monkeypatch, dest):
    client, db = canonical_mongo_db
    run = await _setup(client, allow_always_gate, db, monkeypatch,
                       [{"type": "project", "ref_id": PROJECT, "qty": 10}])
    await _deliver(run, dest, "10", linked=False)
    for i in range(3):
        if i:
            await rebuild_from_ledger(db, tenant_id=T)
        assert await _costs(run) == (pytest.approx(100.0), pytest.approx(100.0), [], [])
