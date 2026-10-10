"""
W0-06A — the File Registry against a REAL, disposable, local MongoDB.

Skipped unless ``W0_06A_REAL_MONGO_URL`` (or the shared ``W0_03_REAL_MONGO_URL``)
names a plain local server::

    W0_06A_REAL_MONGO_URL=mongodb://127.0.0.1:27017 \\
        pytest tests/test_w0_06a_real_mongo.py -v --noconftest

Why this file exists next to the in-memory suites. ``mongomock_motor`` is a
model of MongoDB, and the properties this task has to prove are exactly the
ones a model can get wrong:

* a UNIQUE INDEX is a server feature. The in-memory double will happily accept
  two files with one id in one tenant; the server will not. This gate builds
  the real indexes and proves both halves — the same id in two tenants is
  ALLOWED (that is the collision the boundary must survive), and a duplicate
  inside one tenant is REFUSED.
* genuinely CONCURRENT writes. Ten parallel registrations under one
  idempotency key must produce one file, and ten parallel relation additions
  must produce one relation — on a real server, with real races.
* the audit hash CHAIN under concurrency: two tenants writing at once must each
  end with an intact, independently verifiable chain.
* ``$filter``/sort/aggregation semantics the double approximates.

Safety. The URL must pass the same local-only guard the W0-03C bootstrap uses
(no Atlas, no NAS, no ``mongodb+srv``). Each test works in its OWN database
``w006a_realmongo_<random>`` and drops exactly that database afterwards —
never anything else. Nothing here reads ``.env``, ``MONGO_URL`` or any
production value, and nothing here touches a storage provider.

Required skips: 0. Every test in this file runs when the URL is given.
"""
import asyncio
import hashlib
import os
import uuid

import pytest

from app.files import models as m
from app.files.registry import (
    STATUS_DUPLICATE,
    STATUS_REGISTERED,
    STATUS_REPLAYED,
    FileRegistry,
)
from app.tenancy.data_access import TenantData

REAL_URL = os.environ.get("W0_06A_REAL_MONGO_URL") or os.environ.get("W0_03_REAL_MONGO_URL", "")
DB_PREFIX = "w006a_realmongo_"

A, B = "BEG", "TCB"
ACTOR = "user-1"
PROJECT = "P-SHARED"
INVOICE = "I-SHARED"
SHARED_FILE_ID = "file_realmongosharedidentity0000"


def _refusal():
    if not REAL_URL:
        return ("W0_06A_REAL_MONGO_URL / W0_03_REAL_MONGO_URL is not set — "
                "no disposable local MongoDB given")
    try:
        from app.master_data import index_bootstrap as ib
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        scheme, hosts = parse_mongo_url(REAL_URL)
        ib.check_local(hosts=hosts, scheme=scheme)
    except Exception as exc:                                  # noqa: BLE001
        return "W0_06A_REAL_MONGO_URL refused: %s" % exc
    try:
        import motor.motor_asyncio  # noqa: F401
    except ImportError:
        return "motor is not installed"
    return ""


pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


def digest(text: str) -> dict:
    return {"algorithm": m.CHECKSUM_SHA256,
            "value": hashlib.sha256(text.encode()).hexdigest()}


