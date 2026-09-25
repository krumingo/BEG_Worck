"""Drift tests against the canonical producer logic.

``tools/control_engine.py`` is the authority: Codex validates and renders with it. This
dashboard carries its own adaptation so that it can check a state against a schema
fetched from the branch, collect every finding instead of the first, and tolerate a
partly malformed document. An adaptation can drift from its original, and a projection
that drifts from the producer becomes a second opinion about protocol truth -- which
CLAUDE.md section 2 rule 12 forbids.

These tests pin the relationship instead of trusting it. They are the main reason this
dashboard is written in Python: the canonical engine can be imported and compared
directly, which a port into another language cannot do.

Three properties are asserted:

1. **Soundness** -- the dashboard never rejects a state the canonical engine accepts.
2. **Completeness** -- the dashboard never accepts a state the canonical engine rejects.
3. **Severity agreement** -- for a state with one injected defect, both assign the same
   severity, so a STALE cannot quietly become an INVALID or vice versa.

One divergence is deliberate and is asserted as such rather than hidden:
``validation_mode: SYNTHETIC_TEST``. The canonical engine accepts it, because the
producer uses it for its own test artefacts. A dashboard that rendered a synthetic
snapshot as a verified live state would be lying about the pipeline, so this dashboard
demotes it to CONFLICT.
"""

from __future__ import annotations

import control_engine
import pytest
from app import board, invariants, schema
from app.status import Status

# Each entry: label, mutation, the status the canonical engine assigns.
SINGLE_DEFECT_CASES = [
    (
        "stage_only_claims_a_percentage",
        lambda s: s["progress"].__setitem__("percent", 55),
        Status.INVALID,
    ),
    (
        "work_id_does_not_compose",
        lambda s: s.__setitem__("current_work_id", "W0-03C/C02/GPT"),
        Status.INVALID,
    ),
    (
        "agent_role_mismatch",
        lambda s: s.__setitem__("current_role", "IMPLEMENTER"),
        Status.INVALID,
    ),
    (
        "pipeline_step_belongs_to_another_agent",
        lambda s: s.__setitem__("pipeline_step", "IMPLEMENTATION"),
        Status.INVALID,
    ),
    (
        "not_active_agent_still_carries_work",
        lambda s: s["agent_states"]["GPT"].__setitem__("work_id", "W0-03C/C02/GPT"),
        Status.INVALID,
    ),
    (
        "requires_krum_without_a_reason",
        lambda s: s.__setitem__("requires_krum_reason", "   "),
        Status.INVALID,
    ),
    (
        # Cleared on the snapshot *and* on the current agent's card. Clearing only the
        # snapshot would inject a second defect (the card would then disagree) and the
        # canonical engine reports that one first, so the case would no longer be
        # testing what it names.
        "blocked_without_waiting_for",
        lambda s: (s.__setitem__("waiting_for", ""),
                   s["agent_states"]["CODEX"].__setitem__("waiting_for", "")),
        Status.INVALID,
    ),
    (
        "history_invents_a_future_cycle",
        lambda s: s["history"][0].__setitem__("mapped_cycle", "C09"),
        Status.INVALID,
    ),
    (
        "duplicate_history_event_id",
        lambda s: s["history"].__setitem__(1, dict(s["history"][1], event_id=s["history"][0]["event_id"])),
        Status.INVALID,
    ),
    (
        "validation_predates_the_source",
        lambda s: s.__setitem__("validated_at", "2026-09-01T00:00:00Z"),
        Status.INVALID,
    ),
    (
        "review_is_not_on_the_current_head",
        lambda s: s["last_review"].__setitem__("reviewed_head_sha", "0" * 40),
        Status.STALE,
    ),
    (
        "handoff_is_not_on_the_current_head",
        lambda s: s["last_handoff"].__setitem__("head_sha", "1" * 40),
        Status.STALE,
    ),
    (
        "review_blob_reference_disagrees",
        lambda s: s["source_refs"].__setitem__("review_blob_sha", "2" * 40),
        Status.STALE,
    ),
    (
        "state_contradicts_the_review_verdict",
        lambda s: (s.__setitem__("state", "PASS"), s["agent_states"]["CODEX"].__setitem__("state", "PASS")),
        Status.CONFLICT,
    ),
    (
        "current_agent_card_disagrees_with_the_snapshot",
        lambda s: s["agent_states"]["CODEX"].__setitem__("waiting_for", "something else entirely"),
        Status.CONFLICT,
    ),
    (
        "producer_published_a_non_valid_status",
        lambda s: s.__setitem__("control_state_status", "STALE"),
        Status.STALE,
    ),
]


