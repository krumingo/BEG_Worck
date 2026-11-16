"""
FIX-MAT-02 — Р99 (Крум, 16.11.2026): ONE rule for when a supplier invoice
is project / company cost.

    „Фактурата от доставчик става разход по проекта, когато е официално
    въведена. Чернова и анулирана фактура не са разход за материали и не са
    ДДС по проекта. Всички екрани (P&L, финансов резултат, пълна
    себестойност, табла) ползват едно и също правило, за да показват едно
    число."

"Officially entered" = the invoice's status is in ``OFFICIAL_INVOICE_STATUSES``
— every status of ``models.finance.INVOICE_STATUSES`` except ``Draft`` (not
entered yet: it can still be edited or deleted) and ``Cancelled`` (void).
Today that is ``Sent``, ``PartiallyPaid``, ``Paid``, ``Overdue``.

The set is POSITIVE on purpose: a line whose invoice is missing in the tenant
(e.g. the lines left behind by a deleted Draft) or carries an unknown status
is not officially entered either, so it is no cost.

Read-time only: nothing is stored, no document is changed, no migration.
Every reader that turns supplier (Received) invoices or their lines into a
cost / expense / input-VAT total goes through this module (Path B and input
VAT in ``canonical_material_cost``; the per-line result projection in
``invoice_allocation``; the dashboard / report header totals).

Issued (client) invoices are NOT governed by this module (revenue rules
R86 / R89 are a separate area).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from app.models.finance import INVOICE_STATUSES

# Р99 — not officially entered: never cost, never project input VAT.
NOT_OFFICIAL_INVOICE_STATUSES: Tuple[str, ...] = ("Draft", "Cancelled")

# Р99 — officially entered (the positive set every reader uses).
OFFICIAL_INVOICE_STATUSES: Tuple[str, ...] = tuple(
    s for s in INVOICE_STATUSES if s not in NOT_OFFICIAL_INVOICE_STATUSES)

R99_RULE = "R99_officially_entered_invoice"


def is_officially_entered(invoice: Optional[dict]) -> bool:
    """True when the invoice document is officially entered (Р99)."""
    return bool(invoice) and invoice.get("status") in OFFICIAL_INVOICE_STATUSES


def official_status_query() -> Dict[str, Any]:
    """The Mongo condition on ``status`` for an officially entered invoice."""
    return {"$in": list(OFFICIAL_INVOICE_STATUSES)}


def official_status_expr(field: str = "$status") -> Dict[str, Any]:
    """The aggregation-expression form of the same rule (``$cond`` etc.)."""
    return {"$in": [field, list(OFFICIAL_INVOICE_STATUSES)]}


async def official_invoice_ids(tenant, org_id: str, invoice_ids: Iterable[Any], *,
                               session=None) -> set:
    """The ids among ``invoice_ids`` whose invoice (of THIS tenant) is
    officially entered. Read from the invoice documents themselves, so the
    answer never depends on a caller's projection."""
    ids = sorted({i for i in invoice_ids if i})
    if not ids:
        return set()
    kw = {"session": session} if session is not None else {}
    return {inv["id"] async for inv in tenant.invoices.find(
        {"org_id": org_id, "id": {"$in": ids}, "status": official_status_query()},
        {"_id": 0, "id": 1}, **kw)}
