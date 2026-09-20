"""
W0-03B4 — the route boundary, authorization, and surviving a partial failure.

The four properties this file exists to prove, because a service-level test
cannot prove any of them:

  * **off is inert at the route**, not merely inside the service. Every Master
    Data endpoint is called with the whole machinery replaced by spies that
    explode on contact — tenant resolver, registry, repository, audit store and
    the service entry points. A passing test means the request never reached
    any of them;
  * **an unusable mode refuses first**, before authorization and before
    anything is resolved;
  * **authorization exists**. A role that may not approve is refused, and it is
    refused *before* a repository, a tenant database or a write — proven the
    same way, with the machinery armed to explode;
  * **an interrupted approval does not produce a second official record.** The
    failure is injected between "the Master record was written" and "the pending
    row was closed" — the exact window that makes duplicates — and the retry is
    then required to finish the job, create nothing new, and leave an audit
    trail that says what actually happened. The same window is also driven
    *concurrently*, by two in-flight approvals from the same reviewer, because
    a double click is two callers and the claim must treat it as two.

No database and no live application: a FastAPI app carrying only this router,
plus the spies from the W0-03B3 suite.

Run:  pytest tests/test_w0_03b4_routes_and_authorization.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.deps.auth import get_current_user
from app.master_data import models
from app.master_data.deps import ENV_MODE
from app.master_data.models import MasterDataInvalid
from app.master_data.pending import (
    PENDING_COLLECTION,
    SOURCE_OCR,
    STATUS_PENDING,
    STATUS_RESOLVED,
    STATUS_RESOLVING,
    propose,
)
from app.master_data.repository import MasterDataRepository
from app.master_data.review import approve
from app.master_data.service import MasterDataAuditFailed, MasterDataRefused
from app.permissions import deps as permission_deps
from app.routes import master_data as routes

from tests.test_w0_03b3_review_and_matching import Ctx, SpyDb, run

ORG = models.ENTITY_ORGANIZATION
ENV_PERMISSION_MODE = "PERMISSION_SERVICE_MODE"

# --- the six endpoints, as a client calls them -----------------------------
OWNER = {"id": "u-owner", "role": "Owner"}
OFFICE = {"id": "u-office", "role": "office"}
WAREHOUSE = {"id": "u-wh", "role": "Warehousekeeper"}
DRIVER = {"id": "u-driver", "role": "Driver"}
ROLELESS = {"id": "u-none"}

PROPOSE_BODY = {"entity_type": ORG, "raw_value": "Баумит ЕООД", "source_channel": "ocr"}


def _call(client, name: str):
    """One request per endpoint, by name, so a test can sweep all six."""
    return {
        "propose": lambda: client.post("/api/master-data/pending", json=PROPOSE_BODY),
        "queue": lambda: client.get("/api/master-data/pending"),
        "matches": lambda: client.get("/api/master-data/pending/p-1/matches"),
        "approve": lambda: client.post("/api/master-data/pending/p-1/approve",
                                       json={"confirmation": True, "create_new": True}),
        "reject": lambda: client.post("/api/master-data/pending/p-1/reject",
                                      json={"reason": "not a supplier"}),
        "entity": lambda: client.get("/api/master-data/organization/e-1"),
    }[name]()


ENDPOINTS = ("propose", "queue", "matches", "approve", "reject", "entity")


def _client(user):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    async def _session_user():
        return dict(user)

    app.dependency_overrides[get_current_user] = _session_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def armed(monkeypatch):
    """Replace every piece of Master Data machinery with a landmine.

    Authentication is deliberately NOT armed: ``get_current_user`` is the
    platform's existing auth path that every route already uses, and it is
    outside this boundary. Everything that belongs to Master Data is here.
    """
    touched = []

    def landmine(label):
        async def _boom(*args, **kwargs):
            touched.append(label)
            raise AssertionError("master data machinery touched: %s" % label)
        return _boom

    def sync_landmine(label):
        def _boom(*args, **kwargs):
            touched.append(label)
            raise AssertionError("master data machinery touched: %s" % label)
        return _boom

    monkeypatch.setattr(routes, "get_tenant_context", landmine("tenant resolver"))
    monkeypatch.setattr("app.tenancy.guard._resolve_active_tenant_id",
                        landmine("active tenant resolution"))
    monkeypatch.setattr("app.tenancy.registry.get_tenant", landmine("tenant registry"))
    monkeypatch.setattr("app.master_data.repository.MasterDataRepository",
                        sync_landmine("repository"))
    monkeypatch.setattr("app.audit.store.record_event", landmine("audit store"))
    monkeypatch.setattr(routes.pending_mod, "propose", landmine("pending.propose"))
    monkeypatch.setattr(routes.review, "list_pending", landmine("review.list_pending"))
    monkeypatch.setattr(routes.review, "suggest_matches", landmine("review.suggest_matches"))
    monkeypatch.setattr(routes.review, "approve", landmine("review.approve"))
    monkeypatch.setattr(routes.review, "reject", landmine("review.reject"))
    monkeypatch.setattr(routes.service, "get_entity", landmine("service.get_entity"))
    return touched


# ===========================================================================
# 1. off is inert at the route, not only inside the service
# ===========================================================================

def test_off_answers_every_endpoint_without_touching_any_machinery(monkeypatch, armed):
    monkeypatch.delenv(ENV_MODE, raising=False)          # off is the deployed default
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    client = _client(OWNER)

    for name in ENDPOINTS:
        response = _call(client, name)
        assert response.status_code in (200, 201), (name, response.status_code, response.text)
        assert response.json().get("mode") == "off", name

    assert armed == [], "off reached: %s" % ", ".join(sorted(set(armed)))


def test_off_resolves_no_tenant(monkeypatch, armed):
    """D-15: the tenant is resolved server-side — and while off, not at all."""
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    resolved = []
    monkeypatch.setattr(routes, "get_tenant_context",
                        lambda *a, **kw: resolved.append(a) or None)

    assert _call(_client(OWNER), "approve").status_code == 200
    assert resolved == []
    assert armed == []


def test_an_unusable_mode_refuses_before_authorization_and_everything_else(
        monkeypatch, armed):
    monkeypatch.setenv(ENV_MODE, "offf")                 # a typo, not a mode
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    authorized = []
    monkeypatch.setattr(routes, "_authorize",
                        lambda *a, **kw: authorized.append(a) or None)

    for name in ENDPOINTS:
        response = _call(_client(DRIVER), name)
        assert response.status_code == 503, (name, response.status_code)
        assert "MASTER_DATA_MODE" in response.text

    assert authorized == [], "an unusable mode got as far as authorization"
    assert armed == []


def test_an_empty_mode_is_an_operator_mistake_not_a_default(monkeypatch, armed):
    monkeypatch.setenv(ENV_MODE, "")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    assert _call(_client(OWNER), "queue").status_code == 503
    assert armed == []


def test_off_never_consults_the_permission_service(monkeypatch, armed):
    """A switched-off feature must not read a database to say it is switched off
    — and evaluating the Permission Service is a registry lookup."""
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "enforce")
    asked = []

    def fake_require_permission(action, **kwargs):
        async def dependency(request, user):
            asked.append(action)
            return None
        return dependency

    monkeypatch.setattr(permission_deps, "require_permission", fake_require_permission)

    for name in ENDPOINTS:
        assert _call(_client(OWNER), name).status_code in (200, 201), name
    assert asked == [], "off evaluated the Permission Service"
    assert armed == []

    # Inert, and still closed: a role with no grant is refused rather than told
    # what the endpoint does.
    assert _call(_client(DRIVER), "approve").status_code == 403
    assert asked == [] and armed == []


# ===========================================================================
# 2. authorization — and it happens before any repository, tenant db or write
# ===========================================================================

def _let_the_tenant_through(monkeypatch, tenant_id="tenant-a", user_id="u-office"):
    """Disarm only the resolver, so an allowed request walks on to the service
    landmine and a test can name exactly how far it got."""
    ctx = Ctx(tenant_id, user_id=user_id)

    async def resolved(request, user):
        return ctx

    monkeypatch.setattr(routes, "get_tenant_context", resolved)
    return ctx


def test_a_role_without_the_action_is_refused_on_every_endpoint(monkeypatch, armed):
    """Armed in ENFORCE, so a refusal that reached the machinery would explode."""
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    client = _client(DRIVER)

    for name in ENDPOINTS:
        response = _call(client, name)
        assert response.status_code == 403, (name, response.status_code, response.text)
        assert "PERMISSION_DENIED" in response.text

    assert armed == [], "a forbidden request reached: %s" % ", ".join(sorted(set(armed)))


def test_a_session_without_a_role_is_refused(monkeypatch, armed):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    assert _call(_client(ROLELESS), "approve").status_code == 403
    assert armed == []


def test_a_field_role_may_propose_but_may_not_approve_or_reject(monkeypatch, armed):
    """FLOW-032 §Права: the field proposes, the office decides."""
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    client = _client(WAREHOUSE)

    for name in ("approve", "reject", "queue"):
        assert _call(client, name).status_code == 403, name
    assert armed == [], "a forbidden request reached the machinery"

    # ...and proposing is allowed: with the resolver disarmed, the request walks
    # past the guard and into the service, which is where the landmine is.
    _let_the_tenant_through(monkeypatch)
    assert _call(client, "propose").status_code == 500
    assert armed == ["pending.propose"]


def test_the_office_may_decide(monkeypatch, armed):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    _let_the_tenant_through(monkeypatch)
    client = _client(OFFICE)
    for name in ENDPOINTS:
        _call(client, name)
    # every endpoint got past the guard and reached its own service entry point
    assert set(armed) == {"pending.propose", "review.list_pending", "review.suggest_matches",
                          "review.approve", "review.reject", "service.get_entity"}


def test_the_owner_may_do_everything(monkeypatch, armed):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    _let_the_tenant_through(monkeypatch)
    client = _client(OWNER)
    for name in ENDPOINTS:
        assert _call(client, name).status_code == 500, name   # reached the landmine
    assert len(armed) == len(ENDPOINTS)


def test_in_permission_enforce_the_permission_service_decides_alone(monkeypatch, armed):
    """No second evaluator: when W0-02 enforces, the catalog check is not consulted."""
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "enforce")
    asked = []

    def fake_require_permission(action, **kwargs):
        async def dependency(request, user):
            asked.append((action, user["id"]))
            if user["id"] == "u-driver":
                raise HTTPException(status_code=403, detail="Access denied")
            return None
        return dependency

    monkeypatch.setattr(permission_deps, "require_permission", fake_require_permission)

    # A denial from the Permission Service stops the request at the guard.
    assert _call(_client(DRIVER), "approve").status_code == 403
    assert asked == [("master_data.pending.approve", "u-driver")]
    assert armed == []

    # And its ALLOW is enough on its own — this role has no catalog grant at all,
    # which is the point: in enforce the catalog does not get a second vote.
    asked.clear()
    _let_the_tenant_through(monkeypatch)
    assert _call(_client({"id": "u-x", "role": "Viewer"}), "approve").status_code == 500
    assert asked == [("master_data.pending.approve", "u-x")]
    assert armed == ["review.approve"]


def test_every_endpoint_asks_for_its_own_canonical_action(monkeypatch, armed):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "enforce")
    asked = []

    def fake_require_permission(action, **kwargs):
        async def dependency(request, user):
            asked.append(action)
            raise HTTPException(status_code=403, detail="Access denied")
        return dependency

    monkeypatch.setattr(permission_deps, "require_permission", fake_require_permission)
    client = _client(OWNER)
    for name in ENDPOINTS:
        _call(client, name)

    assert asked == ["master_data.pending.propose", "master_data.pending.read",
                     "master_data.pending.read", "master_data.pending.approve",
                     "master_data.pending.reject", "master_data.entity.read"]
    assert armed == []


def test_the_actions_are_in_the_canonical_catalog():
    """A guard that names an action the catalog does not know would be a guard
    that cannot be granted to anybody."""
    from app.permissions.catalog import ACTIONS, CANONICAL_ROLES

    for action in (routes.ACTION_PROPOSE, routes.ACTION_PENDING_READ, routes.ACTION_APPROVE,
                   routes.ACTION_REJECT, routes.ACTION_ENTITY_READ):
        assert action in ACTIONS, action
        assert action in CANONICAL_ROLES["owner"]["actions"], action
        assert action in CANONICAL_ROLES["admin"]["actions"], action

    assert routes.ACTION_APPROVE in CANONICAL_ROLES["office"]["actions"]
    assert routes.ACTION_APPROVE not in CANONICAL_ROLES["warehouse"]["actions"]
    assert CANONICAL_ROLES["driver"]["actions"] == set()


# ===========================================================================
# 3. shadow and enforce get a server-side resolved tenant, and only that
# ===========================================================================

def _resolving_client(monkeypatch, user, ctx):
    seen = {}

    async def fake_resolver(request, resolved_user):
        seen["user"] = resolved_user
        seen["query"] = dict(request.query_params)
        return ctx

    monkeypatch.setattr(routes, "get_tenant_context", fake_resolver)
    return _client(user), seen


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_shadow_and_enforce_hand_the_service_the_resolved_context(monkeypatch, mode):
    monkeypatch.setenv(ENV_MODE, mode)
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    ctx = Ctx("tenant-a", user_id="u-office")
    client, seen = _resolving_client(monkeypatch, OFFICE, ctx)

    received = {}

    async def fake_list(passed_ctx, **kwargs):
        received["ctx"] = passed_ctx
        received["mode"] = kwargs.get("mode")
        return []

    monkeypatch.setattr(routes.review, "list_pending", fake_list)

    response = client.get("/api/master-data/pending?tenant_id=tenant-b")
    assert response.status_code == 200
    assert received["ctx"] is ctx, "the handler used something other than the resolved tenant"
    assert received["mode"] == mode
    assert seen["user"]["id"] == "u-office"
    # The claimed tenant went to the W0-01 guard, which is the only thing
    # allowed to have an opinion about it; the route never reads it.
    assert seen["query"] == {"tenant_id": "tenant-b"}


def test_the_route_passes_no_tenant_of_its_own(monkeypatch):
    """The propose body carries no tenant and the route invents none."""
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    ctx = Ctx("tenant-a", user_id="u-office")
    client, _ = _resolving_client(monkeypatch, OFFICE, ctx)

    captured = {}

    async def fake_propose(passed_ctx, **kwargs):
        captured.update(kwargs)
        captured["ctx"] = passed_ctx
        raise MasterDataInvalid("stop here")

    monkeypatch.setattr(routes.pending_mod, "propose", fake_propose)

    body = dict(PROPOSE_BODY)
    body["tenant_id"] = "tenant-b"            # a client trying its luck
    assert client.post("/api/master-data/pending", json=body).status_code == 400
    assert captured["ctx"] is ctx
    assert "tenant_id" not in captured


def test_a_refusal_from_the_service_is_a_conflict_not_a_crash(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    client, _ = _resolving_client(monkeypatch, OFFICE, Ctx())

    async def refuse(*a, **kw):
        raise MasterDataRefused("already resolved")

    monkeypatch.setattr(routes.review, "approve", refuse)
    response = _call(client, "approve")
    assert response.status_code == 409 and "already resolved" in response.text


def test_a_failed_audit_is_never_reported_as_success(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")
    client, _ = _resolving_client(monkeypatch, OFFICE, Ctx())

    async def audit_failed(*a, **kw):
        raise MasterDataAuditFailed("the AuditEvent failed; the operation is NOT successful")

    monkeypatch.setattr(routes.review, "approve", audit_failed)
    response = _call(client, "approve")
    assert response.status_code == 500
    assert "NOT successful" in response.text


# ===========================================================================
# 4. a partial failure must not leave a second official record behind
# ===========================================================================

class FlakyRepo:
    """The real repository with one method rigged to fail a given number of times."""

    def __init__(self, inner, fail_method: str, times: int = 1):
        self.inner = inner
        self.fail_method = fail_method
        self.remaining = times

    def __getattr__(self, name):
        target = getattr(self.inner, name)
        if name != self.fail_method:
            return target

        async def _maybe_fail(*args, **kwargs):
            if self.remaining > 0:
                self.remaining -= 1
                raise RuntimeError("simulated storage failure in %s" % name)
            return await target(*args, **kwargs)

        return _maybe_fail


def _proposed(db, ctx, repo, raw="Баумит ЕООД", ref="ocr:inv-1"):
    return run(propose(ctx, entity_type=ORG, raw_value=raw, source_channel=SOURCE_OCR,
                       source_ref=ref, mode="enforce", repository=repo)).pending["id"]


def _actions(db):
    return [e["action"] for e in (db.audit().docs if db.audit() else [])]


def test_a_failure_between_the_record_and_the_pending_row_creates_no_second_master():
    """The exact window that makes duplicates: the Master record is written, then
    closing the pending row fails. The retry must finish the job, not repeat it."""
    db = SpyDb()
    ctx = Ctx("tenant-a", user_id="office-1", db=db)
    repo = MasterDataRepository("tenant-a", db=db)
    pending_id = _proposed(db, ctx, repo)

    flaky = FlakyRepo(repo, "finish_pending", times=1)
    with pytest.raises(RuntimeError):
        run(approve(ctx, pending_id=pending_id, confirmation=True, create_new=True,
                    display_name="Баумит България ЕООД", mode="enforce", repository=flaky))

    # The record exists — it is not deleted to compensate (FLOW-032) — and the
    # approval did NOT report success.
    assert len(db.master(ORG).docs) == 1
    assert _actions(db).count("master_data.pending.approved") == 0
    # The row went back to the queue, so a person can retry.
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING

    first_id = db.master(ORG).docs[0]["id"]
    outcome = run(approve(ctx, pending_id=pending_id, confirmation=True, create_new=True,
                          display_name="Баумит България ЕООД", mode="enforce", repository=repo))

    assert outcome.performed is True
    assert len(db.master(ORG).docs) == 1, "the retry created a second Master record"
    assert outcome.entity_id == first_id, "the retry pointed at a different record"
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_RESOLVED
    assert db[PENDING_COLLECTION].docs[0]["resolved_entity_id"] == first_id
    # The trail says what happened: created once, approved once, and the retry
    # says out loud that it reused the record.
    assert _actions(db).count("master_data.organization.created") == 1
    assert _actions(db).count("master_data.pending.approved") == 1
    assert "reused" in (outcome.reason or "")


class PausedAtTheWrite:
    """Holds one caller at the insert, after it has already looked and found
    nothing — the interleaving in which two callers would both write."""

    def __init__(self, inner):
        self.inner = inner
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.first = True

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def create(self, *args, **kwargs):
        if self.first:
            self.first = False
            self.reached.set()
            await self.release.wait()
        return await self.inner.create(*args, **kwargs)


def test_two_in_flight_approvals_by_the_same_reviewer_create_one_record():
    """A double click is two callers, not one.

    The claim must not make an exception for the reviewer who already holds it:
    there is no way to tell a request that died from one that is still working,
    so recognising the actor would put both inside the body at once — and both
    would look for the record, both would find nothing, and both would write.
    """
    async def scenario():
        db = SpyDb()
        ctx = Ctx("tenant-a", user_id="office-1", db=db)
        repo = MasterDataRepository("tenant-a", db=db)
        pending = (await propose(ctx, entity_type=ORG, raw_value="Баумит ЕООД",
                                 source_channel=SOURCE_OCR, mode="enforce",
                                 repository=repo)).pending
        paused = PausedAtTheWrite(repo)

        first = asyncio.ensure_future(approve(
            ctx, pending_id=pending["id"], confirmation=True, create_new=True,
            mode="enforce", repository=paused))
        await paused.reached.wait()          # claimed, looked, found nothing

        second = asyncio.ensure_future(approve(
            ctx, pending_id=pending["id"], confirmation=True, create_new=True,
            mode="enforce", repository=repo))
        for _ in range(50):                  # let it run as far as it can get
            await asyncio.sleep(0)
        paused.release.set()
        return db, await asyncio.gather(first, second, return_exceptions=True)

    db, outcomes = run(scenario())

    assert len(db.master(ORG).docs) == 1, "a second in-flight approval created another record"
    assert _actions(db).count("master_data.organization.created") == 1
    assert _actions(db).count("master_data.pending.approved") == 1
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_RESOLVED

    refused = [o for o in outcomes if isinstance(o, MasterDataRefused)]
    succeeded = [o for o in outcomes if not isinstance(o, Exception)]
    assert len(refused) == 1 and len(succeeded) == 1
    assert "another reviewer" in str(refused[0])


def test_an_attempt_whose_evidence_failed_keeps_the_row_and_creates_nothing_more():
    """The record was written and its creation event was not.

    The row stays claimed rather than going back to the queue, and no later
    approval — by this reviewer or any other — can act on it. Reconciling an
    unaudited record is W0-04B/W0-03E work; a retry must not paper over it by
    quietly writing the missing event and declaring success.
    """
    db = SpyDb()
    ctx = Ctx("tenant-a", user_id="office-1", db=db)
    repo = MasterDataRepository("tenant-a", db=db)
    pending_id = _proposed(db, ctx, repo)

    db["audit_events"].fail_on_insert = True
    with pytest.raises(MasterDataAuditFailed):
        run(approve(ctx, pending_id=pending_id, confirmation=True, create_new=True,
                    mode="enforce", repository=repo))
    db["audit_events"].fail_on_insert = False

    assert len(db.master(ORG).docs) == 1
    assert _actions(db).count("master_data.organization.created") == 0
    row = db[PENDING_COLLECTION].docs[0]
    assert row["status"] == STATUS_RESOLVING and row["claimed_by"] == "office-1"

    for reviewer in (ctx, Ctx("tenant-a", user_id="office-2", db=db)):
        with pytest.raises(MasterDataRefused):
            run(approve(reviewer, pending_id=pending_id, confirmation=True, create_new=True,
                        mode="enforce", repository=repo))

    assert len(db.master(ORG).docs) == 1, "a refused approval still wrote something"
    assert _actions(db).count("master_data.pending.approved") == 0


def test_only_the_holder_of_a_claim_can_release_or_close_it():
    """Defence in depth around the one door: the claim decides who may act."""
    db = SpyDb()
    ctx = Ctx("tenant-a", user_id="office-1", db=db)
    repo = MasterDataRepository("tenant-a", db=db)
    pending_id = _proposed(db, ctx, repo)
    run(repo.claim_pending(pending_id, actor_id="office-1", now="t1"))

    assert run(repo.finish_pending(pending_id, entity_id="e-1",
                                   actor_id="office-2", now="t2")) is False
    run(repo.release_pending(pending_id, actor_id="office-2", now="t2"))
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_RESOLVING

    run(repo.release_pending(pending_id, actor_id="office-1", now="t3"))
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING


def test_the_identifier_of_a_retried_approval_is_derived_not_invented():
    same = models.derived_entity_id("tenant-a", "pending-1")
    assert same == models.derived_entity_id("tenant-a", "pending-1")
    assert same != models.derived_entity_id("tenant-b", "pending-1")
    assert same != models.derived_entity_id("tenant-a", "pending-2")
    for bad in ("", None):
        with pytest.raises(MasterDataInvalid):
            models.derived_entity_id(bad, "pending-1")
        with pytest.raises(MasterDataInvalid):
            models.derived_entity_id("tenant-a", bad)


def test_a_retried_mapping_leaves_one_alias_not_two():
    """The same window on the other branch: the alias was added and the pending
    row was not closed. Adding it again must be a no-op, not a second entry."""
    db = SpyDb()
    ctx = Ctx("tenant-a", user_id="office-1", db=db)
    repo = MasterDataRepository("tenant-a", db=db)

    first = _proposed(db, ctx, repo, raw="Баумит ЕООД", ref="ocr:inv-1")
    created = run(approve(ctx, pending_id=first, confirmation=True, create_new=True,
                          display_name="Баумит България ЕООД", mode="enforce", repository=repo))

    second = _proposed(db, ctx, repo, raw="БАУМИТ Е.О.О.Д.", ref="ocr:inv-2")
    flaky = FlakyRepo(repo, "finish_pending", times=1)
    with pytest.raises(RuntimeError):
        run(approve(ctx, pending_id=second, confirmation=True,
                    canonical_entity_id=created.entity_id, mode="enforce", repository=flaky))

    record = db.master(ORG).docs[0]
    assert len(record["aliases"]) == 1

    run(approve(ctx, pending_id=second, confirmation=True,
                canonical_entity_id=created.entity_id, mode="enforce", repository=repo))
    assert len(db.master(ORG).docs[0]["aliases"]) == 1, "the retry added the alias twice"
    assert len(db.master(ORG).docs) == 1


# --- the alias primitive itself --------------------------------------------

def _record(db, name="Баумит България ЕООД"):
    repo = MasterDataRepository("tenant-a", db=db)
    entity = models.build_entity(tenant_id="tenant-a", entity_type=ORG, display_name=name)
    run(repo.create(entity))
    return repo, entity


def test_adding_the_same_alias_twice_leaves_one_entry():
    db = SpyDb()
    repo, entity = _record(db)
    alias = models.new_alias("БАУМИТ Е.О.О.Д.", added_by="office-1")

    assert run(repo.add_alias(ORG, entity["id"], alias, "t1")) is True
    assert run(repo.add_alias(ORG, entity["id"], alias, "t2")) is True, \
        "an alias that is already there is the end state the caller asked for"
    assert len(db.master(ORG).docs[0]["aliases"]) == 1


def test_a_different_spelling_of_the_same_alias_is_also_the_same_alias():
    """Idempotency is by the normalized form, which is the thing that matches."""
    db = SpyDb()
    repo, entity = _record(db)
    run(repo.add_alias(ORG, entity["id"], models.new_alias("БАУМИТ Е.О.О.Д.", "office-1"), "t1"))
    run(repo.add_alias(ORG, entity["id"], models.new_alias("баумит еоод", "office-2"), "t2"))
    aliases = db.master(ORG).docs[0]["aliases"]
    assert len(aliases) == 1 and aliases[0]["added_by"] == "office-1"


def test_two_genuinely_different_aliases_both_land():
    db = SpyDb()
    repo, entity = _record(db)
    run(repo.add_alias(ORG, entity["id"], models.new_alias("Баумит", "office-1"), "t1"))
    run(repo.add_alias(ORG, entity["id"], models.new_alias("Baumit Bulgaria", "office-1"), "t2"))
    assert len(db.master(ORG).docs[0]["aliases"]) == 2


def test_an_alias_for_a_record_that_is_not_in_this_tenant_fails():
    db = SpyDb()
    repo, _ = _record(db)
    alias = models.new_alias("Баумит", added_by="office-1")
    assert run(repo.add_alias(ORG, "no-such-record", alias, "t1")) is False


def test_an_alias_without_its_normalized_form_is_refused():
    db = SpyDb()
    repo, entity = _record(db)
    with pytest.raises(MasterDataInvalid):
        run(repo.add_alias(ORG, entity["id"], {"value": "Баумит"}, "t1"))
