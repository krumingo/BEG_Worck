"""
W0-06B — tenant storage bindings, the credential vault and the onboarding gate.

FLOW-016 §"Onboarding gate": activation is BLOCKED until every step passed —
provider selected, credentials valid, tenant-specific root verified, temporary
object uploaded and read back, checksum round-trip matched, test object cleaned
up, Primary recorded in the Tenant Registry, AuditEvent written and the
customer-vs-BEG_Work responsibility boundary accepted. Each step is broken
deliberately here and each break must leave the tenant inactive.

All four adapter families run against in-process fakes with fake credentials.

    pytest tests/test_w0_06b_storage_onboarding.py -v --noconftest
"""
import asyncio
import base64
import json

import pytest

from app.files import models as m
from app.files.authorization import FileAccessDenied
from app.files.credentials import (
    CredentialRejected,
    CredentialReferenceInvalid,
    CredentialVault,
    CredentialVaultUnavailable,
    ENV_MASTER_KEY,
)
from app.files.storage import (
    BINDING_ACTIVE,
    BINDING_VERIFICATION_FAILED,
    RESPONSIBILITY_VERSION,
    STEPS,
    StorageConfigurationRefused,
    StorageNotActive,
    public_view,
)
from app.tenancy.data_access import TenantData
from tests import w0_06b_fake_backends as fb
from tests.w0_06b_support import (
    A, B, MASTER_KEY, OWNER_A, OWNER_B, WORKER_A, accepted, configure, ctx,
    install_permissions, service_for, world,
)

pytest.importorskip("mongomock_motor")

KINDS = sorted(m.CUSTOMER_MANAGED_PROVIDER_KINDS)


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _perms(monkeypatch):
    install_permissions(monkeypatch)


async def _setup(kind, **kw):
    db, sysdb = await world()
    backends = {}
    svc = service_for(db, sysdb, A, backends)
    binding_id, backend = await configure(svc, OWNER_A, kind, **kw)
    backends[binding_id] = backend
    return db, sysdb, svc, binding_id, backend


async def _assert_blocked(db, sysdb, svc, binding_id, out, step, code=None):
    assert out["activated"] is False, out
    assert out["failed_step"] == step, out
    if code:
        assert out["code"] == code, out
    row = await svc.get_binding(binding_id)
    assert row["status"] == BINDING_VERIFICATION_FAILED
    reg = await sysdb["tenant_registry"].find_one({"id": A}, {"_id": 0})
    assert reg["storage_status"] != "active"
    assert reg.get("primary_storage_provider_reference") is None
    with pytest.raises(StorageNotActive):
        await svc.adapter()
    ev = await db["audit_events"].find_one({"action": "storage.provider.verification_failed"},
                                           {"_id": 0})
    assert ev and ev["structured_diff"]["failed_step"] == step and ev["result"] == "failure"
    run_row = await svc.runs.find_one({"id": out["run_id"]}, {"_id": 0})
    assert run_row["activated"] is False and run_row["failed_step"] == step


