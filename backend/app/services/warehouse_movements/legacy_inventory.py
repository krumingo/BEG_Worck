"""
Legacy warehouse writer inventory + runtime guard.

C01 — "no runtime configuration can create a second authoritative stock
source". The previous `LEGACY_WAREHOUSE_WRITERS_ENABLED` escape hatch has
been REMOVED. Retired writers always raise `LegacyWriterRetiredError`
and the route surface renders HTTP 410 Gone with a pointer to the
canonical command. There is no env flag that can bring a legacy writer
back; a one-off recovery is a code change through canonical review.

The static scanner is **platform-independent**: it uses
`PurePosixPath`-shaped relative paths so a Windows run of pytest
reports the same hits as a Linux run (C01 Windows normalization fix).

Legacy writer catalog (v6 §12.1):
  * POST /supplier-invoices/{id}/post-to-warehouse   -> procurement.py
  * POST /warehouse-issue                            -> procurement.py
  * POST /warehouse-return                           -> procurement.py
  * POST /project-consumption                        -> procurement.py
  * POST /warehouse/batches                          -> warehouse_batches.py
  * POST /warehouse/consume                          -> warehouse_batches.py
  * PUT  /warehouse/batches/{id}/block               -> warehouse_batches.py
  * POST /material-entries/sync/{project_id}         -> material_smr.py (canonical rebuild only)
  * project_material_ops  — historical read-only reconciliation
  * material_consumption_log — historical read-only reconciliation
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Set, Tuple

from app.services.warehouse_movements.errors import LegacyWriterRetiredError


# Routes whose POST / PUT bodies are retired physical writers.
RETIRED_ROUTE_IDS: Set[str] = {
    "procurement.post_to_warehouse",
    "procurement.warehouse_issue",
    "procurement.warehouse_return",
    "procurement.project_consumption",
    "warehouse_batches.create_batch",
    "warehouse_batches.consume",
    "warehouse_batches.block",
}

# Collections that must only be written by the canonical service.
# A search for `.insert_one(` or `.update_one(` on these collections in
# non-service modules is a failed static check.
CANONICAL_ONLY_COLLECTIONS: Set[str] = {
    "warehouse_transactions",
    # `warehouse_batches` is a PROJECTION in TASK 5C regime; the only
    # legitimate writer is `projections.py`. All other callers are
    # retired.
    "warehouse_batches",
    "material_entries",             # projection-only
    "warehouse_in_transit",         # projection-only
}

# Allowed writer modules (the canonical service and the projector only).
# POSIX-form so the comparison is platform-independent.
#
# C11.2 — `fifo_service.py` is no longer whitelisted. Its `consume_fifo`
# now routes stock-depletion through the canonical command service
# instead of touching `warehouse_batches` directly, so the module no
# longer appears as a legacy writer.
ALLOWED_WRITER_MODULES: Tuple[str, ...] = (
    "backend/app/services/warehouse_movements/service.py",
    "backend/app/services/warehouse_movements/projections.py",
    # The canonical material_entries rebuild in material_smr.py (C02)
    # derives its rows deterministically from the canonical ledger.
    "backend/app/routes/material_smr.py",
)

# Directory prefixes that are TEST or EXAMPLE fixtures, never production
# writers. The scanner skips these explicitly rather than by accidental
# path spelling (C01 — "test fixtures may be excluded explicitly").
TEST_FIXTURE_PREFIXES: Tuple[str, ...] = (
    "backend/tests/",
    "backend/validation_tests/",
    "tests/",
    "node_modules/",
    ".git/",
    "backend/scripts/",
    "backend/tools/",
)

# Lightweight pattern (not an AST): matches `tenant.<coll>.insert_one`,
# `.update_one`, `.update_many`, `.delete_one`, `.delete_many`, `.replace_one`.
_WRITER_METHOD_RE = re.compile(
    r"\.(?P<coll>\w+)\.(?:insert_one|insert_many|update_one|update_many|"
    r"delete_one|delete_many|replace_one|bulk_write|find_one_and_update|"
    r"find_one_and_delete|find_one_and_replace)\s*\("
)


def refuse_legacy_writer(route_id: str, canonical_action: str) -> None:
    """Raise `LegacyWriterRetiredError` unconditionally.

    C01 — there is no runtime configuration that lets a retired writer
    run. The exception message points at the canonical replacement so
    the UI can redirect without inventing its own text.
    """
    raise LegacyWriterRetiredError(
        f"legacy writer '{route_id}' is retired; use canonical action {canonical_action!r}",
        context={"route_id": route_id, "canonical_action": canonical_action},
    )


# Backwards-compatible alias so earlier call sites don't crash during
# the correction window. New call sites use `refuse_legacy_writer`.
def refuse_if_disabled(route_id: str, canonical_action: str) -> None:
    refuse_legacy_writer(route_id, canonical_action)


def legacy_writers_enabled() -> bool:
    """Preserved for the test suite; always returns False (C01).

    A test may assert that no env flag can flip it True.
    """
    return False


def scan_repository_for_legacy_writers(repo_root: Path | None = None) -> Dict[str, List[Dict]]:
    """Scan the repo and return a dict:
         {collection_name: [{"file": "...", "line": 123, "snippet": "..."}, ...]}
    reporting every write-shaped call on a canonical-only collection.

    The caller (test) then diffs this against a frozen baseline. New
    entries outside `ALLOWED_WRITER_MODULES` are failures.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[4]
    hits: Dict[str, List[Dict]] = {c: [] for c in CANONICAL_ONLY_COLLECTIONS}

    for py_path in repo_root.rglob("*.py"):
        # Platform-independent POSIX path (C01 Windows normalization fix).
        rel = PurePosixPath(py_path.relative_to(repo_root).as_posix()).as_posix()
        if any(rel.startswith(p) for p in TEST_FIXTURE_PREFIXES):
            continue
        if rel in ALLOWED_WRITER_MODULES:
            continue
        try:
            text = py_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            m = _WRITER_METHOD_RE.search(line)
            if not m:
                continue
            coll = m.group("coll")
            if coll not in CANONICAL_ONLY_COLLECTIONS:
                continue
            hits[coll].append({
                "file": rel,
                "line": line_no,
                "snippet": line.strip(),
            })
    return hits
