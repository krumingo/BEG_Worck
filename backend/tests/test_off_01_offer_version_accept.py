"""
OFF-01 — a superseded offer version cannot be accepted; a sent offer is never deleted.

Package: ``docs/architecture/tasks/OFF-01_OFFER_VERSION_ACCEPT_AND_NO_DELETE.md``
(branch ``claude/happy-meitner-bmcnel`` @ 174b4ee). Findings FG-129 (high), FG-130 (medium).
Canon: FLOW-003 „Версии“, „Клиентско одобрение“, „Какво НЕ трябва да позволява“ (стара/заменена
версия да бъде одобрена след публикуване на нова); FLOW-002 (клиентски линк); CLAUDE.md §2.9,
§8, §14; R29 (Idempotency-Key on contractual writes).

  1. new version → the old one is superseded in the same transaction (superseded_by, who,
     when), its review link revoked (kept, not deleted); /accept of the old one → 409
     OFFER_VERSION_SUPERSEDED;
  2. the public /respond on the old link → 409 with a neutral Bulgarian text, no internal ids;
  3. DELETE of a Sent / Rejected / Accepted / Superseded offer, or of a draft that is a new
     version of one → 409 OFFER_IN_USE, nothing changed; an unsent draft is still removable;
  4. accepting the CURRENT version works and writes a canonical AuditEvent with the exact
     version and the approval method (internal and magic link);
  5. a sent offer is cancelled instead (status Cancelled + reason + AuditEvent, link revoked);
  6. Idempotency-Key: missing → 428 nothing written; replay → the first result, written once;
  7. concurrency ×10: new-version ∥ accept of the old one → never both; two new-versions → one;
     new-version ∥ public approve → never both;
  8. forbidden: roles without the right, another tenant, a deployment without transactions.

Every transactional scenario runs on a REAL MongoDB replica set (``W0_03_REAL_MONGO_URL``,
local only), in PERMISSION_SERVICE_MODE off / shadow / enforce. The checks that refuse
before any transaction opens also run on mongomock.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27017/?replicaSet=rs0' \\
        PYTHONPATH=. pytest tests/test_off_01_offer_version_accept.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import uuid

import pytest

from tests.test_r0_05_pay_run_selected_only import _real_refusal, _token

ORG_A, ORG_B = "ORG-OFF01-A", "ORG-OFF01-B"
USERS = {
    "owner-a": (ORG_A, "Owner"), "admin-a": (ORG_A, "Admin"), "acct-a": (ORG_A, "Accountant"),
    "viewer-a": (ORG_A, "Viewer"), "site-a": (ORG_A, "SiteManager"), "site-x": (ORG_A, "SiteManager"),
    "tech-a": (ORG_A, "Technician"), "admin-b": (ORG_B, "Admin"),
}
MODES = ["off", "shadow", "enforce"]
PRJ_A, PRJ_B = "prj-off01-a", "prj-off01-b"
TOKEN = "tok" + "a" * 21
COLLS = ("offers", "offer_events", "offer_versions", "audit_events", "audit_logs", "audit_idempotency",
         "media_files")

REAL = pytest.param("real", marks=pytest.mark.skipif(bool(_real_refusal()),
                                                     reason=_real_refusal() or "ok"))


@pytest.fixture(params=[REAL])
def backend(request):
    """Transactional scenarios: a real replica set only (mongomock has no transactions)."""
    return request.param


@pytest.fixture(params=["mongomock", REAL])
def any_backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


def hdr(uid, key=None):
    """Auth headers; ``key=None`` sends a fresh Idempotency-Key, a string that key, False none."""
    org, role = USERS[uid]
    h = _token(uid, org, role)
    if key is None:
        key = "auto-" + uuid.uuid4().hex
    if key:
        h["Idempotency-Key"] = key
    return h


def pub(key=None):
    """Headers of the public (unauthenticated) review link."""
    if key is None:
        key = "pub-" + uuid.uuid4().hex
    return {"Idempotency-Key": key} if key else {}


# ═══════════════════════════════════════════════════════════════════ harness
class _Dbs:
    def __init__(self, backend):
        tag = uuid.uuid4().hex[:10]
        self.backend, self.client = backend, None
        self.names = ("off01_op_" + tag, "off01_sys_" + tag)

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.names[0]], self.client[self.names[1]]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            for name in self.names:
                await self.client.drop_database(name)
            self.client.close()


def offer_doc(oid, status="Sent", version=1, org=ORG_A, project=PRJ_A, token=None, parent=None,
              total=1200.0, **extra):
    doc = {
        "id": oid, "org_id": org, "project_id": project, "offer_no": "OFF-0001",
        "title": "Баня", "status": status, "version": version, "parent_offer_id": parent,
        "currency": "EUR", "vat_percent": 20,
        "lines": [{"id": "ln-" + oid, "activity_name": "Плочки", "unit": "m2", "qty": 10,
                   "material_unit_cost": 40, "labor_unit_cost": 60, "line_total": 1000.0}],
        "subtotal": 1000.0, "vat_amount": 200.0, "total": total, "notes": "",
        "created_at": "2026-11-01T10:00:00+00:00", "updated_at": "2026-11-01T10:00:00+00:00",
        "sent_at": "2026-11-02T10:00:00+00:00" if status != "Draft" else None, "accepted_at": None,
    }
    if token:
        doc["review_token"] = token
    doc.update(extra)
    return doc


async def _seed(op, sysdb):
    from app.permissions.catalog import LEGACY_ROLE_MAP
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org, "phone": "1", "email": "o@x"})
        await op.subscriptions.insert_one({"id": "sub-" + org, "org_id": org, "plan_id": "enterprise",
                                           "status": "active"})
        await sysdb.tenant_registry.insert_one({"id": org, "legacy_org_id": org, "status": "active",
                                                "database_name": op.name})
    for uid, (org, role) in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": org, "role": role, "is_active": True,
                                   "email": uid + "@off01.example", "first_name": uid, "last_name": "T"})
        await sysdb.tenant_memberships.insert_one({"id": "tm_" + uid, "user_id": uid, "tenant_id": org,
                                                   "status": "active"})
        await sysdb.tenant_role_assignments.insert_one({
            "id": "ra_" + uid, "user_id": uid, "tenant_id": org, "role_id": LEGACY_ROLE_MAP[role],
            "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
            "status": "active", "sync_source": "users.role"})
    # Addendum A §3: the tenant's file store (media_files — the File Registry W0-06 is not built)
    for fid, org, ctype, cid in (("file-123", ORG_A, None, None), ("file-prj", ORG_A, "project", PRJ_A),
                                 ("file-other-prj", ORG_A, "project", "prj-elsewhere"),
                                 ("file-of-b", ORG_B, None, None)):
        await op.media_files.insert_one({"id": fid, "org_id": org, "owner_user_id": "admin-a",
                                         "filename": fid + ".pdf", "stored_filename": fid + ".pdf",
                                         "context_type": ctype, "context_id": cid})
    for prj, org in ((PRJ_A, ORG_A), (PRJ_B, ORG_B)):
        await op.projects.insert_one({"id": prj, "org_id": org, "code": prj, "name": prj,
                                      "status": "Active"})
    await op.project_team.insert_one({"id": "pt-site-a", "org_id": ORG_A, "project_id": PRJ_A,
                                      "user_id": "site-a", "role_in_project": "SiteManager",
                                      "active": True})


def _app(monkeypatch, op, sysdb, mode):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth, modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.routes import finance as r_finance, offer_versions as r_versions, offers as r_offers
    from app.tenancy import guard, registry, resolver
    from app.utils import audit as u_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    for module in (appdb, deps_auth, deps_modules, r_finance, r_offers, r_versions, u_audit):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for coll in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, coll, sysdb[coll])

    async def _get_db(tenant_id, require_operational=False):
        return op
    monkeypatch.setattr(resolver, "get_tenant_db", _get_db)
    monkeypatch.setattr(guard, "get_tenant_db", _get_db)
    app = FastAPI()
    app.include_router(r_offers.router, prefix="/api")
    app.include_router(r_versions.router, prefix="/api")
    return app


async def _bootstrap_indexes(op):
    from scripts.w0_04_bootstrap_audit_indexes import PLANNED_INDEXES
    for coll, keys, opts in PLANNED_INDEXES:
        await op[coll].create_index(keys, **opts)


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _bootstrap_indexes(op)
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://off01") as c:
                return await scenario(c, op)
    return asyncio.run(go())


async def snap(op, colls=COLLS):
    import bson
    out = {}
    for coll in colls:
        docs = await op[coll].find({}, {"_id": 0}).to_list(None)
        out[coll] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d)}) for d in docs)
    return out


async def get(op, oid):
    return await op.offers.find_one({"id": oid}, {"_id": 0})


async def events(op, action):
    return await op.audit_events.find({"action": action}, {"_id": 0}).to_list(None)


def code(r):
    d = r.json().get("detail")
    return d.get("error_code") if isinstance(d, dict) else None


async def new_version(c, oid, who="admin-a", key=None):
    return await c.post("/api/offers/%s/new-version" % oid, headers=hdr(who, key))


async def accept(c, oid, who="admin-a", key=None, body=None):
    return await c.post("/api/offers/%s/accept" % oid, headers=hdr(who, key), json=body)


async def respond(c, token, action="approve", key=None):
    return await c.post("/api/offers/review/%s/respond" % token, headers=pub(key),
                        json={"action": action, "comment": "ok", "client_name": "Иван"})


async def cancel(c, oid, who="admin-a", key=None, reason="клиентът се отказа"):
    body = {"reason": reason} if reason is not None else {}
    return await c.post("/api/offers/%s/cancel" % oid, headers=hdr(who, key), json=body)


# ═══════════════════════════════════════════ 1. FG-129: the old version via /accept
def test_01_superseded_version_cannot_be_accepted(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        r = await new_version(c, "o1")
        assert r.status_code == 200, r.text
        v2 = r.json()
        assert v2["version"] == 2 and v2["parent_offer_id"] == "o1" and v2["status"] == "Draft"
        assert "review_token" not in v2

        old = await get(op, "o1")
        assert old["status"] == "Superseded" and old["superseded_by"] == v2["id"]
        assert old["superseded_by_user"] == "admin-a" and old["superseded_at"]
        assert old["status_before_supersede"] == "Sent"
        assert old["review_token"] == TOKEN                         # kept, not deleted
        assert old["review_token_status"] == "revoked"
        assert old["review_token_revoked_reason"] == "superseded"
        ev = await events(op, "offers.offer.superseded")
        assert len(ev) == 1 and ev[0]["entity_id"] == "o1" and ev[0]["entity_version"] == "1"
        assert ev[0]["structured_diff"]["superseded_by"] == v2["id"]

        before = await snap(op)
        r = await accept(c, "o1")
        assert r.status_code == 409, r.text
        assert code(r) == "OFFER_VERSION_SUPERSEDED"
        after = await snap(op)
        for coll in ("offers", "audit_events", "audit_logs", "offer_events"):
            assert after[coll] == before[coll], coll

        # the old version cannot be versioned again either (the chain has one head)
        r = await new_version(c, "o1")
        assert r.status_code == 409 and code(r) == "OFFER_VERSION_SUPERSEDED", r.text
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════ 2. FG-129: the old version via the public link
def test_02_superseded_version_cannot_be_approved_by_the_old_link(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        r = await new_version(c, "o1")
        assert r.status_code == 200, r.text
        v2_id = r.json()["id"]
        before = await snap(op)
        for action in ("approve", "reject", "revision"):
            r = await respond(c, TOKEN, action)
            assert r.status_code == 409, r.text
            detail = r.json()["detail"]
            assert detail["error_code"] == "OFFER_VERSION_SUPERSEDED"
            text = r.text
            for internal in (v2_id, "o1", ORG_A, PRJ_A, "admin-a", "superseded_by"):
                assert internal not in text, internal
            assert any("Ѐ" <= ch <= "ӿ" for ch in detail["message"])   # Bulgarian
        after = await snap(op)
        for coll in ("offers", "audit_events", "offer_events"):
            assert after[coll] == before[coll], coll
        # the review page itself still opens and says the version is replaced
        g = await c.get("/api/offers/review/" + TOKEN)
        assert g.status_code == 200, g.text
        assert g.json()["status"] == "Superseded"
        assert (await get(op, "o1"))["status"] == "Superseded"
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════ 3. FG-130: no delete of a used offer
def test_03_sent_offer_is_never_deleted(monkeypatch, any_backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o-sent", token=TOKEN))
        await op.offers.insert_one(offer_doc("o-rej", status="Rejected", token="t2" + "b" * 22))
        await op.offers.insert_one(offer_doc("o-acc", status="Accepted"))
        await op.offers.insert_one(offer_doc("o-sup", status="Superseded", superseded_by="o-v2"))
        await op.offers.insert_one(offer_doc("o-can", status="Cancelled"))
        await op.offers.insert_one(offer_doc("o-v2", status="Draft", version=2, parent="o-sup"))
        await op.offers.insert_one(offer_doc("o-rev", status="NeedsRevision"))
        # a draft that was sent once (sent_at kept) is a used record too
        await op.offers.insert_one(offer_doc("o-was-sent", status="Draft",
                                             sent_at="2026-11-02T10:00:00+00:00"))
        await op.offers.insert_one(offer_doc("o-draft", status="Draft"))
        before = await snap(op)
        for oid in ("o-sent", "o-rej", "o-acc", "o-sup", "o-can", "o-v2", "o-rev", "o-was-sent"):
            r = await c.delete("/api/offers/" + oid, headers=hdr("admin-a"))
            assert r.status_code == 409, (oid, r.text)
            assert code(r) == "OFFER_IN_USE", oid
        after = await snap(op)
        assert after == before                                   # nothing deleted, nothing written

        # an unsent draft is still removable (unchanged rule)
        r = await c.delete("/api/offers/o-draft", headers=hdr("admin-a"))
        assert r.status_code == 200, r.text
        assert await get(op, "o-draft") is None
        # roles: unchanged — only Admin/Owner
        await op.offers.insert_one(offer_doc("o-draft2", status="Draft"))
        for who in ("site-a", "viewer-a", "acct-a"):
            r = await c.delete("/api/offers/o-draft2", headers=hdr(who))
            assert r.status_code == 403, (who, r.text)
        assert await get(op, "o-draft2") is not None
    run(monkeypatch, any_backend, mode, scenario)


# ════════════════════════════════════════════ 4. accepting the CURRENT version works
def test_04_current_version_is_accepted_with_exact_version_evidence(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        r = await new_version(c, "o1")
        v2_id = r.json()["id"]
        r = await c.post("/api/offers/%s/send" % v2_id, headers=hdr("admin-a"))
        assert r.status_code == 200, r.text
        v2_token = r.json()["review_token"]
        assert v2_token != TOKEN
        assert (await get(op, v2_id))["review_token_version"] == 2

        r = await accept(c, v2_id, key="acc-1",
                         body={"approval_method": "signed_pdf", "evidence_file_id": "file-123"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "Accepted"
        doc = await get(op, v2_id)
        assert doc["status"] == "Accepted" and doc["accepted_by"] == "admin-a"
        assert doc["approval"]["method"] == "signed_pdf" and doc["approval"]["version"] == 2
        assert doc["approval"]["evidence_file_id"] == "file-123"
        ev = await events(op, "offers.offer.accepted")
        assert len(ev) == 1
        e = ev[0]
        assert e["entity_id"] == v2_id and e["entity_version"] == "2" and e["tenant_id"] == ORG_A
        assert e["source_flow"] == "FLOW-003" and e["actor_id"] == "admin-a"
        assert e["idempotency_key"] == "acc-1" and e["related_file_ids"] == ["file-123"]
        assert e["structured_diff"]["approval_method"] == "signed_pdf"
        assert e["structured_diff"]["total"] == 1200.0

        # replay: the same key → the first result, nothing written twice
        before = await snap(op)
        r2 = await accept(c, v2_id, key="acc-1",
                          body={"approval_method": "signed_pdf", "evidence_file_id": "file-123"})
        assert r2.status_code == 200 and r2.json() == r.json(), r2.text
        after = await snap(op)
        for coll in ("offers", "audit_events", "audit_logs"):
            assert after[coll] == before[coll], coll
        # same key, other request → 409; new key on an accepted offer → 400 (not Sent)
        r3 = await accept(c, v2_id, key="acc-1", body={"approval_method": "verified_email"})
        assert r3.status_code == 409 and code(r3) == "IDEMPOTENCY_KEY_REUSED", r3.text
        r4 = await accept(c, v2_id)
        assert r4.status_code == 400, r4.text
        # an unknown approval method is refused before anything is written
        await op.offers.insert_one(offer_doc("o3", token="t3" + "c" * 22))
        r5 = await accept(c, "o3", body={"approval_method": "verbal"})
        assert r5.status_code == 422, r5.text
        assert (await get(op, "o3"))["status"] == "Sent"
        # no body: still accepted (the internal button), the method is recorded as such
        r6 = await accept(c, "o3")
        assert r6.status_code == 200, r6.text
        assert (await get(op, "o3"))["approval"]["method"] == "internal_unspecified"
    run(monkeypatch, backend, mode, scenario)


def test_05_current_version_is_approved_by_its_link(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN, review_token_version=1))
        r = await respond(c, TOKEN, "approve", key="p-1")
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "status": "Accepted"}
        doc = await get(op, "o1")
        assert doc["status"] == "Accepted" and doc["approval"]["method"] == "magic_link"
        assert doc["approval"]["version"] == 1 and doc["client_name"] == "Иван"
        ev = await events(op, "offers.offer.client_approved")
        assert len(ev) == 1
        e = ev[0]
        assert e["actor_type"] == "external_principal" and e["entity_version"] == "1"
        assert e["source_channel"] == "magic_link" and e["idempotency_key"] == "p-1"
        assert TOKEN not in str(e)                                   # the link is not logged
        # replay
        before = await snap(op)
        r2 = await respond(c, TOKEN, "approve", key="p-1")
        assert r2.status_code == 200 and r2.json() == r.json()
        assert await snap(op) == before
        # already processed → unchanged 400 text
        r3 = await respond(c, TOKEN, "reject")
        assert r3.status_code == 400, r3.text
        # reject / revision on another current version write their own event
        await op.offers.insert_one(offer_doc("o2", token="t2" + "d" * 22))
        r4 = await respond(c, "t2" + "d" * 22, "revision")
        assert r4.status_code == 200 and r4.json()["status"] == "NeedsRevision", r4.text
        assert len(await events(op, "offers.offer.client_revision_requested")) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════ 5. cancel instead of delete
def test_06_sent_offer_is_cancelled_not_deleted(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        r = await cancel(c, "o1", reason=None)
        assert r.status_code == 400 and code(r) == "REASON_REQUIRED", r.text
        r = await cancel(c, "o1", reason="   ")
        assert r.status_code == 400 and code(r) == "REASON_REQUIRED", r.text
        for who in ("viewer-a", "site-a", "acct-a", "tech-a"):
            r = await cancel(c, "o1", who=who)
            assert r.status_code == 403, (who, r.text)
        assert (await get(op, "o1"))["status"] == "Sent"

        r = await cancel(c, "o1", key="c-1")
        assert r.status_code == 200, r.text
        doc = await get(op, "o1")
        assert doc["status"] == "Cancelled" and doc["cancel_reason"] == "клиентът се отказа"
        assert doc["cancelled_by"] == "admin-a" and doc["cancelled_at"]
        assert doc["status_before_cancel"] == "Sent"
        assert doc["review_token"] == TOKEN and doc["review_token_status"] == "revoked"
        assert doc["review_token_revoked_reason"] == "cancelled"
        ev = await events(op, "offers.offer.cancelled")
        assert len(ev) == 1 and ev[0]["reason"] == "клиентът се отказа"
        assert ev[0]["idempotency_key"] == "c-1" and ev[0]["entity_version"] == "1"
        # replay
        before = await snap(op)
        r2 = await cancel(c, "o1", key="c-1")
        assert r2.status_code == 200 and r2.json() == r.json()
        assert await snap(op) == before
        # cancelled: no accept, no client answer, no second cancel
        r = await accept(c, "o1")
        assert r.status_code == 400, r.text
        r = await respond(c, TOKEN, "approve")
        assert r.status_code == 409 and code(r) == "OFFER_NOT_OPEN", r.text
        assert "o1" not in r.text and ORG_A not in r.text
        r = await cancel(c, "o1")
        assert r.status_code == 409 and code(r) == "OFFER_NOT_CANCELLABLE", r.text

        # an accepted offer is not cancelled here (canon silent → debt D-OFF01-3)
        await op.offers.insert_one(offer_doc("o-acc", status="Accepted"))
        r = await cancel(c, "o-acc")
        assert r.status_code == 409 and code(r) == "OFFER_NOT_CANCELLABLE", r.text
        # a never-sent draft is deleted, not cancelled
        await op.offers.insert_one(offer_doc("o-d", status="Draft"))
        r = await cancel(c, "o-d")
        assert r.status_code == 409 and code(r) == "OFFER_NOT_CANCELLABLE", r.text
        # a draft new version (cannot be deleted) can be cancelled
        await op.offers.insert_one(offer_doc("o-v2", status="Draft", version=2, parent="o-x"))
        r = await cancel(c, "o-v2")
        assert r.status_code == 200, r.text
        # another tenant: 404, nothing changed
        r = await cancel(c, "o-acc", who="admin-b")
        assert r.status_code == 404, r.text
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════════ 6. Idempotency-Key
def test_07_contractual_writes_without_a_key_are_refused(monkeypatch, any_backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        before = await snap(op)
        for r in (await new_version(c, "o1", key=False), await accept(c, "o1", key=False),
                  await cancel(c, "o1", key=False), await respond(c, TOKEN, key=False)):
            assert r.status_code == 428, r.text
            assert code(r) == "IDEMPOTENCY_KEY_REQUIRED"
        assert await snap(op) == before
        # permission and tenant checks still come first (unchanged answers)
        r = await accept(c, "o1", who="site-a", key=False)
        assert r.status_code == 403, r.text
        r = await accept(c, "o1", who="admin-b", key=False)
        assert r.status_code == 404, r.text
        r = await respond(c, "nope" * 6, key=False)
        assert r.status_code == 404, r.text
    run(monkeypatch, any_backend, mode, scenario)


def test_08_without_transactions_nothing_is_written(monkeypatch, mode):
    """A deployment that cannot run transactions refuses the write (503), writes nothing."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        before = await snap(op, ("offers", "offer_events", "audit_events", "audit_logs"))
        for r in (await new_version(c, "o1"), await accept(c, "o1"), await cancel(c, "o1"),
                  await respond(c, TOKEN)):
            assert r.status_code == 503, r.text
            assert code(r) == "TRANSACTIONS_UNAVAILABLE"
        assert await snap(op, ("offers", "offer_events", "audit_events", "audit_logs")) == before
    run(monkeypatch, "mongomock", mode, scenario)


