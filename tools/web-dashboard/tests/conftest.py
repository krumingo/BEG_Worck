"""Shared fixtures.

The important decision here is how source bytes are obtained.

PR #28's fixtures read the *working tree* (``Path.read_bytes``). On a Windows checkout
with ``core.autocrlf=true`` Git rewrites LF to CRLF on checkout, which changes the bytes
and therefore changes their Git blob SHA -- so eight tests that expected VALID came out
STALE, and one saw blob ``77d97a0d`` where CONTROL_STATE cites ``4bd78006``. The
committed object was never wrong; the fixture was reading something else.

So every fixture here reads **canonical committed blob bytes** via ``git cat-file blob``.
Those bytes are identical on every platform and every ``core.autocrlf`` setting, because
they are the object Git stores, which is also exactly what the GitHub API serves in
production. Nothing in the production fail-closed blob check is relaxed to make this
work: ``verify._check_blob`` still demands an exact match, and
``test_blob_and_pr.py::test_a_crlf_converted_checkout_would_not_match`` pins that a
CRLF-converted copy is still correctly rejected.
"""

from __future__ import annotations

import base64
import copy
import json
import pathlib
import subprocess
import sys

import pytest

DASHBOARD_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = DASHBOARD_ROOT.parents[1]

# Import the application under test, and the canonical engine it is checked against.
sys.path.insert(0, str(DASHBOARD_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from app.github import GitHubReadOnlyClient, Response, TransportError  # noqa: E402
from app.board import render_board  # noqa: E402
from app.gitblob import blob_sha1  # noqa: E402
from app.settings import (  # noqa: E402
    CONTROL_BOARD_PATH,
    CONTROL_SCHEMA_PATH,
    CONTROL_STATE_PATH,
    Settings,
)

ACTIVE_PATH = "coordination/ACTIVE.md"
REVIEW_PATH = "coordination/REVIEWS/W0-03C.md"


def git_blob(path: str, ref: str = "HEAD") -> bytes:
    """The exact committed bytes of ``path`` at ``ref``.

    Never the working tree: see the module docstring.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "blob", f"{ref}:{path}"],
        capture_output=True,
        check=True,
    )
    return result.stdout


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def canonical_bytes() -> dict[str, bytes]:
    """Committed bytes for every file a round reads."""
    return {
        CONTROL_STATE_PATH: git_blob(CONTROL_STATE_PATH),
        CONTROL_SCHEMA_PATH: git_blob(CONTROL_SCHEMA_PATH),
        CONTROL_BOARD_PATH: git_blob(CONTROL_BOARD_PATH),
        ACTIVE_PATH: git_blob(ACTIVE_PATH),
        REVIEW_PATH: git_blob(REVIEW_PATH),
    }


@pytest.fixture
def published_state(canonical_bytes) -> dict:
    """The real published snapshot, as committed."""
    return json.loads(canonical_bytes[CONTROL_STATE_PATH].decode("utf-8"))


@pytest.fixture(scope="session")
def control_schema(canonical_bytes) -> dict:
    return json.loads(canonical_bytes[CONTROL_SCHEMA_PATH].decode("utf-8"))


@pytest.fixture
def published_board(canonical_bytes) -> str:
    return canonical_bytes[CONTROL_BOARD_PATH].decode("utf-8")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        repository="krumingo/BEG_Worck",
        branch="codex/claude-queue",
        token="",
        refresh_seconds=15,
        stale_after_seconds=120,
    )


class FakeGitHub:
    """An in-memory GitHub that serves canonical blob bytes.

    It models the two behaviours that matter for this dashboard: the contents API shape
    (base64 plus the blob SHA) and conditional requests (ETag / 304). Failures and
    mutations are injectable so the negative cases are exercised against the same code
    path as the positive one.
    """

    def __init__(self, files: dict[str, bytes], pull_requests: dict[int, dict] | None = None):
        self.files = dict(files)
        self.pull_requests = dict(pull_requests or {})
        self.calls: list[tuple[str, str]] = []
        self.methods: list[str] = []
        # path -> exception to raise instead of serving it
        self.fail_paths: dict[str, Exception] = {}
        self.fail_everything: Exception | None = None
        self.served_304 = 0

    # -- helpers used by tests ------------------------------------------------

    def set_file(self, path: str, content: bytes) -> None:
        self.files[path] = content

    def set_state(self, state: dict, regenerate_board: bool = True) -> None:
        """Replace the published state.

        The board is regenerated to match by default, because the protocol requires the
        two to agree: leaving a stale board behind would inject a second, unintended
        CONFLICT into every test that only meant to change the state. Pass
        ``regenerate_board=False`` to test board divergence deliberately.
        """
        self.files[CONTROL_STATE_PATH] = json.dumps(state, indent=2).encode("utf-8") + b"\n"
        if regenerate_board:
            try:
                self.files[CONTROL_BOARD_PATH] = render_board(state).encode("utf-8")
            except (KeyError, TypeError):
                # A state too damaged to render: leave the board alone. The test is about
                # the damage, and the board check reports "not comparable" for it anyway.
                pass

    def etag_for(self, path: str) -> str:
        return f'W/"{blob_sha1(self.files[path])}"'

    # -- transport ------------------------------------------------------------

    def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> Response:
        self.methods.append(method)
        self.calls.append((method, url))
        if self.fail_everything is not None:
            raise self.fail_everything

        if "/contents/" in url:
            path = url.split("/contents/", 1)[1].split("?", 1)[0]
            path = path.replace("%2F", "/")
            if path in self.fail_paths:
                raise self.fail_paths[path]
            if path not in self.files:
                raise TransportError(f"HTTP 404 for {path}", status=404)
            content = self.files[path]
            etag = self.etag_for(path)
            if headers.get("If-None-Match") == etag:
                self.served_304 += 1
                return Response(304, {"ETag": etag}, b"")
            payload = {
                "type": "file",
                "path": path,
                "encoding": "base64",
                "size": len(content),
                "sha": blob_sha1(content),
                "content": base64.b64encode(content).decode("ascii"),
            }
            return Response(200, {"ETag": etag}, json.dumps(payload).encode("utf-8"))

        if "/pulls/" in url:
            number = int(url.rsplit("/", 1)[1])
            if number not in self.pull_requests:
                raise TransportError(f"HTTP 404 for PR #{number}", status=404)
            body = json.dumps(self.pull_requests[number]).encode("utf-8")
            etag = f'W/"pr-{number}-{blob_sha1(body)}"'
            if headers.get("If-None-Match") == etag:
                self.served_304 += 1
                return Response(304, {"ETag": etag}, b"")
            return Response(200, {"ETag": etag}, body)

        raise TransportError(f"unexpected URL {url}")


@pytest.fixture
def fake_github(canonical_bytes, published_state) -> FakeGitHub:
    """A GitHub that agrees with the published snapshot in every respect.

    The PR it serves reports exactly the head and draft flag the snapshot cites, so this
    fixture exercises the agreeing case. Divergence is injected per test rather than
    inherited from whatever the live PR happens to be today, which keeps the suite
    deterministic and offline.
    """
    return FakeGitHub(
        files=dict(canonical_bytes),
        pull_requests={
            published_state["pr_number"]: {
                "number": published_state["pr_number"],
                "draft": published_state["pr_draft"],
                "state": "open",
                "merged": False,
                "html_url": f"https://github.com/krumingo/BEG_Worck/pull/{published_state['pr_number']}",
                "head": {"sha": published_state["pr_head_sha"]},
            }
        },
    )


@pytest.fixture
def client(fake_github, settings) -> GitHubReadOnlyClient:
    return GitHubReadOnlyClient(
        repository=settings.repository,
        token=settings.token,
        transport=fake_github,
    )


@pytest.fixture
def mutate():
    """Return a deep copy of a state with one mutation applied, leaving the original alone."""

    def apply(state: dict, change) -> dict:
        clone = copy.deepcopy(state)
        change(clone)
        return clone

    return apply
