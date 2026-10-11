"""
LIVE-OPS-01 / TASK 5B — Material Request safe-write core, over real HTTP on a
REAL MongoDB replica set.

Contract v6 §4.3 makes replica-set transaction semantics mandatory for the
idempotency claim + versioned domain write + canonical AuditEvent boundary, so
this suite does not run on ``mongomock``: without a disposable local replica set
every test is SKIPPED with the reason, and a skip is never a PASS.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27077/?replicaSet=rs0' \\
        pytest tests/test_live_ops_b_request_commands.py -v --noconftest

Authentication is real (JWT from ``/api/auth/login``; the tenant is whatever
``get_current_user`` loads server-side). Authorization is the real Permission
Service over ``tenant_role_assignments`` in a disposable system database. Two
tenants share one operational database with colliding ids stored in BOTH
orders, so a bare-id lookup would be caught.
"""
import asyncio
import os
import uuid

import pytest

PASSWORD = "LiveOpsB-2026!"
BEG, TCB = "BEG", "TCB"
MARK = {BEG: "BEGMARK-", TCB: "TCBMARK-"}
REAL_URL = os.environ.get("W0_03_REAL_MONGO_URL", "")

#: Collections a request command must NEVER change (TASK 5B no-write proof),
#: plus identity/master collections it reads.
FORBIDDEN_WRITE = (
    "warehouse_transactions", "warehouse_batches", "material_consumption_log",
    "project_material_ops", "material_entries", "asset_units", "asset_items", "asset_custody",
    "asset_repairs", "asset_movements", "md_item", "md_pending_mapping", "md_pending_slots",
    "warehouses", "projects", "supplier_invoices", "audit_logs", "users", "subscriptions",
)
#: The only collections a request command may write.
ALLOWED_WRITE = {"material_requests", "audit_events", "audit_idempotency"}



def _refusal():
    if not REAL_URL:
        return "W0_03_REAL_MONGO_URL is not set — no disposable local MongoDB replica set given"
    try:
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        from app.master_data import index_bootstrap as ib
        scheme, hosts = parse_mongo_url(REAL_URL)
        ib.check_local(hosts=hosts, scheme=scheme)
    except Exception as exc:                                  # noqa: BLE001
        return "W0_03_REAL_MONGO_URL refused: %s" % exc
    try:
        from pymongo import MongoClient
        c = MongoClient(REAL_URL, serverSelectionTimeoutMS=3000)
        hello = c.admin.command("hello")
        c.close()
        if not hello.get("setName"):
            return "the MongoDB at W0_03_REAL_MONGO_URL is not a replica set (no transactions)"
    except Exception as exc:                                  # noqa: BLE001
        return "MongoDB not reachable: %s" % type(exc).__name__
    return ""


pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


# ═══════════════════════════════════════════════════════════════ fixtures
def _ra(rid, user_id, tenant, *, role_id=None, scope_type="project", scope_id="P1",
        permissions=(), status="active"):
    return {"id": rid, "user_id": user_id, "tenant_id": tenant, "role_id": role_id or "worker",
            "scope_type": scope_type, "scope_id": scope_id, "module": None,
            "permissions": list(permissions), "status": status, "revision": 3,
            "valid_from": None, "valid_to": None}


REQ_CREATE_SUBMIT = ["material_request.create", "material_request.submit"]
APPROVER = ["material_request.approve", "material_request.cancel_approved",
            "material_request.cancel"]


async def _seed(op, sysdb):
    from app.deps.auth import hash_password
    pw = hash_password(PASSWORD)
    for org in (BEG, TCB):
        await op.organizations.insert_one({"id": org, "name": org, "slug": org.lower()})
        await sysdb.tenant_registry.insert_one({"id": org, "database_name": op.name,
                                                "status": "active"})
        await op.subscriptions.insert_one({"org_id": org, "plan_id": "pro", "status": "active"})

    def projects(org):
        m = MARK[org]
        return [{"id": "P1", "org_id": org, "code": m + "P1", "name": m + "PROJECT1", "status": "Active"},
                {"id": "P2", "org_id": org, "code": m + "P2", "name": m + "PROJECT2", "status": "Active"},
                {"id": "PC", "org_id": org, "code": m + "PC", "name": m + "CLOSED", "status": "Completed"}]

    def warehouses(org):
        return [{"id": "W1", "org_id": org, "code": MARK[org] + "W", "name": MARK[org] + "WAREHOUSE",
                 "type": "central", "active": True}]

    def items(org):
        m = MARK[org]
        return [{"id": "IT-1", "tenant_id": org, "entity_type": "item", "display_name": m + "ITEM",
                 "status": "active"},
                {"id": "IT-ARCH", "tenant_id": org, "entity_type": "item", "display_name": m + "OLD",
                 "status": "archived"}]

    # colliding ids, BEG stored first for P1/W1/IT-1, TCB first for P2
    for org in (BEG, TCB):
        await op.projects.insert_one(projects(org)[0])
        await op.warehouses.insert_many(warehouses(org))
        await op.md_item.insert_many(items(org))
    for org in (TCB, BEG):
        await op.projects.insert_many(projects(org)[1:])
    await op.md_item.insert_one({"id": "IT-TCBONLY", "tenant_id": TCB, "entity_type": "item",
                                 "display_name": "TCBMARK-ONLY", "status": "active"})

    # rows in every collection that must stay untouched
    for org in (BEG, TCB):
        m = MARK[org]
        await op.warehouse_transactions.insert_one({
            "id": "WT-" + org, "org_id": org, "type": "intake", "warehouse_id": "W1",
            "lines": [{"material_name": m + "CEMENT", "qty_received": 10.0, "unit": "бр"}]})
        await op.warehouse_batches.insert_one({"id": "B-" + org, "org_id": org, "qty": 10.0})
        await op.material_consumption_log.insert_one({"id": "MC-" + org, "org_id": org, "qty": 1.0})
        await op.project_material_ops.insert_one({"id": "PM-" + org, "org_id": org, "qty": 2.0})
        await op.material_entries.insert_one({"id": "ME-" + org, "org_id": org, "qty": 3.0})
        await op.asset_items.insert_one({"id": "AI-" + org, "org_id": org, "name": m + "ASSET"})
        await op.asset_units.insert_one({"id": "AU-" + org, "org_id": org, "status": "in_stock"})
        await op.asset_custody.insert_one({"id": "AC-" + org, "org_id": org, "status": "active"})
        await op.asset_repairs.insert_one({"id": "AR-" + org, "org_id": org, "status": "open"})
        await op.asset_movements.insert_one({"id": "AM-" + org, "org_id": org})
        await op.audit_logs.insert_one({"id": "AL-" + org, "org_id": org, "action": "seed"})

    users = []
    ras = []
    for org in (BEG, TCB):
        p = org.lower()
        for name, role in (("owner", "Owner"), ("tech", "Technician"), ("sm", "SiteManager"),
                           ("outsider", "Technician"), ("revoked", "SiteManager"),
                           ("nobody", "Owner"), ("tech2", "Technician"), ("member", "Technician")):
            users.append({"id": "%s-%s" % (p, name), "org_id": org, "email": "%s@%s.test" % (name, p),
                          "password_hash": pw, "role": role, "first_name": MARK[org] + name,
                          "last_name": "B", "is_active": True})
        ras += [
            _ra(p + "-ra-owner", p + "-owner", org, role_id="owner", scope_type="company", scope_id=None),
            _ra(p + "-ra-tech", p + "-tech", org, permissions=REQ_CREATE_SUBMIT),
            _ra(p + "-ra-tech2", p + "-tech2", org, permissions=REQ_CREATE_SUBMIT),
            _ra(p + "-ra-sm", p + "-sm", org, permissions=APPROVER),
            _ra(p + "-ra-out", p + "-outsider", org, scope_id="P2",
                permissions=REQ_CREATE_SUBMIT + APPROVER),
            _ra(p + "-ra-rev", p + "-revoked", org, permissions=APPROVER, status="revoked"),
            # "nobody" carries the legacy JWT role Owner and NO assignment at all.
        ]
        # "member": legacy project_team membership on P2 and NO RoleAssignment.
        await op.project_team.insert_one({
            "id": p + "-pt-member", "org_id": org, "project_id": "P2", "user_id": p + "-member",
            "role_in_project": "Technician", "active": True, "from_date": None, "to_date": None})
    await op.users.insert_many(users)
    await sysdb.tenant_role_assignments.insert_many(ras)
    # the pilot prerequisite indexes, provisioned the way staging/pilot does it
    from scripts.live_ops_b_bootstrap import apply as bootstrap_apply
    out = await bootstrap_apply(op)
    assert out["status"] == "OK", out


