"""
AUTH-01 RC — the CODEX INTEGRATED-RC-2026-10-25 CHANGES_REQUESTED findings on
PR #56 head ``8e435a0e``.

* RC-AUTH-01 — reproduction (comment 6395188427): two successful overlapping
  reset deliveries left zero usable links because every ``settle_delivery``
  unconditionally revoked EVERY other open token of the user. The fix is NOT
  to drop supersession — it is to make it atomically ORDER-AWARE so that under
  either completion order exactly one usable link remains, and it is always
  the one from the newer request. The old F-06 behaviour "a newer-sent link
  supersedes the older ones" is preserved (comment 6395345262).

* RC-AUTH-02 — the dev-only reset-URL logging guard must be fail-closed
  against production markers across BOTH ``ENV`` and ``ENVIRONMENT``.

Harness is the shared seed/HTTP double from ``test_auth_01_password_recovery``;
mongomock by default, real transactions when ``W0_03_REAL_MONGO_URL`` names a
replica set.

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
# RC-AUTH-01 — ordered settlement leaves exactly one usable link from the newer
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


async def _mint_pair_strict_order(op, pr):
    """Insert two deterministic pending tokens for u-owner with strictly
    ordered ``requested_at``: A at t0, B at t0+1ms. Returns ``(a_mail, b_mail)``.

    This bypasses the rate limiter (direct insert; no HTTP) and avoids the
    clock-tick ambiguity of back-to-back real ``request_reset`` calls on
    some backends, so the ordering tests are deterministic across both
    mongomock and real Mongo.
    """
    import secrets
    import uuid
    from datetime import datetime, timezone, timedelta as _td
    t0 = datetime.now(timezone.utc)
    mails = []
    for i, requested_at in enumerate((t0, t0 + _td(milliseconds=1))):
        tok = secrets.token_urlsafe(pr.TOKEN_BYTES)
        tok_id = str(uuid.uuid4())
        await op.password_reset_tokens.insert_one({
            "id": tok_id, "org_id": ORG_A, "user_id": "u-owner",
            "token_hash": pr.hash_token(tok),
            "requested_at": requested_at,
            "expires_at": requested_at + pr.TOKEN_TTL,
            "used_at": None, "requested_ip": "ip-x",
            "delivery_status": pr.DELIVERY_PENDING,
        })
        mails.append(pr.ResetMail(to=OWNER, user_id="u-owner", org_id=ORG_A,
                                  token_id=tok_id, requested_at=requested_at,
                                  token=tok))
    return mails[0], mails[1]


def test_rc_auth_01_two_overlapping_deliveries_leave_exactly_one_usable_newer(monkeypatch):
    """CODEX reproduction (forward order): A delivered, then B delivered →
    the newer link (B) is the single usable one; A is superseded. The old
    reproduction counted zero usable; the fix makes it exactly one."""
    async def body(op, c, outbox):
        await _forgot(c, OWNER)                                       # A sent
        await _forgot(c, OWNER)                                       # B sent (newer)
        usable = await _usable_delivered(op)
        assert len(usable) == 1, (
            "Exactly one usable link must remain under forward order; "
            "pre-RC-AUTH-01 reproduction counted zero.")
        assert usable[0]["id"] == outbox[1].token_id                  # the newer

        rows = await _tokens_for_owner(op)
        assert rows[0]["id"] == outbox[0].token_id
        assert rows[0]["used_at"] is not None
        assert rows[0].get("revoked_reason") == "superseded"
        assert rows[1]["id"] == outbox[1].token_id
        assert rows[1]["used_at"] is None
        assert rows[1]["delivery_status"] == "sent"
    scenario(monkeypatch, body)


def test_rc_auth_01_reverse_order_also_leaves_exactly_one_usable_newer(monkeypatch):
    """Mint A, mint B, then settle B first (newer) and A after (older) →
    still exactly one usable link, and it is the newer (B). A's late
    settle must not reactivate itself and must not touch B."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        a_mail, b_mail = await _mint_pair_strict_order(op, pr)

        await pr.settle_delivery(op, b_mail, pr.DELIVERY_SENT, "ip-x")
        await pr.settle_delivery(op, a_mail, pr.DELIVERY_SENT, "ip-x")

        usable = await _usable_delivered(op)
        assert len(usable) == 1
        assert usable[0]["id"] == b_mail.token_id                      # newer

        tokens = {t["id"]: t for t in await _tokens_for_owner(op)}
        a, b = tokens[a_mail.token_id], tokens[b_mail.token_id]
        assert a["used_at"] is not None and a["revoked_reason"] == "superseded"
        assert b["used_at"] is None and b["delivery_status"] == "sent"

        # A's late settle must have recorded an "already_resolved" audit row,
        # NOT a plain link_sent.
        actions = [row.get("action") for row in await op.audit_logs.find(
            {"entity_id": "u-owner"}, {"_id": 0}).to_list(None)]
        assert "password_reset_link_sent_but_already_resolved" in actions
    scenario(monkeypatch, body)


