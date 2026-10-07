"""
W0-06C — the application bootstrap step of the File Registry integrity monitor.

The C03 independent review's second finding was that the unique finding index
existed only because a test chose to build it: no application path built it, so
a real deployment would have run the monitor without the server-enforced "one
open finding per deterministic identity". And the owner architecture decision
for C04 makes multi-document transaction capability an explicit prerequisite,
which something has to CHECK at a moment a human can still read the answer.

This module is that moment. It is called once from the FastAPI startup hook
(``server.py``) and it does exactly two things:

1. builds :data:`app.files.monitoring.MONITOR_INDEXES` if they are missing —
   idempotent, additive, and it never drops, rebuilds or migrates anything;
2. reports whether this deployment may run the monitor at all: a replica set or
   a transaction-capable mongos, the required unique indexes, and claim rows a
   fence comparison can still be made against.

What it deliberately does NOT do
--------------------------------

* It **activates nothing**. W0-06C has no cron, no timer and no periodic
  scheduler; the report is the input a future scheduler would have to consult,
  and on a FAILED report that scheduler stays ``DISABLED``.
* It **never fails startup**. The rest of BEG_Work does not depend on the
  integrity monitor, so a missing prerequisite must not take the whole server
  down. It is logged as a warning with the exact blockers, and the monitor
  itself then refuses to run (``MonitorNotReady``) — the refusal lives in the
  runner, where it cannot be bypassed by starting the server anyway.
* It **migrates no data** and touches no customer original.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.files.monitoring import (
    READINESS_READY,
    SCHEDULER_DISABLED,
    prepare_monitor_runtime,
)

_LOG = logging.getLogger(__name__)


async def bootstrap_integrity_monitor(db, *, logger: Optional[logging.Logger] = None,
                                      create_indexes: bool = True,
                                      transactions=None) -> Dict[str, Any]:
    """Prepare and report the W0-06C runtime for one database. Never raises.

    Returns the readiness report so a caller (a health route, an operator
    command, a test) can assert on it rather than parse a log line.
    ``transactions`` is the capability source; the default is the real
    :class:`~app.files.monitoring.MongoTransactionRunner`, which probes this
    deployment and fails closed.
    """
    log = logger or _LOG
    try:
        report = await prepare_monitor_runtime(db, create_indexes=create_indexes,
                                               transactions=transactions)
    except Exception as exc:                                          # noqa: BLE001
        # Startup must not die for the integrity monitor, and the monitor must
        # not then run as if nothing happened: it re-checks readiness itself.
        log.warning("W0-06C integrity monitor bootstrap failed (%s); the periodic "
                    "integrity monitor stays disabled", type(exc).__name__)
        return {"status": "FAILED", "ready": False, "scheduler": SCHEDULER_DISABLED,
                "blockers": [{"blocker": "bootstrap_error",
                              "detail": type(exc).__name__}],
                "indexes_created": [], "index_build_error": type(exc).__name__}
    if report.get("status") == READINESS_READY:
        log.info("W0-06C integrity monitor ready: topology=%s, indexes=%s; no "
                 "scheduler is started by W0-06C",
                 (report.get("transactions") or {}).get("topology"),
                 ",".join(report.get("indexes_created") or []) or "already present")
    else:
        log.warning("W0-06C integrity monitor NOT ready; it will refuse to run and "
                    "any scheduler stays %s. Blockers: %s",
                    report.get("scheduler"),
                    "; ".join("%s(%s)" % (b.get("blocker"), b.get("detail"))
                              for b in report.get("blockers") or []))
    return report