def _app(monkeypatch, op, sysdb):
    from fastapi import FastAPI, APIRouter

    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.deps import modules as deps_modules
    from app.tenancy import registry, guard
    from app.master_data.deps import ENV_MODE
    import server  # noqa: F401
    from app.routes import auth, material_request_commands, procurement, technician
    from app.utils import audit as utils_audit
    from app.services import project_guards

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "enforce")
    for module in (appdb, deps_auth, deps_modules, utils_audit, project_guards, auth,
                   material_request_commands, procurement, technician):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for name in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, name, sysdb[name])

    async def _tenant_db(tenant_id, require_operational=False):
        from app.tenancy.resolver import TenantNotFound
        if not await sysdb.tenant_registry.find_one({"id": tenant_id}):
            raise TenantNotFound(tenant_id)
        return op
    monkeypatch.setattr(guard, "get_tenant_db", _tenant_db)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(material_request_commands.router)
    api.include_router(procurement.router)
    api.include_router(technician.router)
    app.include_router(api)
    return app


class Caller:
    def __init__(self, client, token, tenant, user_id):
        self.c, self.tenant, self.user_id = client, tenant, user_id
        self.h = {"Authorization": "Bearer " + token}

    async def get(self, path):
        return await self.c.get(path, headers=self.h)

    async def send(self, method, path, body=None, *, key="auto", corr=None, channel="desktop"):
        h = dict(self.h)
        if key == "auto":
            key = "k-" + uuid.uuid4().hex
        if key:
            h["Idempotency-Key"] = key
        if corr:
            h["X-Correlation-Id"] = corr
        h["X-Client-Channel"] = channel
        return await self.c.request(method, path, json=body if body is not None else {}, headers=h)


class H:
    """The running scenario: databases, callers and assertion helpers."""

    def __init__(self, op, sysdb, callers):
        self.op, self.sysdb, self.u = op, sysdb, callers

    async def create(self, caller, *, project="P1", lines=None, **header):
        body = {"project_id": project, "needed_date": "2026-11-01", "destination_type": "project",
                "lines": lines if lines is not None else
                [{"item_id": "IT-1", "qty_requested": 10, "unit": "бр"}], **header}
        r = await caller.send("POST", "/api/material-requests", body)
        assert r.status_code == 201, (r.status_code, r.text[:400])
        return r.json()["request"]

    async def submitted(self, caller=None, **kw):
        caller = caller or self.u[BEG]["tech"]
        req = await self.create(caller, **kw)
        r = await caller.send("POST", "/api/material-requests/%s/submit" % req["id"])
        assert r.status_code == 200, r.text[:400]
        return r.json()["request"]

    async def approved(self, **kw):
        req = await self.submitted(**kw)
        r = await self.u[BEG]["sm"].send("POST", "/api/material-requests/%s/approve" % req["id"])
        assert r.status_code == 200, r.text[:400]
        return r.json()["request"]

    async def doc(self, req_id, org=BEG):
        return await self.op.material_requests.find_one({"id": req_id, "org_id": org}, {"_id": 0})

    async def events(self, tenant=BEG, **flt):
        return await self.op.audit_events.find({"tenant_id": tenant, **flt}, {"_id": 0}) \
            .sort("sequence", 1).to_list(10000)

    async def snapshot(self, names=None):
        import bson
        out = {}
        names = names or sorted(await self.op.list_collection_names())
        for name in names:
            docs = await self.op[name].find({}).sort("_id", 1).to_list(100000)
            out[name] = b"".join(bson.BSON.encode(d) for d in docs)
        return out

    async def chain_ok(self, tenant=BEG):
        from app.audit.store import verify_chain
        evs = await self.events(tenant)
        ok, why = verify_chain(evs)
        assert ok, why
        return evs


def run(scenario):
    """Fresh disposable databases on the real replica set; dropped afterwards."""
    async def body(monkeypatch):
        import httpx
        from motor.motor_asyncio import AsyncIOMotorClient
        tag = uuid.uuid4().hex[:10]
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        op, sysdb = client["liveopsb_op_" + tag], client["liveopsb_sys_" + tag]
        try:
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://b") as c:
                callers = {}
                for org in (BEG, TCB):
                    callers[org] = {}
                    for name in ("owner", "tech", "sm", "outsider", "revoked", "nobody", "tech2",
                                 "member"):
                        r = await c.post("/api/auth/login", json={
                            "email": "%s@%s.test" % (name, org.lower()), "password": PASSWORD})
                        assert r.status_code == 200, (name, r.text[:200])
                        callers[org][name] = Caller(c, r.json()["token"], org,
                                                    "%s-%s" % (org.lower(), name))
                return await scenario(H(op, sysdb, callers))
        finally:
            await client.drop_database(op.name)
            await client.drop_database(sysdb.name)
            client.close()

    def test(monkeypatch):
        return asyncio.run(body(monkeypatch))
    return test


def _code(r):
    try:
        d = r.json().get("detail")
    except Exception:                                         # noqa: BLE001
        return None
    return d.get("error_code") if isinstance(d, dict) else d


