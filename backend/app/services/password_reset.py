"""
AUTH-01 — self-service password reset: one-time, hashed, 30-minute tokens.

Flow (after the C01 corrections to CODEX F-01/F-05/F-06/F-08)
--------------------------------------------------------------
``POST /auth/forgot-password`` answers immediately with one generic body and
schedules :func:`process_forgot_request`. Everything that depends on whether
the account exists happens AFTER the response (F-05):

1. per-email shared rate limit (``rate_limit``); over the limit → event, stop;
2. exactly ONE active user must match the normalized email in the login
   registry — the same rule and the same helper as ``POST /auth/login``
   (R0-03 ``app.tenancy.identity``); none / disabled → event, stop. Several
   (a legacy duplicate) → the same generic answer, no token, and a
   ``forgot_ambiguous`` security event (R0-04);
3. one transaction (F-01): insert a ``pending`` token (only its SHA-256 is
   stored) + audit ``password_reset_requested``. Older links are NOT touched yet;
4. :func:`deliver` sends the link; then one transaction settles it (F-06):
   * delivered → token ``sent``, the user's OLDER open tokens are revoked
     (``superseded``) + audit ``password_reset_link_sent``;
   * not delivered (provider error / no e-mail configured) → only the NEW token
     is revoked (``delivery_failed`` / ``delivery_not_configured``) + audit +
     security event. The user's older links stay usable, so a broken mail
     server never destroys the last working recovery link.
   No automatic retry: the user asks again (bounded by the per-email limit).

``POST /auth/reset-password`` → :func:`reset_password`. Pre-checks classify a
failure for the security event (invalid / expired / replay / inactive user);
then ONE transaction (F-01) does all of it or none of it: the conditional token
claim (``used_at: None`` and not expired), the new password hash, ``$inc
auth_version`` (F-02: every session issued before the reset stops working),
revocation of the user's remaining open tokens, the legacy audit row and the
canonical W0-04 AuditEvent ``user.password_reset`` (R0-04). A failure
inside leaves the old password, the token unused and no audit row; it is
reported as :class:`ResetNotCompleted` ("nothing was changed"), never as a
success and never as a half-done state.

Transactions need a replica set (Atlas in production). Without one these
operations are refused (``auth_tx.TransactionsUnavailable``) before any write.

Storage: ``password_reset_tokens`` {id, org_id, user_id, token_hash,
requested_at, expires_at, used_at, requested_ip, delivery_status
[, revoked_reason]}. ``expires_at`` is a BSON date for the TTL index.
"""
import asyncio
import hashlib
import logging
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import auth_events, rate_limit
from app.services.auth_tx import run_in_transaction
from app.services.mailer import app_public_url, get_mail_provider
from app.services.user_role_policy import audit_user_change
from app.tenancy.data_access import TenantData, resolve_owner_by_unique_key
from app.tenancy.identity import normalize_email, users_with_email
from app.utils.audit import log_audit

logger = logging.getLogger("beg.password_reset")

COLLECTION = "password_reset_tokens"
TOKEN_TTL = timedelta(minutes=30)
TOKEN_BYTES = 32                    # 256 bits of entropy
TOKEN_MIN_LENGTH, TOKEN_MAX_LENGTH = 20, 256
#: RFC 5321 path limit; a longer value cannot name an account (no lookup is made).
MAX_EMAIL_LENGTH = 254

EMAIL_LIMIT, EMAIL_WINDOW_SECONDS = 3, 900

DELIVERY_PENDING = "pending"
DELIVERY_SENT = "sent"
DELIVERY_DEV_LOGGED = "dev_logged"
DELIVERY_FAILED = "failed"
DELIVERY_NOT_CONFIGURED = "not_configured"
_DELIVERED = (DELIVERY_SENT, DELIVERY_DEV_LOGGED)

#: Explicit opt-in for LOCAL development only: with no outbound e-mail
#: configured, print the reset URL to the server console. Ignored when
#: ``ENV=production``.
DEV_LOG_URL_FLAG = "PASSWORD_RESET_DEV_LOG_URL"

GENERIC_REQUEST_MESSAGE = ("If an active account exists for this email, "
                           "we sent a password reset link.")
GENERIC_RESET_FAILURE = "This password reset link is invalid or has expired."
RESET_NOT_COMPLETED_MESSAGE = "The password was not changed. Please try again."

