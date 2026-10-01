"""
W0-03E-A2B / C01 — canonical onboarding, tenant-bound W0-02 bootstrap, session identity.

* Phase 7: a second company is created through ONE canonical onboarding path
  (``app.tenancy.onboarding.onboard_tenant``, used by ``POST /billing/signup``
  and ``scripts/create_company.py``). The tenant id is generated server-side, the
  tenant is registered (registry, membership, owner assignment), it is never
  the primary installation, and a caller cannot steer any of it.
* Phase 5: ``scripts/w0_02_bootstrap_permissions.py`` derives project-scope
  permissions ONLY from tenant-bound memberships of a Tenant Registry tenant of
  its database, pairs a row only with that tenant's own user, stamps the
  registry tenant id, and refuses outright while any membership is ownerless —
  even with colliding user/project ids across tenants.
* The session user is resolved by the signed (user id, tenant) pair: with the
  same user id in two tenants, each token reaches its own user.

Run:  pytest tests/test_w0_03e_a2b_onboarding_bootstrap.py -v --noconftest
"""
import importlib.util
from pathlib import Path

import pytest

from app.tenancy import ownership as own
from app.tenancy.onboarding import OnboardingRefused, onboard_tenant
from tests.test_w0_03e_a2b_backfill import BEG_ORG, mock_dbs, run, seed_legacy

BACKEND = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------ onboarding
def test_onboarding_creates_and_registers_a_tenant_with_a_server_generated_id():
    async def body():
        op, sysdb = mock_dbs()
        await seed_legacy(op, sysdb, bound_only=True)
        out = await onboard_tenant(op, sysdb, org_name="TEST COMPANY B",
                                   owner_email="Owner@B.test", owner_password_hash="h",
                                   owner_first_name="B", owner_last_name="Owner",
                                   organization_extra={"id": "forged", "org_id": BEG_ORG,
                                                       "tenant_id": BEG_ORG, "phone": "1"})
        tid = out["tenant"]["id"]
        assert tid not in ("forged", BEG_ORG) and len(tid) == 36
        org = await op.organizations.find_one({"id": tid}, {"_id": 0})
        assert org["name"] == "TEST COMPANY B" and org["phone"] == "1"
        assert "org_id" not in org and "tenant_id" not in org
        owner = await op.users.find_one({"email": "owner@b.test"}, {"_id": 0})
        assert owner["org_id"] == tid and owner["role"] == "Owner"
        reg = await sysdb.tenant_registry.find_one({"id": tid}, {"_id": 0})
        assert reg["database_name"] == op.name and reg["is_primary_installation"] is False
        assert reg["legacy_org_id"] == tid and reg["status"] == "active"
        assert reg["storage_status"] == "not_configured"
        m = await sysdb.tenant_memberships.find_one({"tenant_id": tid}, {"_id": 0})
        assert m["user_id"] == owner["id"] and m["status"] == "active"
        ra = await sysdb.tenant_role_assignments.find_one({"tenant_id": tid}, {"_id": 0})
        assert (ra["role_id"], ra["scope_type"], ra["user_id"]) == ("owner", "company", owner["id"])
        assert "password_hash" not in out["owner"]
        # nothing of BEG was read into, copied or changed
        assert await op.projects.count_documents({"org_id": tid}) == 0
        assert (await sysdb.tenant_registry.find_one({"id": BEG_ORG}))["is_primary_installation"]
    run(body())


def test_onboarding_refuses_a_duplicate_email_and_writes_nothing():
    async def body():
        op, sysdb = mock_dbs()
        await seed_legacy(op, sysdb, bound_only=True)
        counts = (await op.organizations.count_documents({}),
                  await sysdb.tenant_registry.count_documents({}))
        with pytest.raises(OnboardingRefused) as exc:
            await onboard_tenant(op, sysdb, org_name="X", owner_email="SM@beg.test",
                                 owner_password_hash="h", owner_first_name="x")
        assert exc.value.code == "EMAIL_EXISTS"
        assert counts == (await op.organizations.count_documents({}),
                          await sysdb.tenant_registry.count_documents({}))
    run(body())


