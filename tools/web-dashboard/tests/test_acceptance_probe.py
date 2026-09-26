"""The acceptance probe must not mistake repeated samples for repeated refresh cycles.

Regression suite for the C02 re-review finding. ``remote_rounds()`` computed whether
``/healthz.rounds`` had advanced and then used that only for a printed note: a sample
counted as successful whenever ``link=ONLINE`` and ``consecutive_failures=0``. Five
polls of one frozen round therefore printed ``rounds observed healthy: 5/5`` and exited
0 — so a target whose refresh loop had stopped entirely would pass the very check meant
to prove it was refreshing.

The corrected probe counts a cycle only when the round counter is **strictly greater**
than at the previously counted cycle, and fails when no new round arrives inside a
bounded window. A second claim is kept separate: that the target authenticates, and
whether its token's scope was ever established.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import pathlib
import socketserver
import sys
import threading

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "acceptance_probe.py"


def _load_probe():
    """Import the probe script as a module.

    It is a CLI script rather than a package member, so it is loaded by path. The module
    must be registered in ``sys.modules`` *before* execution: ``@dataclass(slots=True)``
    rebuilds the class and looks its module up there, and fails on a module that is not
    registered.
    """
    spec = importlib.util.spec_from_file_location("acceptance_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


class HealthStub:
    """A stand-in for a running dashboard, with a scriptable round counter."""

    def __init__(self, rounds_sequence, token_configured=False, link="ONLINE", failures=0,
                 state_available=True):
        self.rounds = list(rounds_sequence)
        self.token_configured = token_configured
        self.link = link
        self.failures = failures
        self.state_available = state_available
        self.index = 0
        self.health_hits = 0
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path.startswith("/api/state"):
                    if not stub.state_available:
                        self.send_error(500)
                        return
                    payload = {
                        "config": {
                            "token_configured": stub.token_configured,
                            "repository": "krumingo/BEG_Worck",
                            "branch": "codex/claude-queue",
                            "acceptance_mode": False,
                        },
                        "refresh_seconds": 15,
                    }
                else:
                    stub.health_hits += 1
                    value = stub.rounds[min(stub.index, len(stub.rounds) - 1)]
                    stub.index += 1
                    payload = {
                        "status": "ok",
                        "link": stub.link,
                        "control_state_status": "VALID",
                        "consecutive_failures": stub.failures,
                        "age_seconds": 3.0,
                        "rounds": value,
                        "acceptance_mode": False,
                    }
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # noqa: A002
                pass

        self._server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self._server.allow_reuse_address = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


class Clock:
    """A monotonic clock the test advances, so bounded waits cost no wall-clock time."""

    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def run(stub, count=5, interval=1.0, max_wait=10.0, **kwargs):
    clock = Clock()
    lines: list[str] = []
    code = probe.remote_rounds(
        stub.base_url, count, interval, max_wait=max_wait,
        printer=lines.append, sleep=clock.sleep, monotonic=clock.monotonic, **kwargs,
    )
    return code, "\n".join(lines)


# ------------------------------------ the reported defect: repeated identical rounds


def test_five_identical_rounds_fail_instead_of_counting_as_five_cycles():
    """The exact reproduction from the review: five healthy samples of ``rounds=7``."""
    with HealthStub([7] * 200, token_configured=True) as stub:
        code, output = run(stub)

    assert code == 1, "a frozen round counter must fail, not report five cycles"
    assert "cycles counted (strictly increasing rounds): 0/5" in output
    assert "REFRESH RESULT: FAIL" in output
    assert "refresh loop is not advancing" in output
    assert "REFRESH RESULT: PASS" not in output
    # And it must not claim anything about authentication off the back of a failed run.
    assert "AUTHENTICATED REFRESH PASS : YES" not in output


def test_a_counter_that_advances_once_then_freezes_still_fails():
    """Partial progress is not five cycles."""
    with HealthStub([7, 8] + [8] * 200, token_configured=True) as stub:
        code, output = run(stub)
    assert code == 1
    assert "cycles counted (strictly increasing rounds): 1/5" in output


def test_a_counter_that_goes_backwards_does_not_count():
    """A restarted target resets its counter; that is not a new cycle."""
    with HealthStub([9, 3, 3, 3] + [3] * 200, token_configured=True) as stub:
        code, output = run(stub)
    assert code == 1
    assert "0/5" in output


# ------------------------------------------------- the passing case: strict increase


def test_five_strictly_increasing_rounds_pass():
    with HealthStub(list(range(7, 40)), token_configured=True) as stub:
        code, output = run(stub, auth_evidence="fine-grained PAT, Contents:read, PRs:read")

    assert code == 0
    assert "cycles counted (strictly increasing rounds): 5/5" in output
    assert "REFRESH RESULT: PASS" in output
    assert "each counted cycle had a strictly higher round counter" in output
    for cycle in range(1, 6):
        assert f"COUNTED   cycle {cycle}/5" in output


def test_duplicate_samples_between_advances_are_tolerated_but_not_counted():
    """Polling faster than the target refreshes is normal; it must not inflate the count."""
    sequence = [7, 7, 7, 8, 8, 9, 9, 9, 10, 11, 11, 12]
    with HealthStub(sequence + [12] * 100, token_configured=True) as stub:
        code, output = run(stub, auth_evidence="attested")

    assert code == 0
    assert "cycles counted (strictly increasing rounds): 5/5" in output
    # More samples than cycles: the duplicates were seen and correctly ignored.
    assert stub.health_hits > 5
    assert "no new round yet — not counted" in output


def test_the_first_sample_is_a_baseline_and_is_never_counted_as_a_cycle():
    """'Increases strictly between counted cycles' needs a baseline to increase from."""
    with HealthStub(list(range(7, 40)), token_configured=True) as stub:
        _, output = run(stub, auth_evidence="attested")
    assert "baseline (rounds=7); waiting for it to advance" in output
    assert "COUNTED   cycle 1/5 at rounds=8" in output


# --------------------------------------------------------- bounded observation window


def test_the_wait_for_a_new_round_is_bounded_and_reported_as_a_failure():
    with HealthStub([7] * 500, token_configured=True) as stub:
        code, output = run(stub, interval=5.0, max_wait=30.0)
    assert code == 1
    assert "no new refresh round within the bounded 30s window" in output
    assert "TIMEOUT" in output


def test_an_unreachable_target_fails_immediately():
    with HealthStub([7, 8, 9], token_configured=True) as stub:
        base = stub.base_url
    # Server is now closed.
    clock = Clock()
    lines: list[str] = []
    code = probe.remote_rounds(base, 5, 1.0, max_wait=10.0, printer=lines.append,
                               sleep=clock.sleep, monotonic=clock.monotonic)
    output = "\n".join(lines)
    assert code == 1
    assert "unreachable" in output.lower()


def test_a_round_that_advances_while_unhealthy_fails():
    """Five *successful* cycles: an advancing but offline target is not success."""
    with HealthStub(list(range(7, 40)), token_configured=True, link="OFFLINE", failures=2) as stub:
        code, output = run(stub)
    assert code == 1
    assert "not healthy" in output
    assert "consecutive *successful* cycles" in output


def test_a_non_integer_round_counter_is_refused():
    with HealthStub([None] * 10, token_configured=True) as stub:
        code, output = run(stub)
    assert code == 1
    assert "integer round counter" in output


# ------------------------------------------------- the authentication claim, separate


def test_a_target_without_a_token_never_yields_an_authenticated_pass():
    """Refresh can pass anonymously; the authenticated claim must not follow from it."""
    with HealthStub(list(range(7, 40)), token_configured=False) as stub:
        code, output = run(stub)

    assert "REFRESH RESULT: PASS" in output
    assert "token configured on target : NO" in output
    assert "AUTHENTICATED REFRESH PASS : NOT CLAIMED" in output
    assert "ANONYMOUS" in output
    # 2, not 0: an unproven claim must stay distinguishable from a proven one.
    assert code == 2


def test_require_auth_turns_a_missing_token_into_a_failure():
    with HealthStub(list(range(7, 40)), token_configured=False) as stub:
        code, output = run(stub, require_auth=True)
    assert code == 1
    assert "--require-auth was set" in output


def test_a_configured_token_alone_is_not_proof_of_read_only_scope():
    """A token proves authentication, not scope, and the probe never sees the token."""
    with HealthStub(list(range(7, 40)), token_configured=True) as stub:
        code, output = run(stub)

    assert "REFRESH RESULT: PASS" in output
    assert "token configured on target : YES" in output
    assert "read-only scope            : UNPROVEN" in output
    assert "AUTHENTICATED REFRESH PASS : NOT CLAIMED" in output
    assert "Contents: Read-only" in output
    assert code == 2


def test_operator_attested_scope_is_labelled_as_attestation_not_verification():
    evidence = "fine-grained PAT 2026-09-26: repo-scoped, Contents:read, Pull requests:read"
    with HealthStub(list(range(7, 40)), token_configured=True) as stub:
        code, output = run(stub, auth_evidence=evidence)

    assert code == 0
    assert "OPERATOR-ATTESTED" in output
    assert evidence in output
    assert "AUTHENTICATED REFRESH PASS : YES" in output
    # The distinction is explicit, so a reader cannot take it for probe verification.
    assert "not probe-verified" in output


def test_authentication_is_never_reported_when_the_refresh_itself_failed():
    """A failed refresh must not be followed by an authentication verdict of any kind."""
    with HealthStub([7] * 200, token_configured=True) as stub:
        code, output = run(stub, auth_evidence="attested")
    assert code == 1
    assert "AUTHENTICATION" not in output


def test_the_target_profile_reports_what_the_dashboard_publishes():
    with HealthStub([7], token_configured=True) as stub:
        profile = probe.profile_target(stub.base_url)
    assert profile.reachable is True
    assert profile.token_configured is True
    assert profile.repository == "krumingo/BEG_Worck"
    assert profile.refresh_seconds == 15


def test_an_unreadable_target_profile_is_not_treated_as_authenticated():
    """If ``/api/state`` cannot be read, ``token_configured`` is unknown — not true.

    The refresh itself is still observable from ``/healthz``, so this exercises a
    passing refresh with an unknown authentication posture: the probe must decline the
    authenticated claim rather than defaulting to it.
    """
    with HealthStub(list(range(7, 40)), token_configured=True, state_available=False) as stub:
        profile = probe.profile_target(stub.base_url)
        assert profile.reachable is False
        assert profile.token_configured is None

        code, output = run(stub, auth_evidence="attested anyway")

    assert "REFRESH RESULT: PASS" in output
    assert "/api/state unreachable" in output
    assert "token configured on target : NO (or not reported)" in output
    assert "AUTHENTICATED REFRESH PASS : NOT CLAIMED" in output
    # Operator attestation cannot substitute for the target actually having a token.
    assert "AUTHENTICATED REFRESH PASS : YES" not in output
    assert code == 2


# ------------------------------------------------------------------ the default wait


def test_the_default_bounded_wait_is_derived_from_the_target_cadence():
    """Long enough to survive a missed round and a backoff step; never unbounded."""
    captured = {}
    original = probe.observe_rounds

    def spy(base_url, count, poll_interval, max_wait, **kwargs):
        captured["max_wait"] = max_wait
        return original(base_url, count, poll_interval, max_wait, **kwargs)

    probe.observe_rounds = spy
    try:
        with HealthStub(list(range(7, 40)), token_configured=True) as stub:
            clock = Clock()
            probe.remote_rounds(stub.base_url, 5, 1.0, printer=lambda *_: None,
                                sleep=clock.sleep, monotonic=clock.monotonic,
                                auth_evidence="attested")
    finally:
        probe.observe_rounds = original

    # 15s cadence -> 3x is 45, floored at 90, and always capped at 600.
    assert captured["max_wait"] == 90.0
    assert 0 < captured["max_wait"] <= 600.0
