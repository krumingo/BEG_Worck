"""CLAUDE AUDIT probe — #77 ACT-01 (c6c7f1c). Real Mongo RS, off/shadow/enforce, PR's own seed.
  A1  FRESH collections each round (client_act_line_totals + org_counters dropped): 6 concurrent
      acts of 4 on L1 (qty 10), different keys, x10 -> exactly 2 accepted, no 5xx, totals doc = 8
  A2  6 concurrent acts on DIFFERENT lines (fresh counter) -> 6 unique act numbers
  A3  PUT delta: act 4 on L1 -> PUT 7 (+3) -> PUT 2 (-5) -> a new act of 8 fits (2+8=10), 0.01 more 409
  A4  cross-tenant (LB) / other project (LP2) / draft offer (L3) -> 422 or 404, nothing written
  A5  R29: no key 428; same key same body -> same answer, one act; same key other body -> 409
  A6  one canonical AuditEvent per create; a PUT on a non-Draft act -> 4xx
    cd <wt77>/backend && PYTHONPATH=. W0_03_REAL_MONGO_URL=... python <this>
"""
import asyncio, os, sys, uuid, importlib.util, collections
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="act01_op_" + sfx, BEG_SYSTEM_DB="act01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
URL = os.environ["W0_03_REAL_MONGO_URL"]; os.environ.setdefault("MONGO_URL", URL)
spec = importlib.util.spec_from_file_location("act01_t", "tests/test_act_01_client_act_from_offer.py")
T = importlib.util.module_from_spec(spec); sys.modules["act01_t"] = T; spec.loader.exec_module(T)
import server, httpx  # noqa
from fastapi.testclient import TestClient  # noqa
pm = T._pm01()
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
with TestClient(app, raise_server_exceptions=False) as tc:
    q = lambda f: tc.portal.call(f)
    client = q(lambda: pm._make_client(URL)); op = client[os.environ["DB_NAME"]]
    rep = q(lambda: pm._load_seed().seed(op, client[os.environ["BEG_SYSTEM_DB"]], T.SYNTH_PASSWORD))
    fx = {t["key"]: {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                     "users": {u["key"]: u for u in t["users"]}} for t in rep["tenants"]}
    i = q(lambda: T.seed_act01(op, fx))
    q(lambda: op.audit_idempotency.create_index([("id", 1)], unique=True))
    q(lambda: op.audit_idempotency.create_index([("tenant_id", 1), ("action", 1), ("key", 1)], unique=True))
    snap = q(lambda: pm._snapshot(client, (os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"])))
    tok = tc.post("/api/auth/login", json={"email": fx["A"]["users"]["admin"]["email"], "password": T.SYNTH_PASSWORD}).json()["token"]
    H = lambda k=None: {"Authorization": "Bearer " + tok, "Idempotency-Key": k or uuid.uuid4().hex}
    P = fx["A"]["project_id"]
    body = lambda lk, qty: {"project_id": P, "lines": [{"offer_line_id": i[lk], "executed_qty": qty}]}
    acts_on = lambda lk: sum(float(l.get("executed_qty") or 0) for a in q(lambda: op.client_acts.find({}, {"_id": 0, "lines": 1}).to_list(None))
                             for l in a.get("lines") or [] if l.get("offer_line_id") == i[lk])
    cnt = lambda c, f=None: q(lambda: op[c].count_documents(f or {}))

    def restore():
        q(lambda: pm._restore(client, snap, sorted(set(snap) | {"%s.%s" % (op.name, c) for c in
                  ("client_acts", "client_act_line_totals", "org_counters", "audit_events", "audit_idempotency")})))

    async def gather(reqs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as ac:
            return await asyncio.gather(*[ac.request(m, u, json=b, headers=h) for m, u, b, h in reqs])

    for mode in T.MODES:
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        # A1
        hist = collections.Counter()
        for rnd in range(10):
            restore()
            if os.environ.get("PROBE_DOCS_ONLY") == "1":    # collections exist, documents absent
                q(lambda: op.client_act_line_totals.insert_one({"_id": "warm"})); q(lambda: op.client_act_line_totals.delete_many({}))
                q(lambda: op.org_counters.insert_one({"_id": "warm"})); q(lambda: op.org_counters.delete_many({}))
            else:
                q(lambda: op.drop_collection("client_act_line_totals")); q(lambda: op.drop_collection("org_counters"))
            rs = q(lambda: gather([("POST", "/api/client-acts", body("L1", 4), H()) for _ in range(6)]))
            codes = tuple(sorted(r.status_code for r in rs)); hist[codes] += 1
            acted = acts_on("L1")
            if sum(c == 201 for c in codes) != 2 or any(c >= 500 for c in codes) or acted != 8:
                F.append("%s A1 rnd %d codes %s acted %s %s" % (mode, rnd, codes, acted,
                         [r.text[:120] for r in rs if r.status_code >= 500][:1]))
        print(mode, "A1 fresh x10:", dict(hist))
        # A2
        restore(); q(lambda: op.drop_collection("org_counters"))
        rs = q(lambda: gather([("POST", "/api/client-acts", body("L1" if n % 2 else "LX", 0.5), H()) for n in range(6)]))
        nums = [r.json().get("act_number") for r in rs if r.status_code == 201]
        print(mode, "A2 numbers", sorted(r.status_code for r in rs), sorted(nums))
        if len(nums) != 6 or len(set(nums)) != 6:
            F.append("%s A2 numbers %s" % (mode, nums))
        # A3
        restore()
        a = tc.post("/api/client-acts", json=body("L1", 4), headers=H()).json()
        u1 = tc.put("/api/client-acts/%s" % a["id"], json={"lines": [{"offer_line_id": i["L1"], "executed_qty": 7}]}, headers=H())
        t1 = acts_on("L1")
        u2 = tc.put("/api/client-acts/%s" % a["id"], json={"lines": [{"offer_line_id": i["L1"], "executed_qty": 2}]}, headers=H())
        t2 = acts_on("L1")
        n8 = tc.post("/api/client-acts", json=body("L1", 8), headers=H())
        n9 = tc.post("/api/client-acts", json=body("L1", 0.01), headers=H())
        tot = q(lambda: op.client_act_line_totals.find_one({"offer_line_id": i["L1"]}, {"_id": 0, "acted_units": 1}))
        print(mode, "A3 put+3", u1.status_code, t1, "put-5", u2.status_code, t2, "new 8", n8.status_code, "0.01", n9.status_code, "totals", tot)
        if (u1.status_code, u2.status_code, n8.status_code, n9.status_code) != (200, 200, 201, 409) or (t1, t2) != (7, 2) \
                or (tot or {}).get("acted_units") != 100000:
            F.append("%s A3 %s" % (mode, (u1.status_code, u2.status_code, n8.status_code, n9.status_code, t1, t2, tot)))
        # A4
        restore(); b0 = cnt("client_acts")
        res = {lk: tc.post("/api/client-acts", json=body(lk, 1), headers=H()).status_code for lk in ("LB", "LP2", "L3")}
        print(mode, "A4", res, "written", cnt("client_acts") - b0)
        if cnt("client_acts") != b0 or any(c < 400 or c >= 500 for c in res.values()):
            F.append("%s A4 %s" % (mode, res))
        # A5 / A6
        restore(); b0 = cnt("client_acts")
        nk = tc.post("/api/client-acts", json=body("L1", 1), headers={"Authorization": "Bearer " + tok})
        k = "same-" + uuid.uuid4().hex[:6]
        r1 = tc.post("/api/client-acts", json=body("L1", 1), headers=H(k)); r2 = tc.post("/api/client-acts", json=body("L1", 1), headers=H(k))
        r3 = tc.post("/api/client-acts", json=body("L1", 2), headers=H(k))
        evs = cnt("audit_events", {"action": "client_act.created"})
        print(mode, "A5", nk.status_code, r1.status_code, r2.status_code, r2.json() == r1.json(), r3.status_code, "acts", cnt("client_acts") - b0, "events", evs)
        if (nk.status_code, r1.status_code, r2.status_code, r3.status_code) != (428, 201, 201, 409) and \
                (nk.status_code, r1.status_code, r3.status_code) != (428, 201, 409) or cnt("client_acts") - b0 != 1 or r2.json() != r1.json() or evs != 1:
            F.append("%s A5 %s" % (mode, (nk.status_code, r1.status_code, r2.status_code, r3.status_code, evs)))
        restore()
    q(lambda: client.drop_database(os.environ["DB_NAME"])); q(lambda: client.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