def test_signup_over_http_is_the_canonical_onboarding_and_ignores_a_body_tenant(monkeypatch):
    import httpx
    from fastapi import FastAPI

    import server  # noqa: F401 — billing imports server constants; load it first
    from app.routes import billing
    from app.tenancy import registry

    async def body():
        op, sysdb = mock_dbs()
        await seed_legacy(op, sysdb, bound_only=True)
        monkeypatch.setattr(billing, "db", op)
        monkeypatch.setattr(registry, "system_db", sysdb)

        async def _noop(*a, **kw):
            return None
        monkeypatch.setattr(billing, "log_audit", _noop)
        app = FastAPI()
        app.include_router(billing.router, prefix="/api")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            r = await c.post("/api/billing/signup", json={
                "org_name": "TEST COMPANY B", "owner_name": "Бойко Б",
                "owner_email": "owner@b.test", "password": "Secret-Pass-1!",
                "org_id": BEG_ORG, "tenant_id": BEG_ORG})
            assert r.status_code == 200, r.text
            payload = r.json()
            dup = await c.post("/api/billing/signup", json={
                "org_name": "X", "owner_name": "X", "owner_email": "owner@b.test",
                "password": "Secret-Pass-1!"})
            assert dup.status_code == 400
        tid = payload["organization"]["id"]
        assert tid != BEG_ORG and payload["user"]["org_id"] == tid
        assert (await sysdb.tenant_registry.find_one({"id": tid}))["is_primary_installation"] is False
        for coll in ("subscriptions", "feature_flags"):
            rows = await op[coll].find({"org_id": tid}).to_list(None)
            assert rows and all(r["org_id"] == tid for r in rows)
        assert await op.users.count_documents({"org_id": BEG_ORG, "email": "owner@b.test"}) == 0
    run(body())


# ------------------------------------------------------------ W0-02 bootstrap
def _boot(op, sysdb):
    spec = importlib.util.spec_from_file_location(
        "w0_02_boot_a2b", BACKEND / "scripts" / "w0_02_bootstrap_permissions.py")
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)
    boot.op_db, boot.sys_db = op, sysdb
    return boot


async def _two_tenants(op, sysdb, *, ownerless=False):
    """Tenants A and B in one database, colliding user id + project id."""
    for t in ("TA", "TB"):
        await op.organizations.insert_one({"id": t, "name": t})
        await sysdb.tenant_registry.insert_one({"id": t, "database_name": op.name,
                                                "status": "active"})
        await op.projects.insert_one({"id": "P1", "org_id": t})
    # same user id in both tenants: Technician in A, Viewer in B
    await op.users.insert_one({"id": "u1", "org_id": "TA", "role": "Technician"})
    await op.users.insert_one({"id": "u1", "org_id": "TB", "role": "Viewer"})
    await op.users.insert_one({"id": "u-sm", "org_id": "TB", "role": "SiteManager"})
    # B's rows (inserted first): u1 member, u-sm manager. A has u1 as member only.
    await op.project_team.insert_one({"id": "b1", "org_id": "TB", "project_id": "P1",
                                      "user_id": "u1", "role_in_project": "Worker",
                                      "active": True})
    await op.project_team.insert_one({"id": "b2", "org_id": "TB", "project_id": "P1",
                                      "user_id": "u-sm", "role_in_project": "SiteManager",
                                      "active": True})
    await op.project_team.insert_one({"id": "a1", "org_id": "TA", "project_id": "P1",
                                      "user_id": "u1", "role_in_project": "Worker",
                                      "active": True})
    # a row of an unregistered tenant and a user whose row is in another tenant
    await op.project_team.insert_one({"id": "x1", "org_id": "TX", "project_id": "P1",
                                      "user_id": "u1", "role_in_project": "SiteManager",
                                      "active": True})
    if ownerless:
        await op.project_team.insert_one({"id": "o1", "project_id": "P1", "user_id": "u1",
                                          "role_in_project": "SiteManager", "active": True})


