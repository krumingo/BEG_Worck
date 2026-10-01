import json
import tempfile
import unittest
from pathlib import Path

from relay_log import append_event


class RelayLogTests(unittest.TestCase):
    def test_appends_without_replacing_earlier_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            first = {"actor": "codex", "event": "review", "task_id": "W0-03C", "result": "BLOCKED", "evidence": "review.md"}
            append_event(path, first)
            append_event(path, {**first, "event": "owner_gate"})
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["event"], "review")
            self.assertEqual(json.loads(lines[1])["event"], "owner_gate")
            self.assertTrue(json.loads(lines[0])["at_utc"].endswith("Z"))

    def test_rejects_unattributed_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            with self.assertRaises(ValueError):
                append_event(path, {"event": "dispatch"})
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
