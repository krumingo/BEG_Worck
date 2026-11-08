"""CLAUDE AUDIT probe — #69 F-69-03 (3fb55f2 / da47777): a retry recognises its own certified-cap
reservation. PR #69's C02 seed (package certified 100). Real Mongo RS, off/shadow/enforce.
  F1  crash right AFTER the cap reservation (before the ledger insert), same-key retry
      -> 1 ledger row of 60, committed 60, paid 60
  F2  same crash, then 6 CONCURRENT same-key retries -> still 1 row, committed 60
  F3  phantom: crash after reserving 60 and the key is abandoned; a NEW key for 50 -> 409
      (the phantom only blocks headroom; it never pays) and a new key for 40 -> 201 (100 total)
  F4  FG-105: paid_total == Σ ordinary payments in the DB after F1
    cd <tree>/backend && PYTHONPATH=. W0_03_REAL_MONGO_URL=... python <this>
"""
import asyncio, os, sys, uuid, importlib.util
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
URL = os.environ["W0_03_REAL_MONGO_URL"]; os.environ.setdefault("MONGO_URL", URL)
def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, "tests/" + fn)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m
pm = _load("f6903_pm", "test_pm_01_permission_matrix.py"); c02 = _load("f6903_c02", "test_sec_01_c02_flow_guard_money_writes.py")
import server, httpx  # noqa
from fastapi.testclient import TestClient  # noqa
from app.routes import subcontractors as sc  # noqa
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
PW = "F6903-Synthetic-Pass-2026!"; F = []
with TestClient(app, raise_server_exceptions=False) as tc:
    q = lambda f: tc.portal.call(f)
    client = q(lambda: pm._make_client(URL)); op = client[os.environ["DB_NAME"]]
    rep = q(lambda: pm._load_seed().seed(op, client[os.environ["BEG_SYSTEM_DB"]], PW))
    fx = {t["key"]: {"tenant_id": t["tenant_id"], "project_id": t["project_id"], "users": {u["key"]: u for u in t["users"]}} for t in rep["tenants"]}
    q(lambda: pm.seed_existing_records(op, fx)); q(lambda: c02.seed_c02_records(op, fx))
    q(lambda: op.audit_idempotency.create_index([("id", 1)], unique=True))
    q(lambda: op.audit_idempotency.create_index([("tenant_id", 1), ("action", 1), ("key", 1)], unique=True))
    snap = q(lambda: pm._snapshot(client, (os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"])))
    tok = tc.post("/api/auth/login", json={"email": fx["A"]["users"]["accountant"]["email"], "password": PW}).json()["token"]
    H = lambda k=None: {"Authorization": "Bearer " + tok, "Idempotency-Key": k or uuid.uuid4().hex}
    PKG = c02.rid("A", "pkg")
    pay = lambda amt: {"package_id": PKG, "amount": amt}
    pkg = lambda: q(lambda: op.subcontractor_packages.find_one({"id": PKG}, {"_id": 0}))
    rows = lambda: q(lambda: op.subcontractor_payments.find({"package_id": PKG, "status": "completed"}, {"_id": 0, "amount": 1}).to_list(None))
    ledger = lambda: q(lambda: op.finance_payments.count_documents({"subcontractor_payment_id": {"$exists": True}}))
    restore = lambda: q(lambda: pm._restore(client, snap, sorted(snap)))
    orig = sc._reserve_within_certified

    def crash_after_reserve():
        st = {"armed": True}
        async def wrapped(*a, **k):
            r = await orig(*a, **k)
            if st["armed"]:
                st["armed"] = False
                raise RuntimeError("synthetic crash after the cap reservation")
            return r
        sc._reserve_within_certified = wrapped

    async def gather(reqs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as ac:
            return await asyncio.gather(*[ac.post(u, json=b, headers=h) for u, b, h in reqs])

    for mode in ("off", "shadow", "enforce"):
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        for name in ("F1", "F2"):
            restore(); l0 = ledger(); k = "%s-%s" % (name, uuid.uuid4().hex[:6])
            crash_after_reserve()
            r1 = tc.post("/api/subcontractor-payments", json=pay(60), headers=H(k))
            sc._reserve_within_certified = orig
            if name == "F1":
                r2 = [tc.post("/api/subcontractor-payments", json=pay(60), headers=H(k))]
            else:
                r2 = q(lambda: gather([("/api/subcontractor-payments", pay(60), H(k)) for _ in range(6)]))
            p = pkg(); paid_rows = sum(float(x.get("amount") or 0) for x in rows())
            st = (ledger() - l0, p.get("committed_paid_total"), p.get("paid_total"), paid_rows)
            print(mode, name, r1.status_code, sorted(x.status_code for x in r2), "ledger+%d committed %s paid %s Σrows %s" % st)
            if st != (1, 60, 60, 60) and st[:3] != (1, 60.0, 60.0):
                F.append("%s %s %s" % (mode, name, st))
            if name == "F1" and abs(float(p.get("paid_total") or 0) - paid_rows) > 0.005:
                F.append("%s F4 paid_total %s != Σ %s" % (mode, p.get("paid_total"), paid_rows))
        restore()
        crash_after_reserve()
        tc.post("/api/subcontractor-payments", json=pay(60), headers=H())          # abandoned key
        sc._reserve_within_certified = orig
        a = tc.post("/api/subcontractor-payments", json=pay(50), headers=H())
        b = tc.post("/api/subcontractor-payments", json=pay(40), headers=H())
        p = pkg()
        print(mode, "F3 phantom 60 held; new 50 ->", a.status_code, "new 40 ->", b.status_code, "committed", p.get("committed_paid_total"), "paid", p.get("paid_total"))
        if a.status_code != 409 or float(p.get("paid_total") or 0) > 100.005:
            F.append("%s F3 %s %s paid %s" % (mode, a.status_code, b.status_code, p.get("paid_total")))
        restore()
        if os.environ.get("PROBE_G") == "1":
            # G (#69 25ffd9b, addendum G): crash right AFTER the payment's audit insert, then 2
            # same-key retries -> exactly 1 audit_logs row "subcontractor_payment_created"
            restore()
            real_la = sc.log_audit; st = {"armed": True}
            async def la(*a, **k):
                r = await real_la(*a, **k)
                if st["armed"] and a[3] == "subcontractor_payment_created":
                    st["armed"] = False
                    raise RuntimeError("synthetic crash after the audit insert")
                return r
            sc.log_audit = la
            k = "G-" + uuid.uuid4().hex[:6]
            l0 = q(lambda: op.audit_logs.count_documents({"action": "subcontractor_payment_created"}))
            g1 = tc.post("/api/subcontractor-payments", json=pay(60), headers=H(k))
            sc.log_audit = real_la
            g2 = tc.post("/api/subcontractor-payments", json=pay(60), headers=H(k))
            g3 = tc.post("/api/subcontractor-payments", json=pay(60), headers=H(k))
            dl = q(lambda: op.audit_logs.count_documents({"action": "subcontractor_payment_created"})) - l0
            print(mode, "G payment crash after audit:", g1.status_code, g2.status_code, g3.status_code, "audit rows +%d" % dl, "ledger", ledger())
            if dl != 1 or g3.status_code >= 500:
                F.append("%s G audit +%d" % (mode, dl))
            restore()
        if os.environ.get("PROBE_H") == "1":
            # H (#69 b2b3ae0, addendum H, Codex F-69-04): money in whole cents.
            def setcap(cert):
                q(lambda: op.subcontractor_packages.update_one({"id": PKG}, {"$set": {
                    "certified_total": cert, "paid_total": 0, "committed_paid_total": 0}}))
            restore(); setcap(0.05); l0 = ledger()
            h1 = [tc.post("/api/subcontractor-payments", json=pay(0.0049), headers=H()).status_code for _ in range(20)]
            p = pkg(); st1 = (p.get("committed_paid_total"), p.get("paid_total"), ledger() - l0)
            print(mode, "H1 cap 0.05, 20x0.0049 seq:", sorted(set(h1)), "committed/paid/ledger+", st1)
            if set(h1) != {422} or st1 != (0, 0, 0):
                F.append("%s H1 %s %s" % (mode, sorted(set(h1)), st1))
            restore(); setcap(0.05); l0 = ledger()
            h2 = q(lambda: gather([("/api/subcontractor-payments", pay(0.01), H()) for _ in range(12)]))
            codes = sorted(x.status_code for x in h2); p = pkg(); srows = round(sum(float(x["amount"]) for x in rows()), 6)
            st2 = (codes.count(201), round(float(p.get("committed_paid_total") or 0), 6), round(float(p.get("paid_total") or 0), 6), srows, ledger() - l0)
            print(mode, "H2 cap 0.05, 12x0.01 concurrent:", codes, "201s/committed/paid/Σrows/ledger+", st2)
            if st2 != (5, 0.05, 0.05, 0.05, 5):
                F.append("%s H2 %s" % (mode, st2))
            restore(); setcap(100000)
            cells = {}
            for v, want in ((0.30000000000000004, 422), (1e-3, 422), (5e-324, 422), (123.456789, 422),
                            (99.999, 422), (10.10, 201), (100, 201), (1e2, 201), (0.01, 201), (12345.67, 201)):
                r = tc.post("/api/subcontractor-payments", json=pay(v), headers=H())
                cells[repr(v)] = r.status_code
                if r.status_code != want:
                    F.append("%s H3 %r -> %s (want %s)" % (mode, v, r.status_code, want))
            vat = tc.post("/api/subcontractor-payments", json={**pay(10), "vat_amount": 0.005}, headers=H()).status_code
            cells["vat 0.005"] = vat
            if vat != 422:
                F.append("%s H3 vat 0.005 -> %s" % (mode, vat))
            print(mode, "H3 values:", cells)
            restore()
    q(lambda: client.drop_database(os.environ["DB_NAME"])); q(lambda: client.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
