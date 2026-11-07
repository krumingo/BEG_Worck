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
        async with _Db("real") as dbs:
            if isinstance(dbs, tuple):      # harness >= 09409f0: (tenant db, system db)
                op, sysdb = dbs
                await _seed(op, sysdb)
                app = _app(monkeypatch, op, sysdb, mode)
            else:
                op = dbs
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
        assert all(v in (403, 404) for v in out.values()) and doc.get("status") != "archived"
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


def test_o6_lock_edges(monkeypatch):
    """O6 a FRESH foreign lock -> 409 ALLOCATION_BUSY, nothing written, lock intact;
    a STALE (>30 s) lock -> taken over, allocation succeeds, lock released afterwards."""
    async def scenario(c, op):
        from datetime import datetime, timedelta, timezone
        cat = await _category(c)
        await _cost(c, cat["id"])
        snap = await _snapshot(c)
        url = f"/api/overhead/snapshots/{snap['id']}/allocate"
        fresh = {"token": "other", "at": datetime.now(timezone.utc).isoformat()}
        lock_id = "%s|%s..%s" % (ORG, snap["period_start"], snap["period_end"])
        use_period = hasattr(__import__("app.services.overhead_lifecycle", fromlist=["x"]), "period_lock")

        async def set_lock(v):
            if use_period:
                await op.overhead_period_locks.update_one({"_id": lock_id}, {"$set": {"allocation_lock": v, "org_id": ORG}}, upsert=True)
            else:
                await op.overhead_snapshots.update_one({"id": snap["id"]}, {"$set": {"allocation_lock": v}})

        async def get_lock():
            d = await (op.overhead_period_locks.find_one({"_id": lock_id}) if use_period
                       else op.overhead_snapshots.find_one({"id": snap["id"]}))
            return (d or {}).get("allocation_lock")
        await set_lock(fresh)
        r1 = await c.post(url, json={"method": "PersonDays"}, headers=_h(key=_key()))
        n1 = await op.project_overhead_allocations.count_documents({})
        lock1 = await get_lock()
        old = {"token": "dead", "at": (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()}
        await set_lock(old)
        r2 = await c.post(url, json={"method": "PersonDays"}, headers=_h(key=_key()))
        doc = await op.overhead_snapshots.find_one({"id": snap["id"]})
        doc = dict(doc, allocation_lock=await get_lock())
        print("O6 fresh:", r1.status_code, r1.json().get("detail", {}).get("error_code") if r1.status_code != 200 else "",
              "rows", n1, "lock kept", lock1 == fresh, "| stale:", r2.status_code,
              "lock after", doc.get("allocation_lock"), "version", doc.get("allocation_version"))
        assert r1.status_code == 409 and n1 == 0 and lock1 == fresh
        assert r2.status_code == 200 and doc.get("allocation_lock") is None
    _run(monkeypatch, "enforce", scenario)



async def _compute(c, start, end, key=None):
    return await c.post("/api/overhead/snapshots/compute", headers=_h(key=key or _key()), json={
        "period_start": start, "period_end": end, "method": "PersonDays"})


async def _pnl_overhead(project):
    from app.services.project_pnl import compute_project_pnl
    from tests.test_oh_01_overhead_no_hard_delete import ORG as _O
    r = await compute_project_pnl(_O, project)
    return r.get("overhead") if isinstance(r, dict) and "overhead" in r else r


def test_o7_overlapping_periods(monkeypatch):
    """O7 (D6): month Oct 1-31 and half-month Oct 1-15, both allocated -> P&L overhead?"""
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], date="2026-10-10", amount=400.0)
        a = (await _compute(c, "2026-10-01", "2026-10-31")).json()
        b = (await _compute(c, "2026-10-01", "2026-10-15")).json()
        for s_ in (a, b):
            r = await c.post(f"/api/overhead/snapshots/{s_['id']}/allocate", json={"method": "PersonDays"},
                             headers=_h(key=_key()))
            assert r.status_code == 200, r.text
        cur = await op.project_overhead_allocations.find({"superseded_by": None}, {"_id": 0}).to_list(None)
        act = await op.overhead_snapshots.count_documents({"superseded_by": None})
        print("O7 active snapshots", act, "snapshot totals", a["total_overhead"], b["total_overhead"],
              "current allocation total", round(sum(x["allocated_amount"] for x in cur), 2))
    _run(monkeypatch, "enforce", scenario)


