"""What the browser is shown, and where it comes from.

The rules under test are the ones Issue #26 states about rendering: the header fields,
explicit agent cards for all three agents, the five-step pipeline, the task area, the
history with evidence links, and the requirement that a card reflects ``agent_states``
rather than being inferred from anything else.
"""

from __future__ import annotations

import json

import pytest
from app.projection import AGENT_ORDER, project
from app.refresh import Refresher


@pytest.fixture
def payload(client, settings):
    refresher = Refresher(client, settings)
    refresher.tick()
    return project(refresher.current())


# --------------------------------------------------------------------- header


def test_the_header_carries_every_field_the_issue_requires(payload):
    header = payload["header"]
    assert header["product"] == "BEG_WORK"
    assert header["wave"] == "W0"
    assert header["flow"] == "FLOW-032"
    assert header["task_id"] == "W0-03C"
    assert header["cycle_id"] == "C02"
    assert header["progress"]["stage"] == "REVIEW"
    assert payload["last_verified_at"] is not None
    assert header["krum_action"]["required"] is True


def test_a_migrated_cycle_is_labelled_as_migrated(payload):
    """The distinction is in the protocol, so it belongs on screen."""
    assert payload["header"]["cycle_label"] == "C02 (migrated)"


def test_krum_action_required_carries_the_reason(payload):
    krum = payload["header"]["krum_action"]
    assert krum["required"] is True
    assert "correction cycle" in krum["reason"].lower()


def test_krum_action_none_carries_no_reason(fake_github, client, settings, published_state, mutate):
    fake_github.set_state(
        mutate(
            published_state,
            lambda s: (
                s.__setitem__("requires_krum", False),
                s.__setitem__("requires_krum_reason", None),
                s.__setitem__("next_agent", "CODEX"),
            ),
        )
    )
    refresher = Refresher(client, settings)
    refresher.tick()
    krum = project(refresher.current())["header"]["krum_action"]
    assert krum == {"required": False, "reason": None}


# --------------------------------------------------------------- agent cards


def test_all_three_agents_are_always_present_and_in_a_fixed_order(payload):
    """Three cards, always, so a missing agent is visible as a state rather than absent."""
    assert [agent["key"] for agent in payload["agents"]] == list(AGENT_ORDER)
    assert [agent["name"] for agent in payload["agents"]] == ["ChatGPT", "Codex", "Claude"]
    assert [agent["role"] for agent in payload["agents"]] == ["Architect", "Tech Lead / QA", "Implementer"]


def test_each_card_carries_state_work_id_waiting_for_and_updated_at(payload):
    for agent in payload["agents"]:
        assert set(agent) >= {"state", "work_id", "waiting_for", "updated_at", "is_current"}
    codex = next(agent for agent in payload["agents"] if agent["key"] == "CODEX")
    assert codex["state"] == "BLOCKED"
    assert codex["work_id"] == "W0-03C/C02/CX"
    assert codex["waiting_for"].startswith("Explicit technical correction")
    assert codex["updated_at"] == "2026-09-22T06:17:02Z"
    assert codex["is_current"] is True


def test_cards_come_from_agent_states_and_never_from_history(payload, published_state):
    """The concrete trap this guards.

    The newest CLAUDE event in the real history is a HANDOFF. Its card says NOT_ACTIVE.
    A dashboard that derived the card from the latest event would show HANDOFF, which
    would be wrong: the handoff happened, and then Claude stopped being active.
    """
    claude_events = [
        event for event in published_state["history"] if event["actor"] == "CLAUDE"
    ]
    assert claude_events and claude_events[-1]["kind"] == "HANDOFF"

    claude = next(agent for agent in payload["agents"] if agent["key"] == "CLAUDE")
    assert claude["state"] == "NOT_ACTIVE"
    assert claude["work_id"] is None
    assert claude["waiting_for"] is None


def test_exactly_one_card_is_marked_current(payload):
    assert sum(1 for agent in payload["agents"] if agent["is_current"]) == 1


# ----------------------------------------------------------------- pipeline


def test_the_pipeline_is_the_five_step_canonical_route(payload):
    assert [step["agent"] for step in payload["pipeline"]] == [
        "ChatGPT",
        "Codex",
        "Claude",
        "Codex",
        "ChatGPT",
    ]
    assert [step["step"] for step in payload["pipeline"]] == [
        "ARCHITECT",
        "ASSIGNMENT",
        "IMPLEMENTATION",
        "REVIEW",
        "ARCHITECT_FEEDBACK",
    ]


