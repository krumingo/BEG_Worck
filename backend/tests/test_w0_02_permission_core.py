"""
W0-02 — Core Permission Model tests (FLOW-002).

The pure-logic tests need NO database: they monkeypatch the assignment loader,
so they run anywhere with `pytest`. The integration tests (routes, migration,
audit chain against Mongo) are guarded behind W0_02_INTEGRATION=1 and run on a
dev / Synology test environment.

Run (logic):        pytest tests/test_w0_02_permission_core.py -v
Run (integration):  W0_02_INTEGRATION=1 pytest tests/test_w0_02_permission_core.py -v
"""
import os
import asyncio
import pytest

from app.permissions import service
from app.permissions.service import (
    evaluate_permission, has_permission, _scope_covers,
    ALLOWED, REASON_NO_ASSIGNMENT, REASON_ACTION_NOT_ALLOWED,
    REASON_MODULE_NOT_ALLOWED, REASON_SCOPE_MISMATCH, REASON_ASSIGNMENT_EXPIRED,
    REASON_ASSIGNMENT_REVOKED, REASON_CROSS_TENANT, REASON_AMOUNT_LIMIT_EXCEEDED,
)
from app.permissions.deps import _shadow_category
from app.permissions.catalog import (
    role_actions, is_canonical_role, is_significant_action,
    CANONICAL_ROLES, LEGACY_ROLES, LEGACY_ROLE_MAP,
)


def run(coro):
    return asyncio.run(coro)


class FakeCtx:
    def __init__(self, tenant_id="tenant-a", user_id="user-1"):
        self.tenant_id = tenant_id
        self.user_id = user_id


def make_assignment(**over):
    a = dict(
        id="ra_1", user_id="user-1", tenant_id="tenant-a",
        role_id="admin", scope_type="company", scope_id=None, module=None,
        permissions=[], max_amount=None, valid_from=None, valid_to=None,
        status="active",
    )
    a.update(over)
    return a


def patch_assignments(monkeypatch, assignments):
    async def fake(uid, tid):
        return [a for a in assignments if a["user_id"] == uid and a["tenant_id"] == tid]
    monkeypatch.setattr(service, "_load_assignments", fake)


