"""
AUTH-01 RC — the CODEX INTEGRATED-RC-2026-10-25 CHANGES_REQUESTED findings on
PR #56 head ``8e435a0e``: RC-AUTH-01 (overlapping successful deliveries must
not revoke each other) and RC-AUTH-02 (dev-only reset-URL logging must be
fail-closed against production markers).

Harness is the same shared seed/HTTP double from
``test_auth_01_password_recovery``; mongomock by default, real transactions
when ``W0_03_REAL_MONGO_URL`` names a replica set.

    pytest tests/test_auth_01_rc_corrections.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27018/?replicaSet=rs0' \
        pytest tests/test_auth_01_rc_corrections.py -v --noconftest
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_auth_01_password_recovery import (
    GENERIC, NEW_PW, ORG_A, OWNER, _forgot, _is_generic_reset_failure, _mail,
    _reset, scenario,
)


# ---------------------------------------------------------------------------
# RC-AUTH-01 — settle_delivery must preserve overlapping delivered siblings
# ---------------------------------------------------------------------------


async def _tokens_for_owner(op):
    return await op.password_reset_tokens.find(
        {"user_id": "u-owner"}, {"_id": 0}
    ).sort("requested_at", 1).to_list(None)


async def _usable_delivered(op):
    """Rows that are still consumable: delivery succeeded AND token not used."""
    rows = await _tokens_for_owner(op)
    return [t for t in rows
            if t.get("used_at") is None
            and t.get("delivery_status") in ("sent", "dev_logged")]


def test_rc_auth_01_two_overlapping_deliveries_both_remain_usable(monkeypatch):
    """A → request B → deliver A → deliver B must leave BOTH links usable."""
    async def body(op, c, outbox):
        await _forgot(c, OWNER)
        await _forgot(c, OWNER)
        assert len(outbox) == 2
        tokens = await _tokens_for_owner(op)
        assert len(tokens) == 2
        for t in tokens:
            assert t["delivery_status"] == "sent"
            assert t["used_at"] is None
            assert t.get("revoked_reason") is None
        usable = await _usable_delivered(op)
        assert len(usable) == 2, (
            "Both overlapping successful deliveries must stay consumable; "
            "RC-AUTH-01 reproduction expected ≥1 usable link, we now keep 2.")
    scenario(monkeypatch, body)


def test_rc_auth_01_reverse_order_also_keeps_both_links_usable(monkeypatch):
    """Mint A, mint B directly, then deliver B first and A after → both usable."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        # Mint two tokens directly to control ``requested_at`` ordering, and
        # settle delivery manually in reverse order (B before A).
        a_mail = await pr.request_reset(op, OWNER, "ip-x")
        b_mail = await pr.request_reset(op, OWNER, "ip-x")
        assert a_mail is not None and b_mail is not None
        assert a_mail.requested_at <= b_mail.requested_at
        # If both were minted inside the same clock tick, give b_mail a
        # strictly-newer requested_at by bumping its row + the ResetMail copy.
        if a_mail.requested_at >= b_mail.requested_at:
            later = b_mail.requested_at + timedelta(microseconds=1)
            await op.password_reset_tokens.update_one(
                {"id": b_mail.token_id}, {"$set": {"requested_at": later}})
            b_mail = pr.ResetMail(to=b_mail.to, user_id=b_mail.user_id,
                                  org_id=b_mail.org_id, token_id=b_mail.token_id,
                                  requested_at=later, token=b_mail.token)

        await pr.settle_delivery(op, b_mail, pr.DELIVERY_SENT, "ip-x")
        await pr.settle_delivery(op, a_mail, pr.DELIVERY_SENT, "ip-x")

        usable = await _usable_delivered(op)
        assert len(usable) == 2
        ids = sorted(t["id"] for t in usable)
        assert ids == sorted([a_mail.token_id, b_mail.token_id])
    scenario(monkeypatch, body)


