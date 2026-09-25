"""Protocol invariants for a control snapshot.

This is an adaptation of ``tools/control_engine.py:validate_state`` -- the producer's
own invariant set -- with the same rules and the same severities, but collecting all
violations instead of raising on the first, and tolerating a partly malformed
document (the schema pass has already reported the structural damage; the invariant
pass should not crash on it).

Each check below carries the severity the canonical engine assigns it. Where the
engine raises ``ControlError("STALE", ...)`` this module emits a STALE finding, and so
on, so the two cannot disagree about how serious something is.
``tests/test_canonical_engine.py`` pins that agreement.
"""

from __future__ import annotations

from .schema import parse_timestamp
from .status import Finding, Status, Verdict

AGENTS = ("GPT", "CODEX", "CLAUDE")
WORK_ID_SUFFIX = {"GPT": "GPT", "CODEX": "CX", "CLAUDE": "CL"}
AGENT_ROLE = {"GPT": "ARCHITECT", "CODEX": "TECH_LEAD_QA", "CLAUDE": "IMPLEMENTER"}
STEP_AGENT = {
    "ARCHITECT": "GPT",
    "ASSIGNMENT": "CODEX",
    "IMPLEMENTATION": "CLAUDE",
    "REVIEW": "CODEX",
    "ARCHITECT_FEEDBACK": "GPT",
}
BUSY_STATES = {"WORKING", "REVIEW"}
VERDICT_STATES = {"PASS", "CHANGES_REQUESTED", "BLOCKED"}


def validate(state: object) -> Verdict:
    findings: list[Finding] = []
    if not isinstance(state, dict):
        return Verdict([Finding(Status.INVALID, "STATE_UNUSABLE", "Control state is not an object.")])

    _claimed_status(state, findings)
    _timeline(state, findings)
    _identity(state, findings)
    _agents(state, findings)
    _krum(state, findings)
    _evidence(state, findings)
    _history(state, findings)
    _progress(state, findings)
    return Verdict(findings)


def _add(findings: list[Finding], status: Status, code: str, message: str) -> None:
    findings.append(Finding(status, code, message))


def _text(state: dict, key: str) -> str:
    value = state.get(key)
    return value if isinstance(value, str) else ""


def _claimed_status(state: dict, findings: list[Finding]) -> None:
    """The producer's own status field, folded in as a claim of that severity."""
    claimed = _text(state, "control_state_status")
    if claimed and claimed != "VALID":
        _add(
            findings,
            Status.parse(claimed),
            "PRODUCER_STATUS_NOT_VALID",
            f"The producer published control_state_status {claimed}; stop and recheck the sources.",
        )
    if _text(state, "validation_mode") == "SYNTHETIC_TEST":
        # A synthetic snapshot is a well-formed test artefact. It is not evidence about
        # the real pipeline, so it must never render as a verified live state.
        _add(
            findings,
            Status.CONFLICT,
            "SYNTHETIC_SNAPSHOT",
            "validation_mode is SYNTHETIC_TEST: this snapshot is a test artefact, not live verification.",
        )


def _timeline(state: dict, findings: list[Finding]) -> None:
    validated = parse_timestamp(state.get("validated_at"))
    updated = parse_timestamp(state.get("updated_at"))
    if validated and updated and validated < updated:
        _add(
            findings,
            Status.INVALID,
            "VALIDATION_PREDATES_SOURCE",
            "validated_at is earlier than updated_at: the validation predates the source it claims to cover.",
        )


def _identity(state: dict, findings: list[Finding]) -> None:
    agent = _text(state, "current_agent")
    task = _text(state, "task_id")
    cycle = _text(state, "cycle_id")

    if agent in WORK_ID_SUFFIX and task and cycle:
        expected = f"{task}/{cycle}/{WORK_ID_SUFFIX[agent]}"
        if _text(state, "current_work_id") != expected:
            _add(
                findings,
                Status.INVALID,
                "WORK_ID_MISMATCH",
                f"current_work_id is {_text(state, 'current_work_id')!r} but Task/Cycle/agent compose to {expected!r}.",
            )
    if agent in AGENT_ROLE and _text(state, "current_role") != AGENT_ROLE[agent]:
        _add(
            findings,
            Status.INVALID,
            "AGENT_ROLE_MISMATCH",
            f"current_agent {agent} must hold role {AGENT_ROLE[agent]}, not {_text(state, 'current_role')!r}.",
        )

    step = _text(state, "pipeline_step")
    if step and step not in STEP_AGENT:
        _add(findings, Status.INVALID, "PIPELINE_STEP_UNKNOWN", f"Unknown pipeline_step {step!r}.")
    elif step and agent and agent != STEP_AGENT[step]:
        _add(
            findings,
            Status.INVALID,
            "PIPELINE_AGENT_MISMATCH",
            f"pipeline_step {step} belongs to {STEP_AGENT[step]}, but current_agent is {agent}.",
        )


