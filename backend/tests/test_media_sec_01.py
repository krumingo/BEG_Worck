"""
MEDIA-SEC-01 — media: tenant-bound avatars, no hard delete, project-photo membership,
no silent re-link.

Findings: FLOW Guard pass 44 (FLOW-029 sweep on main 3863610) FG-540, FG-541, FG-542,
FG-544. Canon: CLAUDE.md §2 rules 9 and 11, §3 (Tenant Guard, server-side tenant
resolution), §4 (originals are kept), §14 (consequential write: permission, tenant,
idempotency key, AuditEvent), §15.

* FG-540 — ``GET /api/media/avatar/{filename}`` needs a login and resolves the file only
  through a profile ``media_files`` row of the caller's tenant; anything else is 404.
* FG-542 — ``DELETE /api/media/{id}``: a linked / used file -> 409, nothing touched;
  an unused file is RETIRED (row kept, file kept, canonical AuditEvent ``media.file.retire``).
* FG-541 — project photos (list / upload / file / retire) check project membership,
  the same ``can_access_project`` as ``GET /projects/{id}``, in off, shadow and enforce.
* FG-544 — ``POST /api/media/link`` refuses to re-link an already linked file (409).

Every scenario runs through the WHOLE application (``server.app``) on a disposable LOCAL
MongoDB replica set (two fresh scratch databases, dropped afterwards), with the ST-01
synthetic tenants A and B, real logins and real JWTs.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_media_sec_01.py -q --noconftest -p no:cacheprovider -rs
    # the evidence:
    PYTHONPATH=. python tests/test_media_sec_01.py --harness \\
        --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
"""
from __future__ import annotations

import argparse
import importlib.util
import io
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
EVIDENCE = REPO / "docs" / "evidence" / "MEDIA-SEC-01"
RESULTS_JSON = EVIDENCE / "results.json"
DB_PREFIX_OP, DB_PREFIX_SYS = "mediasec01_op_", "mediasec01_sys_"
SYNTH_PASSWORD = "MEDIASEC01-Synthetic-Pass-2026!"   # synthetic users of a scratch database
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant", "viewer")
UPLOADS = Path("/app/backend/uploads")
NOW = "2026-11-09T08:00:00+00:00"
MODES = ("off", "shadow", "enforce")
# a tiny valid JPEG header + payload: the server never decodes it, it only stores bytes
JPEG = b"\xff\xd8\xff\xe0" + b"MEDIA-SEC-01" * 8 + b"\xff\xd9"


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "mediasec01_pm01_helpers",
        Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pid(tkey: str, name: str) -> str:
    return "mediasec01-%s-%s" % (tkey, name)


