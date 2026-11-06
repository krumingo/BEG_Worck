"""
ST-01 — synthetic staging fixtures and the API scenario runner.

Package: docs/architecture/tasks/ST-01_STAGING_FIXTURES_SCENARIOS.md (§Тестове):

* the seed is idempotent (a second run creates and changes nothing);
* it refuses a non-local target without the flag, production names always, and a
  database that holds non-synthetic records;
* it creates exactly the release-gate roles, per tenant;
* tenants A and B do not see each other's records through the API;
* the runner marks a missing function/screen ``blocked``, never ``pass``.

In-process against ``mongomock_motor``; the end-to-end gate also runs against a
disposable local MongoDB when ``W0_03_REAL_MONGO_URL`` is set. Authentication is
real (JWT from ``/api/auth/login``).

    PYTHONPATH=. pytest tests/test_st_01_staging_fixtures.py -v --noconftest
"""
import asyncio
import copy
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
STAGING = BACKEND.parent / "ops" / "staging"
PASSWORD = "ST01-Synthetic-Pass-2026!"
RELEASE_GATE_ROLES = {"owner", "admin", "requester", "approver", "denied", "warehousekeeper",
                      "technician", "accountant", "viewer", "driver"}


def _load(name):
    spec = importlib.util.spec_from_file_location("st01_" + name, STAGING / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed_mod = _load("seed_synthetic")
runner = _load("run_scenarios")
FIXTURE = seed_mod.load_fixture()
SCENARIOS = runner.load_json(runner.SCENARIOS_PATH)


def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


def _mock_dbs():
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()
    return client["st01_op"], client["st01_sys"]


def _app(monkeypatch, op, sysdb):
    """The real routers the scenarios use, pointed at the disposable database."""
    from fastapi import FastAPI

    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.deps import modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.tenancy import registry
    import server  # noqa: F401 — some routers import server constants
    from app.routes import auth, health, procurement, projects, warehouses
    from app.services import audit as services_audit, project_guards
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, deps_modules, utils_audit, services_audit, project_guards):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for name in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, name, sysdb[name])
    app = FastAPI()
    for module in (auth, health, procurement, projects, warehouses):
        monkeypatch.setattr(module, "db", op)
        app.include_router(module.router, prefix="/api")
    return app


async def _snapshot(op, sysdb):
    """Every document of every collection, for 'the second run changed nothing'."""
    out = {}
    for label, database in (("op", op), ("sys", sysdb)):
        for name in sorted(await database.list_collection_names()):
            rows = await database[name].find({}, {"_id": 0}).to_list(None)
            out["%s.%s" % (label, name)] = sorted(json.dumps(r, sort_keys=True, default=str)
                                                  for r in rows)
    return out


# ═══════════════════════════════════════════════════════════════ target refusals
@pytest.mark.parametrize("url", [
    "mongodb://10.0.0.5:27017", "mongodb://nas.local:27017",
    "mongodb+srv://user:pw@cluster0.example.mongodb.net", "mongodb://127.0.0.1,db.example.com",
])
def test_seed_refuses_a_non_local_target_without_the_flag(url):
    with pytest.raises(seed_mod.SeedRefused, match="allow-remote"):
        seed_mod.check_target(url=url, db_name="st01_staging", system_db_name="st01_staging_sys",
                              confirm_db="st01_staging", allow_remote=False, env={})
    # the explicit flag lifts only the host check
    seed_mod.check_target(url=url, db_name="st01_staging", system_db_name="st01_staging_sys",
                          confirm_db="st01_staging", allow_remote=True, env={})


@pytest.mark.parametrize("db_name,sys_name", [
    ("begwork", "st01_sys"), ("begwork_beg", "st01_sys"), ("BegWork_copy", "st01_sys"),
    ("st01_op", "begwork_system"), ("live_db", "st01_sys"),
])
@pytest.mark.parametrize("allow_remote", [False, True])
def test_seed_refuses_production_names_even_with_the_flag(db_name, sys_name, allow_remote):
    with pytest.raises(seed_mod.SeedRefused, match="production name"):
        seed_mod.check_target(url="mongodb://127.0.0.1:27017", db_name=db_name,
                              system_db_name=sys_name, confirm_db=db_name,
                              allow_remote=allow_remote, env={"DB_NAME": "live_db"})


