"""CLAUDE AUDIT probe — #71 SEC-02-C (B-D2/R31): a member SiteManager reads the pulse of his site.
Keys kept for him: budget_snapshot, smr_summary (total_cost + workers_count per SMR), total_labor_cost;
workers[] keeps hours (not money). With ONE worker on an SMR (or on the site that day), is the worker's
pay derivable? Seeds 2 workers on 2 different SMR types on one day.
    cd <wt71>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
"""
import os, sys, uuid, json
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
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    tok = lambda k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
    Hadm, Hsm = tok("admin"), tok("requester")
    print("team:", tc.post("/api/projects/%s/team" % A["project_id"], json={"user_id": U["requester"]["id"], "role_in_project": "SiteManager"}, headers=Hadm).status_code)
    org, p1, day = A["tenant_id"], A["project_id"], "2026-11-04"
    w1, w2 = U["technician"]["id"], U["driver"]["id"]
    seed = ((w1, "Мазилка", 8, 200.0), (w2, "Шпакловка", 6, 210.0))
    if os.environ.get("PROBE_SINGLE") == "1":
        seed = seed[:1]
    for wid, smr, hrs, cost in seed:
        q(lambda: op.work_sessions.insert_one({"id": str(uuid.uuid4()), "org_id": org, "worker_id": wid, "site_id": p1,
            "smr_type_id": smr, "started_at": day + "T07:00:00", "ended_at": day + "T15:00:00",
            "duration_hours": hrs, "labor_cost": cost, "created_at": day}))
    r = tc.get("/api/sites/%s/pulse?date=%s" % (p1, day), headers=Hsm)
    j = r.json()
    print("SM pulse:", r.status_code, "keys:", sorted(j)[:20])
    print("workers:", json.dumps(j.get("workers"), ensure_ascii=False)[:400])
    print("smr_summary:", json.dumps(j.get("smr_summary"), ensure_ascii=False))
    print("total_labor_cost:", j.get("total_labor_cost"))
    derived = {}
    for s in j.get("smr_summary") or []:
        if s.get("workers_count") == 1 and s.get("total_cost"):
            ws = [w for w in (j.get("workers") or []) if s["smr_type"] in (w.get("smr_types") or [])]
            if len(ws) == 1 and ws[0].get("hours"):
                derived[ws[0].get("worker_id") or ws[0].get("name")] = (s["total_cost"], round(s["total_cost"] / ws[0]["hours"], 2))
    print("DERIVED per-worker (pay, rate/h):", derived)
    if derived: F.append("per-worker pay derivable from the SM budget view: %s" % derived)
    if os.environ.get("PROBE_SINGLE") == "1" and j.get("total_labor_cost") not in (None, 0, 0.0):
        F.append("single worker on site: total_labor_cost %s exposed" % j.get("total_labor_cost"))
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
