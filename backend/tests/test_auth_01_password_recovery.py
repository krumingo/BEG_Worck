"""
AUTH-01 — owner access recovery CLI + Forgot/Reset Password MVP.

Proven here, over real HTTP against the real ``auth`` router (in-process,
``mongomock_motor``; a disposable local MongoDB when ``W0_03_REAL_MONGO_URL``
is set):

* forgot-password answers the SAME body for an unknown, a disabled, an
  ambiguous and a real account, and only the real one gets a token;
* only the SHA-256 of a token is stored — the plaintext appears in no stored
  document and in no response;
* a token is single-use, expires after 30 minutes, is superseded by a newer
  request and is invalidated with every other open token of the user on
  success; a disabled user cannot reset;
* the reset really changes the password (old one stops working);
* login / forgot are case-insensitive and a case-only duplicate fails closed;
* Admin Reset and Change Password keep their contracts;
* the local recovery CLI: dry run writes nothing, the real run changes exactly
  one user, and 0 / >1 / disabled / weak password all exit non-zero.

    pytest tests/test_auth_01_password_recovery.py -v --noconftest
    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27018 pytest ... --noconftest
"""
import asyncio
import io
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

ORG_A, ORG_B = "ORG-A", "ORG-B"
PW = "Recovery-2026!"
NEW_PW = "Brand-New-Pass-77!"
OWNER = "Krum@begfull.bg"
TECH = "tech@a.bg"
DISABLED = "gone@a.bg"
OTHER = "other@b.bg"
GENERIC = {"ok": True, "message": "If an active account exists for this email, "
                                  "we sent a password reset link."}


# ═══════════════════════════════════════════════════════════════════ harness
async def _database():
    url = os.environ.get("W0_03_REAL_MONGO_URL", "")
    if url:
        from tests.test_w0_03c_real_mongo import _refusal
        refused = _refusal()
        if refused:
            pytest.skip(refused)
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(url)
        name = "auth01_" + uuid.uuid4().hex[:12]

        async def cleanup():
            await client.drop_database(name)
            client.close()
        return client[name], client[name + "_sys"], cleanup
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()

    async def nothing():
        return None
    return client["auth01"], client["auth01_sys"], nothing


def _user(uid, org, email, role="Owner", active=True, password=PW):
    from app.deps.auth import hash_password
    return {"id": uid, "org_id": org, "email": email, "password_hash": hash_password(password),
            "role": role, "first_name": "F" + uid, "last_name": "L", "is_active": active}


async def _seed(op, sysdb):
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": org, "slug": org.lower()})
        await sysdb.tenant_registry.insert_one({"id": org, "database_name": op.name,
                                                "status": "active"})
    await op.users.insert_many([
        _user("u-owner", ORG_A, OWNER),
        _user("u-tech", ORG_A, TECH, role="Technician"),
        _user("u-gone", ORG_A, DISABLED, role="Viewer", active=False),
        _user("u-other", ORG_B, OTHER),
    ])


def _app(monkeypatch, op, sysdb, outbox):
    from fastapi import FastAPI

    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.deps import modules as deps_modules
    from app.master_data.deps import ENV_MODE
    from app.tenancy import registry
    import server  # noqa: F401 — billing imports server constants; load it first
    from app.routes import auth
    from app.services import audit as services_audit, password_reset
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, deps_modules, utils_audit, services_audit, auth):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for name in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, name, sysdb[name])
    for limiter in (auth.forgot_password_ip_limiter, auth.forgot_password_email_limiter,
                    auth.reset_password_ip_limiter):
        limiter.reset()
    monkeypatch.setattr(password_reset, "deliver", outbox.append)

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    return app


def scenario(monkeypatch, body):
    """Run ``body(op, client, outbox)`` against a freshly seeded database."""
    import httpx

    async def main():
        op, sysdb, cleanup = await _database()
        try:
            await _seed(op, sysdb)
            outbox = []
            app = _app(monkeypatch, op, sysdb, outbox)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://auth01") as c:
                return await body(op, c, outbox)
        finally:
            await cleanup()
    return asyncio.run(main())


