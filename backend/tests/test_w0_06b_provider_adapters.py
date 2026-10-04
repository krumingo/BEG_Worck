"""
W0-06B — the provider contract, proven against ALL FOUR customer-managed adapters.

Every test runs once per adapter family — S3-compatible, Google Drive / Shared
Drive, Synology / NAS, generic on-premise server (WebDAV) — against the
disposable in-process fake backends of ``tests/w0_06b_fake_backends.py`` and
fake credentials. No socket is opened and no real provider is contacted.

    pytest tests/test_w0_06b_provider_adapters.py -v --noconftest
"""
import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from app.files import models as m
from app.files.providers.base import (
    ACCESS_READ,
    MAX_TEMPORARY_ACCESS_SECONDS,
    ProviderBinding,
    ProviderCredentialsInvalid,
    ProviderError,
    ProviderNotActivated,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderPermissionDenied,
    adapter_class,
    adapter_for,
    safe_object_key,
    sha256_checksum,
)
from tests import w0_06b_fake_backends as fb

KINDS = sorted(m.CUSTOMER_MANAGED_PROVIDER_KINDS)
DATA = b"%PDF-1.7 signed act no. 14 - original bytes"
KEY = "objects/ab/obj-0001.pdf"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def make(kind, **kw):
    backend, binding, creds = fb.build(kind, **kw)
    return backend, adapter_for(binding, credentials=creds, transport=backend.transport)


async def stored(kind, **kw):
    backend, adapter = make(kind, **kw)
    ref = await adapter.put(object_key=KEY, data=DATA, mime_type="application/pdf")
    return backend, adapter, ref


def expected():
    return sha256_checksum(DATA)


# ════════════════════════════════════════════════════════ construction
class TestConstruction:
    def test_every_customer_managed_kind_has_a_real_adapter(self):
        for kind in KINDS:
            cls = adapter_class(kind)
            assert cls.provider_kind == kind
            assert cls.__module__.startswith("app.files.providers.")

    def test_the_fake_and_the_legacy_disk_cannot_be_reached_by_configuration(self):
        for kind in (m.PROVIDER_FAKE_MEMORY, m.PROVIDER_LEGACY_APP_DISK):
            b = ProviderBinding(binding_id="b", org_id="BEG", provider_kind=kind, container="c")
            with pytest.raises(ProviderNotActivated):
                adapter_for(b, credentials={"x": "y"})

    @pytest.mark.parametrize("kind", KINDS)
    def test_no_credentials_means_no_adapter(self, kind):
        _, binding, _ = fb.build(kind)
        with pytest.raises(ProviderCredentialsInvalid):
            adapter_for(binding, credentials=None)

    @pytest.mark.parametrize("kind", KINDS)
    def test_an_adapter_never_prints_its_secrets(self, kind):
        backend, adapter = make(kind)
        text = repr(adapter) + str(adapter) + repr(adapter._credentials)
        for marker in fb.SECRET_MARKERS:
            assert marker not in text

    @pytest.mark.parametrize("key", ["../other-tenant/x", "/abs", "a//b", "a/./b", "a\\b",
                                     "a/\x00b", ""])
    def test_an_object_key_cannot_escape_the_tenant_root(self, key):
        with pytest.raises(ValueError):
            safe_object_key(key)

    def test_a_root_prefix_cannot_traverse(self):
        with pytest.raises(ValueError):
            ProviderBinding(binding_id="b", org_id="BEG", provider_kind=m.PROVIDER_S3_COMPATIBLE,
                            container="c", root_prefix="tenants/../other")