def test_o8_concurrent_compute_same_period(monkeypatch):
    """O8 FG-86: 4 parallel computes of one period, different keys, x3 -> one active snapshot."""
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], date="2026-10-10", amount=400.0)
        bad = 0
        for rnd in range(3):
            rs = await asyncio.gather(*[_compute(c, "2026-10-01", "2026-10-31") for _ in range(4)])
            act = await op.overhead_snapshots.count_documents({"period_start": "2026-10-01", "superseded_by": None})
            vers = sorted(d.get("snapshot_version") for d in await op.overhead_snapshots.find({}).to_list(None))
            print("O8 round", rnd, "codes", sorted(r.status_code for r in rs), "active", act, "versions", vers)
            bad += act != 1
        assert bad == 0
    _run(monkeypatch, "enforce", scenario)


def test_o9_allocate_superseded_and_period_switch(monkeypatch):
    """O9 FG-86: allocate S1, compute S2 (same period) -> S1 allocations superseded, P&L 0;
    allocate S1 again -> 409; allocate S2 -> P&L = one snapshot."""
    async def scenario(c, op):
        cat = await _category(c)
        await _cost(c, cat["id"], date="2026-10-10", amount=400.0)
        s1 = (await _compute(c, "2026-10-01", "2026-10-31")).json()
        await c.post(f"/api/overhead/snapshots/{s1['id']}/allocate", json={"method": "PersonDays"}, headers=_h(key=_key()))
        s2 = (await _compute(c, "2026-10-01", "2026-10-31")).json()
        cur = await op.project_overhead_allocations.count_documents({"superseded_by": None})
        r1 = await c.post(f"/api/overhead/snapshots/{s1['id']}/allocate", json={"method": "PersonDays"}, headers=_h(key=_key()))
        r2 = await c.post(f"/api/overhead/snapshots/{s2['id']}/allocate", json={"method": "PersonDays"}, headers=_h(key=_key()))
        tot = round(sum(x["allocated_amount"] for x in await op.project_overhead_allocations.find({"superseded_by": None}).to_list(None)), 2)
        print("O9 current rows after S2 compute", cur, "| alloc S1 again", r1.status_code,
              (r1.json().get("detail") or {}).get("error_code"), "| alloc S2", r2.status_code, "total", tot, "snap", s2["total_overhead"])
        assert cur == 0 and r1.status_code == 409 and r2.status_code == 200 and tot == s2["total_overhead"]
    _run(monkeypatch, "enforce", scenario)


def test_o10_put_rules(monkeypatch):
    """O10 FG-87: unused cost moved INTO a computed period -> 409; used cost amount edit -> 409;
    archived -> 409; accepted edit -> AuditEvent with before/after; PUT racing an archive."""
    async def scenario(c, op):
        cat = await _category(c)
        used = await _cost(c, cat["id"], date="2026-10-10", amount=400.0)
        free = await _cost(c, cat["id"], date="2025-03-10", amount=50.0)
        await _compute(c, "2026-10-01", "2026-10-31")
        r_move = await c.put(f"/api/overhead/costs/{free['id']}", json={"date_incurred": "2026-10-20"}, headers=_h())
        r_used = await c.put(f"/api/overhead/costs/{used['id']}", json={"amount": 1.0}, headers=_h())
        r_ok = await c.put(f"/api/overhead/costs/{free['id']}", json={"amount": 55.0}, headers=_h())
        ev = await op.audit_events.find_one({"entity_id": free["id"], "action": "overhead.overhead_cost.updated"}, {"_id": 0})
        free2 = await _cost(c, cat["id"], date="2025-04-10", amount=10.0)
        rs = await asyncio.gather(c.delete(f"/api/overhead/costs/{free2['id']}", headers=_h(key=_key())),
                                  *[c.put(f"/api/overhead/costs/{free2['id']}", json={"amount": 11.0 + i}, headers=_h()) for i in range(3)])
        d2 = await op.overhead_costs.find_one({"id": free2["id"]}, {"_id": 0})
        r_arch = await c.put(f"/api/overhead/costs/{free2['id']}", json={"amount": 99.0}, headers=_h())
        print("O10 move-in", r_move.status_code, "| used", r_used.status_code, "| ok", r_ok.status_code,
              "diff", ev and ev.get("structured_diff"), "| race codes", [r.status_code for r in rs],
              "final", d2.get("status"), d2.get("amount"), "| archived PUT", r_arch.status_code)
        assert r_move.status_code == 409 and r_used.status_code == 409 and r_ok.status_code == 200
        assert ev and ev["structured_diff"]["amount"] == {"before": 50.0, "after": 55.0}
        assert r_arch.status_code == 409
    _run(monkeypatch, "enforce", scenario)
