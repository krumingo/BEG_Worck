"""
W0-06D — the real-MongoDB gate: persistence and tenant isolation of the scan.

The focused suite runs on ``mongomock``, which is enough for logic but cannot
prove that a scan's records survive a process, that two tenants' items really
stay apart in one database, or that a tenant-scoped query really is scoped by
the server rather than by the fake. Those are properties of MongoDB, so they
are proven here, on a disposable server bound only to loopback.

Skipped unless ``W0_06D_REAL_MONGO_URL`` (or ``W0_06C_``/``W0_06B_``/
``W0_06A_``/``W0_03_REAL_MONGO_URL``) names a plain LOCAL server::

    W0_06D_REAL_MONGO_URL=mongodb://127.0.0.1:27017 \\
        pytest tests/test_w0_06d_real_mongo.py -v --noconftest

The URL must pass the same local-only guard the W0-03C bootstrap uses (no
Atlas, no NAS, no ``mongodb+srv``). Each test works in its OWN databases
``w006d_realmongo_<random>`` / ``w006d_realsys_<random>`` and drops exactly
those afterwards, and each uses its own temporary legacy root, removed in a
``finally``. Nothing reads ``.env`` or a production value; every provider is a
disposable in-process fake and no customer original exists outside the fixtures
these tests create.

Required skips: 0. Every test runs when the URL is given.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
import uuid

import pytest

from app.files import adoption_readiness as ar
from app.files import migration_map as mp
from app.files import models as m
from app.files.authorization import FileAccessDenied
from app.files.registry import FileRegistry
from app.tenancy.data_access import TenantData

REAL_URL = (os.environ.get("W0_06D_REAL_MONGO_URL")
            or os.environ.get("W0_06C_REAL_MONGO_URL")
            or os.environ.get("W0_06B_REAL_MONGO_URL")
            or os.environ.get("W0_06A_REAL_MONGO_URL")
            or os.environ.get("W0_03_REAL_MONGO_URL", ""))
DB_PREFIX = "w006d_realmongo_"
SYS_PREFIX = "w006d_realsys_"

A, B = "BEG", "TCB"
OPERATOR_A, OPERATOR_B, READER_A = "adopt-a", "adopt-b", "adopt-read-a"
ADOPTION_ACTIONS = ["file.adoption.scan", "file.adoption.read"]


def _refusal():
    if not REAL_URL:
        return "W0_06D_REAL_MONGO_URL is not set — no disposable local MongoDB given"
    try:
        from app.master_data import index_bootstrap as ib
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        scheme, hosts = parse_mongo_url(REAL_URL)
        ib.check_local(hosts=hosts, scheme=scheme)
    except Exception as exc:                                  # noqa: BLE001
        return "W0_06D_REAL_MONGO_URL refused: %s" % exc
    try:
        import motor.motor_asyncio  # noqa: F401
    except ImportError:
        return "motor is not installed"
    return ""


pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


def _install_permissions():
    """The REAL W0-02 Permission Service with an in-memory assignment table."""
    from app.permissions import service
    table = {
        (OPERATOR_A, A): [{"id": "ra-ad-a", "status": "active", "role_id": "custom",
                           "permissions": list(ADOPTION_ACTIONS),
                           "scope_type": "company"}],
        (OPERATOR_B, B): [{"id": "ra-ad-b", "status": "active", "role_id": "custom",
                           "permissions": list(ADOPTION_ACTIONS),
                           "scope_type": "company"}],
        (READER_A, A): [{"id": "ra-ad-r", "status": "active", "role_id": "custom",
                         "permissions": ["file.adoption.read"],
                         "scope_type": "company"}],
    }

    async def load(user_id, tenant_id):
        return [dict(a) for a in table.get((user_id, tenant_id), [])]
    service._load_assignments = load


def _ctx(user, tenant):
    from types import SimpleNamespace
    return SimpleNamespace(user_id=user, tenant_id=tenant)


class _Roots:
    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="w006d_real_")
        self.uploads = os.path.join(self.base, "uploads")
        self.projects = os.path.join(self.uploads, "projects")
        os.makedirs(self.projects, exist_ok=True)

    def write(self, relative, data=b"legacy original bytes"):
        path = os.path.join(self.uploads, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def inventory(self, **budget):
        budget.setdefault("allow_content_read", True)
        return ar.LegacyRootInventory(
            [self.uploads, self.projects],
            budget=ar.ScanBudget(**budget),
            declared_roots={mp.LEGACY_PROJECT_UPLOADS_ROOT: self.projects,
                            mp.LEGACY_UPLOADS_ROOT: self.uploads})

    def remove(self):
        shutil.rmtree(self.base, ignore_errors=True)


async def _w004_indexes(db):
    await db["audit_events"].create_index([("event_id", 1)], unique=True)
    await db["audit_events"].create_index([("tenant_id", 1), ("sequence", 1)],
                                          unique=True)
    await db["audit_idempotency"].create_index("id", unique=True)


def scratch(test):
    """Run ``test(db, sysdb, roots)`` on the real server; drop everything after."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        name = DB_PREFIX + uuid.uuid4().hex[:12]
        sys_name = SYS_PREFIX + uuid.uuid4().hex[:12]
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        roots = _Roots()
        try:
            db, sysdb = client[name], client[sys_name]
            await _w004_indexes(db)
            for org in (A, B):
                await sysdb["tenant_registry"].insert_one(
                    {"id": org, "legacy_org_id": org, "status": "active",
                     "storage_provider": None, "storage_status": "not_configured"})
            return await test(db, sysdb, roots)
        finally:
            roots.remove()
            await client.drop_database(name)
            await client.drop_database(sys_name)
            client.close()
    _install_permissions()
    return asyncio.run(body())


