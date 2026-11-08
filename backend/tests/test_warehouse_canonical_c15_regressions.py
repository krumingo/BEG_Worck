"""LIVE-OPS-01 / TASK 5C — CODEX C15 bounded correction regression gates.

CODEX accelerated C14 re-review on head `c3d6d834…`: 7 passed / 2
failed on the focused real-Mongo gate. Both new C13 Mongo tests
(`test_c13_1_cross_item_audit_chain_no_fork_under_ten_concurrent_writes`
and `test_c13_2_rule_b_10_3_4_3_zero_unresolved_at_close`) failed
BEFORE reaching their intended business assertions because the raw
`db["warehouse_transactions"]` (`AsyncIOMotorCollection`) has no
`._scope` attribute; `CommandService._next_ledger_sequence` reads
`tenant_collection._scope._db` and `svc.execute` wraps the resulting
`AttributeError` as `AuditChainWriteError`. CODEX also flagged
`test_c13_1_audit_failure_rolls_back_movement_and_counters` as a
FALSE POSITIVE: `pytest.raises(Exception)` can be satisfied by that
same pre-audit error — the test proves nothing about rollback.

These DB-free gates lock the two C15.* contracts the real-Mongo
re-run must verify:

* **C15.1** every C13 real-Mongo CommandService test uses the
  production tenant-scoped `TenantCollection` wrapper
  (`_tenant_coll(db)` → `TenantData.for_resolved_org(db, tenant_id)
  .warehouse_transactions`) and NEVER passes raw
  `db["warehouse_transactions"]` to `svc.execute(...)`;
* **C15.2** `test_c13_1_audit_failure_rolls_back_movement_and_counters`
  asserts the SPECIFIC injected sentinel exception, proves
  `_record_event_in_session` was actually invoked, and checks
  counter non-advance in addition to ledger/projection/audit/
  idempotency residue.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_C13_MONGO = Path("tests/test_warehouse_canonical_c13_mongo.py")


# ───────────────────────────── C15.1 ─────────────────────────────

def test_c15_1_c13_mongo_has_tenant_coll_helper():
    """The test module exposes a `_tenant_coll(db, tenant_id)` helper
    that returns the production `TenantCollection` wrapper, so every
    `svc.execute` call reaches the service with the proper collection.
    """
    src = _C13_MONGO.read_text()
    assert "def _tenant_coll(" in src, (
        "C15.1 regression: the tenant-scoped collection helper is "
        "gone. The tests must use `TenantData.for_resolved_org(...)."
        "warehouse_transactions`, not the raw motor collection."
    )
    # The helper calls the SAME production path that production
    # routes and the established canonical Mongo suite use:
    assert "TenantData.for_resolved_org(" in src, (
        "C15.1 regression: `_tenant_coll` no longer builds the "
        "tenant via `TenantData.for_resolved_org`."
    )
    assert "tenant.warehouse_transactions" in src, (
        "C15.1 regression: `_tenant_coll` no longer returns "
        "`tenant.warehouse_transactions`."
    )


def test_c15_1_no_svc_execute_with_raw_motor_collection():
    """No `svc.execute(ctx, db, db["warehouse_transactions"], ...)` survives."""
    src = _C13_MONGO.read_text()
    # The failure pattern CODEX reproduced:
    assert 'svc.execute(_TestCtx("T"), db, db["warehouse_transactions"]' not in src, (
        "C15.1 regression: a raw motor-collection `svc.execute` call "
        "survives. `CommandService._next_ledger_sequence` reads "
        "`tenant_collection._scope._db` — this will fail with "
        "AuditChainWriteError wrapping AttributeError before any "
        "business assertion runs."
    )
    # Every live execute call must go through _tenant_coll:
    exec_calls = re.findall(
        r"svc\.execute\(_TestCtx\(\"T\"\),\s*db,\s*([^,]+),",
        src,
    )
    assert exec_calls, "no svc.execute calls found in C13 mongo tests"
    for third_arg in exec_calls:
        third_arg = third_arg.strip()
        assert "_tenant_coll" in third_arg, (
            f"C15.1 regression: `svc.execute` third arg is "
            f"{third_arg!r} — must be `_tenant_coll(db)` (or an "
            f"equivalent tenant-scoped collection)."
        )


# ───────────────────────────── C15.2 ─────────────────────────────

def _rollback_test_body(src: str) -> str:
    """Slice the audit-rollback test body for inspection."""
    anchor = "async def test_c13_1_audit_failure_rolls_back_movement_and_counters("
    idx = src.find(anchor)
    assert idx != -1, (
        "C15.2 regression: the required audit-rollback gate is gone."
    )
    tail = src[idx:idx + 10000]
    next_test = re.search(r"\n(?:async def |def )test_", tail[len(anchor):])
    if next_test:
        tail = tail[: len(anchor) + next_test.start()]
    return tail


def test_c15_2_rollback_test_uses_specific_sentinel_exception():
    """The injected failure is a UNIQUE class so a pre-audit error
    cannot satisfy `pytest.raises`."""
    body = _rollback_test_body(_C13_MONGO.read_text())
    assert "class _C15AuditSentinel" in body, (
        "C15.2 regression: the sentinel exception class is gone. "
        "A broad `pytest.raises(Exception)` was flagged by CODEX as "
        "satisfied by pre-audit errors — the rollback test must "
        "assert a specific exception class to prove the audit path "
        "was the one that failed."
    )
    # And the test asserts (directly or via chain) that `_C15AuditSentinel`
    # was raised. The service may wrap it as `AuditChainWriteError`,
    # so we walk `__cause__`:
    assert "isinstance(" in body and "_C15AuditSentinel" in body, (
        "C15.2 regression: the test must assert the raised exception "
        "IS or CHAINS to `_C15AuditSentinel`."
    )
    assert "__cause__" in body, (
        "C15.2 regression: the test must walk `__cause__` to peel the "
        "service's `AuditChainWriteError` wrapper off the sentinel."
    )


def test_c15_2_rollback_test_proves_boom_was_called():
    """The patched `_record_event_in_session` was ACTUALLY invoked."""
    body = _rollback_test_body(_C13_MONGO.read_text())
    assert "boom_calls" in body, (
        "C15.2 regression: the invocation ledger `boom_calls` is "
        "gone. The patched function must record its call so the "
        "test can prove the audit write was the failure site."
    )
    assert "len(boom_calls) >= 1" in body, (
        "C15.2 regression: the test must assert the patch was "
        "invoked at least once. If `_record_event_in_session` was "
        "never called, the rollback invariant is UNVERIFIED."
    )


def test_c15_2_rollback_test_asserts_counter_non_advance():
    """Counters must not have advanced past their pre-call snapshot."""
    body = _rollback_test_body(_C13_MONGO.read_text())
    for marker in ("pre_ledger_val", "post_ledger_val",
                   "post_ledger_val == pre_ledger_val",
                   "pre_chain_seq", "post_chain_seq",
                   "post_chain_seq == pre_chain_seq"):
        assert marker in body, (
            f"C15.2 regression: counter-advance proof missing "
            f"`{marker}`. If the ledger_sequence or audit_chain_head "
            f"counter survived an aborted tx, future writes would "
            f"use gapped sequences and the chain would be broken."
        )


def test_c15_2_rollback_test_still_asserts_four_residue_invariants():
    """The pre-existing invariants (ledger, projection, audit,
    idempotency) remain asserted after the C15.2 tightening."""
    body = _rollback_test_body(_C13_MONGO.read_text())
    # Four residue invariants:
    assert "warehouse_transactions" in body and "== 0" in body
    assert "warehouse_batches" in body
    assert "audit_events" in body
    assert "audit_idempotency" in body
    # And the broad `pytest.raises(Exception)` is tightened by an
    # immediate sentinel discrimination — not left as the only check.
    # We locate the single real `pytest.raises(Exception) as exc_info`
    # call site (not inside comments) and prove it's followed by
    # unwrap-and-assert logic within ~30 lines.
    live_raises = re.search(
        r"with pytest\.raises\(Exception\) as exc_info:\s*\n"
        r"\s*await svc\.execute\(",
        body,
    )
    assert live_raises, (
        "C15.2 regression: the live `pytest.raises(Exception) as "
        "exc_info` call site is gone or malformed."
    )
    tail_after = body[live_raises.end(): live_raises.end() + 2000]
    assert "is_sentinel" in tail_after and "_C15AuditSentinel" in tail_after, (
        "C15.2 regression: the live `pytest.raises(Exception)` is "
        "not tightened by a sentinel discrimination step."
    )


# ───────────────────────────── Cross-check ─────────────────────────────

def test_c15_both_fixed_tests_do_not_regress_elsewhere():
    """Both named failing tests from C14 run under the new rules.

    The specific tests CODEX enumerated must still exist, retain the
    exact names (CODEX enumerates them by name), and now use
    `_tenant_coll(db)` in every `svc.execute` call.
    """
    src = _C13_MONGO.read_text()
    for name in (
        "test_c13_1_cross_item_audit_chain_no_fork_under_ten_concurrent_writes",
        "test_c13_2_rule_b_10_3_4_3_zero_unresolved_at_close",
        "test_c13_1_audit_failure_rolls_back_movement_and_counters",
    ):
        assert f"async def {name}(" in src, (
            f"C15 regression: required gate {name!r} was renamed or "
            f"removed. CODEX enumerates it by exact name."
        )