async def seed(op_db, fx: Dict[str, Any]) -> None:
    """Per tenant: project ``other`` that NOBODY is a member of (the FG-541 target)."""
    for name in ("audit_logs", "audit_events", "project_photos", "media_files", "missing_smr"):
        if name not in await op_db.list_collection_names():
            await op_db.create_collection(name)
    for tkey, t in fx.items():
        await op_db.projects.insert_one({
            "id": pid(tkey, "other"), "org_id": t["tenant_id"], "code": "MS-%s-OTHER" % tkey,
            "name": "MEDIA-SEC-01 %s other" % tkey, "status": "Active", "type": "Billable",
            "created_at": NOW, "updated_at": NOW})


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
        # P1's team: the Technician is a member; nobody is a member of ``other``.
        r = tc.post("/api/projects/%s/team" % A["project_id"],
                    json={"user_id": A["users"]["technician"]["id"], "role_in_project": "Technician"},
                    headers={"Authorization": "Bearer " + tokens[("A", "admin")]})
        assert r.status_code == 201, (r.status_code, r.text[:300])

        def call(method, url, role="owner", tkey="A", key: Optional[str] = None, auth=True, **kw):
            headers = {}
            if auth:
                headers["Authorization"] = "Bearer " + tokens[(tkey, role)]
            if key == "auto":
                key = uuid.uuid4().hex
            if key:
                headers["Idempotency-Key"] = key
            resp = tc.request(method, url, headers=headers, **kw)
            try:
                body = resp.json()
            except Exception:                                   # noqa: BLE001
                body = None
            detail = body.get("detail") if isinstance(body, dict) else None
            return {"status": resp.status_code,
                    "error_code": detail.get("error_code") if isinstance(detail, dict) else None,
                    "body": body, "content": resp.content}

        def q(fn):
            return tc.portal.call(fn)

        def upload(role="technician", tkey="A", context=None, name="a.jpg"):
            data = {}
            if context:
                data = {"context_type": context[0], "context_id": context[1]}
            r = call("POST", "/api/media/upload", role=role, tkey=tkey, data=data,
                     files={"file": (name, io.BytesIO(JPEG), "image/jpeg")})
            assert r["status"] == 200, (role, tkey, context, r["status"], r["body"])
            return r["body"]

        def media_row(media_id):
            return q(lambda: op_db.media_files.find_one({"id": media_id}, {"_id": 0})) or {}

        def events(entity_id, prefix):
            rows = q(lambda: op_db.audit_events.find({"entity_id": entity_id},
                                                     {"_id": 0}).to_list(None))
            return [{"action": e.get("action"), "reason": e.get("reason"),
                     "tenant_id": e.get("tenant_id"), "source_flow": e.get("source_flow"),
                     "entity_type": e.get("entity_type"),
                     "idempotency_key": e.get("idempotency_key"),
                     "diff": e.get("structured_diff")}
                    for e in rows if str(e.get("action", "")).startswith(prefix)]

        def stored(body):
            return media_row(body["id"]).get("stored_filename")

        # ─────────────────────────────────────────────── FG-540 — avatars
        d: Dict[str, Any] = {}
        tech_a = A["users"]["technician"]["id"]
        av_a = upload(context=("profile", tech_a))
        av_b = upload(tkey="B", context=("profile", fx["B"]["users"]["technician"]["id"]))
        plain_a = upload()                                    # a non-avatar file of tenant A
        site_a = upload(context=("project", A["project_id"]), name="site.jpg")
        url_a = "/api/media/avatar/%s" % stored(av_a)
        d["no_login"] = call("GET", url_a, auth=False)["status"]
        d["bad_token"] = tc.get(url_a, headers={"Authorization": "Bearer not-a-jwt"}).status_code
        own = call("GET", url_a, role="technician")
        d["own"] = {"status": own["status"], "same_bytes": own["content"] == JPEG}
        d["same_tenant_viewer"] = call("GET", url_a, role="viewer")["status"]
        d["other_tenant"] = call("GET", url_a, tkey="B", role="owner")["status"]
        d["other_tenant_file_on_disk"] = (UPLOADS / stored(av_a)).is_file()
        d["b_avatar_from_a"] = call("GET", "/api/media/avatar/%s" % stored(av_b))["status"]
        d["b_avatar_from_b"] = call("GET", "/api/media/avatar/%s" % stored(av_b),
                                    tkey="B", role="viewer")["status"]
        d["non_avatar_plain"] = call("GET", "/api/media/avatar/%s" % stored(plain_a))["status"]
        d["non_avatar_site"] = call("GET", "/api/media/avatar/%s" % stored(site_a))["status"]
        d["unknown"] = call("GET", "/api/media/avatar/%s.jpg" % uuid.uuid4())["status"]
        # a file that is on disk in the shared upload dir but has NO media row at all
        orphan = "%s.jpg" % uuid.uuid4()
        UPLOADS.mkdir(parents=True, exist_ok=True)
        (UPLOADS / orphan).write_bytes(JPEG)
        d["orphan_on_disk"] = call("GET", "/api/media/avatar/%s" % orphan)["status"]
        (UPLOADS / orphan).unlink()
        traversal = {}
        for probe in ("..%2F..%2Fetc%2Fpasswd", "..%2f" + stored(av_a), "%2e%2e%2f" + stored(av_a),
                      "%2E%2E", "...", "..%5C" + stored(av_a), stored(av_a) + "%00.jpg",
                      ".%2F" + stored(av_a), "projects%2F" + stored(av_a), "%2Fetc%2Fpasswd",
                      "..%252F" + stored(av_a), "x" * 300 + ".jpg"):
            traversal[probe[:40]] = call("GET", "/api/media/avatar/" + probe)["status"]
        d["traversal"] = traversal
        obs["fg540"] = d

        # ─────────────────────────────────────────────── FG-542 — no hard delete
        d = {}
        # linked (a site photo of P1) -> 409
        r = call("DELETE", "/api/media/%s" % site_a["id"], role="technician", key="auto",
                 json={"reason": "стара снимка"})
        d["linked"] = {"status": r["status"], "error_code": r["error_code"],
                       "row_kept": bool(media_row(site_a["id"])),
                       "status_after": media_row(site_a["id"]).get("status"),
                       "file_kept": (UPLOADS / stored(site_a)).is_file(),
                       "events": events(site_a["id"], "media.")}
        # used by an approved missing-SMR item (attachment, no link on the media row)
        used = upload()
        q(lambda: op_db.missing_smr.insert_one({
            "id": pid("A", "smr_used"), "org_id": A["tenant_id"], "project_id": A["project_id"],
            "status": "approved_by_client", "created_at": NOW,
            "attachments": [{"media_id": used["id"], "url": used["url"]}],
            "client_approval": {"status": "approved", "signature_media_id": None}}))
        r = call("DELETE", "/api/media/%s" % used["id"], role="technician", key="auto",
                 json={"reason": "грешна снимка"})
        d["used_by_approved_smr"] = {
            "status": r["status"], "error_code": r["error_code"],
            "uses": ((r["body"] or {}).get("detail") or {}).get("use_kinds")
            if isinstance(r["body"], dict) else None,
            "row_kept": bool(media_row(used["id"])),
            "status_after": media_row(used["id"]).get("status"),
            "file_kept": (UPLOADS / stored(used)).is_file(),
            "events": events(used["id"], "media.")}
        # used as a client-approval signature
        sig = upload()
        q(lambda: op_db.missing_smr.insert_one({
            "id": pid("A", "smr_sig"), "org_id": A["tenant_id"], "project_id": A["project_id"],
            "status": "approved_by_client", "created_at": NOW, "attachments": [],
            "client_approval": {"status": "approved", "signature_media_id": sig["id"]}}))
        r = call("DELETE", "/api/media/%s" % sig["id"], role="technician", key="auto",
                 json={"reason": "x"})
        d["used_as_signature"] = {"status": r["status"], "error_code": r["error_code"],
                                  "file_kept": (UPLOADS / stored(sig)).is_file()}
        # FG-556: a photo referenced by a work report, an extra-work draft, a pending expense
        # or a payment receipt (by id, stored name or url; plain list or sub-document)
        def by_name(m):
            return stored(m)

        def by_url(m):
            return "/api/media/file/%s" % stored(m)

        fg556 = {
            "work_report_id": ("work_reports", lambda m: {"photos": [m["id"]], "status": "Approved"}),
            "work_report_url": ("work_reports", lambda m: {"photos": [{"url": by_url(m)}]}),
            "extra_work_draft": ("extra_work_drafts", lambda m: {"photos": [by_name(m)]}),
            "pending_expense": ("pending_expenses", lambda m: {"media_id": m["id"],
                                                               "status": "pending_approval"}),
            "pending_expense_url": ("pending_expenses", lambda m: {"media_url": by_url(m)}),
            "payment_receipt": ("finance_payments", lambda m: {"cash_receipt_file_id": m["id"],
                                                               "direction": "Outflow",
                                                               "amount": 10}),
        }
        d["fg556"] = {}
        for label, (coll, shape) in fg556.items():
            m = upload()
            row = {"id": pid("A", "use_" + label), "org_id": A["tenant_id"], "created_at": NOW,
                   **shape(m)}
            q(lambda: op_db[coll].insert_one(row))
            r = call("DELETE", "/api/media/%s" % m["id"], role="technician", key="auto",
                     json={"reason": "x"})
            d["fg556"][label] = {
                "status": r["status"], "error_code": r["error_code"],
                "use_kind": ((((r["body"] or {}).get("detail") or {}).get("use_kinds")) or [None])[0]
                if isinstance(r["body"], dict) else None,
                "status_after": media_row(m["id"]).get("status"),
                "file_kept": (UPLOADS / stored(m)).is_file()}
        # the same rows of ANOTHER tenant do not block tenant A's file
        m = upload()
        q(lambda: op_db.work_reports.insert_one({"id": pid("B", "use_other"),
                                                 "org_id": fx["B"]["tenant_id"],
                                                 "photos": [m["id"]], "created_at": NOW}))
        d["fg556"]["other_tenant_row"] = call("DELETE", "/api/media/%s" % m["id"],
                                              role="technician", key="auto",
                                              json={"reason": "x"})["status"]
        # an unused file: rights, reason, key; then retired, file kept, AuditEvent
        free = upload()
        url = "/api/media/%s" % free["id"]
        d["no_key"] = call("DELETE", url, role="technician", json={"reason": "x"})["status"]
        d["no_reason"] = call("DELETE", url, role="technician", key="auto", json={})["status"]
        d["other_technician"] = call("DELETE", url, role="requester", key="auto",
                                     json={"reason": "x"})["status"]
        d["other_tenant"] = call("DELETE", url, tkey="B", key="auto", json={"reason": "x"})["status"]
        d["before"] = {"status": media_row(free["id"]).get("status"),
                       "events": events(free["id"], "media.")}
        k = uuid.uuid4().hex
        r = call("DELETE", url, role="technician", key=k, json={"reason": "дублирана снимка"})
        r2 = call("DELETE", url, role="technician", key=k, json={"reason": "дублирана снимка"})
        row = media_row(free["id"])
        listing = call("GET", "/api/media", role="technician")["body"]
        d["unused"] = {
            "status": r["status"], "body": r["body"], "replay_status": r2["status"],
            "replay_same": r2["body"] == r["body"],
            "row_kept": bool(row), "status_after": row.get("status"),
            "retired_reason": row.get("retired_reason"),
            "retired_by_technician": row.get("retired_by") == tech_a,
            "file_kept": (UPLOADS / stored(free)).is_file(),
            "listed": any(m.get("id") == free["id"] for m in listing)
            if isinstance(listing, list) else None,
            "file_technician": call("GET", "/api/media/file/%s" % stored(free),
                                    role="technician")["status"],
            "file_owner": call("GET", "/api/media/file/%s" % stored(free))["status"],
            "again": call("DELETE", url, role="technician", key="auto",
                          json={"reason": "пак"})["error_code"],
            "meta_technician": call("GET", "/api/media/%s" % free["id"], role="technician")["status"],
            "meta_requester": call("GET", "/api/media/%s" % free["id"], role="requester")["status"],
            "meta_owner": call("GET", "/api/media/%s" % free["id"])["status"],
            "relink": call("POST", "/api/media/link", role="technician", json={
                "media_id": free["id"], "context_type": "project",
                "context_id": A["project_id"]})["status"],
            "events": events(free["id"], "media.")}
        obs["fg542"] = d

        # ─────────────────────────────────────────────── FG-544 — no silent re-link
        d = {}
        f = upload()
        link = {"media_id": f["id"], "context_type": "project", "context_id": A["project_id"]}
        d["first"] = call("POST", "/api/media/link", role="technician", json=link)["status"]
        d["same_again"] = call("POST", "/api/media/link", role="technician", json=link)["status"]
        r = call("POST", "/api/media/link", role="technician",
                 json={**link, "context_type": "profile", "context_id": tech_a})
        d["other_record"] = {"status": r["status"], "error_code": r["error_code"]}
        r = call("POST", "/api/media/link",
                 json={**link, "context_id": pid("A", "other")})
        d["owner_other_project"] = {"status": r["status"], "error_code": r["error_code"]}
        row = media_row(f["id"])
        d["after"] = {"context_type": row.get("context_type"),
                      "context_id_is_first": row.get("context_id") == A["project_id"]}
        obs["fg544"] = d

        # ─────────────────────────────────────────────── R83 — Krum's decisions
        r83: Dict[str, Any] = {}
        users_a = A["users"]

        def user_row(uid):
            return q(lambda: op_db.users.find_one({"id": uid}, {"_id": 0, "avatar_url": 1})) or {}

        # R83(1) — a Viewer only reads photos, member or not
        for ukey, rip in (("viewer", "Viewer"), ("requester", "Viewer")):
            r = tc.post("/api/projects/%s/team" % A["project_id"],
                        json={"user_id": users_a[ukey]["id"], "role_in_project": rip},
                        headers={"Authorization": "Bearer " + tokens[("A", "admin")]})
            assert r.status_code == 201, (ukey, r.status_code, r.text[:200])
        v = {}
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            before = q(lambda: op_db.project_photos.count_documents({"project_id": A["project_id"]}))
            v[mode] = {
                "viewer_member_upload": call("POST", "/api/projects/%s/photos" % A["project_id"],
                                             role="viewer", files={"file": ("v.jpg", io.BytesIO(JPEG),
                                                                            "image/jpeg")})["status"],
                "project_viewer_sitemanager_upload": call(
                    "POST", "/api/projects/%s/photos" % A["project_id"], role="requester",
                    files={"file": ("v.jpg", io.BytesIO(JPEG), "image/jpeg")})["status"],
                "viewer_member_list": call("GET", "/api/projects/%s/photos" % A["project_id"],
                                           role="viewer")["status"],
                "rows_added": q(lambda: op_db.project_photos.count_documents(
                    {"project_id": A["project_id"]})) - before,
                "technician_upload": call("POST", "/api/projects/%s/photos" % A["project_id"],
                                          role="technician",
                                          files={"file": ("t.jpg", io.BytesIO(JPEG),
                                                          "image/jpeg")})["status"]}
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        r83["viewer"] = v

        # R83(2) — a USED file is retired only by a request the Owner approves
        # (pass 46 interim policy: an Admin files, an Owner approves — media_policy)
        a2: Dict[str, Any] = {}
        used2 = upload()
        q(lambda: op_db.work_reports.insert_one({
            "id": pid("A", "wr_approved"), "org_id": A["tenant_id"], "project_id": A["project_id"],
            "status": "Approved", "photos": [used2["id"]], "created_at": NOW}))
        rq_url = "/api/media/%s/retire-request" % used2["id"]
        r = call("DELETE", "/api/media/%s" % used2["id"], role="technician", key="auto",
                 json={"reason": "грешна"})
        det = ((r["body"] or {}).get("detail") or {}) if isinstance(r["body"], dict) else {}
        a2["delete"] = (r["status"], r["error_code"])
        a2["delete_detail_technician"] = sorted(det.keys())
        r = call("DELETE", "/api/media/%s" % used2["id"], role="admin", key="auto",
                 json={"reason": "грешна"})
        det = ((r["body"] or {}).get("detail") or {}) if isinstance(r["body"], dict) else {}
        a2["delete_detail_admin_uses"] = [u.get("kind") for u in det.get("uses") or []]
        a2["req_no_key"] = call("POST", rq_url, role="admin", json={"reason": "x"})["status"]
        a2["req_no_reason"] = call("POST", rq_url, role="admin", key="auto", json={})["status"]
        a2["req_technician_owner_of_file"] = call("POST", rq_url, role="technician", key="auto",
                                                  json={"reason": "x"})["error_code"]
        a2["req_owner"] = call("POST", rq_url, key="auto", json={"reason": "x"})["error_code"]
        a2["req_other_tenant"] = call("POST", rq_url, tkey="B", role="admin", key="auto",
                                      json={"reason": "x"})["status"]
        k = uuid.uuid4().hex
        r = call("POST", rq_url, role="admin", key=k, json={"reason": "снимката е на друг обект"})
        r2 = call("POST", rq_url, role="admin", key=k, json={"reason": "снимката е на друг обект"})
        rid = (r["body"] or {}).get("id")
        a2["request"] = {"status": r["status"], "req_status": (r["body"] or {}).get("status"),
                         "replay_same": r2["body"] == r["body"],
                         "has_version": bool((r["body"] or {}).get("uses_version")),
                         "interim_until": (r["body"] or {}).get("interim_until")}
        req_row = q(lambda: op_db.media_retire_requests.find_one({"id": rid}, {"_id": 0})) or {}
        a2["request_row"] = {"uses_kinds": [u.get("kind") for u in req_row.get("uses") or []],
                             "uses_version": bool(req_row.get("uses_version")),
                             "ref_version_kept": "ref_version" in req_row}
        a2["second_request"] = call("POST", rq_url, role="admin", key="auto",
                                    json={"reason": "пак"})["error_code"]
        a2["delete_while_pending"] = call("DELETE", "/api/media/%s" % used2["id"], role="technician",
                                          key="auto", json={"reason": "x"})["error_code"]
        # FG-577: no new reference while the request is pending — /media/link and the writers
        a2["link_while_pending"] = call("POST", "/api/media/link", role="technician", json={
            "media_id": used2["id"], "context_type": "project",
            "context_id": A["project_id"]})["error_code"]
        smr_item = pid("A", "smr_pending_target")
        q(lambda: op_db.missing_smr.insert_one({
            "id": smr_item, "org_id": A["tenant_id"], "project_id": A["project_id"],
            "status": "reported", "attachments": [], "created_at": NOW}))
        a2["attach_while_pending"] = call(
            "POST", "/api/missing-smr/%s/attachments" % smr_item, role="admin",
            json={"media_id": used2["id"], "url": used2["url"], "filename": "x.jpg"})["error_code"]
        a2["attach_not_written"] = (q(lambda: op_db.missing_smr.find_one(
            {"id": smr_item}, {"_id": 0, "attachments": 1})) or {}).get("attachments") == []
        ap_url = "/api/media/retire-requests/%s/approve" % rid
        a2["approve_admin"] = call("POST", ap_url, role="admin", key="auto", json={})["error_code"]
        a2["approve_technician"] = call("POST", ap_url, role="technician", key="auto",
                                        json={})["error_code"]
        a2["approve_no_key"] = call("POST", ap_url, json={})["status"]
        a2["approve_other_tenant"] = call("POST", ap_url, tkey="B", key="auto", json={})["status"]
        a2["before_approve"] = {"status": media_row(used2["id"]).get("status"),
                                "events": [e["action"] for e in events(used2["id"], "media.")]}
        a2["pending_list_owner"] = [x.get("id") for x in (call("GET", "/api/media-retire-requests")["body"] or [])]
        a2["pending_list_technician"] = call("GET", "/api/media-retire-requests",
                                             role="technician")["status"]
        k = uuid.uuid4().hex
        r = call("POST", ap_url, key=k, json={})
        r2 = call("POST", ap_url, key=k, json={})
        row = media_row(used2["id"])
        meta_t = call("GET", "/api/media/%s" % used2["id"], role="technician")
        a2["approve"] = {
            "status": r["status"], "replay_same": r2["body"] == r["body"],
            "media_status": row.get("status"), "in_use": row.get("retired_in_use"),
            "approved_by_owner": row.get("retire_approved_by") == users_a["owner"]["id"],
            "retired_by_requester": row.get("retired_by") == users_a["admin"]["id"],
            "reason": row.get("retired_reason"), "pending": row.get("retire_request_pending"),
            "file_kept": (UPLOADS / stored(used2)).is_file(),
            "record_keeps_ref": (q(lambda: op_db.work_reports.find_one(
                {"id": pid("A", "wr_approved")}, {"_id": 0, "photos": 1})) or {}).get("photos")
            == [used2["id"]],
            "meta_technician": meta_t["status"],
            "meta_technician_detail": (meta_t["body"] or {}).get("detail"),
            "meta_owner_status": (call("GET", "/api/media/%s" % used2["id"])["body"] or {}).get("status"),
            "again": call("POST", ap_url, key="auto", json={})["error_code"],
            "events": [{"action": e["action"], "reason": e["reason"],
                        "approved_by": (e["diff"] or {}).get("approved_by") == users_a["owner"]["id"],
                        "requested_by": (e["diff"] or {}).get("requested_by") == users_a["admin"]["id"]}
                       for e in events(used2["id"], "media.")]}
        # FG-577: the holders changed after the request → approve 409 RETIRE_REQUEST_STALE
        used4 = upload()
        q(lambda: op_db.work_reports.insert_one({
            "id": pid("A", "wr_stale"), "org_id": A["tenant_id"], "status": "Approved",
            "photos": [used4["id"]], "created_at": NOW}))
        r = call("POST", "/api/media/%s/retire-request" % used4["id"], role="admin", key="auto",
                 json={"reason": "дубликат"})
        rid4 = (r["body"] or {}).get("id")
        q(lambda: op_db.pending_expenses.insert_one({     # a second holder appears (raw write)
            "id": pid("A", "pe_stale"), "org_id": A["tenant_id"], "media_id": used4["id"],
            "status": "approved", "created_at": NOW}))
        r = call("POST", "/api/media/retire-requests/%s/approve" % rid4, key="auto", json={})
        a2["stale"] = {"request": rid4 is not None, "approve": (r["status"], r["error_code"]),
                       "media_status": media_row(used4["id"]).get("status"),
                       "request_status": (q(lambda: op_db.media_retire_requests.find_one(
                           {"id": rid4}, {"_id": 0, "status": 1})) or {}).get("status")}
        # the second-person check — exercised with the policy widened to let an Owner file
        # (an open question to Krum; interim: only an Admin files)
        try:                                   # absent on code before pass 46 → recorded as None
            import app.services.media_policy as media_policy
        except ImportError:
            media_policy = None
        saved_roles = getattr(media_policy, "RETIRE_REQUEST_ROLES", None)
        if media_policy is not None:
            media_policy.RETIRE_REQUEST_ROLES = frozenset({"Admin", "Owner"})
        try:
            used3 = upload(role="owner")
            q(lambda: op_db.pending_expenses.insert_one({
                "id": pid("A", "pe_used3"), "org_id": A["tenant_id"], "media_id": used3["id"],
                "status": "approved", "created_at": NOW}))
            r = call("POST", "/api/media/%s/retire-request" % used3["id"], key="auto",
                     json={"reason": "дубликат"})
            rid3 = (r["body"] or {}).get("id")
            a2["self"] = {
                "request": r["status"],
                "approve": call("POST", "/api/media/retire-requests/%s/approve" % rid3, key="auto",
                                json={})["error_code"],
                "reject_no_reason": call("POST", "/api/media/retire-requests/%s/reject" % rid3,
                                         key="auto", json={})["status"],
                "reject": call("POST", "/api/media/retire-requests/%s/reject" % rid3, key="auto",
                               json={"reason": "остава"})["status"]}
            row = media_row(used3["id"])
            a2["self"].update({"media_status": row.get("status"),
                               "pending": row.get("retire_request_pending"),
                               "events": [e["action"] for e in events(used3["id"], "media.")],
                               "request_again": call("POST", "/api/media/%s/retire-request"
                                                     % used3["id"], key="auto",
                                                     json={"reason": "пак"})["status"]})
        finally:
            if media_policy is not None:
                media_policy.RETIRE_REQUEST_ROLES = saved_roles
        # an UNUSED file has no request path: it is retired directly
        free2 = upload()
        a2["unused_request"] = call("POST", "/api/media/%s/retire-request" % free2["id"],
                                    role="admin", key="auto", json={"reason": "x"})["error_code"]
        r83["approval"] = a2

        # R83(3) — avatars: only a fresh profile upload; changes audited; old ones retirable
        a3: Dict[str, Any] = {}
        tech = users_a["technician"]["id"]
        a3["av_a_flag"] = media_row(av_a["id"]).get("avatar")
        loose = upload()
        a3["link_as_profile"] = call("POST", "/api/media/link", role="technician", json={
            "media_id": loose["id"], "context_type": "profile", "context_id": tech})["error_code"]
        a3["loose_not_avatar"] = call("GET", "/api/media/avatar/%s" % stored(loose))["status"]
        put = lambda url, who="admin": call("PUT", "/api/users/%s" % tech, role=who,
                                            json={"avatar_url": url})
        a3["put_site_photo"] = put("/api/media/avatar/%s" % stored(site_a))["error_code"]
        a3["put_file_form"] = put("/api/media/file/%s" % stored(av_a))["error_code"]
        a3["put_b_avatar"] = put("/api/media/avatar/%s" % stored(av_b))["error_code"]
        other_prof = upload(role="admin", context=("profile", users_a["accountant"]["id"]))
        a3["put_other_users_profile"] = put("/api/media/avatar/%s" % stored(other_prof))["error_code"]
        a3["after_refusals"] = user_row(tech).get("avatar_url")
        a3["put_ok"] = put("/api/media/avatar/%s" % stored(av_a))["status"]
        a3["after_put"] = user_row(tech).get("avatar_url") == "/api/media/avatar/%s" % stored(av_a)
        a3["current_avatar_delete"] = call("DELETE", "/api/media/%s" % av_a["id"], role="technician",
                                           key="auto", json={"reason": "x"})["error_code"]
        av2 = upload(context=("profile", tech), name="av2.jpg")
        r = call("PUT", "/api/employees/%s/basic" % tech,
                 json={"avatar_url": "/api/media/avatar/%s" % stored(av2)})
        a3["basic_put"] = r["status"]
        a3["basic_put_bad"] = call("PUT", "/api/employees/%s/basic" % tech,
                                   json={"avatar_url": "/api/media/avatar/%s" % stored(loose)})["error_code"]
        a3["avatar_events"] = [{"action": e["action"],
                                "after": ((e["diff"] or {}).get("after") or {}).get("avatar_url")}
                               for e in events(tech, "user.avatar")]
        # av_a is now an OLD avatar: its owner retires it; another user may not
        a3["old_other_user"] = call("DELETE", "/api/media/%s" % av_a["id"], role="requester",
                                    key="auto", json={"reason": "x"})["status"]
        a3["old_owner"] = call("DELETE", "/api/media/%s" % av_a["id"], role="technician",
                               key="auto", json={"reason": "стара снимка"})["status"]
        a3["old_owner_status"] = media_row(av_a["id"]).get("status")
        a3["old_avatar_served"] = call("GET", "/api/media/avatar/%s" % stored(av_a))["status"]
        # an Admin retires another user's old avatar (other_prof is nobody's current avatar)
        a3["old_admin"] = call("DELETE", "/api/media/%s" % other_prof["id"], role="admin",
                               key="auto", json={"reason": "стара"})["status"]
        a3["current_served"] = call("GET", "/api/media/avatar/%s" % stored(av2), role="viewer")["status"]
        r83["avatars"] = a3

        # R83(4) + FG-578 — the legacy-avatar backfill: dry run counts; apply needs an Owner's
        # USER ID; only files UPLOADED as profile; matched_count checked; revert mode
        a4: Dict[str, Any] = {}
        spec = importlib.util.spec_from_file_location(
            "mediasec01_backfill", BACKEND / "scripts" / "media_sec_01_avatar_backfill.py")
        bf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bf)
        owner_id, admin_id = users_a["owner"]["id"], users_a["admin"]["id"]
        viewer_id = users_a["viewer"]["id"]

        def legacy(row_id, uid, **extra):
            name = "%s.jpg" % uuid.uuid4()
            (UPLOADS / name).write_bytes(JPEG)
            q(lambda: op_db.media_files.insert_one({
                "id": pid("A", row_id), "org_id": A["tenant_id"], "owner_user_id": uid,
                "filename": "legacy.jpg", "stored_filename": name,
                "url": "/api/media/file/%s" % name, "content_type": "image/jpeg",
                "context_type": "profile", "context_id": uid, "created_at": NOW, **extra}))
            q(lambda: op_db.users.update_one({"id": uid},
                                             {"$set": {"avatar_url": "/api/media/file/%s" % name}}))
            return name
        legacy_name = legacy("legacy_av", viewer_id)
        legacy("legacy_linked", admin_id, linked_at=NOW)          # only LINKED to a profile
        site_url = "/api/media/file/%s" % stored(site_a)
        q(lambda: op_db.users.update_one({"id": users_a["accountant"]["id"]},
                                         {"$set": {"avatar_url": site_url}}))
        q(lambda: op_db.users.update_one({"id": users_a["requester"]["id"]},
                                         {"$set": {"avatar_url": "/static/x.png"}}))
        a4["served_before"] = call("GET", "/api/media/avatar/%s" % legacy_name)["status"]
        audit_before = q(lambda: op_db.audit_events.count_documents({"action": "media.avatar.backfill"}))

        async def _try(**kw):
            try:
                await bf.migrate(op_db, **kw)
                return "ran"
            except (bf.PlanMismatch, bf.NotApproved) as exc:
                return type(exc).__name__
        a4["dry_no_approver"] = q(lambda: _try())
        a4["dry_free_text"] = q(lambda: _try(approved_by="Крум"))
        a4["dry_admin_id"] = q(lambda: _try(approved_by=admin_id))
        dry = q(lambda: bf.migrate(op_db, approved_by=owner_id))
        mine = {r["user_id"]: r["action"] for r in dry["plan"]}
        a4["dry"] = {"viewer": mine.get(viewer_id), "admin_linked": mine.get(admin_id),
                     "accountant": mine.get(users_a["accountant"]["id"]),
                     "requester": mine.get(users_a["requester"]["id"]),
                     "technician": mine.get(tech), "applied": dry["applied"],
                     "only_tenant_a": {r["org_id"] for r in dry["plan"]} == {A["tenant_id"]},
                     "flag_written": media_row(pid("A", "legacy_av")).get("avatar"),
                     "audit_written": q(lambda: op_db.audit_events.count_documents(
                         {"action": "media.avatar.backfill"})) - audit_before}
        b_dry = q(lambda: bf.migrate(op_db, approved_by=fx["B"]["users"]["owner"]["id"]))
        a4["b_owner_sees_only_b"] = all(r["org_id"] == fx["B"]["tenant_id"] for r in b_dry["plan"])
        a4["apply_wrong_sha"] = q(lambda: _try(apply=True, approved_by=owner_id, plan_sha="0" * 64))
        # FG-578: a write that matches nothing aborts the user's transaction ("conflict")
        flag_row = next(r for r in dry["plan"] if r["user_id"] == viewer_id)
        stale_row = dict(flag_row, avatar_url="/api/media/file/not-the-current-one.jpg")
        a4["conflict"] = (q(lambda: bf._apply_flag(op_db, stale_row, owner_id))
                          if hasattr(bf, "_apply_flag") else "no _apply_flag (pre pass 46)")
        a4["conflict_rolled_back"] = media_row(pid("A", "legacy_av")).get("avatar") is None
        res = q(lambda: bf.migrate(op_db, apply=True, approved_by=owner_id, plan_sha=dry["plan_sha"]))
        a4["apply"] = {"written": res.get("written"), "conflict": res.get("conflict"),
                       "flag": media_row(pid("A", "legacy_av")).get("avatar"),
                       "linked_flag": media_row(pid("A", "legacy_linked")).get("avatar"),
                       "viewer_url": user_row(viewer_id).get("avatar_url") == "/api/media/avatar/%s" % legacy_name,
                       "served_after": call("GET", "/api/media/avatar/%s" % legacy_name)["status"],
                       "site_photo_served": call("GET", "/api/media/avatar/%s" % stored(site_a))["status"],
                       "events": [{"action": e["action"],
                                   "approved_by_owner": (e["diff"] or {}).get("approved_by") == owner_id}
                                  for e in events(pid("A", "legacy_av"), "media.avatar")]}
        dry2 = q(lambda: bf.migrate(op_db, approved_by=owner_id))
        res2 = q(lambda: bf.migrate(op_db, apply=True, approved_by=owner_id, plan_sha=dry2["plan_sha"]))
        a4["second_apply_written"] = res2.get("written")
        a4["second_viewer_action"] = {r["user_id"]: r["action"] for r in dry2["plan"]}.get(viewer_id)
        # revert: dry run first, then the approved plan
        try:
            rdry = q(lambda: bf.migrate(op_db, approved_by=owner_id, revert=True))
        except TypeError:                      # pre pass 46: no revert mode
            rdry = {"counts": None, "applied": None, "plan_sha": None, "plan": [None]}
        a4["revert_dry"] = {"counts": rdry["counts"], "applied": rdry["applied"],
                            "flag_still": media_row(pid("A", "legacy_av")).get("avatar")}
        try:
            rres = q(lambda: bf.migrate(op_db, apply=True, approved_by=owner_id, revert=True,
                                        plan_sha=rdry["plan_sha"]))
        except TypeError:
            rres = {}
        a4["revert"] = {"written": rres.get("written"),
                        "flag": media_row(pid("A", "legacy_av")).get("avatar"),
                        "viewer_url_restored": user_row(viewer_id).get("avatar_url")
                        == "/api/media/file/%s" % legacy_name,
                        "served": call("GET", "/api/media/avatar/%s" % legacy_name)["status"],
                        "events": [e["action"] for e in events(pid("A", "legacy_av"), "media.avatar")]}
        try:
            rdry2 = q(lambda: bf.migrate(op_db, approved_by=owner_id, revert=True))
        except TypeError:
            rdry2 = {"plan": [None]}
        a4["second_revert_rows"] = len(rdry2["plan"])
        r83["backfill"] = a4
        obs["r83"] = r83

        # ─────────────────────────────────────────────── FLOW Guard pass 46
        p46: Dict[str, Any] = {}
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        # FG-576 — one test per holder the registry was missing (the real field names)
        holders = {
            "offer_acceptance": ("offers", lambda m: {"status": "Accepted",
                                                     "approval": {"evidence_file_id": m["id"]}}),
            "warehouse_movement": ("warehouse_transactions",
                                   lambda m: {"tenant_id": A["tenant_id"], "file_ids": [m["id"]]}),
            "payment_receipt": ("finance_payments", lambda m: {"cash_receipt_file_id": m["id"]}),
            "subcontractor_payment_receipt": ("subcontractor_payments",
                                              lambda m: {"cash_receipt_file_id": m["id"]}),
        }
        p46["fg576"] = {}
        for kind, (coll, shape) in holders.items():
            m = upload()
            row = {"id": pid("A", "h_" + kind), "org_id": A["tenant_id"], "created_at": NOW,
                   **shape(m)}
            q(lambda: op_db[coll].insert_one(row))
            r = call("DELETE", "/api/media/%s" % m["id"], role="technician", key="auto",
                     json={"reason": "x"})
            ra = call("DELETE", "/api/media/%s" % m["id"], role="admin", key="auto",
                      json={"reason": "x"})
            p46["fg576"][kind] = {
                "status": r["status"], "error_code": r["error_code"],
                "kinds_shown_to_uploader": ((r["body"] or {}).get("detail") or {}).get("use_kinds"),
                "ids_hidden_from_uploader": "uses" not in ((r["body"] or {}).get("detail") or {}),
                "admin_sees": [u.get("kind") for u in ((ra["body"] or {}).get("detail") or {}).get("uses") or []],
                "status_after": media_row(m["id"]).get("status"),
                "file_kept": (UPLOADS / stored(m)).is_file()}
        # audit_events.related_file_ids — the chain is written only through the audit store
        m = upload()
        from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
        from app.audit.store import record_event
        ev = build_event(tenant_id=A["tenant_id"], actor_type=ACTOR_HUMAN,
                         actor_id=users_a["owner"]["id"], action="probe.evidence",
                         source_flow="FLOW-029", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
                         entity_type="probe", entity_id=pid("A", "probe_ev"), reason="probe",
                         structured_diff={}, related_file_ids=[m["id"]], source_channel="api")
        q(lambda: record_event(op_db, ev))
        r = call("DELETE", "/api/media/%s" % m["id"], role="technician", key="auto",
                 json={"reason": "x"})
        p46["fg576"]["audit_event"] = {
            "status": r["status"], "error_code": r["error_code"],
            "kinds_shown_to_uploader": ((r["body"] or {}).get("detail") or {}).get("use_kinds"),
            "status_after": media_row(m["id"]).get("status")}
        # the same holders in ANOTHER tenant never block
        m = upload()
        q(lambda: op_db.finance_payments.insert_one({
            "id": pid("B", "h_pay"), "org_id": fx["B"]["tenant_id"], "cash_receipt_file_id": m["id"],
            "created_at": NOW}))
        p46["fg576"]["other_tenant_row"] = call("DELETE", "/api/media/%s" % m["id"],
                                                role="technician", key="auto",
                                                json={"reason": "x"})["status"]

        # FG-575 — ONE upload guard at every entry point (Viewer → 403, nothing written)
        def files_now():
            return len(list(UPLOADS.glob("*"))) + (len(list((UPLOADS / "projects").glob("*")))
                                                   if (UPLOADS / "projects").is_dir() else 0)
        f = lambda: {"file": ("v.jpg", io.BytesIO(JPEG), "image/jpeg")}
        before_files = files_now()
        before_media = q(lambda: op_db.media_files.count_documents({}))
        before_pe = q(lambda: op_db.pending_expenses.count_documents({}))
        up = {}
        up["media_upload_no_context"] = call("POST", "/api/media/upload", role="viewer", files=f())["status"]
        up["media_upload_project_member"] = call("POST", "/api/media/upload", role="viewer",
                                                 data={"context_type": "project",
                                                       "context_id": A["project_id"]},
                                                 files=f())["status"]
        up["photo_invoice"] = call("POST", "/api/technician/photo-invoice", role="viewer",
                                   data={"project_id": A["project_id"], "amount": "1"},
                                   files=f())["status"]
        up["ocr_upload"] = call("POST", "/api/ocr-invoice/upload", role="viewer",
                                data={"project_id": A["project_id"]}, files=f())["status"]
        up["supplier_invoice_file"] = call("POST", "/api/supplier-invoices/%s/upload-file"
                                           % pid("A", "no_inv"), role="viewer", files=f())["status"]
        up["project_photo"] = call("POST", "/api/projects/%s/photos" % A["project_id"],
                                   role="viewer", files=f())["status"]
        up["project_viewer_sitemanager_media_upload"] = call(
            "POST", "/api/media/upload", role="requester",
            data={"context_type": "project", "context_id": A["project_id"]}, files=f())["status"]
        up["written"] = {"files": files_now() - before_files,
                         "media_rows": q(lambda: op_db.media_files.count_documents({})) - before_media,
                         "pending_expenses": q(lambda: op_db.pending_expenses.count_documents({})) - before_pe}
        # positives: the member Technician still uploads
        r = tc.post("/api/projects/%s/team" % A["project_id"],
                    json={"user_id": tech, "role_in_project": "Technician"},
                    headers={"Authorization": "Bearer " + tokens[("A", "admin")]})
        up["tech_photo_invoice"] = call("POST", "/api/technician/photo-invoice", role="technician",
                                        data={"project_id": A["project_id"], "amount": "1"},
                                        files=f())["status"]
        up["tech_media_upload"] = call("POST", "/api/media/upload", role="technician", files=f())["status"]
        up["tech_photo_invoice_other_project"] = call(
            "POST", "/api/technician/photo-invoice", role="technician",
            data={"project_id": pid("A", "other"), "amount": "1"}, files=f())["status"]
        p46["fg575"] = up

        # FG-579 — write skew: a reference committed while a retire runs → the retire refuses
        try:                                   # absent on code before pass 46 → no race possible
            import app.services.file_holders as fh
        except ImportError:
            fh = None
        from app.db import db as app_db
        from app.tenancy.data_access import TenantData
        racy = upload()
        real_find = getattr(fh, "find_holders", None)
        state = {"done": False}

        async def racing_find(tenant, org_id, media, session=None, kinds=None):
            out = await real_find(tenant, org_id, media, session=session, kinds=kinds)
            if media.get("id") == racy["id"] and not state["done"]:
                state["done"] = True
                t = TenantData.for_resolved_org(app_db, A["tenant_id"])
                await fh.claimed_write(t, A["tenant_id"], [racy["id"]],
                                       lambda s: t.scan_docs.insert_one(
                                           {"id": pid("A", "race_scan"), "org_id": A["tenant_id"],
                                            "media_id": racy["id"], "created_at": NOW},
                                           session=s))
            return out
        if fh is not None:
            fh.find_holders = racing_find
        try:
            r = call("DELETE", "/api/media/%s" % racy["id"], role="technician", key="auto",
                     json={"reason": "x"})
        finally:
            if fh is not None:
                fh.find_holders = real_find
        p46["fg579"] = {"race_happened": state["done"], "status": r["status"],
                        "error_code": r["error_code"],
                        "media_status": media_row(racy["id"]).get("status"),
                        "reference_kept": q(lambda: op_db.scan_docs.count_documents(
                            {"id": pid("A", "race_scan")})) == 1,
                        "ref_version": media_row(racy["id"]).get("ref_version")}
        # …and a writer refuses a file retired just before (claim sees "retired")
        gone = upload()
        call("DELETE", "/api/media/%s" % gone["id"], role="technician", key="auto", json={"reason": "x"})
        smr2 = pid("A", "smr_after_retire")
        q(lambda: op_db.missing_smr.insert_one({
            "id": smr2, "org_id": A["tenant_id"], "project_id": A["project_id"],
            "status": "reported", "attachments": [], "created_at": NOW}))
        p46["fg579"]["attach_retired"] = call(
            "POST", "/api/missing-smr/%s/attachments" % smr2, role="admin",
            json={"media_id": gone["id"], "url": gone["url"], "filename": "g.jpg"})["error_code"]

        # FG-544 — the link is an AuditEvent
        lk = upload()
        r = call("POST", "/api/media/link", role="technician", json={
            "media_id": lk["id"], "context_type": "project", "context_id": A["project_id"]})
        p46["fg544_link"] = {"status": r["status"],
                             "events": [{"action": e["action"],
                                         "after": (e["diff"] or {}).get("after")}
                                        for e in events(lk["id"], "media.file.link")],
                             "ref_version": media_row(lk["id"]).get("ref_version")}
        obs["pass46"] = p46

        # ─────────────────────────────────────────────── FG-541 — project photos
        other = pid("A", "other")
        own_up = call("POST", "/api/projects/%s/photos" % other,
                      files={"file": ("o.jpg", io.BytesIO(JPEG), "image/jpeg")})
        photo = own_up["body"] if own_up["status"] == 201 else {}
        d = {"owner_upload_other": own_up["status"]}

        def counts():
            return {"photos": q(lambda: op_db.project_photos.count_documents({"project_id": other})),
                    "audit_logs": q(lambda: op_db.audit_logs.count_documents(
                        {"action": "photo_uploaded", "entity_id": other})),
                    "files": len(list((UPLOADS / "projects").glob("project_*")))
                    if (UPLOADS / "projects").is_dir() else 0}

        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            m: Dict[str, Any] = {}
            before = counts()
            for role in ("viewer", "technician", "accountant", "requester"):
                m["upload_" + role] = call("POST", "/api/projects/%s/photos" % other, role=role,
                                           files={"file": ("x.jpg", io.BytesIO(JPEG),
                                                           "image/jpeg")})["status"]
                m["list_" + role] = call("GET", "/api/projects/%s/photos" % other,
                                         role=role)["status"]
                m["file_" + role] = call("GET", "/api/projects/photos/file/%s"
                                         % photo.get("stored_filename"), role=role)["status"]
            m["retire_nonmember_uploader"] = None
            m["counts_before"], m["counts_after"] = before, counts()
            # positives: the member Technician on P1, the Owner anywhere
            up = call("POST", "/api/projects/%s/photos" % A["project_id"], role="technician",
                      files={"file": ("m.jpg", io.BytesIO(JPEG), "image/jpeg")})
            m["member_upload"] = up["status"]
            m["member_list"] = call("GET", "/api/projects/%s/photos" % A["project_id"],
                                    role="technician")["status"]
            m["member_file"] = call("GET", "/api/projects/photos/file/%s"
                                    % (up["body"] or {}).get("stored_filename"),
                                    role="technician")["status"]
            m["owner_list_other"] = call("GET", "/api/projects/%s/photos" % other)["status"]
            m["owner_file_other"] = call("GET", "/api/projects/photos/file/%s"
                                         % photo.get("stored_filename"))["status"]
            m["other_tenant_list"] = call("GET", "/api/projects/%s/photos" % other,
                                          tkey="B")["status"]
            d[mode] = m
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        # an uploader that is no longer on the team cannot retire the photo
        up = call("POST", "/api/projects/%s/photos" % A["project_id"], role="technician",
                  files={"file": ("r.jpg", io.BytesIO(JPEG), "image/jpeg")})
        tid = q(lambda: op_db.project_team.find_one(
            {"project_id": A["project_id"], "user_id": tech_a}, {"_id": 0, "id": 1})) or {}
        removed = call("DELETE", "/api/projects/%s/team/%s" % (A["project_id"], tid.get("id")),
                       role="admin")["status"]
        r = call("DELETE", "/api/projects/photos/%s" % (up["body"] or {}).get("id"),
                 role="technician", key="auto", json={"reason": "x"})
        d["retire_after_removal"] = {"removed": removed, "status": r["status"],
                                     "photo_status": (q(lambda: op_db.project_photos.find_one(
                                         {"id": (up["body"] or {}).get("id")},
                                         {"_id": 0, "status": 1})) or {}).get("status")}
        obs["fg541"] = d

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(obs, ensure_ascii=False, indent=1, sort_keys=True,
                                   default=lambda b: None) + "\n", encoding="utf-8")
    return obs


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 1800) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "mediasec01-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="MEDIA-SEC-01 media evidence")
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
    out = tmp_path_factory.mktemp("mediasec01") / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    return json.loads(out.read_text(encoding="utf-8"))


