"""
FIFO Warehouse Service — Batch-based stock management.
All stock operations go through batches ordered by received_at (FIFO).
"""
from datetime import datetime, timezone
from typing import Optional
import uuid
import logging

from app.db import db

logger = logging.getLogger(__name__)


class InsufficientStockError(Exception):
    def __init__(self, item_id: str, warehouse_id: str, requested: float, available: float):
        self.item_id = item_id
        self.warehouse_id = warehouse_id
        self.requested = requested
        self.available = available
        super().__init__(f"Insufficient stock: requested {requested}, available {available}")


async def generate_batch_number(org_id: str) -> str:
    year = datetime.now(timezone.utc).strftime("%Y")
    last = await db.warehouse_batches.find_one(
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
    now = datetime.now(timezone.utc).isoformat()
    if not batch_number:
        batch_number = await generate_batch_number(org_id)

    batch = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "item_id": item_id,
        "warehouse_id": warehouse_id,
        "batch_number": batch_number,
        "source_type": source_type,
        "supplier_id": supplier_id,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "ordered_by": ordered_by,
        "initial_qty": round(qty, 4),
        "remaining_qty": round(qty, 4),
        "unit_cost": round(unit_cost, 4),
        "currency": currency,
        "received_at": received_at or now,
        "expires_at": expires_at,
        "status": "active",
        "notes": notes,
        "created_at": now,
        "updated_at": now,
    }
    await db.warehouse_batches.insert_one(batch)
    clean = {k: v for k, v in batch.items() if k != "_id"}
    return clean


async def consume_fifo(
    org_id: str,
    item_id: str,
    warehouse_id: str,
    qty_needed: float,
) -> list:
    """
    Consume stock in FIFO order (oldest batch first).
    Returns list of { batch_id, batch_number, qty_taken, unit_cost, total_cost }.
    Raises InsufficientStockError if not enough stock.
    """
    batches = await db.warehouse_batches.find(
        {
            "org_id": org_id,
            "item_id": item_id,
            "warehouse_id": warehouse_id,
            "status": "active",
            "remaining_qty": {"$gt": 0},
        },
        {"_id": 0},
    ).sort("received_at", 1).to_list(500)

    available = sum(b["remaining_qty"] for b in batches)
    if available < qty_needed:
        raise InsufficientStockError(item_id, warehouse_id, qty_needed, available)

    now = datetime.now(timezone.utc).isoformat()
    consumption = []
    remaining_need = qty_needed

    for batch in batches:
        if remaining_need <= 0:
            break

        take = min(batch["remaining_qty"], remaining_need)
        new_remaining = round(batch["remaining_qty"] - take, 4)
        new_status = "depleted" if new_remaining <= 0 else "active"

        await db.warehouse_batches.update_one(
            {"id": batch["id"]},
            {"$set": {"remaining_qty": new_remaining, "status": new_status, "updated_at": now}},
        )

        consumption.append({
            "batch_id": batch["id"],
            "batch_number": batch["batch_number"],
            "qty_taken": round(take, 4),
            "unit_cost": batch["unit_cost"],
            "total_cost": round(take * batch["unit_cost"], 2),
        })
        remaining_need = round(remaining_need - take, 4)

    return consumption


async def get_current_stock(org_id: str, item_id: str, warehouse_id: Optional[str] = None) -> dict:
    query = {"org_id": org_id, "item_id": item_id, "status": "active", "remaining_qty": {"$gt": 0}}
    if warehouse_id:
        query["warehouse_id"] = warehouse_id

    batches = await db.warehouse_batches.find(query, {"_id": 0}).to_list(500)

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
    batches = await db.warehouse_batches.find(
        {"org_id": org_id, "warehouse_id": warehouse_id, "status": "active", "remaining_qty": {"$gt": 0}},
        {"_id": 0, "remaining_qty": 1, "unit_cost": 1, "item_id": 1},
    ).to_list(5000)

    total = round(sum(b["remaining_qty"] * b["unit_cost"] for b in batches), 2)
    items_count = len(set(b["item_id"] for b in batches))

    return {"total_value": total, "items_count": items_count, "batches_count": len(batches)}


async def ensure_indexes(org_id: str = None):
    """Create required indexes for warehouse_batches."""
    coll = db.warehouse_batches
    await coll.create_index([("org_id", 1), ("item_id", 1), ("warehouse_id", 1), ("status", 1), ("received_at", 1)])
    await coll.create_index([("org_id", 1), ("batch_number", 1)], unique=True)
    await coll.create_index([("org_id", 1), ("supplier_id", 1)])
    await coll.create_index([("org_id", 1), ("invoice_number", 1)])