# ═══════════════════════════════════════════════════════ 1. valid transitions
def test_valid_transitions_draft_edit_submit_approve_and_reject(monkeypatch):
    async def s(h):
        tech, sm = h.u[BEG]["tech"], h.u[BEG]["sm"]
        req = await h.create(tech, lines=[{"item_id": "IT-1", "qty_requested": 10, "unit": "бр"},
                                          {"material_name": "Лепило X", "qty_requested": 4, "unit": "торба"}])
        assert req["request_state"] == "draft" and req["version"] == 1
        line_ids = [l["id"] for l in req["lines"]]
        assert req["lines"][1]["mapping_status"] == "pending_mapping"

        # draft edit: requester basis; line ids stay stable; free text now mapped
        r = await tech.send("PATCH", "/api/material-requests/%s/draft" % req["id"], {
            "expected_version": 1, "priority": "high", "notes": "спешно",
            "lines": [{"id": line_ids[0], "item_id": "IT-1", "qty_requested": 12, "unit": "бр"},
                      {"id": line_ids[1], "item_id": "IT-1", "material_name": "Лепило X",
                       "qty_requested": 4, "unit": "торба"}]})
        assert r.status_code == 200, r.text
        d = r.json()["request"]
        assert [l["id"] for l in d["lines"]] == line_ids
        assert d["version"] == 2 and d["priority"] == "high"
        assert all(l["mapping_status"] == "confirmed" for l in d["lines"])

        r = await tech.send("POST", "/api/material-requests/%s/submit" % req["id"])
        assert r.status_code == 200 and r.json()["request"]["request_state"] == "submitted"

        r = await sm.send("POST", "/api/material-requests/%s/approve" % req["id"], {
            "lines": [{"line_id": line_ids[0], "qty_approved": 8}], "note": "частично"})
        assert r.status_code == 200, r.text
        d = r.json()["request"]
        assert d["request_state"] == "approved" and d["approved_by"] == "beg-sm"
        l0 = d["lines"][0]
        assert l0["qty_requested"] == 12 and l0["qty_approved"] == 8 and l0["remaining_qty"] == 8

        # reject path on another request
        req2 = await h.submitted()
        r = await sm.send("POST", "/api/material-requests/%s/reject" % req2["id"],
                          {"reason": "няма бюджет"})
        assert r.status_code == 200 and r.json()["request"]["request_state"] == "rejected"
        assert r.json()["request"]["rejection_reason"] == "няма бюджет"

        # cancel paths: draft (requester basis) and submitted
        req3 = await h.create(tech)
        r = await tech.send("POST", "/api/material-requests/%s/cancel" % req3["id"], {"reason": "грешка"})
        assert r.status_code == 200 and r.json()["request"]["request_state"] == "cancelled"
        await h.chain_ok()
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 2. invalid transitions
def test_invalid_transitions_fail_closed_without_partial_writes(monkeypatch):
    async def s(h):
        tech, sm = h.u[BEG]["tech"], h.u[BEG]["sm"]
        draft = await h.create(tech)
        before = await h.doc(draft["id"])
        for method, path, body, who in (
                ("POST", "approve", {}, sm), ("POST", "reject", {"reason": "x"}, sm)):
            r = await who.send(method, "/api/material-requests/%s/%s" % (draft["id"], path), body)
            assert r.status_code == 409 and _code(r) == "INVALID_TRANSITION", (path, r.text)
        assert await h.doc(draft["id"]) == before

        sub = await h.submitted()
        before = await h.doc(sub["id"])
        for path, body, who in (("submit", {}, tech), ("draft", {"notes": "x"}, tech)):
            m = "PATCH" if path == "draft" else "POST"
            r = await who.send(m, "/api/material-requests/%s/%s" % (sub["id"], path), body)
            assert r.status_code in (403, 409), (path, r.status_code, r.text)
        assert await h.doc(sub["id"]) == before

        appr = await h.approved()
        for path, body in (("approve", {}), ("reject", {"reason": "x"}), ("submit", {})):
            r = await h.u[BEG]["owner"].send("POST", "/api/material-requests/%s/%s" % (appr["id"], path), body)
            assert r.status_code == 409 and _code(r) == "INVALID_TRANSITION", (path, r.text)

        # no reopen of a terminal state
        r = await sm.send("POST", "/api/material-requests/%s/reject" % sub["id"], {"reason": "no"})
        assert r.status_code == 200
        for path in ("submit", "approve"):
            r = await h.u[BEG]["owner"].send("POST", "/api/material-requests/%s/%s" % (sub["id"], path))
            assert r.status_code == 409 and _code(r) == "INVALID_TRANSITION"

        # a legacy stored status (invoice-driven "fulfilled") is not a control state
        await h.op.material_requests.insert_one({
            "id": "MR-LEGACY", "org_id": BEG, "project_id": "P1", "status": "fulfilled",
            "lines": [{"id": "L-LEG", "material_name": "x", "qty_requested": 1, "unit": "бр"}]})
        for path, body in (("cancel", {"reason": "x"}), ("approve", {}), ("submit", {})):
            r = await h.u[BEG]["owner"].send("POST", "/api/material-requests/MR-LEGACY/%s" % path, body)
            assert r.status_code == 409 and _code(r) == "INVALID_TRANSITION"
        r = await h.u[BEG]["owner"].get("/api/material-requests/MR-LEGACY")
        assert r.json()["request_state"] is None and r.json()["legacy_status"] == "fulfilled"

        # every validation stop is a canonical failure event
        stops = await h.events(action="material_request.approve", result="failure")
        assert stops and all(e["error_code"] for e in stops)
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 3. raw-status bypass
def test_raw_status_and_legacy_writers_are_blocked(monkeypatch):
    async def s(h):
        owner, tech = h.u[BEG]["owner"], h.u[BEG]["tech"]
        req = await h.create(tech)
        snap = await h.snapshot()
        for method, path, body in (
                ("PUT", "/api/material-requests/%s" % req["id"], {"status": "approved"}),
                ("DELETE", "/api/material-requests/%s" % req["id"], None),
                ("POST", "/api/material-requests/from-offer/O-1", {}),
                ("POST", "/api/technician/material-request",
                 {"project_id": "P1", "items": [{"item_name": "x", "qty": 1, "unit": "бр"}],
                  "urgent": True})):
            r = await owner.send(method, path, body)
            assert r.status_code == 410, (path, r.status_code, r.text[:200])
            assert _code(r) == "LEGACY_WRITER_RETIRED"
        assert await h.snapshot() == snap

        # raw state / actor / approval / fulfilment / derived fields are refused
        for field, value in (("status", "approved"), ("approved_by", "x"), ("version", 9),
                             ("org_id", TCB), ("requested_by", "tcb-owner")):
            r = await tech.send("PATCH", "/api/material-requests/%s/draft" % req["id"], {field: value})
            assert r.status_code == 422 and _code(r) == "FIELD_NOT_ALLOWED", (field, r.text)
        for field in ("qty_fulfilled", "qty_approved", "remaining_qty", "qty_cancelled", "facts"):
            r = await tech.send("PATCH", "/api/material-requests/%s/draft" % req["id"], {
                "lines": [{"item_id": "IT-1", "qty_requested": 1, "unit": "бр", field: 5}]})
            assert r.status_code == 422 and _code(r) == "FIELD_NOT_ALLOWED", (field, r.text)
        r = await owner.send("POST", "/api/material-requests", {
            "project_id": "P1", "status": "approved", "lines": []})
        assert r.status_code == 422
        assert await h.snapshot(["material_requests"]) == {"material_requests": snap["material_requests"]}
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 4. not enforce ⇒ no write
@pytest.mark.parametrize("mode", ["off", "shadow", "enforcing", "", None])
def test_permission_service_not_enforce_denies_every_write(monkeypatch, mode):
    async def s(h):
        owner = h.u[BEG]["owner"]
        req = await h.submitted()
        if mode is None:
            monkeypatch.delenv("PERMISSION_SERVICE_MODE", raising=False)
        else:
            monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
        snap = await h.snapshot(["material_requests", "audit_idempotency"])
        n_events = len(await h.events())
        for method, path, body in (
                ("POST", "/api/material-requests", {"project_id": "P1", "lines": []}),
                ("PATCH", "/api/material-requests/%s/draft" % req["id"], {"notes": "x"}),
                ("POST", "/api/material-requests/%s/submit" % req["id"], {}),
                ("POST", "/api/material-requests/%s/approve" % req["id"], {}),
                ("POST", "/api/material-requests/%s/reject" % req["id"], {"reason": "x"}),
                ("POST", "/api/material-requests/%s/cancel" % req["id"], {"reason": "x"})):
            r = await owner.send(method, path, body)
            assert r.status_code == 503 and _code(r) == "PERMISSION_SERVICE_NOT_ENFORCED", (path, r.text)
        assert await h.snapshot(["material_requests", "audit_idempotency"]) == snap
        refused = await h.events(action="material_request.write_refused")
        assert len(refused) == 6 and len(await h.events()) == n_events + 6
        assert all(e["result"] == "denied" for e in refused)
        r = await owner.get("/api/material-requests/write-status")
        assert r.json()["writes_enabled"] is False
    run(s)(monkeypatch)