@real
def test_fg540_an_avatar_needs_a_login(obs):
    d = obs["fg540"]
    assert d["no_login"] == 401
    assert d["bad_token"] == 401


@real
def test_fg540_own_tenant_avatar_is_served(obs):
    d = obs["fg540"]
    assert d["own"] == {"status": 200, "same_bytes": True}
    assert d["same_tenant_viewer"] == 200
    assert d["b_avatar_from_b"] == 200


@real
def test_fg540_another_tenants_avatar_is_404_although_the_file_is_on_disk(obs):
    d = obs["fg540"]
    assert d["other_tenant_file_on_disk"] is True
    assert d["other_tenant"] == 404
    assert d["b_avatar_from_a"] == 404


@real
def test_fg540_a_non_avatar_media_file_is_404(obs):
    d = obs["fg540"]
    assert d["non_avatar_plain"] == 404
    assert d["non_avatar_site"] == 404
    assert d["unknown"] == 404
    assert d["orphan_on_disk"] == 404


@real
def test_fg540_every_traversal_attempt_is_404(obs):
    t = obs["fg540"]["traversal"]
    assert len(t) == 12
    assert set(t.values()) == {404}, t


@real
def test_fg542_a_linked_file_is_409_and_stays(obs):
    d = obs["fg542"]["linked"]
    assert (d["status"], d["error_code"]) == (409, "MEDIA_IN_USE")
    assert d["row_kept"] and d["file_kept"] and d["status_after"] is None
    assert d["events"] == []


