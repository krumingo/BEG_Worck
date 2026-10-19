"""
R0-03 — roles without escalation, one email = one User (AUD-025, AUTH-01 F-03).

The 17 rows of docs/architecture/tasks/R0-03_ROLES_EMAIL.md, positive and forbidden:

1.  Accountant → ``/employees/{self}/basic`` with ``role=Admin`` → 400, role byte-equal;
2.  Accountant/Admin → ``/basic`` with ``email`` → 400, nothing written;
3.  ``/basic`` with name/phone only → 200 as before;
4.  Admin → ``PUT /users/{x}`` ``role=Owner`` (and ``POST /users`` with Owner) → 403;
5.  Admin → role / ``is_active`` of an Owner → 403;
6.  Admin → ``/admin/set-password/{owner}`` → 403, hash byte-equal;
7.  Admin → ``DELETE /users/{owner}`` → 403;
8.  anyone → own role → 403;
9.  Owner: Admin → Viewer, Viewer → Admin → 200 + AuditEvent (before/after, no secret);
10. the last active Owner cannot be demoted / deactivated / deleted → 409;
11. creating a user with an email of another firm, or ``Ivan@X.bg `` next to
    ``ivan@x.bg`` → 409 ``EMAIL_EXISTS`` (``POST /users``, signup/onboarding,
    platform bootstrap creates nothing);
12. login with an email held by 2 Users → 409 ``DUPLICATE_IDENTITY``, no token;
13. login with ``IVAN@x.bg`` for ``ivan@x.bg`` → logs in;
14. two firms: nothing of A touches B, a foreign User is 404;
15. the duplicates report on a fixture with 2 duplicates → reports them, DB byte-equal;
16. mutation: run by hand against ``main`` (docs/evidence/R0-03);
17. every role row runs in ``off``, ``shadow`` and ``enforce`` with the same outcome.

Runs on ``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL`` names a disposable
LOCAL MongoDB, again against it (one operational + one system database per test,
dropped afterwards). Authentication is real: a JWT the route verifies and a user
``get_current_user`` loads from the database.

    PYTHONPATH=. pytest tests/test_r0_03_roles_email.py -v --noconftest
"""
import asyncio
import uuid

import pytest

from tests.test_r0_05_pay_run_selected_only import _real_refusal, _token

ORG_A, ORG_B = "ORG-R003-A", "ORG-R003-B"
PASSWORD = "R003-test-only-Pass1!"
USERS = {   # id -> (org, role)
    "owner-a": (ORG_A, "Owner"), "owner2-a": (ORG_A, "Owner"), "admin-a": (ORG_A, "Admin"),
    "admin2-a": (ORG_A, "Admin"), "acct-a": (ORG_A, "Accountant"), "viewer-a": (ORG_A, "Viewer"),
    "owner-b": (ORG_B, "Owner"), "admin-b": (ORG_B, "Admin"), "ivan-b": (ORG_B, "Viewer"),
}
EMAILS = {"ivan-b": "ivan@x.bg"}
MODES = ["off", "shadow", "enforce"]


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


def email_of(uid):
    return EMAILS.get(uid, uid + "@r003.example")


def hdr(uid):
    org, role = USERS[uid]
    return _token(uid, org, role)


# ═══════════════════════════════════════════════════════════════════ harness
_HASH = {}


def _hash():
    if "h" not in _HASH:
        from app.deps.auth import hash_password
        _HASH["h"] = hash_password(PASSWORD)
    return _HASH["h"]


class _Dbs:
    """Fresh operational + system databases on the chosen backend."""

    def __init__(self, backend):
        tag = uuid.uuid4().hex[:10]
        self.backend, self.client, self.names = backend, None, ("r0_03_op_" + tag, "r0_03_sys_" + tag)

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.names[0]], self.client[self.names[1]]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            for name in self.names:
                await self.client.drop_database(name)
            left = await self.client.list_database_names()
            assert not set(self.names) & set(left)
            self.client.close()