# ════════════════════════════════════════════════════════════ the happy path
class TestActivation:
    @pytest.mark.parametrize("kind", KINDS)
    def test_every_step_passes_and_the_tenant_is_activated(self, kind):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(kind)
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            assert out["activated"] is True, out
            assert [s["step"] for s in out["steps"]] == list(STEPS)
            assert all(s["ok"] for s in out["steps"])
            row = await svc.get_binding(binding_id)
            assert row["status"] == BINDING_ACTIVE and row["connection_status"] == "connected"
            assert row["responsibility"]["version"] == RESPONSIBILITY_VERSION
            assert row["responsibility"]["accepted_by"] == OWNER_A
            reg = await sysdb["tenant_registry"].find_one({"id": A}, {"_id": 0})
            assert reg["storage_status"] == "active"
            assert reg["primary_storage_provider_type"] == kind
            assert reg["primary_storage_provider_reference"] == binding_id
            assert reg["storage_verified_at"]
            # B's registry row is untouched
            reg_b = await sysdb["tenant_registry"].find_one({"id": B}, {"_id": 0})
            assert reg_b["storage_status"] == "not_configured"
            # the activation object is gone; only the root marker remains
            adapter = await svc.adapter()
            from app.files.providers.base import ProviderObjectRef
            probe = ProviderObjectRef(container=adapter.binding.container,
                                      object_key="_beg_work/activation/%s.bin" % out["run_id"])
            assert (await adapter.stat(probe)).exists is False
            ev = await db["audit_events"].find_one({"action": "storage.provider.verified"},
                                                   {"_id": 0})
            assert ev["structured_diff"]["run_id"] == out["run_id"]
            connected = await db["audit_events"].find_one(
                {"action": "storage.provider.connected"}, {"_id": 0})
            assert connected["structured_diff"]["credential_field_names"]
        run(body())

    def test_a_backup_is_recorded_without_touching_the_primary(self):
        async def body():
            db, sysdb, svc, primary, backend = await _setup(m.PROVIDER_S3_COMPATIBLE)
            await svc.activate(ctx(OWNER_A, A), binding_id=primary,
                               responsibility=accepted(OWNER_A))
            backup, be2 = await configure(svc, OWNER_A, m.PROVIDER_SYNOLOGY_NAS,
                                          role=m.LOCATION_ROLE_BACKUP)
            svc._transport_for = lambda row: (be2 if row["id"] == backup else backend).transport
            out = await svc.activate(ctx(OWNER_A, A), binding_id=backup,
                                     responsibility=accepted(OWNER_A))
            assert out["activated"] is True
            reg = await sysdb["tenant_registry"].find_one({"id": A}, {"_id": 0})
            assert reg["primary_storage_provider_reference"] == primary
            assert reg["backup_storage_provider_reference"] == backup
            assert (await svc.active_binding(m.LOCATION_ROLE_BACKUP))["id"] == backup
        run(body())

    def test_a_replay_of_the_same_activation_does_not_run_the_gate_twice(self):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(m.PROVIDER_ON_PREM_SERVER)
            first = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                       responsibility=accepted(OWNER_A), idempotency_key="act-1")
            n = len(backend.requests)
            again = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                       responsibility=accepted(OWNER_A), idempotency_key="act-1")
            assert again["status"] == "replayed" and again["run_id"] == first["run_id"]
            assert again["activated"] is True and len(backend.requests) == n
        run(body())


