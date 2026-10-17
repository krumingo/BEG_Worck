"""LIVE-OPS-01 / TASK 5C — CODEX C14 bounded correction regression gates.

CODEX accelerated re-review on head `86dda91f…`: 11 passed / 2 failed
on the focused selector + 0 passed / 2 failed on the two previously
failing tests re-run independently. These DB-free gates lock the
three C14.* contracts the real-Mongo re-run must verify:

* **C14.1** audit serialization under 10 concurrent cross-item
  writes — delegated to Mongo's `session.with_transaction` for proper
  exponential-backoff retry on `TransientTransactionError`; no
  service-level retry inflation; no fixed-count loop that exhausts
  under load.
* **C14.2** every new real-Mongo C13 test uses a valid enforce-mode
  TenantContext (not `ctx=None`); `allow_always_gate` replaces only
  the decision, not the ctx contract.
* **C14.3** the named `test_sales_consume_fifo_writes_canonical_ledger`
  gate asserts the frozen C13.3 fail-closed semantics
  (`LegacyWriterRetiredError` + zero ledger/audit/projection
  mutations) and no longer expects an invented sale=WRITE_OFF row.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# ─────────────────────────── C14.1 ───────────────────────────

def test_c14_1_execute_uses_session_with_transaction():
    """The business tx is wrapped by Mongo's `with_transaction`."""
    src = Path("app/services/warehouse_movements/service.py").read_text()
    assert "session.with_transaction(" in src, (
        "C14.1 regression: service no longer uses the Mongo-native "
        "transaction wrapper. The manual retry loop exhausted under "
        "10 concurrent writes; `session.with_transaction(callback)` "
        "is the canonical pattern that handles WriteConflict with "
        "exponential backoff and the server's 120s deadline."
    )
    assert "session.with_transaction(_tx_body)" in src or \
           "session.with_transaction(" in src


def test_c14_1_no_fixed_small_retry_budget_in_execute():
    """The outer execute() no longer runs a hard `_MAX_RETRIES=5` loop.

    The retry budget belongs to MongoDB's own `with_transaction`;
    the service wrapper only handles non-transient hard failures.
    """
    src = Path("app/services/warehouse_movements/service.py").read_text()
    # The `while attempt < _MAX_RETRIES:` loop in execute() must be
    # gone. The constant `_MAX_RETRIES` may still exist (fail-closed
    # outside of concurrent-tx paths) but the OUTER retry loop in
    # execute() must have been removed.
    assert "while attempt < _MAX_RETRIES" not in src, (
        "C14.1 regression: the fixed 5-retry service-level loop is "
        "back. 10 concurrent cross-item writes exhaust this budget "
        "with Mongo code 112 WriteConflict."
    )


def test_c14_1_execute_one_attempt_delegates_retry_to_mongo():
    """`_execute_one_attempt` uses `session.with_transaction`
    exclusively — no manual `start_transaction` block inside it."""
    src = Path("app/services/warehouse_movements/service.py").read_text()
    # Slice the file at the function definition and take ~80 lines of
    # body (enough to catch either pattern):
    anchor = "async def _execute_one_attempt("
    idx = src.find(anchor)
    assert idx != -1, "could not locate _execute_one_attempt"
    body = src[idx:idx + 4000]
    assert "session.with_transaction(" in body, (
        "C14.1 regression: _execute_one_attempt does not call "
        "with_transaction. Retry delegation to the driver is the fix."
    )
    # The manual `async with session.start_transaction()` body is gone
    # in favour of the callback. If a stray one survives, flag it.
    assert "async with session.start_transaction()" not in body, (
        "C14.1 regression: a manual start_transaction block is back "
        "inside _execute_one_attempt; the callback form is required."
    )


# ─────────────────────────── C14.2 ───────────────────────────

def test_c14_2_c13_mongo_tests_use_real_ctx_not_none():
    """No `svc.execute(None, ...)` call survives in the C13 Mongo tests."""
    src = Path("tests/test_warehouse_canonical_c13_mongo.py").read_text()
    assert "svc.execute(None," not in src, (
        "C14.2 regression: a `svc.execute(None, ...)` call survives. "
        "PermissionGate.ensure() raises 'missing tenant context' when "
        "ctx is None, so the test never reaches the audit chain / "
        "Rule B behaviour it claims to prove."
    )
    # And a shared ctx helper exists so the tests build a real
    # TenantContext-shaped object.
    assert "class _TestCtx" in src or "class _Ctx" in src, (
        "C14.2 regression: the TenantContext stand-in is gone from "
        "the C13 mongo tests."
    )