async def _seed(op, sysdb):
    from app.permissions.catalog import LEGACY_ROLE_MAP
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
        await op.subscriptions.insert_one({"id": "sub-" + org, "org_id": org, "plan_id": "enterprise",
                                           "status": "active"})
        await sysdb.tenant_registry.insert_one({"id": org, "legacy_org_id": org, "status": "active",
                                                "database_name": op.name})
    for uid, (org, role) in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": org, "role": role, "is_active": True,
                                   "email": email_of(uid), "password_hash": _hash(),
                                   "first_name": uid, "last_name": "Staff", "phone": "000"})
        await sysdb.tenant_memberships.insert_one({"id": "tm_%s_%s" % (uid, org), "user_id": uid,
                                                   "tenant_id": org, "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_%s_%s" % (uid, org), "user_id": uid, "tenant_id": org,
            "role_id": LEGACY_ROLE_MAP[role], "scope_type": "company", "scope_id": None,
            "module": None, "permissions": [], "status": "active", "sync_source": "users.role"})


def _app(monkeypatch, op, sysdb, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth, modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.routes import auth as r_auth, hr as r_hr, platform as r_platform
    from app.tenancy import guard, registry, resolver
    from app.utils import audit as u_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    for module in (appdb, deps_auth, deps_modules, r_auth, r_hr, r_platform, u_audit):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for coll in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, coll, sysdb[coll])

    async def _get_db(tenant_id, require_operational=False):
        t = await registry.get_tenant(tenant_id)
        if not t:
            raise resolver.TenantNotFound(tenant_id)
        assert registry.resolve_database_name(t) == op.name
        return op
    monkeypatch.setattr(resolver, "get_tenant_db", _get_db)
    monkeypatch.setattr(guard, "get_tenant_db", _get_db)
    app = FastAPI()
    for router in (r_auth.router, r_hr.router):
        app.include_router(router, prefix="/api")
    app.include_router(r_platform.router)              # carries its own /api/platform prefix
    return app


def run(monkeypatch, backend, mode, scenario, extra_seed=None):
    import httpx

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _seed(op, sysdb)
            if extra_seed:
                await extra_seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r003") as c:
                return await scenario(c, op, sysdb)
    return asyncio.run(go())


async def snap(op, *colls):
    """Byte-level snapshot of the given collections (default: users)."""
    import bson
    out = {}
    for coll in colls or ("users",):
        docs = await op[coll].find({}, {"_id": 0}).to_list(None)
        out[coll] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d)}) for d in docs)
    return out


async def user(op, uid, org=None):
    flt = {"id": uid}
    if org:
        flt["org_id"] = org
    return await op.users.find_one(flt, {"_id": 0})


async def events(op, action):
    return await op.audit_events.find({"action": action}, {"_id": 0}).to_list(None)


def code_of(r):
    d = r.json().get("detail")
    return d.get("error_code") if isinstance(d, dict) else None


def _refused(monkeypatch, backend, mode, who, method, url, body, status, code=None,
             colls=("users",), extra_seed=None):
    """``who`` sends the request → ``status`` (and ``code``); ``colls`` byte-equal."""
    async def scenario(c, op, sysdb):
        before = await snap(op, *colls)
        r = await c.request(method, url, json=body, headers=hdr(who))
        assert r.status_code == status, r.text
        if code:
            assert code_of(r) == code, r.text
        assert await snap(op, *colls) == before
        return r
    return run(monkeypatch, backend, mode, scenario, extra_seed)


# ════════════════════════════════════════════════ 1–3  /employees/{id}/basic
def test_01_accountant_cannot_change_own_role_via_basic(monkeypatch, backend, mode):
    r = _refused(monkeypatch, backend, mode, "acct-a", "PUT", "/api/employees/acct-a/basic",
                 {"role": "Admin"}, 400, "FIELD_NOT_ALLOWED")
    assert r.json()["detail"]["fields"] == ["role"]