async def _login(c, email, password=PW):
    return await c.post("/api/auth/login", json={"email": email, "password": password})


async def _forgot(c, email):
    r = await c.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 200, r.text
    assert r.json() == GENERIC
    return r


async def _reset(c, token, password=NEW_PW):
    return await c.post("/api/auth/reset-password",
                        json={"token": token, "new_password": password})


async def _all_documents(op):
    out = []
    for name in await op.list_collection_names():
        out.extend(await op[name].find({}).to_list(None))
    return out


def _is_generic_reset_failure(r):
    return (r.status_code == 400
            and r.json()["detail"]["error_code"] == "RESET_TOKEN_INVALID"
            and "invalid or has expired" in r.json()["detail"]["message"])


# ═══════════════════════════════════════════════ 1. forgot-password: enumeration
def test_unknown_disabled_and_real_accounts_get_the_same_answer(monkeypatch):
    async def body(op, c, outbox):
        bodies = set()
        for email in ("nobody@nowhere.bg", DISABLED, "not-an-email", OWNER):
            r = await _forgot(c, email)
            bodies.add(r.text)
        assert len(bodies) == 1                          # byte-identical responses
        rows = await op.password_reset_tokens.find({}).to_list(None)
        assert [(x["user_id"], x["org_id"]) for x in rows] == [("u-owner", ORG_A)]
        assert [m.user_id for m in outbox] == ["u-owner"]
    scenario(monkeypatch, body)


def test_a_token_is_stored_only_as_its_hash(monkeypatch):
    from app.services.password_reset import TOKEN_TTL, hash_token

    async def body(op, c, outbox):
        r = await _forgot(c, OWNER)
        token = outbox[0].token
        assert len(token) >= 40
        assert token not in r.text
        rows = await op.password_reset_tokens.find({}, {"_id": 0}).to_list(None)
        assert len(rows) == 1
        row = rows[0]
        assert set(row) >= {"id", "org_id", "user_id", "token_hash", "requested_at",
                            "expires_at", "used_at", "requested_ip"}
        assert row["token_hash"] == hash_token(token) != token
        assert row["used_at"] is None
        assert row["user_id"] == "u-owner" and row["org_id"] == ORG_A
        lifetime = row["expires_at"] - row["requested_at"]
        assert lifetime == TOKEN_TTL == timedelta(minutes=30)
        # the plaintext is nowhere in the database — not in tokens, not in audit
        dump = json.dumps(await _all_documents(op), default=str)
        assert token not in dump
        audit = await op.audit_logs.find({"action": "password_reset_requested"}).to_list(None)
        assert len(audit) == 1 and audit[0]["org_id"] == ORG_A
        assert "ResetMail" in repr(outbox[0]) and token not in repr(outbox[0])
    scenario(monkeypatch, body)


# ═════════════════════════════════════════════════════ 2. reset: happy path
def test_reset_changes_the_password_and_the_old_one_stops_working(monkeypatch):
    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        r = await _reset(c, outbox[0].token)
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert (await _login(c, OWNER, PW)).status_code == 401
        ok = await _login(c, OWNER, NEW_PW)
        assert ok.status_code == 200 and ok.json()["user"]["id"] == "u-owner"
        user = await op.users.find_one({"id": "u-owner"})
        assert user["password_reset_by"] == "SELF_SERVICE_TOKEN" and user["password_reset_at"]
        assert await op.audit_logs.count_documents({"action": "password_reset_completed",
                                                    "entity_id": "u-owner"}) == 1
        # nobody else was touched
        assert (await _login(c, TECH)).status_code == 200
        assert (await _login(c, OTHER)).status_code == 200
    scenario(monkeypatch, body)