def test_rc_auth_01_newer_send_does_not_touch_older_pending(monkeypatch):
    """RC-AUTH-01 counter-example of the old supersession path: a newer
    successful delivery must NOT revoke other open tokens of the same user —
    neither pending nor already sent. ``reset_password`` is the single point
    that invalidates every remaining open token when the user actually uses
    one; otherwise they survive to the TTL cutoff. This proves ``settle_delivery``
    issues no ``update_many`` against sibling tokens."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        a_mail = await pr.request_reset(op, OWNER, "ip-x")               # A: pending
        b_mail = await pr.request_reset(op, OWNER, "ip-x")               # B: pending
        assert a_mail is not None and b_mail is not None

        # Deliver only B. A is older and still pending → with the RC-AUTH-01
        # fix it must remain pending (NOT revoked).
        await pr.settle_delivery(op, b_mail, pr.DELIVERY_SENT, "ip-x")

        tokens = {t["id"]: t for t in await _tokens_for_owner(op)}
        a, b = tokens[a_mail.token_id], tokens[b_mail.token_id]
        assert a["used_at"] is None and a["delivery_status"] == "pending"
        assert a.get("revoked_reason") is None
        assert b["used_at"] is None and b["delivery_status"] == "sent"
    scenario(monkeypatch, body)


def test_rc_auth_01_smtp_failure_on_second_keeps_first_usable(monkeypatch):
    """F-06 is preserved: a failed delivery does NOT kill the older usable link."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        outbox.outcome = "sent"
        await _forgot(c, OWNER)                                       # A: delivered
        outbox.outcome = "failed"
        await _forgot(c, OWNER)                                       # B: failed

        a = next(t for t in await _tokens_for_owner(op)
                 if t["id"] == outbox[0].token_id)
        b = next(t for t in await _tokens_for_owner(op)
                 if t["id"] == outbox[1].token_id)
        assert a["used_at"] is None and a["delivery_status"] == "sent"
        assert b["used_at"] is not None and b["delivery_status"] == "failed"
        assert b.get("revoked_reason") == "delivery_failed"
    scenario(monkeypatch, body)


