"""CLAUDE AUDIT probe — #71 FG-63: SiteManager budget views over a NARROW date window holding ONE worker.
Seeds 2 workers on 2 different days (work_sessions + approved daily reports), then the member SiteManager
asks expected-actual / centralized-reports/activities for ONE day (only worker 1). Any non-null money figure
for that window = that worker's pay. Also the full window (2 workers) for contrast.
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
MONEY = ("cost", "spent", "amount", "value", "pay", "price", "total_labor")

def money_vals(v, path="", out=None):
    out = [] if out is None else out
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, (int, float)) and not isinstance(x, bool) and x and any(m in k.lower() for m in MONEY):
                out.append("%s.%s=%s" % (path, k, x))
            else:
                money_vals(x, path + "." + k, out)
    elif isinstance(v, list):
        for x in v: money_vals(x, path + "[]", out)
    return out

with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    tok = lambda k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
    Hadm, Hsm = tok("admin"), tok("requester")
    tc.post("/api/projects/%s/team" % A["project_id"], json={"user_id": U["requester"]["id"], "role_in_project": "SiteManager"}, headers=Hadm)
    org, p1 = A["tenant_id"], A["project_id"]
    w1, w2 = U["technician"]["id"], U["driver"]["id"]
    q(lambda: op.activity_budgets.insert_one({"id": "ab-" + sfx, "org_id": org, "project_id": p1, "type": "Мазилка", "labor_budget": 5000, "coefficient": 1}))
    seed = ((w1, "2026-11-02", 200.0), (w2, "2026-11-03", 210.0))
    if os.environ.get("PROBE_SINGLE") == "1":
        seed = seed[:1]
    if os.environ.get("PROBE_ZERO") == "1":     # FG-74: a second worker with ZERO pay must not unlock the 2+ rule
        seed = (seed[0], (w2, "2026-11-03", 0.0))
    for wid, day, cost in seed:
        q(lambda: op.work_sessions.insert_one({"id": str(uuid.uuid4()), "org_id": org, "worker_id": wid, "site_id": p1, "smr_type_id": "Мазилка",
            "started_at": day + "T07:00:00", "ended_at": day + "T15:00:00", "duration_hours": 8, "labor_cost": cost, "created_at": day}))
        q(lambda: op.employee_daily_reports.insert_one({"id": str(uuid.uuid4()), "org_id": org, "worker_id": wid, "date": day, "project_id": p1,
            "smr_type": "Мазилка", "hours": 8, "status": "APPROVED", "payroll_status": "none", "created_at": day}))
        q(lambda: op.employee_profiles.update_one({"user_id": wid}, {"$set": {"org_id": org, "user_id": wid, "pay_type": "Hourly", "hourly_rate": cost / 8}}, upsert=True))
    for label, rng in (("ONE day / one worker", "date_from=2026-11-02&date_to=2026-11-02"), ("both days / two workers", "date_from=2026-11-01&date_to=2026-11-30")):
        for path in ("/api/projects/%s/expected-actual" % p1, "/api/projects/%s/centralized-reports/activities" % p1):
            r = tc.get(path + "?" + rng, headers=Hsm)
            mv = money_vals(r.json()) if r.status_code == 200 else []
            print("%-24s %-52s → %s money %s" % (label, path.split(p1)[1], r.status_code, mv[:6]))
            if label.startswith("ONE") and mv: F.append("narrow window exposes money on %s: %s" % (path.split(p1)[1], mv[:3]))
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
