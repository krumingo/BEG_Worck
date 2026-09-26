"""CONTROL_BOARD.md cross-check.

``CONTROL_BOARD.md`` is the human-readable rendering of ``CONTROL_STATE.json``. The
canonical producer asserts an exact relationship between them
(``tools/control_engine.py:validate_board``): the board must be byte-identical to
``render_board(state)``. Anything else is a CONFLICT.

So this module carries a port of ``render_board`` and performs the same exact
comparison. PR #28 compared only the banner fields, which its review recorded as a
known gap: a board could drift in its history table or evidence list and still pass.
A full re-render closes that, and it is cheap here because the canonical renderer is
already Python -- ``tests/test_canonical_engine.py`` asserts this port is
byte-identical to it, so the port cannot drift.

The direction of the check matters: the board may only ever *demote* the status. It
can never promote a value. A board claiming PASS over a state of BLOCKED yields
CONFLICT and the state still reads BLOCKED.
"""

from __future__ import annotations

import difflib

from .status import Finding, Status, Verdict

_ROUTE = [
    ("ARCHITECT", "GPT"),
    ("ASSIGNMENT", "Codex"),
    ("IMPLEMENTATION", "Claude"),
    ("REVIEW", "Codex"),
    ("ARCHITECT_FEEDBACK", "GPT"),
]


def _cell(value: object) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")


