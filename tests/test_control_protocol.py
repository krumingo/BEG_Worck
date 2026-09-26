"""Offline, stdlib-only fail-closed tests for Issue #25 Phase 2."""

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import control_protocol as cp  # noqa: E402
import control_engine as engine  # noqa: E402


HEAD = "ed588e9420e241f58c14146de6f0c890b38b3743"
OTHER_HEAD = "be8cd207c94388e81b24173af6d690d69abcea00"
ACTIVE_COMMIT = "4ddea223e7eccb29eb9f81e9c4eeca952b9bd5c1"
ACTIVE_BLOB = "4bd7800657b9c7d60eab5b5b7560ecbfe46540da"
REVIEW_BLOB = "730736763991e2b1486c6ef0829d1d5f88017117"


class ControlProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The migration adapter is intentionally C02-only; pin its historical
        # source instead of treating the live C03 dispatch pointer as C02 input.
        cls.active = (ROOT / "tests" / "fixtures" / "active_w0_03c_c02.md").read_text(encoding="utf-8")
        # C02 migration fixture stops at the preserved historical review section.
        cls.review = cp.REVIEW_PATH.read_text(encoding="utf-8").split("\n---\n", 1)[0]
        cls.pr = {"number": 20, "url": cp.PR_URL, "state": "OPEN",
                  "isDraft": True, "headRefOid": HEAD}
        cls.handoff = {"id": 5771922130,
                       "html_url": cp.PR_URL + "#issuecomment-5771922130",
                       "created_at": "2026-09-22T06:03:35Z",
                       "body": "W0-03C HANDOFF exact head " + HEAD}
        cls.canonical = cp.canonical_sources(HEAD)

    def state(self):
        return cp.build_state(self.active, self.review, self.pr, self.handoff,
                              self.canonical, ACTIVE_COMMIT,
                              ACTIVE_BLOB, REVIEW_BLOB, "2026-09-22T06:17:02Z")

    def assert_status(self, expected, call):
        with self.assertRaises(cp.ControlError) as captured:
            call()
        self.assertEqual(captured.exception.status, expected)

    def test_valid_current_w003c_migration(self):
        state = self.state()
        self.assertEqual((state["task_id"], state["cycle_id"], state["state"]),
                         ("W0-03C", "C02", "BLOCKED"))
        self.assertEqual(state["next_agent"], "KRUM")
        self.assertTrue(state["requires_krum"])
        self.assertEqual(state["pr_head_sha"], HEAD)
        self.assertIsNone(state["control_state_commit_sha"])
        self.assertEqual(len(state["history"]), 10)
        self.assertFalse(any(item["cycle_id"] == "C03" or item["mapped_cycle"] == "C03"
                             for item in state["history"]))
        cp.validate_sources(state, self.active, self.review, self.pr,
                            self.handoff, self.canonical,
                            ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB)

    def test_stale_pr_head_fails_closed(self):
        moved = {**self.pr, "headRefOid": OTHER_HEAD}
        self.assert_status("STALE", lambda: cp.validate_sources(
            self.state(), self.active, self.review, moved,
            self.handoff, self.canonical,
            ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB))

    def test_merged_pr_requires_exact_base_and_merge_sha(self):
        merge_sha = "4f46212486e7f2704007cece774939230e0a51f0"
        active = self.active + f"\nIntegration-State: MERGED\nMerge-Base: main\nMerge-SHA: {merge_sha}\n"
        state = self.state()
        state["progress"]["stage"] = "MERGED"
        state["pr_draft"] = False
        pr = {**self.pr, "state": "MERGED", "isDraft": False,
              "baseRefName": "main", "mergeCommit": {"oid": merge_sha}}
        cp.validate_sources(state, active, self.review, pr, self.handoff,
                            self.canonical, ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB)
        for changed in ({**pr, "baseRefName": "other"},
                        {**pr, "mergeCommit": {"oid": "0" * 40}},
                        {**pr, "state": "OPEN"},
                        {**pr, "isDraft": True}):
            self.assert_status("CONFLICT", lambda changed=changed: cp.validate_sources(
                state, active, self.review, changed, self.handoff,
                self.canonical, ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB))

    def test_stale_review_sha_fails_closed(self):
        self.assert_status("STALE", lambda: cp.validate_sources(
            self.state(), self.active, self.review, self.pr,
            self.handoff, self.canonical,
            ACTIVE_COMMIT, ACTIVE_BLOB, "0" * 40))
        stale_review = self.review.replace(HEAD, OTHER_HEAD)
        self.assert_status("STALE", lambda: cp.build_state(
            self.active, stale_review, self.pr, self.handoff, self.canonical, ACTIVE_COMMIT,
            ACTIVE_BLOB, REVIEW_BLOB, "2026-09-22T06:17:02Z"))

    def test_conflicting_active_vs_pr_head_fails_closed(self):
        altered = self.active.replace("PR-Head: " + HEAD, "PR-Head: " + OTHER_HEAD)
        self.assert_status("CONFLICT", lambda: cp.build_state(
            altered, self.review, self.pr, self.handoff, self.canonical, ACTIVE_COMMIT,
            ACTIVE_BLOB, REVIEW_BLOB, "2026-09-22T06:17:02Z"))

    def test_requires_krum_without_reason_is_invalid(self):
        state = self.state()
        state["requires_krum_reason"] = ""
        self.assert_status("INVALID", lambda: cp.validate_state(state))

    def test_work_id_mismatch_is_invalid(self):
        state = self.state()
        state["current_work_id"] = "W0-03C/C01/CX"
        self.assert_status("INVALID", lambda: cp.validate_state(state))

    def test_duplicate_history_event_id_is_invalid(self):
        state = self.state()
        state["history"].append(copy.deepcopy(state["history"][0]))
        self.assert_status("INVALID", lambda: cp.validate_state(state))

    def test_legacy_cycle_null_with_mapping(self):
        state = self.state()
        self.assertTrue(all(item["cycle_id"] is None and item["mapped_cycle"] in {"C01", "C02"}
                            for item in state["history"]))
        cp.validate_state(state)
        state["history"][0]["mapped_cycle"] = None
        self.assert_status("INVALID", lambda: cp.validate_state(state))

    def test_board_is_exactly_generated_from_state(self):
        state = self.state()
        board = cp.render_board(state)
        cp.validate_board(state, board)
        self.assert_status("CONFLICT", lambda: cp.validate_board(state, board + "manual edit"))
        if cp.STATE_PATH.exists() and cp.BOARD_PATH.exists():
            committed_state = json.loads(cp.STATE_PATH.read_text(encoding="utf-8"))
            cp.validate_board(committed_state, cp.BOARD_PATH.read_text(encoding="utf-8"))

    def test_stale_active_blob_fails_closed(self):
        self.assert_status("STALE", lambda: cp.validate_sources(
            self.state(), self.active, self.review, self.pr,
            self.handoff, self.canonical,
            ACTIVE_COMMIT, "0" * 40, REVIEW_BLOB))

    def test_changed_handoff_fails_closed(self):
        changed = {**self.handoff, "body": self.handoff["body"] + " changed"}
        self.assert_status("STALE", lambda: cp.validate_sources(
            self.state(), self.active, self.review, self.pr,
            changed, self.canonical, ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB))

    def test_changed_canonical_doc_fails_closed(self):
        changed = copy.deepcopy(self.canonical)
        changed[0]["blob_sha"] = "0" * 40
        self.assert_status("STALE", lambda: cp.validate_sources(
            self.state(), self.active, self.review, self.pr,
            self.handoff, changed, ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB))

    def test_unproven_progress_percentage_is_invalid(self):
        state = self.state()
        state["progress"]["percent"] = 90
        self.assert_status("INVALID", lambda: cp.validate_state(state))

    def test_remote_queue_source_change_fails_closed(self):
        cp.verify_remote_queue_sources(ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB,
                                       ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB)
        self.assert_status("STALE", lambda: cp.verify_remote_queue_sources(
            ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB,
            ACTIVE_COMMIT, "0" * 40, REVIEW_BLOB))

    def synthetic_state(self):
        state = self.state()
        state.update(task_id="W2-07A", cycle_id="C01", cycle_origin="NATIVE",
                     current_agent="CLAUDE", current_role="IMPLEMENTER",
                     agent_states={
                         "GPT": {"state": "WAITING", "work_id": "W2-07A/C01/GPT",
                                 "waiting_for": "Claude implementation", "updated_at": "2026-09-23T00:00:00Z"},
                         "CODEX": {"state": "WAITING", "work_id": "W2-07A/C01/CX",
                                   "waiting_for": "Claude HANDOFF", "updated_at": "2026-09-23T00:00:00Z"},
                         "CLAUDE": {"state": "WORKING", "work_id": "W2-07A/C01/CL",
                                    "waiting_for": None, "updated_at": "2026-09-23T00:00:00Z"}},
                     current_work_id="W2-07A/C01/CL", state="WORKING",
                     pipeline_step="IMPLEMENTATION", next_agent="CODEX",
                     waiting_for=None, wave="W2", flow="FLOW-101",
                     pr_number=None, pr_head_sha=None, pr_draft=None,
                     last_handoff=None, last_review=None,
                     dispatch_state="RUNNING", dispatch_run_url="https://example.test/run/1",
                     requires_krum=False, requires_krum_reason=None,
                     validation_mode="SYNTHETIC_TEST", generated_from=["ACTIVE"],
                     progress={"mode": "STAGE_ONLY", "stage": "IMPLEMENTATION",
                               "completed": None, "total": None, "percent": None},
                     source_refs={"active_path": "coordination/ACTIVE.md", "active_blob_sha": ACTIVE_BLOB},
                     history=[{"event_id": "synthetic-start", "occurred_at": "2026-09-23T00:00:00Z",
                               "task_id": "W2-07A", "cycle_id": "C01", "mapped_cycle": None,
                               "actor": "CLAUDE", "kind": "DISPATCH", "state_after": "WORKING",
                               "head_sha": None, "source_url": "https://example.test/run/1",
                               "source_commit_sha": None, "summary": "Synthetic implementation started."}])
        return state

    def test_generic_nonblocked_synthetic_task_without_pr(self):
        state = self.synthetic_state()
        engine.validate_state(state)
        board = engine.render_board(state)
        engine.validate_board(state, board)
        self.assertIn("W2-07A / C01 / CLAUDE / **WORKING**", board)
        self.assertIn("**Claude (WORKING)**", board)
        self.assertIn("| WORKING |", board)
        self.assertNotIn("W0-03C", board)
        self.assertNotIn("pull/20", board)
        self.assertNotIn("No C03", board)
        self.assertNotIn("(migrated)", board)
        self.assert_status("INVALID", lambda: cp.validate_sources(
            state, self.active, self.review, self.pr, self.handoff,
            self.canonical, ACTIVE_COMMIT, ACTIVE_BLOB, REVIEW_BLOB))

    def test_claude_working_agent_cards_are_explicit(self):
        state = self.synthetic_state()
        board = engine.render_board(state)
        self.assertIn("| W2-07A | C01 | WAITING | WAITING | WORKING | CLAUDE |", board)
        self.assertIn("| GPT | WAITING | W2-07A/C01/GPT | Claude implementation |", board)
        self.assertIn("| CODEX | WAITING | W2-07A/C01/CX | Claude HANDOFF |", board)
        self.assertIn("| CLAUDE | WORKING | W2-07A/C01/CL | — |", board)
        changed = copy.deepcopy(state)
        changed["agent_states"]["CODEX"]["state"] = "REVIEW"
        self.assert_status("INVALID", lambda: engine.validate_state(changed))

    def test_codex_review_with_claude_handoff(self):
        state = self.synthetic_state()
        state.update(current_agent="CODEX", current_role="TECH_LEAD_QA",
                     current_work_id="W2-07A/C01/CX", state="REVIEW",
                     pipeline_step="REVIEW", waiting_for=None)
        state["agent_states"]["CODEX"].update(state="REVIEW", waiting_for=None)
        state["agent_states"]["CLAUDE"].update(state="HANDOFF", waiting_for="Codex review")
        board = engine.render_board(state)
        self.assertIn("| W2-07A | C01 | WAITING | REVIEW | HANDOFF | CODEX |", board)
        self.assertIn("| CLAUDE | HANDOFF | W2-07A/C01/CL | Codex review |", board)
        self.assertIn("**Codex (REVIEW)**", board)

    def test_old_blocked_history_does_not_override_explicit_waiting(self):
        state = self.synthetic_state()
        state["history"].append({"event_id": "old-gpt-block", "occurred_at": "2026-09-22T23:00:00Z",
                                 "task_id": "W2-07A", "cycle_id": "C00", "mapped_cycle": None,
                                 "actor": "GPT", "kind": "REVIEW", "state_after": "BLOCKED",
                                 "head_sha": None, "source_url": "https://example.test/old",
                                 "source_commit_sha": None, "summary": "Historical blocker only."})
        board = engine.render_board(state)
        self.assertIn("| W2-07A | C01 | WAITING | WAITING | WORKING | CLAUDE |", board)
        cards = board.split("## Agent cards", 1)[1].split("## Evidence", 1)[0]
        self.assertIn("| GPT | WAITING | W2-07A/C01/GPT |", cards)
        self.assertNotIn("| GPT | BLOCKED |", cards)
        self.assertIn("| GPT | BLOCKED |", board.split("## Append-only history", 1)[1])

    def test_current_agent_record_must_match_top_level(self):
        state = self.synthetic_state()
        state["agent_states"]["CLAUDE"]["work_id"] = "W2-07A/C02/CL"
        self.assert_status("CONFLICT", lambda: engine.validate_state(state))

    def test_idle_none_are_explicitly_unsupported_in_v1(self):
        state = self.state()
        state.update(state="IDLE", current_agent="NONE", current_role="NONE")
        self.assert_status("INVALID", lambda: engine.validate_state(state))

    def test_validation_metadata_required_and_not_live_by_label(self):
        state = self.state()
        for field in ("validated_at", "validation_mode"):
            changed = copy.deepcopy(state)
            changed.pop(field)
            self.assert_status("INVALID", lambda: engine.validate_state(changed))
        board = engine.render_board(state)
        self.assertIn("Snapshot only", board)
        self.assertIn("as of ", board)


if __name__ == "__main__":
    unittest.main()