# --------------------------------------------------------------------------
# evaluate_permission — the authoritative decision
# --------------------------------------------------------------------------
class TestEvaluate:
    def test_allow_company_admin(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(role_id="admin")])
        d = run(evaluate_permission(FakeCtx(), "user.create", module="M0", scope_type="company"))
        assert d.allowed and d.reason_code == ALLOWED and d.effective_assignment_ids == ["ra_1"]

    def test_deny_no_assignment(self, monkeypatch):
        patch_assignments(monkeypatch, [])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_NO_ASSIGNMENT

    def test_deny_action_not_in_role(self, monkeypatch):
        # worker cannot approve asset intake
        patch_assignments(monkeypatch, [make_assignment(role_id="worker")])
        d = run(evaluate_permission(FakeCtx(), "asset_intake.approve", module="M8", scope_type="company"))
        assert not d.allowed and d.reason_code == REASON_ACTION_NOT_ALLOWED

    def test_deny_module_mismatch(self, monkeypatch):
        # explicit budget.read permission so the MODULE check is what fails
        patch_assignments(monkeypatch, [make_assignment(
            role_id="site_manager", module="M3", permissions=["budget.read"])])
        d = run(evaluate_permission(FakeCtx(), "budget.read", module="M2", scope_type="company"))
        assert not d.allowed and d.reason_code == REASON_MODULE_NOT_ALLOWED

    def test_deny_scope_project_vs_project(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(
            role_id="site_manager", scope_type="project", scope_id="XOPark",
            permissions=["budget.read"])])
        d = run(evaluate_permission(FakeCtx(), "budget.read", module="M2",
                                    scope_type="project", scope_id="Boyana"))
        assert not d.allowed and d.reason_code == REASON_SCOPE_MISMATCH

    def test_allow_company_covers_project(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(role_id="admin", scope_type="company")])
        d = run(evaluate_permission(FakeCtx(), "budget.read", module="M2",
                                    scope_type="project", scope_id="Boyana"))
        assert d.allowed

    def test_allow_project_scoped_member(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(
            role_id="site_manager", scope_type="project", scope_id="XOPark",
            permissions=["budget.read"])])
        d = run(evaluate_permission(FakeCtx(), "budget.read", module="M2",
                                    scope_type="project", scope_id="XOPark"))
        assert d.allowed

    def test_deny_expired(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(
            role_id="admin", valid_to="2000-01-01T00:00:00+00:00")])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_EXPIRED

    def test_deny_not_yet_valid(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(
            role_id="admin", valid_from="2999-01-01T00:00:00+00:00")])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_EXPIRED

    def test_deny_revoked(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(role_id="admin", status="revoked")])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_REVOKED

    def test_deny_amount_over_limit(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(
            role_id="admin", max_amount=1000.0)])
        d = run(evaluate_permission(FakeCtx(), "user.create", amount=5000.0))
        assert not d.allowed and d.reason_code == REASON_AMOUNT_LIMIT_EXCEEDED

    def test_allow_amount_within_limit(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(role_id="admin", max_amount=1000.0)])
        d = run(evaluate_permission(FakeCtx(), "user.create", amount=500.0))
        assert d.allowed

    def test_cross_tenant_denied(self, monkeypatch):
        patch_assignments(monkeypatch, [make_assignment(role_id="admin")])
        d = run(evaluate_permission(FakeCtx(tenant_id="tenant-a"), "user.create",
                                    resource_tenant_id="tenant-b"))
        assert not d.allowed and d.reason_code == REASON_CROSS_TENANT

    def test_multi_role_union_scoped(self, monkeypatch):
        patch_assignments(monkeypatch, [
            make_assignment(id="ra_view", role_id="office",
                            scope_type="project", scope_id="Boyana", permissions=["budget.read"]),
            make_assignment(id="ra_mgr", role_id="site_manager",
                            scope_type="project", scope_id="XOPark",
                            permissions=["budget.read", "budget.write"]),
        ])
        # budget.write only where site_manager on XOPark
        assert run(has_permission(FakeCtx(), "budget.write", module="M2",
                                  scope_type="project", scope_id="XOPark"))
        assert not run(has_permission(FakeCtx(), "budget.write", module="M2",
                                      scope_type="project", scope_id="Boyana"))

    def test_permissions_override_role(self, monkeypatch):
        # explicit permissions list wins over role catalog
        patch_assignments(monkeypatch, [make_assignment(
            role_id="driver", permissions=["budget.read"])])
        assert run(has_permission(FakeCtx(), "budget.read", module="M2", scope_type="company"))


class TestScopeCovers:
    def test_company_covers_all(self):
        assert _scope_covers("company", None, "project", "X")
        assert _scope_covers("company", None, None, None)

    def test_narrow_cannot_cover_company(self):
        assert not _scope_covers("project", "X", None, None)

    def test_exact_project(self):
        assert _scope_covers("project", "X", "project", "X")
        assert not _scope_covers("project", "X", "project", "Y")


class TestShadowCategory:
    def test_categories(self):
        assert _shadow_category(True, True) == "OLD_ALLOW_NEW_ALLOW"
        assert _shadow_category(True, False) == "OLD_ALLOW_NEW_DENY"
        assert _shadow_category(False, True) == "OLD_DENY_NEW_ALLOW"
        assert _shadow_category(False, False) == "OLD_DENY_NEW_DENY"


class TestCatalog:
    def test_legacy_roles_not_canonical(self):
        assert not is_canonical_role("LEGACY_TECHNICIAN")
        assert not is_canonical_role("LEGACY_VIEWER")
        assert set(LEGACY_ROLES) == {"LEGACY_TECHNICIAN", "LEGACY_VIEWER"}

    def test_legacy_technician_reproduces_exact(self):
        # Technician today: may submit asset intake; nothing more.
        acts = role_actions("LEGACY_TECHNICIAN")
        assert acts == {"asset_intake.submit"}
        assert "asset_intake.approve" not in acts
        assert "user.create" not in acts

    def test_legacy_viewer_reproduces_exact(self):
        # Viewer today: no company-wide elevated action (reads are membership-gated).
        assert role_actions("LEGACY_VIEWER") == set()

    def test_legacy_map(self):
        assert LEGACY_ROLE_MAP["Technician"] == "LEGACY_TECHNICIAN"
        assert LEGACY_ROLE_MAP["Viewer"] == "LEGACY_VIEWER"
        assert LEGACY_ROLE_MAP["Owner"] == "owner"

    def test_significant_actions(self):
        assert is_significant_action("user.create")
        assert is_significant_action("asset_intake.approve")
        assert is_significant_action("permission.role_assignment.revoked")
        assert not is_significant_action("budget.read")
        assert not is_significant_action("user.read")


