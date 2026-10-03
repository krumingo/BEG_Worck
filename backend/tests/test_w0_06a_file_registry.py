"""
W0-06A — the File Registry rules, against the record layer and the service.

Every assertion here is one sentence of FLOW-016 turned into a test. The order
follows the acceptance list of Issue #43 / the W0-06A assignment:

* one stable ``file_id`` serves many relations with NO duplicate registry record;
* a new version never overwrites an old one, and exactly one is current;
* an approved/signed version is never replaced in place;
* duplicate checksum behaviour is deterministic;
* unlink removes exactly one relation and touches nothing else;
* an unavailable or externally mutated provider object never lets a cached
  preview become the canonical original;
* registry actions are audited and retryable writes are idempotent.

Runs in process against ``mongomock_motor`` — no server, no real MongoDB, no
provider. The two-tenant collision matrix lives in
``tests/test_w0_06a_tenant_isolation.py`` and the same suite runs against a
disposable real MongoDB in ``tests/test_w0_06a_real_mongo.py``.

    pytest tests/test_w0_06a_file_registry.py -v --noconftest
"""
import asyncio
import hashlib

import pytest

from app.files import models as m
from app.files.migration_map import SOURCES_BY_KEY
from app.files.providers.base import DeleteReceipt
from app.files.registry import (
    ACTION_REGISTER,
    ON_DUPLICATE_NEW_FILE,
    STATUS_DUPLICATE,
    STATUS_REGISTERED,
    STATUS_REPLAYED,
    FileNotFound,
    FileRegistry,
    FileRegistryError,
    RelationTargetNotFound,
    VersionSealed,
)
from app.tenancy.data_access import TenantData

pytest.importorskip("mongomock_motor")

ORG = "BEG"
ACTOR = "user-1"
PROJECT = "P-1"
INVOICE = "I-1"
DEFECT = "D-1"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def digest(text: str) -> dict:
    return {"algorithm": m.CHECKSUM_SHA256,
            "value": hashlib.sha256(text.encode()).hexdigest()}


async def _registry(org: str = ORG):
    """A registry over an in-memory database seeded with the relation targets."""
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["w0_06a"]
    await db["projects"].insert_one({"id": PROJECT, "org_id": org, "name": "Site"})
    await db["invoices"].insert_one({"id": INVOICE, "org_id": org, "invoice_no": "1"})
    await db["missing_smr"].insert_one({"id": DEFECT, "org_id": org, "title": "crack"})
    return FileRegistry(TenantData(db, org)), db


async def _register(reg, *, text="photo-bytes", name="site.jpg",
                    category=m.CATEGORY_PHOTO_VIDEO, relations=(), **kw):
    return await reg.register_file(
        actor_id=ACTOR, display_name=name, original_name=name, category=category,
        checksum_value=digest(text), size_bytes=len(text), mime_type="image/jpeg",
        relations=relations, **kw)


