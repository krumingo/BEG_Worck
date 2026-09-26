"""W0-03C migration adapter for the task-independent control engine.

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
from control_engine import ControlError, validate_state, render_board, validate_board


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
    return json.loads(command("gh", "api", "repos/krumingo/BEG_Worck/issues/comments/5847481878",
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
    known = {5771922130: "2026-09-22T06:03:35Z", 5847481878: "2026-09-26T15:29:30Z"}
    comment_id = handoff.get("id")
    if (comment_id not in known or handoff.get("html_url") != PR_URL + f"#issuecomment-{comment_id}"
            or handoff.get("created_at") != known[comment_id]
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
                updated_at: str, previous_control_commit: str | None = None,
                validated_at: str | None = None) -> dict:
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
        "validated_at": validated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "validation_mode": "LIVE_GITHUB",
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
        "agent_states": {
            "GPT": {"state": "NOT_ACTIVE", "work_id": None, "waiting_for": None, "updated_at": updated_at},
            "CODEX": {"state": "BLOCKED", "work_id": "W0-03C/C02/CX",
                      "waiting_for": "Explicit technical correction cycle or design decision from Krum",
                      "updated_at": updated_at},
            "CLAUDE": {"state": "NOT_ACTIVE", "work_id": None, "waiting_for": None, "updated_at": updated_at},
        },
        "current_work_id": "W0-03C/C02/CX", "state": "BLOCKED", "pipeline_step": "REVIEW", "next_agent": "KRUM",
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


def validate_sources(state: dict, active_text: str, review_text: str, pr: dict,
                     handoff: dict, canonical: list[dict],
                     active_commit: str, active_blob: str, review_blob: str) -> None:
    validate_state(state)
    if state["validation_mode"] != "LIVE_GITHUB":
        raise ControlError("INVALID", "synthetic snapshot cannot pass live source validation")
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
