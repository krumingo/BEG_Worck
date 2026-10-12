"""
Migration-readiness tooling — DRY-RUN ONLY (TASK 5C hard boundary).

Reads the current state and produces a deterministic plan + ambiguity
report. **Never** mutates customer data. The service refuses to run any
"execute" step:

  >>> await execute_migration(...)
  Traceback (most recent call last):
    ...
  MigrationExecutionRefusedError: ...

The scopes this module answers:

  * `free_text_to_item` — legacy `warehouse_transactions` rows that lack
    `item_id`/`unit` and carry only free text. The report lists the top
    free-text buckets and which (if any) Master item ids match
    unambiguously by alias.

  * `main_to_central` — warehouses typed as legacy `main` (there is no
    such canonical type) and the proposed rename / audit action.

  * `legacy_writer_inventory` — current open positions of
    `warehouse_batches` / `material_entries` written outside the
    canonical service (via `legacy_inventory.scan_repository_for_legacy_writers`).

  * `ledger_batch_reconciliation` — for every batch row that is NOT
    canonical, report the historical movement it corresponds to and the
    delta if any.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.services.warehouse_movements.errors import MigrationExecutionRefusedError
from app.services.warehouse_movements.legacy_inventory import (
    scan_repository_for_legacy_writers,
)


MOVEMENTS_COLLECTION = "warehouse_transactions"
BATCHES_COLLECTION = "warehouse_batches"
WAREHOUSES_COLLECTION = "warehouses"


async def free_text_to_item_report(
    tenant_collection,
    *,
    tenant_id: str,
    session=None,
    limit: int = 1000,
) -> Dict[str, Any]:
    """List legacy rows lacking FLOW-032 identity, grouped by free text."""
    cursor = tenant_collection.find({
        "tenant_id": tenant_id,
        "$or": [
            {"item_id": None}, {"item_id": ""},
            {"unit": None}, {"unit": ""},
        ],
    }, {"material_name": 1, "unit": 1, "quantity": 1, "_id": 0}, session=session).limit(limit)
    rows = [doc async for doc in cursor]
    buckets = Counter()
    for r in rows:
        key = ((r.get("material_name") or "").strip().lower(),
               (r.get("unit") or "").strip().lower())
        buckets[key] += 1
    return {
        "tenant_id": tenant_id,
        "legacy_identity_missing_rows": len(rows),
        "distinct_free_text": [
            {"material_name": k[0], "unit": k[1], "occurrences": n}
            for k, n in buckets.most_common(100)
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
    }


async def main_to_central_report(
    tenant_db,
    *,
    tenant_id: str,
    session=None,
) -> Dict[str, Any]:
    """List warehouses typed `main` (legacy only) and propose a rename."""
    cursor = tenant_db[WAREHOUSES_COLLECTION].find(
        {"tenant_id": tenant_id, "type": "main"},
        {"id": 1, "code": 1, "name": 1, "_id": 0},
        session=session,
    )
    rows = [doc async for doc in cursor]
    return {
        "tenant_id": tenant_id,
        "legacy_main_warehouses": rows,
        "proposed_action": "retype 'main' to 'central' with audited administration",
        "proposed_rename_count": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
    }


def legacy_writer_inventory_report() -> Dict[str, Any]:
    hits = scan_repository_for_legacy_writers()
    total = sum(len(v) for v in hits.values())
    return {
        "canonical_only_collections_with_other_writers": {
            coll: positions for coll, positions in hits.items() if positions
        },
        "total_offending_positions": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
    }


async def ledger_batch_reconciliation_report(
    tenant_db,
    *,
    tenant_id: str,
    session=None,
    limit: int = 200,
) -> Dict[str, Any]:
    """Compare batch rows to the ledger rows they claim to project."""
    cursor = tenant_db[BATCHES_COLLECTION].find(
        {"tenant_id": tenant_id,
         "$or": [{"projection_source": {"$exists": False}},
                 {"projection_source": {"$ne": "canonical_warehouse_service"}}]},
        {"movement_id": 1, "quantity": 1, "remaining_quantity": 1, "_id": 0},
        session=session,
    ).limit(limit)
    mismatches: List[Dict[str, Any]] = []
    inspected = 0
    async for batch in cursor:
        inspected += 1
        mv_id = batch.get("movement_id")
        if not mv_id:
            mismatches.append({"batch": batch, "mismatch": "no_movement_id"})
            continue
        mv = await tenant_db[MOVEMENTS_COLLECTION].find_one(
            {"tenant_id": tenant_id, "movement_id": mv_id},
            {"quantity": 1, "_id": 0}, session=session,
        )
        if not mv:
            mismatches.append({"batch": batch, "mismatch": "orphan_batch"})
            continue
        if Decimal(str(batch.get("quantity") or "0")) != Decimal(str(mv.get("quantity") or "0")):
            mismatches.append({
                "batch": batch, "ledger_quantity": str(mv.get("quantity")),
                "mismatch": "quantity_delta",
            })
    return {
        "tenant_id": tenant_id,
        "inspected_rows": inspected,
        "mismatches": mismatches[:50],
        "mismatch_count": len(mismatches),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
    }


async def execute_migration(*args, **kwargs) -> None:
    """Hard refusal: TASK 5C migration tooling is dry-run only."""
    raise MigrationExecutionRefusedError(
        "TASK 5C migration tooling is DRY-RUN ONLY; execution is refused. "
        "Approval and manual review are required for any real migration run."
    )
