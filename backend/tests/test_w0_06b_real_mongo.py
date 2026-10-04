"""
W0-06B — the real-MongoDB gate: entry-gate findings + provider/onboarding/integrity.

Skipped unless ``W0_06B_REAL_MONGO_URL`` (or ``W0_06A_REAL_MONGO_URL`` /
``W0_03_REAL_MONGO_URL``) names a plain LOCAL server::

    W0_06B_REAL_MONGO_URL=mongodb://127.0.0.1:27017 \\
        pytest tests/test_w0_06b_real_mongo.py -v --noconftest

The URL must pass the same local-only guard the W0-03C bootstrap uses (no
Atlas, no NAS, no ``mongodb+srv``). Each test works in its OWN database
``w006b_realmongo_<random>`` (operational) plus ``w006b_realsys_<random>``
(Tenant Registry stand-in) and drops exactly those afterwards. Nothing reads
``.env`` or a production value; every provider is a disposable local fake.

Required skips: 0. Every test runs when the URL is given.
"""
import asyncio
import hashlib
import os
import uuid

import pytest

from app.audit import store
from app.audit.envelope import RETENTION_R2_PROJECT_OPERATIONAL, build_event
from app.files import models as m
from app.files.providers.base import DeleteReceipt, IntegrityVerdict
from app.files.registry import (
    ON_DUPLICATE_NEW_FILE,
    STATUS_DUPLICATE,
    FileRegistry,
    RelationTargetNotFound,
)
from app.tenancy.data_access import TenantData

REAL_URL = (os.environ.get("W0_06B_REAL_MONGO_URL") or os.environ.get("W0_06A_REAL_MONGO_URL")
            or os.environ.get("W0_03_REAL_MONGO_URL", ""))
DB_PREFIX = "w006b_realmongo_"
SYS_PREFIX = "w006b_realsys_"

A, B = "BEG", "TCB"
ACTOR = "user-1"
PROJECT = "P-SHARED"
ONLY_IN_B = "P-ONLY-B"


def _refusal():
    if not REAL_URL:
        return "W0_06B_REAL_MONGO_URL is not set — no disposable local MongoDB given"
    try:
        from app.master_data import index_bootstrap as ib
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        scheme, hosts = parse_mongo_url(REAL_URL)
        ib.check_local(hosts=hosts, scheme=scheme)
    except Exception as exc:                                  # noqa: BLE001
        return "W0_06B_REAL_MONGO_URL refused: %s" % exc
    try:
        import motor.motor_asyncio  # noqa: F401
    except ImportError:
        return "motor is not installed"
    return ""


pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


def digest(text) -> dict:
    data = text if isinstance(text, bytes) else text.encode()
    return {"algorithm": m.CHECKSUM_SHA256, "value": hashlib.sha256(data).hexdigest()}


async def _w004_indexes(db):
    """The W0-04 bootstrap indexes (scripts/w0_04_bootstrap_audit_indexes.py)."""
    await db["audit_events"].create_index([("event_id", 1)], unique=True)
    await db["audit_events"].create_index([("tenant_id", 1), ("sequence", 1)], unique=True)
    await db["audit_idempotency"].create_index("id", unique=True)


