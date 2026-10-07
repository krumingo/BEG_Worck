"""
W0-06B — integrity/availability checks, affected records, and protected access.

* The five failure states (missing, permission denied, checksum mismatch,
  provider unavailable, changed external object) stay distinct on all four
  adapters, each with its own AuditEvent and an explicit W0-07 finding.
* Every active FileRelation is resolved and grouped (projects, offers /
  contracts / annexes, acts / invoices, deliveries, daily reports, tasks,
  defects / warranties, assets / repairs, other).
* A preview/cache is never promoted to the canonical original.
* Upload, open, download and share pass FLOW-002 (scope + sensitivity), use
  expiring single-use grants or capped pre-signed URLs, and never leak the
  token or a credential.

    pytest tests/test_w0_06b_integrity_access.py -v --noconftest
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.files import models as m
from app.files.access import (
    MODE_BEG_GRANT,
    MODE_PROVIDER_PRESIGNED,
    FileAccessService,
    GrantInvalid,
    OriginalUnavailable,
)
from app.files.authorization import FileAccessDenied
from app.files.integrity import FINDING_SCHEMA, FileIntegrityService
from app.files.providers.base import IntegrityVerdict
from app.files.registry import FileNotFound, FileRegistry, RelationTargetNotFound
from app.files.storage import StorageNotActive
from app.tenancy.data_access import TenantData
from tests import w0_06b_fake_backends as fb
from tests.w0_06b_support import (
    A, B, OWNER_A, OWNER_B, WORKER_A, accepted, configure, ctx, install_permissions,
    service_for, world,
)

pytest.importorskip("mongomock_motor")

KINDS = sorted(m.CUSTOMER_MANAGED_PROVIDER_KINDS)
DATA = b"%PDF-1.7 act 14 signed original"
SCOPED, FIN = "pm-p1", "fin-a"

#: One business record per FLOW-016 target family, in tenant A.
RECORDS = {
    m.RELATION_PROJECT: ("projects", "P-1", {"name": "Sofia site"}),
    m.RELATION_OFFER: ("offers", "O-1", {"offer_no": "OF-7"}),
    m.RELATION_ANNEX: ("change_orders", "AN-1", {"number": "AN-1"}),
    m.RELATION_ACT: ("client_acts", "ACT-1", {"act_number": "14"}),
    m.RELATION_INVOICE: ("invoices", "I-1", {"invoice_no": "2026-001"}),
    m.RELATION_DELIVERY: ("deliveries", "DL-1", {"number": "DL-1"}),
    m.RELATION_DAILY_REPORT: ("daily_work_logs", "DR-1", {"date": "2026-10-04"}),
    m.RELATION_TASK: ("worker_calendar", "T-1", {"title": "pour slab"}),
    m.RELATION_DEFECT: ("missing_smr", "D-1", {"title": "crack"}),
    m.RELATION_REPAIR: ("asset_repairs", "R-1", {"title": "pump repair"}),
}
EXPECTED_GROUPS = {"projects", "offers_contracts_annexes", "acts_invoices", "deliveries",
                   "daily_reports", "tasks", "defects_warranties", "assets_repairs"}


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _perms(monkeypatch):
    install_permissions(monkeypatch, {
        # file.open/download at project P-1 only (a project-scope assignment)
        (SCOPED, A): [{"id": "ra-pm", "status": "active", "role_id": "custom",
                       "permissions": ["file.open", "file.download"],
                       "scope_type": "project", "scope_id": "P-1"}],
        # company-wide open, but no sensitivity right
        (FIN, A): [{"id": "ra-fin", "status": "active", "role_id": "custom",
                    "permissions": ["file.open", "file.download", "file.upload"],
                    "scope_type": "company"}],
    })


async def _activated(kind, org=A, owner=OWNER_A, db=None, sysdb=None):
    if db is None:
        db, sysdb = await world()
    backends = {}
    svc = service_for(db, sysdb, org, backends)
    binding_id, backend = await configure(svc, owner, kind)
    backends[binding_id] = backend
    out = await svc.activate(ctx(owner, org), binding_id=binding_id,
                             responsibility=accepted(owner))
    assert out["activated"], out
    reg = FileRegistry(TenantData(db, org))
    return db, sysdb, svc, reg, backend


async def _seed_records(db, org=A):
    for _, (coll, rid, extra) in RECORDS.items():
        await db[coll].insert_one({"id": rid, "org_id": org, **extra})


async def _uploaded(kind, relations=None, sensitivity=m.SENSITIVITY_STANDARD):
    db, sysdb, svc, reg, backend = await _activated(kind)
    await _seed_records(db)
    access = FileAccessService(reg, svc)
    rels = relations if relations is not None else [
        {"relation_type": t, "record_id": rid} for t, (_, rid, _) in RECORDS.items()]
    out = await access.upload(ctx(OWNER_A, A), data=DATA, display_name="Act 14",
                              original_name="act14.pdf", category=m.CATEGORY_ACTS,
                              mime_type="application/pdf", sensitivity=sensitivity,
                              relations=rels)
    assert out["status"] == "registered", out
    return db, sysdb, svc, reg, backend, access, out["file_id"]


def _key_of(reg_location):
    return reg_location["object_key"]


# ════════════════════════════════════════════════════════════ integrity
class TestIntegrityStates:
    @pytest.mark.parametrize("kind", KINDS)
    def test_an_intact_original_is_available_with_its_affected_records(self, kind):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(kind)
            await reg.register_derived(actor_id=OWNER_A, file_id=file_id, source_version_no=1,
                                       kind=m.DERIVED_THUMBNAIL, cache_reference="cache/t1")
            finding = await FileIntegrityService(reg, svc).check(ctx(OWNER_A, A), file_id=file_id)
            assert finding["schema"] == FINDING_SCHEMA and finding["ok"] is True
            assert finding["availability"] == m.AVAILABILITY_AVAILABLE
            assert finding["finding_type"] is None and finding["severity"] == "none"
            assert finding["method"] in ("server_checksum", "read_and_hash")
            assert set(finding["affected_by_group"]) == EXPECTED_GROUPS
            assert all(r["exists"] and r["label"] for r in finding["affected_records"])
            assert finding["derived_cache"][0]["recoverable"] is True
            assert finding["dq_handoff"]["blocking"] is False
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("inject,availability,finding_type,action", [
        ("mutate", m.AVAILABILITY_CHECKSUM_MISMATCH, "checksum_mismatch",
         "file.integrity.checksum_mismatch"),
        ("remove", m.AVAILABILITY_MISSING, "missing_original", "file.integrity.missing"),
        ("deny", m.AVAILABILITY_PERMISSION_DENIED, "permission_failure",
         "file.integrity.permission_denied"),
        ("offline", m.AVAILABILITY_PROVIDER_UNREACHABLE, "provider_unavailable",
         "file.integrity.provider_unreachable"),
        ("replace", m.AVAILABILITY_EXTERNALLY_CHANGED, "external_change",
         "file.integrity.externally_changed"),
    ])
    def test_each_failure_is_its_own_state_event_and_finding(self, kind, inject, availability,
                                                             finding_type, action):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(kind)
            await reg.register_derived(actor_id=OWNER_A, file_id=file_id, source_version_no=1,
                                       kind=m.DERIVED_PREVIEW, cache_reference="cache/p1")
            key = (await reg.primary_location(file_id, 1))["object_key"]
            if inject == "mutate":
                backend.mutate(key, DATA.replace(b"14", b"41"))
            elif inject == "offline":
                backend.offline = True
            else:
                getattr(backend, inject)(key)
            finding = await FileIntegrityService(reg, svc).check(ctx(OWNER_A, A), file_id=file_id)
            assert finding["availability"] == availability, finding
            assert finding["finding_type"] == finding_type
            assert finding["severity"] in ("high", "critical")
            assert finding["dq_handoff"] == {"consumer": "W0-07", "state": "not_consumed",
                                             "blocking": True}
            assert finding["recovery"]["owner"] == "customer"
            assert set(finding["affected_by_group"]) == EXPECTED_GROUPS
            # never a new version, never the cache as original
            assert finding["treated_as_new_version"] is False
            assert await db[m.VERSIONS_COLLECTION].count_documents({"file_id": file_id}) == 1
            assert finding["derived_cache"][0]["recoverable"] is False
            assert finding["derived_cache"][0]["is_canonical_original"] is False
            answer = await reg.canonical_original(file_id)
            assert answer["available"] is False and answer["derived"]
            # the generic event AND the outcome event, correlated
            # (the upload recorded its own verification first; take this check's)
            checks = await db["audit_events"].find({"action": "file.integrity.checked"},
                                                   {"_id": 0}).sort("sequence", 1).to_list(None)
            assert checks[0]["structured_diff"]["availability"] == m.AVAILABILITY_AVAILABLE
            generic = checks[-1]
            outcome = await db["audit_events"].find_one({"action": action}, {"_id": 0})
            assert outcome and outcome["correlation_id"] == generic["event_id"]
            assert outcome["structured_diff"]["affected_records"]
            assert finding["audit_event_ids"] == [generic["event_id"], outcome["event_id"]]
            # and access to the original is refused despite the cached preview
            with pytest.raises(OriginalUnavailable):
                await access.issue_access(ctx(OWNER_A, A), file_id=file_id, purpose="open")
        run(body())

    def test_an_inactive_binding_is_unavailable_not_missing(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_S3_COMPATIBLE)
            await svc.bindings.update_many({}, {"$set": {"status": "superseded"}})
            finding = await FileIntegrityService(reg, svc).check(ctx(OWNER_A, A), file_id=file_id)
            assert finding["availability"] == m.AVAILABILITY_PROVIDER_UNREACHABLE
            assert finding["observed"]["error"] == "BINDING_NOT_ACTIVE"
        run(body())

    def test_a_relation_whose_record_was_removed_is_reported_as_dangling(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_ON_PREM_SERVER)
            await db["invoices"].delete_many({"id": "I-1"})
            finding = await FileIntegrityService(reg, svc).check(ctx(OWNER_A, A), file_id=file_id)
            invoice = next(r for r in finding["affected_records"] if r["record_id"] == "I-1")
            assert invoice["exists"] is False and invoice["group"] == "acts_invoices"
        run(body())

    def test_integrity_needs_the_permission_and_the_tenant(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_SYNOLOGY_NAS)
            integ = FileIntegrityService(reg, svc)
            with pytest.raises(FileAccessDenied):
                await integ.check(ctx(WORKER_A, A), file_id=file_id)
            with pytest.raises(FileAccessDenied):
                await integ.check(ctx(OWNER_B, B), file_id=file_id)
            # B's own service cannot even see A's file under the same id
            svc_b = service_for(db, sysdb, B, {})
            reg_b = FileRegistry(TenantData(db, B))
            with pytest.raises(FileNotFound):
                await FileIntegrityService(reg_b, svc_b).check(ctx(OWNER_B, B), file_id=file_id)
        run(body())


# ═══════════════════════════════════════════════════════════════ upload
class TestUpload:
    @pytest.mark.parametrize("kind", KINDS)
    def test_an_upload_lands_at_the_primary_with_its_provider_identity(self, kind):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(kind)
            loc = await reg.primary_location(file_id, 1)
            assert loc["provider_kind"] == kind and loc["expected_size_bytes"] == len(DATA)
            assert loc["object_key"].startswith("objects/") and file_id not in loc["object_key"]
            adapter = await svc.adapter()
            from app.files.providers.base import ProviderObjectRef
            got = await adapter.read(ProviderObjectRef(container=loc["container"],
                                                       object_key=loc["object_key"],
                                                       provider_file_id=loc["provider_file_id"]))
            assert got == DATA
            ev = await db["audit_events"].find_one({"action": "file.uploaded"}, {"_id": 0})
            assert ev["entity_id"] == file_id
        run(body())

    def test_a_tenant_without_an_active_provider_cannot_store_an_original(self):
        async def body():
            db, sysdb = await world()
            svc_b = service_for(db, sysdb, B, {})
            access = FileAccessService(FileRegistry(TenantData(db, B)), svc_b)
            with pytest.raises(StorageNotActive):
                await access.upload(ctx(OWNER_B, B), data=DATA, display_name="x",
                                    original_name="x.pdf", category=m.CATEGORY_OTHER,
                                    mime_type="application/pdf")
            assert await db[m.FILES_COLLECTION].count_documents({}) == 0
        run(body())

    def test_a_duplicate_is_reported_before_anything_is_written(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_S3_COMPATIBLE)
            before = len(backend.objects)
            again = await access.upload(ctx(OWNER_A, A), data=DATA, display_name="copy",
                                        original_name="copy.pdf", category=m.CATEGORY_ACTS,
                                        mime_type="application/pdf")
            assert again["status"] == "duplicate" and again["file_id"] == file_id
            assert again["provider_written"] is False and len(backend.objects) == before
        run(body())

    def test_a_foreign_relation_target_is_refused_before_the_provider_write(self):
        async def body():
            db, sysdb, svc, reg, backend, access, _ = await _uploaded(m.PROVIDER_S3_COMPATIBLE)
            await db["projects"].insert_one({"id": "P-B", "org_id": B, "name": "B"})
            before = len(backend.objects)
            with pytest.raises(RelationTargetNotFound):
                await access.upload(ctx(OWNER_A, A), data=b"other", display_name="x",
                                    original_name="x.pdf", category=m.CATEGORY_OTHER,
                                    mime_type="application/pdf",
                                    relations=[{"relation_type": "project", "record_id": "P-B"}])
            assert len(backend.objects) == before
        run(body())

    def test_upload_needs_the_permission_and_sensitivity_right(self):
        async def body():
            db, sysdb, svc, reg, backend, access, _ = await _uploaded(m.PROVIDER_S3_COMPATIBLE)
            with pytest.raises(FileAccessDenied):
                await access.upload(ctx(WORKER_A, A), data=b"w", display_name="x",
                                    original_name="x", category=m.CATEGORY_OTHER,
                                    mime_type="text/plain")
            with pytest.raises(FileAccessDenied):
                await access.upload(ctx(FIN, A), data=b"payroll", display_name="x",
                                    original_name="x", category=m.CATEGORY_OTHER,
                                    mime_type="text/plain",
                                    sensitivity=m.SENSITIVITY_CONFIDENTIAL)
        run(body())

    def test_a_replayed_upload_writes_once(self):
        async def body():
            db, sysdb, svc, reg, backend, access, _ = await _uploaded(m.PROVIDER_ON_PREM_SERVER)
            outs = [await access.upload(ctx(OWNER_A, A), data=b"new photo", display_name="p",
                                        original_name="p.jpg", category=m.CATEGORY_PHOTO_VIDEO,
                                        mime_type="image/jpeg", idempotency_key="up-1")
                    for _ in range(3)]
            assert {o["file_id"] for o in outs} == {outs[0]["file_id"]}
            assert [o["status"] for o in outs] == ["registered", "replayed", "replayed"]
        run(body())


# ═══════════════════════════════════════════════════════ protected access
class TestProtectedAccess:
    @pytest.mark.parametrize("kind", KINDS)
    def test_open_is_a_single_use_expiring_grant_served_after_a_recheck(self, kind):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(kind)
            grant = await access.issue_access(ctx(OWNER_A, A), file_id=file_id, purpose="open")
            assert grant["mode"] == MODE_BEG_GRANT
            expires = datetime.fromisoformat(grant["expires_at"])
            assert expires - datetime.now(timezone.utc) <= timedelta(seconds=301)
            data, mime, fid = await access.redeem(ctx(OWNER_A, A), token=grant["token"])
            assert data == DATA and mime == "application/pdf" and fid == file_id
            with pytest.raises(GrantInvalid):
                await access.redeem(ctx(OWNER_A, A), token=grant["token"])
            for action in ("file.access.granted", "file.opened"):
                assert await db["audit_events"].count_documents({"action": action}) == 1
        run(body())

    def test_s3_download_is_a_capped_presigned_url_others_get_a_beg_grant(self):
        async def body():
            for kind in KINDS:
                db, sysdb, svc, reg, backend, access, file_id = await _uploaded(kind)
                grant = await access.issue_access(ctx(OWNER_A, A), file_id=file_id,
                                                  purpose="download", seconds=600)
                if kind == m.PROVIDER_S3_COMPATIBLE:
                    assert grant["mode"] == MODE_PROVIDER_PRESIGNED
                    assert "X-Amz-Expires=600" in grant["url"]
                    assert backend.secret_key not in grant["url"]
                else:
                    assert grant["mode"] == MODE_BEG_GRANT and "url" not in grant
                with pytest.raises(ValueError):
                    await access.issue_access(ctx(OWNER_A, A), file_id=file_id,
                                              purpose="download", seconds=3600)
        run(body())

    def test_an_expired_or_revoked_grant_is_refused(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_ON_PREM_SERVER)
            g1 = await access.issue_access(ctx(OWNER_A, A), file_id=file_id, purpose="open")
            await access.grants.update_one({"id": g1["grant_id"]}, {"$set": {
                "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}})
            with pytest.raises(GrantInvalid):
                await access.redeem(ctx(OWNER_A, A), token=g1["token"])
            g2 = await access.issue_access(ctx(OWNER_A, A), file_id=file_id, purpose="open")
            await access.revoke(ctx(OWNER_A, A), grant_id=g2["grant_id"])
            with pytest.raises(GrantInvalid):
                await access.redeem(ctx(OWNER_A, A), token=g2["token"])
        run(body())

    def test_a_grant_is_bound_to_its_user_and_its_tenant(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_SYNOLOGY_NAS)
            grant = await access.issue_access(ctx(OWNER_A, A), file_id=file_id, purpose="open")
            with pytest.raises(GrantInvalid):
                await access.redeem(ctx(FIN, A), token=grant["token"])
            # the same token through tenant B's service is simply unknown
            db2, sys2, svc_b, reg_b, _ = await _activated(m.PROVIDER_S3_COMPATIBLE, org=B,
                                                          owner=OWNER_B, db=db, sysdb=sysdb)
            with pytest.raises(GrantInvalid):
                await FileAccessService(reg_b, svc_b).redeem(ctx(OWNER_B, B),
                                                             token=grant["token"])
            # and it still works for its owner afterwards
            assert (await access.redeem(ctx(OWNER_A, A), token=grant["token"]))[0] == DATA
        run(body())

    def test_flow_002_scope_is_exact_and_denials_are_audited(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_S3_COMPATIBLE)
            # project-scoped user: allowed at P-1 (the file is related to P-1) ...
            grant = await access.issue_access(ctx(SCOPED, A), file_id=file_id, purpose="open",
                                              scope_type="project", scope_id="P-1")
            assert grant["mode"] == MODE_BEG_GRANT
            # ... not company-wide, not at a project the file is not attached to
            with pytest.raises(FileAccessDenied):
                await access.issue_access(ctx(SCOPED, A), file_id=file_id, purpose="open")
            await db["projects"].insert_one({"id": "P-2", "org_id": A, "name": "other"})
            with pytest.raises(FileAccessDenied) as info:
                await access.issue_access(ctx(SCOPED, A), file_id=file_id, purpose="open",
                                          scope_type="project", scope_id="P-2")
            assert info.value.reason_code == "FILE_NOT_IN_SCOPE"
            with pytest.raises(FileAccessDenied):
                await access.issue_access(ctx(SCOPED, A), file_id=file_id, purpose="share",
                                          scope_type="project", scope_id="P-1")
            with pytest.raises(FileAccessDenied):
                await access.issue_access(ctx(WORKER_A, A), file_id=file_id, purpose="open")
            with pytest.raises(FileAccessDenied):
                await access.issue_access(ctx(OWNER_B, B), file_id=file_id, purpose="open")
            denied = await db["audit_events"].find({"action": "file.access.denied"},
                                                   {"_id": 0}).to_list(None)
            assert len(denied) == 5 and all(e["result"] == "denied" for e in denied)
        run(body())

    def test_a_confidential_file_needs_the_narrower_right(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_ON_PREM_SERVER, sensitivity=m.SENSITIVITY_CONFIDENTIAL)
            with pytest.raises(FileAccessDenied) as info:
                await access.issue_access(ctx(FIN, A), file_id=file_id, purpose="open")
            assert info.value.action == "file.sensitivity.confidential"
            assert (await access.issue_access(ctx(OWNER_A, A), file_id=file_id,
                                              purpose="open"))["token"]
        run(body())

    def test_a_permission_revoked_after_the_grant_blocks_the_redeem(self, monkeypatch):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_ON_PREM_SERVER)
            grant = await access.issue_access(ctx(FIN, A), file_id=file_id, purpose="open")
            install_permissions(monkeypatch, {(FIN, A): []})
            with pytest.raises(FileAccessDenied):
                await access.redeem(ctx(FIN, A), token=grant["token"])
        run(body())

    @pytest.mark.parametrize("kind", KINDS)
    def test_bytes_changed_after_the_grant_are_never_served(self, kind):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(kind)
            await reg.record_integrity_check(
                actor_id=OWNER_A, file_id=file_id, version_no=1,
                verdict=IntegrityVerdict(availability=m.AVAILABILITY_AVAILABLE,
                                         checked_at="2026-10-04T00:00:00+00:00"))
            grant = await access.issue_access(ctx(OWNER_A, A), file_id=file_id, purpose="open")
            key = (await reg.primary_location(file_id, 1))["object_key"]
            backend.mutate(key, DATA.replace(b"14", b"41"))
            with pytest.raises(OriginalUnavailable) as info:
                await access.redeem(ctx(OWNER_A, A), token=grant["token"])
            assert info.value.availability == m.AVAILABILITY_CHECKSUM_MISMATCH
        run(body())

    def test_the_token_and_credentials_are_never_stored_or_audited(self):
        async def body():
            db, sysdb, svc, reg, backend, access, file_id = await _uploaded(
                m.PROVIDER_GOOGLE_DRIVE)
            grant = await access.issue_access(ctx(OWNER_A, A), file_id=file_id, purpose="open")
            await access.redeem(ctx(OWNER_A, A), token=grant["token"])
            blob = []
            for database in (db, sysdb):
                for name in await database.list_collection_names():
                    blob.append(json.dumps(await database[name].find({}, {"_id": 0})
                                           .to_list(None), default=str))
            text = "\n".join(blob)
            assert grant["token"] not in text
            for marker in fb.SECRET_MARKERS:
                assert marker not in text
        run(body())