def test_a_token_is_single_use(monkeypatch):
    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        token = outbox[0].token
        assert (await _reset(c, token)).status_code == 200
        again = await _reset(c, token, "Another-Pass-99!")
        assert _is_generic_reset_failure(again), again.text
        assert (await _login(c, OWNER, NEW_PW)).status_code == 200
    scenario(monkeypatch, body)


def test_a_racing_submission_that_read_the_token_unused_still_loses(monkeypatch):
    """The single-use guarantee is the conditional claim IN the database.

    Two concurrent submissions can both read the row while it is unused. This
    replays the loser deterministically: its read is a stale snapshot (unused),
    but by the time it claims, the winner has already spent the token. The claim
    must fail and the winner's password must stand.
    """
    from app.deps.auth import hash_password, verify_password
    from app.services import password_reset

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        token = outbox[0].token
        tenant, stale = await password_reset.resolve_owner_by_unique_key(
            op, "password_reset_tokens", "token_hash", password_reset.hash_token(token),
            {"_id": 0})
        assert stale["used_at"] is None
        await password_reset.reset_password(op, token, hash_password("First-Winner-11!"))

        async def stale_read(*args, **kw):
            return tenant, dict(stale)
        monkeypatch.setattr(password_reset, "resolve_owner_by_unique_key", stale_read)
        with pytest.raises(password_reset.ResetFailed):
            await password_reset.reset_password(op, token, hash_password("Second-Loser-22!"))
        user = await op.users.find_one({"id": "u-owner"})
        assert verify_password("First-Winner-11!", user["password_hash"])
    scenario(monkeypatch, body)


def test_an_expired_token_is_rejected(monkeypatch):
    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        await op.password_reset_tokens.update_one({"user_id": "u-owner"},
                                                  {"$set": {"expires_at": past}})
        r = await _reset(c, outbox[0].token)
        assert _is_generic_reset_failure(r), r.text
        assert (await _login(c, OWNER, PW)).status_code == 200      # unchanged
    scenario(monkeypatch, body)


def test_unknown_and_malformed_tokens_get_the_same_failure(monkeypatch):
    async def body(op, c, outbox):
        for token in ("x" * 43, "short", "", "y" * 256):
            assert _is_generic_reset_failure(await _reset(c, token)), token
        r = await _reset(c, "z" * 300)                              # over the field bound
        assert r.status_code == 422
    scenario(monkeypatch, body)


def test_a_newer_request_supersedes_the_older_token(monkeypatch):
    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        await _forgot(c, OWNER)
        first, second = outbox[0].token, outbox[1].token
        assert first != second
        assert await op.password_reset_tokens.count_documents(
            {"user_id": "u-owner", "used_at": None}) == 1
        assert _is_generic_reset_failure(await _reset(c, first))
        assert (await _reset(c, second)).status_code == 200
    scenario(monkeypatch, body)


def test_success_invalidates_every_remaining_token_of_the_user(monkeypatch):
    from app.services.password_reset import hash_token

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        await _forgot(c, TECH)
        # a second open row for the owner (e.g. a race between two requests)
        now = datetime.now(timezone.utc)
        await op.password_reset_tokens.insert_one({
            "id": "stray", "org_id": ORG_A, "user_id": "u-owner",
            "token_hash": hash_token("stray-token-value-0123456789"), "requested_at": now,
            "expires_at": now + timedelta(minutes=30), "used_at": None, "requested_ip": None})
        assert (await _reset(c, outbox[0].token)).status_code == 200
        assert await op.password_reset_tokens.count_documents(
            {"user_id": "u-owner", "used_at": None}) == 0
        stray = await op.password_reset_tokens.find_one({"id": "stray"})
        assert stray["revoked_reason"] == "password_reset"
        assert _is_generic_reset_failure(await _reset(c, "stray-token-value-0123456789"))
        # another user's open token is untouched
        assert await op.password_reset_tokens.count_documents(
            {"user_id": "u-tech", "used_at": None}) == 1
    scenario(monkeypatch, body)


