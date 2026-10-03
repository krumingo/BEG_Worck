"""GitHub-event adapter for the Issue #22 coordination read-model.

No schedule, polling, model call, PR-head checkout, dispatch, merge or deploy.
Both workflow entrypoints call this same module and the same pure projector.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from coordination_status import (
    canonical_json,
    fields,
    handoff_for_head,
    project,
    utc_timestamp,
    valid_sha,
    validate,
)


REPOSITORY = "krumingo/BEG_Worck"
QUEUE = "codex/claude-queue"
STATUS_PATH = "coordination/STATUS.json"
ACTIVE_PATH = "coordination/ACTIVE.md"
REVIEW_PREFIX = "coordination/REVIEWS/"
WAVES_PATH = "docs/architecture/IMPLEMENTATION_WAVES.md"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"


class RefChanged(RuntimeError):
    """The queue advanced while a projection commit was being prepared."""


class GitHubAPI:
    def __init__(self, token: str):
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self.token = token

    def request(self, method: str, endpoint: str, data: dict | None = None):
        body = None if data is None else json.dumps(data).encode("utf-8")
        request = Request(
            API_ROOT + endpoint,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "beg-work-status-v1",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in {409, 422} and method == "PATCH":
                raise RefChanged("queue ref changed; no forced update") from exc
            raise

    def get(self, endpoint: str):
        return self.request("GET", endpoint)

    def post(self, endpoint: str, data: dict):
        return self.request("POST", endpoint, data)

    def patch(self, endpoint: str, data: dict):
        return self.request("PATCH", endpoint, data)

    def branch_sha(self, branch: str) -> str:
        item = self.get(f"/git/ref/heads/{branch}")
        sha = item["object"]["sha"] if item else None
        if not valid_sha(sha):
            raise ValueError(f"unverifiable branch: {branch}")
        return sha

    def file_text(self, path: str, ref: str) -> str | None:
        item = self.get(f"/contents/{path}?ref={quote(ref, safe='')}")
        if item is None:
            return None
        if item.get("encoding") != "base64" or item.get("type") != "file":
            raise ValueError(f"unverifiable file: {path}")
        return base64.b64decode(item["content"], validate=False).decode("utf-8")

    def path_commit(self, path: str, ref: str) -> str | None:
        items = self.get(
            f"/commits?path={quote(path, safe='')}"
            f"&sha={quote(ref, safe='')}&per_page=1"
        )
        sha = items[0]["sha"] if items else None
        return sha if valid_sha(sha) else None

    def issue_comments(self, number: int):
        comments = []
        for page in range(1, 11):
            chunk = self.get(f"/issues/{number}/comments?per_page=100&page={page}")
            if not isinstance(chunk, list):
                raise ValueError("unverifiable PR comments")
            comments.extend(chunk)
            if len(chunk) < 100:
                return comments
        raise ValueError("comment pagination limit; fail closed")

    def changed_files(self, before: str, after: str) -> set[str]:
        if not (valid_sha(before) and valid_sha(after)):
            return set()
        comparison = self.get(f"/compare/{before}...{after}")
        if not comparison or comparison.get("files") is None:
            return set()
        if comparison.get("total_commits", 0) > 250 or len(comparison["files"]) >= 300:
            return set()
        return {item["filename"] for item in comparison["files"]}

    def write_status(self, expected_queue_sha: str, content: str) -> str:
        """Create one fast-forward commit; never overwrite a concurrent queue push."""
        if self.branch_sha(QUEUE) != expected_queue_sha:
            raise RefChanged("queue advanced before write")
        parent = self.get(f"/git/commits/{expected_queue_sha}")
        if not parent or not valid_sha(parent.get("tree", {}).get("sha")):
            raise ValueError("queue tree is unverifiable")
        blob = self.post(
            "/git/blobs", {"content": content, "encoding": "utf-8"}
        )["sha"]
        tree = self.post(
            "/git/trees",
            {
                "base_tree": parent["tree"]["sha"],
                "tree": [
                    {
                        "path": STATUS_PATH,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob,
                    }
                ],
            },
        )["sha"]
        commit = self.post(
            "/git/commits",
            {
                "message": "coordination: project verified status event",
                "tree": tree,
                "parents": [expected_queue_sha],
            },
        )["sha"]
        self.patch(
            f"/git/refs/heads/{QUEUE}",
            {"sha": commit, "force": False},
        )
        return commit


def trusted_actor(payload: dict, allowed: set[str]) -> bool:
    actor = payload.get("sender", {}).get("login")
    return isinstance(actor, str) and actor in allowed


def push_changed_files(payload: dict, api: GitHubAPI) -> set[str]:
    if payload.get("ref") != f"refs/heads/{QUEUE}":
        return set()
    files = api.changed_files(payload.get("before", ""), payload.get("after", ""))
    return {path for path in files if path == ACTIVE_PATH or path.startswith(REVIEW_PREFIX)}


def latest_handoff(api: GitHubAPI, number: int, head: str, allowed: set[str]):
    matches = []
    for item in api.issue_comments(number):
        if item.get("user", {}).get("login") not in allowed:
            continue
        candidate = {"body": item.get("body"), "url": item.get("html_url")}
        if handoff_for_head(candidate, head):
            matches.append((item.get("created_at", ""), candidate))
    return max(matches, default=(None, None), key=lambda pair: pair[0])[1]


def read_snapshot(api: GitHubAPI, allowed: set[str]) -> tuple[dict, str]:
    queue_sha = api.branch_sha(QUEUE)
    main_sha = api.branch_sha("main")
    active = api.file_text(ACTIVE_PATH, queue_sha)
    if active is None:
        raise ValueError("ACTIVE missing")
    header = fields(active)
    task = header.get("Task-ID", "")
    review_path = (
        REVIEW_PREFIX + task + ".md"
        if task and task != "NONE" and "/" not in task and ".." not in task
        else None
    )
    review = api.file_text(review_path, queue_sha) if review_path else None
    url = header.get("PR-URL", "")
    number = int(url.rsplit("/", 1)[1]) if url.startswith(
        f"https://github.com/{REPOSITORY}/pull/"
    ) and url.rsplit("/", 1)[1].isdigit() else None
    remote_pr = api.get(f"/pulls/{number}") if number else None
    pr = {}
    handoff = None
    if remote_pr and remote_pr.get("html_url") == url:
        pr = {
            "number": remote_pr.get("number"),
            "url": remote_pr.get("html_url"),
            "state": "MERGED" if remote_pr.get("merged_at") else
            str(remote_pr.get("state", "")).upper(),
            "headRefOid": remote_pr.get("head", {}).get("sha"),
        }
        if valid_sha(pr["headRefOid"]):
            handoff = latest_handoff(api, number, pr["headRefOid"], allowed)
    snapshot = {
        "active": active,
        "review": review or "",
        "waves": api.file_text(WAVES_PATH, main_sha) or "",
        "active_commit_sha": api.path_commit(ACTIVE_PATH, queue_sha),
        "review_commit_sha": api.path_commit(review_path, queue_sha)
        if review_path and review else None,
        "waves_commit_sha": api.path_commit(WAVES_PATH, main_sha),
        "pr": pr,
        "handoff": handoff,
    }
    if not valid_sha(snapshot["active_commit_sha"]):
        raise ValueError("ACTIVE source commit is unverifiable")
    if review and not valid_sha(snapshot["review_commit_sha"]):
        raise ValueError("review source commit is unverifiable")
    if not valid_sha(snapshot["waves_commit_sha"]):
        raise ValueError("Waves source commit is unverifiable")
    return snapshot, queue_sha


def classify(
    event_name: str, payload: dict, snapshot: dict, api: GitHubAPI,
    allowed: set[str],
) -> dict | None:
    """Return only a verified transition; None means no privileged write."""
    if payload.get("repository", {}).get("full_name") != REPOSITORY:
        return None
    if not trusted_actor(payload, allowed):
        return None
    active = fields(snapshot["active"])
    pr = snapshot["pr"]
    if event_name == "push":
        files = push_changed_files(payload, api)
        if not files:
            return None
        # A delayed webhook must not project a later, unrelated queue state.
        if payload.get("after") != api.branch_sha(QUEUE):
            return None
        review = fields(snapshot["review"])
        verdict = review.get("Verdict", "").split(" ", 1)[0]
        review_changed = any(path.startswith(REVIEW_PREFIX) for path in files)
        if review_changed and verdict in {"PASS", "CHANGES_REQUESTED", "BLOCKED"}:
            kind = "CODEX_" + verdict
        elif ACTIVE_PATH in files and active.get("Dispatch-State") == "RUNNING":
            kind = "DISPATCH_STARTED"
        elif ACTIVE_PATH in files and active.get("Status") == "READY":
            kind = "ASSIGNMENT"
        elif ACTIVE_PATH in files and active.get("Status") == "BLOCKED" and verdict == "BLOCKED":
            kind = "CODEX_BLOCKED"
        else:
            return None
        stamp = payload.get("head_commit", {}).get("timestamp")
        return {"kind": kind, "at": stamp} if utc_timestamp(stamp) else None

    number = payload.get("number") or payload.get("issue", {}).get("number")
    if not pr or number != pr.get("number"):
        return None
    if event_name == "pull_request_target":
        if payload.get("action") not in {"opened", "synchronize", "closed"}:
            return None
        event_pr = payload.get("pull_request", {})
        if (
            event_pr.get("html_url") != pr.get("url")
            or event_pr.get("head", {}).get("sha") != pr.get("headRefOid")
            or event_pr.get("base", {}).get("ref") != "main"
            or event_pr.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY
        ):
            return None
        if payload["action"] == "closed":
            return None  # No PR-state field in v1; no synthetic transition.
        stamp = event_pr.get("updated_at")
        return {"kind": "PR_HEAD_CHANGED", "at": stamp} if utc_timestamp(stamp) else None

    if event_name == "issue_comment":
        if payload.get("action") != "created":
            return None
        issue = payload.get("issue", {})
        comment = payload.get("comment", {})
        if not issue.get("pull_request"):
            return None
        if comment.get("user", {}).get("login") not in allowed:
            return None
        candidate = {"body": comment.get("body"), "url": comment.get("html_url")}
        if (
            not handoff_for_head(candidate, pr.get("headRefOid"))
            or active.get("PR-Head") != pr.get("headRefOid")
        ):
            return None
        # The event must be the exact HANDOFF selected by the fresh snapshot.
        if not snapshot.get("handoff") or snapshot["handoff"]["url"] != candidate["url"]:
            return None
        stamp = comment.get("created_at")
        return {"kind": "CLAUDE_HANDOFF", "at": stamp} if utc_timestamp(stamp) else None
    return None


def update(api: GitHubAPI, event_name: str, payload: dict, allowed: set[str]) -> str:
    snapshot, queue_sha = read_snapshot(api, allowed)
    event = classify(event_name, payload, snapshot, api, allowed)
    if event is None:
        return "IGNORED_UNVERIFIED_EVENT"
    candidate = project(snapshot, event)
    if validate(candidate):
        raise ValueError("projected STATUS fails schema validation")
    if candidate["last_event"] == "UNKNOWN":
        return "IGNORED_AMBIGUOUS_EVENT"
    existing_text = api.file_text(STATUS_PATH, queue_sha)
    existing = json.loads(existing_text) if existing_text else None
    if existing == candidate:
        return "NO_SEMANTIC_CHANGE"
    # An unrelated prose edit or duplicate event must not rewrite provenance.
    if isinstance(existing, dict):
        stable = {
            "last_event", "last_event_at", "source_versions"
        }
        if all(
            existing.get(key) == candidate.get(key)
            for key in candidate.keys() - stable
        ):
            return "NO_STATE_TRANSITION"
    return "WROTE " + api.write_status(queue_sha, canonical_json(candidate))


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    token = os.environ.get("GITHUB_TOKEN")
    allowed = {
        actor.strip()
        for actor in os.environ.get("STATUS_TRUSTED_ACTORS", "").split(",")
        if actor.strip()
    }
    if not (event_path and event_name and token and allowed):
        print("missing event/token/trusted-actor configuration", file=sys.stderr)
        return 2
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    try:
        result = update(GitHubAPI(token), event_name, payload, allowed)
    except RefChanged as exc:
        print(f"FAIL_CLOSED: {exc}", file=sys.stderr)
        return 3
    except (ValueError, HTTPError, KeyError, TypeError) as exc:
        print(f"FAIL_CLOSED: {exc}", file=sys.stderr)
        return 4
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
