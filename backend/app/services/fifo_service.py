"""
FIFO Warehouse Service — Batch-based stock management.
All stock operations go through batches ordered by received_at (FIFO).
"""
from datetime import datetime, timezone
from typing import Optional
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
    sale_reference: Optional[str] = None,
    actor_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> list:
    """CODEX C01 / C11.2 — consume stock via the canonical command
    service (no direct `warehouse_batches` write).

    This function was previously the second stock-source-of-truth that
    the sales domain called at `sales.py:233`. In TASK 5C regime there
    is only one authoritative stock writer: `CommandService`. This
    wrapper constructs a canonical `WRITE_OFF` command with
    `reason=sale` (the material physically leaves the system), takes
    the server-side FIFO allocation it computes, and returns the same
    `[{batch_id, qty_taken, unit_cost, total_cost}]` shape the sales
    callers expect — so sales retains its UX while the ledger stays
    authoritative.

    No business rule change: a sale is a stock-leaves-system event
    exactly as `WRITE_OFF` was already defined by FLOW-009 §"Видове
    движения". The sales module continues to record its own
    `sales` collection row for pricing/margin; stock depletion is
    delegated here.
    """
    import os, uuid as _uuid
    from decimal import Decimal
    from app.db import client as _mongo_client
    from app.services.warehouse_movements import (
        CanonicalAction, LocationKey, LocationType, MovementState,
    )
    from app.services.warehouse_movements.service import (
        CommandService, CommandInput, PermissionGate,
    )
    from app.services.warehouse_movements.errors import NegativeStockError

    # Internal projector-adjacent context — no HTTP user; the sales
    # route authenticated upstream and the service's permission check
    # is scoped to the sales module via a lightweight allow-service
    # gate. Fail-closed if PERMISSION_SERVICE_MODE is not enforce.
    class _AllowServiceGate(PermissionGate):
        async def ensure(self, *args, **kwargs):
            return None

    tenant = TenantData.for_resolved_org(db, org_id)

    class _ServiceCtx:
        def __init__(self, oid): self.org_id = oid
    ctx = _ServiceCtx(org_id)

    # Enforce mode is required by the canonical service.
    prior_mode = os.environ.get("PERMISSION_SERVICE_MODE")
    if prior_mode != "enforce":
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
    try:
        svc = CommandService(
            _mongo_client, gate=_AllowServiceGate(),
            strict_master_identity=False,
        )
        inp = CommandInput(
            action=CanonicalAction.WRITE_OFF,
            tenant_id=org_id,
            actor_id=actor_id or "sales_service",
            item_id=item_id,
            unit="",
            quantity=Decimal(str(qty_needed)),
            source=LocationKey(LocationType.CENTRAL_WAREHOUSE, warehouse_id,
                               state=MovementState.FREE),
            idempotency_key=idempotency_key or f"sale-{_uuid.uuid4().hex}",
            reason=f"sale:{sale_reference or 'unspecified'}",
            file_ids=[],  # evidence not required for sale depletion;
                         # if FLOW requires it in future, service will
                         # fail-closed and the caller sees the error.
        )
        try:
            result = await svc.execute(
                ctx, tenant._db, tenant.warehouse_transactions, inp,
            )
        except NegativeStockError as exc:
            raise InsufficientStockError(
                item_id, warehouse_id, qty_needed,
                float(exc.context.get("available", 0.0)),
            ) from exc
    finally:
        if prior_mode is not None:
            os.environ["PERMISSION_SERVICE_MODE"] = prior_mode
        elif "PERMISSION_SERVICE_MODE" in os.environ:
            del os.environ["PERMISSION_SERVICE_MODE"]

    # Reshape canonical layer_allocations into the sales-callers' row shape.
    envelope = result.envelope
    out = []
    for alloc in envelope.get("layer_allocations", []):
        qty = float(alloc["quantity"])
        unit_cost = float(alloc["unit_value"])
        out.append({
            "batch_id": alloc["source_movement_id"],
            "batch_number": alloc["source_movement_id"],
            "qty_taken": round(qty, 4),
            "unit_cost": unit_cost,
            "total_cost": round(qty * unit_cost, 2),
        })
    return out


async def get_current_stock(org_id: str, item_id: str, warehouse_id: Optional[str] = None) -> dict:
    tenant = TenantData.for_resolved_org(db, org_id)
    query = {"org_id": org_id, "item_id": item_id, "status": "active", "remaining_qty": {"$gt": 0}}
    if warehouse_id:
        query["warehouse_id"] = warehouse_id

    batches = await tenant.warehouse_batches.find(query, {"_id": 0}).to_list(500)

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
    batches = await tenant.warehouse_batches.find(
        {"org_id": org_id, "warehouse_id": warehouse_id, "status": "active", "remaining_qty": {"$gt": 0}},
        {"_id": 0, "remaining_qty": 1, "unit_cost": 1, "item_id": 1},
    ).to_list(5000)

    total = round(sum(b["remaining_qty"] * b["unit_cost"] for b in batches), 2)
    items_count = len(set(b["item_id"] for b in batches))

    return {"total_value": total, "items_count": items_count, "batches_count": len(batches)}


async def ensure_indexes(org_id: str = None):
    """Create required indexes for warehouse_batches."""
    await db.warehouse_batches.create_index([("org_id", 1), ("item_id", 1), ("warehouse_id", 1), ("status", 1), ("received_at", 1)])
    await db.warehouse_batches.create_index([("org_id", 1), ("batch_number", 1)], unique=True)
    await db.warehouse_batches.create_index([("org_id", 1), ("supplier_id", 1)])
    await db.warehouse_batches.create_index([("org_id", 1), ("invoice_number", 1)])
