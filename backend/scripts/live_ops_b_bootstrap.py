#!/usr/bin/env python3
"""
LIVE-OPS-01 / TASK 5B — inventory, bootstrap and verify the request-write
prerequisites of ONE OR MORE tenant databases.

The prerequisite list is ``REQUIRED_UNIQUE_INDEXES`` of
``app/services/material_request_commands.py`` — the same tuple the runtime
gate checks before every request command, so the tool and the gate cannot
drift apart:

  * ``audit_events``       unique ``event_id`` and ``(tenant_id, sequence)``;
  * ``audit_idempotency``  unique ``id``;
  * ``material_requests``  unique ``(org_id, request_number)``, partial on a
                           string ``request_number``.

Modes (one per run):

  --inventory  (default) READ-ONLY. Per database: request-number duplicates
               per tenant (with the ids involved), non-standard and missing
               numbers, the highest number, duplicate audit/idempotency keys
               that would block the indexes, and which required indexes are
               present. Writes nothing. The report is deterministic for
               unchanged data and carries its own SHA-256.
  --apply      Creates the missing required indexes, but ONLY when the
               inventory of that database has no blocking row; otherwise it
               stops for that database and changes nothing there. Every
               database must be named twice (``--db X --confirm-db X``).
               Re-running is a no-op.
  --verify     Exit 0 only when every required index is present in every
               named database (the same check the runtime gate makes).

It never edits, renumbers, merges or deletes any business record: legacy
duplicates are reported for a separately approved migration task.

Usage:
    python scripts/live_ops_b_bootstrap.py --db TENANT_DB [--db ...]
    python scripts/live_ops_b_bootstrap.py --all-tenants              # from the registry
    python scripts/live_ops_b_bootstrap.py --apply --db X --confirm-db X
    python scripts/live_ops_b_bootstrap.py --verify --db X
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.material_request_commands import (  # noqa: E402
    COLLECTION, REQUEST_NUMBER_PATTERN, REQUIRED_UNIQUE_INDEXES, missing_required_indexes,
)

EXIT_OK, EXIT_BLOCKED, EXIT_MISSING, EXIT_USAGE = 0, 2, 3, 64
_NUM = re.compile(REQUEST_NUMBER_PATTERN)


async def _dupes(coll, keys: List[str], match: Dict[str, Any]) -> List[Dict[str, Any]]:
    group = {k: "$" + k for k in keys}
    rows = await coll.aggregate([
        {"$match": match},
        {"$group": {"_id": group, "count": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"_id": 1}},
    ]).to_list(None)
    return [{**r["_id"], "count": r["count"], "ids": sorted(str(i) for i in r["ids"] if i is not None)}
            for r in rows]


async def inventory(db) -> Dict[str, Any]:
    """Read-only report for one database."""
    reqs = db[COLLECTION]
    per_org: Dict[str, Dict[str, Any]] = {}
    async for d in reqs.find({}, {"_id": 0, "org_id": 1, "request_number": 1}):
        o = per_org.setdefault(str(d.get("org_id")), {"requests": 0, "missing_number": 0,
                                                       "non_standard_number": 0, "max_number": 0})
        o["requests"] += 1
        num = d.get("request_number")
        if not isinstance(num, str):
            o["missing_number"] += 1
        elif not _NUM.match(num):
            o["non_standard_number"] += 1
        else:
            o["max_number"] = max(o["max_number"], int(num[3:]))
    request_dupes = await _dupes(reqs, ["org_id", "request_number"],
                                 {"request_number": {"$type": "string"}})
    audit_event_dupes = await _dupes(db["audit_events"], ["event_id"], {})
    audit_seq_dupes = await _dupes(db["audit_events"], ["tenant_id", "sequence"], {})
    idem_dupes = await _dupes(db["audit_idempotency"], ["id"], {})
    info = {c: await db[c].index_information() for c in sorted({c for c, _, _ in REQUIRED_UNIQUE_INDEXES})}
    missing = missing_required_indexes(info)
    blocking = bool(request_dupes or audit_event_dupes or audit_seq_dupes or idem_dupes)
    report = {
        "database": db.name,
        "tenants": dict(sorted(per_org.items())),
        "request_number_duplicates": request_dupes,
        "audit_event_id_duplicates": audit_event_dupes,
        "audit_sequence_duplicates": audit_seq_dupes,
        "idempotency_id_duplicates": idem_dupes,
        "missing_indexes": missing,
        "blocking": blocking,
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return report


async def apply(db) -> Dict[str, Any]:
    """Create the missing required indexes when (and only when) nothing blocks them."""
    rep = await inventory(db)
    if rep["blocking"]:
        return {"database": db.name, "applied": [], "status": "BLOCKED", "inventory": rep}
    created = []
    for coll, keys, partial in REQUIRED_UNIQUE_INDEXES:
        if not any(m["collection"] == coll and m["keys"] == [k for k, _ in keys]
                   for m in rep["missing_indexes"]):
            continue
        opts: Dict[str, Any] = {"unique": True,
                                "name": "liveops_b_uniq_" + "_".join(k for k, _ in keys)}
        if partial is not None:
            opts["partialFilterExpression"] = partial
        await db[coll].create_index(list(keys), **opts)
        created.append({"collection": coll, "keys": [k for k, _ in keys], "name": opts["name"]})
    after = await verify(db)
    return {"database": db.name, "applied": created,
            "status": "OK" if after["ok"] else "MISSING", "verify": after}


async def verify(db) -> Dict[str, Any]:
    info = {c: await db[c].index_information() for c in sorted({c for c, _, _ in REQUIRED_UNIQUE_INDEXES})}
    missing = missing_required_indexes(info)
    return {"database": db.name, "ok": not missing, "missing_indexes": missing}


async def _tenant_databases(client, system_db: str) -> List[str]:
    rows = await client[system_db].tenant_registry.find({}, {"_id": 0, "database_name": 1}).to_list(None)
    return sorted({r["database_name"] for r in rows if r.get("database_name")})


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--inventory", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    ap.add_argument("--db", action="append", default=[])
    ap.add_argument("--confirm-db", action="append", default=[])
    ap.add_argument("--all-tenants", action="store_true")
    ap.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    ap.add_argument("--system-db", default=os.environ.get("BEG_SYSTEM_DB", "begwork_system"))
    a = ap.parse_args(argv)

    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(a.mongo_url, serverSelectionTimeoutMS=5000)
    try:
        names = list(a.db)
        if a.all_tenants:
            names += await _tenant_databases(client, a.system_db)
        names = sorted(set(names))
        if not names:
            print("no database named (--db or --all-tenants)", file=sys.stderr)
            return EXIT_USAGE
        if a.apply and sorted(set(a.confirm_db)) != names:
            print("--apply needs every database repeated with --confirm-db", file=sys.stderr)
            return EXIT_USAGE
        out, code = [], EXIT_OK
        for name in names:
            db = client[name]
            if a.apply:
                r = await apply(db)
                code = max(code, EXIT_BLOCKED if r["status"] == "BLOCKED" else
                           EXIT_MISSING if r["status"] != "OK" else EXIT_OK)
            elif a.verify:
                r = await verify(db)
                code = max(code, EXIT_OK if r["ok"] else EXIT_MISSING)
            else:
                r = await inventory(db)
                code = max(code, EXIT_BLOCKED if r["blocking"] else EXIT_OK)
            out.append(r)
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return code
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
