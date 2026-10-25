"""
AUTH-01 C01 — the CODEX CHANGES_REQUESTED findings F-01…F-08 on PR #56, each
proven against the real ``auth`` router on the shared harness of
``test_auth_01_password_recovery`` (mongomock + transaction test double; the
production transaction path when ``W0_03_REAL_MONGO_URL`` names a replica set).

    pytest tests/test_auth_01_c01_corrections.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27018/?replicaSet=rs0' pytest ... --noconftest
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_auth_01_password_recovery import (
    DISABLED, NEW_PW, ORG_A, ORG_B, OTHER, OWNER, PW, TECH, _cli_args, _forgot,
    _is_generic_reset_failure, _login, _reset, _user, force_no_transactions, scenario,
    type_password,
)


async def _events(op, event=None):
    flt = {"event": event} if event else {}
    return await op.auth_security_events.find(flt, {"_id": 0}).to_list(None)


async def _owner_state(op):
    user = await op.users.find_one({"id": "u-owner"}, {"_id": 0})
    tokens = await op.password_reset_tokens.find({"user_id": "u-owner"}, {"_id": 0}) \
        .sort("requested_at", 1).to_list(None)
    audit = await op.audit_logs.count_documents({"entity_id": "u-owner"})
    return user, tokens, audit


def _auth(token):
    return {"Authorization": "Bearer " + token}


# ═══════════════════════════════════════════════════════════════ F-01 atomic
@pytest.mark.parametrize("stage", ["user_update", "revoke_remaining", "audit"])
def test_f01_a_failed_reset_changes_nothing(monkeypatch, stage):
    """Inject a failure at each write after the claim: the whole reset rolls back."""
    from app.services import password_reset
    from app.tenancy import data_access

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        token = outbox[0].token
        user0, tokens0, audit0 = await _owner_state(op)

        boom = RuntimeError("injected " + stage)
        if stage == "audit":
            async def failing_audit(*a, **kw):
                raise boom
            monkeypatch.setattr(password_reset, "log_audit", failing_audit)
        else:
            name, method = (("users", "update_one") if stage == "user_update"
                            else ("password_reset_tokens", "update_many"))
            original = getattr(data_access.TenantCollection, method)

            async def failing(self, *a, **kw):
                if self.name == name:
                    raise boom
                return await original(self, *a, **kw)
            monkeypatch.setattr(data_access.TenantCollection, method, failing)

        r = await _reset(c, token)
        assert r.status_code == 503, r.text
        assert r.json()["detail"]["error_code"] == "RESET_NOT_COMPLETED"
        user1, tokens1, audit1 = await _owner_state(op)
        assert user1 == user0                       # old hash, same auth_version
        assert tokens1 == tokens0                   # the token is still unused
        assert audit1 == audit0                     # no "completed" audit row
        assert len(await _events(op, "reset_not_completed")) == 1
    scenario(monkeypatch, body)


def test_f01_after_a_rolled_back_reset_the_same_link_still_works(monkeypatch):
    from app.services import password_reset

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        real_audit = password_reset.log_audit
        calls = {"n": 0}

        async def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("injected once")
            return await real_audit(*a, **kw)
        monkeypatch.setattr(password_reset, "log_audit", flaky)
        assert (await _reset(c, outbox[0].token)).status_code == 503
        assert (await _login(c, OWNER, PW)).status_code == 200
        assert (await _reset(c, outbox[0].token)).status_code == 200
        assert (await _login(c, OWNER, NEW_PW)).status_code == 200
    scenario(monkeypatch, body)


def test_f01_a_failed_recovery_cli_changes_nothing(monkeypatch, capsys):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        user0, tokens0, audit0 = await _owner_state(op)

        def boom():
            raise RuntimeError("injected at the audit write")
        monkeypatch.setattr(cli.socket, "gethostname", boom)
        type_password(monkeypatch)
        code = await cli.run(op, _cli_args("--email", OWNER))
        assert code == cli.EXIT_WRITE_FAILED
        assert "NOTHING CHANGED" in capsys.readouterr().out
        assert await _owner_state(op) == (user0, tokens0, audit0)
        assert (await _login(c, OWNER, PW)).status_code == 200
    scenario(monkeypatch, body)


def test_f01_a_failed_request_leaves_no_token_and_keeps_older_links(monkeypatch):
    from app.services import password_reset

    async def body(op, c, outbox):
        await _forgot(c, OWNER)                        # link 1, delivered
        first = outbox[0].token

        real_audit = password_reset.log_audit

        async def failing_audit(*a, **kw):
            raise RuntimeError("injected at request audit")
        monkeypatch.setattr(password_reset, "log_audit", failing_audit)
        await _forgot(c, OWNER)                        # link 2 fails to commit
        monkeypatch.setattr(password_reset, "log_audit", real_audit)
        assert len(outbox) == 1                        # nothing was sent for link 2
        rows = await op.password_reset_tokens.find({"user_id": "u-owner"}).to_list(None)
        assert len(rows) == 1                          # no half-created token
        assert len(await _events(op, "forgot_processing_failed")) == 1
        assert (await _reset(c, first)).status_code == 200      # link 1 still works
    scenario(monkeypatch, body)


def test_f01_without_transactions_everything_is_refused_and_nothing_written(monkeypatch):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        token = outbox[0].token
        state0 = await _owner_state(op)
        force_no_transactions(monkeypatch)
        r = await _reset(c, token)
        assert r.status_code == 503 and r.json()["detail"]["error_code"] == "RESET_NOT_COMPLETED"
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_NO_TRANSACTIONS
        await _forgot(c, TECH)                         # cannot even mint a token
        assert len(outbox) == 1
        assert await op.password_reset_tokens.count_documents({"user_id": "u-tech"}) == 0
        assert await _owner_state(op) == state0
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════════ F-02 old sessions die
def test_f02_a_self_service_reset_ends_older_sessions(monkeypatch):
    async def body(op, c, outbox):
        old = (await _login(c, OWNER)).json()["token"]
        assert (await c.get("/api/auth/me", headers=_auth(old))).status_code == 200
        await _forgot(c, OWNER)
        assert (await _reset(c, outbox[0].token)).status_code == 200
        r = await c.get("/api/auth/me", headers=_auth(old))
        assert r.status_code == 401 and r.json()["detail"] == "Session expired"
        new = (await _login(c, OWNER, NEW_PW)).json()["token"]
        assert (await c.get("/api/auth/me", headers=_auth(new))).status_code == 200
        assert (await op.users.find_one({"id": "u-owner"}))["auth_version"] == 1
    scenario(monkeypatch, body)


def test_f02_owner_recovery_ends_older_sessions(monkeypatch):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        old = (await _login(c, OWNER)).json()["token"]
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_OK
        assert (await c.get("/api/auth/me", headers=_auth(old))).status_code == 401
        new = (await _login(c, OWNER, NEW_PW)).json()["token"]
        assert (await c.get("/api/auth/me", headers=_auth(new))).status_code == 200
    scenario(monkeypatch, body)


def test_f02_change_password_and_admin_reset_keep_their_semantics(monkeypatch):
    async def body(op, c, outbox):
        tech = (await _login(c, TECH)).json()["token"]
        owner = (await _login(c, OWNER)).json()["token"]
        r = await c.post("/api/admin/set-password/u-tech", json={"new_password": NEW_PW},
                         headers=_auth(owner))
        assert r.status_code == 200
        assert (await c.get("/api/auth/me", headers=_auth(tech))).status_code == 200
        r = await c.post("/api/auth/change-password",
                         json={"current_password": PW, "new_password": NEW_PW},
                         headers=_auth(owner))
        assert r.status_code == 200
        assert (await c.get("/api/auth/me", headers=_auth(owner))).status_code == 200
    scenario(monkeypatch, body)


def test_f02_tokens_from_before_this_change_still_work(monkeypatch):
    """A token without ``av`` and a user without ``auth_version`` are both version 0."""
    from app.deps.auth import create_token

    async def body(op, c, outbox):
        legacy = create_token({"user_id": "u-owner", "org_id": ORG_A, "role": "Owner"})
        assert (await c.get("/api/auth/me", headers=_auth(legacy))).status_code == 200
        forged = create_token({"user_id": "u-owner", "org_id": ORG_A, "role": "Owner",
                               "av": "x"})
        assert (await c.get("/api/auth/me", headers=_auth(forged))).status_code == 401
    scenario(monkeypatch, body)


# ═════════════════════════════════════════════ F-03 one email = one login
def test_f03_an_email_of_another_organization_cannot_be_created(monkeypatch):
    """R0-04: F-03 is the R0-03 rule — 409 EMAIL_EXISTS, no company named."""
    async def body(op, c, outbox):
        h = _auth((await _login(c, OTHER)).json()["token"])             # org B owner
        payload = {"password": PW, "first_name": "N", "last_name": "U", "role": "Viewer"}
        for spelling in (OWNER, " KRUM@BEGFULL.BG "):                    # lives in org A
            r = await c.post("/api/users", json={**payload, "email": spelling}, headers=h)
            assert r.status_code == 409 and r.json()["detail"]["error_code"] == "EMAIL_EXISTS"
            assert ORG_A not in r.text
        assert await op.users.count_documents({"org_id": ORG_B}) == 1
        # login and recovery for the owner keep working: still exactly one row
        assert (await _login(c, "krum@begfull.bg")).status_code == 200
        await _forgot(c, OWNER)
        assert len(outbox) == 1
    scenario(monkeypatch, body)


def test_f03_onboarding_refuses_a_case_variant_of_an_existing_login(monkeypatch):
    from app.tenancy.onboarding import OnboardingRefused, onboard_tenant

    async def body(op, c, outbox):
        sysdb = op.client[op.name + "_sys"]
        with pytest.raises(OnboardingRefused) as exc:
            await onboard_tenant(op, sysdb, org_name="Clone Co",
                                 owner_email=" KRUM@BEGFULL.BG ", owner_password_hash="x",
                                 owner_first_name="Clone")
        assert exc.value.code == "EMAIL_EXISTS"
        assert await op.organizations.count_documents({"name": "Clone Co"}) == 0
    scenario(monkeypatch, body)


def test_f03_one_identity_implementation_and_one_duplicates_report():
    """R0-04: R0-03 is the single source for identity; PR #56's copies are gone."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert importlib.util.find_spec("app.utils.email_identity") is None
    assert not (root / "scripts" / "auth_duplicate_emails_report.py").exists()
    assert (root / "scripts" / "r0_03_email_duplicates_report.py").exists()
    from app.tenancy import data_access
    assert not hasattr(data_access, "resolve_identities_by_email")
    from app.services import password_reset
    from app.tenancy import identity
    assert password_reset.users_with_email is identity.users_with_email
    assert password_reset.normalize_email is identity.normalize_email
    guard = (root / "scripts" / "w0_03e_a2c_tenant_boundary_guard.py").read_text()
    assert "auth_duplicate_emails_report" not in guard


