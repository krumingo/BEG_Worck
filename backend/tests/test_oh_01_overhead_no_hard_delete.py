"""
OH-01 — overhead records are never hard-deleted; a re-allocation is a new version.

Package: docs/architecture/tasks/OH-01_OVERHEAD_NO_HARD_DELETE.md (CLAUDE.md §2.9, §7, §14;
FLOW-024; R29). Every case runs in PERMISSION_SERVICE_MODE off / shadow / enforce, against
``mongomock_motor`` always and against a disposable LOCAL MongoDB (replica set) when
``W0_03_REAL_MONGO_URL`` is set — one database per test, dropped afterwards. Authentication is
real: a JWT the route verifies and a user ``get_current_user`` loads from the database.

1. used category / cost / asset -> 409 OVERHEAD_RECORD_IN_USE, the document is byte-equal;
2. unused category / cost / asset -> archived (who/when/why), still in the database, hidden
   from the default list, visible with include_archived; canonical AuditEvent written;
   a repeat with the same key replays, nothing written twice;
3. allocate ×3 (initial + 2 re-allocations) -> 3 versions in the database, the reports
   (snapshot detail, /overhead/allocations, project P&L) show only the last one and the sum
   is not doubled; the replay of a key writes nothing; a different body under a key -> 409;
4. a non-finance role -> 403 and nothing written; no Idempotency-Key -> 428 and nothing written;
5. an archived cost / asset is not summed by a new snapshot.

    PYTHONPATH=. pytest tests/test_oh_01_overhead_no_hard_delete.py -q --noconftest
"""
import asyncio
import uuid

import pytest

ORG = "ORG-OH01"
PROJ_A, PROJ_B = "P-OH01-A", "P-OH01-B"
MODES = ("off", "shadow", "enforce")
BUSINESS = ("overhead_categories", "overhead_costs", "overhead_assets",
            "overhead_snapshots", "project_overhead_allocations")


def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


# ═══════════════════════════════════════════════════════════════════ harness
USERS = {
    "owner": "Owner", "admin": "Admin", "accountant": "Accountant",
    "sitemanager": "SiteManager", "technician": "Technician", "viewer": "Viewer",
}


async def _seed(op, sysdb):
    """The tenant is REGISTERED (registry + memberships + role assignments in a separate
    system database), so enforce-mode routes — also #69's require_money_write on compute —
    resolve it like a real installation."""
    from app.permissions.catalog import LEGACY_ROLE_MAP
    from app.services.overhead_lifecycle import ensure_overhead_indexes
    await ensure_overhead_indexes(op)        # what server.py startup / onboarding do (OH01-3)
    await op.organizations.insert_one({"id": ORG, "name": "OH-01 Org"})
    await op.subscriptions.insert_one({"org_id": ORG, "plan_id": "pro", "status": "active"})
    await sysdb.tenant_registry.insert_one({"id": ORG, "legacy_org_id": ORG, "status": "active",
                                            "database_name": op.name})
    for uid, role in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@oh01.test", "first_name": uid})
        await sysdb.tenant_memberships.insert_one({"id": "tm_%s" % uid, "user_id": uid,
                                                   "tenant_id": ORG, "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_%s" % uid, "user_id": uid, "tenant_id": ORG,
            "role_id": LEGACY_ROLE_MAP[role], "scope_type": "company", "scope_id": None,
            "module": None, "permissions": [], "status": "active", "sync_source": "users.role"})
    await op.projects.insert_many([
        {"id": PROJ_A, "org_id": ORG, "code": "A", "name": "Project A", "status": "Active"},
        {"id": PROJ_B, "org_id": ORG, "code": "B", "name": "Project B", "status": "Active"},
    ])
    # 3 person-days on A, 1 on B in October
    await op.attendance_entries.insert_many([
        {"id": "att-%d" % i, "org_id": ORG, "user_id": u, "date": d, "status": "Present",
         "project_id": p}
        for i, (u, d, p) in enumerate([
            ("technician", "2026-10-05", PROJ_A), ("technician", "2026-10-06", PROJ_A),
            ("viewer", "2026-10-05", PROJ_A), ("viewer", "2026-10-06", PROJ_B)])
    ])
    await op.work_reports.insert_many([
        {"id": "wr-1", "org_id": ORG, "project_id": PROJ_A, "date": "2026-10-05",
         "status": "Approved", "total_hours": 30},
        {"id": "wr-2", "org_id": ORG, "project_id": PROJ_B, "date": "2026-10-06",
         "status": "Approved", "total_hours": 10},
    ])