@real
def test_fg542_a_photo_used_by_an_approved_record_is_409_and_stays(obs):
    d = obs["fg542"]["used_by_approved_smr"]
    assert (d["status"], d["error_code"]) == (409, "MEDIA_IN_USE")
    assert d["uses"] == ["missing_smr"]          # the uploader sees kinds, never record ids
    assert d["row_kept"] and d["file_kept"] and d["status_after"] is None
    assert d["events"] == []
    s = obs["fg542"]["used_as_signature"]
    assert (s["status"], s["error_code"], s["file_kept"]) == (409, "MEDIA_IN_USE", True)


@real
def test_fg542_retire_needs_rights_reason_and_key(obs):
    d = obs["fg542"]
    assert d["no_key"] == 428
    assert d["no_reason"] == 400
    assert d["other_technician"] == 403
    assert d["other_tenant"] == 404
    assert d["before"] == {"status": None, "events": []}


@real
def test_fg542_an_unused_file_is_retired_kept_and_audited(obs):
    d = obs["fg542"]["unused"]
    assert d["status"] == 200 and d["body"]["retired"]
    assert d["replay_status"] == 200 and d["replay_same"]
    assert d["row_kept"] and d["file_kept"]
    assert d["status_after"] == "retired" and d["retired_reason"] == "дублирана снимка"
    assert d["retired_by_technician"]
    assert d["listed"] is False
    assert d["file_technician"] == 404 and d["file_owner"] == 200
    assert d["again"] == "MEDIA_ALREADY_RETIRED"
    assert d["relink"] == 409
    assert len(d["events"]) == 1
    ev = d["events"][0]
    assert ev["action"] == "media.file.retire" and ev["entity_type"] == "media_file"
    assert ev["reason"] == "дублирана снимка" and ev["source_flow"] == "FLOW-029"
    assert ev["idempotency_key"] and ev["tenant_id"]
    assert ev["diff"]["before"] == {"status": "active"}
    assert ev["diff"]["after"] == {"status": "retired"}