# ═══════════════════════════════════════════════════════════ F-04 rate limits
def _request(peer, headers=None):
    from starlette.requests import Request
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "client": (peer, 1234), "headers": raw,
                    "method": "POST", "path": "/"})


def test_f04_proxy_headers_count_only_from_a_trusted_proxy(monkeypatch):
    from app.utils.client_ip import client_ip
    spoof = {"X-Forwarded-For": "6.6.6.6", "X-Real-IP": "7.7.7.7"}
    assert client_ip(_request("203.0.113.9", spoof), trusted="") == "203.0.113.9"
    assert client_ip(_request("203.0.113.9", spoof), trusted="172.16.0.0/12") == "203.0.113.9"
    nginx = "172.18.0.5"
    assert client_ip(_request(nginx, {"X-Forwarded-For": "6.6.6.6, 198.51.100.7"}),
                     trusted="172.16.0.0/12") == "198.51.100.7"      # right-most untrusted
    assert client_ip(_request(nginx, {"X-Forwarded-For": "198.51.100.7, 172.18.0.9"}),
                     trusted="172.16.0.0/12") == "198.51.100.7"      # skip trusted hops
    assert client_ip(_request(nginx, {"X-Real-IP": "198.51.100.8"}),
                     trusted="172.16.0.0/12") == "198.51.100.8"
    assert client_ip(_request(nginx), trusted="172.16.0.0/12") == nginx
    assert client_ip(_request(nginx, {"X-Forwarded-For": "garbage"}),
                     trusted="172.16.0.0/12") == nginx