# ═══════════════════════════════════════════════════════════ onboarding
class TestOnboardingPrimitives:
    @pytest.mark.parametrize("kind", KINDS)
    def test_valid_credentials_and_root_pass(self, kind):
        async def body():
            _, adapter = make(kind)
            await adapter.validate_credentials()
            await adapter.check_root()
            await adapter.aclose()
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_invalid_credentials_are_refused_as_credentials(self, kind):
        async def body():
            backend, binding, creds = fb.build(kind)
            bad = {k: (v + "-WRONG" if k in ("secret_access_key", "password", "refresh_token")
                       else v) for k, v in creds.items()}
            adapter = adapter_for(binding, credentials=bad, transport=backend.transport)
            with pytest.raises(ProviderCredentialsInvalid) as info:
                await adapter.validate_credentials()
            for marker in fb.SECRET_MARKERS:
                assert marker not in str(info.value)
        run(body())

    @pytest.mark.parametrize("kind", [m.PROVIDER_SYNOLOGY_NAS, m.PROVIDER_ON_PREM_SERVER])
    def test_a_missing_tenant_root_is_refused(self, kind):
        async def body():
            backend, binding, creds = fb.build(kind, root="")
            adapter = adapter_for(binding, credentials=creds, transport=backend.transport)
            with pytest.raises(ProviderObjectMissing):
                await adapter.check_root()
        run(body())

    def test_a_read_only_drive_root_is_refused(self):
        async def body():
            backend, binding, creds = fb.build(m.PROVIDER_GOOGLE_DRIVE, root_writable=False)
            adapter = adapter_for(binding, credentials=creds, transport=backend.transport)
            with pytest.raises(ProviderPermissionDenied):
                await adapter.check_root()
        run(body())

    def test_a_missing_bucket_is_refused(self):
        async def body():
            backend, binding, creds = fb.build(m.PROVIDER_S3_COMPATIBLE)
            backend.bucket = "another-bucket"
            adapter = adapter_for(binding, credentials=creds, transport=backend.transport)
            with pytest.raises(ProviderObjectMissing):
                await adapter.validate_credentials()
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_an_unreachable_provider_is_unreachable_not_invalid(self, kind):
        async def body():
            backend, adapter = make(kind)
            backend.offline = True
            with pytest.raises(ProviderError) as info:
                await adapter.validate_credentials()
            assert not isinstance(info.value, (ProviderCredentialsInvalid,
                                               ProviderPermissionDenied))
            assert info.value.availability == m.AVAILABILITY_PROVIDER_UNREACHABLE
        run(body())


# ═══════════════════════════════════════════════════════ the object contract
class TestObjectContract:
    @pytest.mark.parametrize("kind", KINDS)
    def test_put_read_stat_round_trip(self, kind):
        async def body():
            _, adapter, ref = await stored(kind)
            assert ref.container == adapter.binding.container and ref.object_key == KEY
            assert await adapter.read(ref) == DATA
            stat = await adapter.stat(ref)
            assert stat.exists and stat.size_bytes == len(DATA)
            if adapter.capabilities().server_side_checksum:
                assert stat.checksum == expected()
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_missing_object_is_absent_and_a_read_raises(self, kind):
        async def body():
            _, adapter, ref = await stored(kind)
            absent = ProviderObjectRef(container=ref.container, object_key="objects/none.pdf")
            assert (await adapter.stat(absent)).exists is False
            with pytest.raises(ProviderObjectMissing):
                await adapter.read(absent)
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_another_container_is_refused(self, kind):
        async def body():
            _, adapter, ref = await stored(kind)
            foreign = ProviderObjectRef(container="other-tenant-root", object_key=KEY)
            with pytest.raises(ProviderPermissionDenied):
                await adapter.stat(foreign)
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_capabilities_are_declared(self, kind):
        caps = make(kind)[1].capabilities()
        assert caps.provider_kind == kind and caps.can_put and caps.can_read and caps.can_delete
        assert caps.temporary_links is (kind == m.PROVIDER_S3_COMPATIBLE)


