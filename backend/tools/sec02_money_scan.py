"""SEC-02-B — the audit scanner (claude/audit-log docs/audit/probes/sec02/
probe_sec02_unregistered_money_gets.py) re-run over EVERY GET route, registered or not,
for every non-finance role. Same money regex and same seeds as the audit.

Changes against the audit copy (SEC-02 addendum B: "докажи 0 пари за не-финансови роли"):
  * registered routes are NOT skipped;
  * roles: SiteManager (requester), Technician, Warehousekeeper, Driver, Viewer — the
    P1 team (SiteManager, Technician, Viewer, Driver) is added through the real API as in
    the SEC-02 harness;
  * modes off, shadow, enforce;
  * allowed: the R20 budget view of the Technical Manager on his own project (R20-2B /
    R20-5B routes) — listed separately under "allowed_budget_view", never as a hit.
Output: docs/evidence/SEC-02/scan_sec02b.json ({"hits": {...}, "allowed_budget_view": {...}}).

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
                   r"vat|paid|balance|budget|_value$|^value$|payable|receivable|invoiced|earned|"
                   r"sale|markup|commission)", re.I)   # SEC-02-G: + sale/markup/commission
ROLES = ("requester", "technician", "warehousekeeper", "driver", "viewer")
MODES = ("off", "shadow", "enforce")
OUT = BACKEND.parent / "docs" / "evidence" / "SEC-02" / "scan_sec02b.json"


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
    from app.permissions.finance_read import (by_route, R20_2B, R20_5B, EMPLOYEE_FILE_ACTION,
                                              SCAN_JUDGED_NOT_MONEY, SCAN_OWN_RECORD_PATHS,
                                              budget_view_forbidden)
    reg = by_route()
    budget_view = {p for (m, p), e in reg.items()
                   if e.rule in (R20_2B, R20_5B) and e.action != EMPLOYEE_FILE_ACTION}
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
        routes = sorted({(r.path) for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods})
        results, allowed, judged, own, calls = {}, {}, {}, {}, 0
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ROLES:
                for path in routes:
                    if not path.startswith("/api/"):
                        continue
                    url = path
                    for k, v in vals.items():
                        url = url.replace("{%s}" % k, str(v))
                    if "{" in url:
                        url = re.sub(r"\{[^}]+\}", fx["A"]["project_id"], url)
                    r = tc.get(url, headers={"Authorization": "Bearer " + tok[role]})
                    calls += 1
                    if r.status_code != 200:
                        continue
                    try:
                        hits = money_hits(r.json())
                    except Exception:
                        continue
                    if hits:
                        # SEC-02-G (Codex SEC71-01): the budget view never carries a client
                        # price / sale / margin / profit — such a key is a hit, not "allowed"
                        bad = [h for h in hits
                               if budget_view_forbidden(re.split(r"[.\[\]]+", h.strip(".[]"))[-1])]
                        if role == "requester" and path in budget_view and bad:
                            bucket, hits = results, bad
                        elif role == "requester" and path in budget_view:
                            bucket = allowed
                        elif path in SCAN_JUDGED_NOT_MONEY:
                            bucket = judged
                        elif path in SCAN_OWN_RECORD_PATHS and role == "technician":
                            bucket = own            # {user_id} is the technician himself
                        else:
                            bucket = results
                        bucket.setdefault(path, {})["%s/%s" % (mode, role)] = (
                            sorted(set(hits)) if bucket is allowed else sorted(set(hits))[:8])
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        OUT.write_text(json.dumps({"calls": calls, "roles": list(ROLES), "modes": list(MODES),
                                   "hits": results, "allowed_budget_view": allowed,
                                   "judged_not_money": {p: {"reason": SCAN_JUDGED_NOT_MONEY[p],
                                                            "seen": v} for p, v in judged.items()},
                                   "own_record": own},
                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("calls", calls, "hits", len(results), "allowed_budget_view", len(allowed),
              "judged_not_money", len(judged), "own_record", len(own))


if __name__ == "__main__":
    if "--child" in sys.argv:
        child(sys.argv[sys.argv.index("--child") + 1]); sys.exit(0)
    mongo_url = os.environ.get("W0_03_REAL_MONGO_URL")
    pm = T._pm01(); sfx = uuid.uuid4().hex[:12]
    op, sy = T.DB_PREFIX_OP + sfx, T.DB_PREFIX_SYS + sfx
    env = pm.child_env(mongo_url, op, sy); env["JWT_SECRET"] = "probe-" + uuid.uuid4().hex
    try:
        subprocess.run([sys.executable, __file__, "--child", mongo_url], cwd=str(BACKEND), env=env, timeout=3000, check=True)
    finally:
        import pymongo
        c = pymongo.MongoClient(mongo_url); [c.drop_database(n) for n in (op, sy)]
