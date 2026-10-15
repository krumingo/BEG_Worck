"""
AUTH-01 — self-service password reset: one-time, hashed, 30-minute tokens.

Flow
----
``request_reset`` (behind ``POST /auth/forgot-password``)
    Starts from an email and no session. Exactly ONE active user must match the
    email case-insensitively (``resolve_identities_by_email``); zero, several or
    a disabled one produce nothing — and the caller answers the same generic
    sentence in every case, so the response never says whether an account
    exists. For the one user, every older still-usable token is invalidated and
    a new random token is minted. Only its SHA-256 is stored; the plaintext
    leaves this module once, inside the :class:`ResetMail` handed to
    :func:`deliver`, and is never logged or returned by the API.

``reset_password`` (behind ``POST /auth/reset-password``)
    Hashes the presented token and needs exactly one stored row for it
    (``resolve_owner_by_unique_key``: fail closed, never first-match). The row
    must be unused and unexpired and its user active. The token is CLAIMED with
    one conditional ``find_one_and_update`` (``used_at: None`` and not expired
    in the filter), so two concurrent submissions cannot both succeed; only the
    winner then writes the new password and invalidates the user's remaining
    tokens. Every failure is the same :class:`ResetFailed`.

Ordering note: claiming the token BEFORE the password write means a crash in
between leaves a consumed token and the old password — the user simply asks for
a new link. The opposite order could leave a reusable token behind a changed
password, which is the unsafe side.

Storage: ``password_reset_tokens`` {id, org_id, user_id, token_hash,
requested_at, expires_at, used_at, requested_ip}. ``expires_at`` is a BSON date
so the TTL index can purge expired rows; the audit trail lives in
``audit_logs``.
"""
import hashlib
import logging
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services.mailer import app_public_url, get_mail_provider
from app.tenancy.data_access import (
    TenantData, resolve_identities_by_email, resolve_owner_by_unique_key)
from app.utils.audit import log_audit, security_logger

logger = logging.getLogger("beg.password_reset")

COLLECTION = "password_reset_tokens"
TOKEN_TTL = timedelta(minutes=30)
TOKEN_BYTES = 32                    # 256 bits of entropy
TOKEN_MIN_LENGTH, TOKEN_MAX_LENGTH = 20, 256

#: Explicit opt-in for LOCAL development only: with no outbound e-mail
#: configured, print the reset URL to the server console. Ignored when
#: ``ENV=production``.
DEV_LOG_URL_FLAG = "PASSWORD_RESET_DEV_LOG_URL"

GENERIC_REQUEST_MESSAGE = ("If an active account exists for this email, "
                           "we sent a password reset link.")
GENERIC_RESET_FAILURE = "This password reset link is invalid or has expired."

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


@dataclass(frozen=True)
class ResetMail:
    """What :func:`deliver` needs. ``token`` is plaintext: never log this object."""
    to: str
    user_id: str
    org_id: str
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
async def request_reset(db, email: str, requested_ip: Optional[str],
                        now: Optional[datetime] = None) -> Optional[ResetMail]:
    """Mint a token for the ONE active user ``email`` names; ``None`` otherwise.

    The return value is for the caller to hand to :func:`deliver`; it must never
    shape the HTTP response.
    """
    candidates = await resolve_identities_by_email(
        db, email, {"_id": 0, "id": 1, "org_id": 1, "email": 1, "is_active": 1})
    if len(candidates) != 1:
        security_logger.info("PASSWORD_RESET_REQUEST outcome=%s ip=%s",
                             "ambiguous_email" if candidates else "no_match", requested_ip)
        if len(candidates) > 1:
            logger.warning("PASSWORD_RESET_REQUEST refused: %d users share this email up to "
                           "letter case (user_ids=%s); resolve the duplicate",
                           len(candidates), [c.get("id") for c in candidates])
        return None
    user = candidates[0]
    uid, org_id = user.get("id"), user.get("org_id")
    if not user.get("is_active", True) or not isinstance(uid, str) or not uid \
            or not isinstance(org_id, str) or not org_id:
        security_logger.info("PASSWORD_RESET_REQUEST outcome=not_eligible ip=%s", requested_ip)
        return None

    tenant = TenantData.for_owner_of(db, user)
    now = now or datetime.now(timezone.utc)
    await tenant.password_reset_tokens.update_many(
        {"user_id": uid, "used_at": None},
        {"$set": {"used_at": now, "revoked_reason": "superseded"}})
    token = secrets.token_urlsafe(TOKEN_BYTES)
    await tenant.password_reset_tokens.insert_one({
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": uid,
        "token_hash": hash_token(token),
        "requested_at": now,
        "expires_at": now + TOKEN_TTL,
        "used_at": None,
        "requested_ip": requested_ip,
    })
    await log_audit(org_id, uid, user.get("email"), "password_reset_requested", "user", uid,
                    {"requested_ip": requested_ip}, db_handle=db)
    return ResetMail(to=user["email"].strip(), user_id=uid, org_id=org_id, token=token)


