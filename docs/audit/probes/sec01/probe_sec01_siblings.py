"""CLAUDE AUDIT probe SEC-01 (#69): money-write SIBLING routes that the PR left on the old rule.

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
        python <this file>
Uses the ST-01 seed (tenants A/B) on fresh scratch DBs, real login/JWT, the whole server.app, all 3 modes.

S1  Admin of A sets project price modifiers (PUT, now SEC-01-guarded) → Viewer of A calls
    DELETE /api/price-modifiers/project/{id} → expect 403 and the config still there.
S2  Viewer of A calls POST /api/labor-entries/sync-from-work-reports for A's project after a work report
    exists → expect 403 / no labor_entries written (POST /api/labor-entries itself is SEC-01-guarded).
"""
import os, sys, uuid, importlib.util
from pathlib import Path

sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
BACKEND = Path.cwd()
sys.path.insert(0, str(BACKEND.parent / "ops" / "staging"))
import seed_synthetic as seed_mod  # noqa: E402
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
fails = []
with TestClient(app, raise_server_exceptions=False) as tc:
    cli = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"]))
    op, sysdb = cli[os.environ["DB_NAME"]], cli[os.environ["BEG_SYSTEM_DB"]]
    rep = tc.portal.call(lambda: seed_mod.seed(op, sysdb, PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A")
    users = {u["key"]: u for u in A["users"]}
    tok = {}
    for k in ("admin", "viewer"):
        r = tc.post("/api/auth/login", json={"email": users[k]["email"], "password": PW})
        tok[k] = {"Authorization": "Bearer " + r.json()["token"]}
    pid = A["project_id"]
    for mode in ("off", "shadow", "enforce"):
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        r = tc.put("/api/price-modifiers/project/%s" % pid, json={"modifiers": {}}, headers=tok["admin"])
        setup = r.status_code
        r = tc.delete("/api/price-modifiers/project/%s" % pid, headers=tok["viewer"])
        left = tc.portal.call(lambda: op["price_modifiers_config"].count_documents(
            {"scope": "project", "project_id": pid}))
        print("S1 %-7s admin PUT=%s  viewer DELETE=%s  config rows left=%s" % (mode, setup, r.status_code, left))
        if r.status_code < 300 or left == 0:
            fails.append("S1-" + mode)
        tc.portal.call(lambda: op["work_reports"].insert_one({
            "id": "wr-" + mode, "org_id": A["tenant_id"], "project_id": pid, "user_id": users["viewer"]["id"],
            "date": "2026-11-06", "lines": [{"activity_name": "probe", "hours": 8}]}))
        before = tc.portal.call(lambda: op["labor_entries"].count_documents({}))
        r = tc.post("/api/labor-entries/sync-from-work-reports", json={"project_id": pid}, headers=tok["viewer"])
        after = tc.portal.call(lambda: op["labor_entries"].count_documents({}))
        print("S2 %-7s viewer sync-from-work-reports=%s  labor_entries %s -> %s" % (mode, r.status_code, before, after))
        if r.status_code < 300 and after > before:
            fails.append("S2-" + mode)
    tc.portal.call(lambda: cli.drop_database(os.environ["DB_NAME"]))
    tc.portal.call(lambda: cli.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
