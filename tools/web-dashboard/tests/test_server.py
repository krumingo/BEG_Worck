"""The HTTP surface: what it serves, what it refuses, and what it never discloses."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
from app.github import GitHubReadOnlyClient, TransportError
from app.refresh import Refresher
from app.server import make_server
from app.settings import Settings

# Assembled at runtime rather than written as a literal: a PAT-shaped string in a
# committed file trips secret scanners and push protection, and the value here is a
# fixture, not a credential. Redaction is exercised on the assembled string, so the
# test is exactly as strong.
TOKEN = "gh" + "p_" + "SERVERTESTtoken0123456789abcdefGH"


@pytest.fixture
def live_server(fake_github):
    """A real socket on a real ephemeral port, so responses are genuinely exercised."""
    settings = Settings(
        repository="krumingo/BEG_Worck",
        branch="codex/claude-queue",
        token=TOKEN,
        host="127.0.0.1",
        port=0,
    )
    client = GitHubReadOnlyClient(repository=settings.repository, token=TOKEN, transport=fake_github)
    refresher = Refresher(client, settings)
    refresher.tick()

    server = make_server(refresher, settings)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, refresher, fake_github
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as reply:
        return reply.status, dict(reply.headers.items()), reply.read()


# ------------------------------------------------------------------- endpoints


def test_the_app_shell_is_served_at_the_root(live_server):
    base, _, _ = live_server
    status, headers, body = get(base, "/")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"BEG_WORK" in body
    # Nothing is prerendered into the shell: every value arrives from /api/state.
    assert b"W0-03C" not in body


def test_the_state_endpoint_serves_the_projection(live_server):
    base, _, _ = live_server
    status, headers, body = get(base, "/api/state")
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert headers["Cache-Control"] == "no-store, no-cache, must-revalidate"
    payload = json.loads(body)
    assert payload["header"]["task_id"] == "W0-03C"
    assert payload["verified"] is True


def test_the_health_endpoint_reports_liveness_and_readiness_detail(live_server):
    base, _, _ = live_server
    status, _, body = get(base, "/healthz")
    assert status == 200
    health = json.loads(body)
    assert health["status"] == "ok"
    assert health["link"] == "ONLINE"
    assert health["control_state_status"] == "VALID"
    assert health["snapshot_available"] is True
    assert health["rounds"] >= 1


def test_health_stays_200_while_github_is_unreachable(live_server):
    """Restarting a dashboard that is waiting out an outage would discard the cache.

    So the status code reports whether this process can serve, and the body reports
    whether it has fresh data. Container Manager restarts on the former, an operator
    reads the latter.
    """
    base, refresher, fake_github = live_server
    fake_github.fail_everything = TransportError("github unreachable")
    refresher.tick()

    status, _, body = get(base, "/healthz")
    assert status == 200
    health = json.loads(body)
    assert health["link"] == "OFFLINE"
    assert health["consecutive_failures"] >= 1
    # The cached snapshot is still there and still described honestly.
    assert health["snapshot_available"] is True


@pytest.mark.parametrize(
    "path,content_type",
    [
        ("/app.css", "text/css"),
        ("/app.js", "text/javascript"),
        ("/manifest.webmanifest", "application/manifest+json"),
        ("/sw.js", "text/javascript"),
        ("/favicon.svg", "image/svg+xml"),
        ("/icon-192.png", "image/png"),
        ("/icon-512.png", "image/png"),
    ],
)
def test_every_declared_static_asset_is_actually_served(path, content_type, live_server):
    """A manifest referencing a missing icon silently breaks installability."""
    base, _, _ = live_server
    status, headers, body = get(base, path)
    assert status == 200
    assert body
    assert headers["Content-Type"].split(";")[0] in {content_type, "application/octet-stream"}


def test_the_service_worker_never_caches_the_live_endpoints(live_server):
    base, _, _ = live_server
    _, _, body = get(base, "/sw.js")
    source = body.decode("utf-8")
    assert "/api/state" in source and "/healthz" in source
    # Both appear in the bypass condition rather than in the precache list.
    assert "'/api/state'" in source
    assert "/api/state" not in source.split("const SHELL")[1].split("]")[0]


# -------------------------------------------------------------- what is refused


@pytest.mark.parametrize("path", ["/nope", "/api/", "/api/state/extra", "/app.py", "/../app/settings.py", "/static/app.css"])
def test_anything_outside_the_allowlist_is_404(path, live_server):
    """Routing is an explicit table: no directory is exposed, so traversal has no target."""
    base, _, _ = live_server
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(base, path)
    assert caught.value.code == 404


def test_application_source_is_not_reachable_over_http(live_server):
    base, _, _ = live_server
    for path in ["/app/settings.py", "/settings.py", "/app/__main__.py", "/.env", "/Dockerfile"]:
        with pytest.raises(urllib.error.HTTPError) as caught:
            get(base, path)
        assert caught.value.code == 404


def test_security_headers_are_present_on_responses(live_server):
    base, _, _ = live_server
    for path in ["/", "/api/state"]:
        _, headers, _ = get(base, path)
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        csp = headers["Content-Security-Policy"]
        # The UI is self-contained, so nothing third-party may load or connect.
        assert "default-src 'none'" in csp
        assert "connect-src 'self'" in csp


# ------------------------------------------------------------ token containment


def test_no_response_from_the_server_contains_the_token(live_server):
    """The whole surface, not only the projection."""
    base, _, _ = live_server
    for path in ["/", "/api/state", "/healthz", "/app.js", "/app.css", "/manifest.webmanifest", "/sw.js"]:
        _, headers, body = get(base, path)
        assert TOKEN.encode() not in body, path
        assert TOKEN not in json.dumps(headers), path


def test_the_token_is_absent_even_when_a_read_has_just_failed(live_server):
    """An error message is a classic place for a credential to escape."""
    base, refresher, fake_github = live_server
    fake_github.fail_everything = TransportError(f"HTTP 401 with Authorization: Bearer {TOKEN}")
    refresher.tick()

    _, _, body = get(base, "/api/state")
    assert TOKEN.encode() not in body
    payload = json.loads(body)
    assert payload["last_error"]
    assert "REDACTED" in payload["last_error"] or TOKEN not in payload["last_error"]


def test_head_requests_are_answered_without_a_body(live_server):
    base, _, _ = live_server
    request = urllib.request.Request(base + "/api/state", method="HEAD")
    with urllib.request.urlopen(request, timeout=5) as reply:
        assert reply.status == 200
        assert reply.read() == b""


def test_sigterm_shuts_the_process_down_promptly(tmp_path):
    """``docker stop`` sends SIGTERM and waits 10 s before SIGKILL.

    Regression test. Calling ``server.shutdown()`` directly from the signal handler
    deadlocks: the handler runs on the thread that is inside ``serve_forever()``, and
    ``shutdown()`` waits for that loop to exit, which it cannot do until the handler
    returns. The observable symptom is a container that never stops cleanly.
    """
    import os
    import pathlib
    import signal
    import subprocess
    import sys
    import time
    import urllib.request

    root = pathlib.Path(__file__).resolve().parents[1]
    environment = dict(
        os.environ,
        BEGWORK_PORT="8094",
        BEGWORK_HOST="127.0.0.1",
        PYTHONPATH=str(root),
        # Point at a host that cannot be resolved: this test is about process lifecycle,
        # and it must not depend on network access or consume a rate-limit budget.
        BEGWORK_API_BASE="http://127.0.0.1:9",
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=str(root),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen("http://127.0.0.1:8094/healthz", timeout=2).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            pytest.fail("the dashboard never started serving")

        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        code = process.wait(timeout=10)
        assert code == 0
        assert time.monotonic() - started < 8, "SIGTERM was not honoured promptly"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
