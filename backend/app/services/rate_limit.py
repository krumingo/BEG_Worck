"""
AUTH-01 C01 (F-04) — a shared, atomic rate limiter for the pre-session auth surface.

The previous limiter lived in process memory: every worker and every restart had
its own counters. These counters live in MongoDB (``auth_rate_limits``) so all
workers and instances that share the database share them.

Fixed window, one document per (scope, key, window): a single atomic
``find_one_and_update`` with ``$inc`` and ``upsert`` both counts and reads the
hit, so two concurrent requests cannot both see "first". The key is a keyed
HMAC (never a raw email or IP), and each document expires with its window (TTL).

Fail closed: if the counter cannot be updated the hit is treated as NOT allowed;
the caller decides what that means for its response.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.services.auth_events import keyed_ref

logger = logging.getLogger("beg.rate_limit")

COLLECTION = "auth_rate_limits"


@dataclass(frozen=True)
class Hit:
    allowed: bool
    count: int
    limit: int

    @property
    def first_rejection(self) -> bool:
        """True exactly once per window — the hit that first went over the limit."""
        return self.count == self.limit + 1


async def ensure_indexes(db) -> None:
    await db.auth_rate_limits.create_index(
        "expires_at", expireAfterSeconds=0, name="expires_at_ttl")


async def hit(db, scope: str, key: str, limit: int, window_seconds: int,
              now: Optional[datetime] = None) -> Hit:
    """Count one request for ``(scope, key)`` and say whether it is within ``limit``."""
    now = now or datetime.now(timezone.utc)
    window = int(now.timestamp()) // window_seconds
    window_end = datetime.fromtimestamp((window + 1) * window_seconds, tz=timezone.utc)
    bucket = f"{scope}:{keyed_ref(key or '-')}:{window}"
    for _attempt in range(2):
        try:
            doc = await db.auth_rate_limits.find_one_and_update(
                {"_id": bucket},
                {"$inc": {"count": 1},
                 "$setOnInsert": {"scope": scope,
                                  "expires_at": window_end + timedelta(seconds=60)}},
                upsert=True, return_document=ReturnDocument.AFTER)
            count = int(doc["count"])
            return Hit(allowed=count <= limit, count=count, limit=limit)
        except DuplicateKeyError:
            continue                    # two first hits raced on the upsert: retry once
        except Exception as exc:
            logger.error("RATE_LIMIT_UNAVAILABLE scope=%s error=%s", scope, type(exc).__name__)
            break
    return Hit(allowed=False, count=limit + 1, limit=limit)
