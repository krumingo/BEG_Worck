"""W0-02 — regression tests for the five application findings PR-01..PR-05.

Every test first describes the OLD defect it guards against. Default backend is
in-process mongomock; with W0_02_REAL_MONGO=1 the same tests run against the
isolated real MongoDB (fail-closed guard, identical to test_w0_02_permission_core).

Scope note: these are router-level / direct-call tests with identity stubs. They
prove the application logic, not full lifespan/middleware; the real-Mongo run
additionally proves the real unique-index enforcement (PR-02).
"""
import os
import asyncio
import importlib.util
from pathlib import Path

import pytest
from w0_02_validation_env import require_runtime_env

if os.environ.get("W0_02_REAL_MONGO") == "1" or os.environ.get("W0_02_VALIDATION") == "1":
    require_runtime_env()

from app.permissions import service
from app.permissions.service import (
    evaluate_permission, has_permission, REASON_ASSIGNMENT_EXPIRED,
    REASON_ASSIGNMENT_REVOKED, REASON_ASSIGNMENT_INACTIVE, REASON_ASSIGNMENT_INVALID,
)

REAL_MONGO = os.environ.get("W0_02_REAL_MONGO") == "1"
try:
    import mongomock_motor  # noqa: F401
    HAS_MONGOMOCK = True
except Exception:
    HAS_MONGOMOCK = False
try:
    import httpx  # noqa: F401
    HAS_HTTPX = True
except Exception:
    HAS_HTTPX = False
_RUN_INTEG = REAL_MONGO or HAS_MONGOMOCK
_TEST_OP_DB = os.environ.get("DB_NAME", "w002_op_test")
_TEST_SYS_DB = os.environ.get("BEG_SYSTEM_DB", "w002_sys_test")
# Second operational database for the two-tenant tests (PR-04). In real-Mongo
# mode it lives next to the sanctioned test DB (same prefix, never production).
_TEST_OP_DB_B = _TEST_OP_DB + "_b"

# Captured at import (collection) time: another test module in the same
# session stubs these route helpers; the PR-04 tests need the REAL ones.
import app.routes.assets_intake_pending as _r_intake_mod
_ORIGINAL_MATERIALIZE = _r_intake_mod._materialize


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
def _make_client():
    if REAL_MONGO:
        require_runtime_env()
        from motor.motor_asyncio import AsyncIOMotorClient
        return AsyncIOMotorClient(os.environ["MONGO_URL"])
    from mongomock_motor import AsyncMongoMockClient
    return AsyncMongoMockClient()


async def _drop_all(*dbs):
    for d in dbs:
        for name in await d.list_collection_names():
            await d[name].drop()


def _load_boot(sysdb, opdb):
    boot_path = Path(__file__).parent.parent / "scripts" / "w0_02_bootstrap_permissions.py"
    spec = importlib.util.spec_from_file_location("w0_02_boot_pr", boot_path)
    boot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boot)
    boot.op_db, boot.sys_db = opdb, sysdb
    return boot


def _bind_registry(sysdb):
    from app.tenancy import registry
    registry.system_db = sysdb
    registry.tenant_registry = sysdb.tenant_registry
    registry.tenant_memberships = sysdb.tenant_memberships
    registry.tenant_role_assignments = sysdb.tenant_role_assignments


def _bind_global_db(opdb):
    import app.db as appdb
    import app.utils.audit as uaudit
    import app.deps.auth as dauth
    import app.deps.modules as dmod
    import app.routes.auth as r_auth
    import app.routes.activity_budgets as r_budg
    import app.routes.assets_intake_pending as r_intake
    import app.routes.assets_qr as r_qr
    import app.routes.asset_item_types as r_types
    for m in (appdb, uaudit, dauth, dmod, r_auth, r_budg, r_intake, r_qr, r_types):
        m.db = opdb
    appdb.users = opdb.users
    appdb.organizations = opdb.organizations


async def _seed_legacy(sysdb, opdb):
    """Same synthetic seed as the validation runner: 4 legacy mirrors, one
    project with two members (Viewer worker, SiteManager)."""
    await opdb.organizations.insert_one({"id": "T1", "name": "BEG"})
    roles = {"u_admin": "Admin", "u_view": "Viewer", "u_tech": "Technician", "u_sm": "SiteManager"}
    for uid, role in roles.items():
        await opdb.users.insert_one({"id": uid, "org_id": "T1", "role": role, "is_active": True})
        await sysdb.tenant_role_assignments.insert_one({
            "id": f"ra_{uid}_T1_legacy", "user_id": uid, "tenant_id": "T1", "role": role,
            "scope_type": "company", "scope_ids": [], "status": "active",
            "created_at": "2026-08-01T00:00:00+00:00", "migrated_from": "users.role"})
    await sysdb.tenant_registry.insert_one({"id": "T1", "database_name": _TEST_OP_DB, "status": "active"})
    await opdb.projects.insert_one({"id": "P1", "org_id": "T1"})
    await opdb.project_team.insert_many([
        {"id": "pt_v", "project_id": "P1", "user_id": "u_view", "role_in_project": "Worker", "active": True},
        {"id": "pt_s", "project_id": "P1", "user_id": "u_sm", "role_in_project": "SiteManager", "active": True},
    ])


async def snapshot(db):
    """Full content + index snapshot of a database (documents without _id)."""
    out = {}
    for name in sorted(await db.list_collection_names()):
        docs = [d async for d in db[name].find({}, {"_id": 0})]
        docs = sorted(docs, key=lambda d: repr(sorted(d.items())))
        idx = await db[name].index_information()
        out[name] = {"documents": docs, "indexes": sorted(idx.keys())}
    return out


async def _doc(db, coll, **q):
    return await db[coll].find_one(q, {"_id": 0})


class MCtx:
    """Direct-call context bound to one operational db (as the routes would)."""
    enforced = True

    def __init__(self, uid, opdb, tenant_id="T1"):
        self.tenant_id, self.user_id, self._db = tenant_id, uid, opdb
        self.user = {"id": uid, "org_id": tenant_id}
        self.mode = "enforce"

    async def db(self, require_operational=False):
        return self._db


# ==========================================================================
# PR-03 — invalid / inactive assignments never grant (pure, always runs)
# ==========================================================================
class FakeCtx:
    def __init__(self, tenant_id="tenant-a", user_id="user-1"):
        self.tenant_id, self.user_id = tenant_id, user_id


