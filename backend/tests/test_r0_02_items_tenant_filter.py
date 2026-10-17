"""
R0-02 — items of another tenant through the list filter (AUD-026).

The 8 cases of docs/architecture/tasks/R0-02_ITEMS_TENANT_FILTER.md, positive
and forbidden:

1. tenant A lists its own items with the filters and sorts the UI sends;
2. ``filters=org_id=<B>`` is a 400 and returns nothing of B;
3. ``org_id.in=<A>|<B>`` is a 400;
4. a key carrying ``$`` (``$where``, ``$expr``, ``$or``, ``name.$regex``) is a 400;
5. an unknown field or operator in ``filters``, or an unknown ``sort_by``, is a 400;
6. A reads/updates/deletes B's item by id: 404, and B's document is byte-equal;
7. ``/sales/history`` and ``/sales/{id}/details`` name an item only from A;
8. the A2C guard catches ``db.items.find`` in a new module (and only the
   ``.items()`` dict method stays exempt).

Every refused request is also proven to read NOTHING: the route's database
handle is a spy, and no collection is opened before the 400.

Runs in-process against ``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL``
names a disposable LOCAL MongoDB, again against it — one database per test,
dropped afterwards. Authentication is real: a JWT the route verifies and a user
``get_current_user`` loads from the database.

    pytest tests/test_r0_02_items_tenant_filter.py -v --noconftest
    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27018 pytest tests/test_r0_02_items_tenant_filter.py -v --noconftest
"""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

ORG_A, ORG_B = "ORG-R002-A", "ORG-R002-B"
A_MARK, B_MARK = "AMARK-", "BMARK-"
SHARED_ID = "IT-SHARED"          # an item id BOTH tenants hold (ids collide)
B_ONLY_ID = "IT-B-ONLY"          # an item id only B holds
A_ONLY_ID = "IT-A-ONLY"


def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    """``mongomock`` always; ``real`` when W0_03_REAL_MONGO_URL is a local MongoDB."""
    return request.param


# ═══════════════════════════════════════════════════════════════════ helpers
def _item(org, mark, item_id, sku, name, category, price, active=True, brand="Knauf"):
    return {"id": item_id, "org_id": org, "sku": mark + sku, "name": mark + name,
            "unit": "бр.", "category": category, "brand": brand, "description": mark + "DESC",
            "default_price": price, "min_stock": 1.0, "is_active": active,
            "created_at": "2026-10-01T00:00:00", "updated_at": "2026-10-01T00:00:00"}


async def _seed(op):
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
    # B first, so a global first-match lookup would land on B.
    await op.items.insert_many([
        _item(ORG_B, B_MARK, SHARED_ID, "SH", "Shared", "Materials", 77.0),
        _item(ORG_B, B_MARK, B_ONLY_ID, "BO", "Bonly", "Tools", 88.0),
        _item(ORG_B, B_MARK, "IT-B-3", "B3", "Cement", "Materials", 99.0),
    ])
    await op.items.insert_many([
        _item(ORG_A, A_MARK, SHARED_ID, "SH", "Shared", "Materials", 10.0),
        _item(ORG_A, A_MARK, A_ONLY_ID, "AO", "Drill", "Tools", 50.0),
        _item(ORG_A, A_MARK, "IT-A-3", "A3", "Cement", "Materials", 20.0, brand="Baumit"),
        _item(ORG_A, A_MARK, "IT-A-4", "A4", "Old", "Consumables", 5.0, active=False),
    ])
    for uid, org in (("admin-a", ORG_A), ("admin-b", ORG_B)):
        await op.users.insert_one({"id": uid, "org_id": org, "role": "Admin", "is_active": True,
                                   "email": uid + "@r002.test", "first_name": uid})
    # Sales of A: one names A's item, one names an id that exists ONLY in B.
    await op.sales.insert_many([
        {"id": "S-A-1", "org_id": ORG_A, "item_id": A_ONLY_ID, "quantity": 1,
         "created_at": "2026-10-02T00:00:00"},
        {"id": "S-A-2", "org_id": ORG_A, "item_id": B_ONLY_ID, "quantity": 1,
         "created_at": "2026-10-03T00:00:00"},
    ])