def _dev_url_logging_enabled() -> bool:
    if os.environ.get("ENV", "development").strip().lower() == "production":
        return False
    return os.environ.get(DEV_LOG_URL_FLAG, "").strip().lower() in ("1", "true", "yes")


def deliver(mail: ResetMail) -> bool:
    """Send the reset link. ``True`` only when the provider accepted the message.

    Never logs the token or the link — except the explicit local-development
    flag above, outside production, when no e-mail is configured.
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
        return False
    url = f"{base}/reset-password?token={mail.token}"
    try:
        provider.send(mail.to, MAIL_SUBJECT, MAIL_TEXT.format(url=url))
    except Exception as exc:          # delivery must never surface to the requester
        logger.error("PASSWORD_RESET_EMAIL_FAILED user_id=%s provider=%s error=%s",
                     mail.user_id, provider.name, type(exc).__name__)
        return False
    logger.info("PASSWORD_RESET_EMAIL_SENT user_id=%s provider=%s", mail.user_id, provider.name)
    return True


# -------------------------------------------------------------------- reset
async def reset_password(db, token: str, new_password_hash: str,
                         now: Optional[datetime] = None) -> dict:
    """Consume ``token`` and set the password; the user row on success.

    ``new_password_hash`` is already strength-checked and hashed by the caller.
    Raises :class:`ResetFailed` for every unusable token.
    """
    if not isinstance(token, str) or not TOKEN_MIN_LENGTH <= len(token) <= TOKEN_MAX_LENGTH:
        raise ResetFailed()
    now = now or datetime.now(timezone.utc)
    tenant, row = await resolve_owner_by_unique_key(
        db, COLLECTION, "token_hash", hash_token(token), {"_id": 0})
    if row is None:
        raise ResetFailed()
    expires_at = _aware(row.get("expires_at"))
    if row.get("used_at") is not None or expires_at is None or expires_at <= now:
        raise ResetFailed()
    uid = row.get("user_id")
    user = await tenant.users.get(uid, {"_id": 0, "id": 1, "org_id": 1, "email": 1,
                                        "is_active": 1})
    if not user or not user.get("is_active", True):
        raise ResetFailed()

    # The single-use guarantee: only one caller can flip used_at from None.
    claimed = await tenant.password_reset_tokens.find_one_and_update(
        {"id": row["id"], "user_id": uid, "used_at": None, "expires_at": {"$gt": now}},
        {"$set": {"used_at": now}})
    if not claimed:
        raise ResetFailed()

    stamp = now.isoformat()
    result = await tenant.users.update_one(
        {"id": uid},
        {"$set": {
            "password_hash": new_password_hash,
            "updated_at": stamp,
            "password_reset_at": stamp,
            "password_reset_by": "SELF_SERVICE_TOKEN",
        }})
    if result.matched_count != 1:
        raise ResetFailed()
    await tenant.password_reset_tokens.update_many(
        {"user_id": uid, "used_at": None},
        {"$set": {"used_at": now, "revoked_reason": "password_reset"}})
    await log_audit(tenant.org_id, uid, user.get("email"), "password_reset_completed", "user",
                    uid, {"method": "self_service_token"}, db_handle=db)
    return user
