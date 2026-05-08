"""
FIFO Service Tests — standalone runner (no pytest-asyncio issues).
Run: cd /app/backend && python tests/test_fifo.py
"""
import asyncio
import uuid
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from motor.motor_asyncio import AsyncIOMotorClient

TEST_DB = f"test_fifo_{uuid.uuid4().hex[:6]}"
TEST_ORG = "test-org-fifo"
TEST_ORG2 = "test-org-fifo-2"


async def run_all():
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = client[TEST_DB]

    # Monkey-patch
    import app.services.fifo_service as svc
    svc.db = db

    from app.services.fifo_service import add_batch, consume_fifo, get_current_stock, get_stock_value, InsufficientStockError

    passed = 0
    failed = 0

    async def clean():
        await db.warehouse_batches.delete_many({})

    async def make(org=TEST_ORG, item="ITEM-1", wh="WH-1", qty=100, cost=10.0, received="2026-01-01T00:00:00"):
        return await add_batch(org, item, wh, qty, cost, batch_number=f"B-{uuid.uuid4().hex[:6]}", received_at=received)

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  [+] {name}")
            passed += 1
        else:
            print(f"  [X] {name} — {detail}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"  FIFO Tests (DB: {TEST_DB})")
    print(f"{'='*50}")

    # Test 1
    await clean()
    b = await add_batch(TEST_ORG, "ITEM-1", "WH-1", 50, 12.5)
    check("01 Create batch", b["initial_qty"] == 50 and b["status"] == "active")

    # Test 2
    await clean()
    await make(qty=100, cost=10.0)
    rows = await consume_fifo(TEST_ORG, "ITEM-1", "WH-1", 30)
    check("02 FIFO single batch", len(rows) == 1 and rows[0]["qty_taken"] == 30)

    # Test 3
    await clean()
    await make(qty=40, cost=10.0, received="2026-01-01T00:00:00")
    await make(qty=60, cost=15.0, received="2026-01-02T00:00:00")
    rows = await consume_fifo(TEST_ORG, "ITEM-1", "WH-1", 70)
    check("03 FIFO split", len(rows) == 2 and rows[0]["qty_taken"] == 40 and rows[1]["qty_taken"] == 30)

    # Test 4
    await clean()
    await make(qty=20, cost=10.0)
    try:
        await consume_fifo(TEST_ORG, "ITEM-1", "WH-1", 50)
        check("04 Insufficient error", False, "no exception raised")
    except InsufficientStockError:
        check("04 Insufficient error", True)

    # Test 5
    await clean()
    b = await make(qty=25, cost=10.0)
    await consume_fifo(TEST_ORG, "ITEM-1", "WH-1", 25)
    updated = await db.warehouse_batches.find_one({"id": b["id"]}, {"_id": 0})
    check("05 Depleted status", updated["remaining_qty"] == 0 and updated["status"] == "depleted")

    # Test 6
    await clean()
    await make(qty=50, cost=10.0, received="2026-01-01T00:00:00")
    await make(qty=30, cost=20.0, received="2026-01-02T00:00:00")
    s = await get_current_stock(TEST_ORG, "ITEM-1", "WH-1")
    check("06 Stock summary", s["total_qty"] == 80 and s["batches_count"] == 2)

    # Test 7
    await clean()
    await make(qty=60, cost=10.0, received="2026-01-01T00:00:00")
    await make(qty=40, cost=20.0, received="2026-01-02T00:00:00")
    s = await get_current_stock(TEST_ORG, "ITEM-1", "WH-1")
    check("07 Weighted avg cost", s["weighted_avg_cost"] == 14.0, f"got {s['weighted_avg_cost']}")

    # Test 8
    await clean()
    b = await add_batch(TEST_ORG, "MIG-1", "WH-1", 200, 5.0, source_type="opening_balance", batch_number="OPENING-MIG1")
    check("08 Opening balance", b["source_type"] == "opening_balance")

    # Test 9
    await clean()
    b = await add_batch(TEST_ORG, "ITEM-1", "WH-1", 100, 8.0, source_type="purchase", supplier_id="SUP-1", invoice_number="INV-001")
    check("09 Purchase batch", b["supplier_id"] == "SUP-1" and b["invoice_number"] == "INV-001")

    # Test 10
    await clean()
    b1 = await make(qty=50, cost=10.0, received="2026-01-01T00:00:00")
    await make(qty=50, cost=20.0, received="2026-01-02T00:00:00")
    await db.warehouse_batches.update_one({"id": b1["id"]}, {"$set": {"status": "blocked"}})
    rows = await consume_fifo(TEST_ORG, "ITEM-1", "WH-1", 30)
    check("10 Blocked excluded", len(rows) == 1 and rows[0]["unit_cost"] == 20.0)

    # Test 11
    await clean()
    await make(wh="WH-A", qty=50, cost=10.0)
    await make(wh="WH-B", qty=30, cost=20.0)
    a = await get_current_stock(TEST_ORG, "ITEM-1", "WH-A")
    b = await get_current_stock(TEST_ORG, "ITEM-1", "WH-B")
    check("11 Multi-warehouse", a["total_qty"] == 50 and b["total_qty"] == 30)

    # Test 12
    await clean()
    await make(org=TEST_ORG, qty=100, cost=10.0)
    await make(org=TEST_ORG2, qty=200, cost=5.0)
    s1 = await get_current_stock(TEST_ORG, "ITEM-1", "WH-1")
    s2 = await get_current_stock(TEST_ORG2, "ITEM-1", "WH-1")
    check("12 Multi-tenant", s1["total_qty"] == 100 and s2["total_qty"] == 200)

    print(f"{'='*50}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'='*50}\n")

    await client.drop_database(TEST_DB)
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)