# --------------------------------------------------------------------------
# Audit significance — denials audited only when security/business significant
# --------------------------------------------------------------------------
class TestDeniedAuditPolicy:
    def _capture(self, monkeypatch):
        captured = {}
        from app.permissions import audit_hooks

        async def fake_record(db, event):
            captured["event"] = event
            return event

        async def fake_db(ctx):
            return None
        monkeypatch.setattr(audit_hooks, "record_event", fake_record)
        monkeypatch.setattr(audit_hooks, "_audit_db", fake_db)
        return audit_hooks, captured

    def test_significant_denial_audited(self, monkeypatch):
        audit_hooks, captured = self._capture(monkeypatch)

        class D:
            reason_code = REASON_NO_ASSIGNMENT
            effective_assignment_ids = []
        run(audit_hooks.audit_permission_denied(
            FakeCtx(), "user.create", module="M0", resource_type="user",
            resource_id=None, scope_type="company", scope_id=None, decision=D(), request=None))
        assert captured.get("event") and captured["event"]["action"] == "permission.denied"
        assert captured["event"]["error_code"] == REASON_NO_ASSIGNMENT
        assert captured["event"]["result"] == "denied"

    def test_read_denial_not_audited(self, monkeypatch):
        audit_hooks, captured = self._capture(monkeypatch)

        class D:
            reason_code = REASON_ACTION_NOT_ALLOWED
            effective_assignment_ids = []
        out = run(audit_hooks.audit_permission_denied(
            FakeCtx(), "budget.read", module="M2", resource_type="activity_budget",
            resource_id="p1", scope_type="project", scope_id="p1", decision=D(), request=None))
        assert out is None and "event" not in captured   # read denial not flooded

    def test_cross_tenant_always_audited(self, monkeypatch):
        audit_hooks, captured = self._capture(monkeypatch)

        class D:
            reason_code = REASON_CROSS_TENANT
            effective_assignment_ids = []
        run(audit_hooks.audit_permission_denied(
            FakeCtx(), "budget.read", decision=D(), request=None))
        assert captured.get("event")   # cross-tenant audited even for a read


# --------------------------------------------------------------------------
# Integration — real code paths against an in-memory Mongo (mongomock_motor).
# Runs the actual registry / service / audit store / migration script, so it
# needs no Docker or Atlas. Skipped only if mongomock_motor is not installed.
#   pip install mongomock_motor
# --------------------------------------------------------------------------
try:
    import mongomock_motor  # noqa: F401
    HAS_MONGOMOCK = True
except Exception:
    HAS_MONGOMOCK = False

import importlib.util
from pathlib import Path


def _mock_env():
    """Patch the app's Mongo clients to a fresh in-memory database."""
    from mongomock_motor import AsyncMongoMockClient
    from app.tenancy import registry
    import app.db as appdb

    mock = AsyncMongoMockClient()
    sysdb = mock["sys_test"]
    opdb = mock["op_test"]
    registry.system_db = sysdb
    registry.tenant_registry = sysdb.tenant_registry
    registry.tenant_memberships = sysdb.tenant_memberships
    registry.tenant_role_assignments = sysdb.tenant_role_assignments
    appdb.db = opdb
    appdb.users = opdb.users
    appdb.organizations = opdb.organizations

    boot_path = Path(__file__).parent.parent / "scripts" / "w0_02_bootstrap_permissions.py"
    spec = importlib.util.spec_from_file_location("w0_02_boot", boot_path)
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)
    boot.op_db = opdb
    boot.sys_db = sysdb
    return sysdb, opdb, boot


