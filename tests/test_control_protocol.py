"""Offline, stdlib-only fail-closed tests for Issue #25 Phase 2."""

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import control_protocol as cp  # noqa: E402


HEAD = "ed588e9420e241f58c14146de6f0c890b38b3743"
OTHER_HEAD = "be8cd207c94388e81b24173af6d690d69abcea00"
ACTIVE_COMMIT = "4ddea223e7eccb29eb9f81e9c4eeca952b9bd5c1"
ACTIVE_BLOB = "4bd7800657b9c7d60eab5b5b7560ecbfe46540da"
REVIEW_BLOB = "730736763991e2b1486c6ef0829d1d5f88017117"


class ControlProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.active = cp.ACTIVE_PATH.read_text(encoding="utf-8")
        cls.review = cp.REVIEW_PATH.read_text(encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
