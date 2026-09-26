"""Boundary tests for the offline dispatch gate."""

import copy
import unittest

from agent_relay import REQUIRED_TESTS, evaluate


HEAD = "a" * 40


def ready_snapshot():
    evidence = {"status": "PASS", "command": "independent test", "evidence": "review log"}
    return {
        "queue_sha": "c" * 40,
        "dispatch_state": "PENDING",
        "active_session": False,
        "already_dispatched": False,
        "owner_required": False,
        "next_task": {
            "task_id": "W0-03D",
            "branch": "feat/w0-03d",
            "base_sha": HEAD,
            "scope": "one bounded technical step",
            "exclusions": "no production",
            "acceptance_tests": "positive and negative cases",
            "prerequisites_proven": True,
        },
        "predecessor": {
            "verdict": "PASS",
            "reviewer": "codex",
            "implementer": "claude",
            "final_handoff": True,
            "session_ended": True,
            "head_stable": True,
            "pr_head_sha": HEAD,
            "reviewed_sha": HEAD,
            "diff_reviewed": True,
            "review_artifact": "coordination/REVIEWS/W0-03C.md",
            "independent_tests": {name: copy.deepcopy(evidence) for name in REQUIRED_TESTS},
            "task_specific_tests": [copy.deepcopy(evidence)],
        },
    }


class RelayGateTests(unittest.TestCase):
    def test_complete_review_is_ready_but_does_not_dispatch(self):
        result = evaluate(ready_snapshot())
        self.assertEqual(result["decision"], "READY_TO_DISPATCH")
        self.assertEqual(len(result["idempotency_key"]), 64)
        self.assertIn("no Claude session", result["detail"])

    def test_current_blocked_review_cannot_advance(self):
        snapshot = ready_snapshot()
        snapshot["dispatch_state"] = "BLOCKED"
        snapshot["predecessor"]["verdict"] = "BLOCKED"
        self.assertEqual(evaluate(snapshot)["decision"], "HOLD")

    def test_green_claim_without_independent_test_holds(self):
        snapshot = ready_snapshot()
        del snapshot["predecessor"]["independent_tests"]["rollback"]
        self.assertEqual(evaluate(snapshot)["reason"], "TEST_GATE")

    def test_new_push_invalidates_review(self):
        snapshot = ready_snapshot()
        snapshot["predecessor"]["pr_head_sha"] = "b" * 40
        self.assertEqual(evaluate(snapshot)["reason"], "SHA_MISMATCH")

    def test_intermediate_push_is_not_handoff(self):
        snapshot = ready_snapshot()
        snapshot["predecessor"]["final_handoff"] = False
        self.assertEqual(evaluate(snapshot)["reason"], "HANDOFF_GATE")

    def test_owner_gate_prevents_automation(self):
        snapshot = ready_snapshot()
        snapshot["owner_required"] = True
        self.assertEqual(evaluate(snapshot)["reason"], "OWNER_GATE")

    def test_duplicate_session_prevents_automation(self):
        snapshot = ready_snapshot()
        snapshot["active_session"] = True
        self.assertEqual(evaluate(snapshot)["reason"], "DUPLICATE_RISK")

    def test_unproved_prerequisite_holds(self):
        snapshot = ready_snapshot()
        snapshot["next_task"]["prerequisites_proven"] = False
        self.assertEqual(evaluate(snapshot)["reason"], "PREREQUISITE_GATE")

    def test_na_needs_reason(self):
        snapshot = ready_snapshot()
        snapshot["predecessor"]["independent_tests"]["rollback"] = {"status": "N_A"}
        self.assertEqual(evaluate(snapshot)["reason"], "TEST_GATE")

    def test_self_review_cannot_advance(self):
        snapshot = ready_snapshot()
        snapshot["predecessor"]["reviewer"] = "claude"
        self.assertEqual(evaluate(snapshot)["reason"], "REVIEW_GATE")


if __name__ == "__main__":
    unittest.main()