async def _snapshot(op, org, item_id):
    """A byte-level snapshot of one item, for proving a write did NOT touch it."""
    import bson
    doc = await op.items.find_one({"id": item_id, "org_id": org})
    assert doc is not None, (org, item_id)
    return bson.BSON.encode({k: doc[k] for k in sorted(doc) if k != "_id"})


def _token(user_id, org_id, role="Admin"):
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token(
        {"user_id": user_id, "org_id": org_id, "role": role})}




def _headers(who):
    return _token("admin-a", ORG_A) if who == "A" else _token("admin-b", ORG_B)


class SpyDb:
    """The route's database handle; records every collection the route opens."""

    def __init__(self, real):
        self._real, self.opened = real, []

    def __getitem__(self, name):
        self.opened.append(name)
        return self._real[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self.opened.append(name)
        return getattr(self._real, name)


def _app(monkeypatch, op):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.master_data.deps import ENV_MODE
    from app.routes import items, sales
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, utils_audit, sales):
        monkeypatch.setattr(module, "db", op)
    spy = SpyDb(op)
    monkeypatch.setattr(items, "db", spy)
    app = FastAPI()
    app.include_router(items.router, prefix="/api")
    app.include_router(sales.router, prefix="/api")
    return app, spy


class _Db:
    """A fresh, empty database on the chosen backend; a real one is dropped on exit."""

    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, "r0_02_" + uuid.uuid4().hex[:10]

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


def run(monkeypatch, scenario, backend="mongomock"):
    """Fresh seeded database + in-process client; ``scenario(c, op, spy)``."""
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app, spy = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r002") as c:
                return await scenario(c, op, spy)
    return asyncio.run(body())


async def _list(c, who="A", **params):
    return await c.get("/api/items", params=params, headers=_headers(who))


def _skus(r):
    return sorted(i["sku"] for i in r.json()["items"])


async def _assert_refused(c, spy, **params):
    """400, a clear 'Invalid ...' detail, no item data, and NO collection opened."""
    spy.opened.clear()
    r = await _list(c, **params)
    assert r.status_code == 400, (params, r.status_code, r.text[:300])
    assert r.json()["detail"].startswith("Invalid "), r.text
    assert B_MARK not in r.text and A_MARK not in r.text, r.text
    assert "items" not in r.json()
    assert spy.opened == [], "a refused request read %s" % spy.opened
    return r


# ═══════════════════════════════════════════════════════════════════ 1
def test_01_tenant_a_lists_its_own_items_with_normal_filters_and_sorting(monkeypatch, backend):
    async def scenario(c, op, spy):
        r = await _list(c)
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 4 and B_MARK not in r.text
        assert _skus(r) == ["AMARK-A3", "AMARK-A4", "AMARK-AO", "AMARK-SH"]

        # exactly what the DataTable sends for each filterable column
        cases = [
            ("sku.contains=a3", ["AMARK-A3"]),
            ("name.contains=cement", ["AMARK-A3"]),
            ("brand.contains=baumit", ["AMARK-A3"]),
            ("category.in=Tools", ["AMARK-AO"]),
            ("category.equals=Materials", ["AMARK-A3", "AMARK-SH"]),
            ("default_price.min=15,default_price.max=60", ["AMARK-A3", "AMARK-AO"]),
            ("is_active.bool=false", ["AMARK-A4"]),
            ("category=Consumables", ["AMARK-A4"]),          # bare key = equals
            ("created_at.from=2026-01-01,created_at.to=2026-12-31",
             ["AMARK-A3", "AMARK-A4", "AMARK-AO", "AMARK-SH"]),
        ]
        for flt, expected in cases:
            r = await _list(c, filters=flt)
            assert r.status_code == 200, (flt, r.text)
            assert _skus(r) == expected, (flt, _skus(r))
            assert B_MARK not in r.text

        r = await _list(c, sort_by="default_price", sort_dir="desc")
        assert [i["default_price"] for i in r.json()["items"]] == [50.0, 20.0, 10.0, 5.0]
        r = await _list(c, sort_by="name", sort_dir="asc", page_size=2, page=2)
        assert [i["name"] for i in r.json()["items"]] == ["AMARK-Old", "AMARK-Shared"]
        assert r.json()["total_pages"] == 2
        r = await _list(c, search="cement")
        assert _skus(r) == ["AMARK-A3"]

        # B sees only B — the same shared id answers with B's own document
        r = await _list(c, who="B")
        assert r.json()["total"] == 3 and A_MARK not in r.text
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 2
@pytest.mark.parametrize("flt", [
    "org_id=" + ORG_B, "org_id.equals=" + ORG_B, "org_id.contains=R002",
    "tenant_id=" + ORG_B, "_id.equals=x", "name.contains=x,org_id=" + ORG_B])