def test_f04_spoofed_forwarded_for_does_not_escape_the_ip_limit(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)

    async def body(op, c, outbox):
        for i in range(10):
            r = await c.post("/api/auth/forgot-password", json={"email": "x%d@y.bg" % i},
                             headers={"X-Forwarded-For": "10.9.8.%d" % i})
            assert r.status_code == 200
        r = await c.post("/api/auth/forgot-password", json={"email": "z@y.bg"},
                         headers={"X-Forwarded-For": "10.9.8.250"})
        assert r.status_code == 429
    scenario(monkeypatch, body)


def test_f04_counters_are_shared_between_app_instances(monkeypatch):
    import httpx
    from tests.test_auth_01_password_recovery import _app

    async def body(op, c, outbox):
        sysdb = op.client[op.name + "_sys"]
        second = _app(monkeypatch, op, sysdb, outbox)       # another worker, same database
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=second),
                                     base_url="http://worker2") as c2:
            for i in range(10):
                client = c if i % 2 else c2
                r = await client.post("/api/auth/forgot-password", json={"email": "s%d@y.bg" % i})
                assert r.status_code == 200
            assert (await c.post("/api/auth/forgot-password", json={"email": "a@y.bg"})).status_code == 429
            assert (await c2.post("/api/auth/forgot-password", json={"email": "b@y.bg"})).status_code == 429
    scenario(monkeypatch, body)


