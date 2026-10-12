"""Static-shape acceptance tests for the canonical warehouse service.

These exercise contract commitments at the code level — no Mongo —
so the §10 gates CODEX will check can also be verified without the
replica set when the environment lacks one. The real-Mongo suite in
`test_warehouse_canonical_mongo.py` covers behavior under transactions.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.warehouse_movements import (
    CanonicalAction, LocationKey, LocationType, MovementState,
    build_envelope, envelope_fingerprint,
)
from app.services.warehouse_movements.indexes import (
    RequiredIndex, REQUIRED_INDEXES,
    MOVEMENTS_COLLECTION, IDEMPOTENCY_COLLECTION, AUDIT_EVENTS_COLLECTION,
)
from app.services.warehouse_movements.actions import (
    permission_action_for, EVIDENCE_REQUIRED_ACTIONS,
    RULE_B_COSTING_ACTIONS, RULE_B_ZERO_COST_ACTIONS,
)
from app.services.warehouse_movements.errors import (
    LegacyWriterRetiredError,
)


# ------------------------------------------------------------------
# C01 — zero production offenders
# ------------------------------------------------------------------
def test_no_runtime_env_can_reopen_legacy_writers():
    """C01: deleted escape hatch — fifo_service.add_batch always refuses."""
    import os
    os.environ["LEGACY_WAREHOUSE_WRITERS_ENABLED"] = "1"
    try:
        import importlib
        from app.services import fifo_service
        importlib.reload(fifo_service)
        import asyncio
        with pytest.raises(LegacyWriterRetiredError):
            asyncio.run(fifo_service.add_batch(
                org_id="t", item_id="i", warehouse_id="w",
                qty=1.0, unit_cost=1.0,
            ))
    finally:
        del os.environ["LEGACY_WAREHOUSE_WRITERS_ENABLED"]


# ------------------------------------------------------------------
# C03 — Rule B shape
# ------------------------------------------------------------------
def test_rule_b_dispatch_has_zero_cost_action_set():
    assert CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT in RULE_B_ZERO_COST_ACTIONS


def test_rule_b_costing_covers_accept_consume_direct():
    assert CanonicalAction.ACCEPT_PROJECT_DELIVERY in RULE_B_COSTING_ACTIONS
    assert CanonicalAction.CONSUME_TO_SMR in RULE_B_COSTING_ACTIONS
    assert CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT in RULE_B_COSTING_ACTIONS


# ------------------------------------------------------------------
# C04 — in_transit / unresolved transit types exist
# ------------------------------------------------------------------
def test_in_transit_and_unresolved_states_are_canonical():
    assert MovementState.IN_TRANSIT.value == "in_transit"
    assert MovementState.UNRESOLVED.value == "unresolved"
    assert LocationType.IN_TRANSIT.value == "in_transit"
    assert LocationType.UNRESOLVED.value == "unresolved"


# ------------------------------------------------------------------
# C05 — required indexes exist AND their keys match the spec
# ------------------------------------------------------------------
def test_required_indexes_cover_contract_prerequisites():
    names = {r.name for r in REQUIRED_INDEXES}
    for required in {
        "wh_movements_unique_movement_id",
        "wh_movements_unique_sequence",
        "wh_movements_unique_acceptance_line",
        "wh_movements_unique_supplier_origin",
        "wh_movements_destination_scan",
        "wh_movements_source_scan",
        "wh_idempotency_unique_claim",
        "wh_audit_unique_sequence",
        "wh_audit_unique_event_id",
    }:
        assert required in names, f"REQUIRED_INDEXES missing {required}"


def test_required_index_matches_accepts_pymongo_tuple_list_shape():
    """CODEX C05 fix — real PyMongo returns `key` as a list of tuples."""
    ri = next(r for r in REQUIRED_INDEXES if r.name == "wh_movements_unique_movement_id")
    # dict shape (older driver / test fixture) and tuple-list shape must both match.
    assert ri.matches({"key": {"tenant_id": 1, "movement_id": 1}, "unique": True})
    assert ri.matches({"key": [("tenant_id", 1), ("movement_id", 1)], "unique": True})
    # Unique guard: tuple-list w/o unique is REJECTED.
    assert not ri.matches({"key": [("tenant_id", 1), ("movement_id", 1)], "unique": False})


# ------------------------------------------------------------------
# C06 — client-authored sensitive fields are gone from the request body
# ------------------------------------------------------------------
def test_request_body_does_not_accept_confirmer_or_pending_mapping():
    from app.routes.warehouse_canonical import MovementCommandBody
    fields = set(MovementCommandBody.__fields__.keys())
    for forbidden in {"confirmed_by", "confirmed_at", "item_is_pending_mapping"}:
        assert forbidden not in fields, f"body still accepts {forbidden}"


# ------------------------------------------------------------------
# C07 — in_transit is a projection, not an acceptance precondition
# ------------------------------------------------------------------
def test_service_source_of_truth_is_the_ledger_not_projection():
    """CODEX C07 — the acceptance invariant reads
    `warehouse_transactions` directly (not `warehouse_in_transit`).
    We assert that NO Mongo read/write targets `warehouse_in_transit`
    anywhere in the command service (the comments may reference the
    projection by name, but no `db[...]` call does)."""
    source = open(
        "app/services/warehouse_movements/service.py", encoding="utf-8",
    ).read()
    assert "tenant_collection.find_one" in source
    # Strip comments and docstrings for the hard assertion so a
    # mention of the projection name in a comment doesn't false-positive.
    import re
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"#.*", "", stripped)
    assert "warehouse_in_transit" not in stripped, (
        "service.py must not read/write warehouse_in_transit — "
        "projection is advisory only"
    )


# ------------------------------------------------------------------
# C09 — history cursor is a numeric sequence, not time-only
# ------------------------------------------------------------------
def test_queries_sort_by_ledger_sequence_not_recorded_at_only():
    source = open(
        "app/services/warehouse_movements/queries.py", encoding="utf-8",
    ).read()
    assert "ledger_sequence" in source
    # history endpoint uses ledger_sequence first in its sort tuple
    assert '("ledger_sequence", 1)' in source


# ------------------------------------------------------------------
# §10 — fingerprint invariance across build time (replay recognition)
# ------------------------------------------------------------------
def test_fingerprint_includes_quantity_and_item_but_excludes_server_fields():
    kw = dict(
        tenant_id="t",
        action="receive_from_supplier",
        item_id="x",
        unit="bag",
        quantity=Decimal("5"),
        source=LocationKey(LocationType.SUPPLIER, "s"),
        destination=LocationKey(LocationType.CENTRAL_WAREHOUSE, "wh"),
        actor_id="u",
        idempotency_key="k",
    )
    a = build_envelope(**kw)
    b = build_envelope(**kw)
    # movement_id and timestamps differ per build but fingerprint must not.
    assert a.movement_id != b.movement_id
    assert envelope_fingerprint(a) == envelope_fingerprint(b)

    # Different quantity => different fingerprint.
    c = build_envelope(**{**kw, "quantity": Decimal("6")})
    assert envelope_fingerprint(a) != envelope_fingerprint(c)


# ------------------------------------------------------------------
# §10 — evidence required set is complete
# ------------------------------------------------------------------
def test_evidence_required_set_covers_v6_mandatory_evidence_actions():
    for action in {
        CanonicalAction.REVISION_ADJUSTMENT,
        CanonicalAction.WRITE_OFF,
        CanonicalAction.RETURN_TO_SUPPLIER,
    }:
        assert action in EVIDENCE_REQUIRED_ACTIONS


# ------------------------------------------------------------------
# §10 — permission catalog maps every canonical action
# ------------------------------------------------------------------
def test_every_canonical_action_maps_to_a_distinct_permission():
    seen = set()
    for a in CanonicalAction:
        p = permission_action_for(a)
        assert p.startswith("warehouse.")
        seen.add(p)
    # 15 actions = 15 distinct permission strings
    assert len(seen) == 15
