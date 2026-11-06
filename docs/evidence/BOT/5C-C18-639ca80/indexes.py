import asyncio, sys
sys.path.insert(0, '.')
from motor.motor_asyncio import AsyncIOMotorClient
import os
from app.services.warehouse_movements.indexes import ensure_required_indexes
async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    for name in ("bot_op", "begwork_tenant_bot-firm-b"):
        print(name, len(await ensure_required_indexes(c[name])), "created")
asyncio.run(main())
