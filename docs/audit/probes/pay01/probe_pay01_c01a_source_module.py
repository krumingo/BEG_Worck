"""CLAUDE AUDIT probe — #70 PAY-01-C01 Addendum A (FG-45). Real server.app, ST-01 seed, real Mongo.
Module-owned finance_payments rows are created by the REAL hr routes (advance, loan, loan repay);
pay-run and subcontractor rows are inserted with the EXACT field set of their writers
(pay_runs._write_salary_outflows, subcontractors create payment). Then:
 M1 DELETE /finance/payments/{id} on each → 409 SOURCE_MODULE_REVERSAL_REQUIRED, finance_payments +
    payment_allocations + audit_events unchanged.
 M2 manual payment → 200 reversed.
 M3 allocation of a module payment: cancel non-last → 200; cancel last → 409, nothing written.
 M4 same with an Idempotency-Key, sent twice → 409 both times (the refusal is not cached as success).
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
AUTO_KEY = os.environ.get("PROBE_AUTO_KEY", "1") == "1"   # R29 (#70 8aac73d): money writes need a key
with TestClient(app, raise_server_exceptions=False) as tc:
    if AUTO_KEY:
        _orig_request = tc.request
        def _keyed(method, url, **kw):
            if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
                h = dict(kw.get("headers") or {})
                h.setdefault("Idempotency-Key", "auto-" + uuid.uuid4().hex)
                kw["headers"] = h
            return _orig_request(method, url, **kw)
        tc.request = _keyed
        tc.post = lambda url, **kw: _keyed("POST", url, **kw)
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    org = A["tenant_id"]
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    a1 = tc.post("/api/finance/accounts", json={"name": "K", "type": "Cash"}, headers=H).json()["id"]
    snap = lambda: tuple(q(lambda: op[x].count_documents({})) for x in ("finance_payments", "payment_allocations", "audit_events"))
    rev = lambda pid, key=None: tc.request("DELETE", "/api/finance/payments/%s" % pid, json={"reason": "грешка"},
                                           headers=dict(H, **({"Idempotency-Key": key} if key else {})))
    # real hr writers
    r = tc.post("/api/advances", json={"user_id": U["technician"]["id"], "type": "Advance", "amount": 50, "account_id": a1}, headers=H)
    r2 = tc.post("/api/advances", json={"guest_name": "Гост", "type": "Loan", "amount": 80, "account_id": a1}, headers=H)
    loan_id = r2.json().get("id")
    r3 = tc.post("/api/advances/%s/repay?amount=30&account_id=%s" % (loan_id, a1), headers=H)
    print("hr advance/loan/repay:", r.status_code, r2.status_code, r3.status_code)
    rows = q(lambda: op.finance_payments.find({"category": {"$in": ["Аванс", "Заем", "Връщане заем"]}}, {"_id": 0}).to_list(10))
    mod = {row["category"]: row["id"] for row in rows}
    now = "2026-11-06T10:00:00+00:00"
    sal = str(uuid.uuid4()); sub = str(uuid.uuid4())
    q(lambda: op.finance_payments.insert_one({"id": sal, "org_id": org, "direction": "Outflow", "amount": 900, "currency": "EUR",
        "date": now[:10], "method": "Cash", "account_id": a1, "counterparty_name": "Служител", "user_id": U["technician"]["id"],
        "reference": "run-x", "note": "Заплата 7", "category": "Заплата", "created_at": now, "updated_at": now}))
    q(lambda: op.finance_payments.insert_one({"id": sub, "org_id": org, "direction": "Outflow", "amount": 300, "currency": "EUR",
        "date": now[:10], "method": "Cash", "account_id": a1, "counterparty_name": "Подизпълнител", "reference": "SP-1",
        "note": "Подизпълнител/бригада плащане", "project_id": A["project_id"], "subcontractor_payment_id": str(uuid.uuid4()),
        "created_at": now, "updated_at": now}))
    mod.update({"Заплата": sal, "subcontractor": sub})
    for label in ("Аванс", "Заем", "Връщане заем", "Заплата", "subcontractor"):
        pid = mod.get(label)
        if not pid:
            check(False, "M1 %s row missing (writer did not write)" % label); continue
        b = snap(); r = rev(pid); d = tuple(x - y for x, y in zip(snap(), b))
        code = (r.json().get("detail") or {}).get("error_code") if r.status_code == 409 else None
        check(r.status_code == 409 and code == "SOURCE_MODULE_REVERSAL_REQUIRED" and d == (0, 0, 0),
              "M1 %-13s DELETE → %s %s, writes %s" % (label, r.status_code, code, d))
    man = tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": 10, "date": "2026-11-06", "account_id": a1}, headers=H).json()["id"]
    r = rev(man); check(r.status_code == 200, "M2 manual payment DELETE → %s" % r.status_code)
    # M3: allocations on the salary row (direction Outflow → needs a Received invoice)
    def inv(direction):
        x = tc.post("/api/finance/invoices", json={"direction": direction, "invoice_no": "I-" + uuid.uuid4().hex[:5],
                    "issue_date": "2026-11-06", "due_date": "2026-12-06", "lines": [{"description": "x", "qty": 1, "unit_price": 1000}]}, headers=H)
        iid = x.json().get("id"); tc.post("/api/finance/invoices/%s/send" % iid, headers=H); return iid
    i1, i2 = inv("Received"), inv("Received")
    ra = tc.post("/api/finance/payments/%s/allocate" % sal, json={"allocations": [{"invoice_id": i1, "amount": 100}, {"invoice_id": i2, "amount": 100}]}, headers=H)
    allocs = q(lambda: op.payment_allocations.find({"payment_id": sal}, {"_id": 0}).to_list(10))
    print("allocate on salary row:", ra.status_code, len(allocs))
    if len(allocs) == 2:
        cancel = lambda a, key=None: tc.request("DELETE", "/api/finance/invoices/%s/payments/%s" % (a["invoice_id"], a["id"]),
                                               json={"reason": "грешка"}, headers=dict(H, **({"Idempotency-Key": key} if key else {})))
        r = cancel(allocs[0]); check(r.status_code == 200, "M3 cancel non-last allocation → %s" % r.status_code)
        b = snap(); r = cancel(allocs[1], key="k-" + sfx); r2 = cancel(allocs[1], key="k-" + sfx); d = tuple(x - y for x, y in zip(snap(), b))
        check(r.status_code == 409 and r2.status_code == 409 and d == (0, 0, 0),
              "M3/M4 cancel last allocation (key x2) → %s %s, writes %s" % (r.status_code, r2.status_code, d))
    else:
        check(False, "M3 allocation setup failed: %s %s" % (ra.status_code, ra.text[:200]))
    # M5 race: a module payment with 2 allocations, both cancelled concurrently — each request sees
    # the other still active, so neither is "the last". Does the payment end up reversed anyway?
    from concurrent.futures import ThreadPoolExecutor
    for attempt in range(5):
        sal2 = str(uuid.uuid4())
        q(lambda: op.finance_payments.insert_one({"id": sal2, "org_id": org, "direction": "Outflow", "amount": 900, "currency": "EUR",
            "date": now[:10], "method": "Cash", "account_id": a1, "counterparty_name": "Служител", "user_id": U["technician"]["id"],
            "reference": "run-y", "note": "Заплата 8", "category": "Заплата", "created_at": now, "updated_at": now}))
        j1, j2 = inv("Received"), inv("Received")
        tc.post("/api/finance/payments/%s/allocate" % sal2, json={"allocations": [{"invoice_id": j1, "amount": 100}, {"invoice_id": j2, "amount": 100}]}, headers=H)
        al = q(lambda: op.payment_allocations.find({"payment_id": sal2}, {"_id": 0}).to_list(10))
        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda a: tc.request("DELETE", "/api/finance/invoices/%s/payments/%s" % (a["invoice_id"], a["id"]),
                                                   json={"reason": "грешка"}, headers=H).status_code, al))
        prow = q(lambda: op.finance_payments.find_one({"id": sal2}, {"_id": 0, "status": 1}))
        nrev = q(lambda: op.finance_payments.count_documents({"reverses_payment_id": sal2}))
        active = q(lambda: op.payment_allocations.count_documents({"payment_id": sal2, "status": {"$ne": "cancelled"}}))
        print("M5 attempt %d: statuses %s, payment status %s, reversal rows %d, allocations not cancelled %d" % (
            attempt, sorted(res), (prow or {}).get("status"), nrev, active))
        if nrev or (prow or {}).get("status") == "reversed":
            check(False, "M5 race reversed a module-owned payment"); break
    # M6 lock: a FRESH foreign lock → 409 PAYMENT_BUSY, nothing written; a STALE one (31 s) → taken over.
    import app.routes.finance as fin
    from datetime import datetime, timezone, timedelta
    def mk_sal():
        pid = str(uuid.uuid4())
        q(lambda: op.finance_payments.insert_one({"id": pid, "org_id": org, "direction": "Outflow", "amount": 900, "currency": "EUR",
            "date": now[:10], "method": "Cash", "account_id": a1, "counterparty_name": "Служител", "user_id": U["technician"]["id"],
            "reference": "run-z", "note": "Заплата 9", "category": "Заплата", "created_at": now, "updated_at": now}))
        k1, k2 = inv("Received"), inv("Received")
        tc.post("/api/finance/payments/%s/allocate" % pid, json={"allocations": [{"invoice_id": k1, "amount": 100}, {"invoice_id": k2, "amount": 100}]}, headers=H)
        return pid, q(lambda: op.payment_allocations.find({"payment_id": pid}, {"_id": 0}).to_list(10))
    cancel1 = lambda a: tc.request("DELETE", "/api/finance/invoices/%s/payments/%s" % (a["invoice_id"], a["id"]), json={"reason": "грешка"}, headers=H)
    for label, age, expect in (("fresh 5s", 5, 409), ("stale 31s", 31, 200)):
        pid, al = mk_sal()
        at = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
        q(lambda: op.finance_payments.update_one({"id": pid}, {"$set": {"allocation_lock": {"token": "other", "at": at}}}))
        b = snap(); r = cancel1(al[0]); d = tuple(x - y for x, y in zip(snap(), b))
        code = (r.json().get("detail") or {}).get("error_code") if r.status_code == 409 else ""
        lock = q(lambda: op.finance_payments.find_one({"id": pid}, {"_id": 0, "allocation_lock": 1}))
        check(r.status_code == expect and (expect == 200 or (code == "PAYMENT_BUSY" and d == (0, 0, 0))),
              "M6 %s foreign lock → %s %s writes %s; lock after: %s" % (label, r.status_code, code, d, lock))
    # M7 takeover race: every lock counts as stale (a slow holder overtaken) → both concurrent cancels run.
    # The guard in _reverse_one must still keep the module payment ACTIVE. What do the responses/state look like?
    old = fin.PAYMENT_LOCK_STALE_SECONDS; fin.PAYMENT_LOCK_STALE_SECONDS = -5
    try:
        for attempt in range(5):
            pid, al = mk_sal()
            with ThreadPoolExecutor(2) as ex:
                res = list(ex.map(lambda a: cancel1(a), al))
            prow = q(lambda: op.finance_payments.find_one({"id": pid}, {"_id": 0, "status": 1}))
            nrev = q(lambda: op.finance_payments.count_documents({"reverses_payment_id": pid}))
            active = q(lambda: op.payment_allocations.count_documents({"payment_id": pid, "status": {"$ne": "cancelled"}}))
            print("M7 attempt %d: %s payment status %s reversal rows %d active allocations %d" % (
                attempt, sorted((x.status_code, ((x.json().get("detail") or {}) if x.status_code >= 400 else {}).get("error_code") if isinstance(x.json().get("detail"), dict) else None) for x in res),
                (prow or {}).get("status"), nrev, active))
            if nrev or (prow or {}).get("status") == "reversed":
                check(False, "M7 takeover race reversed a module payment"); break
    finally:
        fin.PAYMENT_LOCK_STALE_SECONDS = old
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