async def _seed(sysdb, opdb):
    await opdb.organizations.insert_one({"id": "T1", "name": "BEG"})
    roles = {"u_admin": "Admin", "u_view": "Viewer", "u_tech": "Technician", "u_sm": "SiteManager"}
    for uid, role in roles.items():
        await opdb.users.insert_one({"id": uid, "org_id": "T1", "role": role, "is_active": True})
        await sysdb.tenant_role_assignments.insert_one({
            "id": f"ra_{uid}_T1_legacy", "user_id": uid, "tenant_id": "T1", "role": role,
            "scope_type": "company", "scope_ids": [], "status": "active",
            "created_at": "2026-08-01T00:00:00+00:00", "migrated_from": "users.role",
        })
    await sysdb.tenant_registry.insert_one({"id": "T1", "database_name": "op_test", "status": "active"})


class MCtx:
    def __init__(self, uid, opdb):
        self.tenant_id = "T1"; self.user_id = uid; self._db = opdb
    async def db(self):
        return self._db


@pytest.mark.skipif(not HAS_MONGOMOCK, reason="pip install mongomock_motor to run integration")
class TestMigrationIntegration:
    def test_apply_maps_and_leaves_operational_untouched(self):
        sysdb, opdb, boot = _mock_env()

        async def go():
            await _seed(sysdb, opdb)
            before = (await opdb.users.count_documents({}), await opdb.organizations.count_documents({}))
            await boot.run(apply=True, verify_only=False, revert=False)
            after = (await opdb.users.count_documents({}), await opdb.organizations.count_documents({}))
            assert after == before                                  # operational untouched
            got = {u: (await sysdb.tenant_role_assignments.find_one({"user_id": u}))["role_id"]
                   for u in ("u_admin", "u_view", "u_tech", "u_sm")}
            return got
        got = run(go())
        assert got == {"u_admin": "admin", "u_view": "LEGACY_VIEWER",
                       "u_tech": "LEGACY_TECHNICIAN", "u_sm": "site_manager"}

    def test_idempotent_then_revert(self):
        sysdb, opdb, boot = _mock_env()

        async def go():
            await _seed(sysdb, opdb)
            await boot.run(apply=True, verify_only=False, revert=False)
            n1 = await sysdb.tenant_role_assignments.count_documents({})
            await boot.run(apply=True, verify_only=False, revert=False)   # idempotent
            n2 = await sysdb.tenant_role_assignments.count_documents({})
            assert n1 == n2                                                # no duplicates
            await boot.run(apply=True, verify_only=False, revert=True)     # revert
            return await sysdb.tenant_role_assignments.count_documents({"role_id": {"$exists": True}})
        assert run(go()) == 0                                              # W0-02 fields stripped