def test_c14_2_c13_test_ctx_has_required_fields():
    """The ctx stand-in exposes `tenant_id`, `user_id` and `org_id`."""
    src = Path("tests/test_warehouse_canonical_c13_mongo.py").read_text()
    # Grab the body of the ctx class:
    match = re.search(
        r"class _TestCtx[^:]*:\s*(?:\"\"\".+?\"\"\"\s*)?"
        r"def __init__\([^)]*\)[^:]*:\s*(.+?)(?=\n(?:class |def |#|\Z))",
        src, flags=re.DOTALL,
    )
    assert match, (
        "C14.2 regression: _TestCtx class not found in the C13 mongo tests."
    )
    body = match.group(1)
    for required in ("self.tenant_id", "self.user_id", "self.org_id"):
        assert required in body, (
            f"C14.2 regression: _TestCtx does not set {required}. "
            f"PermissionGate.ensure + evaluate_permission read these."
        )


# ─────────────────────────── C14.3 ───────────────────────────

def _named_sales_test_body(src: str) -> str:
    """Slice the file at the required gate's def line.

    CODEX enumerates the gate by its exact name — slicing by anchor
    beats regex here because the body contains `#` comments and
    multi-line strings that break lazy regex.
    """
    anchor = "async def test_sales_consume_fifo_writes_canonical_ledger("
    idx = src.find(anchor)
    assert idx != -1, (
        "C14.3 regression: the required gate was renamed or removed. "
        "CODEX enumerates it by exact name — keep the name."
    )
    # Take ~8000 chars (comfortably more than the function body) and
    # stop at the next top-level `async def` so we don't bleed into
    # the next test.
    tail = src[idx:idx + 8000]
    next_test = re.search(r"\nasync def test_", tail[len(anchor):])
    if next_test:
        tail = tail[: len(anchor) + next_test.start()]
    return tail


def test_c14_3_named_sales_test_asserts_legacy_writer_retired():
    """The required gate name must now check fail-closed semantics."""
    src = Path("tests/test_warehouse_canonical_mongo_full.py").read_text()
    body = _named_sales_test_body(src)
    assert "LegacyWriterRetiredError" in body, (
        "C14.3 regression: the named gate does not assert "
        "LegacyWriterRetiredError. The frozen C13.3 behavior is "
        "fail-closed; the obsolete sale=WRITE_OFF expectation must go."
    )
    assert "pytest.raises(LegacyWriterRetiredError)" in body, (
        "C14.3 regression: the named gate does not use "
        "`pytest.raises(LegacyWriterRetiredError)` to assert the raise."
    )


def test_c14_3_named_sales_test_asserts_zero_ledger_mutation():
    """The named gate proves the fail-closed invariant on real Mongo."""
    src = Path("tests/test_warehouse_canonical_mongo_full.py").read_text()
    body = _named_sales_test_body(src)
    # Ledger / audit / projection NOT mutated:
    assert "baseline_ledger" in body and "after_ledger == baseline_ledger" in body, (
        "C14.3 regression: ledger-equivalence assertion gone."
    )
    assert "baseline_audit" in body and "after_audit == baseline_audit" in body, (
        "C14.3 regression: audit-event equivalence assertion gone."
    )
    # No `write_off` row:
    assert '"action": "write_off"' in body and "wo_rows == 0" in body, (
        "C14.3 regression: write_off-row-count-zero assertion gone."
    )
    # No idempotency claim:
    assert 'audit_idempotency' in body and "claim is None" in body, (
        "C14.3 regression: idempotency-claim-none assertion gone."
    )


def test_c14_3_named_sales_test_does_not_assert_obsolete_write_off_row():
    """The old `count == 1` assertion for sale=WRITE_OFF is gone."""
    src = Path("tests/test_warehouse_canonical_mongo_full.py").read_text()
    body = _named_sales_test_body(src)
    # The pre-C14 body asserted `count == 1` where count was the
    # `write_off` row count. That assertion contradicts C13.3.
    assert 'fifo_service must route through the canonical service' not in body, (
        "C14.3 regression: the old 'canonical write_off' assertion "
        "text is back. The sale is NOT a write-off; the gate must "
        "assert zero write_off rows."
    )
