"""W0-04-C01 F-69-01 probe: a FAILED key retaken by 6 concurrent begin_idempotent calls, 10 rounds.
Exactly one STARTED per round; the others IN_PROGRESS (or DUPLICATE once the winner is in).
    cd <wt72>/backend && PYTHONPATH=. MONGO_URL=... python <this>"""
import asyncio, os, uuid, collections
from motor.motor_asyncio import AsyncIOMotorClient
from app.audit.indexes import ensure_audit_indexes
from app.audit.idempotency import begin_idempotent, fail_idempotent

async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); db = c["retake_" + uuid.uuid4().hex[:8]]
    await ensure_audit_indexes(db)
    bad = 0
    for rnd in range(10):
        key = "k%d" % rnd
        await begin_idempotent(db, tenant_id="t", key=key, action="a", request_fingerprint="fp")
        await fail_idempotent(db, tenant_id="t", key=key, action="a", error_code="x")
        rs = await asyncio.gather(*[begin_idempotent(db, tenant_id="t", key=key, action="a", request_fingerprint="fp")
                                    for _ in range(6)])
        cnt = collections.Counter(r["status"] for r in rs)
        print("round", rnd, dict(cnt))
        bad += cnt.get("started", 0) != 1
    await c.drop_database(db.name)
    print("FAILS", bad or "none")
asyncio.run(main())
