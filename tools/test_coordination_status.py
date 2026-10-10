"""No-network tests for the Issue #22 read-model and its v1 schema."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

import coordination_status as status


ROOT = Path(__file__).resolve().parents[1]
HEAD = "ed588e9420e241f58c14146de6f0c890b38b3743"
ACTIVE_SHA = "4ddea223e7eccb29eb9f81e9c4eeca952b9bd5c1"
REVIEW_SHA = "3b991fae892f7a22fdeb3e9d0f0920aa71841f19"
WAVES_SHA = "89762fe0c0953d0bbed6874ee1a232fd6f704c95"
HANDOFF_URL = (
    "https://github.com/krumingo/BEG_Worck/pull/20#issuecomment-5771922130"
)


def snapshot() -> dict:
    return {
        "active": (ROOT / "coordination" / "ACTIVE.md").read_text(encoding="utf-8"),
        "review": (ROOT / "coordination" / "REVIEWS" / "W0-03C.md").read_text(
            encoding="utf-8"
        ),
        "waves": (
            ROOT / "docs" / "architecture" / "IMPLEMENTATION_WAVES.md"
        ).read_text(encoding="utf-8"),
        "active_commit_sha": ACTIVE_SHA,
        "review_commit_sha": REVIEW_SHA,
        "waves_commit_sha": WAVES_SHA,
        "pr": {
            "number": 20,
            "url": "https://github.com/krumingo/BEG_Worck/pull/20",
            "state": "OPEN",
            "headRefOid": HEAD,
        },
        "handoff": {
            "url": HANDOFF_URL,
            "body": f"## HANDOFF — W0-03C correction\nHEAD={HEAD}\n",
        },
    }


EVENT = {"kind": "CODEX_BLOCKED", "at": "2026-09-22T09:17:02+03:00"}


class StatusProjectionTests(unittest.TestCase):
    def test_checked_in_status_matches_exact_source_projection(self) -> None:
        self.maxDiff = None
        actual = status.project(snapshot(), EVENT)
        expected = json.loads(
            (ROOT / "coordination" / "STATUS.json").read_text(encoding="utf-8")
        )
        self.assertEqual(actual, expected)
        self.assertEqual(status.validate(actual), [])
        self.assertIsNone(actual["progress_percent"])

    def test_schema_rejects_missing_extra_wrong_sha_and_percentage(self) -> None:
        document = status.project(snapshot(), EVENT)
        self.assertEqual(status.validate(document), [])
        for edit in (
            lambda d: d.pop("task_id"),
            lambda d: d.update({"unapproved_field": True}),
            lambda d: d.update({"pr_head_sha": "short"}),
            lambda d: d.update({"progress_percent": 50}),
        ):
            bad = deepcopy(document)
            edit(bad)
            self.assertTrue(status.validate(bad))

    def test_new_pr_head_invalidates_old_review_and_handoff(self) -> None:
        changed = snapshot()
        changed["pr"]["headRefOid"] = "a" * 40
        result = status.project(
            changed, {"kind": "PR_HEAD_CHANGED", "at": "2026-09-24T10:00:00Z"}
        )
        self.assertEqual(result["pr_head_sha"], "a" * 40)
        self.assertEqual(result["codex_review_state"], "UNKNOWN")
        self.assertEqual(result["claude_state"], "UNKNOWN")
        self.assertEqual(result["next_action"], "UNKNOWN")
        self.assertIsNone(result["source_versions"]["review_commit_sha"])
        self.assertIsNone(result["source_versions"]["handoff_comment_url"])

    def test_handoff_is_not_session_completion(self) -> None:
        data = snapshot()
        data["active"] = data["active"].replace(
            "The Claude session completed", "The Claude session may still be active"
        )
        data["review"] = data["review"].replace(
            "The Claude session ended with a final HANDOFF",
            "A final HANDOFF was posted",
        )
        self.assertEqual(status.project(data)["claude_state"], "HANDOFF_RECORDED")

    def test_unknown_event_and_stale_review_fail_closed(self) -> None:
        data = snapshot()
        data["review"] = data["review"].replace(
            f"Head-SHA: {HEAD}", "Head-SHA: " + "b" * 40
        )
        result = status.project(
            data, {"kind": "CODEX_BLOCKED", "at": "not a timestamp"}
        )
        self.assertEqual(result["codex_review_state"], "UNKNOWN")
        self.assertEqual(result["last_event"], "UNKNOWN")
        self.assertIsNone(result["last_event_at"])
        self.assertFalse(result["requires_krum"])


if __name__ == "__main__":
    unittest.main()
