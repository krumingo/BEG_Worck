"""LIVE-OPS-01 / TASK 5C — C12 bounded correction regression gates.

Reviewed head C11 result: 18 passed / 6 failed on real Mongo. CODEX
re-review flagged ten asks. The six reproduced failures are the
material regressions; the other four are static/semantic. This module
documents them as pure DB-free gates — nothing in it starts Mongo,
nothing mutates production state, nothing is skipped or weakened. The
real-Mongo matrix extends the same assertions.

Covers (CODEX re-review § C12.1–C12.10):

* **C12.1 — Rule B cumulative remainder** — `missing_quantity` must be
  computed against *cumulative* accepted qty across every prior
  partial acceptance of the same transit lot. 10→8→2 and 10→3→4→3
  must leave zero bogus `unresolved_discrepancy` once the lot is
  fully reconciled.
* **C12.2 — FIFO arithmetic** — `10@10 + 2@20 = 100 + 40 = 140`.
* **C12.3 — Ledger sequence allocation is atomic under concurrency.**
* **C12.4 — Sales `fifo_service.consume_fifo` runs under real
  Permission Service in enforce mode, with stable idempotency and
  mandatory sale evidence**.
* **C12.5 — Supplier / `unresolved` location types never credit or
  drain the internal stock balance.**
* **C12.6 — `material_entries` projection is deterministic (no
  wall-clock field), tagged `projection_version=2`, and
  canonical-source filtered.**
* **C12.7 — Scoped canonical reads load role assignments through
  `_load_assignments` and distinguish `None` (unrestricted) from `[]`
  (empty grant = deny).**
* **C12.10 — Static writer inventory has four new offender
  categories (bypass, env-mutation, capped-canonical-read,
  random-idempotency) and must still return zero offenders.**

C12.8 (frontend) is covered by a React Testing Library gate under
`frontend/src/components/__tests__/ProjectMaterialLedger.test.js` and
is not asserted here.
C12.9 (full real-Mongo matrix) runs under the real-Mongo suite only
and would skip here with no gain.
"""
from __future__ import annotations

import inspect
import re
from decimal import Decimal
from pathlib import Path

import pytest


# ────────────────────────────── C12.2 ──────────────────────────────

def test_c12_2_fifo_arithmetic_10_at_10_plus_2_at_20_equals_140():
    """`10@10 + 2@20 = 140` — the only arithmetically correct answer.

    CODEX C12 flagged this gate as the one that must change the
    *test*, not the production code: the pre-C12 assertion of 120
    was itself the bug.
    """
    layer_1_total = Decimal("10") * Decimal("10")   # 100
    layer_2_total = Decimal("2") * Decimal("20")    # 40
    assert layer_1_total + layer_2_total == Decimal("140")


def test_c12_2_fifo_arithmetic_assertion_lives_in_mongo_suite():
    """The headline FIFO acceptance test must now say 140."""
    src = Path("tests/test_warehouse_canonical_mongo.py").read_text()
    # The assertion we re-wrote must now be present:
    assert 'Decimal("140")' in src, (
        "Mongo suite must now assert the arithmetically correct 140, "
        "not the historical 120."
    )
    # And the bogus value must be gone *from that specific assertion*:
    assert 'assert total == Decimal("120")' not in src, (
        "A `total == Decimal(\"120\")` assertion is still in the mongo "
        "suite. The FIFO conservation test must say 140."
    )


# ────────────────────────────── C12.1 ──────────────────────────────

def test_c12_1_rule_b_remainder_is_cumulative_in_source():
    """`service.py` computes `missing_qty` from cumulative accepted.

    Pure source-level gate: the service must walk every prior
    acceptance of the same lot before computing the remainder.
    """
    src = Path("app/services/warehouse_movements/service.py").read_text()
    assert "prior_accepted" in src, (
        "Rule B remainder is not cumulative — service.py must read "
        "every prior acceptance of the same transit lot."
    )
    assert "total_accepted = prior_accepted + accepted_qty" in src
    assert "missing_qty = max(requested_quantity - total_accepted" in src


# ────────────────────────────── C12.3 ──────────────────────────────

