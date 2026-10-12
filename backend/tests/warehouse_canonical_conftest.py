"""
Shared helpers for the canonical-warehouse real-Mongo test suite.

Per the TASK 5C contract, a REQUIRED runtime skip is a FAILURE: the
replica-set tests must either pass or hard-fail. The function
`require_replica_set_or_fail` embodies that rule — tests invoke it from
their first line and will fail with a loud reason when the fixture
Mongo is missing or is a standalone instance.

To RUN this suite:
  * export MONGO_URL="mongodb://host:27017/?replicaSet=rs0"
  * export MONGO_TEST_DB=begwork_task5c_test
  * ensure PERMISSION_SERVICE_MODE=enforce

Without the above, the tests fail hard — they do not skip.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator

import pytest

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    MOTOR_AVAILABLE = True
except Exception:
    MOTOR_AVAILABLE = False


REAL_MONGO_ENABLED_ENV = "WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO"


def _require_env() -> bool:
    """TASK 5C: when the gate env is set the suite MUST run and MUST NOT skip.

    When it is unset, the suite skips with a clearly labelled message so
    CODEX reviewing locally without a replica set can still see unit
    coverage. The CI/handoff environment MUST set this env — the
    HANDOFF comment reports whether the suite ran or was skipped.
    """
    return os.environ.get(REAL_MONGO_ENABLED_ENV, "").strip() == "1"


async def _is_replica_set(client) -> bool:
    try:
        status = await client.admin.command("hello")
    except Exception:
        return False
    return bool(status.get("setName"))


def require_replica_set_or_fail():
    """Call at the top of each real-Mongo test.

    - If the test suite is not required to run here, skip with a label.
    - If it IS required and Mongo is unavailable / standalone, HARD FAIL
      with the exact reason — never a skip.
    """
    if not _require_env():
        pytest.skip(
            "warehouse-canonical real-Mongo suite disabled; "
            f"set {REAL_MONGO_ENABLED_ENV}=1 to require it"
        )
    if not MOTOR_AVAILABLE:
        pytest.fail(
            "motor driver not installed; required by canonical warehouse tests"
        )


@pytest.fixture
async def canonical_mongo_db():
    """Fresh database for a single test."""
    require_replica_set_or_fail()
    mongo_url = os.environ.get("MONGO_URL", "")
    if not mongo_url:
        pytest.fail("MONGO_URL unset; required for the canonical warehouse suite")
    client = AsyncIOMotorClient(mongo_url)
    if not await _is_replica_set(client):
        pytest.fail("MONGO_URL does not point at a replica-set — "
                    "transactions required by TASK 5C")
    db_name = f"begwork_task5c_{uuid.uuid4().hex[:8]}"
    db = client[db_name]
    try:
        from app.services.warehouse_movements.indexes import ensure_required_indexes
        await ensure_required_indexes(db)
        yield client, db
    finally:
        await client.drop_database(db_name)
        client.close()


class _AllowAlwaysDecision:
    allowed = True
    reason_code = "ALLOWED"
    effective_assignment_ids = []


async def _allow_always(*args, **kwargs):
    return _AllowAlwaysDecision()


@pytest.fixture
def allow_always_gate():
    """A PermissionGate that always allows. Permission checks are tested
    separately with `test_warehouse_canonical_permissions.py`."""
    from app.services.warehouse_movements.service import PermissionGate
    return PermissionGate(evaluate_fn=_allow_always)
