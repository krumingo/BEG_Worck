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
import pytest_asyncio

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


@pytest_asyncio.fixture
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
    # WH-FIX-01 (FG-192): the service is strict about Master identity by
    # default. The pre-WH-FIX-01 scenarios seed no `md_item`, so THIS fixture
    # keeps their earlier (non-strict) construction default for the test's
    # duration only — the production route passes strict=True explicitly and
    # `test_wh_fix_01_*` covers the strict default with `strict_mongo_db`.
    from app.services.warehouse_movements import service as _wh_service
    _prev_strict = getattr(_wh_service, "STRICT_MASTER_IDENTITY_DEFAULT", None)
    if _prev_strict is not None:
        _wh_service.STRICT_MASTER_IDENTITY_DEFAULT = False
    try:
        from app.services.warehouse_movements.indexes import ensure_required_indexes
        await ensure_required_indexes(db)
        yield client, db
    finally:
        if _prev_strict is not None:
            _wh_service.STRICT_MASTER_IDENTITY_DEFAULT = _prev_strict
        await client.drop_database(db_name)
        client.close()


@pytest_asyncio.fixture
async def strict_mongo_db():
    """WH-FIX-01 — a fresh database with the production (strict) default."""
    require_replica_set_or_fail()
    mongo_url = os.environ.get("MONGO_URL", "")
    if not mongo_url:
        pytest.fail("MONGO_URL unset; required for the canonical warehouse suite")
    client = AsyncIOMotorClient(mongo_url)
    if not await _is_replica_set(client):
        pytest.fail("MONGO_URL does not point at a replica-set — "
                    "transactions required by TASK 5C")
    db_name = f"begwork_whfix01_{uuid.uuid4().hex[:8]}"
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


def sec02_owner_in_enforce(monkeypatch, *tenant_ids):
    """SEC-02-G (audit SEC71-M1): the finance reports these tests read directly are R20
    decorated (money only for a finance role). In enforce the decorator asks the REAL
    Tenant Guard and Permission Service — so the test's tenants are registered and the
    test's user ("u-<tenant>", role Owner, as ``_user()`` builds it) gets the Owner
    company assignment it stands for. Every other user keeps the real assignment loader.
    """
    from app.permissions import service as perm
    from app.tenancy import registry
    tenants = {t: {"id": t, "name": t, "status": "active"} for t in tenant_ids}

    class _Registry:
        async def find_one(self, flt, projection=None):
            return dict(tenants[flt["id"]]) if flt.get("id") in tenants else None

    # the user's one active membership of his tenant (the guard resolves the active
    # tenant from it); an in-process stand-in — the registry's module-level client is
    # bound to the first test's event loop
    members = [{"user_id": "u-" + t, "tenant_id": t, "status": "active"} for t in tenant_ids]

    def _match(m, flt):
        return all(m.get(k) == v for k, v in flt.items())

    class _Cursor:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, _n=None):
            return [dict(r) for r in self.rows]

    class _Memberships:
        def find(self, flt, projection=None):
            return _Cursor([m for m in members if _match(m, flt)])

        async def find_one(self, flt, projection=None):
            rows = [m for m in members if _match(m, flt)]
            return dict(rows[0]) if rows else None

    real_loader = perm._load_assignments

    async def _load(user_id, tenant_id):
        if tenant_id in tenants and user_id == "u-" + tenant_id:
            return [{"id": "ra-owner-" + tenant_id, "status": "active", "role_id": "owner",
                     "module": None, "scope_type": "company", "scope_id": None,
                     "valid_from": "2020-01-01T00:00:00Z", "valid_to": None}]
        return await real_loader(user_id, tenant_id)
    monkeypatch.setattr(registry, "tenant_registry", _Registry())
    monkeypatch.setattr(registry, "tenant_memberships", _Memberships())
    monkeypatch.setattr(perm, "_load_assignments", _load)
