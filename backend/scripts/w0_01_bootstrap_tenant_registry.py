#!/usr/bin/env python3
"""
W0-01 — Bootstrap the Tenant Registry from the existing installation.

What it does:
  * reads existing `organizations` from the current operational database;
  * writes one tenant_registry record per organization into the SYSTEM database;
  * writes one tenant_membership per existing user;
  * mirrors each user's current single `role` into tenant_role_assignments.

What it does NOT do:
  * it never writes to, alters or deletes anything in the operational database;
  * it never touches users, projects, invoices or any business collection;
  * `org_id` fields stay exactly as they are.

Idempotent: running it twice changes nothing (upsert by id).

Usage:
    python scripts/w0_01_bootstrap_tenant_registry.py            # dry run
    python scripts/w0_01_bootstrap_tenant_registry.py --apply    # write
    python scripts/w0_01_bootstrap_tenant_registry.py --verify   # check only
"""
import asyncio
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
OPERATIONAL_DB = os.environ.get('DB_NAME', 'begwork')
SYSTEM_DB = os.environ.get('BEG_SYSTEM_DB', 'begwork_system')

client = AsyncIOMotorClient(MONGO_URL)
op_db = client[OPERATIONAL_DB]
sys_db = client[SYSTEM_DB]

SCHEMA_VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_tenant_record(org: dict, is_primary: bool) -> dict:
    """One organization -> one tenant registry record."""
    return {
        "id": org["id"],
        "name": org.get("name", "Unnamed"),
        "slug": org.get("slug", ""),
        "legal_name": org.get("name", ""),
        "eik": org.get("eik", ""),
        "vat_number": org.get("vat_number", ""),
        "email": org.get("email", ""),
        "phone": org.get("phone", ""),
        "address": org.get("address", ""),
        "timezone": org.get("org_timezone", "Europe/Sofia"),
        "currency": org.get("currency", "BGN"),
        "vat_percent": org.get("vat_percent", 20.0),

        # Resolver target. The first tenant keeps the existing database.
        "database_name": OPERATIONAL_DB if is_primary else f"begwork_tenant_{org.get('slug', org['id'])}",
        "is_primary_installation": is_primary,

        # Subscription / lifecycle (FLOW-050). Migrated as-is.
        "status": "active",
        "plan": org.get("subscription_plan", "pro"),
        "plan_version": "migrated-2026-08",
        "subscription_status": org.get("subscription_status", "active"),

        # Storage provider (D-11 / FLOW-016). Existing install keeps local
        # storage until it is onboarded properly in W0-04.
        "storage_provider": "legacy_local" if is_primary else None,
        "storage_status": "grandfathered" if is_primary else "not_configured",

        # Migration bookkeeping.
        "schema_version": SCHEMA_VERSION,
        "migration_status": "bootstrapped",
        "last_successful_migration": now(),

        "created_at": org.get("created_at", now()),
        "updated_at": now(),
        "migrated_from": "organizations",
        "migrated_at": now(),
    }


async def collect():
    orgs = await op_db.organizations.find({}, {"_id": 0}).to_list(1000)
    users = await op_db.users.find({}, {"_id": 0}).to_list(10000)
    return orgs, users


async def run(apply: bool, verify_only: bool):
    orgs, users = await collect()

    print(f"Source database : {OPERATIONAL_DB}")
    print(f"System database : {SYSTEM_DB}")
    print(f"Organizations   : {len(orgs)}")
    print(f"Users           : {len(users)}")
    print()

    if not orgs:
        print("No organizations found. Nothing to bootstrap.")
        return 1

    # The oldest organization is the primary installation and keeps the
    # existing database. Platform System is never treated as primary.
    real_orgs = [o for o in orgs if o.get("slug") != "platform-system"]
    ordered = sorted(real_orgs or orgs, key=lambda o: o.get("created_at", ""))
    primary_id = ordered[0]["id"] if ordered else None

    tenants = [build_tenant_record(o, o["id"] == primary_id) for o in orgs]

    memberships = []
    assignments = []
    for u in users:
        org_id = u.get("org_id")
        if not org_id:
            print(f"  ! user {u.get('email')} has no org_id — skipped")
            continue
        memberships.append({
            "id": f"tm_{u['id']}_{org_id}",
            "user_id": u["id"],
            "tenant_id": org_id,
            "email": u.get("email", ""),
            "status": "active" if u.get("is_active", True) else "disabled",
            "is_owner": u.get("role") == "Owner",
            "created_at": now(),
            "migrated_from": "users.org_id",
        })
        assignments.append({
            "id": f"ra_{u['id']}_{org_id}_legacy",
            "user_id": u["id"],
            "tenant_id": org_id,
            "role": u.get("role", "Viewer"),
            "scope_type": "company",
            "scope_ids": [],
            "status": "active",
            "created_at": now(),
            "migrated_from": "users.role",
            "note": "Mirrored from the legacy single-role field; not yet authoritative.",
        })

    print("Planned tenant records:")
    for t in tenants:
        flag = " (primary — keeps existing database)" if t["is_primary_installation"] else ""
        print(f"  - {t['name']}: db={t['database_name']}{flag}")
    print(f"\nPlanned memberships : {len(memberships)}")
    print(f"Planned assignments : {len(assignments)}")

    if verify_only:
        existing = await sys_db.tenant_registry.count_documents({})
        m = await sys_db.tenant_memberships.count_documents({})
        print(f"\nIn system database now: {existing} tenants, {m} memberships")
        return 0

    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return 0

    for t in tenants:
        await sys_db.tenant_registry.update_one({"id": t["id"]}, {"$set": t}, upsert=True)
    for m in memberships:
        await sys_db.tenant_memberships.update_one({"id": m["id"]}, {"$set": m}, upsert=True)
    for a in assignments:
        await sys_db.tenant_role_assignments.update_one({"id": a["id"]}, {"$set": a}, upsert=True)

    await sys_db.tenant_registry.create_index("id", unique=True)
    await sys_db.tenant_memberships.create_index([("user_id", 1), ("tenant_id", 1)])
    await sys_db.tenant_role_assignments.create_index([("user_id", 1), ("tenant_id", 1)])

    print("\nWritten. Verifying...")
    assert await sys_db.tenant_registry.count_documents({}) >= len(tenants)
    assert await sys_db.tenant_memberships.count_documents({}) >= len(memberships)

    # Prove the operational database was not touched.
    after_orgs = await op_db.organizations.count_documents({})
    after_users = await op_db.users.count_documents({})
    assert after_orgs == len(orgs), "organizations count changed!"
    assert after_users == len(users), "users count changed!"
    print(f"Operational database untouched: {after_orgs} organizations, {after_users} users.")
    print("Bootstrap complete.")
    return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    verify = "--verify" in sys.argv
    sys.exit(asyncio.run(run(apply, verify)))
