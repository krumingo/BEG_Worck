"""
W0-06A — the storage provider contract, proven against the in-memory adapter.

FLOW-016 makes the tenant's own storage the home of the originals, so the
registry must work the same way whichever provider a tenant brings. "Must" is
worth nothing without a full implementation to run the contract against: this
file runs it against :class:`app.files.providers.fake.FakeStorageProvider`,
which is the only concrete adapter W0-06A ships, and against the four declared
customer-managed adapters, which must all refuse to do anything at all.

What the contract has to hold:

* put / read / stat / verify / request_delete / temporary_access all behave as
  the interface says, and capability reporting tells the truth;
* a temporary grant is short-lived, single-purpose and never a permanent URL;
* a provider failure is reported as the RIGHT state — a lost permission, a
  deleted object and an outage are three different answers, not one;
* an externally mutated object produces a checksum mismatch, and the registry
  turns that into an integrity problem, never a new version;
* the registry drives any adapter through the location it stored, so the same
  registry code works unchanged against a different provider;
* the four customer-managed adapters are DECLARED and NOT ACTIVATED — W0-06A
  touches no credential, no NAS, no Drive and no bucket.

    pytest tests/test_w0_06a_provider_contract.py -v --noconftest
"""
import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from app.files import models as m
from app.files.providers import base
from app.files.providers.base import (
    ACCESS_PREVIEW,
    ACCESS_READ,
    DECLARED_ADAPTERS,
    MAX_TEMPORARY_ACCESS_SECONDS,
    ProviderBinding,
    ProviderError,
    ProviderNotActivated,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderPermissionDenied,
    adapter_for,
    expiry_for,
)
from app.files.providers.fake import FakeStorageProvider, sha256_of
from app.files.registry import FileRegistry
from app.tenancy.data_access import TenantData

pytest.importorskip("mongomock_motor")

ORG = "BEG"
ACTOR = "user-1"
PROJECT = "P-1"
CONTENT = b"the original bytes of a signed contract"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def binding(org=ORG, kind=m.PROVIDER_FAKE_MEMORY, container="tenant-root"):
    return ProviderBinding(binding_id="bind-1", org_id=org, provider_kind=kind,
                           container=container, secret_reference="vault://tenant/BEG/storage")


async def _stored(adapter=None):
    adapter = adapter or FakeStorageProvider(binding())
    ref = await adapter.put(object_key="k/contract.pdf", data=CONTENT,
                            mime_type="application/pdf")
    return adapter, ref


# ══════════════════════════════════════════════════════════ the binding
class TestBinding:
    def test_a_binding_never_holds_the_secret_itself(self):
        b = binding()
        assert b.secret_reference.startswith("vault://")
        for field in b.__dataclass_fields__:
            assert "secret_value" not in field
        # the reference is a locator, and the object carries nothing else secret
        assert set(b.__dataclass_fields__) == {
            "binding_id", "org_id", "provider_kind", "container", "secret_reference",
            "root_prefix"}

    def test_a_binding_requires_an_owner_a_container_and_a_known_provider(self):
        for kwargs in ({"org_id": ""}, {"container": ""}, {"binding_id": ""}):
            with pytest.raises(ValueError):
                ProviderBinding(binding_id=kwargs.get("binding_id", "b"),
                                org_id=kwargs.get("org_id", ORG),
                                provider_kind=m.PROVIDER_FAKE_MEMORY,
                                container=kwargs.get("container", "c"))
        with pytest.raises(ValueError):
            ProviderBinding(binding_id="b", org_id=ORG, provider_kind="dropbox", container="c")

    def test_an_adapter_refuses_a_binding_for_another_provider(self):
        with pytest.raises(ValueError):
            FakeStorageProvider(binding(kind=m.PROVIDER_S3_COMPATIBLE))


