"""CLAUDE AUDIT probe — #70 D5 allocate. Validation reads a snapshot, then writes; nothing serialises two
DIFFERENT-key allocate requests. R1: one payment of 100, two concurrent allocates of 80 (to two invoices,
different keys) → over-allocation? R2: one invoice of 1000 remaining, two payments of 800 allocated to it
concurrently → invoice over-paid? Also: retry of a failed key after the own allocation was cancelled.
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
        iid = r.json()["id"]; tc.post("/api/finance/invoices/%s/send" % iid, headers=K())
        return iid, q(lambda: op.invoices.find_one({"id": iid}, {"_id": 0, "total": 1}))["total"]
    pay = lambda amt: tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": amt, "date": "2026-11-06", "account_id": a1}, headers=K()).json()["id"]
    alloc = lambda pid, iid, amt: tc.post("/api/finance/payments/%s/allocate" % pid, json={"allocations": [{"invoice_id": iid, "amount": amt}]}, headers=K())
    act = lambda flt: sum(a["amount_allocated"] for a in q(lambda: op.payment_allocations.find(dict(flt, status={"$ne": "cancelled"}), {"_id": 0}).to_list(100)))
    over_p = over_i = 0
    for attempt in range(5):
        p = pay(100); (i1, t1), (i2, t2) = inv(1000), inv(1000)
        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda iid: alloc(p, iid, 80).status_code, (i1, i2)))
        tot = act({"payment_id": p})
        print("R1 attempt %d: payment 100, 2x80 concurrent → %s; allocated on payment %s" % (attempt, sorted(res), tot))
        over_p += tot > 100
        (i3, t3) = inv(1000); p1, p2 = pay(800), pay(800)
        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda pid: alloc(pid, i3, 800).status_code, (p1, p2)))
        ti = act({"invoice_id": i3})
        print("R2 attempt %d: invoice total %s, 2 payments x800 concurrent → %s; allocated on invoice %s" % (attempt, t3, sorted(res), ti))
        over_i += ti > t3
    if over_p: F.append("R1 payment over-allocated in %d/5" % over_p)
    if over_i: F.append("R2 invoice over-paid in %d/5" % over_i)
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