def _h(who="owner", key=None):
    from app.deps.auth import create_token
    h = {"Authorization": "Bearer " + create_token(
        {"user_id": who, "org_id": ORG, "role": USERS[who]})}
    if key is not None:
        h["Idempotency-Key"] = key
    return h


def _key():
    return "k-" + uuid.uuid4().hex


def _app(monkeypatch, op, sysdb, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth, modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.routes import overhead
    from app.services import project_pnl
    from app.tenancy import guard, registry, resolver
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    for module in (appdb, deps_auth, deps_modules, utils_audit, overhead, project_pnl):
        monkeypatch.setattr(module, "db", op)
    try:    # PR #69 (SEC-01): compute is guarded by require_money_write, which compares
        # the resolved tenant database with ITS legacy handle — absent on main.
        from app.permissions import money_write
        monkeypatch.setattr(money_write, "db", op)
    except ImportError:
        pass
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
    app.include_router(overhead.router, prefix="/api")
    return app


class _Db:
    def __init__(self, backend):
        self.backend, self.client = backend, None
        suffix = uuid.uuid4().hex[:10]
        self.names = ("oh_01_" + suffix, "oh_01_sys_" + suffix)

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
            assert not set(self.names) & set(await self.client.list_database_names())
            self.client.close()


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def body():
        async with _Db(backend) as (op, sysdb):
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://oh01") as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def _dump(op):
    """Every business row (bytes) — proves a refused request wrote nothing. AuditEvents:
    the overhead ones (an enforce-mode permission DENIAL event is a refusal record, not a
    business write — PM-01 counts it the same way)."""
    import bson
    out = {}
    for name in BUSINESS + ("audit_events", "audit_logs"):
        flt = {"action": {"$regex": "^overhead\\."}} if name == "audit_events" else {}
        docs = await op[name].find(flt).sort("id", 1).to_list(None)
        out[name] = [bson.BSON.encode({k: d[k] for k in sorted(d) if k != "_id"}) for d in docs]
    return out


async def _create(c, kind, body):
    r = await c.post("/api/overhead/%s" % kind, json=body, headers=_h())
    assert r.status_code == 200, r.text
    return r.json()


async def _category(c, name="Office"):
    return await _create(c, "categories", {"name": name, "active": True})


async def _cost(c, cat_id, date="2026-10-10", amount=400.0):
    return await _create(c, "costs", {
        "category_id": cat_id, "name": "Rent", "amount": amount, "currency": "EUR",
        "vat_percent": 20, "date_incurred": date, "frequency": "OneTime",
        "allocation_type": "CompanyWide"})


async def _asset(c):
    return await _create(c, "assets", {
        "name": "Laptop", "purchase_cost": 1826.25, "currency": "EUR",
        "purchase_date": "2026-01-01", "useful_life_months": 60, "active": True})


async def _snapshot(c, start="2026-10-01", end="2026-10-31", key=None):
    r = await c.post("/api/overhead/snapshots/compute", headers=_h(key=key or _key()), json={
        "period_start": start, "period_end": end, "method": "PersonDays"})
    assert r.status_code == 200, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════ 1. used -> 409
def test_01_used_category_cost_asset_are_refused_409_and_untouched(monkeypatch, backend, mode):
    async def scenario(c, op):
        cat = await _category(c)
        cost = await _cost(c, cat["id"])
        asset = await _asset(c)
        await _snapshot(c)          # uses the cost (period covers it) and the asset
        before = await _dump(op)
        for path, used_by in ((f"categories/{cat['id']}", "overhead_costs"),
                              (f"costs/{cost['id']}", "overhead_snapshots"),
                              (f"assets/{asset['id']}", "overhead_snapshots")):
            r = await c.delete("/api/overhead/" + path, headers=_h(key=_key()))
            assert r.status_code == 409, (path, r.text)
            d = r.json()["detail"]
            assert d["error_code"] == "OVERHEAD_RECORD_IN_USE" and used_by in d["used_by"]
        after = await _dump(op)
        for name in BUSINESS + ("audit_events", "audit_logs"):
            assert before[name] == after[name], name
        assert await op.overhead_costs.count_documents({"id": cost["id"]}) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 2. unused -> archived
def test_02_unused_records_are_archived_not_deleted(monkeypatch, backend, mode):
    async def scenario(c, op):
        cat = await _category(c, "Unused")
        cost = await _cost(c, (await _category(c, "Other"))["id"], date="2026-12-01")
        asset = await _asset(c)     # no snapshot computed after it
        for kind, rec, entity in (("categories", cat, "overhead_category"),
                                  ("costs", cost, "overhead_cost"),
                                  ("assets", asset, "overhead_asset")):
            coll = "overhead_" + kind
            key = _key()
            r = await c.delete(f"/api/overhead/{kind}/{rec['id']}?reason=duplicate",
                               headers=_h("accountant", key))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["archived"] is True and body["deleted"] is False
            doc = await op[coll].find_one({"id": rec["id"]}, {"_id": 0})
            assert doc is not None, "hard-deleted"
            assert doc["status"] == "archived" and doc["archived_by_user_id"] == "accountant"
            assert doc["archive_reason"] == "duplicate" and doc["archived_at"]
            ev = await op.audit_events.find_one(
                {"action": "overhead.%s.archived" % entity, "entity_id": rec["id"]})
            assert ev and ev["source_flow"] == "FLOW-024" and ev["tenant_id"] == ORG
            # the same key replays: same answer, nothing written again
            n_events = await op.audit_events.count_documents({})
            r2 = await c.delete(f"/api/overhead/{kind}/{rec['id']}?reason=duplicate",
                                headers=_h("accountant", key))
            assert r2.status_code == 200 and r2.json()["id"] == rec["id"], r2.text
            assert await op.audit_events.count_documents({}) == n_events
            # a new key on an archived record -> 409, nothing written
            r3 = await c.delete(f"/api/overhead/{kind}/{rec['id']}", headers=_h(key=_key()))
            assert r3.status_code == 409 and r3.json()["detail"]["error_code"] == "ALREADY_ARCHIVED"
            # default list hides it; include_archived shows it
            q = "?active_only=false" if kind == "assets" else "?"
            ids = [x["id"] for x in (await c.get(f"/api/overhead/{kind}{q}", headers=_h())).json()]
            assert rec["id"] not in ids
            sep = "&" if q != "?" else ""
            ids = [x["id"] for x in (await c.get(
                f"/api/overhead/{kind}{q}{sep}include_archived=true", headers=_h())).json()]
            assert rec["id"] in ids
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 3. versions
def test_03_reallocation_twice_keeps_three_versions_reports_only_the_last(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.services.project_pnl import compute_project_pnl
        cat = await _category(c)
        await _cost(c, cat["id"], amount=400.0)
        snap = await _snapshot(c)
        total = snap["total_overhead"]
        sid = snap["id"]
        url = f"/api/overhead/snapshots/{sid}/allocate"
        keys = []
        for i, method in enumerate(("PersonDays", "Hours", "PersonDays")):
            keys.append(_key())
            r = await c.post(url, json={"method": method}, headers=_h(key=keys[-1]))
            assert r.status_code == 200, r.text
            assert r.json()["allocation_version"] == i + 1
        rows = await op.project_overhead_allocations.find(
            {"overhead_snapshot_id": sid}, {"_id": 0}).to_list(None)
        assert sorted({r["allocation_version"] for r in rows}) == [1, 2, 3]
        assert len(rows) == 6                               # 2 projects × 3 versions
        current = [r for r in rows if r.get("superseded_by") is None]
        assert {r["allocation_version"] for r in current} == {3}
        old = [r for r in rows if r["allocation_version"] < 3]
        assert all(r["superseded_by"] for r in old)
        # reports: only the last version, the sum is not doubled
        detail = (await c.get(f"/api/overhead/snapshots/{sid}", headers=_h())).json()
        assert {a["allocation_version"] for a in detail["allocations"]} == {3}
        assert round(sum(a["allocated_amount"] for a in detail["allocations"]), 2) == pytest.approx(total, abs=0.02)
        lst = (await c.get("/api/overhead/allocations", headers=_h())).json()
        assert len(lst) == 2 and {a["allocation_version"] for a in lst} == {3}
        hist = (await c.get("/api/overhead/allocations?include_superseded=true", headers=_h())).json()
        assert len(hist) == 6
        pnl_sum = 0
        for p in (PROJ_A, PROJ_B):
            pnl = await compute_project_pnl(ORG, p)
            pnl_sum += pnl["expense"]["overhead"]
        assert round(pnl_sum, 2) == pytest.approx(total, abs=0.02)
        # PersonDays v3: A 3/4, B 1/4
        by_p = {a["project_id"]: a["allocated_amount"] for a in lst}
        assert by_p[PROJ_A] == round(total * 0.75, 2)
        # audit: one canonical event per version
        assert await op.audit_events.count_documents(
            {"action": "overhead.allocation.version_created"}) == 3
        # replay of the last key: same batch, nothing new
        before = await _dump(op)
        r = await c.post(url, json={"method": "PersonDays"}, headers=_h(key=keys[-1]))
        assert r.status_code == 200 and r.json()["allocation_version"] == 3
        assert await _dump(op) == before
        # same key, different body -> 409, nothing written
        r = await c.post(url, json={"method": "Hours"}, headers=_h(key=keys[-1]))
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "IDEMPOTENCY_CONFLICT"
        assert await _dump(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 4. 403 / 428
@pytest.mark.parametrize("who", ["sitemanager", "technician", "viewer"])
def test_04_non_finance_role_403_and_missing_key_428_write_nothing(monkeypatch, backend, mode, who):
    async def scenario(c, op):
        cat = await _category(c, "Unused")
        cost = await _cost(c, cat["id"], date="2026-12-01")
        asset = await _asset(c)
        snap = await _snapshot(c)
        targets = [("DELETE", f"/api/overhead/categories/{cat['id']}", None),
                   ("DELETE", f"/api/overhead/costs/{cost['id']}", None),
                   ("DELETE", f"/api/overhead/assets/{asset['id']}", None),
                   ("POST", f"/api/overhead/snapshots/{snap['id']}/allocate", {"method": "PersonDays"}),
                   ("POST", "/api/overhead/snapshots/compute",                       # FG-88
                    {"period_start": "2026-11-01", "period_end": "2026-11-30", "method": "PersonDays"})]
        before = await _dump(op)
        n_keys = await op.audit_idempotency.count_documents({})
        for verb, path, body in targets:
            r = await c.request(verb, path, json=body, headers=_h(who, _key()))
            assert r.status_code == 403, (who, path, r.text)
            r = await c.request(verb, path, json=body, headers=_h("owner"))   # no key
            assert r.status_code == 428, (path, r.text)
            assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
            r = await c.request(verb, path, json=body, headers=_h("owner", "   "))  # blank key
            assert r.status_code == 428, (path, r.text)
        assert await _dump(op) == before
        assert await op.audit_idempotency.count_documents({}) == n_keys
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 5. compute
def test_05_archived_cost_and_asset_are_not_summed_by_a_new_snapshot(monkeypatch, backend, mode):
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], amount=100.0)
        gone = await _cost(c, cat["id"], amount=900.0)
        asset = await _asset(c)
        for kind, rec in (("costs", gone), ("assets", asset)):
            r = await c.delete(f"/api/overhead/{kind}/{rec['id']}", headers=_h(key=_key()))
            assert r.status_code == 200, r.text
        snap = await _snapshot(c)
        assert snap["total_costs"] == 100.0 and snap["total_amortization"] == 0
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 6. no delete left
def test_06_overhead_routes_have_no_hard_delete():
    import inspect
    from app.routes import overhead
    src = inspect.getsource(overhead)
    assert "delete_one(" not in src and "delete_many(" not in src


# ═══════════════════════════════════════════════════════════════════ 7. concurrency (audit of a3e0b91)
def test_07_concurrent_reallocations_never_leave_two_current_versions(monkeypatch, backend, mode):
    """OH01-1: 4 parallel re-allocations with different keys -> ONE current batch, distinct
    versions, the P&L sum equals the snapshot (was 4 current batches = 4x the overhead)."""
    async def scenario(c, op):
        from app.services.project_pnl import compute_project_pnl
        cat = await _category(c)
        await _cost(c, cat["id"], amount=400.0)
        snap = await _snapshot(c)
        sid, total = snap["id"], snap["total_overhead"]
        url = f"/api/overhead/snapshots/{sid}/allocate"
        r = await c.post(url, json={"method": "PersonDays"}, headers=_h(key=_key()))
        assert r.status_code == 200, r.text
        for _round in range(3):
            rs = await asyncio.gather(*[
                c.post(url, json={"method": "PersonDays"}, headers=_h(key=_key()))
                for _ in range(4)])
            codes = sorted(x.status_code for x in rs)
            assert set(codes) <= {200, 409}, [x.text for x in rs]
            assert 200 in codes, [x.text for x in rs]
            for x in rs:
                if x.status_code == 409:
                    assert x.json()["detail"]["error_code"] in (
                        "ALLOCATION_BUSY", "ALLOCATION_VERSION_CONFLICT"), x.text
            rows = await op.project_overhead_allocations.find(
                {"overhead_snapshot_id": sid}, {"_id": 0}).to_list(None)
            current = [x for x in rows if x.get("superseded_by") is None]
            assert len({x["allocation_batch_id"] for x in current}) == 1, current
            versions = sorted({x["allocation_version"] for x in rows})
            assert versions == list(range(1, len(versions) + 1))
            per_version = {}
            for x in rows:
                per_version.setdefault(x["allocation_version"], set()).add(x["allocation_batch_id"])
            assert all(len(b) == 1 for b in per_version.values()), per_version
            pnl_sum = 0
            for p in (PROJ_A, PROJ_B):
                pnl_sum += (await compute_project_pnl(ORG, p))["expense"]["overhead"]
            assert round(pnl_sum, 2) == pytest.approx(total, abs=0.02)
            assert await op.audit_events.count_documents(
                {"action": "overhead.allocation.version_created"}) == len(versions)
            s = await op.overhead_snapshots.find_one({"id": sid})
            assert s["allocation_version"] == versions[-1]
            assert await op.overhead_period_locks.count_documents(
                {"allocation_lock": {"$exists": True}}) == 0          # every lock released
    run(monkeypatch, backend, mode, scenario)


def test_08_concurrent_archive_of_one_cost_archives_and_audits_once(monkeypatch, backend, mode):
    """OH01-2: 6 parallel DELETEs (different keys) of one unused cost -> one 200, the
    rest 409 ALREADY_ARCHIVED, exactly ONE archive AuditEvent and one legacy audit row."""
    async def scenario(c, op):
        cat = await _category(c)
        cost = await _cost(c, cat["id"], date="2026-12-01")
        rs = await asyncio.gather(*[
            c.delete(f"/api/overhead/costs/{cost['id']}", headers=_h(key=_key()))
            for _ in range(6)])
        codes = sorted(x.status_code for x in rs)
        assert codes.count(200) == 1 and codes.count(409) == 5, [x.text for x in rs]
        for x in rs:
            if x.status_code == 409:
                assert x.json()["detail"]["error_code"] == "ALREADY_ARCHIVED"
        assert await op.audit_events.count_documents(
            {"action": "overhead.overhead_cost.archived", "entity_id": cost["id"]}) == 1
        assert await op.audit_logs.count_documents(
            {"action": "archived", "entity_id": cost["id"]}) == 1
        assert await op.overhead_costs.count_documents({"id": cost["id"], "status": "archived"}) == 1
    run(monkeypatch, backend, mode, scenario)


def test_09_allocation_version_index_is_unique_and_idempotent(monkeypatch, backend):
    async def scenario(c, op):
        from app.services.overhead_lifecycle import ensure_allocation_indexes, ALLOCATION_VERSION_INDEX
        await ensure_allocation_indexes(op)
        await ensure_allocation_indexes(op)          # idempotent
        info = await op.project_overhead_allocations.index_information()
        assert info[ALLOCATION_VERSION_INDEX]["unique"] is True
        row = {"org_id": ORG, "overhead_snapshot_id": "S", "allocation_version": 2,
               "project_id": PROJ_A, "version_key": "%s|S|2|%s" % (ORG, PROJ_A)}
        # legacy rows (no key) are not indexed — two of them never collide
        await op.project_overhead_allocations.insert_many([
            {"id": "l1", "org_id": ORG, "overhead_snapshot_id": "S", "project_id": PROJ_A},
            {"id": "l2", "org_id": ORG, "overhead_snapshot_id": "S", "project_id": PROJ_A}])
        await op.project_overhead_allocations.insert_one({**row, "id": "r1"})
        with pytest.raises(Exception) as exc:
            await op.project_overhead_allocations.insert_one({**row, "id": "r2"})
        assert "duplicate" in str(exc.value).lower() or "E11000" in str(exc.value)
    run(monkeypatch, backend, "off", scenario)



async def _pnl_overhead(op):
    from app.services.project_pnl import compute_project_pnl
    total = 0
    for p in (PROJ_A, PROJ_B):
        total += (await compute_project_pnl(ORG, p))["expense"]["overhead"]
    return round(total, 2)


# ═══════════════════════════════════════════════════════════════════ 10. FG-86
def test_10_one_active_snapshot_per_period_never_double_counted(monkeypatch, backend, mode):
    """FG-86: two snapshots of one period, both allocated, counted 2x in P&L. Now a new
    snapshot supersedes the period's active one AND its allocations; a superseded snapshot
    cannot be allocated; P&L == one snapshot."""
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], amount=400.0)
        s1 = await _snapshot(c)
        r = await c.post(f"/api/overhead/snapshots/{s1['id']}/allocate",
                         json={"method": "PersonDays"}, headers=_h(key=_key()))
        assert r.status_code == 200, r.text
        assert await _pnl_overhead(op) == pytest.approx(s1["total_overhead"], abs=0.02)
        s2 = await _snapshot(c)
        assert s2["snapshot_version"] == 2 and s1["snapshot_version"] == 1
        old = await op.overhead_snapshots.find_one({"id": s1["id"]}, {"_id": 0})
        assert old["superseded_by"] == s2["id"] and "active_period_key" not in old
        assert await _pnl_overhead(op) == 0          # s1's allocations went with it
        r = await c.post(f"/api/overhead/snapshots/{s1['id']}/allocate",
                         json={"method": "PersonDays"}, headers=_h(key=_key()))
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "SNAPSHOT_SUPERSEDED"
        r = await c.post(f"/api/overhead/snapshots/{s2['id']}/allocate",
                         json={"method": "PersonDays"}, headers=_h(key=_key()))
        assert r.status_code == 200, r.text
        assert await _pnl_overhead(op) == pytest.approx(s2["total_overhead"], abs=0.02)
        lst = (await c.get("/api/overhead/snapshots", headers=_h())).json()
        assert [x["id"] for x in lst] == [s2["id"]]
        hist = (await c.get("/api/overhead/snapshots?include_superseded=true", headers=_h())).json()
        assert {x["id"] for x in hist} == {s1["id"], s2["id"]}
        assert await op.overhead_snapshots.count_documents({}) == 2      # nothing deleted
        # another period is independent
        s3 = await _snapshot(c, "2026-11-01", "2026-11-30")
        assert s3["snapshot_version"] == 1
        assert (await op.overhead_snapshots.find_one({"id": s2["id"]}))["superseded_by"] is None
    run(monkeypatch, backend, mode, scenario)