@pytest.mark.parametrize("body", [{"role": "Owner", "first_name": "X"}, {"role": ""}, {"role": None}])
def test_01b_role_key_in_any_form_is_refused_whole(monkeypatch, backend, mode, body):
    _refused(monkeypatch, backend, mode, "admin-a", "PUT", "/api/employees/viewer-a/basic", body, 400,
             "FIELD_NOT_ALLOWED")


@pytest.mark.parametrize("who,target", [("acct-a", "acct-a"), ("acct-a", "owner-a"),
                                        ("admin-a", "viewer-a"), ("owner-a", "admin-a")])
def test_02_email_via_basic_is_refused(monkeypatch, backend, mode, who, target):
    _refused(monkeypatch, backend, mode, who, "PUT", "/api/employees/%s/basic" % target,
             {"email": "new@r003.example", "phone": "111"}, 400, "FIELD_NOT_ALLOWED")


def test_03_basic_name_phone_still_works(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        before = await user(op, "viewer-a")
        r = await c.put("/api/employees/viewer-a/basic", headers=hdr("acct-a"),
                        json={"first_name": "Иван", "last_name": "Петров", "phone": "+359888"})
        assert r.status_code == 200, r.text
        after = await user(op, "viewer-a")
        assert (after["first_name"], after["last_name"], after["phone"]) == ("Иван", "Петров", "+359888")
        assert (after["role"], after["email"]) == (before["role"], before["email"])
        assert r.json()["role"] == "Viewer"
    run(monkeypatch, backend, mode, scenario)


# ════════════════════════════════════════════════ 4–8  escalation / Owner
def test_04_admin_cannot_grant_owner(monkeypatch, backend, mode):
    _refused(monkeypatch, backend, mode, "admin-a", "PUT", "/api/users/viewer-a", {"role": "Owner"},
             403, "ROLE_ABOVE_OWN_FORBIDDEN", colls=("users", "audit_events"))


def test_04b_admin_cannot_create_an_owner(monkeypatch, backend, mode):
    _refused(monkeypatch, backend, mode, "admin-a", "POST", "/api/users",
             {"email": "boss@r003.example", "password": PASSWORD, "first_name": "B", "last_name": "B",
              "role": "Owner"}, 403, "ROLE_ABOVE_OWN_FORBIDDEN")


@pytest.mark.parametrize("body", [{"role": "Viewer"}, {"role": "Admin"}, {"is_active": False},
                                  {"role": "Viewer", "first_name": "x"}])
def test_05_admin_cannot_change_an_owner(monkeypatch, backend, mode, body):
    _refused(monkeypatch, backend, mode, "admin-a", "PUT", "/api/users/owner-a", body, 403,
             "OWNER_CHANGE_REQUIRES_OWNER", colls=("users", "audit_events"))


def test_05b_admin_may_still_rename_an_owner(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        r = await c.put("/api/users/owner-a", json={"first_name": "Крум", "role": "Owner"},
                        headers=hdr("admin-a"))
        assert r.status_code == 200, r.text
        u = await user(op, "owner-a")
        assert (u["first_name"], u["role"], u["is_active"]) == ("Крум", "Owner", True)
    run(monkeypatch, backend, mode, scenario)


def test_06_admin_cannot_reset_owner_password(monkeypatch, backend, mode):
    _refused(monkeypatch, backend, mode, "admin-a", "POST", "/api/admin/set-password/owner-a",
             {"new_password": "Another-Pass-123!"}, 403, "OWNER_CHANGE_REQUIRES_OWNER",
             colls=("users", "audit_logs", "audit_events"))


@pytest.mark.parametrize("who,target", [("owner-a", "owner2-a"), ("owner-a", "admin-a"),
                                        ("admin-a", "viewer-a"), ("admin-a", "admin2-a")])
def test_06b_allowed_password_resets_still_work(monkeypatch, backend, mode, who, target):
    async def scenario(c, op, sysdb):
        before = (await user(op, target))["password_hash"]
        r = await c.post("/api/admin/set-password/" + target, json={"new_password": "Another-Pass-123!"},
                         headers=hdr(who))
        assert r.status_code == 200, r.text
        assert (await user(op, target))["password_hash"] != before
        ev = await events(op, "user.admin_password_reset")
        assert len(ev) == 1 and ev[0]["entity_id"] == target and ev[0]["actor_id"] == who
        assert "Another-Pass" not in str(ev) and "$2b$" not in str(ev)
    run(monkeypatch, backend, mode, scenario)


def test_07_admin_cannot_delete_owner(monkeypatch, backend, mode):
    _refused(monkeypatch, backend, mode, "admin-a", "DELETE", "/api/users/owner-a", None, 403,
             "OWNER_CHANGE_REQUIRES_OWNER", colls=("users", "audit_logs", "audit_events"))


def test_07b_owner_deletes_another_owner_when_one_remains(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        r = await c.delete("/api/users/owner2-a", headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        assert await user(op, "owner2-a") is None
        ev = await events(op, "user.deleted")
        assert len(ev) == 1 and ev[0]["structured_diff"]["before"]["role"] == "Owner"
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("who,role", [("admin-a", "Viewer"), ("admin-a", "Owner"),
                                      ("owner-a", "Admin"), ("owner-a", "Viewer")])
def test_08_nobody_changes_their_own_role(monkeypatch, backend, mode, who, role):
    code = "ROLE_ABOVE_OWN_FORBIDDEN" if (who, role) == ("admin-a", "Owner") else "OWN_ROLE_CHANGE_FORBIDDEN"
    _refused(monkeypatch, backend, mode, who, "PUT", "/api/users/" + who, {"role": role}, 403,
             code if role != "Owner" else None, colls=("users", "audit_events"))


def test_08b_accountant_cannot_use_put_users_at_all(monkeypatch, backend, mode):
    _refused(monkeypatch, backend, mode, "acct-a", "PUT", "/api/users/acct-a", {"role": "Admin"}, 403)


# ════════════════════════════════════════════════ 9   positive + AuditEvent
def test_09_owner_demotes_admin_and_grants_admin_with_audit(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        r1 = await c.put("/api/users/admin-a", json={"role": "Viewer"}, headers=hdr("owner-a"))
        r2 = await c.put("/api/users/viewer-a", json={"role": "Admin"}, headers=hdr("owner-a"))
        assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
        assert (await user(op, "admin-a"))["role"] == "Viewer"
        assert (await user(op, "viewer-a"))["role"] == "Admin"
        ev = await events(op, "user.role_status_changed")
        by_target = {e["entity_id"]: e for e in ev}
        assert set(by_target) == {"admin-a", "viewer-a"} and len(ev) == 2
        assert by_target["admin-a"]["structured_diff"] == {"before": {"role": "Admin"},
                                                           "after": {"role": "Viewer"}}
        assert by_target["viewer-a"]["structured_diff"] == {"before": {"role": "Viewer"},
                                                            "after": {"role": "Admin"}}
        for e in ev:
            assert e["actor_id"] == "owner-a" and e["tenant_id"] == ORG_A
            assert e["retention_class"] == "R3" and "password" not in str(e).lower()
    run(monkeypatch, backend, mode, scenario)


def test_09b_admin_may_demote_another_admin_and_grant_admin(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        assert (await c.put("/api/users/admin2-a", json={"role": "Viewer"}, headers=hdr("admin-a"))).status_code == 200
        assert (await c.put("/api/users/acct-a", json={"role": "Admin"}, headers=hdr("admin-a"))).status_code == 200
        assert (await user(op, "admin2-a"))["role"] == "Viewer" and (await user(op, "acct-a"))["role"] == "Admin"
    run(monkeypatch, backend, mode, scenario)


def test_09c_owner_changes_another_owner_and_is_active_is_audited(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        r = await c.put("/api/users/owner2-a", json={"is_active": False}, headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        assert (await user(op, "owner2-a"))["is_active"] is False
        ev = await events(op, "user.role_status_changed")
        assert ev[0]["structured_diff"] == {"before": {"is_active": True}, "after": {"is_active": False}}
    run(monkeypatch, backend, mode, scenario)


# ════════════════════════════════════════════════ 10  last active Owner
async def _single_owner(op, sysdb):
    await op.users.update_one({"id": "owner2-a"}, {"$set": {"is_active": False}})


async def _boss_by_assignment(op, sysdb):
    """enforce: ``boss-a`` is an Owner by its authoritative RoleAssignment while
    its users.role mirror says Admin; ``owner-a`` is the only users.role Owner."""
    await _single_owner(op, sysdb)
    await op.users.insert_one({"id": "boss-a", "org_id": ORG_A, "role": "Admin", "is_active": True,
                               "email": "boss-a@r003.example", "password_hash": _hash(),
                               "first_name": "boss", "last_name": "x"})
    await sysdb.tenant_memberships.insert_one({"id": "tm_boss", "user_id": "boss-a", "tenant_id": ORG_A,
                                               "status": "active"})
    await sysdb.tenant_role_assignments.insert_one({
        "id": "ra_boss", "user_id": "boss-a", "tenant_id": ORG_A, "role_id": "owner",
        "scope_type": "company", "scope_id": None, "module": None, "permissions": [], "status": "active"})


def test_10_last_owner_cannot_deactivate_self(monkeypatch, backend, mode):
    _refused(monkeypatch, backend, mode, "owner-a", "PUT", "/api/users/owner-a", {"is_active": False},
             409, "LAST_ACTIVE_OWNER", colls=("users", "audit_events"), extra_seed=_single_owner)


def test_10b_last_owner_cannot_demote_self(monkeypatch, backend, mode):
    # own-role rule first (403); the 409 is the next line of defence
    _refused(monkeypatch, backend, mode, "owner-a", "PUT", "/api/users/owner-a", {"role": "Admin"},
             403, "OWN_ROLE_CHANGE_FORBIDDEN", extra_seed=_single_owner)


@pytest.mark.parametrize("method,url,body", [("PUT", "/api/users/owner-a", {"role": "Admin"}),
                                             ("PUT", "/api/users/owner-a", {"is_active": False}),
                                             ("DELETE", "/api/users/owner-a", None)])
def test_10c_enforce_owner_by_assignment_cannot_remove_last_owner(monkeypatch, backend, method, url, body):
    async def seed(op, sysdb):
        await _boss_by_assignment(op, sysdb)
    _hdr = _token("boss-a", ORG_A, "Admin")

    async def scenario(c, op, sysdb):
        before = await snap(op, "users", "audit_events", "audit_logs")
        r = await c.request(method, url, json=body, headers=_hdr)
        assert r.status_code == 409 and code_of(r) == "LAST_ACTIVE_OWNER", r.text
        assert await snap(op, "users", "audit_events", "audit_logs") == before
    run(monkeypatch, backend, "enforce", scenario, seed)


def test_10d_enforce_owner_by_assignment_may_change_owner_when_another_remains(monkeypatch, backend):
    async def seed(op, sysdb):
        await _boss_by_assignment(op, sysdb)
        await op.users.update_one({"id": "owner2-a"}, {"$set": {"is_active": True}})

    async def scenario(c, op, sysdb):
        r = await c.put("/api/users/owner-a", json={"role": "Admin"}, headers=_token("boss-a", ORG_A, "Admin"))
        assert r.status_code == 200, r.text
    run(monkeypatch, backend, "enforce", scenario, seed)


def test_10e_enforce_rank_comes_from_assignments_not_users_role(monkeypatch, backend):
    """enforce: a users.role "Owner" without an owner assignment is not an Owner."""
    async def seed(op, sysdb):
        await sysdb.tenant_role_assignments.update_one({"id": "ra_owner2-a_%s" % ORG_A},
                                                       {"$set": {"role_id": "admin"}})

    async def scenario(c, op, sysdb):
        before = await snap(op)
        r = await c.put("/api/users/viewer-a", json={"role": "Owner"}, headers=hdr("owner2-a"))
        assert r.status_code == 403 and code_of(r) == "ROLE_ABOVE_OWN_FORBIDDEN", r.text
        assert await snap(op) == before
    run(monkeypatch, backend, "enforce", scenario, seed)


# ════════════════════════════════════════════════ 11  EMAIL_EXISTS
def _new(email, role="Viewer"):
    return {"email": email, "password": PASSWORD, "first_name": "N", "last_name": "N", "role": role}


@pytest.mark.parametrize("email", ["ivan@x.bg", "Ivan@X.bg ", "  IVAN@x.BG", "owner-b@r003.example",
                                   "OWNER-A@r003.example"])
def test_11_create_with_an_existing_email_anywhere_is_409(monkeypatch, backend, mode, email):
    r = _refused(monkeypatch, backend, mode, "admin-a", "POST", "/api/users", _new(email), 409,
                 "EMAIL_EXISTS", colls=("users", "audit_logs", "audit_events"))
    assert ORG_B not in r.text and "Org " not in r.text            # no firm is named


def test_11b_new_email_is_stored_normalized(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        r = await c.post("/api/users", json=_new("  New.Person@R003.Example "), headers=hdr("admin-a"))
        assert r.status_code == 201, r.text
        assert r.json()["email"] == "new.person@r003.example"
        assert await op.users.count_documents({"email": "new.person@r003.example"}) == 1
        r2 = await c.post("/api/users", json=_new("NEW.PERSON@r003.example"), headers=hdr("owner-b"))
        assert r2.status_code == 409 and code_of(r2) == "EMAIL_EXISTS"
    run(monkeypatch, backend, mode, scenario)


def test_11c_enforce_checks_every_registered_tenant_database(monkeypatch, backend):
    """enforce: a User living in another tenant's own database blocks the email too."""
    async def scenario(c, op, sysdb):
        other = op.client[op.name + "_t"]
        try:
            await sysdb.tenant_registry.insert_one({"id": "ORG-R003-C", "status": "active",
                                                    "database_name": other.name})
            await other.users.insert_one({"id": "c1", "org_id": "ORG-R003-C", "email": "Far@Away.bg"})
            from app.tenancy import registry, resolver
            real = resolver.get_tenant_db

            async def _get_db(tenant_id, require_operational=False):
                t = await registry.get_tenant(tenant_id)
                return other if t["database_name"] == other.name else await real(tenant_id)
            monkeypatch.setattr(resolver, "get_tenant_db", _get_db)
            r = await c.post("/api/users", json=_new("far@away.bg"), headers=hdr("admin-a"))
            assert r.status_code == 409 and code_of(r) == "EMAIL_EXISTS", r.text
            assert await op.users.count_documents({"email": "far@away.bg"}) == 0
        finally:
            await op.client.drop_database(other.name)
    run(monkeypatch, backend, "enforce", scenario)


def test_11d_off_never_reads_the_registry_for_the_email_check(monkeypatch, backend):
    async def scenario(c, op, sysdb):
        from app.tenancy import registry

        async def _boom(*a, **k):
            raise AssertionError("registry read in off mode")
        monkeypatch.setattr(registry, "list_tenants", _boom)
        r = await c.post("/api/users", json=_new("solo@r003.example"), headers=hdr("admin-a"))
        assert r.status_code == 201, r.text
        assert (await c.post("/api/users", json=_new("ivan@x.bg"), headers=hdr("admin-a"))).status_code == 409
    run(monkeypatch, backend, "off", scenario)


def test_11e_signup_and_onboarding_refuse_an_existing_email(monkeypatch, backend):
    import httpx
    from fastapi import FastAPI

    import server  # noqa: F401 — billing imports server constants; load it first
    from app.routes import billing
    from app.tenancy import registry
    from app.tenancy.onboarding import OnboardingRefused, onboard_tenant

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _seed(op, sysdb)
            monkeypatch.setattr(billing, "db", op)
            monkeypatch.setattr(registry, "system_db", sysdb)

            async def _noop(*a, **kw):
                return None
            monkeypatch.setattr(billing, "log_audit", _noop)
            before = await snap(op, "users", "organizations")
            reg_before = await sysdb.tenant_registry.count_documents({})
            for spelling in ("Ivan@X.bg ", "IVAN@x.bg"):
                with pytest.raises(OnboardingRefused) as exc:
                    await onboard_tenant(op, sysdb, org_name="Dup", owner_email=spelling,
                                         owner_password_hash="h", owner_first_name="x")
                assert exc.value.code == "EMAIL_EXISTS"
            app = FastAPI()
            app.include_router(billing.router, prefix="/api")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
                r = await c.post("/api/billing/signup", json={
                    "org_name": "Dup Firm", "owner_name": "Dup Owner", "owner_email": " Ivan@x.BG",
                    "password": PASSWORD})
            assert r.status_code == 409 and code_of(r) == "EMAIL_EXISTS", r.text
            assert await snap(op, "users", "organizations") == before
            assert await sysdb.tenant_registry.count_documents({}) == reg_before
    asyncio.run(go())


def test_11f_platform_bootstrap_creates_nothing_for_an_existing_email(monkeypatch, backend, mode):
    from app.routes.platform import bootstrap_rate_limiter
    monkeypatch.setenv("PLATFORM_BOOTSTRAP_TOKEN", "r003-test-bootstrap-token")
    bootstrap_rate_limiter.reset()

    async def scenario(c, op, sysdb):
        before = await snap(op, "users", "organizations")
        r = await c.post("/api/platform/bootstrap-create-platform-admin",
                         headers={"X-Bootstrap-Token": "r003-test-bootstrap-token"},
                         json={"email": "IVAN@x.bg", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["created"] is False, r.text
        assert await snap(op, "users", "organizations") == before
    run(monkeypatch, backend, mode, scenario)


# ════════════════════════════════════════════════ 12–13 login
async def _dup_ivan(op, sysdb):
    await op.users.insert_one({"id": "ivan-a", "org_id": ORG_A, "role": "Viewer", "is_active": True,
                               "email": " Ivan@X.bg", "password_hash": _hash(), "first_name": "Ivan",
                               "last_name": "A"})


def test_12_login_with_a_duplicated_email_is_409_without_token(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        r = await c.post("/api/auth/login", json={"email": "ivan@x.bg", "password": PASSWORD})
        assert r.status_code == 409 and code_of(r) == "DUPLICATE_IDENTITY", r.text
        assert "token" not in r.text and ORG_A not in r.text and ORG_B not in r.text
        ev = await events(op, "auth.login_refused")
        assert sorted(e["tenant_id"] for e in ev) == [ORG_A, ORG_B]
        assert all(e["error_code"] == "DUPLICATE_IDENTITY" and e["result"] == "denied" for e in ev)
        assert PASSWORD not in str(ev)
        # a wrong password learns nothing about the duplicate
        r2 = await c.post("/api/auth/login", json={"email": "IVAN@x.bg", "password": "wrong-Pass-1!"})
        assert r2.status_code == 401 and "token" not in r2.text
    run(monkeypatch, backend, mode, scenario, _dup_ivan)


def test_13_login_is_case_and_space_insensitive(monkeypatch, backend, mode):
    async def scenario(c, op, sysdb):
        for spelling in ("IVAN@x.bg", "  Ivan@X.BG "):
            r = await c.post("/api/auth/login", json={"email": spelling, "password": PASSWORD})
            assert r.status_code == 200, r.text
            assert r.json()["token"] and r.json()["user"]["id"] == "ivan-b"
            assert "password_hash" not in r.json()["user"]
        r = await c.post("/api/auth/login", json={"email": "ivan@x.bg", "password": "wrong-Pass-1!"})
        assert r.status_code == 401
    run(monkeypatch, backend, mode, scenario)


# ════════════════════════════════════════════════ 14  two firms
@pytest.mark.parametrize("method,url,body", [
    ("PUT", "/api/users/admin-b", {"role": "Viewer"}),
    ("PUT", "/api/users/owner-b", {"is_active": False}),
    ("PUT", "/api/employees/admin-b/basic", {"first_name": "X"}),
    ("POST", "/api/admin/set-password/owner-b", {"new_password": "Another-Pass-123!"}),
    ("DELETE", "/api/users/admin-b", None),
])
def test_14_a_foreign_user_is_404_and_untouched(monkeypatch, backend, mode, method, url, body):
    who = "owner-a"
    _refused(monkeypatch, backend, mode, who, method, url, body, 404,
             colls=("users", "audit_logs", "audit_events"))


# ════════════════════════════════════════════════ 15  duplicates report
def test_15_duplicates_report_counts_and_writes_nothing(backend):
    from scripts.r0_03_email_duplicates_report import build_report

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _seed(op, sysdb)
            await _dup_ivan(op, sysdb)
            await op.users.insert_one({"id": "owner-a-twin", "org_id": ORG_B, "email": "OWNER-A@r003.example"})
            await op.users.insert_one({"id": "no-mail", "org_id": ORG_B})
            before = await snap(op, *sorted(await op.list_collection_names()))
            idx_before = await op.users.index_information()
            rep = await build_report(op)
            assert await snap(op, *sorted(await op.list_collection_names())) == before
            assert await op.users.index_information() == idx_before
            return rep
    rep = asyncio.run(go())
    assert rep["read_only"] is True
    assert rep["counts"]["duplicated_emails"] == 2 and rep["counts"]["users_in_duplicates"] == 4
    assert rep["counts"]["users_without_email"] == 1
    masked = {d["email_masked"]: d for d in rep["duplicates"]}
    assert set(masked) == {"iv***@x.bg", "ow***@r003.example"}
    assert {u["id"] for u in masked["iv***@x.bg"]["users"]} == {"ivan-a", "ivan-b"}
    assert masked["iv***@x.bg"]["spellings_differ"] is True
    text = str(rep)
    assert "ivan@x.bg" not in text.lower() and "owner-a@r003" not in text.lower()


def test_15b_report_handle_refuses_writes():
    from scripts.r0_01_billing_exposure_report import ReadOnlyDb
    from mongomock_motor import AsyncMongoMockClient
    ro = ReadOnlyDb(AsyncMongoMockClient()["x"])
    for method in ("insert_one", "update_one", "delete_many", "create_index", "drop"):
        with pytest.raises(PermissionError):
            getattr(ro["users"], method)


# ════════════════════════════════════════════════ helpers
def test_normalize_and_mask():
    from app.tenancy.identity import mask_email, normalize_email, email_match_filter
    import re
    assert normalize_email("  Ivan@X.bg ") == "ivan@x.bg" and normalize_email(None) == ""
    assert mask_email("Ivan@abv.bg") == "iv***@abv.bg" and mask_email("nope") == "***"
    rx = email_match_filter("a.b+c@x.bg")["email"]["$regex"]
    assert re.match(rx, "A.B+C@X.BG ", re.I) and not re.match(rx, "aXb+c@x.bg", re.I)


def test_no_unique_index_is_created_at_import_or_request(monkeypatch, backend):
    async def scenario(c, op, sysdb):
        await c.post("/api/users", json=_new("idx@r003.example"), headers=hdr("admin-a"))
        names = set((await op.users.index_information()).keys())
        assert "r0_03_email_unique_ci" not in names
    run(monkeypatch, backend, "off", scenario)