def test_a_weak_password_is_refused_without_spending_the_token(monkeypatch):
    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        weak = await _reset(c, outbox[0].token, "short")
        assert weak.status_code == 400 and "at least 10" in weak.json()["detail"]
        assert (await _reset(c, outbox[0].token)).status_code == 200
    scenario(monkeypatch, body)


def test_a_disabled_user_cannot_reset(monkeypatch):
    async def body(op, c, outbox):
        await _forgot(c, DISABLED)
        assert outbox == []
        assert await op.password_reset_tokens.count_documents({}) == 0
        # a token minted while active dies when the user is disabled
        await _forgot(c, TECH)
        await op.users.update_one({"id": "u-tech"}, {"$set": {"is_active": False}})
        assert _is_generic_reset_failure(await _reset(c, outbox[0].token))
        user = await op.users.find_one({"id": "u-tech"})
        from app.deps.auth import verify_password
        assert verify_password(PW, user["password_hash"])
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════ 3. email case and ambiguity
def test_login_and_reset_ignore_letter_case_and_spaces(monkeypatch):
    async def body(op, c, outbox):
        for spelling in (OWNER, "krum@begfull.bg", "  KRUM@BEGFULL.BG  "):
            r = await _login(c, spelling)
            assert r.status_code == 200, (spelling, r.text)
            assert r.json()["user"]["id"] == "u-owner"
        await _forgot(c, " kRuM@BegFull.bg ")
        assert [m.user_id for m in outbox] == ["u-owner"]
        assert outbox[0].to == OWNER                     # sent to the stored address
        assert (await _reset(c, outbox[0].token)).status_code == 200
        assert (await _login(c, "krum@begfull.bg", NEW_PW)).status_code == 200
    scenario(monkeypatch, body)


def test_a_case_only_duplicate_fails_closed(monkeypatch, caplog):
    async def body(op, c, outbox):
        await op.users.insert_many([_user("u-dup1", ORG_A, "dup@a.bg"),
                                    _user("u-dup2", ORG_B, "DUP@a.bg")])
        with caplog.at_level(logging.WARNING):
            for spelling in ("dup@a.bg", "DUP@a.bg"):
                r = await _login(c, spelling)
                assert r.status_code == 401 and r.json()["detail"] == "Invalid credentials"
        assert "LOGIN_REFUSED_AMBIGUOUS_EMAIL" in caplog.text
        await _forgot(c, "dup@a.bg")
        assert outbox == []
        assert await op.password_reset_tokens.count_documents({}) == 0
    scenario(monkeypatch, body)


def test_a_regex_shaped_email_matches_only_itself(monkeypatch):
    async def body(op, c, outbox):
        assert (await _login(c, ".*")).status_code == 401
        assert (await _login(c, "krum@begfull.b.")).status_code == 401
        await _forgot(c, ".*@.*")
        assert outbox == []
    scenario(monkeypatch, body)


def test_user_create_refuses_a_case_variant_of_an_existing_email(monkeypatch):
    async def body(op, c, outbox):
        token = (await _login(c, OTHER)).json()["token"]
        h = {"Authorization": "Bearer " + token}
        payload = {"password": PW, "first_name": "N", "last_name": "U", "role": "Viewer"}
        dup = await c.post("/api/users", json={**payload, "email": " OTHER@B.bg "}, headers=h)
        assert dup.status_code == 400 and "already exists" in dup.json()["detail"]
        ok = await c.post("/api/users", json={**payload, "email": " New.User@b.bg "}, headers=h)
        assert ok.status_code == 201, ok.text
        assert ok.json()["email"] == "New.User@b.bg"           # stored stripped, case kept
        assert (await _login(c, "new.user@b.bg")).status_code == 200
    scenario(monkeypatch, body)


