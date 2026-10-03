#!/usr/bin/env python3
"""
W0-03E-A2C — migrate the three global ``settings`` rows to per-tenant identity.

What it does and why. ``worker_rates``, ``employee_cost_config`` and
``overtime_config`` were stored in the shared ``settings`` collection under a
GLOBAL literal ``_id``. ``_id`` is unique per collection, so the installation can
hold exactly one of each: the first tenant to save owns the row, every other
tenant's upsert fails with a duplicate key, and its (correctly tenant-scoped)
read then returns nothing, so it silently falls back to defaults and can never
store its own rates, employee cost config or overtime rule. The W0-03E-A2B review
recorded this as an unclosed second-tenant limitation.

``app.tenancy.settings_identity`` gives each row the id ``"<key>:<org_id>"``.
This script moves the EXISTING rows onto those ids. ``_id`` is immutable in
MongoDB, so each move is: read the legacy row, write a copy under the
tenant-scoped id with every other field preserved, verify the copy, delete the
legacy row. No setting value, default or user-facing behaviour changes.

Properties:

* **Dry run by default.** ``--apply`` is required to write anything.
* **Idempotent and resumable.** A row already migrated is reported ``already``
  and skipped; a half-finished move (copy written, legacy row still present)
  completes on the next run. Re-running changes nothing.
* **Never overwrites.** If the tenant-scoped id already exists with different
  content, the legacy row is left alone and the pair is reported ``conflict``;
  the operator decides. Nothing is merged by guess.
* **Owner-aware.** The tenant comes from the legacy row's own ``org_id``. A row
  with no ``org_id`` is ``ownerless`` and is NOT migrated — W0-03E-A2B's backfill
  is what gives legacy rows an owner, and this script never guesses one.
* **Reconciled.** Before/after counts are printed per key and the run fails
  (exit 1) if the after-state does not match what it planned.

This is implementation/test tooling. Running it against a production database is
an operator decision outside W0-03E-A2C; the task's hard boundaries forbid a
production migration here.

    python scripts/w0_03e_a2c_settings_identity_migration.py                 # dry run
    python scripts/w0_03e_a2c_settings_identity_migration.py --apply
    MONGO_URL=... DB_NAME=... python scripts/w0_03e_a2c_settings_identity_migration.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tenancy.settings_identity import (  # noqa: E402
    LEGACY_GLOBAL_KEYS,
    SETTINGS_COLLECTION,
    settings_id,
)

#: The collection the rows live in, as a literal so the static guard can see which
#: collection every query below names. Asserted equal to the canonical value, so
#: the two can never drift apart.
COLLECTION = "settings"
assert COLLECTION == SETTINGS_COLLECTION

STATE_MIGRATED = "migrated"
STATE_ALREADY = "already"
STATE_ABSENT = "absent"
STATE_OWNERLESS = "ownerless"
STATE_CONFLICT = "conflict"


def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
    """The row's content without its identity fields."""
    return {k: v for k, v in row.items() if k not in ("_id",)}


