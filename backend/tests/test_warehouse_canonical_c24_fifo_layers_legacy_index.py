"""LIVE-OPS-01 / TASK 5C — 5C-C24: exact FIFO layers after acceptance and the
movement-id index against real legacy history.

Package: ``docs/architecture/tasks/5C-C24_CODEX_FIFO_LAYERS_LEGACY_INDEX.md``
(branch ``claude/happy-meitner-bmcnel``), approved by Крум under Р9
(06.11.2026). Codex review: PR #55 comment 6691597676 (its independent probes
live unchanged in ``tests/test_codex_c23_independent.py``).

F-55-C23-01 — an acceptance lands the dispatched layers at the destination:
one FIFO layer per traced allocation, stable identity ``(acceptance
movement_id, part)`` (the same key as the ``warehouse_batches`` row), exact
unit value. The rounded weighted-average ``unit_value`` of the row is never
the stock or cost basis; consume / write-off / rebuild / sync carry the exact
Σ of the FIFO allocations.

F-55-C23-02 — ``wh_movements_unique_movement_id`` is a PARTIAL unique index
over canonical rows (``movement_id`` is a string). Legacy rows in ``main``'s
``procurement.issue_to_project`` shape (no ``tenant_id`` / ``movement_id``)
are admitted untouched; every canonical movement stays unique.

Run (real Mongo, required):
    WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1 PERMISSION_SERVICE_MODE=enforce \\
    MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true' \\
    PYTHONPATH=. pytest -q tests/test_warehouse_canonical_c24_fifo_layers_legacy_index.py
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from pymongo.errors import DuplicateKeyError

from app.services.canonical_material_cost import project_material_cost
from app.services.warehouse_movements import CanonicalAction, LocationKey, LocationType
from app.services.warehouse_movements.errors import IndexMissingError
from app.services.warehouse_movements.fifo import allocations_value, inbound_layer_parts
from app.services.warehouse_movements.indexes import (
    CANONICAL_MOVEMENT_FILTER,
    REQUIRED_INDEXES,
    ensure_required_indexes_at_startup,
    verify_required_indexes,
)
from app.services.warehouse_movements.projections import rebuild_from_ledger
from app.services.warehouse_movements.queries import stock_at
from app.services.warehouse_movements.service import CommandService
from app.tenancy.data_access import TenantData
from tests.test_warehouse_canonical_c22_all_reports_cutover import (
    BEFORE, ITEM, PRJ, PROJECT, T, WH, _all_reports, _assert_all, _Ctx, _inp,
    _patch_dbs, _seed, _user,
)

pytest_plugins = ["tests.warehouse_canonical_conftest"]

SUP = LocationKey(LocationType.SUPPLIER, "sup_c24")
Q4 = Decimal("0.0001")


# ───────────────────────────── helpers ─────────────────────────────

class _Run:
    def __init__(self, client, gate, db, tenant=T):
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        self.db = db
        self.tenant = tenant
        self.coll = TenantData.for_resolved_org(db, tenant).warehouse_transactions
        self.svc = CommandService(client, gate=gate)
        self.ctx = _Ctx(tenant)

    async def __call__(self, action, **kw):
        return await self.svc.execute(self.ctx, self.db, self.coll,
                                      _inp(action, self.tenant, **kw))

    async def receive(self, qty, price):
        return await self(CanonicalAction.RECEIVE_FROM_SUPPLIER, source=SUP,
                          destination=WH, quantity=Decimal(qty),
                          unit_value=Decimal(price))

    async def dispatch(self, qty):
        return await self(CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, source=WH,
                          quantity=Decimal(qty), project_id=PROJECT)

    async def accept(self, dispatch, qty):
        return await self(CanonicalAction.ACCEPT_PROJECT_DELIVERY, destination=PRJ,
                          quantity=Decimal(qty), accepted_quantity=Decimal(qty),
                          dispatch_movement_id=dispatch.movement_id,
                          project_id=PROJECT)

    async def consume(self, qty):
        return await self(CanonicalAction.CONSUME_TO_SMR, source=PRJ,
                          quantity=Decimal(qty), project_id=PROJECT, smr_id="smr-c24")

    async def write_off(self, qty):
        return await self(CanonicalAction.WRITE_OFF, source=PRJ, quantity=Decimal(qty),
                          reason="брак", file_ids=["f-c24"])

    async def stock(self, loc):
        return await stock_at(self.coll, tenant_id=self.tenant, item_id=ITEM, location=loc)


def _alloc_value(result) -> Decimal:
    return allocations_value(result.envelope["layer_allocations"])


async def _batches_value(db, loc: LocationKey) -> Decimal:
    """Σ remaining × unit value of the canonical batch rows at one bucket."""
    total = Decimal("0")
    async for b in db["warehouse_batches"].find({
        "tenant_id": T, "projection_source": "canonical_warehouse_service",
        "location.location_type": loc.location_type.value,
        "location.location_id": loc.location_id,
    }):
        total += Decimal(str(b["remaining_quantity"])) * Decimal(str(b["unit_value"]))
    return total.quantize(Q4)


async def _cost_entries(db) -> Decimal:
    total = Decimal("0")
    async for e in db["material_entries"].find({
        "tenant_id": T, "projection_source": "canonical_warehouse_service",
        "movement_kind": {"$in": ["consume", "write_off"]}, "cost_recognized": True,
    }):
        total += Decimal(str(e["total_value"]))
    return total.quantize(Q4)


async def _ledger_cost(db) -> Decimal:
    total = Decimal("0")
    async for row in db["warehouse_transactions"].find({
        "tenant_id": T, "action": {"$in": ["consume_to_smr", "write_off"]},
        "source.location_type": "project",
    }):
        total += allocations_value(row["layer_allocations"])
    return total.quantize(Q4)


async def _projection_snapshot(db):
    batches = sorted(
        [(b["movement_id"], b["layer_sequence"], str(b["quantity"]),
          str(b["remaining_quantity"]), str(b["unit_value"]))
         async for b in db["warehouse_batches"].find(
             {"tenant_id": T, "projection_source": "canonical_warehouse_service"})])
    entries = sorted(
        [(e["movement_id"], e.get("movement_kind"), str(e["total_value"]))
         async for e in db["material_entries"].find(
             {"tenant_id": T, "projection_source": "canonical_warehouse_service"})])
    return batches, entries


async def _assert_agree(run: _Run, expected_cost: Decimal, expected_stock: Decimal):
    """ledger ↔ stock ↔ batches ↔ material_entries ↔ shared cost helper."""
    db = run.db
    prj = await run.stock(PRJ)
    assert Decimal(prj["total_value"]) == expected_stock
    assert await _batches_value(db, PRJ) == expected_stock
    assert await _ledger_cost(db) == expected_cost
    assert await _cost_entries(db) == expected_cost
    cost = await project_material_cost(TenantData.for_resolved_org(db, T), T, PROJECT)
    # the report helper presents money in stotinki (2 dp); the basis above is exact
    assert cost["total_cost"] == pytest.approx(round(float(expected_cost), 2), abs=1e-9)


# ═══════════════════ F-55-C23-01 — exact FIFO layers ═══════════════════

def test_inbound_layer_parts_is_one_layer_per_allocation_with_exact_price():
    row = {"movement_id": "acc", "quantity": "30000", "unit_value": "1.6667",
           "layer_allocations": [
               {"source_movement_id": "r1", "layer_sequence": 1,
                "quantity": "10000", "unit_value": "1"},
               {"source_movement_id": "r2", "layer_sequence": 1,
                "quantity": "20000", "unit_value": "2"}]}
    assert inbound_layer_parts(row) == [
        (1, Decimal("10000"), Decimal("1"), "BGN"),
        (2, Decimal("20000"), Decimal("2"), "BGN")]
    # A plain receive is ONE layer, part 1, at its own price.
    assert inbound_layer_parts({"movement_id": "r", "quantity": "5", "unit_value": "3"}) \
        == [(1, Decimal("5"), Decimal("3"), "BGN")]
    # Exact value: never 30000 × 1.6667 = 50001.
    assert allocations_value(row["layer_allocations"]) == Decimal("50000.0000")


async def test_mixed_prices_full_accept_keeps_two_exact_layers_in_fifo_order(
        canonical_mongo_db, allow_always_gate):
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    r1 = await run.receive("10000", "1")
    r2 = await run.receive("20000", "2")
    disp = await run.dispatch("30000")
    acc = await run.accept(disp, "30000")

    prj = await run.stock(PRJ)
    assert prj["layer_count"] == 2
    assert Decimal(prj["total_value"]) == Decimal("50000")
    # FIFO order is the dispatch order (oldest receive first), stable ids.
    assert [(l["source_movement_id"], l["layer_sequence"], Decimal(l["unit_value"]))
            for l in prj["layers"]] == [(acc.movement_id, 1, Decimal("1")),
                                        (acc.movement_id, 2, Decimal("2"))]
    assert [a["source_movement_id"] for a in acc.envelope["layer_allocations"]] \
        == [r1.movement_id, r2.movement_id]
    wh = await run.stock(WH)
    assert Decimal(wh["quantity"]) == 0
    assert await _batches_value(db, WH) == 0          # both receive batches drained
    assert await _batches_value(db, PRJ) == Decimal("50000")

    # FIFO consume takes the @1 layer first.
    c1 = await run.consume("10000")
    assert _alloc_value(c1) == Decimal("10000")
    await _assert_agree(run, Decimal("10000"), Decimal("40000"))
    c2 = await run.consume("20000")
    assert _alloc_value(c2) == Decimal("40000")
    await _assert_agree(run, Decimal("50000"), Decimal("0"))


async def test_partial_accepts_then_consume_and_write_off_keep_the_exact_sum(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    monkeypatch.setenv("FILE_REGISTRY_ENABLED", "1")
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await run.receive("7", "1.13")
    await run.receive("11", "2.07")
    received = Decimal("7") * Decimal("1.13") + Decimal("11") * Decimal("2.07")  # 30.68
    disp = await run.dispatch("18")

    a1 = await run.accept(disp, "5")
    v1 = _alloc_value(a1)
    assert Decimal((await run.stock(PRJ))["total_value"]) == v1
    assert (await run.stock(PRJ))["layer_count"] == 2
    await _assert_agree(run, Decimal("0"), v1)

    a2 = await run.accept(disp, "13")
    v2 = _alloc_value(a2)
    assert v1 + v2 == received                        # nothing created or lost
    await _assert_agree(run, Decimal("0"), received)

    c1 = await run.consume("4")
    w1 = await run.write_off("6")
    cost = _alloc_value(c1) + _alloc_value(w1)
    await _assert_agree(run, cost, received - cost)
    c2 = await run.consume("8")
    await _assert_agree(run, cost + _alloc_value(c2), Decimal("0"))
    assert cost + _alloc_value(c2) == received        # 30.68 exactly

    # the „фира" line is exact too
    pmc = await project_material_cost(TenantData.for_resolved_org(db, T), T, PROJECT)
    assert pmc["waste_cost"] == pytest.approx(round(float(_alloc_value(w1)), 2), abs=1e-9)


async def test_rebuild_twice_and_sync_keep_exact_values(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    from app.routes import material_smr
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10000", "1")
    await run.receive("20000", "2")
    disp = await run.dispatch("30000")
    await run.accept(disp, "12000")
    await run.accept(disp, "18000")
    await run.consume("15000")
    await run.write_off("5000")
    # PRJ layers (FIFO): 4000@1, 8000@2 (accept 1) · 6000@1, 12000@2 (accept 2)
    # consume 15000 = 4000@1 + 8000@2 + 3000@1 = 23000
    # write-off 5000 = 3000@1 + 2000@2 = 7000 („фира")
    expected_cost = Decimal("30000")
    await _assert_agree(run, expected_cost, Decimal("50000") - expected_cost)

    live = await _projection_snapshot(db)
    await rebuild_from_ledger(db, tenant_id=T)
    first = await _projection_snapshot(db)
    await rebuild_from_ledger(db, tenant_id=T)
    second = await _projection_snapshot(db)
    assert live == first == second
    await _assert_agree(run, expected_cost, Decimal("20000"))

    before = await _all_reports()
    await material_smr.sync_material_entries(PROJECT, user=_user())
    after = await _all_reports()
    assert before == after
    _assert_all(after, 30000.0, 7000.0)
    await _assert_agree(run, expected_cost, Decimal("20000"))


async def test_consume_from_a_mixed_bucket_follows_fifo_across_rows(
        canonical_mongo_db, allow_always_gate):
    """Direct delivery + acceptance in one project bucket: the batch rows and
    the FIFO layers share one identity, so every drain hits its own batch."""
    client, db = canonical_mongo_db
    run = _Run(client, allow_always_gate, db)
    await run(CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT, source=SUP,
              destination=PRJ, quantity=Decimal("3"), unit_value=Decimal("5"),
              project_id=PROJECT)
    await run.receive("4", "1")
    await run.receive("6", "3")
    disp = await run.dispatch("10")
    await run.accept(disp, "10")                       # 4@1 + 6@3 = 22
    assert Decimal((await run.stock(PRJ))["total_value"]) == Decimal("37")
    c = await run.consume("5")                         # 3@5 + 2@1 = 17
    assert _alloc_value(c) == Decimal("17")
    assert await _batches_value(db, PRJ) == Decimal("20")
    assert Decimal((await run.stock(PRJ))["total_value"]) == Decimal("20")


# ═══════════════════ F-55-C23-02 — legacy history + index ═══════════════════

def _legacy_rows(n=2, *, org=T):
    """``main``'s ``procurement.issue_to_project`` shape: no canonical ids."""
    return [{"id": f"issue-{uuid.uuid4().hex[:6]}", "org_id": org, "project_id": PROJECT,
             "type": "issue", "status": "posted", "created_at": BEFORE,
             "lines": [{"material_name": "Лепило", "unit": "bag", "qty_issued": 10,
                        "unit_price": 10, "total_price": 100}], "total": 100}
            for _ in range(n)]


