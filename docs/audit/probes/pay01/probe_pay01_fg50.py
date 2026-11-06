"""CLAUDE AUDIT probe — #70 FG-50: other-expense / other-income with project_id = nonexistent, another
tenant's project, a non-string, "" / absent. Expect 422 + 0 writes for the first three, 201 for absent.
    cd <wt70>/backend && PYTHONPATH=. MONGO_URL=... python <this>
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
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    T = {t["key"]: t for t in rep["tenants"]}; U = {u["key"]: u for u in T["A"]["users"]}
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    K = lambda: dict(H, **{"Idempotency-Key": "k-" + uuid.uuid4().hex})
    a1 = tc.post("/api/finance/accounts", json={"name": "K", "type": "Cash"}, headers=K()).json()["id"]
    rows = lambda: q(lambda: op.finance_payments.count_documents({}))
    for route in ("other-expense", "other-income"):
        for label, pid, expect in (("nonexistent", "no-such-project", 422), ("tenant B project", T["B"]["project_id"], 422),
                                   ("non-string", {"$ne": None}, 422), ("own project", T["A"]["project_id"], 201)):
            body = {"account_id": a1, "amount": 5, "date": "2026-11-06", "counterparty_name": "X", "project_id": pid}
            b = rows(); r = tc.post("/api/finance/%s" % route, json=body, headers=K()); d = rows() - b
            ok = r.status_code == expect and d == (1 if expect == 201 else 0)
            print(("ok   " if ok else "FAIL ") + "%s %-16s → %s writes +%d" % (route, label, r.status_code, d))
            if not ok: F.append("%s %s" % (route, label))
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