def test_02_filter_naming_another_tenant_is_400_and_returns_nothing_of_b(
        monkeypatch, backend, flt):
    async def scenario(c, op, spy):
        await _assert_refused(c, spy, filters=flt)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 3
@pytest.mark.parametrize("flt", [
    "org_id.in=%s|%s" % (ORG_A, ORG_B), "org_id.in=" + ORG_B, "tenant_id.in=%s|%s" % (ORG_A, ORG_B)])
def test_03_org_id_in_both_tenants_is_400(monkeypatch, backend, flt):
    async def scenario(c, op, spy):
        await _assert_refused(c, spy, filters=flt)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 4
@pytest.mark.parametrize("flt", [
    "$where=1", "$where=this.org_id!=''", "$expr=1", "$or=x", "$and.equals=x",
    "name.$regex=.*", "$comment", "price.$gt=0"])
def test_04_operator_keys_are_400(monkeypatch, backend, flt):
    async def scenario(c, op, spy):
        await _assert_refused(c, spy, filters=flt)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 5
@pytest.mark.parametrize("params", [
    {"filters": "password_hash=x"}, {"filters": "id=" + SHARED_ID},
    {"filters": "foo.contains=x"}, {"filters": "name.regex=x"},
    {"filters": "name.min=1"}, {"filters": "is_active.equals=true"},
    {"filters": "default_price.min=abc"}, {"filters": "name"},
    {"sort_by": "org_id"}, {"sort_by": "$natural"}, {"sort_by": "password_hash"},
    {"sort_by": "_id"}, {"sort_by": "unknown"}])
def test_05_unknown_field_or_operator_in_filters_or_sort_by_is_400(monkeypatch, backend, params):
    async def scenario(c, op, spy):
        await _assert_refused(c, spy, **params)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 6