def test_unavailable_tenant_or_permission_resolution_fails_closed(monkeypatch):
    async def s(h):
        from app.tenancy import guard
        from app.permissions import service
        owner = h.u[BEG]["owner"]
        req = await h.submitted()
        snap = await h.snapshot(["material_requests"])

        async def broken_assignments(*a, **k):
            raise RuntimeError("registry down")
        monkeypatch.setattr(service, "_load_assignments", broken_assignments)
        r = await owner.send("POST", "/api/material-requests/%s/approve" % req["id"])
        assert r.status_code == 503 and _code(r) == "PERMISSION_EVALUATION_UNAVAILABLE", r.text

        async def broken_db(tenant_id, require_operational=False):
            raise ConnectionError("tenant db down")
        monkeypatch.setattr(guard, "get_tenant_db", broken_db)
        r = await owner.send("POST", "/api/material-requests/%s/approve" % req["id"])
        assert r.status_code == 503 and _code(r) == "TENANT_RESOLUTION_UNAVAILABLE", r.text
        assert await h.snapshot(["material_requests"]) == snap
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 5./7. project/action denial
def test_project_action_denials_and_direct_url_calls(monkeypatch):
    async def s(h):
        u = h.u[BEG]
        req = await h.submitted()
        snap = await h.snapshot(["material_requests", "audit_idempotency"])
        cases = (
            (u["tech"], "approve", {}, "ACTION_NOT_ALLOWED"),          # requester cannot approve
            (u["outsider"], "approve", {}, "SCOPE_MISMATCH"),          # approver on ANOTHER project
            (u["revoked"], "approve", {}, "ASSIGNMENT_REVOKED"),
            (u["nobody"], "approve", {}, "NO_ASSIGNMENT"),             # JWT role Owner, no assignment
            (u["nobody"], "reject", {"reason": "x"}, "NO_ASSIGNMENT"),
            (u["tech2"], "cancel", {"reason": "x"}, "ACTION_NOT_ALLOWED"),  # not the requester
            (u["outsider"], "submit", {}, "SCOPE_MISMATCH"),
        )
        for caller, path, body, reason in cases:
            r = await caller.send("POST", "/api/material-requests/%s/%s" % (req["id"], path), body)
            assert r.status_code == 403, (caller.user_id, path, r.status_code, r.text)
            assert r.json()["detail"]["reason"] == reason, (caller.user_id, path, r.text)
        # create in a project outside the assignment scope
        r = await u["tech"].send("POST", "/api/material-requests", {"project_id": "P2", "lines": []})
        assert r.status_code == 403 and r.json()["detail"]["reason"] == "SCOPE_MISMATCH"
        assert await h.snapshot(["material_requests", "audit_idempotency"]) == snap

        denied = await h.events(result="denied")
        assert len(denied) == len(cases) + 1
        for e in denied:
            assert e["actor_id"] and e["error_code"] and e["entity_type"] == "material_request"
            assert e["correlation_id"] and e["idempotency_key"]
        # draft edit by another project member who is not the requester is denied
        d = await h.create(u["tech"])
        r = await u["tech2"].send("PATCH", "/api/material-requests/%s/draft" % d["id"], {"notes": "x"})
        assert r.status_code == 403 and r.json()["detail"]["reason"] == "ACTION_NOT_ALLOWED"
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 6. tenant A/B
def test_two_tenants_colliding_ids_both_orders_no_cross_read_or_write(monkeypatch):
    async def s(h):
        a, b = h.u[BEG], h.u[TCB]
        # P1 (BEG stored first) and P2 (TCB stored first) — each tenant writes its OWN
        ra = await h.create(a["owner"], project="P1")
        rb = await h.create(b["owner"], project="P2", lines=[
            {"item_id": "IT-1", "qty_requested": 3, "unit": "бр"}])
        assert (await h.doc(ra["id"], BEG))["project_id"] == "P1"
        assert (await h.doc(rb["id"], TCB))["project_id"] == "P2"
        assert rb["lines"][0]["material_name"] == "TCBMARK-ITEM"        # own colliding item
        assert ra["lines"][0]["material_name"] == "BEGMARK-ITEM"

        # an item id that exists only in the other tenant is not trusted
        r = await a["owner"].send("POST", "/api/material-requests", {
            "project_id": "P1", "lines": [{"item_id": "IT-TCBONLY", "qty_requested": 1, "unit": "бр"}]})
        assert r.status_code == 422 and _code(r) == "ITEM_NOT_FOUND"

        # commands on the other tenant's request id: 404, the owner's doc byte-equal
        for caller, victim, owner_org in ((a["owner"], rb["id"], TCB), (b["owner"], ra["id"], BEG)):
            snap = await h.snapshot(["material_requests"])
            for m, path, body in (("PATCH", "draft", {"notes": "X"}), ("POST", "submit", {}),
                                  ("POST", "approve", {}), ("POST", "reject", {"reason": "x"}),
                                  ("POST", "cancel", {"reason": "x"})):
                r = await caller.send(m, "/api/material-requests/%s/%s" % (victim, path), body)
                assert r.status_code == 404, (caller.tenant, path, r.status_code, r.text)
            r = await caller.get("/api/material-requests/%s" % victim)
            assert r.status_code == 404
            r = await caller.get("/api/material-requests/%s/view" % victim)
            assert r.status_code == 404
            assert await h.snapshot(["material_requests"]) == snap

        # lists and views never echo the other tenant
        for caller, foreign in ((a["owner"], "TCBMARK"), (b["owner"], "BEGMARK")):
            r = await caller.get("/api/material-requests")
            assert r.status_code == 200 and foreign not in r.text
            assert all(x["org_id"] == caller.tenant for x in r.json())
        r = await a["owner"].get("/api/material-requests/%s/view" % ra["id"])
        assert r.status_code == 200 and "TCBMARK" not in r.text
        assert r.json()["history"]["status"] == "ok"
        assert all(e.get("event_id") for e in r.json()["history"]["events"])

        # the Master item picker returns only the session tenant's ACTIVE items
        r = await a["owner"].get("/api/material-requests/item-options?q=item")
        assert r.status_code == 200 and [i["id"] for i in r.json()["items"]] == ["IT-1"]
        assert "TCBMARK" not in r.text
        r = await b["owner"].get("/api/material-requests/item-options")
        assert sorted(i["id"] for i in r.json()["items"]) == ["IT-1", "IT-TCBONLY"]
        assert "BEGMARK" not in r.text

        # each chain holds only its own tenant's events, and both chains verify
        for org in (BEG, TCB):
            evs = await h.chain_ok(org)
            assert evs and all(e["tenant_id"] == org for e in evs)
        assert not await h.events(BEG, entity_id=rb["id"], result="success")
        assert not await h.events(TCB, entity_id=ra["id"], result="success")
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 8./9. canonical AuditEvent
def test_each_consequential_action_appends_one_complete_canonical_event(monkeypatch):
    async def s(h):
        tech, sm = h.u[BEG]["tech"], h.u[BEG]["sm"]
        logs_before = await h.op.audit_logs.count_documents({})
        r = await tech.send("POST", "/api/material-requests", {
            "project_id": "P1", "needed_date": "2026-11-01", "destination_type": "warehouse",
            "destination_id": "W1", "lines": [{"item_id": "IT-1", "qty_requested": 5, "unit": "бр"}]},
            key="key-create-0001", corr="corr-flow-0001", channel="phone")
        rid = r.json()["request"]["id"]
        steps = [(tech, "PATCH", "draft", {"notes": "n"}, "key-edit-0001"),
                 (tech, "POST", "submit", {}, "key-submit-0001"),
                 (sm, "POST", "approve", {}, "key-approve-0001"),
                 (sm, "POST", "cancel", {"reason": "обектът спря"}, "key-cancel-0001")]
        for caller, m, path, body, key in steps:
            r = await caller.send(m, "/api/material-requests/%s/%s" % (rid, path), body,
                                  key=key, corr="corr-flow-0001")
            assert r.status_code == 200, (path, r.text)

        evs = await h.events(entity_id=rid, result="success")
        assert [e["action"] for e in evs] == [
            "material_request.create", "material_request.edit_draft", "material_request.submit",
            "material_request.approve", "material_request.cancel"]
        for i, (e, key) in enumerate(zip(evs, ["key-create-0001", "key-edit-0001", "key-submit-0001",
                                               "key-approve-0001", "key-cancel-0001"])):
            assert e["tenant_id"] == BEG and e["actor_type"] == "human"
            assert e["source_flow"] == "FLOW-020" and e["entity_type"] == "material_request"
            assert e["scope_type"] == "project" and e["scope_id"] == "P1"
            assert e["correlation_id"] == "corr-flow-0001" and e["idempotency_key"] == key
            basis = e["structured_diff"]["permission_basis"]
            if i == 1:
                # beg-tech holds no edit_draft: the frozen requester alternative
                # allowed it, and the event says so instead of borrowing a role
                assert basis["basis"] == "requester" and basis["action"] == "material_request.edit_draft"
                assert basis["decision"] == "ACTION_NOT_ALLOWED"
                assert e["effective_role_assignments"] == []
            else:
                assert basis["basis"] == "permission" and basis["decision"] == "ALLOWED"
                assert e["effective_role_assignments"], e["action"]
                assert basis["role_assignment_revisions"]
            assert e["retention_class"] == "R2" and e["integrity_hash"] and e["sequence"]
            assert e["entity_version"]
        assert evs[0]["source_channel"] == "phone"
        assert evs[0]["actor_id"] == "beg-tech" and evs[3]["actor_id"] == "beg-sm"
        assert evs[3]["effective_role_assignments"] == ["beg-ra-sm"]
        sub = evs[2]["structured_diff"]
        assert sub["from_state"] == "draft" and sub["to_state"] == "submitted"
        assert sub["before"]["status"] == "draft" and sub["after"]["status"] == "submitted"
        assert evs[4]["structured_diff"]["reason"] == "обектът спря"
        assert evs[4]["reason"] == "обектът спря"
        await h.chain_ok()
        # legacy audit_logs is not the evidence path for these writes
        assert await h.op.audit_logs.count_documents({}) == logs_before
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 10./11. idempotency
def test_idempotent_retry_is_one_effect_and_different_payload_conflicts(monkeypatch):
    async def s(h):
        tech, sm = h.u[BEG]["tech"], h.u[BEG]["sm"]
        body = {"project_id": "P1", "needed_date": "2026-11-01", "destination_type": "project",
                "lines": [{"item_id": "IT-1", "qty_requested": 2, "unit": "бр"}]}
        r1 = await tech.send("POST", "/api/material-requests", body, key="same-key-create")
        r2 = await tech.send("POST", "/api/material-requests", body, key="same-key-create")
        assert r1.status_code == 201 and r2.status_code == 201
        assert r2.json()["replayed"] is True and r1.json()["replayed"] is False
        assert r1.json()["result"] == r2.json()["result"]
        assert await h.op.material_requests.count_documents({"org_id": BEG}) == 1
        rid = r1.json()["request"]["id"]

        r = await tech.send("POST", "/api/material-requests", {**body, "notes": "other"},
                            key="same-key-create")
        assert r.status_code == 409 and _code(r) == "IDEMPOTENCY_CONFLICT"
        assert await h.op.material_requests.count_documents({"org_id": BEG}) == 1

        for _ in range(3):
            r = await tech.send("POST", "/api/material-requests/%s/submit" % rid, key="submit-key-1")
            assert r.status_code == 200, r.text
        r = await sm.send("POST", "/api/material-requests/%s/approve" % rid, key="approve-key-1")
        v = r.json()["request"]["version"]
        for _ in range(2):
            r = await sm.send("POST", "/api/material-requests/%s/approve" % rid, key="approve-key-1")
            assert r.status_code == 200 and r.json()["replayed"] is True
        assert (await h.doc(rid))["version"] == v
        assert len(await h.events(entity_id=rid, action="material_request.submit", result="success")) == 1
        assert len(await h.events(entity_id=rid, action="material_request.approve", result="success")) == 1
        replays = await h.events(entity_id=rid, action="material_request.replay")
        # 1 create retry + 2 submit retries + 2 approve retries; each is a replay
        # event, never a second transition
        assert sorted(e["idempotency_key"] for e in replays) == sorted(
            ["same-key-create", "submit-key-1", "submit-key-1", "approve-key-1", "approve-key-1"])

        # same key for a different request is a conflict, not a replay
        other = await h.create(tech)
        r = await tech.send("POST", "/api/material-requests/%s/submit" % other["id"], key="submit-key-1")
        assert r.status_code == 409 and _code(r) == "IDEMPOTENCY_CONFLICT"
        # missing key is refused before anything happens
        r = await tech.send("POST", "/api/material-requests/%s/submit" % other["id"], key=None)
        assert r.status_code == 428 and _code(r) == "IDEMPOTENCY_KEY_REQUIRED"
        assert (await h.doc(other["id"]))["status"] == "draft"
        await h.chain_ok()
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 12. concurrency
def test_concurrent_actions_on_one_request_have_exactly_one_winner(monkeypatch):
    async def s(h):
        sm, owner = h.u[BEG]["sm"], h.u[BEG]["owner"]
        req = await h.submitted()
        calls = [sm.send("POST", "/api/material-requests/%s/approve" % req["id"]) for _ in range(4)]
        calls += [owner.send("POST", "/api/material-requests/%s/reject" % req["id"], {"reason": "r"})
                  for _ in range(4)]
        rs = await asyncio.gather(*calls)
        ok = [r for r in rs if r.status_code == 200]
        assert len(ok) == 1, [(r.status_code, r.text[:120]) for r in rs]
        assert all(r.status_code == 409 for r in rs if r.status_code != 200)
        doc = await h.doc(req["id"])
        assert doc["status"] in ("approved", "rejected") and doc["version"] == 3
        wins = await h.events(entity_id=req["id"], result="success",
                              action={"$in": ["material_request.approve", "material_request.reject"]})
        assert len(wins) == 1

        # same key fired concurrently: one effect, the rest replay or wait-conflict
        req2 = await h.create(h.u[BEG]["tech"])
        rs = await asyncio.gather(*[h.u[BEG]["tech"].send(
            "POST", "/api/material-requests/%s/submit" % req2["id"], key="race-key-00001")
            for _ in range(6)])
        assert all(r.status_code in (200, 409) for r in rs), [r.text[:120] for r in rs]
        assert len(await h.events(entity_id=req2["id"], action="material_request.submit",
                                  result="success")) == 1
        assert (await h.doc(req2["id"]))["version"] == 2

        # many creates in one tenant: no lost, duplicate or unchained event
        n = len(await h.events())
        rs = await asyncio.gather(*[h.create(h.u[BEG]["tech"]) for _ in range(8)])
        assert len({r["id"] for r in rs}) == 8
        evs = await h.chain_ok()
        assert len(evs) == n + 8
        assert [e["sequence"] for e in evs] == list(range(1, len(evs) + 1))
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 13./14. quantities
def test_partial_facts_stay_on_the_same_line_and_cancel_only_the_remainder(monkeypatch):
    async def s(h):
        sm, tech = h.u[BEG]["sm"], h.u[BEG]["tech"]
        req = await h.approved(lines=[{"item_id": "IT-1", "qty_requested": 10, "unit": "бр"},
                                      {"item_id": "IT-1", "qty_requested": 6, "unit": "бр"}])
        l0, l1 = req["lines"][0]["id"], req["lines"][1]["id"]
        # a canonical acceptance fact (written by the FUTURE warehouse writer) on line 0
        await h.op.warehouse_transactions.insert_one({
            "id": "WT-RCV-1", "org_id": BEG, "movement_type": "receive", "status": "posted",
            "item_id": "IT-1", "qty": 3.0, "request_line_id": l0})
        await h.op.warehouse_transactions.insert_one({     # other tenant, same line id: ignored
            "id": "WT-RCV-X", "org_id": TCB, "movement_type": "receive", "status": "posted",
            "item_id": "IT-1", "qty": 5.0, "request_line_id": l0})
        r = await h.u[BEG]["owner"].get("/api/material-requests/%s" % req["id"])
        d = r.json()
        line = d["lines"][0]
        assert line["id"] == l0 and line["qty_requested"] == 10 and line["qty_approved"] == 10
        assert line["facts"]["accepted_qty"] == 3 and line["remaining_qty"] == 7
        assert d["has_partial_facts"] is True and d["fulfilled_derived"] is False

        # partial cancel of 2 on line 0 keeps the request approved
        r = await sm.send("POST", "/api/material-requests/%s/cancel" % req["id"], {
            "reason": "по-малко", "lines": [{"line_id": l0, "qty": 2}]})
        assert r.status_code == 200, r.text
        d = r.json()["request"]
        assert d["request_state"] == "approved"
        assert d["lines"][0]["qty_cancelled"] == 2 and d["lines"][0]["remaining_qty"] == 5
        # cannot cancel more than the remainder, or executed quantity
        r = await sm.send("POST", "/api/material-requests/%s/cancel" % req["id"], {
            "reason": "x", "lines": [{"line_id": l0, "qty": 6}]})
        assert r.status_code == 422 and _code(r) == "INVALID_QUANTITY"

        # full cancel: only the remainder, executed facts preserved
        r = await sm.send("POST", "/api/material-requests/%s/cancel" % req["id"], {"reason": "край"})
        assert r.status_code == 200, r.text
        d = r.json()["request"]
        assert d["request_state"] == "cancelled"
        assert d["lines"][0]["qty_cancelled"] == 7 and d["lines"][0]["facts"]["accepted_qty"] == 3
        assert d["lines"][1]["qty_cancelled"] == 6
        assert d["lines"][0]["qty_requested"] == 10                    # evidence unchanged
        ev = (await h.events(entity_id=req["id"], action="material_request.cancel",
                             result="success"))[-1]
        assert ev["structured_diff"]["cancelled_qty"] == {l0: 5.0, l1: 6.0}

        # requested quantity is immutable after submit (no draft edit path exists)
        sub = await h.submitted()
        r = await tech.send("PATCH", "/api/material-requests/%s/draft" % sub["id"], {
            "lines": [{"id": sub["lines"][0]["id"], "item_id": "IT-1", "qty_requested": 99, "unit": "бр"}]})
        assert r.status_code in (403, 409)
        assert (await h.doc(sub["id"]))["lines"][0]["qty_requested"] == 10
    run(s)(monkeypatch)