def test_rc_auth_01_concurrent_settles_never_leave_zero_usable_links(monkeypatch):
    """The CODEX RC-AUTH-01 count check: at the end of either completion
    order, the number of unused ``sent`` tokens for the user is >= 1."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        for order in (("forward",), ("reverse",)):
            await op.password_reset_tokens.delete_many({"user_id": "u-owner"})
            a_mail, b_mail = await _mint_pair_strict_order(op, pr)
            if order[0] == "forward":
                await pr.settle_delivery(op, a_mail, pr.DELIVERY_SENT, "ip-x")
                await pr.settle_delivery(op, b_mail, pr.DELIVERY_SENT, "ip-x")
            else:
                await pr.settle_delivery(op, b_mail, pr.DELIVERY_SENT, "ip-x")
                await pr.settle_delivery(op, a_mail, pr.DELIVERY_SENT, "ip-x")
            count = await op.password_reset_tokens.count_documents(
                {"user_id": "u-owner", "used_at": None, "delivery_status": "sent"})
            assert count >= 1, (
                f"RC-AUTH-01 reproduction ({order[0]} order): "
                f"expected at least one usable link, got {count}.")
    scenario(monkeypatch, body)


def test_rc_auth_01_smtp_failure_on_second_keeps_first_usable(monkeypatch):
    """F-06 is preserved: a FAILED delivery does NOT kill the older usable link."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        outbox.outcome = "sent"
        await _forgot(c, OWNER)                                       # A: delivered
        outbox.outcome = "failed"
        await _forgot(c, OWNER)                                       # B: failed

        tokens = {t["id"]: t for t in await _tokens_for_owner(op)}
        a = tokens[outbox[0].token_id]
        b = tokens[outbox[1].token_id]
        assert a["used_at"] is None and a["delivery_status"] == "sent"
        assert b["used_at"] is not None and b["delivery_status"] == "failed"
        assert b.get("revoked_reason") == "delivery_failed"
    scenario(monkeypatch, body)


def test_rc_auth_01_settle_delivery_does_not_reactivate_a_revoked_token(monkeypatch):
    """A token already revoked by a successful reset must stay revoked and
    must NOT touch any other token when a late SMTP success arrives."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr

        a_mail, b_mail = await _mint_pair_strict_order(op, pr)

        # Deliver B so it becomes consumable, then successfully reset with B
        # (reset_password revokes every remaining open token of this user).
        await pr.settle_delivery(op, b_mail, pr.DELIVERY_SENT, "ip-x")
        r = await _reset(c, b_mail.token)
        assert r.status_code == 200, r.text

        # A's late SMTP success — settle_delivery must NOT resurrect A and must
        # NOT change the state of B.
        before = {t["id"]: dict(t) for t in await _tokens_for_owner(op)}
        await pr.settle_delivery(op, a_mail, pr.DELIVERY_SENT, "ip-x")
        after = {t["id"]: t for t in await _tokens_for_owner(op)}

        a_before, a_after = before[a_mail.token_id], after[a_mail.token_id]
        b_before, b_after = before[b_mail.token_id], after[b_mail.token_id]
        assert a_after.get("delivery_status") == a_before.get("delivery_status")
        assert a_after["used_at"] == a_before["used_at"]
        assert b_after == b_before
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


# ---------------------------------------------------------------------------
# RC-AUTH-03 — stable total ordering under same-millisecond and concurrent
# settlement (CODEX independent review 6396118840 / PR #64 contract test)
# ---------------------------------------------------------------------------


async def _mint_pair_equal_timestamp(op, pr, when):
    """Mint two pending tokens for u-owner with EXACTLY the same
    ``requested_at`` (persisted BSON datetime, millisecond precision).
    Returns ``(a_mail, b_mail)`` with ``a.token_id < b.token_id`` so the
    tie-breaker's expected winner is deterministic for assertions."""
    import secrets
    import uuid
    mails = []
    for _ in range(2):
        tok = secrets.token_urlsafe(pr.TOKEN_BYTES)
        tok_id = str(uuid.uuid4())
        await op.password_reset_tokens.insert_one({
            "id": tok_id, "org_id": ORG_A, "user_id": "u-owner",
            "token_hash": pr.hash_token(tok),
            "requested_at": when,
            "expires_at": when + pr.TOKEN_TTL,
            "used_at": None, "requested_ip": "ip-x",
            "delivery_status": pr.DELIVERY_PENDING,
        })
        mails.append(pr.ResetMail(to=OWNER, user_id="u-owner", org_id=ORG_A,
                                  token_id=tok_id, requested_at=when, token=tok))
    # Order so the "smaller id" is first — matches natural lexicographic
    # tiebreaker expectations in the assertions below.
    mails.sort(key=lambda m: m.token_id)
    return mails[0], mails[1]


