"""Independent review probes; synthetic identities, disposable Mongo only."""
from tests.test_auth_01_password_recovery import scenario, OWNER


def test_two_inflight_deliveries_preserve_at_least_one_usable_link(monkeypatch):
    from app.services import password_reset as service

    async def body(op, client, outbox):
        first = await service.request_reset(op, OWNER, "127.0.0.1")
        second = await service.request_reset(op, OWNER, "127.0.0.1")
        # Both SMTP calls may be in flight before either settles.
        await service.settle_delivery(op, first, service.DELIVERY_SENT, "127.0.0.1")
        await service.settle_delivery(op, second, service.DELIVERY_SENT, "127.0.0.1")
        usable = await op.password_reset_tokens.count_documents(
            {"user_id": first.user_id, "used_at": None, "delivery_status": "sent"})
        assert usable >= 1, "two successfully delivered links invalidated each other"
    scenario(monkeypatch, body)


def test_environment_production_disables_dev_token_logging(monkeypatch):
    from app.services import password_reset as service
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PASSWORD_RESET_DEV_LOG_URL", "1")
    assert not service._dev_url_logging_enabled()
