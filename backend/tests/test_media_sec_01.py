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
                      "..", "...", "..%5C" + stored(av_a), stored(av_a) + "%00.jpg",
                      ".%2F" + stored(av_a), "projects%2F" + stored(av_a), "%2Fetc%2Fpasswd",
                      "..%252F" + stored(av_a), "x" * 300 + ".jpg"):
            traversal[probe[:40]] = call("GET", "/api/media/avatar/" + probe)["status"]
        d["traversal"] = traversal
        obs["fg540"] = d

        # ─────────────────────────────────────────────── FG-542 — no hard delete
        d = {}
        # linked (a profile avatar) -> 409
        r = call("DELETE", "/api/media/%s" % av_a["id"], role="technician", key="auto",
                 json={"reason": "стара снимка"})
        d["linked"] = {"status": r["status"], "error_code": r["error_code"],
                       "row_kept": bool(media_row(av_a["id"])),
                       "status_after": media_row(av_a["id"]).get("status"),
                       "file_kept": (UPLOADS / stored(av_a)).is_file(),
                       "events": events(av_a["id"], "media.")}
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
            "uses": ((r["body"] or {}).get("detail") or {}).get("uses")
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
    assert d["uses"] and d["uses"][0]["kind"] == "missing_smr"
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
def test_the_committed_evidence_is_a_run_of_this_harness():
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert set(data) == {"fg540", "fg541", "fg542", "fg544"}


if __name__ == "__main__":
    sys.exit(main())
