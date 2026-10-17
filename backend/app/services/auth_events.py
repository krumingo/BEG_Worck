"""
AUTH-01 C01 (F-08) — durable, privacy-preserving security events for auth.

Denials and throttling on the pre-session auth surface (forgot / reset password,
ambiguous login) used to live only in the process log. They are now rows in
``auth_security_events`` so abuse and replay stay observable after a restart and
can be correlated:

* the email is never stored — ``subject`` is a keyed HMAC-SHA256 of the
  normalized email (key ``AUTH_EVENT_HMAC_KEY``, else ``JWT_SECRET``), so the
  same address correlates across events without being readable;
* a token is never stored — ``token_ref`` is the stored token row's ``id`` when
  one was found, else a keyed HMAC of the presented token's hash;
* no password, hash or response body is ever written.

The collection is installation-level security bookkeeping (an unknown email has
no tenant), classified TECHNICAL in ``app.tenancy.ownership``. Tenant business
history stays in that tenant's ``audit_logs``. Rows expire after
:data:`RETENTION` (TTL index; owner decision 180 days).

Writing an event never raises into the caller: a lost event is logged, the
request outcome is unchanged.
"""
import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("beg.auth_events")

COLLECTION = "auth_security_events"
RETENTION = timedelta(days=180)

# event names
FORGOT_NO_MATCH = "forgot_no_match"
FORGOT_AMBIGUOUS = "forgot_ambiguous"
FORGOT_NOT_ELIGIBLE = "forgot_not_eligible"
FORGOT_FAILED = "forgot_processing_failed"
RATE_LIMITED_IP = "rate_limited_ip"
RATE_LIMITED_EMAIL = "rate_limited_email"
RESET_INVALID = "reset_token_invalid"
RESET_EXPIRED = "reset_token_expired"
RESET_REPLAY = "reset_token_replay"
RESET_USER_INACTIVE = "reset_user_inactive"
RESET_NOT_COMPLETED = "reset_not_completed"
DELIVERY_FAILED = "reset_delivery_failed"
DELIVERY_NOT_CONFIGURED = "reset_delivery_not_configured"
LOGIN_AMBIGUOUS = "login_ambiguous"


def _key() -> bytes:
    key = os.environ.get("AUTH_EVENT_HMAC_KEY") or os.environ.get("JWT_SECRET") \
        or "dev-auth-event-key-NOT-FOR-PRODUCTION"
    return key.encode("utf-8")


def keyed_ref(value: Optional[str]) -> Optional[str]:
    """Keyed, non-reversible reference (32 hex) for an email / token hash / IP."""
    if not value:
        return None
    return hmac.new(_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


async def ensure_indexes(db) -> None:
    await db.auth_security_events.create_index(
        "expires_at", expireAfterSeconds=0, name="expires_at_ttl")
    await db.auth_security_events.create_index(
        [("event", 1), ("ts", -1)], name="event_ts")
    await db.auth_security_events.create_index(
        [("subject", 1), ("ts", -1)], name="subject_ts")


async def record(db, event: str, *, ip: Optional[str] = None, subject: Optional[str] = None,
                 token_ref: Optional[str] = None, org_id: Optional[str] = None,
                 user_id: Optional[str] = None, detail: Optional[dict] = None,
                 now: Optional[datetime] = None) -> None:
    """Store one event. ``subject``/``token_ref`` must already be keyed refs."""
    now = now or datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "ts": now,
        "expires_at": now + RETENTION,
        "event": event,
        "ip": ip,
        "subject": subject,
        "token_ref": token_ref,
        "org_id": org_id,
        "user_id": user_id,
        "detail": detail or {},
    }
    try:
        await db.auth_security_events.insert_one(doc)
    except Exception as exc:          # an event must never change the outcome
        logger.error("AUTH_SECURITY_EVENT_LOST event=%s error=%s", event, type(exc).__name__)