def test_11_legacy_snapshot_of_the_period_is_superseded_too(monkeypatch, backend, mode):
    async def scenario(c, op):
        # a pre-OH-01 snapshot (no key, no version) with a pre-OH-01 allocation row
        await op.overhead_snapshots.insert_one({
            "id": "legacy-snap", "org_id": ORG, "period_start": "2026-10-01",
            "period_end": "2026-10-31", "method": "PersonDays", "total_overhead": 431.0,
            "total_person_days": 4, "total_hours": 40, "computed_at": "2026-10-31T00:00:00"})
        await op.project_overhead_allocations.insert_one({
            "id": "legacy-alloc", "org_id": ORG, "overhead_snapshot_id": "legacy-snap",
            "project_id": PROJ_A, "allocated_amount": 431.0})
        assert await _pnl_overhead(op) == 431.0
        cat = await _category(c)
        await _cost(c, cat["id"], amount=431.0)
        s = await _snapshot(c)
        assert s["snapshot_version"] == 2
        assert (await op.overhead_snapshots.find_one({"id": "legacy-snap"}))["superseded_by"] == s["id"]
        r = await c.post(f"/api/overhead/snapshots/{s['id']}/allocate",
                         json={"method": "PersonDays"}, headers=_h(key=_key()))
        assert r.status_code == 200, r.text
        assert await _pnl_overhead(op) == pytest.approx(s["total_overhead"], abs=0.02)   # not 862
        assert await op.project_overhead_allocations.count_documents({"id": "legacy-alloc"}) == 1
    run(monkeypatch, backend, mode, scenario)