# ═══════════════════════════════════════════ every failure blocks activation
class TestEveryFailureBlocks:
    @pytest.mark.parametrize("responsibility", [
        None, {}, {"accepted": False, "version": RESPONSIBILITY_VERSION, "accepted_by": OWNER_A},
        {"accepted": True, "version": "FLOW-016/old", "accepted_by": OWNER_A},
        {"accepted": True, "version": RESPONSIBILITY_VERSION, "accepted_by": "someone-else"}])
    def test_without_the_accepted_responsibility_boundary(self, responsibility):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(m.PROVIDER_S3_COMPATIBLE)
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=responsibility)
            await _assert_blocked(db, sysdb, svc, binding_id, out, "responsibility_accepted")
            assert backend.requests == [], "the provider was contacted before acceptance"
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_with_invalid_credentials(self, kind):
        async def body():
            db, sysdb = await world()
            backends = {}
            svc = service_for(db, sysdb, A, backends)
            backend, binding, creds = fb.build(kind, org_id=A)
            bad = {k: v + "-WRONG" if k in ("secret_access_key", "password", "refresh_token")
                   else v for k, v in creds.items()}
            out = await svc.configure_binding(
                ctx(OWNER_A, A), role="primary", provider_kind=kind, container=binding.container,
                root_prefix=binding.root_prefix, endpoint=binding.endpoint,
                account=binding.account, credentials=bad)
            backends[out["binding_id"]] = backend
            res = await svc.activate(ctx(OWNER_A, A), binding_id=out["binding_id"],
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, out["binding_id"], res, "credentials_valid")
        run(body())

    @pytest.mark.parametrize("kind", [m.PROVIDER_SYNOLOGY_NAS, m.PROVIDER_ON_PREM_SERVER])
    def test_with_a_missing_tenant_root(self, kind):
        async def body():
            db, sysdb, svc, binding_id, _ = await _setup(kind, root="")
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, binding_id, out, "root_verified")
        run(body())

    def test_with_a_read_only_root(self):
        async def body():
            db, sysdb, svc, binding_id, _ = await _setup(m.PROVIDER_GOOGLE_DRIVE,
                                                         root_writable=False)
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, binding_id, out, "root_verified")
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_when_the_test_object_cannot_be_written(self, kind):
        async def body():
            import httpx
            db, sysdb, svc, binding_id, backend = await _setup(kind)
            original = backend._dispatch

            def refuse_activation_writes(request):
                names_activation = (b"activation" in str(request.url).encode()
                                    or b"activation" in (request.content or b""))
                if backend._is_write(request) and names_activation:
                    backend.requests.append(request)
                    return httpx.Response(403)
                return original(request)
            backend._dispatch = refuse_activation_writes
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, binding_id, out, "test_object_uploaded")
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_when_the_bytes_read_back_differ(self, kind):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(kind)
            backend.corrupt_reads = True
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, binding_id, out, "test_object_read_back")
            assert not any("activation" in k for k in getattr(backend, "objects", {}))
        run(body())

    def test_when_the_provider_checksum_disagrees(self, monkeypatch):
        async def body():
            from app.files.providers import s3
            db, sysdb, svc, binding_id, backend = await _setup(m.PROVIDER_S3_COMPATIBLE)
            real = s3.S3CompatibleAdapter._checksum_from
            monkeypatch.setattr(s3.S3CompatibleAdapter, "_checksum_from", staticmethod(
                lambda h: {"algorithm": "sha256", "value": "0" * 64} if real(h) else None))
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, binding_id, out, "checksum_round_trip",
                                  "CHECKSUM_MISMATCH")
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_when_the_test_object_cannot_be_cleaned_up(self, kind):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(kind)
            backend.refuse_deletes = True
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, binding_id, out, "test_object_cleaned_up")
        run(body())

    def test_when_the_tenant_is_not_in_the_registry(self):
        async def body():
            db, sysdb, svc, binding_id, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            await sysdb["tenant_registry"].delete_many({"id": A})
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            assert out["activated"] is False and out["failed_step"] == "registry_recorded"
            with pytest.raises(StorageNotActive):
                await svc.adapter()
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_when_the_provider_is_unreachable(self, kind):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(kind)
            backend.offline = True
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            await _assert_blocked(db, sysdb, svc, binding_id, out, "credentials_valid")
        run(body())

    def test_an_unknown_binding_is_blocked_at_selection(self):
        async def body():
            db, sysdb, svc, _, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            out = await svc.activate(ctx(OWNER_A, A), binding_id="sb_nope",
                                     responsibility=accepted(OWNER_A))
            assert out["activated"] is False and out["failed_step"] == "provider_selected"
        run(body())

    def test_a_failed_new_provider_never_deactivates_the_active_one(self):
        async def body():
            db, sysdb, svc, primary, backend = await _setup(m.PROVIDER_S3_COMPATIBLE)
            await svc.activate(ctx(OWNER_A, A), binding_id=primary,
                               responsibility=accepted(OWNER_A))
            second, be2 = await configure(svc, OWNER_A, m.PROVIDER_ON_PREM_SERVER)
            be2.offline = True
            svc._transport_for = lambda row: (be2 if row["id"] == second else backend).transport
            out = await svc.activate(ctx(OWNER_A, A), binding_id=second,
                                     responsibility=accepted(OWNER_A))
            assert out["activated"] is False
            assert (await svc.active_binding())["id"] == primary
            reg = await sysdb["tenant_registry"].find_one({"id": A}, {"_id": 0})
            assert reg["storage_status"] == "active"
            assert reg["primary_storage_provider_reference"] == primary
        run(body())