# ════════════════════════════════════════════════════════════════════ 7. concurrency
ROUNDS = 10


def test_09_new_version_races_accept_of_the_old_one(monkeypatch, backend, mode):
    async def scenario(c, op):
        for i in range(ROUNDS):
            oid = "race-%d" % i
            await op.offers.insert_one(offer_doc(oid, token="tr%02d" % i + "e" * 20))
            a, b = await asyncio.gather(new_version(c, oid), accept(c, oid))
            ok = [r for r in (a, b) if r.status_code == 200]
            assert len(ok) == 1, (i, a.status_code, a.text, b.status_code, b.text)
            doc = await get(op, oid)
            children = await op.offers.count_documents({"parent_offer_id": oid})
            if a.status_code == 200:                    # the new version won
                assert doc["status"] == "Superseded" and children == 1
                assert b.status_code == 409, b.text
                assert not await op.audit_events.count_documents(
                    {"action": "offers.offer.accepted", "entity_id": oid})
            else:                                       # the acceptance won
                assert doc["status"] == "Accepted" and not doc.get("superseded_by")
                assert children == 0
                assert a.status_code == 409, a.text
    run(monkeypatch, backend, mode, scenario)


def test_10_two_new_versions_only_one_wins(monkeypatch, backend, mode):
    async def scenario(c, op):
        for i in range(ROUNDS):
            oid = "twin-%d" % i
            await op.offers.insert_one(offer_doc(oid))
            a, b = await asyncio.gather(new_version(c, oid), new_version(c, oid))
            codes = sorted((a.status_code, b.status_code))
            assert codes == [200, 409], (i, a.text, b.text)
            assert await op.offers.count_documents({"parent_offer_id": oid}) == 1
            win = a if a.status_code == 200 else b
            assert (await get(op, oid))["superseded_by"] == win.json()["id"]
            assert len([e for e in await events(op, "offers.offer.superseded")
                        if e["entity_id"] == oid]) == 1
    run(monkeypatch, backend, mode, scenario)


