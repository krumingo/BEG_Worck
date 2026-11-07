"""CLAUDE AUDIT probe — #71 SEC-02-D. (a) POST /api/sites/{id}/pulse/generate has no money strip and only
get_current_user: does a non-member Warehousekeeper / Viewer get per-worker labor_cost? (b) budget_snapshot.
total_spent is the site's ALL-TIME labor at generation time and is kept for the SM: two stored daily pulses
differ by that day's labor — on a single-worker day, that worker's pay (GET /pulse/range as member SM).
    cd <wt71>/backend && PYTHONPATH=. MONGO_URL=... python <this>
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
    Hadm, Hsm, Hwk, Hview = tok("admin"), tok("requester"), tok("warehousekeeper"), tok("viewer")
    tc.post("/api/projects/%s/team" % A["project_id"], json={"user_id": U["requester"]["id"], "role_in_project": "SiteManager"}, headers=Hadm)
    org, p1, w1 = A["tenant_id"], A["project_id"], U["technician"]["id"]
    def sess(day, cost, hrs=8):
        q(lambda: op.work_sessions.insert_one({"id": str(uuid.uuid4()), "org_id": org, "worker_id": w1, "site_id": p1,
            "smr_type_id": "Мазилка", "started_at": day + "T07:00:00", "ended_at": day + "T15:00:00",
            "duration_hours": hrs, "labor_cost": cost, "created_at": day}))
    sess("2026-11-02", 200.0)
    # (a) unguarded generate
    for who, H in (("warehousekeeper (non-member)", Hwk), ("viewer", Hview)):
        r = tc.post("/api/sites/%s/pulse/generate?date=2026-11-02" % p1, headers=H)
        j = r.json() if r.status_code == 200 else {}
        leak = [w.get("labor_cost") for w in (j.get("workers") or []) if w.get("labor_cost")]
        print("A %s POST pulse/generate → %s; workers[].labor_cost %s; total_labor_cost %s; budget %s" % (
            who, r.status_code, leak, j.get("total_labor_cost"), (j.get("budget_snapshot") or {}).get("total_spent")))
        if leak: F.append("pulse/generate leaks per-worker labor_cost to %s" % who)
    # (b) cumulative snapshot differencing
    sess("2026-11-03", 210.0)
    tc.post("/api/sites/%s/pulse/generate?date=2026-11-03" % p1, headers=Hadm)
    r = tc.get("/api/sites/%s/pulse/range?date_from=2026-11-01&date_to=2026-11-30" % p1, headers=Hsm)
    items = sorted(r.json().get("items") or [], key=lambda x: x.get("date"))
    spent = [((i.get("budget_snapshot") or {}).get("total_spent"), i.get("date"), i.get("total_workers")) for i in items]
    print("B SM pulse/range → %s; per day (total_spent, date, workers): %s" % (r.status_code, spent))
    if len(spent) >= 2 and spent[0][0] is not None and spent[1][0] is not None:
        diff = round(spent[1][0] - spent[0][0], 2)
        print("B day-2 labor by difference = %s (one worker that day)" % diff)
        if diff == 210.0: F.append("single-worker day pay derivable from cumulative budget_snapshot: %s" % diff)
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
