"""CLAUDE AUDIT probe #55 5C-C26 Addendum A (FG-23 / Р20): does a non-finance role (Warehousekeeper, role_id
'warehouse') see money on ANY canonical warehouse endpoint? Real server.app, ST-01 seed, enforce, real JWT.

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
Admin receives 10 @10 into A's warehouse; then the Warehousekeeper calls GET stock / balance / history /
integrity-warnings and POSTs a dispatch. Every response is scanned for money keys (value / cost / price).
"""
import os, sys, uuid, json, re
from pathlib import Path
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test", JWT_SECRET="p-" + sfx,
                  PERMISSION_SERVICE_MODE="enforce")
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod, server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW = "Probe-Synthetic-Pass-2026!"
MONEY = re.compile(r"(value|cost|price|amount)", re.I)
def money_keys(obj, path=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if MONEY.search(k) and k != "values_hidden" and v not in (None, "", 0, "0"):
                out.append(path + "." + k)
            out += money_keys(v, path + "." + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            out += money_keys(v, path + "[%d]" % i)
    return out
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
leaks = {}
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    tid = A["tenant_id"]
    from app.services.warehouse_movements.indexes import ensure_required_indexes
    q(lambda: ensure_required_indexes(op))
    q(lambda: op["md_item"].insert_one({"tenant_id": tid, "org_id": tid, "id": "I1", "canonical_unit": "бр", "name": "Цимент"}))
    H = {k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
         for k in ("admin", "warehousekeeper")}
    WH = {"location_type": "central_warehouse", "location_id": A["warehouse_id"], "state": "free"}
    r = tc.post("/api/warehouse/canonical/movements", json={"action": "receive_from_supplier", "item_id": "I1", "unit": "бр",
                "quantity": "10", "unit_value": "10", "destination": WH, "idempotency_key": "r-" + sfx,
                "reason": "доставка", "file_ids": ["f1"]}, headers=H["admin"])
    print("admin receive:", r.status_code, r.text[:160] if r.status_code >= 300 else "")
    calls = {
        "GET stock": lambda: tc.get("/api/warehouse/canonical/stock/I1", params=WH, headers=H["warehousekeeper"]),
        "GET balance": lambda: tc.get("/api/warehouse/canonical/balance/I1", headers=H["warehousekeeper"]),
        "GET history": lambda: tc.get("/api/warehouse/canonical/history", params={"item_id": "I1"}, headers=H["warehousekeeper"]),
        "GET integrity-warnings": lambda: tc.get("/api/warehouse/canonical/integrity-warnings", headers=H["warehousekeeper"]),
        "POST dispatch (response)": lambda: tc.post("/api/warehouse/canonical/movements", json={
            "action": "dispatch_warehouse_to_project", "item_id": "I1", "unit": "бр", "quantity": "4", "source": WH,
            "destination": {"location_type": "in_transit", "location_id": "pending", "state": "in_transit"},
            "project_id": A["project_id"], "idempotency_key": "d-" + sfx, "reason": "към обект", "file_ids": ["f1"]},
            headers=H["warehousekeeper"]),
    }
    for name, fn in calls.items():
        resp = fn()
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        keys = money_keys(body)
        print("%-26s %s  values_hidden=%s  money keys: %s" % (name, resp.status_code,
              body.get("values_hidden") if isinstance(body, dict) else None, keys[:6] or "none"))
        if resp.status_code < 300 and keys:
            leaks[name] = keys[:6]
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("LEAKS:", leaks or "none")
sys.exit(1 if leaks else 0)
