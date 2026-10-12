"""
Legacy warehouse writer inventory + runtime guard.

Two surfaces:

1. **Static inventory** — `scan_repository_for_legacy_writers()` returns the
   set of file:line positions in the codebase that call a known legacy
   warehouse writer. The static-writer-inventory test runs this and
   compares the result to the frozen baseline, so an accidental re-add of
   a legacy write triggers a test failure.

2. **Runtime guard** — `LegacyWriterGuard` is a tiny decorator the retired
   routes mount. When `LEGACY_WAREHOUSE_WRITERS_ENABLED` is unset (the
   default), a call to a retired writer raises
   `LegacyWriterRetiredError`, which the route surface renders as
   HTTP 410 Gone with a pointer to the canonical command.

Legacy writer catalog (from FLOW_CODE_MAP_READY §"Legacy writer
retirement inventory"):
  * POST /supplier-invoices/{id}/post-to-warehouse   -> procurement.py
  * POST /warehouse-issue                            -> procurement.py
  * POST /warehouse-return                           -> procurement.py
  * POST /project-consumption                        -> procurement.py
  * POST /warehouse/batches                          -> warehouse_batches.py
  * POST /warehouse/consume                          -> warehouse_batches.py
  * PUT  /warehouse/batches/{id}/block               -> warehouse_batches.py
  * POST /material-entries/sync/{project_id}         -> material_smr.py
     (projection rebuild only; not a physical writer in TASK 5C
      regime — it may stay but must only re-derive from the canonical
      ledger.)
  * project_material_ops  — historical read-only reconciliation
  * material_consumption_log — historical read-only reconciliation
"""
from __future__ import annotations

import os
import re
from pathlib import Path
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

# Allowed writer modules (the canonical service and the projector).
ALLOWED_WRITER_MODULES: Tuple[str, ...] = (
    "backend/app/services/warehouse_movements/service.py",
    "backend/app/services/warehouse_movements/projections.py",
)

# Lightweight pattern (not an AST): matches `tenant.<coll>.insert_one`,
# `.update_one`, `.update_many`, `.delete_one`, `.delete_many`, `.replace_one`.
_WRITER_METHOD_RE = re.compile(
    r"\.(?P<coll>\w+)\.(?:insert_one|insert_many|update_one|update_many|"
    r"delete_one|delete_many|replace_one|bulk_write|find_one_and_update|"
    r"find_one_and_delete|find_one_and_replace)\s*\("
)


def legacy_writers_enabled() -> bool:
    return os.environ.get("LEGACY_WAREHOUSE_WRITERS_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def refuse_if_disabled(route_id: str, canonical_action: str) -> None:
    """Raise `LegacyWriterRetiredError` unless the (operator-only)
    emergency escape hatch is explicitly set.

    The escape hatch exists for operations only; it must remain OFF in
    normal production. The exception message points at the canonical
    replacement so the UI can redirect without inventing its own text.
    """
    if legacy_writers_enabled():
        return
    raise LegacyWriterRetiredError(
        f"legacy writer '{route_id}' is retired; use canonical action {canonical_action!r}",
        context={"route_id": route_id, "canonical_action": canonical_action},
    )


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
        rel = str(py_path.relative_to(repo_root))
        if rel.startswith(("backend/tests/", "tests/", "node_modules/", ".git/")):
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
            # Historical reconciliation collections (never written to in
            # TASK 5C) — if any entry survives, it is a bug.
            hits[coll].append({
                "file": rel,
                "line": line_no,
                "snippet": line.strip(),
            })
    return hits