def test_seed_refuses_missing_url_confirmation_and_same_databases():
    ok = dict(url="mongodb://127.0.0.1:27017", db_name="st01_op", system_db_name="st01_sys",
              confirm_db="st01_op", allow_remote=False, env={})
    seed_mod.check_target(**ok)
    for patch, match in (({"url": ""}, "MONGO_URL"), ({"confirm_db": None}, "confirm-db"),
                         ({"confirm_db": "st01_other"}, "confirm-db"),
                         ({"system_db_name": "st01_op"}, "different")):
        with pytest.raises(seed_mod.SeedRefused, match=match):
            seed_mod.check_target(**{**ok, **patch})


def test_cli_refuses_before_connecting(monkeypatch, capsys):
    monkeypatch.setenv("ST01_SEED_PASSWORD", PASSWORD)
    code = seed_mod.main(["--mongo-url", "mongodb://10.1.2.3:27017", "--db", "st01_op",
                          "--system-db", "st01_sys", "--confirm-db", "st01_op"])
    assert code == seed_mod.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "refused" in err and PASSWORD not in err


def test_password_comes_from_env_or_a_terminal_only():
    assert seed_mod.read_password("X", env={"X": PASSWORD}, interactive=False) == PASSWORD
    with pytest.raises(seed_mod.SeedRefused, match="no password"):
        seed_mod.read_password("X", env={}, interactive=False)
    with pytest.raises(seed_mod.SeedRefused, match="at least"):
        seed_mod.read_password("X", env={"X": "short"}, interactive=False)