@pytest.mark.skipif(not HAS_MONGOMOCK, reason="pip install mongomock_motor to run integration")
class TestServiceAndAuditIntegration:
    def test_evaluate_reads_authoritative_and_scope_isolation(self):
        sysdb, opdb, boot = _mock_env()

        async def go():
            await _seed(sysdb, opdb)
            await boot.run(apply=True, verify_only=False, revert=False)
            # admin (company) allowed to read a project budget; viewer denied (empty legacy role)
            admin_ok = await has_permission(MCtx("u_admin", opdb), "budget.read",
                                            module="M2", scope_type="project", scope_id="P1")
            view_denied = not await has_permission(MCtx("u_view", opdb), "budget.read",
                                                   module="M2", scope_type="project", scope_id="P1")
            # a project-scope backfill grants the member; another project stays isolated
            from app.tenancy import registry
            await registry.upsert_role_assignment({
                "id": "ra_uview_P1", "user_id": "u_view", "tenant_id": "T1", "role_id": "LEGACY_VIEWER",
                "scope_type": "project", "scope_id": "P1", "module": None,
                "permissions": ["budget.read"], "status": "active"})
            p1 = await has_permission(MCtx("u_view", opdb), "budget.read", module="M2",
                                      scope_type="project", scope_id="P1")
            p2 = await has_permission(MCtx("u_view", opdb), "budget.read", module="M2",
                                      scope_type="project", scope_id="P2")
            return admin_ok, view_denied, p1, p2
        admin_ok, view_denied, p1, p2 = run(go())
        assert admin_ok and view_denied and p1 and not p2

    def test_audit_change_denied_policy_and_chain(self):
        sysdb, opdb, boot = _mock_env()

        async def go():
            await _seed(sysdb, opdb)
            await boot.run(apply=True, verify_only=False, revert=False)
            from app.permissions import audit_hooks
            from app.audit.store import verify_chain, AUDIT_COLLECTION
            ctx = MCtx("u_admin", opdb)
            a = await sysdb.tenant_role_assignments.find_one({"user_id": "u_view"}, {"_id": 0})
            await audit_hooks.audit_permission_change(ctx, "granted", a, before=None, after=a)

            class D:
                def __init__(s, r): s.reason_code = r; s.effective_assignment_ids = []
            sig = await audit_hooks.audit_permission_denied(ctx, "user.create", decision=D("NO_ASSIGNMENT"))
            read = await audit_hooks.audit_permission_denied(ctx, "budget.read", decision=D("ACTION_NOT_ALLOWED"))
            xt = await audit_hooks.audit_permission_denied(ctx, "budget.read", decision=D("CROSS_TENANT"))
            events = await opdb[AUDIT_COLLECTION].find({"tenant_id": "T1"}, {"_id": 0}).sort([("sequence", 1)]).to_list(100)
            ok, _ = verify_chain(events)
            return (sig is not None), (read is None), (xt is not None), ok, len(events)
        sig_stored, read_skipped, xt_stored, chain_ok, n = run(go())
        assert sig_stored and read_skipped and xt_stored and chain_ok and n == 3

    def test_role_change_and_membership_revoke_take_effect(self):
        """update_user role change + project removal update authoritative
        assignments so the next check reflects them (no diverging sources)."""
        sysdb, opdb, boot = _mock_env()

        async def go():
            await _seed(sysdb, opdb)
            await boot.run(apply=True, verify_only=False, revert=False)
            from app.permissions.sync import grant_company_role, sync_project_membership
            from app.tenancy import registry
            ctx = MCtx("u_admin", opdb)
            # u_tech starts as LEGACY_TECHNICIAN (cannot user.read); promote to admin
            before = await has_permission(MCtx("u_tech", opdb), "asset_intake.approve",
                                          module="M8", scope_type="company")
            await grant_company_role(ctx, "u_tech", "Admin", actor_id="u_admin")
            after = await has_permission(MCtx("u_tech", opdb), "asset_intake.approve",
                                         module="M8", scope_type="company")
            # old company role (LEGACY_TECHNICIAN) must be revoked, not left active
            actives = [a for a in await registry.list_role_assignments("u_tech", "T1")
                       if a.get("scope_type") == "company" and a.get("status") == "active"]
            # project membership grant then revoke
            await sync_project_membership(ctx, "u_view", "LEGACY_VIEWER", "PX", "Worker", True, actor_id="u_admin")
            granted = await has_permission(MCtx("u_view", opdb), "budget.read",
                                           module="M2", scope_type="project", scope_id="PX")
            await sync_project_membership(ctx, "u_view", "LEGACY_VIEWER", "PX", "Worker", False, actor_id="u_admin")
            revoked = not await has_permission(MCtx("u_view", opdb), "budget.read",
                                               module="M2", scope_type="project", scope_id="PX")
            return before, after, len(actives), [a["role_id"] for a in actives], granted, revoked
        before, after, n_active, active_roles, granted, revoked = run(go())
        assert before is False and after is True          # promotion takes effect
        assert n_active == 1 and active_roles == ["admin"]  # stale broad grant revoked
        assert granted and revoked                        # membership grant then revoke both apply


# --------------------------------------------------------------------------
# API tests — real FastAPI app via TestClient (mock DB). The permission and
# tenant checks are NOT mocked; only identity (get_current_user) is injected
# and non-authz side deps (enforce_limit, _materialize) are stubbed.
# --------------------------------------------------------------------------
try:
    from fastapi.testclient import TestClient
    HAS_TESTCLIENT = True