# ════════════════════════════════════════════════════ the record vocabulary
class TestRecordLayer:
    def test_registry_collections_match_the_ownership_classification(self):
        """The one list of collections is classified in exactly one place.

        ``app.tenancy.ownership`` is the single answer to "which collections are
        tenant-owned". A registry collection missing from it would be
        UNCLASSIFIED to the A2C guard and invisible to the backfill.
        """
        from app.tenancy import ownership
        for name in m.REGISTRY_COLLECTIONS:
            assert ownership.classify_collection(name) == ownership.CLASS_ORG
            assert ownership.tenant_key_of(name) == m.ORG_KEY
        assert ownership.family_of(m.FILES_COLLECTION) == ownership.FAMILY_FILES

    def test_every_relation_type_targets_a_tenant_owned_collection(self):
        """A relation must be verifiable inside one tenant, on both sides."""
        from app.tenancy import ownership
        for relation_type, collection in m.RELATION_TARGETS.items():
            assert ownership.classify_collection(collection) == ownership.CLASS_ORG, \
                "%s -> %s is not tenant-owned" % (relation_type, collection)
        assert set(m.RELATION_TYPES) == set(m.RELATION_TARGETS)

    def test_the_issue_43_minimum_relation_types_all_exist(self):
        for required in (m.RELATION_PROJECT, m.RELATION_SUB_PROJECT, m.RELATION_SMR,
                         m.RELATION_DAILY_REPORT, m.RELATION_OFFER, m.RELATION_CONTRACT,
                         m.RELATION_ANNEX, m.RELATION_ACT, m.RELATION_INVOICE,
                         m.RELATION_DELIVERY, m.RELATION_TASK, m.RELATION_DEFECT,
                         m.RELATION_WARRANTY, m.RELATION_SUBCONTRACTOR,
                         m.RELATION_ASSET, m.RELATION_REPAIR):
            assert required in m.RELATION_TYPES

    def test_a_record_cannot_be_built_without_an_owner(self):
        """Ownerless is refused at BUILD time, before any database is involved."""
        for builder, kwargs in (
            (m.build_file, dict(display_name="a", original_name="a", category=m.CATEGORY_OTHER,
                                uploaded_by=ACTOR)),
            (m.build_version, dict(file_id="file_x", version_no=1, checksum_value=digest("a"),
                                   size_bytes=1, mime_type="image/jpeg", original_name="a",
                                   created_by=ACTOR)),
            (m.build_relation, dict(file_id="file_x", relation_type=m.RELATION_PROJECT,
                                    record_id=PROJECT, created_by=ACTOR)),
            (m.build_provider_location, dict(file_id="file_x", version_no=1,
                                             provider_kind=m.PROVIDER_FAKE_MEMORY,
                                             provider_binding_id="b", container="c",
                                             object_key="k")),
            (m.build_derived, dict(file_id="file_x", source_version_no=1,
                                   kind=m.DERIVED_THUMBNAIL, cache_reference="c")),
            (m.build_delete_request, dict(file_id="file_x", requested_by=ACTOR, reason="r")),
        ):
            for bad in ("", "   ", None):
                with pytest.raises(m.FileRecordInvalid):
                    builder(org_id=bad, **kwargs)

    def test_a_file_id_carries_no_provider_information(self):
        """The identity must survive a provider migration, so it encodes nothing."""
        file_id = m.new_file_id()
        assert file_id.startswith(m.ID_PREFIX_FILE)
        for provider_word in ("drive", "nas", "s3", "http", "/", "\\", ".jpg"):
            assert provider_word not in file_id

    def test_a_second_version_must_say_why_and_what_it_follows(self):
        with pytest.raises(m.FileRecordInvalid):
            m.build_version(org_id=ORG, file_id="file_x", version_no=2,
                            checksum_value=digest("b"), size_bytes=1, mime_type="application/pdf",
                            original_name="c.pdf", created_by=ACTOR, reason="",
                            supersedes_version_no=1)
        with pytest.raises(m.FileRecordInvalid):
            m.build_version(org_id=ORG, file_id="file_x", version_no=2,
                            checksum_value=digest("b"), size_bytes=1, mime_type="application/pdf",
                            original_name="c.pdf", created_by=ACTOR, reason="re-signed",
                            supersedes_version_no=None)

    def test_a_stored_version_refuses_an_update_of_its_content(self):
        """Read-only means the content fields cannot be changed, by anyone."""
        for field in ("checksum", "size_bytes", "mime_type", "original_name", "created_by",
                      "version_no", "file_id", "org_id", "reason"):
            with pytest.raises(m.FileRecordInvalid):
                m.assert_version_update_allowed({field: "whatever"})
            with pytest.raises(m.FileRecordInvalid):
                m.assert_version_update_allowed({"$set": {field: "whatever"}})
        # the successor fields and the seal are the only legal changes
        m.assert_version_update_allowed({"is_current": False, "superseded_by_version_no": 2,
                                         "superseded_at": "now"})
        m.assert_version_update_allowed({"approval_state": m.APPROVAL_SIGNED})

    def test_a_derivative_can_never_claim_to_be_the_original(self):
        row = m.build_derived(org_id=ORG, file_id="file_x", source_version_no=1,
                              kind=m.DERIVED_THUMBNAIL, cache_reference="cache/1")
        assert row["is_canonical_original"] is False
        assert row["regenerable"] is True

    def test_severity_follows_the_affected_records_not_the_error(self):
        """FLOW-016: the same failure is a cache problem or a business incident
        depending on what the file is attached to."""
        assert m.severity_of(m.AVAILABILITY_MISSING, 0) == "low"
        assert m.severity_of(m.AVAILABILITY_MISSING, 1) == "high"
        assert m.severity_of(m.AVAILABILITY_MISSING, 3) == "critical"
        assert m.severity_of(m.AVAILABILITY_AVAILABLE, 5) == "none"


