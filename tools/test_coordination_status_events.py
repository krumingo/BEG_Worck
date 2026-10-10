"""Offline webhook and idempotency fixtures for both draft entrypoints."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import coordination_status_events as events
from test_coordination_status import HEAD, snapshot


ROOT = Path(__file__).resolve().parents[1]
QUEUE_SHA = "4ddea223e7eccb29eb9f81e9c4eeca952b9bd5c1"
OTHER_SHA = "a" * 40
ALLOWED = {"krumingo"}


def envelope(sender="krumingo"):
    return {
        "repository": {"full_name": events.REPOSITORY},
        "sender": {"login": sender},
    }


class FakeAPI:
    def __init__(self, changed=None, current=QUEUE_SHA, status=None):
        self.changed = changed or set()
        self.current = current
        self.status = status
        self.writes = []

    def changed_files(self, before, after):
        return self.changed

    def branch_sha(self, branch):
        return self.current

    def file_text(self, path, ref):
        return self.status if path == events.STATUS_PATH else None

    def write_status(self, expected, content):
        self.writes.append((expected, content))
        return OTHER_SHA


class EventAdapterTests(unittest.TestCase):
    def test_status_only_push_is_ignored_without_write(self):
        payload = envelope()
        payload.update({"ref": f"refs/heads/{events.QUEUE}",
                        "before": OTHER_SHA, "after": QUEUE_SHA})
        api = FakeAPI({events.STATUS_PATH})
        self.assertIsNone(events.classify("push", payload, snapshot(), api, ALLOWED))

    def test_review_push_classifies_only_changed_review(self):
        payload = envelope()
        payload.update({"ref": f"refs/heads/{events.QUEUE}",
                        "before": OTHER_SHA, "after": QUEUE_SHA,
                        "head_commit": {"timestamp": "2026-09-22T06:17:02Z"}})
        api = FakeAPI({"coordination/REVIEWS/W0-03C.md"})
        self.assertEqual(events.classify("push", payload, snapshot(), api, ALLOWED),
                         {"kind": "CODEX_BLOCKED", "at": "2026-09-22T06:17:02Z"})
        api.current = OTHER_SHA
        self.assertIsNone(events.classify("push", payload, snapshot(), api, ALLOWED))

    def test_pr_head_mismatch_and_untrusted_actor_fail_closed(self):
        payload = envelope()
        payload.update({"number": 20, "action": "synchronize",
                        "pull_request": {
                            "html_url": "https://github.com/krumingo/BEG_Worck/pull/20",
                            "head": {"sha": OTHER_SHA},
                            "base": {"ref": "main", "repo": {"full_name": events.REPOSITORY}},
                            "updated_at": "2026-09-24T10:00:00Z"}})
        self.assertIsNone(events.classify("pull_request_target", payload,
                                          snapshot(), FakeAPI(), ALLOWED))
        payload["pull_request"]["head"]["sha"] = HEAD
        payload["sender"]["login"] = "untrusted-user"
        self.assertIsNone(events.classify("pull_request_target", payload,
                                          snapshot(), FakeAPI(), ALLOWED))
        payload["sender"]["login"] = "krumingo"
        self.assertEqual(events.classify("pull_request_target", payload,
                                         snapshot(), FakeAPI(), ALLOWED)["kind"],
                         "PR_HEAD_CHANGED")
        payload["action"] = "closed"
        self.assertIsNone(events.classify("pull_request_target", payload,
                                          snapshot(), FakeAPI(), ALLOWED))

    def test_handoff_requires_active_pr_exact_sha_and_selected_comment(self):
        data = snapshot()
        payload = envelope()
        payload.update({"number": 20, "action": "created",
                        "issue": {"number": 20, "pull_request": {
                            "url": "https://api.github.com/repos/krumingo/BEG_Worck/pulls/20"
                        }},
                        "comment": {"user": {"login": "krumingo"},
                                    "html_url": data["handoff"]["url"],
                                    "body": f"## HANDOFF — W0-03C\n**Exact new head:** `{HEAD}`",
                                    "created_at": "2026-09-22T06:00:00Z"}})
        self.assertEqual(events.classify("issue_comment", payload, data,
                                         FakeAPI(), ALLOWED)["kind"], "CLAUDE_HANDOFF")
        payload["comment"]["body"] = payload["comment"]["body"].replace(HEAD, OTHER_SHA)
        self.assertIsNone(events.classify("issue_comment", payload, data,
                                          FakeAPI(), ALLOWED))
        payload["comment"]["body"] = f"## HANDOFF\nHEAD={HEAD}"
        data["active"] = data["active"].replace(HEAD, OTHER_SHA)
        self.assertIsNone(events.classify("issue_comment", payload, data,
                                          FakeAPI(), ALLOWED))

    def test_duplicate_event_and_source_versions_do_not_write(self):
        data = snapshot()
        event = {"kind": "CODEX_BLOCKED", "at": "2026-09-22T06:17:02Z"}
        existing = (ROOT / events.STATUS_PATH).read_text(encoding="utf-8")
        api = FakeAPI(status=existing)
        with patch.object(events, "read_snapshot", return_value=(data, QUEUE_SHA)), \
             patch.object(events, "classify", return_value=event):
            self.assertEqual(events.update(api, "push", envelope(), ALLOWED),
                             "NO_SEMANTIC_CHANGE")
        self.assertEqual(api.writes, [])
        document = json.loads(existing)
        document["source_versions"]["review_commit_sha"] = OTHER_SHA
        api.status = json.dumps(document)
        with patch.object(events, "read_snapshot", return_value=(data, QUEUE_SHA)), \
             patch.object(events, "classify", return_value=event):
            self.assertEqual(events.update(api, "push", envelope(), ALLOWED),
                             "NO_STATE_TRANSITION")
        self.assertEqual(api.writes, [])


if __name__ == "__main__":
    unittest.main()