def readiness(db, org, roots, **kw):
    return ar.LegacyAdoptionReadiness(
        FileRegistry(TenantData(db, org)), inventory=roots.inventory(), **kw)


async def _seed(db, org, collection, rows):
    for row in rows:
        await db[collection].insert_one(dict(row, org_id=org))


def _media_row(media_id, stored):
    return {"id": media_id, "stored_filename": stored, "filename": stored,
            "url": "/uploads/" + stored, "context_type": "project",
            "context_id": "P-1", "owner_user_id": "u-1"}


# ═════════════════════════════════════════════════════════════ persistence
class TestRealPersistence:
    def test_a_scan_and_its_items_persist_exactly_as_written(self):
        async def test(db, sysdb, roots):
            roots.write("p1.pdf", b"one")
            roots.write("p2.pdf", b"two")
            await _seed(db, A, "media_files", [_media_row("md-1", "p1.pdf"),
                                               _media_row("md-2", "missing.pdf")])
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            stored = await db[ar.ADOPTION_SCANS_COLLECTION].find_one(
                {"id": out["id"]}, {"_id": 0})
            assert stored is not None
            assert stored["plan_hash"] == out["plan_hash"]
            assert stored["schema"] == ar.ADOPTION_SCHEMA
            assert stored["dry_run"] is True and stored["executable"] is False
            assert stored["org_id"] == A
            items = await db[ar.ADOPTION_ITEMS_COLLECTION].find(
                {"scan_id": out["id"]}, {"_id": 0}).to_list(None)
            assert len(items) == len(out["item_records"])
            assert {i["org_id"] for i in items} == {A}
            # the readiness really round-tripped, field for field
            by_id = {i["id"]: i for i in items}
            for produced in out["item_records"]:
                kept = by_id[produced["id"]]
                assert kept["state"] == produced["state"]
                assert kept["fingerprint"] == produced["fingerprint"]
                assert kept["proposed_action"] == produced["proposed_action"]
        scratch(test)

    def test_a_second_client_reads_the_same_plan_and_validates_it(self):
        """Durability across clients: a new connection sees the same hash."""
        async def test(db, sysdb, roots):
            from motor.motor_asyncio import AsyncIOMotorClient
            roots.write("d.pdf", b"durable")
            await _seed(db, A, "media_files", [_media_row("md-1", "d.pdf")])
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            other = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
            try:
                fresh_db = other[db.name]
                service = readiness(fresh_db, A, roots)
                answer = await service.validate_plan(_ctx(OPERATOR_A, A),
                                                      scan_id=out["id"])
                assert answer["valid"] is True
                assert answer["plan_hash"] == out["plan_hash"]
            finally:
                other.close()
        scratch(test)

    def test_drift_on_the_real_server_refuses_the_stored_plan(self):
        async def test(db, sysdb, roots):
            path = roots.write("c.pdf", b"before")
            await _seed(db, A, "media_files", [_media_row("md-1", "c.pdf")])
            service = readiness(db, A, roots)
            out = await service.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            with open(path, "wb") as handle:                 # the customer replaced it
                handle.write(b"after")
            with pytest.raises(ar.AdoptionPlanStale) as stale:
                await readiness(db, A, roots).validate_plan(_ctx(OPERATOR_A, A),
                                                             scan_id=out["id"])
            assert any("observed.checksum" in str(d["drift"]) for d in stale.value.drifted)
            # the stored plan is untouched by the refusal
            stored = await db[ar.ADOPTION_SCANS_COLLECTION].find_one({"id": out["id"]})
            assert stored["plan_hash"] == out["plan_hash"]
            refusals = await db["audit_events"].count_documents(
                {"action": ar.AUDIT_PLAN_REFUSED})
            assert refusals == 1
        scratch(test)

    def test_the_audit_chain_is_intact_on_a_real_server(self):
        async def test(db, sysdb, roots):
            from app.audit import store
            roots.write("a.pdf", b"a")
            await _seed(db, A, "media_files", [_media_row("md-1", "a.pdf")])
            service = readiness(db, A, roots)
            for index in range(3):
                await service.scan(_ctx(OPERATOR_A, A), scan_id="adsc_s%d" % index,
                                    source_keys=["media_files"])
            intact, reason = await store.verify_tenant_chain(db, A)
            assert intact is True, reason
            events = await db["audit_events"].count_documents(
                {"action": {"$regex": "^file.adoption"}})
            assert events >= 6                      # start + finish per scan
        scratch(test)


