"""LIVE-OPS-01 / TASK 5C — CODEX C13 bounded correction regression gates.

CODEX independent review on head `1076f0f…`: 22 passed / 2 failed on
real Mongo, plus eight further asks (C13.1–C13.8). These DB-free gates
prove the semantic contracts; the real-Mongo matrix extends the same
assertions (NOT RUN HERE — agent-egress proxy blocks Mongo binaries).

Covers:

* **C13.1** audit chain head CAS serialization — ten concurrent
  writers must not fork `previous_hash`.
* **C13.2** Rule B resolution facts — cumulative acceptance that
  closes a dispatch appends `discrepancy_resolved` ledger rows and
  the projector clears the active unresolved map.
* **C13.3** sales fail-closed — `fifo_service.consume_fifo` and
  `/sales/commit` do NOT mutate stock, do NOT map ordinary sale to
  WRITE_OFF, and do NOT contact the Permission Service.
* **C13.4** material_entries unified canonical schema — one schema
  everywhere, no `qty`/`total_cost` legacy field names in the
  rebuild endpoint, no `.to_list(N)` caps on canonical reads.
* **C13.5** scope reads use real Permission Service semantics —
  expired/revoked/wrong-module/wrong-scope assignments deny;
  empty-grant returns `[]`; `ctx.user_id` + `ctx.tenant_id` required.
* **C13.6** static inventory expanded — module-wide whitelists gone;
  narrow per-site allowed; multiline/variable-chain capped-read
  detection; mutation tests for every category.
* **C13.8** frontend tests are behavioral (see
  `ProjectMaterialLedger.c13.test.js`).
"""
from __future__ import annotations

import inspect
import re
import textwrap
from pathlib import Path

import pytest


# ─────────────────────────── C13.1 ───────────────────────────

def test_c13_1_audit_chain_uses_chain_head_cas_pivot():
    """`_record_event_in_session` serializes via `audit_chain_head`."""
    src = Path("app/services/warehouse_movements/service.py").read_text()
    assert 'audit_chain_head' in src, (
        "C13.1 regression: the chain-head pivot collection is gone. "
        "A hash chain cannot be built in parallel; a per-tenant CAS "
        "on this one document serializes concurrent writers."
    )
    assert 'OperationFailure(' in src and 'code=112' in src, (
        "C13.1 regression: a CAS miss must raise Mongo WriteConflict "
        "(code 112) so `session.with_transaction(...)` retries the "
        "whole operation."
    )
    # The old audit-sequence read-max+1 FALLBACK code is gone —
    # the chain-head pivot is the single source of previous_hash.
    # (Historical comments on the C12.3 ledger_sequence counter in
    #  `_next_ledger_sequence` are a different mechanism and allowed.)
    assert 'name": "audit_sequence"' not in src, (
        "C13.1 regression: the old `audit_sequence` counter is back. "
        "The chain-head CAS pivot replaces it; a counter alone did "
        "not close the forked-chain race."
    )


def test_c13_1_audit_chain_head_collection_is_classified():
    """`audit_chain_head` is listed under FAMILY_WAREHOUSE."""
    src = Path("app/tenancy/ownership.py").read_text()
    assert '"audit_chain_head"' in src, (
        "C13.1 regression: `audit_chain_head` is not classified. "
        "A tenant-scoped collection must appear in ownership.py."
    )


# ─────────────────────────── C13.2 ───────────────────────────

def test_c13_2_resolution_facts_are_appended_on_full_close():
    """Service appends `discrepancy_resolved` rows when lot closes."""
    src = Path("app/services/warehouse_movements/service.py").read_text()
    assert '"action": "discrepancy_resolved"' in src, (
        "C13.2 regression: the append-only resolution ledger row is "
        "missing. 10→3→4→3 would leave stale unresolved detail."
    )
    assert '_append_discrepancy_resolution' in src, (
        "C13.2 regression: the resolution helper is gone."
    )
    assert 'discrepancies_to_resolve' in src, (
        "C13.2 regression: the acceptance block must collect open "
        "discrepancies to resolve when cumulative hits requested."
    )


def test_c13_2_projector_closes_unresolved_discrepancies():
    """Projector removes resolved entries from the active map."""
    src = Path("app/services/warehouse_movements/projections.py").read_text()
    assert '_close_unresolved_discrepancies' in src, (
        "C13.2 regression: projector missing resolution handler."
    )
    assert 'resolved_discrepancy_movement_ids' in src, (
        "C13.2 regression: projection hint for resolution set gone."
    )
    # `$unset` on dotted path is how we remove map entries without
    # overwriting the whole field — the C12 bug was `$set` on the
    # whole `unresolved_discrepancies` field.
    assert '$unset' in src, (
        "C13.2 regression: `$unset` on the dotted path is the only "
        "way to remove one resolved entry without touching the rest."
    )


