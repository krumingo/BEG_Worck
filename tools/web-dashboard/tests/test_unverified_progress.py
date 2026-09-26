"""An unverified round must expose no numeric progress.

Regression suite for the C02 review finding: the verifier correctly marked
``EVIDENCE_COUNT {completed: 3, total: 8, percent: 90}`` INVALID with
``PROGRESS_NOT_DETERMINISTIC`` -- 100*3//8 is 37, not 90 -- but the projection forwarded
``percent: 90`` regardless, and the UI drew "3 of 8 verified milestones · 90%" with a
90%-full bar. A number the verifier has just rejected is not evidence of anything, and
putting it on a wall display is precisely the invented progress Issue #26 forbids.

The rule enforced here: numbers are emitted only when this round verified **and** the
mode is ``EVIDENCE_COUNT``. The stage survives, labelled unverified.
"""

from __future__ import annotations

import pytest
from app.projection import project
from app.refresh import Refresher
from app.status import Status

from conftest import CONTROL_BOARD_PATH

# A percentage that is arithmetically impossible for its own numerator and denominator.
IMPOSSIBLE = {"mode": "EVIDENCE_COUNT", "stage": "REVIEW", "completed": 3, "total": 8, "percent": 90}
# One that is correct: 100 * 3 // 8 == 37.
DETERMINISTIC = {"mode": "EVIDENCE_COUNT", "stage": "REVIEW", "completed": 3, "total": 8, "percent": 37}


def project_round(client, settings):
    refresher = Refresher(client, settings)
    refresher.tick()
    return project(refresher.current())


def make_unverified(status, fake_github, published_state, mutate, progress):
    """Publish ``progress`` and additionally force the round to ``status``."""
    state = mutate(published_state, lambda s: s.__setitem__("progress", dict(progress)))
    if status is Status.STALE:
        fake_github.set_state(state)
        fake_github.set_file("coordination/ACTIVE.md", b"moved on\n")
    elif status is Status.CONFLICT:
        fake_github.set_state(state)
        board = fake_github.files[CONTROL_BOARD_PATH].decode("utf-8")
        fake_github.set_file(
            CONTROL_BOARD_PATH, board.replace("## Evidence", "## Evidence altered").encode("utf-8")
        )
    elif status is Status.INVALID:
        # The impossible percentage is itself the INVALID; a deterministic one needs help.
        if progress is DETERMINISTIC:
            state["wave"] = "not-a-wave"
        fake_github.set_state(state)
    else:
        fake_github.set_state(state)


# ------------------------------------------- the reported case, end to end


def test_an_impossible_percentage_is_rejected_and_not_forwarded(
    fake_github, client, settings, published_state, mutate
):
    fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("progress", dict(IMPOSSIBLE))))
    payload = project_round(client, settings)

    assert payload["control_state_status"] == "INVALID"
    assert payload["verified"] is False
    assert any(finding["code"] == "PROGRESS_NOT_DETERMINISTIC" for finding in payload["findings"])

    progress = payload["header"]["progress"]
    assert progress["percent"] is None
    assert progress["completed"] is None
    assert progress["total"] is None
    assert progress["numbers_withheld"] is True
    assert progress["withheld_reason"]
    # The stage survives, marked unverified.
    assert progress["stage"] == "REVIEW"
    assert progress["stage_verified"] is False
    # And 90 appears nowhere in the payload the browser receives.
    import json

    assert "90" not in json.dumps(progress)


@pytest.mark.parametrize("status", [Status.STALE, Status.CONFLICT, Status.INVALID], ids=lambda s: s.label)
@pytest.mark.parametrize("progress", [IMPOSSIBLE, DETERMINISTIC], ids=["impossible_percent", "deterministic_percent"])
def test_no_numbers_on_any_unverified_status(
    status, progress, fake_github, client, settings, published_state, mutate
):
    """Even an arithmetically correct count is withheld when the round did not verify.

    Correct arithmetic over unverified bytes still proves nothing: the file itself was
    not confirmed this round.
    """
    make_unverified(status, fake_github, published_state, mutate, progress)
    payload = project_round(client, settings)

    # An impossible percentage is itself an INVALID finding, and worst-of precedence
    # means it outranks an injected STALE or CONFLICT. That is correct: the expectation
    # here is the severity the round should actually reach, not the one injected.
    expected = Status.INVALID if progress is IMPOSSIBLE else status
    assert payload["control_state_status"] == expected.label
    assert payload["verified"] is False
    reported = payload["header"]["progress"]
    assert reported["percent"] is None
    assert reported["completed"] is None
    assert reported["total"] is None
    assert reported["numbers_withheld"] is True
    assert reported["stage"] == "REVIEW"