#: The indexes the File Registry needs on a real server. They are created here
#: rather than imported from a bootstrap script because W0-06A ships no
#: migration runner: declaring them in the gate is how the uniqueness
#: requirements are stated and proven before the slice that installs them.
async def create_indexes(db):
    await db[m.FILES_COLLECTION].create_index(
        [("org_id", 1), ("id", 1)], unique=True, name="file_identity")
    await db[m.VERSIONS_COLLECTION].create_index(
        [("org_id", 1), ("file_id", 1), ("version_no", 1)], unique=True,
        name="version_identity")
    await db[m.VERSIONS_COLLECTION].create_index(
        [("org_id", 1), ("file_id", 1), ("is_current", 1)], name="version_current")
    await db[m.VERSIONS_COLLECTION].create_index(
        [("org_id", 1), ("checksum_key", 1)], name="version_checksum")
    await db[m.RELATIONS_COLLECTION].create_index(
        [("org_id", 1), ("file_id", 1), ("relation_type", 1), ("record_id", 1)],
        unique=True, name="relation_identity",
        partialFilterExpression={"active": True})
    await db[m.RELATIONS_COLLECTION].create_index(
        [("org_id", 1), ("relation_type", 1), ("record_id", 1)], name="relation_lookup")
    await db[m.LOCATIONS_COLLECTION].create_index(
        [("org_id", 1), ("file_id", 1), ("version_no", 1), ("role", 1)],
        name="location_lookup")
    await db["audit_idempotency"].create_index("id", unique=True, name="idem_identity")