def test_no_password_or_secret_is_in_the_tracked_files():
    for path in sorted(STAGING.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json", ".md"):
            text = path.read_text(encoding="utf-8")
            assert PASSWORD not in text, path
            assert "password_hash\": \"$2" not in text, path
    # every synthetic email is on the reserved .test domain
    for t in FIXTURE["tenants"]:
        assert t["email_domain"].endswith(".test")


def test_seed_refuses_a_database_with_non_synthetic_records():
    async def body():
        op, sysdb = _mock_dbs()
        await op.users.insert_one({"id": "real", "org_id": "X", "email": "krum@real.bg"})
        with pytest.raises(seed_mod.SeedRefused, match="non-synthetic"):
            await seed_mod.seed(op, sysdb, PASSWORD)
        assert await op.organizations.count_documents({}) == 0
        assert await sysdb.tenant_registry.count_documents({}) == 0
        assert await op.users.count_documents({}) == 1
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ roles and idempotency
def test_fixture_holds_exactly_the_release_gate_roles():
    keys = [r["key"] for r in FIXTURE["roles"]]
    assert len(keys) == len(set(keys))
    assert set(keys) == RELEASE_GATE_ROLES
    from app.permissions.catalog import CANONICAL_ROLES, LEGACY_ROLE_MAP
    from app.core.config import ROLES
    for r in FIXTURE["roles"]:
        assert r["legacy_role"] in ROLES, r
        assert LEGACY_ROLE_MAP[r["legacy_role"]] == r["role_id"], r
        assert r["role_id"] in CANONICAL_ROLES or r["role_id"].startswith("LEGACY_"), r


def test_seed_creates_exactly_the_roles_and_is_idempotent():
    async def body():
        op, sysdb = _mock_dbs()
        first = await seed_mod.seed(op, sysdb, PASSWORD)
        n_roles = len(FIXTURE["roles"])
        assert first["created"]["tenants"] == 2
        assert first["created"]["users"] == 2 * n_roles
        assert await op.users.count_documents({}) == 2 * n_roles
        tenants = await sysdb.tenant_registry.find({}, {"_id": 0}).to_list(None)
        assert sorted(t["fixture_key"] for t in tenants) == ["A", "B"]
        for t in tenants:
            users = await op.users.find({"org_id": t["id"]}, {"_id": 0}).to_list(None)
            assert sorted(u["fixture_role"] for u in users) == sorted(RELEASE_GATE_ROLES)
            by_role = {u["fixture_role"]: u for u in users}
            for r in FIXTURE["roles"]:
                assert by_role[r["key"]]["role"] == r["legacy_role"]
            assert all(u["synthetic_fixture"] == "st-01" for u in users)
            assert all(u["email"].endswith(".st01.test") for u in users)
            # one membership and one active company RoleAssignment per user, this tenant only
            for u in users:
                ms = await sysdb.tenant_memberships.find({"user_id": u["id"]}).to_list(None)
                assert [m["tenant_id"] for m in ms] == [t["id"]], u["fixture_role"]
                ras = await sysdb.tenant_role_assignments.find(
                    {"user_id": u["id"], "status": "active"}).to_list(None)
                assert len(ras) == 1 and ras[0]["tenant_id"] == t["id"], u["fixture_role"]
                assert ras[0]["scope_type"] == "company"
            assert await op.projects.count_documents({"org_id": t["id"]}) == 1
            assert await op.warehouses.count_documents({"org_id": t["id"]}) == 1
        # one canonical AuditEvent per created user, none for the password
        events = await op.audit_events.find({}, {"_id": 0}).to_list(None)
        assert len(events) == 2 * n_roles
        assert PASSWORD not in json.dumps(events, default=str)
        assert PASSWORD not in json.dumps(first, default=str)
        assert "password_hash" not in json.dumps(first, default=str)

        snap = await _snapshot(op, sysdb)
        second = await seed_mod.seed(op, sysdb, PASSWORD)
        assert all(v == 0 for v in second["created"].values()), second["created"]
        assert all(v == 0 for v in second["updated"].values()), second["updated"]
        assert await _snapshot(op, sysdb) == snap, "a second run changed the database"
        assert [t["tenant_id"] for t in second["tenants"]] == [t["tenant_id"] for t in first["tenants"]]
    asyncio.run(body())


def test_seed_repairs_a_drifted_role_once_with_an_audit_event():
    async def body():
        op, sysdb = _mock_dbs()
        await seed_mod.seed(op, sysdb, PASSWORD)
        await op.users.update_one({"fixture_role": "denied", "email": {"$regex": "tenant-a"}},
                                  {"$set": {"role": "Admin"}})
        before = await op.audit_events.count_documents({})
        report = await seed_mod.seed(op, sysdb, PASSWORD)
        assert report["updated"]["users"] == 1
        assert await op.audit_events.count_documents({}) == before + 1
        user = await op.users.find_one({"fixture_role": "denied", "email": {"$regex": "tenant-a"}})
        assert user["role"] == "Viewer"
        again = await seed_mod.seed(op, sysdb, PASSWORD)
        assert again["updated"]["users"] == 0
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ API: isolation + runner
async def _end_to_end(op, sysdb, monkeypatch):
    import httpx
    await seed_mod.seed(op, sysdb, PASSWORD)
    app = _app(monkeypatch, op, sysdb)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://st01") as c:
        result = await runner.run(c, SCENARIOS, FIXTURE, PASSWORD, base_url="http://st01")

        # independent isolation proof, not through the runner's own helpers
        tokens = {}
        for t in FIXTURE["tenants"]:
            r = await c.post("/api/auth/login", json={
                "email": seed_mod.user_email(t, {"key": "owner"}), "password": PASSWORD})
            assert r.status_code == 200
            tokens[t["key"]] = {"Authorization": "Bearer " + r.json()["token"]}
        ids = {t["key"]: seed_mod.stable_id(t["key"], "project", t["project"]["code"])
               for t in FIXTURE["tenants"]}
        for mine, theirs in (("A", "B"), ("B", "A")):
            r = await c.get("/api/projects/%s" % ids[theirs], headers=tokens[mine])
            assert r.status_code == 404, (mine, r.status_code)
            r = await c.get("/api/material-requests", headers=tokens[mine])
            assert r.status_code == 200
            own_org = (await sysdb.tenant_registry.find_one({"fixture_key": mine}))["id"]
            rows = r.json()
            assert all(row["org_id"] == own_org for row in rows), (mine, rows)
        reqs_b = await op.material_requests.count_documents(
            {"org_id": (await sysdb.tenant_registry.find_one({"fixture_key": "B"}))["id"]})
        assert reqs_b == 0, "the runner's B-side attempts wrote into tenant B"
    return result


def _assert_result(result):
    by_id = {s["id"]: s for s in result["scenarios"]}
    assert set(by_id) == {s["id"] for s in SCENARIOS["scenarios"]}
    steps = {(s["id"], st["id"]): st for s in result["scenarios"] for st in s["steps"]}
    failed = [(k, v.get("reason")) for k, v in steps.items() if v["status"] == "fail"]
    assert not failed, failed
    # every implemented API check passed on main
    for key, st in steps.items():
        if st.get("api_check") in runner.CHECKS:
            assert st["status"] == "pass", (key, st)
    # S03 isolation steps ran and passed
    for step in ("login-all-roles", "cross-tenant-project", "cross-tenant-warehouse",
                 "cross-tenant-request", "denied-zero-write"):
        assert steps[("S03-roles-isolation", step)]["status"] == "pass"
    # a missing function/screen is blocked — and so is every scenario that has one
    for sc in SCENARIOS["scenarios"]:
        has_blocked = any(st.get("blocked") or st.get("ui") for st in sc["steps"])
        if has_blocked:
            assert by_id[sc["id"]]["status"] == "blocked", sc["id"]
    assert result["summary"]["scenarios"]["pass"] == 0, "no scenario is complete on main"
    assert result["summary"]["scenarios"]["blocked"] == len(SCENARIOS["scenarios"])
    # a live backend with passing API checks is evidence: exit 0 (ST-01-C01)
    assert result["outcome"] == {"exit_code": runner.EXIT_OK, "status": "ok", "reasons": []}
    text = json.dumps(result, ensure_ascii=False)
    assert PASSWORD not in text and "password_hash" not in text and "token" not in text.lower()


def test_tenants_are_isolated_over_the_api_and_the_runner_writes_its_result(monkeypatch):
    async def body():
        op, sysdb = _mock_dbs()
        return await _end_to_end(op, sysdb, monkeypatch)
    _assert_result(asyncio.run(body()))


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_the_end_to_end_gate_on_a_real_disposable_mongodb(monkeypatch):
    from motor.motor_asyncio import AsyncIOMotorClient
    from tests.test_w0_03c_real_mongo import REAL_URL
    suffix = uuid.uuid4().hex[:10]
    op_name, sys_name = "st01_op_" + suffix, "st01_sys_" + suffix

    async def body():
        client = AsyncIOMotorClient(REAL_URL)
        try:
            result = await _end_to_end(client[op_name], client[sys_name], monkeypatch)
            snap = await _snapshot(client[op_name], client[sys_name])
            again = await seed_mod.seed(client[op_name], client[sys_name], PASSWORD)
            assert all(v == 0 for v in again["created"].values())
            assert await _snapshot(client[op_name], client[sys_name]) == snap
            return result
        finally:
            await client.drop_database(op_name)
            await client.drop_database(sys_name)
            client.close()
    _assert_result(asyncio.run(body()))


# ═══════════════════════════════════════════════════════════════ runner semantics
def test_runner_never_passes_a_missing_function_screen_or_check():
    doc = {"scenarios": [
        {"id": "X1", "title": "missing function", "steps": [
            {"id": "s", "action": "a", "blocked": "NO_CANONICAL_FUNCTION", "reason": "absent",
             "api_check": "health.api_up"}]},
        {"id": "X2", "title": "ui only", "steps": [{"id": "s", "action": "a", "ui": True}]},
        {"id": "X3", "title": "unknown check", "steps": [{"id": "s", "action": "a",
                                                           "api_check": "does.not.exist"}]},
        {"id": "X4", "title": "no steps", "steps": []},
    ]}

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("a blocked step must not call the backend")

    result = asyncio.run(runner.run(NoNetwork(), doc, FIXTURE, PASSWORD))
    for sc in result["scenarios"]:
        assert sc["status"] == "blocked", sc
        for st in sc["steps"]:
            assert st["status"] == "blocked" and st["reason_code"], st
    codes = [st["reason_code"] for sc in result["scenarios"] for st in sc["steps"]]
    assert codes == ["NO_CANONICAL_FUNCTION", "UI_NOT_RUN_BY_API_RUNNER", "NO_RUNNER_CHECK"]
    assert result["summary"]["scenarios"] == {"pass": 0, "fail": 0, "blocked": 4}


def test_scenario_status_rules():
    s = runner.scenario_status
    assert s(["pass", "pass"]) == "pass"
    assert s(["pass", "blocked"]) == "blocked"
    assert s(["blocked", "fail", "pass"]) == "fail"
    assert s([]) == "blocked"


def test_runner_reports_a_failed_assertion_and_an_unreachable_backend():
    import httpx

    def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(503, json={"status": "down"})
        raise httpx.ConnectError("refused", request=request)

    doc = {"scenarios": [{"id": "Y", "title": "y", "steps": [
        {"id": "h", "action": "a", "api_check": "health.api_up"},
        {"id": "l", "action": "a", "api_check": "auth.owner_login"}]}]}

    async def body():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url="http://st01") as c:
            return await runner.run(c, doc, FIXTURE, PASSWORD)
    result = asyncio.run(body())
    steps = result["scenarios"][0]["steps"]
    assert steps[0]["status"] == "fail" and "503" in steps[0]["reason"]
    assert steps[1]["status"] == "blocked" and steps[1]["reason_code"] == "UNREACHABLE"
    assert result["scenarios"][0]["status"] == "fail"


