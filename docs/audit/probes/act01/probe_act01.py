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
        if os.environ.get("PROBE_ACT_B") == "1":          # #77 8188689 (Addendum B)
            from app.services import client_acts as ca
            tv = tc.post("/api/auth/login", json={"email": fx["A"]["users"]["viewer"]["email"], "password": T.SYNTH_PASSWORD}).json()["token"]
            HV = {"Authorization": "Bearer " + tv, "Idempotency-Key": uuid.uuid4().hex}
            a = tc.post("/api/client-acts", json=body("L1", 3), headers=H()).json()
            v = tc.post("/api/client-acts/%s/confirm" % a["id"], headers=HV)
            nk = tc.post("/api/client-acts/%s/confirm" % a["id"], headers={"Authorization": "Bearer " + tok})
            st0 = q(lambda: op.client_acts.find_one({"id": a["id"]}, {"_id": 0, "status": 1}))["status"]
            # A8: a crash in the confirm's audit write -> full rollback; same-key retry -> once
            orig = ca._audit; fail = [True]
            async def flaky(*aa, **kk):
                if fail[0] and kk.get("action", "").endswith("confirmed"):
                    fail[0] = False
                    raise RuntimeError("synthetic crash in the confirm audit")
                return await orig(*aa, **kk)
            ca._audit = flaky
            k = "cf-" + uuid.uuid4().hex[:6]
            c1 = tc.post("/api/client-acts/%s/confirm" % a["id"], headers=H(k))
            st1 = q(lambda: op.client_acts.find_one({"id": a["id"]}, {"_id": 0, "status": 1}))["status"]
            ev1 = cnt("audit_events", {"entity_id": a["id"], "action": {"$regex": "confirm"}})
            ca._audit = orig
            c2 = tc.post("/api/client-acts/%s/confirm" % a["id"], headers=H(k))
            c3 = tc.post("/api/client-acts/%s/confirm" % a["id"], headers=H(k))
            st2 = q(lambda: op.client_acts.find_one({"id": a["id"]}, {"_id": 0, "status": 1}))["status"]
            ev2 = cnt("audit_events", {"entity_id": a["id"], "action": {"$regex": "confirm"}})
            print(mode, "A7 viewer", v.status_code, "nokey", nk.status_code, "status", st0,
                  "| A8 crash", c1.status_code, st1, "events", ev1, "-> retry", c2.status_code, c3.status_code, st2, "events", ev2)
            if (v.status_code, nk.status_code, st0) != (403, 428, "Draft") or c1.status_code < 500 and c1.status_code != 500                     or st1 != "Draft" or ev1 != 0 or c2.status_code != 200 or st2 != "Accepted" or ev2 != 1:
                F.append("%s A7/A8 %s" % (mode, (v.status_code, nk.status_code, st0, c1.status_code, st1, ev1, c2.status_code, st2, ev2)))
            restore()
            # A9: exact price 12.345 x 100 -> 1234.50 (half up on the line value only)
            q(lambda: op.offers.update_one({"id": i["O1"], "lines.id": i["L1"]}, {"$set": {
                "lines.$.material_unit_cost": 12.345, "lines.$.labor_unit_cost": 0, "lines.$.qty": 1000}}))
            r = tc.post("/api/client-acts", json=body("L1", 100), headers=H())
            ln = (r.json().get("lines") or [{}])[0] if r.status_code == 201 else {}
            rw = tc.post("/api/client-acts", json={"project_id": P, "lines": [{"offer_line_id": i["L1"], "executed_qty": 1, "unit_price": 12.35}]}, headers=H())
            print(mode, "A9", r.status_code, "unit", ln.get("unit_price"), "total", ln.get("line_total"), "| 12.35 given ->", rw.status_code)
            if ln.get("unit_price") != 12.345 or ln.get("line_total") != 1234.5 or rw.status_code != 422:
                F.append("%s A9 %s %s %s" % (mode, ln.get("unit_price"), ln.get("line_total"), rw.status_code))
            # A10: a non-finance GET shows no prices
            tt = tc.post("/api/auth/login", json={"email": fx["A"]["users"]["technician"]["email"], "password": T.SYNTH_PASSWORD}).json()["token"]
            g = tc.get("/api/client-acts", params={"project_id": P}, headers={"Authorization": "Bearer " + tt})
            txt = g.text
            leak = [k for k in ("unit_price", "line_total", "subtotal", "vat_amount", '"total"', "1234.5", "12.345") if k in txt]
            print(mode, "A10 technician GET", g.status_code, "money keys present:", leak or "none")
            if g.status_code == 200 and leak:
                F.append("%s A10 non-finance sees %s" % (mode, leak))
            restore()
        if os.environ.get("PROBE_ACT_C") == "1":          # #77 611d17e (Addendum C, FG-131)
            import random
            from decimal import Decimal as Dm, ROUND_HALF_UP
            PR_ = Dm("12.345"); CAP = Dm("100")
            val = lambda units: (Dm(units) / 10000 * PR_).quantize(Dm("0.01"), rounding=ROUND_HALF_UP)
            def state(lk="LD"):
                acts = q(lambda: op.client_acts.find({}, {"_id": 0, "lines": 1}).to_list(None))
                s_ = sum((Dm(str(l.get("line_total") or 0)) for a in acts for l in a.get("lines") or []
                          if l.get("offer_line_id") == i[lk]), Dm(0))
                u_ = sum(int(round(float(l.get("executed_qty") or 0) * 10000)) for a in acts
                         for l in a.get("lines") or [] if l.get("offer_line_id") == i[lk])
                tot = q(lambda: op.client_act_line_totals.find_one({"offer_line_id": i[lk]}, {"_id": 0})) or {}
                return s_, u_, tot
            def check(tag, lk="LD"):
                s_, u_, tot = state(lk)
                av = tot.get("acted_value")
                ok = s_ == val(u_) and s_ <= val(1000000) and (av is None or abs(Dm(str(av)) - s_) < Dm("0.005")) \
                    and (not tot or int(tot.get("acted_units", u_)) == u_)
                if not ok:
                    F.append("%s C %s: sum %s vs round(acted x price) %s, acted_value %s, units %s/%s" % (
                        mode, tag, s_, val(u_), av, u_, tot.get("acted_units")))
                return ok
            rng = random.Random(131)
            for rnd in range(3):
                restore(); drafts = []
                for step in range(25):
                    s_, u_, _ = state(); room = 1000000 - u_
                    op_ = rng.choice(["new", "new", "put", "burst", "confirm", "split"])
                    if op_ == "new" and room > 0:
                        qty = min(rng.choice([3.3333, 0.0001, 7.7777, 1.2345, 0.5]), room / 10000)
                        r = tc.post("/api/client-acts", json=body("LD", round(qty, 4)), headers=H())
                        if r.status_code == 201: drafts.append(r.json()["id"])
                    elif op_ == "split" and room >= 2:
                        r = tc.post("/api/client-acts", json={"project_id": P, "lines": [
                            {"offer_line_id": i["LD"], "executed_qty": 0.3333}, {"offer_line_id": i["LD"], "executed_qty": 0.6667}]}, headers=H())
                        if r.status_code == 201: drafts.append(r.json()["id"])
                    elif op_ == "put" and drafts:
                        aid = rng.choice(drafts)
                        qty = rng.choice([0.0001, 2.4691, 5.5555, 9.9999])
                        tc.put("/api/client-acts/%s" % aid, json={"lines": [{"offer_line_id": i["LD"], "executed_qty": qty}]}, headers=H())
                    elif op_ == "burst":
                        rs = q(lambda: gather([("POST", "/api/client-acts", body("LD", 2.2222), H()) for _ in range(8)]))
                        if any(x.status_code >= 500 for x in rs): F.append("%s C burst 5xx" % mode)
                        drafts += [x.json()["id"] for x in rs if x.status_code == 201]
                    elif op_ == "confirm" and drafts:
                        aid = drafts.pop(rng.randrange(len(drafts)))
                        tc.post("/api/client-acts/%s/confirm" % aid, headers=H())
                    check("r%d s%d %s" % (rnd, step, op_))
                # move one draft to another line (its LD part is released), then fill LD exactly
                if drafts:
                    tc.put("/api/client-acts/%s" % drafts[0], json={"lines": [{"offer_line_id": i["L1"], "executed_qty": 1}]}, headers=H())
                    check("r%d moved off LD" % rnd)
                s_, u_, _ = state()
                r = tc.post("/api/client-acts", json=body("LD", (1000000 - u_) / 10000), headers=H())
                over = tc.post("/api/client-acts", json=body("LD", 0.0001), headers=H())
                s_, u_, tot = state()
                print(mode, "C r%d" % rnd, "fill", r.status_code, "sum", s_, "acted", u_ / 10000, "acted_value", tot.get("acted_value"), "| +0.0001 ->", over.status_code)
                if r.status_code != 201 or s_ != Dm("1234.50") or over.status_code != 409:
                    F.append("%s C r%d fill %s sum %s over %s" % (mode, rnd, r.status_code, s_, over.status_code))
                check("r%d full" % rnd)
            restore()
    q(lambda: client.drop_database(os.environ["DB_NAME"])); q(lambda: client.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
