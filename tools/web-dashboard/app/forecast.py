"""Fail-closed, read-only management projection of the versioned effort model.

Lifecycle counts describe completed *steps*, not engineering effort.  The two are
never converted into one another.  Hours and percentages appear only for an
APPROVED, complete row-level estimate on the same verified control snapshot.
"""

from __future__ import annotations

import json
import math
import re

from .gitblob import sha_equal

WAVES = ("W0", "W1", "W2", "W3", "W4")
STATUSES = {"COMPLETED", "PARTIAL", "NOT_STARTED", "UNVERIFIED"}


def _empty(reason: str) -> dict:
    return {
        "verified": False, "reason": reason, "business": None,
        "overall": None, "current_wave": None, "current_task": None,
    }


def _hours(rows: list[dict]) -> tuple[float | None, float | None, float | None]:
    if not rows or any(
        not isinstance(row.get("estimated_total_hours"), (int, float))
        or isinstance(row.get("estimated_total_hours"), bool)
        or row["estimated_total_hours"] <= 0
        or not math.isfinite(row["estimated_total_hours"])
        or not isinstance(row.get("estimated_remaining_hours"), (int, float))
        or isinstance(row.get("estimated_remaining_hours"), bool)
        or not 0 <= row["estimated_remaining_hours"] <= row["estimated_total_hours"]
        for row in rows
    ):
        return None, None, None
    total = sum(row["estimated_total_hours"] for row in rows)
    remaining = sum(row["estimated_remaining_hours"] for row in rows)
    accepted = sum(row["estimated_total_hours"] for row in rows if row["status"] == "COMPLETED")
    return round(100 * accepted / total, 1), round(total, 1), round(remaining, 1)


def project_forecast(fetched, control: dict | None, *, control_verified: bool, repository: str, branch: str) -> dict:
    if not control_verified or control is None:
        return _empty("CONTROL STATE UNVERIFIED — management metrics withheld")
    if fetched is None:
        return _empty("FORECAST.json not available — management metrics withheld")
    if fetched.api_reported_sha and not sha_equal(fetched.blob_sha, fetched.api_reported_sha):
        return _empty("FORECAST.json transport blob mismatch")
    try:
        model = json.loads(fetched.text)
    except (ValueError, UnicodeError):
        return _empty("FORECAST.json is not valid JSON")
    if not isinstance(model, dict) or model.get("repository") != repository or model.get("source_branch") != branch:
        return _empty("Forecast repository or branch does not match the verified control target")
    rows = model.get("rows")
    task = model.get("current_task")
    business = model.get("business_flow")
    wave = model.get("current_wave")
    if not isinstance(rows, list) or not rows or not isinstance(task, dict) or not isinstance(business, dict) or wave not in WAVES:
        return _empty("Forecast structure is incomplete")
    if any(not isinstance(row, dict) or row.get("wave") not in WAVES or row.get("status") not in STATUSES
           or not row.get("canonical_item") or not row.get("deliverable") for row in rows):
        return _empty("Forecast has malformed deliverable rows")
    if len({(row["wave"], row["canonical_item"], row["deliverable"]) for row in rows}) != len(rows):
        return _empty("Forecast contains duplicate deliverables")
    if task.get("task_id") != control.get("task_id") or task.get("cycle_id") != control.get("cycle_id") or task.get("exact_head") != control.get("pr_head_sha"):
        return _empty("Forecast task/cycle/head does not match the verified control state")
    if not isinstance(business.get("business_locked"), int) or not isinstance(business.get("total"), int) or not 0 <= business["business_locked"] <= business["total"]:
        return _empty("Business FLOW counts are invalid")
    lifecycle = task.get("lifecycle")
    if not isinstance(lifecycle, list) or not lifecycle or any(
        not isinstance(stage, dict) or not isinstance(stage.get("stage"), str)
        or stage.get("status") not in {"COMPLETED", "PENDING", "WORKING", "BLOCKED"}
        for stage in lifecycle
    ):
        return _empty("Task lifecycle is invalid")
    completed = sum(stage["status"] == "COMPLETED" for stage in lifecycle)
    if task.get("completed_lifecycle_stages") != completed or task.get("total_lifecycle_stages") != len(lifecycle):
        return _empty("Task lifecycle count does not match the listed stages")

    approval = model.get("approval") if isinstance(model.get("approval"), dict) else {}
    approved = (model.get("status") == "APPROVED_ESTIMATION"
                and approval.get("status") == "APPROVED"
                and isinstance(approval.get("source_url"), str)
                and approval["source_url"].startswith(f"https://github.com/{repository}/"))
    whole_pct, total_hours, remaining_hours = _hours(rows) if approved else (None, None, None)
    wave_rows = [row for row in rows if row["wave"] == wave]
    wave_pct, wave_total, wave_remaining = _hours(wave_rows) if approved else (None, None, None)
    task_id = task["task_id"]
    task_item = re.sub(r"[A-Z]$", "", task_id)
    task_suffix = task_id[len(task_item):]
    task_rows = [row for row in wave_rows if row["canonical_item"] == task_item
                 and (not task_suffix or re.match(rf"^{re.escape(task_suffix)}(?:\b|\s|[—–-])", row["deliverable"]))]
    task_pct, task_total, task_remaining = _hours(task_rows) if approved else (None, None, None)

    def counts(scope: list[dict]) -> dict:
        return {status.lower(): sum(row["status"] == status for row in scope) for status in STATUSES}

    return {
        "verified": True,
        "reason": None,
        "estimate_status": model.get("status"),
        "estimate_label": "ESTIMATE / FORECAST" if whole_pct is not None else "NOT ESTIMATED",
        "business": {
            "closed": business["business_locked"], "total": business["total"],
            "legacy": business.get("legacy", []), "implementation_credit": False,
        },
        "overall": {"percent": whole_pct, "total_hours": total_hours,
                    "remaining_hours": remaining_hours, "counts": counts(rows), "current_wave": wave},
        "current_wave": {"id": wave, "percent": wave_pct, "total_hours": wave_total,
                         "remaining_hours": wave_remaining, "counts": counts(wave_rows)},
        "current_task": {"id": task["task_id"], "cycle": task["cycle_id"], "name": task.get("name"),
                         "status": task.get("status"), "next_step": task.get("next_step"),
                         "lifecycle": lifecycle, "completed_stages": completed, "total_stages": len(lifecycle),
                         "percent": task_pct, "total_hours": task_total, "remaining_hours": task_remaining},
    }
