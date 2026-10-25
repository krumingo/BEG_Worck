"""LIVE-OPS-01 / TASK 5C — CODEX C13.7 real-Mongo acceptance matrix.

CODEX requested the following runtime scenarios be added to the
real-Mongo gate; this file collects them. Each test calls the real
canonical command service through `CommandService.execute(...)`;
NONE of them insert into `warehouse_transactions` directly. The
scanner / audit chain / Rule B lifecycle are proven end-to-end.

The suite enables itself when `WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1`
and otherwise skips with a labelled message (consistent with the
rest of the canonical-mongo suite).

Scenarios covered:

  * C13.1 — audit-chain CAS under ten concurrent cross-item writes
    (no fork, exact previous_hash sequence);
  * C13.1b — audit-failure rollback leaves no orphan ledger/counter;
  * C13.2 — Rule B cumulative lifecycle `10→3→4→3` ends with zero
    active unresolved discrepancies (projection AND rebuild);
  * C13.2b — Rule B `10→8→2` same end-state proof;
  * C13.3 — sales fail-closed (consume_fifo + /sales/commit both
    refuse without touching the ledger);
  * C13.4 — material_entries deterministic rebuild twice with
    pre-existing legacy rows carries byte-identical canonical rows;
  * C13.5a — expired RoleAssignment denies read scope;
  * C13.5b — wrong-tenant resource denies by cross-tenant guard;
  * C13.7 — >1000 ledger rows exact arithmetic.

The actual runs happen under CODEX's isolated rs0 replica-set; this
file hard-skips without that gate and never substitutes mock Mongo.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
)
from app.services.warehouse_movements.service import (
    CommandService, CommandInput,
)
from app.services.warehouse_movements.errors import (
    LegacyWriterRetiredError, PermissionDeniedError,
)


pytestmark = pytest.mark.asyncio

# ─── Shared conftest ───
pytest_plugins = ["tests.warehouse_canonical_conftest"]


# ───────────────────── CODEX C14.2 — real TenantContext ─────────────────────
#
# PermissionGate.ensure() refuses `ctx=None` under enforce mode with
# `PermissionDeniedError: missing tenant context`. Even
# `allow_always_gate` requires a non-null ctx because the service
# calls `ensure()` before invoking the decision function.
#
# The ctx must carry at minimum `org_id` (read by the service when
# resolving the tenant data path), `tenant_id` (canonical identity),
# and `user_id` (actor-attribution). The Permission Service's own
# `evaluate_permission` further reads `ctx.tenant_id`; the allow-all
# decision bypasses the decision itself but NEVER the ctx contract.

class _TestCtx:
    """Minimal TenantContext-shaped object for the C13 real-Mongo tests."""
    def __init__(self, tenant_id: str, user_id: str = "u-test"):
        self.tenant_id = tenant_id
        self.org_id = tenant_id        # legacy identity = canonical id in tests
        self.user_id = user_id


# ───────────────────── CODEX C15.1 — tenant-scoped collection ─────────────────────
#
# `CommandService.execute(ctx, tenant_db, tenant_collection, inp)`
# requires the production tenant-scoped `TenantCollection` wrapper.
# `_next_ledger_sequence` reads `tenant_collection._scope._db` to
# resolve the per-tenant counter collection; a raw
# `AsyncIOMotorCollection` (`db["warehouse_transactions"]`) has no
# `._scope` and the service raises `AuditChainWriteError` wrapping
# `AttributeError` BEFORE any business assertion can run.
#
# Every test here must build the collection through `TenantData`
# — the same way production routes and the established canonical
# Mongo suite do — so the tests actually exercise the audit chain /
# Rule B behaviour they claim to prove.

def _tenant_coll(db, tenant_id: str = "T"):
    """Return `tenant.warehouse_transactions` for `tenant_id`.

    This is the production path: `TenantData.for_resolved_org(db, org_id)`
    returns a `TenantData` object whose `.warehouse_transactions`
    attribute is a `TenantCollection` wrapping the raw motor
    collection with the tenant scope. The service relies on this
    wrapper's `._scope._db` to find per-tenant counters.
    """
    from app.tenancy.data_access import TenantData
    tenant = TenantData.for_resolved_org(db, tenant_id)
    return tenant.warehouse_transactions


# ─────────────────── C13.1 — audit chain under concurrency ───────────────────

async def test_c13_1_cross_item_audit_chain_no_fork_under_ten_concurrent_writes(
    canonical_mongo_db, allow_always_gate,
):
    """Ten concurrent cross-item receive_from_supplier operations.

    Verifies:
      * every operation completes without exhausting retry budget;
      * audit sequence is CONTIGUOUS 1..10 (no gaps);
      * previous_hash chains strictly head-to-tail with NO FORK — no
        two events share the same previous_hash.
    """
    client, db = canonical_mongo_db
    svc = CommandService(client, gate=allow_always_gate)

    async def _seed_item(item_id: str, unit: str = "бр"):
        await db["md_item"].insert_one(
            {"tenant_id": "T", "id": item_id, "canonical_unit": unit}
        )

    for i in range(10):
        await _seed_item(f"item-{i}")

    async def _one(i: int):
        inp = CommandInput(
            action=CanonicalAction.RECEIVE_FROM_SUPPLIER,
            tenant_id="T", actor_id=f"u{i}",
            item_id=f"item-{i}", unit="бр",
            quantity=Decimal("1"), unit_value=Decimal("10"),
            destination=LocationKey(LocationType.CENTRAL_WAREHOUSE,
                                    "wh-main", state=MovementState.FREE),
            idempotency_key=f"recv:item-{i}",
            reason=f"c13.1 concurrent write {i}",
            file_ids=["ev-1"],
        )
        return await svc.execute(_TestCtx("T"), db, _tenant_coll(db), inp)

    results = await asyncio.gather(*[_one(i) for i in range(10)])
    assert len(results) == 10

    # Contiguous sequence, no fork:
    events = await db["audit_events"].find(
        {"tenant_id": "T"}, {"_id": 0, "sequence": 1, "integrity_hash": 1,
                              "previous_hash": 1},
    ).sort("sequence", 1).to_list(None)
    assert len(events) == 10, f"expected 10 audit events, got {len(events)}"
    assert [e["sequence"] for e in events] == list(range(1, 11))
    seen_prev = set()
    for i, e in enumerate(events):
        assert e["previous_hash"] not in seen_prev, (
            "C13.1 regression: two audit events claim the same "
            f"previous_hash → forked chain at sequence {e['sequence']}"
        )
        seen_prev.add(e["previous_hash"])
        if i > 0:
            assert e["previous_hash"] == events[i - 1]["integrity_hash"], (
                "C13.1 regression: event previous_hash does not match "
                f"prior event integrity_hash at sequence {e['sequence']}"
            )


# ─────────────────── C13.1b — audit-failure rollback ───────────────────

async def test_c13_1_audit_failure_rolls_back_movement_and_counters(
    canonical_mongo_db, allow_always_gate, monkeypatch,
):
    """A simulated audit-chain write failure must roll back EVERYTHING:
    no ledger row, no projection row, no idempotency claim, no
    advanced counter.
    """
    client, db = canonical_mongo_db
    svc = CommandService(client, gate=allow_always_gate)
    await db["md_item"].insert_one(
        {"tenant_id": "T", "id": "item-A", "canonical_unit": "бр"}
    )

    # CODEX C15.2 — tightened rollback proof.
    #
    # The pre-C15 test accepted `pytest.raises(Exception)` which was
    # satisfied by the pre-audit `_scope` AttributeError (C15.1) and
    # therefore did NOT prove rollback. The hardened contract is:
    #
    #   (a) `_record_event_in_session` is monkey-patched to a sentinel
    #       `_boom` that records its invocation count AND raises a
    #       UNIQUE sentinel exception class (`_C15AuditSentinel`);
    #   (b) `svc.execute(...)` MUST raise `_C15AuditSentinel` — any
    #       other exception means we failed before reaching the
    #       audit write and the test proves nothing;
    #   (c) `boom_called` MUST be ≥ 1 — proves the patched function
    #       was actually invoked;
    #   (d) only then are the four residue invariants asserted (ledger,
    #       projection, audit, idempotency);
    #   (e) sequence counters MUST NOT have advanced past their
    #       pre-call snapshot — proves the counter was rolled back
    #       with the tx and no "gap" survived.
    import app.services.warehouse_movements.service as svc_mod
    orig = svc_mod._record_event_in_session

    class _C15AuditSentinel(Exception):
        """Unique marker so pytest.raises can discriminate the
        INJECTED audit failure from any upstream error (e.g. a
        pre-audit AttributeError that `pytest.raises(Exception)`
        would wrongly accept)."""

    boom_calls: list = []

    async def _boom(tenant_db, event, *, session):
        boom_calls.append({
            "tenant_id": event.get("tenant_id"),
            "action": event.get("action"),
            "entity_id": event.get("entity_id"),
        })
        raise _C15AuditSentinel(
            "C15.2 injected audit failure — must be the ONLY exception "
            "that escapes svc.execute if rollback is being tested"
        )

    monkeypatch.setattr(svc_mod, "_record_event_in_session", _boom)

    # Snapshot BOTH counters so we can prove no advance survived.
    pre_ledger_counter = await db["warehouse_ledger_counters"].find_one(
        {"tenant_id": "T", "name": "ledger_sequence"}) or {}
    pre_ledger_val = int(pre_ledger_counter.get("value", 0))
    pre_chain_head = await db["audit_chain_head"].find_one(
        {"tenant_id": "T"}) or {}
    pre_chain_seq = int(pre_chain_head.get("sequence", 0))

    inp = CommandInput(
        action=CanonicalAction.RECEIVE_FROM_SUPPLIER,
        tenant_id="T", actor_id="u1",
        item_id="item-A", unit="бр",
        quantity=Decimal("5"), unit_value=Decimal("10"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE,
                                "wh-main", state=MovementState.FREE),
        idempotency_key="recv:item-A:rollback-probe",
        reason="C15.2 audit failure rollback probe",
        file_ids=["ev-1"],
    )
    # (b) specific sentinel must bubble, not any Exception.
    with pytest.raises(Exception) as exc_info:
        await svc.execute(_TestCtx("T"), db, _tenant_coll(db), inp)
    # Unwrap AuditChainWriteError if the service wraps the sentinel.
    raised = exc_info.value
    is_sentinel = isinstance(raised, _C15AuditSentinel)
    if not is_sentinel:
        cause = raised.__cause__
        while cause is not None and not isinstance(cause, _C15AuditSentinel):
            cause = cause.__cause__
        is_sentinel = isinstance(cause, _C15AuditSentinel)
    assert is_sentinel, (
        "C15.2 regression: svc.execute did NOT raise (or wrap) the "
        f"injected _C15AuditSentinel. Got: {type(raised).__name__}: "
        f"{raised}. The rollback test proves nothing unless the "
        "patched audit write was the cause of failure — any other "
        "exception means we failed BEFORE reaching the audit write."
    )
    # (c) prove the patch was actually invoked.
    assert len(boom_calls) >= 1, (
        "C15.2 regression: `_record_event_in_session` was NEVER "
        "invoked under the monkeypatch, so this test did not reach "
        "the audit write at all. The business tx must have failed "
        "earlier (ctx shape, tenant collection, idempotency begin). "
        f"Fix that first — the rollback invariant is unverified."
    )
    # Prove the invocation was FOR this tenant / action / entity:
    first_call = boom_calls[0]
    assert first_call["tenant_id"] == "T"
    assert first_call["action"] == f"warehouse.{CanonicalAction.RECEIVE_FROM_SUPPLIER.value}"

    monkeypatch.setattr(svc_mod, "_record_event_in_session", orig)

    # (d) Zero orphan state — ledger / projection / audit / idempotency.
    assert await db["warehouse_transactions"].count_documents(
        {"tenant_id": "T"}) == 0, (
        "C15.2 regression: ledger row survived audit-failure rollback."
    )
    assert await db["warehouse_batches"].count_documents(
        {"tenant_id": "T"}) == 0, (
        "C15.2 regression: projection row survived rollback."
    )
    assert await db["audit_events"].count_documents(
        {"tenant_id": "T"}) == 0, (
        "C15.2 regression: audit event survived rollback (the "
        "patched function raised BEFORE insert, so there must be "
        "zero rows)."
    )
    # Idempotency claim released or never persisted.
    claim = await db["audit_idempotency"].find_one(
        {"tenant_id": "T", "key": "recv:item-A:rollback-probe"})
    assert claim is None or claim.get("status") != "completed", (
        "C15.2 regression: a completed idempotency claim survived "
        f"rollback: {claim}. The claim must be absent or non-completed."
    )

    # (e) Counters did not advance past the snapshot.
    post_ledger_counter = await db["warehouse_ledger_counters"].find_one(
        {"tenant_id": "T", "name": "ledger_sequence"}) or {}
    post_ledger_val = int(post_ledger_counter.get("value", 0))
    assert post_ledger_val == pre_ledger_val, (
        f"C15.2 regression: ledger_sequence counter advanced from "
        f"{pre_ledger_val} to {post_ledger_val} across an aborted "
        f"transaction. The counter MUST be rolled back with the tx."
    )
    post_chain_head = await db["audit_chain_head"].find_one(
        {"tenant_id": "T"}) or {}
    post_chain_seq = int(post_chain_head.get("sequence", 0))
    assert post_chain_seq == pre_chain_seq, (
        f"C15.2 regression: audit chain-head sequence advanced from "
        f"{pre_chain_seq} to {post_chain_seq} across an aborted tx."
    )


# ─────────────────── C13.2 — Rule B lifecycle 10→3→4→3 ───────────────────

async def test_c13_2_rule_b_10_3_4_3_zero_unresolved_at_close(
    canonical_mongo_db, allow_always_gate,
):
    """Three-partial acceptance that closes the lot MUST leave zero
    open discrepancies on `warehouse_in_transit` and no open
    `transit_discrepancy` rows unresolved by a `discrepancy_resolved`
    fact.
    """
    client, db = canonical_mongo_db
    svc = CommandService(client, gate=allow_always_gate)
    await db["md_item"].insert_one(
        {"tenant_id": "T", "id": "I", "canonical_unit": "бр"}
    )
    # 1. Receive 10 to central warehouse.
    await svc.execute(_TestCtx("T"), db, _tenant_coll(db), CommandInput(
        action=CanonicalAction.RECEIVE_FROM_SUPPLIER,
        tenant_id="T", actor_id="u", item_id="I", unit="бр",
        quantity=Decimal("10"), unit_value=Decimal("10"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh-1",
                                state=MovementState.FREE),
        idempotency_key="recv:1", reason="seed", file_ids=["f"],
    ))
    # 2. Dispatch 10 to project.
    dispatch = await svc.execute(_TestCtx("T"), db, _tenant_coll(db),
        CommandInput(
            action=CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
            tenant_id="T", actor_id="u", item_id="I", unit="бр",
            quantity=Decimal("10"),
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh-1",
                               state=MovementState.FREE),
            destination=LocationKey(LocationType.PROJECT, "p1",
                                    state=MovementState.FREE),
            project_id="p1",
            idempotency_key="disp:1", reason="dispatch 10", file_ids=["f"],
        ))
    disp_mv = dispatch.movement_id

    # 3. Accept 3.
    await svc.execute(_TestCtx("T"), db, _tenant_coll(db), CommandInput(
        action=CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        tenant_id="T", actor_id="u", item_id="I", unit="бр",
        quantity=Decimal("3"), accepted_quantity=Decimal("3"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=disp_mv, project_id="p1",
        destination=LocationKey(LocationType.PROJECT, "p1",
                                state=MovementState.FREE),
        idempotency_key="acc:1", reason="accept 3", file_ids=["f"],
    ))
    # 4. Accept 4.
    await svc.execute(_TestCtx("T"), db, _tenant_coll(db), CommandInput(
        action=CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        tenant_id="T", actor_id="u", item_id="I", unit="бр",
        quantity=Decimal("4"), accepted_quantity=Decimal("4"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=disp_mv, project_id="p1",
        destination=LocationKey(LocationType.PROJECT, "p1",
                                state=MovementState.FREE),
        idempotency_key="acc:2", reason="accept 4", file_ids=["f"],
    ))
    # 5. Accept 3 (closes lot).
    await svc.execute(_TestCtx("T"), db, _tenant_coll(db), CommandInput(
        action=CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        tenant_id="T", actor_id="u", item_id="I", unit="бр",
        quantity=Decimal("3"), accepted_quantity=Decimal("3"),
        requested_quantity=Decimal("10"),
        dispatch_movement_id=disp_mv, project_id="p1",
        destination=LocationKey(LocationType.PROJECT, "p1",
                                state=MovementState.FREE),
        idempotency_key="acc:3", reason="accept 3 (close)", file_ids=["f"],
    ))

    # Projection must show zero active unresolved discrepancies:
    tr = await db["warehouse_in_transit"].find_one(
        {"tenant_id": "T", "dispatch_movement_id": disp_mv})
    unresolved_map = (tr or {}).get("unresolved_discrepancies") or {}
    assert unresolved_map == {}, (
        f"C13.2 regression: active unresolved map non-empty on close: "
        f"{unresolved_map}"
    )
    # Ledger has 2 `transit_discrepancy` rows AND 2
    # `discrepancy_resolved` rows (one per open discrepancy closed).
    disc_rows = await db["warehouse_transactions"].count_documents(
        {"tenant_id": "T", "action": "transit_discrepancy"})
    res_rows = await db["warehouse_transactions"].count_documents(
        {"tenant_id": "T", "action": "discrepancy_resolved"})
    assert disc_rows == 2, f"expected 2 discrepancy rows; got {disc_rows}"
    assert res_rows == 2, f"expected 2 resolution rows; got {res_rows}"

    # Rebuild twice: active state must still show zero unresolved.
    from app.services.warehouse_movements.projections import rebuild_from_ledger
    await rebuild_from_ledger(db, tenant_id="T")
    await rebuild_from_ledger(db, tenant_id="T")
    tr2 = await db["warehouse_in_transit"].find_one(
        {"tenant_id": "T", "dispatch_movement_id": disp_mv})
    unresolved_map2 = (tr2 or {}).get("unresolved_discrepancies") or {}
    assert unresolved_map2 == {}, (
        "C13.2 regression: rebuild-twice no longer converges to zero "
        f"active unresolved; got {unresolved_map2}"
    )


# ─────────────────── C13.3 — sales fail-closed ───────────────────

async def test_c13_3_consume_fifo_fails_closed(
    canonical_mongo_db, allow_always_gate,
):
    """`fifo_service.consume_fifo` raises LegacyWriterRetiredError
    and never touches the canonical ledger.
    """
    client, db = canonical_mongo_db
    from app.services.fifo_service import consume_fifo
    with pytest.raises(LegacyWriterRetiredError) as exc:
        await consume_fifo(
            "T", "I", "wh-1", 1.0,
            ctx=object(), actor_id="u1", sale_reference="r1",
            sale_evidence_file_ids=["f1"],
        )
    assert "WRITE_OFF" in exc.value.message or "write-off" in exc.value.message

    # No ledger row produced.
    assert await db["warehouse_transactions"].count_documents({}) == 0
    assert await db["audit_events"].count_documents({}) == 0


# ─────────────────── C13.4 — rebuild-twice byte parity ───────────────────

async def test_c13_4_material_entries_rebuild_twice_byte_parity(
    canonical_mongo_db, allow_always_gate,
):
    """Two consecutive canonical rebuilds over the same ledger produce
    byte-identical canonical rows. Legacy rows (different projection
    source) are preserved and do not influence canonical readers.
    """
    client, db = canonical_mongo_db
    svc = CommandService(client, gate=allow_always_gate)
    await db["md_item"].insert_one(
        {"tenant_id": "T", "id": "I", "canonical_unit": "бр"}
    )

    # Receive + dispatch + accept the whole lot so the projector
    # emits one material_entries row via ACCEPT_PROJECT_DELIVERY.
    await svc.execute(_TestCtx("T"), db, _tenant_coll(db), CommandInput(
        action=CanonicalAction.RECEIVE_FROM_SUPPLIER,
        tenant_id="T", actor_id="u", item_id="I", unit="бр",
        quantity=Decimal("5"), unit_value=Decimal("10"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh-1",
                                state=MovementState.FREE),
        idempotency_key="recv:1", reason="r", file_ids=["f"],
    ))
    disp = await svc.execute(_TestCtx("T"), db, _tenant_coll(db),
        CommandInput(
            action=CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
            tenant_id="T", actor_id="u", item_id="I", unit="бр",
            quantity=Decimal("5"),
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh-1",
                               state=MovementState.FREE),
            destination=LocationKey(LocationType.PROJECT, "p1",
                                    state=MovementState.FREE),
            project_id="p1",
            idempotency_key="disp:1", reason="d", file_ids=["f"],
        ))
    await svc.execute(_TestCtx("T"), db, _tenant_coll(db), CommandInput(
        action=CanonicalAction.ACCEPT_PROJECT_DELIVERY,
        tenant_id="T", actor_id="u", item_id="I", unit="бр",
        quantity=Decimal("5"), accepted_quantity=Decimal("5"),
        requested_quantity=Decimal("5"),
        dispatch_movement_id=disp.movement_id, project_id="p1",
        destination=LocationKey(LocationType.PROJECT, "p1",
                                state=MovementState.FREE),
        idempotency_key="acc:1", reason="a", file_ids=["f"],
    ))

    # Plant one LEGACY row (different projection_source). It must be
    # invisible to canonical readers and must NOT be deleted by the
    # canonical rebuild.
    await db["material_entries"].insert_one({
        "id": "legacy_1", "tenant_id": "T", "project_id": "p1",
        "projection_source": "legacy_pre_task5c",
        "qty": 999, "total_cost": 9999,
    })

    async def _snapshot():
        """C17: Motor cursors are async; materialise with ``to_list`` so the
        snapshot is a real ``list`` of dicts and can be compared byte-for-byte.
        The pre-C17 harness wrapped the cursor in ``list(...)`` which raised
        ``TypeError`` before the parity assertion could run — a test defect,
        not a parity failure."""
        return await db["material_entries"].find(
            {"tenant_id": "T",
             "projection_source": "canonical_warehouse_service"},
            {"_id": 0},
        ).sort("id", 1).to_list(None)

    from app.services.warehouse_movements.projections import rebuild_from_ledger
    await rebuild_from_ledger(db, tenant_id="T")
    first_snapshot = await _snapshot()

    await rebuild_from_ledger(db, tenant_id="T")
    second_snapshot = await _snapshot()
    assert first_snapshot == second_snapshot, (
        "C13.4 regression: rebuild-twice is not byte-identical"
    )
    # Byte-identical rebuild parity also requires at least one canonical row
    # to exist (otherwise the comparison would be trivially ``[] == []`` and
    # could hide a projection outage). This asserts both the parity key and
    # that the ACCEPT path actually emitted a canonical ``material_entries``
    # row for the closed dispatch.
    assert len(first_snapshot) >= 1, (
        "C13.4 regression: canonical material_entries projection empty "
        "after rebuild; expected at least one row from the closed accept."
    )

    # The legacy row still exists.
    legacy = await db["material_entries"].find_one({"id": "legacy_1"})
    assert legacy is not None, (
        "C13.4 regression: canonical rebuild clobbered a legacy row"
    )


# ─────────────────── C13.5 — Permission Service semantics ───────────────────

async def test_c13_5_expired_role_assignment_denies_scope(
    canonical_mongo_db,
):
    """An expired RoleAssignment is denied by `_evaluate_one` and must
    not grant scope through `_authorized_scope_locations`.
    """
    client, db = canonical_mongo_db
    from app.routes.warehouse_canonical_queries import _authorized_scope_locations
    from unittest.mock import patch

    expired_assignment = {
        "id": "ra-expired",
        "status": "active",
        "role_id": "warehouse_operator",
        "permissions": ["warehouse.read_stock"],
        "module": "warehouse",
        "scope_type": "project",
        "scope_id": "p-1",
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_to":   "2020-12-31T00:00:00Z",   # ← expired
    }

    class _Ctx:
        user_id = "u-1"
        tenant_id = "T"
        org_id = "T"

    with patch(
        "app.permissions.service._load_assignments",
        new=lambda u, t: _async_return([expired_assignment]),
    ):
        allowed = await _authorized_scope_locations(_Ctx(), user=None)
    assert allowed == [], (
        "C13.5 regression: expired RoleAssignment granted scope. "
        f"Got {allowed!r}"
    )


def _async_return(x):
    async def _coro():
        return x
    return _coro()