def render_board(state: dict) -> str:
    """Port of ``tools/control_engine.py:render_board``.

    Unlike the canonical function this one does not re-validate first: the caller has
    already run the schema and invariant passes and collected their findings, and
    re-raising here would hide the board comparison behind an unrelated failure.
    """
    agent_status = state["agent_states"]
    pipeline = " → ".join(
        f"**{name} ({state['state']})**" if step == state["pipeline_step"] else name
        for step, name in _ROUTE
    )
    cycle = state["cycle_id"] + (" (migrated)" if state["cycle_origin"] == "MIGRATED" else "")
    refs = state["source_refs"]
    lines = [
        "# BEG_WORK control board",
        "",
        f"Source: `coordination/CONTROL_STATE.json` · branch: `{state['branch']}` · protocol v{state['protocol_version']}",
        f"ACTIVE source updated: {state['updated_at']} · CONTROL STATE: **{state['control_state_status']}** as of {state['validated_at']} ({state['validation_mode']})",
        "**Snapshot only:** `VALID` is not live verification. Recheck source blobs, PR head and review before any consequential action.",
        "",
        f"CURRENT: {state['task_id']} / {cycle} / {state['current_agent']} / **{state['state']}**",
        f"NEXT: {state['next_agent']}",
        f"KRUM ACTION: {'REQUIRED — ' + state['requires_krum_reason'] if state['requires_krum'] else 'NONE'}",
        f"WAITING FOR: {state['waiting_for'] or '—'}",
        "",
        "## Required agent banner",
        "",
        "All three agents must read the control state and recheck live evidence before consequential work. STALE, CONFLICT or INVALID: **STOP**.",
        "",
        "```text",
        "BEG_WORK",
        f"TASK: {state['task_id']}",
        f"CYCLE: {state['cycle_id']}",
        "AGENT: GPT | CODEX | CLAUDE (select the actual sender)",
        "ROLE: ARCHITECT | TECH_LEAD_QA | IMPLEMENTER (match AGENT)",
        f"STATE: {state['state']}",
        f"NEXT: {state['next_agent']}",
        f"WAITING_FOR: {state['waiting_for'] or 'NONE'}",
        "```",
        "",
        "| Task | Cycle | ChatGPT | Codex | Claude | Current | Waiting for | Result |",
        "|---|---|---|---|---|---|---|---|",
        f"| {_cell(state['task_id'])} | {_cell(cycle)} | {_cell(agent_status['GPT']['state'])} | {_cell(agent_status['CODEX']['state'])} | {_cell(agent_status['CLAUDE']['state'])} | {_cell(state['current_agent'])} | {_cell(state['waiting_for'])} | {_cell(state['state'])} |",
        "",
        "## Agent cards",
        "",
        "Current agent state is explicit in `agent_states`; history below is evidence, not a status source.",
        "",
        "| Agent | State | Work-ID | Waiting for | Updated at (UTC) |",
        "|---|---|---|---|---|",
    ]
    for name in ("GPT", "CODEX", "CLAUDE"):
        item = agent_status[name]
        lines.append(
            f"| {name} | {_cell(item['state'])} | {_cell(item['work_id'])} | {_cell(item['waiting_for'])} | {_cell(item['updated_at'])} |"
        )
    lines += [
        "",
        pipeline,
        "",
        "## Evidence",
        "",
        f"- ACTIVE: `{refs['active_path']}` · source commit `{state['active_source_commit_sha']}` · blob `{refs['active_blob_sha']}`",
    ]
    if state["last_review"]:
        review = state["last_review"]
        lines.append(
            f"- Review: `{review['path']}` · blob `{review['blob_sha']}` · verdict **{review['verdict']}** on `{review['reviewed_head_sha']}`"
        )
    if state["pr_number"]:
        url = f"https://github.com/{state['repository']}/pull/{state['pr_number']}"
        lines.append(
            f"- {'Draft ' if state['pr_draft'] else ''}PR: [#{state['pr_number']}]({url}) · exact head `{state['pr_head_sha']}`"
        )
    if state["last_handoff"]:
        lines.append(
            f"- HANDOFF: [comment]({state['last_handoff']['url']}) · head `{state['last_handoff']['head_sha']}`"
        )
    lines += [
        f"- Dispatch session: {state['dispatch_run_url'] or '—'} · dispatch state **{state['dispatch_state']}**",
        f"- HANDOFF comment SHA-256: `{refs.get('handoff_comment_sha256') or '—'}`",
        "- Canonical docs: "
        + (
            ", ".join(f"`{item['path']}` @ `{item['blob_sha'][:8]}`" for item in refs.get("canonical_docs", []))
            or "—"
        ),
        f"- Wave/Flow: `{state['wave']}` / `{state['flow']}` · progress: **{state['progress']['stage']} / {state['progress']['mode']}**"
        + (
            f" ({state['progress']['percent']}%)"
            if state["progress"]["percent"] is not None
            else " (no proven percentage)"
        ),
        "- `control_state_commit_sha` names the previous published state commit; it cannot self-reference this file's own Git commit.",
        "",
        "## Append-only history",
        "",
        "Legacy events have no original Cycle-ID; `mapped_cycle` is an explicit mapping, not a rewritten historical claim.",
        "",
        "| UTC | Original cycle | Mapped cycle | Event | Agent | State after | Exact head | Source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in state["history"]:
        head = item["head_sha"][:8] if item["head_sha"] else "—"
        lines.append(
            f"| {_cell(item['occurred_at'])} | {_cell(item['cycle_id'])} | {_cell(item['mapped_cycle'])} | {_cell(item['kind'])} | {_cell(item['actor'])} | {_cell(item['state_after'])} | `{head}` | [evidence]({item['source_url']}) |"
        )
    if state["state"] == "BLOCKED":
        gate = f"{state['task_id']} is BLOCKED. No new cycle, PASS, merge or deploy is authorized by this read-model."
    else:
        gate = f"{state['task_id']} is {state['state']}. Progression requires independent evidence and the relevant owner approval; this board grants none."
    lines += ["", f"**Gate:** {gate}", ""]
    return "\n".join(lines)


def cross_check(state: dict, board_text: str | None) -> Verdict:
    """Compare the published board against the board this state should render to."""
    if board_text is None:
        return Verdict(
            [
                Finding(
                    Status.STALE,
                    "BOARD_UNVERIFIED",
                    "CONTROL_BOARD.md was not read this round, so it is unverified against the state.",
                )
            ]
        )
    try:
        expected = render_board(state)
    except (KeyError, TypeError) as exception:
        # A state too damaged to render is already reported by the schema pass; saying
        # so again as a board conflict would double-count the same defect.
        return Verdict(
            [
                Finding(
                    Status.STALE,
                    "BOARD_NOT_COMPARABLE",
                    f"The state could not be re-rendered for comparison ({exception.__class__.__name__}), so the board is unverified.",
                )
            ]
        )

    # Git may deliver the board with either line ending; the protocol's claim is about
    # content, not about how a checkout wrote it.
    if _normalise(board_text) == _normalise(expected):
        return Verdict()

    return Verdict(
        [
            Finding(
                Status.CONFLICT,
                "BOARD_NOT_GENERATED_FROM_STATE",
                "CONTROL_BOARD.md is not exactly what CONTROL_STATE.json renders to: "
                + _first_difference(_normalise(expected), _normalise(board_text)),
            )
        ]
    )


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _first_difference(expected: str, observed: str) -> str:
    """A short, human-readable pointer at the first divergence."""
    for line in difflib.unified_diff(
        expected.splitlines(), observed.splitlines(), "expected", "published", lineterm="", n=0
    ):
        if line.startswith("@@"):
            return f"first divergence at {line.strip()}"
    return "the two differ in trailing content only"
