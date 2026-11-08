"""
C16 regressions — Rule B lifecycle resolution identity (CODEX feedback
https://github.com/krumingo/BEG_Worck/issues/52#issuecomment-6395322198).

The pre-C16 defect: the live service path passed the NEWLY CREATED
``discrepancy_resolved`` row's movement_id into the projection hint
``resolved_discrepancy_movement_ids``, while the active
``warehouse_in_transit.unresolved_discrepancies`` map is keyed by the
ORIGINAL ``transit_discrepancy`` row's movement_id. The projection
``$unset`` never matched, so the live projection kept the stale entries
even though the rebuild path (which reads the ``resolves_discrepancy_
movement_id`` on each ``discrepancy_resolved`` ledger row — the original
id) correctly closed them. The CODEX accelerated gate reproduced it on
real Mongo as ``test_c13_2_rule_b_10_3_4_3_zero_unresolved_at_close``
failing with two unresolved entries at close.

The C16 fix (same PR #55):
* ``service.execute`` collects the ORIGINAL discrepancy movement_ids in
  ``resolved_discrepancy_mv_ids`` and the NEW resolution movement_ids
  in a separate ``resolution_mv_ids`` list;
* both identities are forwarded to the projector as distinct hints
  (``resolved_discrepancy_movement_ids`` for closure, ``resolution_
  movement_ids`` for audit/reporting);
* the rebuild path is unchanged — it still keys off ``resolves_
  discrepancy_movement_id`` on the ``discrepancy_resolved`` ledger row,
  which is the original id — so live and rebuild converge to the SAME
  empty map on close under every acceptance split (10→3→4→3, 10→8→2,
  reorderings, etc.).

These are static-source regressions. The behavioural reproduction stays
in ``test_warehouse_canonical_c13_mongo.py::test_c13_2_rule_b_10_3_4_3_
zero_unresolved_at_close`` (requires a real Mongo replica set) and is
owned by CODEX for the C16 re-review.
"""
from pathlib import Path

import pytest


_SERVICE_SRC = Path("app/services/warehouse_movements/service.py").read_text()
_PROJ_SRC = Path("app/services/warehouse_movements/projections.py").read_text()


def test_c16_service_appends_original_discrepancy_mv_id_not_resolution_mv_id():
    """The resolved list carries the ORIGINAL ``disc_mv_id``.

    The pre-C16 defect was ``resolved_discrepancy_mv_ids.append(
    resolution_mv_id)``. This test asserts the fix is present AND the
    old bug is gone (defence in depth against a re-regression)."""
    assert "resolved_discrepancy_mv_ids.append(disc_mv_id)" in _SERVICE_SRC, (
        "C16 regression: service must forward the ORIGINAL discrepancy "
        "movement_id into the projection hint, not the new resolution id. "
        "Expected `resolved_discrepancy_mv_ids.append(disc_mv_id)`."
    )
    assert "resolved_discrepancy_mv_ids.append(resolution_mv_id)" not in _SERVICE_SRC, (
        "C16 regression: the pre-fix line "
        "`resolved_discrepancy_mv_ids.append(resolution_mv_id)` reappeared; "
        "this is the exact defect CODEX reproduced on real Mongo."
    )


def test_c16_service_also_exposes_resolution_movement_ids_hint():
    """The NEW resolution movement_ids are still carried to the projector
    through a distinct hint so audit/reporting can access them without
    re-querying the ledger. Both identities, both preserved."""
    assert "resolution_mv_ids: List[str] = []" in _SERVICE_SRC, (
        "C16: a second collection for the new resolution ids must be "
        "declared alongside the original-id list."
    )
    assert "resolution_mv_ids.append(resolution_mv_id)" in _SERVICE_SRC, (
        "C16: every resolution must also record its new movement_id."
    )
    assert 'projection_hints["resolution_movement_ids"]' in _SERVICE_SRC, (
        "C16: the new resolution ids must be forwarded as the distinct "
        "``resolution_movement_ids`` hint (keeps the active-map hint "
        "unambiguously keyed by the ORIGINAL ids)."
    )


def test_c16_projection_closure_still_keys_off_original_discrepancy_mv_id():
    """The projector's ``$unset`` continues to use the hint named
    ``resolved_discrepancy_movement_ids`` and does NOT use
    ``resolution_movement_ids`` for closure. This is the invariant that
    live and rebuild share. If closure switched to the resolution ids,
    rebuild would diverge (it keys off ``resolves_discrepancy_movement_
    id`` on the ``discrepancy_resolved`` row, which is the original id)."""
    assert 'hints.get("resolved_discrepancy_movement_ids")' in _PROJ_SRC, (
        "C16 regression: projector must still read "
        "`resolved_discrepancy_movement_ids` from the hints."
    )
    # The closure helper must $unset dotted paths keyed by the mv_ids it
    # was handed.
    assert "_close_unresolved_discrepancies" in _PROJ_SRC
    assert 'f"unresolved_discrepancies.{mv_id}"' in _PROJ_SRC


def test_c16_rebuild_closure_key_is_the_original_discrepancy_id_not_the_row_id():
    """``rebuild_from_ledger`` closes the active map using
    ``resolves_discrepancy_movement_id`` on each ``discrepancy_resolved``
    ledger row — which, by construction in
    ``_append_discrepancy_resolution``, is the ORIGINAL
    ``transit_discrepancy`` movement_id. This is the parity key between
    live and rebuild; a change here would re-introduce the C16 defect."""
    assert "resolves_discrepancy_movement_id" in _PROJ_SRC, (
        "C16 regression: rebuild must key off `resolves_discrepancy_"
        "movement_id` on the resolution row."
    )
    assert ('resolves_discrepancy_movement_id": resolved_discrepancy_movement_id'
            in _SERVICE_SRC), (
        "C16 regression: the resolution ledger row must carry the ORIGINAL "
        "discrepancy movement_id in its `resolves_discrepancy_movement_id` "
        "field so rebuild can close the map."
    )


def test_c16_resolution_row_also_carries_resolving_acceptance_movement_id():
    """Preserve both identities and ledger facts: the resolution row
    carries (a) the ORIGINAL discrepancy id, (b) the resolving acceptance
    movement id, AND (c) its own new ledger movement id. All three
    survive on the append-only ledger row and are therefore replay-safe."""
    assert '"resolved_by_acceptance_movement_id": resolving_acceptance_movement_id' in _SERVICE_SRC, (
        "C16 regression: the resolution ledger row must carry the "
        "resolving acceptance movement_id for audit traceability."
    )
    # The row's own `movement_id` field is `mv_id` (generated with
    # `uuid.uuid4().hex`); this is the resolution identity itself.
    assert '"movement_id": mv_id' in _SERVICE_SRC
