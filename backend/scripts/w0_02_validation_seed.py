#!/usr/bin/env python3
"""Synthetic seed/reset. No application or driver imports before exact guard."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from w0_02_validation_env import require_validation_env, require_runtime_env, VALIDATION_ENV

SYNTHETIC_USERS = {"u_admin": "Admin", "u_view": "Viewer", "u_tech": "Technician", "u_sm": "SiteManager"}


def guarded_client(mongo_url, db_name, sys_db):
    require_validation_env(mongo_url, db_name, sys_db)
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000,
                             connectTimeoutMS=5000, socketTimeoutMS=15000)


def _check_handles(op, sy):
    require_runtime_env()
    if op.name != VALIDATION_ENV["DB_NAME"] or sy.name != VALIDATION_ENV["BEG_SYSTEM_DB"]:
        raise SystemExit("FAIL-CLOSED: seed/reset received unexpected DB handles")
    if op.client is not sy.client:
        raise SystemExit("FAIL-CLOSED: seed/reset DB handles have different clients")


async def reset_docs(op, sy):
    _check_handles(op, sy)
    for db in (op, sy):
        for name in await db.list_collection_names():
            await db[name].drop()


async def seed_docs(op, sy):
    _check_handles(op, sy)
    await op.organizations.insert_one({"id": "T1", "name": "BEG"})
    for uid, role in SYNTHETIC_USERS.items():
        await op.users.insert_one({"id": uid, "org_id": "T1", "role": role, "is_active": True})
        await sy.tenant_role_assignments.insert_one({
            "id": f"ra_{uid}_T1_legacy", "user_id": uid, "tenant_id": "T1", "role": role,
            "scope_type": "company", "scope_ids": [], "status": "active",
            "created_at": "2026-08-01T00:00:00+00:00", "migrated_from": "users.role"})
    await op.projects.insert_one({"id": "P1", "org_id": "T1"})
    await op.project_team.insert_many([
        {"id": "pt_v", "project_id": "P1", "user_id": "u_view", "role_in_project": "Worker", "active": True},
        {"id": "pt_s", "project_id": "P1", "user_id": "u_sm", "role_in_project": "SiteManager", "active": True},
    ])


async def reset_and_seed(mongo_url, db_name, sys_db):
    client = guarded_client(mongo_url, db_name, sys_db)
    try:
        op, sy = client[db_name], client[sys_db]
        await reset_docs(op, sy)
        await seed_docs(op, sy)
        print("seed OK — synthetic users:", await op.users.count_documents({}))
    finally:
        client.close()


if __name__ == "__main__":
    env = require_runtime_env()
    asyncio.run(reset_and_seed(*(env[k] for k in VALIDATION_ENV)))
