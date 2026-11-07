"""
5C-C26l Addendum N — FLOW Guard FG-140 (FLOW-006 / CLAUDE §7: an official
invoice is not edited; corrections go through correction / reversal).

Every writer that changes an invoice (its lines, its header totals, its
status, its payments) decides the invoice's status INSIDE its transaction and
writes the invoice document with that status as a CAS condition
(``claim_invoice``). Two consequences:

  * the status check and the write cannot be separated by a concurrent
    send / pay / cancel — a status read before the transaction is never
    trusted;
  * every such transaction WRITES the invoice document, so two of them on
    the same invoice write-conflict and ``with_transaction`` re-runs the
    loser, which then sees the committed status: an edit racing a send or a
    payment either commits while the invoice is still in its editable
    status, or gets 409 and writes nothing.

The status sets themselves are the routes' existing business rules; only
WHERE they are decided changes.
"""
from __future__ import annotations

from typing import Iterable, Optional

from fastapi import HTTPException

NOT_DRAFT = "INVOICE_NOT_DRAFT"
STATUS_CHANGED = "INVOICE_STATUS_CHANGED"


def status_conflict(code: str, invoice_id: str, status: Optional[str]) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "error_code": code, "invoice_id": invoice_id, "status": status,
        "message": "Статусът на фактурата се промени — промяната не е записана "
                   "(официален документ се коригира само чрез корекция/сторно)."})


async def claim_invoice(tenant, invoice_id: str, *, session,
                        allowed: Optional[Iterable[str]] = None,
                        forbidden: Optional[Iterable[str]] = None,
                        code: str = STATUS_CHANGED) -> Optional[dict]:
    """Read the invoice in ``session`` and claim it: a CAS write on the
    invoice document conditioned on its status (``allowed`` or not
    ``forbidden``). 409 when the status does not qualify; None when the
    invoice does not exist (the caller keeps its own 404 / orphan rule)."""
    invoice = await tenant.invoices.get(invoice_id, session=session)
    if invoice is None:
        return None
    cond = ({"$in": list(allowed)} if allowed is not None
            else {"$nin": list(forbidden or ())})
    res = await tenant.invoices.update_one(
        {"id": invoice_id, "status": cond}, {"$inc": {"edit_seq": 1}}, session=session)
    if res.matched_count == 0:
        raise status_conflict(code, invoice_id, invoice.get("status"))
    return invoice