@real
def test_fg556_a_photo_used_by_a_report_draft_expense_or_payment_is_409(obs):
    d = obs["fg542"]["fg556"]
    kinds = {"work_report_id": "work_report", "work_report_url": "work_report",
             "extra_work_draft": "extra_work_draft", "pending_expense": "pending_expense",
             "pending_expense_url": "pending_expense", "payment_receipt": "payment_receipt"}
    for label, kind in kinds.items():
        cell = d[label]
        assert (cell["status"], cell["error_code"]) == (409, "MEDIA_IN_USE"), (label, cell)
        assert cell["use_kind"] == kind, (label, cell)
        assert cell["status_after"] is None and cell["file_kept"] is True, (label, cell)
    assert d["other_tenant_row"] == 200


@real
def test_fg558_a_retired_files_metadata_is_for_owner_admin_only(obs):
    d = obs["fg542"]["unused"]
    # R83(2): a reader of the record learns only THAT the file was retired (410, no metadata);
    # a user with no access to the file still gets the ACL answer (403), not its status
    assert d["meta_technician"] == 410
    assert d["meta_requester"] == 403
    assert d["meta_owner"] == 200


@real
def test_fg544_a_linked_file_is_not_moved_to_another_record(obs):
    d = obs["fg544"]
    assert d["first"] == 200 and d["same_again"] == 200
    assert d["other_record"] == {"status": 409, "error_code": "MEDIA_ALREADY_LINKED"}
    assert d["owner_other_project"] == {"status": 409, "error_code": "MEDIA_ALREADY_LINKED"}
    assert d["after"] == {"context_type": "project", "context_id_is_first": True}


