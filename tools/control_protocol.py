"""Read-only W0-03C control projection for Issue #25.

The queue files and exact PR head are evidence; this module never dispatches work,
changes ACTIVE/REVIEWS, merges, or creates a new cycle. The first migration is
intentionally pinned to W0-03C and fails closed for any other task.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "coordination/CONTROL_STATE.json"
BOARD_PATH = ROOT / "coordination/CONTROL_BOARD.md"
SCHEMA_PATH = ROOT / "coordination/CONTROL_STATE.schema.json"
ACTIVE_PATH = ROOT / "coordination/ACTIVE.md"
REVIEW_PATH = ROOT / "coordination/REVIEWS/W0-03C.md"
PR_URL = "https://github.com/krumingo/BEG_Worck/pull/20"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CANONICAL_PATHS = [
    "CLAUDE.md",
    "docs/architecture/IMPLEMENTATION_GATE_MATRIX.md",
    "docs/architecture/IMPLEMENTATION_WAVES.md",
    "docs/architecture/W0-03C_UNIQUENESS_READINESS.md",
    "docs/flows/FLOW-032.md",
]


class ControlError(ValueError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def command(*args: str) -> str:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise ControlError("INVALID", f"command failed: {args[0]} {args[1]}: {result.stderr.strip()}")
    return result.stdout.strip()


def source_commit(path: Path) -> str:
    return command("git", "log", "-1", "--format=%H", "--", str(path.relative_to(ROOT)))


def source_time(path: Path) -> str:
    raw = command("git", "log", "-1", "--format=%aI", "--", str(path.relative_to(ROOT)))
    return dt.datetime.fromisoformat(raw).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verify_remote_queue_sources(active_commit: str, active_blob: str, review_blob: str,
                                remote_active_commit: str, remote_active_blob: str,
                                remote_review_blob: str) -> None:
    if (active_commit != remote_active_commit or active_blob != remote_active_blob
            or review_blob != remote_review_blob):
        raise ControlError("STALE", "local ACTIVE/REVIEW does not match the live coordination branch")


def remote_queue_sources() -> tuple[str, str, str]:
    prefix = "repos/krumingo/BEG_Worck"
    branch = "codex/claude-queue"
    active_commit = command("gh", "api", f"{prefix}/commits?sha={branch}&path=coordination/ACTIVE.md&per_page=1",
                            "--jq", ".[0].sha")
    active_blob = command("gh", "api", f"{prefix}/contents/coordination/ACTIVE.md?ref={branch}", "--jq", ".sha")
    review_blob = command("gh", "api", f"{prefix}/contents/coordination/REVIEWS/W0-03C.md?ref={branch}",
                          "--jq", ".sha")
    return active_commit, active_blob, review_blob


def blob_sha(path: Path) -> str:
    return command("git", "hash-object", str(path.relative_to(ROOT)))


def pr_metadata() -> dict:
    return json.loads(command("gh", "pr", "view", "20", "--repo", "krumingo/BEG_Worck",
                              "--json", "number,url,headRefOid,isDraft,state"))


def handoff_metadata() -> dict:
    return json.loads(command("gh", "api", "repos/krumingo/BEG_Worck/issues/comments/5771922130",
                              "--jq", "{id,body,created_at,html_url}"))


def canonical_sources(head: str) -> list[dict]:
    if not SHA_RE.fullmatch(head):
        raise ControlError("INVALID", "canonical document ref is not an exact PR head")
    result = []
    for path in CANONICAL_PATHS:
        try:
            content = command("git", "show", f"{head}:{path}")
            sha = command("git", "rev-parse", f"{head}:{path}")
        except ControlError:
            # A queue-only clone need not contain PR #20's head object.
            item = json.loads(command("gh", "api", f"repos/krumingo/BEG_Worck/contents/{path}?ref={head}"))
            content = base64.b64decode(item["content"]).decode("utf-8")
            sha = item["sha"]
        if path == CANONICAL_PATHS[3] and "FLOW-032" not in content:
            raise ControlError("CONFLICT", "W0-03C readiness document no longer names FLOW-032")
        result.append({"path": path, "blob_sha": sha})
    return result


def checked_handoff(handoff: dict, head: str) -> str:
    body = handoff.get("body")
    if (handoff.get("id") != 5771922130 or handoff.get("html_url") != PR_URL + "#issuecomment-5771922130"
            or handoff.get("created_at") != "2026-09-22T06:03:35Z"
            or not isinstance(body, str) or "W0-03C" not in body or head not in body):
        raise ControlError("STALE", "final HANDOFF comment no longer matches W0-03C and exact PR head")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def fields(text: str) -> dict[str, str]:
    return dict(re.findall(r"^([A-Za-z][A-Za-z-]*):\s*(.*?)\s*$", text, re.MULTILINE))


def event(event_id: str, occurred_at: str, mapped_cycle: str, actor: str,
          kind: str, state_after: str | None, head_sha: str | None,
          source_url: str, source_commit_sha: str | None, summary: str) -> dict:
    return dict(event_id=event_id, occurred_at=occurred_at, task_id="W0-03C",
                cycle_id=None, mapped_cycle=mapped_cycle, actor=actor, kind=kind,
                state_after=state_after, head_sha=head_sha, source_url=source_url,
                source_commit_sha=source_commit_sha, summary=summary)


def migration_history() -> list[dict]:
    """Verbatim-source chronology; C01/C02 are mappings, not historical IDs."""
    c = "https://github.com/krumingo/BEG_Worck/pull/20#issuecomment-"
    q = "https://github.com/krumingo/BEG_Worck/commit/"
    return [
        event("pr20-comment-5764513929", "2026-09-21T17:13:38Z", "C01", "UNKNOWN", "HANDOFF", "HANDOFF",
              "25394418b118449db389066ec1c4ef0ae663ab20", c + "5764513929", None,
              "Initial Draft PR implementation HANDOFF; not an independent PASS."),
        event("pr20-comment-5765042461", "2026-09-21T17:54:07Z", "C01", "UNKNOWN", "HANDOFF", "HANDOFF",
              "be8cd207c94388e81b24173af6d690d69abcea00", c + "5765042461", None,
              "Pre-protocol repair HANDOFF after an earlier blocked review claim."),
        event("pr20-comment-5765269841", "2026-09-21T18:11:51Z", "C01", "UNKNOWN", "EVIDENCE", None,
              "be8cd207c94388e81b24173af6d690d69abcea00", c + "5765269841", None,
              "Real-Mongo test evidence for the earlier exact head; not proof for a later head."),
        event("pr20-comment-5771473368", "2026-09-22T05:04:44Z", "C01", "UNKNOWN", "EVIDENCE", None,
              "be8cd207c94388e81b24173af6d690d69abcea00", c + "5771473368", None,
              "NAS restore-copy report evidence for the earlier exact head/data snapshot."),
        event("review-ef006594", "2026-09-22T05:46:10Z", "C01", "CODEX", "REVIEW", "CHANGES_REQUESTED",
              "be8cd207c94388e81b24173af6d690d69abcea00",
              q + "ef00659423e899265a0c39657ebd0c97c1011e73",
              "ef00659423e899265a0c39657ebd0c97c1011e73",
              "Independent review requested three bounded corrections."),
        event("queue-2a86eefb", "2026-09-22T05:46:36Z", "C02", "CODEX", "ASSIGNMENT", "CHANGES_REQUESTED",
              "be8cd207c94388e81b24173af6d690d69abcea00",
              q + "2a86eefb1a38b200e0842d9b6b18f36e22f5905c",
              "2a86eefb1a38b200e0842d9b6b18f36e22f5905c",
              "One-of-one correction assignment on the existing PR branch."),
        event("queue-554109c4", "2026-09-22T05:50:41Z", "C02", "CODEX", "DISPATCH", None,
              "be8cd207c94388e81b24173af6d690d69abcea00",
              q + "554109c4332b13a5da90310d9674419f9a5eb1eb",
              "554109c4332b13a5da90310d9674419f9a5eb1eb",
              "Claude correction session recorded as RUNNING; not completion."),
        event("pr20-comment-5771922130", "2026-09-22T06:03:35Z", "C02", "CLAUDE", "HANDOFF", "HANDOFF",
              "ed588e9420e241f58c14146de6f0c890b38b3743", c + "5771922130", None,
              "Correction HANDOFF for exact Draft PR head; awaiting independent review."),
        event("review-3b991fae", "2026-09-22T06:16:16Z", "C02", "CODEX", "REVIEW", "BLOCKED",
              "ed588e9420e241f58c14146de6f0c890b38b3743",
              q + "3b991fae892f7a22fdeb3e9d0f0920aa71841f19",
              "3b991fae892f7a22fdeb3e9d0f0920aa71841f19",
              "Independent re-review found an untracked-index ambiguous-result defect; correction exhausted."),
        event("queue-4ddea223", "2026-09-22T06:17:02Z", "C02", "CODEX", "CONTROL_UPDATE", "BLOCKED",
              "ed588e9420e241f58c14146de6f0c890b38b3743",
              q + "4ddea223e7eccb29eb9f81e9c4eeca952b9bd5c1",
              "4ddea223e7eccb29eb9f81e9c4eeca952b9bd5c1",
              "ACTIVE and Dispatch-State blocked; no next task or C03 authorized."),
    ]


def build_state(active_text: str, review_text: str, pr: dict, handoff: dict, canonical: list[dict],
                active_commit: str, active_blob: str, review_blob: str,
                updated_at: str, previous_control_commit: str | None = None) -> dict:
    a, r = fields(active_text), fields(review_text)
    if a.get("Task-ID") != "W0-03C" or r.get("Task-ID") != "W0-03C":
        raise ControlError("INVALID", "this migration only supports W0-03C")
    if pr.get("number") != 20 or pr.get("url") != PR_URL or pr.get("state") != "OPEN" or pr.get("isDraft") is not True:
        raise ControlError("CONFLICT", "PR #20 must remain open and Draft")
    head = pr.get("headRefOid")
    if not isinstance(head, str) or not SHA_RE.fullmatch(head):
        raise ControlError("INVALID", "PR head is not an exact SHA")
    if a.get("PR-Head") != head:
        raise ControlError("CONFLICT", "ACTIVE PR-Head conflicts with live PR head")
    if r.get("Head-SHA") != head:
        raise ControlError("STALE", "review Head-SHA is stale for live PR head")
    if a.get("Status") != "BLOCKED" or a.get("Dispatch-State") != "BLOCKED" or not r.get("Verdict", "").startswith("BLOCKED"):
        raise ControlError("CONFLICT", "current ACTIVE/REVIEW blocker does not match approved migration")
    if a.get("Correction-cycle") != "1-of-1" or a.get("PR-URL") != PR_URL:
        raise ControlError("CONFLICT", "correction limit or PR URL changed")
    if a.get("Review") != "coordination/REVIEWS/W0-03C.md":
        raise ControlError("CONFLICT", "ACTIVE points to a different review")
    handoff_hash = checked_handoff(handoff, head)
    if [item.get("path") for item in canonical] != CANONICAL_PATHS:
        raise ControlError("CONFLICT", "canonical document set changed")
    for item in canonical:
        if not SHA_RE.fullmatch(item.get("blob_sha", "")):
            raise ControlError("INVALID", "canonical document blob is not an exact SHA")
    for name, value in (("active source commit", active_commit), ("ACTIVE blob", active_blob),
                        ("REVIEW blob", review_blob)):
        if not SHA_RE.fullmatch(value):
            raise ControlError("INVALID", f"invalid {name} SHA")
    state = {
        "protocol_version": 1,
        "control_state_status": "VALID",
        "repository": "krumingo/BEG_Worck",
        "branch": "codex/claude-queue",
        "producer": "CODEX",
        # Self-reference to this output commit is impossible. On first bootstrap this is null;
        # subsequent snapshots point to the *previously published* state commit.
        "active_source_commit_sha": active_commit,
        "control_state_commit_sha": previous_control_commit,
        "generated_from": ["ACTIVE", "REVIEW", "PR/HANDOFF", "CANONICAL_DOCS"],
        "task_id": "W0-03C", "cycle_id": "C02", "cycle_origin": "MIGRATED",
        "current_agent": "CODEX", "current_role": "TECH_LEAD_QA",
        "current_work_id": "W0-03C/C02/CX", "state": "BLOCKED", "next_agent": "KRUM",
        "waiting_for": "Explicit technical correction cycle or design decision from Krum",
        "wave": "W0", "flow": "FLOW-032", "pr_number": 20,
        "pr_head_sha": head, "pr_draft": True,
        "dispatch_state": "BLOCKED", "dispatch_run_url": a.get("Dispatch-Run"),
        "last_handoff": {"url": PR_URL + "#issuecomment-5771922130", "head_sha": head,
                         "at": "2026-09-22T06:03:35Z"},
        "last_review": {"path": "coordination/REVIEWS/W0-03C.md", "blob_sha": review_blob,
                        "reviewed_head_sha": head, "verdict": "BLOCKED"},
        "requires_krum": True,
        "requires_krum_reason": "Correction cycle 1-of-1 is exhausted; authorize a new technical cycle or decide ambiguous create_index handling.",
        "progress": {"mode": "STAGE_ONLY", "stage": "REVIEW", "completed": None,
                     "total": None, "percent": None},
        "source_refs": {"active_path": "coordination/ACTIVE.md", "active_blob_sha": active_blob,
                        "review_path": "coordination/REVIEWS/W0-03C.md", "review_blob_sha": review_blob,
                        "handoff_comment_sha256": handoff_hash, "canonical_docs": canonical},
        "updated_at": updated_at,
        "history": migration_history(),
    }
    validate_state(state)
    return state


def _check_schema(value, rule: dict, root: dict, location: str = "$state") -> None:
    if "$ref" in rule:
        name = rule["$ref"].removeprefix("#/$defs/")
        return _check_schema(value, root["$defs"][name], root, location)
    if "anyOf" in rule:
        if not any(_schema_ok(value, part, root) for part in rule["anyOf"]):
            raise ControlError("INVALID", f"{location}: no anyOf branch matches")
        return
    if "const" in rule and value != rule["const"]:
        raise ControlError("INVALID", f"{location}: expected {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        raise ControlError("INVALID", f"{location}: invalid enum value {value!r}")
    kinds = rule.get("type")
    if kinds:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        matches = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
                   "string": lambda x: isinstance(x, str), "integer": lambda x: type(x) is int,
                   "boolean": lambda x: type(x) is bool, "null": lambda x: x is None}
        if not any(matches[k](value) for k in kinds):
            raise ControlError("INVALID", f"{location}: wrong type")
    if isinstance(value, dict):
        missing = set(rule.get("required", [])) - set(value)
        if missing:
            raise ControlError("INVALID", f"{location}: missing {sorted(missing)}")
        properties = rule.get("properties", {})
        if rule.get("additionalProperties") is False and set(value) - set(properties):
            raise ControlError("INVALID", f"{location}: unknown fields {sorted(set(value)-set(properties))}")
        for key, child in value.items():
            if key in properties:
                _check_schema(child, properties[key], root, f"{location}.{key}")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", float("inf")):
            raise ControlError("INVALID", f"{location}: wrong item count")
        if rule.get("uniqueItems") and len(set(map(json.dumps, value))) != len(value):
            raise ControlError("INVALID", f"{location}: duplicate items")
        for index, child in enumerate(value):
            _check_schema(child, rule.get("items", {}), root, f"{location}[{index}]")
    if isinstance(value, str):
        if "pattern" in rule and not re.search(rule["pattern"], value):
            raise ControlError("INVALID", f"{location}: pattern mismatch")
        if len(value) < rule.get("minLength", 0):
            raise ControlError("INVALID", f"{location}: string too short")
        if rule.get("format") == "date-time":
            try:
                if dt.datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError("timezone missing")
            except ValueError as exc:
                raise ControlError("INVALID", f"{location}: invalid date-time") from exc
        if rule.get("format") == "uri" and not urlparse(value).scheme:
            raise ControlError("INVALID", f"{location}: invalid URI")
    if type(value) is int and (value < rule.get("minimum", -float("inf")) or
                               value > rule.get("maximum", float("inf"))):
        raise ControlError("INVALID", f"{location}: number outside range")


def _schema_ok(value, rule: dict, root: dict) -> bool:
    try:
        _check_schema(value, rule, root)
        return True
    except ControlError:
        return False


def validate_state(state: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _check_schema(state, schema, schema)
    if state["control_state_status"] != "VALID":
        raise ControlError(state["control_state_status"], "control state is not VALID; stop")
    suffix = {"GPT": "GPT", "CODEX": "CX", "CLAUDE": "CL"}.get(state["current_agent"])
    if not suffix or state["current_work_id"] != f"{state['task_id']}/{state['cycle_id']}/{suffix}":
        raise ControlError("INVALID", "Work-ID does not match Task/Cycle/current agent")
    role = {"GPT": "ARCHITECT", "CODEX": "TECH_LEAD_QA", "CLAUDE": "IMPLEMENTER"}
    if state["current_role"] != role[state["current_agent"]]:
        raise ControlError("INVALID", "agent/role mismatch")
    if state["requires_krum"] and not (state["requires_krum_reason"] or "").strip():
        raise ControlError("INVALID", "requires_krum has no reason")
    if state["state"] in {"WAITING", "BLOCKED"} and not (state["waiting_for"] or "").strip():
        raise ControlError("INVALID", "waiting/blocked state has no waiting_for")
    if state["state"] == "BLOCKED" and (state["next_agent"] != "KRUM" or not state["requires_krum"]):
        raise ControlError("INVALID", "blocked migration must wait for Krum")
    if state["pr_head_sha"] != state["last_review"]["reviewed_head_sha"]:
        raise ControlError("STALE", "review was not on the current PR head")
    if state["last_review"]["blob_sha"] != state["source_refs"]["review_blob_sha"]:
        raise ControlError("STALE", "review blob reference mismatch")
    if state["state"] in {"PASS", "CHANGES_REQUESTED", "BLOCKED"} and state["last_review"]["verdict"] != state["state"]:
        raise ControlError("CONFLICT", "state conflicts with independent review verdict")
    ids = [item["event_id"] for item in state["history"]]
    if len(ids) != len(set(ids)):
        raise ControlError("INVALID", "duplicate history event_id")
    for item in state["history"]:
        if item["task_id"] != state["task_id"]:
            raise ControlError("INVALID", "history Task-ID mismatch")
        if item["cycle_id"] is None and item["mapped_cycle"] is None:
            raise ControlError("INVALID", "legacy event needs mapped_cycle")
        if item["cycle_id"] is not None and item["mapped_cycle"] is not None:
            raise ControlError("INVALID", "native event cannot also have mapped_cycle")
        if item["cycle_id"] is not None and int(item["cycle_id"][1:]) > int(state["cycle_id"][1:]):
            raise ControlError("INVALID", "history invents a future cycle")
    if state["progress"]["mode"] == "STAGE_ONLY":
        if any(state["progress"][key] is not None for key in ("completed", "total", "percent")):
            raise ControlError("INVALID", "stage-only progress cannot claim numbers")
    elif state["progress"]["total"] is None or state["progress"]["completed"] is None or state["progress"]["percent"] is None:
        raise ControlError("INVALID", "evidence-count progress needs numerator, denominator, percent")
    elif state["progress"]["percent"] != 100 * state["progress"]["completed"] // state["progress"]["total"]:
        raise ControlError("INVALID", "progress percentage is not deterministic")


def validate_sources(state: dict, active_text: str, review_text: str, pr: dict,
                     handoff: dict, canonical: list[dict],
                     active_commit: str, active_blob: str, review_blob: str) -> None:
    validate_state(state)
    a, r = fields(active_text), fields(review_text)
    if state["active_source_commit_sha"] != active_commit or state["source_refs"]["active_blob_sha"] != active_blob:
        raise ControlError("STALE", "ACTIVE source commit/blob changed")
    if state["source_refs"]["review_blob_sha"] != review_blob:
        raise ControlError("STALE", "REVIEW blob changed")
    if state["source_refs"]["handoff_comment_sha256"] != checked_handoff(handoff, state["pr_head_sha"]):
        raise ControlError("STALE", "HANDOFF comment changed")
    if state["source_refs"]["canonical_docs"] != canonical:
        raise ControlError("STALE", "canonical document blob changed")
    if state["pr_head_sha"] != pr.get("headRefOid"):
        raise ControlError("STALE", "PR head moved after control-state generation")
    if a.get("PR-Head") != pr.get("headRefOid"):
        raise ControlError("CONFLICT", "ACTIVE PR-Head conflicts with live PR")
    if r.get("Head-SHA") != pr.get("headRefOid"):
        raise ControlError("STALE", "REVIEW head is stale")
    if a.get("Status") != state["state"] or not r.get("Verdict", "").startswith(state["state"]):
        raise ControlError("CONFLICT", "ACTIVE/REVIEW verdict changed")
    if pr.get("isDraft") is not state["pr_draft"] or pr.get("state") != "OPEN":
        raise ControlError("CONFLICT", "PR draft/open state changed")


def render_board(state: dict) -> str:
    validate_state(state)
    def cell(text: str | None) -> str:
        return (text or "—").replace("|", "\\|").replace("\n", " ")
    rows = [
        "# BEG_WORK control board", "",
        f"Source: `coordination/CONTROL_STATE.json` · branch: `{state['branch']}` · protocol v{state['protocol_version']}",
        f"ACTIVE source updated: {state['updated_at']} · CONTROL STATE: **{state['control_state_status']}**", "",
        f"CURRENT: {state['task_id']} / {state['cycle_id']} (migrated) / {state['current_agent']} / **{state['state']}**",
        f"NEXT: {state['next_agent']}",
        f"KRUM ACTION: {'REQUIRED — ' + state['requires_krum_reason'] if state['requires_krum'] else 'NONE'}",
        f"WAITING FOR: {state['waiting_for'] or '—'}", "",
        "## Required agent banner", "",
        "All three agents must read the control state before consequential work. If its status is STALE, CONFLICT or INVALID: **STOP**.", "",
        "```text", "BEG_WORK",
        f"TASK: {state['task_id']}", f"CYCLE: {state['cycle_id']}",
        "AGENT: GPT | CODEX | CLAUDE (select the actual sender)",
        "ROLE: ARCHITECT | TECH_LEAD_QA | IMPLEMENTER (match AGENT)",
        f"STATE: {state['state']}", f"NEXT: {state['next_agent']}",
        f"WAITING_FOR: {state['waiting_for'] or 'NONE'}", "```", "",
        "| Task | Cycle | ChatGPT | Codex | Claude | Current | Waiting for | Result |",
        "|---|---|---|---|---|---|---|---|",
        f"| {state['task_id']} | {state['cycle_id']} | — | BLOCKED | HANDOFF | Codex | {cell(state['waiting_for'])} | BLOCKED |", "",
        "GPT → Codex → Claude → **Codex (BLOCKED)** → GPT", "",
        "## Evidence", "",
        f"- ACTIVE: `{state['source_refs']['active_path']}` · source commit `{state['active_source_commit_sha']}` · blob `{state['source_refs']['active_blob_sha']}`",
        f"- Review: `{state['last_review']['path']}` · blob `{state['last_review']['blob_sha']}` · verdict **{state['last_review']['verdict']}** on `{state['last_review']['reviewed_head_sha']}`",
        f"- Draft PR: [#{state['pr_number']}]({PR_URL}) · exact head `{state['pr_head_sha']}` · HANDOFF [comment]({state['last_handoff']['url']})",
        f"- Dispatch session: {state['dispatch_run_url'] or '—'} · dispatch state **{state['dispatch_state']}**",
        f"- HANDOFF comment SHA-256: `{state['source_refs']['handoff_comment_sha256']}`",
        "- Canonical docs: " + ", ".join(f"`{item['path']}` @ `{item['blob_sha'][:8]}`" for item in state["source_refs"]["canonical_docs"]),
        f"- Wave/Flow: `{state['wave']}` / `{state['flow']}` · progress: **{state['progress']['stage']} / {state['progress']['mode']}** (no proven percentage)",
        "- `control_state_commit_sha` names the previous published state commit; `null` on first bootstrap. The GitHub commit containing this file cannot self-reference its own SHA.", "",
        "## Append-only history", "",
        "Legacy events have no original Cycle-ID; `mapped_cycle` is an explicit migration mapping, not a rewritten historical claim.", "",
        "| UTC | Original cycle | Mapped cycle | Event | Agent | State after | Exact head | Source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in state["history"]:
        short = item["head_sha"][:8] if item["head_sha"] else "—"
        rows.append(f"| {item['occurred_at']} | {item['cycle_id'] or '—'} | {item['mapped_cycle'] or '—'} | {item['kind']} | {item['actor']} | {item['state_after'] or '—'} | `{short}` | [evidence]({item['source_url']}) |")
    rows += ["", "**Gate:** W0-03C is BLOCKED. No C03, next implementation task, PASS, merge or deploy is authorized by this read-model.", ""]
    return "\n".join(rows)


def validate_board(state: dict, board: str) -> None:
    if board != render_board(state):
        raise ControlError("CONFLICT", "BOARD is not exactly generated from STATE")


def read_inputs() -> tuple[str, str, dict, dict, list[dict], str, str, str]:
    pr = pr_metadata()
    active_commit = source_commit(ACTIVE_PATH)
    active_blob = blob_sha(ACTIVE_PATH)
    review_blob = blob_sha(REVIEW_PATH)
    verify_remote_queue_sources(active_commit, active_blob, review_blob, *remote_queue_sources())
    return (ACTIVE_PATH.read_text(encoding="utf-8"), REVIEW_PATH.read_text(encoding="utf-8"),
            pr, handoff_metadata(), canonical_sources(pr["headRefOid"]), active_commit,
            active_blob, review_blob)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["generate", "validate", "render"])
    args = parser.parse_args()
    try:
        if args.mode == "generate":
            active, review, pr, handoff, canonical, active_commit, active_blob, review_blob = read_inputs()
            previous = source_commit(STATE_PATH) or None
            state = build_state(active, review, pr, handoff, canonical, active_commit, active_blob, review_blob,
                                source_time(ACTIVE_PATH), previous)
            board = render_board(state)
            STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            BOARD_PATH.write_text(board, encoding="utf-8", newline="\n")
            print("VALID: generated CONTROL_STATE and CONTROL_BOARD from verified sources")
        else:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if args.mode == "render":
                print(render_board(state), end="")
            else:
                active, review, pr, handoff, canonical, active_commit, active_blob, review_blob = read_inputs()
                validate_sources(state, active, review, pr, handoff, canonical,
                                 active_commit, active_blob, review_blob)
                validate_board(state, BOARD_PATH.read_text(encoding="utf-8"))
                print("VALID: sources, exact PR head, state and board agree")
        return 0
    except (ControlError, OSError, json.JSONDecodeError) as exc:
        status = exc.status if isinstance(exc, ControlError) else "INVALID"
        print(f"{status}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