# ═══════════════════════════════════════════════════════════════ isolation
class TestRealIsolation:
    def test_two_tenants_scan_the_same_filename_into_separate_records(self):
        async def test(db, sysdb, roots):
            roots.write("shared.pdf", b"identical bytes")
            await _seed(db, A, "media_files", [_media_row("md-1", "shared.pdf")])
            await _seed(db, B, "media_files", [_media_row("md-1", "shared.pdf")])
            out_a = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                        source_keys=["media_files"])
            out_b = await readiness(db, B, roots).scan(_ctx(OPERATOR_B, B),
                                                        source_keys=["media_files"])
            assert out_a["plan_hash"] != out_b["plan_hash"]
            a_items = await db[ar.ADOPTION_ITEMS_COLLECTION].find(
                {"scan_id": out_a["id"]}, {"_id": 0}).to_list(None)
            b_items = await db[ar.ADOPTION_ITEMS_COLLECTION].find(
                {"scan_id": out_b["id"]}, {"_id": 0}).to_list(None)
            assert {i["org_id"] for i in a_items} == {A}
            assert {i["org_id"] for i in b_items} == {B}
            a_rows = [i for i in a_items if i["direction"] == ar.DIRECTION_DB_ROW]
            b_rows = [i for i in b_items if i["direction"] == ar.DIRECTION_DB_ROW]
            assert a_rows[0]["plan"]["file_id"] != b_rows[0]["plan"]["file_id"]
            assert a_rows[0]["id"] != b_rows[0]["id"]
        scratch(test)

    def test_a_tenants_projection_never_returns_the_other_tenants_items(self):
        async def test(db, sysdb, roots):
            roots.write("a.pdf", b"a")
            roots.write("b.pdf", b"b")
            await _seed(db, A, "media_files", [_media_row("md-a", "a.pdf")])
            await _seed(db, B, "media_files", [_media_row("md-b", "b.pdf")])
            await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                source_keys=["media_files"])
            await readiness(db, B, roots).scan(_ctx(OPERATOR_B, B),
                                                source_keys=["media_files"])
            a_view = await readiness(db, A, roots).list_items(
                _ctx(OPERATOR_A, A), include_source_reference=True)
            refs = {r.get("legacy_reference") for r in a_view}
            assert "md-b" not in refs
            assert all(r.get("org_id") in (A, None) for r in a_view)
            # the server, not the fake, enforced it: the raw collection holds both
            total = await db[ar.ADOPTION_ITEMS_COLLECTION].count_documents({})
            assert total > len(a_view)
        scratch(test)

    def test_a_cross_tenant_scan_is_refused_and_audited_on_a_real_server(self):
        async def test(db, sysdb, roots):
            await _seed(db, A, "media_files", [_media_row("md-1", "x.pdf")])
            with pytest.raises(FileAccessDenied) as denied:
                await readiness(db, A, roots).scan(_ctx(OPERATOR_B, B))
            assert denied.value.reason_code == "CROSS_TENANT"
            assert await db[ar.ADOPTION_SCANS_COLLECTION].count_documents({}) == 0
            events = await db["audit_events"].find(
                {"action": "file.access.denied"}, {"_id": 0}).to_list(None)
            assert len(events) == 1 and events[0]["tenant_id"] == A
        scratch(test)

    def test_the_same_business_id_in_two_tenants_resolves_to_this_tenant_only(self):
        async def test(db, sysdb, roots):
            # the SAME project id in both tenants, and a row in each
            for org in (A, B):
                await db["projects"].insert_one({"id": "P-1", "org_id": org,
                                                 "name": "site " + org})
            roots.write("x.pdf", b"x")
            await _seed(db, A, "media_files", [_media_row("md-x", "x.pdf")])
            await _seed(db, B, "media_files", [_media_row("md-x", "x.pdf")])
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            rows = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert len(rows) == 1, "a foreign tenant's row entered the scan"
            assert rows[0]["org_id"] == A
            assert rows[0]["relations"] == [
                {"relation_type": m.RELATION_PROJECT, "record_id": "P-1",
                 "source_field": "context_type/context_id"}]
        scratch(test)


