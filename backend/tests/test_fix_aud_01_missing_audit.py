"""
FIX-AUD-01 — Missing SMR and Assets QR writes record a canonical AuditEvent.

Canon: CLAUDE.md §2.8 (one append-only AuditEvent envelope), §14 (AuditEvent for every
consequential write), FLOW-040; FLOW-007 (missing / additional SMR), FLOW-011 (QR).

Every scenario runs through the WHOLE application (``server.app``) on a disposable LOCAL
MongoDB replica set (two fresh scratch databases ``fixtest_aud_op_*`` / ``fixtest_aud_sys_*``,
dropped afterwards), with the ST-01 synthetic tenants A and B, real logins and real JWTs.
The child process writes one JSON of observations; each test below checks one rule.

For each write: one success → exactly one ``audit_events`` row with the tenant, the actor and
the entity; a forbidden role → 403, no business row, no success event; an invalid request →
no business row and no event.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27021/?directConnection=true&replicaSet=rs0' \\
        PYTHONPATH=. pytest tests/test_fix_aud_01_missing_audit.py -q --noconftest -rs
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parent.parent
DB_PREFIX_OP, DB_PREFIX_SYS = "fixtest_aud_op_", "fixtest_aud_sys_"
SYNTH_PASSWORD = "FIXAUD01-Synthetic-Pass-2026!"   # synthetic users of a scratch database
ROLE_KEYS = ("owner", "admin", "requester", "technician", "viewer")


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "fixaud01_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ═══════════════════════════════════════════════════════════════════ harness (child)
def run_harness(mongo_url: str, out_json: Path) -> Dict[str, Any]:
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    pm = _pm01()
    import server
    from fastapi.testclient import TestClient

    app = server.app
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    seed_mod = pm._load_seed()
    obs: Dict[str, Any] = {}

    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url))
        op_db = client[op_name]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name],
                                                      SYNTH_PASSWORD))
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
        obs["fx"] = {k: {"tenant_id": v["tenant_id"], "project_id": v["project_id"],
                         "users": {r: v["users"][r]["id"] for r in ROLE_KEYS}}
                     for k, v in fx.items()}

        def q(fn):
            return tc.portal.call(fn)

        def call(method, url, role="owner", tkey="A", **kw):
            headers = {"Authorization": "Bearer " + tokens[(tkey, role)],
                       "Idempotency-Key": uuid.uuid4().hex}
            resp = tc.request(method, url, headers=headers, **kw)
            try:
                body = resp.json()
            except Exception:                                   # noqa: BLE001
                body = resp.text[:300]
            return {"status": resp.status_code, "body": body}

        def count(coll, flt=None):
            return q(lambda: op_db[coll].count_documents(flt or {}))

        def events(prefix, entity_id=None):
            flt: Dict[str, Any] = {"action": {"$regex": "^" + prefix}}
            if entity_id is not None:
                flt["entity_id"] = entity_id
            rows = q(lambda: op_db.audit_events.find(flt, {"_id": 0}).sort("sequence", 1)
                     .to_list(1000))
            return [{k: r.get(k) for k in ("tenant_id", "actor_id", "action", "entity_type",
                                           "entity_id", "scope_id", "source_flow",
                                           "retention_class", "result", "source_channel",
                                           "structured_diff")} for r in rows]

        def snap():
            return {"missing_smr": count("missing_smr"), "offers": count("offers"),
                    "extra_work_drafts": count("extra_work_drafts"),
                    "asset_qr_codes": count("asset_qr_codes"),
                    "qr_seq": (q(lambda: op_db.asset_counters.find_one(
                        {"org_id": A["tenant_id"], "name": "qr"})) or {}).get("seq", 0),
                    "msmr_events": len(events("missing_smr.")),
                    "qr_events": len(events("asset_qr."))}

        def step(name, method, url, role="owner", tkey="A", entity=None, prefix="", **kw):
            before = snap()
            res = call(method, url, role=role, tkey=tkey, **kw)
            eid = entity(res) if callable(entity) else entity
            obs[name] = {"status": res["status"], "body": res["body"] if res["status"] >= 400
                         else None, "before": before, "after": snap(),
                         "events": events(prefix, eid) if prefix and eid else [],
                         "entity_id": eid}
            return res

        P = A["project_id"]
        new = {"project_id": P, "smr_type": "Шпакловка", "qty": 2, "unit": "m2"}

        # ── Missing SMR ──────────────────────────────────────────────
        r = step("msmr_create", "POST", "/api/missing-smr", role="requester", json=new,
                 entity=lambda res: (res["body"] or {}).get("id"), prefix="missing_smr.created")
        item = r["body"]["id"]
        step("msmr_create_forbidden", "POST", "/api/missing-smr", role="technician", json=new)
        step("msmr_create_invalid_source", "POST", "/api/missing-smr", role="requester",
             json={**new, "source": "fax"})
        step("msmr_create_invalid_body", "POST", "/api/missing-smr", role="requester",
             json={"smr_type": "без обект"})
        step("msmr_create_other_tenant_project", "POST", "/api/missing-smr", role="requester",
             json={**new, "project_id": B["project_id"]})
        step("msmr_update", "PUT", "/api/missing-smr/%s" % item, role="requester",
             json={"qty": 5}, entity=item, prefix="missing_smr.updated")
        step("msmr_status", "PUT", "/api/missing-smr/%s/status" % item, role="requester",
             json={"status": "reported"}, entity=item, prefix="missing_smr.status_changed")
        step("msmr_status_invalid", "PUT", "/api/missing-smr/%s/status" % item,
             role="requester", json={"status": "offered"})
        step("msmr_attach", "POST", "/api/missing-smr/%s/attachments" % item, role="requester",
             json={"media_id": "m-1", "url": "/x"}, entity=item,
             prefix="missing_smr.attachment_added")
        step("msmr_detach", "DELETE", "/api/missing-smr/%s/attachments/m-1" % item,
             role="requester", entity=item, prefix="missing_smr.attachment_removed")
        step("msmr_detach_absent", "DELETE", "/api/missing-smr/%s/attachments/none" % item,
             role="requester")
        step("msmr_request_approval", "POST", "/api/missing-smr/%s/request-approval" % item,
             role="requester", json={"client_name": "Синтетичен клиент"}, entity=item,
             prefix="missing_smr.client_approval_requested")
        step("msmr_client_approve", "PUT", "/api/missing-smr/%s/client-approve" % item,
             role="requester", json={}, entity=item, prefix="missing_smr.client_approved")
        step("msmr_to_analysis", "POST", "/api/missing-smr/%s/to-analysis" % item,
             role="requester", entity=item, prefix="missing_smr.sent_to_analysis")
        step("msmr_to_offer_forbidden", "POST", "/api/missing-smr/%s/to-offer" % item,
             role="requester")
        step("msmr_to_offer", "POST", "/api/missing-smr/%s/to-offer" % item, role="owner",
             entity=item, prefix="missing_smr.offer_created")

        rej = call("POST", "/api/missing-smr", role="requester", json=new)["body"]["id"]
        call("PUT", "/api/missing-smr/%s/status" % rej, role="requester",
             json={"status": "reported"})
        call("POST", "/api/missing-smr/%s/request-approval" % rej, role="requester",
             json={"client_name": "Синтетичен клиент"})
        step("msmr_client_reject", "PUT", "/api/missing-smr/%s/client-reject" % rej,
             role="requester", json={}, entity=rej, prefix="missing_smr.client_rejected")

        em = call("POST", "/api/missing-smr", role="requester",
                  json={**new, "urgency_type": "emergency"})["body"]["id"]
        step("msmr_execute_invalid", "PUT", "/api/missing-smr/%s/execute" % em,
             role="requester", json={})
        call("PUT", "/api/missing-smr/%s/status" % em, role="requester",
             json={"status": "reported"})
        step("msmr_execute", "PUT", "/api/missing-smr/%s/execute" % em, role="requester",
             json={"executed_date": "2026-11-16"}, entity=em, prefix="missing_smr.executed")

        step("msmr_ai_estimate", "POST", "/api/missing-smr/%s/ai-estimate" % em,
             role="requester", entity=em, prefix="missing_smr.ai_estimated")

        batch = []
        for _ in range(2):
            bid = call("POST", "/api/missing-smr", role="requester", json=new)["body"]["id"]
            call("PUT", "/api/missing-smr/%s/status" % bid, role="requester",
                 json={"status": "reported"})
            batch.append(bid)
        step("msmr_batch_forbidden", "POST", "/api/missing-smr/batch-to-offer",
             role="requester", json={"ids": batch})
        step("msmr_batch", "POST", "/api/missing-smr/batch-to-offer", role="owner",
             json={"ids": batch})
        obs["msmr_batch"]["per_item_events"] = {
            b: events("missing_smr.offer_created", b) for b in batch}

        dr = call("POST", "/api/missing-smr", role="requester", json=new)["body"]["id"]
        step("msmr_delete_invalid", "DELETE", "/api/missing-smr/%s" % item, role="requester")
        step("msmr_delete", "DELETE", "/api/missing-smr/%s" % dr, role="requester",
             entity=dr, prefix="missing_smr.deleted")

        # ── Assets QR ───────────────────────────────────────────────
        step("qr_generate", "POST", "/api/assets/qr/generate", role="admin",
             json={"entity_type": "guest", "name": "Синтетичен гост"},
             entity=lambda res: (res["body"] or {}).get("id"), prefix="asset_qr.generated")
        step("qr_generate_project", "POST", "/api/assets/qr/generate", role="admin",
             json={"entity_type": "project", "entity_id": P},
             entity=lambda res: (res["body"] or {}).get("id"), prefix="asset_qr.generated")
        step("qr_generate_project_again", "POST", "/api/assets/qr/generate", role="admin",
             json={"entity_type": "project", "entity_id": P},
             entity=lambda res: (res["body"] or {}).get("id"), prefix="asset_qr.generated")
        step("qr_generate_forbidden", "POST", "/api/assets/qr/generate", role="technician",
             json={"entity_type": "guest", "name": "x"})
        step("qr_generate_invalid_type", "POST", "/api/assets/qr/generate", role="admin",
             json={"entity_type": "spaceship", "name": "x"})
        step("qr_generate_invalid_noname", "POST", "/api/assets/qr/generate", role="admin",
             json={"entity_type": "guest"})
        step("qr_generate_other_tenant", "POST", "/api/assets/qr/generate", role="admin",
             json={"entity_type": "project", "entity_id": B["project_id"]})
        step("qr_bulk_forbidden", "POST", "/api/assets/qr/generate-bulk", role="technician",
             json={})
        step("qr_bulk", "POST", "/api/assets/qr/generate-bulk", role="admin", json={})
        obs["qr_bulk"]["bulk_events"] = [e for e in events("asset_qr.generated")
                                         if e["source_channel"] == "bulk"]
        gq = obs["qr_generate"]
        qr_id = q(lambda: op_db.asset_qr_codes.find_one({"id": gq["entity_id"]}))["qr_id"]
        step("qr_status", "PATCH", "/api/assets/qr/%s/status" % qr_id, role="admin",
             json={"status": "inactive"}, entity=gq["entity_id"],
             prefix="asset_qr.status_changed")
        obs["qr_status"]["stored"] = q(lambda: op_db.asset_qr_codes.find_one(
            {"qr_id": qr_id, "org_id": A["tenant_id"]}))["status"]
        step("qr_status_forbidden", "PATCH", "/api/assets/qr/%s/status" % qr_id,
             role="technician", json={"status": "active"})
        step("qr_status_invalid", "PATCH", "/api/assets/qr/%s/status" % qr_id, role="admin",
             json={"status": "gone"})
        step("qr_status_unknown", "PATCH", "/api/assets/qr/QR-999999/status", role="admin",
             json={"status": "active"})
        obs["qr_status_forbidden"]["stored"] = q(lambda: op_db.asset_qr_codes.find_one(
            {"qr_id": qr_id, "org_id": A["tenant_id"]}))["status"]

        from app.audit.store import verify_tenant_chain
        obs["chain_ok"] = list(q(lambda: verify_tenant_chain(op_db, A["tenant_id"])))
        client.close()

    out_json.write_text(json.dumps(obs, ensure_ascii=False, indent=1, sort_keys=True,
                                   default=str), encoding="utf-8")
    return obs


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 900) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "fixaud01-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="FIX-AUD-01 audit harness")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args(argv)
    if not args.mongo_url:
        print("no --mongo-url and no W0_03_REAL_MONGO_URL", file=sys.stderr)
        return 2
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    _pm01()._check_local(args.mongo_url)
    if args.child:
        run_harness(args.mongo_url, Path(args.out_json))
    else:
        run_in_child(args.mongo_url, Path(args.out_json))
    return 0


# ═══════════════════════════════════════════════════════════════════ real-Mongo tests
def _real_refusal() -> str:
    try:
        return _pm01()._real_refusal()
    except Exception as exc:                                   # noqa: BLE001
        return "refused: %s" % exc


pytestmark = pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")


@pytest.fixture(scope="module")
def obs(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixaud01") / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    return json.loads(out.read_text(encoding="utf-8"))


def _delta(o, key):
    return o["after"][key] - o["before"][key]


def _one_event(obs, name, actor_role, action, entity_type, flow, retention, project=True):
    o = obs[name]
    assert o["status"] in (200, 201), (name, o["status"], o["body"])
    assert len(o["events"]) == 1, (name, o["events"])
    e = o["events"][0]
    A = obs["fx"]["A"]
    assert e["action"] == action
    assert e["tenant_id"] == A["tenant_id"]
    assert e["actor_id"] == A["users"][actor_role]
    assert e["entity_type"] == entity_type and e["entity_id"] == o["entity_id"]
    assert e["source_flow"] == flow and e["retention_class"] == retention
    assert e["result"] == "success"
    if project:
        assert e["scope_id"] == A["project_id"]
    return e


def _nothing_written(o, *keys):
    for k in keys:
        assert _delta(o, k) == 0, (k, o["before"], o["after"])


# ── Missing SMR ─────────────────────────────────────────────────────────────
def test_create_records_exactly_one_event(obs):
    e = _one_event(obs, "msmr_create", "requester", "missing_smr.created", "missing_smr",
                   "FLOW-007", "R2")
    assert _delta(obs["msmr_create"], "missing_smr") == 1
    assert _delta(obs["msmr_create"], "msmr_events") == 1
    assert e["structured_diff"]["after"]["qty"] == 2
    assert e["structured_diff"]["after"]["status"] == "draft"


def test_create_forbidden_role_writes_nothing(obs):
    o = obs["msmr_create_forbidden"]
    assert o["status"] == 403
    _nothing_written(o, "missing_smr", "msmr_events")


@pytest.mark.parametrize("name,status", [("msmr_create_invalid_source", 400),
                                         ("msmr_create_invalid_body", 422),
                                         ("msmr_create_other_tenant_project", 404)])
def test_create_invalid_writes_nothing(obs, name, status):
    o = obs[name]
    assert o["status"] == status, o
    _nothing_written(o, "missing_smr", "msmr_events")


@pytest.mark.parametrize("name,action,retention", [
    ("msmr_update", "missing_smr.updated", "R2"),
    ("msmr_status", "missing_smr.status_changed", "R2"),
    ("msmr_attach", "missing_smr.attachment_added", "R2"),
    ("msmr_detach", "missing_smr.attachment_removed", "R2"),
    ("msmr_request_approval", "missing_smr.client_approval_requested", "R1"),
    ("msmr_client_approve", "missing_smr.client_approved", "R1"),
    ("msmr_client_reject", "missing_smr.client_rejected", "R1"),
    ("msmr_to_analysis", "missing_smr.sent_to_analysis", "R2"),
    ("msmr_execute", "missing_smr.executed", "R2"),
    ("msmr_ai_estimate", "missing_smr.ai_estimated", "R2"),
    ("msmr_delete", "missing_smr.deleted", "R2"),
])
def test_every_missing_smr_write_records_one_event(obs, name, action, retention):
    _one_event(obs, name, "requester", action, "missing_smr", "FLOW-007", retention)
    assert _delta(obs[name], "msmr_events") == 1


def test_update_and_status_diffs(obs):
    u = obs["msmr_update"]["events"][0]["structured_diff"]
    assert u == {"before": {"qty": 2}, "after": {"qty": 5}}
    s = obs["msmr_status"]["events"][0]["structured_diff"]
    assert s == {"before": {"status": "draft"}, "after": {"status": "reported"}}


def test_to_offer_records_one_r1_event_with_the_offer(obs):
    e = _one_event(obs, "msmr_to_offer", "owner", "missing_smr.offer_created", "missing_smr",
                   "FLOW-007", "R1")
    assert _delta(obs["msmr_to_offer"], "offers") == 1
    assert e["structured_diff"]["after"]["linked_offer_id"]


def test_to_offer_forbidden_role_writes_nothing(obs):
    o = obs["msmr_to_offer_forbidden"]
    assert o["status"] == 403
    _nothing_written(o, "offers", "msmr_events")


def test_batch_to_offer_records_one_event_per_item(obs):
    o = obs["msmr_batch"]
    assert o["status"] == 200 and _delta(o, "offers") == 1
    assert _delta(o, "msmr_events") == 2
    for evs in o["per_item_events"].values():
        assert len(evs) == 1 and evs[0]["actor_id"] == obs["fx"]["A"]["users"]["owner"]
        assert evs[0]["structured_diff"]["after"]["batch"] is True


def test_batch_to_offer_forbidden_role_writes_nothing(obs):
    o = obs["msmr_batch_forbidden"]
    assert o["status"] == 403
    _nothing_written(o, "offers", "msmr_events")


@pytest.mark.parametrize("name", ["msmr_status_invalid", "msmr_execute_invalid",
                                  "msmr_delete_invalid"])
def test_refused_transition_writes_no_event(obs, name):
    o = obs[name]
    assert o["status"] == 400, o
    _nothing_written(o, "missing_smr", "msmr_events")


def test_removing_an_absent_attachment_records_nothing(obs):
    o = obs["msmr_detach_absent"]
    assert o["status"] == 200
    _nothing_written(o, "msmr_events")


# ── Assets QR ───────────────────────────────────────────────────────────────
def test_qr_generate_records_exactly_one_event(obs):
    e = _one_event(obs, "qr_generate", "admin", "asset_qr.generated", "asset_qr", "FLOW-011",
                   "R2", project=False)
    o = obs["qr_generate"]
    assert _delta(o, "asset_qr_codes") == 1 and _delta(o, "qr_events") == 1
    assert e["structured_diff"]["after"]["entity_type"] == "guest"
    assert e["structured_diff"]["after"]["qr_id"].startswith("QR-")


def test_qr_generate_idempotent_repeat_records_no_second_event(obs):
    first, again = obs["qr_generate_project"], obs["qr_generate_project_again"]
    _one_event(obs, "qr_generate_project", "admin", "asset_qr.generated", "asset_qr",
               "FLOW-011", "R2", project=False)
    assert again["status"] == 200 and again["entity_id"] == first["entity_id"]
    _nothing_written(again, "asset_qr_codes", "qr_seq", "qr_events")


def test_qr_generate_forbidden_role_writes_nothing(obs):
    o = obs["qr_generate_forbidden"]
    assert o["status"] == 403
    _nothing_written(o, "asset_qr_codes", "qr_seq", "qr_events")


@pytest.mark.parametrize("name,status", [("qr_generate_invalid_type", 400),
                                         ("qr_generate_invalid_noname", 400),
                                         ("qr_generate_other_tenant", 404)])
def test_qr_generate_invalid_writes_nothing(obs, name, status):
    o = obs[name]
    assert o["status"] == status, o
    _nothing_written(o, "asset_qr_codes", "qr_seq", "qr_events")


def test_qr_bulk_records_one_event_per_created_qr(obs):
    o = obs["qr_bulk"]
    assert o["status"] == 200
    made = _delta(o, "asset_qr_codes")
    assert made > 0
    assert _delta(o, "qr_events") == made == len(o["bulk_events"])
    A = obs["fx"]["A"]
    assert all(e["tenant_id"] == A["tenant_id"] and e["actor_id"] == A["users"]["admin"]
               for e in o["bulk_events"])
    assert len({e["entity_id"] for e in o["bulk_events"]}) == made


def test_qr_bulk_forbidden_role_writes_nothing(obs):
    o = obs["qr_bulk_forbidden"]
    assert o["status"] == 403
    _nothing_written(o, "asset_qr_codes", "qr_seq", "qr_events")


def test_qr_status_records_one_event(obs):
    e = _one_event(obs, "qr_status", "admin", "asset_qr.status_changed", "asset_qr",
                   "FLOW-011", "R2", project=False)
    assert e["structured_diff"]["before"]["status"] == "active"
    assert e["structured_diff"]["after"]["status"] == "inactive"
    assert obs["qr_status"]["stored"] == "inactive"


def test_qr_status_forbidden_role_changes_nothing(obs):
    o = obs["qr_status_forbidden"]
    assert o["status"] == 403 and o["stored"] == "inactive"
    _nothing_written(o, "qr_events")


@pytest.mark.parametrize("name,status", [("qr_status_invalid", 400),
                                         ("qr_status_unknown", 404)])
def test_qr_status_invalid_records_nothing(obs, name, status):
    o = obs[name]
    assert o["status"] == status, o
    _nothing_written(o, "qr_events")


def test_the_tenant_chain_stays_valid(obs):
    assert obs["chain_ok"][0] is True, obs["chain_ok"]


if __name__ == "__main__":
    sys.exit(main())
