"""The synthetic acceptance mode: safe, off by default, and honest about itself.

Acceptance testing needs STALE, CONFLICT and INVALID on screen, and the only safe way
to get them is to manufacture them. That is a feature with real risk attached -- a
demonstration mistaken for the real queue, or a test hook left enabled in production --
so every one of its safety properties is pinned here.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import threading
import urllib.error
import urllib.request

import pytest
from app.acceptance import (
    DESCRIPTIONS,
    SCENARIOS,
    AcceptanceDisabled,
    AcceptanceError,
    build,
    catalogue,
)
from app.github import GitHubReadOnlyClient
from app.projection import project
from app.refresh import Refresher
from app.server import make_server
from app.settings import Settings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CANONICAL = [
    "coordination/CONTROL_STATE.json",
    "coordination/CONTROL_STATE.schema.json",
    "coordination/CONTROL_BOARD.md",
    "coordination/ACTIVE.md",
    "coordination/REVIEWS/W0-03C.md",
]


def refresher_with(fake_github, **overrides):
    settings = Settings(repository="krumingo/BEG_Worck", branch="codex/claude-queue", **overrides)
    client = GitHubReadOnlyClient(repository=settings.repository, transport=fake_github)
    refresher = Refresher(client, settings)
    refresher.tick()
    return refresher


# ------------------------------------------------------------ off by default


def test_acceptance_mode_is_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv("BEGWORK_ACCEPTANCE_MODE", raising=False)
    assert Settings.from_environment().acceptance_mode is False
    assert Settings().acceptance_mode is False


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("on", True),
                                            ("0", False), ("false", False), ("", False)])
def test_the_flag_is_read_from_the_environment(value, expected, monkeypatch):
    monkeypatch.setenv("BEGWORK_ACCEPTANCE_MODE", value)
    assert Settings.from_environment().acceptance_mode is expected


def test_building_a_scenario_while_disabled_is_refused(fake_github):
    refresher = refresher_with(fake_github, acceptance_mode=False)
    for scenario in SCENARIOS:
        with pytest.raises(AcceptanceDisabled):
            build(scenario, refresher.current())


def test_the_catalogue_reports_the_mode_off(fake_github):
    off = catalogue(Settings())
    assert off["enabled"] is False
    assert off["scenarios"] == []
    on = catalogue(Settings(acceptance_mode=True))
    assert on["enabled"] is True
    assert set(on["scenarios"]) == set(SCENARIOS)


# ------------------------------------------------- it demonstrates what it claims


@pytest.mark.parametrize(
    "scenario,expected_status",
    [("stale", "STALE"), ("conflict", "CONFLICT"), ("invalid", "INVALID")],
)
def test_each_mutation_scenario_produces_its_status_through_the_real_verifier(
    scenario, expected_status, fake_github
):
    """Not a hand-written payload: mutated bytes are re-run through ``verify()``."""
    refresher = refresher_with(fake_github, acceptance_mode=True)
    payload = build(scenario, refresher.current())

    assert payload["control_state_status"] == expected_status
    assert payload["verified"] is False
    assert payload["findings"], "a scenario with no findings has demonstrated nothing"


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("stale", "SOURCE_BLOB_MISMATCH"),
        ("conflict", "BOARD_NOT_GENERATED_FROM_STATE"),
        ("invalid", "STAGE_ONLY_CLAIMS_NUMBERS"),
    ],
)
def test_each_scenario_fires_the_check_it_names_and_not_a_different_one(scenario, code, fake_github):
    refresher = refresher_with(fake_github, acceptance_mode=True)
    payload = build(scenario, refresher.current())
    codes = [finding["code"] for finding in payload["findings"]]
    assert code in codes, f"{scenario} produced {codes}, not {code}"
    # Isolated to one defect, so the reviewer sees which check fired.
    assert len(codes) == 1, f"{scenario} produced extra findings {codes}"


def test_the_offline_scenario_keeps_the_cached_verdict_but_drops_the_link(fake_github):
    """The point of OFFLINE: a previously verified reading, dated, with the feed down."""
    refresher = refresher_with(fake_github, acceptance_mode=True)
    payload = build("offline", refresher.current())
    assert payload["link"] == "OFFLINE"
    assert payload["available"] is True
    assert payload["verified"] is False  # aged, so not presented as current
    assert payload["aged"] is True
    # The snapshot's own protocol verdict is not rewritten by a connectivity loss.
    assert payload["control_state_status"] == "VALID"


def test_the_unavailable_scenario_reports_no_snapshot(fake_github):
    refresher = refresher_with(fake_github, acceptance_mode=True)
    payload = build("unavailable", refresher.current())
    assert payload["available"] is False
    assert payload["verified"] is False
    assert "NOT AVAILABLE" in payload["header"]["state_display"]


def test_an_unknown_scenario_is_refused(fake_github):
    refresher = refresher_with(fake_github, acceptance_mode=True)
    with pytest.raises(AcceptanceError):
        build("everything-is-fine", refresher.current())


def test_a_scenario_cannot_be_built_before_any_snapshot_has_been_read(fake_github):
    """Scenarios mutate real bytes; without any, there is nothing honest to show."""
    from app.github import TransportError

    fake_github.fail_everything = TransportError("no route")
    refresher = refresher_with(fake_github, acceptance_mode=True)
    with pytest.raises(AcceptanceError):
        build("stale", refresher.current())


# --------------------------------------------------- it cannot pass for the truth


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_scenario_is_flagged_synthetic_and_never_verified(scenario, fake_github):
    refresher = refresher_with(fake_github, acceptance_mode=True)
    payload = build(scenario, refresher.current())

    assert payload["synthetic"] is True
    assert payload["acceptance_scenario"] == scenario
    assert payload["acceptance_description"] == DESCRIPTIONS[scenario]
    assert "SYNTHETIC ACCEPTANCE DATA" in payload["acceptance_notice"]
    assert payload["verified"] is False, "synthetic data must never read as verified"


def test_no_scenario_can_report_valid_and_verified(fake_github):
    """The structural guarantee, not merely the current behaviour."""
    refresher = refresher_with(fake_github, acceptance_mode=True)
    for scenario in SCENARIOS:
        payload = build(scenario, refresher.current())
        assert not (payload["verified"] and payload["control_state_status"] == "VALID")


def test_the_guard_refuses_a_scenario_that_came_out_verified(fake_github, monkeypatch):
    """If a mutation ever stops being caught, acceptance mode must fail, not reassure.

    Simulated by neutering the mutation: the scenario then verifies cleanly, which is
    exactly the silent-success case the guard exists to catch.
    """
    import app.acceptance as acceptance

    monkeypatch.setattr(acceptance, "_mutate", lambda scenario, snapshot: snapshot)
    refresher = refresher_with(fake_github, acceptance_mode=True)
    with pytest.raises(AcceptanceError, match="no longer being caught|verified payload"):
        acceptance.build("stale", refresher.current())


# ------------------------------------------------------------- it writes nothing


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_no_github_request_is_issued_by_a_scenario(scenario, fake_github):
    refresher = refresher_with(fake_github, acceptance_mode=True)
    before = len(fake_github.calls)
    build(scenario, refresher.current())
    assert len(fake_github.calls) == before, "acceptance mode contacted GitHub"


def test_no_canonical_queue_file_is_touched(fake_github):
    """The mutation is in memory. Nothing on disk may change."""
    before = {
        path: hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest() for path in CANONICAL
    }
    refresher = refresher_with(fake_github, acceptance_mode=True)
    for scenario in SCENARIOS:
        build(scenario, refresher.current())
    after = {
        path: hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest() for path in CANONICAL
    }
    assert before == after


def test_the_live_state_is_not_modified_by_building_a_scenario(fake_github):
    """Scenarios build a copy; the dashboard's own reading must survive intact."""
    refresher = refresher_with(fake_github, acceptance_mode=True)
    live_before = project(refresher.current())

    for scenario in SCENARIOS:
        build(scenario, refresher.current())

    live_after = project(refresher.current())
    assert live_after["control_state_status"] == "VALID"
    assert live_after["verified"] is True
    assert "synthetic" not in live_after
    assert live_after["header"] == live_before["header"]


