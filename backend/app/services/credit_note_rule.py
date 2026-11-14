"""WH-REV-01 — Р47 (Крум 08.11.2026): paid ≤ net received.

A supplier invoice whose linked receipt was reversed awaits a credit note
(open ``expected_credit_notes``). Until the credit note is registered (debt
t26) the invoice may be paid only up to its NET value:

    paid + new payment  ≤  invoice total − awaited credit

The ONE comparison, in canonical integer cents with NO allowance (F-82-02),
shared by every FLOW-006 path to an invoice (quick-pay, allocate) and by the
reversal itself. Р84 (Крум 14.11.2026, FG-570): a reversal that leaves the
invoice paid above its net value is still recorded; the overpaid part
(``overpaid_cents``) becomes a supplier claim — a payment is never cancelled
or netted automatically.
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


def overpaid_cents(total, paid, credit) -> int:
    """How much of what is ALREADY paid lies above the net value
    (total − credit): the Р84 supplier claim. 0 when nothing is paid."""
    if cents(paid) <= 0:
        return 0
    return max(-payable_cents(total, paid, credit), 0)


def credit_exceeds_unpaid(total, paid, credit) -> bool:
    """True when an awaited credit would put the net value (total − credit)
    below what is ALREADY paid. Nothing paid → nothing to protect (False)."""
    return cents(paid) > 0 and payable_cents(total, paid, credit) < 0