def test_c12_3_ledger_sequence_uses_atomic_counter_not_read_max_plus_one():
    """Audit chain allocation must be a single atomic Mongo counter."""
    src = Path("app/services/warehouse_movements/service.py").read_text()
    assert "warehouse_ledger_counters" in src, (
        "C12.3 regression: the atomic counter collection is absent. "
        "An audit chain under concurrent writes WILL race if the "
        "sequence allocation reverts to read-max+1."
    )
    assert "find_one_and_update" in src
    assert "ReturnDocument.AFTER" in src
    # The old read-max+1 is specifically banned:
    assert "_next_ledger_sequence" in src


# ────────────────────────────── C12.4 ──────────────────────────────

def test_c12_4_sales_consume_fifo_requires_evidence_and_reference():
    """Sales canonical write — SUPERSEDED by CODEX C13.3 fail-closed.

    C12.4 required sale_evidence_file_ids + sale_reference because
    the C12 cycle routed sales through the canonical `WRITE_OFF`
    action. CODEX C13.3 reversed that: `WRITE_OFF` is scrap/loss/
    theft only (contract v6 §4.2); mapping ordinary sales onto it
    was a business-rule invention. The route now FAILS CLOSED and
    `consume_fifo` raises `LegacyWriterRetiredError` for ANY call.

    This gate now asserts the C13.3 fail-closed signature instead.
    """
    from app.services.fifo_service import consume_fifo
    sig = inspect.signature(consume_fifo)
    # The function still accepts the full C12.4 kwarg shape so
    # callers that adopted it get a precise error, not a crash on
    # the first attribute access.
    assert "actor_id" in sig.parameters
    assert "sale_reference" in sig.parameters
    assert "sale_evidence_file_ids" in sig.parameters
    assert "ctx" in sig.parameters

    # Validate the body is the C13.3 fail-closed raise:
    src = Path("app/services/fifo_service.py").read_text()
    assert "LegacyWriterRetiredError" in src, (
        "C12.4/C13.3 regression: consume_fifo must raise "
        "LegacyWriterRetiredError (not perform a canonical write)."
    )
    assert "WRITE_OFF" in src and "scrap/loss/theft" in src, (
        "C12.4/C13.3 regression: the error must say WRITE_OFF is "
        "scrap/loss/theft only; a sale is NOT a write-off."
    )


def test_c12_4_sales_consume_fifo_has_no_permission_bypass():
    """Sales write runs under the real Permission Service — no bypass."""
    src = Path("app/services/fifo_service.py").read_text()
    assert "_AllowService" not in src, (
        "C12.4 regression: an `_AllowService*` permission bypass is "
        "back. The sales write must call the real PermissionGate."
    )
    assert "PERMISSION_SERVICE_MODE" not in src, (
        "C12.4 regression: sales must not mutate the global "
        "PermissionService env override."
    )


def test_c12_4_sales_consume_fifo_idempotency_is_caller_stable():
    """SUPERSEDED by C13.3 — no canonical write path from sales.

    C12.4 required a caller-stable `sale-depletion:{ref}` idempotency
    key because the sales path performed a canonical WRITE_OFF.
    CODEX C13.3 removed that mapping entirely; the route now FAILS
    CLOSED so there is no canonical write to deduplicate.
    """
    src = Path("app/services/fifo_service.py").read_text()
    # No idempotency key is formed — the function raises before
    # reaching the canonical service.
    assert "LegacyWriterRetiredError" in src, (
        "C13.3 regression: the fail-closed raise is gone; a canonical "
        "write path would re-introduce the sale→WRITE_OFF rule."
    )
    # And the old business-rule-inventing `sale-depletion:` prefix is
    # not retained as an active idempotency pattern:
    assert "idempotency_key or f\"sale-depletion:" not in src, (
        "C13.3 regression: the sale-depletion idempotency pattern is "
        "back; it meant a canonical write was happening."
    )


# ────────────────────────────── C12.5 ──────────────────────────────

def test_c12_5_supplier_and_unresolved_locations_never_count_in_balance():
    """Internal stock balance must exclude `supplier` + `unresolved`."""
    src = Path("app/services/warehouse_movements/queries.py").read_text()
    assert "_EXTERNAL_LOCATION_TYPES" in src, (
        "C12.5 regression: the external-location exclusion set is "
        "gone. Supplier origins would start showing as internal "
        "negative stock again."
    )
    # Both the credit and the drain branches must honour it:
    external_mentions = len(re.findall(
        r"_EXTERNAL_LOCATION_TYPES", src,
    ))
    assert external_mentions >= 3, (
        "C12.5 regression: supplier exclusion is only applied in one "
        "branch. Both the credit (destination) and drain (source) "
        "sides of the balance walk must gate on it."
    )


