"""Cadence, conditional reads, bounded backoff and the offline path."""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
from app.github import TransportError
from app.projection import project
from app.refresh import BackoffPolicy, Refresher
from app.settings import MAX_REFRESH_SECONDS, MIN_REFRESH_SECONDS, Settings
from app.status import Link, Status

from conftest import ACTIVE_PATH


# ------------------------------------------------------------------- cadence


@pytest.mark.parametrize(
    "requested,expected",
    [("1", MIN_REFRESH_SECONDS), ("10", 10), ("15", 15), ("30", 30), ("600", MAX_REFRESH_SECONDS), ("nonsense", 15), ("", 15)],
)
def test_the_refresh_interval_is_clamped_into_the_supported_band(requested, expected, monkeypatch):
    """Issue #26 asks for 10-30 s. A value outside it is clamped, not obeyed or rejected."""
    monkeypatch.setenv("BEGWORK_REFRESH_SECONDS", requested)
    assert Settings.from_environment().refresh_seconds == expected


def test_a_healthy_dashboard_waits_the_configured_interval(client, settings):
    refresher = Refresher(client, settings)
    refresher.tick()
    assert refresher.delay_seconds == settings.refresh_seconds


# --------------------------------------------------------- conditional requests


def test_the_second_round_sends_if_none_match_and_reuses_the_unchanged_bytes(
    client, settings, fake_github, published_state
):
    """A 304 must reuse the cached bytes, and the blob check must still pass on them."""
    from app.verify import read_snapshot, verify

    first = verify(read_snapshot(client, settings), settings)
    assert first.status is Status.VALID
    assert fake_github.served_304 == 0

    second = verify(read_snapshot(client, settings), settings)

    assert fake_github.served_304 > 0, "no conditional request was answered 304"
    assert second.status is Status.VALID, second.verdict.as_dicts()
    # The cited blob still verifies from the reused bytes, not from a blank body.
    assert second.snapshot.active.blob_sha == published_state["source_refs"]["active_blob_sha"]
    assert second.snapshot.active.from_cache is True


def test_a_changed_file_invalidates_its_etag_and_is_read_afresh(client, settings, fake_github):
    from app.verify import read_snapshot, verify

    assert verify(read_snapshot(client, settings), settings).status is Status.VALID
    fake_github.set_file(ACTIVE_PATH, b"changed on the branch\n")
    second = verify(read_snapshot(client, settings), settings)
    assert second.snapshot.active.from_cache is False
    assert second.status is Status.STALE


# ------------------------------------------------------------------- backoff


def test_backoff_escalates_then_caps():
    policy = BackoffPolicy(10, 120)
    assert [policy.next(n) for n in range(1, 8)] == [10, 20, 40, 80, 120, 120, 120]


def test_no_backoff_is_applied_before_a_failure():
    assert BackoffPolicy(10, 120).next(0) == 0.0


def test_a_retry_after_hint_is_honoured_but_capped():
    policy = BackoffPolicy(10, 120)
    assert policy.next(1, retry_after=45) == 45      # longer than the step: honoured
    assert policy.next(1, retry_after=3600) == 120   # absurdly long: capped
    assert policy.next(4, retry_after=5) == 80       # shorter than the step: ignored


def test_backoff_rejects_an_incoherent_configuration():
    with pytest.raises(ValueError):
        BackoffPolicy(0, 100)
    with pytest.raises(ValueError):
        BackoffPolicy(100, 10)


def test_a_rate_limited_read_is_recognised_as_such():
    assert TransportError("x", status=403).is_rate_limited
    assert TransportError("x", status=429).is_rate_limited
    assert not TransportError("x", status=500).is_rate_limited


def test_consecutive_failures_escalate_the_delay(client, settings, fake_github):
    refresher = Refresher(client, settings)
    refresher.tick()
    assert refresher.delay_seconds == settings.refresh_seconds

    fake_github.fail_everything = TransportError("network down")
    observed = []
    for _ in range(5):
        refresher.tick()
        observed.append(refresher.delay_seconds)
    assert observed == [10, 20, 40, 80, 120]


def test_recovery_clears_the_backoff_immediately(client, settings, fake_github):
    refresher = Refresher(client, settings)
    fake_github.fail_everything = TransportError("network down")
    refresher.tick()
    refresher.tick()
    assert refresher.delay_seconds == 20

    fake_github.fail_everything = None
    state = refresher.tick()
    assert state.link is Link.ONLINE
    assert state.consecutive_failures == 0
    assert refresher.delay_seconds == settings.refresh_seconds


# ------------------------------------------------------------------- offline


