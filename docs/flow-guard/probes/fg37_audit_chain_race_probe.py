"""FLOW GUARD probe FG-37 (FLOW-040 §8 append-only hash chain on main).
From backend/: PYTHONPATH=. python <this file>
Needs a MongoDB replica set at 127.0.0.1:27019 (rs0). Uses a throwaway database fg37_*, dropped at the end.
Fires N concurrent record_event() calls for one tenant and checks the chain."""
import asyncio, json, uuid
from motor.motor_asyncio import AsyncIOMotorClient
from app.audit import envelope, store

URL = "mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true"
N = 20

async def main():
    cl = AsyncIOMotorClient(URL)
    db = cl["fg37_" + uuid.uuid4().hex[:6]]
    tenant = "t-" + uuid.uuid4().hex[:6]
    import inspect
    params = inspect.signature(envelope.build_event).parameters
    def ev(i):
        kw = dict(tenant_id=tenant, actor_type="human", actor_id="u1", action="probe.write",
                  source_flow="FLOW-040", entity_type="probe", entity_id=str(i),
                  retention_class=sorted(envelope.RETENTION_CLASSES)[0], result="success")
        return envelope.build_event(**{k: v for k, v in kw.items() if k in params})
    await asyncio.gather(*(store.record_event(db, ev(i)) for i in range(N)))
    rows = await db[store.AUDIT_COLLECTION].find({"tenant_id": tenant}, {"_id": 0}).sort("sequence", 1).to_list(None)
    seqs = [r["sequence"] for r in rows]
    ok, err = store.verify_chain(rows)
    print("FGRESULT " + json.dumps({"events": len(rows), "distinct_sequences": len(set(seqs)),
                                    "max_sequence": max(seqs), "verify_chain_ok": ok, "error": err}))
    await cl.drop_database(db.name)

asyncio.run(main())