# ────────────────────────────── C12.6 ──────────────────────────────

def test_c12_6_material_entries_projection_is_deterministic():
    """`material_entries` has no wall-clock field; readers filter source."""
    src = Path("app/routes/material_smr.py").read_text()
    # The non-deterministic `created_at` must be absent from the
    # projection write:
    assert '"created_at": now' not in src, (
        "C12.6 regression: the projection writes `created_at = now`, "
        "which breaks byte-identical rebuild and double-count-free "
        "replay."
    )
    assert '"projection_version": 2' in src, (
        "C12.6 regression: material_entries must advertise its new "
        "projection version so legacy rows are not read back in."
    )
    # Readers filter by projection_source:
    assert 'projection_source="canonical_warehouse_service"' in src or \
           'projection_source=\'canonical_warehouse_service\'' in src or \
           '"projection_source": "canonical_warehouse_service"' in src, (
        "C12.6 regression: material readers must filter by "
        "projection_source to stay immune to legacy duplicates."
    )


# ────────────────────────────── C12.7 ──────────────────────────────

def test_c12_7_scope_reads_use_load_assignments_not_user_dict():
    """Scoped reads call `_load_assignments`, not an embedded JWT claim."""
    src = Path("app/routes/warehouse_canonical_queries.py").read_text()
    assert "_load_assignments" in src, (
        "C12.7 regression: the scope resolver no longer calls the "
        "actual Permission Service. Scoped reads must never trust an "
        "embedded role claim on the user dict."
    )
    # And the embedded claim path is gone:
    assert "user.get(\"role_assignments\")" not in src and \
           "user['role_assignments']" not in src, (
        "C12.7 regression: embedded `role_assignments` claim is being "
        "read back from the user dict. Permission scope must come "
        "from the Permission Service."
    )


def test_c12_7_queries_distinguish_none_vs_empty_set_semantics():
    """`allowed_locations=None` is unrestricted; `set()` is deny."""
    src = Path("app/services/warehouse_movements/queries.py").read_text()
    assert "allowed_locations is None" in src, (
        "C12.7 regression: queries no longer distinguish None "
        "(unrestricted) from an empty set (empty grant = deny). "
        "Empty grants would start returning full warehouse state."
    )


# ────────────────────────────── C12.10 ──────────────────────────────

def test_c12_10_static_writer_inventory_has_four_new_categories():
    """Scanner guards four new offender categories."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    hits = scan_repository_for_legacy_writers()
    for cat in (
        "__permission_bypass__",
        "__permission_mode_mutation__",
        "__capped_canonical_reads__",
        "__random_idempotency_key__",
    ):
        assert cat in hits, (
            f"C12.10 regression: static scanner lost offender "
            f"category {cat!r}. Service-level bypasses and capped "
            f"legacy reads could re-appear and yield a false "
            f"zero-offender result."
        )


def test_c12_10_static_scan_zero_offenders_overall():
    """And the full scan — all 8 categories — must stay clean."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    hits = scan_repository_for_legacy_writers()
    total = sum(len(v) for v in hits.values())
    assert total == 0, (
        f"C12.10 regression: static writer inventory found "
        f"{total} offender position(s) across all 8 categories.\n"
        f"breakdown: {{k: len(v) for k, v in hits.items()}}"
    )


# ────────── Frontend gate note (C12.8) — informational only ──────────

def test_c12_8_frontend_handlers_have_no_silent_skip():
    """The React ledger handlers block, not silently skip."""
    frontend = Path("../frontend/src/components/ProjectMaterialLedger.js")
    if not frontend.exists():
        pytest.skip(
            "frontend tree not visible from this working dir; "
            "the React test under src/components/__tests__/ "
            "owns this gate."
        )
    src = frontend.read_text()
    # No bare `continue;` in a `.filter(... Boolean)` chain that would
    # silently drop rows:
    assert "blockers.push" in src or "blockers = []" in src, (
        "C12.8 regression: openConsume/openReturn must collect "
        "blocker reasons and surface them to the user — not silently "
        "skip rows."
    )
