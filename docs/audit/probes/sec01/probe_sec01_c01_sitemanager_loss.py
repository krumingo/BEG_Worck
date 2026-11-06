"""CLAUDE AUDIT probe SEC-01-C01 (#69): what SiteManager actually loses on projects (implementer's claim:
client create/change). Real server.app, 3 modes. SiteManager = fixture 'requester', made a SiteManager
member of A's project by Admin (so can_manage_project is true).

  create project without owner           → expect 201 (kept)
  create project with owner_type/owner_id → expect 403 (lost, R14)
  PUT project: change owner_id            → expect 403 (lost)
  PUT project: same owner_id + new name   → expect 200 (kept: unchanged value passes)
  PUT project: name only                  → expect 200 (kept)
"""
import os, sys, uuid
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
with TestClient(app, raise_server_exceptions=False) as tc:
    cli = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"]))
    op, sysdb = cli[os.environ["DB_NAME"]], cli[os.environ["BEG_SYSTEM_DB"]]
    rep = tc.portal.call(lambda: seed_mod.seed(op, sysdb, PW))
    A = next(t for t in rep["tenants"] if t["key"] == "A"); U = {u["key"]: u for u in A["users"]}
    tok = {k: {"Authorization": "Bearer " + tc.post("/api/auth/login", json={"email": U[k]["email"], "password": PW}).json()["token"]}
           for k in ("admin", "requester")}
    pid = A["project_id"]
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    print("setup SM member:", tc.post("/api/projects/%s/team" % pid, json={"user_id": U["requester"]["id"],
          "role_in_project": "SiteManager"}, headers=tok["admin"]).status_code)
    print("setup owner:", tc.put("/api/projects/%s" % pid, json={"owner_type": "company", "owner_id": "c-1"},
          headers=tok["admin"]).status_code)
    for mode in ("off", "shadow", "enforce"):
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        n = uuid.uuid4().hex[:5]
        r = [tc.post("/api/projects", json={"code": "P" + n, "name": "x" + n, "status": "Active"}, headers=tok["requester"]).status_code,
             tc.post("/api/projects", json={"code": "Q" + n, "name": "y" + n, "status": "Active", "owner_type": "company",
                     "owner_id": "c-2"}, headers=tok["requester"]).status_code,
             tc.put("/api/projects/%s" % pid, json={"owner_id": "c-3"}, headers=tok["requester"]).status_code,
             tc.put("/api/projects/%s" % pid, json={"owner_id": "c-1", "name": "renamed" + n}, headers=tok["requester"]).status_code,
             tc.put("/api/projects/%s" % pid, json={"name": "renamed2" + n}, headers=tok["requester"]).status_code]
        print("%-7s create=%s create+owner=%s change_owner=%s same_owner+name=%s name_only=%s" % ((mode,) + tuple(r)))
    tc.portal.call(lambda: cli.drop_database(os.environ["DB_NAME"])); tc.portal.call(lambda: cli.drop_database(os.environ["BEG_SYSTEM_DB"]))
