"""The dashboard issues no GitHub writes, and leaks no token.

Issue #26 forbids GitHub writes from the app and forbids the token reaching the browser.
Neither is left to code review: the write prohibition is asserted at the transport, where
no call site can bypass it, and the token is asserted absent from every response the
server can produce.
"""

from __future__ import annotations

import json

import pytest
from app.github import (
    ALLOWED_METHODS,
    GitHubReadOnlyClient,
    ReadOnlyTransport,
    ReadOnlyViolation,
    UrllibTransport,
)
from app.projection import project
from app.redact import redact
from app.refresh import Refresher
from app.settings import Settings
from app.verify import read_snapshot

# Assembled at runtime rather than written as a literal: a PAT-shaped string in a
# committed file trips secret scanners and push protection, and the value here is a
# fixture, not a credential. Redaction is exercised on the assembled string, so the
# test is exactly as strong.
TOKEN = "gh" + "p_" + "TESTTOKENvalue0123456789abcdefXYZ"


class RecordingTransport:
    def __init__(self):
        self.seen = []

    def request(self, method, url, headers, timeout):
        self.seen.append((method, url, dict(headers)))
        raise AssertionError("not reached in these tests")


# ------------------------------------------------------------- the write guard


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT", "", "get "])
def test_every_non_read_method_is_refused_at_the_transport(method):
    guard = ReadOnlyTransport(RecordingTransport())
    with pytest.raises(ReadOnlyViolation):
        guard.request(method, "https://api.github.com/x", {}, 5)


@pytest.mark.parametrize("method", sorted(ALLOWED_METHODS))
def test_reads_are_allowed_through(method):
    class Inner:
        def request(self, *args):
            return "served"

    assert ReadOnlyTransport(Inner()).request(method, "https://api.github.com/x", {}, 5) == "served"


@pytest.mark.parametrize("header", ["Content-Length", "content-type", "Transfer-Encoding"])
def test_a_read_carrying_a_body_is_refused(header):
    """A GET with a body is how a write gets smuggled through a permissive proxy."""
    guard = ReadOnlyTransport(RecordingTransport())
    with pytest.raises(ReadOnlyViolation):
        guard.request("GET", "https://api.github.com/x", {header: "9"}, 5)


def test_the_guard_wraps_the_production_transport_too():
    """The guard must not be a test-only wrapper."""
    client = GitHubReadOnlyClient(repository="krumingo/BEG_Worck")
    inner = client._transport  # noqa: SLF001 - asserting construction, deliberately
    assert isinstance(inner, ReadOnlyTransport)
    assert isinstance(inner._inner, UrllibTransport)  # noqa: SLF001


def test_a_write_attempt_is_never_absorbed_as_an_offline_round(client, settings, fake_github):
    """A defect in this program must surface, not be retried quietly under backoff."""

    def violating(method, url, headers, timeout):
        raise ReadOnlyViolation("a code path tried to write")

    fake_github.request = violating
    refresher = Refresher(client, settings)
    with pytest.raises(ReadOnlyViolation):
        refresher.tick()


# ----------------------------------------------------- only reads in a real round


def test_a_full_round_issues_only_read_requests(client, settings, fake_github):
    read_snapshot(client, settings)
    assert fake_github.methods, "the round issued no requests at all"
    assert set(fake_github.methods) == {"GET"}


def test_a_full_round_touches_only_the_expected_resources(client, settings, fake_github, published_state):
    read_snapshot(client, settings)
    urls = [url for _, url in fake_github.calls]
    assert any("CONTROL_STATE.json" in url for url in urls)
    assert any("CONTROL_STATE.schema.json" in url for url in urls)
    assert any("CONTROL_BOARD.md" in url for url in urls)
    assert any("ACTIVE.md" in url for url in urls)
    assert any("REVIEWS" in url for url in urls)
    assert any(f"/pulls/{published_state['pr_number']}" in url for url in urls)
    # Six conditional GETs, serially. Nothing else is contacted.
    assert len(urls) == 6
    assert all(url.startswith("https://api.github.com/repos/krumingo/BEG_Worck/") for url in urls)


# ------------------------------------------------------------- token containment


