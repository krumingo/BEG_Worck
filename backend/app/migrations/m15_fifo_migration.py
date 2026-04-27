"""
M15 FIFO Migration — Convert flat stock to batch-tracked FIFO model.
Creates opening_balance batches for all items with current_stock > 0.
"""
import asyncio
from datetime import datetime, timezone
import uuid
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from motor.motor_asyncio import AsyncIOMotorClient


async def run_migration(db_url=None, db_name=None):
    client = AsyncIOMotorClient(db_url or os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = client[db_name or os.environ.get("DB_NAME", "test_database")]
    now = datetime.now(timezone.utc).isoformat()

    # Check if already migrated
    setting = await db.settings.find_one({"_id": "fifo_migration"})
    if setting and setting.get("completed_at"):
        print(f"[SKIP] FIFO migration already completed at {setting['completed_at']}")
        return

    orgs = await db.organizations.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(100)
    total_batches = 0

    for org in orgs:
        org_id = org["id"]
        items = await db.items.find(
            {"org_id": org_id, "current_stock": {"$gt": 0}},
            {"_id": 0, "id": 1, "name": 1, "current_stock": 1, "average_cost": 1, "warehouse_id": 1},
        ).to_list(5000)

        for item in items:
            item_id = item["id"]
            warehouse_id = item.get("warehouse_id", "default")
            stock = item.get("current_stock", 0)
            if stock <= 0:
                continue

            # Check if opening batch already exists
            existing = await db.warehouse_batches.find_one(
                {"org_id": org_id, "item_id": item_id, "source_type": "opening_balance"}
            )
            if existing:
                continue

            # Find best cost estimate
            unit_cost = item.get("average_cost", 0) or 0
            if unit_cost == 0:
                last_txn = await db.warehouse_transactions.find_one(
                    {"org_id": org_id, "item_id": item_id, "total_ex_vat": {"$gt": 0}},
                    {"_id": 0, "total_ex_vat": 1, "quantity": 1},
                    sort=[("created_at", -1)],
                )
                if last_txn and last_txn.get("quantity", 0) > 0:
                    unit_cost = round(last_txn["total_ex_vat"] / last_txn["quantity"], 4)

            # Find earliest transaction date
            earliest_txn = await db.warehouse_transactions.find_one(
                {"org_id": org_id, "item_id": item_id},
                {"_id": 0, "created_at": 1},
                sort=[("created_at", 1)],
            )
            received_at = earliest_txn.get("created_at", now) if earliest_txn else now

            batch = {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "item_id": item_id,
                "warehouse_id": warehouse_id,
                "batch_number": f"OPENING-{item_id[:8]}",
                "source_type": "opening_balance",
                "supplier_id": None,
                "invoice_number": None,
                "invoice_date": None,
                "ordered_by": None,
                "initial_qty": round(stock, 4),
                "remaining_qty": round(stock, 4),
                "unit_cost": round(unit_cost, 4),
                "currency": "BGN",
                "received_at": received_at,
                "expires_at": None,
                "status": "active",
                "notes": "Начален остатък при миграция към FIFO",
                "created_at": now,
                "updated_at": now,
            }
            await db.warehouse_batches.insert_one(batch)
            total_batches += 1

        print(f"  [{org.get('name', org_id[:8])}] {len(items)} items → {total_batches} batches")

    # Create indexes
    coll = db.warehouse_batches
    await coll.create_index([("org_id", 1), ("item_id", 1), ("warehouse_id", 1), ("status", 1), ("received_at", 1)])
    try:
        await coll.create_index([("org_id", 1), ("batch_number", 1)], unique=True)
    except Exception:
        pass
    await coll.create_index([("org_id", 1), ("supplier_id", 1)])
    await coll.create_index([("org_id", 1), ("invoice_number", 1)])

    # Mark migration complete
    await db.settings.update_one(
        {"_id": "fifo_migration"},
        {"$set": {"completed_at": now, "total_batches": total_batches}},
        upsert=True,
    )

    print(f"\n[OK] FIFO migration complete: {total_batches} opening batches created")


if __name__ == "__main__":
    asyncio.run(run_migration())