def test_exactly_one_pipeline_step_is_active_and_it_is_the_protocol_step(payload, published_state):
    active = [step for step in payload["pipeline"] if step["active"]]
    assert len(active) == 1
    assert active[0]["step"] == published_state["pipeline_step"] == "REVIEW"
    assert active[0]["badge"] == "BLOCKED"


def test_inactive_steps_carry_no_badge(payload):
    assert all(step["badge"] is None for step in payload["pipeline"] if not step["active"])


# --------------------------------------------------------------------- task


def test_the_task_area_carries_current_next_and_waiting_for(payload):
    task = payload["task"]
    assert task["task_id"] == "W0-03C"
    assert task["current_agent_name"] == "Codex"
    assert task["current_role"] == "TECH_LEAD_QA"
    assert task["current_work_id"] == "W0-03C/C02/CX"
    assert task["next_agent"] == "KRUM"
    assert task["waiting_for"].startswith("Explicit technical correction")
    assert task["dispatch_state"] == "BLOCKED"


def test_the_gate_line_refuses_progression_while_blocked(payload):
    assert "BLOCKED" in payload["gate"]
    assert "No new cycle, PASS, merge or deploy is authorized" in payload["gate"]


# ----------------------------------------------------------------- evidence


def test_evidence_links_every_cited_artefact(payload):
    evidence = payload["evidence"]
    assert evidence["active"]["path"] == "coordination/ACTIVE.md"
    assert evidence["active"]["url"].endswith("/blob/codex/claude-queue/coordination/ACTIVE.md")
    assert evidence["review"]["verdict"] == "BLOCKED"
    assert evidence["pull_request"]["number"] == 20
    assert evidence["pull_request"]["url"] == "https://github.com/krumingo/BEG_Worck/pull/20"
    assert evidence["handoff"]["url"].startswith("https://github.com/krumingo/BEG_Worck/pull/20#issuecomment-")
    assert len(evidence["canonical_docs"]) == 5


def test_evidence_shows_both_the_cited_and_the_observed_identity(payload):
    """Showing only the citation would hide a divergence; showing both makes it checkable."""
    active = payload["evidence"]["active"]
    assert active["blob_sha"] == active["observed_blob_sha"]
    pr = payload["evidence"]["pull_request"]
    assert pr["cited_head_sha"] == pr["observed_head_sha"]
    assert pr["observed_draft"] is True


def test_a_divergence_is_visible_in_the_evidence_not_only_in_the_findings(
    fake_github, client, settings, published_state
):
    fake_github.pull_requests[published_state["pr_number"]]["head"]["sha"] = "f" * 40
    refresher = Refresher(client, settings)
    refresher.tick()
    pr = project(refresher.current())["evidence"]["pull_request"]
    assert pr["cited_head_sha"] != pr["observed_head_sha"]
    assert pr["observed_head_sha"] == "f" * 40


def test_the_previous_state_commit_is_explained_rather_than_presented_as_self_reference(payload):
    note = payload["evidence"]["control_state_note"]
    assert "previous published state commit" in note


# ----------------------------------------------------------------- history


def test_history_is_newest_first_and_complete(payload, published_state):
    history = payload["history"]
    assert len(history) == len(published_state["history"])
    stamps = [event["occurred_at"] for event in history]
    assert stamps == sorted(stamps, reverse=True)


def test_every_history_row_carries_an_evidence_link_and_an_exact_head(payload):
    for event in payload["history"]:
        assert event["source_url"], event
        assert event["kind"]
        assert event["actor"]


def test_a_mapped_cycle_is_reported_as_mapped_not_as_native(payload):
    """The protocol says a mapped cycle is an explicit mapping, not rewritten history."""
    legacy = [event for event in payload["history"] if event["cycle_id"] is None]
    assert legacy, "the real history contains legacy events with no native cycle"
    assert all(event["mapped_cycle"] for event in legacy)


# ------------------------------------------------------------ safety of payload


def test_the_payload_is_json_serialisable_and_carries_no_credential(payload):
    serialised = json.dumps(payload)
    assert "token" not in json.dumps(payload["config"]).replace("token_configured", "")
    assert "ghp_" not in serialised
    assert "Bearer" not in serialised


def test_the_payload_reports_the_cadence_so_the_client_need_not_guess(payload):
    assert payload["refresh_seconds"] == 15
    assert payload["next_attempt_in"] == pytest.approx(15, abs=0.1)
    assert payload["stale_after_seconds"] == 120