# ═════════════════════════════════════════════ 4. existing flows: regressions
def test_admin_reset_still_works_for_another_user_and_never_for_self(monkeypatch):
    async def body(op, c, outbox):
        h = {"Authorization": "Bearer " + (await _login(c, OWNER)).json()["token"]}
        r = await c.post("/api/admin/set-password/u-tech", json={"new_password": NEW_PW},
                         headers=h)
        assert r.status_code == 200 and r.json() == {"ok": True}, r.text
        assert (await _login(c, TECH, NEW_PW)).status_code == 200
        assert (await _login(c, TECH, PW)).status_code == 401
        me = await c.post("/api/admin/set-password/u-owner", json={"new_password": NEW_PW},
                          headers=h)
        assert me.status_code == 400 and "own password" in me.json()["detail"]
        foreign = await c.post("/api/admin/set-password/u-other",
                               json={"new_password": NEW_PW}, headers=h)
        assert foreign.status_code == 404
        weak = await c.post("/api/admin/set-password/u-tech", json={"new_password": "weak"},
                            headers=h)
        assert weak.status_code == 400
        th = {"Authorization": "Bearer " + (await _login(c, TECH, NEW_PW)).json()["token"]}
        denied = await c.post("/api/admin/set-password/u-owner",
                              json={"new_password": NEW_PW}, headers=th)
        assert denied.status_code == 403
    scenario(monkeypatch, body)


def test_change_password_still_works(monkeypatch):
    async def body(op, c, outbox):
        h = {"Authorization": "Bearer " + (await _login(c, TECH)).json()["token"]}
        wrong = await c.post("/api/auth/change-password",
                             json={"current_password": "Wrong-Pass-00!", "new_password": NEW_PW},
                             headers=h)
        assert wrong.status_code == 403
        weak = await c.post("/api/auth/change-password",
                            json={"current_password": PW, "new_password": "weak"}, headers=h)
        assert weak.status_code == 400
        same = await c.post("/api/auth/change-password",
                            json={"current_password": PW, "new_password": PW}, headers=h)
        assert same.status_code == 400
        ok = await c.post("/api/auth/change-password",
                          json={"current_password": PW, "new_password": NEW_PW}, headers=h)
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        assert (await _login(c, TECH, NEW_PW)).status_code == 200
        assert (await _login(c, TECH, PW)).status_code == 401
    scenario(monkeypatch, body)


def test_login_contract_is_unchanged(monkeypatch):
    async def body(op, c, outbox):
        r = await _login(c, OWNER)
        assert r.status_code == 200
        assert set(r.json()) == {"token", "user"} and "password_hash" not in r.json()["user"]
        assert (await _login(c, OWNER, "Wrong-Pass-00!")).status_code == 401
        assert (await _login(c, "nobody@nowhere.bg")).status_code == 401
        assert (await _login(c, DISABLED)).status_code == 403
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════════════ 5. rate limits
def test_the_per_email_limit_is_silent_and_the_ip_limit_is_429(monkeypatch):
    async def body(op, c, outbox):
        for _ in range(5):
            await _forgot(c, OWNER)                     # same generic answer every time
        assert len(outbox) == 3                         # but only 3 tokens minted
        for i in range(5):
            await _forgot(c, "someone%d@x.bg" % i)
        limited = await c.post("/api/auth/forgot-password", json={"email": OWNER})
        assert limited.status_code == 429
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════════ 6. delivery
def _mail(token="tok-plain-0123456789-abcdefghij"):
    from app.services.password_reset import ResetMail
    return ResetMail(to=OWNER, user_id="u-owner", org_id=ORG_A, token=token)


def _clear_mail_env(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
              "SMTP_SECURITY", "APP_PUBLIC_URL", "PASSWORD_RESET_DEV_LOG_URL", "ENV"):
        monkeypatch.delenv(k, raising=False)


