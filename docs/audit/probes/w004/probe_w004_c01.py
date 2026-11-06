"""CLAUDE AUDIT probe — #72 W0-04-C01. Real Mongo RS, fresh databases with NO indexes.
 I1 real app startup (server.app startup handlers NOT cleared) on an empty op DB + a registry naming a
    second tenant DB → both DBs carry the unique indexes.
 I2 6 concurrent begin_idempotent with ONE key → exactly 1 STARTED (others DUPLICATE/conflict-free).
 I3 50 concurrent record_event → 50 stored, sequences 1..50 unique, verify_chain true.
 I4 a conflicting existing index (non-unique on audit_idempotency.id) → AuditIndexConflict, index kept.
 I5 existing duplicate idempotency rows → AuditIndexDuplicates, both rows still there.
 I6 onboarding (POST /api/billing/signup path → onboard_tenant) on a DB without indexes → indexes exist.
    cd <wt72>/backend && PYTHONPATH=. MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' python <this>
"""
import asyncio, os, sys, uuid
sfx = uuid.uuid4().hex[:8]
OP, SYS, T2 = "w004op_" + sfx, "w004sys_" + sfx, "w004t2_" + sfx
os.environ.update(DB_NAME=OP, BEG_SYSTEM_DB=SYS, ENV="test", JWT_SECRET="probe-" + sfx, PERMISSION_SERVICE_MODE="off")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa
F = []
def check(c, label):
    print(("ok   " if c else "FAIL ") + label)
    if not c: F.append(label)

def uniq_keys(info):
    return sorted(tuple(k for k, _ in v["key"]) for v in info.values() if v.get("unique"))

async def main_async(client):
    from app.audit.idempotency import begin_idempotent, IDEMPOTENCY_STARTED
    from app.audit.indexes import ensure_audit_indexes, AuditIndexConflict, AuditIndexDuplicates
    from app.audit.envelope import build_event, ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS
    from app.audit.store import record_event, verify_chain
    import inspect
    # I2
    db = client["w004i2_" + sfx]
    await ensure_audit_indexes(db)
    res = await asyncio.gather(*[begin_idempotent(db, tenant_id="t", key="k1", action="a", request_fingerprint="f")
                                 for _ in range(6)], return_exceptions=True)
    started = sum(1 for r in res if isinstance(r, dict) and r.get("status") == IDEMPOTENCY_STARTED)
    check(started == 1, "I2 6 concurrent begin_idempotent, one key → STARTED %d (statuses %s)" % (
        started, sorted(str(r.get("status") if isinstance(r, dict) else type(r).__name__) for r in res)))
    # I3
    sig = inspect.signature(build_event)
    def ev(i):
        kw = dict(tenant_id="t3", action="probe.event", source_flow="FLOW-040", entity_type="probe", entity_id="e%d" % i,
                  actor_type=ACTOR_HUMAN, actor_id="u", retention_class=RETENTION_R1_CRITICAL_BUSINESS)
        kw = {k: v for k, v in kw.items() if k in sig.parameters}
        return build_event(**kw)
    out = await asyncio.gather(*[record_event(db, ev(i)) for i in range(50)], return_exceptions=True)
    errs = [type(o).__name__ for o in out if isinstance(o, Exception)]
    n = await db["audit_events"].count_documents({"tenant_id": "t3"})
    seqs = await db["audit_events"].distinct("sequence", {"tenant_id": "t3"})
    vc = verify_chain(await db["audit_events"].find({"tenant_id": "t3"}, {"_id": 0}).sort("sequence", 1).to_list(None))
    vc = await vc if inspect.isawaitable(vc) else vc
    check(not errs and n == 50 and len(seqs) == 50 and min(seqs) == 1 and max(seqs) == 50,
          "I3 50 concurrent record_event → stored %d, distinct seq %d, errors %s, verify_chain %s" % (n, len(seqs), errs[:3], vc))
    # I4
    db4 = client["w004i4_" + sfx]
    await db4["audit_idempotency"].create_index("id")       # non-unique, same keys
    try:
        await ensure_audit_indexes(db4); check(False, "I4 conflicting index accepted silently")
    except AuditIndexConflict as e:
        info = await db4["audit_idempotency"].index_information()
        check("id_1" in info and not info["id_1"].get("unique"), "I4 conflict → AuditIndexConflict, index kept: %s" % str(e)[:90])
    # I5
    db5 = client["w004i5_" + sfx]
    await db5["audit_idempotency"].insert_many([{"id": "dup", "tenant_id": "t", "action": "a", "key": "k"},
                                                {"id": "dup", "tenant_id": "t", "action": "a", "key": "k"}])
    try:
        await ensure_audit_indexes(db5); check(False, "I5 duplicates accepted silently")
    except AuditIndexDuplicates as e:
        check(await db5["audit_idempotency"].count_documents({"id": "dup"}) == 2, "I5 duplicates → AuditIndexDuplicates, rows kept: %s" % str(e)[:80])
    for name in ("w004i2_", "w004i4_", "w004i5_"):
        await client.drop_database(name + sfx)

if __name__ == "__main__":
    import pymongo
    sync = pymongo.MongoClient(os.environ["MONGO_URL"])
    sync[SYS]["tenant_registry"].insert_one({"id": "t2", "database_name": T2, "status": "active"})
    import server  # noqa
    from fastapi.testclient import TestClient
    with TestClient(server.app, raise_server_exceptions=False) as tc:     # startup handlers RUN
        for name in (OP, T2):
            keys = uniq_keys(sync[name]["audit_idempotency"].index_information()) + uniq_keys(sync[name]["audit_events"].index_information())
            check(("id",) in keys and ("tenant_id", "action", "key") in keys and ("tenant_id", "sequence") in keys and ("event_id",) in keys,
                  "I1 startup created unique indexes in %s: %s" % ("op" if name == OP else "registry tenant DB", keys))
        c = tc.portal.call(lambda: AsyncIOMotorClient(os.environ["MONGO_URL"]))
        tc.portal.call(lambda: main_async(c))
        # I6: onboarding on a database whose indexes were dropped
        sync[OP]["audit_idempotency"].drop_indexes(); sync[OP]["audit_events"].drop_indexes()
        r = tc.post("/api/billing/signup", json={"org_name": "Probe Co", "owner_email": "o-%s@probe.example" % sfx,
                                                 "owner_name": "Owner", "password": "Probe-Pass-2026!x", "first_name": "O", "last_name": "P"})
        keys = uniq_keys(sync[OP]["audit_idempotency"].index_information())
        check(r.status_code in (200, 201) and ("id",) in keys, "I6 signup/onboarding → %s, idempotency unique keys %s (%s)" % (r.status_code, keys, r.text[:120] if r.status_code >= 300 else ""))
    for name in (OP, SYS, T2):
        sync.drop_database(name)
    print("FAILS:", F or "none")
