"""Producer-side routing policy; human relay is a separate transport fact.

Inputs requiring a decision are explicit. In particular, a CHANGES_REQUESTED
verdict alone does not prove that another correction cycle is available.
"""

from __future__ import annotations


def next_execution_agent(event: str, *, correction_available: bool = False,
                         architect_decision_required: bool = False) -> str:
    routes = {
        "ARCHITECT_ASSIGNMENT": "CODEX",
        "CODEX_DISPATCH_OBSERVED": "CLAUDE",
        "CLAUDE_HANDOFF_OBSERVED": "CODEX",
        "CODEX_PASS_PUBLISHED": "GPT",
    }
    if event in routes:
        return routes[event]
    if event == "CODEX_CHANGES_REQUESTED_PUBLISHED" and correction_available:
        return "CLAUDE"
    if event == "BLOCKED_PUBLISHED" and architect_decision_required:
        return "GPT"
    raise ValueError("No evidenced route for this event/decision; leave next_agent unset")