def test_unconfigured_mail_logs_a_warning_without_the_token(monkeypatch, caplog):
    from app.services import password_reset
    _clear_mail_env(monkeypatch)
    with caplog.at_level(logging.INFO):
        assert password_reset.deliver(_mail()) is False
    assert "PASSWORD_RESET_EMAIL_NOT_SENT" in caplog.text
    assert "tok-plain" not in caplog.text


def test_the_dev_flag_prints_the_url_only_outside_production(monkeypatch, caplog):
    from app.services import password_reset
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "1")
    with caplog.at_level(logging.INFO):
        password_reset.deliver(_mail())
    assert "/reset-password?token=tok-plain" in caplog.text
    caplog.clear()
    monkeypatch.setenv("ENV", "production")
    with caplog.at_level(logging.INFO):
        password_reset.deliver(_mail())
    assert "tok-plain" not in caplog.text and "PASSWORD_RESET_EMAIL_NOT_SENT" in caplog.text


def test_configured_mail_sends_the_public_reset_link(monkeypatch, caplog):
    from app.services import mailer, password_reset
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "BEG_Work <no-reply@begfull.bg>")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://work.begfull.bg/")
    sent = []

    class Fake:
        name = "fake"

        def send(self, to, subject, text):
            sent.append((to, subject, text))
    monkeypatch.setattr(password_reset, "get_mail_provider", lambda: Fake())
    with caplog.at_level(logging.INFO):
        assert password_reset.deliver(_mail()) is True
    (to, subject, text), = sent
    assert to == OWNER
    assert "https://work.begfull.bg/reset-password?token=tok-plain-0123456789-abcdefghij" in text
    assert "tok-plain" not in caplog.text
    # the real SMTP provider is selected from the environment
    cfg = mailer.SmtpConfig.from_env()
    assert cfg.host == "smtp.example.test" and cfg.port == 587 and cfg.security == "starttls"
    assert isinstance(mailer.get_mail_provider(), mailer.SmtpMailProvider)


def test_a_failing_provider_is_logged_not_raised(monkeypatch, caplog):
    from app.services import password_reset
    _clear_mail_env(monkeypatch)
    monkeypatch.setenv("APP_PUBLIC_URL", "https://work.begfull.bg")

    class Broken:
        name = "broken"

        def send(self, to, subject, text):
            raise ConnectionError("boom tok-plain")
    monkeypatch.setattr(password_reset, "get_mail_provider", lambda: Broken())
    with caplog.at_level(logging.INFO):
        assert password_reset.deliver(_mail()) is False
    assert "PASSWORD_RESET_EMAIL_FAILED" in caplog.text and "tok-plain" not in caplog.text


def test_the_token_indexes(monkeypatch):
    from app.services import password_reset

    async def body(op, c, outbox):
        await password_reset.ensure_indexes(op)
        info = await op.password_reset_tokens.index_information()
        assert info["token_hash_unique"]["unique"] is True
        assert info["token_hash_unique"]["key"] == [("token_hash", 1)]
        assert info["expires_at_ttl"]["expireAfterSeconds"] == 0
        assert info["user_id_used_at"]["key"] == [("user_id", 1), ("used_at", 1)]
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════ 7. the local recovery CLI
def _cli_args(*argv):
    from scripts.reset_user_password import parse_args
    return parse_args(list(argv))


def test_cli_dry_run_finds_the_owner_and_writes_nothing(monkeypatch, capsys):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        before = await op.users.find_one({"id": "u-owner"}, {"_id": 0})
        code = await cli.run(op, _cli_args("--email", "krum@BEGFULL.bg", "--dry-run"))
        assert code == cli.EXIT_OK
        assert await op.users.find_one({"id": "u-owner"}, {"_id": 0}) == before
        out = capsys.readouterr().out
        assert "DRY RUN" in out and "u-owner" in out
    scenario(monkeypatch, body)


