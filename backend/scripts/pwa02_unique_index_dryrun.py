"""PWA-02 FG-636 — READ-ONLY dry run for the offline-sync unique indexes.

Reports, per tenant database, the rows that stop a unique index from being created (the
startup then logs an ALARM and skips that index), and, for attendance, what a backfill of
``attendance_day_key`` onto older rows would find: worker+day groups with more than one entry.

It never writes. Fixing duplicates is a data decision (which entry stays) — a migration with
Approval (CLAUDE.md §8), not this script.

    PYTHONPATH=. python scripts/pwa02_unique_index_dryrun.py --mongo-url '<url>' --db <op_db> [--registry-db <system_db>]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorClient


async def _dupes(coll, keys: List[str], field: str, limit: int = 50) -> List[Dict[str, Any]]:
    pipeline = [
        {"$match": {field: {"$type": "string"}}},
        {"$group": {"_id": {k: "$" + k for k in keys}, "n": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": limit},
    ]
    return [{"key": d["_id"], "rows": d["n"], "ids": d["ids"][:10]}
            async for d in coll.aggregate(pipeline)]


async def _attendance_backfill(coll, limit: int = 50) -> Dict[str, Any]:
    without = await coll.count_documents({"attendance_day_key": {"$exists": False}})
    pipeline = [
        {"$group": {"_id": {"org_id": "$org_id", "user_id": "$user_id", "project_id": "$project_id", "date": "$date"},
                    "n": {"$sum": 1}, "ids": {"$push": "$id"}, "projects": {"$addToSet": "$project_id"},
                    "sources": {"$addToSet": "$source"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": limit},
    ]
    groups = [{"key": d["_id"], "rows": d["n"], "ids": d["ids"][:10], "projects": d["projects"],
               "sources": d["sources"]} async for d in coll.aggregate(pipeline)]
    return {"rows_without_key": without, "worker_day_groups_with_more_than_one_entry": groups}


async def run(url: str, db_name: str, registry_db: str | None) -> Dict[str, Any]:
    from app.services.offline_sync import UNIQUE_INDEXES
    client = AsyncIOMotorClient(url)
    try:
        names = [db_name]
        if registry_db:
            async for r in client[registry_db]["tenant_registry"].find({}, {"_id": 0, "database_name": 1}):
                n = r.get("database_name")
                if n and n not in names:
                    names.append(n)
        out: Dict[str, Any] = {"mode": "dry-run (read-only)", "databases": {}}
        for name in names:
            d = client[name]
            rep: Dict[str, Any] = {}
            for coll, keys, index, field in UNIQUE_INDEXES:
                rep[index] = await _dupes(d[coll], [k for k, _ in keys], field)
            rep["attendance_day_key_backfill"] = await _attendance_backfill(d["attendance_entries"])
            out["databases"][name] = rep
        return out
    finally:
        client.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mongo-url", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--registry-db")
    a = ap.parse_args(argv)
    print(json.dumps(asyncio.run(run(a.mongo_url, a.db, a.registry_db)), ensure_ascii=False, indent=1,
                     default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
