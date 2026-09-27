"""The next *agent* is never the person carrying a manual relay."""

from __future__ import annotations

import pytest
from control_routing import next_execution_agent


@pytest.mark.parametrize("event,kwargs,expected", [
    ("ARCHITECT_ASSIGNMENT", {}, "CODEX"),
    ("CODEX_DISPATCH_OBSERVED", {}, "CLAUDE"),
    ("CLAUDE_HANDOFF_OBSERVED", {}, "CODEX"),
    ("CODEX_CHANGES_REQUESTED_PUBLISHED", {"correction_available": True}, "CLAUDE"),
    ("CODEX_PASS_PUBLISHED", {}, "GPT"),
    ("BLOCKED_PUBLISHED", {"architect_decision_required": True}, "GPT"),
])
def test_route_is_real_agent(event, kwargs, expected):
    assert next_execution_agent(event, **kwargs) == expected
    assert expected != "KRUM"


def test_a_correction_or_architect_route_cannot_be_invented_without_authority():
    with pytest.raises(ValueError):
        next_execution_agent("CODEX_CHANGES_REQUESTED_PUBLISHED")
    with pytest.raises(ValueError):
        next_execution_agent("BLOCKED_PUBLISHED")
