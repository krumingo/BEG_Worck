"""
FIFO Warehouse Service — Batch-based stock management.
All stock operations go through batches ordered by received_at (FIFO).
"""
from datetime import datetime, timezone
from typing import Optional, List
import uuid
import logging

from app.db import db
from app.tenancy.data_access import TenantData

logger = logging.getLogger(__name__)


class InsufficientStockError(Exception):
    def __init__(self, item_id: str, warehouse_id: str, requested: float, available: float):
        self.item_id = item_id
        self.warehouse_id = warehouse_id
        self.requested = requested
        self.available = available
        super().__init__(f"Insufficient stock: requested {requested}, available {available}")


async def generate_batch_number(org_id: str) -> str:
    tenant = TenantData.for_resolved_org(db, org_id)
    year = datetime.now(timezone.utc).strftime("%Y")
    last = await tenant.warehouse_batches.find_one(
        {"org_id": org_id, "batch_number": {"$regex": f"^BATCH-{year}-"}},
        sort=[("batch_number", -1)],
    )
    seq = 1
    if last:
        try:
            seq = int(last["batch_number"].split("-")[2]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"BATCH-{year}-{seq:04d}"


async def add_batch(
    org_id: str,
    item_id: str,
    warehouse_id: str,
    qty: float,
    unit_cost: float,
    source_type: str = "purchase",
    supplier_id: str = None,
    invoice_number: str = None,
    invoice_date: str = None,
    ordered_by: str = None,
    currency: str = "BGN",
    expires_at: str = None,
    notes: str = None,
    batch_number: str = None,
    received_at: str = None,
) -> dict:
    """LIVE-OPS-01 / TASK 5C — RETIRED physical writer.

    `warehouse_batches` is a projection over the canonical ledger.
    Every production caller has been retired to the canonical command
    service. Any residual call now fails CLOSED instead of writing a
    second stock source (C01).
    """
    from app.services.warehouse_movements.errors import LegacyWriterRetiredError
    raise LegacyWriterRetiredError(
        "fifo_service.add_batch is retired; use the canonical command service",
        context={"route_id": "fifo_service.add_batch",
                 "canonical_action": "receive_from_supplier"},
    )


async def consume_fifo(
    org_id: str,
    item_id: str,
    warehouse_id: str,
    qty_needed: float,
    *,
    ctx=None,
    actor_id: Optional[str] = None,
    sale_reference: Optional[str] = None,
    sale_evidence_file_ids: Optional[List[str]] = None,
    idempotency_key: Optional[str] = None,
    unit: str = "бр",
) -> list:
    """LIVE-OPS-01 / TASK 5C — CODEX C13.3 — **FAIL CLOSED**.

    An ordinary sale is NOT scrap/loss/theft, so it does not map onto
    the frozen contract's `WRITE_OFF` canonical action (contract v6
    §4.2 defines `WRITE_OFF` as scrap/loss/theft only). The C12.4
    wrapper that routed sales through `WRITE_OFF` was itself a
    business-rule invention. TASK 5C MUST NOT invent "sale =
    write-off"; a canonical "sale depletion" movement is not in the
    frozen vocabulary yet.

    Until the frozen contract adds a canonical sale-depletion movement
    (future owner decision — out of TASK 5C scope), the legacy sales
    stock mutation path FAILS CLOSED here: no stock is mutated, no
    ledger event is written, no envelope is produced. The caller
    receives `LegacyWriterRetiredError` with the canonical-pending
    pointer so the route can surface HTTP 410 to the UI.

    This closes:
      * the fake `Ctx(org_id)` call site (no stock mutation, no
        Permission Service invocation at all here);
      * the non-atomic sale-row + stock-depletion pair;
      * the `WRITE_OFF` evidence-gate mis-mapping of sale receipts.
    """
    from app.services.warehouse_movements.errors import LegacyWriterRetiredError

    # Signature-level validation remains so callers who adopted the
    # C12.4 shape get a precise error rather than a silent no-op.
    # We bind the kwargs defensively so the message carries what the
    # caller tried; nothing here mutates stock.
    _ctx_present = ctx is not None
    _actor_present = bool(actor_id)
    _sale_ref_present = bool(sale_reference)
    _evidence_present = bool(sale_evidence_file_ids)
    _unused = (_ctx_present, _actor_present, _sale_ref_present,
               _evidence_present, idempotency_key, unit, qty_needed)

    raise LegacyWriterRetiredError(
        "fifo_service.consume_fifo is retired for ordinary sales. "
        "The frozen canonical vocabulary (contract v6 §4.2) defines "
        "WRITE_OFF as scrap/loss/theft only; an ordinary sale is NOT "
        "a write-off. A canonical sale-depletion movement is not in "
        "the frozen contract yet, so this path fails closed. Legacy "
        "sales stock mutation is suspended pending an owner decision "
        "to extend the canonical vocabulary.",
        context={
            "route_id": "fifo_service.consume_fifo",
            "canonical_action_pending": "sale_depletion",
            "redirect_endpoint": "POST /api/warehouse/canonical/movements "
                                 "(when a canonical sale-depletion action "
                                 "ships; see FLOW-009 extension)",
            "attempted_item_id": item_id,
            "attempted_warehouse_id": warehouse_id,
        },
    )


async def get_current_stock(org_id: str, item_id: str, warehouse_id: Optional[str] = None) -> dict:
    tenant = TenantData.for_resolved_org(db, org_id)
    query = {"org_id": org_id, "item_id": item_id, "status": "active", "remaining_qty": {"$gt": 0}}
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    # CODEX C12.10 — no silent cap on canonical/projection reads.
    batches = [row async for row in tenant.warehouse_batches.find(query, {"_id": 0})]

    total_qty = sum(b["remaining_qty"] for b in batches)
    total_value = sum(b["remaining_qty"] * b["unit_cost"] for b in batches)
    avg_cost = round(total_value / total_qty, 4) if total_qty > 0 else 0
    oldest = min((b["received_at"] for b in batches), default=None) if batches else None

    return {
        "total_qty": round(total_qty, 4),
        "weighted_avg_cost": avg_cost,
        "total_value": round(total_value, 2),
        "batches_count": len(batches),
        "oldest_batch_date": oldest,
    }


async def get_stock_value(org_id: str, warehouse_id: str) -> dict:
    tenant = TenantData.for_resolved_org(db, org_id)
    # CODEX C12.10 — no silent cap on canonical/projection reads.
    batches = [row async for row in tenant.warehouse_batches.find(
        {"org_id": org_id, "warehouse_id": warehouse_id, "status": "active", "remaining_qty": {"$gt": 0}},
        {"_id": 0, "remaining_qty": 1, "unit_cost": 1, "item_id": 1},
    )]

    total = round(sum(b["remaining_qty"] * b["unit_cost"] for b in batches), 2)
    items_count = len(set(b["item_id"] for b in batches))

    return {"total_value": total, "items_count": items_count, "batches_count": len(batches)}


async def ensure_indexes(org_id: str = None):
    """Create required indexes for warehouse_batches."""
    await db.warehouse_batches.create_index([("org_id", 1), ("item_id", 1), ("warehouse_id", 1), ("status", 1), ("received_at", 1)])
    await db.warehouse_batches.create_index([("org_id", 1), ("batch_number", 1)], unique=True)
    await db.warehouse_batches.create_index([("org_id", 1), ("supplier_id", 1)])
    await db.warehouse_batches.create_index([("org_id", 1), ("invoice_number", 1)])