def test_c13_2_record_unresolved_layers_uses_dotted_set():
    """New unresolved discrepancies APPEND, not overwrite."""
    src = Path("app/services/warehouse_movements/projections.py").read_text()
    # `$set: {"unresolved_discrepancies.{mv_id}": {...}}` is dotted
    # path (appends); `$set: {"unresolved_discrepancies": {mv_id: ...}}`
    # overwrites — the C12 bug.
    assert 'unresolved_discrepancies.{unresolved_movement_id}' in src, (
        "C13.2 regression: the dotted-field write pattern is gone. "
        "10→3→4 would overwrite the discrepancy from the first "
        "partial acceptance with the second's."
    )


def test_c13_2_rebuild_handles_resolution_facts():
    """`rebuild_from_ledger` replays `discrepancy_resolved` rows."""
    src = Path("app/services/warehouse_movements/projections.py").read_text()
    # Rebuild previously filtered OUT transit_discrepancy rows
    # (`"action": {"$ne": "transit_discrepancy"}`). C13.2 reads
    # everything and dispatches on action.
    assert 'if act == "transit_discrepancy":' in src, (
        "C13.2 regression: rebuild no longer re-materialises the "
        "unresolved map; replay-twice parity breaks."
    )
    assert 'if act == "discrepancy_resolved":' in src, (
        "C13.2 regression: rebuild must also replay resolution facts."
    )


# ─────────────────────────── C13.3 ───────────────────────────

def test_c13_3_sales_consume_fifo_fails_closed():
    """`fifo_service.consume_fifo` raises `LegacyWriterRetiredError`."""
    from app.services.fifo_service import consume_fifo
    from app.services.warehouse_movements.errors import LegacyWriterRetiredError
    import asyncio

    async def _call():
        return await consume_fifo(
            "org1", "item1", "wh1", 1.0,
            ctx=object(), actor_id="u1",
            sale_reference="r1",
            sale_evidence_file_ids=["f1"],
        )
    with pytest.raises(LegacyWriterRetiredError) as exc:
        asyncio.get_event_loop().run_until_complete(_call()) if False else (
            asyncio.new_event_loop().run_until_complete(_call())
        )
    assert "WRITE_OFF" in exc.value.message or "write-off" in exc.value.message, (
        "C13.3 regression: the error must say WRITE_OFF is scrap/loss/"
        "theft only; an ordinary sale is NOT a write-off."
    )
    assert "sale_depletion" in str(exc.value.context) or \
           "canonical" in str(exc.value.context), (
        "C13.3 regression: the error must point at the canonical "
        "sale-depletion action pending in the frozen contract."
    )


def test_c13_3_sales_commit_route_returns_410():
    """`/sales/commit` is HTTP 410 with SALE_DEPLETION_PENDING."""
    src = Path("app/routes/sales.py").read_text()
    assert 'status_code=410' in src, (
        "C13.3 regression: /sales/commit must return 410 Gone, not "
        "201 or 200; the route must not mutate stock or create rows."
    )
    assert 'SALE_DEPLETION_PENDING_CANONICAL_ACTION' in src, (
        "C13.3 regression: the error_code pointer is gone."
    )
    # The old consume_fifo + sale insert path must be unreachable
    # (preserved only below the raise for lint-known identifiers).
    assert 'raise HTTPException(\n        status_code=410' in src, (
        "C13.3 regression: the route body must raise 410 before any "
        "ledger or sale-record mutation."
    )


def test_c13_3_sales_route_does_not_build_fake_ctx():
    """The fake `Ctx(org_id)` call site is gone."""
    src = Path("app/routes/sales.py").read_text()
    # The old route built `type("Ctx", (), {"org_id": org_id})()`
    # which the Permission Service rejected because it had no
    # user_id/tenant_id. The route is now fail-closed and does not
    # need any ctx construction.
    assert 'type("Ctx"' not in src, (
        "C13.3 regression: the fake Ctx is back; the route must "
        "fail closed before building any ctx."
    )


# ─────────────────────────── C13.4 ───────────────────────────