def test_f04_a_window_expires(monkeypatch):
    from app.services import rate_limit

    async def body(op, c, outbox):
        t0 = datetime(2026, 10, 17, 10, 0, 0, tzinfo=timezone.utc)
        for _ in range(3):
            assert (await rate_limit.hit(op, "t", "k", 3, 900, now=t0)).allowed
        over = await rate_limit.hit(op, "t", "k", 3, 900, now=t0)
        assert not over.allowed and over.first_rejection
        again = await rate_limit.hit(op, "t", "k", 3, 900, now=t0)
        assert not again.allowed and not again.first_rejection
        later = await rate_limit.hit(op, "t", "k", 3, 900, now=t0 + timedelta(seconds=900))
        assert later.allowed and later.count == 1
        docs = await op.auth_rate_limits.find({}).to_list(None)
        assert all("k" not in d["_id"].split(":")[1] for d in docs)   # key is a keyed hash
        assert all(d["expires_at"] for d in docs)
    scenario(monkeypatch, body)


# ═════════════════════════════════════════ F-05 same work before the response
def test_f05_the_handler_does_identical_work_for_every_kind_of_email(monkeypatch):
    from fastapi import BackgroundTasks

    from app.routes import auth
    from app.services import password_reset
    from app.routes.auth import ForgotPasswordRequest

    class Recorder:
        def __init__(self, real):
            self.real, self.ops = real, []

        def __getattr__(self, name):
            coll = getattr(self.real, name)
            ops = self.ops

            class C:
                def __getattr__(self, method):
                    fn = getattr(coll, method)

                    def call(*a, **kw):
                        ops.append((name, method))
                        return fn(*a, **kw)
                    return call
            return C()

    async def body(op, c, outbox):
        await op.users.insert_many([_user("u-d1", ORG_A, "dup@a.bg"),
                                    _user("u-d2", ORG_B, "DUP@a.bg")])
        shapes = {}
        for kind, email in (("unknown", "nobody@nowhere.bg"), ("disabled", DISABLED),
                            ("ambiguous", "dup@a.bg"), ("valid", OWNER)):
            rec = Recorder(op)
            monkeypatch.setattr(auth, "db", rec)
            tasks = BackgroundTasks()
            resp = await auth.forgot_password(ForgotPasswordRequest(email=email),
                                              _request("192.0.2.%d" % len(shapes)), tasks)
            shapes[kind] = (json.dumps(resp, sort_keys=True), tuple(rec.ops),
                            tuple(t.func for t in tasks.tasks))
        assert len(set(shapes.values())) == 1, shapes
        _body, ops, funcs = shapes["valid"]
        assert ops == (("auth_rate_limits", "find_one_and_update"),)
        assert funcs == (password_reset.process_forgot_request,)
        assert await op.password_reset_tokens.count_documents({}) == 0   # nothing yet
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════════════ F-06 delivery
@pytest.mark.parametrize("outcome,event", [("failed", "reset_delivery_failed"),
                                           ("not_configured", "reset_delivery_not_configured")])
