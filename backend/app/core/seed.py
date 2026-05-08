"""
Production-safe seed data initialization.

Creates the initial admin user, organization, subscription, and feature flags
ONLY when both SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD environment variables
are explicitly set. Idempotent: skips if the admin user already exists.

Moved from server.py during M16.8 refactor (2026-05-06).
"""
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta

from app.db import db
from app.constants import MODULES
from app.deps.auth import hash_password

logger = logging.getLogger(__name__)


async def seed_data() -> None:
    """Production-safe seed.

    Only creates the initial admin user if BOTH environment variables are set:
    - SEED_ADMIN_EMAIL
    - SEED_ADMIN_PASSWORD

    This prevents predictable default credentials (admin123) in production.
    For dev/test, set these env vars or use pytest fixtures.
    """
    seed_email = os.environ.get("SEED_ADMIN_EMAIL", "").strip()
    seed_password = os.environ.get("SEED_ADMIN_PASSWORD", "").strip()

    if not seed_email or not seed_password:
        logger.warning(
            "Seed skipped: missing SEED_ADMIN_EMAIL/SEED_ADMIN_PASSWORD. "
            "Set both env vars to create initial admin user."
        )
        return

    # Idempotent check: skip if admin already exists
    existing = await db.users.find_one({"email": seed_email})
    if existing:
        logger.info(f"Seed data already exists for {seed_email}, skipping")
        return

    logger.info(f"Creating seed data with admin: {seed_email}")

    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

    await db.organizations.insert_one({
        "id": org_id,
        "name": "BEG_Work Production",
        "slug": "begwork-prod",
        "address": "",
        "phone": "",
        "email": seed_email,
        "logo_url": "",
        "subscription_plan": "enterprise",
        "subscription_status": "active",
        "subscription_expires_at": expires,
        "created_at": now,
        "updated_at": now,
    })

    user_id = str(uuid.uuid4())
    await db.users.insert_one({
        "id": user_id,
        "org_id": org_id,
        "email": seed_email,
        "password_hash": hash_password(seed_password),
        "first_name": "System",
        "last_name": "Admin",
        "role": "Admin",
        "phone": "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    })

    for code, info in MODULES.items():
        await db.feature_flags.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "module_code": code,
            "module_name": info["name"],
            "description": info["description"],
            "enabled": code == "M0",
            "updated_at": now,
            "updated_by": user_id,
        })

    await db.subscriptions.insert_one({
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "plan": "enterprise",
        "plan_id": "enterprise",
        "status": "active",
        "started_at": now,
        "expires_at": expires,
        "payment_method": "seed",
        "amount": 0,
        "currency": "EUR",
        "created_at": now,
    })

    logger.info(f"Seed data created successfully for: {seed_email}")