def _agents(state: dict, findings: list[Finding]) -> None:
    agents = state.get("agent_states")
    if not isinstance(agents, dict):
        return
    current_name = _text(state, "current_agent")
    snapshot_state = _text(state, "state")
    validated = parse_timestamp(state.get("validated_at"))
    task = _text(state, "task_id")
    cycle = _text(state, "cycle_id")

    current = agents.get(current_name)
    if isinstance(current, dict):
        if (
            current.get("state") != snapshot_state
            or current.get("work_id") != state.get("current_work_id")
            or current.get("waiting_for") != state.get("waiting_for")
        ):
            _add(
                findings,
                Status.CONFLICT,
                "CURRENT_AGENT_CARD_CONFLICT",
                f"The {current_name} card disagrees with the snapshot's own state/work_id/waiting_for.",
            )

    busy = [name for name in AGENTS
            if isinstance(agents.get(name), dict) and agents[name].get("state") in BUSY_STATES]
    expected_busy = [current_name] if snapshot_state in BUSY_STATES and current_name else []
    if busy != expected_busy:
        _add(
            findings,
            Status.INVALID,
            "BUSY_AGENT_OWNERSHIP",
            f"WORKING/REVIEW must belong only to the current pipeline agent; observed {busy or 'none'}, expected {expected_busy or 'none'}.",
        )

    for name in AGENTS:
        card = agents.get(name)
        if not isinstance(card, dict):
            continue
        card_state = card.get("state")
        observed = parse_timestamp(card.get("updated_at"))
        if validated and observed and observed > validated:
            _add(
                findings,
                Status.INVALID,
                "AGENT_UPDATED_AFTER_VALIDATION",
                f"{name} card is stamped after validated_at, so it was never validated.",
            )
        if card_state == "NOT_ACTIVE" and (
            card.get("work_id") is not None or card.get("waiting_for") is not None
        ):
            _add(
                findings,
                Status.INVALID,
                "NOT_ACTIVE_NOT_EMPTY",
                f"{name} is NOT_ACTIVE but still carries a work_id or waiting_for.",
            )
        if card_state == "WAITING" and not str(card.get("waiting_for") or "").strip():
            _add(
                findings,
                Status.INVALID,
                "WAITING_WITHOUT_REASON",
                f"{name} is WAITING with no explicit waiting_for.",
            )
        work_id = card.get("work_id")
        if work_id is not None and task and cycle:
            expected = f"{task}/{cycle}/{WORK_ID_SUFFIX[name]}"
            if work_id != expected:
                _add(
                    findings,
                    Status.INVALID,
                    "AGENT_WORK_ID_MISMATCH",
                    f"{name} work_id {work_id!r} does not match the current task/cycle ({expected!r}).",
                )


def _krum(state: dict, findings: list[Finding]) -> None:
    requires = state.get("requires_krum")
    reason = str(state.get("requires_krum_reason") or "").strip()
    if requires is True and not reason:
        _add(findings, Status.INVALID, "KRUM_WITHOUT_REASON", "requires_krum is set with no reason given.")
    if _text(state, "state") in {"WAITING", "BLOCKED"} and not str(state.get("waiting_for") or "").strip():
        _add(
            findings,
            Status.INVALID,
            "BLOCKED_WITHOUT_REASON",
            f"State {_text(state, 'state')} carries no waiting_for.",
        )
    if _text(state, "next_agent") == "KRUM" and requires is not True:
        _add(
            findings,
            Status.INVALID,
            "KRUM_NEXT_WITHOUT_FLAG",
            "next_agent is KRUM but requires_krum is not set, so no reason is recorded.",
        )