@pytest.fixture
async def fresh_db(canonical_mongo_db):
    client, _ = canonical_mongo_db
    name = "c24_idx_" + uuid.uuid4().hex[:8]
    try:
        yield client, client[name]
    finally:
        await client.drop_database(name)


async def _snapshot(db):
    return await db.warehouse_transactions.find({}, {"_id": 0}).sort("id", 1).to_list(None)


async def test_legacy_rows_startup_twice_then_canonical_write(fresh_db, allow_always_gate):
    client, db = fresh_db
    await db.warehouse_transactions.insert_many(_legacy_rows(2))
    await db.warehouse_transactions.insert_one(          # explicit null id, too
        {**_legacy_rows(1)[0], "movement_id": None})
    before = await _snapshot(db)

    first = await ensure_required_indexes_at_startup(db)
    assert first["ok"], first
    assert "wh_movements_unique_movement_id" in first["created"]
    await verify_required_indexes(db)
    info = (await db.warehouse_transactions.index_information())["wh_movements_unique_movement_id"]
    assert info["unique"] is True
    assert dict(info["partialFilterExpression"]) == {"movement_id": {"$type": "string"}}
    assert info["key"] == [("tenant_id", 1), ("movement_id", 1)]

    second = await ensure_required_indexes_at_startup(db)    # repeated startup
    assert second == {"ok": True, "created": [], "error": None}
    assert await _snapshot(db) == before                     # history untouched
    assert all("movement_id" not in r or r["movement_id"] is None for r in before)

    # The canonical writer works on that database …
    run = _Run(client, allow_always_gate, db)
    rcv = await run.receive("2", "4")
    assert Decimal((await run.stock(WH))["total_value"]) == Decimal("8")
    # … and a canonical movement id is still unique.
    row = await db.warehouse_transactions.find_one({"movement_id": rcv.movement_id}, {"_id": 0})
    with pytest.raises(DuplicateKeyError):
        await db.warehouse_transactions.insert_one({**row, "ledger_sequence": 999})
    assert await _snapshot(db) != before                      # legacy rows still there
    assert len([r for r in await _snapshot(db) if r.get("type") == "issue"]) == 3


