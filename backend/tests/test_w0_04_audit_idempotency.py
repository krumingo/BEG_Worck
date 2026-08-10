"""
W0-04 — AuditEvent + idempotency tests.

These tests encode the FLOW-040 rules that, if broken, make the audit
trail unusable as evidence: an event that can be forged, a chain that
does not notice a deleted record, a secret leaking into the log, or a
double-click creating a second payment.

Pure logic tests — no database needed, same style as W0-01.

Run:  pytest tests/test_w0_04_audit_idempotency.py -v
"""
import pytest

from app.audit.envelope import (
    build_event,
    validate_event,
    mask_sensitive,
    AuditEventInvalid,
    ACTOR_HUMAN,
    ACTOR_AI,
    MASKED_VALUE,
    RETENTION_R1_CRITICAL_BUSINESS,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RESULT_SUCCESS,
)
from app.audit.store import (
    chain_hashes,
    canonical_hash,
    verify_chain,
    GENESIS_HASH,
)
from app.audit.idempotency import request_fingerprint


def make_event(**overrides):
    """A valid payment event, the highest-stakes case (R1)."""
    defaults = dict(
        tenant_id="tenant-a",
        actor_type=ACTOR_HUMAN,
        actor_id="user-1",
        action="payment.created",
        source_flow="FLOW-006",
        retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="payment",
        entity_id="pay-100",
        reason="Invoice INV-42 paid",
    )
    defaults.update(overrides)
    return build_event(**defaults)


def make_chain(n=3):
    """Build a valid n-event chain for tenant-a."""
    events, previous = [], None
    for i in range(n):
        e = chain_hashes(make_event(entity_id=f"pay-{i}"), previous)
        events.append(e)
        previous = e
    return events


# ---------------------------------------------------------------------------
# Envelope: required fields (FLOW-040 §15)
# ---------------------------------------------------------------------------

def test_valid_event_builds():
    e = make_event()
    assert e["event_id"].startswith("ae_")
    assert e["tenant_id"] == "tenant-a"
    assert e["retention_class"] == "R1"


def test_event_without_tenant_is_rejected():
    """§15: event without tenant must never be accepted."""
    with pytest.raises(AuditEventInvalid):
        make_event(tenant_id="")


def test_event_without_action_is_rejected():
    with pytest.raises(AuditEventInvalid):
        make_event(action="")


def test_event_without_source_flow_is_rejected():
    with pytest.raises(AuditEventInvalid):
        make_event(source_flow="")


def test_event_with_unknown_retention_class_is_rejected():
    """§6: retention_class is assigned at creation — an unknown class
    would make the retention job undefined."""
    with pytest.raises(AuditEventInvalid):
        make_event(retention_class="R9")


def test_event_with_unknown_actor_type_is_rejected():
    with pytest.raises(AuditEventInvalid):
        make_event(actor_type="robot")


# ---------------------------------------------------------------------------
# AI rules (FLOW-040 §4.4, §5)
# ---------------------------------------------------------------------------

def test_ai_event_requires_model_version():
    """§4.4: an AI action must record which model did it."""
    with pytest.raises(AuditEventInvalid):
        make_event(actor_type=ACTOR_AI)


def test_ai_event_with_model_is_valid():
    e = make_event(actor_type=ACTOR_AI, model_and_version="beg-brain-1.0")
    assert e["model_and_version"] == "beg-brain-1.0"


def test_ai_success_requiring_confirmation_needs_a_human():
    """§5: DOMAIN_ACTION_EXECUTED without a confirming human is a
    blocking incident — it must be impossible to even record."""
    with pytest.raises(AuditEventInvalid):
        make_event(
            actor_type=ACTOR_AI,
            model_and_version="beg-brain-1.0",
            confirmation_required=True,
            result=RESULT_SUCCESS,
        )


def test_ai_confirmed_by_human_is_valid():
    e = make_event(
        actor_type=ACTOR_AI,
        model_and_version="beg-brain-1.0",
        confirmation_required=True,
        confirmed_by="user-1",
    )
    assert e["confirmed_by"] == "user-1"


# ---------------------------------------------------------------------------
# Data minimization (FLOW-040 §9)
# ---------------------------------------------------------------------------

def test_password_is_masked_in_diff():
    e = make_event(structured_diff={"password": "BegWork2026!", "email": "a@b.bg"})
    assert e["structured_diff"]["password"] == MASKED_VALUE
    assert e["structured_diff"]["email"] == "a@b.bg"


def test_nested_secrets_are_masked():
    e = make_event(structured_diff={
        "settings": {"api_key": "sk-123", "items": [{"refresh_token": "xyz"}]}
    })
    assert e["structured_diff"]["settings"]["api_key"] == MASKED_VALUE
    assert e["structured_diff"]["settings"]["items"][0]["refresh_token"] == MASKED_VALUE


