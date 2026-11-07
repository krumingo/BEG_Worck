"""CLAUDE AUDIT probe — #72 FG-57 (record_event refuses an unprotected chain). Real Mongo RS.
 G1 fresh DB, NO indexes, 30 concurrent record_event → index created lazily, 30 stored, seq 1..30, chain ok.
 G2 non-unique (tenant_id, sequence) index present → AuditChainUnprotected, 0 appended, index kept.
 G3 existing duplicate sequences → AuditChainUnprotected, 0 appended, rows kept.
 G4 begin_idempotent on a DB without the idempotency index (is there an equivalent guard?) → 6 concurrent winners?
"""
import asyncio, os, uuid
from motor.motor_asyncio import AsyncIOMotorClient
from app.audit.envelope import build_event, ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS
from app.audit import store
from app.audit.idempotency import begin_idempotent, IDEMPOTENCY_STARTED

def ev(t, i):
    return build_event(tenant_id=t, action="probe.event", source_flow="FLOW-040", entity_type="p", entity_id="e%d" % i,
                       actor_type=ACTOR_HUMAN, actor_id="u", retention_class=RETENTION_R1_CRITICAL_BUSINESS)

async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); sfx = uuid.uuid4().hex[:8]; F = []
    db = c["fg57a_" + sfx]
    res = await asyncio.gather(*[store.record_event(db, ev("t", i)) for i in range(30)], return_exceptions=True)
    errs = [type(r).__name__ for r in res if isinstance(r, Exception)]
    evs = await db.audit_events.find({}, {"_id": 0}).sort("sequence", 1).to_list(None)
    seqs = [e["sequence"] for e in evs]
    ok = not errs and seqs == list(range(1, 31)) and store.verify_chain(evs)[0]
    print(("ok   " if ok else "FAIL ") + "G1 no index, 30 concurrent → errors %s, stored %d, seq ok %s, chain %s" % (errs[:2], len(evs), seqs == list(range(1, 31)), store.verify_chain(evs)))
    if not ok: F.append("G1")
    db2 = c["fg57b_" + sfx]; await db2.audit_events.create_index([("tenant_id", 1), ("sequence", 1)])
    try:
        await store.record_event(db2, ev("t", 1)); r2 = "appended"
    except store.AuditChainUnprotected as e:
        r2 = "AuditChainUnprotected"
    n2 = await db2.audit_events.count_documents({})
    ok = r2 == "AuditChainUnprotected" and n2 == 0
    print(("ok   " if ok else "FAIL ") + "G2 non-unique index → %s, appended %d" % (r2, n2)); F += [] if ok else ["G2"]
    db3 = c["fg57c_" + sfx]; await db3.audit_events.insert_many([{"tenant_id": "t", "sequence": 1, "x": 1}, {"tenant_id": "t", "sequence": 1, "x": 2}])
    try:
        await store.record_event(db3, ev("t", 1)); r3 = "appended"
    except store.AuditChainUnprotected:
        r3 = "AuditChainUnprotected"
    n3 = await db3.audit_events.count_documents({})
    ok = r3 == "AuditChainUnprotected" and n3 == 2
    print(("ok   " if ok else "FAIL ") + "G3 existing fork → %s, rows %d (kept 2)" % (r3, n3)); F += [] if ok else ["G3"]
    db4 = c["fg57d_" + sfx]
    res = await asyncio.gather(*[begin_idempotent(db4, tenant_id="t", key="k", action="a", request_fingerprint="f") for _ in range(6)], return_exceptions=True)
    started = sum(1 for r in res if isinstance(r, dict) and r.get("status") == IDEMPOTENCY_STARTED)
    print("info G4 begin_idempotent with no index (no startup) → STARTED %d of 6" % started)
    for d in (db, db2, db3, db4): await c.drop_database(d.name)
    print("FAILS:", F or "none")

asyncio.run(main())