async def test_real_legacy_shape_counts_before_the_cutover_on_every_report(
        canonical_mongo_db, allow_always_gate, monkeypatch):
    """C22's 100 + 30 = 130, with the legacy row in its REAL shape (no
    invented ``movement_id``) under the C24 index."""
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db)
    await _seed(db)
    legacy = _legacy_rows(1)[0]
    await db.warehouse_transactions.insert_one(legacy)
    run = _Run(client, allow_always_gate, db)
    await run.receive("10", "10")
    disp = await run.dispatch("5")
    await run.accept(disp, "5")
    await run.consume("3")
    _assert_all(await _all_reports(), 130.0, 0.0)
    stored = await db.warehouse_transactions.find_one({"id": legacy["id"]}, {"_id": 0})
    assert "movement_id" not in stored and "tenant_id" not in stored


async def test_pre_c24_full_unique_index_is_accepted_and_kept(fresh_db):
    """A database from before C24 (no legacy rows) holds the FULL unique
    index under our name: it is strictly stronger, so it is kept as is."""
    _, db = fresh_db
    await db.warehouse_transactions.create_index(
        [("tenant_id", 1), ("movement_id", 1)], name="wh_movements_unique_movement_id",
        unique=True)
    result = await ensure_required_indexes_at_startup(db)
    assert result["ok"], result
    assert "wh_movements_unique_movement_id" not in result["created"]
    await verify_required_indexes(db)
    info = (await db.warehouse_transactions.index_information())["wh_movements_unique_movement_id"]
    assert info["unique"] is True and "partialFilterExpression" not in info