def scratch(test, *, w004_indexes=False):
    """Run ``test(db, sysdb)`` in fresh databases on the real server; drop them after."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        name = DB_PREFIX + uuid.uuid4().hex[:12]
        sys_name = SYS_PREFIX + uuid.uuid4().hex[:12]
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        try:
            db, sysdb = client[name], client[sys_name]
            await db["audit_idempotency"].create_index("id", unique=True)
            if w004_indexes:
                await _w004_indexes(db)
            for org in (A, B):
                await db["projects"].insert_one({"id": PROJECT, "org_id": org, "name": org})
            await db["projects"].insert_one({"id": ONLY_IN_B, "org_id": B, "name": "B only"})
            return await test(db, sysdb)
        finally:
            await client.drop_database(name)
            await client.drop_database(sys_name)
            client.close()
    return asyncio.run(body())


def registry(db, org):
    return FileRegistry(TenantData(db, org))


async def register(reg, text="bytes", name="a.jpg", **kw):
    return await reg.register_file(
        actor_id=ACTOR, display_name=name, original_name=name,
        category=m.CATEGORY_PHOTO_VIDEO, checksum_value=digest(text),
        size_bytes=len(text), mime_type="image/jpeg", **kw)


def _event(tenant, n):
    return build_event(tenant_id=tenant, actor_type="human", actor_id=ACTOR,
                       action="test.append", source_flow="FLOW-040",
                       retention_class=RETENTION_R2_PROJECT_OPERATIONAL,
                       entity_type="probe", entity_id="probe-%d" % n)


async def _sequences(db, org):
    rows = await db["audit_events"].find({"tenant_id": org}, {"_id": 0, "sequence": 1}).sort(
        "sequence", 1).to_list(None)
    return [r["sequence"] for r in rows]


# ═══════════════════════════════════════ finding 1 — the audit chain on a server
@pytest.mark.parametrize("w004_indexes", [False, True], ids=["builtin-id-only", "w004-indexes"])
@pytest.mark.parametrize("writers", [10, 40])
def test_concurrent_appends_of_two_tenants_never_fork_a_chain(writers, w004_indexes):
    async def t(db, _):
        await asyncio.gather(*[store.record_event(db, _event(org, i))
                               for i in range(writers) for org in (A, B)])
        for org in (A, B):
            assert await _sequences(db, org) == list(range(1, writers + 1)), org
            assert await store.verify_tenant_chain(db, org) == (True, None)
    scratch(t, w004_indexes=w004_indexes)


def test_concurrent_registry_writes_keep_intact_chains_on_a_server():
    """The review's failing scenario, widened: 10 interleaved writers per tenant."""
    async def t(db, _):
        regs = {org: registry(db, org) for org in (A, B)}

        async def work(org, i):
            out = await register(regs[org], text="%s-%d" % (org, i), name="%s%d.jpg" % (org, i))
            await regs[org].add_relation(actor_id=ACTOR, file_id=out["file_id"],
                                         relation_type=m.RELATION_PROJECT, record_id=PROJECT)

        await asyncio.gather(*[work(org, i) for i in range(10) for org in (A, B)])
        for org in (A, B):
            seqs = await _sequences(db, org)
            assert seqs == list(range(1, 21)), (org, seqs)
            assert await store.verify_tenant_chain(db, org) == (True, None)
    scratch(t)


def test_concurrent_idempotent_retries_take_one_sequence_on_a_server():
    async def t(db, _):
        reg = registry(db, A)
        await asyncio.gather(*[register(reg, idempotency_key="k-1") for _ in range(10)],
                             return_exceptions=True)
        assert await db[m.FILES_COLLECTION].count_documents({}) == 1
        assert await _sequences(db, A) == [1]
        assert await store.verify_tenant_chain(db, A) == (True, None)
    scratch(t)


def test_mutation_random_slot_forks_the_chain_on_a_server(monkeypatch):
    """UNSAFE MUTATION on the real server: the pre-fix random key + a stale head."""
    async def t(db, _):
        await store.record_event(db, _event(A, 0))
        stale = await store._last_event(db, A)
        await store.record_event(db, _event(A, 1))
        monkeypatch.setattr(store, "chain_slot_id", lambda tenant, seq: uuid.uuid4().hex)

        async def stale_last(db_, tenant):
            return stale
        monkeypatch.setattr(store, "_last_event", stale_last)
        await store.record_event(db, _event(A, 2))
        assert await _sequences(db, A) == [1, 2, 2]
        ok, _ = await store.verify_tenant_chain(db, A)
        assert ok is False
    scratch(t)


# ═══════════════════════════════════════ finding 2 — no bypass, on a server
@pytest.mark.parametrize("target", ["NOPE", ONLY_IN_B])
def test_a_missing_or_foreign_target_is_refused_on_a_server(target):
    async def t(db, _):
        reg = registry(db, A)
        with pytest.raises(RelationTargetNotFound):
            await register(reg, relations=[{"relation_type": m.RELATION_PROJECT,
                                            "record_id": target}])
        file_id = (await register(reg, text="ok"))["file_id"]
        with pytest.raises(RelationTargetNotFound):
            await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                   relation_type=m.RELATION_PROJECT, record_id=target)
        with pytest.raises(TypeError):
            await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                   relation_type=m.RELATION_PROJECT, record_id=target,
                                   verify_target=False)
        assert await db[m.RELATIONS_COLLECTION].count_documents({}) == 0
        assert await db[m.FILES_COLLECTION].count_documents({}) == 1
    scratch(t)


