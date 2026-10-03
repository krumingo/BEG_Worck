"""
W0-06A — two tenants, colliding ids: no file metadata, location or relation crosses.

The File Registry is a new tenant-owned surface, so it inherits the whole
W0-03E problem rather than being exempt from it. With one shared legacy
database, two tenants can hold the same ``file_id``, the same relation target
id and the same provider object key, and every lookup that resolves a record by
its id alone returns whichever document the database reaches first.

So every assertion here is made with COLLIDING ids, and in BOTH storage orders
— A first and B first — because a global lookup can pass by luck in one order.
What must hold for each tenant:

* its own file reads back; the other tenant's file of the same id is simply
  absent, never "found but filtered";
* its relations, versions, provider locations and cached derivatives are its
  own, and the counts prove no row of the other tenant was counted;
* a provider object key, container and binding id of the other tenant never
  appear in anything it can read — those are the credentials-adjacent values
  FLOW-016 forbids crossing;
* it cannot create a relation to the other tenant's business record, even when
  that record's id also exists in its own tenant under different content;
* its audit chain contains only its own events and verifies independently.

Runs in process against ``mongomock_motor``; the same matrix runs against a
disposable real MongoDB in ``tests/test_w0_06a_real_mongo.py``.

    pytest tests/test_w0_06a_tenant_isolation.py -v --noconftest
"""
import asyncio
import hashlib

import pytest

from app.files import models as m
from app.files.migration_map import deterministic_file_id
from app.files.registry import FileNotFound, FileRegistry, RelationTargetNotFound
from app.tenancy.data_access import TenantData, TenantScopeViolation

pytest.importorskip("mongomock_motor")

A, B = "BEG", "TCB"
ACTOR_A, ACTOR_B = "user-a", "user-b"

#: The SAME ids in both tenants. Every one of these is a trap for a lookup that
#: resolves by id alone.
SHARED_PROJECT = "P-SHARED"
SHARED_INVOICE = "I-SHARED"
SHARED_FILE_ID = "file_sharedidentity0000000000000"
SHARED_OBJECT_KEY = "tenants/x/files/shared/object.pdf"
SHARED_CONTAINER = "shared-container"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def digest(text: str) -> dict:
    return {"algorithm": m.CHECKSUM_SHA256,
            "value": hashlib.sha256(text.encode()).hexdigest()}


async def _seed(order):
    """Both tenants, seeded in ``order``. Returns ``(db, {org: FileRegistry})``."""
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["w0_06a_iso"]
    registries = {}
    for org in order:
        await db["projects"].insert_one(
            {"id": SHARED_PROJECT, "org_id": org, "name": "%s project" % org})
        await db["invoices"].insert_one(
            {"id": SHARED_INVOICE, "org_id": org, "invoice_no": "%s-1" % org})
        registries[org] = FileRegistry(TenantData(db, org))
    return db, registries


async def _register_colliding(reg, org, actor):
    """One file per tenant, under the SAME file_id, the SAME object key and the
    SAME container — the worst case the boundary has to survive."""
    file_doc = m.build_file(org_id=org, display_name="%s secret.pdf" % org,
                            original_name="secret.pdf", category=m.CATEGORY_CONTRACTS,
                            uploaded_by=actor, file_id=SHARED_FILE_ID,
                            sensitivity=m.SENSITIVITY_CONFIDENTIAL)
    await reg.files.insert_one(dict(file_doc))
    version = m.build_version(org_id=org, file_id=SHARED_FILE_ID, version_no=1,
                              checksum_value=digest("%s-bytes" % org), size_bytes=len(org),
                              mime_type="application/pdf", original_name="secret.pdf",
                              created_by=actor)
    await reg.versions.insert_one(dict(version))
    await reg.files.update_one({"id": SHARED_FILE_ID},
                               {"$set": {"current_version_no": 1, "version_count": 1}})
    await reg.set_provider_location(
        actor_id=actor, file_id=SHARED_FILE_ID, version_no=1,
        provider_kind=m.PROVIDER_SYNOLOGY_NAS,
        provider_binding_id="binding-%s" % org, container=SHARED_CONTAINER,
        object_key=SHARED_OBJECT_KEY)
    await reg.add_relation(actor_id=actor, file_id=SHARED_FILE_ID,
                           relation_type=m.RELATION_PROJECT, record_id=SHARED_PROJECT)
    await reg.add_relation(actor_id=actor, file_id=SHARED_FILE_ID,
                           relation_type=m.RELATION_INVOICE, record_id=SHARED_INVOICE)
    await reg.register_derived(actor_id=actor, file_id=SHARED_FILE_ID, source_version_no=1,
                               kind=m.DERIVED_THUMBNAIL, cache_reference="cache/%s" % org)
    return file_doc