def test_cli_resets_exactly_one_user_and_prints_no_secret(monkeypatch, capsys):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        await _forgot(c, OWNER)                             # an open e-mail link
        others = {u["id"]: u for u in await op.users.find(
            {"id": {"$ne": "u-owner"}}, {"_id": 0}).to_list(None)}
        monkeypatch.setattr("sys.stdin", io.StringIO(NEW_PW + "\n"))
        code = await cli.run(op, _cli_args("--email", " krum@begfull.bg", "--password-stdin"))
        assert code == cli.EXIT_OK
        owner = await op.users.find_one({"id": "u-owner"}, {"_id": 0})
        assert owner["password_reset_by"] == cli.RECOVERY_MARKER and owner["password_reset_at"]
        assert (await _login(c, OWNER, NEW_PW)).status_code == 200
        assert (await _login(c, OWNER, PW)).status_code == 401
        for u in await op.users.find({"id": {"$ne": "u-owner"}}, {"_id": 0}).to_list(None):
            assert u == others[u["id"]]                     # nobody else touched
        # the e-mailed link died with the recovery
        assert _is_generic_reset_failure(await _reset(c, outbox[0].token))
        assert await op.audit_logs.count_documents({"action": "password_recovery_cli",
                                                    "entity_id": "u-owner"}) == 1
        out = capsys.readouterr().out
        assert NEW_PW not in out and owner["password_hash"] not in out and "$2b$" not in out
    scenario(monkeypatch, body)


@pytest.mark.parametrize("email,expected", [
    ("nobody@nowhere.bg", "EXIT_NOT_FOUND"),
    (DISABLED, "EXIT_INACTIVE"),
    ("dup@a.bg", "EXIT_AMBIGUOUS"),
])
def test_cli_fails_closed(monkeypatch, capsys, email, expected):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        await op.users.insert_many([_user("u-dup1", ORG_A, "dup@a.bg"),
                                    _user("u-dup2", ORG_B, "Dup@A.bg")])
        before = await op.users.find({}, {"_id": 0}).sort("id", 1).to_list(None)
        for argv in (("--email", email, "--dry-run"),
                     ("--email", email, "--new-password", NEW_PW)):
            assert await cli.run(op, _cli_args(*argv)) == getattr(cli, expected)
        assert await op.users.find({}, {"_id": 0}).sort("id", 1).to_list(None) == before
        assert NEW_PW not in capsys.readouterr().out
    scenario(monkeypatch, body)


def test_cli_refuses_a_weak_password_before_touching_anything(monkeypatch, capsys):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        before = await op.users.find_one({"id": "u-owner"}, {"_id": 0})
        code = await cli.run(op, _cli_args("--email", OWNER, "--new-password", "weakpass"))
        assert code == cli.EXIT_INVALID_PASSWORD
        assert await op.users.find_one({"id": "u-owner"}, {"_id": 0}) == before
        assert "weakpass" not in capsys.readouterr().out
    scenario(monkeypatch, body)


def test_cli_rejects_mismatched_prompt_entries(monkeypatch):
    from scripts import reset_user_password as cli
    answers = iter([NEW_PW, NEW_PW + "x"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))

    async def body(op, c, outbox):
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_INVALID_PASSWORD
    scenario(monkeypatch, body)


def test_cli_usage_errors_exit_non_zero():
    from scripts import reset_user_password as cli
    assert cli.main([]) == cli.EXIT_USAGE                       # --email is required
    assert cli.main(["--email", "x@y.bg", "--password-stdin", "--new-password", "a"]) \
        == cli.EXIT_USAGE


def test_no_public_recovery_endpoint_exists():
    """The recovery path is the shell command only; the API offers token reset alone."""
    from app.routes import auth
    paths = sorted(r.path for r in auth.router.routes if "password" in r.path)
    assert paths == ["/admin/set-password/{user_id}", "/auth/change-password",
                     "/auth/forgot-password", "/auth/reset-password"]
