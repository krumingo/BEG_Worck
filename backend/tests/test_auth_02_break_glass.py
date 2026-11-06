"""
AUTH-02 — break-glass recovery CLI with a named operator and a reason (Р19),
plus the FLOW Guard findings FG-8…FG-11 and FG-16 on PR #56.

Proven on the AUTH-01 harness (``mongomock_motor``; the production transaction
path on a disposable replica set when ``W0_03_REAL_MONGO_URL`` is set):

* no ``--operator`` / ``--reason`` (or a blank, oversized, control-character,
  hash-like or password-containing one) → refused, no prompt reached where it
  matters, nothing written;
* success → ONE canonical AuditEvent with ``actor_type=human``, the operator,
  the reason, ``source_channel=break_glass_cli`` and retention R1 (FG-9); the
  legacy row names the operator; one in-app notification per active Owner,
  committed in the same transaction; no password and no hash anywhere;
* failure inside the transaction → no hash change, no event, no notification;
* FG-8: a non-Owner target is refused (dry run and real run), nothing written;
* FG-11: admin set-password ends the target's older sessions and revokes the
  target's open e-mail links in one transaction; a failure changes nothing;
* FG-10: security events are kept 730 days;
* FG-16: no literal HMAC key outside an explicitly non-production deployment.

    pytest tests/test_auth_02_break_glass.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?replicaSet=rs0' pytest ... --noconftest
"""
import json
from datetime import timedelta

import pytest

from tests.test_auth_01_password_recovery import (
    NEW_PW, OPERATOR, ORG_A, OWNER, PW, REASON, TECH, _cli_args, _forgot, _login, _reset,
    _user, scenario, type_password,
)


def _auth(token):
    return {"Authorization": "Bearer " + token}


async def _state(op):
    """Everything a recovery may write, for byte-equal before/after checks."""
    out = {}
    for name in ("users", "audit_logs", "audit_events", "notifications",
                 "password_reset_tokens"):
        out[name] = await op[name].find({}, {"_id": 0}).sort("id", 1).to_list(None)
    return out


def _dump(value) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


# ═══════════════════════════════════════════ Р19: operator + reason required
def test_main_without_operator_or_reason_is_a_usage_error():
    from scripts import reset_user_password as cli
    assert cli.main(["--email", OWNER, "--reason", REASON]) == cli.EXIT_USAGE
    assert cli.main(["--email", OWNER, "--operator", OPERATOR]) == cli.EXIT_USAGE
    assert cli.main(["--email", OWNER]) == cli.EXIT_USAGE


@pytest.mark.parametrize("operator,reason", [
    ("   ", REASON),                                   # blank operator
    (OPERATOR, "   "),                                 # blank reason
    ("X", REASON),                                     # too short
    ("O" * 121, REASON),                               # too long
    (OPERATOR, "short"),                               # reason too short
    (OPERATOR, "r" * 501),                             # reason too long
    ("Ivan\nPetrov", REASON),                          # control character
    (OPERATOR, "locked out\x1b[2J clear screen"),      # control character
    (OPERATOR, "old hash was $2b$12$abcdefghijklmnop"),  # looks like a hash
])
def test_invalid_attribution_is_refused_before_anything(monkeypatch, capsys, operator, reason):
    from scripts import reset_user_password as cli

    def no_prompt(prompt=""):
        raise AssertionError("the password prompt must not be reached")

    async def body(op, c, outbox):
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(cli.getpass, "getpass", no_prompt)
        before = await _state(op)
        for extra in ((), ("--dry-run",)):
            args = _cli_args("--email", OWNER, "--operator", operator, "--reason", reason,
                             *extra)
            assert await cli.run(op, args) == cli.EXIT_USAGE
        assert await _state(op) == before
        assert "Nothing changed" in capsys.readouterr().out
    scenario(monkeypatch, body)


