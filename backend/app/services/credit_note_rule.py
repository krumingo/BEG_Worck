"""WH-REV-01 — Р47 (Крум 08.11.2026): paid ≤ net received.

A supplier invoice whose linked receipt was reversed awaits a credit note
(open ``expected_credit_notes``). Until the credit note is registered (debt
t26) the invoice may be paid only up to its NET value:

    paid + new payment  ≤  invoice total − awaited credit

The ONE comparison, in canonical integer cents with NO allowance (F-82-02),
shared by every FLOW-006 path to an invoice (quick-pay, allocate) and by the
reversal itself (F-82-01: a reversal that would push the payable amount
below what is already paid is refused — a payment is never cancelled
automatically).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def cents(value) -> int:
    """Canonical integer cents of a money value (half-up)."""
    return int((Decimal(str(value or 0)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def payable_cents(total, paid, credit) -> int:
    """What may still be paid: total − paid − awaited credit (may be < 0)."""
    return cents(total) - cents(paid) - cents(credit)


def payment_exceeds_net(amount, total, paid, credit) -> bool:
    """True when paying ``amount`` would bring paid above the net value."""
    return cents(amount) > payable_cents(total, paid, credit)


def credit_exceeds_unpaid(total, paid, credit) -> bool:
    """True when an awaited credit would put the net value below what is paid."""
    return payable_cents(total, paid, credit) < 0
