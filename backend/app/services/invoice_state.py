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
BUSY = "INVOICE_BUSY"

# PAY-01 (#70) row lock on the invoice / payment document (``finance._row_lock``):
# the field and the staleness window — one definition, used by both.
ROW_LOCK_FIELD = "allocation_lock"
PAYMENT_LOCK_STALE_SECONDS = 30


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
    ``forbidden``) AND on no live PAY-01 row lock (a payment / allocation
    being written under ``finance._invoice_lock``). 409 when the status does
    not qualify (``code``) or the invoice is locked (INVOICE_BUSY); None when
    the invoice does not exist (the caller keeps its own 404 / orphan rule)."""
    from datetime import datetime, timedelta, timezone
    invoice = await tenant.invoices.get(invoice_id, session=session)
    if invoice is None:
        return None
    cond = ({"$in": list(allowed)} if allowed is not None
            else {"$nin": list(forbidden or ())})
    stale = (datetime.now(timezone.utc)
             - timedelta(seconds=PAYMENT_LOCK_STALE_SECONDS)).isoformat()
    res = await tenant.invoices.update_one(
        {"id": invoice_id, "status": cond,
         "$or": [{ROW_LOCK_FIELD: {"$exists": False}},
                 {ROW_LOCK_FIELD + ".at": {"$lt": stale}}]},
        {"$inc": {"edit_seq": 1}}, session=session)
    if res.matched_count == 0:
        lock = invoice.get(ROW_LOCK_FIELD) or {}
        if lock and str(lock.get("at") or "") >= stale:
            raise HTTPException(status_code=409, detail={
                "error_code": BUSY, "invoice_id": invoice_id,
                "message": "Фактурата се обработва от друга заявка — опитайте отново"})
        raise status_conflict(code, invoice_id, invoice.get("status"))
    return invoice
