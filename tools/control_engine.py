"""Pure, task-independent validation and rendering for BEG control snapshots.

VALID means structurally valid at validated_at, not live verification. A consumer
must revalidate the cited sources before any consequential action.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlparse


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "coordination/CONTROL_STATE.schema.json"


class ControlError(ValueError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _schema_ok(value, rule: dict, root: dict) -> bool:
    try:
        _check_schema(value, rule, root)
        return True
    except ControlError:
        return False


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
        if rule.get("format") == "uri" and value and not urlparse(value).scheme:
            raise ControlError("INVALID", f"{location}: invalid URI")
    if type(value) is int and (value < rule.get("minimum", -float("inf")) or
                               value > rule.get("maximum", float("inf"))):
        raise ControlError("INVALID", f"{location}: number outside range")


def validate_state(state: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _check_schema(state, schema, schema)
    if state["control_state_status"] != "VALID":
        raise ControlError(state["control_state_status"], "control state is not VALID; stop")
    if state["validation_mode"] not in {"LIVE_GITHUB", "SYNTHETIC_TEST"}:
        raise ControlError("INVALID", "unknown validation mode")
    if dt.datetime.fromisoformat(state["validated_at"].replace("Z", "+00:00")) < dt.datetime.fromisoformat(state["updated_at"].replace("Z", "+00:00")):
        raise ControlError("INVALID", "validation predates source update")
    suffixes = {"GPT": "GPT", "CODEX": "CX", "CLAUDE": "CL"}
    suffix = suffixes[state["current_agent"]]
    if state["current_work_id"] != f"{state['task_id']}/{state['cycle_id']}/{suffix}":
        raise ControlError("INVALID", "Work-ID does not match Task/Cycle/current agent")
    role = {"GPT": "ARCHITECT", "CODEX": "TECH_LEAD_QA", "CLAUDE": "IMPLEMENTER"}
    if state["current_role"] != role[state["current_agent"]]:
        raise ControlError("INVALID", "agent/role mismatch")
    if state["pipeline_step"] not in {"ARCHITECT", "ASSIGNMENT", "IMPLEMENTATION", "REVIEW", "ARCHITECT_FEEDBACK"}:
        raise ControlError("INVALID", "invalid pipeline step")
    step_agent = {"ARCHITECT": "GPT", "ASSIGNMENT": "CODEX", "IMPLEMENTATION": "CLAUDE", "REVIEW": "CODEX", "ARCHITECT_FEEDBACK": "GPT"}
    if state["current_agent"] != step_agent[state["pipeline_step"]]:
        raise ControlError("INVALID", "pipeline step/agent mismatch")
    agents = state["agent_states"]
    current = agents[state["current_agent"]]
    if (current["state"] != state["state"] or
            current["work_id"] != state["current_work_id"] or
            current["waiting_for"] != state["waiting_for"]):
        raise ControlError("CONFLICT", "current agent state/work/waiting does not match snapshot")
    active = [name for name, item in agents.items() if item["state"] in {"WORKING", "REVIEW"}]
    if active != ([state["current_agent"]] if state["state"] in {"WORKING", "REVIEW"} else []):
        raise ControlError("INVALID", "WORKING/REVIEW must belong only to current pipeline agent")
    validated = dt.datetime.fromisoformat(state["validated_at"].replace("Z", "+00:00"))
    for name, item in agents.items():
        observed = dt.datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
        if observed > validated:
            raise ControlError("INVALID", f"{name} agent state updated after validation")
        if item["state"] == "NOT_ACTIVE" and (item["work_id"] is not None or item["waiting_for"] is not None):
            raise ControlError("INVALID", f"{name} NOT_ACTIVE must have null work and waiting")
        if item["state"] == "WAITING" and not (item["waiting_for"] or "").strip():
            raise ControlError("INVALID", f"{name} WAITING needs explicit waiting_for")
        if item["work_id"] is not None:
            expected = f"{state['task_id']}/{state['cycle_id']}/{suffixes[name]}"
            if item["work_id"] != expected:
                raise ControlError("INVALID", f"{name} work_id does not match current task/cycle")
    if state["requires_krum"] and not (state["requires_krum_reason"] or "").strip():
        raise ControlError("INVALID", "requires_krum has no reason")
    if state["state"] in {"WAITING", "BLOCKED"} and not (state["waiting_for"] or "").strip():
        raise ControlError("INVALID", "waiting/blocked state has no waiting_for")
    if state["next_agent"] == "KRUM" and not state["requires_krum"]:
        raise ControlError("INVALID", "next Krum action needs explicit reason")
    if state["pr_number"] is None:
        if state["pr_head_sha"] is not None or state["pr_draft"] is not None or state["last_handoff"] is not None or state["last_review"] is not None:
            raise ControlError("INVALID", "PR evidence is incomplete")
    elif state["pr_head_sha"] is None or state["pr_draft"] is None:
        raise ControlError("INVALID", "PR number needs head and draft status")
    review = state["last_review"]
    if review:
        if state["pr_head_sha"] != review["reviewed_head_sha"]:
            raise ControlError("STALE", "review was not on the current PR head")
        if review["blob_sha"] != state["source_refs"].get("review_blob_sha"):
            raise ControlError("STALE", "review blob reference mismatch")
        if state["state"] in {"PASS", "CHANGES_REQUESTED", "BLOCKED"} and review["verdict"] != state["state"]:
            raise ControlError("CONFLICT", "state conflicts with independent review verdict")
    elif state["state"] in {"PASS", "CHANGES_REQUESTED"}:
        raise ControlError("INVALID", "review verdict requires exact review evidence")
    if state["last_handoff"] and state["last_handoff"]["head_sha"] != state["pr_head_sha"]:
        raise ControlError("STALE", "handoff is not on current PR head")
    ids = [item["event_id"] for item in state["history"]]
    if len(ids) != len(set(ids)):
        raise ControlError("INVALID", "duplicate history event_id")
    for item in state["history"]:
        if item["task_id"] != state["task_id"]:
            raise ControlError("INVALID", "history Task-ID mismatch")
        if (item["cycle_id"] is None) == (item["mapped_cycle"] is None):
            raise ControlError("INVALID", "history needs exactly one native or mapped cycle")
        cycle = item["cycle_id"] or item["mapped_cycle"]
        if int(cycle[1:]) > int(state["cycle_id"][1:]):
            raise ControlError("INVALID", "history invents a future cycle")
    progress = state["progress"]
    if progress["mode"] == "STAGE_ONLY":
        if any(progress[key] is not None for key in ("completed", "total", "percent")):
            raise ControlError("INVALID", "stage-only progress cannot claim numbers")
    elif progress["total"] is None or progress["completed"] is None or progress["percent"] is None:
        raise ControlError("INVALID", "evidence-count progress needs numerator, denominator, percent")
    elif progress["completed"] > progress["total"] or progress["percent"] != 100 * progress["completed"] // progress["total"]:
        raise ControlError("INVALID", "progress percentage is not deterministic")


def render_board(state: dict) -> str:
    validate_state(state)
    def cell(value) -> str:
        return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")
    agent_status = state["agent_states"]
    route = [("ARCHITECT", "GPT"), ("ASSIGNMENT", "Codex"), ("IMPLEMENTATION", "Claude"),
             ("REVIEW", "Codex"), ("ARCHITECT_FEEDBACK", "GPT")]
    pipeline = " → ".join(f"**{name} ({state['state']})**" if step == state["pipeline_step"] else name
                          for step, name in route)
    cycle = state["cycle_id"] + (" (migrated)" if state["cycle_origin"] == "MIGRATED" else "")
    refs = state["source_refs"]
    lines = ["# BEG_WORK control board", "",
             f"Source: `coordination/CONTROL_STATE.json` · branch: `{state['branch']}` · protocol v{state['protocol_version']}",
             f"ACTIVE source updated: {state['updated_at']} · CONTROL STATE: **{state['control_state_status']}** as of {state['validated_at']} ({state['validation_mode']})",
             "**Snapshot only:** `VALID` is not live verification. Recheck source blobs, PR head and review before any consequential action.", "",
             f"CURRENT: {state['task_id']} / {cycle} / {state['current_agent']} / **{state['state']}**",
             f"NEXT: {state['next_agent']}",
             f"KRUM ACTION: {'REQUIRED — ' + state['requires_krum_reason'] if state['requires_krum'] else 'NONE'}",
             f"WAITING FOR: {state['waiting_for'] or '—'}", "", "## Required agent banner", "",
             "All three agents must read the control state and recheck live evidence before consequential work. STALE, CONFLICT or INVALID: **STOP**.", "", "```text", "BEG_WORK",
             f"TASK: {state['task_id']}", f"CYCLE: {state['cycle_id']}",
             "AGENT: GPT | CODEX | CLAUDE (select the actual sender)",
             "ROLE: ARCHITECT | TECH_LEAD_QA | IMPLEMENTER (match AGENT)",
             f"STATE: {state['state']}", f"NEXT: {state['next_agent']}",
             f"WAITING_FOR: {state['waiting_for'] or 'NONE'}", "```", "",
             "| Task | Cycle | ChatGPT | Codex | Claude | Current | Waiting for | Result |",
             "|---|---|---|---|---|---|---|---|",
             f"| {cell(state['task_id'])} | {cell(cycle)} | {cell(agent_status['GPT']['state'])} | {cell(agent_status['CODEX']['state'])} | {cell(agent_status['CLAUDE']['state'])} | {cell(state['current_agent'])} | {cell(state['waiting_for'])} | {cell(state['state'])} |", "",
             "## Agent cards", "",
             "Current agent state is explicit in `agent_states`; history below is evidence, not a status source.", "",
             "| Agent | State | Work-ID | Waiting for | Updated at (UTC) |",
             "|---|---|---|---|---|"]
    for name in ("GPT", "CODEX", "CLAUDE"):
        item = agent_status[name]
        lines.append(f"| {name} | {cell(item['state'])} | {cell(item['work_id'])} | {cell(item['waiting_for'])} | {cell(item['updated_at'])} |")
    lines += ["", pipeline, "", "## Evidence", "",
             f"- ACTIVE: `{refs['active_path']}` · source commit `{state['active_source_commit_sha']}` · blob `{refs['active_blob_sha']}`"]
    if state["last_review"]:
        review = state["last_review"]
        lines.append(f"- Review: `{review['path']}` · blob `{review['blob_sha']}` · verdict **{review['verdict']}** on `{review['reviewed_head_sha']}`")
    if state["pr_number"]:
        url = f"https://github.com/{state['repository']}/pull/{state['pr_number']}"
        lines.append(f"- {'Draft ' if state['pr_draft'] else ''}PR: [#{state['pr_number']}]({url}) · exact head `{state['pr_head_sha']}`")
    if state["last_handoff"]:
        lines.append(f"- HANDOFF: [comment]({state['last_handoff']['url']}) · head `{state['last_handoff']['head_sha']}`")
    lines += [f"- Dispatch session: {state['dispatch_run_url'] or '—'} · dispatch state **{state['dispatch_state']}**",
              f"- HANDOFF comment SHA-256: `{refs.get('handoff_comment_sha256') or '—'}`",
              "- Canonical docs: " + (", ".join(f"`{item['path']}` @ `{item['blob_sha'][:8]}`" for item in refs.get("canonical_docs", [])) or "—"),
              f"- Wave/Flow: `{state['wave']}` / `{state['flow']}` · progress: **{state['progress']['stage']} / {state['progress']['mode']}**" + (f" ({state['progress']['percent']}%)" if state['progress']['percent'] is not None else " (no proven percentage)"),
              "- `control_state_commit_sha` names the previous published state commit; it cannot self-reference this file's own Git commit.", "",
              "## Append-only history", "",
              "Legacy events have no original Cycle-ID; `mapped_cycle` is an explicit mapping, not a rewritten historical claim.", "",
              "| UTC | Original cycle | Mapped cycle | Event | Agent | State after | Exact head | Source |",
              "|---|---|---|---|---|---|---|---|"]
    for item in state["history"]:
        head = item["head_sha"][:8] if item["head_sha"] else "—"
        lines.append(f"| {cell(item['occurred_at'])} | {cell(item['cycle_id'])} | {cell(item['mapped_cycle'])} | {cell(item['kind'])} | {cell(item['actor'])} | {cell(item['state_after'])} | `{head}` | [evidence]({item['source_url']}) |")
    if state["state"] == "BLOCKED":
        gate = f"{state['task_id']} is BLOCKED. No new cycle, PASS, merge or deploy is authorized by this read-model."
    else:
        gate = f"{state['task_id']} is {state['state']}. Progression requires independent evidence and the relevant owner approval; this board grants none."
    lines += ["", f"**Gate:** {gate}", ""]
    return "\n".join(lines)


def validate_board(state: dict, board: str) -> None:
    if board != render_board(state):
        raise ControlError("CONFLICT", "BOARD is not exactly generated from STATE")