def test_11_new_version_races_the_public_approval(monkeypatch, backend, mode):
    async def scenario(c, op):
        for i in range(ROUNDS):
            oid, tok = "pub-%d" % i, "tp%02d" % i + "f" * 20
            await op.offers.insert_one(offer_doc(oid, token=tok))
            a, b = await asyncio.gather(new_version(c, oid), respond(c, tok, "approve"))
            ok = [r for r in (a, b) if r.status_code == 200]
            assert len(ok) == 1, (i, a.status_code, a.text, b.status_code, b.text)
            doc = await get(op, oid)
            if a.status_code == 200:
                assert doc["status"] == "Superseded"
                assert b.status_code == 409 and code(b) == "OFFER_VERSION_SUPERSEDED", b.text
            else:
                assert doc["status"] == "Accepted" and not doc.get("superseded_by")
                assert await op.offers.count_documents({"parent_offer_id": oid}) == 0
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════════════════════════════ 8. forbidden
def test_12_forbidden_roles_and_other_tenant(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        await op.offers.insert_one(offer_doc("ob", org=ORG_B, project=PRJ_B))
        before = await snap(op)
        for who in ("site-a", "viewer-a", "acct-a", "tech-a"):        # unchanged: Admin/Owner
            assert (await accept(c, "o1", who=who)).status_code == 403, who
        for who in ("site-x", "viewer-a", "acct-a", "tech-a"):        # unchanged: managers
            assert (await new_version(c, "o1", who=who)).status_code == 403, who
        for r in (await accept(c, "o1", who="admin-b"), await new_version(c, "o1", who="admin-b"),
                  await accept(c, "ob"), await new_version(c, "ob"), await cancel(c, "ob")):
            assert r.status_code == 404, r.text
        assert await snap(op) == before
        # the project manager may still version (unchanged rule)
        r = await new_version(c, "o1", who="site-a")
        assert r.status_code == 200, r.text
    run(monkeypatch, backend, mode, scenario)


# ═════════════════════════════════════════════ Addendum A (07.11) — audit OFF79-01/02
def _snapshot(oid, n=1, total=12.0):
    return {"id": "ver-%s-%d" % (oid, n), "org_id": ORG_A, "project_id": PRJ_A, "offer_id": oid,
            "version_number": n, "created_at": "2026-11-01T09:00:00+00:00", "created_by": "admin-a",
            "note": "old", "is_auto_backup": False,
            "snapshot_json": {"title": "Баня", "currency": "EUR", "vat_percent": 20, "notes": "",
                              "lines": [{"id": "ln-x", "activity_name": "Плочки", "unit": "m2",
                                         "qty": 1, "material_unit_cost": 5, "labor_unit_cost": 5,
                                         "line_total": 10.0}],
                              "subtotal": 10.0, "vat_amount": 2.0, "total": total}}


def test_13_restore_and_snapshot_delete_only_on_an_unsent_draft(monkeypatch, any_backend, mode):
    """OFF79-01 = D-OFF01-7: restore rewrote a Sent offer 1200 → 12 and the client accepted 12."""
    async def scenario(c, op):
        used = {"o-sent": dict(status="Sent", token=TOKEN),
                "o-acc": dict(status="Accepted"),
                "o-sup": dict(status="Superseded", superseded_by="o-v2"),
                "o-can": dict(status="Cancelled"),
                "o-rej": dict(status="Rejected"),
                "o-v2": dict(status="Draft", version=2, parent="o-sup"),
                "o-was-sent": dict(status="Draft", sent_at="2026-11-02T10:00:00+00:00")}
        for oid, kw in used.items():
            await op.offers.insert_one(offer_doc(oid, **kw))
            await op.offer_versions.insert_one(_snapshot(oid, 1))
            await op.offer_versions.insert_one(_snapshot(oid, 2))
        before = await snap(op)
        for oid in used:
            r = await c.post("/api/offers/%s/versions/1/restore" % oid, headers=hdr("admin-a"))
            assert r.status_code == 409 and code(r) == "OFFER_IN_USE", (oid, r.text)
            r = await c.delete("/api/offers/%s/versions/1" % oid, headers=hdr("admin-a"))
            assert r.status_code == 409 and code(r) == "OFFER_IN_USE", (oid, r.text)
        assert await snap(op) == before                    # 1200 stays 1200, no snapshot gone
        assert (await get(op, "o-sent"))["total"] == 1200.0

        # a never-sent draft: restore and snapshot delete still work (unchanged rule)
        await op.offers.insert_one(offer_doc("o-d", status="Draft"))
        await op.offer_versions.insert_one(_snapshot("o-d", 1))
        await op.offer_versions.insert_one(_snapshot("o-d", 2))
        r = await c.post("/api/offers/o-d/versions/1/restore", headers=hdr("admin-a"))
        assert r.status_code == 200, r.text
        assert (await get(op, "o-d"))["total"] == 12.0
        r = await c.delete("/api/offers/o-d/versions/2", headers=hdr("admin-a"))
        assert r.status_code == 200, r.text
    run(monkeypatch, any_backend, mode, scenario)


def test_14_accepted_offer_gets_no_new_version(monkeypatch, backend, mode):
    """D-OFF01-2 (FLOW-003 „След приемане … само при ново възлагане/анекс“; FLOW-005)."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o-acc", status="Accepted"))
        before = await snap(op)
        r = await new_version(c, "o-acc")
        assert r.status_code == 409 and code(r) == "OFFER_ACCEPTED_USE_ANNEX", r.text
        after = await snap(op)          # the refused key stays recorded as failed (W0-04)
        for coll in ("offers", "offer_events", "audit_events", "audit_logs"):
            assert after[coll] == before[coll], coll

        # Sent v1 → v2 → v1 Superseded; v2 sent and accepted → exactly one accepted version
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        v2 = (await new_version(c, "o1")).json()["id"]
        assert (await get(op, "o1"))["status"] == "Superseded"
        assert (await c.post("/api/offers/%s/send" % v2, headers=hdr("admin-a"))).status_code == 200
        assert (await accept(c, v2)).status_code == 200
        assert (await accept(c, "o1")).status_code == 409
        assert (await new_version(c, v2)).status_code == 409
        chain = await op.offers.count_documents({"id": {"$in": ["o1", v2]}, "status": "Accepted"})
        assert chain == 1

        # Draft and Rejected may be versioned; the old one is superseded
        for oid, st in (("o-dr", "Draft"), ("o-rj", "Rejected")):
            await op.offers.insert_one(offer_doc(oid, status=st))
            r = await new_version(c, oid)
            assert r.status_code == 200, (oid, r.text)
            old = await get(op, oid)
            assert old["status"] == "Superseded" and old["status_before_supersede"] == st
    run(monkeypatch, backend, mode, scenario)


def test_15_accept_evidence_must_be_a_file_of_this_tenant(monkeypatch, backend, mode):
    """D-OFF01-5 / OFF79-02 (CLAUDE.md §2.6): the evidence file must exist in this tenant's
    file store and be linked (or linkable) to the offer's project."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        before = await snap(op)
        for fid, want in (("file-of-nobody", "EVIDENCE_FILE_NOT_FOUND"),
                          ("file-of-b", "EVIDENCE_FILE_NOT_FOUND"),
                          ("file-other-prj", "EVIDENCE_FILE_NOT_LINKABLE")):
            r = await accept(c, "o1", body={"approval_method": "signed_pdf", "evidence_file_id": fid})
            assert r.status_code == 422 and code(r) == want, (fid, r.text)
            assert ORG_B not in r.text
        after = await snap(op)
        for coll in ("offers", "audit_events", "audit_logs", "media_files"):
            assert after[coll] == before[coll], coll
        r = await accept(c, "o1", body={"approval_method": "signed_pdf", "evidence_file_id": "file-prj"})
        assert r.status_code == 200, r.text
        assert (await get(op, "o1"))["approval"]["evidence_file_id"] == "file-prj"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════ audit OFF79-03 / legacy pairs (orchestrator, 07.11, after 449c1f4)
def test_16_restore_or_edit_racing_send_never_leaves_a_sent_offer_unlike_its_snapshot(
        monkeypatch, backend, mode):
    """OFF79-03: restore read „Draft“, then wrote unconditionally — racing /send it left the
    offer Sent at 12 while the send snapshot said 1200. Every draft write is now a CAS."""
    async def scenario(c, op):
        stats = {"restore": 0, "send": 0, "lines": 0}
        for i in range(ROUNDS):
            for rival in ("restore", "lines"):
                oid = "rr-%s-%d" % (rival, i)
                await op.offers.insert_one(offer_doc(oid, status="Draft"))
                await op.offer_versions.insert_one(_snapshot(oid, 1, total=12.0))
                if rival == "restore":
                    other = c.post("/api/offers/%s/versions/1/restore" % oid, headers=hdr("admin-a"))
                else:
                    other = c.put("/api/offers/%s/lines" % oid, headers=hdr("admin-a"), json={
                        "lines": [{"activity_name": "Плочки", "unit": "m2", "qty": 1,
                                   "material_unit_cost": 5, "labor_unit_cost": 5}]})
                s, o = await asyncio.gather(
                    c.post("/api/offers/%s/send" % oid, headers=hdr("admin-a")), other)
                assert sorted((s.status_code, o.status_code)) in ([200, 409],), (
                    i, rival, s.status_code, s.text, o.status_code, o.text)
                doc = await get(op, oid)
                sent_snaps = await op.offer_versions.find(
                    {"offer_id": oid, "is_auto_backup": True, "snapshot_json.status": "Sent"},
                    {"_id": 0}).to_list(None)
                if s.status_code == 200:
                    stats["send"] += 1
                    assert doc["status"] == "Sent" and doc["total"] == 1200.0, (rival, doc["total"])
                    assert len(sent_snaps) == 1 and sent_snaps[0]["snapshot_json"]["total"] == 1200.0
                    assert o.status_code == 409 and code(o) == "OFFER_IN_USE", o.text
                else:
                    stats[rival] += 1
                    assert doc["status"] == "Draft" and doc["total"] != 1200.0
                    assert sent_snaps == []
                    assert s.status_code == 409 and code(s) == "OFFER_CHANGED", s.text
        assert stats["send"] > 0
    run(monkeypatch, backend, mode, scenario)


def test_17_a_legacy_pair_never_ends_with_two_accepted_versions(monkeypatch, backend, mode):
    """A v1/v2 pair linked before OFF-01 (v1 not marked superseded): once one version of the
    family is accepted, the other → 409 OFFER_FAMILY_ALREADY_ACCEPTED (internal + public)."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("ov1", token=TOKEN))
        await op.offers.insert_one(offer_doc("ov2", version=2, parent="ov1", status="Accepted"))
        before = await snap(op)
        r = await accept(c, "ov1")
        assert r.status_code == 409 and code(r) == "OFFER_FAMILY_ALREADY_ACCEPTED", r.text
        r = await respond(c, TOKEN)
        assert r.status_code == 409 and code(r) == "OFFER_FAMILY_ALREADY_ACCEPTED", r.text
        assert "ov2" not in r.text and ORG_A not in r.text
        after = await snap(op)
        for coll in ("offers", "offer_events", "audit_events", "audit_logs"):
            assert after[coll] == before[coll], coll
        # a three-version chain: the accepted one is the root, the caller the grandchild
        await op.offers.insert_one(offer_doc("ow1", status="Accepted", offer_no="OFF-0009"))
        await op.offers.insert_one(offer_doc("ow2", version=2, parent="ow1", status="Rejected"))
        await op.offers.insert_one(offer_doc("ow3", version=3, parent="ow2", token="tw3" + "z" * 21))
        r = await accept(c, "ow3")
        assert r.status_code == 409 and code(r) == "OFFER_FAMILY_ALREADY_ACCEPTED", r.text

        # races: two Sent versions of one legacy family, accepted at once → exactly one
        for i in range(ROUNDS):
            a1, a2 = "lg1-%d" % i, "lg2-%d" % i
            t1, t2 = "tl1%02d" % i + "y" * 19, "tl2%02d" % i + "y" * 19
            await op.offers.insert_one(offer_doc(a1, token=t1))
            await op.offers.insert_one(offer_doc(a2, version=2, parent=a1, token=t2))
            x, y = await asyncio.gather(accept(c, a1), respond(c, t2))
            assert sorted((x.status_code, y.status_code)) == [200, 409], (i, x.text, y.text)
            loser = x if x.status_code == 409 else y
            assert code(loser) == "OFFER_FAMILY_ALREADY_ACCEPTED", loser.text
            assert await op.offers.count_documents({"id": {"$in": [a1, a2]},
                                                    "status": "Accepted"}) == 1
    run(monkeypatch, backend, mode, scenario)