# ══════════════════════════════════════════════════ nothing is touched, really
class TestRealNothingIsTouched:
    def test_a_real_scan_writes_only_its_own_two_collections(self):
        async def test(db, sysdb, roots):
            roots.write("k1.pdf", b"one")
            roots.write("k2.pdf", b"two")
            await _seed(db, A, "media_files", [_media_row("md-1", "k1.pdf"),
                                               _media_row("md-2", "k2.pdf")])
            before = {}
            for name in await db.list_collection_names():
                before[name] = await db[name].count_documents({})
            await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                source_keys=["media_files"])
            after = {}
            for name in await db.list_collection_names():
                after[name] = await db[name].count_documents({})
            grew = {name for name in after
                    if after[name] != before.get(name, 0)}
            assert grew <= {ar.ADOPTION_SCANS_COLLECTION, ar.ADOPTION_ITEMS_COLLECTION,
                            "audit_events", "audit_idempotency"}, \
                "a readiness scan wrote outside its own collections: %s" % sorted(grew)
            for name in (m.FILES_COLLECTION, m.VERSIONS_COLLECTION,
                         m.RELATIONS_COLLECTION, m.LOCATIONS_COLLECTION,
                         "media_files"):
                assert after.get(name, 0) == before.get(name, 0)
        scratch(test)

    def test_the_originals_are_byte_identical_after_a_real_scan(self):
        async def test(db, sysdb, roots):
            kept = {}
            for index in range(5):
                name = "orig%d.pdf" % index
                path = roots.write(name, b"content %d" % index)
                kept[path] = (os.path.getsize(path), os.path.getmtime(path),
                              hashlib.sha256(open(path, "rb").read()).hexdigest())
                await _seed(db, A, "media_files", [_media_row("md-%d" % index, name)])
            service = readiness(db, A, roots)
            out = await service.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            await service.validate_plan(_ctx(OPERATOR_A, A), scan_id=out["id"])
            for path, (size, mtime, digest) in kept.items():
                assert os.path.exists(path)
                assert os.path.getsize(path) == size
                assert os.path.getmtime(path) == mtime
                with open(path, "rb") as handle:
                    assert hashlib.sha256(handle.read()).hexdigest() == digest
        scratch(test)

    def test_all_sixteen_declared_sources_scan_on_a_real_server(self):
        async def test(db, sysdb, roots):
            for source in mp.LEGACY_SOURCES:
                name = "%s.bin" % source.key
                roots.write(name, b"bytes of " + source.key.encode())
                await _seed(db, A, source.collection, [{
                    "id": "lg-%s" % source.key, "stored_filename": name,
                    "filename": name, "url": "/uploads/" + name,
                    "avatar_url": "/uploads/" + name,
                    "original_file_url": "/uploads/" + name,
                    "context_type": "project", "context_id": "P-1",
                    "project_id": "P-1"}])
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A))
            seen = {i["source_key"] for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW}
            assert seen == {s.key for s in mp.LEGACY_SOURCES}
            assert ar.PROPOSE_ADOPT_IN_PLACE not in {
                i["proposed_action"] for i in out["item_records"]}
            persisted = await db[ar.ADOPTION_ITEMS_COLLECTION].count_documents(
                {"scan_id": out["id"]})
            assert persisted == len(out["item_records"])
        scratch(test)

    def test_no_filesystem_path_is_persisted_on_a_real_server(self):
        async def test(db, sysdb, roots):
            import json
            roots.write("deep/inside.pdf", b"p")
            await _seed(db, A, "media_files", [_media_row("md-1", "deep/inside.pdf")])
            await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                source_keys=["media_files"])
            for collection in (ar.ADOPTION_ITEMS_COLLECTION,
                               ar.ADOPTION_SCANS_COLLECTION, "audit_events"):
                payload = json.dumps(await db[collection].find(
                    {}, {"_id": 0}).to_list(None))
                assert roots.base not in payload
                assert mp.LEGACY_UPLOADS_ROOT not in payload
        scratch(test)


