"""Independent acceptance of existing supersession policy, disposable Mongo only."""
from datetime import datetime, timedelta, timezone
import pytest
from tests.test_auth_01_password_recovery import scenario, OWNER


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_overlapping_success_keeps_only_newest_delivered_request(monkeypatch, order):
    from app.services import password_reset as s

    async def body(db, client, outbox):
        t = datetime.now(timezone.utc)
        mails = [await s.request_reset(db, OWNER, "127.0.0.1", now=t),
                 await s.request_reset(db, OWNER, "127.0.0.1", now=t + timedelta(milliseconds=10))]
        for i in order:
            await s.settle_delivery(db, mails[i], s.DELIVERY_SENT, "127.0.0.1")
        rows = await db.password_reset_tokens.find(
            {"user_id": mails[0].user_id, "used_at": None, "delivery_status": "sent"}
        ).to_list(None)
        assert [r["id"] for r in rows] == [mails[1].token_id]
    scenario(monkeypatch, body)


def test_reset_while_new_mail_is_pending_cannot_be_undone_by_late_settlement(monkeypatch):
    from app.services import password_reset as s

    async def body(db, client, outbox):
        first = await s.request_reset(db, OWNER, "127.0.0.1")
        await s.settle_delivery(db, first, s.DELIVERY_SENT, "127.0.0.1")
        pending = await s.request_reset(db, OWNER, "127.0.0.1")
        await s.reset_password(db, first.token, "synthetic-hash-never-used-for-login")
        await s.settle_delivery(db, pending, s.DELIVERY_SENT, "127.0.0.1")
        assert await db.password_reset_tokens.count_documents(
            {"user_id": first.user_id, "used_at": None}) == 0
        with pytest.raises(s.ResetFailed):
            await s.reset_password(db, pending.token, "another-synthetic-hash")
    scenario(monkeypatch, body)


def test_same_millisecond_requests_still_leave_one_delivered_link(monkeypatch):
    from app.services import password_reset as s

    async def body(db, client, outbox):
        t = datetime.now(timezone.utc).replace(microsecond=123000)
        first = await s.request_reset(db, OWNER, "127.0.0.1", now=t)
        second = await s.request_reset(db, OWNER, "127.0.0.1", now=t)
        await s.settle_delivery(db, first, s.DELIVERY_SENT, "127.0.0.1")
        await s.settle_delivery(db, second, s.DELIVERY_SENT, "127.0.0.1")
        assert await db.password_reset_tokens.count_documents(
            {"user_id": first.user_id, "used_at": None, "delivery_status": "sent"}) == 1
    scenario(monkeypatch, body)


@pytest.mark.parametrize("failed_first", [True, False])
def test_failed_newer_delivery_preserves_successful_older_link(monkeypatch, failed_first):
    from app.services import password_reset as s

    async def body(db, client, outbox):
        first = await s.request_reset(db, OWNER, "127.0.0.1")
        newer = await s.request_reset(db, OWNER, "127.0.0.1")
        steps = [(first, s.DELIVERY_SENT), (newer, s.DELIVERY_FAILED)]
        if failed_first:
            steps.reverse()
        for mail, status in steps:
            await s.settle_delivery(db, mail, status, "127.0.0.1")
        rows = await db.password_reset_tokens.find(
            {"user_id": first.user_id, "used_at": None, "delivery_status": "sent"}
        ).to_list(None)
        assert [r["id"] for r in rows] == [first.token_id]
    scenario(monkeypatch, body)


@pytest.mark.parametrize("env,environment", [(None, None), (None, "production"),
    ("development", "production"), ("production", "development"), ("unknown", None)])
def test_plaintext_link_logging_fails_closed(monkeypatch, env, environment):
    from app.services import password_reset as s
    for key, value in [("ENV", env), ("ENVIRONMENT", environment)]:
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "1")
    assert s._dev_url_logging_enabled() is False