# ══════════════════════════════════════════════════ one file, many relations
class TestOneFileManyRelations:
    def test_one_file_id_serves_many_relations_without_a_second_record(self):
        async def body():
            reg, db = await _registry()
            out = await _register(reg, relations=[
                {"relation_type": m.RELATION_PROJECT, "record_id": PROJECT}])
            file_id = out["file_id"]
            await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                   relation_type=m.RELATION_INVOICE, record_id=INVOICE)
            await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                   relation_type=m.RELATION_DEFECT, record_id=DEFECT)

            # ONE registry record and ONE version, three relations.
            assert await db[m.FILES_COLLECTION].count_documents({}) == 1
            assert await db[m.VERSIONS_COLLECTION].count_documents({}) == 1
            assert len(await reg.list_relations(file_id)) == 3

            # and the same file_id is what each screen reads
            for rel_type, record in ((m.RELATION_PROJECT, PROJECT),
                                     (m.RELATION_INVOICE, INVOICE),
                                     (m.RELATION_DEFECT, DEFECT)):
                files = await reg.files_for_record(rel_type, record)
                assert [f["id"] for f in files] == [file_id]
        run(body())

    def test_unlink_removes_exactly_one_relation_and_nothing_else(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg, relations=[
                {"relation_type": m.RELATION_PROJECT, "record_id": PROJECT},
                {"relation_type": m.RELATION_INVOICE, "record_id": INVOICE}]))["file_id"]
            before = await db[m.FILES_COLLECTION].find_one({"id": file_id}, {"_id": 0})

            out = await reg.remove_relation(actor_id=ACTOR, file_id=file_id,
                                            relation_type=m.RELATION_PROJECT,
                                            record_id=PROJECT, reason="wrong project")
            assert out["remaining_relations"] == 1
            remaining = await reg.list_relations(file_id)
            assert [(r["relation_type"], r["record_id"]) for r in remaining] == \
                [(m.RELATION_INVOICE, INVOICE)]

            # the file, its version and its provider location are untouched
            assert await db[m.FILES_COLLECTION].find_one({"id": file_id}, {"_id": 0}) == before
            assert await db[m.VERSIONS_COLLECTION].count_documents({"file_id": file_id}) == 1
            # the removed relation is kept as history, not destroyed
            all_rows = await reg.list_relations(file_id, include_removed=True)
            removed = [r for r in all_rows if not r["active"]]
            assert len(removed) == 1
            assert removed[0]["removed_by"] == ACTOR
            assert removed[0]["removed_reason"] == "wrong project"
        run(body())

    def test_relinking_the_same_record_does_not_create_a_second_row(self):
        async def body():
            reg, _ = await _registry()
            file_id = (await _register(reg))["file_id"]
            first = await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                           relation_type=m.RELATION_PROJECT, record_id=PROJECT)
            again = await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                           relation_type=m.RELATION_PROJECT, record_id=PROJECT)
            assert again["status"] == STATUS_DUPLICATE
            assert again["relation_id"] == first["relation_id"]
            assert len(await reg.list_relations(file_id)) == 1
        run(body())

    def test_a_relation_to_a_record_that_does_not_exist_here_is_refused(self):
        async def body():
            reg, _ = await _registry()
            file_id = (await _register(reg))["file_id"]
            with pytest.raises(RelationTargetNotFound):
                await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                       relation_type=m.RELATION_PROJECT,
                                       record_id="P-DOES-NOT-EXIST")
        run(body())