# ------------------------------------------------------------- over HTTP


@pytest.fixture
def served_with(fake_github):
    servers = []

    def start(**overrides):
        settings = Settings(
            repository="krumingo/BEG_Worck", branch="codex/claude-queue",
            host="127.0.0.1", port=0, **overrides,
        )
        client = GitHubReadOnlyClient(repository=settings.repository, transport=fake_github)
        refresher = Refresher(client, settings)
        refresher.tick()
        server = make_server(refresher, settings)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}"

    try:
        yield start
    finally:
        for server, thread in servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as reply:
        return reply.status, json.loads(reply.read())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_the_endpoint_404s_while_the_mode_is_disabled(scenario, served_with):
    """A disabled deployment answers exactly like an unknown path, revealing nothing."""
    base = served_with(acceptance_mode=False)
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(base, f"/api/acceptance/{scenario}")
    assert caught.value.code == 404


def test_the_catalogue_endpoint_says_the_mode_is_off(served_with):
    base = served_with(acceptance_mode=False)
    status, payload = get(base, "/api/acceptance")
    assert status == 200
    assert payload["enabled"] is False
    assert payload["scenarios"] == []


def test_healthz_discloses_whether_acceptance_mode_is_on(served_with):
    """An operator must be able to tell an acceptance box from a production one."""
    assert get(served_with(acceptance_mode=False), "/healthz")[1]["acceptance_mode"] is False
    assert get(served_with(acceptance_mode=True), "/healthz")[1]["acceptance_mode"] is True


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_the_endpoint_serves_each_scenario_when_enabled(scenario, served_with):
    base = served_with(acceptance_mode=True)
    status, payload = get(base, f"/api/acceptance/{scenario}")
    assert status == 200
    assert payload["synthetic"] is True
    assert payload["verified"] is False


def test_the_live_endpoint_is_never_synthetic_even_with_the_mode_on(served_with):
    base = served_with(acceptance_mode=True)
    _, payload = get(base, "/api/state")
    assert "synthetic" not in payload
    assert payload["verified"] is True