def _a(**over):
    a = dict(id="ra_1", user_id="user-1", tenant_id="tenant-a", role_id="admin",
             scope_type="company", scope_id=None, module=None, permissions=[],
             max_amount=None, valid_from=None, valid_to=None, status="active")
    a.update(over)
    return a


def _patch(monkeypatch, assignments):
    async def fake(uid, tid):
        return [x for x in assignments if x["user_id"] == uid and x["tenant_id"] == tid]
    monkeypatch.setattr(service, "_load_assignments", fake)


class TestPR03Evaluator:
    """OLD defect: status != 'revoked' was treated as active, and an unparseable
    valid_from/valid_to silently became an OPEN bound (grant)."""

    @pytest.mark.parametrize("status", ["inactive", "pending", "", None, "ACTIVE", 42])
    def test_non_active_status_denies(self, monkeypatch, status):
        _patch(monkeypatch, [_a(status=status)])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_INACTIVE

    def test_missing_status_key_denies(self, monkeypatch):
        a = _a(); del a["status"]
        _patch(monkeypatch, [a])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_INACTIVE

    @pytest.mark.parametrize("field,value", [
        ("valid_from", "not-a-date"), ("valid_to", "yesterday"),
        ("valid_from", 12345), ("valid_to", {"$date": 1}), ("valid_to", ["2027-01-01"]),
        ("valid_from", "2027-13-45T00:00:00+00:00"),
    ])
    def test_malformed_validity_denies_with_invalid_reason(self, monkeypatch, field, value):
        _patch(monkeypatch, [_a(**{field: value})])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_INVALID

    def test_reversed_interval_denies(self, monkeypatch):
        _patch(monkeypatch, [_a(valid_from="2030-01-01T00:00:00+00:00",
                                valid_to="2020-01-01T00:00:00+00:00")])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_INVALID

    def test_legit_empty_bounds_allow(self, monkeypatch):
        for vf, vt in ((None, None), ("", ""), (None, "")):
            _patch(monkeypatch, [_a(valid_from=vf, valid_to=vt)])
            assert run(evaluate_permission(FakeCtx(), "user.create")).allowed

    def test_active_valid_window_allows(self, monkeypatch):
        _patch(monkeypatch, [_a(valid_from="2020-01-01T00:00:00+00:00",
                                valid_to="2999-01-01T00:00:00+00:00")])
        assert run(evaluate_permission(FakeCtx(), "user.create")).allowed

    def test_invalid_plus_valid_union_allows_via_valid_only(self, monkeypatch):
        _patch(monkeypatch, [_a(id="bad", valid_to="garbage"),
                             _a(id="good", role_id="admin")])
        d = run(evaluate_permission(FakeCtx(), "user.create"))
        assert d.allowed and d.effective_assignment_ids == ["good"]

    def test_invalid_does_not_crash_request(self, monkeypatch):
        _patch(monkeypatch, [_a(id="bad", max_amount="lots"), _a(id="bad2", permissions="x")])
        d = run(evaluate_permission(FakeCtx(), "user.create", amount=5))
        assert not d.allowed and d.reason_code == REASON_ASSIGNMENT_INVALID

    def test_expired_and_revoked_still_deny(self, monkeypatch):
        _patch(monkeypatch, [_a(valid_to="2000-01-01T00:00:00+00:00")])
        assert run(evaluate_permission(FakeCtx(), "user.create")).reason_code == REASON_ASSIGNMENT_EXPIRED
        _patch(monkeypatch, [_a(status="revoked")])
        assert run(evaluate_permission(FakeCtx(), "user.create")).reason_code == REASON_ASSIGNMENT_REVOKED

    def test_no_role_name_fallback(self, monkeypatch):
        # a legacy-looking role string on an inactive record grants nothing
        _patch(monkeypatch, [_a(status="inactive", role="Admin", role_id="admin")])
        assert not run(has_permission(FakeCtx(), "admin.access"))


