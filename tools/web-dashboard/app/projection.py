"""The browser-facing view model.

Everything the UI can display passes through here, which makes this the single place
where the safety rules are enforced rather than hoped for:

* **The token never appears.** Only ``Settings.redacted()`` is emitted, which reports
  whether a credential is configured and never what it is. Nothing in this module can
  reach the token, because nothing in this module is given it.
* **An unverified state is never promoted.** ``state.verified`` is true only when this
  round's verdict is VALID. The UI renders an unverified state with an explicit
  UNVERIFIED qualifier, so a stored ``PASS`` that failed verification reads as
  "PASS (UNVERIFIED)" and never as a pass.
* **No percentage is invented, and none survives an unverified round.**
  ``progress.percent`` is emitted only when this round verified *and* the mode is
  ``EVIDENCE_COUNT``. Under ``STAGE_ONLY`` it stays null. On any INVALID, STALE, CONFLICT
  or otherwise unverified round the counts and the percentage are withheld even when the
  file carries them, because an unverified number is not evidence of anything -- a state
  claiming ``3 of 8, 90%`` fails ``PROGRESS_NOT_DETERMINISTIC``, and forwarding 90 would
  put an arithmetically impossible figure and a 90%-full bar on the wall. The stage is
  kept, labelled unverified, and ``withheld_reason`` says in words why no number is
  shown.
* **Agent cards come from ``agent_states``, never from history.** History is evidence
  about what happened; it is not a status source. Deriving a card from the newest event
  would show CLAUDE as HANDOFF when its card says NOT_ACTIVE.
"""

from __future__ import annotations

import datetime as dt

from .redact import redact
from .refresh import DashboardState
from .status import Link, Status

AGENT_ORDER = ("GPT", "CODEX", "CLAUDE")
AGENT_DISPLAY = {"GPT": "ChatGPT", "CODEX": "Codex", "CLAUDE": "Claude"}
AGENT_ROLE = {"GPT": "Architect", "CODEX": "Tech Lead / QA", "CLAUDE": "Implementer"}

# The canonical route, as CONTROL_BOARD.md renders it:
# ChatGPT -> Codex -> Claude -> Codex -> ChatGPT
PIPELINE = (
    ("ARCHITECT", "ChatGPT", "GPT"),
    ("ASSIGNMENT", "Codex", "CODEX"),
    ("IMPLEMENTATION", "Claude", "CLAUDE"),
    ("REVIEW", "Codex", "CODEX"),
    ("ARCHITECT_FEEDBACK", "ChatGPT", "GPT"),
)


