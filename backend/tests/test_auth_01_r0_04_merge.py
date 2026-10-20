"""
R0-04 — AUTH-01 (PR #56) merged onto main after R0-03.

R0-03 is the single source for identity (``app.tenancy.identity``); these tests
prove the merged behaviour on the shared harness of
``test_auth_01_password_recovery`` (mongomock + transaction test double, or the
real driver on a replica set when ``W0_03_REAL_MONGO_URL`` is set):

* forgot-password for an email held by several Users → the generic 200, no
  token, one ``forgot_ambiguous`` security event;
* login keeps the R0-03 contract (401 / 409 ``DUPLICATE_IDENTITY``) and adds a
  ``login_ambiguous`` security event (F-08);
* an old JWT is refused after a reset (F-02 ``av`` claim);
* a successful reset / recovery writes ONE canonical W0-04 AuditEvent inside the
  same transaction, with no password, hash or token; the legacy row stays;
* without transactions (standalone mongod) nothing is written, not even an
  AuditEvent.

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        pytest tests/test_auth_01_r0_04_merge.py -v --noconftest
"""
import json

from tests.test_auth_01_password_recovery import (
    NEW_PW, ORG_A, ORG_B, OWNER, PW, _cli_args, _forgot, _login, _reset, _user,
    force_no_transactions, scenario, type_password,
)


def _auth(token):
    return {"Authorization": "Bearer " + token}


async def _canonical(op, action=None):
    flt = {"action": action} if action else {}
    return await op.audit_events.find(flt, {"_id": 0}).sort("sequence", 1).to_list(None)


# ════════════════════════════════════════════ duplicates (R0-03 + AUTH-01 F-08)
def test_forgot_for_a_duplicate_email_is_generic_without_token_with_event(monkeypatch):
    from app.services.auth_events import keyed_ref

    async def body(op, c, outbox):
        await op.users.insert_many([_user("u-d1", ORG_A, "twin@x.bg"),
                                    _user("u-d2", ORG_B, " TWIN@x.bg")])
        r = await _forgot(c, "Twin@X.bg ")            # asserts status 200 + generic body
        assert outbox == []
        assert await op.password_reset_tokens.count_documents({}) == 0
        events = await op.auth_security_events.find(
            {"event": "forgot_ambiguous"}, {"_id": 0}).to_list(None)
        assert len(events) == 1
        assert events[0]["subject"] == keyed_ref("twin@x.bg")
        assert events[0]["detail"] == {"candidates": 2}
        assert "twin" not in json.dumps(events, default=str).lower()
        # the response for a unique, active account is byte-identical
        same = await _forgot(c, OWNER)
        assert same.content == r.content
    scenario(monkeypatch, body)


def test_duplicate_identity_login_contract_is_unchanged_and_recorded(monkeypatch):
    async def body(op, c, outbox):
        await op.users.insert_many([_user("u-d1", ORG_A, "twin@x.bg"),
                                    _user("u-d2", ORG_B, "TWIN@x.bg")])
        wrong = await _login(c, "twin@x.bg", "Wrong-Pass-00!")
        assert wrong.status_code == 401 and wrong.json() == {"detail": "Invalid credentials"}
        known = await _login(c, "twin@x.bg")
        assert known.status_code == 409
        assert known.json() == {"detail": {
            "error_code": "DUPLICATE_IDENTITY",
            "message": "This account cannot sign in until its identity is resolved. "
                       "Contact your administrator."}}
        refused = await _canonical(op, "auth.login_refused")
        assert sorted(e["tenant_id"] for e in refused) == [ORG_A, ORG_B]    # R0-03, unchanged
        assert all(e["error_code"] == "DUPLICATE_IDENTITY" for e in refused)
        assert await op.auth_security_events.count_documents({"event": "login_ambiguous"}) == 2
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════ F-02 after the merge
def test_old_jwt_is_refused_after_a_reset_new_login_works(monkeypatch):
    async def body(op, c, outbox):
        old = (await _login(c, " krum@BEGFULL.bg")).json()["token"]
        assert (await c.get("/api/auth/me", headers=_auth(old))).status_code == 200
        await _forgot(c, OWNER)
        assert (await _reset(c, outbox[0].token)).status_code == 200
        r = await c.get("/api/auth/me", headers=_auth(old))
        assert r.status_code == 401
        assert (await _login(c, OWNER, PW)).status_code == 401
        new = (await _login(c, OWNER, NEW_PW)).json()["token"]
        assert (await c.get("/api/auth/me", headers=_auth(new))).status_code == 200
    scenario(monkeypatch, body)


# ═════════════════════════════════════════════ canonical W0-04 AuditEvent
def _no_secret(events, *secrets):
    dump = json.dumps(events, default=str)
    for secret in secrets:
        assert secret not in dump, "secret leaked into the AuditEvent"
    for key in ("password", "password_hash", "token", "token_hash"):
        assert '"%s"' % key not in dump