def test_a_reason_that_contains_the_new_password_is_refused(monkeypatch, capsys):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        before = await _state(op)
        type_password(monkeypatch)
        args = _cli_args("--email", OWNER, "--reason", "reset to " + NEW_PW.lower() + " today")
        assert await cli.run(op, args) == cli.EXIT_INVALID_PASSWORD
        assert await _state(op) == before
        assert NEW_PW not in capsys.readouterr().out
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════════════════ success
def test_success_records_operator_reason_r1_and_notifies_every_owner(monkeypatch, capsys):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        await op.users.insert_many([
            _user("u-owner2", ORG_A, "co-owner@a.bg"),
            _user("u-owner-off", ORG_A, "old-owner@a.bg", active=False),
        ])
        await _forgot(c, OWNER)                              # an open e-mail link
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_OK
        user = await op.users.find_one({"id": "u-owner"}, {"_id": 0})

        events = await op.audit_events.find({"action": "user.password_recovery_cli"},
                                            {"_id": 0}).to_list(None)
        assert len(events) == 1
        e = events[0]
        assert (e["actor_type"], e["actor_id"], e["reason"]) == \
            ("human", "break_glass:" + OPERATOR, REASON)
        assert (e["retention_class"], e["source_channel"], e["entity_id"], e["tenant_id"]) == \
            ("R1", "break_glass_cli", "u-owner", ORG_A)
        diff = e["structured_diff"]
        assert diff["operator"] == OPERATOR and diff["target_role"] == "Owner"
        assert diff["notified_owner_ids"] == ["u-owner", "u-owner2"]

        legacy = await op.audit_logs.find_one({"action": "password_recovery_cli"}, {"_id": 0})
        assert legacy["changes"]["operator"] == OPERATOR
        assert legacy["changes"]["reason"] == REASON

        notes = await op.notifications.find({}, {"_id": 0}).sort("user_id", 1).to_list(None)
        assert [n["user_id"] for n in notes] == ["u-owner", "u-owner2"]   # active Owners only
        for n in notes:
            assert n["org_id"] == ORG_A and n["is_read"] is False
            assert n["type"] == cli.NOTIFICATION_TYPE
            assert OPERATOR in n["message"] and REASON in n["message"]
            assert n["data"]["audit_event_id"] == e["event_id"]
        # no password, no hash in anything the run wrote or printed
        written = _dump([events, legacy, notes]) + capsys.readouterr().out
        assert NEW_PW not in written and PW not in written
        assert user["password_hash"] not in written and "$2b$" not in written
        # the reset itself
        assert (await _login(c, OWNER, NEW_PW)).status_code == 200
        assert outbox and (await _reset(c, outbox[0].token)).status_code == 400
    scenario(monkeypatch, body)


def test_owner_email_is_sent_after_commit_when_configured(monkeypatch, capsys):
    from app.services import mailer
    from scripts import reset_user_password as cli
    sent = []

    class Fake:
        name = "fake"

        def send(self, to, subject, text):
            sent.append((to, subject, text))

    async def body(op, c, outbox):
        monkeypatch.setattr(mailer, "get_mail_provider", lambda: Fake())
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_OK
        assert [s[0] for s in sent] == [OWNER]
        assert OPERATOR in sent[0][2] and REASON in sent[0][2] and NEW_PW not in sent[0][2]
        assert "Owner e-mail: sent." in capsys.readouterr().out
    scenario(monkeypatch, body)


def test_a_failing_email_does_not_undo_the_committed_notice(monkeypatch, capsys):
    from app.services import mailer
    from scripts import reset_user_password as cli

    class Broken:
        name = "broken"

        def send(self, to, subject, text):
            raise OSError("smtp down")

    async def body(op, c, outbox):
        monkeypatch.setattr(mailer, "get_mail_provider", lambda: Broken())
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_OK
        assert await op.notifications.count_documents({"user_id": "u-owner"}) == 1
        assert "WARNING: Owner e-mail failed" in capsys.readouterr().out
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════════════════ failure
@pytest.mark.parametrize("where", ["audit", "notification"])
def test_a_failure_in_the_transaction_writes_nothing(monkeypatch, where):
    from app.services import user_role_policy
    from app.tenancy import data_access
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        before = await _state(op)
        if where == "audit":
            async def failing(*a, **kw):
                raise RuntimeError("injected at the AuditEvent")
            monkeypatch.setattr(user_role_policy, "audit_user_change", failing)
        else:
            real = data_access.TenantCollection.insert_one

            async def failing(self, doc, **kw):
                if self.name == "notifications":
                    raise RuntimeError("injected at the notification")
                return await real(self, doc, **kw)
            monkeypatch.setattr(data_access.TenantCollection, "insert_one", failing)
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_WRITE_FAILED
        assert await _state(op) == before
        assert (await _login(c, OWNER, PW)).status_code == 200
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════════ FG-8: Owner only
def test_fg8_a_non_owner_target_is_refused(monkeypatch, capsys):
    from scripts import reset_user_password as cli

    async def body(op, c, outbox):
        before = await _state(op)
        type_password(monkeypatch)
        for extra in (("--dry-run",), ()):
            assert await cli.run(op, _cli_args("--email", TECH, *extra)) == cli.EXIT_NOT_OWNER
        assert await _state(op) == before
        assert "NOT AN OWNER" in capsys.readouterr().out
    scenario(monkeypatch, body)


