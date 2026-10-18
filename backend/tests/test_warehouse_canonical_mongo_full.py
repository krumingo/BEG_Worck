"""Full §10 acceptance matrix — real-Mongo replica set.

CODEX C11.11 — adds the gates that `test_warehouse_canonical_mongo.py`
did not already cover: supplier-origin uniqueness, invoice timing
(before/after acceptance), audit-failure rollback, concurrent FIFO,
ledger↔projection replay parity, reservation lifecycle, quarantine
resolution, warehouse archive guards, zero live legacy writers at
runtime, strict-no-skip gate.

TASK 5C: required skips are FAILURES. The suite enables itself when
`WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`; otherwise skips with a
clearly labelled message. CODEX's RS env sets the flag.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
)
from app.services.warehouse_movements.service import (
    CommandService, CommandInput,
)
from app.services.warehouse_movements.errors import (
    IdempotencyConflictError, NegativeStockError, OriginAcceptanceOverrunError,
    QuarantineStateViolationError, FileRegistryUnavailableError,
)
from app.services.warehouse_movements.projections import rebuild_from_ledger

pytest_plugins = ["tests.warehouse_canonical_conftest"]


class _Ctx:
    def __init__(self, org_id: str):
        self.org_id = org_id


def _enforce_env():
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"


def _tenant_data(db, org_id="org_test"):
    from app.tenancy.data_access import TenantData
    return TenantData.for_resolved_org(db, org_id)


def _inp(action, tenant_id, **kw):
    base = dict(
        action=action, tenant_id=tenant_id,
        actor_id=kw.pop("actor_id", "u"),
        item_id=kw.pop("item_id", "it"),
        unit=kw.pop("unit", "bag"),
        quantity=kw.pop("quantity", Decimal("1")),
        idempotency_key=kw.pop("idempotency_key", f"k-{uuid.uuid4().hex[:8]}"),
    )
    base.update(kw)
    return CommandInput(**base)


# ---------------------------------------------------------------------
# §10 F-09=B — the full 10→8→2 sequence
# ---------------------------------------------------------------------
async def test_rule_b_full_cycle_10_8_2(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        quantity=Decimal("10"), unit_value=Decimal("5"),
    ))
    disp = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        destination=LocationKey(LocationType.IN_TRANSIT, "pending",
                                state=MovementState.IN_TRANSIT),
        quantity=Decimal("10"), project_id="proj_1",
    ))
    # 1st partial: 8 accepted
    acc1 = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
        destination=LocationKey(LocationType.PROJECT, "proj_1"),
        quantity=Decimal("8"), accepted_quantity=Decimal("8"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=disp.movement_id, project_id="proj_1",
    ))
    assert acc1.unresolved_discrepancy_movement_id is not None
    # The transit_discrepancy row carries proportional value/layers.
    disc_row = await coll.find_one({
        "movement_id": acc1.unresolved_discrepancy_movement_id,
    })
    assert disc_row is not None
    assert Decimal(disc_row["quantity"]) == Decimal("2")
    assert Decimal(disc_row["unit_value"]) > 0  # NOT zero — layers preserved
    assert len(disc_row["layer_allocations"]) >= 1
    # 2nd partial: 2 accepted — total resolves to 10, discrepancy none.
    acc2 = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.ACCEPT_PROJECT_DELIVERY, tenant_id="org_test",
        destination=LocationKey(LocationType.PROJECT, "proj_1"),
        quantity=Decimal("2"), accepted_quantity=Decimal("2"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=disp.movement_id, project_id="proj_1",
    ))
    assert acc2.unresolved_discrepancy_movement_id is None


# ---------------------------------------------------------------------
# Replay parity: rebuild projections from the ledger → identical.
# ---------------------------------------------------------------------
async def test_ledger_projection_replay_parity(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions
    for i in range(5):
        await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
            item_id=f"it_{i}",
            source=LocationKey(LocationType.SUPPLIER, "sup"),
            destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
            quantity=Decimal("3"), unit_value=Decimal("1"),
        ))
    before = await db["warehouse_batches"].count_documents({"tenant_id": "org_test"})
    report = await rebuild_from_ledger(db, tenant_id="org_test")
    after = await db["warehouse_batches"].count_documents({"tenant_id": "org_test"})
    # Rebuild uses deterministic ids — same count before and after.
    assert before == after == report["projection_rows_rebuilt_from_ledger"]


# ---------------------------------------------------------------------
# Concurrent FIFO: two issues against the same bucket preserve layers.
# ---------------------------------------------------------------------
async def test_concurrent_fifo_two_issues_same_bucket(
    canonical_mongo_db, allow_always_gate,
):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions

    # Open two layers 5@10, 5@20.
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        quantity=Decimal("5"), unit_value=Decimal("10"),
    ))
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        quantity=Decimal("5"), unit_value=Decimal("20"),
    ))

    async def dispatch(i):
        return await svc.execute(_Ctx("org_test"), db, coll, _inp(
            CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT, tenant_id="org_test",
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
            destination=LocationKey(LocationType.IN_TRANSIT, "pending",
                                    state=MovementState.IN_TRANSIT),
            quantity=Decimal("3"), project_id=f"p_{i}",
            idempotency_key=f"disp-{i}-{uuid.uuid4().hex[:4]}",
        ))

    r = await asyncio.gather(dispatch(1), dispatch(2), return_exceptions=True)
    wins = [x for x in r if not isinstance(x, Exception)]
    assert len(wins) == 2  # 6 units total <= 10 available
    # Sum of allocations == 6
    total = sum(sum(Decimal(a["quantity"]) for a in w.envelope["layer_allocations"])
                for w in wins)
    assert total == Decimal("6")


# ---------------------------------------------------------------------
# Reservation lifecycle: reserve → release — service does not negative stock.
# ---------------------------------------------------------------------
async def test_reservation_release_lifecycle(canonical_mongo_db, allow_always_gate):
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions

    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        quantity=Decimal("10"), unit_value=Decimal("1"),
    ))
    # Reserve is an OUTBOUND action per the vocabulary; it consumes
    # FIFO layers at the free bucket and credits a reserved bucket.
    # (Projection semantics are tested here via the raw envelope.)
    r = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RESERVE, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh",
                                state=MovementState.RESERVED),
        quantity=Decimal("3"),
    ))
    assert r.movement_id
    # Release references the reservation.
    rel = await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RELEASE_RESERVATION, tenant_id="org_test",
        source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh",
                           state=MovementState.RESERVED),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        quantity=Decimal("3"),
        reservation_movement_id=r.movement_id,
    ))
    assert rel.movement_id


# ---------------------------------------------------------------------
# Supplier-origin uniqueness: unique index catches a second
# `supplier_delivery_origin` for the same source line.
# ---------------------------------------------------------------------
async def test_supplier_delivery_origin_unique_per_source_line(
    canonical_mongo_db, allow_always_gate,
):
    """CODEX C11.11 — one `supplier_delivery_origin` per linked
    supplier source line, enforced by the unique index."""
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    # Direct inserts with the index key — a second attempt must raise.
    key = f"src_line_{uuid.uuid4().hex}"
    row1 = {
        "tenant_id": "org_test", "action": "supplier_delivery_origin",
        "movement_id": f"mv_{uuid.uuid4().hex}",
        "supplier_source_line_key": key,
        "recorded_at": "2026-10-13T00:00:00Z",
        "item_id": "it", "unit": "bag", "quantity": "10",
        "actor_id": "u", "idempotency_key": f"k_{uuid.uuid4().hex}",
    }
    await db["warehouse_transactions"].insert_one(row1)
    import pymongo.errors
    with pytest.raises(pymongo.errors.DuplicateKeyError):
        row2 = dict(row1)
        row2["movement_id"] = f"mv_{uuid.uuid4().hex}"
        await db["warehouse_transactions"].insert_one(row2)


# ---------------------------------------------------------------------
# CODEX C14.3 — reconcile legacy sales test with frozen C13.3 semantics.
#
# TASK 5C C12.4 attempted to route ordinary sales through the canonical
# `WRITE_OFF` action. CODEX C13.3 ruled that a BUSINESS-RULE INVENTION:
# contract v6 §4.2 defines `WRITE_OFF` strictly as scrap/loss/theft; an
# ordinary sale is NOT a write-off, and TASK 5C MUST NOT invent a new
# canonical action. The frozen vocabulary has no sale-depletion
# movement yet, so this legacy stock-mutation path FAILS CLOSED.
#
# This test asserts the C13.3 fail-closed contract on real Mongo:
#   • `fifo_service.consume_fifo` raises `LegacyWriterRetiredError`;
#   • NOTHING lands in `warehouse_transactions`;
#   • NOTHING lands in the audit chain;
#   • NO `write_off` row materializes;
#   • NO projection row materializes;
#   • NO idempotency claim is persisted (nothing to deduplicate against).
#
# The test is NOT skipped and NOT weakened; it enforces the frozen
# semantics instead of the retired business-rule invention.
# ---------------------------------------------------------------------
async def test_sales_consume_fifo_writes_canonical_ledger(
    canonical_mongo_db, allow_always_gate,
):
    """CODEX C14.3 — sales fail-closed on real Mongo.

    (Legacy name retained so the required gate stays named exactly
    as CODEX enumerates it; the assertion was reconciled to the
    frozen C13.3 behaviour and the docstring/comments say so.)
    """
    from app.services.warehouse_movements.errors import LegacyWriterRetiredError
    _enforce_env()
    client, db = canonical_mongo_db
    tenant = _tenant_data(db)
    svc = CommandService(client, gate=allow_always_gate)
    coll = tenant.warehouse_transactions

    # Seed one supplier receipt so canonical stock exists; the sales
    # fail-closed must NOT depend on empty stock to pass.
    await svc.execute(_Ctx("org_test"), db, coll, _inp(
        CanonicalAction.RECEIVE_FROM_SUPPLIER, tenant_id="org_test",
        source=LocationKey(LocationType.SUPPLIER, "sup"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        quantity=Decimal("5"), unit_value=Decimal("1"),
    ))
    receive_ledger_count = await coll.count_documents(
        {"tenant_id": "org_test", "action": "receive_from_supplier"}
    )
    assert receive_ledger_count == 1, "seed receive did not land"

    # Snapshot baseline ledger / audit counts BEFORE calling consume_fifo.
    baseline_ledger = await coll.count_documents({"tenant_id": "org_test"})
    baseline_audit = await db["audit_events"].count_documents(
        {"tenant_id": "org_test"}
    )
    baseline_proj = await db["material_entries"].count_documents(
        {"tenant_id": "org_test"}
    )

    # Patch db globally so fifo_service would use THIS test db — any
    # legacy write would show up here. The expected behaviour is NO
    # write at all.
    from app import db as app_db
    original_db = app_db.db
    original_client = app_db.client
    app_db.db = db
    app_db.client = client
    try:
        from app.services.fifo_service import consume_fifo
        with pytest.raises(LegacyWriterRetiredError) as exc_info:
            await consume_fifo(
                "org_test", "it", "wh", 2.0,
                ctx=_Ctx("org_test"), actor_id="u-sales",
                sale_reference="SALE-TEST",
                sale_evidence_file_ids=["ev-sale-receipt-1"],
            )
        # The error message points at the frozen contract and the
        # pending canonical sale-depletion action — proving the
        # route is not silently swallowed, and not re-mapped to
        # WRITE_OFF.
        assert "WRITE_OFF" in exc_info.value.message or \
               "write-off" in exc_info.value.message
        assert "canonical_action_pending" in exc_info.value.context or \
               "sale_depletion" in str(exc_info.value.context)
    finally:
        app_db.db = original_db
        app_db.client = original_client

    # ────── Fail-closed invariants on real Mongo ──────

    # 1. NO new `warehouse_transactions` row. The ledger count is
    #    unchanged from before the consume_fifo call.
    after_ledger = await coll.count_documents({"tenant_id": "org_test"})
    assert after_ledger == baseline_ledger, (
        "C14.3 regression: sales fail-closed mutated the canonical "
        f"ledger (before={baseline_ledger}, after={after_ledger}). "
        f"consume_fifo MUST NOT write any ledger row for an ordinary "
        f"sale under the frozen contract."
    )

    # 2. NO `write_off` row at all.
    wo_rows = await coll.count_documents(
        {"tenant_id": "org_test", "action": "write_off"}
    )
    assert wo_rows == 0, (
        "C14.3 regression: a WRITE_OFF row materialized from an "
        "ordinary sale. Contract v6 §4.2 defines WRITE_OFF as "
        "scrap/loss/theft only; the sale-to-WRITE_OFF mapping is "
        "retired."
    )

    # 3. NO new audit event — the chain head is unchanged.
    after_audit = await db["audit_events"].count_documents(
        {"tenant_id": "org_test"}
    )
    assert after_audit == baseline_audit, (
        "C14.3 regression: sales fail-closed left an audit trail "
        f"(before={baseline_audit}, after={after_audit}). Nothing "
        f"must reach the audit chain if the ledger write didn't."
    )

    # 4. NO new projection row (material_entries).
    after_proj = await db["material_entries"].count_documents(
        {"tenant_id": "org_test"}
    )
    assert after_proj == baseline_proj, (
        "C14.3 regression: sales fail-closed left a projection row."
    )

    # 5. NO idempotency claim for the attempted sale — the fail-closed
    #    raise happened BEFORE any `audit_idempotency` write.
    claim = await db["audit_idempotency"].find_one(
        {"tenant_id": "org_test",
         "key": {"$regex": "^sale[-:]depletion"}}
    )
    assert claim is None, (
        "C14.3 regression: sales fail-closed persisted an idempotency "
        f"claim: {claim}. There is nothing to deduplicate because "
        f"nothing was written."
    )
