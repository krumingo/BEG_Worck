"""AUDIT-2 independent probes for #92 PWA-02 (offline sync): crash-retry idempotency of the
daily report, concurrent same key, cross-tenant project / device / console ids.
Runs the whole app on a disposable local Mongo, reusing tests/test_pwa_02_offline_sync.py's
seed / login / envelope helpers. Copy into backend/tests to run."""
from __future__ import annotations
import importlib.util, json, os, subprocess, sys, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent


def _pwa():
    spec = importlib.util.spec_from_file_location("pwa02_main", HERE / "test_pwa_02_offline_sync.py")
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
    return m


def child(mongo_url, out):
    P = _pwa(); pm = P._pm01()
    import server
    from fastapi.testclient import TestClient
    from app.services import offline_sync as sync
    from app.services import offline_sync_handlers as H
    import app.routes.attendance as attendance_routes
    attendance_routes.now_hour = lambda: 7
    app = server.app; app.router.on_startup.clear(); app.router.on_shutdown.clear()
    seed_mod = pm._load_seed(); op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    obs = {}
    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url)); op = client[op_name]
        rep = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name], P.SYNTH_PASSWORD))
        tc.portal.call(lambda: sync.ensure_sync_indexes(op))
        for n in ("audit_events", "audit_logs"):
            if n not in tc.portal.call(op.list_collection_names):
                tc.portal.call(lambda: op.create_collection(n))
        fx = {t["key"]: {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                         "users": {u["key"]: u for u in t["users"]}} for t in rep["tenants"]}
        tok = {}
        for tk in ("A", "B"):
            for k in ("owner", "admin", "technician"):
                r = tc.post("/api/auth/login", json={"email": fx[tk]["users"][k]["email"], "password": P.SYNTH_PASSWORD})
                tok[(tk, k)] = r.json()["token"]
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        q = lambda fn: tc.portal.call(fn)
        def call(m, url, role="technician", tk="A", key=None, **kw):
            h = {"Authorization": "Bearer " + tok[(tk, role)]}
            if key: h["Idempotency-Key"] = key
            r = tc.request(m, url, headers=h, **kw)
            try: b = r.json()
            except Exception: b = r.text[:200]
            return {"status": r.status_code, "body": b}
        A, B = fx["A"], fx["B"]; tech = A["users"]["technician"]; techB = B["users"]["technician"]
        for tk in ("A", "B"):   # flag on in both tenants (platform admin), devices registered
            q(lambda tk=tk: op.users.update_one({"id": fx[tk]["users"]["owner"]["id"]}, {"$set": {"is_platform_admin": True}}))
        for tk, dev in (("A", P.DEVICE_A), ("B", P.DEVICE_A2)):
            call("PUT", "/api/sync/flag", role="owner", tk=tk, json={"enabled": True})
            call("POST", "/api/sync/devices/register", tk=tk, json={"device_id": dev, "label": "p"})
        batch = lambda items, tk="A", dev=P.DEVICE_A: call("POST", "/api/sync/batch", tk=tk, json={"device_id": dev, "items": items})
        today = datetime.now(timezone.utc)

        # S1 — crash AFTER the domain write of a daily report, BEFORE its sync_local_id tag
        obs["S1_att"] = batch([P.envelope(tech["id"], A["tenant_id"], "attendance.mark",
                                          {"status": "Present", "project_id": A["project_id"]})])["body"]["results"][0]["status"]
        e = P.envelope(tech["id"], A["tenant_id"], "technician.daily_report",
                       {"project_id": A["project_id"], "entries": [{"smr_type": "Шпакловка", "hours": 4}]})
        # crash AFTER the handler committed the report, BEFORE the receipt is finished:
        # the first sync.item_synced AuditEvent raises (the post-write window).
        real_audit = sync.audit; state = {"n": 0}
        async def crashing(user, **kw):
            if kw.get("action") == "sync.item_synced" and state["n"] == 0:
                state["n"] += 1
                raise RuntimeError("audit probe: crash after the domain write")
            return await real_audit(user, **kw)
        sync.audit = crashing
        first = batch([e])
        sync.audit = real_audit
        q(lambda: op.sync_receipts.update_one({"idempotency_key": e["idempotency_key"]},
                                              {"$set": {"received_at": (today - timedelta(minutes=5)).isoformat()}}))
        second = batch([e])
        rows = q(lambda: op.employee_daily_reports.find({"org_id": A["tenant_id"], "worker_id": tech["id"]},
                                                        {"_id": 0, "id": 1, "sync_local_id": 1, "date": 1}).to_list(None))
        obs["S1"] = {"first_status": first["status"], "first_body": first["body"], "second": second["body"],
                     "receipt": q(lambda: op.sync_receipts.find_one({"idempotency_key": e["idempotency_key"]}, {"_id": 0, "status": 1, "result": 1})),
                     "daily_report_rows": len(rows), "tagged": sum(1 for r in rows if r.get("sync_local_id"))}

        # S2 — attendance into ANOTHER tenant's project
        own = A["users"]["admin"]
        call("POST", "/api/sync/devices/register", role="admin", json={"device_id": P.DEVICE_A, "label": "p"})
        e2 = P.envelope(own["id"], A["tenant_id"], "attendance.mark", {"status": "Present", "project_id": B["project_id"]})
        r2 = call("POST", "/api/sync/batch", role="admin", json={"device_id": P.DEVICE_A, "items": [e2]})["body"]["results"][0]
        obs["S2"] = {"result": r2, "rows": q(lambda: op.attendance_entries.count_documents({"project_id": B["project_id"], "user_id": own["id"]}))}
        # S3 — daily report into ANOTHER tenant's project (fresh technician day: use tenant B's technician into A's project)
        e3 = P.envelope(techB["id"], B["tenant_id"], "technician.daily_report",
                        {"project_id": A["project_id"], "entries": [{"smr_type": "Боя", "hours": 2}]}, device_id=P.DEVICE_A2)
        r3 = batch([e3], tk="B", dev=P.DEVICE_A2)["body"]["results"][0]
        obs["S3"] = {"result": r3, "rows": q(lambda: op.employee_daily_reports.count_documents({"worker_id": techB["id"], "project_id": A["project_id"]}))}
        # S4 — tenant B syncing through tenant A's device id
        r4 = call("POST", "/api/sync/batch", tk="B", json={"device_id": P.DEVICE_A, "items": [
            P.envelope(techB["id"], B["tenant_id"], "attendance.mark", {"status": "Present", "project_id": B["project_id"]})]})
        obs["S4"] = {"status": r4["status"], "body": r4["body"]}
        # S5 — tenant B admin acting on tenant A's device / conflict / late ids
        conf = q(lambda: op.sync_conflicts.find_one({"org_id": A["tenant_id"]}, {"_id": 0, "id": 1}))
        obs["S5"] = {
            "revoke_A_device_as_B": call("POST", "/api/sync/devices/%s/revoke" % P.DEVICE_A, role="admin", tk="B",
                                         key=str(uuid.uuid4()), json={"reason": "probe"})["status"],
            "A_device_revoked": q(lambda: op.sync_devices.find_one({"org_id": A["tenant_id"], "id": P.DEVICE_A}, {"_id": 0, "revoked_at": 1})),
            "console_B_devices": [d.get("id") for d in call("GET", "/api/sync/console", role="admin", tk="B")["body"].get("devices", [])],
        }
        # S6 — the same new key sent twice in parallel (attendance, fresh day for B's tech)
        e6 = P.envelope(techB["id"], B["tenant_id"], "attendance.mark", {"status": "Present", "project_id": B["project_id"]}, device_id=P.DEVICE_A2)
        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda _: batch([e6], tk="B", dev=P.DEVICE_A2), range(2)))
        obs["S6"] = {"statuses": [r["body"]["results"][0]["status"] if isinstance(r["body"], dict) and "results" in r["body"] else r["status"] for r in res],
                     "rows": q(lambda: op.attendance_entries.count_documents({"user_id": techB["id"]})),
                     "receipts": q(lambda: op.sync_receipts.count_documents({"idempotency_key": e6["idempotency_key"]}))}
        # S7 — the same record (local_id) under two keys, in parallel: the unique backstop
        lid = str(uuid.uuid4())
        e7 = [P.envelope(techB["id"], B["tenant_id"], "technician.daily_report",
                         {"project_id": B["project_id"], "entries": [{"smr_type": "Боя", "hours": 3}]},
                         device_id=P.DEVICE_A2, local_id=lid) for _ in range(2)]
        with ThreadPoolExecutor(2) as ex:
            res7 = list(ex.map(lambda e: batch([e], tk="B", dev=P.DEVICE_A2), e7))
        obs["S7"] = {"statuses": [r["body"]["results"][0]["status"] if isinstance(r["body"], dict) and "results" in r["body"] else r["status"] for r in res7],
                     "rows": q(lambda: op.employee_daily_reports.count_documents({"sync_local_id": lid}))}
    Path(out).write_text(json.dumps(obs, ensure_ascii=False, default=str, indent=1), encoding="utf-8")


