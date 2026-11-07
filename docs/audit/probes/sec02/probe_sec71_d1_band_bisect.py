"""CLAUDE AUDIT probe — #71 5af530e, SEC-02-G-D1: the Technical Manager keeps
budget_snapshot.status (on_track <= 80 % < warning <= 100 % < over_budget) of a generated
site pulse. He can also upsert the site's activity budget (can_manage_project) and generate
a pulse. Bisection on the budget -> the site's cumulative labor spent, which R31 hides on a
one-paid-worker site (spent is withheld from him on the pulse since SEC-02-E).
Uses the PR's own SEC-02 fixture (P1: one paid technician). Real Mongo RS, 3 modes.
    cd <wt71>/backend && PYTHONPATH=. W0_03_REAL_MONGO_URL=... python <this>
"""
import os, sys, uuid, importlib.util
sfx = uuid.uuid4().hex[:10]
os.environ.update(DB_NAME="sec02_op_" + sfx, BEG_SYSTEM_DB="sec02_sys_" + sfx, ENV="test",
                  JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
URL = os.environ["W0_03_REAL_MONGO_URL"]; os.environ.setdefault("MONGO_URL", URL)
spec = importlib.util.spec_from_file_location("sec02_t", "tests/test_sec_02_finance_read.py")
T = importlib.util.module_from_spec(spec); sys.modules["sec02_t"] = T; spec.loader.exec_module(T)
import server  # noqa
from fastapi.testclient import TestClient  # noqa
pm, c02 = T._pm01(), T._c02()
app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
F = []
with TestClient(app, raise_server_exceptions=False) as tc:
    q = lambda f: tc.portal.call(f)
    client = q(lambda: pm._make_client(URL)); op = client[os.environ["DB_NAME"]]
    rep = q(lambda: pm._load_seed().seed(op, client[os.environ["BEG_SYSTEM_DB"]], T.SYNTH_PASSWORD))
    fx = {t["key"]: {"tenant_id": t["tenant_id"], "project_id": t["project_id"], "project2_id": t.get("project2_id"),
                     "warehouse_id": t.get("warehouse_id"), "users": {u["key"]: u for u in t["users"]}} for t in rep["tenants"]}
    q(lambda: pm.seed_existing_records(op, fx)); q(lambda: c02.seed_c02_records(op, fx)); q(lambda: T.seed_sec02_records(op, fx))
    tok = {k: tc.post("/api/auth/login", json={"email": fx["A"]["users"][k]["email"], "password": T.SYNTH_PASSWORD}).json()["token"]
           for k in ("admin", "requester")}
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    for ukey, rip in c02.TEAM:
        tc.post("/api/projects/%s/team" % fx["A"]["project_id"], json={"user_id": fx["A"]["users"][ukey]["id"], "role_in_project": rip},
                headers={"Authorization": "Bearer " + tok["admin"]})
    P1 = fx["A"]["project_id"]; H = {"Authorization": "Bearer " + tok["requester"]}
    actual = sum(float(s.get("labor_cost") or 0) for s in q(lambda: op.work_sessions.find(
        {"site_id": P1, "ended_at": {"$ne": None}}, {"_id": 0, "labor_cost": 1}).to_list(None)))
    paid = {s["worker_id"] for s in q(lambda: op.work_sessions.find({"site_id": P1, "labor_cost": {"$gt": 0}}, {"_id": 0, "worker_id": 1}).to_list(None))}
    for mode in T.MODES:
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        others = sum(float(b.get("labor_budget") or 0) for b in q(lambda: op.activity_budgets.find(
            {"project_id": P1, "type": {"$ne": "AuditProbe"}}, {"_id": 0, "labor_budget": 1}).to_list(None)))
        lo, hi, steps, seen = 0.0, 100000.0, 0, set()
        first = None
        while hi - lo > 0.05 and steps < 40:
            mid = (lo + hi) / 2
            b = tc.post("/api/projects/%s/activity-budgets" % P1, headers=H,
                        json={"type": "AuditProbe", "subtype": "", "labor_budget": max(mid - others, 0.0), "materials_budget": 0})
            g = tc.post("/api/sites/%s/pulse/generate" % P1, params={"date": "2026-11-06"}, headers=H)
            if first is None:
                first = (b.status_code, g.status_code, (g.json() if g.status_code == 200 else g.text)
                         if g.status_code != 200 else g.json().get("budget_snapshot"))
            if b.status_code not in (200, 201) or g.status_code != 200:
                break
            st = (g.json().get("budget_snapshot") or {}).get("status"); seen.add(st)
            if st == "over_budget":
                lo = mid
            else:
                hi = mid
            steps += 1
        derived = round((lo + hi) / 2, 2)
        print("%s: first answer %s | steps %d statuses %s | derived spent %.2f vs actual %.2f (paid workers on P1: %d)"
              % (mode, first, steps, sorted(map(str, seen)), derived, actual, len(paid)))
        if steps >= 10 and abs(derived - actual) <= max(5.0, 0.001 * actual):   # burn_pct is rounded to 0.1 %
            F.append("%s: TM derives the site's cumulative labor spent %.2f (actual %.2f) in %d budget edits" % (mode, derived, actual, steps))
    # ── /alarms path (#71 02a1441, FG-111): an Admin-made budget rule ("> 100 %"); the TM
    # moves the budget, POSTs /alarms/evaluate, sees whether an event for P1 fires (the
    # stripped list still lists it), resolves it (no role check) and repeats.
    HA = {"Authorization": "Bearer " + tok["admin"]}
    rr = tc.post("/api/alarm-rules", headers=HA, json={"name": "Бюджет 100", "type": "budget", "severity": "critical",
                 "condition": {"metric": "burn_pct", "operator": ">", "threshold": 100}, "cooldown_hours": 24})
    rules_seen = tc.get("/api/alarm-rules", headers=H).json()
    thr_visible = any((r.get("condition") or {}).get("threshold") == 100 for r in rules_seen.get("items", []))
    for mode in T.MODES:
        os.environ["PERMISSION_SERVICE_MODE"] = mode
        others = sum(float(b.get("labor_budget") or 0) for b in q(lambda: op.activity_budgets.find(
            {"project_id": P1, "type": {"$ne": "AuditProbe"}}, {"_id": 0, "labor_budget": 1}).to_list(None)))
        lo, hi, steps, first = 0.0, 100000.0, 0, None
        while hi - lo > 0.05 and steps < 40:
            mid = (lo + hi) / 2
            tc.post("/api/projects/%s/activity-budgets" % P1, headers=H,
                    json={"type": "AuditProbe", "subtype": "", "labor_budget": max(mid - others, 0.0), "materials_budget": 0})
            ev = tc.post("/api/alarms/evaluate", headers=H)
            lst = tc.get("/api/alarms", params={"site_id": P1}, headers=H)
            if first is None:
                first = (rr.status_code, ev.status_code, lst.status_code, "threshold visible to TM" if thr_visible else "threshold hidden")
            if ev.status_code != 200 or lst.status_code != 200:
                break
            items = [i for i in (lst.json().get("items") or lst.json().get("data") or []) if i.get("site_id") == P1]
            if items:
                lo = mid
                for i in items:
                    tc.put("/api/alarms/%s/resolve" % i["id"], headers=H, json={"notes": "probe"})
            else:
                hi = mid
            steps += 1
        derived = round((lo + hi) / 2, 2)
        print("%s /alarms: first %s | steps %d | derived spent %.2f vs actual %.2f" % (mode, first, steps, derived, actual))
        if steps >= 10 and abs(derived - actual) <= max(5.0, 0.001 * actual):
            F.append("%s /alarms: TM derives cumulative labor spent %.2f (actual %.2f) via evaluate + resolve" % (mode, derived, actual))
    # ── #71 e90aa5f extras ────────────────────────────────────────────────────────────
    # (e) 404 oracle: a hidden (single-paid-site) alarm id vs a nonexistent id
    os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    tc.post("/api/projects/%s/activity-budgets" % P1, headers=H,
            json={"type": "AuditProbe", "subtype": "", "labor_budget": 1.0, "materials_budget": 0})
    tc.post("/api/alarms/evaluate", headers=HA)                       # admin: creates the event
    hidden = q(lambda: op.alarm_events.find_one({"site_id": P1, "type": "budget", "status": "active"}, {"_id": 0, "id": 1}))
    if hidden:
        for verb, path in (("GET", "/api/alarms/%s"), ("PUT", "/api/alarms/%s/acknowledge"), ("PUT", "/api/alarms/%s/resolve")):
            a = tc.request(verb, path % hidden["id"], headers=H, json={"notes": "x"} if verb == "PUT" else None)
            b = tc.request(verb, path % ("nope-" + uuid.uuid4().hex[:8]), headers=H, json={"notes": "x"} if verb == "PUT" else None)
            same = (a.status_code, a.text) == (b.status_code, b.text)
            print("e90 404-oracle %s %s: hidden %s vs none %s same=%s" % (verb, path, a.status_code, b.status_code, same))
            if not same:
                F.append("404 oracle on %s %s: %s/%s vs %s/%s" % (verb, path, a.status_code, a.text[:60], b.status_code, b.text[:60]))
    # (c) auto_resolve oracle: evaluate's resolved_events count is not filtered
    q(lambda: op.alarm_events.delete_many({}))
    ar = tc.post("/api/alarm-rules", headers=HA, json={"name": "Бюджет AR", "type": "budget", "severity": "critical", "auto_resolve": True,
                 "condition": {"metric": "burn_pct", "operator": ">", "threshold": 100}, "cooldown_hours": 24})
    q(lambda: op.alarm_rules.update_many({"name": "Бюджет 100"}, {"$set": {"is_active": False}}))
    others = sum(float(b.get("labor_budget") or 0) for b in q(lambda: op.activity_budgets.find(
        {"project_id": P1, "type": {"$ne": "AuditProbe"}}, {"_id": 0, "labor_budget": 1}).to_list(None)))
    lo, hi, steps = 0.0, 100000.0, 0
    while hi - lo > 0.05 and steps < 40:
        mid = (lo + hi) / 2
        tc.post("/api/projects/%s/activity-budgets" % P1, headers=H, json={"type": "AuditProbe", "subtype": "", "labor_budget": max(mid - others, 0.0), "materials_budget": 0})
        tc.post("/api/alarms/evaluate", headers=H)                      # fires (hidden) if over
        tc.post("/api/projects/%s/activity-budgets" % P1, headers=H, json={"type": "AuditProbe", "subtype": "", "labor_budget": 10**9, "materials_budget": 0})
        ev = tc.post("/api/alarms/evaluate", headers=H)                 # nothing fires -> auto-resolve
        if ev.status_code != 200:
            break
        if (ev.json().get("resolved_events") or 0) > 0:
            lo = mid
        else:
            hi = mid
        steps += 1
    derived = round((lo + hi) / 2, 2)
    print("e90 auto_resolve oracle: rule %s | steps %d | derived %.2f vs actual %.2f" % (ar.status_code, steps, derived, actual))
    if steps >= 10 and abs(derived - actual) <= max(5.0, 0.001 * actual):
        F.append("auto_resolve oracle: TM derives %.2f (actual %.2f) from evaluate.resolved_events" % (derived, actual))
    q(lambda: op.alarm_rules.update_many({}, {"$set": {"is_active": False}}))
    # (f) #71 bde1728: generic band oracles on other readers — expected-actual (any row status),
    # morning-briefing (+compact): any band-like value that changes as the budget moves
    import json as _json, re as _re
    def band_sig(obj):
        txt = _json.dumps(obj, ensure_ascii=False, sort_keys=True)
        return tuple(sorted(set(_re.findall(r'"(?:status|budget_status|severity|band|level|health)": ?"([a-z_]+)"', txt))))
    for label, path in (("expected-actual", "/api/projects/%s/expected-actual" % P1), ("morning-briefing", "/api/morning-briefing"),
                        ("morning-briefing/compact", "/api/morning-briefing/compact")):
        sigs = set()
        for b in (1.0, 6000.0, 6300.0, 10**7):
            tc.post("/api/projects/%s/activity-budgets" % P1, headers=H, json={"type": "AuditProbe", "subtype": "", "labor_budget": b, "materials_budget": 0})
            r = tc.get(path, headers=H, params={"date": "2026-11-06"} if "morning" in path else None)
            sigs.add((r.status_code, band_sig(r.json()) if r.status_code == 200 else ()))
        varies = len(sigs) > 1
        print("e90 band-varies %s: %s %s" % (label, varies, sorted(sigs)[:4]))
        if varies:
            F.append("%s: a band value changes with the budget on a single-paid site: %s" % (label, sorted(sigs)))
    # (d) known-pay variant: the TM's own paid session makes the site 2-paid; he knows his pay
    me = fx["A"]["users"]["requester"]["id"]
    q(lambda: op.work_sessions.insert_one({"id": "probe-own", "org_id": fx["A"]["tenant_id"], "worker_id": me, "site_id": P1,
        "smr_type_id": "Мазилка", "started_at": "2026-11-05T07:00:00", "ended_at": "2026-11-05T15:00:00",
        "duration_hours": 8, "labor_cost": 500.0, "created_at": "2026-11-05T15:00:00"}))
    own = 500.0
    lo, hi, steps, seen = 0.0, 100000.0, 0, set()
    while hi - lo > 0.05 and steps < 40:
        mid = (lo + hi) / 2
        tc.post("/api/projects/%s/activity-budgets" % P1, headers=H, json={"type": "AuditProbe", "subtype": "", "labor_budget": max(mid - others, 0.0), "materials_budget": 0})
        g = tc.post("/api/sites/%s/pulse/generate" % P1, params={"date": "2026-11-06"}, headers=H)
        st = (g.json().get("budget_snapshot") or {}).get("status") if g.status_code == 200 else None
        seen.add(st)
        if st is None:
            break
        lo, hi = (mid, hi) if st == "over_budget" else (lo, mid)
        steps += 1
    derived_other = round((lo + hi) / 2 - own, 2)
    print("e90 known-pay variant (2 paid: TM 500 + technician): statuses %s steps %d | derived other worker %.2f vs actual %.2f"
          % (sorted(map(str, seen)), steps, derived_other, actual))
    if steps >= 10 and abs(derived_other - actual) <= max(5.0, 0.001 * actual):
        F.append("known-pay variant: TM derives the other worker's pay %.2f (actual %.2f)" % (derived_other, actual))
    q(lambda: client.drop_database(os.environ["DB_NAME"])); q(lambda: client.drop_database(os.environ["BEG_SYSTEM_DB"]))
print("FAILS:", F or "none")