def test_f06_an_undelivered_link_is_revoked_and_older_links_survive(monkeypatch, outcome, event):
    async def body(op, c, outbox):
        await _forgot(c, OWNER)                              # link 1 delivered
        first = outbox[0].token
        outbox.outcome = outcome
        await _forgot(c, OWNER)                              # link 2 NOT delivered
        rows = await op.password_reset_tokens.find({"user_id": "u-owner"}, {"_id": 0}) \
            .sort("requested_at", 1).to_list(None)
        assert [r["delivery_status"] for r in rows] == ["sent", outcome]
        assert rows[0]["used_at"] is None                    # link 1 untouched
        assert rows[1]["used_at"] is not None
        assert rows[1]["revoked_reason"] == "delivery_" + outcome
        assert _is_generic_reset_failure(await _reset(c, outbox[1].token))
        assert len(await _events(op, event)) == 1
        assert await op.audit_logs.count_documents(
            {"action": "password_reset_link_not_delivered", "entity_id": "u-owner"}) == 1
        assert (await _reset(c, first)).status_code == 200   # the working link still works
    scenario(monkeypatch, body)


def test_f06_overlapping_deliveries_both_remain_usable(monkeypatch):
    """RC-AUTH-01 (supersedes the old 'older_link_is_superseded' behaviour):
    two successful deliveries must leave BOTH links consumable. The old F-06
    semantics (newer-sent revokes older-sent) was itself the RC-AUTH-01 defect
    and is explicitly reversed. A ``reset_password`` call still revokes every
    remaining open token at use-time; the TTL (30 min) collects surplus."""
    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        await _forgot(c, OWNER)
        rows = await op.password_reset_tokens.find({"user_id": "u-owner"}, {"_id": 0}) \
            .sort("requested_at", 1).to_list(None)
        assert [r["delivery_status"] for r in rows] == ["sent", "sent"]
        assert rows[0]["used_at"] is None and rows[1]["used_at"] is None
        assert rows[0].get("revoked_reason") is None
        assert rows[1].get("revoked_reason") is None
        assert await op.audit_logs.count_documents(
            {"action": "password_reset_link_sent", "entity_id": "u-owner"}) == 2
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════════════ F-07 CLI secrets
def test_f07_the_cli_has_no_password_option_and_needs_a_terminal(monkeypatch, capsys):
    from scripts import reset_user_password as cli
    with pytest.raises(SystemExit):
        cli.parse_args(["--help"])
    help_text = capsys.readouterr().out
    assert "--new-password" not in help_text and "--password-stdin" not in help_text
    assert "password" not in " ".join(a for a in help_text.split() if a.startswith("--"))

    async def body(op, c, outbox):
        before = await op.users.find_one({"id": "u-owner"}, {"_id": 0})
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
        code = await cli.run(op, _cli_args("--email", OWNER))
        assert code == cli.EXIT_USAGE
        assert "docker exec -it" in capsys.readouterr().out
        assert await op.users.find_one({"id": "u-owner"}, {"_id": 0}) == before
    scenario(monkeypatch, body)


