"""Two-phase dashboard-first lifecycle: intent is never promoted without evidence."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/web-dashboard"))
import control_engine as engine
from app import invariants as dashboard_invariants
from app import schema as dashboard_schema

HEAD = "a" * 40
BLOB = "b" * 40
SESSION = "https://example.test/claude/session/1"
HANDOFF = "https://github.com/krumingo/BEG_Worck/pull/99#issuecomment-1"
REVIEW = "https://github.com/krumingo/BEG_Worck/blob/codex/claude-queue/coordination/REVIEWS/W0-03D.md"


class TwoPhaseTests(unittest.TestCase):
    def pending(self):
        state = json.loads((ROOT / "coordination/CONTROL_STATE.json").read_text(encoding="utf-8"))
        state["protocol_version"] = 2
        state["now"] = "Codex preparing/sending task to Claude"
        state["transition"] = {"event": "DISPATCH", "phase": "INTENT", "evidence_url": None,
                               "verdict_publication": "NONE"}
        state["agent_states"]["GPT"]["state"] = "HANDOFF_READY"
        state["agent_states"]["CLAUDE"] = {
            "state": "WAITING", "work_id": "W0-03D/C01/CL",
            "waiting_for": "Codex Send and observed session start", "updated_at": state["updated_at"]}
        return state

    def started(self):
        state = self.pending()
        state.update(current_agent="CLAUDE", current_role="IMPLEMENTER",
                     current_work_id="W0-03D/C01/CL", state="WORKING",
                     pipeline_step="IMPLEMENTATION", next_agent="CODEX",
                     waiting_for=None, requires_krum=False, requires_krum_reason=None,
                     dispatch_state="RUNNING", dispatch_run_url=SESSION,
                     now="Claude working")
        state["agent_states"]["CODEX"].update(state="WAITING", waiting_for="Claude HANDOFF")
        state["agent_states"]["CLAUDE"].update(state="WORKING", waiting_for=None)
        state["transition"] = {"event": "CLAUDE_START", "phase": "OBSERVED",
                               "evidence_url": SESSION, "verdict_publication": "NONE"}
        state["relay"].update(last_agent="CODEX", last_event="Dispatched to Claude",
                              last_result="DISPATCHED", **{"from": None, "to": None},
                              status="NO_RELAY_NEEDED", required_by_krum=False,
                              source_url=SESSION, instruction="No manual relay is needed.")
        return state

    def handed_off(self):
        state = self.started()
        state.update(current_agent="CODEX", current_role="TECH_LEAD_QA",
                     current_work_id="W0-03D/C01/CX", state="REVIEW",
                     pipeline_step="REVIEW", next_agent="GPT", now="Codex reviewing Claude",
                     pr_number=99, pr_head_sha=HEAD, pr_draft=True,
                     last_handoff={"url": HANDOFF, "head_sha": HEAD, "at": state["updated_at"]})
        state["agent_states"]["GPT"].update(state="WAITING", waiting_for="Codex verdict")
        state["agent_states"]["CODEX"].update(state="REVIEWING", waiting_for=None)
        state["agent_states"]["CLAUDE"].update(state="HANDOFF_READY", waiting_for="Codex review")
        state["transition"] = {"event": "CLAUDE_HANDOFF", "phase": "OBSERVED",
                               "evidence_url": HANDOFF, "verdict_publication": "NONE"}
        state["relay"].update(last_agent="CLAUDE", last_event="Exact-head HANDOFF",
                              last_result="HANDOFF", source_url=HANDOFF)
        return state

    def assert_rejected(self, state):
        with self.assertRaises(engine.ControlError):
            engine.validate_state(state)
        self.assertNotEqual(dashboard_invariants.validate(state).status.label, "VALID")

    def assert_agree(self, state):
        engine.validate_state(state)
        schema = json.loads((ROOT / "coordination/CONTROL_STATE.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(dashboard_schema.validate(state, schema).status.label, "VALID")
        self.assertEqual(dashboard_invariants.validate(state).status.label, "VALID")

    def test_dispatch_pending_before_send(self):
        state = self.pending()
        self.assert_agree(state)
        self.assertIn("TRANSITION: DISPATCH / INTENT", engine.render_board(state))
        premature = copy.deepcopy(state)
        premature["agent_states"]["CLAUDE"]["state"] = "WORKING"
        premature["agent_states"]["CLAUDE"]["waiting_for"] = None
        self.assert_rejected(premature)

    def test_claude_working_only_after_observed_start(self):
        state = self.started()
        self.assert_agree(state)
        missing_session = copy.deepcopy(state)
        missing_session["dispatch_run_url"] = None
        self.assert_rejected(missing_session)
        intent_only = copy.deepcopy(state)
        intent_only["transition"]["phase"] = "INTENT"
        intent_only["transition"]["evidence_url"] = None
        self.assert_rejected(intent_only)

    def test_codex_reviewing_only_after_published_handoff(self):
        state = self.handed_off()
        self.assert_agree(state)
        no_handoff = copy.deepcopy(state)
        no_handoff["last_handoff"] = None
        self.assert_rejected(no_handoff)
        stale_handoff = copy.deepcopy(state)
        stale_handoff["last_handoff"]["head_sha"] = "c" * 40
        self.assert_rejected(stale_handoff)

    def test_verdict_ready_is_not_published(self):
        state = self.handed_off()
        state["transition"] = {"event": "CODEX_VERDICT", "phase": "INTENT",
                               "evidence_url": None, "verdict_publication": "READY"}
        self.assert_agree(state)
        self.assertIsNone(state["last_review"])
        self.assertEqual(state["state"], "REVIEW")
        premature = copy.deepcopy(state)
        premature["state"] = "PASS"
        self.assert_rejected(premature)

    def test_confirmed_verdict_only_after_publish(self):
        state = self.handed_off()
        state.update(state="PASS", waiting_for="GPT acknowledgement",
                     requires_krum=True, requires_krum_reason="Relay Codex verdict to GPT",
                     now="Codex verdict published; GPT pending relay")
        state["agent_states"]["CODEX"].update(state="WAITING", waiting_for=state["waiting_for"])
        state["source_refs"].update(review_path="coordination/REVIEWS/W0-03D.md", review_blob_sha=BLOB)
        state["last_review"] = {"path": "coordination/REVIEWS/W0-03D.md", "blob_sha": BLOB,
                                "reviewed_head_sha": HEAD, "verdict": "PASS"}
        state["transition"] = {"event": "CODEX_VERDICT", "phase": "OBSERVED",
                               "evidence_url": REVIEW, "verdict_publication": "PUBLISHED"}
        state["relay"].update(last_agent="CODEX", last_event="Independent review",
                              last_result="PASS", **{"from": "CODEX", "to": "GPT"},
                              status="NOT_SENT", required_by_krum=True, source_url=REVIEW)
        self.assert_agree(state)
        self.assertIn("LAST: CODEX", engine.render_board(state))
        unpublished = copy.deepcopy(state)
        unpublished["last_review"] = None
        self.assert_rejected(unpublished)


if __name__ == "__main__":
    unittest.main()