def test_fg8_a_role_change_during_the_run_writes_nothing(monkeypatch):
    """The role is re-checked inside the transaction (filter ``role: Owner``)."""
    from scripts import reset_user_password as cli
    real = cli.apply_reset

    async def demote_then_apply(db, target, *a, **kw):
        await db.users.update_one({"id": target["id"]}, {"$set": {"role": "Admin"}})
        return await real(db, target, *a, **kw)

    async def body(op, c, outbox):
        monkeypatch.setattr(cli, "apply_reset", demote_then_apply)
        type_password(monkeypatch)
        assert await cli.run(op, _cli_args("--email", OWNER)) == cli.EXIT_WRITE_FAILED
        assert await op.audit_events.count_documents({}) == 0
        assert await op.notifications.count_documents({}) == 0
        assert (await _login(c, OWNER, PW)).status_code == 200
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════ FG-11: admin reset is atomic
def test_fg11_admin_reset_ends_old_sessions_and_revokes_open_links(monkeypatch):
    async def body(op, c, outbox):
        tech = (await _login(c, TECH)).json()["token"]
        owner = (await _login(c, OWNER)).json()["token"]
        await _forgot(c, TECH)
        link = outbox[-1].token
        r = await c.post("/api/admin/set-password/u-tech", json={"new_password": NEW_PW},
                         headers=_auth(owner))
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert (await c.get("/api/auth/me", headers=_auth(tech))).status_code == 401
        assert (await _reset(c, link, "Another-Pass-99!")).status_code == 400
        row = await op.password_reset_tokens.find_one({"user_id": "u-tech"}, {"_id": 0})
        assert row["revoked_reason"] == "admin_password_reset"
        assert (await _login(c, TECH, NEW_PW)).status_code == 200
        ev = await op.audit_events.find({"action": "user.admin_password_reset"},
                                        {"_id": 0}).to_list(None)
        assert len(ev) == 1 and ev[0]["actor_id"] == "u-owner"
        assert await op.audit_logs.count_documents({"action": "admin_password_reset"}) == 1
    scenario(monkeypatch, body)


def test_fg11_a_failing_admin_reset_changes_nothing(monkeypatch):
    from app.services import password_reset

    async def body(op, c, outbox):
        tech = (await _login(c, TECH)).json()["token"]
        owner = (await _login(c, OWNER)).json()["token"]
        await _forgot(c, TECH)
        before = await _state(op)

        async def failing(*a, **kw):
            raise RuntimeError("injected at the AuditEvent")
        monkeypatch.setattr(password_reset, "audit_user_change", failing)
        r = await c.post("/api/admin/set-password/u-tech", json={"new_password": NEW_PW},
                         headers=_auth(owner))
        assert r.status_code == 503 and r.json()["detail"]["error_code"] == "RESET_NOT_COMPLETED"
        assert await _state(op) == before
        assert (await c.get("/api/auth/me", headers=_auth(tech))).status_code == 200
        assert (await _login(c, TECH, PW)).status_code == 200
    scenario(monkeypatch, body)


# ═══════════════════════════════════════════════ FG-10 / FG-16
def test_fg10_security_events_are_kept_two_years():
    from app.services import auth_events
    assert auth_events.RETENTION == timedelta(days=730)


@pytest.mark.parametrize("env,environment,allowed", [
    (None, None, False),                    # unlabeled → treated as production
    ("production", None, False),
    (None, "prod", False),
    ("development", "production", False),   # contradiction → production
    ("something", None, False),             # unknown label
    ("development", None, True),
    ("test", "test", True),
])
def test_fg16_no_literal_key_outside_explicit_non_production(monkeypatch, env, environment,
                                                            allowed):
    from app.services import auth_events
    for key in ("AUTH_EVENT_HMAC_KEY", "JWT_SECRET", "ENV", "ENVIRONMENT"):
        monkeypatch.delenv(key, raising=False)
    if env:
        monkeypatch.setenv("ENV", env)
    if environment:
        monkeypatch.setenv("ENVIRONMENT", environment)
    if allowed:
        assert len(auth_events.keyed_ref("a@b.bg")) == 32
    else:
        with pytest.raises(auth_events.AuthEventKeyMissing):
            auth_events.keyed_ref("a@b.bg")
    monkeypatch.setenv("JWT_SECRET", "configured")
    assert len(auth_events.keyed_ref("a@b.bg")) == 32   # a configured key always works
