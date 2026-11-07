"""CLAUDE AUDIT probe — #76 SUB-ADV-01 (f42da33). Real Mongo RS, every permission mode.
Reuses the PR's own seed (package certified 3200: act1 3000, act2 200, confirmed).
  S1  advance 1000; 6 CONCURRENT advance-deductions of 400 on act1, different keys
      -> deducted <= 1000; act1.advance_deducted == package advance_deducted_total
  S2  advance 1000; 6 CONCURRENT payments on act1 (amount 100 + advance_deducted 400),
      different keys -> deducted <= 1000, committed <= certified, counters == rows
  S3  cap with cash first: act1 paid 3000 in cash, act2 200 deducted -> committed 3200;
      ordinary 0.01 -> 409; a further deduction -> 409
  S4  interrupted advance (_refresh_package_totals fails once) + same-key retry
      -> 1 advance row, 1 ledger row, advance_total once, 1 audit row
  S5  interrupted deduction (same) + same-key retry -> deducted once, 1 act entry
  S6  tenant B accountant on tenant A's package -> 404, nothing written
  S7  6 concurrent advances with ONE key -> 1 row (the package's own claim, re-run)
    cd <tree>/backend && PYTHONPATH=. W0_03_REAL_MONGO_URL=... python <this>
"""
import asyncio, os, sys, uuid
from pathlib import Path
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="subadv_op_" + sfx, BEG_SYSTEM_DB="subadv_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
URL = os.environ["W0_03_REAL_MONGO_URL"]
os.environ.setdefault("MONGO_URL", URL)
sys.path.insert(0, str(Path.cwd()))
import importlib.util  # noqa
spec = importlib.util.spec_from_file_location("subadv_t", "tests/test_sub_adv_01_subcontractor_advance.py")
T = importlib.util.module_from_spec(spec); sys.modules["subadv_t"] = T; spec.loader.exec_module(T)
import server, httpx  # noqa
from fastapi.testclient import TestClient  # noqa
from app.routes import subcontractors as sc  # noqa
pm, c02 = T._pm01(), T._c02()
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
with TestClient(app, raise_server_exceptions=False) as tc:
    q = lambda f: tc.portal.call(f)
    client = q(lambda: pm._make_client(URL)); op = client[os.environ["DB_NAME"]]
    rep = q(lambda: pm._load_seed().seed(op, client[os.environ["BEG_SYSTEM_DB"]], T.SYNTH_PASSWORD))
    fx = {t["key"]: {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                     "users": {u["key"]: u for u in t["users"]}} for t in rep["tenants"]}
    q(lambda: pm.seed_existing_records(op, fx)); q(lambda: c02.seed_c02_records(op, fx))
    q(lambda: T.seed_advance_records(op, fx))
    q(lambda: op.audit_idempotency.create_index([("id", 1)], unique=True))
    q(lambda: op.audit_idempotency.create_index([("tenant_id", 1), ("action", 1), ("key", 1)], unique=True))
    snap = q(lambda: pm._snapshot(client, (os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"])))
    tok = lambda t, r: tc.post("/api/auth/login", json={"email": fx[t]["users"][r]["email"],
                                                        "password": T.SYNTH_PASSWORD}).json()["token"]
    TA, TB = tok("A", "accountant"), tok("B", "accountant")
    H = lambda t=TA, k=None: {"Authorization": "Bearer " + t, "Idempotency-Key": k or uuid.uuid4().hex}
    PKG, A1, A2 = T.rid("pkg"), T.rid("act1"), T.rid("act2")
    ADV = "/api/subcontractor-packages/%s/advances" % PKG
    adv = {"amount": 1000, "reason": "Аванс", "advance_date": "2026-11-07"}
    pkg = lambda: q(lambda: op.subcontractor_packages.find_one({"id": PKG}, {"_id": 0}))
    act = lambda a: q(lambda: op.subcontractor_acts.find_one({"id": a}, {"_id": 0}))
    cnt = lambda coll, flt: q(lambda: op[coll].count_documents(flt))
    restore = lambda: q(lambda: pm._restore(client, snap, sorted(snap)))

    async def gather(reqs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
            return await asyncio.gather(*[ac.post(u, json=b, headers=h) for u, b, h in reqs])

    for mode in T.MODES:
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        # S1
        assert tc.post(ADV, json=adv, headers=H()).status_code == 201
        rs = q(lambda: gather([("/api/subcontractor-acts/%s/advance-deduction" % A1, {"amount": 400}, H())
                               for _ in range(6)]))
        p, a = pkg(), act(A1)
        print(mode, "S1", sorted(r.status_code for r in rs), "deducted", p.get("advance_deducted_total"),
              "act", a.get("advance_deducted"), len(a.get("advance_deductions") or []))
        if (p.get("advance_deducted_total") or 0) > 1000 or a.get("advance_deducted") != p.get("advance_deducted_total"):
            F.append("%s S1 deducted %s act %s" % (mode, p.get("advance_deducted_total"), a.get("advance_deducted")))
        restore()
        # S2
        assert tc.post(ADV, json=adv, headers=H()).status_code == 201
        rs = q(lambda: gather([("/api/subcontractor-payments", {"package_id": PKG, "act_id": A1, "amount": 100,
                                                                "advance_deducted": 400}, H()) for _ in range(6)]))
        p, a = pkg(), act(A1)
        pays = q(lambda: op.subcontractor_payments.find({"package_id": PKG, "kind": "payment"}, {"_id": 0}).to_list(50))
        rows_ded = sum(x.get("advance_deducted") or 0 for x in pays)
        print(mode, "S2", sorted(r.status_code for r in rs), "deducted", p.get("advance_deducted_total"),
              "rows", rows_ded, "committed", p.get("committed_paid_total"), "paid", p.get("paid_total"))
        if (p.get("advance_deducted_total") or 0) > 1000 or rows_ded != p.get("advance_deducted_total") \
                or (p.get("committed_paid_total") or 0) > 3200:
            F.append("%s S2 %s" % (mode, {k: p.get(k) for k in ("advance_deducted_total", "committed_paid_total")}))
        restore()
        # S3
        assert tc.post(ADV, json=adv, headers=H()).status_code == 201
        r1 = tc.post("/api/subcontractor-payments", json={"package_id": PKG, "act_id": A1, "amount": 3000}, headers=H())
        r2 = tc.post("/api/subcontractor-acts/%s/advance-deduction" % A2, json={"amount": 200}, headers=H())
        r3 = tc.post("/api/subcontractor-payments", json={"package_id": PKG, "amount": 0.01}, headers=H())
        r4 = tc.post("/api/subcontractor-acts/%s/advance-deduction" % A2, json={"amount": 1}, headers=H())
        p = pkg()
        print(mode, "S3", r1.status_code, r2.status_code, r3.status_code, r4.status_code, "committed",
              p.get("committed_paid_total"), "outstanding", p.get("advance_outstanding"), "payable", p.get("payable_total"))
        if (r1.status_code, r2.status_code, r3.status_code, r4.status_code)[:2] != (201, 201) or r3.status_code != 409 \
                or r4.status_code != 409:
            F.append("%s S3 %s" % (mode, (r1.status_code, r2.status_code, r3.status_code, r4.status_code)))
        restore()
        # S4 / S5 — interrupted after the counter steps
        orig = sc._refresh_package_totals
        for name, url, body in (("S4", ADV, adv), ("S5", "/api/subcontractor-acts/%s/advance-deduction" % A1, {"amount": 300})):
            if name == "S5":
                assert tc.post(ADV, json=adv, headers=H()).status_code == 201
            fail = [True]
            async def flaky(*a, **k):
                if fail[0]:
                    fail[0] = False
                    raise RuntimeError("synthetic interruption")
                return await orig(*a, **k)
            sc._refresh_package_totals = flaky
            k = "int-%s-%s" % (name, uuid.uuid4().hex[:6])
            x1 = tc.post(url, json=body, headers=H(k=k)); x2 = tc.post(url, json=body, headers=H(k=k))
            sc._refresh_package_totals = orig
            p, a = pkg(), act(A1)
            if name == "S4":
                st = (cnt("subcontractor_payments", {"kind": "advance"}), cnt("finance_payments", {"subcontractor_advance": True}),
                      p.get("advance_total"), cnt("audit_logs", {"action": "subcontractor_advance_created"}))
                ok = st == (1, 1, 1000, 1)
            else:
                st = (p.get("advance_deducted_total"), a.get("advance_deducted"), len(a.get("advance_deductions") or []),
                      cnt("audit_logs", {"action": "subcontractor_advance_deducted"}))
                ok = st == (300, 300, 1, 1)
            print(mode, name, x1.status_code, x2.status_code, st)
            if not ok:
                F.append("%s %s %s %s %s" % (mode, name, x1.status_code, x2.status_code, st))
            restore()
        # S6
        b0 = cnt("subcontractor_payments", {}), cnt("finance_payments", {})
        r = tc.post(ADV, json=adv, headers=H(TB))
        b1 = cnt("subcontractor_payments", {}), cnt("finance_payments", {})
        print(mode, "S6 tenant B →", r.status_code, "written", b1 != b0)
        if r.status_code not in (403, 404) or b1 != b0:
            F.append("%s S6 %s" % (mode, r.status_code))
        restore()
        # S7
        k = "same-" + uuid.uuid4().hex[:6]
        rs = q(lambda: gather([(ADV, adv, H(k=k)) for _ in range(6)]))
        n = cnt("subcontractor_payments", {"kind": "advance"}); led = cnt("finance_payments", {"subcontractor_advance": True})
        print(mode, "S7", sorted(r.status_code for r in rs), "rows", n, "ledger", led, "total", pkg().get("advance_total"))
        if (n, led, pkg().get("advance_total")) != (1, 1, 1000):
            F.append("%s S7 %s" % (mode, (n, led)))
        restore()
        if os.environ.get("PROBE_FG114") == "1":
            # S8 (#76 17aa55d, FG-114): contract 5000, nothing committed; 6 CONCURRENT advances
            # of 999.99 under different keys -> exactly 5 pass (4999.95 <= 5000), 1 x 409
            rs = q(lambda: gather([(ADV, {**adv, "amount": 999.99}, H()) for _ in range(6)]))
            p = pkg(); n = cnt("subcontractor_payments", {"kind": "advance"})
            print(mode, "S8", sorted(r.status_code for r in rs), "rows", n, "advance_total", p.get("advance_total"),
                  "contract", p.get("contract_total"))
            if n != 5 or (p.get("advance_total") or 0) > (p.get("contract_total") or 0) + 0.005:
                F.append("%s S8 %s rows %s total %s" % (mode, sorted(r.status_code for r in rs), n, p.get("advance_total")))
            restore()
            # S9: committed counts — act1 3000 + act2 200 paid in cash (committed 3200), then an
            # advance of 1800 -> 201 (= 5000), a further 0.01 -> 409; a deduction moves nothing
            a = tc.post("/api/subcontractor-payments", json={"package_id": PKG, "act_id": A1, "amount": 3000}, headers=H())
            b = tc.post("/api/subcontractor-payments", json={"package_id": PKG, "act_id": A2, "amount": 200}, headers=H())
            c1 = tc.post(ADV, json={**adv, "amount": 1800}, headers=H())
            c2 = tc.post(ADV, json={**adv, "amount": 0.01}, headers=H())
            print(mode, "S9", a.status_code, b.status_code, c1.status_code, c2.status_code,
                  (c2.json().get("detail") or {}).get("error_code") if c2.status_code != 201 else "")
            if (c1.status_code, c2.status_code) != (201, 409):
                F.append("%s S9 %s %s" % (mode, c1.status_code, c2.status_code))
            restore()
        if os.environ.get("PROBE_F76") == "1":
            # S10 (#76 c4de7c9, Codex F-76-01): contract 5000, certified 3200 (act1 3000 / act2 200).
            PAY = "/api/subcontractor-payments"
            a0 = tc.post(ADV, json={**adv, "amount": 2000}, headers=H())
            p1 = tc.post(PAY, json={"package_id": PKG, "act_id": A1, "amount": 2999.99}, headers=H())
            p2 = tc.post(PAY, json={"package_id": PKG, "act_id": A2, "amount": 0.01}, headers=H())
            p3 = tc.post(PAY, json={"package_id": PKG, "act_id": A2, "amount": 0.01}, headers=H())
            pk = pkg()
            taken = round((pk.get("advance_total") or 0) - (pk.get("advance_deducted_total") or 0) + (pk.get("committed_paid_total") or 0), 2)
            e3 = (p3.json().get("detail") or {}).get("error_code") if p3.status_code != 201 else ""
            print(mode, "S10a adv 2000 | pay 2999.99 %s | +0.01 %s (taken 5000) | +0.01 %s %s | taken %s" % (
                p1.status_code, p2.status_code, p3.status_code, e3, taken))
            if (a0.status_code, p1.status_code, p2.status_code, p3.status_code) != (201, 201, 201, 409) or taken > 5000.005:
                F.append("%s S10a %s %s" % (mode, (a0.status_code, p1.status_code, p2.status_code, p3.status_code), taken))
            restore()
            # S10b: advance 2000, then 6 CONCURRENT ordinary payments of 600 on act1 -> exactly 5 (3000)
            tc.post(ADV, json={**adv, "amount": 2000}, headers=H())
            rs = q(lambda: gather([(PAY, {"package_id": PKG, "act_id": A1, "amount": 600}, H()) for _ in range(6)]))
            pk = pkg(); n = cnt("subcontractor_payments", {"package_id": PKG, "kind": "payment"})
            taken = round((pk.get("advance_total") or 0) - (pk.get("advance_deducted_total") or 0) + (pk.get("committed_paid_total") or 0), 2)
            print(mode, "S10b", sorted(r.status_code for r in rs), "payments", n, "taken", taken)
            if n != 5 or taken > 5000.005:
                F.append("%s S10b %s n=%s taken=%s" % (mode, sorted(r.status_code for r in rs), n, taken))
            restore()
            # S10c: 3 advances of 1000 || 3 payments of 1000 on act1 (one batch) -> taken <= 5000, exactly 5 pass
            rs = q(lambda: gather([(ADV, {**adv, "amount": 1000}, H()) for _ in range(3)] +
                                  [(PAY, {"package_id": PKG, "act_id": A1, "amount": 1000}, H()) for _ in range(3)]))
            pk = pkg()
            taken = round((pk.get("advance_total") or 0) - (pk.get("advance_deducted_total") or 0) + (pk.get("committed_paid_total") or 0), 2)
            ok_n = sum(r.status_code == 201 for r in rs)
            print(mode, "S10c adv||pay", [r.status_code for r in rs], "taken", taken)
            if ok_n != 5 or taken > 5000.005:
                F.append("%s S10c ok=%s taken=%s" % (mode, ok_n, taken))
            restore()
            # S11 (Codex F-76-02): crash at each step, then 2 same-key retries -> 1 audit_logs row and
            # the same number of canonical audit_events as a clean run, per action
            import app.routes.subcontractors as scm
            real = {n_: getattr(scm, n_) for n_ in ("log_audit", "_confirm_advance", "_confirm_deduction", "_refresh_package_totals")}
            def crash_after(name):
                fn = real[name]; state = [True]
                async def w(*a, **k):
                    r = await fn(*a, **k)
                    if state[0]:
                        state[0] = False
                        raise RuntimeError("synthetic crash after " + name)
                    return r
                return w
            def ev():
                return cnt("audit_events", {})
            cases = [("advance", ADV, {**adv, "amount": 1000}, "subcontractor_advance_created", None),
                     ("deduction", "/api/subcontractor-acts/%s/advance-deduction" % A1, {"amount": 300}, "subcontractor_advance_deducted", True),
                     ("payment", PAY, {"package_id": PKG, "act_id": A1, "amount": 100}, "subcontractor_payment_created", None)]
            for cname, url, body, act_name, need_adv in cases:
                # clean baseline
                if need_adv: tc.post(ADV, json=adv, headers=H())
                e0, l0 = ev(), cnt("audit_logs", {"action": act_name})
                tc.post(url, json=body, headers=H())
                d_ev, d_log = ev() - e0, cnt("audit_logs", {"action": act_name}) - l0
                restore()
                for point in ("log_audit", "_confirm_advance", "_confirm_deduction", "_refresh_package_totals"):
                    if need_adv: tc.post(ADV, json=adv, headers=H())
                    e0, l0 = ev(), cnt("audit_logs", {"action": act_name})
                    setattr(scm, point, crash_after(point))
                    k = "f76-%s-%s-%s" % (cname, point, uuid.uuid4().hex[:6])
                    r1 = tc.post(url, json=body, headers=H(k=k))
                    setattr(scm, point, real[point])
                    r2 = tc.post(url, json=body, headers=H(k=k)); r3 = tc.post(url, json=body, headers=H(k=k))
                    de, dl = ev() - e0, cnt("audit_logs", {"action": act_name}) - l0
                    tag = "%s crash after %s: %s %s %s | audit_logs +%d (clean +%d) audit_events +%d (clean +%d)" % (
                        cname, point, r1.status_code, r2.status_code, r3.status_code, dl, d_log, de, d_ev)
                    print(mode, "S11", tag)
                    if (dl, de) != (d_log, d_ev) or r3.status_code >= 500:
                        F.append("%s S11 %s" % (mode, tag))
                    restore()
    q(lambda: client.drop_database(os.environ["DB_NAME"])); q(lambda: client.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