MAIL_SUBJECT = "BEG_Work — смяна на парола"
MAIL_TEXT = (
    "Здравейте,\n\n"
    "Получихме заявка за смяна на паролата за вашия акаунт в BEG_Work.\n"
    "Отворете линка по-долу в рамките на 30 минути, за да зададете нова парола:\n\n"
    "{url}\n\n"
    "Линкът важи само веднъж. Ако не сте поискали смяна на паролата, игнорирайте "
    "това съобщение — паролата ви остава непроменена.\n"
)


class ResetFailed(Exception):
    """Invalid, unknown, expired, reused or otherwise unusable token — one answer."""


class ResetNotCompleted(Exception):
    """The reset could not be committed; NOTHING was changed (transaction aborted)."""


class _ClaimLost(Exception):
    """Inside the transaction: the token or the user is no longer eligible."""


@dataclass(frozen=True)
class ResetMail:
    """What :func:`deliver` needs. ``token`` is plaintext: never log this object."""
    to: str
    user_id: str
    org_id: str
    token_id: str
    token: str = field(repr=False)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value) -> Optional[datetime]:
    """A stored datetime as aware UTC (MongoDB hands back naive UTC)."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def ensure_indexes(db) -> None:
    """unique token_hash · TTL on expires_at · (user_id, used_at)."""
    await db.password_reset_tokens.create_index(
        "token_hash", unique=True, name="token_hash_unique")
    await db.password_reset_tokens.create_index(
        "expires_at", expireAfterSeconds=0, name="expires_at_ttl")
    await db.password_reset_tokens.create_index(
        [("user_id", 1), ("used_at", 1)], name="user_id_used_at")


# ------------------------------------------------------------------ request
async def process_forgot_request(db, email: str, requested_ip: Optional[str],
                                 now: Optional[datetime] = None) -> Optional[str]:
    """The whole eligibility-dependent part of forgot-password (runs after the response).

    Never raises. Returns the delivery outcome when a link was created, else
    ``None`` (the value is for tests and logs only).
    """
    normalized = normalize_email(email)
    if len(normalized) > MAX_EMAIL_LENGTH:
        normalized = ""
    subject = auth_events.keyed_ref(normalized or None)
    try:
        if not normalized:
            await auth_events.record(db, auth_events.FORGOT_NO_MATCH, ip=requested_ip)
            return None
        limited = await rate_limit.hit(db, "forgot_email", normalized, EMAIL_LIMIT,
                                       EMAIL_WINDOW_SECONDS, now=now)
        if not limited.allowed:
            if limited.first_rejection:
                await auth_events.record(db, auth_events.RATE_LIMITED_EMAIL,
                                         ip=requested_ip, subject=subject)
            return None
        mail = await request_reset(db, normalized, requested_ip, now=now)
        if mail is None:
            return None
        outcome = await asyncio.to_thread(deliver, mail)
        await settle_delivery(db, mail, outcome, requested_ip)
        return outcome
    except Exception as exc:
        logger.error("PASSWORD_RESET_REQUEST_FAILED error=%s", type(exc).__name__)
        await auth_events.record(db, auth_events.FORGOT_FAILED, ip=requested_ip,
                                 subject=subject, detail={"error": type(exc).__name__})
        return None


async def request_reset(db, email: str, requested_ip: Optional[str],
                        now: Optional[datetime] = None) -> Optional[ResetMail]:
    """Mint a ``pending`` token for the ONE active user ``email`` names; ``None`` otherwise."""
    subject = auth_events.keyed_ref(normalize_email(email) or None)
    # R0-03/R0-04: the login registry (global ``users``), the one R0-03 helper.
    # A duplicate never gets a token: the requester sees the generic answer.
    candidates = await users_with_email([db], email)
    if len(candidates) != 1:
        if candidates:
            logger.warning("PASSWORD_RESET_REQUEST refused: %d users share this email "
                           "(user_ids=%s); resolve the duplicate (r0_03_email_duplicates_report)",
                           len(candidates), [c.get("id") for c in candidates])
        await auth_events.record(
            db, auth_events.FORGOT_AMBIGUOUS if candidates else auth_events.FORGOT_NO_MATCH,
            ip=requested_ip, subject=subject,
            detail={"candidates": len(candidates)} if candidates else None)
        return None
    user = candidates[0]
    uid, org_id = user.get("id"), user.get("org_id")
    if not user.get("is_active", True) or not isinstance(uid, str) or not uid \
            or not isinstance(org_id, str) or not org_id:
        await auth_events.record(db, auth_events.FORGOT_NOT_ELIGIBLE, ip=requested_ip,
                                 subject=subject, org_id=org_id or None, user_id=uid or None)
        return None

    tenant = TenantData.for_owner_of(db, user)
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    token_id = str(uuid.uuid4())

    async def body(session):
        await tenant.password_reset_tokens.insert_one({
            "id": token_id,
            "org_id": org_id,
            "user_id": uid,
            "token_hash": hash_token(token),
            "requested_at": now,
            "expires_at": now + TOKEN_TTL,
            "used_at": None,
            "requested_ip": requested_ip,
            "delivery_status": DELIVERY_PENDING,
        }, session=session)
        await log_audit(org_id, uid, user.get("email"), "password_reset_requested", "user", uid,
                        {"requested_ip": requested_ip}, db_handle=db, session=session)

    await run_in_transaction(db, body)
    return ResetMail(to=user["email"].strip(), user_id=uid, org_id=org_id,
                     token_id=token_id, token=token)


def _dev_url_logging_enabled() -> bool:
    if os.environ.get("ENV", "development").strip().lower() == "production":
        return False
    return os.environ.get(DEV_LOG_URL_FLAG, "").strip().lower() in ("1", "true", "yes")


def deliver(mail: ResetMail) -> str:
    """Send the reset link; return the delivery outcome.

    ``sent`` only when the provider accepted the message. Never logs the token or
    the link — except the explicit local-development flag, outside production,
    when no e-mail is configured (``dev_logged``).
    """
    base = app_public_url()
    provider = get_mail_provider()
    if provider is None or base is None:
        logger.warning(
            "PASSWORD_RESET_EMAIL_NOT_SENT: outbound e-mail is not configured "
            "(need SMTP_HOST, SMTP_FROM and APP_PUBLIC_URL); user_id=%s did not receive a link",
            mail.user_id)
        if _dev_url_logging_enabled():
            dev_base = base or "http://localhost:3000"
            logger.warning("DEV ONLY (%s=1) reset URL: %s/reset-password?token=%s",
                           DEV_LOG_URL_FLAG, dev_base, mail.token)
            return DELIVERY_DEV_LOGGED
        return DELIVERY_NOT_CONFIGURED
    url = f"{base}/reset-password?token={mail.token}"
    try:
        provider.send(mail.to, MAIL_SUBJECT, MAIL_TEXT.format(url=url))
    except Exception as exc:          # delivery must never surface to the requester
        logger.error("PASSWORD_RESET_EMAIL_FAILED user_id=%s provider=%s error=%s",
                     mail.user_id, provider.name, type(exc).__name__)
        return DELIVERY_FAILED
    logger.info("PASSWORD_RESET_EMAIL_SENT user_id=%s provider=%s", mail.user_id, provider.name)
    return DELIVERY_SENT


async def settle_delivery(db, mail: ResetMail, outcome: str, requested_ip: Optional[str],
                          now: Optional[datetime] = None) -> None:
    """Record the delivery outcome atomically (see module docstring, step 4)."""
    tenant = TenantData.for_resolved_org(db, mail.org_id)
    now = now or datetime.now(timezone.utc)
    delivered = outcome in _DELIVERED

    async def body(session):
        if delivered:
            await tenant.password_reset_tokens.update_one(
                {"id": mail.token_id, "used_at": None},
                {"$set": {"delivery_status": outcome}}, session=session)
            await tenant.password_reset_tokens.update_many(
                {"user_id": mail.user_id, "used_at": None, "id": {"$ne": mail.token_id}},
                {"$set": {"used_at": now, "revoked_reason": "superseded"}}, session=session)
            action = "password_reset_link_sent"
        else:
            await tenant.password_reset_tokens.update_one(
                {"id": mail.token_id, "used_at": None},
                {"$set": {"used_at": now, "delivery_status": outcome,
                          "revoked_reason": "delivery_" + outcome}}, session=session)
            action = "password_reset_link_not_delivered"
        await log_audit(mail.org_id, mail.user_id, mail.to, action, "user", mail.user_id,
                        {"delivery_status": outcome}, db_handle=db, session=session)

    await run_in_transaction(db, body)
    if not delivered:
        await auth_events.record(
            db, auth_events.DELIVERY_NOT_CONFIGURED if outcome == DELIVERY_NOT_CONFIGURED
            else auth_events.DELIVERY_FAILED,
            ip=requested_ip, org_id=mail.org_id, user_id=mail.user_id, token_ref=mail.token_id)


# -------------------------------------------------------------------- reset
async def reset_password(db, token: str, new_password_hash: str,
                         requested_ip: Optional[str] = None,
                         now: Optional[datetime] = None) -> dict:
    """Consume ``token`` and set the password atomically; the user row on success.

    ``new_password_hash`` is already strength-checked and hashed by the caller.
    Raises :class:`ResetFailed` for every unusable token and
    :class:`ResetNotCompleted` when the commit failed (nothing changed).
    """
    now = now or datetime.now(timezone.utc)

    async def deny(event, **kw):
        await auth_events.record(db, event, ip=requested_ip, **kw)
        raise ResetFailed()

    if not isinstance(token, str) or not TOKEN_MIN_LENGTH <= len(token) <= TOKEN_MAX_LENGTH:
        await deny(auth_events.RESET_INVALID,
                   token_ref=auth_events.keyed_ref(token if isinstance(token, str) else None))
    token_hash = hash_token(token)
    tenant, row = await resolve_owner_by_unique_key(
        db, COLLECTION, "token_hash", token_hash, {"_id": 0})
    if row is None:
        await deny(auth_events.RESET_INVALID, token_ref=auth_events.keyed_ref(token_hash))
    uid = row.get("user_id")
    where = {"token_ref": row.get("id"), "org_id": row.get("org_id"), "user_id": uid}
    if row.get("used_at") is not None:
        await deny(auth_events.RESET_REPLAY, **where,
                   detail={"revoked_reason": row.get("revoked_reason")})
    expires_at = _aware(row.get("expires_at"))
    if expires_at is None or expires_at <= now:
        await deny(auth_events.RESET_EXPIRED, **where)
    user = await tenant.users.get(uid, {"_id": 0, "id": 1, "org_id": 1, "email": 1,
                                        "is_active": 1})
    if not user or not user.get("is_active", True):
        await deny(auth_events.RESET_USER_INACTIVE, **where)

    stamp = now.isoformat()

    async def body(session):
        # The single-use guarantee: only one transaction can flip used_at from None.
        claimed = await tenant.password_reset_tokens.find_one_and_update(
            {"id": row["id"], "user_id": uid, "used_at": None, "expires_at": {"$gt": now}},
            {"$set": {"used_at": now}}, session=session)
        if not claimed:
            raise _ClaimLost()
        result = await tenant.users.update_one(
            {"id": uid, "is_active": {"$ne": False}},
            {"$set": {
                "password_hash": new_password_hash,
                "updated_at": stamp,
                "password_reset_at": stamp,
                "password_reset_by": "SELF_SERVICE_TOKEN",
            }, "$inc": {"auth_version": 1}}, session=session)
        if result.matched_count != 1:
            raise _ClaimLost()
        await tenant.password_reset_tokens.update_many(
            {"user_id": uid, "used_at": None},
            {"$set": {"used_at": now, "revoked_reason": "password_reset"}}, session=session)
        await log_audit(tenant.org_id, uid, user.get("email"), "password_reset_completed",
                        "user", uid, {"method": "self_service_token"},
                        db_handle=db, session=session)
        # R0-04: the canonical W0-04 AuditEvent, in the same transaction. No
        # password, hash or token — only who, what and through which endpoint.
        await audit_user_change(
            db, tenant_id=tenant.org_id, actor_id=uid, action="user.password_reset",
            target_id=uid, reason="password reset with a one-time e-mail link (no hash recorded)",
            tool_or_endpoint="POST /api/auth/reset-password", session=session)

    try:
        await run_in_transaction(db, body)
    except _ClaimLost:
        await deny(auth_events.RESET_REPLAY, **where, detail={"stage": "claim"})
    except Exception as exc:
        logger.error("PASSWORD_RESET_NOT_COMPLETED user_id=%s error=%s", uid,
                     type(exc).__name__)
        await auth_events.record(db, auth_events.RESET_NOT_COMPLETED, ip=requested_ip, **where,
                                 detail={"error": type(exc).__name__})
        raise ResetNotCompleted() from exc
    return user