# ═══════════════════════════════════════════════════ C02 bounded correction
async def _seed_registered(db, org, file_id, data, *, relations,
                           availability=m.AVAILABILITY_AVAILABLE,
                           provider_kind="s3_compatible", size=None):
    """A registry row the C02 comparisons read, written to the real server.

    Seeded directly rather than through the upload path because the identity
    under test is the DERIVED ``file_id`` of a legacy row, which the upload
    path generates for itself.
    """
    digest = m.checksum(hashlib.sha256(data).hexdigest())
    await db[m.FILES_COLLECTION].insert_one({
        "id": file_id, "org_id": org, "status": m.FILE_ACTIVE,
        "category": m.CATEGORY_PHOTO_VIDEO,
        "sensitivity": m.SENSITIVITY_STANDARD, "created_at": "2026-01-01"})
    await db[m.VERSIONS_COLLECTION].insert_one({
        "file_id": file_id, "org_id": org, "version_no": 1, "is_current": True,
        "checksum": digest, "checksum_key": m.checksum_key(digest),
        "size_bytes": len(data) if size is None else size,
        "created_at": "2026-01-01"})
    await db[m.LOCATIONS_COLLECTION].insert_one({
        "file_id": file_id, "org_id": org, "version_no": 1,
        "role": m.LOCATION_ROLE_PRIMARY, "provider_kind": provider_kind,
        "provider_binding_id": "pb-1", "object_key": "k/" + file_id,
        "availability": availability, "created_at": "2026-01-01"})
    for relation_type, record_id in relations:
        await db[m.RELATIONS_COLLECTION].insert_one({
            "file_id": file_id, "org_id": org, "relation_type": relation_type,
            "record_id": record_id, "active": True, "created_at": "2026-01-01"})


