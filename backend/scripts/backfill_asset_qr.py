"""
ONE-TIME backfill for the Assets module (Етап 0).

Generates a unique QR for every EXISTING project, active employee (user) and
warehouse across ALL organizations that don't already have one. Idempotent:
entities that already have a QR are skipped, so re-running changes nothing.

Run once after deploying the Assets module:
    cd backend && python -m scripts.backfill_asset_qr

This reuses the exact same logic as POST /assets/qr/generate-bulk, but loops
over every org (the endpoint is scoped to a single admin's org).
"""
import asyncio

from app.db import db
from app.tenancy.data_access import all_tenant_ids
from app.routes.assets_qr import _make_qr

CREATED_BY = "system-backfill"


async def backfill():
    # W0-03E-A2C: tenants come from the one declared enumeration helper
    # (app.tenancy.data_access.all_tenant_ids), not from distinct("org_id") over
    # three business collections — that read a raw handle for each of them and
    # would also "find" a tenant that has no organization row at all.
    org_ids = set(await all_tenant_ids(db))

    grand = {"project": 0, "employee": 0, "warehouse": 0}

    for org_id in sorted(org_ids):
        async for p in db.projects.find({"org_id": org_id}, {"_id": 0, "id": 1, "name": 1, "code": 1}):
            if await db.asset_qr_codes.find_one({"org_id": org_id, "entity_type": "project", "entity_id": p["id"]}):
                continue
            await _make_qr(org_id, CREATED_BY, "project", p["id"], p.get("name", ""), p.get("code", ""))
            grand["project"] += 1

        async for u in db.users.find(
            {"org_id": org_id, "is_active": True},
            {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1, "email": 1},
        ):
            if await db.asset_qr_codes.find_one({"org_id": org_id, "entity_type": "employee", "entity_id": u["id"]}):
                continue
            nm = (u.get("name")
                  or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                  or (u.get("email", "").split("@")[0] if u.get("email") else ""))
            await _make_qr(org_id, CREATED_BY, "employee", u["id"], nm, "")
            grand["employee"] += 1

        async for w in db.warehouses.find({"org_id": org_id}, {"_id": 0, "id": 1, "name": 1}):
            if await db.asset_qr_codes.find_one({"org_id": org_id, "entity_type": "warehouse", "entity_id": w["id"]}):
                continue
            await _make_qr(org_id, CREATED_BY, "warehouse", w["id"], w.get("name", ""), "")
            grand["warehouse"] += 1

    print(f"Backfill done across {len(org_ids)} org(s): {grand} (total {sum(grand.values())})")


if __name__ == "__main__":
    asyncio.run(backfill())
