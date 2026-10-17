"""
R0-01 — Billing P0: signed webhook + no mock in production (AUD-009, AUD-045).

The 11 cases of docs/architecture/tasks/R0-01_BILLING_P0.md, positive and
forbidden, plus three supporting proofs (unknown checkout session, Stripe mode
only records the session, honest /billing/config).

R0-01-C01 adds the Codex corrections F-01..F-06 (tests 14-19).

Every scenario runs in-process against ``mongomock_motor`` and, when
``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB (a replica set for the
lease/unique-index cases), again against it — each test on its own database,
dropped afterwards. No server, no network. Webhook signatures are REAL Stripe v1 signatures computed here with a
test-only secret and verified by the real ``stripe.Webhook.construct_event``.
Every "nothing was written" claim is a byte-level comparison of the whole
billing state (``subscriptions``, ``feature_flags``, ``billing_webhook_events``,
``billing_checkout_sessions``, ``audit_logs``) before and after.

    pytest tests/test_r0_01_billing_p0.py -v --noconftest
    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27018 pytest tests/test_r0_01_billing_p0.py -v --noconftest
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
import types
import uuid

import pytest

#: Test-only signing secret. Not a credential; never used outside this file.
SECRET = "whsec_r0_01_test_only_not_a_real_secret"
OTHER_SECRET = "whsec_r0_01_some_other_test_secret"

ORG_A, ORG_B = "ORG-A", "ORG-B"
CUS_A, CUS_B = "cus_A_r001", "cus_B_r001"
SUB_B = "sub_B_r001"
CS_A = "cs_A_r001"

BILLING_STATE = ("subscriptions", "feature_flags", "billing_webhook_events",
                 "billing_checkout_sessions", "audit_logs")

#: Marker for "leave this key out of the Stripe object".
OMIT = object()


def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    """``mongomock`` always; ``real`` when W0_03_REAL_MONGO_URL is a local MongoDB."""
    return request.param


# ═══════════════════════════════════════════════════════════════════ helpers
def _sign(payload: bytes, secret: str = SECRET) -> str:
    ts = int(time.time())
    mac = hmac.new(secret.encode(), b"%d." % ts + payload, hashlib.sha256).hexdigest()
    return "t=%d,v1=%s" % (ts, mac)


def _event(event_id, event_type, obj) -> bytes:
    return json.dumps({"id": event_id, "object": "event", "type": event_type,
                       "data": {"object": obj}}).encode()


def _checkout_completed(event_id="evt_cs_A_1", session_id=CS_A, customer=CUS_A,
                        org_id=ORG_A, plan_id="pro", subscription="sub_A_new",
                        payment_status="paid", mode="subscription"):
    obj = {"id": session_id, "object": "checkout.session", "customer": customer,
           "subscription": subscription, "payment_status": payment_status, "mode": mode,
           "metadata": {"org_id": org_id, "plan_id": plan_id}}
    for key in ("subscription", "payment_status", "mode"):
        if obj[key] is OMIT:
            del obj[key]
    if obj["metadata"]["plan_id"] is OMIT:
        del obj["metadata"]["plan_id"]
    return _event(event_id, "checkout.session.completed", obj)


async def _seed(op):
    from app.constants import MODULES
    from app.deps.modules import SUBSCRIPTION_PLANS
    free = SUBSCRIPTION_PLANS["free"]["allowed_modules"]
    for org, cus, sub_id in ((ORG_A, CUS_A, None), (ORG_B, CUS_B, SUB_B)):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
        await op.subscriptions.insert_one({
            "id": "sub-row-" + org, "org_id": org, "plan_id": "free", "status": "trialing",
            "stripe_customer_id": cus, "stripe_subscription_id": sub_id,
            "trial_ends_at": "2099-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00"})
        for code in MODULES:
            await op.feature_flags.insert_one({"id": "ff-%s-%s" % (org, code), "org_id": org,
                                               "module_code": code, "enabled": code in free})
    for uid, org, role in (("owner-a", ORG_A, "Owner"), ("admin-a", ORG_A, "Admin"),
                           ("viewer-a", ORG_A, "Viewer"), ("tech-a", ORG_A, "Technician"),
                           ("owner-b", ORG_B, "Owner")):
        await op.users.insert_one({"id": uid, "org_id": org, "role": role, "is_active": True,
                                   "email": uid + "@r001.test", "first_name": uid})
    # The BEG_Work-side record a real checkout writes (tenant A bought "pro").
    await op.billing_checkout_sessions.insert_one({
        "id": "bcs-1", "org_id": ORG_A, "stripe_session_id": CS_A,
        "stripe_customer_id": CUS_A, "plan_id": "pro", "status": "open"})


async def _state(op, collections=BILLING_STATE):
    """A byte-level snapshot of the billing state."""
    import bson
    out = {}
    for name in collections:
        docs = await op[name].find({}).to_list(None)
        out[name] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d) if k != "_id"})
                           for d in docs)
    return out


def _token(user_id, org_id, role):
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token(
        {"user_id": user_id, "org_id": org_id, "role": role})}


def _clean_env(monkeypatch):
    for name in ("STRIPE_WEBHOOK_SECRET", "BILLING_PROVIDER", "ENV", "STRIPE_API_KEY",
                 "STRIPE_PRICE_ID_PRO", "STRIPE_PRICE_ID_ENTERPRISE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")


def _app(monkeypatch, op):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.routes import billing
    from app.utils import audit as utils_audit
    for module in (appdb, deps_auth, billing, utils_audit):
        monkeypatch.setattr(module, "db", op)
    app = FastAPI()
    app.include_router(billing.router, prefix="/api")
    return app


class _Db:
    """A fresh, empty database on the chosen backend; a real one is dropped on exit."""

    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, "r0_01_" + uuid.uuid4().hex[:10]

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.name]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            await self.client.drop_database(self.name)
            assert self.name not in await self.client.list_database_names()
            self.client.close()


def run(monkeypatch, scenario, backend="mongomock"):
    """Fresh seeded database + in-process client; ``scenario(c, op)``."""
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r001") as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def _post_event(c, payload, secret=SECRET, signature=None):
    sig = signature if signature is not None else _sign(payload, secret)
    headers = {"content-type": "application/json"}
    if sig:
        headers["stripe-signature"] = sig
    return await c.post("/api/billing/webhook", content=payload, headers=headers)


def _security_events(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name == "security" and "BILLING_WEBHOOK_REJECTED" in r.getMessage()]


# ═══════════════════════════════════════════════════════════════════ 1
def test_01_webhook_without_secret_is_503_and_writes_nothing(monkeypatch, backend):
    _clean_env(monkeypatch)                       # STRIPE_WEBHOOK_SECRET absent

    async def scenario(c, op):
        before = await _state(op)
        r = await _post_event(c, _checkout_completed())
        assert r.status_code == 503, r.text
        # the old "development mode" json.loads fallback is gone: unsigned too
        r2 = await _post_event(c, _checkout_completed(), signature="")
        assert r2.status_code == 503, r2.text
        assert await _state(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 2
def test_02_webhook_with_wrong_signature_is_400_and_writes_nothing(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        before = await _state(op)
        payload = _checkout_completed()
        for sig in (_sign(payload, OTHER_SECRET),          # signed with another secret
                    "",                                      # no signature header at all
                    "t=1,v1=deadbeef"):                      # garbage signature
            r = await _post_event(c, payload, signature=sig)
            assert r.status_code == 400, (sig, r.status_code, r.text)
        # a valid signature over DIFFERENT bytes does not cover a tampered body
        tampered = _checkout_completed(plan_id="enterprise")
        r = await _post_event(c, tampered, signature=_sign(payload))
        assert r.status_code == 400, r.text
        assert await _state(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 3
def test_03_valid_signed_checkout_completed_writes_once_for_the_right_tenant(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        from app.deps.modules import SUBSCRIPTION_PLANS
        b_before = await _state_of(op, ORG_B)
        r = await _post_event(c, _checkout_completed())
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "received"}

        sub = await op.subscriptions.find_one({"org_id": ORG_A})
        assert sub["plan_id"] == "pro" and sub["status"] == "active"
        assert sub["stripe_subscription_id"] == "sub_A_new"
        assert sub["stripe_customer_id"] == CUS_A and sub["trial_ends_at"] is None
        pro = set(SUBSCRIPTION_PLANS["pro"]["allowed_modules"])
        async for flag in op.feature_flags.find({"org_id": ORG_A}):
            assert flag["enabled"] == (flag["module_code"] in pro), flag
        events = await op.billing_webhook_events.find({}).to_list(None)
        assert len(events) == 1
        assert events[0]["org_id"] == ORG_A and events[0]["stripe_event_id"] == "evt_cs_A_1"
        assert events[0]["status"] == "processed"
        rec = await op.billing_checkout_sessions.find_one({"stripe_session_id": CS_A})
        assert rec["status"] == "completed"
        # tenant B is byte-equal
        assert await _state_of(op, ORG_B) == b_before
    run(monkeypatch, scenario, backend)


async def _state_of(op, org):
    import bson
    out = {}
    for name in BILLING_STATE:
        docs = await op[name].find({"org_id": org}).to_list(None)
        out[name] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d) if k != "_id"})
                           for d in docs)
    return out


# ═══════════════════════════════════════════════════════════════════ 4
def test_04_the_same_event_again_is_200_without_a_second_change(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        payload = _checkout_completed()
        r1 = await _post_event(c, payload)
        assert r1.status_code == 200 and r1.json()["status"] == "received", r1.text
        # Change the state after the first delivery: a re-application would undo it.
        await op.subscriptions.update_one({"org_id": ORG_A}, {"$set": {"status": "past_due"}})
        after_first = await _state(op)

        r2 = await _post_event(c, payload)                  # identical replay
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"status": "duplicate"}
        assert await _state(op) == after_first
        assert (await op.subscriptions.find_one({"org_id": ORG_A}))["status"] == "past_due"
        assert await op.billing_webhook_events.count_documents({}) == 1

        # The unique index is what decides: a raw duplicate insert is refused.
        from pymongo.errors import DuplicateKeyError
        with pytest.raises(DuplicateKeyError):
            await op.billing_webhook_events.insert_one(
                {"org_id": ORG_A, "stripe_event_id": "evt_cs_A_1"})
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 5
def test_05_metadata_org_id_of_another_tenant_writes_nothing_and_is_security_logged(
        monkeypatch, backend, caplog):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        before = await _state(op)
        with caplog.at_level(logging.WARNING, logger="security"):
            # A's real checkout session, but the event claims tenant B
            r = await _post_event(c, _checkout_completed(org_id=ORG_B))
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "rejected", "reason_class": "mismatch"}
        assert await _state(op) == before
        rows = await op.billing_webhook_rejections.find({}, {"_id": 0}).to_list(None)
        assert [(x["stripe_event_id"], x["reason_class"]) for x in rows] == [
            ("evt_cs_A_1", "mismatch")]
        assert rows[0]["local_org_id"] == ORG_A          # from the local record, not metadata
        logged = _security_events(caplog)
        assert len(logged) == 1, logged
        assert "metadata.org_id does not match" in logged[0]
        assert ORG_A in logged[0] and "evt_cs_A_1" in logged[0]
        assert SECRET not in caplog.text and CUS_A not in logged[0]   # ids/reason only

        # and B's own customer on A's session is refused the same way
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="security"):
            r = await _post_event(c, _checkout_completed(event_id="evt_x2", customer=CUS_B))
        assert r.json() == {"status": "rejected", "reason_class": "mismatch"}
        assert "customer does not match" in _security_events(caplog)[0]
        assert await _state(op) == before
    run(monkeypatch, scenario, backend)


def test_05b_unknown_checkout_session_resolves_no_tenant_even_with_valid_metadata(
        monkeypatch, backend, caplog):
    """metadata.org_id alone never selects a tenant."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        before = await _state(op)
        with caplog.at_level(logging.WARNING, logger="security"):
            r = await _post_event(c, _checkout_completed(
                event_id="evt_unknown", session_id="cs_never_created_by_beg"))
        assert r.status_code == 503, r.text                      # R0-01-C01: Stripe retries
        assert "no BEG_Work checkout record" in _security_events(caplog)[0]
        row = await op.billing_webhook_rejections.find_one({"stripe_event_id": "evt_unknown"})
        assert row["reason_class"] == "unresolved" and row["local_org_id"] is None
        assert await _state(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 6
def test_06_subscription_deleted_for_a_foreign_customer_writes_nothing(monkeypatch, backend, caplog):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        before = await _state(op)
        a_before = await _state_of(op, ORG_A)
        with caplog.at_level(logging.WARNING, logger="security"):
            for i, customer in enumerate((CUS_A, "cus_unknown", None)):
                obj = {"id": SUB_B, "object": "subscription", "status": "canceled"}
                if customer:
                    obj["customer"] = customer
                r = await _post_event(c, _event("evt_del_%d" % i,
                                                "customer.subscription.deleted", obj))
                assert r.status_code == 200, r.text
                assert r.json() == {"status": "rejected", "reason_class": "mismatch"}
        assert await _state(op) == before
        assert len(_security_events(caplog)) == 3

        # Positive control: B's own customer DOES cancel B — so the test can see a write.
        r = await _post_event(c, _event("evt_del_ok", "customer.subscription.deleted",
                                        {"id": SUB_B, "object": "subscription",
                                         "customer": CUS_B}))
        assert r.json() == {"status": "received"}, r.text
        sub_b = await op.subscriptions.find_one({"org_id": ORG_B})
        assert sub_b["plan_id"] == "free" and sub_b["status"] == "canceled"
        assert await _state_of(op, ORG_A) == a_before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 7
@pytest.mark.parametrize("user_id,role", [("viewer-a", "Viewer"), ("tech-a", "Technician")])
def test_07_checkout_and_portal_as_viewer_or_technician_is_403(monkeypatch, backend, user_id, role):
    _clean_env(monkeypatch)
    # mock IS allowed here, so the refusal can only come from the role
    monkeypatch.setenv("BILLING_PROVIDER", "mock")
    monkeypatch.setenv("ENV", "test")

    async def scenario(c, op):
        before = await _state(op)
        h = _token(user_id, ORG_A, role)
        r = await c.post("/api/billing/create-checkout-session", headers=h,
                         json={"plan_id": "pro", "origin_url": "https://x.test"})
        assert r.status_code == 403, r.text
        r = await c.post("/api/billing/create-portal-session", headers=h)
        assert r.status_code == 403, r.text
        assert await _state(op) == before
        # control: the Admin of the same tenant passes the same gate
        r = await c.post("/api/billing/create-checkout-session",
                         headers=_token("admin-a", ORG_A, "Admin"),
                         json={"plan_id": "pro", "origin_url": "https://x.test"})
        assert r.status_code == 200, r.text
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 8
def test_08_owner_checkout_with_mock_in_production_is_503_and_plan_unchanged(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("BILLING_PROVIDER", "mock")
    monkeypatch.setenv("ENV", "production")       # and no Stripe keys

    async def scenario(c, op):
        before = await _state(op)
        h = _token("owner-a", ORG_A, "Owner")
        r = await c.post("/api/billing/create-checkout-session", headers=h,
                         json={"plan_id": "enterprise", "origin_url": "https://x.test"})
        assert r.status_code == 503, r.text
        assert "not configured" in r.json()["detail"]
        r = await c.post("/api/billing/create-portal-session", headers=h)
        assert r.status_code == 503, r.text
        assert await _state(op) == before
        sub = await op.subscriptions.find_one({"org_id": ORG_A})
        assert sub["plan_id"] == "free" and sub["status"] == "trialing"
        assert await op.audit_logs.count_documents({"action": "checkout_mock"}) == 0
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 9
@pytest.mark.parametrize("env", ["test", "development"])
def test_09_checkout_with_mock_provider_in_test_env_works_as_before(monkeypatch, backend, env):
    _clean_env(monkeypatch)
    monkeypatch.setenv("BILLING_PROVIDER", "mock")
    monkeypatch.setenv("ENV", env)

    async def scenario(c, op):
        from app.deps.modules import SUBSCRIPTION_PLANS
        b_before = await _state_of(op, ORG_B)
        r = await c.post("/api/billing/create-checkout-session",
                         headers=_token("owner-a", ORG_A, "Owner"),
                         json={"plan_id": "enterprise", "origin_url": "https://x.test"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mock_mode"] is True and data["session_id"].startswith("mock_cs_")
        sub = await op.subscriptions.find_one({"org_id": ORG_A})
        assert sub["plan_id"] == "enterprise" and sub["status"] == "active"
        assert sub["stripe_subscription_id"].startswith("mock_sub_")
        ent = set(SUBSCRIPTION_PLANS["enterprise"]["allowed_modules"])
        async for flag in op.feature_flags.find({"org_id": ORG_A}):
            assert flag["enabled"] == (flag["module_code"] in ent), flag
        assert await op.audit_logs.count_documents(
            {"org_id": ORG_A, "action": "checkout_mock"}) == 1
        assert await _state_of(op, ORG_B) == b_before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 10
@pytest.mark.parametrize("env", [None, "", "staging", "prod", "Production"])
def test_10_mock_without_an_explicit_dev_or_test_env_is_forbidden(monkeypatch, backend, env):
    _clean_env(monkeypatch)
    monkeypatch.setenv("BILLING_PROVIDER", "mock")
    if env is not None:
        monkeypatch.setenv("ENV", env)

    from app.core import stripe_config
    assert stripe_config.is_mock_billing_allowed() is False
    assert stripe_config.billing_mode() == stripe_config.BILLING_MODE_UNCONFIGURED

    async def scenario(c, op):
        before = await _state(op)
        r = await c.post("/api/billing/create-checkout-session",
                         headers=_token("owner-a", ORG_A, "Owner"),
                         json={"plan_id": "pro", "origin_url": "https://x.test"})
        assert r.status_code == 503, r.text
        assert await _state(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 11
def test_11_exposure_report_is_read_only(monkeypatch, backend):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import r0_01_billing_exposure_report as report

    async def scenario(db):
        await db.subscriptions.insert_many([
            {"org_id": "M", "plan_id": "enterprise", "status": "active",
             "stripe_customer_id": "mock_cus_M", "stripe_subscription_id": "mock_sub_1234"},
            {"org_id": "P", "plan_id": "pro", "status": "active",
             "stripe_customer_id": "cus_P", "stripe_subscription_id": "sub_P"},
            {"org_id": "S", "plan_id": "pro", "status": "active",
             "stripe_customer_id": "cus_S", "stripe_subscription_id": "sub_S"},
            {"org_id": "F", "plan_id": "free", "status": "trialing"}])
        await db.audit_logs.insert_many([
            {"org_id": "M", "user_id": "u1", "user_email": "secret.person@x.test",
             "action": "checkout_mock", "entity_id": "mock_cs_1",
             "changes": {"plan_id": "enterprise"}, "timestamp": "2026-05-01"},
            {"org_id": "S", "action": "checkout_started", "entity_id": "cs_S"}])

        async def everything():
            out = {}
            for name in sorted(await db.list_collection_names()):
                out[name] = await db[name].find({}, {"_id": 0}).to_list(None)
            return out

        before = await everything()
        rep = await report.build_report(db)
        assert await everything() == before            # nothing written, nothing created
        assert rep["read_only"] is True and rep["dry_run"] is True
        assert rep["counts"] == {"mock_subscriptions": 1, "checkout_mock_audit": 1,
                                 "unverified_paid_plan_candidates": 1}
        assert rep["mock_subscriptions"][0]["org_id"] == "M"
        assert rep["checkout_mock_audit"][0]["session_id"] == "mock_cs_1"
        assert rep["unverified_paid_plan_candidates"][0]["org_id"] == "P"
        assert "secret.person@x.test" not in json.dumps(rep, default=str)

        ro = report.ReadOnlyDb(db)
        for method in ("insert_one", "update_one", "delete_many", "create_index", "drop"):
            with pytest.raises(PermissionError):
                getattr(ro["subscriptions"], method)

    async def body():
        async with _Db(backend) as db:
            await scenario(db)
    asyncio.run(body())

    # a non-local target is refused before any connection without --allow-remote
    assert report.main(["--db", "x", "--mongo-url", "mongodb+srv://example.invalid"]) == 2
    monkeypatch.delenv("MONGO_URL", raising=False)
    assert report.main(["--db", "x"]) == 2


# ═══════════════════════════════════════════════════════════════════ supporting
def test_12_stripe_mode_checkout_records_the_session_and_does_not_change_the_plan(monkeypatch, backend):
    """Outside mock, checkout only creates a session; the plan waits for the webhook."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_r001_fake")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_pro_fake")
    monkeypatch.setenv("STRIPE_PRICE_ID_ENTERPRISE", "price_ent_fake")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    import stripe
    from app.deps import modules as deps_modules
    calls = {}

    def fake_session_create(**kw):
        calls["session"] = kw
        return types.SimpleNamespace(id="cs_new_r001", url="https://checkout.stripe.test/x")
    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(fake_session_create))
    monkeypatch.setattr(stripe.Customer, "create",
                        staticmethod(lambda **kw: pytest.fail("customer exists already")))
    monkeypatch.setitem(deps_modules.SUBSCRIPTION_PLANS["pro"], "stripe_price_id", "price_pro_fake")

    async def scenario(c, op):
        r = await c.post("/api/billing/create-checkout-session",
                         headers=_token("owner-a", ORG_A, "Owner"),
                         json={"plan_id": "pro", "origin_url": "https://x.test"})
        assert r.status_code == 200, r.text
        assert r.json()["mock_mode"] is False and r.json()["session_id"] == "cs_new_r001"
        assert calls["session"]["customer"] == CUS_A
        sub = await op.subscriptions.find_one({"org_id": ORG_A})
        assert sub["plan_id"] == "free" and sub["status"] == "trialing"   # unchanged
        rec = await op.billing_checkout_sessions.find_one({"stripe_session_id": "cs_new_r001"})
        assert rec["org_id"] == ORG_A and rec["stripe_customer_id"] == CUS_A
        assert rec["plan_id"] == "pro" and rec["status"] == "open"

        # ...and the signed webhook for THAT session activates it
        r = await _post_event(c, _checkout_completed(event_id="evt_new", session_id="cs_new_r001"))
        assert r.json() == {"status": "received"}, r.text
        assert (await op.subscriptions.find_one({"org_id": ORG_A}))["plan_id"] == "pro"
    run(monkeypatch, scenario, backend)


def test_13_billing_config_reports_unconfigured_honestly(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("BILLING_PROVIDER", "mock")
    monkeypatch.setenv("ENV", "production")

    async def scenario(c, op):
        await op.users.update_one({"id": "owner-a"}, {"$set": {"is_platform_admin": True}})
        r = await c.get("/api/billing/config", headers=_token("owner-a", ORG_A, "Owner"))
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert cfg["billing_mode"] == "unconfigured"
        assert cfg["billing_configured"] is False
        assert cfg["stripe_mock_mode"] is False and cfg["stripe_configured"] is False
        r = await c.get("/api/billing/config", headers=_token("admin-a", ORG_A, "Admin"))
        assert r.status_code == 403
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════ R0-01-C01 (Codex F-01..F-06)
#: Fields a rejection row may carry (F-04): ids, class, reason, counters, times.
REJECTION_FIELDS = {"id", "stripe_event_id", "event_type", "reason_class", "reason",
                    "stripe_object_id", "local_org_id", "received_at", "last_received_at",
                    "attempts", "resolved_at", "resolved_org_id"}


async def _rejections(op):
    return await op.billing_webhook_rejections.find({}, {"_id": 0}).to_list(None)


@pytest.mark.parametrize("variant,kw,reason_class", [
    ("unpaid", {"payment_status": "unpaid"}, "not_paid"),
    ("no_payment_required", {"payment_status": "no_payment_required"}, "not_paid"),
    ("no_payment_status", {"payment_status": OMIT}, "malformed"),
    ("mode_payment", {"mode": "payment"}, "malformed"),
    ("no_mode", {"mode": OMIT}, "malformed"),
    ("empty_subscription", {"subscription": ""}, "malformed"),
    ("no_subscription", {"subscription": OMIT}, "malformed"),
])
def test_14_F01_only_a_paid_subscription_checkout_activates(monkeypatch, backend, variant, kw,
                                                            reason_class):
    """F-01: anything but payment_status=paid + mode=subscription + a subscription id
    changes no plan and no flag, is recorded once, and is acknowledged (200)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        before = await _state(op)
        payload = _checkout_completed(event_id="evt_f01_" + variant, **kw)
        for attempt in (1, 2):                                    # + a redelivery
            r = await _post_event(c, payload)
            assert r.status_code == 200, (attempt, r.text)
            assert r.json() == {"status": "rejected", "reason_class": reason_class}
        assert await _state(op) == before                         # no plan, no flag, no claim
        rows = await _rejections(op)
        assert len(rows) == 1, rows
        assert rows[0]["reason_class"] == reason_class and rows[0]["attempts"] == 2
        assert rows[0]["stripe_object_id"] == CS_A
        assert set(rows[0]) <= REJECTION_FIELDS, set(rows[0]) - REJECTION_FIELDS
    run(monkeypatch, scenario, backend)


@pytest.mark.parametrize("plan_id", [OMIT, "", "enterprise"])
def test_15_F05_metadata_plan_id_is_required_and_exact(monkeypatch, backend, plan_id):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        before = await _state(op)
        r = await _post_event(c, _checkout_completed(plan_id=plan_id))
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "rejected", "reason_class": "mismatch"}
        assert await _state(op) == before
        rows = await _rejections(op)
        assert len(rows) == 1 and "metadata.plan_id" in rows[0]["reason"], rows
        # control: the exact local plan activates (test_03 shows the full effect)
        r = await _post_event(c, _checkout_completed(event_id="evt_f05_ok"))
        assert r.json() == {"status": "received"}, r.text
        assert (await op.subscriptions.find_one({"org_id": ORG_A}))["plan_id"] == "pro"
    run(monkeypatch, scenario, backend)


def test_16_F03_unknown_session_is_503_recorded_and_activates_once_when_resolvable(
        monkeypatch, backend):
    """F-03 (bounded): no metadata fallback, no Stripe backfill. An unknown session
    is refused with 503 so Stripe retries; once BEG_Work holds the local record, the
    retried delivery activates the plan exactly once."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        before = await _state(op)
        payload = _checkout_completed(event_id="evt_cutover", session_id="cs_pre_deploy")
        for _ in (1, 2):
            r = await _post_event(c, payload)
            assert r.status_code == 503, r.text
        assert await _state(op) == before
        rows = await _rejections(op)
        assert len(rows) == 1 and rows[0]["reason_class"] == "unresolved", rows
        assert rows[0]["attempts"] == 2 and rows[0].get("resolved_at") is None

        # an operator restores the local record (manual reconciliation)
        await op.billing_checkout_sessions.insert_one({
            "id": "bcs-cut", "org_id": ORG_A, "stripe_session_id": "cs_pre_deploy",
            "stripe_customer_id": CUS_A, "plan_id": "pro", "status": "open"})
        r = await _post_event(c, payload)                         # Stripe's next retry
        assert r.json() == {"status": "received"}, r.text
        sub = await op.subscriptions.find_one({"org_id": ORG_A})
        assert sub["plan_id"] == "pro" and sub["status"] == "active"
        row = (await _rejections(op))[0]
        assert row["resolved_at"] is not None and row["resolved_org_id"] == ORG_A
        r = await _post_event(c, payload)                         # and never twice
        assert r.json() == {"status": "duplicate"}, r.text
        assert await op.billing_webhook_events.count_documents({}) == 1
    run(monkeypatch, scenario, backend)


def test_17_F04_each_class_has_its_status_and_one_sanitized_system_record(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    cases = [
        # (event, expected status, expected class)
        (_event("evt_c_unres", "customer.subscription.updated",
                {"id": "sub_nobody", "customer": CUS_A, "status": "active"}), 503, "unresolved"),
        (_event("evt_c_mis", "invoice.payment_failed",
                {"id": "in_1", "subscription": SUB_B, "customer": CUS_A,
                 "customer_email": "victim@r001.test", "amount_due": 9999}), 200, "mismatch"),
        (_checkout_completed(event_id="evt_c_np", payment_status="unpaid"), 200, "not_paid"),
        (_event("evt_c_mal", "invoice.payment_succeeded",
                {"id": "in_2", "customer": CUS_B}), 200, "malformed"),
    ]

    async def scenario(c, op):
        before = await _state(op)
        for payload, status, cls in cases:
            for _ in (1, 2):
                r = await _post_event(c, payload)
                assert r.status_code == status, (cls, r.status_code, r.text)
        assert await _state(op) == before                         # no tenant collection touched
        rows = {x["stripe_event_id"]: x for x in await _rejections(op)}
        assert {k: v["reason_class"] for k, v in rows.items()} == {
            "evt_c_unres": "unresolved", "evt_c_mis": "mismatch",
            "evt_c_np": "not_paid", "evt_c_mal": "malformed"}
        for row in rows.values():
            assert row["attempts"] == 2, row
            assert set(row) <= REJECTION_FIELDS, set(row) - REJECTION_FIELDS
            assert "org_id" not in row                            # owned by no tenant
        dumped = json.dumps(list(rows.values()), default=str)
        assert "victim@r001.test" not in dumped and "9999" not in dumped
        assert rows["evt_c_mis"]["local_org_id"] == ORG_B         # the local owner of SUB_B
        idx = await op.billing_webhook_rejections.index_information()
        assert any(v.get("unique") and v["key"] == [("stripe_event_id", 1)]
                   for v in idx.values()), idx

        from app.tenancy import ownership
        assert ownership.classify_collection("billing_webhook_rejections") == ownership.CLASS_TECHNICAL
        assert ownership.tenant_key_of("billing_webhook_rejections") is None
    run(monkeypatch, scenario, backend)


def test_18_F02_lease_claim_crash_reclaim_and_token_fenced_finish(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    async def scenario(c, op):
        from datetime import timedelta
        from app.routes import billing
        from app.tenancy.data_access import TenantData
        a = TenantData.for_resolved_org(op, ORG_A)
        ev = op.billing_webhook_events

        # 1. two live concurrent claims -> exactly one owner
        tokens = await asyncio.gather(*(billing._claim_event(a, "evt_lease", "t") for _ in range(4)))
        owners = [t for t in tokens if t]
        assert len(owners) == 1, tokens
        assert await ev.count_documents({"stripe_event_id": "evt_lease"}) == 1
        first = owners[0]

        # 2. "crash": no finish. A delivery inside the lease is a duplicate.
        assert await billing._claim_event(a, "evt_lease", "t") is None

        # 3. lease expired -> atomically re-claimed with a NEW token, attempts + 1
        await ev.update_one({"stripe_event_id": "evt_lease"}, {"$set": {
            "processing_started_at": billing._utcnow() - timedelta(seconds=301)}})
        second = await billing._claim_event(a, "evt_lease", "t")
        assert second and second != first
        row = await ev.find_one({"stripe_event_id": "evt_lease"})
        assert row["attempts"] == 2 and row["attempt_token"] == second
        assert row["status"] == "processing"

        # 4. the stale attempt can no longer write the final state
        assert await billing._finish_event(a, "evt_lease", first, {"status": "processed"}) is False
        assert (await ev.find_one({"stripe_event_id": "evt_lease"}))["status"] == "processing"
        assert await billing._finish_event(a, "evt_lease", second, {"status": "failed"}) is True

        # 5. failed -> retry re-claims at once
        third = await billing._claim_event(a, "evt_lease", "t")
        assert third and third not in (first, second)
        assert await billing._finish_event(a, "evt_lease", third, {"status": "processed"})
        # 6. processed is final, even with an expired lease
        await ev.update_one({"stripe_event_id": "evt_lease"}, {"$set": {
            "processing_started_at": billing._utcnow() - timedelta(days=1)}})
        assert await billing._claim_event(a, "evt_lease", "t") is None

        # 7. end to end: a crashed checkout delivery is applied once after the lease
        payload = _checkout_completed(event_id="evt_crash")
        await billing._claim_event(a, "evt_crash", "checkout.session.completed")   # dies here
        r = await _post_event(c, payload)
        assert r.json() == {"status": "duplicate"}, r.text
        assert (await op.subscriptions.find_one({"org_id": ORG_A}))["plan_id"] == "free"
        await ev.update_one({"stripe_event_id": "evt_crash"}, {"$set": {
            "processing_started_at": billing._utcnow() - timedelta(seconds=301)}})
        r = await _post_event(c, payload)
        assert r.json() == {"status": "received"}, r.text
        assert (await op.subscriptions.find_one({"org_id": ORG_A}))["plan_id"] == "pro"
        row = await ev.find_one({"stripe_event_id": "evt_crash"})
        assert row["status"] == "processed" and row["attempts"] == 2
        assert (await _post_event(c, payload)).json() == {"status": "duplicate"}
    run(monkeypatch, scenario, backend)


def test_18b_F02_a_failing_apply_marks_failed_and_the_retry_applies(monkeypatch, backend):
    _clean_env(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    from app.routes import billing
    resolve, apply = billing._WEBHOOK_HANDLERS["checkout.session.completed"]
    calls = {"n": 0}

    async def flaky_apply(*args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated failure")
        return await apply(*args)
    monkeypatch.setitem(billing._WEBHOOK_HANDLERS, "checkout.session.completed",
                        (resolve, flaky_apply))

    async def scenario(c, op):
        payload = _checkout_completed(event_id="evt_flaky")
        r = await _post_event(c, payload)
        assert r.status_code == 500, r.text
        assert (await op.billing_webhook_events.find_one({"stripe_event_id": "evt_flaky"}))[
            "status"] == "failed"
        r = await _post_event(c, payload)
        assert r.json() == {"status": "received"}, r.text
        row = await op.billing_webhook_events.find_one({"stripe_event_id": "evt_flaky"})
        assert row["status"] == "processed" and row["attempts"] == 2
        assert (await op.subscriptions.find_one({"org_id": ORG_A}))["plan_id"] == "pro"
    run(monkeypatch, scenario, backend)


@pytest.mark.parametrize("value,expected", [(None, 300), ("60", 60), ("0", 300), ("-5", 300),
                                            ("abc", 300)])
def test_18c_F02_lease_seconds_setting(monkeypatch, value, expected):
    from app.routes import billing
    monkeypatch.delenv("BILLING_WEBHOOK_LEASE_SECONDS", raising=False)
    if value is not None:
        monkeypatch.setenv("BILLING_WEBHOOK_LEASE_SECONDS", value)
    assert billing._webhook_lease_seconds() == expected


def test_19_F06_report_wrapper_is_an_allowlist_and_refuses_out_and_merge(backend):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import r0_01_billing_exposure_report as report

    async def scenario(db):
        await db.subscriptions.insert_one({"org_id": "M", "stripe_subscription_id": "mock_sub_9"})
        names_before = sorted(await db.list_collection_names())
        docs_before = await db.subscriptions.find({}, {"_id": 0}).to_list(None)
        ro = report.ReadOnlyDb(db)
        coll = ro["subscriptions"]
        for method in ("insert_one", "insert_many", "update_one", "update_many", "replace_one",
                       "delete_one", "delete_many", "find_one_and_update",
                       "find_one_and_delete", "find_one_and_replace", "bulk_write",
                       "create_index", "drop", "drop_index", "rename", "watch",
                       "initialize_ordered_bulk_op", "database", "with_options"):
            with pytest.raises(PermissionError):
                getattr(coll, method)
        for attr in ("drop_collection", "command", "create_collection", "client"):
            with pytest.raises(PermissionError):
                getattr(ro, attr)
        for pipeline in ([{"$match": {}}, {"$out": "r001_probe_out"}],
                         [{"$match": {}}, {"$merge": {"into": "r001_probe_merge"}}],
                         [{"$facet": {"x": [{"$match": {}}, {"$out": "r001_nested"}]}}],
                         [{"$unionWith": {"coll": "subscriptions",
                                          "pipeline": [{"$merge": "r001_union"}]}}]):
            with pytest.raises(PermissionError):
                coll.aggregate(pipeline)
        # reads still work, through the wrapper, on the real driver
        assert await coll.count_documents({}) == 1
        assert (await coll.find_one({}, {"_id": 0}))["org_id"] == "M"
        assert await coll.find({}, {"_id": 0}).to_list(None) == docs_before
        assert await coll.distinct("org_id") == ["M"]
        agg = await coll.aggregate([{"$match": {"org_id": "M"}},
                                    {"$project": {"_id": 0, "org_id": 1}}]).to_list(None)
        assert agg == [{"org_id": "M"}]
        assert sorted(await ro.list_collection_names()) == names_before
        # nothing was created or changed
        assert sorted(await db.list_collection_names()) == names_before
        assert await db.subscriptions.find({}, {"_id": 0}).to_list(None) == docs_before

    async def body():
        async with _Db(backend) as db:
            await scenario(db)
    asyncio.run(body())
