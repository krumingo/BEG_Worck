"""CLAUDE AUDIT probes AUTH-02 (#56). Real server.app on scratch DBs (ST-01 seed), real JWT.

    cd <PR worktree>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this> <worktree>
A1  validate_attribution refuses: blank, whitespace, zero-width only (U+200B), bidi override (U+202E) inside,
    newline/ESC, bcrypt-hash-looking text, over-long text; accepts a normal Cyrillic name + reason.
A2  admin set-password (FG-11): Viewer of A logs in (token T1) and has an open reset link; Owner of A sets
    Viewer's password → T1 now 401, old password 401, new password 200, reset link revoked, audit rows written.
A3  Owner of B cannot set the password of A's Viewer (cross-tenant) → 403/404, A's hash unchanged.
"""
import os, sys, uuid, importlib.util, asyncio
from pathlib import Path
W = sys.argv[1]
SEED = sys.argv[2] if len(sys.argv) > 2 else W
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="pm01_op_" + sfx, BEG_SYSTEM_DB="pm01_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
spec = importlib.util.spec_from_file_location("cli", W + "/backend/scripts/reset_user_password.py")
cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
fails = []
bad = ["", "   ", "​​​", "Ivan ‮Petrov", "Ivan\nPetrov", "Ivan\x1b[31m",
       "$2b$12$abcdefghijklmnopqrstuuJzVb7yHkG1pmJkA0dQ4oGq3aQz5c1r6", "x" * 5000]
for op in bad:
    try:
        cli.validate_attribution(op, "Owner locked out, ticket 123"); fails.append("A1 operator accepted %r" % op[:20])
    except cli.AttributionInvalid:
        pass
    try:
        cli.validate_attribution("Иван Петров", op); fails.append("A1 reason accepted %r" % op[:20])
    except cli.AttributionInvalid:
        pass
try:
    cli.validate_attribution("Иван Петров", "Собственикът е заключен, тикет 123")
except cli.AttributionInvalid as e:
    fails.append("A1 normal refused: %s" % e)
print("A1 done")

sys.path.insert(0, SEED + "/ops/staging")
import seed_synthetic as seed_mod  # noqa
import server  # noqa
from fastapi.testclient import TestClient  # noqa
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
PW, NEW = "Probe-Synthetic-Pass-2026!", "Brand-New-Pass-2026!x"
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
with TestClient(app, raise_server_exceptions=False) as tc:
    c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"]))
    op, sysdb = c[os.environ["DB_NAME"]], c[os.environ["BEG_SYSTEM_DB"]]
    rep = tc.portal.call(lambda: seed_mod.seed(op, sysdb, PW))
    T = {t["key"]: t for t in rep["tenants"]}
    UA = {u["key"]: u for u in T["A"]["users"]}; UB = {u["key"]: u for u in T["B"]["users"]}
    login = lambda u, p: tc.post("/api/auth/login", json={"email": u["email"], "password": p})
    t1 = login(UA["viewer"], PW).json()["token"]
    ownerA = login(UA["owner"], PW).json()["token"]; ownerB = login(UB["owner"], PW).json()["token"]
    tc.portal.call(lambda: op["password_reset_tokens"].insert_one({
        "id": "tok-1", "org_id": T["A"]["tenant_id"], "user_id": UA["viewer"]["id"], "token_hash": "x" * 64,
        "used_at": None, "delivery_status": "sent"}))
    before_hash = tc.portal.call(lambda: op["users"].find_one({"id": UA["viewer"]["id"]}))["password_hash"]
    r3 = tc.post("/api/admin/set-password/%s" % UA["viewer"]["id"], json={"new_password": NEW},
                 headers={"Authorization": "Bearer " + ownerB})
    after_b = tc.portal.call(lambda: op["users"].find_one({"id": UA["viewer"]["id"]}))["password_hash"]
    print("A3 cross-tenant owner B →", r3.status_code, "hash unchanged:", before_hash == after_b)
    if r3.status_code < 300 or before_hash != after_b: fails.append("A3")
    r = tc.post("/api/admin/set-password/%s" % UA["viewer"]["id"], json={"new_password": NEW},
                headers={"Authorization": "Bearer " + ownerA})
    me = tc.get("/api/auth/me", headers={"Authorization": "Bearer " + t1}).status_code
    old = login(UA["viewer"], PW).status_code; new = login(UA["viewer"], NEW).status_code
    tok = tc.portal.call(lambda: op["password_reset_tokens"].find_one({"id": "tok-1"}))
    audits = tc.portal.call(lambda: op["audit_events"].count_documents({"action": "user.admin_password_reset"}))
    print("A2 set=%s old-session=%s old-pw=%s new-pw=%s link-revoked=%s canonical-audit=%s" % (
        r.status_code, me, old, new, tok.get("revoked_reason"), audits))
    if not (r.status_code == 200 and me == 401 and old == 401 and new == 200 and tok.get("used_at") and audits == 1):
        fails.append("A2")
    tc.portal.call(lambda: c.drop_database(os.environ["DB_NAME"])); tc.portal.call(lambda: c.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", fails or "none")
sys.exit(1 if fails else 0)