# ═══════════════════════════════════════════════════════ the full contract
class TestContract:
    def test_put_read_stat_round_trip(self):
        async def body():
            adapter, ref = await _stored()
            assert ref.container == "tenant-root"
            assert ref.object_key == "k/contract.pdf"
            assert ref.provider_file_id
            assert await adapter.read(ref) == CONTENT
            stat = await adapter.stat(ref)
            assert stat.exists and stat.size_bytes == len(CONTENT)
            assert stat.checksum == sha256_of(CONTENT)
        run(body())

    def test_capabilities_are_declared_not_assumed(self):
        caps = FakeStorageProvider(binding()).capabilities()
        assert caps.provider_kind == m.PROVIDER_FAKE_MEMORY
        assert caps.server_side_checksum is True and caps.temporary_links is True
        assert set(caps.as_dict()) >= {"can_put", "can_read", "can_stat", "can_delete",
                                       "server_side_checksum", "native_file_ids",
                                       "temporary_links", "versioning"}

    def test_a_missing_object_is_missing_and_a_read_raises(self):
        async def body():
            adapter, _ = await _stored()
            absent = ProviderObjectRef(container="tenant-root", object_key="k/none.pdf")
            assert (await adapter.stat(absent)).exists is False
            with pytest.raises(ProviderObjectMissing):
                await adapter.read(absent)
        run(body())

    def test_a_binding_cannot_reach_another_container(self):
        """A provider account reaches ONE container. This is the adapter-level
        half of tenant isolation: a reference naming someone else's container is
        refused before any byte is read."""
        async def body():
            adapter, _ = await _stored()
            foreign = ProviderObjectRef(container="another-tenant-root",
                                        object_key="k/contract.pdf")
            with pytest.raises(ProviderPermissionDenied):
                await adapter.read(foreign)
            with pytest.raises(ProviderPermissionDenied):
                await adapter.stat(foreign)
        run(body())

    def test_the_three_failure_modes_are_three_different_answers(self):
        async def body():
            adapter, ref = await _stored()
            assert (await adapter.verify(ref, sha256_of(CONTENT))).availability == \
                m.AVAILABILITY_AVAILABLE

            adapter.simulate_permission_loss(ref)
            assert (await adapter.verify(ref, sha256_of(CONTENT))).availability == \
                m.AVAILABILITY_PERMISSION_DENIED
            adapter.simulate_permission_restored(ref)

            adapter.simulate_outage(True)
            assert (await adapter.verify(ref, sha256_of(CONTENT))).availability == \
                m.AVAILABILITY_PROVIDER_UNREACHABLE
            adapter.simulate_outage(False)

            adapter.simulate_external_delete(ref)
            assert (await adapter.verify(ref, sha256_of(CONTENT))).availability == \
                m.AVAILABILITY_MISSING
        run(body())

    def test_an_externally_mutated_object_is_a_checksum_mismatch(self):
        async def body():
            adapter, ref = await _stored()
            adapter.simulate_external_mutation(ref, b"somebody edited this in Drive")
            verdict = await adapter.verify(ref, sha256_of(CONTENT))
            assert verdict.availability == m.AVAILABILITY_CHECKSUM_MISMATCH
            assert verdict.expected_checksum == sha256_of(CONTENT)
            assert verdict.observed_checksum != verdict.expected_checksum
            assert verdict.ok is False
        run(body())

    def test_a_delete_receipt_always_carries_the_providers_own_answer(self):
        async def body():
            adapter, ref = await _stored()
            receipt = await adapter.request_delete(ref, reason="client erasure request")
            assert receipt.state == m.DELETE_PROVIDER_CONFIRMED
            assert receipt.confirmed_at
            assert adapter.object_count() == 0
            # deleting what is not there is NOT a confirmed destruction
            again = await adapter.request_delete(ref, reason="again")
            assert again.state == m.DELETE_PROVIDER_FAILED
            assert again.response_code == "NOT_FOUND"
        run(body())

    def test_a_delete_receipt_cannot_be_constructed_without_an_answer(self):
        with pytest.raises(ValueError):
            base.DeleteReceipt(state=m.DELETE_REQUESTED, provider_kind=m.PROVIDER_FAKE_MEMORY)

    def test_temporary_access_is_short_lived_single_purpose_and_not_a_public_url(self):
        async def body():
            adapter, ref = await _stored()
            grant = await adapter.temporary_access(ref, purpose=ACCESS_READ, seconds=60)
            assert grant.purpose == ACCESS_READ
            assert grant.provider_url is None
            expires = datetime.fromisoformat(grant.expires_at)
            delta = (expires - datetime.now(timezone.utc)).total_seconds()
            assert 0 < delta <= 60 + 5
            with pytest.raises(ValueError):
                await adapter.temporary_access(ref, purpose="forever", seconds=60)
            with pytest.raises(ValueError):
                await adapter.temporary_access(ref, purpose=ACCESS_PREVIEW,
                                               seconds=MAX_TEMPORARY_ACCESS_SECONDS + 1)
            with pytest.raises(ValueError):
                expiry_for(0)
        run(body())

    def test_the_interface_offers_no_way_to_mint_a_permanent_url(self):
        """FLOW-016: a permanent public URL is never an access right.

        Asserted on the interface itself rather than on its prose: the only
        thing that hands back a link is ``temporary_access``, every grant
        carries an expiry, and no adapter method is named for a durable link.
        """
        grant_fields = set(base.TemporaryAccessGrant.__dataclass_fields__)
        assert "expires_at" in grant_fields
        assert not {"public_url", "permanent_url", "share_link"} & grant_fields
        methods = {name for name in dir(base.StorageProviderAdapter)
                   if not name.startswith("_")}
        assert not {"public_url", "permanent_url", "share_link", "make_public"} & methods
        assert "temporary_access" in methods
        # and an expiry is mandatory: a grant cannot be built without one
        with pytest.raises(TypeError):
            base.TemporaryAccessGrant(purpose=ACCESS_READ, token="t",
                                      container="c", object_key="k")

    def test_a_failed_put_raises_and_stores_nothing(self):
        async def body():
            adapter = FakeStorageProvider(binding())
            adapter.fail_next_put = True
            with pytest.raises(ProviderError):
                await adapter.put(object_key="k/x", data=b"x", mime_type="text/plain")
            assert adapter.object_count() == 0
            # the retry succeeds
            await adapter.put(object_key="k/x", data=b"x", mime_type="text/plain")
            assert adapter.object_count() == 1
        run(body())


