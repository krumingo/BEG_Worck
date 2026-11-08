"""
WH-REV-01 — supplier receipt reversal (сторно на получаване), the shared reads.

A reversal is its own append-only ledger row (``reverse_supplier_receipt`` /
``reverse_supplier_receipt_to_project``) naming the receipt in
``reverses_movement_id``; the receipt row itself is never changed or deleted
(CLAUDE §2.9, §7; FLOW-009). Everything that reads "the linked supplier
receipts of an invoice line" — the per-line covered quantity (Addendum K/L),
the FG-109 allocation lock, Path B, the over-link and project-conflict
warnings, the price history — must therefore read the receipts that are NOT
reversed. ``reversed_ids`` is that one rule.
"""
from __future__ import annotations

from typing import Iterable, Set

REVERSAL_ACTION_VALUES = ("reverse_supplier_receipt", "reverse_supplier_receipt_to_project")


async def reversed_ids(collection, movement_ids: Iterable[str], *, session=None) -> Set[str]:
    """The receipts among ``movement_ids`` that a reversal row reverses.
    ``collection`` is the tenant's (TenantData-scoped) ledger."""
    ids = sorted({m for m in movement_ids if m})
    if not ids:
        return set()
    out: Set[str] = set()
    async for row in collection.find(
            {"action": {"$in": list(REVERSAL_ACTION_VALUES)},
             "reverses_movement_id": {"$in": ids}},
            {"_id": 0, "reverses_movement_id": 1}, session=session):
        out.add(row["reverses_movement_id"])
    return out


async def without_reversed(collection, rows, *, session=None):
    """``rows`` minus the reversed receipts and minus reversal rows."""
    rows = [r for r in rows if r.get("action") not in REVERSAL_ACTION_VALUES]
    gone = await reversed_ids(collection, [r.get("movement_id") for r in rows],
                              session=session)
    return [r for r in rows if r.get("movement_id") not in gone]