def test_rc_auth_01_settle_delivery_does_not_reactivate_a_revoked_token(monkeypatch):
    """A token already revoked by a successful reset must stay revoked and
    must NOT touch any other token."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        a_mail = await pr.request_reset(op, OWNER, "ip-x")               # A: pending
        b_mail = await pr.request_reset(op, OWNER, "ip-x")               # B: pending
        assert a_mail is not None and b_mail is not None
        if a_mail.requested_at >= b_mail.requested_at:
            later = b_mail.requested_at + timedelta(microseconds=1)
            await op.password_reset_tokens.update_one(
                {"id": b_mail.token_id}, {"$set": {"requested_at": later}})
            b_mail = pr.ResetMail(to=b_mail.to, user_id=b_mail.user_id,
                                  org_id=b_mail.org_id, token_id=b_mail.token_id,
                                  requested_at=later, token=b_mail.token)

        # Deliver B so it becomes consumable, then successfully reset with B
        # (which revokes every other remaining open token of this user).
        await pr.settle_delivery(op, b_mail, pr.DELIVERY_SENT, "ip-x")
        r = await _reset(c, b_mail.token)
        assert r.status_code == 200, r.text

        # Now A's late SMTP success arrives — settle_delivery must NOT
        # resurrect A and must NOT change the state of B.
        before = {t["id"]: dict(t) for t in await _tokens_for_owner(op)}
        await pr.settle_delivery(op, a_mail, pr.DELIVERY_SENT, "ip-x")
        after = {t["id"]: t for t in await _tokens_for_owner(op)}

        a_before, a_after = before[a_mail.token_id], after[a_mail.token_id]
        b_before, b_after = before[b_mail.token_id], after[b_mail.token_id]
        assert a_after.get("delivery_status") == a_before.get("delivery_status")
        assert a_after["used_at"] == a_before["used_at"]
        assert b_after == b_before
        # The audit row for the late delivery must mark it as already-resolved,
        # not as a plain "link_sent".
        actions = [row.get("action") for row in await op.audit_logs.find(
            {"entity_id": "u-owner"}, {"_id": 0}).to_list(None)]
        assert "password_reset_link_sent_but_already_resolved" in actions
    scenario(monkeypatch, body)


# ---------------------------------------------------------------------------
# RC-AUTH-02 — _dev_url_logging_enabled must be fail-closed against production
# ---------------------------------------------------------------------------


def _clear_env(monkeypatch):
    for k in ("ENV", "ENVIRONMENT", "PASSWORD_RESET_DEV_LOG_URL"):
        monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize(
    "env,environment,expected",
    [
        # Reproduction of CODEX RC-AUTH-02: ENV unset, ENVIRONMENT=production,
        # FLAG=1 → MUST be False (was True before the fix).
        (None,            "production",  False),
        ("production",    None,          False),
        ("production",    "development", False),
        ("development",   "production",  False),
        ("prod",          "development", False),
        ("development",   "live",        False),
        (None,            None,          False),  # unlabeled deployment → fail-closed
        ("foo",           "development", False),  # unknown label → fail-closed
        ("development",   "foo",         False),
        ("development",   None,          True),
        (None,            "development", True),
        ("development",   "development", True),
        ("dev",           "staging",     True),
        ("  DEVELOPMENT  ", "  Dev  ",   True),  # normalisation
    ],
)
def test_rc_auth_02_dev_url_logging_fail_closed_matrix(monkeypatch, env, environment, expected):
    from app.services import password_reset as pr
    _clear_env(monkeypatch)
    if env is not None:
        monkeypatch.setenv("ENV", env)
    if environment is not None:
        monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "1")
    assert pr._dev_url_logging_enabled() is expected, (
        f"ENV={env!r} ENVIRONMENT={environment!r} → expected {expected}")


def test_rc_auth_02_flag_off_always_disables_logging(monkeypatch):
    from app.services import password_reset as pr
    _clear_env(monkeypatch)
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("PASSWORD_RESET_DEV_LOG_URL", raising=False)
    assert pr._dev_url_logging_enabled() is False
    monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "0")
    assert pr._dev_url_logging_enabled() is False
    monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "")
    assert pr._dev_url_logging_enabled() is False


def test_rc_auth_02_production_never_logs_reset_url_even_with_flag(monkeypatch, caplog):
    """Behavioural proof: ``deliver`` NEVER prints the reset URL when either
    marker names production, no matter what the flag says."""
    from app.services import password_reset as pr

    for env, environment in [
        (None,            "production"),
        ("production",    None),
        ("development",   "production"),
        ("production",    "development"),
    ]:
        _clear_env(monkeypatch)
        if env is not None:
            monkeypatch.setenv("ENV", env)
        if environment is not None:
            monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "1")
        # No SMTP configured and no APP_PUBLIC_URL → the delivery path would be
        # the one that could log the dev URL.
        for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                    "SMTP_FROM", "SMTP_SECURITY", "APP_PUBLIC_URL"):
            monkeypatch.delenv(key, raising=False)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            outcome = pr.deliver(_mail(token="rc-auth-02-token-xxxxxxxxxxxx"))
        assert outcome == pr.DELIVERY_NOT_CONFIGURED, (
            f"ENV={env!r} ENVIRONMENT={environment!r}: expected not_configured, "
            f"got {outcome!r}")
        assert "DEV ONLY" not in caplog.text
        assert "rc-auth-02-token" not in caplog.text


def test_rc_auth_02_development_still_works_as_before(monkeypatch, caplog):
    from app.services import password_reset as pr
    _clear_env(monkeypatch)
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "1")
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                "SMTP_FROM", "SMTP_SECURITY", "APP_PUBLIC_URL"):
        monkeypatch.delenv(key, raising=False)
    with caplog.at_level(logging.WARNING):
        outcome = pr.deliver(_mail(token="rc-auth-02-dev-token-yyyyyyyyyyyy"))
    assert outcome == pr.DELIVERY_DEV_LOGGED
    assert "DEV ONLY" in caplog.text