def test_12_concurrent_computes_of_one_period_leave_one_active_snapshot(monkeypatch, backend, mode):
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], amount=400.0)
        await _snapshot(c)
        for _round in range(3):
            rs = await asyncio.gather(*[
                c.post("/api/overhead/snapshots/compute", headers=_h(key=_key()), json={
                    "period_start": "2026-10-01", "period_end": "2026-10-31",
                    "method": "PersonDays"}) for _ in range(4)])
            assert 200 in [x.status_code for x in rs], [x.text for x in rs]
            for x in rs:
                assert x.status_code in (200, 409), x.text
                if x.status_code == 409:
                    assert x.json()["detail"]["error_code"] in (
                        "ALLOCATION_BUSY", "SNAPSHOT_VERSION_CONFLICT"), x.text
            active = await op.overhead_snapshots.find(
                {"period_start": "2026-10-01", "superseded_by": None}).to_list(None)
            assert len(active) == 1, active
            versions = sorted(x["snapshot_version"] for x in
                              await op.overhead_snapshots.find({}).to_list(None))
            assert versions == list(range(1, len(versions) + 1))
        from app.services.overhead_lifecycle import ensure_snapshot_indexes, SNAPSHOT_PERIOD_INDEX
        await ensure_snapshot_indexes(op)                     # idempotent
        info = await op.overhead_snapshots.index_information()
        assert info[SNAPSHOT_PERIOD_INDEX]["unique"] is True
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 13. FG-87
def test_13_used_or_archived_records_are_read_only_edits_are_audited(monkeypatch, backend, mode):
    async def scenario(c, op):
        cat = await _category(c)
        used = await _cost(c, cat["id"], amount=400.0)                  # 2026-10-10
        free = await _cost(c, cat["id"], date="2026-12-01", amount=50.0)
        asset = await _asset(c)
        await _snapshot(c)
        before = await _dump(op)
        refusals = [
            (f"costs/{used['id']}", {"amount": 99999}, "OVERHEAD_RECORD_IN_USE"),
            (f"costs/{free['id']}", {"date_incurred": "2026-10-15"}, "OVERHEAD_RECORD_IN_USE"),
            (f"categories/{cat['id']}", {"name": "Renamed"}, "OVERHEAD_RECORD_IN_USE"),
            (f"assets/{asset['id']}", {"purchase_cost": 1.0}, "OVERHEAD_RECORD_IN_USE"),
        ]
        for path, body, code in refusals:
            r = await c.put("/api/overhead/" + path, json=body, headers=_h())
            assert r.status_code == 409 and r.json()["detail"]["error_code"] == code, (path, r.text)
        assert await _dump(op) == before                                  # nothing written
        # the bypass of the audit: move the date, then delete -> both refused
        r = await c.delete(f"/api/overhead/costs/{used['id']}", headers=_h(key=_key()))
        assert r.status_code == 409
        # an unused cost: edited, with a canonical before/after AuditEvent
        r = await c.put(f"/api/overhead/costs/{free['id']}", json={"amount": 75.0}, headers=_h())
        assert r.status_code == 200 and r.json()["amount"] == 75.0, r.text
        ev = await op.audit_events.find_one({"action": "overhead.overhead_cost.updated",
                                             "entity_id": free["id"]})
        assert ev and ev["structured_diff"]["amount"] == {"before": 50.0, "after": 75.0}
        # archived -> read-only
        lone = await _category(c, "Lone")
        r = await c.delete(f"/api/overhead/categories/{lone['id']}", headers=_h(key=_key()))
        assert r.status_code == 200, r.text
        snap_before = await _dump(op)
        r = await c.put(f"/api/overhead/categories/{lone['id']}", json={"name": "X"}, headers=_h())
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "RECORD_ARCHIVED"
        r = await c.put(f"/api/overhead/costs/{free['id']}", json={"amount": 1.0},
                        headers=_h("sitemanager"))
        assert r.status_code == 403
        assert await _dump(op) == snap_before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════════ 14. FG-88