except Exception:
    HAS_TESTCLIENT = False


def _patch_db_refs(sysdb, opdb):
    from app.tenancy import registry, resolver
    import app.db as appdb
    import app.routes.auth as r_auth
    import app.routes.activity_budgets as r_budg
    import app.routes.assets_intake_pending as r_intake
    registry.system_db = sysdb
    registry.tenant_registry = sysdb.tenant_registry
    registry.tenant_memberships = sysdb.tenant_memberships
    registry.tenant_role_assignments = sysdb.tenant_role_assignments
    appdb.db = opdb
    r_auth.db = opdb
    r_budg.db = opdb
    r_intake.db = opdb
    import app.utils.audit as uaudit
    uaudit.db = opdb            # log_audit holds a module-level db reference
    import app.deps.auth as dauth
    dauth.db = opdb             # can_access_project (legacy check) uses this in off/shadow

    async def _get_db(tenant_id, require_operational=False):
        return opdb
    resolver.get_tenant_db = _get_db
    # guard imported get_tenant_db by name at import time — patch that binding too,
    # else TenantContext.db() (used by audit) would hit a real Mongo on localhost.
    import app.tenancy.guard as guard
    guard.get_tenant_db = _get_db

    # non-authz side dependencies stubbed (entitlement gate / asset materialize)
    async def _noop(*a, **k):
        return None
    r_auth.enforce_limit = _noop

    async def _mat(*a, **k):
        return {"item_id": "x"}
    r_intake._materialize = _mat


async def _seed_api(sysdb, opdb, boot):
    await opdb.organizations.insert_one({"id": "T1", "name": "BEG"})
    for uid, role in {"u_admin": "Admin", "u_view": "Viewer", "u_out": "Viewer"}.items():
        await opdb.users.insert_one({"id": uid, "org_id": "T1", "role": role,
                                     "is_active": True, "email": f"{uid}@t"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": f"ra_{uid}_T1_legacy", "user_id": uid, "tenant_id": "T1", "role": role,
            "scope_type": "company", "scope_ids": [], "status": "active",
            "created_at": "2026-08-01T00:00:00+00:00", "migrated_from": "users.role"})
        await sysdb.tenant_memberships.insert_one({"id": f"tm_{uid}", "user_id": uid,
                                                   "tenant_id": "T1", "status": "active"})
    await sysdb.tenant_registry.insert_one({"id": "T1", "database_name": "op_test", "status": "active"})
    await opdb.projects.insert_one({"id": "P1", "org_id": "T1", "name": "P1"})
    await opdb.project_team.insert_one({"id": "pt1", "project_id": "P1", "user_id": "u_view",
                                        "role_in_project": "Worker", "active": True})
    await opdb.activity_budgets.insert_one({"id": "b1", "org_id": "T1", "project_id": "P1",
                                            "type": "Общо", "subtype": ""})
    await opdb.asset_intake_pending.insert_one({"id": "i1", "org_id": "T1", "status": "pending", "suggestion": {}})
    await boot.run(apply=True, verify_only=False, revert=False)


def _build_api(mode):
    os.environ["PERMISSION_SERVICE_MODE"] = mode
    from mongomock_motor import AsyncMongoMockClient
    from fastapi import FastAPI
    from app.deps.auth import get_current_user
    import app.routes.auth as r_auth
    import app.routes.activity_budgets as r_budg
    import app.routes.assets_intake_pending as r_intake

    mock = AsyncMongoMockClient()
    sysdb, opdb = mock["s"], mock["o"]
    bp = Path(__file__).parent.parent / "scripts" / "w0_02_bootstrap_permissions.py"
    spec = importlib.util.spec_from_file_location(f"w0_02_boot_{mode}", bp)
    boot = importlib.util.module_from_spec(spec); spec.loader.exec_module(boot)
    boot.op_db = opdb; boot.sys_db = sysdb
    _patch_db_refs(sysdb, opdb)
    run(_seed_api(sysdb, opdb, boot))

    holder = {"user": None}

    async def fake_user():
        return holder["user"]

    app = FastAPI()
    app.include_router(r_auth.router)
    app.include_router(r_budg.router)
    app.include_router(r_intake.router)
    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app), holder, opdb, sysdb