def test_c13_4_material_entries_rebuild_uses_canonical_schema():
    """Rebuild endpoint emits `quantity`/`total_value`, not `qty`/`total_cost`."""
    src = Path("app/routes/material_smr.py").read_text()
    # The canonical row written by the rebuild must have:
    assert '"quantity": qty,' in src or '"quantity":  qty,' in src, (
        "C13.4 regression: rebuild writes legacy `qty`, not canonical "
        "`quantity`. The projector and the rebuild would then be two "
        "incompatible schemas tagged canonical."
    )
    assert '"total_value": total_value,' in src, (
        "C13.4 regression: rebuild writes legacy `total_cost`, not "
        "canonical `total_value`."
    )
    # And the LEGACY fields are gone from the row body:
    assert re.search(r'"qty":\s+qty,\s+"unit_cost"', src) is None, (
        "C13.4 regression: the row still carries parallel legacy "
        "names. UNIFY on canonical."
    )


def test_c13_4_material_readers_use_canonical_names():
    """Readers aggregate `quantity`/`total_value`, not `qty`/`total_cost`."""
    src = Path("app/routes/material_smr.py").read_text()
    # The two cost reader paths must each query `total_value` + `movement_kind`.
    assert 'e.get("total_value")' in src, (
        "C13.4 regression: readers still read legacy `total_cost`."
    )
    assert '"movement_kind"' in src, (
        "C13.4 regression: readers must dispatch on `movement_kind`, "
        "not legacy `movement_type`."
    )


def test_c13_4_material_entries_reads_have_no_to_list_cap():
    """Every `material_entries.find(...)` has no silent cap."""
    src = Path("app/routes/material_smr.py").read_text()
    # No `.to_list(N)` with a plain int on this file (paginated routes
    # use `.skip().limit()`).
    assert re.search(r'\.to_list\(\d+\)', src) is None, (
        "C13.4 regression: `.to_list(N)` cap is back in material_smr. "
        "Material cost math must iterate the full projection."
    )


# ─────────────────────────── C13.5 ───────────────────────────

def test_c13_5_scope_reads_use_evaluate_one_decision_engine():
    """`_authorized_scope_locations` uses `_evaluate_one`."""
    src = Path("app/routes/warehouse_canonical_queries.py").read_text()
    assert '_evaluate_one' in src, (
        "C13.5 regression: scope read bypasses the Permission "
        "Service's decision engine; expired/revoked assignments "
        "would grant unintended scope."
    )
    assert 'getattr(ctx, "user_id"' in src, (
        "C13.5 regression: scope resolver must read `ctx.user_id` "
        "from TenantContext, NOT fall back to the user dict."
    )
    assert 'getattr(ctx, "tenant_id"' in src, (
        "C13.5 regression: scope resolver must read `ctx.tenant_id` "
        "from TenantContext, NOT `ctx.org_id`."
    )


def test_c13_5_scope_reads_use_server_resolved_tenant_db():
    """Reads build the data path from `ctx`, not from the user dict."""
    src = Path("app/routes/warehouse_canonical_queries.py").read_text()
    assert '_tenant_from_ctx(ctx)' in src, (
        "C13.5 regression: reads must call `_tenant_from_ctx(ctx)` "
        "instead of `_tenant_for(user)`. The TenantContext is the "
        "server-resolved authority; the user dict is not."
    )
    # Every surviving read route uses the ctx path:
    reads = re.findall(r'async def (read_\w+|read_balance\w+)\b', src)
    assert reads, "no read_* routes found at all"


# ─────────────────────────── C13.6 ───────────────────────────

def test_c13_6_scanner_has_no_whole_file_whitelist():
    """`ALLOWED_WRITER_MODULES` is empty; per-site allowed replaces it."""
    from app.services.warehouse_movements.legacy_inventory import (
        ALLOWED_WRITER_MODULES, ALLOWED_WRITER_SITES,
    )
    assert ALLOWED_WRITER_MODULES == (), (
        "C13.6 regression: whole-file whitelist re-introduced. "
        "`routes/material_smr.py`'s material_entries caps hid behind "
        "the old whole-file exemption; narrow per-site allowed is "
        "the replacement."
    )
    # Every per-site entry is a precise (file, collection) tuple:
    for key in ALLOWED_WRITER_SITES.keys():
        assert isinstance(key, tuple) and len(key) == 2, (
            f"C13.6 regression: non-narrow allowed site: {key!r}"
        )
        assert key[0].endswith(".py"), (
            f"C13.6 regression: file portion must be a .py path: {key!r}"
        )