# ═════════════════════════════════════════════════ F-08 durable security events
def test_f08_every_denial_leaves_one_durable_event(monkeypatch):
    from app.services.auth_events import keyed_ref

    async def body(op, c, outbox):
        await op.users.insert_many([_user("u-d1", ORG_A, "dup@a.bg"),
                                    _user("u-d2", ORG_B, "DUP@a.bg")])
        await _forgot(c, "nobody@nowhere.bg")
        await _forgot(c, "dup@a.bg")
        await _forgot(c, DISABLED)
        assert (await _reset(c, "x" * 43)).status_code == 400
        await _forgot(c, OWNER)
        token = outbox[0].token
        assert (await _reset(c, token)).status_code == 200
        assert (await _reset(c, token, "Another-Pass-99!")).status_code == 400   # replay
        await _forgot(c, TECH)
        await op.password_reset_tokens.update_one(
            {"user_id": "u-tech"},
            {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        assert (await _reset(c, outbox[1].token)).status_code == 400            # expired
        assert (await _login(c, "dup@a.bg")).status_code == 409                  # ambiguous
        expected = {"forgot_no_match": 1, "forgot_ambiguous": 1, "forgot_not_eligible": 1,
                    "reset_token_invalid": 1, "reset_token_replay": 1,
                    "reset_token_expired": 1, "login_ambiguous": 1}
        got = {}
        for e in await _events(op):
            got[e["event"]] = got.get(e["event"], 0) + 1
        assert got == expected, got
        no_match = (await _events(op, "forgot_no_match"))[0]
        assert no_match["subject"] == keyed_ref("nobody@nowhere.bg")
        assert no_match["expires_at"] - no_match["ts"] == timedelta(days=180)
        replay = (await _events(op, "reset_token_replay"))[0]
        assert replay["user_id"] == "u-owner" and replay["org_id"] == ORG_A
    scenario(monkeypatch, body)


def test_f08_throttling_is_recorded_once_per_window(monkeypatch):
    async def body(op, c, outbox):
        for _ in range(6):
            await _forgot(c, OWNER)                 # per-email limit is 3
        assert len(outbox) == 3
        assert len(await _events(op, "rate_limited_email")) == 1
        for i in range(8):
            await c.post("/api/auth/forgot-password", json={"email": "q%d@y.bg" % i})
        assert len(await _events(op, "rate_limited_ip")) == 1
    scenario(monkeypatch, body)


def test_f08_events_hold_no_email_token_or_password(monkeypatch):
    async def body(op, c, outbox):
        await _forgot(c, "nobody@nowhere.bg")
        await _forgot(c, OWNER)
        token = outbox[0].token
        await _reset(c, token)
        await _reset(c, token, "Another-Pass-99!")
        await _reset(c, "y" * 50)
        await _login(c, OWNER, "Wrong-Pass-00!")
        dump = json.dumps(await op.auth_security_events.find({}, {"_id": 0}).to_list(None)
                          + await op.auth_rate_limits.find({}).to_list(None), default=str)
        for secret in ("nobody@nowhere.bg", "krum@begfull.bg", OWNER, token, "y" * 50,
                       NEW_PW, "Another-Pass-99!", PW, "Wrong-Pass-00!"):
            assert secret.lower() not in dump.lower(), secret
    scenario(monkeypatch, body)
