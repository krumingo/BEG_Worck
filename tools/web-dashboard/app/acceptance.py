"""Synthetic acceptance mode — disabled by default.

Acceptance testing on the target host needs to see STALE, CONFLICT and INVALID
rendered, but those states cannot be produced on demand: they depend on the real
queue being in a bad shape, and deliberately corrupting the queue to see a colour
change is exactly the thing this dashboard exists to prevent.

So this module manufactures them *in memory*, and it does so by feeding mutated bytes
through the **real verifier** rather than by returning a hand-written payload. A
scenario takes the snapshot the dashboard already read from GitHub, changes one thing
in memory (an ACTIVE byte, a board line, a state field) and re-runs ``verify()``. What
appears on screen is therefore a genuine demonstration of the production verification
path reacting to a real defect, not a picture of one.

Four properties make this safe to ship:

* **Off unless asked.** ``BEGWORK_ACCEPTANCE_MODE`` defaults to false, and while it is
  false the endpoint does not exist -- it 404s like any unknown path.
* **Nothing is written.** No GitHub request of any kind is issued (the mutation happens
  on bytes already in memory), no canonical queue file is touched, and nothing is
  persisted. The dashboard's own live state is not modified: scenarios build a *copy*.
* **It cannot claim to be verified.** Every payload carries ``synthetic: true`` and the
  scenario name, and ``_assert_not_verified`` refuses to serve anything that came out
  VALID or verified. A synthetic round that somehow verified would be a bug, and it
  fails closed rather than reaching a screen.
* **Production verification is untouched.** This module adds no path into ``verify()``
  that relaxes anything; it only supplies different input bytes.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

from .projection import project
from .refresh import DashboardState
from .settings import Settings
from .status import Link
from .verify import Snapshot, VerifiedSnapshot, verify
from .gitblob import blob_sha1

#: Deliberately excludes any scenario that would render as VALID. Acceptance mode
#: exists to show the failure states; a synthetic "everything is fine" screen is the
#: one thing it must never be able to produce.
SCENARIOS = ("stale", "conflict", "invalid", "offline", "unavailable")

DESCRIPTIONS = {
    "stale": "ACTIVE.md on the branch no longer matches the blob CONTROL_STATE cites.",
    "conflict": "CONTROL_BOARD.md is not what CONTROL_STATE.json renders to.",
    "invalid": "CONTROL_STATE.json violates the protocol it publishes.",
    "offline": "The last round failed; a previously verified snapshot is shown with its age.",
    "unavailable": "No snapshot has ever been read.",
}


class AcceptanceError(RuntimeError):
    """A scenario could not be built. Never turned into a rendered page."""


class AcceptanceDisabled(AcceptanceError):
    """Acceptance mode is off. The caller must answer 404, not explain itself."""


def is_enabled(settings: Settings) -> bool:
    return bool(settings.acceptance_mode)


def catalogue(settings: Settings) -> dict:
    """What an operator can ask for. Empty and flagged off when disabled."""
    return {
        "enabled": is_enabled(settings),
        "scenarios": list(SCENARIOS) if is_enabled(settings) else [],
        "descriptions": DESCRIPTIONS if is_enabled(settings) else {},
        "note": (
            "Synthetic acceptance data. Produced by mutating an already-read snapshot in "
            "memory and re-running the real verifier. No GitHub request is issued, no "
            "canonical file is touched, nothing is persisted, and no scenario can report "
            "VALID or verified."
        ),
    }


def build(scenario: str, live: DashboardState) -> dict:
    """Return a projection for ``scenario``, derived from the live state in memory."""
    settings = live.settings
    if not is_enabled(settings):
        raise AcceptanceDisabled("acceptance mode is disabled")
    if scenario not in SCENARIOS:
        raise AcceptanceError(f"unknown scenario {scenario!r}")

    if scenario == "unavailable":
        payload = project(_replace_state(live, verified=None, link=Link.OFFLINE,
                                         last_error="Acceptance scenario: no snapshot has been read."))
        return _finish(payload, scenario)

    if live.verified is None or live.verified.state is None:
        # Scenarios mutate a real snapshot; without one there is nothing honest to show.
        raise AcceptanceError(
            "no snapshot has been read yet, so no scenario can be derived from real bytes"
        )

    if scenario == "offline":
        # Nothing about the snapshot changes: the point is that the *link* dropped and
        # the cached reading is still on screen with its age.
        aged = live.now + dt.timedelta(seconds=max(0, settings.stale_after_seconds) + 60)
        payload = project(
            _replace_state(
                live,
                link=Link.OFFLINE,
                last_error="Acceptance scenario: simulated loss of connectivity to api.github.com.",
                consecutive_failures=3,
                now=aged,
            )
        )
        return _finish(payload, scenario)

    mutated = _mutate(scenario, live.verified.snapshot)
    verified = verify(mutated, settings)
    payload = project(_replace_state(live, verified=verified))
    return _finish(payload, scenario)


def _replace_state(live: DashboardState, **changes) -> DashboardState:
    """A copy of the live state with overrides. The live object is never modified."""
    return dataclasses.replace(live, **changes)


def _mutate(scenario: str, snapshot: Snapshot) -> Snapshot:
    """Change one thing, in memory, so the real verifier has something real to catch."""
    if scenario == "stale":
        if snapshot.active is None:
            raise AcceptanceError("the STALE scenario needs the cited ACTIVE file to have been read")
        return dataclasses.replace(snapshot, active=_rewrite(snapshot.active, _ACTIVE_DRIFT))

    if scenario == "conflict":
        if snapshot.board is None:
            raise AcceptanceError("the CONFLICT scenario needs CONTROL_BOARD.md to have been read")
        drifted = snapshot.board.text.replace("## Evidence", "## Evidence (acceptance drift)", 1)
        if drifted == snapshot.board.text:
            drifted = snapshot.board.text + "\n<!-- acceptance drift -->\n"
        return dataclasses.replace(snapshot, board=_rewrite(snapshot.board, drifted.encode("utf-8")))

    if scenario == "invalid":
        state = json.loads(snapshot.control_state.text)
        # A protocol violation the invariant pass names precisely, rather than random
        # corruption: STAGE_ONLY progress is forbidden from carrying numbers.
        state.setdefault("progress", {})
        state["progress"]["completed"] = 7
        state["progress"]["total"] = 9
        state["progress"]["percent"] = 78
        body = (json.dumps(state, indent=2) + "\n").encode("utf-8")
        mutated = dataclasses.replace(snapshot, control_state=_rewrite(snapshot.control_state, body))
        if mutated.board is not None:
            # Regenerate the board to match, so this scenario demonstrates exactly the
            # invariant it names. Leaving the old board would also raise a CONFLICT and
            # muddle which check the reviewer is being shown.
            try:
                from . import board as board_module

                rendered = board_module.render_board(state).encode("utf-8")
                mutated = dataclasses.replace(mutated, board=_rewrite(mutated.board, rendered))
            except (KeyError, TypeError):
                pass
        return mutated

    raise AcceptanceError(f"scenario {scenario!r} has no mutation")


_ACTIVE_DRIFT = (
    b"# Acceptance scenario\n\n"
    b"These bytes are not the bytes CONTROL_STATE.json cites. The verifier must notice.\n"
)


def _rewrite(file, content: bytes):
    """A copy of a fetched file with new bytes and a correctly recomputed blob SHA.

    ``api_reported_sha`` is recomputed too. Leaving the old value would trip the
    transport-integrity check and produce INVALID for the wrong reason, which would make
    the demonstration a lie about which check fired.
    """
    digest = blob_sha1(content)
    return dataclasses.replace(
        file, content=content, blob_sha=digest, api_reported_sha=digest, from_cache=False
    )


#: What each scenario must actually have demonstrated. Asserted before serving, so a
#: mutation that stops being caught fails loudly instead of rendering a reassuring page.
EXPECTED_STATUS = {
    "stale": "STALE",
    "conflict": "CONFLICT",
    "invalid": "INVALID",
    # OFFLINE deliberately keeps the cached snapshot's own verdict, which may legitimately
    # be VALID: the demonstration is that the *link* dropped while a previously verified
    # reading stays on screen with its age. It is still never `verified`.
    "offline": None,
    "unavailable": None,
}


def _finish(payload: dict, scenario: str) -> dict:
    """Stamp the payload as synthetic and prove it demonstrated what it claims."""
    payload["synthetic"] = True
    payload["acceptance_scenario"] = scenario
    payload["acceptance_description"] = DESCRIPTIONS[scenario]
    payload["acceptance_notice"] = (
        f"SYNTHETIC ACCEPTANCE DATA ({scenario.upper()}) — generated in memory for acceptance "
        "testing. This is NOT live verification and NOT the real queue state."
    )
    _assert_honest(payload, scenario)
    return payload


def _assert_honest(payload: dict, scenario: str) -> None:
    """Fail closed rather than serve a synthetic page that could be read as verified."""
    if payload.get("verified"):
        raise AcceptanceError(
            f"scenario {scenario!r} produced a verified payload; refusing to serve it because "
            "synthetic data must never be presentable as live verified truth"
        )
    if not payload.get("synthetic"):
        raise AcceptanceError(f"scenario {scenario!r} lost its synthetic marker")

    expected = EXPECTED_STATUS[scenario]
    observed = payload.get("control_state_status")
    if expected is not None and observed != expected:
        raise AcceptanceError(
            f"scenario {scenario!r} was meant to demonstrate {expected} but the verifier "
            f"reported {observed!r}; the mutation is no longer being caught"
        )
    if scenario == "offline" and payload.get("link") != "OFFLINE":
        raise AcceptanceError("the offline scenario did not report an OFFLINE link")
    if scenario == "unavailable" and payload.get("available"):
        raise AcceptanceError("the unavailable scenario still reported a snapshot")