# ══════════════════════════════════════════════ declared, not activated
class TestDeclaredAdaptersAreNotActivated:
    def test_every_customer_managed_provider_has_an_adapter_class(self):
        assert set(DECLARED_ADAPTERS) == set(m.CUSTOMER_MANAGED_PROVIDER_KINDS)
        assert set(DECLARED_ADAPTERS) == {m.PROVIDER_GOOGLE_DRIVE, m.PROVIDER_SYNOLOGY_NAS,
                                          m.PROVIDER_S3_COMPATIBLE, m.PROVIDER_ON_PREM_SERVER}

    @pytest.mark.parametrize("kind", sorted(m.CUSTOMER_MANAGED_PROVIDER_KINDS))
    def test_a_declared_adapter_refuses_every_operation(self, kind):
        async def body():
            adapter = adapter_for(ProviderBinding(binding_id="b", org_id=ORG,
                                                  provider_kind=kind, container="c"))
            ref = ProviderObjectRef(container="c", object_key="k")
            for call in (adapter.put(object_key="k", data=b"x", mime_type="text/plain"),
                         adapter.read(ref), adapter.stat(ref), adapter.verify(ref),
                         adapter.request_delete(ref, reason="r"),
                         adapter.temporary_access(ref, purpose=ACCESS_READ)):
                with pytest.raises(ProviderNotActivated):
                    await call
            caps = adapter.capabilities()
            assert caps.can_put is False and caps.can_read is False
        run(body())

    def test_the_fake_provider_cannot_be_reached_by_configuration(self):
        with pytest.raises(ProviderNotActivated):
            adapter_for(binding(kind=m.PROVIDER_FAKE_MEMORY))

    def test_the_fake_is_not_a_customer_managed_provider(self):
        assert m.PROVIDER_FAKE_MEMORY not in m.CUSTOMER_MANAGED_PROVIDER_KINDS
        assert m.PROVIDER_LEGACY_APP_DISK not in m.CUSTOMER_MANAGED_PROVIDER_KINDS