def test_cancel_with_an_active_reservation_is_refused_atomically(monkeypatch):
    async def s(h):
        sm = h.u[BEG]["sm"]
        req = await h.approved()
        lid = req["lines"][0]["id"]
        await h.op.warehouse_transactions.insert_one({
            "id": "WT-RES-1", "org_id": BEG, "movement_type": "reserve", "status": "posted",
            "item_id": "IT-1", "qty": 4.0, "request_line_id": lid})
        snap = await h.snapshot(["material_requests", "warehouse_transactions", "audit_idempotency"])
        r = await sm.send("POST", "/api/material-requests/%s/cancel" % req["id"], {"reason": "x"})
        assert r.status_code == 409 and _code(r) == "RESERVATION_RELEASE_NOT_AVAILABLE", r.text
        assert await h.snapshot(["material_requests", "warehouse_transactions",
                                 "audit_idempotency"]) == snap
        stop = (await h.events(entity_id=req["id"], action="material_request.cancel"))[-1]
        assert stop["result"] == "failure" and stop["error_code"] == "RESERVATION_RELEASE_NOT_AVAILABLE"
        # a released reservation no longer blocks
        await h.op.warehouse_transactions.insert_one({
            "id": "WT-REL-1", "org_id": BEG, "movement_type": "release_reservation",
            "status": "posted", "item_id": "IT-1", "qty": 4.0, "request_line_id": lid})
        r = await sm.send("POST", "/api/material-requests/%s/cancel" % req["id"], {"reason": "x"})
        assert r.status_code == 200 and r.json()["request"]["request_state"] == "cancelled"
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 15. unmapped material
def test_unmapped_material_stays_pending_and_never_creates_a_master_item(monkeypatch):
    async def s(h):
        tech, sm = h.u[BEG]["tech"], h.u[BEG]["sm"]
        master = await h.snapshot(["md_item", "md_pending_mapping", "md_pending_slots"])
        req = await h.submitted(lines=[{"material_name": "Баумит леп. бяло 25", "qty_requested": 40,
                                        "unit": "торба", "pending_mapping_id": "PM-REF-1"}])
        line = req["lines"][0]
        assert line["mapping_status"] == "pending_mapping" and line["item_id"] is None
        assert line["pending_mapping_id"] == "PM-REF-1" and req["unmapped_lines"] == 1
        r = await sm.send("POST", "/api/material-requests/%s/approve" % req["id"])
        assert r.status_code == 409 and _code(r) == "UNMAPPED_MATERIAL", r.text
        assert (await h.doc(req["id"]))["status"] == "submitted"
        # an archived / foreign item is never a confirmed mapping
        r = await tech.send("POST", "/api/material-requests", {
            "project_id": "P1", "lines": [{"item_id": "IT-ARCH", "qty_requested": 1, "unit": "бр"}]})
        assert r.status_code == 422 and _code(r) == "ITEM_NOT_FOUND"
        assert await h.snapshot(["md_item", "md_pending_mapping", "md_pending_slots"]) == master

        # an item archived AFTER drafting blocks submit
        d = await h.create(tech)
        await h.op.md_item.update_one({"id": "IT-1", "tenant_id": BEG}, {"$set": {"status": "archived"}})
        r = await tech.send("POST", "/api/material-requests/%s/submit" % d["id"])
        assert r.status_code == 409 and _code(r) == "ITEM_NOT_ACTIVE"
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ 16. invoice cannot fulfil
def test_invoice_posting_cannot_mark_the_request_fulfilled(monkeypatch):
    async def s(h):
        owner = h.u[BEG]["owner"]
        req = await h.approved()
        before = await h.doc(req["id"])
        r = await owner.send("POST", "/api/supplier-invoices", {
            "invoice_number": "INV-1", "invoice_date": "2026-10-10", "project_id": "P1",
            "linked_request_id": req["id"]})
        assert r.status_code == 201, r.text
        inv = r.json()["id"]
        await h.op.supplier_invoices.update_one({"id": inv, "org_id": BEG}, {"$set": {"lines": [
            {"material_name": "x", "qty": 10, "unit": "бр", "unit_price": 1, "total_price": 10,
             "linked_request_id": req["id"]}]}})
        r = await owner.send("POST", "/api/supplier-invoices/%s/post-to-warehouse" % inv)
        assert r.status_code == 201, r.text
        assert await h.doc(req["id"]) == before                      # byte-for-byte unchanged
        r = await owner.get("/api/material-requests/%s" % req["id"])
        assert r.json()["request_state"] == "approved" and r.json()["fulfilled_derived"] is False
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ atomic boundary
def test_audit_failure_aborts_the_domain_write_and_the_idempotency_claim(monkeypatch):
    async def s(h):
        from app.services import material_request_commands as mrc
        tech = h.u[BEG]["tech"]
        req = await h.create(tech)
        snap = await h.snapshot(["material_requests", "audit_idempotency", "audit_events"])
        real = mrc.record_event
        calls = {"n": 0}

        async def failing(db, event, *, session=None):
            if session is not None and event["action"] == "material_request.submit":
                calls["n"] += 1
                await real(db, event, session=session)      # the append itself happens…
                raise RuntimeError("audit store failure after append")  # …then the txn fails
            return await real(db, event, session=session)
        monkeypatch.setattr(mrc, "record_event", failing)
        try:
            await tech.send("POST", "/api/material-requests/%s/submit" % req["id"], key="atomic-key-01")
        except RuntimeError:
            pass
        assert calls["n"] == 1
        assert await h.snapshot(["material_requests", "audit_idempotency", "audit_events"]) == snap
        monkeypatch.setattr(mrc, "record_event", real)
        r = await tech.send("POST", "/api/material-requests/%s/submit" % req["id"], key="atomic-key-01")
        assert r.status_code == 200 and r.json()["replayed"] is False
        await h.chain_ok()
    run(s)(monkeypatch)