# ══════════════════════════════════════════ tenant root / binding isolation
class TestRootAndBindingIsolation:
    def test_two_tenants_can_never_be_activated_on_one_root(self):
        async def body():
            db, sysdb = await world()
            backend, binding, creds = fb.build(m.PROVIDER_S3_COMPATIBLE, org_id=A)
            backends = {m.PROVIDER_S3_COMPATIBLE: backend}
            svc_a = service_for(db, sysdb, A, backends)
            svc_b = service_for(db, sysdb, B, backends)
            for svc, owner in ((svc_a, OWNER_A), (svc_b, OWNER_B)):
                await svc.configure_binding(
                    ctx(owner, svc.org_id), role="primary", provider_kind=binding.provider_kind,
                    container=binding.container, root_prefix=binding.root_prefix,
                    endpoint=binding.endpoint, account=binding.account, credentials=creds)
            a_id = (await svc_a.bindings.find_one({}, {"_id": 0}))["id"]
            b_id = (await svc_b.bindings.find_one({}, {"_id": 0}))["id"]
            assert (await svc_a.activate(ctx(OWNER_A, A), binding_id=a_id,
                                         responsibility=accepted(OWNER_A)))["activated"]
            out = await svc_b.activate(ctx(OWNER_B, B), binding_id=b_id,
                                       responsibility=accepted(OWNER_B))
            assert out["activated"] is False and out["failed_step"] == "root_verified"
            assert out["code"] == "ROOT_CLAIMED_BY_ANOTHER_TENANT"
        run(body())

    def test_the_root_marker_refuses_a_root_claimed_outside_this_registry(self):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(m.PROVIDER_ON_PREM_SERVER)
            from app.files.storage import tenant_root_marker
            backend.files["beg/tenant-beg/_beg_work/tenant-root.json"] = {
                "data": tenant_root_marker("SOME-OTHER-TENANT"), "etag": "x"}
            backend.collections.add("beg/tenant-beg/_beg_work")
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            assert out["failed_step"] == "root_verified"
            assert out["code"] == "ROOT_CLAIMED_BY_ANOTHER_TENANT"
        run(body())

    def test_a_tenant_cannot_activate_or_read_another_tenants_binding(self):
        async def body():
            db, sysdb, svc_a, a_id, backend = await _setup(m.PROVIDER_S3_COMPATIBLE)
            svc_b = service_for(db, sysdb, B, {a_id: backend})
            assert await svc_b.get_binding(a_id) is None
            out = await svc_b.activate(ctx(OWNER_B, B), binding_id=a_id,
                                       responsibility=accepted(OWNER_B))
            assert out["activated"] is False and out["failed_step"] == "provider_selected"
            assert (await svc_a.get_binding(a_id))["status"] == "unverified"
            with pytest.raises(StorageNotActive):
                await svc_b.adapter_for_binding(a_id)
        run(body())


# ═══════════════════════════════════════════════════════════ FLOW-002
class TestPermissions:
    def test_a_worker_cannot_configure_activate_or_list(self):
        async def body():
            db, sysdb, svc, binding_id, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            backend, binding, creds = fb.build(m.PROVIDER_S3_COMPATIBLE, org_id=A)
            with pytest.raises(FileAccessDenied):
                await svc.configure_binding(ctx(WORKER_A, A), role="primary",
                                            provider_kind=binding.provider_kind,
                                            container="c", endpoint=binding.endpoint,
                                            credentials=creds)
            with pytest.raises(FileAccessDenied):
                await svc.activate(ctx(WORKER_A, A), binding_id=binding_id,
                                   responsibility=accepted(WORKER_A))
            with pytest.raises(FileAccessDenied):
                await svc.list_bindings(ctx(WORKER_A, A))
        run(body())

    def test_a_session_of_another_tenant_is_refused_as_cross_tenant(self):
        async def body():
            db, sysdb, svc, binding_id, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            with pytest.raises(FileAccessDenied) as info:
                await svc.activate(ctx(OWNER_B, B), binding_id=binding_id,
                                   responsibility=accepted(OWNER_B))
            assert info.value.reason_code == "CROSS_TENANT"
            with pytest.raises(FileAccessDenied):
                await svc.activate(ctx(OWNER_A, B), binding_id=binding_id,
                                   responsibility=accepted(OWNER_A))
        run(body())

    def test_a_fake_or_legacy_provider_cannot_be_configured(self):
        async def body():
            db, sysdb, svc, _, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            for kind in (m.PROVIDER_FAKE_MEMORY, m.PROVIDER_LEGACY_APP_DISK):
                with pytest.raises(StorageConfigurationRefused):
                    await svc.configure_binding(ctx(OWNER_A, A), role="primary",
                                                provider_kind=kind, container="c",
                                                credentials={"password": "x"})
        run(body())


