"""Offline, fail-closed dispatch gate for the BEG_Work coordination queue.

This program never starts Claude and never writes to GitHub. It only evaluates a
verified snapshot supplied by an operator/monitor and prints a JSON decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_TESTS = (
    "positive",
    "forbidden",
    "tenant_isolation",
    "idempotency",
    "rollback",
    "regression",
)


def _hold(reason: str, detail: str) -> dict[str, str]:
    return {"decision": "HOLD", "reason": reason, "detail": detail}


def evaluate(snapshot: dict) -> dict[str, str]:
    """Return readiness, never authorization or evidence of actual dispatch."""
    if not isinstance(snapshot, dict):
        return _hold("INVALID_SNAPSHOT", "Snapshot must be a JSON object.")

    if snapshot.get("dispatch_state") not in ("PENDING",):
        return _hold("NOT_PENDING", "Only a PENDING task can be considered.")
    if snapshot.get("active_session") or snapshot.get("already_dispatched"):
        return _hold("DUPLICATE_RISK", "An active or already sent task exists.")
    if snapshot.get("owner_required") or snapshot.get("security_or_access_change"):
        return _hold("OWNER_GATE", "Owner/security decision must not be automated.")
    if snapshot.get("production_or_nas_or_atlas") or snapshot.get("merge_or_deploy"):
        return _hold("OWNER_GATE", "Production, NAS, Atlas, merge or deploy needs the owner.")

    task = snapshot.get("next_task")
    prior = snapshot.get("predecessor")
    if not isinstance(task, dict) or not isinstance(prior, dict):
        return _hold("MISSING_EVIDENCE", "Task and predecessor evidence are required.")
    if not SHA.fullmatch(str(snapshot.get("queue_sha", ""))):
        return _hold("INVALID_SHA", "The coordination queue needs an exact source SHA.")
    if not task.get("task_id") or not task.get("branch"):
        return _hold("MISSING_TASK", "Task-ID and exact branch are required.")
    if not SHA.fullmatch(str(task.get("base_sha", ""))):
        return _hold("INVALID_SHA", "Next task requires an exact 40-character base SHA.")
    if not task.get("scope") or not task.get("exclusions") or not task.get("acceptance_tests"):
        return _hold("MISSING_TASK", "Scope, exclusions and acceptance tests are required.")
    if not task.get("prerequisites_proven"):
        return _hold("PREREQUISITE_GATE", "Prerequisites have not been independently proven.")

    if prior.get("verdict") != "PASS":
        return _hold("REVIEW_GATE", "Predecessor has no independent PASS.")
    if not prior.get("reviewer") or not prior.get("implementer") or prior["reviewer"] == prior["implementer"]:
        return _hold("REVIEW_GATE", "Reviewer must be identified and independent of implementer.")
    if not prior.get("final_handoff") or not prior.get("session_ended"):
        return _hold("HANDOFF_GATE", "Final HANDOFF and ended session are both required.")
    if not prior.get("head_stable"):
        return _hold("HEAD_UNSTABLE", "PR head is not confirmed stable.")
    head = str(prior.get("pr_head_sha", ""))
    if not SHA.fullmatch(head) or head != prior.get("reviewed_sha"):
        return _hold("SHA_MISMATCH", "Independent review must match current exact PR head.")
    if task["base_sha"] != head:
        return _hold("BASE_MISMATCH", "Next task must stack on the reviewed predecessor SHA.")

    tests = prior.get("independent_tests")
    if not isinstance(tests, dict):
        return _hold("TEST_GATE", "Independent test matrix is missing.")
    for name in REQUIRED_TESTS:
        result = tests.get(name)
        if not isinstance(result, dict):
            return _hold("TEST_GATE", f"Missing independent test: {name}.")
        if result.get("status") == "PASS":
            if not result.get("evidence") or not result.get("command"):
                return _hold("TEST_GATE", f"Test {name} lacks command/evidence.")
        elif result.get("status") == "N_A":
            if not result.get("reason"):
                return _hold("TEST_GATE", f"N_A test {name} lacks a reason.")
        else:
            return _hold("TEST_GATE", f"Test {name} is not PASS or justified N_A.")
    extra = prior.get("task_specific_tests")
    if not isinstance(extra, list) or not extra:
        return _hold("TEST_GATE", "Task-specific test evidence is required.")
    if any(not isinstance(test, dict) or test.get("status") != "PASS"
           or not test.get("evidence") or not test.get("command") for test in extra):
        return _hold("TEST_GATE", "Every task-specific test must have a PASS and evidence.")

    if not prior.get("review_artifact") or not prior.get("diff_reviewed"):
        return _hold("REVIEW_GATE", "Real diff review and REVIEW artifact are required.")
    key_data = f"{task['task_id']}:{task['branch']}:{task['base_sha']}"
    key = hashlib.sha256(key_data.encode("utf-8")).hexdigest()
    return {
        "decision": "READY_TO_DISPATCH",
        "reason": "ALL_GATES_PASS",
        "detail": "Offline readiness only; no Claude session was started.",
        "idempotency_key": key,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = _hold("INVALID_SNAPSHOT", str(exc))
    else:
        result = evaluate(snapshot)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["decision"] == "READY_TO_DISPATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
