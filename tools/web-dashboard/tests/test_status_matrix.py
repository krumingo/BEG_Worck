"""The four control-state statuses, and the rules that must never bend.

Issue #26 requires VALID / STALE / CONFLICT / INVALID to be distinguishable, requires
that unverified data is never promoted to PASS, and requires that no percentage is
invented. Those are the tests here, driven through a whole round so they exercise the
same path production takes.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
from app.refresh import Refresher
from app.projection import project
from app.status import Link, Status
from app.verify import read_snapshot, verify

from conftest import CONTROL_BOARD_PATH


def round_verdict(client, settings):
    return verify(read_snapshot(client, settings), settings)


def project_round(client, settings):
    refresher = Refresher(client, settings)
    refresher.tick()
    return project(refresher.current())


# ------------------------------------------------------------------ the matrix


def test_valid_is_reachable_and_is_the_real_published_snapshot(client, settings):
    assert round_verdict(client, settings).status is Status.VALID


def test_stale_when_a_cited_source_has_moved(fake_github, client, settings):
    fake_github.set_file("coordination/ACTIVE.md", b"moved on\n")
    assert round_verdict(client, settings).status is Status.STALE


def test_conflict_when_the_board_is_not_generated_from_the_state(fake_github, client, settings):
    published = fake_github.files[CONTROL_BOARD_PATH].decode("utf-8")
    fake_github.set_file(CONTROL_BOARD_PATH, published.replace("BLOCKED", "PASS").encode("utf-8"))
    result = round_verdict(client, settings)
    assert result.status is Status.CONFLICT
    assert "BOARD_NOT_GENERATED_FROM_STATE" in result.verdict.codes()


def test_invalid_when_the_state_breaks_its_own_schema(fake_github, client, settings, published_state, mutate):
    fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("protocol_version", 2)))
    assert round_verdict(client, settings).status is Status.INVALID


@pytest.mark.parametrize(
    "expected",
    [Status.VALID, Status.STALE, Status.CONFLICT, Status.INVALID],
    ids=lambda value: value.label,
)
def test_each_status_reaches_the_projection_verbatim(expected, fake_github, client, settings, published_state, mutate):
    """A status must survive the trip to the browser payload unchanged."""
    if expected is Status.STALE:
        fake_github.set_file("coordination/ACTIVE.md", b"moved on\n")
    elif expected is Status.CONFLICT:
        board = fake_github.files[CONTROL_BOARD_PATH].decode("utf-8")
        fake_github.set_file(CONTROL_BOARD_PATH, board.replace("## Evidence", "## EvidenceX").encode("utf-8"))
    elif expected is Status.INVALID:
        fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("wave", "nonsense")))

    payload = project_round(client, settings)
    assert payload["control_state_status"] == expected.label
    assert payload["verified"] is (expected is Status.VALID)


def test_the_worst_finding_wins_when_several_coexist(fake_github, client, settings, published_state, mutate):
    """Precedence INVALID > CONFLICT > STALE > VALID, so nothing is masked by a milder issue."""
    fake_github.set_file("coordination/ACTIVE.md", b"moved on\n")            # STALE
    fake_github.pull_requests[published_state["pr_number"]]["draft"] = False  # CONFLICT
    fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("wave", "nope")))  # INVALID

    result = round_verdict(client, settings)
    codes = result.verdict.codes()
    assert result.status is Status.INVALID
    # Every finding is kept, not just the decisive one.
    assert "SOURCE_BLOB_MISMATCH" in codes
    assert "PR_DRAFT_MISMATCH" in codes


# ------------------------------------- never promote an unverified state to PASS


def test_a_stored_pass_that_fails_verification_is_never_shown_as_a_pass(
    fake_github, client, settings, published_state, mutate
):
    """The load-bearing safety property of the whole dashboard.

    A snapshot claiming PASS whose evidence does not hold up must not read as a pass
    anywhere on the screen: not in the header, not on the pipeline.
    """
    forged = mutate(
        published_state,
        lambda s: (
            s.__setitem__("state", "PASS"),
            s["agent_states"]["CODEX"].__setitem__("state", "PASS"),
            s.__setitem__("control_state_status", "VALID"),
        ),
    )
    fake_github.set_state(forged)

    payload = project_round(client, settings)

    assert payload["verified"] is False
    assert payload["control_state_status"] != "VALID"
    assert payload["header"]["state_display"] == "PASS (UNVERIFIED)"
    assert payload["header"]["state_verified"] is False
    active = [step for step in payload["pipeline"] if step["active"]]
    assert active and active[0]["badge"] == "PASS (UNVERIFIED)"


def test_a_producer_claim_of_valid_cannot_by_itself_produce_valid(
    fake_github, client, settings, published_state, mutate
):
    """``control_state_status: VALID`` is a claim. The bytes decide."""
    fake_github.set_file("coordination/ACTIVE.md", b"the cited blob is not this\n")
    assert published_state["control_state_status"] == "VALID"
    assert round_verdict(client, settings).status is not Status.VALID


def test_a_synthetic_snapshot_is_never_presented_as_live_verification(
    fake_github, client, settings, published_state, mutate
):
    fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("validation_mode", "SYNTHETIC_TEST")))
    payload = project_round(client, settings)
    assert payload["verified"] is False
    assert payload["control_state_status"] == "CONFLICT"
    assert any(finding["code"] == "SYNTHETIC_SNAPSHOT" for finding in payload["findings"])


# ------------------------------------------------- no invented progress numbers


def test_stage_only_progress_shows_a_stage_and_no_numbers(client, settings, published_state):
    assert published_state["progress"]["mode"] == "STAGE_ONLY"
    payload = project_round(client, settings)
    progress = payload["header"]["progress"]
    assert progress["mode"] == "STAGE_ONLY"
    assert progress["stage"] == "REVIEW"
    assert progress["percent"] is None
    assert progress["completed"] is None
    assert progress["total"] is None


def test_numbers_smuggled_into_a_stage_only_progress_are_refused_and_not_echoed(
    fake_github, client, settings, published_state, mutate
):
    """Two defences: the invariant reports it, and the projection still shows no number."""
    fake_github.set_state(
        mutate(
            published_state,
            lambda s: s["progress"].update({"completed": 7, "total": 9, "percent": 77}),
        )
    )
    payload = project_round(client, settings)
    assert payload["control_state_status"] == "INVALID"
    assert any(finding["code"] == "STAGE_ONLY_CLAIMS_NUMBERS" for finding in payload["findings"])
    assert payload["header"]["progress"]["percent"] is None


def test_a_deterministic_evidence_count_progress_is_passed_through(
    fake_github, client, settings, published_state, mutate
):
    """When the protocol does prove a proportion, showing it is correct."""
    fake_github.set_state(
        mutate(
            published_state,
            lambda s: s.__setitem__(
                "progress",
                {"mode": "EVIDENCE_COUNT", "stage": "REVIEW", "completed": 3, "total": 8, "percent": 37},
            ),
        )
    )
    payload = project_round(client, settings)
    assert payload["control_state_status"] == "VALID"
    assert payload["header"]["progress"] == {
        "mode": "EVIDENCE_COUNT",
        "stage": "REVIEW",
        "stage_verified": True,
        "completed": 3,
        "total": 8,
        "percent": 37,
        "numbers_withheld": False,
        "withheld_reason": None,
        "workflow_position": {"index": 4, "total": 6, "label": "REVIEW"},
    }


def test_a_non_deterministic_percentage_is_invalid(fake_github, client, settings, published_state, mutate):
    fake_github.set_state(
        mutate(
            published_state,
            lambda s: s.__setitem__(
                "progress",
                {"mode": "EVIDENCE_COUNT", "stage": "REVIEW", "completed": 3, "total": 8, "percent": 90},
            ),
        )
    )
    result = round_verdict(client, settings)
    assert result.status is Status.INVALID
    assert "PROGRESS_NOT_DETERMINISTIC" in result.verdict.codes()


# ----------------------------------------------------------- aged vs offline


def test_an_aged_snapshot_is_not_reported_as_verified(client, settings, fake_github):
    """Verification is about now. A round from an hour ago does not vouch for now."""
    tight = dataclasses.replace(settings, stale_after_seconds=30)
    moments = iter(
        [
            dt.datetime(2026, 9, 25, 12, 0, 0, tzinfo=dt.timezone.utc),  # the read
            dt.datetime(2026, 9, 25, 12, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 9, 25, 13, 0, 0, tzinfo=dt.timezone.utc),  # an hour later
        ]
    )
    last = {"value": dt.datetime(2026, 9, 25, 13, 0, 0, tzinfo=dt.timezone.utc)}

    def clock():
        try:
            last["value"] = next(moments)
        except StopIteration:
            pass
        return last["value"]

    refresher = Refresher(client, tight, clock=clock)
    refresher.tick()
    payload = project(refresher.current())

    assert payload["aged"] is True
    assert payload["verified"] is False
    # The underlying verdict is still VALID -- the snapshot was sound when it was read.
    # Age is reported separately rather than being recast as a protocol problem.
    assert payload["control_state_status"] == "VALID"
    assert payload["link"] == Link.ONLINE.value