def test_mask_does_not_modify_input():
    original = {"password": "secret1"}
    mask_sensitive(original)
    assert original["password"] == "secret1"


def test_validate_rejects_smuggled_secret():
    """A diff injected AFTER build_event (bypassing masking) is caught
    at validate/record time."""
    e = make_event()
    e["structured_diff"] = {"access_key": "AKIA123"}
    with pytest.raises(AuditEventInvalid):
        validate_event(e)


# ---------------------------------------------------------------------------
# Hash chain (FLOW-040 §8)
# ---------------------------------------------------------------------------

def test_first_event_anchors_on_genesis():
    e = chain_hashes(make_event(), None)
    assert e["sequence"] == 1
    assert e["previous_hash"] == GENESIS_HASH
    assert e["integrity_hash"] == canonical_hash(e)


def test_chain_links_via_previous_hash():
    events = make_chain(3)
    assert events[1]["previous_hash"] == events[0]["integrity_hash"]
    assert events[2]["previous_hash"] == events[1]["integrity_hash"]
    assert verify_chain(events) == (True, None)


def test_tampered_amount_is_detected():
    """The core forgery scenario: someone edits a historical event."""
    events = make_chain(3)
    events[1]["reason"] = "Invoice INV-42 paid — amount changed"
    ok, reason = verify_chain(events)
    assert ok is False
    assert "tampered" in reason


def test_deleted_event_is_detected():
    """Removing an event from the middle must not go unnoticed."""
    events = make_chain(3)
    del events[1]
    ok, reason = verify_chain(events)
    assert ok is False


def test_reordered_events_are_detected():
    events = make_chain(3)
    events[1], events[2] = events[2], events[1]
    ok, reason = verify_chain(events)
    assert ok is False


def test_forged_first_link_is_detected():
    """Rewriting previous_hash of the first event breaks the genesis anchor."""
    events = make_chain(2)
    events[0]["previous_hash"] = "f" * 64
    ok, _ = verify_chain(events)
    assert ok is False


def test_empty_chain_is_intact():
    assert verify_chain([]) == (True, None)


def test_r2_operational_event_chains_like_r1():
    e = chain_hashes(
        make_event(
            action="daily_report.approved",
            source_flow="FLOW-014",
            retention_class=RETENTION_R2_PROJECT_OPERATIONAL,
        ),
        None,
    )
    assert e["integrity_hash"] == canonical_hash(e)


# ---------------------------------------------------------------------------
# Idempotency fingerprints
# ---------------------------------------------------------------------------

def test_same_payload_same_fingerprint():
    a = request_fingerprint({"amount": 100, "invoice": "INV-42"})
    b = request_fingerprint({"invoice": "INV-42", "amount": 100})
    assert a == b  # key order must not matter


def test_different_payload_different_fingerprint():
    a = request_fingerprint({"amount": 100})
    b = request_fingerprint({"amount": 200})
    assert a != b


# ---------------------------------------------------------------------------
# Store + idempotency against a database.
#
# Uses the real MongoDB from MONGO_URL when reachable (the Synology
# container), otherwise falls back to mongomock-motor when installed,
# otherwise skips. No new hard dependency is introduced.
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402
import os  # noqa: E402
import uuid as _uuid  # noqa: E402

from app.audit.store import (  # noqa: E402
    record_event,
    record_correction,
    verify_tenant_chain,
)
from app.audit.idempotency import (  # noqa: E402
    begin_idempotent,
    complete_idempotent,
    fail_idempotent,
    IdempotencyConflict,
    IDEMPOTENCY_STARTED,
    IDEMPOTENCY_DUPLICATE,
)


def _get_db():
    """A throwaway test database: real Mongo if reachable, else mongomock."""
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = f"begwork_w0_04_test_{_uuid.uuid4().hex[:8]}"
    try:
        from pymongo import MongoClient
        MongoClient(mongo_url, serverSelectionTimeoutMS=500).admin.command("ping")
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(mongo_url)
        return client[db_name], lambda: client.drop_database(db_name)
    except Exception:
        try:
            from mongomock_motor import AsyncMongoMockClient
        except ImportError:
            pytest.skip("No MongoDB and no mongomock-motor available")
        client = AsyncMongoMockClient()
        return client[db_name], lambda: None