@real
@pytest.mark.parametrize("mode", MODES)
def test_fg541_a_non_member_is_forbidden_with_no_write(obs, mode):
    assert obs["fg541"]["owner_upload_other"] == 201
    m = obs["fg541"][mode]
    for role in ("viewer", "technician", "accountant", "requester"):
        assert m["upload_" + role] == 403, (mode, role)
        assert m["list_" + role] == 403, (mode, role)
        assert m["file_" + role] == 403, (mode, role)
    assert m["counts_after"]["photos"] == m["counts_before"]["photos"]
    assert m["counts_after"]["audit_logs"] == m["counts_before"]["audit_logs"]
    # member uploads in the same mode add exactly one file each; the denials add none
    assert m["counts_after"]["files"] == m["counts_before"]["files"]
    assert m["other_tenant_list"] == 404


@real
@pytest.mark.parametrize("mode", MODES)
def test_fg541_members_and_owner_keep_working(obs, mode):
    m = obs["fg541"][mode]
    assert m["member_upload"] == 201
    assert m["member_list"] == 200 and m["member_file"] == 200
    assert m["owner_list_other"] == 200 and m["owner_file_other"] == 200


@real
def test_fg541_an_uploader_removed_from_the_team_cannot_retire(obs):
    d = obs["fg541"]["retire_after_removal"]
    assert d["removed"] == 200
    assert d["status"] == 403 and d["photo_status"] is None