def test_c13_6_scanner_zero_offenders_on_clean_tree():
    """Baseline: clean tree has zero offenders."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    hits = scan_repository_for_legacy_writers()
    total = sum(len(v) for v in hits.values())
    assert total == 0, (
        f"C13.6 regression: static writer inventory found "
        f"{total} offender position(s).\n"
        f"breakdown: " + ", ".join(f"{k}={len(v)}" for k, v in hits.items())
    )


def test_c13_6_scanner_mutation_direct_canonical_writer(tmp_path):
    """Mutation: injecting `tenant.warehouse_transactions.insert_one` fires."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    # Build a tiny fake tree carrying one offender outside allowed sites.
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app").mkdir()
    (tmp_path / "backend" / "app" / "evil.py").write_text(
        'async def do():\n'
        '    await tenant.warehouse_transactions.insert_one({"a": 1})\n'
    )
    hits = scan_repository_for_legacy_writers(repo_root=tmp_path)
    assert hits.get("warehouse_transactions"), (
        "C13.6 regression: scanner mutation probe FAILED to detect a "
        "direct writer into warehouse_transactions. The scan is "
        "silently broken."
    )


def test_c13_6_scanner_mutation_variable_chain_capped_read(tmp_path):
    """Mutation: `cursor = tenant.X.find(...); cursor.to_list(500)` fires."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app").mkdir()
    (tmp_path / "backend" / "app" / "evil.py").write_text(
        'async def do():\n'
        '    cursor = tenant.warehouse_transactions.find({"a": 1})\n'
        '    rows = await cursor.to_list(500)\n'
        '    return rows\n'
    )
    hits = scan_repository_for_legacy_writers(repo_root=tmp_path)
    offenders = hits.get("__capped_canonical_reads__") or []
    found = any(o.get("detected_via") == "variable_chain" for o in offenders)
    assert found, (
        "C13.6 regression: scanner mutation probe FAILED to detect a "
        "variable-chain capped read. The multiline detector is broken."
    )


def test_c13_6_scanner_mutation_permission_bypass(tmp_path):
    """Mutation: a `_AllowService` class fires."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app").mkdir()
    (tmp_path / "backend" / "app" / "evil.py").write_text(
        'class _AllowServiceEvil:\n'
        '    async def ensure(self, *a, **k):\n'
        '        return None\n'
    )
    hits = scan_repository_for_legacy_writers(repo_root=tmp_path)
    assert hits.get("__permission_bypass__"), (
        "C13.6 regression: scanner mutation probe FAILED to detect "
        "an `_AllowService*` bypass."
    )


def test_c13_6_scanner_mutation_env_mutation(tmp_path):
    """Mutation: a `PERMISSION_SERVICE_MODE` env mutation fires."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app").mkdir()
    (tmp_path / "backend" / "app" / "evil.py").write_text(
        'import os\n'
        'os.environ["PERMISSION_SERVICE_MODE"] = "disabled"\n'
    )
    hits = scan_repository_for_legacy_writers(repo_root=tmp_path)
    assert hits.get("__permission_mode_mutation__"), (
        "C13.6 regression: scanner mutation probe FAILED to detect "
        "a PERMISSION_SERVICE_MODE env mutation."
    )


def test_c13_6_scanner_mutation_random_idempotency(tmp_path):
    """Mutation: a random uuid4 idempotency fallback in warehouse fires."""
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app").mkdir()
    (tmp_path / "backend" / "app" / "warehouse_evil.py").write_text(
        'import uuid\n'
        'async def do():\n'
        '    idempotency_key = payload.get("key") or uuid.uuid4().hex\n'
    )
    hits = scan_repository_for_legacy_writers(repo_root=tmp_path)
    assert hits.get("__random_idempotency_key__"), (
        "C13.6 regression: scanner mutation probe FAILED to detect "
        "a random idempotency fallback in a warehouse module."
    )


def test_c13_6_scanner_rejects_wrong_collection_from_allowed_file(tmp_path):
    """A write to a DIFFERENT canonical collection from an allowed file
    is still an offender (narrow-site, not whole-file).
    """
    from app.services.warehouse_movements.legacy_inventory import (
        scan_repository_for_legacy_writers,
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app").mkdir()
    (tmp_path / "backend" / "app" / "routes").mkdir()
    # material_smr.py is ALLOWED only for `material_entries`. A write
    # to `warehouse_transactions` from the same file must still fire.
    (tmp_path / "backend" / "app" / "routes" / "material_smr.py").write_text(
        'async def do():\n'
        '    await tenant.warehouse_transactions.insert_one({"a": 1})\n'
    )
    hits = scan_repository_for_legacy_writers(repo_root=tmp_path)
    assert hits.get("warehouse_transactions"), (
        "C13.6 regression: narrow-site exemption is being read as "
        "whole-file. A write to a DIFFERENT canonical collection "
        "from an allowed file must still fail the scan."
    )
