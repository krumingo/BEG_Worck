"""Append one validated coordination event to a JSONL audit journal.

This does not reconstruct old activity or perform any dispatch.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("actor", "event", "task_id", "result", "evidence")


def append_event(path: Path, event: dict) -> dict:
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")
    missing = [key for key in REQUIRED if not isinstance(event.get(key), str) or not event[key].strip()]
    if missing:
        raise ValueError(f"missing non-empty fields: {', '.join(missing)}")
    record = dict(event)
    record["at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with path.open("ab") as journal:
        journal.write(encoded)
        journal.flush()
        os.fsync(journal.fileno())
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True, help="JSON object containing one verified event")
    args = parser.parse_args()
    event = json.loads(args.event.read_text(encoding="utf-8"))
    print(json.dumps(append_event(args.log, event), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
