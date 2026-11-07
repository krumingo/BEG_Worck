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


async def _seed(op):
    await op.organizations.insert_one({"id": ORG, "name": "OH-01 Org"})
    await op.subscriptions.insert_one({"org_id": ORG, "plan_id": "pro", "status": "active"})
    for uid, role in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@oh01.test", "first_name": uid})
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


def _app(monkeypatch, op, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth, modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.routes import overhead
    from app.services import project_pnl
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    for module in (appdb, deps_auth, deps_modules, utils_audit, overhead, project_pnl):
        monkeypatch.setattr(module, "db", op)
    app = FastAPI()
    app.include_router(overhead.router, prefix="/api")
    return app


class _Db:
    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, "oh_01_" + uuid.uuid4().hex[:10]

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.name]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            await self.client.drop_database(self.name)
            assert self.name not in await self.client.list_database_names()
            self.client.close()


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://oh01") as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def _dump(op):
    """Every business row (bytes) — proves a refused request wrote nothing."""
    import bson
    out = {}
    for name in BUSINESS + ("audit_events", "audit_logs"):
        docs = await op[name].find({}).sort("id", 1).to_list(None)
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


async def _snapshot(c):
    r = await c.post("/api/overhead/snapshots/compute", headers=_h(), json={
        "period_start": "2026-10-01", "period_end": "2026-10-31", "method": "PersonDays"})
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
                   ("POST", f"/api/overhead/snapshots/{snap['id']}/allocate", {"method": "PersonDays"})]
        before = await _dump(op)
        for verb, path, body in targets:
            r = await c.request(verb, path, json=body, headers=_h(who, _key()))
            assert r.status_code == 403, (who, path, r.text)
            r = await c.request(verb, path, json=body, headers=_h("owner"))   # no key
            assert r.status_code == 428, (path, r.text)
            assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
            r = await c.request(verb, path, json=body, headers=_h("owner", "   "))  # blank key
            assert r.status_code == 428, (path, r.text)
        assert await _dump(op) == before
        assert await op.audit_idempotency.count_documents({}) == 0
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