@real
@pytest.mark.parametrize("mode", MODES)
def test_r83_1_a_viewer_reads_project_photos_but_never_uploads(obs, mode):
    v = obs["r83"]["viewer"][mode]
    assert v["viewer_member_upload"] == 403
    assert v["project_viewer_sitemanager_upload"] == 403
    assert v["viewer_member_list"] == 200
    assert v["rows_added"] == 0
    assert v["technician_upload"] == 201


@real
def test_r83_2_a_used_file_needs_an_admin_request_and_the_owners_approval(obs):
    a = obs["r83"]["approval"]
    assert list(a["delete"]) == [409, "MEDIA_IN_USE"]
    # pass 46 minor: the uploader sees no record ids; Owner/Admin see which records
    assert "uses" not in a["delete_detail_technician"]
    assert {"use_kinds", "uses_count"} <= set(a["delete_detail_technician"])
    assert a["delete_detail_admin_uses"] == ["work_report"]
    assert a["req_no_key"] == 428 and a["req_no_reason"] == 400
    # interim policy (media_policy): an Admin files; the file's uploader / an Owner do not
    assert a["req_technician_owner_of_file"] == "RETIRE_REQUEST_NOT_ALLOWED"
    assert a["req_owner"] == "RETIRE_REQUEST_NOT_ALLOWED"
    assert a["req_other_tenant"] == 404
    assert a["request"] == {"status": 201, "req_status": "pending", "replay_same": True,
                            "has_version": True, "interim_until": "W0-07"}
    assert a["request_row"] == {"uses_kinds": ["work_report"], "uses_version": True,
                                "ref_version_kept": True}
    assert a["second_request"] == "RETIRE_REQUEST_PENDING"
    assert a["delete_while_pending"] == "MEDIA_IN_USE"
    assert a["approve_admin"] == "OWNER_APPROVAL_REQUIRED"
    assert a["approve_technician"] == "OWNER_APPROVAL_REQUIRED"
    assert a["approve_no_key"] == 428 and a["approve_other_tenant"] == 404
    assert a["before_approve"] == {"status": None, "events": ["media.file.retire_request"]}
    assert len(a["pending_list_owner"]) >= 1 and a["pending_list_technician"] == 403