ORDERS = [(A, B), (B, A)]


@pytest.mark.parametrize("order", ORDERS, ids=["A-first", "B-first"])
class TestCollidingIdsDoNotLeak:
    def test_each_tenant_reads_only_its_own_file_under_the_shared_id(self, order):
        async def body():
            db, regs = await _seed(order)
            for org, actor in ((A, ACTOR_A), (B, ACTOR_B)):
                await _register_colliding(regs[org], org, actor)
            for org in (A, B):
                doc = await regs[org].require_file(SHARED_FILE_ID)
                assert doc["org_id"] == org
                assert doc["display_name"] == "%s secret.pdf" % org
                other = B if org == A else A
                assert other not in doc["display_name"]
            # two documents exist under the one id — the collision is real
            assert await db[m.FILES_COLLECTION].count_documents({"id": SHARED_FILE_ID}) == 2
        run(body())

    def test_versions_relations_locations_and_cache_are_each_tenants_own(self, order):
        async def body():
            db, regs = await _seed(order)
            for org, actor in ((A, ACTOR_A), (B, ACTOR_B)):
                await _register_colliding(regs[org], org, actor)
            for org in (A, B):
                reg = regs[org]
                versions = await reg.list_versions(SHARED_FILE_ID)
                assert len(versions) == 1, "another tenant's version was counted"
                assert versions[0]["checksum"] == digest("%s-bytes" % org)

                relations = await reg.list_relations(SHARED_FILE_ID)
                assert len(relations) == 2, "another tenant's relations were counted"
                assert {r["org_id"] for r in relations} == {org}

                location = await reg.primary_location(SHARED_FILE_ID, 1)
                assert location["org_id"] == org
                assert location["provider_binding_id"] == "binding-%s" % org, \
                    "the other tenant's provider binding leaked"

                answer = await reg.canonical_original(SHARED_FILE_ID)
                assert len(answer["derived"]) == 1
                assert answer["derived"][0]["cache_reference"] == "cache/%s" % org
        run(body())

    def test_a_record_screen_shows_only_this_tenants_files(self, order):
        async def body():
            _, regs = await _seed(order)
            for org, actor in ((A, ACTOR_A), (B, ACTOR_B)):
                await _register_colliding(regs[org], org, actor)
            for org in (A, B):
                for relation_type, record in ((m.RELATION_PROJECT, SHARED_PROJECT),
                                              (m.RELATION_INVOICE, SHARED_INVOICE)):
                    files = await regs[org].files_for_record(relation_type, record)
                    assert len(files) == 1
                    assert files[0]["org_id"] == org
        run(body())

    def test_a_duplicate_lookup_never_sees_the_other_tenants_checksum(self, order):
        async def body():
            _, regs = await _seed(order)
            for org, actor in ((A, ACTOR_A), (B, ACTOR_B)):
                await _register_colliding(regs[org], org, actor)
            # the SAME bytes, registered by A only
            await regs[A].register_file(
                actor_id=ACTOR_A, display_name="same.pdf", original_name="same.pdf",
                category=m.CATEGORY_OTHER, checksum_value=digest("identical"),
                size_bytes=9, mime_type="application/pdf")
            assert await regs[B].find_by_checksum(digest("identical")) == []
            assert len(await regs[A].find_by_checksum(digest("identical"))) == 1
        run(body())

    def test_a_write_cannot_touch_the_other_tenants_file(self, order):
        async def body():
            db, regs = await _seed(order)
            docs = {}
            for org, actor in ((A, ACTOR_A), (B, ACTOR_B)):
                docs[org] = await _register_colliding(regs[org], org, actor)

            async def snapshot(org):
                return {
                    "file": await db[m.FILES_COLLECTION].find_one(
                        {"id": SHARED_FILE_ID, "org_id": org}, {"_id": 0}),
                    "versions": sorted(await db[m.VERSIONS_COLLECTION].find(
                        {"file_id": SHARED_FILE_ID, "org_id": org}, {"_id": 0}).to_list(None),
                        key=m.sort_key),
                    "relations": sorted(await db[m.RELATIONS_COLLECTION].find(
                        {"file_id": SHARED_FILE_ID, "org_id": org}, {"_id": 0}).to_list(None),
                        key=m.sort_key),
                    "locations": sorted(await db[m.LOCATIONS_COLLECTION].find(
                        {"file_id": SHARED_FILE_ID, "org_id": org}, {"_id": 0}).to_list(None),
                        key=m.sort_key),
                }

            before_b = await snapshot(B)
            # A does everything it can to the shared id
            await regs[A].add_version(actor_id=ACTOR_A, file_id=SHARED_FILE_ID,
                                      checksum_value=digest("a-v2"), size_bytes=4,
                                      mime_type="application/pdf", original_name="secret.pdf",
                                      reason="A revises its own file")
            await regs[A].remove_relation(actor_id=ACTOR_A, file_id=SHARED_FILE_ID,
                                          relation_type=m.RELATION_INVOICE,
                                          record_id=SHARED_INVOICE, reason="A unlinks")
            await regs[A].request_physical_delete(actor_id=ACTOR_A, file_id=SHARED_FILE_ID,
                                                   reason="A asks for erasure")
            # B's half of the collision is byte-identical to before
            assert await snapshot(B) == before_b
            assert (await regs[B].require_file(SHARED_FILE_ID))["status"] == m.FILE_ACTIVE
            assert len(await regs[B].list_relations(SHARED_FILE_ID)) == 2
            assert len(await regs[B].list_versions(SHARED_FILE_ID)) == 1
        run(body())

    def test_a_relation_cannot_be_created_across_the_boundary(self, order):
        async def body():
            db, regs = await _seed(order)
            # a record that exists ONLY in B
            await db["invoices"].insert_one({"id": "I-ONLY-B", "org_id": B, "invoice_no": "b"})
            out = await regs[A].register_file(
                actor_id=ACTOR_A, display_name="a.pdf", original_name="a.pdf",
                category=m.CATEGORY_OTHER, checksum_value=digest("a"), size_bytes=1,
                mime_type="application/pdf")
            with pytest.raises(RelationTargetNotFound):
                await regs[A].add_relation(actor_id=ACTOR_A, file_id=out["file_id"],
                                           relation_type=m.RELATION_INVOICE,
                                           record_id="I-ONLY-B")
            assert await db[m.RELATIONS_COLLECTION].count_documents(
                {"record_id": "I-ONLY-B"}) == 0
        run(body())

    def test_each_tenant_has_its_own_verifiable_audit_chain(self, order):
        async def body():
            from app.audit.store import verify_tenant_chain
            db, regs = await _seed(order)
            for org, actor in ((A, ACTOR_A), (B, ACTOR_B)):
                await _register_colliding(regs[org], org, actor)
            for org in (A, B):
                events = await db["audit_events"].find({"tenant_id": org},
                                                       {"_id": 0}).to_list(None)
                assert events, "no audit events for %s" % org
                assert {e["tenant_id"] for e in events} == {org}
                intact, reason = await verify_tenant_chain(db, org)
                assert intact, "%s chain broken: %s" % (org, reason)
                # sequences start at 1 per tenant, independent of the other
                assert min(e["sequence"] for e in events) == 1
        run(body())


class TestOwnershipCannotBeForged:
    def test_the_access_layer_refuses_a_write_naming_another_tenant(self):
        async def body():
            db, regs = await _seed((A, B))
            doc = m.build_file(org_id=B, display_name="x", original_name="x",
                               category=m.CATEGORY_OTHER, uploaded_by=ACTOR_B)
            with pytest.raises(TenantScopeViolation):
                await regs[A].files.insert_one(dict(doc))
        run(body())

    def test_the_access_layer_refuses_a_filter_naming_another_tenant(self):
        async def body():
            _, regs = await _seed((A, B))
            with pytest.raises(TenantScopeViolation):
                await regs[A].files.find_one({"id": SHARED_FILE_ID, "org_id": B})
        run(body())

    def test_a_derived_file_id_differs_per_tenant_for_the_same_legacy_row(self):
        """The migration cannot RE-CREATE the collision it is meant to resolve."""
        assert deterministic_file_id(A, "media_files", "m-1") != \
            deterministic_file_id(B, "media_files", "m-1")
        assert deterministic_file_id(A, "media_files", "m-1") == \
            deterministic_file_id(A, "media_files", "m-1")
