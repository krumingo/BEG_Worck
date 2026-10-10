"""Management progress never promotes lifecycle or business counts to effort %."""

from __future__ import annotations

import json

from app.forecast import project_forecast
from app.gitblob import blob_sha1
from app.github import FetchedFile
from app.settings import FORECAST_PATH


def _fetched(model: dict, *, corrupt_sha: bool = False) -> FetchedFile:
    content = json.dumps(model).encode()
    sha = blob_sha1(content)
    return FetchedFile(FORECAST_PATH, content, sha, "0" * 40 if corrupt_sha else sha, '"forecast"', False)


def _model() -> dict:
    return {
        "repository": "krumingo/BEG_Worck", "source_branch": "codex/claude-queue",
        "status": "INCOMPLETE_ESTIMATION", "current_wave": "W0",
        "business_flow": {"business_locked": 49, "total": 50,
                          "legacy": [{"id": "FLOW-018", "absorbed_by": "FLOW-039"}]},
        "current_task": {"task_id": "W0-03D", "cycle_id": "C01", "exact_head": "a" * 40,
                         "name": "Master Data merge and redirect history", "status": "CHANGES_REQUESTED",
                         "next_step": "Bounded correction", "completed_lifecycle_stages": 4,
                         "total_lifecycle_stages": 6, "lifecycle": [
                             {"stage": str(i), "status": "COMPLETED" if i < 4 else "PENDING"}
                             for i in range(6)]},
        "rows": [
            {"wave": "W0", "canonical_item": "W0-03", "deliverable": "C", "status": "COMPLETED",
             "estimated_total_hours": None, "estimated_remaining_hours": 0},
            {"wave": "W0", "canonical_item": "W0-03", "deliverable": "D", "status": "PARTIAL",
             "estimated_total_hours": None, "estimated_remaining_hours": None},
            {"wave": "W1", "canonical_item": "Wave 1", "deliverable": "contracts", "status": "UNVERIFIED",
             "estimated_total_hours": None, "estimated_remaining_hours": None},
        ],
    }


def _control() -> dict:
    return {"task_id": "W0-03D", "cycle_id": "C01", "pr_head_sha": "a" * 40}


def _project(model: dict, control: dict | None = None, *, verified: bool = True) -> dict:
    return project_forecast(_fetched(model), control or _control(), control_verified=verified,
                            repository="krumingo/BEG_Worck", branch="codex/claude-queue")


def test_business_and_lifecycle_visible_but_effort_unknown_without_approved_baseline():
    view = _project(_model())
    assert view["verified"]
    assert (view["business"]["closed"], view["business"]["total"]) == (49, 50)
    assert view["current_task"]["completed_stages"] == 4
    assert view["current_task"]["total_stages"] == 6
    assert view["overall"]["percent"] is None
    assert view["current_wave"]["percent"] is None
    assert view["current_task"]["percent"] is None
    assert view["overall"]["remaining_hours"] is None
    assert view["estimate_label"] == "NOT ESTIMATED"


def test_numeric_effort_requires_approved_complete_rows():
    model = _model()
    model["status"] = "APPROVED_ESTIMATION"
    assert _project(model)["overall"]["percent"] is None
    model["approval"] = {"status": "APPROVED", "source_url": "https://github.com/krumingo/BEG_Worck/issues/26"}
    for row, total, remaining in zip(model["rows"], (20, 40, 40), (0, 20, 40)):
        row.update(estimated_total_hours=total, estimated_remaining_hours=remaining)
    view = _project(model)
    assert view["overall"]["percent"] == 20.0
    assert view["overall"]["remaining_hours"] == 60
    assert view["current_wave"]["percent"] == 33.3
    assert view["current_task"]["percent"] == 0.0
    assert view["estimate_label"] == "ESTIMATE / FORECAST"


def test_unverified_control_or_forecast_head_withholds_every_management_claim():
    model = _model()
    assert not _project(model, verified=False)["verified"]
    model["current_task"]["exact_head"] = "b" * 40
    assert not _project(model)["verified"]
    assert project_forecast(_fetched(_model(), corrupt_sha=True), _control(), control_verified=True,
                            repository="krumingo/BEG_Worck", branch="codex/claude-queue")["business"] is None


def test_missing_or_malformed_forecast_cannot_be_presented_as_progress():
    assert project_forecast(None, _control(), control_verified=True,
                            repository="krumingo/BEG_Worck", branch="codex/claude-queue")["verified"] is False
    model = _model()
    model["current_task"]["completed_lifecycle_stages"] = 5
    assert not _project(model)["verified"]