def test_the_bootstrap_derives_permissions_per_registry_tenant_only():
    async def body():
        op, sysdb = mock_dbs("w002_a2b_op")
        await _two_tenants(op, sysdb)
        boot = _boot(op, sysdb)
        plan = await boot.build_backfill()
        got = sorted((p["tenant_id"], p["user_id"], p["scope_id"], p["role_id"],
                      tuple(p["permissions"])) for p in plan)
        from app.permissions.catalog import PROJECT_MANAGER_ACTIONS, PROJECT_MEMBER_ACTIONS
        assert got == sorted([
            ("TA", "u1", "P1", "LEGACY_TECHNICIAN", tuple(PROJECT_MEMBER_ACTIONS)),
            ("TB", "u1", "P1", "LEGACY_VIEWER", tuple(PROJECT_MEMBER_ACTIONS)),
            ("TB", "u-sm", "P1", "site_manager", tuple(PROJECT_MANAGER_ACTIONS)),
        ]), got
        # the TX row (no registry tenant) derived nothing; A's u1 never got B's
        # SiteManager role and B's role id never came from A's user record
        assert not any(p["tenant_id"] == "TX" for p in plan)
        rc = await boot.run(apply=True, verify_only=False, revert=False)
        assert rc == boot.EXIT_OK
        assert await boot._verify() == boot.EXIT_OK
    run(body())


def test_the_bootstrap_refuses_while_any_membership_is_ownerless():
    async def body():
        op, sysdb = mock_dbs("w002_a2b_op")
        await _two_tenants(op, sysdb, ownerless=True)
        boot = _boot(op, sysdb)
        with pytest.raises(boot.OwnerlessMembership):
            await boot.build_backfill()
        before = await sysdb.tenant_role_assignments.count_documents({})
        rc = await boot.run(apply=True, verify_only=False, revert=False)
        assert rc == boot.EXIT_OWNERLESS
        assert await sysdb.tenant_role_assignments.count_documents({}) == before
        assert await boot._verify() == boot.EXIT_VERIFY_FAILED
    run(body())


def test_the_bootstrap_runs_cleanly_after_the_beg_backfill():
    """The A2B sequence: legacy ownerless rows block it; after backfill it runs."""
    from app.tenancy import legacy_backfill as lb
    from tests.test_w0_03e_a2b_backfill import TrustedApproval

    async def body():
        op, sysdb = mock_dbs()
        await seed_legacy(op, sysdb)
        boot = _boot(op, sysdb)
        assert await boot.run(apply=True, verify_only=False, revert=False) == boot.EXIT_OWNERLESS
        report = await lb.dry_run(op, sysdb)
        await lb.execute(op, sysdb, plan_token=report["plan_token"], idempotency_key="k",
                         actor_id="krum", approval_id="A", approval_verifier=TrustedApproval())
        assert await boot.run(apply=True, verify_only=False, revert=False) == boot.EXIT_OK
        rows = await sysdb.tenant_role_assignments.find({"scope_type": "project"}).to_list(None)
        assert {(r["tenant_id"], r["user_id"], r["scope_id"]) for r in rows} == {
            (BEG_ORG, "U-L", "P-L")}
        assert await op.project_team.count_documents(own.ownerless_predicate()) == 0
    run(body())


# ------------------------------------------------------------ session identity
def test_the_session_user_is_the_signed_user_and_tenant_pair(monkeypatch):
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from app.deps import auth

    async def body():
        op, _ = mock_dbs()
        await op.users.insert_one({"id": "u1", "org_id": "TB", "first_name": "B-USER"})
        await op.users.insert_one({"id": "u1", "org_id": "TA", "first_name": "A-USER"})
        monkeypatch.setattr(auth, "db", op)

        def cred(**claims):
            return HTTPAuthorizationCredentials(scheme="Bearer",
                                                credentials=auth.create_token(claims))
        a = await auth.get_current_user(cred(user_id="u1", org_id="TA"))
        b = await auth.get_current_user(cred(user_id="u1", org_id="TB"))
        assert (a["first_name"], b["first_name"]) == ("A-USER", "B-USER")
        for bad in (dict(user_id="u1"), dict(user_id="u1", org_id=""),
                    dict(user_id="u1", org_id="TX")):
            with pytest.raises(HTTPException) as exc:
                await auth.get_current_user(cred(**bad))
            assert exc.value.status_code == 401
    run(body())
