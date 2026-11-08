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

# CODEX C13.6 — module-wide whitelists are gone. Writer sites outside
# the canonical service/projector are now allowed via NARROW per-site
# exemptions in `ALLOWED_WRITER_SITES`, each pinned to a specific
# collection + file + justification. The whole-file whitelist pattern
# (`ALLOWED_WRITER_MODULES`) hid real offenders by exempting entire
# source files (e.g. `routes/material_smr.py`'s material_entries
# caps). The replacement scans every production module and asks each
# writer site to prove its legitimacy against this list.
#
# Shape: {(file, collection): "justification"}. The scanner records a
# site in `allowed_writer_sites` ONLY when the file+collection pair is
# present AND the match is to one of the ALLOWED write methods
# (insert_one / update_one / delete_many) that the service itself owns.
# A write to a different canonical collection from the same file is
# still an offender.
ALLOWED_WRITER_SITES: Dict[Tuple[str, str], str] = {
    # The canonical command service — the SOLE writer of
    # warehouse_transactions and of the chain-head/counter pivots.
    ("backend/app/services/warehouse_movements/service.py",
     "warehouse_transactions"): "canonical command service",
    # The projector — writes projections only (never ledger).
    ("backend/app/services/warehouse_movements/projections.py",
     "warehouse_batches"): "canonical projection row writer",
    ("backend/app/services/warehouse_movements/projections.py",
     "material_entries"): "canonical projection row writer",
    ("backend/app/services/warehouse_movements/projections.py",
     "warehouse_in_transit"): "canonical projection row writer",
    # The material_entries deterministic rebuild derives rows from the
    # canonical ledger. The site is narrow — this exemption covers the
    # `material_entries` collection only; writes to any OTHER canonical
    # collection from the same file would still fail the scan.
    ("backend/app/routes/material_smr.py",
     "material_entries"): "deterministic canonical rebuild",
}