def plan(rows: List[Dict[str, Any]]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """``[(state, key, row)]`` for the legacy rows found. Pure, so it is testable."""
    out = []
    for row in rows:
        key = row.get("_id")
        if key not in LEGACY_GLOBAL_KEYS:
            continue
        org_id = row.get("org_id")
        if not isinstance(org_id, str) or not org_id.strip():
            out.append((STATE_OWNERLESS, key, row))
        else:
            out.append((STATE_MIGRATED, key, row))
    return out


async def migrate(db, apply: bool = False) -> Dict[str, Any]:
    """Move every legacy global settings row to its tenant-scoped id."""
    before = {}
    for key in LEGACY_GLOBAL_KEYS:
        before[key] = await db[COLLECTION].count_documents({"_id": key})

    legacy = await db[COLLECTION].find({"_id": {"$in": list(LEGACY_GLOBAL_KEYS)}}).to_list(None)
    results: List[Dict[str, Any]] = []

    for state, key, row in plan(legacy):
        org_id = row.get("org_id")
        if state == STATE_OWNERLESS:
            results.append({"key": key, "state": STATE_OWNERLESS, "org_id": None,
                            "detail": "row has no org_id; W0-03E-A2B backfill owns this, "
                                      "not this migration"})
            continue

        target_id = settings_id(key, org_id)
        existing = await db[COLLECTION].find_one({"_id": target_id})
        payload = _payload(row)

        if existing is not None:
            if _payload(existing) == payload:
                # a resumed run: the copy is there, only the legacy row remains
                if apply:
                    await db[COLLECTION].delete_one({"_id": key})
                results.append({"key": key, "state": STATE_ALREADY, "org_id": org_id,
                                "target": target_id,
                                "detail": "tenant row already present and identical; "
                                          "legacy row removed" if apply else
                                          "tenant row already present and identical"})
            else:
                results.append({"key": key, "state": STATE_CONFLICT, "org_id": org_id,
                                "target": target_id,
                                "detail": "tenant row exists with DIFFERENT content; "
                                          "left untouched for an operator decision"})
            continue

        if apply:
            await db[COLLECTION].insert_one({"_id": target_id, **payload})
            written = await db[COLLECTION].find_one({"_id": target_id})
            if written is None or _payload(written) != payload:
                raise RuntimeError("copy of %r to %r did not verify" % (key, target_id))
            await db[COLLECTION].delete_one({"_id": key})
        results.append({"key": key, "state": STATE_MIGRATED, "org_id": org_id,
                        "target": target_id,
                        "detail": "copied then legacy row removed" if apply else
                                  "would copy then remove the legacy row"})

    for key in LEGACY_GLOBAL_KEYS:
        if not any(r["key"] == key for r in results):
            results.append({"key": key, "state": STATE_ABSENT, "org_id": None,
                            "detail": "no legacy row in this database"})

    after = {}
    for key in LEGACY_GLOBAL_KEYS:
        after[key] = await db[COLLECTION].count_documents({"_id": key})

    moved = sum(1 for r in results if r["state"] in (STATE_MIGRATED, STATE_ALREADY))
    expected_after = {k: (0 if apply and any(
        r["key"] == k and r["state"] in (STATE_MIGRATED, STATE_ALREADY) for r in results)
        else before[k]) for k in LEGACY_GLOBAL_KEYS}
    reconciled = (after == expected_after) if apply else (after == before)

    return {"applied": apply, "before": before, "after": after,
            "expected_after": expected_after, "reconciled": reconciled,
            "moved": moved, "results": sorted(results, key=lambda r: (r["key"], r["state"]))}


async def _run(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    name = os.environ.get("DB_NAME", "begwork")
    client = AsyncIOMotorClient(url)
    try:
        report = await migrate(client[name], apply=apply)
    finally:
        client.close()

    print("=== W0-03E-A2C settings identity migration (%s) ===" %
          ("APPLY" if apply else "DRY-RUN"))
    print("database: %s\n" % name)
    width = max(len(k) for k in LEGACY_GLOBAL_KEYS)
    for r in report["results"]:
        print("  %-*s  %-10s  %s" % (width, r["key"], r["state"], r["detail"]))
    print("\nlegacy global rows before: %s" % report["before"])
    print("legacy global rows after:  %s" % report["after"])
    print("moved: %d   reconciled: %s" % (report["moved"], report["reconciled"]))
    if any(r["state"] == STATE_CONFLICT for r in report["results"]):
        print("\nCONFLICT: at least one tenant row exists with different content. "
              "Nothing was merged; resolve it explicitly.")
        return 1
    if not report["reconciled"]:
        print("\nRECONCILIATION FAILED: the after-state does not match the plan.")
        return 1
    if not apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--apply", action="store_true",
                    help="write the migration (default is a dry run)")
    args = ap.parse_args(argv)
    import asyncio
    return asyncio.run(_run(args.apply))


if __name__ == "__main__":
    sys.exit(main())