class TestRealC02Readiness:
    """Defect 1 and 2 on the real server: evidence and relation identity."""

    def test_an_unobserved_original_is_never_ready_on_a_real_server(self):
        """The row is registered and available, but the bytes are NOT there."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            legacy, data = "md-unobs", b"registered content"
            derived = mp.deterministic_file_id(A, "media_files", legacy)
            await _seed_registered(db, A, derived, data,
                                   relations=[(m.RELATION_PROJECT, "P-1")])
            await _seed(db, A, "media_files", [_media_row(legacy, "gone.pdf")])
            # deliberately NOT written to disk
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["state"] != ar.READY_TO_ADOPT
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
            assert ar.REASON_ORIGINAL_NOT_OBSERVED in row["reasons"]
        scratch(test)

    def test_an_unrelated_relation_is_not_already_registered_on_a_real_server(self):
        """Defect 2: the count is 1, but it points somewhere else."""
        async def test(db, sysdb, roots):
            for project in ("P-1", "P-OTHER"):
                await db["projects"].insert_one({"id": project, "org_id": A,
                                                 "name": "site " + project})
            legacy, data = "md-unrelated", b"the very same bytes"
            derived = mp.deterministic_file_id(A, "media_files", legacy)
            # one ACTIVE relation, to the WRONG project
            await _seed_registered(db, A, derived, data,
                                   relations=[(m.RELATION_PROJECT, "P-OTHER")])
            await _seed(db, A, "media_files", [_media_row(legacy, "u.pdf")])
            roots.write("u.pdf", data)
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["relation_count"] == 1
            assert row["registry"]["relations_match"] is False
            assert row["registry"]["relations_missing"] == [
                [m.RELATION_PROJECT, "P-1"]]
            assert row["state"] != ar.ALREADY_REGISTERED
            assert row["proposed_action"] != ar.PROPOSE_REGISTER_REFERENCE_ONLY
            assert ar.REASON_RELATION_NOT_REGISTERED in row["reasons"]
        scratch(test)

    def test_the_exact_relation_is_recognised_on_a_real_server(self):
        """The positive half: same type, same target, target resolves."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            legacy, data = "md-exact", b"exactly these bytes"
            derived = mp.deterministic_file_id(A, "media_files", legacy)
            await _seed_registered(db, A, derived, data,
                                   relations=[(m.RELATION_PROJECT, "P-1")])
            await _seed(db, A, "media_files", [_media_row(legacy, "e.pdf")])
            roots.write("e.pdf", data)
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["relations_match"] is True
            assert row["registry"]["relations_missing"] == []
            assert row["registry"]["relation_targets_missing"] == []
            assert row["state"] == ar.ALREADY_REGISTERED
            assert row["proposed_action"] == ar.PROPOSE_NO_ACTION
        scratch(test)

    def test_a_relation_belonging_to_the_other_tenant_does_not_count(self):
        """Tenant isolation of the C02 relation comparison itself."""
        async def test(db, sysdb, roots):
            # the project and the relation live in B; A plans the same target
            await db["projects"].insert_one({"id": "P-1", "org_id": B,
                                             "name": "b site"})
            legacy, data = "md-cross", b"cross tenant bytes"
            derived = mp.deterministic_file_id(A, "media_files", legacy)
            await _seed_registered(db, B, derived, data,
                                   relations=[(m.RELATION_PROJECT, "P-1")])
            await _seed(db, A, "media_files", [_media_row(legacy, "x.pdf")])
            roots.write("x.pdf", data)
            out = await readiness(db, A, roots).scan(_ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            # A sees neither the file, nor the relation, nor the target
            assert row["registry"]["file_exists"] is False
            assert row["registry"]["relations_match"] is False
            assert row["registry"]["relation_targets_missing"] == [
                [m.RELATION_PROJECT, "P-1"]]
            assert row["state"] != ar.ALREADY_REGISTERED
            assert row["state"] != ar.READY_TO_ADOPT
        scratch(test)

    def test_a_stored_available_location_alone_is_not_readiness(self):
        """Defect 1: the registry SAYS available; the disk says nothing."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            legacy, data = "md-stored", b"stored only"
            derived = mp.deterministic_file_id(A, "media_files", legacy)
            await _seed_registered(db, A, derived, data,
                                   relations=[(m.RELATION_PROJECT, "P-1")])
            await _seed(db, A, "media_files", [_media_row(legacy, "s.pdf")])
            roots.write("s.pdf", data)
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=roots.inventory(allow_content_read=False))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["verified_location"] is True
            assert row["observed"]["checksum"] is None
            assert row["state"] != ar.READY_TO_ADOPT
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
        scratch(test)


class TestRealC02BudgetDeterminism:
    """Defects 3 and 4 on the real server."""

    def test_repeated_validation_at_an_exact_limit_never_drifts(self):
        """The review's counterexample, against a real stored plan."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            for index in range(2):
                roots.write("l%d.pdf" % index, b"limit bytes %d" % index)
                await _seed(db, A, "media_files",
                            [_media_row("md-%d" % index, "l%d.pdf" % index)])
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=roots.inventory(max_checksum_objects=2))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            for _attempt in range(5):
                answer = await svc.validate_plan(_ctx(OPERATOR_A, A),
                                                  scan_id=out["id"])
                assert answer["valid"] is True, answer
                assert answer["plan_hash"] == out["plan_hash"]
            assert await db["audit_events"].count_documents(
                {"action": ar.AUDIT_PLAN_REFUSED}) == 0
        scratch(test)

    def test_a_db_row_and_the_walk_share_one_charge_on_a_real_server(self):
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            roots.write("shared.pdf", b"shared real bytes")
            await _seed(db, A, "media_files", [_media_row("md-1", "shared.pdf")])
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=roots.inventory(max_checksum_objects=1))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            assert out["inventory"]["checksums_read"] == 1
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["observed"]["checksum"] is not None
            assert row["observed"]["checksum_reason"] is None
        scratch(test)

    def test_an_over_cap_object_is_refused_and_persisted_as_refused(self):
        """Defect 4 end to end: the refusal is what the real server stores."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            roots.write("big.pdf", b"z" * 500)
            await _seed(db, A, "media_files", [_media_row("md-1", "big.pdf")])
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=roots.inventory(max_object_bytes=100))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            stored = await db[ar.ADOPTION_ITEMS_COLLECTION].find_one(
                {"scan_id": out["id"], "direction": ar.DIRECTION_DB_ROW})
            assert stored["observed"]["checksum"] is None
            assert stored["observed"]["checksum_reason"] == \
                ar.REASON_BUDGET_EXHAUSTED
            assert stored["state"] != ar.READY_TO_ADOPT
            assert out["inventory"]["bytes_read"] == 0
        scratch(test)


# ═══════════════════════════════════════════════════ C03 bounded correction
def _symlinks_work():
    probe = tempfile.mkdtemp(prefix="w006d_linkprobe_")
    try:
        os.symlink(probe, os.path.join(probe, "l"))
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)


needs_symlinks = pytest.mark.skipif(
    not _symlinks_work(), reason="this host cannot create a symlink, so the "
                                 "link gate cannot be exercised here — NOT a pass")


class _Spy:
    def __init__(self):
        self.opened = []

    def __call__(self, path):
        self.opened.append(path)
        return open(path, "rb")


def _gated(roots, spy=None, **budget):
    budget.setdefault("allow_content_read", True)
    return ar.LegacyRootInventory(
        [roots.uploads, roots.projects],
        budget=ar.ScanBudget(**budget),
        declared_roots={mp.LEGACY_PROJECT_UPLOADS_ROOT: roots.projects,
                        mp.LEGACY_UPLOADS_ROOT: roots.uploads},
        opener=spy or (lambda p: open(p, "rb")))


class TestRealC03Bounds:
    """The three C02 counterexamples, against a real server."""

    def test_a_row_past_the_object_cap_is_persisted_as_refused(self):
        """Defect 1: what the real server stores is the refusal, not a hash."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            roots.write("aaa.pdf", b"first")
            roots.write("zzz.pdf", b"second")
            await _seed(db, A, "media_files", [_media_row("md-1", "zzz.pdf")])
            spy = _Spy()
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=_gated(roots, spy, max_objects=1))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            stored = await db[ar.ADOPTION_ITEMS_COLLECTION].find_one(
                {"scan_id": out["id"], "direction": ar.DIRECTION_DB_ROW})
            assert stored["observed"]["checksum"] is None
            assert stored["observed"]["refusal"] == \
                ar.REASON_OBJECT_BUDGET_EXHAUSTED
            assert stored["state"] not in (ar.MISSING_ORIGINAL, ar.READY_TO_ADOPT)
            assert out["inventory"]["objects_seen"] == 1
            assert out["inventory"]["truncated"] is True
            assert all("zzz" not in path for path in spy.opened), spy.opened
        scratch(test)

    def test_the_byte_budget_is_never_exceeded_on_a_real_scan(self):
        """Defect 2: the stored counters and the physical read agree."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            for index in range(3):
                roots.write("b%d.pdf" % index, b"q" * 10)
                await _seed(db, A, "media_files",
                            [_media_row("md-%d" % index, "b%d.pdf" % index)])
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=_gated(roots, max_object_bytes=10,
                                 max_checksum_bytes=20))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            scan_doc = await db[ar.ADOPTION_SCANS_COLLECTION].find_one(
                {"id": out["id"]})
            assert scan_doc["inventory"]["bytes_read"] <= 20
            assert out["inventory"]["bytes_read"] <= 20
            hashed = [i for i in out["item_records"]
                      if (i["observed"] or {}).get("checksum")]
            assert len(hashed) == 2, "the byte budget was not binding"
            # and repeating it decides the same way
            answer = await svc.validate_plan(_ctx(OPERATOR_A, A),
                                              scan_id=out["id"])
            assert answer["valid"] is True
        scratch(test)

    @needs_symlinks
    def test_a_symlinked_file_is_refused_and_never_read_on_a_real_scan(self):
        """Defect 3: a real in-root symlink to a real outside target."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            outside = os.path.join(roots.base, "elsewhere")
            os.makedirs(outside, exist_ok=True)
            secret = os.path.join(outside, "secret.pdf")
            with open(secret, "wb") as handle:
                handle.write(b"NOT YOURS")
            os.symlink(secret, os.path.join(roots.uploads, "linked.pdf"))
            await _seed(db, A, "media_files", [_media_row("md-1", "linked.pdf")])
            spy = _Spy()
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)), inventory=_gated(roots, spy))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            stored = await db[ar.ADOPTION_ITEMS_COLLECTION].find_one(
                {"scan_id": out["id"], "direction": ar.DIRECTION_DB_ROW})
            assert stored["observed"]["checksum"] is None
            assert stored["observed"]["refusal"] == ar.REASON_PATH_IS_LINK
            assert stored["state"] not in (ar.MISSING_ORIGINAL, ar.READY_TO_ADOPT)
            assert spy.opened == [], spy.opened
            # the outside file is untouched and nothing about it was stored
            with open(secret, "rb") as handle:
                assert handle.read() == b"NOT YOURS"
            text = str(stored)
            assert "NOT YOURS" not in text and "secret" not in text
        scratch(test)