@pytest.mark.parametrize("coll,index", [
    ("audit_events", "liveops_b_uniq_tenant_id_sequence"),
    ("audit_events", "liveops_b_uniq_event_id"),
    ("audit_idempotency", "liveops_b_uniq_id"),
    ("material_requests", "liveops_b_uniq_org_id_request_number"),
])
def test_an_index_dropped_after_a_successful_write_disables_the_next_write(monkeypatch, coll, index):
    """F-03: no positive cache. A first write passes the gate; the index is then
    dropped and the very next write fails closed — no internal state is reset."""
    async def s(h):
        owner = h.u[BEG]["owner"]
        first = await h.create(owner)                        # gate checked and passed
        assert first["request_number"]
        await h.op[coll].drop_index(index)
        snap = await h.snapshot(["material_requests", "audit_idempotency"])
        n_events = len(await h.events())
        r = await owner.send("POST", "/api/material-requests", {"project_id": "P1"})
        assert r.status_code == 503 and _code(r) == "REQUIRED_INDEX_MISSING", r.text
        assert [m["collection"] for m in r.json()["detail"]["missing"]] == [coll]
        r = await owner.send("POST", "/api/material-requests/%s/submit" % first["id"])
        assert r.status_code == 503 and _code(r) == "REQUIRED_INDEX_MISSING"
        assert await h.snapshot(["material_requests", "audit_idempotency"]) == snap
        assert len(await h.events()) == n_events
        # the explicit, repeatable bootstrap restores it; verify is green again
        from scripts.live_ops_b_bootstrap import apply, verify
        assert (await verify(h.op))["ok"] is False
        out = await apply(h.op)
        assert out["status"] == "OK" and [a["name"] for a in out["applied"]] == [index]
        assert (await apply(h.op))["applied"] == []          # re-run is a no-op
        assert (await verify(h.op))["ok"] is True
        r = await owner.send("POST", "/api/material-requests", {"project_id": "P1"})
        assert r.status_code == 201
    run(s)(monkeypatch)