# ══════════════════════════════════════════════════════════════ versioning
class TestVersioning:
    def test_a_new_version_never_overwrites_the_old_one(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg, text="v1", name="contract.pdf",
                                       category=m.CATEGORY_CONTRACTS))["file_id"]
            v1 = await reg.current_version(file_id)

            await reg.add_version(actor_id=ACTOR, file_id=file_id, checksum_value=digest("v2"),
                                  size_bytes=2, mime_type="application/pdf",
                                  original_name="contract.pdf", reason="client requested change")

            versions = await reg.list_versions(file_id)
            assert [v["version_no"] for v in versions] == [1, 2]
            stored_v1 = versions[0]
            # every content fact of v1 is byte-identical to what was written
            for field in ("checksum", "size_bytes", "mime_type", "original_name",
                          "created_by", "created_at", "id"):
                assert stored_v1[field] == v1[field]
            # only the successor bookkeeping moved
            assert stored_v1["is_current"] is False
            assert stored_v1["superseded_by_version_no"] == 2
            assert versions[1]["is_current"] is True
            assert versions[1]["supersedes_version_no"] == 1
            assert versions[1]["reason"] == "client requested change"

            head = await db[m.FILES_COLLECTION].find_one({"id": file_id}, {"_id": 0})
            assert head["current_version_no"] == 2 and head["version_count"] == 2
        run(body())

    def test_exactly_one_version_of_a_family_is_current(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg, text="v1"))["file_id"]
            for i in range(2, 6):
                await reg.add_version(actor_id=ACTOR, file_id=file_id,
                                      checksum_value=digest("v%d" % i), size_bytes=i,
                                      mime_type="image/jpeg", original_name="site.jpg",
                                      reason="revision %d" % i)
            current = await db[m.VERSIONS_COLLECTION].find(
                {"file_id": file_id, "is_current": True}, {"_id": 0}).to_list(None)
            assert len(current) == 1 and current[0]["version_no"] == 5
            assert len(await reg.list_versions(file_id)) == 5
        run(body())

    def test_a_signed_version_cannot_be_resealed_but_can_be_followed(self):
        """FLOW-016: an approved/signed version is never REPLACED; a successor is fine."""
        async def body():
            reg, _ = await _registry()
            file_id = (await _register(reg, name="act.pdf", category=m.CATEGORY_ACTS))["file_id"]
            await reg.seal_version(actor_id=ACTOR, file_id=file_id, version_no=1,
                                   approval_state=m.APPROVAL_SIGNED, reason="client signed")
            with pytest.raises(VersionSealed):
                await reg.seal_version(actor_id=ACTOR, file_id=file_id, version_no=1,
                                       approval_state=m.APPROVAL_APPROVED, reason="oops")
            out = await reg.add_version(actor_id=ACTOR, file_id=file_id,
                                        checksum_value=digest("v2"), size_bytes=2,
                                        mime_type="application/pdf", original_name="act.pdf",
                                        reason="annex signed later")
            assert out["version_no"] == 2
            v1 = (await reg.list_versions(file_id))[0]
            assert v1["approval_state"] == m.APPROVAL_SIGNED
            assert v1["checksum"] == digest("photo-bytes")
        run(body())


# ═══════════════════════════════════════════════════════ duplicate checksum
class TestDuplicateChecksum:
    def test_duplicate_behaviour_is_deterministic_and_writes_nothing_by_default(self):
        async def body():
            reg, db = await _registry()
            first = await _register(reg, text="same")
            second = await _register(reg, text="same")
            assert second["status"] == STATUS_DUPLICATE
            assert second["duplicate_of"] == first["file_id"]
            # nothing was written
            assert await db[m.FILES_COLLECTION].count_documents({}) == 1
            assert await db[m.VERSIONS_COLLECTION].count_documents({}) == 1
            # and it is an AUDITED decision, not a silent drop
            events = await db["audit_events"].find({"action": ACTION_REGISTER},
                                                   {"_id": 0}).to_list(None)
            assert any("duplicate" in (e.get("reason") or "") for e in events)
        run(body())

    def test_the_duplicate_answer_is_the_same_whatever_the_storage_order(self):
        """Determinism: a total order over candidates, never 'whichever came back first'."""
        async def body():
            reg, db = await _registry()
            a = await _register(reg, text="same", name="a.jpg")
            b = await _register(reg, text="same", name="b.jpg",
                                on_duplicate=ON_DUPLICATE_NEW_FILE)
            assert b["status"] == STATUS_REGISTERED and b["duplicate_of"] == a["file_id"]
            # three more lookups must all name the SAME oldest candidate
            answers = {(await _register(reg, text="same", name="c.jpg"))["duplicate_of"]
                       for _ in range(3)}
            assert answers == {a["file_id"]}
            candidates = await reg.find_by_checksum(digest("same"))
            assert [c["id"] for c in candidates] == sorted(
                (c["id"] for c in candidates),
                key=lambda i: next(m.sort_key(c) for c in candidates if c["id"] == i))
        run(body())

    def test_an_explicit_caller_may_register_a_second_file_anyway(self):
        async def body():
            reg, db = await _registry()
            await _register(reg, text="same")
            out = await _register(reg, text="same", on_duplicate=ON_DUPLICATE_NEW_FILE)
            assert out["status"] == STATUS_REGISTERED
            assert await db[m.FILES_COLLECTION].count_documents({}) == 2
        run(body())


