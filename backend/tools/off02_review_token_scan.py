"""OFF-02 F-89-01 [P1] (Codex, PR #89) — the review-link scan: EVERY GET route of server.app,
for every non-finance role, in off / shadow / enforce, searched for the offer's bearer review
link (the token value, a ``review_token`` / ``review_url`` key, ``/offers/review/``) in the raw
response body (JSON, PDF, XLSX alike).

The offer of P1 (the SEC-02 seed) is made Sent with a live review link, and a Sent EXTRA offer
with its own link is added (the project dashboard lists the extra offers). A finance role
(owner) is scanned too, as the control that the seeded link is reachable at all.
Output: docs/evidence/OFF-02/scan_review_token.json ({"hits": {...}, "finance_sees": [...]}).
Expected: hits == {} for every non-finance role and mode.

Reuses the SEC-02 harness setup (ST-01 tenants, PM-01/C02/SEC-02 seeds, P1 team via the
real API) exactly as tools/sec02_money_scan.py.

Run:  cd backend && W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27017/?replicaSet=rs0' \
      PYTHONPATH=. python tools/off02_review_token_scan.py
"""
import importlib.util, json, os, re, subprocess, sys, uuid
from pathlib import Path

BACKEND = Path.cwd()
sys.path.insert(0, str(BACKEND))
spec = importlib.util.spec_from_file_location("sec02t", BACKEND / "tests" / "test_sec_02_finance_read.py")
T = importlib.util.module_from_spec(spec); sys.modules["sec02t"] = T; spec.loader.exec_module(T)

ROLES = ("requester", "technician", "warehousekeeper", "driver", "viewer")
CONTROL = ("owner",)
MODES = ("off", "shadow", "enforce")
OUT = BACKEND.parent / "docs" / "evidence" / "OFF-02" / "scan_review_token.json"
MAIN_TOKEN, EXTRA_TOKEN = "f89rt" + "m" * 19, "f89rt" + "x" * 19


def leaks(body: bytes):
    found = []
    for needle in (MAIN_TOKEN, EXTRA_TOKEN, "review_token\"", "review_url", "/offers/review/"):
        if needle.encode() in body:
            found.append(needle.strip('"'))
    return found


def child(mongo_url):
    pm, c02 = T._pm01(), T._c02()
    import server
    from fastapi.testclient import TestClient
    from fastapi.routing import APIRoute
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
        main_id = T.sid("A", "off1")

        async def link():
            await op_db.offers.update_one({"id": main_id}, {"$set": {
                "status": "Sent", "sent_at": "2026-11-06T09:00:00+00:00",
                "review_token": MAIN_TOKEN, "review_token_version": 1}})
            doc = await op_db.offers.find_one({"id": main_id}, {"_id": 0})
            await op_db.offers.insert_one(dict(doc, id=T.sid("A", "offx"), offer_no="SEC02-X",
                                               offer_type="extra", review_token=EXTRA_TOKEN))
        tc.portal.call(link)
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
                     "employee_id": fx["A"]["users"]["technician"]["id"], "id": fx["A"]["project_id"],
                     "offer_id": main_id})
        routes = sorted({(r.path) for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods})
        hits, finance, ok200, calls = {}, set(), {}, 0
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ROLES + CONTROL:
                for path in routes:
                    if not path.startswith("/api/") or path.startswith("/api/offers/review/"):
                        continue                 # the public client link itself
                    url = path
                    for k, v in vals.items():
                        url = url.replace("{%s}" % k, str(v))
                    if "{" in url:
                        url = re.sub(r"\{[^}]+\}", fx["A"]["project_id"], url)
                    r = tc.get(url, headers={"Authorization": "Bearer " + tok[role]})
                    calls += 1
                    if r.status_code != 200:
                        continue
                    found = leaks(r.content)
                    if role in CONTROL:
                        if found:
                            finance.add(path)
                        continue
                    ok200[role] = ok200.get(role, 0) + 1
                    if found:
                        hits.setdefault(path, {})["%s/%s" % (mode, role)] = found
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"calls": calls, "roles": list(ROLES), "control": list(CONTROL),
                                   "modes": list(MODES), "get_routes": len(routes),
                                   "answered_200_per_role_all_modes": ok200,
                                   "hits": hits, "finance_sees": sorted(finance)},
                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("calls", calls, "hits", len(hits), "finance_sees", len(finance), sorted(finance))


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
