"""CLAUDE AUDIT probe — #71 SEC-02: which GET routes NOT in the finance-read registry
still return money to a non-finance role?

Reuses the SEC-02 harness setup (ST-01 tenants, PM-01/C02/SEC-02 seeds, P1 team via the
real API). Then calls EVERY GET route of server.app as `warehousekeeper` (non-member,
non-finance) and `viewer` (member of P1) in off and enforce, and reports each 200 response
that carries a money-named key with a non-zero number. Output is a candidate list; each hit
must be judged (counts named *total* are noise).

Run:  cd <wt71>/backend && W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \
      PYTHONPATH=. python <this>
"""
import importlib.util, json, os, re, subprocess, sys, uuid
from pathlib import Path

BACKEND = Path.cwd()
sys.path.insert(0, str(BACKEND))
spec = importlib.util.spec_from_file_location("sec02t", BACKEND / "tests" / "test_sec_02_finance_read.py")
T = importlib.util.module_from_spec(spec); sys.modules["sec02t"] = T; spec.loader.exec_module(T)

MONEY = re.compile(r"(cost|price|amount|salary|wage|profit|margin|revenue|hourly_rate|net_pay|"
                   r"vat|paid|balance|budget|_value$|^value$|payable|receivable|invoiced|earned)", re.I)
ROLES = ("warehousekeeper", "viewer")
MODES = ("off", "enforce")


def money_hits(v, path="", out=None):
    out = [] if out is None else out
    if isinstance(v, dict):
        for k, x in v.items():
            p = path + "." + str(k)
            if isinstance(x, (int, float)) and not isinstance(x, bool) and x != 0 and MONEY.search(str(k)):
                out.append(p)
            else:
                money_hits(x, p, out)
    elif isinstance(v, list):
        for x in v[:20]:
            money_hits(x, path + "[]", out)
    return out


def child(mongo_url):
    pm, c02 = T._pm01(), T._c02()
    import server
    from fastapi.testclient import TestClient
    from fastapi.routing import APIRoute
    from app.permissions.finance_read import by_route
    reg = by_route()
    app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
    seed_mod = pm._load_seed()
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url))
        op_db = client[op_name]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name], T.SYNTH_PASSWORD))
        fx = {}
        for t in report["tenants"]:
            fx[t["key"]] = {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                            "warehouse_id": t.get("warehouse_id"), "users": {u["key"]: u for u in t["users"]}}
        tc.portal.call(lambda: pm.seed_existing_records(op_db, fx))
        tc.portal.call(lambda: c02.seed_c02_records(op_db, fx))
        tc.portal.call(lambda: T.seed_sec02_records(op_db, fx))
        tok = {}
        for key in T.ROLE_KEYS:
            r = tc.post("/api/auth/login", json={"email": fx["A"]["users"][key]["email"], "password": T.SYNTH_PASSWORD})
            tok[key] = r.json()["token"]
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        for ukey, rip in c02.TEAM:
            tc.post("/api/projects/%s/team" % fx["A"]["project_id"], json={"user_id": fx["A"]["users"][ukey]["id"],
                    "role_in_project": rip}, headers={"Authorization": "Bearer " + tok["admin"]})
        vals = T.url_values(fx, "A")
        vals.update({"project_id": fx["A"]["project_id"], "site_id": fx["A"]["project_id"],
                     "employee_id": fx["A"]["users"]["technician"]["id"], "id": fx["A"]["project_id"]})
        METHOD = os.environ.get("PROBE_METHOD", "GET")   # GET (default) or POST / PUT sweep (empty body, scratch DB)
        routes = sorted({(r.path) for r in app.routes if isinstance(r, APIRoute) and METHOD in r.methods})
        results = {}
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ROLES:
                for path in routes:
                    if not path.startswith("/api/") or (METHOD, path) in reg or any(x in path for x in ("/auth/", "/logout", "/signup")):
                        continue
                    url = path
                    for k, v in vals.items():
                        url = url.replace("{%s}" % k, str(v))
                    if "{" in url:
                        url = re.sub(r"\{[^}]+\}", fx["A"]["project_id"], url)
                    hdr = {"Authorization": "Bearer " + tok[role], "Idempotency-Key": "scan-" + uuid.uuid4().hex}
                    r = tc.get(url, headers=hdr) if METHOD == "GET" else tc.request(METHOD, url, json={}, headers=hdr)
                    if r.status_code not in (200, 201):
                        continue
                    try:
                        hits = money_hits(r.json())
                    except Exception:
                        continue
                    if hits:
                        results.setdefault(path, {})["%s/%s" % (mode, role)] = sorted(set(hits))[:8]
        print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if "--child" in sys.argv:
        if len(sys.argv) > sys.argv.index("--child") + 2:
            os.environ["PROBE_METHOD"] = sys.argv[sys.argv.index("--child") + 2]
        child(sys.argv[sys.argv.index("--child") + 1]); sys.exit(0)
    mongo_url = os.environ.get("W0_03_REAL_MONGO_URL")
    pm = T._pm01(); sfx = uuid.uuid4().hex[:12]
    op, sy = T.DB_PREFIX_OP + sfx, T.DB_PREFIX_SYS + sfx
    env = pm.child_env(mongo_url, op, sy); env["JWT_SECRET"] = "probe-" + uuid.uuid4().hex
    try:
        subprocess.run([sys.executable, __file__, "--child", mongo_url, os.environ.get("PROBE_METHOD", "GET")], cwd=str(BACKEND), env=env, timeout=3000, check=True)
    finally:
        import pymongo
        c = pymongo.MongoClient(mongo_url); [c.drop_database(n) for n in (op, sy)]
