"""
R0-07 — POST /api/dev/reset-warehouses works only in dev/test (AUD-039).

The 7 cases of docs/architecture/tasks/R0-07_DEV_RESET_DEV_TEST_ONLY.md:

1. ``ENV`` unset → 404, warehouses byte-equal;
2. ``ENV`` = production / staging / prod / empty / random → 404, nothing written;
3. ``ENVIRONMENT=development`` without ``ENV`` (the old bypass) → 404;
4. ``ENV`` = development / test, Admin or Owner → works (per warehouse, through the guard);
5. ``ENV=test``, SiteManager / Warehousekeeper / Technician → 403, nothing written;
6. two firms: reset of A leaves B untouched;
7. mutation: 1–3 and 5 fail on main (run by hand, see docs/evidence/R0-07).

Also: the env gate runs before authentication (no token → 404 outside dev/test, 401 inside).

Runs on ``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL`` names a disposable LOCAL
MongoDB, again against it.

    PYTHONPATH=. pytest tests/test_r0_07_dev_reset.py -v --noconftest
"""
import asyncio

import pytest

from tests.test_r0_05_pay_run_selected_only import _Db, _real_refusal, _token

ORG_A, ORG_B = "ORG-R007-A", "ORG-R007-B"
ROLES_A = {"admin-a": "Admin", "owner-a": "Owner", "sm-a": "SiteManager",
           "wk-a": "Warehousekeeper", "tech-a": "Technician"}
URL = "/api/dev/reset-warehouses"


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


def hdr(uid):
    org, role = (ORG_B, "Admin") if uid == "admin-b" else (ORG_A, ROLES_A[uid])
    return _token(uid, org, role)


async def _seed(op):
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
    for uid, role in list(ROLES_A.items()) + [("admin-b", "Admin")]:
        await op.users.insert_one({"id": uid, "org_id": ORG_B if uid == "admin-b" else ORG_A,
                                   "role": role, "is_active": True, "email": uid + "@r007.example",
                                   "first_name": uid, "last_name": "Staff"})
    await op.warehouses.insert_many(
        [{"id": "wh-a%d" % i, "org_id": ORG_A, "name": "A%d" % i, "active": True} for i in (1, 2, 3)]
        + [{"id": "wh-b%d" % i, "org_id": ORG_B, "name": "B%d" % i, "active": True} for i in (1, 2)])


def _app(monkeypatch, op):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.master_data.deps import ENV_MODE
    from app.routes import warehouses

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, warehouses):
        monkeypatch.setattr(module, "db", op)
    app = FastAPI()
    app.include_router(warehouses.router, prefix="/api")
    return app


def run(monkeypatch, backend, scenario):
    import httpx

    async def go():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r007") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def _snap(op):
    return await op.warehouses.find({}, {"_id": 0}).sort("id", 1).to_list(None)


def _env(monkeypatch, value):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    if value is not None:
        monkeypatch.setenv("ENV", value)


def _refused(monkeypatch, backend, who, status):
    async def scenario(c, op):
        before = await _snap(op)
        r = await c.post(URL, headers=hdr(who))
        assert r.status_code == status, r.text
        assert "deleted_count" not in r.text
        assert await _snap(op) == before
    run(monkeypatch, backend, scenario)


def test_01_env_unset_is_404(monkeypatch, backend):
    _env(monkeypatch, None)
    _refused(monkeypatch, backend, "admin-a", 404)


@pytest.mark.parametrize("value", ["production", "staging", "prod", "", "  ", "dev", "Production", "banana",
                                   "TEST", "Test", "Development", "DEVELOPMENT", " test ", " development ",
                                   "test\n", "development\n", "\ttest", "test "])
def test_02_other_env_is_404(monkeypatch, backend, value):
    _env(monkeypatch, value)
    _refused(monkeypatch, backend, "admin-a", 404)


@pytest.mark.parametrize("legacy", ["development", "test", "production"])
def test_03_old_environment_variable_is_no_bypass(monkeypatch, backend, legacy):
    _env(monkeypatch, None)
    monkeypatch.setenv("ENVIRONMENT", legacy)
    _refused(monkeypatch, backend, "admin-a", 404)


def test_03b_environment_cannot_override_env(monkeypatch, backend):
    _env(monkeypatch, "production")
    monkeypatch.setenv("ENVIRONMENT", "development")
    _refused(monkeypatch, backend, "owner-a", 404)


@pytest.mark.parametrize("env", ["development", "test"])
@pytest.mark.parametrize("who", ["admin-a", "owner-a"])
def test_04_dev_test_admin_owner_works(monkeypatch, backend, env, who):
    _env(monkeypatch, env)

    async def scenario(c, op):
        r = await c.post(URL, headers=hdr(who))
        assert r.status_code == 200, r.text
        assert r.json()["deleted_count"] == 3 and r.json()["ok"] is True
        assert [w["id"] for w in await _snap(op)] == ["wh-b1", "wh-b2"]
    run(monkeypatch, backend, scenario)


@pytest.mark.parametrize("who", ["sm-a", "wk-a", "tech-a"])
def test_05_other_roles_are_403(monkeypatch, backend, who):
    _env(monkeypatch, "test")
    _refused(monkeypatch, backend, who, 403)


@pytest.mark.parametrize("who", ["sm-a", "wk-a", "tech-a", "admin-a"])
def test_05b_other_roles_are_404_outside_dev_test(monkeypatch, backend, who):
    _env(monkeypatch, "production")
    _refused(monkeypatch, backend, who, 404)


def test_06_two_firms_are_isolated(monkeypatch, backend):
    _env(monkeypatch, "test")

    async def scenario(c, op):
        before_b = [w for w in await _snap(op) if w["org_id"] == ORG_B]
        assert (await c.post(URL, headers=hdr("admin-a"))).status_code == 200
        assert [w for w in await _snap(op) if w["org_id"] == ORG_B] == before_b
        assert await op.warehouses.count_documents({"org_id": ORG_A}) == 0
        assert (await c.post(URL, headers=hdr("admin-b"))).json()["deleted_count"] == 2
    run(monkeypatch, backend, scenario)


def test_07_env_gate_runs_before_authentication(monkeypatch, backend):
    async def scenario(c, op):
        _env(monkeypatch, "production")
        assert (await c.post(URL)).status_code == 404
        assert (await c.post(URL, headers={"Authorization": "Bearer junk"})).status_code == 404
        _env(monkeypatch, "test")
        assert (await c.post(URL)).status_code in (401, 403)
        assert len(await _snap(op)) == 5
    run(monkeypatch, backend, scenario)


def test_08_billing_still_normalizes_env_but_reset_does_not(monkeypatch):
    from app.core.stripe_config import is_mock_billing_allowed
    from app.routes.warehouses import _require_dev_or_test_env
    from fastapi import HTTPException
    monkeypatch.setenv("BILLING_PROVIDER", "mock")
    monkeypatch.setenv("ENV", " TEST ")
    assert is_mock_billing_allowed() is True          # R0-01 behaviour, untouched
    with pytest.raises(HTTPException) as e:
        _require_dev_or_test_env()                    # R0-07-C01: strict
    assert e.value.status_code == 404
    for ok in ("development", "test"):
        monkeypatch.setenv("ENV", ok)
        assert _require_dev_or_test_env() is None
    monkeypatch.delenv("ENV")
    with pytest.raises(HTTPException):
        _require_dev_or_test_env()
