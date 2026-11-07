"""OH-01 probes (copy to <wt74>/backend/tests/, one test per process, W0_03_REAL_MONGO_URL set).

O1 concurrent re-allocations, DIFFERENT keys (two admins / two tabs): how many CURRENT
   versions remain, is the P&L overhead doubled, do versions collide?
O2 concurrent archive of the same cost with different keys: one archived, AuditEvents count.
O3 cross-tenant: tenant-B admin DELETEs tenant-A cost id -> 404, untouched.
O4 non-finance roles (sitemanager, technician, viewer, accountant) on allocate/delete, enforce.
"""
import asyncio, os
import pytest
from tests.test_oh_01_overhead_no_hard_delete import (
    ORG, PROJ_A, USERS, _Db, _app, _category, _cost, _h, _key, _seed, _snapshot)
import httpx

ROUNDS = int(os.environ.get("PROBE_ROUNDS", "5"))


def _run(monkeypatch, mode, scenario):
    async def body():
        async with _Db("real") as op:
            await _seed(op)
            app = _app(monkeypatch, op, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as c:
                return await scenario(c, op)
    return asyncio.run(body())


def test_o1_concurrent_reallocations(monkeypatch):
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"])
        snap = await _snapshot(c)
        url = f"/api/overhead/snapshots/{snap['id']}/allocate"
        bad = 0
        for rnd in range(ROUNDS):
            rs = await asyncio.gather(*[c.post(url, json={"method": "PersonDays"}, headers=_h(key=_key()))
                                        for _ in range(4)])
            codes = [r.status_code for r in rs]
            cur = await op.project_overhead_allocations.find(
                {"overhead_snapshot_id": snap["id"], "superseded_by": None}, {"_id": 0}).to_list(None)
            batches = {a["allocation_batch_id"] for a in cur}
            vers = sorted({a["allocation_version"] for a in await op.project_overhead_allocations.find(
                {"overhead_snapshot_id": snap["id"]}).to_list(None)})
            total = round(sum(a["allocated_amount"] for a in cur), 2)
            print(f"O1 round {rnd}: codes {codes} current batches {len(batches)} current total {total}"
                  f" (snapshot {snap['total_overhead']}) versions {vers}")
            if len(batches) != 1:
                bad += 1
        print("O1 rounds with >1 current version:", bad, "/", ROUNDS)
        assert bad == 0
    _run(monkeypatch, "enforce", scenario)


def test_o2_concurrent_archive(monkeypatch):
    async def scenario(c, op):
        cat = await _category(c)
        cost = await _cost(c, cat["id"], date="2025-01-10")  # no snapshot covers it -> unused
        rs = await asyncio.gather(*[c.delete(f"/api/overhead/costs/{cost['id']}", headers=_h(key=_key()))
                                    for _ in range(6)])
        codes = sorted(r.status_code for r in rs)
        n_ev = await op.audit_events.count_documents({"entity_id": cost["id"]})
        doc = await op.overhead_costs.find_one({"id": cost["id"]})
        print("O2 codes", codes, "audit events", n_ev, "status", doc and doc.get("status"))
        assert doc is not None and doc["status"] == "archived"
        assert codes.count(200) == 1 and n_ev == 1, "O2: more than one archive success/event"
    _run(monkeypatch, "enforce", scenario)


def test_o3_cross_tenant(monkeypatch):
    async def scenario(c, op):
        cat = await _category(c)
        cost = await _cost(c, cat["id"], date="2025-01-10")
        await op.organizations.insert_one({"id": "ORG-B", "name": "B"})
        await op.subscriptions.insert_one({"org_id": "ORG-B", "plan_id": "pro", "status": "active"})
        await op.users.insert_one({"id": "b-owner", "org_id": "ORG-B", "role": "Owner", "is_active": True,
                                   "email": "b@x.test", "first_name": "b"})
        from app.deps.auth import create_token
        hb = {"Authorization": "Bearer " + create_token({"user_id": "b-owner", "org_id": "ORG-B", "role": "Owner"}),
              "Idempotency-Key": _key()}
        out = {}
        for path in (f"costs/{cost['id']}", f"categories/{cat['id']}"):
            r = await c.delete("/api/overhead/" + path, headers=hb)
            out[path.split('/')[0]] = r.status_code
        doc = await op.overhead_costs.find_one({"id": cost["id"]}, {"_id": 0})
        print("O3 tenant-B delete of tenant-A ids:", out, "A cost status:", doc.get("status"))
        assert all(v == 404 for v in out.values()) and doc.get("status") != "archived"
    _run(monkeypatch, "enforce", scenario)


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_o4_roles(monkeypatch, mode):
    async def scenario(c, op):
        cat = await _category(c)
        cost = await _cost(c, cat["id"], date="2025-01-10")
        snap = await _snapshot(c)
        res = {}
        for who in ("accountant", "sitemanager", "technician", "viewer"):
            r1 = await c.post(f"/api/overhead/snapshots/{snap['id']}/allocate", json={"method": "PersonDays"},
                              headers=_h(who, key=_key()))
            r2 = await c.delete(f"/api/overhead/costs/{cost['id']}", headers=_h(who, key=_key()))
            res[who] = (r1.status_code, r2.status_code)
        n = await op.project_overhead_allocations.count_documents({})
        st = (await op.overhead_costs.find_one({"id": cost["id"]})).get("status")
        print(f"O4 {mode}:", res, "allocations", n, "cost status", st)
    _run(monkeypatch, mode, scenario)


def test_o5_same_key_race(monkeypatch):
    """O5 4 concurrent allocates with the SAME key (double submit): one version expected."""
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"])
        snap = await _snapshot(c)
        h = _h(key="same-" + _key())
        rs = await asyncio.gather(*[c.post(f"/api/overhead/snapshots/{snap['id']}/allocate",
                                           json={"method": "PersonDays"}, headers=h) for _ in range(4)])
        rows = await op.project_overhead_allocations.find({}, {"_id": 0}).to_list(None)
        cur = [a for a in rows if a.get("superseded_by") is None]
        print("O5 codes", sorted(r.status_code for r in rs), "rows", len(rows), "current rows", len(cur),
              "current total", round(sum(a["allocated_amount"] for a in cur), 2))
        assert len({a["allocation_batch_id"] for a in rows}) == 1 and len(cur) == len(rows) == 2
    _run(monkeypatch, "enforce", scenario)