def _iso(moment: dt.datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def project(state: DashboardState) -> dict:
    """Build the complete, already-sanitised payload served at ``/api/state``."""
    verified_snapshot = state.verified
    verdict = verified_snapshot.verdict if verified_snapshot else None
    control = verified_snapshot.state if verified_snapshot else None

    # "Verified" means this round's own verification passed, not that the producer
    # wrote VALID into the file.
    is_verified = verdict is not None and verdict.status is Status.VALID and not state.is_aged

    payload: dict = {
        "generated_at": _iso(state.now),
        "available": control is not None,
        "verified": is_verified,
        "control_state_status": verdict.status.label if verdict is not None else None,
        "link": Link(state.link).value,
        "aged": state.is_aged,
        "age_seconds": state.age_seconds,
        "last_verified_at": _iso(state.last_success_at),
        "last_attempt_at": _iso(state.last_attempt_at),
        "last_error": state.last_error,
        "consecutive_failures": state.consecutive_failures,
        "next_attempt_in": round(state.next_attempt_in, 1),
        "refresh_seconds": state.settings.refresh_seconds,
        "stale_after_seconds": state.settings.stale_after_seconds,
        "rounds": state.rounds,
        "findings": verdict.as_dicts() if verdict is not None else [],
        "config": state.settings.redacted(),
        # Redacted with the exact configured token as well as by shape: a note quotes
        # transport error text, and this list is served to the browser.
        "notes": [redact(note, state.settings.token) for note in verified_snapshot.snapshot.notes]
        if verified_snapshot is not None
        else [],
    }

    if control is None:
        payload["header"] = _unavailable_header(state)
        payload["agents"] = [_unavailable_agent(name) for name in AGENT_ORDER]
        payload["pipeline"] = [
            {"step": step, "agent": label, "agent_key": key, "active": False}
            for step, label, key in PIPELINE
        ]
        payload["task"] = None
        payload["evidence"] = None
        payload["history"] = []
        payload["gate"] = (
            "CONTROL STATE NOT AVAILABLE. This dashboard has no verified snapshot to "
            "project and grants no progression, PASS, merge or deploy."
        )
        return payload

    payload["header"] = _header(control, state, is_verified)
    payload["agents"] = [_agent(control, name) for name in AGENT_ORDER]
    payload["pipeline"] = _pipeline(control, is_verified)
    payload["task"] = _task(control)
    payload["evidence"] = _evidence(control, verified_snapshot)
    payload["history"] = _history(control)
    payload["gate"] = _gate(control)
    return payload


def _unavailable_header(state: DashboardState) -> dict:
    return {
        "product": "BEG_WORK",
        "task_id": None,
        "cycle_id": None,
        "cycle_label": None,
        "wave": None,
        "flow": None,
        "state": None,
        "state_verified": False,
        "state_display": "CONTROL STATE NOT AVAILABLE",
        "progress": {
            "mode": None,
            "stage": None,
            "stage_verified": False,
            "completed": None,
            "total": None,
            "percent": None,
            "numbers_withheld": True,
            "withheld_reason": "No snapshot has been read, so there is no progress to report.",
        },
        "krum_action": {"required": False, "reason": None},
        "repository": state.settings.repository,
        "branch": state.settings.branch,
        "protocol_version": None,
        "validated_at": None,
        "updated_at": None,
        "validation_mode": None,
    }


def _unavailable_agent(name: str) -> dict:
    return {
        "key": name,
        "name": AGENT_DISPLAY[name],
        "role": AGENT_ROLE[name],
        "state": "UNKNOWN",
        "work_id": None,
        "waiting_for": None,
        "updated_at": None,
        "is_current": False,
    }


def _header(control: dict, state: DashboardState, is_verified: bool) -> dict:
    raw_state = control.get("state")
    progress = control.get("progress") if isinstance(control.get("progress"), dict) else {}
    mode = progress.get("mode")

    # Under STAGE_ONLY the numbers stay null even if the file carried them: the
    # invariant pass has already flagged that as INVALID, and echoing a number the
    # protocol forbids would be inventing progress.
    stage_only = mode == "STAGE_ONLY"
    requires_krum = control.get("requires_krum") is True

    # Numbers are shown only when this round verified AND the protocol proves a
    # proportion. Either condition failing withholds them; the stage still shows.
    show_numbers = is_verified and mode == "EVIDENCE_COUNT"
    if stage_only:
        withheld_reason = (
            "STAGE_ONLY: the protocol proves a stage, not a proportion. "
            "No percentage is shown because none is proven."
        )
    elif not is_verified:
        withheld_reason = (
            "This round did not verify, so any count in the file is unconfirmed. "
            "No numbers or bar are shown; the stage below is UNVERIFIED."
        )
    elif mode != "EVIDENCE_COUNT":
        withheld_reason = f"Unknown progress mode {mode!r}: no number is shown."
    else:
        withheld_reason = None

    return {
        "product": "BEG_WORK",
        "task_id": control.get("task_id"),
        "cycle_id": control.get("cycle_id"),
        "cycle_label": _cycle_label(control),
        "wave": control.get("wave"),
        "flow": control.get("flow"),
        "state": raw_state,
        "state_verified": is_verified,
        # The single string the UI shows large. An unverified round is labelled so.
        "state_display": raw_state if is_verified else f"{raw_state} (UNVERIFIED)",
        "progress": {
            "mode": mode,
            "stage": progress.get("stage"),
            "stage_verified": is_verified,
            "completed": progress.get("completed") if show_numbers else None,
            "total": progress.get("total") if show_numbers else None,
            "percent": progress.get("percent") if show_numbers else None,
            "numbers_withheld": not show_numbers,
            "withheld_reason": withheld_reason,
        },
        "krum_action": {
            "required": requires_krum,
            "reason": control.get("requires_krum_reason") if requires_krum else None,
        },
        "repository": control.get("repository"),
        "branch": control.get("branch"),
        "protocol_version": control.get("protocol_version"),
        "validated_at": control.get("validated_at"),
        "updated_at": control.get("updated_at"),
        "validation_mode": control.get("validation_mode"),
    }


def _cycle_label(control: dict) -> str | None:
    cycle = control.get("cycle_id")
    if not cycle:
        return None
    return f"{cycle} (migrated)" if control.get("cycle_origin") == "MIGRATED" else str(cycle)


def _agent(control: dict, name: str) -> dict:
    cards = control.get("agent_states") if isinstance(control.get("agent_states"), dict) else {}
    card = cards.get(name) if isinstance(cards.get(name), dict) else {}
    return {
        "key": name,
        "name": AGENT_DISPLAY[name],
        "role": AGENT_ROLE[name],
        "state": card.get("state") or "UNKNOWN",
        "work_id": card.get("work_id"),
        "waiting_for": card.get("waiting_for"),
        "updated_at": card.get("updated_at"),
        "is_current": control.get("current_agent") == name,
    }


def _pipeline(control: dict, is_verified: bool) -> list[dict]:
    active_step = control.get("pipeline_step")
    raw_state = control.get("state")
    steps = []
    for step, label, key in PIPELINE:
        active = step == active_step
        steps.append(
            {
                "step": step,
                "agent": label,
                "agent_key": key,
                "active": active,
                # The active step carries the state, with the same UNVERIFIED discipline
                # as the header so the pipeline cannot read as a pass either.
                "badge": (raw_state if is_verified else f"{raw_state} (UNVERIFIED)") if active else None,
            }
        )
    return steps


def _task(control: dict) -> dict:
    return {
        "task_id": control.get("task_id"),
        "cycle_label": _cycle_label(control),
        "current_agent": control.get("current_agent"),
        "current_agent_name": AGENT_DISPLAY.get(str(control.get("current_agent")), control.get("current_agent")),
        "current_role": control.get("current_role"),
        "current_work_id": control.get("current_work_id"),
        "next_agent": control.get("next_agent"),
        "next_agent_name": AGENT_DISPLAY.get(str(control.get("next_agent")), control.get("next_agent")),
        "waiting_for": control.get("waiting_for"),
        "pipeline_step": control.get("pipeline_step"),
        "dispatch_state": control.get("dispatch_state"),
        "dispatch_run_url": control.get("dispatch_run_url"),
    }


def _evidence(control: dict, verified_snapshot) -> dict:
    repository = control.get("repository") or ""
    refs = control.get("source_refs") if isinstance(control.get("source_refs"), dict) else {}
    number = control.get("pr_number")
    review = control.get("last_review") if isinstance(control.get("last_review"), dict) else None
    handoff = control.get("last_handoff") if isinstance(control.get("last_handoff"), dict) else None
    branch = control.get("branch") or ""
    snapshot = verified_snapshot.snapshot if verified_snapshot else None
    observed_pr = snapshot.pull_request if snapshot else None

    def blob_url(path: object) -> str | None:
        if not isinstance(path, str) or not path or not repository or not branch:
            return None
        return f"https://github.com/{repository}/blob/{branch}/{path}"

    return {
        "repository": repository,
        "branch": branch,
        "active": {
            "path": refs.get("active_path"),
            "blob_sha": refs.get("active_blob_sha"),
            "observed_blob_sha": snapshot.active.blob_sha if snapshot and snapshot.active else None,
            "source_commit_sha": control.get("active_source_commit_sha"),
            "url": blob_url(refs.get("active_path")),
        },
        "review": {
            "path": review.get("path") if review else refs.get("review_path"),
            "blob_sha": review.get("blob_sha") if review else refs.get("review_blob_sha"),
            "observed_blob_sha": snapshot.review.blob_sha if snapshot and snapshot.review else None,
            "verdict": review.get("verdict") if review else None,
            "reviewed_head_sha": review.get("reviewed_head_sha") if review else None,
            "url": blob_url(review.get("path") if review else refs.get("review_path")),
        }
        if review or refs.get("review_path")
        else None,
        "pull_request": {
            "number": number,
            "draft": control.get("pr_draft"),
            "cited_head_sha": control.get("pr_head_sha"),
            "observed_head_sha": observed_pr.head_sha if observed_pr else None,
            "observed_draft": observed_pr.draft if observed_pr else None,
            "url": f"https://github.com/{repository}/pull/{number}" if number and repository else None,
        }
        if number
        else None,
        "handoff": {
            "url": handoff.get("url"),
            "head_sha": handoff.get("head_sha"),
            "at": handoff.get("at"),
        }
        if handoff
        else None,
        "handoff_comment_sha256": refs.get("handoff_comment_sha256"),
        "canonical_docs": [
            {"path": item.get("path"), "blob_sha": item.get("blob_sha"), "url": blob_url(item.get("path"))}
            for item in (refs.get("canonical_docs") or [])
            if isinstance(item, dict)
        ],
        "control_state_commit_sha": control.get("control_state_commit_sha"),
        "control_state_note": (
            "control_state_commit_sha names the previous published state commit; "
            "it cannot self-reference this file's own Git commit."
        ),
    }


def _history(control: dict) -> list[dict]:
    history = control.get("history")
    if not isinstance(history, list):
        return []
    rows = []
    for item in history:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "event_id": item.get("event_id"),
                "occurred_at": item.get("occurred_at"),
                "cycle_id": item.get("cycle_id"),
                "mapped_cycle": item.get("mapped_cycle"),
                "kind": item.get("kind"),
                "actor": item.get("actor"),
                "actor_name": AGENT_DISPLAY.get(str(item.get("actor")), item.get("actor")),
                "state_after": item.get("state_after"),
                "head_sha": item.get("head_sha"),
                "source_url": item.get("source_url"),
                "summary": item.get("summary"),
            }
        )
    # Newest first: an operator reads the latest event, not the oldest.
    rows.sort(key=lambda row: str(row.get("occurred_at") or ""), reverse=True)
    return rows


def _gate(control: dict) -> str:
    task = control.get("task_id")
    state = control.get("state")
    if state == "BLOCKED":
        return f"{task} is BLOCKED. No new cycle, PASS, merge or deploy is authorized by this read-model."
    return (
        f"{task} is {state}. Progression requires independent evidence and the relevant "
        "owner approval; this board grants none."
    )