class TestRealC04BoundedInventory:
    """The bounded-inventory accounting, as the real server stores it."""

    @needs_symlinks
    def test_a_bounded_scan_persists_its_real_counters(self):
        """Defect: refused entries were uncharged, so the stored record lied.

        The scan document is what a later slice and an operator read, so the
        counters it persists have to be the ones the pass actually spent.
        """
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            outside = os.path.join(roots.base, "elsewhere")
            os.makedirs(outside, exist_ok=True)
            for index in range(3):
                target = os.path.join(outside, "t%d.pdf" % index)
                with open(target, "wb") as handle:
                    handle.write(b"NOT YOURS %d" % index)
                os.symlink(target,
                           os.path.join(roots.uploads, "link%d.pdf" % index))
            spy = _Spy()
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=_gated(roots, spy, max_objects=1))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            scan_doc = await db[ar.ADOPTION_SCANS_COLLECTION].find_one(
                {"id": out["id"]})
            assert scan_doc["inventory"]["objects_seen"] == 1
            assert scan_doc["inventory"]["truncated"] is True
            assert scan_doc["inventory"]["bytes_read"] == 0
            items = await db[ar.ADOPTION_ITEMS_COLLECTION].count_documents(
                {"scan_id": out["id"],
                 "direction": ar.DIRECTION_PHYSICAL_OBJECT})
            assert items <= 1, items
            assert spy.opened == [], spy.opened
            # the refused targets are untouched and absent from the records
            for index in range(3):
                with open(os.path.join(outside, "t%d.pdf" % index), "rb") as h:
                    assert h.read() == b"NOT YOURS %d" % index
            stored = [d async for d in db[ar.ADOPTION_ITEMS_COLLECTION].find(
                {"scan_id": out["id"]})]
            assert "NOT YOURS" not in str(stored)
        scratch(test)

    @needs_symlinks
    def test_a_bounded_plan_revalidates_on_a_real_server(self):
        """Truncation is not drift: the same bounded inputs stay valid."""
        async def test(db, sysdb, roots):
            await db["projects"].insert_one({"id": "P-1", "org_id": A,
                                             "name": "site"})
            outside = os.path.join(roots.base, "elsewhere")
            os.makedirs(outside, exist_ok=True)
            target = os.path.join(outside, "t.pdf")
            with open(target, "wb") as handle:
                handle.write(b"outside")
            for name in ("a.pdf", "b.pdf"):
                os.symlink(target, os.path.join(roots.uploads, name))
            svc = ar.LegacyAdoptionReadiness(
                FileRegistry(TenantData(db, A)),
                inventory=_gated(roots, max_objects=1))
            out = await svc.scan(_ctx(OPERATOR_A, A), source_keys=["media_files"])
            for _attempt in range(3):
                answer = await svc.validate_plan(_ctx(OPERATOR_A, A),
                                                  scan_id=out["id"])
                assert answer["valid"] is True, answer
                assert answer["plan_hash"] == out["plan_hash"]
            assert await db["audit_events"].count_documents(
                {"action": ar.AUDIT_PLAN_REFUSED}) == 0
        scratch(test)