def _evidence(state: dict, findings: list[Finding]) -> None:
    pr_number = state.get("pr_number")
    head = state.get("pr_head_sha")
    review = state.get("last_review")
    handoff = state.get("last_handoff")

    if pr_number is None:
        if head is not None or state.get("pr_draft") is not None or handoff is not None or review is not None:
            _add(
                findings,
                Status.INVALID,
                "PR_EVIDENCE_INCOMPLETE",
                "PR evidence is present without a pr_number.",
            )
    elif head is None or state.get("pr_draft") is None:
        _add(
            findings,
            Status.INVALID,
            "PR_EVIDENCE_INCOMPLETE",
            f"PR #{pr_number} is cited without an exact head SHA and draft status.",
        )

    refs = state.get("source_refs") if isinstance(state.get("source_refs"), dict) else {}
    snapshot_state = _text(state, "state")

    if isinstance(review, dict):
        if head != review.get("reviewed_head_sha"):
            _add(
                findings,
                Status.STALE,
                "REVIEW_NOT_ON_HEAD",
                "The cited review was not performed on the current PR head.",
            )
        if review.get("blob_sha") != refs.get("review_blob_sha"):
            _add(
                findings,
                Status.STALE,
                "REVIEW_BLOB_MISMATCH",
                "last_review.blob_sha and source_refs.review_blob_sha cite different review bytes.",
            )
        if snapshot_state in VERDICT_STATES and review.get("verdict") != snapshot_state:
            _add(
                findings,
                Status.CONFLICT,
                "STATE_REVIEW_CONFLICT",
                f"State is {snapshot_state} but the independent review verdict is {review.get('verdict')!r}.",
            )
    elif snapshot_state in {"PASS", "CHANGES_REQUESTED"}:
        _add(
            findings,
            Status.INVALID,
            "VERDICT_WITHOUT_REVIEW",
            f"State {snapshot_state} asserts a review verdict with no exact review evidence.",
        )

    if isinstance(handoff, dict) and handoff.get("head_sha") != head:
        _add(
            findings,
            Status.STALE,
            "HANDOFF_NOT_ON_HEAD",
            "The cited HANDOFF is not on the current PR head.",
        )


def _history(state: dict, findings: list[Finding]) -> None:
    history = state.get("history")
    if not isinstance(history, list):
        return
    task = _text(state, "task_id")
    cycle = _text(state, "cycle_id")
    current_cycle = _cycle_number(cycle)

    identifiers = [item.get("event_id") for item in history if isinstance(item, dict)]
    if len(identifiers) != len(set(identifiers)):
        _add(findings, Status.INVALID, "HISTORY_DUPLICATE_EVENT", "history contains a duplicate event_id.")

    for index, item in enumerate(history):
        if not isinstance(item, dict):
            continue
        where = f"history[{index}]"
        if task and item.get("task_id") != task:
            _add(
                findings,
                Status.INVALID,
                "HISTORY_TASK_MISMATCH",
                f"{where} belongs to task {item.get('task_id')!r}, not {task!r}.",
            )
        native = item.get("cycle_id")
        mapped = item.get("mapped_cycle")
        if (native is None) == (mapped is None):
            _add(
                findings,
                Status.INVALID,
                "HISTORY_CYCLE_AMBIGUOUS",
                f"{where} must carry exactly one of cycle_id or mapped_cycle.",
            )
        observed = _cycle_number(native or mapped or "")
        if observed is not None and current_cycle is not None and observed > current_cycle:
            _add(
                findings,
                Status.INVALID,
                "HISTORY_FUTURE_CYCLE",
                f"{where} cites cycle {native or mapped} which is later than the current {cycle}.",
            )


def _cycle_number(cycle: str) -> int | None:
    if not isinstance(cycle, str) or len(cycle) < 2 or not cycle[1:].isdigit():
        return None
    return int(cycle[1:])


def _progress(state: dict, findings: list[Finding]) -> None:
    progress = state.get("progress")
    if not isinstance(progress, dict):
        return
    mode = progress.get("mode")
    completed = progress.get("completed")
    total = progress.get("total")
    percent = progress.get("percent")

    if mode == "STAGE_ONLY":
        claimed = [key for key in ("completed", "total", "percent") if progress.get(key) is not None]
        if claimed:
            _add(
                findings,
                Status.INVALID,
                "STAGE_ONLY_CLAIMS_NUMBERS",
                f"STAGE_ONLY progress must claim no numbers, but sets {sorted(claimed)}.",
            )
        return

    if mode != "EVIDENCE_COUNT":
        return

    if total is None or completed is None or percent is None:
        _add(
            findings,
            Status.INVALID,
            "EVIDENCE_COUNT_INCOMPLETE",
            "EVIDENCE_COUNT progress needs a numerator, a denominator and a percentage.",
        )
        return
    if type(completed) is not int or type(total) is not int or type(percent) is not int:
        return
    if completed > total:
        _add(
            findings,
            Status.INVALID,
            "PROGRESS_OVER_TOTAL",
            f"progress claims {completed} of {total} completed.",
        )
    elif total > 0 and percent != 100 * completed // total:
        _add(
            findings,
            Status.INVALID,
            "PROGRESS_NOT_DETERMINISTIC",
            f"progress percent {percent} is not 100*{completed}//{total} = {100 * completed // total}.",
        )