def run_async(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_store_appends_and_chain_verifies():
    async def scenario():
        db, cleanup = _get_db()
        e1 = await record_event(db, make_event(entity_id="pay-1"))
        e2 = await record_event(db, make_event(entity_id="pay-2"))
        assert e1["sequence"] == 1 and e2["sequence"] == 2
        assert e2["previous_hash"] == e1["integrity_hash"]
        ok, reason = await verify_tenant_chain(db, "tenant-a")
        await asyncio.sleep(0)
        return ok, reason
    ok, reason = run_async(scenario())
    assert ok is True, reason


def test_correction_is_new_event_pointing_at_original():
    """FLOW-040 §2: a mistake is answered by a NEW event, never an edit."""
    async def scenario():
        db, _ = _get_db()
        original = await record_event(db, make_event(entity_id="pay-1"))
        correction = await record_correction(
            db, original,
            actor_type=ACTOR_HUMAN, actor_id="user-1",
            reason="Wrong amount entered; correct amount is 1200 EUR",
        )
        stored_original = await db["audit_events"].find_one(
            {"event_id": original["event_id"]}, {"_id": 0}
        )
        return original, correction, stored_original
    original, correction, stored_original = run_async(scenario())
    assert correction["action"] == "audit.correction"
    assert correction["entity_id"] == original["event_id"]
    assert correction["sequence"] == original["sequence"] + 1
    # The original is untouched, byte for byte.
    assert stored_original == original


def test_correction_without_reason_is_refused():
    async def scenario():
        db, _ = _get_db()
        original = await record_event(db, make_event())
        with pytest.raises(ValueError):
            await record_correction(
                db, original, actor_type=ACTOR_HUMAN, actor_id="user-1", reason="  ",
            )
    run_async(scenario())


def test_tenants_have_independent_chains():
    """Tenant isolation applies to audit too: sequences never interleave."""
    async def scenario():
        db, _ = _get_db()
        a1 = await record_event(db, make_event(tenant_id="tenant-a"))
        b1 = await record_event(db, make_event(tenant_id="tenant-b"))
        b2 = await record_event(db, make_event(tenant_id="tenant-b"))
        return a1, b1, b2
    a1, b1, b2 = run_async(scenario())
    assert a1["sequence"] == 1
    assert b1["sequence"] == 1 and b2["sequence"] == 2
    assert b1["previous_hash"] == GENESIS_HASH


def test_double_click_does_not_double_pay():
    """The reason idempotency exists: same key twice → one write."""
    async def scenario():
        db, _ = _get_db()
        fp = request_fingerprint({"invoice": "INV-42", "amount": 100})
        first = await begin_idempotent(
            db, tenant_id="tenant-a", key="pay-INV-42", action="payment.create",
            request_fingerprint=fp,
        )
        assert first["status"] == IDEMPOTENCY_STARTED
        await complete_idempotent(
            db, tenant_id="tenant-a", key="pay-INV-42", action="payment.create",
            result_reference="payment:pay-100",
        )
        second = await begin_idempotent(
            db, tenant_id="tenant-a", key="pay-INV-42", action="payment.create",
            request_fingerprint=fp,
        )
        return second
    second = run_async(scenario())
    assert second["status"] == IDEMPOTENCY_DUPLICATE
    assert second["prior_status"] == "completed"
    assert second["result_reference"] == "payment:pay-100"


def test_same_key_different_payload_is_conflict():
    """Same key + different content is a caller bug and must be loud."""
    async def scenario():
        db, _ = _get_db()
        await begin_idempotent(
            db, tenant_id="tenant-a", key="k1", action="payment.create",
            request_fingerprint=request_fingerprint({"amount": 100}),
        )
        with pytest.raises(IdempotencyConflict):
            await begin_idempotent(
                db, tenant_id="tenant-a", key="k1", action="payment.create",
                request_fingerprint=request_fingerprint({"amount": 999}),
            )
    run_async(scenario())


def test_failed_write_can_be_retried_completed_cannot_rerun():
    async def scenario():
        db, _ = _get_db()
        fp = request_fingerprint({"amount": 100})
        await begin_idempotent(db, tenant_id="tenant-a", key="k2",
                               action="payment.create", request_fingerprint=fp)
        await fail_idempotent(db, tenant_id="tenant-a", key="k2",
                              action="payment.create", error_code="bank_timeout")
        retry = await begin_idempotent(db, tenant_id="tenant-a", key="k2",
                                       action="payment.create", request_fingerprint=fp)
        return retry
    retry = run_async(scenario())
    assert retry["status"] == IDEMPOTENCY_STARTED
    assert retry.get("retry_of_failed") is True


def test_same_key_different_tenant_is_independent():
    """Tenant isolation: tenant-b's key does not collide with tenant-a's."""
    async def scenario():
        db, _ = _get_db()
        a = await begin_idempotent(db, tenant_id="tenant-a", key="k3",
                                   action="payment.create")
        b = await begin_idempotent(db, tenant_id="tenant-b", key="k3",
                                   action="payment.create")
        return a, b
    a, b = run_async(scenario())
    assert a["status"] == IDEMPOTENCY_STARTED
    assert b["status"] == IDEMPOTENCY_STARTED
