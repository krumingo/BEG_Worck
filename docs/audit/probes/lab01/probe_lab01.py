"""CLAUDE AUDIT probe — #73 LAB-01. Real server.app, ST-01 seed, real Mongo.
Report rows use the "new-style" employee_daily_reports fields the normalizer reads (worker_id, date,
project_id, smr_type, hours, status, payroll_status) — the shape the real writers store: NO quantity,
piece rate or line pay type (no code in the repo writes those).
 L1 FG-48: Akord line 40h, approved 120 m2 × 5 → 600; same line 10h → 600 (hours never price akord).
 L2 real-shape akord: profile pay_type Akord, hourly 15, report 8h (no quantity) → amount? DQ?
 L3 no default rate: Hourly profile without hourly_rate → 0 + MISSING_RATE.
 L4 non-approved lines excluded from Pay Run, spent and sync.
 L5 DOWNTIME on its own line.
 L6 Pay Run (GET /pay-runs/generate) earned == Σ project_labor_cost over the person's projects (same period).
    cd <wt73>/backend && PYTHONPATH=. MONGO_URL=... python <this>
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
from app.services.labor_cost import compute_person_labor, project_labor_cost  # noqa
PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
def check(c, label):
    print(("ok   " if c else "FAIL ") + label)
    if not c: F.append(label)

ak = {"id": "r1", "status": "APPROVED", "date": "2026-11-02", "project_id": "p", "worker_id": "w",
      "pay_type": "Akord", "approved_quantity": 120, "piece_rate": 5, "unit": "m2"}
# LAB-01-B (FG-64): line-level pay_type / piece_rate / approved_quantity are ignored; terms come from the
# package (labor_pay_type Akord, labor_piece_rate 5) and an approval record (approver != worker).
try:   # LAB-01-D (FG-72): approvals keyed by (report, entry, version)
    from app.services.labor_cost import approval_key as _ak
    _qkey = _ak("r1", None, 0)
except ImportError:
    _qkey = "r1"
TERMS = {"packages": {"pkgA": {"id": "pkgA", "project_id": "p", "labor_pay_type": "Akord", "labor_piece_rate": 5}},
         "quantities": {_qkey: {"report_id": "r1", "approved_quantity": 120, "status": "approved", "approved_by": "boss",
                               "execution_package_id": "pkgA"}}}
ak = dict(ak, execution_package_id="pkgA")
r40 = compute_person_labor({"hourly_rate": 15, "pay_type": "Hourly"}, [dict(ak, hours=40)], TERMS)
r10 = compute_person_labor({"hourly_rate": 15, "pay_type": "Hourly"}, [dict(ak, hours=10)], TERMS)
check(r40["total"] == 600 and r10["total"] == 600, "L1 FG-48 akord 40h→%s, 10h→%s (expect 600/600)" % (r40["total"], r10["total"]))
real = {"id": "r2", "status": "APPROVED", "date": "2026-11-02", "project_id": "p", "worker_id": "w", "hours": 8, "smr_type": "Мазилка"}
r2 = compute_person_labor({"hourly_rate": 15, "pay_type": "Akord"}, [real])
print("L2 real-shape akord (profile Akord, 8h, no quantity) → total %s, dq %s" % (r2["total"], [d["code"] for d in r2["dq_warnings"]]))
r3 = compute_person_labor({"pay_type": "Hourly"}, [dict(real, id="r3")])
check(r3["total"] == 0 and any(d["code"] == "MISSING_RATE" for d in r3["dq_warnings"]), "L3 Hourly without rate → %s dq %s" % (r3["total"], [d["code"] for d in r3["dq_warnings"]]))

with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"])); op = c[os.environ["DB_NAME"]]
    q = lambda f: tc.portal.call(f)
    rep = q(lambda: seed_mod.seed(op, c[os.environ["BEG_SYSTEM_DB"]], PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}; org = A["tenant_id"]
    H = {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U["admin"]["email"], "password": PW}).json()["token"]}
    p1 = A["project_id"]; p2 = "p2-" + sfx
    q(lambda: op.projects.insert_one({"id": p2, "org_id": org, "code": "P2", "name": "P2", "status": "Active"}))
    w = U["technician"]["id"]
    q(lambda: op.employee_profiles.update_one({"user_id": w}, {"$set": {"org_id": org, "user_id": w, "pay_type": "Daily", "daily_rate": 120, "hourly_rate": 15}}, upsert=True))
    rows = [("2026-11-02", p1, "Мазилка", 8, "APPROVED", None), ("2026-11-03", p1, "Мазилка", 4, "APPROVED", None),
            ("2026-11-03", p2, "Шпакловка", 4, "APPROVED", None), ("2026-11-04", p2, "Шпакловка", 8, "SUBMITTED", None),
            ("2026-11-05", p1, "Мазилка", 6, "APPROVED", "DOWNTIME")]
    for d, p, smr, h, st, ct in rows:
        doc = {"id": str(uuid.uuid4()), "org_id": org, "worker_id": w, "date": d, "project_id": p, "smr_type": smr,
               "hours": h, "status": st, "payroll_status": "none", "created_at": d}
        if ct: doc["cost_type"] = ct
        q(lambda: op.employee_daily_reports.insert_one(doc))
    r = tc.get("/api/pay-runs/generate?period_start=2026-11-01&period_end=2026-11-30", headers=H)
    row = next((x for x in (r.json().get("rows") or r.json().get("employees") or []) if x.get("employee_id") == w or x.get("user_id") == w), None) if r.status_code == 200 else None
    earned = (row or {}).get("earned_amount")
    s1 = q(lambda: project_labor_cost(org, p1, "2026-11-01", "2026-11-30")); s2 = q(lambda: project_labor_cost(org, p2, "2026-11-01", "2026-11-30"))
    print("pay run:", r.status_code, "earned", earned, "downtime", (row or {}).get("downtime_amount"), "dq", [d["code"] for d in (row or {}).get("labor_dq_warnings", [])])
    print("spent P1", s1["total"], "(labor", s1["labor_total"], "downtime", s1["downtime_total"], ") P2", s2["total"])
    check(earned is not None and abs(earned - (s1["total"] + s2["total"])) < 0.005, "L6 Pay Run earned %s == spent P1+P2 %s" % (earned, round(s1["total"] + s2["total"], 2)))
    check(earned == 360.0, "L4 only approved days count: 3 approved days × 120 = 360 (got %s); SUBMITTED day excluded" % earned)
    check(s1["downtime_total"] == 120.0 and s1["labor_total"] == 180.0, "L5 DOWNTIME apart on P1: labor %s downtime %s" % (s1["labor_total"], s1["downtime_total"]))
    q(lambda: c.drop_database(os.environ["DB_NAME"])); q(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