# ═════════════════════════════════════════════ integrity, cache and originals
class TestIntegrityAndCache:
    async def _with_location(self, reg):
        out = await _register(reg, text="original", relations=[
            {"relation_type": m.RELATION_INVOICE, "record_id": INVOICE},
            {"relation_type": m.RELATION_DEFECT, "record_id": DEFECT}])
        await reg.set_provider_location(
            actor_id=ACTOR, file_id=out["file_id"], version_no=1,
            provider_kind=m.PROVIDER_FAKE_MEMORY, provider_binding_id="bind-1",
            container="tenant-root", object_key="k/1.jpg")
        return out["file_id"]

    def test_a_cached_preview_never_answers_for_a_missing_original(self):
        async def body():
            from app.files.providers.base import IntegrityVerdict
            reg, _ = await _registry()
            file_id = await self._with_location(reg)
            await reg.register_derived(actor_id=ACTOR, file_id=file_id, source_version_no=1,
                                       kind=m.DERIVED_THUMBNAIL, cache_reference="cache/t1")
            await reg.record_integrity_check(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                verdict=IntegrityVerdict(availability=m.AVAILABILITY_MISSING,
                                         checked_at="2026-10-03T00:00:00+00:00",
                                         error="object not found"))
            answer = await reg.canonical_original(file_id)
            assert answer["available"] is False
            assert answer["original_servable"] is False
            assert answer["availability"] == m.AVAILABILITY_MISSING
            # the cache is still listed — and is explicitly not the original
            assert len(answer["derived"]) == 1
            assert answer["derived"][0]["is_canonical_original"] is False
        run(body())

    def test_a_permission_failure_is_not_a_missing_file(self):
        async def body():
            from app.files.providers.base import IntegrityVerdict
            reg, _ = await _registry()
            file_id = await self._with_location(reg)
            out = await reg.record_integrity_check(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                verdict=IntegrityVerdict(availability=m.AVAILABILITY_PERMISSION_DENIED,
                                         checked_at="2026-10-03T00:00:00+00:00"))
            assert out["availability"] == m.AVAILABILITY_PERMISSION_DENIED
            assert out["availability"] != m.AVAILABILITY_MISSING
        run(body())

    def test_an_integrity_failure_names_every_affected_business_record(self):
        async def body():
            from app.files.providers.base import IntegrityVerdict
            reg, db = await _registry()
            file_id = await self._with_location(reg)
            out = await reg.record_integrity_check(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                verdict=IntegrityVerdict(availability=m.AVAILABILITY_CHECKSUM_MISMATCH,
                                         expected_checksum=digest("original"),
                                         observed_checksum=digest("tampered"),
                                         checked_at="2026-10-03T00:00:00+00:00"))
            affected = {(a["relation_type"], a["record_id"]) for a in out["affected_records"]}
            assert affected == {(m.RELATION_INVOICE, INVOICE), (m.RELATION_DEFECT, DEFECT)}
            assert out["severity"] == "critical"
            event = await db["audit_events"].find_one(
                {"action": "file.integrity.checked"}, {"_id": 0})
            assert event["structured_diff"]["treated_as_new_version"] is False
            assert event["result"] == "failure"
            # and NO new version was created from the external change
            assert await db[m.VERSIONS_COLLECTION].count_documents({"file_id": file_id}) == 1
        run(body())


# ═════════════════════════════════════════════════════ provider location
class TestProviderLocation:
    def test_a_provider_migration_keeps_file_id_versions_and_relations(self):
        async def body():
            reg, db = await _registry()
            out = await _register(reg, relations=[
                {"relation_type": m.RELATION_PROJECT, "record_id": PROJECT}])
            file_id = out["file_id"]
            await reg.set_provider_location(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                provider_kind=m.PROVIDER_SYNOLOGY_NAS, provider_binding_id="nas-1",
                container="share", object_key="old/key.jpg")
            moved = await reg.set_provider_location(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                provider_kind=m.PROVIDER_S3_COMPATIBLE, provider_binding_id="s3-1",
                container="bucket", object_key="new/key.jpg", reason="provider migration")
            assert moved["replaced"] is not None

            head = await db[m.FILES_COLLECTION].find_one({"id": file_id}, {"_id": 0})
            assert head["id"] == file_id
            assert len(await reg.list_versions(file_id)) == 1
            assert len(await reg.list_relations(file_id)) == 1
            current = await reg.primary_location(file_id, 1)
            assert current["provider_kind"] == m.PROVIDER_S3_COMPATIBLE
            # the old location is kept as history, not deleted
            assert await db[m.LOCATIONS_COLLECTION].count_documents({"file_id": file_id}) == 2
        run(body())

    def test_a_provider_location_never_carries_a_credential(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg))["file_id"]
            await reg.set_provider_location(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                provider_kind=m.PROVIDER_GOOGLE_DRIVE, provider_binding_id="gd-1",
                container="shared-drive", object_key="k.jpg")
            row = await reg.primary_location(file_id, 1)
            for secret_word in ("secret", "token", "password", "credential", "key_id",
                                "access_key", "refresh"):
                assert not any(secret_word in k.lower() for k in row), row.keys()
        run(body())


