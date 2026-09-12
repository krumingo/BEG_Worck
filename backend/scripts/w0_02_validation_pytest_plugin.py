"""Machine-readable pytest evidence. Loaded explicitly; not a conftest."""
import json
import os
from pathlib import Path

_state = {"schema": 1, "selected": [], "deselected": [], "collection_errors": [],
          "reports": [], "exit_code": None, "internal_errors": []}


def pytest_collection_finish(session):
    _state["selected"] = [item.nodeid for item in session.items]


def pytest_deselected(items):
    _state["deselected"].extend(item.nodeid for item in items)


def pytest_collectreport(report):
    if report.failed or report.skipped:
        _state["collection_errors"].append({"nodeid": report.nodeid,
                                             "outcome": report.outcome,
                                             "detail": str(report.longrepr)})


def pytest_runtest_logreport(report):
    _state["reports"].append({"nodeid": report.nodeid, "when": report.when,
                               "outcome": report.outcome,
                               "wasxfail": getattr(report, "wasxfail", None)})


def pytest_internalerror(excrepr, excinfo):
    _state["internal_errors"].append(str(excrepr))


def pytest_sessionfinish(session, exitstatus):
    _state["exit_code"] = int(exitstatus)
    target = Path(os.environ["W002_PYTEST_EVIDENCE"])
    # Caller owns a fresh output directory; evidence cannot be silently reused.
    with target.open("x", encoding="utf-8") as stream:
        json.dump(_state, stream, indent=2)
        stream.write("\n")
