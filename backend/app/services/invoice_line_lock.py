"""
5C-C26l — the per-invoice-line lock shared by the canonical warehouse and the
invoice-line routes (D-04 / FLOW-009: a lot is cost by ONE path).

  * Addendum K (WH55-C26L-1): every linked supplier receipt (warehouse or
    direct delivery) writes the lock document of its invoice line inside the
    movement transaction, so two linked movements of the same line are
    serialized (WriteConflict → ``with_transaction`` re-runs the loser).
  * Addendum L / FG-109: once a canonical movement links the line, its
    allocation (and the qty / unit / price it is costed by) is LOCKED — 409
    INVOICE_LINE_ALLOCATION_LOCKED, nothing written. The decision is taken
    in one transaction that writes the SAME lock document, so a delivery and
    a reallocation of the same line cannot both pass.

The lock document is one counter per (tenant, line) with a deterministic
``_id`` in the tenant's org_id-keyed ``warehouse_ledger_counters``, reached
through TenantData (never a raw handle).
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

LOCKED_CODE = "INVOICE_LINE_ALLOCATION_LOCKED"
LINKED_RECEIPT_ACTIONS = ("receive_from_supplier", "receive_from_supplier_to_project")


class InvoiceLineAllocationLocked(Exception):
    def __init__(self, line_id: str, movement_id: Optional[str]):
        super().__init__(f"invoice line {line_id} is linked by movement {movement_id}")
        self.line_id = line_id
        self.movement_id = movement_id

    def detail(self) -> dict:
        return {"error_code": LOCKED_CODE,
                "message": "Редът е свързан със складово движение — разпределението, "
                           "количеството, мярката и цената са заключени. Промяна само "
                           "чрез корекция/сторно.",
                "invoice_line_id": self.line_id, "movement_id": self.movement_id}


def lock_id(org_id: str, line_id: str) -> str:
    return f"invoice_line_lock:{org_id}:{line_id}"


async def ensure_line_lock(tenant, line_id: str) -> None:
    """Create the lock document OUTSIDE any transaction (idempotent): a
    transaction then only updates it, so two first transactions never race
    to create the collection / document."""
    from pymongo.errors import DuplicateKeyError
    try:
        await tenant.warehouse_ledger_counters.update_one(
            {"_id": lock_id(tenant.org_id, line_id)},
            {"$setOnInsert": {"tenant_id": tenant.org_id, "name": "invoice_line_lock",
                              "invoice_line_id": line_id, "value": 0}},
            upsert=True)
    except DuplicateKeyError:
        pass                                  # a concurrent caller created it


async def bump_line_lock(tenant, line_id: str, *, session=None) -> None:
    await tenant.warehouse_ledger_counters.update_one(
        {"_id": lock_id(tenant.org_id, line_id)},
        {"$inc": {"value": 1},
         "$setOnInsert": {"tenant_id": tenant.org_id, "name": "invoice_line_lock",
                          "invoice_line_id": line_id}},
        upsert=True, session=session)


async def first_linked_movement(tenant, line_id: str, *, session=None) -> Optional[str]:
    """The movement id of a canonical ledger row that links the line, or None.

    WH-REV-01: a reversed supplier receipt no longer links the line (its
    reversal row carries ``reversed_invoice_line_id``, never
    ``invoice_line_id``) — so reversing every linked receipt unlocks the
    allocation, which can then be corrected."""
    from app.services.warehouse_movements.reversal import without_reversed
    rows = [row async for row in tenant.warehouse_transactions.find(
        {"action": {"$exists": True}, "invoice_line_id": line_id},
        {"_id": 0, "movement_id": 1, "action": 1}, session=session)]
    rows = await without_reversed(tenant.warehouse_transactions, rows, session=session)
    return (rows[0].get("movement_id") or "linked") if rows else None


async def reversed_receipts(tenant, line_id: str, *, session=None) -> list:
    """WH-REV-01 / FG-195 — the line's linked supplier receipts that were
    REVERSED. Non-empty means the line was linked (its allocation had been
    locked, FG-109) and the lock was released by a reversal: changing the
    allocation now is a CORRECTION of an official record (CLAUDE §7) — it
    needs a reason, a version and an AuditEvent, never a silent move."""
    from app.services.warehouse_movements.reversal import reversed_ids
    ids = [row["movement_id"] async for row in tenant.warehouse_transactions.find(
        {"action": {"$in": list(LINKED_RECEIPT_ACTIONS)}, "invoice_line_id": line_id},
        {"_id": 0, "movement_id": 1}, session=session)]
    return sorted(await reversed_ids(tenant.warehouse_transactions, ids, session=session))


def _transactions_unsupported(exc: Exception) -> bool:
    if isinstance(exc, NotImplementedError):     # an in-memory test double
        return True
    code = getattr(exc, "code", None)
    text = str(exc)
    return code == 20 or "Transaction numbers are only allowed" in text \
        or "replica set" in text.lower()


async def run_transaction(tenant, body: Callable[[Optional[object]], Awaitable[None]]) -> None:
    """Run ``body(session)`` in one MongoDB transaction over the TENANT's own
    database (``with_transaction`` retries it on a WriteConflict). A
    deployment without transactions, or an in-memory test double
    (``tenant.transaction_client`` is None), runs ``body(None)`` instead."""
    client = getattr(tenant, "transaction_client", None)
    if client is None:
        await body(None)
        return
    try:
        session_cm = await client.start_session()
    except Exception:
        session_cm = None
    if session_cm is None:
        await body(None)
        return
    async with session_cm as session:
        try:
            await session.with_transaction(body)
            return
        except Exception as exc:
            if not _transactions_unsupported(exc):
                raise
    await body(None)


async def write_unless_linked(tenant, line_id: str,
                              write: Callable[[Optional[object]], Awaitable[None]], *,
                              refuse_if_linked: bool = True) -> None:
    """Run ``write(session)`` in one transaction under the line lock, and —
    with ``refuse_if_linked`` — only if no canonical movement links the line
    (otherwise :class:`InvoiceLineAllocationLocked`, nothing written).

    5C-C26l (Codex F-55-C26-04): ``write`` must read the CURRENT row with
    ``session`` and compute what it writes from it — never from a row read
    before the transaction — so a concurrent writer of the same line (the
    same lock) cannot be overwritten with stale derived values.
    A deployment without transactions (no canonical warehouse there) falls
    back to check-then-write."""
    await ensure_line_lock(tenant, line_id)

    async def _body(session):
        if session is not None:
            await bump_line_lock(tenant, line_id, session=session)
        if refuse_if_linked:
            moved = await first_linked_movement(tenant, line_id, session=session)
            if moved:
                raise InvoiceLineAllocationLocked(line_id, moved)
        await write(session)

    await run_transaction(tenant, _body)


# ───────────── WH-FIX-01 (WHFIX81-01) — the per-SUPPLIER-INVOICE lock ─────────────
# The FG-157 lock of PUT /supplier-invoices is decided in ONE transaction that
# writes the supplier invoice document itself (`link_lock_seq` $inc), and every
# canonical supplier receipt that links that invoice (by `invoice_id`, or by
# `invoice_line_id` of one of its lines) writes the SAME field in its movement
# transaction. A receipt that commits while the PUT is in flight makes the PUT's
# transaction write-conflict → `with_transaction` re-runs it → it sees the
# receipt → 409. The document always exists (no collection is created), and it
# is the tenant's own supplier invoice (org_id-scoped through TenantData).

def supplier_invoice_lock_id(org_id: str, invoice_id: str) -> str:
    return f"supplier_invoice_lock:{org_id}:{invoice_id}"


async def ensure_supplier_invoice_lock(tenant, invoice_id: str) -> None:
    """Nothing to create: the lock is the supplier invoice document."""
    return None


async def bump_supplier_invoice_lock(tenant, invoice_id: str, *, session=None) -> None:
    await tenant.supplier_invoices.update_one(
        {"id": invoice_id}, {"$inc": {"link_lock_seq": 1}}, session=session)


async def supplier_invoices_of_receipt(tenant, invoice_id, invoice_line_id, *, session=None):
    """The supplier invoices a receipt links: its `invoice_id` if that is a
    supplier invoice, and the supplier invoice that holds `invoice_line_id`."""
    out = set()
    ors = []
    if invoice_id:
        ors.append({"id": invoice_id})
    if invoice_line_id:
        ors.append({"lines.id": invoice_line_id})
    if not ors:
        return out
    async for inv in tenant.supplier_invoices.find({"$or": ors}, {"_id": 0, "id": 1},
                                                   session=session):
        out.add(inv["id"])
    return out