# ═════════════════════════════════════════════════════ secrets and the vault
class TestSecretsStaySecret:
    @pytest.mark.parametrize("kind", KINDS)
    def test_no_secret_reaches_any_document_event_view_or_log(self, kind, caplog):
        async def body():
            db, sysdb, svc, binding_id, backend = await _setup(kind)
            out = await svc.activate(ctx(OWNER_A, A), binding_id=binding_id,
                                     responsibility=accepted(OWNER_A))
            views = await svc.list_bindings(ctx(OWNER_A, A))
            dumps = [json.dumps(out, default=str), json.dumps(views, default=str), caplog.text]
            for database in (db, sysdb):
                for name in await database.list_collection_names():
                    rows = await database[name].find({}, {"_id": 0}).to_list(None)
                    dumps.append(json.dumps(rows, default=str))
            blob = "\n".join(dumps)
            for marker in fb.SECRET_MARKERS:
                assert marker not in blob, marker
            assert "credential_reference" not in json.dumps(views)
            stored = await db["storage_credentials"].find_one({}, {"_id": 0})
            assert stored["field_names"] and "ciphertext" in stored
        run(body())

    def test_a_ciphertext_moved_to_another_tenant_does_not_decrypt(self):
        async def body():
            db, sysdb, svc_a, a_id, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            row = await db["storage_credentials"].find_one({"org_id": A}, {"_id": 0})
            forged = dict(row, org_id=B)
            await db["storage_credentials"].insert_one(forged)
            vault_b = CredentialVault(TenantData(db, B), master_key=MASTER_KEY)
            with pytest.raises(CredentialReferenceInvalid):
                await vault_b.resolve(reference=row["id"], binding_id=row["binding_id"],
                                      provider_kind=row["provider_kind"])
        run(body())

    def test_a_ciphertext_moved_to_another_binding_does_not_decrypt(self):
        async def body():
            db, sysdb, svc_a, a_id, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            row = await db["storage_credentials"].find_one({"org_id": A}, {"_id": 0})
            await db["storage_credentials"].insert_one(dict(row, binding_id="sb_other"))
            vault = CredentialVault(TenantData(db, A), master_key=MASTER_KEY)
            with pytest.raises(CredentialReferenceInvalid):
                await vault.resolve(reference=row["id"], binding_id="sb_other",
                                    provider_kind=row["provider_kind"])
            # and the genuine one still resolves
            assert await vault.resolve(reference=row["id"], binding_id=row["binding_id"],
                                       provider_kind=row["provider_kind"])
        run(body())

    def test_another_master_key_cannot_read_the_vault(self):
        async def body():
            import os
            db, sysdb, svc_a, a_id, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            row = await db["storage_credentials"].find_one({"org_id": A}, {"_id": 0})
            other = CredentialVault(TenantData(db, A), master_key=os.urandom(32))
            with pytest.raises(CredentialReferenceInvalid):
                await other.resolve(reference=row["id"], binding_id=row["binding_id"],
                                    provider_kind=row["provider_kind"])
        run(body())

    def test_the_vault_fails_closed_without_a_master_key(self, monkeypatch):
        from mongomock_motor import AsyncMongoMockClient
        tenant = TenantData(AsyncMongoMockClient()["x"], A)
        monkeypatch.delenv(ENV_MASTER_KEY, raising=False)
        with pytest.raises(CredentialVaultUnavailable):
            CredentialVault(tenant)
        monkeypatch.setenv(ENV_MASTER_KEY, base64.b64encode(b"short").decode())
        with pytest.raises(CredentialVaultUnavailable):
            CredentialVault(tenant)
        monkeypatch.setenv(ENV_MASTER_KEY, base64.b64encode(b"k" * 32).decode())
        assert CredentialVault(tenant)

    @pytest.mark.parametrize("kind,creds", [
        (m.PROVIDER_S3_COMPATIBLE, {"access_key_id": "a"}),
        (m.PROVIDER_S3_COMPATIBLE, {"access_key_id": "a", "secret_access_key": "b",
                                    "note": "anything"}),
        (m.PROVIDER_GOOGLE_DRIVE, {"refresh_token": "r"}),
        (m.PROVIDER_ON_PREM_SERVER, {}),
        (m.PROVIDER_SYNOLOGY_NAS, {"password": ""}),
    ])
    def test_a_malformed_credential_set_is_refused_before_storage(self, kind, creds):
        async def body():
            db, sysdb, svc, _, _ = await _setup(m.PROVIDER_S3_COMPATIBLE)
            before = await db["storage_credentials"].count_documents({})
            backend, binding, _ = fb.build(kind, org_id=A)
            with pytest.raises(CredentialRejected):
                await svc.configure_binding(ctx(OWNER_A, A), role="primary", provider_kind=kind,
                                            container=binding.container,
                                            endpoint=binding.endpoint, account=binding.account,
                                            credentials=creds)
            assert await db["storage_credentials"].count_documents({}) == before
        run(body())

    def test_the_public_view_has_no_credential_reference(self):
        view = public_view({"id": "sb", "credential_reference": "cred_x", "provider_kind": "s3"})
        assert "credential_reference" not in view
