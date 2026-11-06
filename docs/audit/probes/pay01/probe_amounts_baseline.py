"""CLAUDE AUDIT probe: non-finite amounts on finance payment create / transfer / allocate (any branch).
    cd <worktree>/backend && PYTHONPATH=. MONGO_URL=... python <this>"""
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
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    rep = tc.portal.call(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    a1 = tc.post("/api/finance/accounts", json={"name": "K", "type": "Cash"}, headers=H).json()["id"]
    a2 = tc.post("/api/finance/accounts", json={"name": "B", "type": "Bank"}, headers=H).json()["id"]
    n = lambda coll: tc.portal.call(lambda: op[coll].count_documents({}))
    for amt in ("nan", "inf"):
        b = n("finance_payments")
        r1 = tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": amt, "date": "2026-11-06", "account_id": a1}, headers=H).status_code
        r2 = tc.post("/api/finance/transfers", json={"from_account_id": a1, "to_account_id": a2, "amount": amt}, headers=H).status_code
        print("amount %-4s payment create %s transfer %s → ledger +%d" % (amt, r1, r2, n("finance_payments") - b))
    tc.portal.call(lambda: c.drop_database(os.environ["DB_NAME"])); tc.portal.call(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
