"""CLAUDE AUDIT probe — #72 × #56 merge recipe: record_event(session=...) inside run_in_transaction does NOT
retry a (tenant_id, sequence) collision; the HANDOFF says "the transaction is retried as a whole".
session.with_transaction only retries errors labelled TransientTransactionError. Run 20 transactional +
20 plain record_event concurrently on ONE tenant: how many transactional appends fail, with what?
    cd <merged #72+#56>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true&replicaSet=rs0' python <this>
"""
import asyncio, os, uuid, collections
from motor.motor_asyncio import AsyncIOMotorClient
from app.audit.indexes import ensure_audit_indexes
from app.audit.envelope import build_event, ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS
from app.audit.store import record_event, verify_chain
from app.services.auth_tx import run_in_transaction

def ev(i):
    return build_event(tenant_id="tx", action="probe.event", source_flow="FLOW-040", entity_type="probe",
                       entity_id="e%d" % i, actor_type=ACTOR_HUMAN, actor_id="u",
                       retention_class=RETENTION_R1_CRITICAL_BUSINESS)

async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); db = c["w004tx_" + uuid.uuid4().hex[:8]]
    await ensure_audit_indexes(db)
    await db["audit_events"].insert_one({"probe": "warm"}); await db["audit_events"].delete_many({"probe": "warm"})
    async def tx(i):
        async def body(session):
            return await record_event(db, ev(i), session=session)
        return await run_in_transaction(db, body)
    for rnd in range(3):
        jobs = [tx(1000 * rnd + i) for i in range(20)] + [record_event(db, ev(1000 * rnd + 100 + i)) for i in range(20)]
        res = await asyncio.gather(*jobs, return_exceptions=True)
        fails = collections.Counter(type(r).__name__ for r in res[:20] if isinstance(r, Exception))
        pfails = collections.Counter(type(r).__name__ for r in res[20:] if isinstance(r, Exception))
        print("round %d: transactional failures %s, plain failures %s" % (rnd, dict(fails), dict(pfails)))
    evs = await db["audit_events"].find({"tenant_id": "tx"}, {"_id": 0}).sort("sequence", 1).to_list(None)
    print("stored", len(evs), "verify_chain", verify_chain(evs))
    await c.drop_database(db.name)

asyncio.run(main())