def test_06_a_reads_updates_deletes_b_item_by_id_404_and_b_unchanged(monkeypatch, backend):
    async def scenario(c, op, spy):
        h = _headers("A")
        before_b_only = await _snapshot(op, ORG_B, B_ONLY_ID)
        before_b_shared = await _snapshot(op, ORG_B, SHARED_ID)

        r = await c.get("/api/items/" + B_ONLY_ID, headers=h)
        assert r.status_code == 404 and B_MARK not in r.text
        r = await c.put("/api/items/" + B_ONLY_ID, json={"name": "HIJACK", "default_price": 1},
                        headers=h)
        assert r.status_code == 404 and B_MARK not in r.text
        r = await c.delete("/api/items/" + B_ONLY_ID, headers=h)
        assert r.status_code == 404

        # the colliding id: A reaches its OWN document, never B's
        r = await c.get("/api/items/" + SHARED_ID, headers=h)
        assert r.status_code == 200 and r.json()["sku"] == "AMARK-SH"
        r = await c.put("/api/items/" + SHARED_ID, json={"name": "A-RENAMED"}, headers=h)
        assert r.status_code == 200 and r.json()["name"] == "A-RENAMED"
        assert r.json()["org_id"] == ORG_A
        r = await c.delete("/api/items/" + SHARED_ID, headers=h)
        assert r.status_code == 200
        a_doc = await op.items.find_one({"id": SHARED_ID, "org_id": ORG_A})
        assert a_doc["name"] == "A-RENAMED" and a_doc["is_active"] is False

        assert await _snapshot(op, ORG_B, B_ONLY_ID) == before_b_only
        assert await _snapshot(op, ORG_B, SHARED_ID) == before_b_shared

        # create stamps A's tenant; a SKU that exists only in B is free for A
        r = await c.post("/api/items", json={"sku": "bmark-bo", "name": "A new"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["org_id"] == ORG_A
        assert await op.items.count_documents({"sku": "BMARK-BO", "org_id": ORG_A}) == 1
        assert await _snapshot(op, ORG_B, B_ONLY_ID) == before_b_only
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 7
def test_07_sales_names_an_item_only_from_its_own_tenant(monkeypatch, backend):
    async def scenario(c, op, spy):
        h = _headers("A")
        r = await c.get("/api/sales/history", headers=h)
        assert r.status_code == 200, r.text
        names = {row["sale_id"]: row["item_name"] for row in r.json()["data"]}
        assert names == {"S-A-1": "AMARK-Drill", "S-A-2": ""}, names
        assert B_MARK not in r.text

        r = await c.get("/api/sales/S-A-1/details", headers=h)
        assert r.status_code == 200 and r.json()["item_name"] == "AMARK-Drill"
        r = await c.get("/api/sales/S-A-2/details", headers=h)
        assert r.status_code == 200 and r.json()["item_name"] == ""
        assert B_MARK not in r.text

        # B cannot open A's sale at all
        r = await c.get("/api/sales/S-A-1/details", headers=_headers("B"))
        assert r.status_code == 404
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 8
def _guard():
    sys.path.insert(0, str(BACKEND / "scripts"))
    import w0_03e_a2c_tenant_boundary_guard as guard
    return guard


def test_08_guard_catches_db_items_in_a_new_module():
    guard = _guard()
    rel = "app/routes/r0_02_new_module.py"
    unsafe = {
        "A2C-READ": '''
async def leak(user=Depends(x)):
    return await db.items.find({"sku": "X"}).to_list(10)
''',
        "A2C-WRITE": '''
async def wipe(item_id, user=Depends(x)):
    await db.items.update_one({"id": item_id}, {"$set": {"is_active": False}})
''',
        "A2C-DYNAMIC": '''
async def hide(user=Depends(x)):
    coll = db.items
    return await coll.find_one({"id": 1})
''',
    }
    for rule, src in unsafe.items():
        found = guard.check_source(src, rel)
        assert any(v[2] == rule and "items" in v[3] for v in found), (rule, found)

    # the dict method on a handle-named variable is still not a collection
    ok = '''
def describe(database):
    return [k for k, v in database.items()]
'''
    assert guard.check_source(ok, rel) == []
    # and the tenant view is the accepted path
    good = '''
async def fine(user=Depends(x)):
    return await _tenant(user).items.find({"sku": "X"}).to_list(10)
'''
    assert guard.check_source(good, rel) == []


def test_08b_guard_rejects_the_pre_r0_02_items_and_sales_access():
    """The exact raw calls main had in items.py / sales.py are violations now."""
    guard = _guard()
    before = '''
async def list_items(user=Depends(get_current_user), filters=None):
    query = build_mongo_query(user["org_id"], parse_filters(filters))
    total = await db.items.count_documents(query)
    return await db.items.find(query, {"_id": 0}).to_list(10)

async def delete_item(item_id, user=Depends(get_current_user)):
    await db.items.update_one({"id": item_id}, {"$set": {"is_active": False}})

async def sale_details(sale, user=Depends(get_current_user)):
    return await db.items.find_one({"id": sale.get("item_id")}, {"_id": 0, "name": 1})
'''
    rules = sorted(v[2] for v in guard.check_source(before, "app/routes/items.py"))
    assert rules == ["A2C-READ", "A2C-READ", "A2C-READ", "A2C-WRITE"], rules


def test_08c_items_is_no_longer_a_database_api_name():
    guard = _guard()
    assert "items" not in guard.DATABASE_API
    assert guard.METHOD_CALL_ONLY == frozenset({"items"})