def dashboard_status(state: dict, control_schema: dict) -> Status:
    """The dashboard's schema + invariant verdict, which is what the engine covers.

    The blob, PR-head and board checks are excluded here: the canonical engine has no
    equivalent for them, so including them would compare different questions.
    """
    return schema.validate(state, control_schema).merge(invariants.validate(state)).status


def canonical_status(state: dict) -> Status:
    """``Status.VALID`` if the canonical engine accepts the state, else its severity."""
    try:
        control_engine.validate_state(state)
    except control_engine.ControlError as error:
        return Status.parse(error.status)
    return Status.VALID


def test_the_canonical_engine_accepts_the_published_snapshot(published_state):
    """A precondition for everything below: the real snapshot is canonically valid."""
    assert canonical_status(published_state) is Status.VALID


def test_the_dashboard_agrees_the_published_snapshot_is_valid(published_state, control_schema):
    assert dashboard_status(published_state, control_schema) is Status.VALID


@pytest.mark.parametrize("label,change,expected", SINGLE_DEFECT_CASES, ids=[case[0] for case in SINGLE_DEFECT_CASES])
def test_severity_agrees_with_the_canonical_engine(
    label, change, expected, published_state, control_schema, mutate
):
    """One defect at a time, so 'worst of all findings' and 'first raised' must coincide."""
    state = mutate(published_state, change)

    canonical = canonical_status(state)
    assert canonical is expected, (
        f"{label}: the canonical engine assigned {canonical.label}, the test expected {expected.label}. "
        "The canonical engine is the authority -- update the expectation, not the engine."
    )

    observed = dashboard_status(state, control_schema)
    assert observed is expected, f"{label}: dashboard said {observed.label}, canonical engine said {canonical.label}"


@pytest.mark.parametrize("label,change,expected", SINGLE_DEFECT_CASES, ids=[case[0] for case in SINGLE_DEFECT_CASES])
def test_the_dashboard_never_accepts_what_the_canonical_engine_rejects(
    label, change, expected, published_state, control_schema, mutate
):
    """Completeness: anything the producer would refuse must not render as verified."""
    state = mutate(published_state, change)
    assert canonical_status(state) is not Status.VALID
    assert dashboard_status(state, control_schema) is not Status.VALID, (
        f"{label} would render as verified while the canonical engine rejects it"
    )


def test_the_synthetic_test_mode_divergence_is_deliberate(published_state, control_schema, mutate):
    """The one place the dashboard is deliberately stricter than the producer.

    The canonical engine accepts ``SYNTHETIC_TEST`` because the producer generates test
    artefacts with it. A dashboard on a wall must not present such an artefact as live
    verification, so it demotes it to CONFLICT. This asymmetry is intentional; the test
    exists so that it cannot be mistaken later for drift.
    """
    state = mutate(published_state, lambda s: s.__setitem__("validation_mode", "SYNTHETIC_TEST"))

    assert canonical_status(state) is Status.VALID
    verdict = invariants.validate(state)
    assert verdict.status is Status.CONFLICT
    assert "SYNTHETIC_SNAPSHOT" in verdict.codes()


def test_the_board_renderer_is_byte_identical_to_the_canonical_renderer(published_state):
    """The cross-check is only meaningful if it compares against the canonical rendering."""
    assert board.render_board(published_state) == control_engine.render_board(published_state)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.__setitem__("next_agent", "CLAUDE"),
        lambda s: s.__setitem__("dispatch_state", "PENDING"),
        lambda s: s["history"].pop(),
        lambda s: s["source_refs"]["canonical_docs"].pop(),
    ],
    ids=["next_agent", "dispatch_state", "shorter_history", "fewer_canonical_docs"],
)
def test_the_board_renderer_tracks_the_canonical_renderer_under_mutation(
    change, published_state, mutate
):
    """Byte-identity on one input could be luck; hold it across varied inputs."""
    state = mutate(published_state, change)
    assert board.render_board(state) == control_engine.render_board(state)


def test_the_published_board_is_exactly_what_the_published_state_renders_to(
    published_state, published_board
):
    """A real check on the repository, not only on this dashboard's code."""
    verdict = board.cross_check(published_state, published_board)
    assert verdict.status is Status.VALID, verdict.as_dicts()
