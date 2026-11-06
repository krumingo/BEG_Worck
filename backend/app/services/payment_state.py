"""
PAY-01 (decision R23, Krum 06.11.2026; FLOW Guard FG-34) — one rule for which payment
rows count as real money.

Canon: CLAUDE.md §2.9 (no hard delete of financial records), §7 (reversal/correction
instead of edit), FLOW-006 §Корекции, FLOW-043 D-03 (one Payment ledger), D-08.

A payment is never deleted. It is reversed:

  * the original row stays in ``finance_payments`` with ``status = "reversed"`` and a
    link ``reversed_by_payment_id``;
  * a reversal row is added with ``status = "reversal"``, ``reverses_payment_id``,
    the OPPOSITE direction and the same amount and account.

An allocation of a payment to an invoice is never deleted either: it gets
``status = "cancelled"``.

Every report excludes the reversed original AND its reversal row, so the pair nets to
0 in every total. (Because the reversal has the opposite direction, an account balance
that forgot this filter would still net to 0 — but the gross inflow/outflow would not.)
Rows written before PAY-01 have no ``status`` and are active.

Pure logic, no database access.
"""
from typing import Any, Dict, Mapping, Optional

PAYMENT_REVERSED = "reversed"        # the original, kept
PAYMENT_REVERSAL = "reversal"        # the reverse entry
NOT_COUNTED_PAYMENT_STATUSES = (PAYMENT_REVERSED, PAYMENT_REVERSAL)

ALLOCATION_CANCELLED = "cancelled"


def _with(flt: Optional[Mapping], clause: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(flt or {})
    if "status" in out:
        # never silently replace a caller's status condition
        return {"$and": [out, clause]}
    out.update(clause)
    return out


def active_payments(flt: Optional[Mapping] = None) -> Dict[str, Any]:
    """``flt`` restricted to payment rows that count as money (not a reversed pair)."""
    return _with(flt, {"status": {"$nin": list(NOT_COUNTED_PAYMENT_STATUSES)}})


def active_allocations(flt: Optional[Mapping] = None) -> Dict[str, Any]:
    """``flt`` restricted to allocations that are not cancelled."""
    return _with(flt, {"status": {"$ne": ALLOCATION_CANCELLED}})


def payment_counts(payment: Optional[Mapping]) -> bool:
    return bool(payment) and payment.get("status") not in NOT_COUNTED_PAYMENT_STATUSES


def opposite_direction(direction: str) -> str:
    return "Outflow" if direction == "Inflow" else "Inflow"


# ── PAY-01-C01 Addendum A (FLOW Guard FG-45) ──────────────────────────────────
# A payment written by another module must be reversed IN that module, or the module's
# own register (pay run / advance / subcontractor package) and the Payment ledger
# diverge (FLOW-006). Until the module has its own reversal, a finance reversal of such a
# row is refused: 409 SOURCE_MODULE_REVERSAL_REQUIRED.
#
# The origin is read from the fields those modules write (on main, the only writers of
# ``finance_payments`` outside finance.py):
#   * subcontractors.py create payment   → ``subcontractor_payment_id``          → "subcontractor"
#   * pay_runs.py _write_salary_outflows → ``category == "Заплата"`` (reference = run id) → "pay_run"
#   * hr.py create advance / loan        → ``category in ("Аванс", "Заем")``      → "hr_advance"
#   * hr.py loan repayment               → ``category == "Връщане заем"``         → "hr_advance"
# ``pay_run_id`` / ``advance_id`` are honoured as well, should a module start linking by id.
SOURCE_MODULE_REVERSAL_REQUIRED = "SOURCE_MODULE_REVERSAL_REQUIRED"
_CATEGORY_SOURCE = {
    "Заплата": "pay_run",
    "Аванс": "hr_advance",
    "Заем": "hr_advance",
    "Връщане заем": "hr_advance",
}


def source_module(payment: Optional[Mapping]) -> Optional[str]:
    """The module that owns this payment row, or None for a finance-owned (manual) payment."""
    if not payment:
        return None
    if payment.get("subcontractor_payment_id"):
        return "subcontractor"
    if payment.get("pay_run_id"):
        return "pay_run"
    if payment.get("advance_id"):
        return "hr_advance"
    return _CATEGORY_SOURCE.get(payment.get("category") or "")