# ═══════════════════════════════════════════════════════ delete is a request
class TestPhysicalDelete:
    def test_requesting_a_delete_destroys_nothing_and_claims_nothing(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg, relations=[
                {"relation_type": m.RELATION_INVOICE, "record_id": INVOICE}]))["file_id"]
            out = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                    reason="client asked for erasure")
            head = await db[m.FILES_COLLECTION].find_one({"id": file_id}, {"_id": 0})
            assert head["status"] == m.FILE_DELETE_REQUESTED
            assert out["affected_records"] == 1
            event = await db["audit_events"].find_one(
                {"action": "file.physical_delete.requested"}, {"_id": 0})
            assert event["structured_diff"]["original_destroyed"] is False
            # the file, its version and its relation all still exist
            assert len(await reg.list_versions(file_id)) == 1
            assert len(await reg.list_relations(file_id)) == 1
        run(body())

    def test_only_a_provider_confirmation_marks_an_original_destroyed(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg))["file_id"]
            request = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                        reason="erasure")
            refused = DeleteReceipt(state=m.DELETE_PROVIDER_REFUSED,
                                    provider_kind=m.PROVIDER_FAKE_MEMORY,
                                    response_code="FORBIDDEN", message="no rights")
            out = await reg.record_delete_result(actor_id=ACTOR,
                                                 request_id=request["request_id"],
                                                 receipt=refused)
            assert out["original_destroyed"] is False
            head = await db[m.FILES_COLLECTION].find_one({"id": file_id}, {"_id": 0})
            assert head["status"] == m.FILE_ACTIVE, "a refused delete must not read as deleted"
        run(body())

    def test_a_confirmed_delete_keeps_the_registry_record_and_its_history(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg, relations=[
                {"relation_type": m.RELATION_INVOICE, "record_id": INVOICE}]))["file_id"]
            await reg.set_provider_location(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                provider_kind=m.PROVIDER_FAKE_MEMORY, provider_binding_id="b",
                container="c", object_key="k")
            request = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                        reason="erasure")
            out = await reg.record_delete_result(
                actor_id=ACTOR, request_id=request["request_id"],
                receipt=DeleteReceipt(state=m.DELETE_PROVIDER_CONFIRMED,
                                      provider_kind=m.PROVIDER_FAKE_MEMORY,
                                      response_code="OK", confirmed_at="2026-10-03T00:00:00Z"))
            assert out["original_destroyed"] is True
            head = await db[m.FILES_COLLECTION].find_one({"id": file_id}, {"_id": 0})
            assert head["status"] == m.FILE_DELETED_AT_PROVIDER
            # the history of what it was attached to survives the bytes
            assert len(await reg.list_relations(file_id)) == 1
            assert len(await reg.list_versions(file_id)) == 1
            location = await reg.primary_location(file_id, 1)
            assert location["availability"] == m.AVAILABILITY_MISSING
        run(body())


