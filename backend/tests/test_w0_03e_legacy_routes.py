"""
W0-03E — legacy route adapters: the identity delete paths, the warehouse bulk
reset, new advances (§4.5), read annotation and the Master Data legacy API.

The promises under test:

  * the seven delete-by-id identity paths of contract §3.2 (auth, clients,
    counterparties, locations, projects person/company, smr_groups) plus the
    asset item/unit deletions scope the actual delete by the org they checked —
    a same-id record of another org is never touched, in any mode;
  * ``warehouses.py`` no longer deletes with ``delete_many({"org_id": ...})``;
  * ``MASTER_DATA_MODE=off``: the legacy response is unchanged and no Master
    Data or audit machinery is touched; ``shadow`` behaves the same and writes
    nothing new;
  * ``enforce``: a used or migrated identity is never hard-deleted — archived
    where the legacy record has an archive flag, refused (409) where it has none;
    the adapter write needs ``master_data.legacy.delete`` (default deny), an
    unresolvable tenant or a foreign data path is refused, and every outcome
    leaves a canonical AuditEvent, the denials included;
  * a new advance without an official Master Person is refused in enforce
    (``ADVANCE_REQUIRES_MASTER_PERSON``); old ``guest_name`` advances stay
    readable and unchanged; off is unchanged;
  * the legacy API is inert when off, closed to other roles, fails closed
    without Approval, refuses a forged org_id and a tenant key in the body.

Run:  pytest tests/test_w0_03e_legacy_routes.py -v --noconftest
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.audit.store import AUDIT_COLLECTION
from app.deps.auth import get_current_user
from app.deps.modules import require_m2, require_m4, require_m5
from app.master_data import legacy_adapter as la
from app.master_data import legacy_plan as lp
from app.master_data.deps import ENV_MODE
from app.routes import (
    assets_items, assets_units, auth, clients, counterparties, hr, items, locations,
    master_data as md_routes, projects, smr_groups, subcontractors, warehouses,
)

from tests.test_w0_03e_legacy_migration import (
    ORG_A, ORG_B, T_A, Ctx, dry, go, new_db, repo, run, seeded,
)

ADMIN = {"id": "admin-1", "org_id": ORG_A, "role": "Admin", "email": "a@x"}
ACCOUNTANT = {"id": "acc-1", "org_id": ORG_A, "role": "Accountant", "email": "acc@x"}
SITE = {"id": "site-1", "org_id": ORG_A, "role": "SiteManager", "email": "s@x"}

# module, collection, url template, allowed legacy role, used-by, archive flag
DELETE_PATHS = [
    (auth, "users", "/api/users/%s", ADMIN, ("project_team", {"user_id": None}), "is_active"),
    (clients, "clients", "/api/clients/%s", ADMIN, ("sales", {"client_id": None}), "is_active"),
    (counterparties, "counterparties", "/api/counterparties/%s", ADMIN,
     ("supplier_invoices", {"supplier_id": None}), "active"),
    (locations, "location_nodes", "/api/locations/%s", ADMIN,
     ("material_waste", {"location_id": None}), None),
    (projects, "persons", "/api/persons/%s", ADMIN, None, "is_active"),
    (projects, "companies", "/api/companies/%s", ADMIN, None, "is_active"),
    (smr_groups, "smr_groups", "/api/smr-groups/%s", ADMIN, ("missing_smr", {"group_id": None}), None),
    (assets_items, "asset_items", "/api/assets/items/%s", ADMIN, None, "is_active"),
    (assets_units, "asset_units", "/api/assets/units/%s", ADMIN,
     ("asset_custody", {"unit_id": None}), "is_active"),
]
IDS = [p[1] for p in DELETE_PATHS]


class RouteCtx(Ctx):
    def __init__(self, db, matches=True, **kw):
        super().__init__(db, **kw)
        self._matches = matches

    async def data_path_matches(self, handle):
        return self._matches


def client_for(monkeypatch, module, db, user):
    monkeypatch.setattr(module, "db", db)

    async def _noop(*a, **kw):
        return None
    if hasattr(module, "log_audit"):
        monkeypatch.setattr(module, "log_audit", _noop)
    app = FastAPI()
    app.include_router(module.router, prefix="/api")

    async def _user():
        return dict(user)
    for dep in (get_current_user, require_m2, require_m4, require_m5):
        app.dependency_overrides[dep] = _user
    return TestClient(app, raise_server_exceptions=False)


def enforce_with(monkeypatch, db, ctx=None, **kw):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    ctx = ctx if ctx is not None else RouteCtx(db, **kw)

    async def _ctx(user):
        return ctx
    monkeypatch.setattr(la, "context_for", _ctx)

    async def _tc(request, user):
        return ctx
    monkeypatch.setattr(md_routes, "get_tenant_context", _tc)
    return ctx


def landmines(monkeypatch):
    touched = []

    def mine(label):
        async def boom(*a, **kw):
            touched.append(label)
            raise AssertionError("touched: " + label)
        return boom
    monkeypatch.setattr(la, "context_for", mine("tenant context"))
    monkeypatch.setattr(la, "count_usage", mine("usage count"))
    monkeypatch.setattr("app.audit.store.record_event", mine("audit store"))
    monkeypatch.setattr("app.tenancy.registry.get_tenant", mine("tenant registry"))
    return touched


def doc_for(collection, legacy_id, org):
    base = {"id": legacy_id, "org_id": org, "name": "Запис " + legacy_id,
            "first_name": "Име", "last_name": legacy_id, "is_active": True, "active": True}
    if collection == "location_nodes":
        base.update(project_id="pr1", parent_id=None)
    if collection == "smr_groups":
        base.update(project_id="pr1")
    return base


def db_with(collection, *docs):
    db = new_db()

    async def fill():
        for d in docs:
            await db[collection].insert_one(dict(d))
    run(fill())
    return db


async def find_all(db, name, query=None):
    return await db[name].find(query or {}, {"_id": 0}).to_list(None)


# ================================================================ scoping, all modes
@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("path", DELETE_PATHS, ids=IDS)
def test_a_same_id_record_of_another_org_is_never_deleted(monkeypatch, path, mode):
    module, coll, url, user, _used, _flag = path
    mine, theirs = doc_for(coll, "same-id", ORG_A), doc_for(coll, "same-id", ORG_B)
    # other org's record is stored FIRST: an unscoped delete_one({"id"}) would take it
    db = db_with(coll, theirs, mine)
    if mode == "enforce":
        enforce_with(monkeypatch, db)
    else:
        monkeypatch.setenv(ENV_MODE, mode)
    response = client_for(monkeypatch, module, db, user).delete(url % "same-id")
    assert response.status_code == 200, response.text
    left = run(find_all(db, coll))
    assert [d["org_id"] for d in left] == [ORG_B], left


@pytest.mark.parametrize("path", DELETE_PATHS, ids=IDS)
def test_a_foreign_id_is_not_found_and_untouched(monkeypatch, path):
    module, coll, url, user, _used, _flag = path
    monkeypatch.setenv(ENV_MODE, "enforce")
    enforce_with(monkeypatch, None)
    db = db_with(coll, doc_for(coll, "b-only", ORG_B))
    response = client_for(monkeypatch, module, db, user).delete(url % "b-only")
    assert response.status_code == 404
    assert len(run(find_all(db, coll))) == 1


# ================================================================ off / shadow
@pytest.mark.parametrize("path", DELETE_PATHS, ids=IDS)
def test_off_keeps_the_legacy_behaviour_and_touches_no_master_data(monkeypatch, path):
    module, coll, url, user, used, _flag = path
    monkeypatch.delenv(ENV_MODE, raising=False)
    touched = landmines(monkeypatch)
    db = db_with(coll, doc_for(coll, "x1", ORG_A))
    if used:
        ref_coll, fields = used
        run(db[ref_coll].insert_one(dict({k: "x1" for k in fields}, id="r1", org_id=ORG_A)))
    response = client_for(monkeypatch, module, db, user).delete(url % "x1")
    assert touched == []
    assert response.status_code == 200, response.text
    assert "archived" not in response.json()
    assert run(db[coll].count_documents({"id": "x1"})) == 0          # legacy hard delete, as before


def test_shadow_never_blocks_and_writes_no_audit(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "shadow")
    db = db_with("clients", doc_for("clients", "x1", ORG_A))
    run(db["sales"].insert_one({"id": "s1", "org_id": ORG_A, "client_id": "x1"}))
    response = client_for(monkeypatch, clients, db, ADMIN).delete("/api/clients/x1")
    assert response.status_code == 200
    assert run(db[AUDIT_COLLECTION].count_documents({})) == 0
    assert run(db["clients"].count_documents({})) == 0


# ================================================================ enforce
@pytest.mark.parametrize("path", [p for p in DELETE_PATHS if p[4]], ids=[p[1] for p in DELETE_PATHS if p[4]])
def test_enforce_never_hard_deletes_a_used_identity(monkeypatch, path):
    module, coll, url, user, used, flag = path
    db = db_with(coll, doc_for(coll, "x1", ORG_A))
    ref_coll, fields = used
    run(db[ref_coll].insert_one(dict({k: "x1" for k in fields}, id="r1", org_id=ORG_A)))
    enforce_with(monkeypatch, db)
    response = client_for(monkeypatch, module, db, user).delete(url % "x1")
    kept = run(db[coll].find_one({"id": "x1"}))
    assert kept is not None, "a used identity was hard-deleted"
    events = run(find_all(db, AUDIT_COLLECTION))
    if flag:
        assert response.status_code == 200 and response.json()["archived"] is True
        assert response.json()["reason"] == la.REASON_IN_USE
        assert kept[flag] is False
        assert events[-1]["action"] == "master_data.legacy.archived_instead_of_delete"
    else:
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == la.REASON_IN_USE
        assert events[-1]["action"] == "master_data.legacy.delete_refused"
        assert events[-1]["result"] == "denied"
    assert events[-1]["tenant_id"] == T_A and events[-1]["entity_id"] == "x1"
    assert "%s.%s" % (ref_coll, list(fields)[0]) in events[-1]["structured_diff"]["usage"]
    assert run(db[ref_coll].count_documents({})) == 1               # references untouched


@pytest.mark.parametrize("path", DELETE_PATHS, ids=IDS)
def test_enforce_never_hard_deletes_a_migrated_identity(monkeypatch, path):
    module, coll, url, user, _used, flag = path
    db = db_with(coll, doc_for(coll, "x1", ORG_A))
    run(db[lp.REFS_COLLECTION].insert_one({
        "_id": lp.ref_row_id(T_A, coll, "x1"), "tenant_id": T_A, "collection": coll,
        "legacy_id": "x1", "org_id": ORG_A, "status": "mapped", "entity_id": "m-1"}))
    enforce_with(monkeypatch, db)
    response = client_for(monkeypatch, module, db, user).delete(url % "x1")
    assert run(db[coll].find_one({"id": "x1"})) is not None
    if flag:
        assert response.status_code == 200 and response.json()["reason"] == la.REASON_MASTER_OWNED
    else:
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == la.REASON_MASTER_OWNED


@pytest.mark.parametrize("path", DELETE_PATHS, ids=IDS)
def test_enforce_deletes_an_unused_unmigrated_identity_with_evidence(monkeypatch, path):
    module, coll, url, user, _used, _flag = path
    db = db_with(coll, doc_for(coll, "x1", ORG_A))
    enforce_with(monkeypatch, db)
    response = client_for(monkeypatch, module, db, user).delete(url % "x1")
    assert response.status_code == 200, response.text
    assert run(db[coll].count_documents({})) == 0
    event = run(find_all(db, AUDIT_COLLECTION))[-1]
    assert event["action"] == "master_data.legacy.deleted" and event["result"] == "success"
    assert event["actor_id"] == "owner-1" and event["entity_type"] == "legacy." + coll


def test_enforce_requires_the_adapter_permission_and_audits_the_denial(monkeypatch):
    for module, coll, url, user in ((clients, "clients", "/api/clients/%s", ACCOUNTANT),
                                    (locations, "location_nodes", "/api/locations/%s", SITE)):
        db = db_with(coll, doc_for(coll, "x1", ORG_A))
        enforce_with(monkeypatch, db)
        response = client_for(monkeypatch, module, db, user).delete(url % "x1")
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["denial_audit"] == "recorded"
        assert run(db[coll].count_documents({})) == 1
        event = run(find_all(db, AUDIT_COLLECTION))[-1]
        assert event["action"] == "permission.denied" and event["result"] == "denied"
        assert "master_data.legacy.delete" in event["reason"]


def test_enforce_refuses_without_a_resolved_tenant_or_on_a_foreign_data_path(monkeypatch):
    db = db_with("clients", doc_for("clients", "x1", ORG_A))
    monkeypatch.setenv(ENV_MODE, "enforce")

    async def none(user):
        return None
    monkeypatch.setattr(la, "context_for", none)
    r = client_for(monkeypatch, clients, db, ADMIN).delete("/api/clients/x1")
    assert r.status_code == 403 and r.json()["detail"]["error_code"] == "TENANT_NOT_RESOLVED"
    enforce_with(monkeypatch, db, matches=False)
    r = client_for(monkeypatch, clients, db, ADMIN).delete("/api/clients/x1")
    assert r.status_code == 409 and r.json()["detail"]["error_code"] == "TENANT_DATA_PATH_NOT_MIGRATED"
    enforce_with(monkeypatch, db, ctx=RouteCtx(db, org_id=ORG_B))
    r = client_for(monkeypatch, clients, db, ADMIN).delete("/api/clients/x1")
    assert r.status_code == 409
    assert run(db["clients"].count_documents({})) == 1


def test_an_invalid_master_data_mode_refuses_the_delete(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "enforc")
    db = db_with("clients", doc_for("clients", "x1", ORG_A))
    r = client_for(monkeypatch, clients, db, ADMIN).delete("/api/clients/x1")
    assert r.status_code == 503
    assert run(db["clients"].count_documents({})) == 1


# ================================================================ warehouses bulk
def test_warehouse_reset_no_longer_bulk_deletes_by_org(monkeypatch):
    import inspect
    assert 'delete_many({"org_id"' not in inspect.getsource(warehouses)
    monkeypatch.delenv(ENV_MODE, raising=False)
    db = db_with("warehouses", {"id": "w1", "org_id": ORG_A, "name": "A", "active": True},
                 {"id": "w2", "org_id": ORG_A, "name": "B", "active": True},
                 {"id": "w1", "org_id": ORG_B, "name": "B's", "active": True})
    r = client_for(monkeypatch, warehouses, db, ADMIN).post("/api/dev/reset-warehouses")
    assert r.status_code == 200 and r.json()["deleted_count"] == 2 and "kept" not in r.json()
    assert [d["org_id"] for d in run(find_all(db, "warehouses"))] == [ORG_B]


def test_warehouse_reset_in_enforce_keeps_used_warehouses(monkeypatch):
    db = db_with("warehouses", {"id": "w1", "org_id": ORG_A, "name": "A", "active": True},
                 {"id": "w2", "org_id": ORG_A, "name": "B", "active": True})
    run(db["warehouse_transactions"].insert_one({"id": "t1", "org_id": ORG_A, "warehouse_id": "w1"}))
    enforce_with(monkeypatch, db)
    r = client_for(monkeypatch, warehouses, db, ADMIN).post("/api/dev/reset-warehouses")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_count"] == 1
    assert r.json()["kept"] == [{"id": "w1", "reason": la.REASON_IN_USE}]
    assert run(db["warehouses"].find_one({"id": "w1"}))["active"] is False


# ================================================================ advances (§4.5)
async def _migrated_world():
    db = await seeded()
    p = await dry(db)
    await go(db, p["plan_token"])
    return db


def _advance(monkeypatch, db, body):
    return client_for(monkeypatch, hr, db, ADMIN).post("/api/advances", json=body)


def test_enforce_refuses_a_new_advance_without_a_master_person(monkeypatch):
    db = run(_migrated_world())
    enforce_with(monkeypatch, db)
    old = run(find_all(db, "advances"))
    for body in ({"type": "Loan", "guest_name": "Мария Георгиева", "amount": 10},
                 {"type": "Advance", "user_id": "u2", "amount": 10},          # u2 is pending
                 {"type": "Loan", "person_id": "no-such", "amount": 10}):
        r = _advance(monkeypatch, db, body)
        assert r.status_code == 422, (body, r.text)
        assert r.json()["detail"]["error_code"] == la.REASON_ADVANCE_PERSON
    assert run(find_all(db, "advances")) == old                     # nothing created or changed
    refusals = [e for e in run(find_all(db, AUDIT_COLLECTION))
                if e["action"] == "master_data.advance.create_refused"]
    assert len(refusals) == 3 and all(e["result"] == "denied" for e in refusals)
    # the exact-name person was not created or linked by the refusal
    assert run(db["md_person"].count_documents({"normalized_name": "мария георгиева"})) == 0


def test_enforce_accepts_an_advance_for_an_official_master_person(monkeypatch):
    db = run(_migrated_world())
    ctx = enforce_with(monkeypatch, db)
    u1 = run(la.resolve_legacy(ctx, collection="users", legacy_id="u1", mode="enforce",
                               repository=repo(db)))
    r = _advance(monkeypatch, db, {"type": "Advance", "user_id": "u1", "amount": 10})
    assert r.status_code == 201, r.text
    assert r.json()["master_person_id"] == u1["canonical_id"]
    r = _advance(monkeypatch, db, {"type": "Loan", "person_id": u1["canonical_id"], "amount": 5})
    assert r.status_code == 201 and r.json()["recipient_name"] == "Иван Петров"
    u3 = run(la.resolve_legacy(ctx, collection="users", legacy_id="u3", mode="enforce",
                               repository=repo(db)))
    r = _advance(monkeypatch, db, {"type": "Advance", "user_id": "u1",
                                   "person_id": u3["canonical_id"], "amount": 5})
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == la.REASON_ADVANCE_MISMATCH
    old = run(db["advances"].find_one({"id": "adv2"}))
    assert old["guest_name"] == "Мария Георгиева" and "master_person_id" not in old


def test_off_and_shadow_keep_guest_loans_unchanged(monkeypatch):
    for mode in ("off", "shadow"):
        monkeypatch.setenv(ENV_MODE, mode)
        touched = landmines(monkeypatch)
        db = new_db()
        r = _advance(monkeypatch, db, {"type": "Loan", "guest_name": "Гост", "amount": 10,
                                       "person_id": "ignored"})
        assert r.status_code == 201 and touched == []
        assert "master_person_id" not in r.json() and r.json()["guest_name"] == "Гост"
        monkeypatch.undo()


# ================================================================ read annotation
def test_enforce_annotates_legacy_reads_and_off_does_not(monkeypatch):
    db = run(_migrated_world())
    monkeypatch.delenv(ENV_MODE, raising=False)
    plain = client_for(monkeypatch, items, db, ADMIN).get("/api/items/i1").json()
    assert "master_ref" not in plain
    enforce_with(monkeypatch, db)
    got = client_for(monkeypatch, items, db, ADMIN).get("/api/items/i1").json()
    assert got["id"] == "i1" and got["sku"] == "ABC-1"                 # the old record, whole
    assert got["master_ref"]["status"] == "mapped" and got["master_ref"]["canonical_id"]
    sub = client_for(monkeypatch, subcontractors, db, ADMIN).get("/api/subcontractors/s2").json()
    assert sub["master_ref"]["canonical_id"] == "org-existing"
    pending = client_for(monkeypatch, subcontractors, db, ADMIN).get("/api/subcontractors/s1").json()
    assert pending["master_ref"]["status"] == "pending" and pending["master_ref"]["canonical_id"] is None


# ================================================================ Master Data legacy API
LEGACY_API = [
    ("get", "/api/master-data/legacy/plan", None),
    ("post", "/api/master-data/legacy/migration", {"plan_token": "t", "idempotency_key": "k"}),
    ("get", "/api/master-data/legacy/migration/r1", None),
    ("get", "/api/master-data/legacy/reconcile", None),
    ("post", "/api/master-data/legacy/rollback/preview", {"run_id": "r1"}),
    ("post", "/api/master-data/legacy/rollback", {"run_id": "r1", "preview_token": "t",
                                                  "idempotency_key": "k", "reason": "x"}),
    ("get", "/api/master-data/legacy/mappings", None),
    ("post", "/api/master-data/legacy/mappings/decide", {"collection": "users", "legacy_id": "u2",
                                                         "decision": "decline",
                                                         "idempotency_key": "k"}),
    ("get", "/api/master-data/legacy/resolve?collection=users&legacy_id=u1", None),
    ("get", "/api/master-data/legacy/advances/mapping-report", None),
]


def md_client(user):
    app = FastAPI()
    app.include_router(md_routes.router, prefix="/api")

    async def _user():
        return dict(user)
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


def call(c, method, url, body):
    return c.get(url) if method == "get" else c.post(url, json=body)


def test_off_answers_every_legacy_endpoint_without_touching_anything(monkeypatch):
    monkeypatch.delenv(ENV_MODE, raising=False)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    touched = landmines(monkeypatch)
    monkeypatch.setattr(md_routes, "get_tenant_context", la.context_for)   # a landmine too
    for method, url, body in LEGACY_API:
        r = call(md_client(ADMIN), method, url, body)
        assert r.status_code == 200, (url, r.text)
        assert r.json()["mode"] == "off"
    assert touched == []


@pytest.mark.parametrize("user", [ACCOUNTANT, SITE, {"id": "u", "org_id": ORG_A, "role": "Driver"}])
def test_other_roles_are_refused_before_any_machinery(monkeypatch, user):
    monkeypatch.setenv(ENV_MODE, "shadow")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    touched = landmines(monkeypatch)
    monkeypatch.setattr(md_routes, "get_tenant_context", la.context_for)
    for method, url, body in LEGACY_API:
        if "resolve?" in url:
            continue                        # the ordinary Master Data read action
        r = call(md_client(user), method, url, body)
        assert r.status_code == 403, (url, r.status_code)
    assert touched == []


def test_the_route_fails_closed_on_approval_and_audits(monkeypatch):
    db = run(seeded())
    enforce_with(monkeypatch, db)
    monkeypatch.setattr(lp, "_repository_for", lambda c: repo(db, c.tenant_id))
    from app.master_data import legacy_migration as lm
    monkeypatch.setattr(lm, "_repository_for", lambda c: repo(db, c.tenant_id))
    monkeypatch.setattr(la, "_repository_for", lambda c: repo(db, c.tenant_id))
    c = md_client(ADMIN)
    plan = c.get("/api/master-data/legacy/plan").json()["plan"]
    assert all("8001011234" not in str(i["identifiers"]) for i in plan["items"])
    r = c.post("/api/master-data/legacy/migration",
               json={"plan_token": plan["plan_token"], "idempotency_key": "k1",
                     "confirmation": True, "approval_id": "APR-forged"})
    assert r.status_code == 403 and r.json()["detail"]["error_code"] == "APPROVAL_REQUIRED"
    assert run(db[lp.REFS_COLLECTION].count_documents({})) == 0
    events = run(find_all(db, AUDIT_COLLECTION))
    assert events[-1]["action"] == "master_data.legacy_migration.execute_refused"
    r = c.post("/api/master-data/legacy/migration",
               json={"plan_token": "t", "idempotency_key": "k", "tenant_id": "tenant-b"})
    assert r.status_code == 422
    r = c.get("/api/master-data/legacy/resolve?collection=users&legacy_id=u1&org_id=" + ORG_B)
    assert r.status_code == 403 and r.json()["detail"]["error_code"] == "LEGACY_ORG_MISMATCH"
    r = c.get("/api/master-data/legacy/reconcile")
    assert r.status_code == 200 and r.json()["reconciliation"]["counts"]["unmigrated"] > 0
    # the office may decide mappings but not execute; its refusal is audited
    r = md_client({"id": "o", "org_id": ORG_A, "role": "office"}).post(
        "/api/master-data/legacy/migration",
        json={"plan_token": "t", "idempotency_key": "k", "confirmation": True})
    assert r.status_code == 403 and r.json()["detail"]["denial_audit"] == "recorded"