def scratch(test):
    """Run ``test(db, name)`` in a fresh database on the real server; drop it after."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        name = DB_PREFIX + uuid.uuid4().hex[:12]
        assert name.startswith(DB_PREFIX)
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        try:
            db = client[name]
            await create_indexes(db)
            for org in (A, B):
                await db["projects"].insert_one(
                    {"id": PROJECT, "org_id": org, "name": "%s project" % org})
                await db["invoices"].insert_one(
                    {"id": INVOICE, "org_id": org, "invoice_no": "%s-1" % org})
            return await test(db, name)
        finally:
            await client.drop_database(name)
            client.close()
    return asyncio.run(body())


def registry(db, org):
    return FileRegistry(TenantData(db, org))


async def register(reg, text="bytes", name="site.jpg", **kw):
    return await reg.register_file(
        actor_id=ACTOR, display_name=name, original_name=name,
        category=m.CATEGORY_PHOTO_VIDEO, checksum_value=digest(text),
        size_bytes=len(text), mime_type="image/jpeg", **kw)


# ═══════════════════════════════ real unique indexes, real collisions
def test_the_same_file_id_in_two_tenants_is_allowed_by_the_real_index():
    """The collision the boundary exists to survive must be STORABLE.

    An index that made it impossible would hide the defect rather than
    prevent it: the identity is unique per TENANT, not per installation.
    """
    async def t(db, _):
        for org in (A, B):
            doc = m.build_file(org_id=org, display_name="%s.pdf" % org, original_name="x.pdf",
                               category=m.CATEGORY_CONTRACTS, uploaded_by=ACTOR,
                               file_id=SHARED_FILE_ID)
            await db[m.FILES_COLLECTION].insert_one(dict(doc))
        assert await db[m.FILES_COLLECTION].count_documents({"id": SHARED_FILE_ID}) == 2
        for org in (A, B):
            found = await registry(db, org).require_file(SHARED_FILE_ID)
            assert found["org_id"] == org and found["display_name"] == "%s.pdf" % org
    scratch(t)


def test_the_real_index_refuses_a_duplicate_identity_inside_one_tenant():
    async def t(db, _):
        from pymongo.errors import DuplicateKeyError
        doc = m.build_file(org_id=A, display_name="x", original_name="x.pdf",
                           category=m.CATEGORY_CONTRACTS, uploaded_by=ACTOR,
                           file_id=SHARED_FILE_ID)
        await db[m.FILES_COLLECTION].insert_one(dict(doc))
        with pytest.raises(DuplicateKeyError):
            await db[m.FILES_COLLECTION].insert_one(dict(doc))
    scratch(t)


def test_the_real_index_refuses_a_second_active_relation_to_the_same_record():
    async def t(db, _):
        from pymongo.errors import DuplicateKeyError
        reg = registry(db, A)
        file_id = (await register(reg))["file_id"]
        await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                               relation_type=m.RELATION_PROJECT, record_id=PROJECT)
        row = m.build_relation(org_id=A, file_id=file_id, relation_type=m.RELATION_PROJECT,
                               record_id=PROJECT, created_by=ACTOR)
        with pytest.raises(DuplicateKeyError):
            await db[m.RELATIONS_COLLECTION].insert_one(dict(row))
        # the SAME triple in the other tenant is a different identity
        await db[m.RELATIONS_COLLECTION].insert_one(dict(m.build_relation(
            org_id=B, file_id=file_id, relation_type=m.RELATION_PROJECT,
            record_id=PROJECT, created_by=ACTOR)))
    scratch(t)


def test_a_removed_relation_frees_the_slot_for_a_relink():
    """The unique index is partial on ``active``: history is kept AND the same
    file can legitimately be attached to the same record again later."""
    async def t(db, _):
        reg = registry(db, A)
        file_id = (await register(reg))["file_id"]
        await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                               relation_type=m.RELATION_PROJECT, record_id=PROJECT)
        await reg.remove_relation(actor_id=ACTOR, file_id=file_id,
                                  relation_type=m.RELATION_PROJECT, record_id=PROJECT,
                                  reason="unlinked by mistake")
        again = await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                       relation_type=m.RELATION_PROJECT, record_id=PROJECT)
        assert again["status"] == STATUS_REGISTERED
        assert len(await reg.list_relations(file_id)) == 1
        assert len(await reg.list_relations(file_id, include_removed=True)) == 2
    scratch(t)


# ═══════════════════════════════════════════ genuine concurrency
@pytest.mark.parametrize("writers", [2, 10])
def test_concurrent_registrations_under_one_key_create_one_file(writers):
    async def t(db, _):
        reg = registry(db, A)
        results = await asyncio.gather(
            *[register(reg, idempotency_key="upload-1") for _ in range(writers)],
            return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        assert not failures, failures
        assert await db[m.FILES_COLLECTION].count_documents({}) == 1, \
            "%d concurrent uploads created %d files" % (
                writers, await db[m.FILES_COLLECTION].count_documents({}))
        assert await db[m.VERSIONS_COLLECTION].count_documents({}) == 1
        statuses = {r["status"] for r in results}
        assert STATUS_REGISTERED in statuses or STATUS_REPLAYED in statuses
    scratch(t)


@pytest.mark.parametrize("writers", [2, 10])
def test_concurrent_relation_adds_create_one_relation(writers):
    async def t(db, _):
        reg = registry(db, A)
        file_id = (await register(reg))["file_id"]
        results = await asyncio.gather(
            *[reg.add_relation(actor_id=ACTOR, file_id=file_id,
                               relation_type=m.RELATION_PROJECT, record_id=PROJECT,
                               idempotency_key="link-1") for _ in range(writers)],
            return_exceptions=True)
        real = [r for r in results if isinstance(r, Exception)
                and type(r).__name__ != "DuplicateKeyError"]
        assert not real, real
        active = await db[m.RELATIONS_COLLECTION].count_documents(
            {"file_id": file_id, "active": True})
        assert active == 1, "%d concurrent links created %d relations" % (writers, active)
    scratch(t)


def test_two_tenants_writing_at_once_keep_separate_intact_audit_chains():
    async def t(db, _):
        from app.audit.store import verify_tenant_chain
        regs = {org: registry(db, org) for org in (A, B)}

        async def work(org):
            out = await register(regs[org], text="%s-bytes" % org, name="%s.jpg" % org)
            await regs[org].add_relation(actor_id=ACTOR, file_id=out["file_id"],
                                         relation_type=m.RELATION_PROJECT, record_id=PROJECT)
            return out["file_id"]

        # interleaved, not sequential
        await asyncio.gather(work(A), work(B), work(A), work(B))
        for org in (A, B):
            events = await db["audit_events"].find({"tenant_id": org},
                                                   {"_id": 0}).sort("sequence", 1).to_list(None)
            assert events, org
            assert {e["tenant_id"] for e in events} == {org}
            assert [e["sequence"] for e in events] == list(range(1, len(events) + 1)), \
                "%s has a sequence gap" % org
            intact, reason = await verify_tenant_chain(db, org)
            assert intact, "%s: %s" % (org, reason)
    scratch(t)


# ═══════════════════════════════ the isolation matrix, on the server
def test_no_registry_read_crosses_the_boundary_on_a_real_server():
    async def t(db, _):
        regs = {org: registry(db, org) for org in (A, B)}
        files = {}
        for org in (A, B):
            doc = m.build_file(org_id=org, display_name="%s secret" % org,
                               original_name="secret.pdf", category=m.CATEGORY_CONTRACTS,
                               uploaded_by=ACTOR, file_id=SHARED_FILE_ID,
                               sensitivity=m.SENSITIVITY_CONFIDENTIAL)
            await db[m.FILES_COLLECTION].insert_one(dict(doc))
            version = m.build_version(org_id=org, file_id=SHARED_FILE_ID, version_no=1,
                                      checksum_value=digest("%s-bytes" % org), size_bytes=3,
                                      mime_type="application/pdf", original_name="secret.pdf",
                                      created_by=ACTOR)
            await db[m.VERSIONS_COLLECTION].insert_one(dict(version))
            await db[m.FILES_COLLECTION].update_one(
                {"id": SHARED_FILE_ID, "org_id": org},
                {"$set": {"current_version_no": 1, "version_count": 1}})
            await regs[org].set_provider_location(
                actor_id=ACTOR, file_id=SHARED_FILE_ID, version_no=1,
                provider_kind=m.PROVIDER_SYNOLOGY_NAS,
                provider_binding_id="binding-%s" % org, container="shared-container",
                object_key="same/object/key.pdf")
            await regs[org].add_relation(actor_id=ACTOR, file_id=SHARED_FILE_ID,
                                         relation_type=m.RELATION_INVOICE,
                                         record_id=INVOICE)
            files[org] = doc

        for org in (A, B):
            other = B if org == A else A
            doc = await regs[org].require_file(SHARED_FILE_ID)
            assert doc["display_name"] == "%s secret" % org
            assert len(await regs[org].list_versions(SHARED_FILE_ID)) == 1
            assert len(await regs[org].list_relations(SHARED_FILE_ID)) == 1
            location = await regs[org].primary_location(SHARED_FILE_ID, 1)
            assert location["provider_binding_id"] == "binding-%s" % org
            assert "binding-%s" % other not in str(location)
            found = await regs[org].files_for_record(m.RELATION_INVOICE, INVOICE)
            assert [f["org_id"] for f in found] == [org]
            assert await regs[org].find_by_checksum(digest("%s-bytes" % other)) == []
    scratch(t)


def test_a_write_by_one_tenant_leaves_the_others_documents_byte_equal():
    async def t(db, _):
        import bson
        regs = {org: registry(db, org) for org in (A, B)}
        ids = {}
        for org in (A, B):
            ids[org] = (await register(regs[org], text="%s-bytes" % org,
                                       relations=[{"relation_type": m.RELATION_INVOICE,
                                                   "record_id": INVOICE}]))["file_id"]

        async def snapshot(org):
            rows = []
            for collection in sorted(m.REGISTRY_COLLECTIONS):
                rows.extend(sorted(
                    await db[collection].find({"org_id": org}, {"_id": 0}).to_list(None),
                    key=m.sort_key))
            return bson.encode({"rows": rows})

        before_b = await snapshot(B)
        # A does everything it can, including on B's file id
        await regs[A].add_version(actor_id=ACTOR, file_id=ids[A], checksum_value=digest("a2"),
                                  size_bytes=2, mime_type="image/jpeg",
                                  original_name="site.jpg", reason="retake")
        await regs[A].set_provider_location(
            actor_id=ACTOR, file_id=ids[A], version_no=2,
            provider_kind=m.PROVIDER_S3_COMPATIBLE, provider_binding_id="s3-%s" % A,
            container="bucket", object_key="a/v2.jpg")
        await regs[A].request_physical_delete(actor_id=ACTOR, file_id=ids[A], reason="erasure",
                                              whole_file=True)
        for method, kwargs in (
            ("get_file", {"file_id": ids[B]}),
            ("list_versions", {"file_id": ids[B]}),
            ("list_relations", {"file_id": ids[B]}),
        ):
            result = await getattr(regs[A], method)(**kwargs)
            assert not result, "A reached B's %s" % method
        assert await snapshot(B) == before_b, "a write by A changed B's documents"
    scratch(t)


# ═══════════════════════════════════ versioning and integrity on the server
def test_versioning_keeps_exactly_one_current_version_on_the_server():
    async def t(db, _):
        reg = registry(db, A)
        file_id = (await register(reg, text="v1"))["file_id"]
        for i in range(2, 8):
            await reg.add_version(actor_id=ACTOR, file_id=file_id,
                                  checksum_value=digest("v%d" % i), size_bytes=i,
                                  mime_type="image/jpeg", original_name="site.jpg",
                                  reason="revision %d" % i)
        current = await db[m.VERSIONS_COLLECTION].find(
            {"org_id": A, "file_id": file_id, "is_current": True}, {"_id": 0}).to_list(None)
        assert len(current) == 1 and current[0]["version_no"] == 7
        every = await reg.list_versions(file_id)
        assert [v["version_no"] for v in every] == list(range(1, 8))
        assert every[0]["checksum"] == digest("v1"), "version 1 was rewritten"
    scratch(t)


def test_a_duplicate_checksum_resolves_to_the_same_file_on_every_call():
    async def t(db, _):
        reg = registry(db, A)
        first = await register(reg, text="identical", name="a.jpg")
        answers = set()
        for _ in range(5):
            out = await register(reg, text="identical", name="b.jpg")
            assert out["status"] == STATUS_DUPLICATE
            answers.add(out["duplicate_of"])
        assert answers == {first["file_id"]}
        assert await db[m.FILES_COLLECTION].count_documents({"org_id": A}) == 1
    scratch(t)


def test_an_external_mutation_never_becomes_a_version_on_the_server():
    async def t(db, _):
        from app.files.providers.base import IntegrityVerdict
        reg = registry(db, A)
        file_id = (await register(reg, text="original", relations=[
            {"relation_type": m.RELATION_INVOICE, "record_id": INVOICE},
            {"relation_type": m.RELATION_PROJECT, "record_id": PROJECT}]))["file_id"]
        await reg.set_provider_location(
            actor_id=ACTOR, file_id=file_id, version_no=1,
            provider_kind=m.PROVIDER_S3_COMPATIBLE, provider_binding_id="s3",
            container="bucket", object_key="k.jpg")
        out = await reg.record_integrity_check(
            actor_id=ACTOR, file_id=file_id, version_no=1,
            verdict=IntegrityVerdict(availability=m.AVAILABILITY_CHECKSUM_MISMATCH,
                                     expected_checksum=digest("original"),
                                     observed_checksum=digest("tampered"),
                                     checked_at="2026-10-03T00:00:00+00:00"))
        assert out["severity"] == "critical"
        assert {a["record_id"] for a in out["affected_records"]} == {INVOICE, PROJECT}
        assert await db[m.VERSIONS_COLLECTION].count_documents({"file_id": file_id}) == 1
        answer = await reg.canonical_original(file_id)
        assert answer["available"] is False and answer["original_servable"] is False
    scratch(t)


def test_the_gate_leaves_no_database_behind():
    """The gate's own safety property: it drops exactly what it created."""
    async def t(db, name):
        await db[m.FILES_COLLECTION].insert_one(dict(m.build_file(
            org_id=A, display_name="x", original_name="x", category=m.CATEGORY_OTHER,
            uploaded_by=ACTOR)))
        return name

    from motor.motor_asyncio import AsyncIOMotorClient

    async def verify(name):
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        try:
            return name in await client.list_database_names()
        finally:
            client.close()

    created = scratch(t)
    assert created.startswith(DB_PREFIX)
    assert asyncio.run(verify(created)) is False
