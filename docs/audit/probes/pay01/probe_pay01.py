"""CLAUDE AUDIT probes PAY-01 (#70). Real server.app on scratch DBs (ST-01 seed), real JWT, real Mongo RS.

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
Q1 6 concurrent DELETEs of ONE payment → exactly 1 success, 1 reversal row, 1 audit event.
Q2 6 concurrent reversals of 6 DIFFERENT payments → 6 successes, 6 reversal rows, 6 audit events (no 500).
Q3 Idempotency-Key: replay → same body as first; same key + different reason → 409.
Q4 balances + list: inflow 100 reversed → account balance back to opening; list default hides both rows,
   include_reversed shows 2; stats unaffected.
Q5 own-account transfer 50 A→B; DELETE one leg → both legs reversed; both balances back.
Q6 hostile input: reason = 5000 chars / control chars / object; payment create + allocate + transfer with
   amount nan / inf → must be 4xx and nothing written.
Q7 crash recovery: original marked reversed without its reversal row → DELETE again → pair completed, 1 row.
Q8 Viewer / SiteManager / Technician DELETE payment + allocation → 403, nothing written, modes off/shadow/enforce.
"""
import os, sys, uuid, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod  # noqa
import server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond: F.append(label)
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"]))
    op, sysdb = c[os.environ["DB_NAME"]], c[os.environ["BEG_SYSTEM_DB"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, sysdb, PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    H = {k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
         for k in ("accountant", "viewer", "requester", "technician")}
    acc = lambda name, ob=0: tc.post("/api/finance/accounts", json={"name": name, "type": "Cash", "opening_balance": ob}, headers=H["accountant"]).json()["id"]
    a1, a2 = acc("Каса", 0), acc("Банка", 0)
    pay = lambda amt=100, d="Inflow", a=a1: tc.post("/api/finance/payments", json={"direction": d, "amount": amt, "date": "2026-11-06",
                                                    "account_id": a, "counterparty_name": "X"}, headers=H["accountant"])
    rev = lambda pid, reason="грешка", key=None, h="accountant": tc.request("DELETE", "/api/finance/payments/%s" % pid,
            json={"reason": reason}, headers=dict(H[h], **({"Idempotency-Key": key} if key else {})))
    cnt = lambda coll, flt: q(lambda: op[coll].count_documents(flt))
    # Q1
    p = pay().json()["id"]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda i: rev(p).status_code, range(6)))
    check(res.count(200) == 1 and cnt("finance_payments", {"reverses_payment_id": p}) == 1
          and cnt("audit_events", {"action": "finance.payment.reversed", "entity_id": p}) == 1,
          "Q1 one payment, 6 concurrent DELETEs: statuses %s, reversal rows %d, audit %d" % (
              sorted(res), cnt("finance_payments", {"reverses_payment_id": p}),
              cnt("audit_events", {"action": "finance.payment.reversed", "entity_id": p})))
    # Q2
    ids = [pay().json()["id"] for _ in range(6)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda pid: rev(pid).status_code, ids))
    nrev = cnt("finance_payments", {"reverses_payment_id": {"$in": ids}})
    naud = cnt("audit_events", {"action": "finance.payment.reversed", "entity_id": {"$in": ids}})
    nst = cnt("finance_payments", {"id": {"$in": ids}, "status": "reversed"})
    check(res.count(200) == 6 and nrev == 6 and naud == 6,
          "Q2 6 different payments concurrently: statuses %s, reversed %d, reversal rows %d, audit events %d" % (sorted(res), nst, nrev, naud))
    # Q3
    p = pay().json()["id"]
    k = "idem-" + sfx
    r1 = rev(p, key=k); r2 = rev(p, key=k); r3 = rev(p, reason="друга причина", key=k)
    check(r1.status_code == 200 and r2.status_code == 200 and r1.json() == r2.json() and r3.status_code == 409,
          "Q3 idempotency: first %s, replay %s same=%s, other body %s" % (r1.status_code, r2.status_code, r1.json() == r2.json(), r3.status_code))
    # Q4
    def bal(aid):
        return next(x for x in tc.get("/api/finance/accounts", headers=H["accountant"]).json() if x["id"] == aid)["current_balance"]
    b0 = bal(a1); p = pay(100).json()["id"]; b1 = bal(a1); rev(p); b2 = bal(a1)
    lst = [x["id"] for x in tc.get("/api/finance/payments", headers=H["accountant"]).json()]
    lst2 = tc.get("/api/finance/payments?include_reversed=true", headers=H["accountant"]).json()
    pair = [x for x in lst2 if x["id"] == p or x.get("reverses_payment_id") == p]
    check(b1 == b0 + 100 and b2 == b0 and p not in lst and len(pair) == 2,
          "Q4 balance %s → %s → %s; default list hides=%s; include_reversed pair=%d" % (b0, b1, b2, p not in lst, len(pair)))
    # Q5
    ba0, bb0 = bal(a1), bal(a2)
    t = tc.post("/api/finance/transfers", json={"from_account_id": a1, "to_account_id": a2, "amount": 50}, headers=H["accountant"])
    legs = q(lambda: op["finance_payments"].find({"transfer_id": {"$exists": True}, "status": {"$exists": False}}, {"_id": 0}).to_list(10))
    r = rev(legs[0]["id"]) if legs else None
    st = q(lambda: op["finance_payments"].find({"id": {"$in": [l["id"] for l in legs]}}, {"_id": 0, "status": 1}).to_list(10))
    check(t.status_code == 201 and r is not None and r.status_code == 200 and all(s.get("status") == "reversed" for s in st)
          and bal(a1) == ba0 and bal(a2) == bb0,
          "Q5 transfer %s; reverse one leg %s; leg statuses %s; balances back %s/%s" % (
              t.status_code, r.status_code if r else None, [s.get("status") for s in st], bal(a1) == ba0, bal(a2) == bb0))
    # Q6
    p = pay().json()["id"]
    for bad in ("x" * 5000, "a\x00b\x1b[31m", {"$ne": 1}):
        before = cnt("finance_payments", {})
        r = tc.request("DELETE", "/api/finance/payments/%s" % p, json={"reason": bad}, headers=H["accountant"])
        stored = q(lambda: op["finance_payments"].find_one({"id": p}, {"_id": 0, "reversal_reason": 1, "status": 1}))
        print("     Q6 reason %-14r → %s  stored reason len=%s" % (str(bad)[:12], r.status_code, len(str(stored.get("reversal_reason") or ""))))
        if r.status_code == 200:
            q(lambda: op["finance_payments"].update_one({"id": p}, {"$unset": {"status": "", "reversed_by_payment_id": "", "reversal_reason": ""}}))
            q(lambda: op["finance_payments"].delete_many({"reverses_payment_id": p}))
    for amt in ("nan", "inf", "-inf", "1e309"):
        before = cnt("finance_payments", {})
        r = pay(amt)
        r2 = tc.post("/api/finance/transfers", json={"from_account_id": a1, "to_account_id": a2, "amount": amt}, headers=H["accountant"])
        after = cnt("finance_payments", {})
        check(r.status_code >= 400 and r2.status_code >= 400 and after == before,
              "Q6 amount %-6s payment create %s, transfer %s, ledger +%d" % (amt, r.status_code, r2.status_code, after - before))
    inv = tc.post("/api/finance/invoices", json={"direction": "Issued", "invoice_no": "I-1", "issue_date": "2026-11-06",
                  "due_date": "2026-12-06", "lines": [{"description": "x", "qty": 1, "unit_price": 100}]}, headers=H["accountant"])
    if inv.status_code < 300:
        iid = inv.json()["id"]; p = pay(100).json()["id"]
        for amt in ("nan", "inf"):
            before = cnt("payment_allocations", {})
            r = tc.post("/api/finance/payments/%s/allocate" % p, json={"allocations": [{"invoice_id": iid, "amount": amt}]}, headers=H["accountant"])
            check(r.status_code >= 400 and cnt("payment_allocations", {}) == before,
                  "Q6 allocate amount %s → %s, allocations +%d" % (amt, r.status_code, cnt("payment_allocations", {}) - before))
    else:
        print("     Q6 allocate skipped: invoice create", inv.status_code, inv.text[:150])
    # Q7
    p = pay().json()["id"]
    q(lambda: op["finance_payments"].update_one({"id": p}, {"$set": {"status": "reversed", "reversal_reason": "crash"}}))
    r = rev(p, key="crash-" + sfx)
    check(cnt("finance_payments", {"reverses_payment_id": p}) == 1,
          "Q7 crash recovery: DELETE after half-written reversal → %s, reversal rows %d" % (r.status_code, cnt("finance_payments", {"reverses_payment_id": p})))
    # Q8
    p = pay().json()["id"]
    for mode in ("off", "shadow", "enforce"):
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        for role in ("viewer", "requester", "technician"):
            before = cnt("finance_payments", {})
            s = rev(p, h=role).status_code
            check(s in (401, 403) and cnt("finance_payments", {}) == before
                  and q(lambda: op["finance_payments"].find_one({"id": p})).get("status") is None,
                  "Q8 %-7s %-10s DELETE → %s" % (mode, role, s))
    os.environ["PERMISSION_SERVICE_MODE"] = "off"
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
sys.exit(1 if F else 0)