# ==========================================================================
# PR-01 — migration ownership / idempotency / limited revert
# ==========================================================================
@pytest.mark.skipif(not _RUN_INTEG, reason="needs mongomock_motor or W0_02_REAL_MONGO=1")
class TestPR01Migration:
    """OLD defects: every users.role mirror was rebuilt from `role` on each run
    ($set/upsert), backfill re-activated and overwrote existing project
    assignments, revert deleted EVERY migrated_from=project_team row and
    stripped fields from every mirror, --verify counted only."""

    SENTINEL = {
        "id": "app-sentinel", "user_id": "synthetic-manual", "tenant_id": "T1",
        "role_id": "LEGACY_VIEWER", "scope_type": "project", "scope_id": "P_OTHER",
        "module": None, "permissions": ["budget.read"], "max_amount": 100,
        "valid_from": None, "valid_to": "2027-01-01T00:00:00+00:00",
        "status": "active", "created_by": "test:application",
    }

    async def _env(self):
        client = _make_client()
        sysdb, opdb = client[_TEST_SYS_DB], client[_TEST_OP_DB]
        await _drop_all(sysdb, opdb)
        _bind_registry(sysdb)
        _bind_global_db(opdb)
        await _seed_legacy(sysdb, opdb)
        await sysdb.tenant_role_assignments.insert_one(dict(self.SENTINEL))
        await opdb.audit_events.insert_one({"id": "audit-sentinel", "synthetic": True})
        return client, sysdb, opdb, _load_boot(sysdb, opdb)

    def test_dry_run_changes_nothing(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            s0, o0 = await snapshot(sysdb), await snapshot(opdb)
            assert await boot.run(apply=False, verify_only=False, revert=False) == 0
            return s0 == await snapshot(sysdb), o0 == await snapshot(opdb)
        assert run(go()) == (True, True)

    def test_apply_maps_four_roles_and_exactly_two_backfills(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            o0 = await snapshot(opdb)
            assert await boot.run(apply=True, verify_only=False, revert=False) == 0
            got = {u: (await _doc(sysdb, "tenant_role_assignments", user_id=u, scope_type="company"))["role_id"]
                   for u in ("u_admin", "u_view", "u_tech", "u_sm")}
            proj = await sysdb.tenant_role_assignments.find(
                {"scope_type": "project", "migrated_from": "project_team"}, {"_id": 0}).to_list(None)
            perms = {p["user_id"]: set(p["permissions"]) for p in proj}
            sentinel = await _doc(sysdb, "tenant_role_assignments", id="app-sentinel")
            journal = await sysdb.migration_journal.count_documents({"migration_id": boot.MIGRATION_ID})
            return got, perms, sentinel, o0 == await snapshot(opdb), journal
        got, perms, sentinel, op_same, journal = run(go())
        assert got == {"u_admin": "admin", "u_view": "LEGACY_VIEWER",
                       "u_tech": "LEGACY_TECHNICIAN", "u_sm": "site_manager"}
        assert perms == {"u_view": {"budget.read"}, "u_sm": {"budget.read", "budget.write"}}
        assert sentinel == self.SENTINEL           # app-owned record byte-identical
        assert op_same and journal == 4 + 2 + 4    # 4 upgrades, 2 creates, 4 indexes

    def test_reapply_is_content_idempotent(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            await boot.run(apply=True, verify_only=False, revert=False)
            s1 = await snapshot(sysdb)
            await boot.run(apply=True, verify_only=False, revert=False)
            return s1 == await snapshot(sysdb)
        assert run(go())

    def test_reapply_keeps_revoke_expiry_and_restrictions(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            await boot.run(apply=True, verify_only=False, revert=False)
            coll = sysdb.tenant_role_assignments
            await coll.update_one({"user_id": "u_view", "scope_type": "project"}, {"$set": {
                "status": "revoked", "revoked_by": "test:application", "revoke_reason": "regression"}})
            await coll.update_one({"user_id": "u_sm", "scope_type": "project"}, {"$set": {
                "valid_to": "2020-01-01T00:00:00+00:00", "max_amount": 5}})
            s1 = await snapshot(sysdb)
            assert await boot.run(apply=True, verify_only=False, revert=False) == 0
            return s1 == await snapshot(sysdb)
        assert run(go())

    def test_upgraded_mirror_is_not_rebuilt_from_old_role(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            await boot.run(apply=True, verify_only=False, revert=False)
            # app legitimately changes the authoritative role_id after apply
            await sysdb.tenant_role_assignments.update_one(
                {"id": "ra_u_view_T1_legacy"}, {"$set": {"role_id": "office", "permissions": ["user.read"]}})
            await boot.run(apply=True, verify_only=False, revert=False)
            return await _doc(sysdb, "tenant_role_assignments", id="ra_u_view_T1_legacy")
        d = run(go())
        assert d["role_id"] == "office" and d["permissions"] == ["user.read"]

    def test_conflict_on_unique_key_writes_nothing(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            # a foreign record already owns u_admin's future company key
            await sysdb.tenant_role_assignments.insert_one({
                "id": "foreign", "user_id": "u_admin", "tenant_id": "T1", "role_id": "admin",
                "scope_type": "company", "scope_id": None, "module": None, "status": "active"})
            s0 = await snapshot(sysdb)
            code = await boot.run(apply=True, verify_only=False, revert=False)
            return code, s0 == await snapshot(sysdb), await _doc(sysdb, "tenant_role_assignments", id="foreign")
        code, same, foreign = run(go())
        assert code == 2 and same and foreign is not None

    def test_revert_limited_to_migration_owned_untouched_records(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            legacy_before = {u: await _doc(sysdb, "tenant_role_assignments", user_id=u, scope_type="company")
                             for u in ("u_admin", "u_view", "u_tech", "u_sm")}
            await boot.run(apply=True, verify_only=False, revert=False)
            coll = sysdb.tenant_role_assignments
            # (a) later app-created project assignment with the SAME marker
            late = dict(self.SENTINEL, id="late", user_id="late-user", scope_id="P_LATE",
                        migrated_from="project_team")
            await coll.insert_one(dict(late))
            # (b) backfill legitimately revoked afterwards; (c) mirror modified afterwards
            await coll.update_one({"user_id": "u_view", "scope_type": "project"},
                                  {"$set": {"status": "revoked", "revoked_by": "app"}})
            await coll.update_one({"id": "ra_u_tech_T1_legacy"}, {"$set": {"max_amount": 999}})
            revoked_doc = await _doc(sysdb, "tenant_role_assignments", user_id="u_view", scope_type="project")
            modified_doc = await _doc(sysdb, "tenant_role_assignments", id="ra_u_tech_T1_legacy")
            o0 = await snapshot(opdb)
            # dry-run of revert writes nothing
            s_before = await snapshot(sysdb)
            assert await boot.run(apply=False, verify_only=False, revert=True) == 0
            assert s_before == await snapshot(sysdb)
            assert await boot.run(apply=True, verify_only=False, revert=True) == 0
            return {
                "late": await _doc(sysdb, "tenant_role_assignments", id="late") == late,
                "sentinel": await _doc(sysdb, "tenant_role_assignments", id="app-sentinel") == self.SENTINEL,
                "revoked_kept": await _doc(sysdb, "tenant_role_assignments", user_id="u_view", scope_type="project") == revoked_doc,
                "modified_kept": await _doc(sysdb, "tenant_role_assignments", id="ra_u_tech_T1_legacy") == modified_doc,
                "untouched_restored": all([
                    (await _doc(sysdb, "tenant_role_assignments", id=legacy_before[u]["id"])) == legacy_before[u]
                    for u in ("u_admin", "u_view", "u_sm")]),
                "sm_backfill_removed": await _doc(sysdb, "tenant_role_assignments", user_id="u_sm", scope_type="project") is None,
                "skipped_reported": await sysdb.migration_journal.count_documents(
                    {"revert_skipped_reason": "SKIPPED_MODIFIED"}) == 2,
                "op_same": o0 == await snapshot(opdb),
                "audit_sentinel": await _doc(opdb, "audit_events", id="audit-sentinel") is not None,
            }
        res = run(go())
        assert res == {k: True for k in res}, res

    def test_verify_is_semantic_and_read_only(self):
        async def go():
            _, sysdb, opdb, boot = await self._env()
            before_apply = await boot.run(apply=False, verify_only=True, revert=False)
            await boot.run(apply=True, verify_only=False, revert=False)
            s1 = await snapshot(sysdb)
            ok = await boot.run(apply=False, verify_only=True, revert=False)
            unchanged = s1 == await snapshot(sysdb)
            # a legitimate later revoke is NOT a verify failure
            await sysdb.tenant_role_assignments.update_one(
                {"user_id": "u_view", "scope_type": "project"}, {"$set": {"status": "revoked"}})
            ok_after_revoke = await boot.run(apply=False, verify_only=True, revert=False)
            # broken invariants ARE: a lost project mirror; a mirror never upgraded
            await sysdb.tenant_role_assignments.delete_one({"user_id": "u_sm", "scope_type": "project"})
            broken1 = await boot.run(apply=False, verify_only=True, revert=False)
            await sysdb.tenant_role_assignments.insert_one({
                "id": "ra_u_new_T1_legacy", "user_id": "u_new", "tenant_id": "T1", "role": "Driver",
                "scope_type": "company", "scope_ids": [], "status": "active", "migrated_from": "users.role"})
            broken2 = await boot.run(apply=False, verify_only=True, revert=False)
            return before_apply, ok, unchanged, ok_after_revoke, broken1, broken2
        before_apply, ok, unchanged, ok_after_revoke, broken1, broken2 = run(go())
        assert before_apply != 0            # not-yet-upgraded mirrors -> mismatch
        assert ok == 0 and unchanged and ok_after_revoke == 0 and broken1 != 0 and broken2 != 0

    def test_sync_project_membership_preserves_existing_fields(self):
        """sync_project_membership must not re-create / reset an existing mirror."""
        async def go():
            _, sysdb, opdb, boot = await self._env()
            await boot.run(apply=True, verify_only=False, revert=False)
            from app.permissions.sync import sync_project_membership
            coll = sysdb.tenant_role_assignments
            await coll.update_one({"user_id": "u_view", "scope_type": "project"},
                                  {"$set": {"valid_to": "2030-01-01T00:00:00+00:00", "max_amount": 7}})
            before = await _doc(sysdb, "tenant_role_assignments", user_id="u_view", scope_type="project")
            ctx = MCtx("u_admin", opdb)
            await sync_project_membership(ctx, "u_view", "LEGACY_VIEWER", "P1", "Worker", True, actor_id="u_admin")
            after_same = await _doc(sysdb, "tenant_role_assignments", user_id="u_view", scope_type="project")
            await sync_project_membership(ctx, "u_view", "LEGACY_VIEWER", "P1", "SiteManager", True, actor_id="u_admin")
            after_change = await _doc(sysdb, "tenant_role_assignments", user_id="u_view", scope_type="project")
            n = await coll.count_documents({"user_id": "u_view", "scope_type": "project"})
            return before, after_same, after_change, n
        before, after_same, after_change, n = run(go())
        assert after_same == before                          # replay: nothing changes
        assert n == 1 and after_change["id"] == before["id"]  # same identity
        assert set(after_change["permissions"]) == {"budget.read", "budget.write"}
        assert after_change["valid_to"] == before["valid_to"] and after_change["max_amount"] == 7


# ==========================================================================
# PR-02 — one identity per logical key in company role sync
# ==========================================================================
@pytest.mark.skipif(not _RUN_INTEG, reason="needs mongomock_motor or W0_02_REAL_MONGO=1")
class TestPR02Identity:
    """OLD defects: identity by freshly generated id (a migrated record was left
    and a second one created -> duplicate logical key / unique-index violation),
    every other active company assignment revoked (manual grants included),
    upsert overwrote the record on a plain replay."""

    async def _env(self):
        client = _make_client()
        sysdb, opdb = client[_TEST_SYS_DB], client[_TEST_OP_DB]
        await _drop_all(sysdb, opdb)
        _bind_registry(sysdb)
        _bind_global_db(opdb)
        await _seed_legacy(sysdb, opdb)
        boot = _load_boot(sysdb, opdb)
        await boot.run(apply=True, verify_only=False, revert=False)
        from app.tenancy import registry
        await registry.ensure_permission_indexes()
        return client, sysdb, opdb

    async def _company(self, sysdb, uid):
        return await sysdb.tenant_role_assignments.find(
            {"user_id": uid, "scope_type": "company"}, {"_id": 0}).sort("id", 1).to_list(None)

    def test_migration_admin_admin_keeps_one_identity(self):
        async def go():
            _, sysdb, opdb = await self._env()
            from app.permissions.sync import grant_company_role
            ctx = MCtx("u_admin", opdb)
            a1 = await grant_company_role(ctx, "u_admin", "Admin", actor_id="u_admin")
            a2 = await grant_company_role(ctx, "u_admin", "Admin", actor_id="u_admin")
            rows = await self._company(sysdb, "u_admin")
            events = await opdb.audit_events.count_documents({"entity_id": "ra_u_admin_T1_legacy"})
            return a1["id"], a2["id"], rows, events
        id1, id2, rows, events = run(go())
        assert id1 == id2 == "ra_u_admin_T1_legacy"         # migrated id kept
        assert len(rows) == 1 and rows[0]["status"] == "active"
        assert events == 0                                     # replay: no audit noise

    def test_technician_admin_technician_reuses_existing_record(self):
        async def go():
            _, sysdb, opdb = await self._env()
            from app.permissions.sync import grant_company_role
            ctx = MCtx("u_admin", opdb)
            await grant_company_role(ctx, "u_tech", "Admin", actor_id="u_admin")
            mid = await self._company(sysdb, "u_tech")
            back = await grant_company_role(ctx, "u_tech", "Technician", actor_id="u_admin")
            rows = await self._company(sysdb, "u_tech")
            can_admin = await has_permission(MCtx("u_tech", opdb), "admin.access")
            can_submit = await has_permission(MCtx("u_tech", opdb), "asset_intake.submit", scope_type="company")
            kinds = [e["action"].rsplit(".", 1)[-1] async for e in
                     opdb.audit_events.find({"entity_type": "role_assignment"}).sort("sequence", 1)]
            return mid, back, rows, can_admin, can_submit, kinds
        mid, back, rows, can_admin, can_submit, kinds = run(go())
        assert {r["role_id"]: r["status"] for r in mid} == {"LEGACY_TECHNICIAN": "revoked", "admin": "active"}
        assert back["id"] == "ra_u_tech_T1_legacy"            # back to the old identity
        assert {r["role_id"]: r["status"] for r in rows} == {"LEGACY_TECHNICIAN": "active", "admin": "revoked"}
        assert len(rows) == 2                                  # no third document
        assert not can_admin and can_submit
        assert kinds == ["revoked", "granted", "revoked", "granted"]

    def test_independent_manual_company_grant_not_revoked(self):
        async def go():
            _, sysdb, opdb = await self._env()
            from app.permissions.sync import grant_company_role
            manual = {"id": "manual-acc", "user_id": "u_tech", "tenant_id": "T1", "role_id": "accountant",
                      "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
                      "status": "active", "created_by": "krum", "note": "manual multi-role grant"}
            await sysdb.tenant_role_assignments.insert_one(dict(manual))
            await grant_company_role(MCtx("u_admin", opdb), "u_tech", "Admin", actor_id="u_admin")
            synced = await _doc(sysdb, "tenant_role_assignments", id="ra_u_tech_T1_legacy")
            return await _doc(sysdb, "tenant_role_assignments", id="manual-acc"), manual, synced["status"]
        got, manual, synced_status = run(go())
        assert got == manual                       # independent manual role untouched
        assert synced_status == "revoked"          # only the synchronized one was revoked

    def test_interrupted_grant_then_retry_completes_once(self):
        """Audit write fails after the assignment was written: the retry must
        neither duplicate the record nor lose the audit event."""
        async def go():
            _, sysdb, opdb = await self._env()
            from app.permissions import sync as psync
            from app.permissions import audit_hooks
            ctx = MCtx("u_admin", opdb)
            real_record = audit_hooks.record_event
            calls = {"n": 0}

            async def flaky(db, event):
                calls["n"] += 1
                if calls["n"] == 2:            # the GRANT event (after the revoke) fails
                    raise RuntimeError("audit store down")
                return await real_record(db, event)
            audit_hooks.record_event = flaky
            try:
                with pytest.raises(RuntimeError):
                    await psync.grant_company_role(ctx, "u_tech", "Admin", actor_id="u_admin")
                mid = await self._company(sysdb, "u_tech")
                ev_mid = await opdb.audit_events.count_documents({"action": "permission.role_assignment.granted"})
                audit_hooks.record_event = real_record
                again = await psync.grant_company_role(ctx, "u_tech", "Admin", actor_id="u_admin")
                rows = await self._company(sysdb, "u_tech")
                ev = await opdb.audit_events.count_documents({"action": "permission.role_assignment.granted"})
                third = await psync.grant_company_role(ctx, "u_tech", "Admin", actor_id="u_admin")
                ev3 = await opdb.audit_events.count_documents({"action": "permission.role_assignment.granted"})
                return mid, ev_mid, again, rows, ev, third, ev3
            finally:
                audit_hooks.record_event = real_record
        mid, ev_mid, again, rows, ev, third, ev3 = run(go())
        assert any(r["role_id"] == "admin" and r["status"] == "active" for r in mid) and ev_mid == 0
        assert len(rows) == 2 and again["id"] == "ra_u_tech_T1_admin_company"
        assert ev == 1 and ev3 == 1 and third["id"] == again["id"]

    def test_duplicate_key_is_read_back_not_swallowed(self):
        async def go():
            _, sysdb, opdb = await self._env()
            from app.tenancy import registry
            from app.permissions import sync as psync
            # a concurrent writer inserts the same logical key just before us
            real_find = registry.find_role_assignment_by_key
            state = {"raced": False}

            async def racing_find(*a, **k):
                r = await real_find(*a, **k)
                if r is None and not state["raced"]:
                    state["raced"] = True
                    await sysdb.tenant_role_assignments.insert_one({
                        "id": "ra_u_view_T1_admin_company", "user_id": "u_view", "tenant_id": "T1",
                        "role_id": "admin", "scope_type": "company", "scope_id": None, "module": None,
                        "permissions": [], "status": "active", "revision": 1, "sync_source": "users.role"})
                return r
            registry.find_role_assignment_by_key = racing_find
            try:
                got = await psync.grant_company_role(MCtx("u_admin", opdb), "u_view", "Admin", actor_id="u_admin")
            finally:
                registry.find_role_assignment_by_key = real_find
            n = await sysdb.tenant_role_assignments.count_documents({"user_id": "u_view", "role_id": "admin"})
            return got["id"], n
        gid, n = run(go())
        assert gid == "ra_u_view_T1_admin_company" and n == 1

    def test_unique_index_survives_and_is_non_partial(self):
        async def go():
            _, sysdb, opdb = await self._env()
            from app.permissions.sync import grant_company_role
            ctx = MCtx("u_admin", opdb)
            await grant_company_role(ctx, "u_tech", "Admin", actor_id="u_admin")
            await grant_company_role(ctx, "u_tech", "Technician", actor_id="u_admin")
            await grant_company_role(ctx, "u_tech", "Admin", actor_id="u_admin")
            idx = await sysdb.tenant_role_assignments.index_information()
            # inserting a second doc with an existing key must be refused by the index
            dup_refused = False
            try:
                await sysdb.tenant_role_assignments.insert_one({
                    "id": "dup", "user_id": "u_tech", "tenant_id": "T1", "role_id": "admin",
                    "scope_type": "company", "scope_id": None, "module": None, "status": "revoked"})
            except Exception as exc:
                dup_refused = "duplicate" in str(exc).lower() or type(exc).__name__ == "DuplicateKeyError"
            rows = await self._company(sysdb, "u_tech")
            return "uniq_assignment" in idx, idx["uniq_assignment"].get("unique"), dup_refused, len(rows)
        present, unique, dup_refused, n = run(go())
        assert present and unique and dup_refused and n == 2


# ==========================================================================
# PR-04 / PR-05 — routes: two real DB handles, off/shadow/enforce, faults
# ==========================================================================
def _u(uid, role, org="T1", active_tenant=None):
    u = {"id": uid, "org_id": org, "role": role, "is_active": True, "email": f"{uid}@t"}
    if active_tenant:
        u["active_tenant_id"] = active_tenant
    return u


NEWUSER = {"email": "n@t", "password": "Secret123!", "first_name": "N", "last_name": "N",
           "role": "Viewer", "phone": ""}


async def _two_tenant_env(mode):
    """Tenant A (legacy installation, global db) and tenant B (own database).
    Identity u_multi: legacy org A, active tenant B, with different assignments
    in each tenant; both DBs hold records with the SAME local ids."""
    os.environ["PERMISSION_SERVICE_MODE"] = mode
    client = _make_client()
    sysdb, dba, dbb = client[_TEST_SYS_DB], client[_TEST_OP_DB], client[_TEST_OP_DB_B]
    await _drop_all(sysdb, dba, dbb)
    _bind_registry(sysdb)
    _bind_global_db(dba)                       # legacy global handle == tenant A
    from app.tenancy import resolver, registry
    import app.tenancy.guard as guard
    dbs = {_TEST_OP_DB: dba, _TEST_OP_DB_B: dbb}

    async def _get_db(tenant_id, require_operational=False):
        t = await registry.get_tenant(tenant_id)
        if not t:
            raise resolver.TenantNotFound(tenant_id)
        return dbs[registry.resolve_database_name(t)]
    resolver.get_tenant_db = _get_db
    guard.get_tenant_db = _get_db

    import app.routes.auth as r_auth
    import app.routes.assets_intake_pending as r_intake

    async def _noop(*a, **k):
        return None
    r_auth.enforce_limit = _noop
    r_intake._materialize = _ORIGINAL_MATERIALIZE     # real writes, not another module's stub
    real_mat = _ORIGINAL_MATERIALIZE

    await sysdb.tenant_registry.insert_many([
        {"id": "A", "database_name": _TEST_OP_DB, "status": "active"},
        {"id": "B", "database_name": _TEST_OP_DB_B, "status": "active"}])
    for tid, db in (("A", dba), ("B", dbb)):
        await db.organizations.insert_one({"id": tid, "name": tid})
        await db.projects.insert_one({"id": "P1", "org_id": tid, "name": "P1"})
        await db.activity_budgets.insert_one({"id": "b1", "org_id": tid, "project_id": "P1",
                                             "type": "Общо", "subtype": "", "marker": tid})
        await db.asset_intake_pending.insert_one({"id": "i1", "org_id": tid, "status": "pending",
                                                  "suggestion": {"name": "drill-" + tid}, "marker": tid})
        await db.users.insert_one({"id": "u_target", "org_id": tid, "role": "Viewer", "is_active": True,
                                   "email": "target@t", "marker": tid})
    # identity: legacy org A, active tenant B; admin in B, plain viewer in A
    await dba.users.insert_one(_u("u_multi", "Viewer", "A", "B"))
    for tid in ("A", "B"):
        await sysdb.tenant_memberships.insert_one({"id": f"tm_u_multi_{tid}", "user_id": "u_multi",
                                                   "tenant_id": tid, "status": "active"})
    await sysdb.tenant_role_assignments.insert_many([
        {"id": "ra_multi_A", "user_id": "u_multi", "tenant_id": "A", "role_id": "LEGACY_VIEWER",
         "scope_type": "company", "scope_id": None, "module": None, "permissions": [], "status": "active"},
        {"id": "ra_multi_B", "user_id": "u_multi", "tenant_id": "B", "role_id": "admin",
         "scope_type": "company", "scope_id": None, "module": None, "permissions": [], "status": "active"},
    ])

    from fastapi import FastAPI
    from app.deps.auth import get_current_user
    import app.routes.activity_budgets as r_budg
    holder = {"user": None}

    async def fake_user():
        return holder["user"]
    app = FastAPI()
    app.include_router(r_auth.router)
    app.include_router(r_budg.router)
    app.include_router(r_intake.router)
    app.dependency_overrides[get_current_user] = fake_user
    return app, holder, sysdb, dba, dbb, real_mat


def _client(app, raise_app_exceptions=True):
    from httpx import AsyncClient, ASGITransport
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
                       base_url="http://t")


@pytest.mark.skipif(not (_RUN_INTEG and HAS_HTTPX), reason="needs httpx and (mongomock_motor or W0_02_REAL_MONGO=1)")
class TestPR04SingleTenant:
    """OLD defect: enforce authorized against the active tenant (B) but the
    handler read/wrote the GLOBAL db with user["org_id"] (A), and audit fell
    back to the global db."""

    def test_enforce_read_uses_active_tenant_db(self):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r = await ac.get("/projects/P1/activity-budgets")
                return r.status_code, [b["marker"] for b in r.json()["items"]]
        code, markers = run(go())
        assert code == 200 and markers == ["B"]              # NOT tenant A's record

    def test_enforce_create_writes_and_audits_in_active_tenant_only(self):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            a0 = await snapshot(dba)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r = await ac.post("/users", json=NEWUSER)
                created = await _doc(dbb, "users", email="n@t")
                assignment = await _doc(sysdb, "tenant_role_assignments", user_id=created["id"]) if created else None
                return (r.status_code, created and created["org_id"], assignment and assignment["tenant_id"],
                        await dbb.audit_events.count_documents({"action": "permission.role_assignment.granted"}),
                        await dbb.audit_logs.count_documents({"action": "created"}),
                        await dbb.audit_idempotency.count_documents({"status": "completed"}),
                        a0 == await snapshot(dba))
        code, org, tid, ev, legacy_log, idem, a_same = run(go())
        assert code == 201 and org == "B" and tid == "B"
        assert ev == 1 and legacy_log == 1 and idem == 1
        assert a_same                                          # tenant A untouched, no audit there

    def test_enforce_update_and_approve_touch_only_tenant_b(self):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            a0 = await snapshot(dba)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r1 = await ac.put("/users/u_target", json={"first_name": "Z"})
                r2 = await ac.post("/assets/intake/i1/approve")
                return (r1.status_code, (await _doc(dbb, "users", id="u_target"))["first_name"],
                        (await _doc(dba, "users", id="u_target")).get("first_name"),
                        r2.status_code, (await _doc(dbb, "asset_intake_pending", id="i1"))["status"],
                        (await _doc(dba, "asset_intake_pending", id="i1"))["status"],
                        await dbb.asset_units.count_documents({}), await dba.asset_units.count_documents({}),
                        a0 == await snapshot(dba))
        r1, b_name, a_name, r2, b_status, a_status, b_units, a_units, a_same = run(go())
        assert r1 == 200 and b_name == "Z" and a_name is None
        assert r2 == 200 and b_status == "approved" and a_status == "pending"
        assert b_units == 1 and a_units == 0 and a_same

    def test_enforce_deny_audits_in_active_tenant_and_no_write(self):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            # flip: active tenant A where u_multi is only a viewer
            b0 = await snapshot(dbb)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "A")
                r = await ac.post("/users", json=NEWUSER)
                r2 = await ac.post("/assets/intake/i1/approve")
                return (r.status_code, r2.status_code,
                        await dba.audit_events.count_documents({"action": "permission.denied"}),
                        await dbb.audit_events.count_documents({"action": "permission.denied"}),
                        await dba.users.count_documents({"email": "n@t"}), b0 == await snapshot(dbb))
        c1, c2, den_a, den_b, created, b_same = run(go())
        assert c1 == 403 and c2 == 403 and den_a == 2 and den_b == 0 and created == 0 and b_same

    def test_foreign_resource_answers_404_without_touching_other_db(self):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            await dbb.asset_intake_pending.delete_many({"id": "i1"})   # only A still has i1
            a0 = await snapshot(dba)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r = await ac.post("/assets/intake/i1/approve")
                return r.status_code, a0 == await snapshot(dba)
        code, a_same = run(go())
        assert code == 404 and a_same

    def test_off_and_shadow_keep_legacy_org_path(self):
        for mode in ("off", "shadow"):
            async def go():
                app, holder, sysdb, dba, dbb, _ = await _two_tenant_env(mode)
                b0 = await snapshot(dbb)
                async with _client(app) as ac:
                    holder["user"] = _u("u_multi", "Admin", "A", "B")    # legacy role decides
                    r = await ac.get("/projects/P1/activity-budgets")
                    r2 = await ac.post("/assets/intake/i1/approve")
                    return ([b["marker"] for b in r.json()["items"]], r2.status_code,
                            (await _doc(dba, "asset_intake_pending", id="i1"))["status"],
                            b0 == await snapshot(dbb))
            markers, code, a_status, b_same = run(go())
            assert markers == ["A"] and code == 200 and a_status == "approved" and b_same, mode

    def test_require_admin_refuses_mismatched_data_path_in_enforce(self):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            a0, b0 = await snapshot(dba), await snapshot(dbb)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")   # admin in B, data path = A
                r = await ac.delete("/users/u_target")
                return r.status_code, r.json()["detail"]["error_code"], a0 == await snapshot(dba), b0 == await snapshot(dbb)
        code, err, a_same, b_same = run(go())
        assert code == 409 and err == "TENANT_DATA_PATH_NOT_MIGRATED" and a_same and b_same

    def test_resolver_failure_in_enforce_is_not_allow_and_not_global_fallback(self):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            import app.tenancy.guard as guard
            from app.tenancy import resolver

            async def broken(tenant_id, require_operational=False):
                raise resolver.TenantNotFound("registry unavailable")
            guard.get_tenant_db = broken
            a0 = await snapshot(dba)
            async with _client(app, raise_app_exceptions=False) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r = await ac.post("/users", json=NEWUSER)
                return (r.status_code, await dba.users.count_documents({"email": "n@t"}),
                        await dbb.users.count_documents({"email": "n@t"}), a0 == await snapshot(dba))
        code, created_a, created_b, a_same = run(go())
        assert code >= 500 and created_a == 0 and created_b == 0 and a_same


@pytest.mark.skipif(not (_RUN_INTEG and HAS_HTTPX), reason="needs httpx and (mongomock_motor or W0_02_REAL_MONGO=1)")
class TestPR05OffShadowFaults:
    """OLD defects: off mode resolved the tenant through the registry
    (_safe_ctx), shadow evaluation errors propagated / were not reported, sync
    failures after a business write had no recorded state and no retry path,
    mode was re-read between authorization and the write."""

    def _break_registry(self, monkeypatch, sysdb):
        from app.tenancy import registry
        calls = {"n": 0}

        async def down(*a, **k):
            calls["n"] += 1
            raise RuntimeError("system registry unreachable")
        for name in ("list_role_assignments", "get_tenant", "get_membership",
                     "get_memberships_for_user", "find_role_assignment_by_key",
                     "insert_role_assignment", "get_role_assignment"):
            monkeypatch.setattr(registry, name, down)
        return calls

    def test_off_never_touches_registry(self, monkeypatch):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("off")
            calls = self._break_registry(monkeypatch, sysdb)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Admin", "A", "B")
                r = await ac.post("/users", json=NEWUSER)
                r2 = await ac.get("/projects/P1/activity-budgets")
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r3 = await ac.post("/users", json=dict(NEWUSER, email="m@t"))
                return (r.status_code, r2.status_code, r3.status_code, calls["n"],
                        await dba.users.count_documents({"email": "n@t"}),
                        await sysdb.tenant_role_assignments.count_documents({"tenant_id": "A", "scope_type": "company", "created_by": {"$exists": True}}))
        c1, c2, c3, calls, created, synced = run(go())
        assert (c1, c2, c3) == (201, 200, 403) and calls == 0 and created == 1 and synced == 0

    def test_shadow_registry_down_reports_and_keeps_legacy_result(self, monkeypatch, caplog):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("shadow")
            self._break_registry(monkeypatch, sysdb)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Admin", "A", "B")
                with caplog.at_level("WARNING", logger="permissions.shadow"):
                    r = await ac.post("/users", json=NEWUSER)
                    holder["user"] = _u("u_multi", "Viewer", "A", "B")
                    r2 = await ac.post("/users", json=dict(NEWUSER, email="m@t"))
                return (r.status_code, r2.status_code, await dba.users.count_documents({"email": "n@t"}),
                        await dba.audit_idempotency.find_one({"status": "failed"}, {"_id": 0}))
        c1, c2, created, failed = run(go())
        assert c1 == 201 and c2 == 403 and created == 1            # legacy decides, exactly once
        text = caplog.text
        assert "SHADOW_EVALUATION_FAILED" in text and "SHADOW_SYNC_FAILED" in text
        assert "OLD_ALLOW_NEW_ALLOW" not in text and "OLD_ALLOW_NEW_DENY" not in text
        assert failed and failed["error_code"] == "SHADOW_SYNC_FAILED"   # visible, not silent

    def test_shadow_evaluation_timeout_is_reported_not_parity(self, monkeypatch, caplog):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("shadow")
            from app.permissions import deps as pdeps
            monkeypatch.setattr(pdeps, "SHADOW_EVALUATION_TIMEOUT_S", 0.05)

            async def slow(uid, tid):
                await asyncio.sleep(1.0)
                return []
            monkeypatch.setattr(service, "_load_assignments", slow)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Admin", "A", "B")
                with caplog.at_level("WARNING", logger="permissions.shadow"):
                    r = await ac.get("/projects/P1/activity-budgets")
                return r.status_code
        assert run(go()) == 200
        assert "SHADOW_EVALUATION_FAILED" in caplog.text and "OLD_ALLOW_NEW" not in caplog.text

    def test_enforce_sync_failure_after_business_write_is_recorded_and_recoverable(self, monkeypatch):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            from app.permissions import sync as psync
            import app.routes.auth as r_auth
            real_grant = psync.grant_company_role
            fail = {"on": True}

            async def flaky(*a, **k):
                if fail["on"]:
                    raise RuntimeError("system db unreachable")
                return await real_grant(*a, **k)
            monkeypatch.setattr(r_auth, "grant_company_role", flaky)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r1 = await ac.post("/users", json=NEWUSER)
                created = await _doc(dbb, "users", email="n@t")
                state1 = await _doc(dbb, "audit_idempotency", action="user.create")
                assigned1 = await sysdb.tenant_role_assignments.count_documents({"user_id": created["id"]})
                # the new user has NO assignment -> denied everywhere in enforce (safe side)
                denied = not await has_permission(MCtx(created["id"], dbb, "B"), "admin.access")
                # a different payload for the (now existing) email: legacy 400, not a replay
                r_conf = await ac.post("/users", json=dict(NEWUSER, first_name="Other"))
                fail["on"] = False
                r2 = await ac.post("/users", json=NEWUSER)             # same request: recovery
                state2 = await _doc(dbb, "audit_idempotency", action="user.create")
                users = await dbb.users.count_documents({"email": "n@t"})
                assigned2 = await sysdb.tenant_role_assignments.count_documents({"user_id": created["id"]})
                events = await dbb.audit_events.count_documents({"action": "permission.role_assignment.granted"})
                legacy_logs = await dbb.audit_logs.count_documents({"entity_id": created["id"]})
                r3 = await ac.post("/users", json=NEWUSER)             # after completion: legacy contract
                return (r1.status_code, r1.json()["detail"], state1, assigned1, denied, r_conf.status_code,
                        r2.status_code, r2.json()["id"], created["id"], state2, users, assigned2, events,
                        legacy_logs, r3.status_code)
        (c1, detail, s1, a1, denied, c_conf, c2, id2, id1, s2, users, a2, events, logs, c3) = run(go())
        assert c1 == 503 and detail["error_code"] == "PERMISSION_SYNC_FAILED" and detail["state"] == "failed"
        assert s1["status"] == "failed" and s1["steps_done"] == ["business"] and a1 == 0 and denied
        assert c_conf == 400
        assert c2 == 201 and id2 == id1 and s2["status"] == "completed"
        assert users == 1 and a2 == 1 and events == 1 and logs == 1      # nothing done twice
        assert c3 == 400                                                  # email exists (legacy contract)

    def test_enforce_role_change_sync_first_no_stale_broad_grant(self, monkeypatch):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            # u_target is currently an admin in B (authoritative) and users.role Admin
            await dbb.users.update_one({"id": "u_target"}, {"$set": {"role": "Admin"}})
            await sysdb.tenant_role_assignments.insert_one({
                "id": "ra_target_admin", "user_id": "u_target", "tenant_id": "B", "role_id": "admin",
                "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
                "status": "active", "sync_source": "users.role", "revision": 1})
            import app.routes.auth as r_auth
            real_log = r_auth.log_audit
            fail = {"on": True}

            async def flaky_log(*a, **k):
                if fail["on"]:
                    raise RuntimeError("legacy audit unavailable")
                return await real_log(*a, **k)
            monkeypatch.setattr(r_auth, "log_audit", flaky_log)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                r1 = await ac.put("/users/u_target", json={"role": "Viewer"})       # demotion
                admin_after_fail = await has_permission(MCtx("u_target", dbb, "B"), "admin.access")
                role_after_fail = (await _doc(dbb, "users", id="u_target"))["role"]
                state1 = await _doc(dbb, "audit_idempotency", action="user.update")
                fail["on"] = False
                r2 = await ac.put("/users/u_target", json={"role": "Viewer"})       # retry
                state2 = await _doc(dbb, "audit_idempotency", action="user.update")
                logs = await dbb.audit_logs.count_documents({"entity_id": "u_target"})
                revoked = await _doc(sysdb, "tenant_role_assignments", id="ra_target_admin")
                return (r1.status_code, admin_after_fail, role_after_fail, state1["status"], state1["steps_done"],
                        r2.status_code, state2["status"], logs, revoked["status"])
        c1, admin_after_fail, role_after_fail, st1, steps1, c2, st2, logs, revoked = run(go())
        assert c1 == 503 and not admin_after_fail                # revoke NOT lost even though the write failed
        assert role_after_fail == "Viewer" and st1 == "failed" and steps1 == ["sync", "business"]
        assert c2 == 200 and st2 == "completed" and logs == 1 and revoked == "revoked"

    def test_grant_and_revoke_work_after_recovery(self, monkeypatch):
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("enforce")
            from app.permissions import sync as psync
            import app.routes.auth as r_auth
            real_grant = psync.grant_company_role
            fail = {"on": True}

            async def flaky(*a, **k):
                if fail["on"]:
                    raise RuntimeError("down")
                return await real_grant(*a, **k)
            monkeypatch.setattr(r_auth, "grant_company_role", flaky)
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Viewer", "A", "B")
                assert (await ac.post("/users", json=NEWUSER)).status_code == 503
                fail["on"] = False
                assert (await ac.post("/users", json=NEWUSER)).status_code == 201
                uid = (await _doc(dbb, "users", email="n@t"))["id"]
                assert (await ac.put(f"/users/{uid}", json={"role": "Admin"})).status_code == 200
                promoted = await has_permission(MCtx(uid, dbb, "B"), "admin.access")
                assert (await ac.put(f"/users/{uid}", json={"role": "Viewer"})).status_code == 200
                demoted = not await has_permission(MCtx(uid, dbb, "B"), "admin.access")
                rows = await sysdb.tenant_role_assignments.find({"user_id": uid}, {"_id": 0}).to_list(None)
                return promoted, demoted, sorted((r["role_id"], r["status"]) for r in rows)
        promoted, demoted, rows = run(go())
        assert promoted and demoted
        assert rows == [("LEGACY_VIEWER", "active"), ("admin", "revoked")]

    def test_mode_is_fixed_once_per_operation(self, monkeypatch):
        """Flipping the env between authorization and the write must not change
        the operation's semantics (the handler uses ctx.mode)."""
        async def go():
            app, holder, sysdb, dba, dbb, _ = await _two_tenant_env("off")
            import app.routes.auth as r_auth
            calls = {"n": 0}
            real = r_auth.grant_company_role

            async def counting(*a, **k):
                calls["n"] += 1
                return await real(*a, **k)
            monkeypatch.setattr(r_auth, "grant_company_role", counting)
            real_limit = r_auth.enforce_limit

            async def flip(*a, **k):
                os.environ["PERMISSION_SERVICE_MODE"] = "enforce"   # env flips mid-request
                return await real_limit(*a, **k)
            r_auth.enforce_limit = flip
            async with _client(app) as ac:
                holder["user"] = _u("u_multi", "Admin", "A", "B")
                r = await ac.post("/users", json=NEWUSER)
                return r.status_code, calls["n"], await dba.users.count_documents({"email": "n@t"})
        code, syncs, created = run(go())
        assert code == 201 and syncs == 0 and created == 1       # stayed on the 'off' path