# ═══════════════════════════════════════════════════════ audit + idempotency
class TestAuditAndIdempotency:
    def test_every_consequential_action_appends_one_audit_event(self):
        async def body():
            from app.audit.store import verify_tenant_chain
            reg, db = await _registry()
            file_id = (await _register(reg))["file_id"]
            await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                   relation_type=m.RELATION_PROJECT, record_id=PROJECT)
            await reg.add_version(actor_id=ACTOR, file_id=file_id, checksum_value=digest("v2"),
                                  size_bytes=2, mime_type="image/jpeg",
                                  original_name="site.jpg", reason="retake")
            await reg.remove_relation(actor_id=ACTOR, file_id=file_id,
                                      relation_type=m.RELATION_PROJECT, record_id=PROJECT,
                                      reason="wrong project")
            actions = [e["action"] for e in
                       await db["audit_events"].find({}, {"_id": 0}).sort("sequence", 1)
                                               .to_list(None)]
            assert actions == ["file.registered", "file.relation.added", "file.version.added",
                               "file.relation.removed"]
            for event in await db["audit_events"].find({}, {"_id": 0}).to_list(None):
                assert event["tenant_id"] == ORG
                assert event["source_flow"] == m.SOURCE_FLOW
            intact, reason = await verify_tenant_chain(db, ORG)
            assert intact, reason
        run(body())

    def test_a_retried_register_under_one_key_writes_once(self):
        async def body():
            reg, db = await _registry()
            first = await _register(reg, idempotency_key="upload-42")
            again = await _register(reg, idempotency_key="upload-42")
            assert first["status"] == STATUS_REGISTERED
            assert again["status"] == STATUS_REPLAYED
            assert again["file_id"] == first["file_id"]
            assert await db[m.FILES_COLLECTION].count_documents({}) == 1
            assert await db["audit_events"].count_documents(
                {"action": ACTION_REGISTER}) == 1
        run(body())

    def test_a_retried_relation_and_version_under_one_key_each_write_once(self):
        async def body():
            reg, db = await _registry()
            file_id = (await _register(reg))["file_id"]
            for _ in range(3):
                await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                       relation_type=m.RELATION_PROJECT, record_id=PROJECT,
                                       idempotency_key="link-1")
            for _ in range(3):
                await reg.add_version(actor_id=ACTOR, file_id=file_id,
                                      checksum_value=digest("v2"), size_bytes=2,
                                      mime_type="image/jpeg", original_name="site.jpg",
                                      reason="retake", idempotency_key="ver-1")
            assert len(await reg.list_relations(file_id)) == 1
            assert len(await reg.list_versions(file_id)) == 2
        run(body())

    def test_one_key_reused_for_a_different_payload_is_a_conflict(self):
        """A retry replays; a DIFFERENT request under the same key is an error."""
        async def body():
            from app.audit.idempotency import IdempotencyConflict
            reg, _ = await _registry()
            await _register(reg, text="first", idempotency_key="k")
            with pytest.raises(IdempotencyConflict):
                await _register(reg, text="second", idempotency_key="k")
        run(body())

    def test_a_failed_attempt_can_be_retried_under_the_same_key(self):
        """A retry of the IDENTICAL request after a failure performs the write.

        The request is byte-identical both times — only the world changed: the
        project the file links to did not exist on the first attempt. This is
        the mobile case the idempotency registry exists for, and it must not be
        confused with the conflict above, where the payload itself differed.
        """
        async def body():
            reg, db = await _registry()
            payload = dict(idempotency_key="k2", relations=[
                {"relation_type": m.RELATION_PROJECT, "record_id": "P-LATE"}])
            with pytest.raises(RelationTargetNotFound):
                await _register(reg, **payload)
            assert await db[m.FILES_COLLECTION].count_documents({}) == 0

            await db["projects"].insert_one({"id": "P-LATE", "org_id": ORG, "name": "Late"})
            out = await _register(reg, **payload)
            assert out["status"] == STATUS_REGISTERED
            assert await db[m.FILES_COLLECTION].count_documents({}) == 1

            # and a THIRD identical call is now a replay, not a second file
            again = await _register(reg, **payload)
            assert again["status"] == STATUS_REPLAYED
            assert await db[m.FILES_COLLECTION].count_documents({}) == 1
        run(body())


# ══════════════════════════════════════════════════════════════ sanity
class TestServiceGuards:
    def test_the_registry_cannot_be_built_without_a_tenant(self):
        with pytest.raises(FileRegistryError):
            FileRegistry(None)

    def test_an_unknown_file_is_not_found_rather_than_invented(self):
        async def body():
            reg, _ = await _registry()
            assert await reg.get_file("file_nope") is None
            with pytest.raises(FileNotFound):
                await reg.require_file("file_nope")
        run(body())

    def test_every_declared_migration_source_names_a_known_collection(self):
        from app.tenancy import ownership
        for key, source in SOURCES_BY_KEY.items():
            assert ownership.classify_collection(source.collection) in (
                ownership.CLASS_ORG, ownership.CLASS_ROOT), key
