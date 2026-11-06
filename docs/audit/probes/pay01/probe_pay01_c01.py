"""CLAUDE AUDIT probe PAY-01-C01 Part 1 (#70): amounts and reason, every money route, real server.app.

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
A  amount ∈ {nan, inf, -inf, 1e309, "", -1, 0, true, "abc"} on: POST payments, transfers, account-funding,
   other-expense, other-income, invoice quick-pay (/invoices/{id}/payments), allocate → 422 (or 4xx), 0 rows.
A+ valid amount 12.5 on each route still 2xx (no regression).
R  reversal reason: 500 chars ok; 501 → 400; ZWSP / bidi RLO / NUL / ESC → 400; plus Cf characters outside the
   list (soft hyphen U+00AD, tag U+E0041, line separator U+2028) reported.
"""
import os, sys, uuid
from pathlib import Path
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test", JWT_SECRET="p-" + sfx,
                  PERMISSION_SERVICE_MODE="off")
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod, server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    a1 = tc.post("/api/finance/accounts", json={"name": "K", "type": "Cash"}, headers=H).json()["id"]
    a2 = tc.post("/api/finance/accounts", json={"name": "B", "type": "Bank"}, headers=H).json()["id"]
    def new_invoice():
        r = tc.post("/api/finance/invoices", json={"direction": "Issued", "invoice_no": "I-" + uuid.uuid4().hex[:5],
                    "issue_date": "2026-11-06", "due_date": "2026-12-06",
                    "lines": [{"description": "x", "qty": 1, "unit_price": 1000}]}, headers=H)
        iid = r.json().get("id")
        tc.post("/api/finance/invoices/%s/send" % iid, headers=H)
        return iid
    inv = new_invoice()
    payid = tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": 500, "date": "2026-11-06", "account_id": a1}, headers=H).json()["id"]
    routes = {
        "payments": lambda v: tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": v, "date": "2026-11-06", "account_id": a1}, headers=H),
        "transfers": lambda v: tc.post("/api/finance/transfers", json={"from_account_id": a1, "to_account_id": a2, "amount": v}, headers=H),
        "account-funding": lambda v: tc.post("/api/finance/account-funding", json={"account_id": a1, "amount": v, "date": "2026-11-06"}, headers=H),
        "other-expense": lambda v: tc.post("/api/finance/other-expense", json={"account_id": a1, "amount": v, "date": "2026-11-06", "project_id": A["project_id"]}, headers=H),
        "other-income": lambda v: tc.post("/api/finance/other-income", json={"account_id": a1, "amount": v, "date": "2026-11-06", "counterparty_name": "X"}, headers=H),
        "invoice quick-pay": lambda v: tc.post("/api/finance/invoices/%s/payments" % inv, json={"amount": v, "method": "Cash", "account_id": a1}, headers=H),
        "allocate": lambda v: tc.post("/api/finance/payments/%s/allocate" % payid, json={"allocations": [{"invoice_id": inv, "amount": v}]}, headers=H),
    }
    rows = lambda: q(lambda: op["finance_payments"].count_documents({})) + q(lambda: op["payment_allocations"].count_documents({}))
    for name, fn in routes.items():
        bad = []
        for v in ("nan", "inf", "-inf", "1e309", "", -1, 0, True, "abc"):
            b = rows(); r = fn(v); d = rows() - b
            if not (400 <= r.status_code < 500) or d != 0:
                bad.append("%r→%s(+%d)" % (v, r.status_code, d))
        ok = fn(12.5)
        line = "A %-18s hostile: %s | valid 12.5 → %s" % (name, "all 4xx, 0 rows" if not bad else bad, ok.status_code)
        print(line)
        if bad or ok.status_code >= 300: F.append(name)
    pid = tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": 7, "date": "2026-11-06", "account_id": a1}, headers=H).json()["id"]
    for label, reason, expect in [("500 chars", "я" * 500, 200), ("501 chars", "я" * 501, 400), ("ZWSP", "грешка​", 400),
                                  ("RLO", "грешка‮", 400), ("NUL", "a\x00b", 400), ("ESC", "a\x1b[31m", 400),
                                  ("soft hyphen U+00AD", "гре­шка", None), ("tag U+E0041", "a\U000E0041b", None),
                                  ("line sep U+2028", "a b", None)]:
        p2 = tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": 7, "date": "2026-11-06", "account_id": a1}, headers=H).json()["id"]
        r = tc.request("DELETE", "/api/finance/payments/%s" % p2, json={"reason": reason}, headers=H)
        tag = "" if expect is None else ("ok  " if r.status_code == expect else "FAIL")
        print("R %-4s %-20s → %s" % (tag, label, r.status_code))
        if expect is not None and r.status_code != expect: F.append("R " + label)
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
sys.exit(1 if F else 0)
