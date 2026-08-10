#!/usr/bin/env python3
"""
W0-04 — Bootstrap the audit collections and indexes for one tenant database.

What it does:
  * creates the indexes for `audit_events` (unique event_id; unique
    (tenant_id, sequence) so the hash chain can have no duplicates;
    search indexes for the FLOW-040 §13 filters);
  * creates the unique index for `audit_idempotency` (one key = one write);
  * verifies an existing chain, if any events are already present.

What it does NOT do:
  * it never writes, alters or deletes any event or business record;
  * it never touches users, projects, invoices or any other collection.

Idempotent: creating an existing index is a no-op.

Usage:
    python scripts/w0_04_bootstrap_audit_indexes.py            # dry run
    python scripts/w0_04_bootstrap_audit_indexes.py --apply    # create indexes
    python scripts/w0_04_bootstrap_audit_indexes.py --verify   # check chain only
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent / '.env')

from app.audit.store import AUDIT_COLLECTION, verify_chain  # noqa: E402
from app.audit.idempotency import IDEMPOTENCY_COLLECTION  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
OPERATIONAL_DB = os.environ.get('DB_NAME', 'begwork')

client = AsyncIOMotorClient(MONGO_URL)
db = client[OPERATIONAL_DB]

PLANNED_INDEXES = [
    (AUDIT_COLLECTION, [("event_id", 1)], {"unique": True}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("sequence", 1)], {"unique": True}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("occurred_at", -1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("actor_id", 1), ("occurred_at", -1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("entity_type", 1), ("entity_id", 1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("action", 1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("correlation_id", 1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("retention_class", 1)], {}),
    (IDEMPOTENCY_COLLECTION, [("id", 1)], {"unique": True}),
    (IDEMPOTENCY_COLLECTION, [("tenant_id", 1), ("action", 1), ("key", 1)], {"unique": True}),
]


async def run(apply: bool, verify_only: bool) -> int:
    n_events = await db[AUDIT_COLLECTION].count_documents({})
    n_keys = await db[IDEMPOTENCY_COLLECTION].count_documents({})

    print(f"Database            : {OPERATIONAL_DB}")
    print(f"Existing audit events: {n_events}")
    print(f"Existing idem keys   : {n_keys}")
    print()

    if verify_only or n_events:
        tenants = await db[AUDIT_COLLECTION].distinct("tenant_id")
        for t in tenants:
            events = await db[AUDIT_COLLECTION].find(
                {"tenant_id": t}, {"_id": 0}
            ).sort("sequence", 1).to_list(1_000_000)
            ok, reason = verify_chain(events)
            mark = "OK " if ok else "FAIL"
            print(f"  chain {mark} tenant={t} events={len(events)}"
                  + (f" reason={reason}" if reason else ""))
            if not ok:
                return 2
    if verify_only:
        return 0

    print("Planned indexes:")
    for coll, keys, opts in PLANNED_INDEXES:
        print(f"  - {coll}: {keys} {opts or ''}")

    if not apply:
        print("\nDRY RUN — nothing created. Re-run with --apply to create indexes.")
        return 0

    for coll, keys, opts in PLANNED_INDEXES:
        name = await db[coll].create_index(keys, **opts)
        print(f"  created {coll}.{name}")

    # Prove nothing but indexes changed.
    assert await db[AUDIT_COLLECTION].count_documents({}) == n_events
    assert await db[IDEMPOTENCY_COLLECTION].count_documents({}) == n_keys
    print("\nIndexes in place. No documents were written or modified.")
    return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    verify = "--verify" in sys.argv
    sys.exit(asyncio.run(run(apply, verify)))