def test_the_first_round_failing_leaves_no_snapshot_and_says_so(client, settings, fake_github):
    fake_github.fail_everything = TransportError("DNS failure")
    refresher = Refresher(client, settings)
    state = refresher.tick()

    assert state.link is Link.OFFLINE
    assert state.has_data is False
    payload = project(state)
    assert payload["available"] is False
    assert payload["verified"] is False
    assert payload["header"]["state_display"] == "CONTROL STATE NOT AVAILABLE"
    assert "CONTROL STATE NOT AVAILABLE" in payload["gate"]
    assert payload["task"] is None


def test_a_cached_snapshot_survives_a_failed_round_and_is_marked_offline(client, settings, fake_github):
    """The point of the cache: keep showing the last thing known to be true, dated."""
    refresher = Refresher(client, settings)
    refresher.tick()
    good = project(refresher.current())
    assert good["link"] == Link.ONLINE.value
    assert good["verified"] is True

    fake_github.fail_everything = TransportError("network down")
    refresher.tick()
    offline = project(refresher.current())

    assert offline["link"] == Link.OFFLINE.value
    assert offline["available"] is True
    assert offline["header"]["task_id"] == good["header"]["task_id"]
    assert offline["header"]["state"] == good["header"]["state"]
    assert offline["last_error"] and "network down" in offline["last_error"]
    assert offline["consecutive_failures"] == 1
    # The cached verdict is not restated as fresh verification: its age is on screen.
    assert offline["last_verified_at"] == good["last_verified_at"]


def test_offline_and_stale_are_reported_as_separate_facts(client, settings, fake_github):
    """A dropped link is not a protocol problem, and must not be rendered as one."""
    refresher = Refresher(client, settings)
    refresher.tick()
    fake_github.fail_everything = TransportError("network down")
    refresher.tick()
    payload = project(refresher.current())

    assert payload["link"] == "OFFLINE"
    # The snapshot itself was sound when it was read; that verdict is not rewritten.
    assert payload["control_state_status"] == "VALID"
    assert payload["aged"] is False


def test_an_unexpected_exception_does_not_kill_the_loop(client, settings, fake_github):
    def explode(method, url, headers, timeout):
        raise RuntimeError("something nobody predicted")

    fake_github.request = explode
    refresher = Refresher(client, settings)
    state = refresher.tick()
    assert state.link is Link.OFFLINE
    assert "RuntimeError" in (state.last_error or "")
    assert refresher.delay_seconds == 10


def test_the_age_of_the_last_successful_read_is_what_is_reported(client, fake_github):
    """Age is wall-clock age of the read, not distance from ``validated_at``.

    A task that is legitimately blocked for days has an old ``validated_at`` and is not
    thereby a stale reading, so the two must not be conflated.
    """
    settings = Settings(repository="krumingo/BEG_Worck", branch="codex/claude-queue", stale_after_seconds=60)
    base = dt.datetime(2026, 9, 25, 18, 0, 0, tzinfo=dt.timezone.utc)
    # An explicitly advanced clock, rather than a list consumed per call: how many times
    # the refresher reads the clock is an implementation detail a test should not encode.
    now = {"at": base}

    refresher = Refresher(client, settings, clock=lambda: now["at"])
    refresher.tick()

    now["at"] = base + dt.timedelta(seconds=10)
    fresh = project(refresher.current())
    assert fresh["aged"] is False
    assert fresh["age_seconds"] == pytest.approx(10, abs=0.5)
    assert fresh["verified"] is True

    now["at"] = base + dt.timedelta(seconds=200)
    aged = project(refresher.current())
    assert aged["aged"] is True
    assert aged["age_seconds"] == pytest.approx(200, abs=0.5)
    assert aged["verified"] is False, "an aged snapshot must not be presented as verified"
    # Still VALID as a verdict: it was sound when read. Age is the separate fact.
    assert aged["control_state_status"] == "VALID"


def test_the_refresh_loop_thread_starts_and_stops_cleanly(client, settings):
    """The background loop must be a daemon and must join on stop."""
    import dataclasses as dc

    from app.refresh import RefreshLoop

    quick = dc.replace(settings, refresh_seconds=MIN_REFRESH_SECONDS)
    refresher = Refresher(client, quick)
    loop = RefreshLoop(refresher)
    loop.start()
    try:
        assert loop._thread is not None  # noqa: SLF001
        assert loop._thread.daemon is True  # noqa: SLF001
    finally:
        loop.stop(timeout=2)
    assert loop._thread is None  # noqa: SLF001
    assert refresher.current().rounds >= 1