async def test_old_index_with_other_options_is_a_documented_fail_closed_conflict(fresh_db):
    """Our name, other options (non-unique): never dropped or rebuilt
    automatically. Startup reports the conflict, the writer stays
    fail-closed, the index and the data are untouched."""
    _, db = fresh_db
    await db.warehouse_transactions.insert_many(_legacy_rows(2))
    await db.warehouse_transactions.create_index(
        [("tenant_id", 1), ("movement_id", 1)], name="wh_movements_unique_movement_id")
    before = await _snapshot(db)
    result = await ensure_required_indexes_at_startup(db)
    assert result["ok"] is False
    assert len(result["conflicts"]) == 1
    assert "wh_movements_unique_movement_id" in result["conflicts"][0]
    assert "partialFilterExpression" in result["conflicts"][0]
    # every other required index was still created
    assert "wh_movements_unique_sequence" in result["created"]
    with pytest.raises(IndexMissingError) as exc:
        await verify_required_indexes(db)
    assert "wh_movements_unique_movement_id" in str(exc.value)
    info = (await db.warehouse_transactions.index_information())["wh_movements_unique_movement_id"]
    assert not info.get("unique") and "partialFilterExpression" not in info
    assert await _snapshot(db) == before
    # a repeated startup is the same, still nothing dropped
    again = await ensure_required_indexes_at_startup(db)
    assert again["ok"] is False and again["created"] == []


def test_required_movement_index_is_partial_on_canonical_rows():
    ri = next(r for r in REQUIRED_INDEXES if r.name == "wh_movements_unique_movement_id")
    assert ri.unique and ri.partial_filter == CANONICAL_MOVEMENT_FILTER
    keys = [("tenant_id", 1), ("movement_id", 1)]
    assert ri.matches({"key": keys, "unique": True,
                       "partialFilterExpression": {"movement_id": {"$type": "string"}}})
    assert ri.matches({"key": keys, "unique": True})               # stricter, kept
    assert not ri.matches({"key": keys, "unique": False})
    assert not ri.matches({"key": keys, "unique": True,
                           "partialFilterExpression": {"movement_id": {"$exists": True}}})
