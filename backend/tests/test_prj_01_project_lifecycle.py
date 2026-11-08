"""
PRJ-01 — projects: no hard delete, controlled reopen, warranty to the original project,
subcontractor rating with rights / versions / AuditEvent and "paid" from the ledger.

Package: ``docs/architecture/tasks/PRJ-01_PROJECT_NO_DELETE_REOPEN_WARRANTY.md`` (branch
``claude/happy-meitner-bmcnel``), decision R54 (``RECOVERY_EXECUTION_PROPOSAL_2026-10-17.md``).
Findings: FLOW Guard FG-236..FG-240 (``docs/flow-guard/DIVERGENCES.md`` @ ``claude/flow-guard``).
Canon: CLAUDE.md §2 rule 9, §4, §14, §15; FLOW-001 P-04, P-06, P-07, P-08, P-09, P-13;
FLOW-018 (consolidated into FLOW-039); FLOW-006 (one Payment ledger).

Every scenario runs through the WHOLE application (``server.app``) on a disposable LOCAL
MongoDB replica set (two fresh scratch databases, dropped afterwards), with the ST-01
synthetic tenants A and B, real logins and real JWTs. The child process writes one JSON of
observations; each test below checks one rule against it.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_prj_01_project_lifecycle.py -q --noconftest -rs
    # the evidence:
    PYTHONPATH=. python tests/test_prj_01_project_lifecycle.py --harness \\
        --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
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
REPO = BACKEND.parent
EVIDENCE = REPO / "docs" / "evidence" / "PRJ-01"
RESULTS_JSON = EVIDENCE / "results.json"
DB_PREFIX_OP, DB_PREFIX_SYS = "prj01_op_", "prj01_sys_"
SYNTH_PASSWORD = "PRJ01-Synthetic-Pass-2026!"     # synthetic users of a scratch database
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant", "viewer")
NOW = "2026-11-08T08:00:00+00:00"

# FG-239: one fresh Draft project per kind of business link (collection, extra fields).
LINKS = {
    "offer": ("offers", {"status": "Draft", "offer_no": "PRB-OF"}),
    "client_act": ("client_acts", {"status": "Draft", "act_number": "PRB-ACT"}),
    "invoice": ("invoices", {"status": "Draft", "direction": "Issued", "invoice_no": "PRB-1"}),
    "payment": ("finance_payments", {"direction": "Inflow", "amount": 10, "status": "posted"}),
    "warehouse": ("warehouse_transactions", {"type": "issue", "qty": 1}),
    "work_report": ("work_reports", {"status": "Draft", "date": "2026-11-02"}),
    "photo": ("project_photos", {"url": "/x", "stored_filename": "none.jpg"}),
    "file": ("media_files", {"filename": "f.pdf"}),
    "labor": ("labor_entries", {"hours": 1, "date": "2026-11-02"}),
    "subcontract": ("subcontractor_packages", {"status": "draft"}),
    "attendance": ("attendance_entries", {"date": "2026-11-02"}),
    "material_waste": ("material_waste_entries", {"qty": 1}),
    "child_project": ("projects", {"code": "PRB-CHILD", "name": "child", "status": "Draft",
                                    "type": "Billable"}),
}


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "prj01_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pid(tkey: str, name: str) -> str:
    return "prj01-%s-%s" % (tkey, name)


async def seed(op_db, fx: Dict[str, Any]) -> None:
    """Per tenant: projects in every lifecycle state the scenarios need; one Draft project
    per link kind with its linked row; a subcontractor, ledger payments and a legacy
    performance row with a MANUAL ``actual_paid_amount``. Every row has the tenant's org_id."""
    for name in ("audit_logs", "audit_events", "dq_issues", "project_photos",
                 "subcontractor_performance"):
        if name not in await op_db.list_collection_names():
            await op_db.create_collection(name)
    for tkey, t in fx.items():
        org = t["tenant_id"]

        def project(name, status, ptype="Billable", **extra):
            return {"id": pid(tkey, name), "org_id": org, "code": "PRB-%s-%s" % (tkey, name),
                    "name": "Probe %s %s" % (tkey, name), "status": status, "type": ptype,
                    "created_at": NOW, "updated_at": NOW, **extra}

        docs = [project("completed", "Completed"), project("completed2", "Completed"),
                project("completed3", "Completed"), project("active_empty", "Active"),
                project("draft_empty", "Draft"), project("draft_cancel", "Draft"),
                project("type_empty", "Draft"), project("type_used", "Active"),
                project("warr_parent", "Completed", "Warranty",
                        parent_project_id=t["project_id"]),
                project("warr_orphan", "Completed", "Warranty")]
        for kind in LINKS:
            docs.append(project("link_" + kind, "Draft"))
        await op_db.projects.insert_many(docs)
        for kind, (coll, extra) in LINKS.items():
            row = {"id": pid(tkey, "row_" + kind), "org_id": org, "created_at": NOW, **extra}
            if kind == "child_project":
                row["parent_project_id"] = pid(tkey, "link_" + kind)
            else:
                row["project_id"] = pid(tkey, "link_" + kind)
            await op_db[coll].insert_one(row)
        await op_db.work_reports.insert_one({"id": pid(tkey, "wr_type_used"), "org_id": org,
                                             "project_id": pid(tkey, "type_used"),
                                             "status": "Draft", "created_at": NOW})
        # FG-240: a subcontractor, its payments in the ONE ledger (one counted 150, one
        # 50 reversed by its reversal row), and a legacy record with a manual 999.
        sub = pid(tkey, "sub")
        await op_db.subcontractors.insert_one({"id": sub, "org_id": org, "name": "Probe Sub",
                                               "created_at": NOW})
        p1 = t["project_id"]
        for n, amount, status in (("sp1", 150, "posted"), ("sp2", 50, "reversed")):
            await op_db.subcontractor_payments.insert_one({
                "id": pid(tkey, n), "org_id": org, "project_id": p1, "subcontractor_id": sub,
                "amount": amount, "status": "completed", "created_at": NOW})
            await op_db.finance_payments.insert_one({
                "id": pid(tkey, "fp_" + n), "org_id": org, "direction": "Outflow",
                "amount": amount, "project_id": p1, "status": status,
                "subcontractor_payment_id": pid(tkey, n), "created_at": NOW})
        await op_db.finance_payments.insert_one({
            "id": pid(tkey, "fp_sp2_rev"), "org_id": org, "direction": "Inflow", "amount": 50,
            "project_id": p1, "status": "reversal", "reversal_of": pid(tkey, "fp_sp2"),
            "subcontractor_payment_id": pid(tkey, "sp2"), "created_at": NOW})
        await op_db.subcontractor_performance.insert_one({
            "id": pid(tkey, "perf_legacy"), "org_id": org, "subcontractor_id": sub,
            "project_id": p1, "promised_amount": 100, "actual_paid_amount": 999,
            "quality_score": 3, "rework_flag": False, "status": "unknown",
            "created_at": NOW, "updated_at": NOW})