@real
def test_fg577_no_new_reference_while_a_retire_request_is_pending(obs):
    a = obs["r83"]["approval"]
    assert a["link_while_pending"] == "RETIRE_REQUEST_PENDING"
    assert a["attach_while_pending"] == "RETIRE_REQUEST_PENDING"
    assert a["attach_not_written"] is True


@real
def test_fg577_an_approval_of_a_changed_set_of_holders_is_stale(obs):
    st = obs["r83"]["approval"]["stale"]
    assert st["request"] is True
    assert list(st["approve"]) == [409, "RETIRE_REQUEST_STALE"]
    assert st["media_status"] is None and st["request_status"] == "pending"


@real
def test_r83_2_the_approved_retire_keeps_the_file_and_the_reference(obs):
    ap = obs["r83"]["approval"]["approve"]
    assert ap["status"] == 200 and ap["replay_same"]
    assert ap["media_status"] == "retired" and ap["in_use"] is True
    assert ap["approved_by_owner"] and ap["retired_by_requester"]
    assert ap["reason"] == "снимката е на друг обект" and ap["pending"] is None
    assert ap["file_kept"] is True and ap["record_keeps_ref"] is True
    assert ap["meta_technician"] == 410
    assert ap["meta_technician_detail"] == {"error_code": "MEDIA_RETIRED",
                                            "media_id": ap["meta_technician_detail"]["media_id"],
                                            "retired": True}
    assert ap["meta_owner_status"] == "retired"
    assert ap["again"] == "RETIRE_REQUEST_DECIDED"
    assert [e["action"] for e in ap["events"]] == ["media.file.retire_request", "media.file.retire"]
    retire = ap["events"][1]
    assert retire["approved_by"] and retire["requested_by"]
    assert retire["reason"] == "снимката е на друг обект"


@real
def test_r83_2_the_requester_never_approves_and_a_reject_leaves_the_file(obs):
    s = obs["r83"]["approval"]["self"]
    assert s["request"] == 201
    assert s["approve"] == "SELF_APPROVAL_FORBIDDEN"
    assert s["reject_no_reason"] == 400 and s["reject"] == 200
    assert s["media_status"] is None and s["pending"] is None
    assert s["events"] == ["media.file.retire_request", "media.file.retire_request.reject"]
    assert s["request_again"] == 201
    assert obs["r83"]["approval"]["unused_request"] == "MEDIA_NOT_IN_USE"


@real
def test_r83_3_only_a_fresh_profile_upload_is_an_avatar_and_changes_are_audited(obs):
    a = obs["r83"]["avatars"]
    assert a["av_a_flag"] is True
    assert a["link_as_profile"] == "AVATAR_LINK_REFUSED" and a["loose_not_avatar"] == 404
    for k in ("put_site_photo", "put_file_form", "put_b_avatar", "put_other_users_profile"):
        assert a[k] == "AVATAR_NOT_ALLOWED", k
    assert a["after_refusals"] in (None, "")
    assert a["put_ok"] == 200 and a["after_put"] is True
    assert a["basic_put"] == 200 and a["basic_put_bad"] == "AVATAR_NOT_ALLOWED"
    assert [e["action"] for e in a["avatar_events"]] == ["user.avatar.change"] * 2
    assert all(e["after"].startswith("/api/media/avatar/") for e in a["avatar_events"])


@real
def test_r83_3_an_old_avatar_is_retired_by_its_owner_or_an_admin_the_current_one_never(obs):
    a = obs["r83"]["avatars"]
    assert a["current_avatar_delete"] == "MEDIA_IN_USE"
    assert a["old_other_user"] == 403
    assert a["old_owner"] == 200 and a["old_owner_status"] == "retired"
    assert a["old_avatar_served"] == 404
    assert a["old_admin"] == 200
    assert a["current_served"] == 200


@real
def test_r83_4_fg578_the_backfill_needs_an_owners_id_and_flags_only_uploaded_profiles(obs):
    b = obs["r83"]["backfill"]
    assert b["served_before"] == 404
    assert b["dry_no_approver"] == "NotApproved"
    assert b["dry_free_text"] == "NotApproved" and b["dry_admin_id"] == "NotApproved"
    assert b["dry"] == {"viewer": "flag", "admin_linked": "skip:linked_not_uploaded_as_profile",
                        "accountant": "skip:not_a_profile_photo",
                        "requester": "skip:url_shape", "technician": "already",
                        "applied": False, "only_tenant_a": True, "flag_written": None,
                        "audit_written": 0}
    assert b["b_owner_sees_only_b"] is True
    assert b["apply_wrong_sha"] == "PlanMismatch"


@real
def test_r83_4_fg578_a_write_that_matches_nothing_rolls_back(obs):
    b = obs["r83"]["backfill"]
    assert b["conflict"] == "conflict" and b["conflict_rolled_back"] is True


@real
def test_r83_4_the_backfill_applies_once_with_an_audit_event(obs):
    b = obs["r83"]["backfill"]
    ap = b["apply"]
    assert ap["written"] == 1 and ap["conflict"] == 0
    assert ap["flag"] is True and ap["linked_flag"] is None and ap["viewer_url"] is True
    assert ap["served_after"] == 200 and ap["site_photo_served"] == 404
    assert ap["events"] == [{"action": "media.avatar.backfill", "approved_by_owner": True}]
    assert b["second_apply_written"] == 0 and b["second_viewer_action"] == "already"


@real
def test_r83_4_fg578_revert_dry_runs_then_undoes_exactly_the_backfill(obs):
    b = obs["r83"]["backfill"]
    assert b["revert_dry"] == {"counts": {"revert": 1}, "applied": False, "flag_still": True}
    rv = b["revert"]
    assert rv["written"] == 1 and rv["flag"] is None and rv["viewer_url_restored"] is True
    assert rv["served"] == 404
    assert rv["events"] == ["media.avatar.backfill", "media.avatar.backfill_revert"]
    assert b["second_revert_rows"] == 0


@real
@pytest.mark.parametrize("kind", ["offer_acceptance", "warehouse_movement", "payment_receipt",
                                  "subcontractor_payment_receipt"])
def test_fg576_every_holder_blocks_the_uploaders_delete(obs, kind):
    c = obs["pass46"]["fg576"][kind]
    assert (c["status"], c["error_code"]) == (409, "MEDIA_IN_USE"), c
    assert c["kinds_shown_to_uploader"] == [kind] and c["ids_hidden_from_uploader"] is True
    assert c["admin_sees"] == [kind]
    assert c["status_after"] is None and c["file_kept"] is True


@real
def test_fg576_an_audit_event_naming_the_file_is_a_holder(obs):
    c = obs["pass46"]["fg576"]["audit_event"]
    assert (c["status"], c["error_code"]) == (409, "MEDIA_IN_USE")
    assert c["kinds_shown_to_uploader"] == ["audit_event"] and c["status_after"] is None
    assert obs["pass46"]["fg576"]["other_tenant_row"] == 200


@real
def test_fg575_one_upload_guard_refuses_a_viewer_everywhere_and_writes_nothing(obs):
    up = obs["pass46"]["fg575"]
    for k in ("media_upload_no_context", "media_upload_project_member", "photo_invoice",
              "ocr_upload", "supplier_invoice_file", "project_photo",
              "project_viewer_sitemanager_media_upload"):
        assert up[k] == 403, (k, up[k])
    assert up["written"] == {"files": 0, "media_rows": 0, "pending_expenses": 0}
    assert up["tech_photo_invoice"] == 201 and up["tech_media_upload"] == 200
    assert up["tech_photo_invoice_other_project"] == 403


@real
def test_fg579_a_reference_written_during_a_retire_wins_and_the_retire_refuses(obs):
    c = obs["pass46"]["fg579"]
    assert c["race_happened"] is True
    assert (c["status"], c["error_code"]) == (409, "MEDIA_IN_USE")
    assert c["media_status"] is None and c["reference_kept"] is True
    assert c["ref_version"] == 1
    assert c["attach_retired"] == "MEDIA_RETIRED"


@real
def test_fg544_a_link_writes_an_audit_event(obs):
    c = obs["pass46"]["fg544_link"]
    assert c["status"] == 200 and c["ref_version"] == 1
    assert c["events"] == [{"action": "media.file.link",
                            "after": {"context_type": "project",
                                      "context_id": c["events"][0]["after"]["context_id"]}}]


@real
def test_the_committed_evidence_is_a_run_of_this_harness():
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert set(data) == {"fg540", "fg541", "fg542", "fg544", "r83", "pass46"}


if __name__ == "__main__":
    sys.exit(main())
