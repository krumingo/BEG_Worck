"""Deterministic, fail-closed BEG_Work coordination read-model.

This module deliberately does not dispatch work, call a model, or write GitHub
state. An event adapter supplies one GitHub snapshot and calls project().
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "coordination" / "STATUS.schema.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PR_RE = re.compile(r"^https://github\.com/krumingo/BEG_Worck/pull/(\d+)$")
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*?)\s*$", re.MULTILINE)
HANDOFF_RE = re.compile(r"^#{1,2}\s+HANDOFF\b", re.IGNORECASE)
HANDOFF_SHA_RE = re.compile(
    r"(?:^HEAD\s*[=:]\s*|\*\*Exact new head:\*\*\s*`)"
    r"([0-9a-f]{40})(?:`)?",
    re.MULTILINE,
)
EVENTS = {
    "ASSIGNMENT", "DISPATCH_STARTED", "PR_HEAD_CHANGED", "CLAUDE_HANDOFF",
    "CODEX_PASS", "CODEX_CHANGES_REQUESTED", "CODEX_BLOCKED", "NEXT_TASK",
}


def fields(markdown: str) -> dict[str, str]:
    """Read only the queue/review header fields, never prose as status."""
    header = markdown.split("\n## ", 1)[0]
    return dict(FIELD_RE.findall(header))


def valid_sha(value: object) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def utc_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def handoff_for_head(comment: dict | None, head: str | None) -> bool:
    if not isinstance(comment, dict) or not valid_sha(head):
        return False
    body = comment.get("body")
    return (
        isinstance(body, str)
        and HANDOFF_RE.search(body) is not None
        and any(match.group(1) == head for match in HANDOFF_SHA_RE.finditer(body))
        and isinstance(comment.get("url"), str)
    )


def wave_for_task(task_id: str | None, waves: str) -> int | None:
    if not isinstance(task_id, str):
        return None
    match = re.fullmatch(r"W([0-4])-([0-9]{2})(?:[A-Z][0-9]*)?", task_id)
    if not match:
        return None
    wave = int(match.group(1))
    if f"# Wave {wave} " not in waves:
        return None
    if wave == 0 and f"## W0-{match.group(2)} " not in waves:
        return None
    return wave


def project(snapshot: dict, event: dict | None = None) -> dict:
    """Project current canonical inputs; uncertainty is UNKNOWN/null.

    Required snapshot keys: active, review, waves (text); active_commit_sha,
    review_commit_sha, waves_commit_sha; pr (GitHub metadata); handoff (comment).
    The supplied event is a verified transition, not an arbitrary webhook body.
    """
    active = fields(snapshot.get("active", ""))
    review = fields(snapshot.get("review", ""))
    pr = snapshot.get("pr") or {}
    if not isinstance(pr, dict):
        pr = {}
    task = active.get("Task-ID")
    task_id = task if task and task != "NONE" else None
    active_pr = PR_RE.fullmatch(active.get("PR-URL", ""))
    pr_number = int(active_pr.group(1)) if active_pr else None
    pr_matches = (
        pr_number is not None
        and pr.get("number") == pr_number
        and pr.get("url") == active.get("PR-URL")
        and pr.get("state") in {"OPEN", "CLOSED", "MERGED"}
    )
    head = pr.get("headRefOid") if pr_matches and valid_sha(pr.get("headRefOid")) else None
    active_head_matches = head is not None and active.get("PR-Head") == head
    review_matches = (
        active_head_matches
        and review.get("Task-ID") == task_id
        and review.get("Head-SHA") == head
        and review.get("PR") == active.get("PR-URL")
    )
    verdict = review.get("Verdict", "").split(" ", 1)[0] if review_matches else "UNKNOWN"
    if verdict not in {"PENDING", "PASS", "CHANGES_REQUESTED", "BLOCKED"}:
        verdict = "UNKNOWN"

    handoff = snapshot.get("handoff")
    exact_handoff = active_head_matches and handoff_for_head(handoff, head)
    dispatch = active.get("Dispatch-State", "UNKNOWN")
    if dispatch == "RUNNING":
        claude = "RUNNING_RECORDED"
    elif exact_handoff:
        # A HANDOFF is not evidence that the cloud session ended. Only the
        # explicit Codex-recorded session outcome can promote this state.
        ended = (
            "The Claude session completed" in snapshot.get("active", "")
            or (
                review_matches
                and "The Claude session ended with a final HANDOFF"
                in snapshot.get("review", "")
            )
        )
        claude = "ENDED_RECORDED" if ended else "HANDOFF_RECORDED"
    else:
        claude = "UNKNOWN"

    owner_sentence = None
    if verdict == "BLOCKED" and review_matches:
        for sentence in re.split(r"(?<=[.!?])\s+", snapshot.get("review", "")):
            sentence = sentence.strip()
            if (
                ("needs a newly authorized technical cycle" in sentence)
                or ("requires Krum" in sentence)
            ):
                owner_sentence = sentence
                break
    requires_krum = owner_sentence is not None
    if verdict == "BLOCKED":
        next_action = "WAIT_KRUM" if requires_krum else "UNKNOWN"
    elif verdict == "CHANGES_REQUESTED":
        next_action = "CLAUDE_CORRECTION"
    elif verdict == "PASS":
        # Predecessor evidence is outside this one-task projection.
        next_action = "UNKNOWN"
    elif exact_handoff and claude == "ENDED_RECORDED":
        next_action = "CODEX_REVIEW"
    elif dispatch == "RUNNING":
        next_action = "WAIT_CLAUDE"
    else:
        next_action = "UNKNOWN"

    event_kind = event.get("kind") if isinstance(event, dict) else None
    event_at = utc_timestamp(event.get("at")) if isinstance(event, dict) else None
    if event_kind not in EVENTS or event_at is None:
        event_kind, event_at = "UNKNOWN", None
    if event_kind == "CODEX_BLOCKED" and verdict != "BLOCKED":
        event_kind, event_at = "UNKNOWN", None
    if event_kind == "CODEX_PASS" and verdict != "PASS":
        event_kind, event_at = "UNKNOWN", None
    if event_kind == "CODEX_CHANGES_REQUESTED" and verdict != "CHANGES_REQUESTED":
        event_kind, event_at = "UNKNOWN", None
    if event_kind == "CLAUDE_HANDOFF" and not exact_handoff:
        event_kind, event_at = "UNKNOWN", None
    if event_kind == "PR_HEAD_CHANGED" and not head:
        event_kind, event_at = "UNKNOWN", None

    base_sha = active.get("Base-SHA")
    sources = {
        "active_commit_sha": snapshot.get("active_commit_sha")
        if valid_sha(snapshot.get("active_commit_sha")) else None,
        "review_commit_sha": snapshot.get("review_commit_sha")
        if review_matches and valid_sha(snapshot.get("review_commit_sha")) else None,
        "waves_commit_sha": snapshot.get("waves_commit_sha")
        if valid_sha(snapshot.get("waves_commit_sha")) else None,
        "handoff_comment_url": handoff.get("url") if exact_handoff else None,
    }
    return {
        "schema_version": 1,
        "wave": wave_for_task(task_id, snapshot.get("waves", "")),
        "task_id": task_id,
        "task_status": active.get("Status", "UNKNOWN"),
        "dispatch_state": dispatch,
        "claude_state": claude,
        "codex_review_state": verdict,
        "base_branch": active.get("Base-branch") or None,
        "base_sha": base_sha if valid_sha(base_sha) else None,
        "pr_number": pr_number if pr_matches else None,
        "pr_head_sha": head,
        "last_event": event_kind,
        "last_event_at": event_at,
        "next_action": next_action,
        "requires_krum": requires_krum,
        "requires_krum_reason": owner_sentence,
        "progress_percent": None,
        "source_versions": sources,
    }


def validate(document: dict, schema: dict | None = None) -> list[str]:
    """Validate the deliberately small JSON Schema subset used by v1.

    No package install or network access is required in the event runner.
    """
    if schema is None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    problems: list[str] = []

    def visit(value: object, rule: dict, path: str) -> None:
        expected = rule.get("type")
        types = [expected] if isinstance(expected, str) else expected
        if types:
            matches = {
                "object": lambda x: isinstance(x, dict),
                "array": lambda x: isinstance(x, list),
                "string": lambda x: isinstance(x, str),
                "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
                "boolean": lambda x: isinstance(x, bool),
                "null": lambda x: x is None,
            }
            if not any(matches[t](value) for t in types):
                problems.append(f"{path}: wrong type")
                return
        if "const" in rule and value != rule["const"]:
            problems.append(f"{path}: wrong const")
        if "enum" in rule and value not in rule["enum"]:
            problems.append(f"{path}: outside enum")
        if isinstance(value, dict):
            required = set(rule.get("required", []))
            properties = rule.get("properties", {})
            for missing in sorted(required - value.keys()):
                problems.append(f"{path}.{missing}: missing")
            if rule.get("additionalProperties") is False:
                for extra in sorted(value.keys() - properties.keys()):
                    problems.append(f"{path}.{extra}: unexpected")
            for key in value.keys() & properties.keys():
                visit(value[key], properties[key], f"{path}.{key}")
        if isinstance(value, str):
            if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
                problems.append(f"{path}: pattern mismatch")
            if rule.get("format") == "date-time" and utc_timestamp(value) is None:
                problems.append(f"{path}: invalid date-time")
            if rule.get("format") == "uri" and not urlparse(value).scheme:
                problems.append(f"{path}: invalid uri")
        if isinstance(value, int) and not isinstance(value, bool):
            if value < rule.get("minimum", value):
                problems.append(f"{path}: below minimum")
            if value > rule.get("maximum", value):
                problems.append(f"{path}: above maximum")

    visit(document, schema, "$")
    return problems


def canonical_json(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