# ═══════════════════════════════════════ finding 3 — scoped delete, on a server
def test_a_version_delete_result_touches_only_that_version_on_a_server():
    async def t(db, _):
        reg = registry(db, A)
        file_id = (await register(reg, text="v1"))["file_id"]
        await reg.add_version(actor_id=ACTOR, file_id=file_id, checksum_value=digest("v2"),
                              size_bytes=2, mime_type="image/jpeg", original_name="a.jpg",
                              reason="retake")
        for v in (1, 2):
            await reg.set_provider_location(actor_id=ACTOR, file_id=file_id, version_no=v,
                                            provider_kind=m.PROVIDER_S3_COMPATIBLE,
                                            provider_binding_id="s3", container="bucket",
                                            object_key="o/v%d" % v)
            await reg.record_integrity_check(
                actor_id=ACTOR, file_id=file_id, version_no=v,
                verdict=IntegrityVerdict(availability=m.AVAILABILITY_AVAILABLE,
                                         checked_at="2026-10-04T00:00:00+00:00"))
        v2_before = await reg.primary_location(file_id, 2)
        req = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id, version_no=1,
                                                reason="old draft")
        await reg.record_delete_result(
            actor_id=ACTOR, request_id=req["request_id"],
            receipt=DeleteReceipt(state=m.DELETE_PROVIDER_CONFIRMED,
                                  provider_kind=m.PROVIDER_S3_COMPATIBLE, response_code="OK"))
        assert (await reg.primary_location(file_id, 1))["availability"] == m.AVAILABILITY_MISSING
        assert await reg.primary_location(file_id, 2) == v2_before
        assert (await reg.require_file(file_id))["status"] == m.FILE_ACTIVE
        assert (await reg.canonical_original(file_id))["available"] is True
    scratch(t)


# ═══════════════════════════════════════ finding 4 — determinism, on a server
def test_equal_timestamps_name_the_first_registered_file_on_a_server(monkeypatch):
    monkeypatch.setattr(m, "_now_iso", lambda: "2026-10-04T00:00:00+00:00")
    ids = iter("file_%032x" % n for n in range(10 ** 6, 0, -1))
    monkeypatch.setattr(m, "new_file_id", lambda: next(ids))

    async def t(db, _):
        reg = registry(db, A)
        first = await register(reg, text="same", name="first.jpg")
        for _ in range(3):
            await register(reg, text="same", on_duplicate=ON_DUPLICATE_NEW_FILE)
        for _ in range(10):
            out = await register(reg, text="same")
            assert out["status"] == STATUS_DUPLICATE
            assert out["duplicate_of"] == first["file_id"]
    scratch(t)


def test_concurrent_registrations_get_distinct_registration_numbers_on_a_server():
    async def t(db, _):
        reg = registry(db, A)
        await asyncio.gather(*[register(reg, text="t%d" % i) for i in range(25)])
        seqs = sorted(d["registration_seq"] for d in
                      await db[m.FILES_COLLECTION].find({"org_id": A}, {"_id": 0}).to_list(None))
        assert seqs == list(range(1, 26))
        counters = await db[m.SEQUENCES_COLLECTION].count_documents({"org_id": A})
        assert counters == 1, "a racing first upsert created a second counter"
    scratch(t)


def test_the_gate_leaves_no_database_behind():
    async def t(db, sysdb):
        await db["probe"].insert_one({"x": 1})
        await sysdb["probe"].insert_one({"x": 1})
        return db.name, sysdb.name

    from motor.motor_asyncio import AsyncIOMotorClient

    async def remaining(names):
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        try:
            listed = await client.list_database_names()
            return [n for n in names if n in listed]
        finally:
            client.close()

    names = scratch(t)
    assert names[0].startswith(DB_PREFIX) and names[1].startswith(SYS_PREFIX)
    assert asyncio.run(remaining(names)) == []