def test_rc_auth_03_same_millisecond_requests_leave_exactly_one_usable(monkeypatch):
    """CODEX RC-AUTH-03 reproduction: two tokens persist with identical
    ``requested_at``. The tie-breaker ``id`` lexicographic order picks
    the winner deterministically. Both completion orders converge."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr
        from datetime import datetime, timezone

        # Equal timestamps for both; `low_id_mail < high_id_mail` by id.
        when = datetime.now(timezone.utc).replace(microsecond=123000)
        low_id_mail, high_id_mail = await _mint_pair_equal_timestamp(op, pr, when)

        # Forward: settle low_id first, then high_id.
        await pr.settle_delivery(op, low_id_mail, pr.DELIVERY_SENT, "ip-x")
        await pr.settle_delivery(op, high_id_mail, pr.DELIVERY_SENT, "ip-x")

        rows = await _tokens_for_owner(op)
        unused_sent = [r for r in rows
                       if r.get("used_at") is None
                       and r.get("delivery_status") == "sent"]
        assert len(unused_sent) == 1, (
            "RC-AUTH-03 reproduction: expected exactly one usable link under "
            "same-millisecond + forward order; got "
            f"{len(unused_sent)}: {[r['id'] for r in unused_sent]}"
        )
        assert unused_sent[0]["id"] == high_id_mail.token_id, (
            "RC-AUTH-03: the tiebreaker must pick the LEX-HIGHER id as "
            "the surviving winner under equal timestamps."
        )
    scenario(monkeypatch, body)


def test_rc_auth_03_same_millisecond_reverse_order_also_leaves_one(monkeypatch):
    """Reverse completion order under equal timestamps still leaves
    exactly one usable link; the deterministic winner is the same."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr
        from datetime import datetime, timezone

        when = datetime.now(timezone.utc).replace(microsecond=321000)
        low_id_mail, high_id_mail = await _mint_pair_equal_timestamp(op, pr, when)

        # Reverse: settle high_id first, then low_id.
        await pr.settle_delivery(op, high_id_mail, pr.DELIVERY_SENT, "ip-x")
        await pr.settle_delivery(op, low_id_mail, pr.DELIVERY_SENT, "ip-x")

        rows = await _tokens_for_owner(op)
        unused_sent = [r for r in rows
                       if r.get("used_at") is None
                       and r.get("delivery_status") == "sent"]
        assert len(unused_sent) == 1, (
            "RC-AUTH-03: expected exactly one usable link under "
            f"same-millisecond + reverse order; got {len(unused_sent)}"
        )
        assert unused_sent[0]["id"] == high_id_mail.token_id


