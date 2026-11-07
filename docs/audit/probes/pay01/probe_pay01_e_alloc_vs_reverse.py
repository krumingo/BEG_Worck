"""CLAUDE AUDIT probe — #70 C01-E (Codex F-70-01): allocate and reverse of the SAME payment racing.
Each round: payment 100, invoice 1000; concurrently POST allocate 60 and DELETE (reverse) the payment.
Invariant: never a REVERSED payment that still has an active allocation; every reversal has exactly one
'finance.payment.reversed' AuditEvent.
    cd <wt>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
"""
import os, sys, uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod, server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW = "Probe-Synthetic-Pass-2026!"
ROUNDS = int(os.environ.get("PROBE_ROUNDS", "12"))
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    K = lambda: dict(H, **{"Idempotency-Key": "k-" + uuid.uuid4().hex})
    a1 = tc.post("/api/finance/accounts", json={"name": "K", "type": "Cash"}, headers=K()).json()["id"]
    def inv(total):
        r = tc.post("/api/finance/invoices", json={"direction": "Issued", "invoice_no": "I-" + uuid.uuid4().hex[:5],
                    "issue_date": "2026-11-06", "due_date": "2026-12-06", "lines": [{"description": "x", "qty": 1, "unit_price": total}]}, headers=K())
        iid = r.json()["id"]; tc.post("/api/finance/invoices/%s/send" % iid, headers=K()); return iid
    pay = lambda amt: tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": amt, "date": "2026-11-06", "account_id": a1}, headers=K()).json()["id"]
    def alloc(pid, iid):
        return ("alloc", tc.post("/api/finance/payments/%s/allocate" % pid, json={"allocations": [{"invoice_id": iid, "amount": 60}]}, headers=K()).status_code)
    def rev(pid):
        return ("rev", tc.request("DELETE", "/api/finance/payments/%s" % pid, json={"reason": "probe"}, headers=K()).status_code)
    bad = dup = 0; outcomes = {}
    for rnd in range(ROUNDS):
        p = pay(100); i = inv(1000)
        with ThreadPoolExecutor(2) as ex:
            futs = [ex.submit(alloc, p, i), ex.submit(rev, p)] if rnd % 2 == 0 else [ex.submit(rev, p), ex.submit(alloc, p, i)]
            res = tuple(sorted(f.result() for f in futs))
        doc = q(lambda: op.finance_payments.find_one({"id": p}, {"_id": 0, "status": 1}))
        act = q(lambda: op.payment_allocations.count_documents({"payment_id": p, "status": {"$ne": "cancelled"}}))
        evs = q(lambda: op.audit_events.count_documents({"action": "finance.payment.reversed", "entity_id": p}))
        outcomes[res] = outcomes.get(res, 0) + 1
        if doc and doc.get("status") == "reversed" and act > 0:
            bad += 1; print("BAD round", rnd, res, "reversed with", act, "active allocation(s)")
        if doc and doc.get("status") == "reversed" and evs != 1:
            dup += 1; print("BAD round", rnd, "reversed events", evs)
    print("outcomes", outcomes)
    if bad: F.append("reversed payment with active allocation in %d/%d" % (bad, ROUNDS))
    if dup: F.append("reversal AuditEvent count != 1 in %d/%d" % (dup, ROUNDS))
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