def test_an_aged_round_also_withholds_numbers(fake_github, client, published_state, mutate):
    """Aged is unverified for this purpose: the verdict no longer vouches for now."""
    import dataclasses
    import datetime as dt

    from app.settings import Settings

    fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("progress", dict(DETERMINISTIC))))
    settings = Settings(repository="krumingo/BEG_Worck", branch="codex/claude-queue", stale_after_seconds=30)
    base = dt.datetime(2026, 9, 25, 18, 0, 0, tzinfo=dt.timezone.utc)
    now = {"at": base}
    refresher = Refresher(client, settings, clock=lambda: now["at"])
    refresher.tick()

    fresh = project(refresher.current())
    assert fresh["verified"] is True
    assert fresh["header"]["progress"]["percent"] == 37

    now["at"] = base + dt.timedelta(seconds=600)
    aged = project(refresher.current())
    assert aged["aged"] is True
    assert aged["verified"] is False
    assert aged["header"]["progress"]["percent"] is None
    assert aged["header"]["progress"]["numbers_withheld"] is True


def test_an_offline_round_with_a_cached_verified_snapshot_keeps_its_numbers(
    fake_github, client, settings, published_state, mutate
):
    """A verified reading does not become false because the next round failed.

    Its numbers were verified when read, and its age is shown. Withholding them here
    would destroy information rather than protect anyone.
    """
    from app.github import TransportError

    fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("progress", dict(DETERMINISTIC))))
    refresher = Refresher(client, settings)
    refresher.tick()
    assert project(refresher.current())["header"]["progress"]["percent"] == 37

    fake_github.fail_everything = TransportError("network down")
    refresher.tick()
    offline = project(refresher.current())
    assert offline["link"] == "OFFLINE"
    assert offline["verified"] is True
    assert offline["header"]["progress"]["percent"] == 37


# --------------------------------------------------- the permitted cases


def test_a_verified_evidence_count_still_shows_its_justified_numbers(
    fake_github, client, settings, published_state, mutate
):
    """The rule withholds unverified numbers; it does not suppress proven ones."""
    fake_github.set_state(mutate(published_state, lambda s: s.__setitem__("progress", dict(DETERMINISTIC))))
    payload = project_round(client, settings)

    assert payload["control_state_status"] == "VALID"
    assert payload["verified"] is True
    progress = payload["header"]["progress"]
    assert progress == {
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


def test_stage_only_remains_stage_only_even_when_verified(client, settings, published_state):
    assert published_state["progress"]["mode"] == "STAGE_ONLY"
    payload = project_round(client, settings)
    progress = payload["header"]["progress"]
    assert payload["verified"] is True
    assert progress["stage"] == "REVIEW"
    assert progress["percent"] is None
    assert progress["numbers_withheld"] is True
    assert "STAGE_ONLY" in progress["withheld_reason"]


def test_numbers_smuggled_into_stage_only_are_still_refused(
    fake_github, client, settings, published_state, mutate
):
    fake_github.set_state(
        mutate(published_state, lambda s: s["progress"].update({"completed": 7, "total": 9, "percent": 77}))
    )
    payload = project_round(client, settings)
    assert payload["control_state_status"] == "INVALID"
    assert payload["header"]["progress"]["percent"] is None
    assert payload["header"]["progress"]["completed"] is None


def test_the_unavailable_projection_reports_withheld_numbers_too(client, settings, fake_github):
    from app.github import TransportError

    fake_github.fail_everything = TransportError("no route")
    payload = project_round(client, settings)
    progress = payload["header"]["progress"]
    assert progress["percent"] is None
    assert progress["numbers_withheld"] is True
    assert progress["stage_verified"] is False