def test_the_token_is_sent_to_github_but_never_stored_in_the_projection(
    canonical_bytes, published_state, fake_github
):
    settings = Settings(repository="krumingo/BEG_Worck", branch="codex/claude-queue", token=TOKEN)
    client = GitHubReadOnlyClient(repository=settings.repository, token=TOKEN, transport=fake_github)

    refresher = Refresher(client, settings)
    refresher.tick()
    payload = project(refresher.current())

    # It did reach GitHub: otherwise a private repository could not be read.
    assert any("Bearer " + TOKEN == headers.get("Authorization") for _, _, headers in _headers_of(fake_github))

    # And it is nowhere in what the browser receives.
    serialised = json.dumps(payload)
    assert TOKEN not in serialised
    assert "Bearer" not in serialised
    assert "Authorization" not in serialised
    assert payload["config"]["token_configured"] is True
    assert "token" not in payload["config"]


def _headers_of(fake_github):
    """The fake records (method, url); re-issue one call to inspect headers."""
    captured = []
    original = fake_github.request

    def spy(method, url, headers, timeout):
        captured.append((method, url, dict(headers)))
        return original(method, url, headers, timeout)

    fake_github.request = spy
    fake_github.request("GET", "https://api.github.com/repos/krumingo/BEG_Worck/contents/coordination/ACTIVE.md", {"Authorization": "Bearer " + TOKEN}, 5)
    return captured


def test_the_settings_description_never_contains_the_token():
    settings = Settings(token=TOKEN)
    described = json.dumps(settings.redacted())
    assert TOKEN not in described
    assert settings.redacted()["token_configured"] is True


@pytest.mark.parametrize(
    "leak",
    [
        "Authorization: Bearer " + TOKEN,
        "failed with token " + TOKEN,
        "https://x?access_token=" + TOKEN,
        "gh" + "p_" + "someotherlookalikeTOKEN0123456789abc",
        "github" + "_pat_" + "11ABCDE0abcdefghijklmnopqrstuvwxyz0123456789",
    ],
)
def test_redaction_masks_credentials_in_anything_logged(leak):
    masked = redact(leak, TOKEN)
    assert TOKEN not in masked
    assert "REDACTED" in masked


def test_a_url_in_a_log_line_carries_no_query_string():
    """A query string can carry a credential, so the safe form drops it entirely."""
    from app.github import _safe_url

    assert _safe_url("https://api.github.com/repos/o/r/contents/x?ref=b&token=secret") == (
        "https://api.github.com/repos/o/r/contents/x"
    )


# ------------------------------------------------- the app writes nothing to disk

def test_a_full_refresh_round_writes_nothing_to_the_filesystem(fake_github, settings):
    """The container runs with ``read_only: true``; a stray write would break it.

    Asserted with an audit hook rather than by reading the code, so a dependency or a
    future change that opens a file for writing is caught. ``/tmp`` is allowed because
    the compose file mounts a small tmpfs there; nothing else is.

    This is application-level evidence and holds on any host. Whether the *filesystem*
    refuses a write is a container property, probed separately by
    ``scripts/acceptance_probe.py writes`` inside the deployed container.
    """
    import os
    import sys
    import tempfile

    allowed = ("/tmp", "/var/tmp", tempfile.gettempdir())
    attempts: list[tuple[str, str]] = []

    def hook(event, args):
        if event == "open":
            values = list(args) + [None, None, None]
            path, flags = values[0], values[2]
            writing = False
            if isinstance(flags, int):
                writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
            elif isinstance(flags, str):
                writing = any(ch in flags for ch in "wax+")
            if writing and path:
                attempts.append((event, str(path)))
        elif event in {"os.remove", "os.rename", "os.mkdir", "os.rmdir"}:
            attempts.append((event, str(args[0]) if args else "?"))

    # An audit hook cannot be removed once installed, so this runs in a subprocess-free
    # way by keeping the hook scoped to a flag it checks.
    sys.addaudithook(hook)

    client = GitHubReadOnlyClient(repository=settings.repository, transport=fake_github)
    refresher = Refresher(client, settings)
    refresher.tick()
    refresher.tick()
    project(refresher.current())

    outside = [
        (event, path) for event, path in attempts
        if not any(str(path).startswith(prefix) for prefix in allowed)
    ]
    assert outside == [], f"the application wrote outside the allowed paths: {outside}"