def test_closed_project_refuses_new_requests(monkeypatch):
    async def s(h):
        r = await h.u[BEG]["owner"].send("POST", "/api/material-requests", {"project_id": "PC"})
        assert r.status_code == 409 and _code(r) == "PROJECT_NOT_WRITABLE"
        assert not await h.op.material_requests.count_documents({"project_id": "PC"})
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ no write outside the domain
def test_request_commands_write_only_request_audit_and_idempotency(monkeypatch):
    async def s(h):
        u = h.u[BEG]
        before = await h.snapshot()
        # the whole command surface, success and refusal, both tenants
        req = await h.approved()
        await u["sm"].send("POST", "/api/material-requests/%s/cancel" % req["id"], {
            "reason": "x", "lines": [{"line_id": req["lines"][0]["id"], "qty": 1}]})
        r2 = await h.submitted()
        await u["sm"].send("POST", "/api/material-requests/%s/reject" % r2["id"], {"reason": "x"})
        d = await h.create(u["tech"], lines=[{"material_name": "свободен текст", "qty_requested": 1,
                                              "unit": "бр"}])
        await u["tech"].send("PATCH", "/api/material-requests/%s/draft" % d["id"], {"notes": "x"})
        await u["tech"].send("POST", "/api/material-requests/%s/cancel" % d["id"], {"reason": "x"})
        await u["nobody"].send("POST", "/api/material-requests/%s/approve" % r2["id"])
        await h.u[TCB]["owner"].send("POST", "/api/material-requests/%s/approve" % req["id"])
        await h.create(h.u[TCB]["owner"])
        for path in ("/api/material-requests", "/api/material-requests/%s" % req["id"],
                     "/api/material-requests/item-options?q=x",
                     "/api/material-requests/project-options",
                     "/api/material-requests/%s/view" % req["id"], "/api/material-requests/write-status"):
            assert (await u["owner"].get(path)).status_code == 200
        after = await h.snapshot()

        changed = {n for n in set(before) | set(after) if before.get(n) != after.get(n)}
        assert changed <= ALLOWED_WRITE, changed
        for name in FORBIDDEN_WRITE:
            assert before.get(name) == after.get(name), name
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ C01 correction — T1 numbering
def test_request_numbers_are_unique_sequential_after_out_of_order_legacy_history(monkeypatch):
    async def s(h):
        owner = h.u[BEG]["owner"]
        # valid legacy history stored out of order: the NEWER row has the LOWER
        # number; plus a non-standard and a missing number, and the other tenant
        await h.op.material_requests.insert_many([
            {"id": "LEG-3", "org_id": BEG, "project_id": "P1", "status": "draft",
             "request_number": "MR-0003", "created_at": "2026-01-01T00:00:00+00:00", "lines": []},
            {"id": "LEG-2", "org_id": BEG, "project_id": "P1", "status": "draft",
             "request_number": "MR-0002", "created_at": "2026-06-01T00:00:00+00:00", "lines": []},
            {"id": "LEG-X", "org_id": BEG, "project_id": "P1", "status": "draft",
             "request_number": "MR-ABC", "created_at": "2026-07-01T00:00:00+00:00", "lines": []},
            {"id": "LEG-N", "org_id": BEG, "project_id": "P1", "status": "submitted", "lines": []},
            {"id": "LEG-T", "org_id": TCB, "project_id": "P1", "status": "draft",
             "request_number": "MR-0950", "created_at": "2026-08-01T00:00:00+00:00", "lines": []},
        ])
        a = await h.create(owner)
        b = await h.create(owner)
        assert (a["request_number"], b["request_number"]) == ("MR-0004", "MR-0005")
        t = await h.create(h.u[TCB]["owner"])                   # per-tenant sequence
        assert t["request_number"] == "MR-0951"

        rs = await asyncio.gather(*[h.create(h.u[BEG]["tech"]) for _ in range(8)])
        nums = [r["request_number"] for r in rs]
        assert len(set(nums)) == 8, nums
        assert sorted(nums) == ["MR-%04d" % n for n in range(6, 14)]
        all_nums = await h.op.material_requests.distinct("request_number", {"org_id": BEG})
        docs = await h.op.material_requests.find(
            {"org_id": BEG, "request_number": {"$type": "string"}}, {"request_number": 1}).to_list(None)
        assert len(docs) == len(all_nums)                        # no display number twice
        await h.chain_ok()
    run(s)(monkeypatch)


def test_request_number_index_refuses_a_duplicate_even_without_the_allocator(monkeypatch):
    async def s(h):
        await h.op.material_requests.insert_one({"id": "D1", "org_id": BEG, "request_number": "MR-0700"})
        from pymongo.errors import DuplicateKeyError
        with pytest.raises(DuplicateKeyError):
            await h.op.material_requests.insert_one({"id": "D2", "org_id": BEG,
                                                     "request_number": "MR-0700"})
        await h.op.material_requests.insert_one({"id": "D3", "org_id": TCB, "request_number": "MR-0700"})
        await h.op.material_requests.insert_many([{"id": "N1", "org_id": BEG},   # partial: no number
                                                  {"id": "N2", "org_id": BEG}])
    run(s)(monkeypatch)


def test_inventory_reports_legacy_duplicates_read_only_and_bootstrap_stays_fail_closed(monkeypatch):
    async def s(h):
        from scripts.live_ops_b_bootstrap import apply, inventory, verify
        await h.op.material_requests.drop_index("liveops_b_uniq_org_id_request_number")
        await h.op.material_requests.insert_many([
            {"id": "DUP-A", "org_id": BEG, "request_number": "MR-0042", "lines": []},
            {"id": "DUP-B", "org_id": BEG, "request_number": "MR-0042", "lines": []},
            {"id": "OK-T", "org_id": TCB, "request_number": "MR-0042", "lines": []},
            {"id": "ODD", "org_id": BEG, "request_number": "заявка 7", "lines": []},
            {"id": "NONE", "org_id": BEG, "lines": []}])
        before = await h.snapshot()
        rep1, rep2 = await inventory(h.op), await inventory(h.op)
        assert await h.snapshot() == before                      # inventory writes nothing
        assert rep1 == rep2                                      # deterministic, same hash
        assert rep1["blocking"] is True
        assert rep1["request_number_duplicates"] == [
            {"org_id": BEG, "request_number": "MR-0042", "count": 2, "ids": ["DUP-A", "DUP-B"]}]
        assert rep1["tenants"][BEG]["non_standard_number"] == 1
        assert rep1["tenants"][BEG]["missing_number"] == 1 and rep1["tenants"][BEG]["max_number"] == 42
        assert [m["collection"] for m in rep1["missing_indexes"]] == ["material_requests"]

        out = await apply(h.op)                                  # refused, nothing changed
        assert out["status"] == "BLOCKED" and out["applied"] == []
        assert await h.snapshot() == before
        assert (await verify(h.op))["ok"] is False
        r = await h.u[BEG]["owner"].send("POST", "/api/material-requests", {"project_id": "P1"})
        assert r.status_code == 503 and _code(r) == "REQUIRED_INDEX_MISSING"
        assert await h.snapshot(["material_requests"]) == {"material_requests": before["material_requests"]}
    run(s)(monkeypatch)


