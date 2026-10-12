"""Static-writer-inventory gate.

Guarantees that NO new code outside the canonical service/projector
writes to a canonical-only collection. The baseline below is the exact
set of pre-TASK-5C positions preserved as historical reads/writes. A
new position means a new legacy writer has been added — fail the test
and ask the author to route the write through the canonical command
service.

To extend the baseline (e.g. the projector gains a new file inside
`warehouse_movements/`), add it to `ALLOWED_WRITER_MODULES` in
`legacy_inventory.py`, not here.
"""
import pytest

from app.services.warehouse_movements.legacy_inventory import (
    scan_repository_for_legacy_writers,
    CANONICAL_ONLY_COLLECTIONS,
)


# The baseline is intentionally a WHITELIST of file:line positions that
# were already in main at TASK 5C baseline SHA 79af297. Each one is a
# retired writer or a legitimate historical read-mutation that TASK 5C
# chose to leave in place with a fail-close shim rather than delete.
#
# Format: {collection_name: {"<rel_file>:<line>", ...}}
#
# The current post-TASK-5C expected baseline is a SUBSET of what was in
# main pre-TASK-5C: the fail-close shims leave the function bodies in
# place for compile-time stability but the physical writes are
# guarded. Any entries that would otherwise flag need an owner decision.
BASELINE_WRITERS: dict[str, set[str]] = {
    # Pre-TASK-5C writer positions preserved in function bodies behind
    # fail-close guards. Each line writes to a canonical-only collection
    # but is unreachable in normal runtime (its route raises
    # LEGACY_WRITER_RETIRED → HTTP 410 before the body runs). Removing
    # the bodies would churn the diff and lose context for operations;
    # the guard is what matters.
    "warehouse_transactions": {
        "backend/app/routes/procurement.py:519",      # post_invoice_to_warehouse body (guarded, 410)
        "backend/app/routes/procurement.py:710",      # record_consumption body (guarded, 410)
        "backend/app/routes/procurement.py:850",      # warehouse_return body (guarded, 410)
    },
    "warehouse_batches": {
        # fifo_service.add_batch / consume_fifo — now callable only from
        # the retired POST /warehouse/batches and /warehouse/consume
        # handlers, both of which fail-close at HTTP 410 before the
        # service is reached.
        "backend/app/services/fifo_service.py:85",
        "backend/app/services/fifo_service.py:129",
        # PUT /warehouse/batches/{id}/block body — guarded (410).
        "backend/app/routes/warehouse_batches.py:208",
    },
    "material_entries": {
        # /material-entries/sync/{project_id} — projection rebuild only.
        # Not a physical writer per FLOW_CODE_MAP_READY: it re-derives
        # from (legacy) sources. The projection source migrates to the
        # canonical ledger as part of CODEX follow-up work; the current
        # positions are preserved as reconciliation input only.
        "backend/app/routes/material_smr.py:55",
        "backend/app/routes/material_smr.py:87",
        "backend/app/routes/material_smr.py:110",
        "backend/app/routes/material_smr.py:132",
    },
}


def test_no_new_legacy_writer_slipped_in():
    hits = scan_repository_for_legacy_writers()
    offenders: dict[str, list[dict]] = {}
    for coll, positions in hits.items():
        allowed = BASELINE_WRITERS.get(coll, set())
        new = [
            p for p in positions
            if f"{p['file']}:{p['line']}" not in allowed
        ]
        if new:
            offenders[coll] = new

    assert not offenders, (
        "New legacy writer positions found outside the canonical service.\n"
        "Each new entry means code outside `warehouse_movements/{service,"
        "projections}.py` is writing to a canonical-only collection.\n"
        "Route the write through the canonical command service, or get an\n"
        "owner decision to add it to the BASELINE_WRITERS whitelist.\n\n"
        f"offenders:\n{offenders!r}"
    )


def test_canonical_only_collections_set_is_frozen():
    expected = {
        "warehouse_transactions",
        "warehouse_batches",
        "material_entries",
        "warehouse_in_transit",
    }
    assert CANONICAL_ONLY_COLLECTIONS == expected