def test_reset_writes_one_canonical_audit_event_and_keeps_the_legacy_row(monkeypatch):
    from app.audit.store import verify_chain

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        token = outbox[0].token
        assert (await _reset(c, token)).status_code == 200
        events = await _canonical(op, "user.password_reset")
        assert len(events) == 1
        e = events[0]
        assert (e["tenant_id"], e["actor_id"], e["entity_id"], e["result"]) == \
            (ORG_A, "u-owner", "u-owner", "success")
        assert e["tool_or_endpoint"] == "POST /api/auth/reset-password"
        user = await op.users.find_one({"id": "u-owner"})
        _no_secret(events, token, NEW_PW, user["password_hash"])
        ok, reason = verify_chain(await op.audit_events.find(
            {"tenant_id": ORG_A}, {"_id": 0}).sort("sequence", 1).to_list(None))
        assert ok, reason
        assert await op.audit_logs.count_documents(
            {"action": "password_reset_completed", "entity_id": "u-owner"}) == 1
        # a replayed link writes no second success event
        assert (await _reset(c, token, "Another-Pass-99!")).status_code == 400
        assert len(await _canonical(op, "user.password_reset")) == 1
    scenario(monkeypatch, body)


def test_recovery_cli_writes_one_canonical_audit_event(monkeypatch):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_OK
        events = await _canonical(op, "user.password_recovery_cli")
        assert len(events) == 1
        e = events[0]
        assert (e["tenant_id"], e["actor_type"], e["actor_id"], e["entity_id"]) == \
            (ORG_A, "system", cli.RECOVERY_MARKER, "u-owner")
        user = await op.users.find_one({"id": "u-owner"})
        _no_secret(events, NEW_PW, user["password_hash"])
        assert await op.audit_logs.count_documents({"action": "password_recovery_cli"}) == 1
    scenario(monkeypatch, body)


def test_a_failing_audit_event_rolls_the_whole_reset_back(monkeypatch):
    from app.services import password_reset

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        token = outbox[0].token
        before = await op.users.find_one({"id": "u-owner"}, {"_id": 0})

        async def failing(*a, **kw):
            raise RuntimeError("injected at the canonical AuditEvent")
        real = password_reset.audit_user_change
        monkeypatch.setattr(password_reset, "audit_user_change", failing)
        r = await _reset(c, token)
        assert r.status_code == 503 and r.json()["detail"]["error_code"] == "RESET_NOT_COMPLETED"
        assert await op.users.find_one({"id": "u-owner"}, {"_id": 0}) == before
        assert await op.audit_logs.count_documents({"action": "password_reset_completed"}) == 0
        assert await _canonical(op, "user.password_reset") == []
        monkeypatch.setattr(password_reset, "audit_user_change", real)
        assert (await _reset(c, token)).status_code == 200        # the link is still unused
        assert len(await _canonical(op, "user.password_reset")) == 1
    scenario(monkeypatch, body)


def test_standalone_mongo_refuses_before_any_write(monkeypatch):
    """No replica set: reset 503 RESET_NOT_COMPLETED, CLI exit 7, forgot mints nothing."""
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        token = outbox[0].token
        users0 = await op.users.find({}, {"_id": 0}).sort("id", 1).to_list(None)
        tokens0 = await op.password_reset_tokens.count_documents({})
        events0 = len(await _canonical(op))
        force_no_transactions(monkeypatch)
        r = await _reset(c, token)
        assert r.status_code == 503 and r.json()["detail"]["error_code"] == "RESET_NOT_COMPLETED"
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_NO_TRANSACTIONS
        await _forgot(c, OWNER)
        assert len(outbox) == 1
        assert await op.users.find({}, {"_id": 0}).sort("id", 1).to_list(None) == users0
        assert await op.password_reset_tokens.count_documents({}) == tokens0
        assert len(await _canonical(op)) == events0
        assert await op.auth_security_events.count_documents(
            {"event": "forgot_processing_failed"}) == 1
    scenario(monkeypatch, body)


def test_the_audit_event_is_inside_the_transaction(monkeypatch):
    """A failure right AFTER the AuditEvent insert leaves no AuditEvent behind.

    On a real replica set this proves ``session=`` reaches the insert (an insert
    outside the transaction would survive the abort). The mongomock double
    restores every touched collection, so there it only checks the contract.
    """
    from app.services import password_reset

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        real = password_reset.audit_user_change

        async def then_fail(*a, **kw):
            await real(*a, **kw)
            raise RuntimeError("injected after the canonical AuditEvent")
        monkeypatch.setattr(password_reset, "audit_user_change", then_fail)
        r = await _reset(c, outbox[0].token)
        assert r.status_code == 503 and r.json()["detail"]["error_code"] == "RESET_NOT_COMPLETED"
        assert await _canonical(op) == []
        assert (await _login(c, OWNER, PW)).status_code == 200
    scenario(monkeypatch, body)