# ══════════════════════════════════ the registry drives any adapter the same
class TestRegistryIsProviderNeutral:
    async def _registry(self):
        from mongomock_motor import AsyncMongoMockClient
        db = AsyncMongoMockClient()["w0_06a_contract"]
        await db["projects"].insert_one({"id": PROJECT, "org_id": ORG, "name": "Site"})
        return FileRegistry(TenantData(db, ORG)), db

    async def _file_on(self, reg, adapter, container="tenant-root"):
        ref = await adapter.put(object_key="k/contract.pdf", data=CONTENT,
                                mime_type="application/pdf")
        out = await reg.register_file(
            actor_id=ACTOR, display_name="contract.pdf", original_name="contract.pdf",
            category=m.CATEGORY_CONTRACTS, checksum_value=sha256_of(CONTENT),
            size_bytes=len(CONTENT), mime_type="application/pdf",
            relations=[{"relation_type": m.RELATION_PROJECT, "record_id": PROJECT}],
            provider_location={"provider_kind": adapter.provider_kind,
                               "provider_binding_id": adapter.binding.binding_id,
                               "container": container, "object_key": ref.object_key,
                               "provider_file_id": ref.provider_file_id})
        return out["file_id"], ref

    def test_a_check_through_the_adapter_records_the_verdict(self):
        async def body():
            reg, _ = await self._registry()
            adapter = FakeStorageProvider(binding())
            file_id, _ = await self._file_on(reg, adapter)
            out = await reg.verify_with_adapter(actor_id=ACTOR, file_id=file_id,
                                                version_no=1, adapter=adapter)
            assert out["availability"] == m.AVAILABILITY_AVAILABLE
            answer = await reg.canonical_original(file_id)
            assert answer["available"] is True and answer["original_servable"] is True
        run(body())

    def test_an_external_mutation_becomes_an_integrity_problem_not_a_version(self):
        async def body():
            reg, db = await self._registry()
            adapter = FakeStorageProvider(binding())
            file_id, ref = await self._file_on(reg, adapter)
            adapter.simulate_external_mutation(ref, b"changed outside BEG_Work")

            out = await reg.verify_with_adapter(actor_id=ACTOR, file_id=file_id,
                                                version_no=1, adapter=adapter)
            assert out["availability"] == m.AVAILABILITY_CHECKSUM_MISMATCH
            assert len(await reg.list_versions(file_id)) == 1, \
                "an external change must never become a new version"
            answer = await reg.canonical_original(file_id)
            assert answer["available"] is False
            assert [a["record_id"] for a in out["affected_records"]] == [PROJECT]
        run(body())

    def test_the_registry_never_hands_the_adapter_a_business_identifier(self):
        """The provider learns a container and an object key, nothing else."""
        async def body():
            reg, _ = await self._registry()
            adapter = FakeStorageProvider(binding())
            file_id, _ = await self._file_on(reg, adapter)
            adapter.calls.clear()
            await reg.verify_with_adapter(actor_id=ACTOR, file_id=file_id, version_no=1,
                                          adapter=adapter)
            for _, object_key in adapter.calls:
                assert file_id not in object_key
                assert PROJECT not in object_key
                assert ORG not in object_key
        run(body())

    def test_the_same_registry_code_works_against_a_second_container(self):
        async def body():
            reg, _ = await self._registry()
            first = FakeStorageProvider(binding(container="nas-share"))
            second = FakeStorageProvider(
                ProviderBinding(binding_id="bind-2", org_id=ORG,
                                provider_kind=m.PROVIDER_FAKE_MEMORY, container="s3-bucket"))
            file_id, _ = await self._file_on(reg, first, container="nas-share")
            moved = await second.put(object_key="migrated/contract.pdf", data=CONTENT,
                                     mime_type="application/pdf")
            await reg.set_provider_location(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                provider_kind=second.provider_kind, provider_binding_id="bind-2",
                container="s3-bucket", object_key=moved.object_key,
                reason="provider migration")
            out = await reg.verify_with_adapter(actor_id=ACTOR, file_id=file_id,
                                                version_no=1, adapter=second)
            assert out["availability"] == m.AVAILABILITY_AVAILABLE
            # identity and relations survived the move
            assert (await reg.require_file(file_id))["id"] == file_id
            assert len(await reg.list_relations(file_id)) == 1
        run(body())

    def test_replaying_the_same_verdict_records_it_once(self):
        async def body():
            reg, db = await self._registry()
            adapter = FakeStorageProvider(binding())
            file_id, _ = await self._file_on(reg, adapter)
            verdict = base.IntegrityVerdict(availability=m.AVAILABILITY_AVAILABLE,
                                            checked_at="2026-10-03T00:00:00+00:00")
            for _ in range(3):
                await reg.record_integrity_check(
                    actor_id=ACTOR, file_id=file_id, version_no=1, verdict=verdict,
                    idempotency_key="check-1")
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.checked"}) == 1
            location = await reg.primary_location(file_id, 1)
            assert location["availability"] == m.AVAILABILITY_AVAILABLE
        run(body())

    def test_a_different_verdict_under_the_same_key_is_a_conflict(self):
        """Two different results cannot both be "the same check".

        Reusing one key for a second, different verdict is a caller bug, and
        the registry must say so rather than silently keep one of the two: the
        availability of a customer's original is not something to guess at.
        """
        async def body():
            from app.audit.idempotency import IdempotencyConflict
            reg, _ = await self._registry()
            adapter = FakeStorageProvider(binding())
            file_id, _ = await self._file_on(reg, adapter)
            await reg.verify_with_adapter(actor_id=ACTOR, file_id=file_id, version_no=1,
                                          adapter=adapter, idempotency_key="check-1")
            with pytest.raises(IdempotencyConflict):
                await reg.record_integrity_check(
                    actor_id=ACTOR, file_id=file_id, version_no=1,
                    verdict=base.IntegrityVerdict(availability=m.AVAILABILITY_MISSING,
                                                  checked_at="2026-10-03T00:00:00+00:00"),
                    idempotency_key="check-1")
            # the first verdict stands; nothing was half-applied
            location = await reg.primary_location(file_id, 1)
            assert location["availability"] == m.AVAILABILITY_AVAILABLE
        run(body())
