"""CLAUDE AUDIT probe — #72 cb5d061 (F-72-01): no operation key, tenant id or reservation id in
any exception message, chained traceback, report or log line. Sentinels are planted as the
key / tenant / reservation id; every path is driven for real on Mongo RS:
  L1 startup  ensure_audit_indexes_for_installation on a db whose audit_idempotency holds
              duplicate (tenant_id, action, key) rows  -> AuditIndexDuplicates
  L2 lazy guard require_unique_index(create=True) on the same duplicates
  L3 lazy guard require_unique_index(create=False) (index absent, inside a tx)
  L4 begin_idempotent: same key, different payload -> IdempotencyConflict
  L5 record_event contention (CHAIN_APPEND_MAX_ATTEMPTS forced to 0)
  L6 the real ErrorHandlerMiddleware: a route raising each of the above; caplog + response
  L7 begin_idempotent on a db with NO unique index -> IdempotencyUnprotected (fail-closed)
    cd <tree>/backend && PYTHONPATH=. MONGO_URL=... python <this>
"""
import asyncio, io, logging, os, traceback, uuid
from motor.motor_asyncio import AsyncIOMotorClient

SK, ST, SR = "SENTINELKEY" + uuid.uuid4().hex[:6], "SENTINELTEN" + uuid.uuid4().hex[:6], "SENTINELRES" + uuid.uuid4().hex[:6]
SENT = (SK, ST, SR, "SENTINEL")
buf = io.StringIO(); h = logging.StreamHandler(buf); h.setLevel(logging.DEBUG)
logging.getLogger().addHandler(h); logging.getLogger().setLevel(logging.DEBUG)
F, OUT = [], []


def leak(label, *texts):
    blob = "\n".join(str(t) for t in texts)
    hit = [s for s in SENT if s in blob]
    OUT.append("%s: %s" % (label, "LEAK %s" % hit if hit else "clean"))
    if hit:
        F.append("%s leaks %s" % (label, hit))


def tb(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


async def main():
    from app.audit import indexes as ix, idempotency as idem, store
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c["f7201_" + uuid.uuid4().hex[:8]]
    # duplicates in the key registry, carrying the sentinels
    for _ in range(2):
        await db["audit_idempotency"].insert_one({"id": SR, "tenant_id": ST, "action": "probe.act", "key": SK})
    # L1 — the startup path
    try:
        await ix.ensure_audit_indexes(db)
        F.append("L1 no refusal")
    except Exception as exc:  # noqa: BLE001
        leak("L1 startup %s" % type(exc).__name__, str(exc), tb(exc), getattr(exc, "report", ""), repr(exc.__cause__), repr(exc.__context__) if not exc.__suppress_context__ else "")
    # L2 / L3 — the lazy guards
    for label, create in (("L2 lazy create", True), ("L3 lazy no-create", False)):
        ix._unique_index_verified.clear()
        try:
            await ix.require_unique_index(db, "audit_idempotency", [("tenant_id", 1), ("action", 1), ("key", 1)],
                                          idem.IdempotencyUnprotected, create=create)
            F.append("%s no refusal" % label)
        except Exception as exc:  # noqa: BLE001
            leak("%s %s" % (label, type(exc).__name__), str(exc), tb(exc),
                 repr(exc.__cause__), "" if exc.__suppress_context__ else repr(exc.__context__))
    # L4 — conflict on a clean, indexed db
    db2 = c["f7201b_" + uuid.uuid4().hex[:8]]
    await ix.ensure_audit_indexes(db2)
    await idem.begin_idempotent(db2, tenant_id=ST, key=SK, action="probe.act", request_fingerprint="fp1")
    try:
        await idem.begin_idempotent(db2, tenant_id=ST, key=SK, action="probe.act", request_fingerprint="fp2")
        F.append("L4 no conflict")
    except idem.IdempotencyConflict as exc:
        leak("L4 conflict", str(exc), tb(exc), "" if exc.__suppress_context__ else repr(exc.__context__))
    # L5 — chain contention
    from app.audit.envelope import build_event, ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS
    old = store.CHAIN_APPEND_MAX_ATTEMPTS
    store.CHAIN_APPEND_MAX_ATTEMPTS = 0
    ev = build_event(tenant_id=ST, action="probe.event", source_flow="FLOW-040", entity_type="probe",
                     entity_id=SR, actor_type=ACTOR_HUMAN, actor_id="u", retention_class=RETENTION_R1_CRITICAL_BUSINESS)
    try:
        await store.record_event(db2, ev)
        OUT.append("L5: no contention raised (loop shape) — skipped")
    except Exception as exc:  # noqa: BLE001
        leak("L5 %s" % type(exc).__name__, str(exc), tb(exc))
    store.CHAIN_APPEND_MAX_ATTEMPTS = old
    # L7 — fail-closed without the index
    db3 = c["f7201c_" + uuid.uuid4().hex[:8]]
    await db3["audit_idempotency"].insert_one({"warm": 1}); await db3["audit_idempotency"].delete_many({})
    await db3["audit_idempotency"].insert_one({"id": SR, "tenant_id": ST, "action": "probe.act", "key": SK})
    await db3["audit_idempotency"].insert_one({"id": SR, "tenant_id": ST, "action": "probe.act", "key": SK})
    ix._unique_index_verified.clear()
    try:
        await idem.begin_idempotent(db3, tenant_id=ST, key=SK + "x", action="probe.act", request_fingerprint="fp")
        F.append("L7 NOT fail-closed: wrote without a unique index")
    except Exception as exc:  # noqa: BLE001
        OUT.append("L7 fail-closed: %s" % type(exc).__name__)
        leak("L7 %s" % type(exc).__name__, str(exc), tb(exc))
    return c, db, db2, db3


async def middleware(c, db, db2):
    from fastapi import FastAPI
    import httpx
    from app.middleware.error_handler import ErrorHandlerMiddleware
    from app.audit import indexes as ix, idempotency as idem
    app = FastAPI(); app.add_middleware(ErrorHandlerMiddleware)

    @app.post("/dup")
    async def dup():
        await ix.ensure_audit_indexes(db)

    @app.post("/lazy")
    async def lazy():
        ix._unique_index_verified.clear()
        await ix.require_unique_index(db, "audit_idempotency", [("tenant_id", 1), ("action", 1), ("key", 1)],
                                      idem.IdempotencyUnprotected, create=True)

    @app.post("/conflict")
    async def conflict():
        await idem.begin_idempotent(db2, tenant_id=ST, key=SK, action="probe.act", request_fingerprint="fp3")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as ac:
        for path in ("/dup", "/lazy", "/conflict"):
            n = len(buf.getvalue())
            r = await ac.post(path)
            leak("L6 middleware %s → %s" % (path, r.status_code), r.text, buf.getvalue()[n:])


async def run():
    c, db, db2, db3 = await main()
    await middleware(c, db, db2)
    leak("L* whole log", buf.getvalue())
    for d in (db, db2, db3):
        await c.drop_database(d.name)

asyncio.run(run())
print("\n".join(OUT)); print("FAILS:", F or "none")