def test_rc_auth_03_concurrent_settles_at_same_millisecond(monkeypatch):
    """Simulated concurrent settlement at the same persisted millisecond.
    Each call runs in its own transaction snapshot; the stable total
    order guarantees exactly one survives whichever one commits first.
    Verified by running both completion permutations against the same
    initial pair and asserting the invariant in both runs."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr
        from datetime import datetime, timezone

        for permutation in ("low_first", "high_first"):
            await op.password_reset_tokens.delete_many({"user_id": "u-owner"})
            when = datetime.now(timezone.utc).replace(microsecond=456000)
            low, high = await _mint_pair_equal_timestamp(op, pr, when)
            order = [low, high] if permutation == "low_first" else [high, low]
            # Fire the two settles back-to-back; the harness's transaction
            # snapshot double emulates the per-transaction isolation the
            # production replica set provides, so the stable total order
            # is what guarantees convergence.
            for mail in order:
                await pr.settle_delivery(op, mail, pr.DELIVERY_SENT, "ip-x")
            count = await op.password_reset_tokens.count_documents(
                {"user_id": "u-owner",
                 "used_at": None, "delivery_status": "sent"})
            assert count == 1, (
                f"RC-AUTH-03 reproduction ({permutation}): expected "
                f"exactly one usable link; got {count}.")
    scenario(monkeypatch, body)


def test_rc_auth_03_strictly_newer_timestamp_still_wins(monkeypatch):
    """Regression over RC-AUTH-01: a strictly-newer timestamp must still
    win over an older one, independent of ``id`` lexicographic order.
    This proves the tiebreaker only kicks in on the equal-timestamp
    tie — never overrides the natural time order."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr
        from datetime import datetime, timezone, timedelta

        # Older with HIGHER id, newer with LOWER id — so the tiebreaker
        # alone would pick the wrong winner.
        import secrets
        import uuid
        when_old = datetime.now(timezone.utc).replace(microsecond=100000)
        when_new = when_old + timedelta(milliseconds=10)

        async def _mint(when, token_id):
            tok = secrets.token_urlsafe(pr.TOKEN_BYTES)
            await op.password_reset_tokens.insert_one({
                "id": token_id, "org_id": ORG_A, "user_id": "u-owner",
                "token_hash": pr.hash_token(tok),
                "requested_at": when,
                "expires_at": when + pr.TOKEN_TTL,
                "used_at": None, "requested_ip": "ip-x",
                "delivery_status": pr.DELIVERY_PENDING,
            })
            return pr.ResetMail(to=OWNER, user_id="u-owner", org_id=ORG_A,
                                token_id=token_id, requested_at=when,
                                token=tok)

        older = await _mint(when_old, "z-older-high-id")   # higher id lex
        newer = await _mint(when_new, "a-newer-low-id")    # lower id lex

        # Forward order: older first, then newer.
        await pr.settle_delivery(op, older, pr.DELIVERY_SENT, "ip-x")
        await pr.settle_delivery(op, newer, pr.DELIVERY_SENT, "ip-x")

        rows = {r["id"]: r for r in await _tokens_for_owner(op)}
        assert rows[newer.token_id]["used_at"] is None, (
            "RC-AUTH-03: strict-newer must survive regardless of id order."
        )
        assert rows[newer.token_id]["delivery_status"] == "sent"
        assert rows[older.token_id]["used_at"] is not None
        assert rows[older.token_id]["revoked_reason"] == "superseded"
    scenario(monkeypatch, body)


def test_rc_auth_03_failed_delivery_still_preserves_older_sent_link(monkeypatch):
    """F-06 is preserved under RC-AUTH-03: a FAILED delivery (any order,
    any id ordering) never touches the surviving older sent link."""
    async def body(op, c, outbox):
        from app.services import password_reset as pr
        from datetime import datetime, timezone

        when = datetime.now(timezone.utc).replace(microsecond=777000)
        low_id, high_id = await _mint_pair_equal_timestamp(op, pr, when)

        # low_id delivered sent, high_id FAILED (both at the same ms).
        await pr.settle_delivery(op, low_id, pr.DELIVERY_SENT, "ip-x")
        await pr.settle_delivery(op, high_id, pr.DELIVERY_FAILED, "ip-x")

        rows = {r["id"]: r for r in await _tokens_for_owner(op)}
        assert rows[low_id.token_id]["used_at"] is None
        assert rows[low_id.token_id]["delivery_status"] == "sent"
        assert rows[low_id.token_id].get("revoked_reason") is None
        assert rows[high_id.token_id]["used_at"] is not None
        assert rows[high_id.token_id]["delivery_status"] == "failed"
        assert rows[high_id.token_id].get("revoked_reason") == "delivery_failed"
    scenario(monkeypatch, body)
