"""CLAUDE AUDIT probe — W0-04 idempotency registry needs a unique index on audit_idempotency.id that
only scripts/w0_04_bootstrap_audit_indexes.py --apply creates (not app startup, not tenant provisioning).
6 concurrent POST /api/finance/payments with ONE Idempotency-Key, with and without the index.
    cd <wt70>/backend && PYTHONPATH=. MONGO_URL=... PROBE_CREATE_IDEM_INDEX=0|1 python <this>
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
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    if os.environ.get("PROBE_RUN_STARTUP_INDEXES") == "1":   # what server.startup does on #72
        from app.audit.indexes import ensure_audit_indexes_for_installation
        q(lambda: ensure_audit_indexes_for_installation(op, c[os.environ["BEG_SYSTEM_DB"]]))
    if os.environ.get("PROBE_CREATE_IDEM_INDEX") == "1":
        q(lambda: op["audit_idempotency"].create_index("id", unique=True))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["accountant"]["email"], "password": PW}).json()["token"]}
    a1 = tc.post("/api/finance/accounts", json={"name": "K", "type": "Cash"}, headers=dict(H, **{"Idempotency-Key": "acc-" + sfx})).json()["id"]
    worst = 0
    for attempt in range(4):
        hk = dict(H, **{"Idempotency-Key": "race-%d-%s" % (attempt, sfx)})
        b = q(lambda: op.finance_payments.count_documents({}))
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda i: tc.post("/api/finance/payments", json={"direction": "Inflow", "amount": 10, "date": "2026-11-06",
                                                                                 "account_id": a1}, headers=hk).status_code, range(6)))
        d = q(lambda: op.finance_payments.count_documents({})) - b
        worst = max(worst, d)
        print("index=%s attempt %d: %s rows +%d" % (os.environ.get("PROBE_CREATE_IDEM_INDEX", "0"), attempt, sorted(res), d))
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("WORST rows per key:", worst)