def test_bootstrap_cli_inventory_apply_verify_per_named_database(monkeypatch):
    async def s(h):
        from scripts import live_ops_b_bootstrap as boot
        await h.op.material_requests.drop_index("liveops_b_uniq_org_id_request_number")
        args = ["--mongo-url", REAL_URL, "--db", h.op.name]
        assert await boot.main(["--verify"] + args) == boot.EXIT_MISSING
        assert await boot.main(args) == boot.EXIT_OK                       # inventory: clean
        assert await boot.main(["--apply"] + args) == boot.EXIT_USAGE      # no confirmation
        assert await boot.main(["--apply", "--confirm-db", h.op.name] + args) == boot.EXIT_OK
        assert await boot.main(["--verify"] + args) == boot.EXIT_OK
        assert await boot.main(["--apply", "--confirm-db", h.op.name] + args) == boot.EXIT_OK
        # --all-tenants reads the registry's database names
        assert await boot.main(["--verify", "--all-tenants", "--system-db", h.sysdb.name,
                                "--mongo-url", REAL_URL]) == boot.EXIT_OK
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ C01 correction — T4 requester
def test_requester_alternative_is_one_decision_and_survives_create_revocation(monkeypatch):
    async def s(h):
        from app.permissions import service
        u = h.u[BEG]
        d1 = await h.create(u["tech"])
        d2 = await h.submitted()
        # the requester's own create/submit assignment is revoked
        await h.sysdb.tenant_role_assignments.update_one(
            {"id": "beg-ra-tech"}, {"$set": {"status": "revoked"}, "$inc": {"revision": 1}})

        calls = []
        real = service.evaluate_permission

        async def counting(ctx, action, **kw):
            calls.append((action, kw.get("scope_type"), kw.get("scope_id")))
            return await real(ctx, action, **kw)
        monkeypatch.setattr(service, "evaluate_permission", counting)

        r = await u["tech"].send("PATCH", "/api/material-requests/%s/draft" % d1["id"], {"notes": "own"})
        assert r.status_code == 200, r.text
        assert calls == [("material_request.edit_draft", "project", "P1")]   # ONE exact decision
        calls.clear()
        r = await u["tech"].send("POST", "/api/material-requests/%s/cancel" % d2["id"], {"reason": "own"})
        assert r.status_code == 200 and r.json()["request"]["request_state"] == "cancelled"
        assert calls == [("material_request.cancel", "project", "P1")]
        for rid, action in ((d1["id"], "material_request.edit_draft"),
                            (d2["id"], "material_request.cancel")):
            ev = (await h.events(entity_id=rid, action=action, result="success"))[-1]
            basis = ev["structured_diff"]["permission_basis"]
            assert basis == {"action": action, "decision": "ASSIGNMENT_REVOKED", "basis": "requester",
                             "role_assignment_revisions": {}}
            assert ev["effective_role_assignments"] == [] and ev["actor_id"] == "beg-tech"

        # the alternative covers ONLY draft edit and pre-approval cancel
        calls.clear()
        r = await u["tech"].send("POST", "/api/material-requests/%s/submit" % d1["id"])
        assert r.status_code == 403 and r.json()["detail"]["reason"] == "ASSIGNMENT_REVOKED"
        assert calls == [("material_request.submit", "project", "P1")]

        # a NON-requester still needs the exact action: tech2 holds create+submit only
        d4 = await h.create(u["owner"])
        r = await u["tech2"].send("PATCH", "/api/material-requests/%s/draft" % d4["id"], {"notes": "x"})
        assert r.status_code == 403 and r.json()["detail"]["reason"] == "ACTION_NOT_ALLOWED"
        r = await u["tech2"].send("POST", "/api/material-requests/%s/cancel" % d4["id"], {"reason": "x"})
        assert r.status_code == 403 and r.json()["detail"]["reason"] == "ACTION_NOT_ALLOWED"
        # …and an exact-action holder who is not the requester is allowed by permission
        r = await u["sm"].send("POST", "/api/material-requests/%s/cancel" % d4["id"], {"reason": "x"})
        assert r.status_code == 200
        ev = (await h.events(entity_id=d4["id"], action="material_request.cancel", result="success"))[-1]
        assert ev["structured_diff"]["permission_basis"]["basis"] == "permission"
        assert ev["effective_role_assignments"] == ["beg-ra-sm"]
        # the requester alternative is never available after approval
        await h.sysdb.tenant_role_assignments.update_one(
            {"id": "beg-ra-tech"}, {"$set": {"status": "active"}})
        appr = await h.approved()
        r = await u["tech"].send("POST", "/api/material-requests/%s/cancel" % appr["id"], {"reason": "x"})
        assert r.status_code == 403 and r.json()["detail"]["action"] == "material_request.cancel_approved"
    run(s)(monkeypatch)


# ═══════════════════════════════════════════════════════ C01 correction — T2 visibility
def test_project_options_follow_the_create_authority(monkeypatch):
    async def s(h):
        u = h.u[BEG]

        async def options(caller):
            r = await caller.get("/api/material-requests/project-options")
            assert r.status_code == 200, r.text
            assert "TCBMARK" not in r.text
            return [p["id"] for p in r.json()["projects"]]
        # beg-tech: project-scope create on P1 and NO project_team row
        assert await options(u["tech"]) == ["P1"]
        r = await u["tech"].send("POST", "/api/material-requests", {"project_id": "P1"})
        assert r.status_code == 201                       # what the picker offers, create accepts
        assert await options(u["outsider"]) == ["P2"]
        assert await options(u["sm"]) == []               # approver, not a creator
        assert await options(u["member"]) == []           # legacy membership grants no write
        assert await options(u["nobody"]) == []           # JWT role Owner, no assignment
        assert await options(u["revoked"]) == []
        assert await options(u["owner"]) == ["P1", "P2"]  # company scope; closed PC omitted
        monkeypatch.setenv("PERMISSION_SERVICE_MODE", "shadow")
        r = await u["owner"].get("/api/material-requests/project-options")
        assert r.json()["status"] == "unavailable" and r.json()["projects"] == []
    run(s)(monkeypatch)


def test_list_and_detail_visibility_has_no_cross_project_leak(monkeypatch):
    async def s(h):
        u = h.u[BEG]
        p1 = await h.create(u["owner"], project="P1", reason="P1-ONLY-MARK")
        p2 = await h.create(u["owner"], project="P2", reason="P2-ONLY-MARK")
        mine = await h.create(u["tech"], project="P1")

        async def visible(caller):
            r = await caller.get("/api/material-requests")
            assert r.status_code == 200
            return r, {x["id"] for x in r.json()}

        # tech: request authority on P1 only (no project_team) → P1, never P2
        r, ids = await visible(u["tech"])
        assert ids == {p1["id"], mine["id"]} and "P2-ONLY-MARK" not in r.text
        for path in ("", "/view"):
            assert (await u["tech"].get("/api/material-requests/%s%s" % (p2["id"], path))).status_code == 404
            assert (await u["tech"].get("/api/material-requests/%s%s" % (p1["id"], path))).status_code == 200
        # outsider: authority on P2 only
        r, ids = await visible(u["outsider"])
        assert ids == {p2["id"]} and "P1-ONLY-MARK" not in r.text
        assert (await u["outsider"].get("/api/material-requests/%s/view" % p1["id"])).status_code == 404
        # member: the preserved legacy boundary — project_team on P2, read only
        r, ids = await visible(u["member"])
        assert ids == {p2["id"]} and "P1-ONLY-MARK" not in r.text
        assert (await u["member"].get("/api/material-requests/%s" % p1["id"])).status_code == 404
        v = (await u["member"].get("/api/material-requests/%s/view" % p2["id"])).json()
        assert not any(a["allowed"] for a in v["allowed_actions"].values())
        # revoked approver on P1, no membership: sees nothing
        r, ids = await visible(u["revoked"])
        assert ids == set()
        # the documented legacy read boundary for Admin/Owner/Accountant is unchanged
        r, ids = await visible(u["nobody"])
        assert {p1["id"], p2["id"], mine["id"]} <= ids
        # a requester keeps seeing their own request after losing the project
        await h.sysdb.tenant_role_assignments.update_one(
            {"id": "beg-ra-tech"}, {"$set": {"status": "revoked"}})
        r, ids = await visible(u["tech"])
        assert ids == {mine["id"]}
        assert (await u["tech"].get("/api/material-requests/%s" % p1["id"])).status_code == 404
        # off-enforce: authority adds nothing, the legacy boundary still applies
        monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
        r, ids = await visible(u["outsider"])
        assert ids == set()
        r, ids = await visible(u["member"])
        assert ids == {p2["id"]}
    run(s)(monkeypatch)
