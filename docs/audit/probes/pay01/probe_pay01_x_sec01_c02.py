"""CLAUDE AUDIT integration probe #70 (PAY-01) × #69 (SEC-01-C02 FG-27), run on a local merge of both heads.
A subcontractor payment (FG-27) writes a finance_payments Outflow + a subcontractor_payments row.
PAY-01 reverses the ledger row. Does the subcontractor side follow (payment status / package paid & payable)?"""
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
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    q(lambda: op["subcontractor_packages"].insert_one({"id": "pkg-1", "org_id": A["tenant_id"], "project_id": A["project_id"],
        "subcontractor_id": "s1", "subcontractor_name": "Sub", "currency": "EUR", "certified_total": 1000.0}))
    acc = tc.post("/api/finance/accounts", json={"name": "Каса", "type": "Cash"}, headers=H).json()["id"]
    r = tc.post("/api/subcontractor-payments", json={"package_id": "pkg-1", "amount": 300, "account_id": acc}, headers=H)
    sp = r.json(); led = sp.get("finance_payment_id")
    pkg0 = q(lambda: op["subcontractor_packages"].find_one({"id": "pkg-1"}, {"_id": 0}))
    rv = tc.request("DELETE", "/api/finance/payments/%s" % led, json={"reason": "грешно плащане"}, headers=H)
    pkg1 = q(lambda: op["subcontractor_packages"].find_one({"id": "pkg-1"}, {"_id": 0}))
    spr = q(lambda: op["subcontractor_payments"].find_one({"id": sp.get("id")}, {"_id": 0, "status": 1, "amount": 1}))
    bal = next(x for x in tc.get("/api/finance/accounts", headers=H).json() if x["id"] == acc)["current_balance"]
    keys = [k for k in pkg0 if "paid" in k or "payable" in k]
    print("subcontractor payment:", r.status_code, "ledger reversal:", rv.status_code)
    print("ledger account balance after reversal:", bal)
    print("subcontractor_payments row after reversal:", spr)
    print("package before:", {k: pkg0.get(k) for k in keys}, " after:", {k: pkg1.get(k) for k in keys})
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