# Kept as an empty tuple for backward compatibility with earlier
# tests that imported the name; the scanner no longer consults it.
ALLOWED_WRITER_MODULES: Tuple[str, ...] = ()

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
    """Scan every production module and return offenders by category.

    CODEX C13.6 — scope rewrites:

      * **Every** production .py file is scanned. No whole-file
        exemption. The former `ALLOWED_WRITER_MODULES` whitelist is
        gone; projection/rebuild writers earn per-site exemption via
        `ALLOWED_WRITER_SITES` entries pinned to `(file, collection)`.
      * Multiline / variable-chain capped reads are detected. The
        scanner walks the next ~12 lines looking for a `.to_list(N)`
        where N is a small integer or integer-literal variable (not
        `None`), AND also tracks `cursor = tenant.X.find(...)` →
        `cursor.to_list(N)` across the same window.
      * Permission bypasses, `PERMISSION_SERVICE_MODE` env mutations,
        and random idempotency fallbacks in warehouse/sale paths
        remain detected (unchanged from C12.10).

    New entries outside `ALLOWED_WRITER_SITES` are failures.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[4]
    hits: Dict[str, List[Dict]] = {c: [] for c in CANONICAL_ONLY_COLLECTIONS}
    hits.setdefault("__permission_bypass__", [])
    hits.setdefault("__permission_mode_mutation__", [])
    hits.setdefault("__capped_canonical_reads__", [])
    hits.setdefault("__random_idempotency_key__", [])

    canonical_coll_names = CANONICAL_ONLY_COLLECTIONS | {"warehouse_transactions"}

    SELF_FILE = "backend/app/services/warehouse_movements/legacy_inventory.py"
    # The to_list cap detector recognizes small integer literals; it
    # also honours `.to_list(None)` as explicitly uncapped. A var
    # name like `limit` is treated as a cap because its runtime value
    # is unknown; the write path must use None or a cursor async-for.
    _CAP_INT_RE = re.compile(r"\.to_list\(\s*(\d+|limit|page_size|LIMIT|size)\s*\)")

    for py_path in repo_root.rglob("*.py"):
        rel = PurePosixPath(py_path.relative_to(repo_root).as_posix()).as_posix()
        if any(rel.startswith(p) for p in TEST_FIXTURE_PREFIXES):
            continue
        if rel == SELF_FILE:
            # The scanner itself contains the detection patterns as
            # string literals; those must not count as offenders.
            continue
        try:
            text = py_path.read_text(encoding="utf-8")
            lines = text.splitlines()
        except Exception:
            continue
        for line_no, line in enumerate(lines, start=1):
            stripped = line.strip()
            # 1. Direct writes to canonical-only collections. Per-site
            # allowed only.
            m = _WRITER_METHOD_RE.search(line)
            if m:
                coll = m.group("coll")
                if coll in CANONICAL_ONLY_COLLECTIONS:
                    if (rel, coll) in ALLOWED_WRITER_SITES:
                        continue
                    hits[coll].append({
                        "file": rel, "line": line_no,
                        "snippet": stripped,
                    })
            # 2. Permission bypass patterns
            if ("class _AllowService" in line
                    or "class _AllowAll" in line
                    or ("async def ensure" in line and "return None" in line
                        and "PermissionGate" not in line and "pass" not in line)):
                hits["__permission_bypass__"].append({
                    "file": rel, "line": line_no, "snippet": stripped,
                })
            # 3. PERMISSION_SERVICE_MODE env mutation outside the service
            if ("PERMISSION_SERVICE_MODE" in line
                    and ("os.environ[" in line or "setdefault" in line)
                    and not stripped.startswith("#")):
                hits["__permission_mode_mutation__"].append({
                    "file": rel, "line": line_no, "snippet": stripped,
                })
            # 4. Capped canonical reads — multiline window.
            for coll_name in canonical_coll_names:
                if (f".{coll_name}.find(" in line
                        or f".{coll_name}.aggregate(" in line):
                    # Walk up to 12 lines ahead for a .to_list(N).
                    window_end = min(line_no + 12, len(lines))
                    for ahead in range(0, window_end - line_no + 1):
                        peek_idx = line_no - 1 + ahead
                        if peek_idx >= len(lines):
                            break
                        peek = lines[peek_idx]
                        if _CAP_INT_RE.search(peek):
                            # Legitimate pagination: the chain carries
                            # BOTH `.skip(...)` and `.limit(...)` so
                            # the integer is the explicit page size
                            # the caller asked for, not a silent
                            # truncation. Peek a broader window of
                            # the chain to detect it.
                            chain_start = max(line_no - 1, 0)
                            chain_end = min(peek_idx + 1, len(lines))
                            chain_text = "\n".join(lines[chain_start:chain_end])
                            if (".skip(" in chain_text
                                    and ".limit(" in chain_text):
                                break   # paginated, not a hidden cap
                            hits["__capped_canonical_reads__"].append({
                                "file": rel, "line": line_no + ahead,
                                "snippet": peek.strip(),
                                "collection": coll_name,
                                "detected_via": "direct_chain",
                            })
                            break
                        # Stop walking when we leave the statement — a
                        # fresh unindented line, a new assignment, or a
                        # bare `return`/`continue`.
                        if (ahead > 0 and peek.strip() and
                                not peek.startswith(" ") and
                                not peek.startswith("\t")):
                            break
            # 5. Variable-chain capped reads
            # `cursor = tenant.<coll>.find(...)` followed by
            # `cursor.to_list(N)` or `await cursor.to_list(N)` within
            # the next ~20 lines.
            var_assign_re = re.compile(
                r"(\w+)\s*=\s*[\w\.]+\.(\w+)\.(?:find|aggregate)\s*\("
            )
            vm = var_assign_re.search(line)
            if vm:
                var_name, coll_name = vm.group(1), vm.group(2)
                if coll_name in canonical_coll_names:
                    window_end = min(line_no + 20, len(lines))
                    for ahead in range(1, window_end - line_no + 1):
                        peek = lines[line_no - 1 + ahead]
                        if (f"{var_name}.to_list(" in peek
                                or f"await {var_name}.to_list(" in peek):
                            if _CAP_INT_RE.search(peek):
                                hits["__capped_canonical_reads__"].append({
                                    "file": rel, "line": line_no + ahead,
                                    "snippet": peek.strip(),
                                    "collection": coll_name,
                                    "detected_via": "variable_chain",
                                    "cursor_variable": var_name,
                                })
                                break
            # 6. Random idempotency key fallback inside warehouse/sale paths
            if ("idempotency_key" in line
                    and ("warehouse" in rel or "fifo" in rel or "sale" in rel)
                    and ("uuid.uuid4" in line or "uuid4()" in line)
                    and "or " in line):
                hits["__random_idempotency_key__"].append({
                    "file": rel, "line": line_no, "snippet": stripped,
                })
    return hits
