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
    # CODEX C01 — ZERO production offenders. Every retired writer body
    # has been gutted; the remaining `fifo_service.consume_fifo` serves
    # the sales domain (out of TASK 5C scope per v6 §12.1) and is
    # whitelisted at the module level in `ALLOWED_WRITER_MODULES`
    # rather than entry-by-entry here.
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