def test_14_compute_requires_a_key_and_replays(monkeypatch, backend, mode):
    async def scenario(c, op):
        body = {"period_start": "2026-10-01", "period_end": "2026-10-31", "method": "PersonDays"}
        before = await _dump(op)
        r = await c.post("/api/overhead/snapshots/compute", json=body, headers=_h())
        assert r.status_code == 428 and r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
        assert await _dump(op) == before
        key = _key()
        s = await _snapshot(c, key=key)
        after = await _dump(op)
        r = await c.post("/api/overhead/snapshots/compute", json=body, headers=_h(key=key))
        assert r.status_code == 200 and r.json()["id"] == s["id"], r.text
        assert await _dump(op) == after                                  # replay wrote nothing
        r = await c.post("/api/overhead/snapshots/compute", json={**body, "method": "Hours"},
                         headers=_h(key=key))
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "IDEMPOTENCY_CONFLICT"
        assert await _dump(op) == after
        assert await op.audit_events.count_documents({"action": "overhead.snapshot.computed"}) == 1
    run(monkeypatch, backend, mode, scenario)



# ═══════════════════════════════════════════════════════════════════ 15. D6
def test_15_overlapping_period_is_refused_nothing_written(monkeypatch, backend, mode):
    """D6: Oct 1-31 and Oct 1-15 both allocated counted one 400 cost as 800. A compute whose
    period overlaps an ACTIVE snapshot of a different period -> 409 PERIOD_OVERLAP, nothing
    written; the same period is still versioned; a non-overlapping period is accepted."""
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], date="2026-10-10", amount=400.0)
        s1 = await _snapshot(c, "2026-10-01", "2026-10-31")
        r = await c.post(f"/api/overhead/snapshots/{s1['id']}/allocate",
                         json={"method": "PersonDays"}, headers=_h(key=_key()))
        assert r.status_code == 200, r.text
        before = await _dump(op)
        n_keys = await op.audit_idempotency.count_documents({})
        for start, end in (("2026-10-01", "2026-10-15"), ("2026-09-15", "2026-10-05"),
                           ("2026-10-31", "2026-11-30"), ("2026-09-01", "2026-12-31")):
            r = await c.post("/api/overhead/snapshots/compute", headers=_h(key=_key()), json={
                "period_start": start, "period_end": end, "method": "PersonDays"})
            assert r.status_code == 409, (start, end, r.text)
            d = r.json()["detail"]
            assert d["error_code"] == "PERIOD_OVERLAP" and d["overlapping"][0]["id"] == s1["id"]
        assert await _dump(op) == before
        assert await op.audit_idempotency.count_documents({}) == n_keys
        assert await _pnl_overhead(op) == pytest.approx(s1["total_overhead"], abs=0.02)  # not 2x
        # the same period: versioned (FG-86), not an overlap
        s2 = await _snapshot(c, "2026-10-01", "2026-10-31")
        assert s2["snapshot_version"] == 2
        # an adjacent, non-overlapping period is fine
        s3 = await _snapshot(c, "2026-11-01", "2026-11-30")
        assert s3["snapshot_version"] == 1
        # a superseded snapshot does not block: only ACTIVE ones count
        old = await op.overhead_snapshots.find_one({"id": s1["id"]})
        assert old["superseded_by"] == s2["id"]
    run(monkeypatch, backend, mode, scenario)


