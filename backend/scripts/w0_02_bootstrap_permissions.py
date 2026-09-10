#!/usr/bin/env python3
"""
W0-02 — Upgrade legacy RoleAssignment mirrors to the authoritative FLOW-002 shape.

What it does:
  * reads existing tenant_role_assignments in the SYSTEM database (the legacy
    mirrors written by W0-01, migrated_from="users.role");
  * upgrades each IN PLACE to the authoritative shape (role_id, module,
    permissions, valid_from/valid_to, max_amount, created_by/approved_by,
    scope_id from scope_ids[0]);
  * creates the W0-02 indexes.

What it does NOT do:
  * it never writes to, alters or deletes anything in the OPERATIONAL database;
  * it never invents business meaning: Technician/Viewer become the transitional
    LEGACY_TECHNICIAN / LEGACY_VIEWER, which reproduce today's behavior only.

Invariant: old real behavior -> transitional RoleAssignment (NOT old name ->
invented canonical role).

Idempotent: running twice changes nothing (in-place $set by id).

Usage:
    python scripts/w0_02_bootstrap_permissions.py            # dry run
    python scripts/w0_02_bootstrap_permissions.py --apply    # write
    python scripts/w0_02_bootstrap_permissions.py --verify   # counts only
    python scripts/w0_02_bootstrap_permissions.py --revert    # back to legacy mirror
"""
import asyncio
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

from app.permissions.catalog import LEGACY_ROLE_MAP

load_dotenv(Path(__file__).parent.parent / '.env')

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
OPERATIONAL_DB = os.environ.get('DB_NAME', 'begwork')
SYSTEM_DB = os.environ.get('BEG_SYSTEM_DB', 'begwork_system')

client = AsyncIOMotorClient(MONGO_URL)
op_db = client[OPERATIONAL_DB]
sys_db = client[SYSTEM_DB]

# Fields W0-02 adds; used by --revert to strip back to the legacy mirror.
ADDED_FIELDS = [
    "role_id", "scope_id", "module", "permissions", "max_amount",
    "valid_from", "valid_to", "created_by", "approved_by",
    "revoked_at", "revoked_by", "revoke_reason", "updated_at",
]
W0_02_INDEXES = ["uniq_assignment", "lookup_active", "by_role", "by_scope"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade_assignment(old: dict) -> dict:
    role_id = LEGACY_ROLE_MAP.get(old.get("role", ""), "LEGACY_" + str(old.get("role", "UNKNOWN")).upper())
    scope_ids = old.get("scope_ids") or []
    return {
        **old,
        "role_id": role_id,
        "scope_type": old.get("scope_type", "company"),
        "scope_id": scope_ids[0] if scope_ids else None,
        "module": None,
        "permissions": [],                       # inherit from role catalog
        "max_amount": None,
        "valid_from": old.get("created_at") or now(),
        "valid_to": None,
        "status": old.get("status", "active"),
        "created_by": old.get("created_by", "system:migration"),
        "approved_by": old.get("approved_by"),
        "note": "W0-02 upgrade of legacy mirror. LEGACY_* = compat only, not FLOW-002 canon.",
    }


async def run(apply: bool, verify_only: bool, revert: bool) -> int:
    olds = await sys_db.tenant_role_assignments.find({}, {"_id": 0}).to_list(10000)
    before = (await op_db.users.count_documents({}), await op_db.organizations.count_documents({}))

    print(f"System database    : {SYSTEM_DB}")
    print(f"Assignments found  : {len(olds)}")
    print(f"Operational (before): users={before[0]} orgs={before[1]}")
    print()

    if verify_only:
        upgraded = await sys_db.tenant_role_assignments.count_documents({"role_id": {"$exists": True}})
        print(f"Already authoritative (have role_id): {upgraded}/{len(olds)}")
        return 0

    if revert:
        print("REVERT: stripping W0-02 fields back to legacy mirror.")
        if apply:
            await sys_db.tenant_role_assignments.update_many(
                {}, {"$unset": {f: "" for f in ADDED_FIELDS}})
            for name in W0_02_INDEXES:
                try:
                    await sys_db.tenant_role_assignments.drop_index(name)
                except Exception:
                    pass
            print("Reverted.")
        else:
            print("DRY RUN — re-run with --apply to revert.")
        return 0

    plan = [upgrade_assignment(o) for o in olds]
    print("Planned upgrades (role -> role_id):")
    seen = {}
    for o in plan:
        seen[o["role_id"]] = seen.get(o["role_id"], 0) + 1
    for rid, n in sorted(seen.items()):
        tag = "" if rid in {"owner", "admin", "site_manager", "accountant", "warehouse", "driver"} else "  (transitional)"
        print(f"  - {rid}: {n}{tag}")

    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return 0

    for a in plan:
        await sys_db.tenant_role_assignments.update_one({"id": a["id"]}, {"$set": a}, upsert=True)

    # Import the app's index helper so the definition lives in one place.
    from app.tenancy import registry
    await registry.ensure_permission_indexes()

    after = (await op_db.users.count_documents({}), await op_db.organizations.count_documents({}))
    assert after == before, f"OPERATIONAL DB CHANGED! before={before} after={after}"
    print(f"\nOperational database untouched: users={after[0]} orgs={after[1]}")
    print("W0-02 permission bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(
        apply="--apply" in sys.argv,
        verify_only="--verify" in sys.argv,
        revert="--revert" in sys.argv,
    )))
