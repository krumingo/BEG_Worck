"""CLAUDE AUDIT probe SEC-01-C01 (#69): R16 member-project rule edge cases, real server.app, 3 modes.

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
R1  Technician added to A's project by Admin with to_date = YESTERDAY (membership ended) → labor entry /
    material waste on that project must be 403 in every mode (and the three modes must agree).
R2  SiteManager (not a member) tries to add himself to the project team → 403 (no self-escalation).
R3  Technician member of A's project posts a labor entry WITHOUT project_id → not 201.
"""
import os, sys, uuid
from datetime import date, timedelta
from pathlib import Path

sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
sys.path.insert(0, str(Path.cwd().parent / "ops" / "staging"))
import seed_synthetic as seed_mod  # noqa
import server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa

PW = "Probe-Synthetic-Pass-2026!"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
res, fails = {}, []
with TestClient(app, raise_server_exceptions=False) as tc:
    cli = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"]))
    op, sysdb = cli[os.environ["DB_NAME"]], cli[os.environ["BEG_SYSTEM_DB"]]
    rep = tc.portal.call(lambda: seed_mod.seed(op, sysdb, PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    tok = {k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
           for k in ("admin", "technician", "requester")}
    pid = A["project_id"]
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"     # add through the real API so the RA mirror exists
    r = tc.post("/api/projects/%s/team" % pid, json={"user_id": U["technician"]["id"], "role_in_project": "Technician",
                "from_date": "2026-01-01", "to_date": yesterday}, headers=tok["admin"])
    print("setup add ended technician:", r.status_code, r.text[:120])
    for mode in ("off", "shadow", "enforce"):
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        a = tc.post("/api/labor-entries", json={"project_id": pid, "hours": 1, "activity_name": "probe"}, headers=tok["technician"]).status_code
        b = tc.post("/api/projects/%s/material-waste" % pid, json={"material_name": "probe", "qty": 1}, headers=tok["technician"]).status_code
        c = tc.post("/api/projects/%s/team" % pid, json={"user_id": U["requester"]["id"], "role_in_project": "SiteManager"},
                    headers=tok["requester"]).status_code
        d = tc.post("/api/labor-entries", json={"hours": 1, "activity_name": "probe"}, headers=tok["technician"]).status_code
        res[mode] = (a, b, c, d)
        print("%-7s R1 ended-member labor=%s waste=%s | R2 SM self-add=%s | R3 no project_id=%s" % (mode, a, b, c, d))
        if a < 300 or b < 300: fails.append("R1-" + mode)
        if c < 300: fails.append("R2-" + mode)
        if d < 300: fails.append("R3-" + mode)
    if len({v[:2] for v in res.values()}) > 1:
        fails.append("R1-modes-disagree %s" % {m: v[:2] for m, v in res.items()})
    # SEC-R1 boundaries (added for 471eaaa): to_date = today → member; from_date = tomorrow → not; from_date = today → member
    today = date.today().isoformat(); tomorrow = (date.today() + timedelta(days=1)).isoformat()
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    for k in ("driver",):
        pass
    tok2 = {k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
            for k in ("accountant",)}
    tc.portal.call(lambda: op["project_team"].update_many({"user_id": U["technician"]["id"]}, {"$set": {"active": False}}))
    cases = [("to_date=today", {"from_date": "2026-01-01", "to_date": today}, True),
             ("from_date=tomorrow", {"from_date": tomorrow}, False),
             ("from_date=today", {"from_date": today}, True)]
    for name, dates, expect_ok in cases:
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        tc.portal.call(lambda: op["project_team"].update_many({"user_id": U["technician"]["id"]}, {"$set": {"active": False}}))
        r = tc.post("/api/projects/%s/team" % pid, json=dict({"user_id": U["technician"]["id"], "role_in_project": "Technician"}, **dates),
                    headers=tok["admin"])
        for mode in ("off", "shadow", "enforce"):
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            st = tc.post("/api/labor-entries", json={"project_id": pid, "hours": 1, "activity_name": "b"}, headers=tok["technician"]).status_code
            ok = st < 300
            print("R1b %-18s add=%s %-7s labor=%s" % (name, r.status_code, mode, st))
            if ok != expect_ok: fails.append("R1b %s %s %s" % (name, mode, st))
    rows = tc.portal.call(lambda: op["project_team"].count_documents({"user_id": U["technician"]["id"], "project_id": pid}))
    print("R4 membership rows for the technician on the project after re-adds:", rows)
    tc.portal.call(lambda: cli.drop_database(os.environ["DB_NAME"])); tc.portal.call(lambda: cli.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