def test_16_concurrent_overlapping_computes_leave_no_overlap(monkeypatch, backend, mode):
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], date="2026-10-10", amount=400.0)
        periods = [("2026-10-01", "2026-10-31"), ("2026-10-01", "2026-10-15"),
                   ("2026-10-10", "2026-10-20"), ("2026-09-20", "2026-10-12")]
        rs = await asyncio.gather(*[
            c.post("/api/overhead/snapshots/compute", headers=_h(key=_key()), json={
                "period_start": a, "period_end": b, "method": "PersonDays"}) for a, b in periods])
        for x in rs:
            assert x.status_code in (200, 409), x.text
        active = await op.overhead_snapshots.find({"superseded_by": None}).to_list(None)
        assert len(active) == 1, [(a["period_start"], a["period_end"]) for a in active]
    run(monkeypatch, backend, mode, scenario)


def test_17_no_request_path_creates_indexes(monkeypatch, backend):
    """OH01-3: compute / allocate never issue createIndexes (startup and onboarding do)."""
    async def scenario(c, op):
        from app.services import overhead_lifecycle
        calls = []

        async def _boom(*a, **k):
            calls.append(a)
            raise AssertionError("createIndexes on a request path")
        monkeypatch.setattr(overhead_lifecycle, "ensure_allocation_indexes", _boom)
        monkeypatch.setattr(overhead_lifecycle, "ensure_snapshot_indexes", _boom)
        monkeypatch.setattr(overhead_lifecycle, "ensure_overhead_indexes", _boom)
        cat = await _category(c)
        await _cost(c, cat["id"], amount=400.0)
        s = await _snapshot(c)
        r = await c.post(f"/api/overhead/snapshots/{s['id']}/allocate",
                         json={"method": "PersonDays"}, headers=_h(key=_key()))
        assert r.status_code == 200, r.text
        assert calls == []
        import inspect
        from app.routes import overhead
        assert "create_index" not in inspect.getsource(overhead)
        assert "ensure_" not in inspect.getsource(overhead)
    run(monkeypatch, backend, "off", scenario)


def test_18_startup_and_onboarding_create_the_overhead_indexes():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    server = (root / "server.py").read_text(encoding="utf-8")
    onboarding = (root / "app" / "tenancy" / "onboarding.py").read_text(encoding="utf-8")
    assert "await ensure_overhead_indexes(db)" in server
    assert "await ensure_overhead_indexes(op_db)" in onboarding
