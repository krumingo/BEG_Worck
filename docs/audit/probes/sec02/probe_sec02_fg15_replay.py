"""CLAUDE AUDIT probe — #71 FG-15 on replay: a member Technician POSTs /labor-entries with an
Idempotency-Key twice. Neither the first response nor the REPLAY may carry hourly_rate / labor_cost;
the stored row keeps them; the replay writes no new row. Accountant replay sees the money.
    cd <wt71>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
"""
import os, sys, uuid
from pathlib import Path
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE=os.environ.get("PROBE_MODE", "off"))
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod, server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
MONEY = {"hourly_rate", "labor_cost"}
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    tok = lambda k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
    Hadm, Htech, Hacc = tok("admin"), tok("technician"), tok("accountant")
    r = tc.post("/api/projects/%s/team" % A["project_id"], json={"user_id": U["technician"]["id"], "role_in_project": "Technician"}, headers=Hadm)
    print("team add:", r.status_code)
    # give the worker a rate so labor_cost is computed
    q(lambda: op.employee_profiles.update_one({"user_id": U["technician"]["id"]}, {"$set": {"hourly_rate": 25, "org_id": A["tenant_id"],
                                              "user_id": U["technician"]["id"]}}, upsert=True))
    body = {"project_id": A["project_id"], "employee_id": U["technician"]["id"], "date": "2026-11-05", "hours": 4}
    for who, H in (("technician", Htech), ("accountant", Hacc)):
        k = dict(H, **{"Idempotency-Key": "fg15-%s-%s" % (who, sfx)})
        n0 = q(lambda: op.labor_entries.count_documents({}))
        r1 = tc.post("/api/labor-entries", json=body, headers=k); r2 = tc.post("/api/labor-entries", json=body, headers=k)
        n1 = q(lambda: op.labor_entries.count_documents({}))
        j1, j2 = r1.json(), r2.json()
        stored = q(lambda: op.labor_entries.find_one({"id": j1.get("id")}, {"_id": 0})) or {}
        leak1, leak2 = sorted(MONEY & set(j1)), sorted(MONEY & set(j2))
        print("%s: %s/%s rows +%d; first money keys %s, replay money keys %s; stored has %s; same id %s" % (
            who, r1.status_code, r2.status_code, n1 - n0, leak1, leak2, sorted(MONEY & set(stored)), j1.get("id") == j2.get("id")))
        if who == "technician" and (leak1 or leak2 or n1 - n0 != 1 or r1.status_code != 201):
            F.append("technician FG-15 first/replay leak or bad write")
        if who == "accountant" and (n1 - n0 != 1 or not leak2 and "hourly_rate" in stored):
            F.append("accountant replay lost the money / bad write")
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