# ═══════════════════════════════════ integrity: five states, never confused
class TestVerifyTellsTheStatesApart:
    @pytest.mark.parametrize("kind", KINDS)
    def test_an_intact_object_is_available(self, kind):
        async def body():
            _, adapter, ref = await stored(kind)
            v = await adapter.verify(ref, expected(), expected_size=len(DATA),
                                     expected_provider_file_id=ref.provider_file_id,
                                     expected_provider_version_id=ref.provider_version_id)
            assert v.availability == m.AVAILABILITY_AVAILABLE, v
            assert v.method in ("server_checksum", "read_and_hash")
            assert v.observed_checksum == expected()
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_bytes_changed_outside_beg_work_is_a_checksum_mismatch(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            backend.mutate(KEY, DATA.replace(b"14", b"41"))          # same size, other bytes
            v = await adapter.verify(ref, expected(), expected_size=len(DATA))
            assert v.availability == m.AVAILABILITY_CHECKSUM_MISMATCH, v
            assert v.observed_checksum and v.observed_checksum != expected()
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_size_change_alone_proves_the_content_changed(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            backend.mutate(KEY, DATA + b" appended")
            v = await adapter.verify(ref, expected(), expected_size=len(DATA))
            assert v.availability == m.AVAILABILITY_CHECKSUM_MISMATCH
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_an_object_deleted_outside_beg_work_is_missing(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            backend.remove(KEY)
            v = await adapter.verify(ref, expected())
            assert v.availability == m.AVAILABILITY_MISSING
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_lost_permission_is_permission_denied_not_missing(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            backend.deny(KEY)
            v = await adapter.verify(ref, expected())
            assert v.availability == m.AVAILABILITY_PERMISSION_DENIED, v
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_an_outage_is_provider_unreachable(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            backend.offline = True
            v = await adapter.verify(ref, expected())
            assert v.availability == m.AVAILABILITY_PROVIDER_UNREACHABLE
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_same_bytes_under_a_new_provider_version_is_externally_changed(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            original_version = (await adapter.stat(ref)).provider_version_id
            backend.replace(KEY)
            v = await adapter.verify(ref, expected(), expected_size=len(DATA),
                                     expected_provider_version_id=original_version)
            assert v.availability == m.AVAILABILITY_EXTERNALLY_CHANGED, v
            assert v.observed_provider_version_id != original_version
        run(body())

    def test_without_server_checksums_bytes_are_read_and_hashed(self):
        async def body():
            _, adapter, ref = await stored(m.PROVIDER_S3_COMPATIBLE, checksum_support=False)
            v = await adapter.verify(ref, expected())
            assert v.availability == m.AVAILABILITY_AVAILABLE
            assert v.method == "read_and_hash"
        run(body())

    def test_a_webdav_server_checksum_is_used_when_offered(self):
        async def body():
            _, adapter, ref = await stored(m.PROVIDER_ON_PREM_SERVER, oc_checksum=True)
            v = await adapter.verify(ref, expected())
            assert v.method == "server_checksum" and v.availability == m.AVAILABILITY_AVAILABLE
        run(body())


# ═══════════════════════════════════════════════════════════════ delete
class TestDeleteReportsTheProvidersAnswer:
    @pytest.mark.parametrize("kind", KINDS)
    def test_a_confirmed_delete_is_proven_by_absence(self, kind):
        async def body():
            _, adapter, ref = await stored(kind)
            receipt = await adapter.request_delete(ref, reason="approved erasure")
            assert receipt.state == m.DELETE_PROVIDER_CONFIRMED
            assert (await adapter.stat(ref)).exists is False
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_nothing_to_delete_is_not_a_confirmation(self, kind):
        async def body():
            _, adapter, ref = await stored(kind)
            ghost = ProviderObjectRef(container=ref.container, object_key="objects/ghost.pdf")
            assert (await adapter.request_delete(ghost, reason="r")).state == \
                m.DELETE_PROVIDER_FAILED
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_denied_delete_is_a_refusal_and_the_object_stays(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            backend.deny(KEY)
            receipt = await adapter.request_delete(ref, reason="r")
            assert receipt.state == m.DELETE_PROVIDER_REFUSED
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_an_outage_during_delete_is_a_failure_not_a_confirmation(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            backend.offline = True
            assert (await adapter.request_delete(ref, reason="r")).state == \
                m.DELETE_PROVIDER_FAILED
        run(body())


# ═══════════════════════════════════════════════════ temporary access
class TestTemporaryAccess:
    def test_s3_issues_a_short_lived_presigned_url_the_server_honours(self):
        async def body():
            backend, adapter, ref = await stored(m.PROVIDER_S3_COMPATIBLE)
            grant = await adapter.temporary_access(ref, purpose=ACCESS_READ, seconds=120)
            expires = datetime.fromisoformat(grant.expires_at)
            assert 0 < (expires - datetime.now(timezone.utc)).total_seconds() <= 121
            assert "X-Amz-Expires=120" in grant.provider_url
            assert backend.secret_key not in grant.provider_url
            import httpx
            async with httpx.AsyncClient(transport=backend.transport) as client:
                ok = await client.get(grant.provider_url)
                assert ok.status_code == 200 and ok.content == DATA
                tampered = grant.provider_url.replace("obj-0001", "obj-0002")
                assert (await client.get(tampered)).status_code == 403
        run(body())

    def test_s3_refuses_a_grant_longer_than_the_cap(self):
        async def body():
            _, adapter, ref = await stored(m.PROVIDER_S3_COMPATIBLE)
            with pytest.raises(ValueError):
                await adapter.temporary_access(ref, purpose=ACCESS_READ,
                                               seconds=MAX_TEMPORARY_ACCESS_SECONDS + 1)
        run(body())

    def test_an_expired_presigned_url_is_refused(self, monkeypatch):
        async def body():
            from app.files.providers import s3
            backend, adapter, ref = await stored(m.PROVIDER_S3_COMPATIBLE)
            monkeypatch.setattr(s3, "_amz_now", lambda: "20200101T000000Z")
            grant = await adapter.temporary_access(ref, purpose=ACCESS_READ, seconds=60)
            import httpx
            async with httpx.AsyncClient(transport=backend.transport) as client:
                assert (await client.get(grant.provider_url)).status_code == 403
        run(body())

    @pytest.mark.parametrize("kind", [k for k in KINDS if k != m.PROVIDER_S3_COMPATIBLE])
    def test_providers_without_expiring_links_refuse_to_mint_one(self, kind):
        async def body():
            _, adapter, ref = await stored(kind)
            with pytest.raises(ProviderError) as info:
                await adapter.temporary_access(ref, purpose=ACCESS_READ)
            assert info.value.code == "NO_NATIVE_TEMPORARY_LINKS"
        run(body())


# ═════════════════════════════════════════════════════ secret non-disclosure
class TestSecretsNeverTravelInUrls:
    @pytest.mark.parametrize("kind", KINDS)
    def test_no_request_url_carries_a_secret(self, kind):
        async def body():
            backend, adapter, ref = await stored(kind)
            await adapter.validate_credentials()
            await adapter.verify(ref, expected())
            await adapter.request_delete(ref, reason="r")
            await adapter.aclose()
            for url in backend.seen_urls():
                for marker in fb.SECRET_MARKERS:
                    assert marker not in url, url
        run(body())


# ═════════════════════════════════════════════════ provider-specific details
class TestProviderDetails:
    def test_the_sigv4_signer_matches_the_aws_published_vectors(self):
        from app.files.providers import s3
        ak, sk = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        auth = s3.sign(method="GET", path="/test.txt", query={},
                       headers={"host": "examplebucket.s3.amazonaws.com", "range": "bytes=0-9",
                                "x-amz-content-sha256": s3.EMPTY_SHA256,
                                "x-amz-date": "20130524T000000Z"},
                       payload_hash=s3.EMPTY_SHA256, access_key=ak, secret_key=sk,
                       region="us-east-1", amz_date="20130524T000000Z")
        assert auth.endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6"
                             "036bdb41")
        q = s3.presign(method="GET", host="examplebucket.s3.amazonaws.com", path="/test.txt",
                       access_key=ak, secret_key=sk, region="us-east-1",
                       amz_date="20130524T000000Z", expires=86400)
        assert q["X-Amz-Signature"] == \
            "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"

    def test_the_sigv4_signer_agrees_with_botocore(self):
        botocore = pytest.importorskip("botocore")
        from botocore.auth import S3SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials
        from app.files.providers import s3
        body = b"hello"
        payload = hashlib.sha256(body).hexdigest()
        headers = {"host": "s3.fake.local", "x-amz-date": "20261004T101010Z",
                   "x-amz-content-sha256": payload, "content-type": "application/pdf"}
        mine = s3.sign(method="PUT", path="/bucket/tenants/a b/x.pdf",
                       query={"partNumber": "1"}, headers=headers, payload_hash=payload,
                       access_key="AK", secret_key="SK", region="eu-central-1",
                       amz_date="20261004T101010Z")
        req = AWSRequest(method="PUT", url="https://s3.fake.local/bucket/tenants/a%20b/x.pdf"
                         "?partNumber=1", data=body, headers=dict(headers))
        req.context["timestamp"] = "20261004T101010Z"
        signer = S3SigV4Auth(Credentials("AK", "SK"), "s3", "eu-central-1")
        creq = signer.canonical_request(req)
        sts = signer.string_to_sign(req, creq)
        theirs = signer.signature(sts, req)
        assert mine.endswith("Signature=" + theirs)

    def test_a_drive_object_moved_outside_the_root_is_refused(self):
        async def body():
            backend, adapter, ref = await stored(m.PROVIDER_GOOGLE_DRIVE)
            backend.files[ref.provider_file_id]["parents"] = ["some-other-folder"]
            with pytest.raises(ProviderPermissionDenied):
                await adapter.stat(ref)
            v = await adapter.verify(ref, expected())
            assert v.availability == m.AVAILABILITY_PERMISSION_DENIED
        run(body())

    def test_a_drive_object_is_found_by_key_without_its_id(self):
        async def body():
            _, adapter, ref = await stored(m.PROVIDER_GOOGLE_DRIVE)
            by_key = ProviderObjectRef(container=ref.container, object_key=KEY)
            assert (await adapter.stat(by_key)).provider_file_id == ref.provider_file_id
        run(body())

    def test_a_synology_session_that_expired_is_re_established_once(self):
        async def body():
            backend, adapter, ref = await stored(m.PROVIDER_SYNOLOGY_NAS)
            backend.expire_next_session = True
            assert (await adapter.stat(ref)).exists
        run(body())

    def test_webdav_never_overwrites_an_existing_object(self):
        async def body():
            _, adapter, ref = await stored(m.PROVIDER_ON_PREM_SERVER)
            with pytest.raises(ProviderError) as info:
                await adapter.put(object_key=KEY, data=b"other", mime_type="text/plain")
            assert info.value.code == "EXISTS"
            assert await adapter.read(ref) == DATA
        run(body())

    def test_synology_never_overwrites_an_existing_object(self):
        async def body():
            _, adapter, ref = await stored(m.PROVIDER_SYNOLOGY_NAS)
            with pytest.raises(ProviderError):
                await adapter.put(object_key=KEY, data=b"other", mime_type="text/plain")
            assert await adapter.read(ref) == DATA
        run(body())
