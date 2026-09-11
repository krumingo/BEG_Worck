#!/usr/bin/env python3
"""
W0-02 — Guarded seed/reset for the isolated validation Mongo.

The validation env is checked BEFORE a Mongo client is created and before ANY
database operation (drop/insert). If the target is not the exact sanctioned temp
env, the process exits non-zero (3) and no client is ever constructed.

Only synthetic test data is written. Never point this at prod / Atlas.
"""
import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.permissions.validation_env import require_validation_env


def guarded_client(mongo_url: str, db_name: str, sys_db: str):
    """Guard FIRST (raises SystemExit(3) on mismatch), then — and only then —
    import motor and construct the client. So a failed guard never opens a
    client or a connection."""
    require_validation_env(mongo_url, db_name, sys_db)
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(mongo_url)


SYNTHETIC_USERS = {"u_admin": "Admin", "u_view": "Viewer", "u_tech": "Technician", "u_sm": "SiteManager"}


async def reset_docs(op, sy):
    for d in (op, sy):
        for name in await d.list_collection_names():
            await d[name].drop()


async def seed_docs(op, sy):
    await op.organizations.insert_one({"id": "T1", "name": "BEG"})
    for uid, role in SYNTHETIC_USERS.items():
        await op.users.insert_one({"id": uid, "org_id": "T1", "role": role, "is_active": True})
        await sy.tenant_role_assignments.insert_one({
            "id": f"ra_{uid}_T1_legacy", "user_id": uid, "tenant_id": "T1", "role": role,
            "scope_type": "company", "scope_ids": [], "status": "active",
            "created_at": "2026-08-01T00:00:00+00:00", "migrated_from": "users.role"})
    await op.projects.insert_one({"id": "P1", "org_id": "T1"})
    await op.project_team.insert_one({"id": "pt_v", "project_id": "P1", "user_id": "u_view",
                                      "role_in_project": "Worker", "active": True})
    await op.project_team.insert_one({"id": "pt_s", "project_id": "P1", "user_id": "u_sm",
                                      "role_in_project": "SiteManager", "active": True})


async def reset_and_seed(mongo_url: str, db_name: str, sys_db: str):
    client = guarded_client(mongo_url, db_name, sys_db)
    op, sy = client[db_name], client[sys_db]
    await reset_docs(op, sy)
    await seed_docs(op, sy)
    n = await op.users.count_documents({})
    print(f"seed OK — op.users = {n}")
    return op, sy


if __name__ == "__main__":
    url = os.environ.get("MONGO_URL", "")
    dbn = os.environ.get("DB_NAME", "")
    sysn = os.environ.get("BEG_SYSTEM_DB", "")
    # Guard again at entry (defense in depth) before the event loop / client.
    require_validation_env(url, dbn, sysn)
    asyncio.run(reset_and_seed(url, dbn, sysn))