def test_probe_pwa02(tmp_path):
    url = os.environ.get("W0_03_REAL_MONGO_URL")
    if not url: pytest.skip("no real mongo")
    P = _pwa(); pm = P._pm01(); sfx = uuid.uuid4().hex[:12]
    opn, sysn = P.DB_PREFIX_OP + sfx, P.DB_PREFIX_SYS + sfx
    env = pm.child_env(url, opn, sysn); env["JWT_SECRET"] = "probe-" + uuid.uuid4().hex
    out = tmp_path / "o.json"
    try:
        subprocess.run([sys.executable, __file__, url, str(out)], cwd=str(BACKEND), check=True, env=env, timeout=900)
    finally:
        import pymongo; c = pymongo.MongoClient(url); c.drop_database(opn); c.drop_database(sysn)
    o = json.loads(out.read_text(encoding="utf-8")); print("PROBE", json.dumps(o, ensure_ascii=False))
    assert o["S1"]["daily_report_rows"] <= 1, o["S1"]          # crash-retry must not write twice
    assert o["S3"]["rows"] == 0, o["S3"]   # S2 (foreign project id on attendance) = main debt, recorded
    assert o["S4"]["status"] == 409, o["S4"]
    assert o["S5"]["revoke_A_device_as_B"] == 404 and not (o["S5"]["A_device_revoked"] or {}).get("revoked_at"), o["S5"]
    assert "0d6f6a2e-7b1c-4c55-9d1e-1a2b3c4d5e6f" not in o["S5"]["console_B_devices"], o["S5"]
    assert o["S6"]["rows"] == 1 and o["S6"]["receipts"] == 1, o["S6"]
    if "S7" in o: assert o["S7"]["rows"] <= 1, o["S7"]


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND)); child(sys.argv[1], sys.argv[2])