# ═══════════════════════════════════════════════════════════════ ST-01-C01 (audit PST-1)
def _closed_local_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]  # closed again on exit: nothing listens there


def test_runner_against_a_dead_backend_exits_non_zero_and_says_why(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ST01_SEED_PASSWORD", PASSWORD)
    out = tmp_path / "result.json"
    url = "http://127.0.0.1:%d" % _closed_local_port()
    code = runner.main(["--base-url", url, "--out", str(out), "--timeout", "2"])
    assert code == runner.EXIT_NO_EVIDENCE != runner.EXIT_OK
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["summary"]["steps"]["pass"] == 0 and result["summary"]["steps"]["fail"] == 0
    verdict = result["outcome"]
    assert verdict["exit_code"] == code and verdict["status"] == "no_evidence"
    codes = [r["code"] for r in verdict["reasons"]]
    assert codes == ["BACKEND_UNREACHABLE", "NOTHING_PASSED"], verdict
    assert url in verdict["reasons"][0]["detail"] and "UNREACHABLE" in verdict["reasons"][0]["detail"]
    assert "BACKEND_UNREACHABLE" in capsys.readouterr().err
    assert PASSWORD not in out.read_text(encoding="utf-8")


def test_runner_outcome_rules():
    def sc(*steps):
        return [{"steps": [dict(st) for st in steps]}]
    ok = {"status": "pass"}
    blocked = {"status": "blocked", "reason_code": "NO_SCREEN"}
    down = {"status": "blocked", "reason_code": "UNREACHABLE", "reason": "UNREACHABLE: ConnectError"}
    fail = {"status": "fail", "reason": "x"}
    o = runner.outcome
    assert o(sc(ok, blocked)) == {"exit_code": 0, "status": "ok", "reasons": []}
    nothing = o(sc(blocked, blocked))  # all blocked, backend never asked: still no evidence
    assert nothing["exit_code"] == runner.EXIT_NO_EVIDENCE
    assert [r["code"] for r in nothing["reasons"]] == ["NOTHING_PASSED"]
    assert o(sc())["exit_code"] == runner.EXIT_NO_EVIDENCE
    partial = o(sc(ok, down), "http://127.0.0.1:8001")  # some passed, then the backend died
    assert partial["exit_code"] == runner.EXIT_NO_EVIDENCE
    assert [r["code"] for r in partial["reasons"]] == ["BACKEND_UNREACHABLE"]
    assert "http://127.0.0.1:8001" in partial["reasons"][0]["detail"]
    failed = o(sc(fail, down))  # a failed assertion stays exit 1, with every reason listed
    assert failed["exit_code"] == runner.EXIT_FAILED and failed["status"] == "failed"
    assert [r["code"] for r in failed["reasons"]] == ["STEP_FAILED", "BACKEND_UNREACHABLE", "NOTHING_PASSED"]


def test_runner_refuses_a_non_local_base_url_without_the_flag(monkeypatch, tmp_path):
    for url in ("https://beg.example.com", "http://192.168.1.20:8001", "ftp://127.0.0.1"):
        with pytest.raises(runner.Refused):
            runner.check_base_url(url, allow_remote=False)
    runner.check_base_url("http://127.0.0.1:8001", allow_remote=False)
    runner.check_base_url("http://192.168.1.20:8001", allow_remote=True)
    monkeypatch.delenv("ST01_SEED_PASSWORD", raising=False)
    out = tmp_path / "result.json"
    assert runner.main(["--base-url", "http://127.0.0.1:8001", "--out", str(out)]) == runner.EXIT_REFUSED
    assert not out.exists()


def test_scenario_list_is_well_formed_and_covers_krums_table():
    titles = [s["title"] for s in SCENARIOS["scenarios"]]
    assert titles == [
        "Build identity", "Owner login/recovery", "Roles and isolation",
        "Project → SMR → material request", "Request submit/approve/reject",
        "Receive → dispatch → partial accept", "Stock issue/consume/return",
        "Payroll recovery regression", "Finance and exports",
        "Daily report → quantity → act → invoice → payment", "Phone 390×844",
        "Failure and restart"]
    role_keys = {r["key"] for r in FIXTURE["roles"]}
    ids = set()
    for sc in SCENARIOS["scenarios"]:
        assert sc["id"] not in ids
        ids.add(sc["id"])
        assert sc["flows"] and all(f.startswith("FLOW-0") for f in sc["flows"]), sc["id"]
        assert set(sc["roles"]) <= role_keys, sc["id"]
        assert sc["expected"] and sc["steps"], sc["id"]
        for st in sc["steps"]:
            assert st.get("api_check") or st.get("ui") or st.get("blocked"), (sc["id"], st["id"])
            if st.get("blocked"):
                assert st["blocked"] in ("NO_CANONICAL_FUNCTION", "NO_SCREEN", "NO_RUNNER_CHECK")
                assert st.get("reason"), (sc["id"], st["id"])
            if st.get("api_check") and not st.get("blocked"):
                assert st["api_check"] in runner.CHECKS, (sc["id"], st["id"])
    # mutation: dropping the 'blocked' marker of a missing function must not turn it into a pass
    doc = copy.deepcopy(SCENARIOS)
    step = doc["scenarios"][4]["steps"][1]
    assert step["id"] == "approve-reject"
    step.pop("blocked")
    result = asyncio.run(runner.run(object(), {"scenarios": [doc["scenarios"][4]]}, FIXTURE, PASSWORD))
    st = [s for s in result["scenarios"][0]["steps"] if s["id"] == "approve-reject"][0]
    assert st["status"] == "blocked" and st["reason_code"] == "NO_RUNNER_CHECK"