def _u(uid, role):
    return {"id": uid, "org_id": "T1", "role": role, "is_active": True, "email": f"{uid}@t"}


NEWUSER = {"email": "n@t", "password": "Secret123!", "first_name": "N", "last_name": "N", "role": "Viewer", "phone": ""}


@pytest.mark.skipif(not (HAS_MONGOMOCK and HAS_TESTCLIENT), reason="pip install mongomock_motor httpx")
class TestApiEndpoints:
    def _created(self, opdb, email="n@t"):
        return run(opdb.users.count_documents({"email": email}))

    def test_off_mode_matches_legacy(self):
        client, holder, opdb, _ = _build_api("off")
        holder["user"] = _u("u_view", "Viewer")
        assert client.post("/users", json=NEWUSER).status_code == 403      # legacy: not admin
        assert self._created(opdb) == 0                                    # no business change
        holder["user"] = _u("u_admin", "Admin")
        assert client.post("/users", json=NEWUSER).status_code == 201
        assert self._created(opdb) == 1

    def test_enforce_create_denies_and_no_side_effect(self):
        client, holder, opdb, _ = _build_api("enforce")
        holder["user"] = _u("u_view", "Viewer")
        r = client.post("/users", json=NEWUSER)
        assert r.status_code == 403 and r.json()["detail"]["error_code"] == "PERMISSION_DENIED"
        assert self._created(opdb) == 0                                    # NOT created
        denied = run(opdb.audit_events.count_documents({"action": "permission.denied"}))
        assert denied >= 1                                                 # significant denial audited
        holder["user"] = _u("u_admin", "Admin")
        assert client.post("/users", json=NEWUSER).status_code == 201
        assert self._created(opdb) == 1

    def test_enforce_read_scope(self):
        client, holder, opdb, _ = _build_api("enforce")
        holder["user"] = _u("u_view", "Viewer")            # member of P1 (backfilled)
        assert client.get("/projects/P1/activity-budgets").status_code == 200
        holder["user"] = _u("u_out", "Viewer")             # not a member
        assert client.get("/projects/P1/activity-budgets").status_code == 403
        holder["user"] = _u("u_admin", "Admin")
        assert client.get("/projects/P1/activity-budgets").status_code == 200

    def test_enforce_approve_denies_without_side_effect(self):
        client, holder, opdb, _ = _build_api("enforce")
        holder["user"] = _u("u_view", "Viewer")
        assert client.post("/assets/intake/i1/approve").status_code == 403
        assert run(opdb.asset_intake_pending.find_one({"id": "i1"}))["status"] == "pending"  # unchanged
        holder["user"] = _u("u_admin", "Admin")
        assert client.post("/assets/intake/i1/approve").status_code == 200
        assert run(opdb.asset_intake_pending.find_one({"id": "i1"}))["status"] == "approved"

    def test_shadow_uses_legacy_and_runs_action_once(self):
        client, holder, opdb, _ = _build_api("shadow")
        holder["user"] = _u("u_view", "Viewer")
        assert client.post("/users", json=NEWUSER).status_code == 403     # legacy decides
        assert self._created(opdb) == 0
        holder["user"] = _u("u_admin", "Admin")
        assert client.post("/users", json=NEWUSER).status_code == 201
        assert self._created(opdb) == 1                                   # executed exactly once

    def test_require_admin_scope_regression(self):
        """require_admin is now flag-aware, so it affects EVERY require_admin
        route in enforce (here: DELETE /users). Behavior stays admin/owner-only;
        a denial must not perform the delete."""
        client, holder, opdb, _ = _build_api("enforce")
        alive = lambda: run(opdb.users.count_documents({"id": "u_out"}))
        holder["user"] = _u("u_view", "Viewer")
        assert client.delete("/users/u_out").status_code == 403
        assert alive() == 1                                               # NOT deleted
        holder["user"] = _u("u_admin", "Admin")
        assert client.delete("/users/u_out").status_code == 200
        assert alive() == 0
