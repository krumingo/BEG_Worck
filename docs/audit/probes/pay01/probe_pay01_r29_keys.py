"""CLAUDE AUDIT probe — #70 R29: every money write without Idempotency-Key → 428 IDEMPOTENCY_KEY_REQUIRED
and nothing written; with a key → success; same key + same body → same response, no new row;
same key + other body → 409. Real server.app, ST-01 seed, real Mongo.
    cd <wt70>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
"""
import os, sys, uuid
from pathlib import Path
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod, server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond: F.append(label)
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    K = lambda: dict(H, **{"Idempotency-Key": "k-" + uuid.uuid4().hex})
    a1 = tc.post("/api/finance/accounts", json={"name": "K", "type": "Cash"}, headers=K()).json().get("id")
    a2 = tc.post("/api/finance/accounts", json={"name": "B", "type": "Bank"}, headers=K()).json().get("id")
    print("accounts:", bool(a1), bool(a2))
    def inv():
        r = tc.post("/api/finance/invoices", json={"direction": "Issued", "invoice_no": "I-" + uuid.uuid4().hex[:5],
                    "issue_date": "2026-11-06", "due_date": "2026-12-06", "lines": [{"description": "x", "qty": 1, "unit_price": 1000}]}, headers=K())
        iid = r.json().get("id"); tc.post("/api/finance/invoices/%s/send" % iid, headers=K()); return iid
    i1 = inv()
    pid = tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": 500, "date": "2026-11-06", "account_id": a1}, headers=K()).json().get("id")
    rows = lambda: sum(q(lambda: op[x].count_documents({})) for x in ("finance_payments", "payment_allocations", "audit_events"))
    routes = {
        "payments": ("POST", "/api/finance/payments", {"direction": "Inflow", "amount": 12.5, "date": "2026-11-06", "account_id": a1}),
        "transfers": ("POST", "/api/finance/transfers", {"from_account_id": a1, "to_account_id": a2, "amount": 12.5}),
        "account-funding": ("POST", "/api/finance/account-funding", {"account_id": a1, "amount": 12.5, "date": "2026-11-06"}),
        "other-expense": ("POST", "/api/finance/other-expense", {"account_id": a1, "amount": 12.5, "date": "2026-11-06", "project_id": A["project_id"]}),
        "other-income": ("POST", "/api/finance/other-income", {"account_id": a1, "amount": 12.5, "date": "2026-11-06", "counterparty_name": "X"}),
        "invoice quick-pay": ("POST", "/api/finance/invoices/%s/payments" % i1, {"amount": 12.5, "method": "Cash", "account_id": a1}),
        "allocate": ("POST", "/api/finance/payments/%s/allocate" % pid, {"allocations": [{"invoice_id": i1, "amount": 12.5}]}),
    }
    for name, (m, url, body) in routes.items():
        b = rows(); r = tc.request(m, url, json=body, headers=H); d = rows() - b
        code = (r.json().get("detail") or {}).get("error_code") if r.status_code == 428 and isinstance(r.json().get("detail"), dict) else r.text[:60]
        check(r.status_code == 428 and d == 0, "R29 %-17s no key → %s %s, writes +%d" % (name, r.status_code, code, d))
        k = K()
        r1 = tc.request(m, url, json=body, headers=k); b2 = rows(); r2 = tc.request(m, url, json=body, headers=k); d2 = rows() - b2
        body3 = dict(body, amount=13) if "amount" in body else {"allocations": [{"invoice_id": i1, "amount": 13}]}
        r3 = tc.request(m, url, json=body3, headers=k)
        check(r1.status_code in (200, 201) and r2.status_code == r1.status_code and r2.json() == r1.json() and d2 == 0 and r3.status_code == 409,
              "R29 %-17s key: %s, replay %s same=%s +%d, other body %s" % (name, r1.status_code, r2.status_code, r1.json() == r2.json(), d2, r3.status_code))
    # reversal / cancel without key
    p2 = tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": 7, "date": "2026-11-06", "account_id": a1}, headers=K()).json()["id"]
    b = rows(); r = tc.request("DELETE", "/api/finance/payments/%s" % p2, json={"reason": "x"}, headers=H); d = rows() - b
    check(r.status_code == 428 and d == 0, "R29 payment reversal no key → %s writes +%d" % (r.status_code, d))
    al = q(lambda: op.payment_allocations.find_one({"payment_id": pid, "status": {"$ne": "cancelled"}}, {"_id": 0}))
    b = rows(); r = tc.request("DELETE", "/api/finance/invoices/%s/payments/%s" % (al["invoice_id"], al["id"]), json={"reason": "x"}, headers=H); d = rows() - b
    check(r.status_code == 428 and d == 0, "R29 allocation cancel no key → %s writes +%d" % (r.status_code, d))
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