# ═══════════════════════════════════════════════════════════════════════════ harness
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
        tc.portal.call(lambda: pm.seed_existing_records(op_db, fx))
        tc.portal.call(lambda: seed(op_db, fx))
        tokens: Dict[tuple, str] = {}
        for tkey in ("A", "B"):
            for key in ROLE_KEYS:
                r = tc.post("/api/auth/login", json={
                    "email": fx[tkey]["users"][key]["email"], "password": SYNTH_PASSWORD})
                assert r.status_code == 200, (tkey, key, r.status_code, r.text[:200])
                tokens[(tkey, key)] = r.json()["token"]
        A = fx["A"]
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        # P1's team: the SiteManager (requester) and the Technician are members.
        for ukey, rip in (("requester", "SiteManager"), ("technician", "Technician")):
            r = tc.post("/api/projects/%s/team" % A["project_id"],
                        json={"user_id": A["users"][ukey]["id"], "role_in_project": rip},
                        headers={"Authorization": "Bearer " + tokens[("A", "admin")]})
            assert r.status_code == 201, (ukey, r.status_code, r.text[:300])

        def call(method, url, role="owner", tkey="A", key: Optional[str] = "auto", **kw):
            headers = {"Authorization": "Bearer " + tokens[(tkey, role)]}
            if key == "auto":
                key = uuid.uuid4().hex
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

        def project_doc(name, tkey="A"):
            return q(lambda: op_db.projects.find_one({"id": pid(tkey, name)}, {"_id": 0}))

        def events(entity_id, action_prefix):
            rows = q(lambda: op_db.audit_events.find(
                {"entity_id": entity_id}, {"_id": 0}).to_list(None))
            return [{"action": e.get("action"), "reason": e.get("reason"),
                     "tenant_id": e.get("tenant_id"), "source_flow": e.get("source_flow"),
                     "idempotency_key": e.get("idempotency_key"),
                     "diff": e.get("structured_diff")}
                    for e in rows if str(e.get("action", "")).startswith(action_prefix)]

        # ─────────────────────────────────────────────── FG-239 — no hard delete
        d: Dict[str, Any] = {}
        for kind, (coll, _extra) in LINKS.items():
            r = call("DELETE", "/api/projects/" + pid("A", "link_" + kind))
            d["link_" + kind] = {
                "status": r["status"], "error_code": r["error_code"],
                "links": (r["body"].get("detail") or {}).get("links")
                if isinstance(r["body"], dict) and isinstance(r["body"].get("detail"), dict)
                else None,
                "project_kept": project_doc("link_" + kind) is not None,
                "row_kept": q(lambda: op_db[coll].count_documents(
                    {"id": pid("A", "row_" + kind)})) == 1}
        r = call("DELETE", "/api/projects/" + pid("A", "active_empty"))
        d["active_empty"] = {"status": r["status"], "error_code": r["error_code"],
                             "project_kept": project_doc("active_empty") is not None}
        r = call("DELETE", "/api/projects/" + pid("A", "completed3"), key=None)
        d["no_key"] = {"status": r["status"], "error_code": r["error_code"],
                       "project_kept": project_doc("completed3") is not None}
        for role in ("requester", "viewer", "technician", "accountant"):
            r = call("DELETE", "/api/projects/" + pid("A", "draft_empty"), role=role)
            d["role_" + role] = {"status": r["status"],
                                 "project_kept": project_doc("draft_empty") is not None}
        r = call("DELETE", "/api/projects/" + pid("A", "draft_empty"), tkey="B")
        d["cross_tenant"] = {"status": r["status"],
                             "project_kept": project_doc("draft_empty") is not None}
        k = uuid.uuid4().hex
        r = call("DELETE", "/api/projects/" + pid("A", "draft_empty"), key=k)
        r2 = call("DELETE", "/api/projects/" + pid("A", "draft_empty"), key=k)
        d["empty_draft"] = {"status": r["status"], "replay_status": r2["status"],
                            "replay_same": r2["body"] == r["body"],
                            "project_kept": project_doc("draft_empty") is not None,
                            "events": events(pid("A", "draft_empty"), "project.")}
        # archive / cancel instead of delete
        r_noreason = call("POST", "/api/projects/%s/archive" % pid("A", "completed2"), json={})
        r_sm = call("POST", "/api/projects/%s/archive" % pid("A", "completed2"),
                    role="requester", json={"reason": "приключен"})
        r_nokey = call("POST", "/api/projects/%s/archive" % pid("A", "completed2"), key=None,
                       json={"reason": "приключен"})
        k = uuid.uuid4().hex
        r_ok = call("POST", "/api/projects/%s/archive" % pid("A", "completed2"), key=k,
                    json={"reason": "приключен и платен"})
        r_rep = call("POST", "/api/projects/%s/archive" % pid("A", "completed2"), key=k,
                     json={"reason": "приключен и платен"})
        r_active = call("POST", "/api/projects/%s/archive" % pid("A", "type_used"),
                        json={"reason": "x"})
        doc = project_doc("completed2") or {}
        d["archive"] = {"no_reason": r_noreason["status"], "site_manager": r_sm["status"],
                        "no_key": r_nokey["status"], "ok": r_ok["status"],
                        "replay": r_rep["status"], "replay_same": r_rep["body"] == r_ok["body"],
                        "from_active": r_active["status"],
                        "from_active_code": r_active["error_code"],
                        "status": doc.get("status"), "reason": doc.get("archived_reason"),
                        "events": events(pid("A", "completed2"), "project.")}
        r = call("POST", "/api/projects/%s/cancel" % pid("A", "draft_cancel"),
                 json={"reason": "клиентът се отказа"})
        doc = project_doc("draft_cancel") or {}
        d["cancel"] = {"status": r["status"], "project_status": doc.get("status"),
                       "reason": doc.get("cancelled_reason"),
                       "events": events(pid("A", "draft_cancel"), "project.")}
        # the generic PUT may no longer archive/cancel without a reason (P-07, rule 9)
        r = call("PUT", "/api/projects/%s" % A["project_id"], role="requester",
                 json={"status": "Paused"})
        r_put = call("PUT", "/api/projects/%s" % A["project_id"], role="requester",
                     json={"status": "Cancelled"})
        d["put_cancel_by_site_manager"] = {
            "pause": r["status"], "status": r_put["status"], "error_code": r_put["error_code"],
            "project_status": (q(lambda: op_db.projects.find_one(
                {"id": A["project_id"]}, {"_id": 0, "status": 1})) or {}).get("status")}
        call("PUT", "/api/projects/%s" % A["project_id"], role="owner", json={"status": "Active"})
        obs["fg239"] = d

        # ─────────────────────────────────────────────── FG-237 — reopen
        d = {}
        url = "/api/projects/%s/reopen" % pid("A", "completed")
        d["no_reason"] = call("POST", url, json={"kind": "warranty"})["status"]
        d["bad_kind"] = call("POST", url, json={"kind": "x", "reason": "дефект"})["status"]
        d["no_key"] = call("POST", url, key=None,
                           json={"kind": "warranty", "reason": "теч"})["status"]
        for role in ("requester", "technician", "viewer", "accountant"):
            d["role_" + role] = call("POST", url, role=role,
                                     json={"kind": "warranty", "reason": "теч"})["status"]
        d["cross_tenant"] = call("POST", url, tkey="B",
                                 json={"kind": "warranty", "reason": "теч"})["status"]
        d["status_before"] = (project_doc("completed") or {}).get("status")
        from app.services.project_guards import check_project_writable

        async def writable(name):
            try:
                await check_project_writable(pid("A", name), A["tenant_id"], "отчети")
                return True
            except Exception:                                   # noqa: BLE001
                return False
        d["writable_before"] = q(lambda: writable("completed"))
        k = uuid.uuid4().hex
        body = {"kind": "warranty", "reason": "теч в банята след приемане"}
        r = call("POST", url, key=k, json=body)
        r2 = call("POST", url, key=k, json=body)
        doc = project_doc("completed") or {}
        d.update({"ok": r["status"], "replay": r2["status"], "replay_same": r2["body"] == r["body"],
                  "status_after": doc.get("status"),
                  "cycles": [{k2: c.get(k2) for k2 in ("kind", "reason", "closed_at")}
                             for c in doc.get("reopen_cycles") or []],
                  "current_reopen_id": bool(doc.get("current_reopen_id")),
                  "writable_after": q(lambda: writable("completed")),
                  "events": events(pid("A", "completed"), "project.")})
        d["again_while_active"] = call("POST", url, json=body)["status"]
        # close again (P-08 „След работата се затваря отново“)
        r = call("PUT", "/api/projects/%s" % pid("A", "completed"), json={"status": "Completed"})
        doc = project_doc("completed") or {}
        d["reclose"] = r["status"]
        d["cycles_after_close"] = [{"kind": c.get("kind"), "closed": bool(c.get("closed_at"))}
                                   for c in doc.get("reopen_cycles") or []]
        d["current_reopen_after_close"] = bool(doc.get("current_reopen_id"))
        # the PUT path still refuses Completed -> Active (only the reopen endpoint)
        d["put_reopen"] = call("PUT", "/api/projects/%s" % pid("A", "completed"),
                               json={"status": "Active"})["status"]
        # enforce: the Owner may, the Viewer may not
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        d["enforce_viewer"] = call("POST", url, role="viewer", json=body)["status"]
        d["enforce_owner"] = call("POST", url, json={"kind": "defect",
                                                    "reason": "втори дефект"})["status"]
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        obs["fg237"] = d

        # ─────────────────────────────────────────────── FG-238 — photos
        d = {}
        up = tc.post("/api/projects/%s/photos" % A["project_id"],
                     headers={"Authorization": "Bearer " + tokens[("A", "technician")]},
                     files={"file": ("p.jpg", b"\xff\xd8\xff\xe0prj01", "image/jpeg")},
                     data={"note": "преди"})
        d["upload"] = up.status_code
        photo = up.json() if up.status_code == 201 else {}
        photo_path = Path("/app/backend/uploads/projects") / str(photo.get("stored_filename"))
        purl = "/api/projects/photos/%s" % photo.get("id")
        d["other_user"] = call("DELETE", purl, role="requester",
                               json={"reason": "грешна снимка"})["status"]
        d["no_reason"] = call("DELETE", purl, role="technician", json={})["status"]
        d["no_key"] = call("DELETE", purl, role="technician", key=None,
                           json={"reason": "грешна снимка"})["status"]
        r = call("DELETE", purl, role="technician", json={"reason": "грешна снимка"})
        row = q(lambda: op_db.project_photos.find_one({"id": photo.get("id")}, {"_id": 0})) or {}
        listing = call("GET", "/api/projects/%s/photos" % A["project_id"], key=None)
        d.update({"retire": r["status"], "row_kept": bool(row),
                  "row_status": row.get("status"), "row_reason": row.get("retired_reason"),
                  "file_kept": photo_path.exists(),
                  "listed": any(p.get("id") == photo.get("id") for p in listing["body"]
                                if isinstance(p, dict)) if isinstance(listing["body"], list)
                  else None,
                  "events": events(photo.get("id"), "project.photo")})
        obs["fg238"] = d

        # ─────────────────────────────────────────────── FG-236 — warranty
        d = {}
        r = call("POST", "/api/projects", json={"code": "PRB-W-NEW", "name": "Нова гаранция",
                                                "type": "Warranty"})
        d["create_warranty"] = {"status": r["status"], "error_code": r["error_code"],
                                "written": q(lambda: op_db.projects.count_documents(
                                    {"code": "PRB-W-NEW"}))}
        r = call("POST", "/api/projects", json={"code": "PRB-B-NEW", "name": "Нов", "type":
                                                "Billable"})
        d["create_billable"] = r["status"]
        r = call("PUT", "/api/projects/%s" % pid("A", "type_used"), json={"type": "Overhead"})
        d["type_used"] = {"status": r["status"], "error_code": r["error_code"],
                          "type": (project_doc("type_used") or {}).get("type")}
        r = call("PUT", "/api/projects/%s" % pid("A", "type_empty"), json={"type": "Warranty"})
        d["to_warranty"] = {"status": r["status"], "error_code": r["error_code"],
                            "type": (project_doc("type_empty") or {}).get("type")}
        r = call("PUT", "/api/projects/%s" % pid("A", "type_empty"), json={"type": "Overhead"})
        d["type_empty"] = {"status": r["status"],
                           "type": (project_doc("type_empty") or {}).get("type")}
        # the migration: dry run -> approval (plan hash) -> apply; twice; nothing deleted
        try:
            from scripts import prj_01_warranty_link_migration as mig
        except Exception as exc:                                # noqa: BLE001
            d["migration"] = {"available": False, "error": type(exc).__name__}
        else:
            before = q(lambda: op_db.projects.count_documents({}))
            audit_before = q(lambda: op_db.audit_events.count_documents({}))
            dry = q(lambda: mig.migrate(op_db, apply=False))
            after_dry = q(lambda: op_db.projects.count_documents(
                {"warranty_of_project_id": {"$exists": True}}))
            refused = None
            try:
                q(lambda: mig.migrate(op_db, apply=True, approved_by="Крум",
                                      plan_sha="0" * 64))
            except Exception as exc:                            # noqa: BLE001
                refused = type(exc).__name__
            first = q(lambda: mig.migrate(op_db, apply=True, approved_by="Крум",
                                          plan_sha=dry["plan_sha"]))
            dry2 = q(lambda: mig.migrate(op_db, apply=False))
            second = q(lambda: mig.migrate(op_db, apply=True, approved_by="Крум",
                                           plan_sha=dry2["plan_sha"]))
            wp = project_doc("warr_parent") or {}
            wo = project_doc("warr_orphan") or {}
            wpb = project_doc("warr_parent", "B") or {}
            dq = q(lambda: op_db.dq_issues.find({"entity_id": pid("A", "warr_orphan")},
                                                {"_id": 0}).to_list(None))
            d["migration"] = {
                "available": True,
                "dry_counts": dry["counts"], "dry_wrote": after_dry,
                "wrong_plan_refused": refused,
                "first_counts": first["counts"], "second_counts": second["counts"],
                "projects_before": before,
                "projects_after": q(lambda: op_db.projects.count_documents({})),
                "parent_linked_to": wp.get("warranty_of_project_id"),
                "parent_expected": A["project_id"],
                "parent_type": wp.get("type"),
                "b_linked_to_own": wpb.get("warranty_of_project_id") == fx["B"]["project_id"],
                "orphan_linked": wo.get("warranty_of_project_id"),
                "orphan_dq": [{"type": x.get("type"), "status": x.get("status")} for x in dq],
                "audit_new": q(lambda: op_db.audit_events.count_documents({})) - audit_before,
                "link_events": len(events(pid("A", "warr_parent"), "project.warranty_link")),
            }
        obs["fg236"] = d

        # ─────────────────────────────────────────────── FG-240 — subcontractor rating
        d = {}
        sub, p1 = pid("A", "sub"), A["project_id"]
        body = {"subcontractor_id": sub, "project_id": p1, "promised_amount": 100,
                "quality_score": 4, "rework_flag": False, "notes": "добре"}
        for role in ("viewer", "technician", "accountant"):
            r = call("POST", "/api/subcontractor-performance", role=role, json=body)
            d["create_" + role] = r["status"]
        d["create_site_manager_p2"] = call(
            "POST", "/api/subcontractor-performance", role="requester",
            json={**body, "project_id": fx["A"]["project2_id"]})["status"]
        d["create_paid_field"] = call("POST", "/api/subcontractor-performance",
                                      json={**body, "actual_paid_amount": 5})["status"]
        d["create_no_key"] = call("POST", "/api/subcontractor-performance", key=None,
                                  json=body)["status"]
        d["create_unknown_sub"] = call("POST", "/api/subcontractor-performance",
                                       json={**body, "subcontractor_id": "nope"})["status"]
        r = call("POST", "/api/subcontractor-performance", role="requester", json=body)
        d["create_site_manager"] = r["status"]
        rec = r["body"] if r["status"] == 201 and isinstance(r["body"], dict) else {}
        rid = rec.get("id")
        d["created_version"] = rec.get("version")
        purl = "/api/subcontractor-performance/%s" % rid
        d["update_viewer"] = call("PUT", purl, role="viewer", json={"quality_score": 1})["status"]
        d["update_paid_field"] = call("PUT", purl, json={"actual_paid_amount": 1})["status"]
        k = uuid.uuid4().hex
        r = call("PUT", purl, key=k, json={"quality_score": 2, "rework_flag": True})
        r2 = call("PUT", purl, key=k, json={"quality_score": 2, "rework_flag": True})
        d["update_owner"] = r["status"]
        d["update_replay_same"] = r2["status"] == r["status"] and r2["body"] == r["body"]
        doc = q(lambda: op_db.subcontractor_performance.find_one({"id": rid}, {"_id": 0})) or {}
        d["version_after"] = doc.get("version")
        d["versions"] = sorted(v.get("version") for v in q(
            lambda: op_db.subcontractor_performance_versions.find(
                {"record_id": rid}, {"_id": 0}).to_list(None)))
        d["events"] = [e["action"] for e in events(rid, "subcontractor_performance")]
        listing = call("GET", "/api/subcontractor-performance?project_id=%s" % p1, key=None)
        items = (listing["body"] or {}).get("items", []) if isinstance(listing["body"], dict) else []
        legacy = next((i for i in items if i.get("id") == pid("A", "perf_legacy")), {})
        d["legacy_paid_shown"] = legacy.get("actual_paid_amount")
        d["legacy_manual_kept"] = (q(lambda: op_db.subcontractor_performance.find_one(
            {"id": pid("A", "perf_legacy")}, {"_id": 0})) or {}).get("actual_paid_amount")
        d["legacy_manual_exposed"] = legacy.get("legacy_manual_paid_amount")
        d["legacy_paid_source"] = legacy.get("actual_paid_source")
        obs["fg240"] = d

    out_json.write_text(json.dumps(obs, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                        encoding="utf-8")
    return obs


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 1800) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "prj01-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="PRJ-01 project lifecycle evidence")
    parser.add_argument("--harness", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-json", default=str(RESULTS_JSON))
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
    out = tmp_path_factory.mktemp("prj01") / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    return json.loads(out.read_text(encoding="utf-8"))


def _actions(events):
    return [e["action"] for e in events]


@real
def test_fg239_a_project_with_any_business_link_is_never_deleted(obs):
    d = obs["fg239"]
    for kind in LINKS:
        cell = d["link_" + kind]
        assert cell["status"] == 409, (kind, cell)
        assert cell["error_code"] == "PROJECT_HAS_HISTORY", (kind, cell)
        assert cell["project_kept"] and cell["row_kept"], (kind, cell)
        assert cell["links"], (kind, cell)


@real
def test_fg239_only_an_empty_draft_may_be_deleted_by_owner_admin_with_a_key(obs):
    d = obs["fg239"]
    assert d["active_empty"]["status"] == 409 and d["active_empty"]["project_kept"]
    assert d["active_empty"]["error_code"] == "PROJECT_NOT_DRAFT"
    assert d["no_key"]["status"] == 428 and d["no_key"]["project_kept"]
    for role in ("requester", "viewer", "technician", "accountant"):
        assert d["role_" + role] == {"status": 403, "project_kept": True}, role
    assert d["cross_tenant"] == {"status": 404, "project_kept": True}
    e = d["empty_draft"]
    assert e["status"] == 200 and not e["project_kept"]
    assert e["replay_status"] == 200 and e["replay_same"]
    assert _actions(e["events"]) == ["project.delete"]


@real
def test_fg239_archive_and_cancel_carry_reason_rights_key_and_audit_event(obs):
    a = obs["fg239"]["archive"]
    assert a["no_reason"] == 400
    assert a["site_manager"] == 403
    assert a["no_key"] == 428
    assert a["ok"] == 200 and a["replay"] == 200 and a["replay_same"]
    assert a["from_active"] == 409 and a["from_active_code"] == "INVALID_TRANSITION"
    assert a["status"] == "Archived" and a["reason"] == "приключен и платен"
    assert _actions(a["events"]) == ["project.archive"]
    ev = a["events"][0]
    assert ev["reason"] == "приключен и платен" and ev["source_flow"] == "FLOW-001"
    assert ev["diff"] == {"before": {"status": "Completed"}, "after": {"status": "Archived"}}
    c = obs["fg239"]["cancel"]
    assert c["status"] == 200 and c["project_status"] == "Cancelled"
    assert c["reason"] == "клиентът се отказа"
    assert _actions(c["events"]) == ["project.cancel"]
    p = obs["fg239"]["put_cancel_by_site_manager"]
    assert p["pause"] == 200
    assert p["status"] == 409 and p["error_code"] == "USE_LIFECYCLE_ENDPOINT"
    assert p["project_status"] == "Paused"


@real
def test_fg237_a_completed_project_reopens_with_reason_audit_and_owner_admin_only(obs):
    d = obs["fg237"]
    assert d["status_before"] == "Completed" and d["writable_before"] is False
    assert d["no_reason"] == 400 and d["bad_kind"] == 400 and d["no_key"] == 428
    for role in ("requester", "technician", "viewer", "accountant"):
        assert d["role_" + role] == 403, role
    assert d["cross_tenant"] == 404
    assert d["ok"] == 200 and d["replay"] == 200 and d["replay_same"]
    assert d["status_after"] == "Active" and d["writable_after"] is True
    assert d["cycles"] == [{"kind": "warranty", "reason": "теч в банята след приемане",
                            "closed_at": None}]
    assert d["current_reopen_id"] is True
    assert _actions(d["events"]) == ["project.reopen"]
    ev = d["events"][0]
    assert ev["reason"] == "теч в банята след приемане" and ev["source_flow"] == "FLOW-001"
    assert ev["diff"]["before"] == {"status": "Completed"}
    assert ev["diff"]["after"]["status"] == "Active" and ev["diff"]["after"]["kind"] == "warranty"
    assert d["again_while_active"] == 409
    assert d["reclose"] == 200
    assert d["cycles_after_close"] == [{"kind": "warranty", "closed": True}]
    assert d["current_reopen_after_close"] is False
    assert d["put_reopen"] == 400
    assert d["enforce_viewer"] == 403 and d["enforce_owner"] == 200


@real
def test_fg238_a_project_photo_is_retired_never_deleted(obs):
    d = obs["fg238"]
    assert d["upload"] == 201
    assert d["other_user"] == 403 and d["no_reason"] == 400 and d["no_key"] == 428
    assert d["retire"] == 200
    assert d["row_kept"] and d["row_status"] == "retired" and d["row_reason"] == "грешна снимка"
    assert d["file_kept"] is True
    assert d["listed"] is False
    assert _actions(d["events"]) == ["project.photo.retire"]


@real
def test_fg236_no_new_warranty_project_and_the_type_is_locked_after_the_first_record(obs):
    d = obs["fg236"]
    assert d["create_warranty"] == {"status": 409, "error_code": "WARRANTY_IN_ORIGINAL_PROJECT",
                                    "written": 0}
    assert d["create_billable"] == 201
    assert d["type_used"] == {"status": 409, "error_code": "PROJECT_TYPE_LOCKED",
                              "type": "Billable"}
    assert d["to_warranty"] == {"status": 409, "error_code": "WARRANTY_IN_ORIGINAL_PROJECT",
                                "type": "Billable"}
    assert d["type_empty"] == {"status": 200, "type": "Overhead"}


@real
def test_fg236_the_warranty_migration_links_dry_run_first_idempotent_never_deletes(obs):
    m = obs["fg236"]["migration"]
    assert m["available"] is True, m
    assert m["dry_wrote"] == 0
    assert m["dry_counts"] == {"link": 2, "dq": 2, "already": 0}
    assert m["wrong_plan_refused"] == "PlanMismatch"
    assert m["first_counts"] == {"link": 2, "dq": 2, "already": 0}
    assert m["second_counts"] == {"link": 0, "dq": 0, "already": 2, "dq_open": 2}
    assert m["projects_after"] == m["projects_before"]
    assert m["parent_linked_to"] == m["parent_expected"] and m["parent_type"] == "Warranty"
    assert m["b_linked_to_own"] is True
    assert m["orphan_linked"] is None
    assert m["orphan_dq"] == [{"type": "PROJECT_WARRANTY_ORIGINAL_UNKNOWN", "status": "open"}]
    assert m["link_events"] == 1
    assert m["audit_new"] == 4          # 2 links + 2 DQ issues, tenants A and B; none twice


@real
def test_fg240_rating_rights_versions_audit_and_paid_from_the_ledger(obs):
    d = obs["fg240"]
    for role in ("viewer", "technician", "accountant"):
        assert d["create_" + role] == 403, role
    assert d["create_site_manager_p2"] == 403
    assert d["create_paid_field"] == 422
    assert d["create_no_key"] == 428
    assert d["create_unknown_sub"] == 422
    assert d["create_site_manager"] == 201 and d["created_version"] == 1
    assert d["update_viewer"] == 403 and d["update_paid_field"] == 422
    assert d["update_owner"] == 200 and d["update_replay_same"]
    assert d["version_after"] == 2 and d["versions"] == [1, 2]
    assert d["events"] == ["subcontractor_performance.create", "subcontractor_performance.update"]
    assert d["legacy_paid_shown"] == 150          # 150 counted, 50 reversed: from the ledger
    assert d["legacy_manual_kept"] == 999         # history kept, not used
    assert d["legacy_manual_exposed"] == 999
    assert d["legacy_paid_source"] == "payment_ledger"


@real
def test_the_committed_evidence_is_a_run_of_this_harness():
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert set(data) == {"fg236", "fg237", "fg238", "fg239", "fg240"}


if __name__ == "__main__":
    sys.exit(main())
