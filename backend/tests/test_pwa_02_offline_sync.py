"""
PWA-02 (R61) — offline queue: idempotent sync, late records, conflicts, blocked devices,
the Owner/Admin console, behind the ``offline_queue`` feature flag.

Package: ``docs/architecture/tasks/PWA-02_OFFLINE_QUEUE_SYNC.md`` (branch
``claude/happy-meitner-bmcnel``), decision R61 (``RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md``).

Every scenario runs through the WHOLE application (``server.app``) on a disposable LOCAL
MongoDB replica set (two fresh scratch databases, dropped afterwards), with the ST-01
synthetic tenants A and B, real logins and real JWTs. The child process writes one JSON of
observations; each test below checks one rule against it.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_pwa_02_offline_sync.py -q --noconftest -rs
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
DB_PREFIX_OP, DB_PREFIX_SYS = "pwa02_op_", "pwa02_sys_"
SYNTH_PASSWORD = "PWA02-Synthetic-Pass-2026!"     # synthetic users of a scratch database
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant", "viewer")
DEVICE_A = "0d6f6a2e-7b1c-4c55-9d1e-1a2b3c4d5e6f"
DEVICE_A2 = "1e7a7b3f-8c2d-4d66-8e2f-2b3c4d5e6f70"


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "pwa02_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def envelope(user_id: str, tenant_id: str, op_type: str, payload: Dict[str, Any], *,
             captured: Optional[datetime] = None, offset_ms: int = 0, device_id: str = DEVICE_A,
             key: Optional[str] = None, local_id: Optional[str] = None,
             base_version: Optional[str] = None) -> Dict[str, Any]:
    return {"local_id": local_id or str(uuid.uuid4()), "idempotency_key": key or str(uuid.uuid4()),
            "op_type": op_type, "captured_at": _iso(captured or datetime.now(timezone.utc)),
            "captured_tz": "Europe/Sofia", "device_clock_offset_ms": offset_ms,
            "user_id": user_id, "tenant_id": tenant_id, "device_id": device_id,
            "payload": payload, "base_version": base_version}


# ═══════════════════════════════════════════════════════════════════════════ harness
def install_probe_handlers(sync) -> Dict[str, Any]:
    """Test-only operations: ``probe.note`` counts its calls and returns; ``probe.edit``
    raises a conflict when ``base_version`` differs from the "office" version."""
    calls: Dict[str, Any] = {"note": 0, "edit": 0, "confirm": 0}

    async def note(user, env, ctx):
        calls["note"] += 1
        return {"entity_type": "probe", "entity_id": env["local_id"], "ok": True}

    async def confirm(user, env, ctx):
        calls["confirm"] += 1
        return {"entity_type": "probe", "entity_id": env["local_id"], "confirmed": True}

    async def edit(user, env, ctx):
        calls["edit"] += 1
        office = {"hours": 8, "updated_at": "2026-11-09T07:00:00+00:00", "status": "APPROVED"}
        if env.get("base_version") != office["updated_at"] or office["status"] == "APPROVED":
            raise sync.SyncConflict(entity_type="probe", entity_id="rec-1", office=office,
                                    field={"hours": env["payload"].get("hours"),
                                           "updated_at": env.get("base_version"),
                                           "status": office["status"]},
                                    kind="approved" if office["status"] == "APPROVED" else "version")
        return {"entity_type": "probe", "entity_id": "rec-1"}

    sync.register("probe.note", note, confirm=confirm)
    sync.register("probe.edit", edit)
    return calls


def run_harness(mongo_url: str, out_json: Path) -> Dict[str, Any]:
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    pm = _pm01()
    import server
    from fastapi.testclient import TestClient
    from app.services import offline_sync as sync

    # The attendance deadline ("Present" after it becomes "Late") is existing behaviour that
    # reads the wall clock at write time (HANDOFF D6). These cells test the SYNC rules, so
    # the harness runs at a fixed 07:00 — the result must not depend on when it is run.
    import app.routes.attendance as attendance_routes
    attendance_routes.now_hour = lambda: 7

    app = server.app
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    seed_mod = pm._load_seed()
    obs: Dict[str, Any] = {}
    calls = install_probe_handlers(sync)

    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url))
        op_db = client[op_name]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name],
                                                      SYNTH_PASSWORD))
        tc.portal.call(lambda: sync.ensure_sync_indexes(op_db))
        for name in ("audit_events", "audit_logs"):
            if name not in tc.portal.call(op_db.list_collection_names):
                tc.portal.call(lambda: op_db.create_collection(name))
        fx: Dict[str, Any] = {}
        for t in report["tenants"]:
            fx[t["key"]] = {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                            "users": {u["key"]: u for u in t["users"]}}
        tokens: Dict[tuple, str] = {}
        for tkey in ("A", "B"):
            for key in ROLE_KEYS:
                r = tc.post("/api/auth/login", json={
                    "email": fx[tkey]["users"][key]["email"], "password": SYNTH_PASSWORD})
                assert r.status_code == 200, (tkey, key, r.status_code, r.text[:200])
                tokens[(tkey, key)] = r.json()["token"]
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        A, B = fx["A"], fx["B"]
        tech = A["users"]["technician"]

        def call(method, url, role="technician", tkey="A", key: Optional[str] = None, **kw):
            headers = {"Authorization": "Bearer " + tokens[(tkey, role)]}
            if key:
                headers["Idempotency-Key"] = key
            resp = tc.request(method, url, headers=headers, **kw)
            try:
                body = resp.json()
            except Exception:                                   # noqa: BLE001
                body = resp.text[:300]
            detail = body.get("detail") if isinstance(body, dict) else None
            return {"status": resp.status_code,
                    "error_code": detail.get("error_code") if isinstance(detail, dict) else None,
                    "body": body}

        def q(fn):
            return tc.portal.call(fn)

        def count(coll, flt):
            return q(lambda: op_db[coll].count_documents(flt))

        def batch(items, role="technician", tkey="A", device=DEVICE_A):
            return call("POST", "/api/sync/batch", role=role, tkey=tkey,
                        json={"device_id": device, "items": items})

        # ─────────────────────────────────────────────── flag: off by default
        f: Dict[str, Any] = {}
        f["status_off"] = call("GET", "/api/sync/status")["body"]
        f["register_off"] = call("POST", "/api/sync/devices/register",
                                 json={"device_id": DEVICE_A, "label": "Телефон"})
        f["batch_off"] = batch([envelope(tech["id"], A["tenant_id"], "probe.note", {})])
        f["flag_by_owner"] = call("PUT", "/api/sync/flag", role="owner", json={"enabled": True})
        # the platform administrator switches it on (as for every feature flag)
        q(lambda: op_db.users.update_one({"id": A["users"]["owner"]["id"]},
                                         {"$set": {"is_platform_admin": True}}))
        f["flag_by_platform_admin"] = call("PUT", "/api/sync/flag", role="owner",
                                           json={"enabled": True})
        f["status_on"] = call("GET", "/api/sync/status")["body"]
        f["status_B_still_off"] = call("GET", "/api/sync/status", tkey="B")["body"]
        obs["flag"] = f

        # ─────────────────────────────────────────────── device registration
        d: Dict[str, Any] = {}
        d["register"] = call("POST", "/api/sync/devices/register",
                             json={"device_id": DEVICE_A, "label": "Телефон Иван"})
        d["register_again"] = call("POST", "/api/sync/devices/register",
                                   json={"device_id": DEVICE_A, "label": "Телефон Иван"})
        d["register_bad_id"] = call("POST", "/api/sync/devices/register",
                                    json={"device_id": "not-a-uuid"})
        d["devices_rows"] = count("sync_devices", {"org_id": A["tenant_id"], "id": DEVICE_A})
        d["batch_unregistered"] = batch([envelope(tech["id"], A["tenant_id"], "probe.note", {},
                                                  device_id=DEVICE_A2)], device=DEVICE_A2)
        obs["device"] = d

        # ─────────────────────────────────────────────── idempotency
        i: Dict[str, Any] = {}
        env1 = envelope(tech["id"], A["tenant_id"], "probe.note", {"text": "бележка"})
        before_events = count("audit_events", {"action": "sync.item_synced"})
        first = batch([env1])
        second = batch([env1])
        third = batch([env1])
        i["first"] = first["body"]["results"][0]
        i["second"] = second["body"]["results"][0]
        i["third"] = third["body"]["results"][0]
        env_par = envelope(tech["id"], A["tenant_id"], "probe.note", {"text": "паралелно"})
        with ThreadPoolExecutor(max_workers=3) as ex:
            par = list(ex.map(lambda _: batch([env_par]), range(3)))
        i["parallel_statuses"] = sorted((p["body"].get("results") or [{}])[0].get("status")
                                        for p in par)
        i["calls_note"] = calls["note"]
        i["receipts_env1"] = count("sync_receipts", {"idempotency_key": env1["idempotency_key"]})
        i["receipts_par"] = count("sync_receipts", {"idempotency_key": env_par["idempotency_key"]})
        i["synced_events"] = count("audit_events", {"action": "sync.item_synced"}) - before_events
        reuse = dict(env1, payload={"text": "друго"})
        i["key_reused"] = batch([reuse])["body"]["results"][0]
        i["event_fields"] = q(lambda: op_db.audit_events.find_one(
            {"action": "sync.item_synced", "idempotency_key": env1["idempotency_key"]},
            {"_id": 0, "tenant_id": 1, "source_flow": 1, "idempotency_key": 1,
             "structured_diff": 1, "source_channel": 1}))
        obs["idempotency"] = i

        # ─────────────────────────────────────────────── refusals
        r: Dict[str, Any] = {}
        r["online_only_payment"] = batch([envelope(tech["id"], A["tenant_id"], "payment.create",
                                                   {"amount": 100})])["body"]["results"][0]
        r["online_only_approve"] = batch([envelope(tech["id"], A["tenant_id"],
                                                   "daily_report.approve", {})])["body"]["results"][0]
        r["unsupported"] = batch([envelope(tech["id"], A["tenant_id"], "rocket.launch",
                                           {})])["body"]["results"][0]
        r["tenant_mismatch"] = batch([envelope(tech["id"], B["tenant_id"], "probe.note",
                                               {})])["body"]["results"][0]
        r["user_mismatch"] = batch([envelope(A["users"]["owner"]["id"], A["tenant_id"],
                                             "probe.note", {})])["body"]["results"][0]
        r["bad_envelope"] = batch([{"op_type": "probe.note"}])["body"]["results"][0]
        r["empty_batch"] = batch([])["status"]
        # tenant B's user cannot touch tenant A's device or console
        r["B_batch_on_A_device"] = batch([envelope(B["users"]["technician"]["id"], B["tenant_id"],
                                                   "probe.note", {})], tkey="B")
        obs["refusals"] = r

        # ─────────────────────────────────────────────── late records (R61-3)
        late: Dict[str, Any] = {}
        yesterday = datetime.now(timezone.utc) - timedelta(days=1, hours=2)
        env_late = envelope(tech["id"], A["tenant_id"], "probe.note", {"text": "вчера"},
                            captured=yesterday)
        notes_before = calls["note"]
        late["previous_day"] = batch([env_late])["body"]["results"][0]
        env_skew = envelope(tech["id"], A["tenant_id"], "probe.note", {"text": "часовник"},
                            offset_ms=11 * 60 * 1000)
        late["clock_skew"] = batch([env_skew])["body"]["results"][0]
        env_ok_skew = envelope(tech["id"], A["tenant_id"], "probe.note", {"text": "9 мин"},
                               offset_ms=9 * 60 * 1000)
        late["nine_minutes_is_fine"] = batch([env_ok_skew])["body"]["results"][0]["status"]
        late["handler_not_called"] = calls["note"] - notes_before == 1  # only the 9-min one
        late["late_rows"] = count("sync_late", {"org_id": A["tenant_id"], "status": "open"})
        late["late_row"] = q(lambda: op_db.sync_late.find_one(
            {"local_id": env_late["local_id"]},
            {"_id": 0, "captured_at": 1, "received_at": 1, "reason": 1, "status": 1,
             "author_id": 1, "device_id": 1}))
        obs["late"] = late

        # ─────────────────────────────────────────────── conflicts (R61-2 / R61-4)
        c: Dict[str, Any] = {}
        env_edit = envelope(tech["id"], A["tenant_id"], "probe.edit", {"hours": 10},
                            base_version="2026-11-08T07:00:00+00:00")
        c["result"] = batch([env_edit])["body"]["results"][0]
        c["row"] = q(lambda: op_db.sync_conflicts.find_one(
            {"local_id": env_edit["local_id"]},
            {"_id": 0, "kind": 1, "diff": 1, "office_version": 1, "field_version": 1,
             "author_id": 1, "status": 1}))
        c["replay"] = batch([env_edit])["body"]["results"][0]
        c["conflict_rows"] = count("sync_conflicts", {"local_id": env_edit["local_id"]})
        obs["conflict"] = c

        # ═══════════════════════ the three real offline types (Q1) ═══════════════════════
        from app.services import offline_sync_handlers  # noqa: F401 — registered by the router too
        from app.services.offline_sync import local_day, zone
        sofia = zone("Europe/Sofia")
        today = local_day(datetime.now(timezone.utc), sofia)
        yesterday_dt = datetime.now(timezone.utc) - timedelta(days=1)
        yesterday = local_day(yesterday_dt, sofia)
        P = A["project_id"]
        q(lambda: op_db.projects.update_one({"id": P}, {"$set": {"status": "Active"}}))
        req = A["users"]["requester"]

        def att(user_id, status="Present", captured=None, **kw):
            return envelope(user_id, A["tenant_id"], "attendance.mark",
                            {"status": status, "project_id": P, "note": "офлайн"}, captured=captured, **kw)

        def att_rows(uid, date):
            return q(lambda: op_db.attendance_entries.find({"user_id": uid, "date": date},
                                                           {"_id": 0}).to_list(None))

        h: Dict[str, Any] = {}
        # R1 — attendance today: synced once, Sofia day, stamped; 3× resend + parallel → 1 entry
        e_att = att(tech["id"])
        h["att_first"] = batch([e_att])["body"]["results"][0]
        for _ in range(2):
            h["att_again"] = batch([e_att])["body"]["results"][0]
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(lambda _: batch([e_att]), range(3)))
        rows = att_rows(tech["id"], today)
        h["att_rows"] = len(rows)
        h["att_row"] = {k: rows[0].get(k) for k in ("date", "status", "source", "version", "sync_local_id",
                                                     "captured_at", "device_id", "marked_by_user_id")} if rows else None
        h["att_events"] = count("audit_events", {"action": "sync.item_synced",
                                                 "idempotency_key": e_att["idempotency_key"]})
        # R2 — identical self-mark (new key): synced, nothing written (Q3)
        h["att_identical"] = batch([att(tech["id"])])["body"]["results"][0]
        h["att_rows_after_identical"] = len(att_rows(tech["id"], today))
        # R3 — a different status the same day: conflict, office entry untouched
        e_diff = att(tech["id"], status="Absent")
        h["att_diff"] = batch([e_diff])["body"]["results"][0]
        h["att_after_diff"] = [r["status"] for r in att_rows(tech["id"], today)]
        cid = h["att_diff"]["result"].get("conflict_id")
        # R4 — resolving: the technician cannot; Owner keeps the office version
        h["resolve_by_tech"] = call("POST", "/api/sync/conflicts/%s/resolve" % cid, role="technician",
                                    key=str(uuid.uuid4()), json={"decision": "keep_office", "reason": "проверено"})["status"]
        h["resolve_no_reason"] = call("POST", "/api/sync/conflicts/%s/resolve" % cid, role="owner",
                                      key=str(uuid.uuid4()), json={"decision": "keep_office"})["status"]
        k1 = str(uuid.uuid4())
        h["resolve_keep"] = call("POST", "/api/sync/conflicts/%s/resolve" % cid, role="owner", key=k1,
                                 json={"decision": "keep_office", "reason": "Говорих с техника — беше на обекта"})
        h["resolve_keep_replay"] = call("POST", "/api/sync/conflicts/%s/resolve" % cid, role="owner", key=k1,
                                        json={"decision": "keep_office", "reason": "Говорих с техника — беше на обекта"})["status"]
        h["resolve_twice"] = call("POST", "/api/sync/conflicts/%s/resolve" % cid, role="owner",
                                  key=str(uuid.uuid4()), json={"decision": "accept_field", "reason": "друго"})
        h["receipt_after_keep"] = q(lambda: op_db.sync_receipts.find_one(
            {"idempotency_key": e_diff["idempotency_key"]}, {"_id": 0, "status": 1, "result": 1}))
        h["status_after_keep"] = [r["status"] for r in att_rows(tech["id"], today)]
        # accept the phone's version of a second conflict: CAS on version, audit
        e_diff2 = att(tech["id"], status="Late")
        cid2 = batch([e_diff2])["body"]["results"][0]["result"].get("conflict_id")
        h["resolve_accept"] = call("POST", "/api/sync/conflicts/%s/resolve" % cid2, role="admin",
                                   key=str(uuid.uuid4()), json={"decision": "accept_field", "reason": "Потвърдено по телефона"})
        h["after_accept"] = [{k: r.get(k) for k in ("status", "version", "update_source")}
                             for r in att_rows(tech["id"], today)]
        h["accept_event"] = q(lambda: op_db.audit_events.find_one(
            {"action": "sync.conflict_accepted_field"}, {"_id": 0, "reason": 1, "actor_id": 1}))
        # R9 — a paid day (pay run paid covering the worker's day): conflict, never written
        q(lambda: op_db.pay_runs.insert_one({"id": "pr-pwa02", "org_id": A["tenant_id"], "status": "paid",
                                             "period_start": today, "period_end": today,
                                             "employee_rows": [{"employee_id": req["id"]}]}))
        call("POST", "/api/sync/devices/register", role="requester", json={"device_id": DEVICE_A})
        h["paid_day"] = batch([att(req["id"])], role="requester")["body"]["results"][0]
        h["paid_rows"] = len(att_rows(req["id"], today))
        pid_conf = h["paid_day"]["result"].get("conflict_id")
        h["paid_accept"] = call("POST", "/api/sync/conflicts/%s/resolve" % pid_conf, role="owner",
                                key=str(uuid.uuid4()), json={"decision": "accept_field", "reason": "опит"})
        h["paid_correct"] = call("POST", "/api/sync/conflicts/%s/resolve" % pid_conf, role="owner",
                                 key=str(uuid.uuid4()), json={"decision": "correct", "reason": "опит",
                                                               "payload": {"status": "Present"}})
        h["paid_rows_after"] = len(att_rows(req["id"], today))
        # R5 — the technician's daily report today (attendance exists): synced once, stamped
        e_rep = envelope(tech["id"], A["tenant_id"], "technician.daily_report",
                         {"project_id": P, "entries": [{"smr_type": "Шпакловка", "hours": 6.5,
                                                        "notes": "офлайн"}], "general_notes": "без интернет"})
        h["report"] = batch([e_rep])["body"]["results"][0]
        batch([e_rep])
        reps = q(lambda: op_db.employee_daily_reports.find({"sync_local_id": e_rep["local_id"]},
                                                           {"_id": 0}).to_list(None))
        h["report_rows"] = len(reps)
        h["report_row"] = {k: reps[0].get(k) for k in ("date", "hours", "status", "version", "worker_id")} if reps else None
        # R10 — a report into a day with an approved report: conflict, nothing added
        acc = A["users"]["accountant"]
        q(lambda: op_db.employee_daily_reports.insert_one({
            "id": "dr-approved", "org_id": A["tenant_id"], "worker_id": acc["id"], "date": today,
            "project_id": P, "hours": 8, "approval_status": "APPROVED"}))
        call("POST", "/api/sync/devices/register", role="accountant", json={"device_id": DEVICE_A})
        e_rep2 = envelope(acc["id"], A["tenant_id"], "technician.daily_report",
                          {"project_id": P, "entries": [{"smr_type": "Зидария", "hours": 2}]})
        h["report_closed"] = batch([e_rep2], role="accountant")["body"]["results"][0]
        h["report_closed_rows"] = count("employee_daily_reports", {"worker_id": acc["id"], "date": today})
        # R6 — photo: waiting for a File Registry, never final; bad input refused
        sha = "ab" * 32
        h["photo"] = batch([envelope(tech["id"], A["tenant_id"], "media.upload",
                                     {"sha256": sha, "size": 2_000_000, "mime": "image/jpeg",
                                      "context_type": "project", "context_id": P})])["body"]["results"][0]
        h["photo_bad_sha"] = batch([envelope(tech["id"], A["tenant_id"], "media.upload",
                                             {"sha256": "nope", "size": 10, "mime": "image/jpeg"})])["body"]["results"][0]
        h["photo_too_big"] = batch([envelope(tech["id"], A["tenant_id"], "media.upload",
                                             {"sha256": sha, "size": 30 * 1024 * 1024, "mime": "image/jpeg"})])["body"]["results"][0]
        h["photo_media_rows"] = count("media_files", {"context_id": P, "sha256": sha})
        # R7 — late attendance (yesterday): not official; worker cannot decide; Owner confirms
        e_late = att(tech["id"], captured=yesterday_dt)
        h["late"] = batch([e_late])["body"]["results"][0]
        lid = h["late"]["result"].get("late_id")
        h["late_rows_before"] = len(att_rows(tech["id"], yesterday))
        h["late_by_tech"] = call("POST", "/api/sync/late/%s/decide" % lid, role="technician",
                                 key=str(uuid.uuid4()), json={"decision": "confirm", "reason": "аз"})["status"]
        k2 = str(uuid.uuid4())
        h["late_confirm"] = call("POST", "/api/sync/late/%s/decide" % lid, role="owner", key=k2,
                                 json={"decision": "confirm", "reason": "Беше без покритие на обекта"})
        h["late_confirm_replay"] = call("POST", "/api/sync/late/%s/decide" % lid, role="owner", key=k2,
                                        json={"decision": "confirm", "reason": "Беше без покритие на обекта"})["status"]
        h["late_decide_again"] = call("POST", "/api/sync/late/%s/decide" % lid, role="owner",
                                      key=str(uuid.uuid4()), json={"decision": "reject", "reason": "друго"})["error_code"]
        yrows = att_rows(tech["id"], yesterday)
        h["late_rows_after"] = len(yrows)
        h["late_row"] = {k: yrows[0].get(k) for k in ("date", "captured_at", "late_confirmed_by",
                                                       "marked_by_user_id", "source")} if yrows else None
        h["late_receipt"] = q(lambda: op_db.sync_receipts.find_one(
            {"idempotency_key": e_late["idempotency_key"]}, {"_id": 0, "status": 1}))
        h["late_event"] = q(lambda: op_db.audit_events.find_one(
            {"action": "sync.late_confirmed"}, {"_id": 0, "reason": 1, "actor_id": 1, "structured_diff": 1}))
        # R8 — a late report the office refuses: nothing written, the phone sees it
        e_late2 = envelope(tech["id"], A["tenant_id"], "technician.daily_report",
                           {"project_id": P, "entries": [{"smr_type": "Боя", "hours": 3}]}, captured=yesterday_dt)
        lid2 = batch([e_late2])["body"]["results"][0]["result"].get("late_id")
        h["late_reject"] = call("POST", "/api/sync/late/%s/decide" % lid2, role="admin", key=str(uuid.uuid4()),
                                json={"decision": "reject", "reason": "Няма такава работа"})["status"]
        h["late_reject_receipt"] = q(lambda: op_db.sync_receipts.find_one(
            {"idempotency_key": e_late2["idempotency_key"]}, {"_id": 0, "status": 1, "result": 1}))
        h["late_reject_rows"] = count("employee_daily_reports", {"sync_local_id": e_late2["local_id"]})
        my = call("GET", "/api/sync/receipts?device_id=" + DEVICE_A)["body"]
        h["my_receipts_statuses"] = sorted({r["status"] for r in my})
        obs["handlers"] = h

        # ─────────────────────────────────────────────── console permissions
        k: Dict[str, Any] = {}
        for role in ROLE_KEYS:
            k[role] = call("GET", "/api/sync/console", role=role)["status"]
        owner_console = call("GET", "/api/sync/console", role="owner")["body"]
        k["owner_counts"] = owner_console.get("counts")
        k["owner_sees_device"] = any(dv["id"] == DEVICE_A for dv in owner_console.get("devices", []))
        k["B_owner_sees_A_device"] = any(
            dv["id"] == DEVICE_A for dv in call("GET", "/api/sync/console", role="owner",
                                                tkey="B")["body"].get("devices", []))
        obs["console"] = k

        # ─────────────────────────────────────────────── revoke (R61-6)
        v: Dict[str, Any] = {}
        v["by_technician"] = call("POST", "/api/sync/devices/%s/revoke" % DEVICE_A,
                                  role="technician", key=str(uuid.uuid4()),
                                  json={"reason": "изгубен"})["status"]
        v["no_key"] = call("POST", "/api/sync/devices/%s/revoke" % DEVICE_A, role="owner",
                           json={"reason": "изгубен"})
        v["no_reason"] = call("POST", "/api/sync/devices/%s/revoke" % DEVICE_A, role="owner",
                              key=str(uuid.uuid4()), json={})
        v["by_B_owner"] = call("POST", "/api/sync/devices/%s/revoke" % DEVICE_A, role="owner",
                               tkey="B", key=str(uuid.uuid4()), json={"reason": "чужд"})
        v["by_owner"] = call("POST", "/api/sync/devices/%s/revoke" % DEVICE_A, role="owner",
                             key=str(uuid.uuid4()), json={"reason": "Изгубен телефон"})
        v["revoke_event"] = q(lambda: op_db.audit_events.find_one(
            {"action": "sync.device_revoked", "entity_id": DEVICE_A},
            {"_id": 0, "reason": 1, "actor_id": 1, "tenant_id": 1}))
        v["status_revoked"] = call("GET", "/api/sync/status?device_id=" + DEVICE_A)["body"]
        notes_before = calls["note"]
        env_q = envelope(tech["id"], A["tenant_id"], "probe.note", {"text": "след блокиране"})
        blocked = batch([env_q])
        v["batch_after_revoke"] = {"status": blocked["status"], "error_code": blocked["error_code"],
                                   "results": (blocked["body"].get("detail") or {}).get("results")}
        v["handler_not_called"] = calls["note"] == notes_before
        v["quarantine_rows"] = count("sync_quarantine", {"local_id": env_q["local_id"]})
        v["register_after_revoke"] = call("POST", "/api/sync/devices/register",
                                          json={"device_id": DEVICE_A})
        v["user_can_still_log_in"] = tc.post("/api/auth/login", json={
            "email": tech["email"], "password": SYNTH_PASSWORD}).status_code
        console_after = call("GET", "/api/sync/console", role="owner")["body"]
        v["console_counts"] = console_after.get("counts")
        obs["revoke"] = v

        # ─────────────────────────────────────────────── flag off again (rollback)
        rb: Dict[str, Any] = {}
        rb["off"] = call("PUT", "/api/sync/flag", role="owner", json={"enabled": False})["status"]
        rb["batch_when_off"] = batch([envelope(tech["id"], A["tenant_id"], "probe.note", {})])
        rb["receipts_kept"] = count("sync_receipts", {"org_id": A["tenant_id"]})
        obs["rollback"] = rb
        obs["calls"] = dict(calls)

    out_json.write_text(json.dumps(obs, indent=1, ensure_ascii=False, sort_keys=True,
                                   default=str) + "\n", encoding="utf-8")
    return obs


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 1800) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "pwa02-local-" + uuid.uuid4().hex
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child",
           "--mongo-url", mongo_url, "--out-json", str(out_json)]
    try:
        subprocess.run(cmd, cwd=str(BACKEND), timeout=timeout, check=True, env=env)
    finally:
        import pymongo
        c = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        for name in (op_name, sys_name):
            assert name.startswith((DB_PREFIX_OP, DB_PREFIX_SYS))
            c.drop_database(name)
        c.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PWA-02 offline sync evidence")
    parser.add_argument("--harness", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-json", default=str(REPO / "docs" / "evidence" / "PWA-02" /
                                                  "results.json"))
    args = parser.parse_args(argv)
    if not args.mongo_url:
        print("no --mongo-url and no W0_03_REAL_MONGO_URL", file=sys.stderr)
        return 2
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    _pm01()._check_local(args.mongo_url)
    if args.child:
        run_harness(args.mongo_url, Path(args.out_json))
        return 0
    if args.harness:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        run_in_child(args.mongo_url, Path(args.out_json))
        return 0
    parser.print_help()
    return 2


# ═══════════════════════════════════════════════════════════════════ real-Mongo tests
def _real_refusal() -> str:
    url = os.environ.get("W0_03_REAL_MONGO_URL", "")
    if not url:
        return "W0_03_REAL_MONGO_URL is not set — no disposable local MongoDB given"
    try:
        return _pm01()._real_refusal()
    except Exception as exc:                                   # noqa: BLE001
        return "refused: %s" % exc


real = pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")


@pytest.fixture(scope="module")
def obs(tmp_path_factory):
    out = tmp_path_factory.mktemp("pwa02") / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    return json.loads(out.read_text(encoding="utf-8"))


@real
def test_flag_is_off_by_default_and_only_the_platform_admin_switches_it(obs):
    f = obs["flag"]
    assert f["status_off"]["enabled"] is False
    assert f["register_off"]["error_code"] == "OFFLINE_QUEUE_DISABLED"
    assert f["batch_off"]["error_code"] == "OFFLINE_QUEUE_DISABLED"
    assert f["flag_by_owner"]["status"] == 403
    assert f["flag_by_platform_admin"]["status"] == 200
    assert f["status_on"]["enabled"] is True
    assert f["status_B_still_off"]["enabled"] is False          # per tenant


@real
def test_a_device_registers_once_and_an_unregistered_one_cannot_sync(obs):
    d = obs["device"]
    assert d["register"]["status"] == 200 and d["register_again"]["status"] == 200
    assert d["devices_rows"] == 1
    assert d["register_bad_id"]["status"] == 422
    assert d["batch_unregistered"]["error_code"] == "DEVICE_NOT_REGISTERED"


@real
def test_resending_three_times_and_in_parallel_writes_one_record_and_one_event(obs):
    i = obs["idempotency"]
    assert i["first"]["status"] == "synced" and i["first"]["replay"] is False
    assert i["second"]["status"] == "synced" and i["second"]["replay"] is True
    assert i["third"]["replay"] is True and i["second"]["result"] == i["first"]["result"]
    assert i["receipts_env1"] == 1 and i["receipts_par"] == 1
    assert i["calls_note"] == 2                     # env1 once + the parallel item once
    assert i["synced_events"] == 2
    assert set(i["parallel_statuses"]) <= {"synced", "processing"}
    assert i["parallel_statuses"].count("synced") >= 1
    assert i["key_reused"]["status"] == "rejected"
    assert i["key_reused"]["result"]["error_code"] == "IDEMPOTENCY_KEY_REUSED"
    ev = i["event_fields"]
    assert ev["source_flow"] == "FLOW-037" and ev["source_channel"] == "offline_sync"
    assert ev["structured_diff"]["device_id"] and ev["structured_diff"]["captured_at"]


@real
def test_online_only_unknown_foreign_tenant_and_bad_items_are_refused(obs):
    r = obs["refusals"]
    assert r["online_only_payment"]["result"]["error_code"] == "ONLINE_ONLY"
    assert r["online_only_approve"]["result"]["error_code"] == "ONLINE_ONLY"
    assert r["unsupported"]["result"]["error_code"] == "UNSUPPORTED_OP"
    assert r["tenant_mismatch"]["result"]["error_code"] == "TENANT_MISMATCH"
    assert r["user_mismatch"]["result"]["error_code"] == "USER_MISMATCH"
    assert r["bad_envelope"]["status"] == "rejected"
    assert r["empty_batch"] == 422
    # B's session: flag off for B, and in any case A's device is not B's
    assert r["B_batch_on_A_device"]["status"] in (403, 409)


@real
def test_a_late_record_is_not_official_and_waits_for_the_office(obs):
    late = obs["late"]
    assert late["previous_day"]["status"] == "late"
    assert late["previous_day"]["result"]["reason"] == "previous_day"
    assert late["clock_skew"]["status"] == "late"
    assert late["clock_skew"]["result"]["reason"] == "clock_skew"
    assert late["nine_minutes_is_fine"] == "synced"
    assert late["handler_not_called"] is True          # no domain write for a late record
    row = late["late_row"]
    assert row["status"] == "open" and row["captured_at"] < row["received_at"]


@real
def test_a_conflict_writes_nothing_keeps_both_versions_and_is_not_duplicated(obs):
    c = obs["conflict"]
    assert c["result"]["status"] == "conflict" and c["result"]["result"]["kind"] == "approved"
    row = c["row"]
    assert row["status"] == "open"
    assert {d["field"] for d in row["diff"]} >= {"hours", "updated_at"}
    assert row["office_version"]["hours"] == 8 and row["field_version"]["hours"] == 10
    assert c["replay"]["replay"] is True and c["conflict_rows"] == 1


@real
def test_only_owner_and_admin_see_the_console_and_only_their_tenant(obs):
    k = obs["console"]
    assert k["owner"] == 200 and k["admin"] == 200
    for role in ("requester", "technician", "accountant", "viewer"):
        assert k[role] == 403, role
    assert k["owner_sees_device"] is True
    assert k["B_owner_sees_A_device"] is False
    assert k["owner_counts"]["conflicts"] >= 1 and k["owner_counts"]["late"] >= 2
    assert all(r == 403 for r in [k["requester"], k["technician"]])


@real
def test_a_blocked_device_is_refused_its_items_go_to_quarantine_and_the_user_is_not_blocked(obs):
    v = obs["revoke"]
    assert v["by_technician"] == 403
    assert v["no_key"]["status"] == 428 and v["no_reason"]["status"] == 422
    assert v["by_B_owner"]["status"] == 404                    # another tenant's device
    assert v["by_owner"]["status"] == 200 and v["by_owner"]["body"]["revoked_at"]
    assert v["revoke_event"]["reason"] == "Изгубен телефон"
    assert v["status_revoked"]["revoked"] is True
    assert v["batch_after_revoke"]["status"] == 403
    assert v["batch_after_revoke"]["error_code"] == "DEVICE_REVOKED"
    assert v["batch_after_revoke"]["results"][0]["status"] == "quarantined"
    assert v["handler_not_called"] is True and v["quarantine_rows"] == 1
    assert v["register_after_revoke"]["error_code"] == "DEVICE_REVOKED"
    assert v["user_can_still_log_in"] == 200
    assert v["console_counts"]["revoked"] == 1 and v["console_counts"]["quarantine"] == 1


@real
def test_switching_the_flag_off_stops_the_queue_and_loses_nothing(obs):
    rb = obs["rollback"]
    assert rb["off"] == 200
    assert rb["batch_when_off"]["error_code"] == "OFFLINE_QUEUE_DISABLED"
    assert rb["receipts_kept"] > 0


@real
def test_attendance_syncs_once_on_the_sofia_day_stamped_with_version_and_capture(obs):
    h = obs["handlers"]
    assert h["att_first"]["status"] == "synced"
    assert h["att_again"]["replay"] is True
    assert h["att_rows"] == 1 and h["att_events"] == 1
    row = h["att_row"]
    assert row["source"] == "offline_sync" and row["version"] == 1
    assert row["sync_local_id"] and row["captured_at"] and row["device_id"]


@real
def test_an_identical_self_mark_is_a_silent_confirmation(obs):
    h = obs["handlers"]
    assert h["att_identical"]["status"] == "synced"
    assert h["att_identical"]["result"]["identical"] is True
    assert h["att_rows_after_identical"] == 1


@real
def test_a_different_mark_is_a_conflict_and_the_office_entry_is_untouched(obs):
    h = obs["handlers"]
    assert h["att_diff"]["status"] == "conflict"
    assert h["att_diff"]["result"]["kind"] == "already_recorded"
    assert h["att_after_diff"] == ["Present"]


@real
def test_only_owner_admin_resolve_with_a_reason_once_and_the_phone_sees_it(obs):
    h = obs["handlers"]
    assert h["resolve_by_tech"] == 403 and h["resolve_no_reason"] == 422
    assert h["resolve_keep"]["status"] == 200 and h["resolve_keep"]["body"]["status"] == "kept_office"
    assert h["resolve_keep_replay"] == 200
    assert h["resolve_twice"]["status"] == 409
    assert h["receipt_after_keep"]["status"] == "rejected"
    assert h["status_after_keep"] == ["Present"]
    assert h["resolve_accept"]["status"] == 200
    assert h["after_accept"] == [{"status": "Late", "version": 2, "update_source": "offline_conflict_resolution"}]
    assert h["accept_event"]["reason"] == "Потвърдено по телефона"


@real
def test_a_paid_day_is_a_conflict_settled_only_by_correction_or_reversal(obs):
    h = obs["handlers"]
    assert h["paid_day"]["status"] == "conflict" and h["paid_day"]["result"]["kind"] == "paid"
    assert h["paid_rows"] == 0
    assert h["paid_accept"]["error_code"] == "CORRECTION_OR_REVERSAL_REQUIRED"
    assert h["paid_correct"]["error_code"] == "CORRECTION_OR_REVERSAL_REQUIRED"
    assert h["paid_rows_after"] == 0


@real
def test_the_daily_report_goes_through_the_domain_once_and_never_into_a_closed_day(obs):
    h = obs["handlers"]
    assert h["report"]["status"] == "synced", h["report"]
    assert h["report_rows"] == 1
    assert h["report_row"]["hours"] == 6.5 and h["report_row"]["version"] == 1
    assert h["report_closed"]["status"] == "conflict" and h["report_closed"]["result"]["kind"] == "approved"
    assert h["report_closed_rows"] == 1                       # only the office's approved one


@real
def test_a_photo_waits_for_the_file_registry_and_bad_files_are_refused(obs):
    h = obs["handlers"]
    assert h["photo"]["status"] == "waiting_file"
    assert h["photo"]["result"]["file_registry"] == "unavailable"
    assert h["photo_bad_sha"]["result"]["error_code"] == "CHECKSUM_INVALID"
    assert h["photo_too_big"]["result"]["error_code"] == "FILE_TOO_LARGE"
    assert h["photo_media_rows"] == 0


@real
def test_a_late_record_becomes_official_only_by_owner_admin_with_the_captured_date(obs):
    h = obs["handlers"]
    assert h["late"]["status"] == "late" and h["late_rows_before"] == 0
    assert h["late_by_tech"] == 403
    assert h["late_confirm"]["status"] == 200 and h["late_confirm"]["body"]["status"] == "confirmed"
    assert h["late_confirm_replay"] == 200 and h["late_decide_again"] == "ALREADY_DECIDED"
    assert h["late_rows_after"] == 1
    row = h["late_row"]
    assert row["late_confirmed_by"] and row["marked_by_user_id"] == row["late_confirmed_by"]
    assert row["captured_at"]
    assert h["late_receipt"]["status"] == "synced"
    ev = h["late_event"]
    assert ev["reason"] == "Беше без покритие на обекта" and ev["structured_diff"]["captured_at"]
    assert h["late_reject"] == 200 and h["late_reject_rows"] == 0
    assert h["late_reject_receipt"]["status"] == "rejected"
    assert {"synced", "conflict", "waiting_file", "rejected"} <= set(h["my_receipts_statuses"])


if __name__ == "__main__":
    sys.exit(main())


@real
def test_the_unique_indexes_tolerate_old_keyless_rows_and_still_refuse_a_duplicate():
    """Partial unique indexes: created over a database that already holds rows without the
    key fields (an old backup, the W0-03E fixtures), and two real receipts with the same
    (org, user, idempotency_key) are still refused."""
    import asyncio
    import uuid as _uuid
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import DuplicateKeyError
    from app.services.offline_sync import ensure_sync_indexes

    async def body():
        name = DB_PREFIX_OP + "idx_" + _uuid.uuid4().hex[:8]
        c = AsyncIOMotorClient(os.environ["W0_03_REAL_MONGO_URL"])
        d = c[name]
        try:
            for coll in ("sync_receipts", "sync_devices"):
                for v in ({"org_id": "o", "marker": 1}, {"marker": 2}, {"org_id": None, "marker": 3},
                          {"org_id": "o", "marker": 4}):
                    await d[coll].insert_one(dict(v))
            await ensure_sync_indexes(d)
            await ensure_sync_indexes(d)                      # idempotent
            r = {"org_id": "o", "user_id": "u", "idempotency_key": "k"}
            await d.sync_receipts.insert_one(dict(r))
            with pytest.raises(DuplicateKeyError):
                await d.sync_receipts.insert_one(dict(r))
            await d.sync_devices.insert_one({"org_id": "o", "id": "dev-1"})
            with pytest.raises(DuplicateKeyError):
                await d.sync_devices.insert_one({"org_id": "o", "id": "dev-1"})
        finally:
            await c.drop_database(name)
            c.close()
    asyncio.run(body())
