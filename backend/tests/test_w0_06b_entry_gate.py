"""
W0-06B entry gate — the four W0-06A review findings, closed and PROVEN.

``coordination/REVIEWS/W0-06A.md`` (Codex, CHANGES_REQUESTED on 9040fc1d) found:

1. concurrent AuditEvent appends of one tenant duplicated a sequence
   (``[1, 1, 2, 3]``) and forked the hash chain;
2. ``register_file(verify_relation_targets=False)`` and
   ``add_relation(verify_target=False)`` let a caller link a file to a missing
   or foreign-tenant record;
3. a delete receipt for ONE version marked every location of the file missing
   and the whole file ``deleted_at_provider``;
4. the duplicate-checksum answer depended on ``(created_at, random id)``, so
   two files registered in one clock tick could swap places.

Every finding is tested three ways: the positive behaviour, the forbidden
behaviour, and an UNSAFE MUTATION — the defect deliberately put back — which
the same test machinery must catch. A test that cannot fail on the bug it is
named after proves nothing. The real-server half of this gate is
``tests/test_w0_06b_real_mongo.py``.

    pytest tests/test_w0_06b_entry_gate.py -v --noconftest
"""
import asyncio
import hashlib
import inspect
import sys
import uuid
from pathlib import Path

import pytest

from app.audit import store
from app.audit.envelope import RETENTION_R2_PROJECT_OPERATIONAL, build_event
from app.files import models as m
from app.files.providers.base import DeleteReceipt, IntegrityVerdict
from app.files.registry import (
    ON_DUPLICATE_NEW_FILE,
    STATUS_DUPLICATE,
    FileRegistry,
    FileRegistryError,
    RelationTargetNotFound,
)
from app.tenancy.data_access import TenantData

pytest.importorskip("mongomock_motor")

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import w0_06a_file_registry_guard as guard          # noqa: E402

A, B = "BEG", "TCB"
ACTOR = "user-1"
PROJECT = "P-1"
ONLY_IN_B = "P-ONLY-B"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def digest(text: str) -> dict:
    return {"algorithm": m.CHECKSUM_SHA256, "value": hashlib.sha256(text.encode()).hexdigest()}


async def _db():
    from mongomock_motor import AsyncMongoMockClient
    db = AsyncMongoMockClient()["w0_06b_gate_%s" % uuid.uuid4().hex[:6]]
    for org in (A, B):
        await db["projects"].insert_one({"id": PROJECT, "org_id": org, "name": org})
    await db["projects"].insert_one({"id": ONLY_IN_B, "org_id": B, "name": "B only"})
    return db


async def _register(reg, text="bytes", name="a.jpg", **kw):
    return await reg.register_file(
        actor_id=ACTOR, display_name=name, original_name=name,
        category=m.CATEGORY_PHOTO_VIDEO, checksum_value=digest(text),
        size_bytes=len(text), mime_type="image/jpeg", **kw)


def _event(tenant, n=0):
    return build_event(tenant_id=tenant, actor_type="human", actor_id=ACTOR,
                       action="test.append", source_flow="FLOW-040",
                       retention_class=RETENTION_R2_PROJECT_OPERATIONAL,
                       entity_type="probe", entity_id="probe-%d" % n)


async def _chain(db, tenant):
    return await db["audit_events"].find({"tenant_id": tenant}, {"_id": 0}).sort(
        "sequence", 1).to_list(None)


def _guard_source(tmp_path, source, rel_name="registry.py"):
    """Run the guard over ``source`` placed at the REAL registry-service path.

    Some rules are scoped to ``app/files/registry.py`` itself, so the mutated
    copy has to be judged under that name. The real file is restored after.
    """
    target = BACKEND / "app" / "files" / rel_name
    original = target.read_text(encoding="utf-8")
    target.write_text(source, encoding="utf-8")
    try:
        return guard.check_files([target.relative_to(BACKEND).as_posix()])
    finally:
        target.write_text(original, encoding="utf-8")


def _rules(found):
    return {v[2] for v in found}


REGISTRY_SRC = (BACKEND / "app" / "files" / "registry.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════ finding 1 — concurrent audit chain
class TestAuditChainUnderConcurrency:
    def test_the_slot_key_is_unambiguous_across_tenants(self):
        # a tenant id containing the separator cannot collide with another
        assert store.chain_slot_id("a:1", 2) != store.chain_slot_id("a", 12)
        assert store.chain_slot_id("a:1", 2) != store.chain_slot_id("a", 1)
        assert store.chain_slot_id(A, 1) != store.chain_slot_id(B, 1)
        assert store.chain_slot_id(A, 7) == store.chain_slot_id(A, 7)

    def test_a_writer_that_read_a_stale_head_retries_instead_of_forking(self, monkeypatch):
        """The exact race of the review, made deterministic.

        Writer 2 reads the head BEFORE writer 1 inserts, so both compute
        sequence N+1. The slot refuses the second insert and writer 2 chains
        onto writer 1's event.
        """
        async def body():
            db = await _db()
            await store.record_event(db, _event(A, 0))
            real_last = store._last_event
            # writer 2 read the head here ...
            stale = await real_last(db, A)
            # ... and writer 1 appended before writer 2 could insert
            await store.record_event(db, _event(A, 1))
            calls = {"n": 0}

            async def racing_last(db_, tenant):
                calls["n"] += 1
                return stale if calls["n"] == 1 else await real_last(db_, tenant)

            monkeypatch.setattr(store, "_last_event", racing_last)
            out = await store.record_event(db, _event(A, 2))
            monkeypatch.setattr(store, "_last_event", real_last)
            chain = await _chain(db, A)
            assert [e["sequence"] for e in chain] == [1, 2, 3]
            assert out["sequence"] == 3 and calls["n"] >= 2
            assert (await store.verify_tenant_chain(db, A)) == (True, None)
        run(body())

    def test_mutation_random_slot_reproduces_the_fork(self, monkeypatch):
        """UNSAFE MUTATION: give every insert a fresh key (the pre-fix code).

        The stale-head race then lands TWO events with one sequence — the
        ``[1, 1, 2, 3]`` the review saw — and the chain verifier rejects it.
        """
        async def body():
            db = await _db()
            await store.record_event(db, _event(A, 0))
            stale = await store._last_event(db, A)
            await store.record_event(db, _event(A, 1))
            monkeypatch.setattr(store, "chain_slot_id",
                                lambda tenant, seq: "random-%s" % uuid.uuid4().hex)

            async def stale_last(db_, tenant):
                return stale
            monkeypatch.setattr(store, "_last_event", stale_last)
            await store.record_event(db, _event(A, 2))
            chain = await _chain(db, A)
            assert [e["sequence"] for e in chain] == [1, 2, 2]
            ok, reason = await store.verify_tenant_chain(db, A)
            assert ok is False and reason
        run(body())

    def test_interleaved_writers_of_two_tenants_keep_contiguous_chains(self):
        async def body():
            db = await _db()
            await asyncio.gather(*[store.record_event(db, _event(org, i))
                                   for i in range(15) for org in (A, B)])
            for org in (A, B):
                chain = await _chain(db, org)
                assert [e["sequence"] for e in chain] == list(range(1, 16))
                assert {e["tenant_id"] for e in chain} == {org}
                assert (await store.verify_tenant_chain(db, org)) == (True, None)
        run(body())

    def test_an_append_that_can_never_win_gives_up_loudly(self, monkeypatch):
        async def body():
            db = await _db()
            await store.record_event(db, _event(A, 0))
            await store.record_event(db, _event(A, 1))
            first = (await _chain(db, A))[0]

            async def always_stale(db_, tenant):
                return first
            monkeypatch.setattr(store, "_last_event", always_stale)
            monkeypatch.setattr(store, "MAX_APPEND_ATTEMPTS", 3)
            with pytest.raises(store.AuditChainContention):
                await store.record_event(db, _event(A, 2))
            # and it wrote nothing while failing
            assert [e["sequence"] for e in await _chain(db, A)] == [1, 2]
        run(body())

    def test_an_idempotent_retry_never_takes_a_second_sequence(self):
        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            for _ in range(3):
                await _register(reg, idempotency_key="upload-1")
            chain = await _chain(db, A)
            assert [e["sequence"] for e in chain] == [1]
            assert (await store.verify_tenant_chain(db, A)) == (True, None)
        run(body())

    def test_a_non_duplicate_storage_error_is_not_swallowed(self, monkeypatch):
        async def body():
            db = await _db()

            class Boom(Exception):
                pass

            async def failing_insert(doc):
                raise Boom("disk full")
            coll = db["audit_events"]
            monkeypatch.setattr(type(coll), "insert_one",
                                lambda self, doc, *a, **k: failing_insert(doc))
            with pytest.raises(Boom):
                await store.record_event(db, _event(A))
        run(body())


# ═══════════════════════════════ finding 2 — no relation-target verification bypass
class TestNoRelationTargetBypass:
    @pytest.mark.parametrize("method,param", [
        ("register_file", "verify_relation_targets"), ("add_relation", "verify_target")])
    def test_the_public_methods_have_no_bypass_parameter(self, method, param):
        params = inspect.signature(getattr(FileRegistry, method)).parameters
        assert param not in params
        assert not [p for p in params if guard._is_bypass_name(p)], params

    def test_a_caller_supplied_bypass_flag_is_refused_and_writes_nothing(self):
        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            with pytest.raises(TypeError):
                await _register(reg, relations=[{"relation_type": m.RELATION_PROJECT,
                                                 "record_id": "NOPE"}],
                                verify_relation_targets=False)
            file_id = (await _register(reg))["file_id"]
            with pytest.raises(TypeError):
                await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                       relation_type=m.RELATION_PROJECT, record_id="NOPE",
                                       verify_target=False)
            assert await db[m.FILES_COLLECTION].count_documents({}) == 1
            assert await db[m.RELATIONS_COLLECTION].count_documents({}) == 0
        run(body())

    @pytest.mark.parametrize("target", ["NOPE", ONLY_IN_B])
    def test_a_missing_or_foreign_target_is_refused_on_register(self, target):
        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            with pytest.raises(RelationTargetNotFound):
                await _register(reg, relations=[{"relation_type": m.RELATION_PROJECT,
                                                 "record_id": target}])
            assert await db[m.FILES_COLLECTION].count_documents({}) == 0
            assert await db[m.VERSIONS_COLLECTION].count_documents({}) == 0
            assert await db[m.RELATIONS_COLLECTION].count_documents({}) == 0
        run(body())

    @pytest.mark.parametrize("target", ["NOPE", ONLY_IN_B])
    def test_a_missing_or_foreign_target_is_refused_on_add_relation(self, target):
        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            file_id = (await _register(reg))["file_id"]
            with pytest.raises(RelationTargetNotFound):
                await reg.add_relation(actor_id=ACTOR, file_id=file_id,
                                       relation_type=m.RELATION_PROJECT, record_id=target)
            assert await db[m.RELATIONS_COLLECTION].count_documents({}) == 0
            # the same id that exists only in B is linkable by B itself
            if target == ONLY_IN_B:
                reg_b = FileRegistry(TenantData(db, B))
                fb = (await _register(reg_b, text="b"))["file_id"]
                out = await reg_b.add_relation(actor_id=ACTOR, file_id=fb,
                                               relation_type=m.RELATION_PROJECT, record_id=target)
                assert out["status"] == "registered"
        run(body())

    def test_an_existing_target_in_this_tenant_still_links(self):
        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            out = await _register(reg, relations=[{"relation_type": m.RELATION_PROJECT,
                                                   "record_id": PROJECT}])
            assert len(out["relation_ids"]) == 1
        run(body())

    def test_the_real_registry_source_passes_the_bypass_rule(self, tmp_path):
        assert "W06B-RELBYPASS" not in _rules(_guard_source(tmp_path, REGISTRY_SRC))

    @pytest.mark.parametrize("mutation", [
        # the pre-fix parameter, put back
        ("record_id: str, role: Optional[str] = None,\n                           "
         "idempotency_key",
         "record_id: str, role: Optional[str] = None,\n                           "
         "verify_target: bool = True, idempotency_key"),
        # the pre-fix conditional check, put back
        ("            await self._assert_relation_target(relation_type, record_id)\n",
         "            if role != 'migration':\n"
         "                await self._assert_relation_target(relation_type, record_id)\n"),
    ])
    def test_mutation_reinstating_the_bypass_is_rejected(self, tmp_path, mutation):
        old, new = mutation
        assert old in REGISTRY_SRC
        found = _guard_source(tmp_path, REGISTRY_SRC.replace(old, new, 1))
        assert "W06B-RELBYPASS" in _rules(found), found

    def test_a_call_passing_a_bypass_keyword_is_rejected(self, tmp_path):
        target = BACKEND / "app" / "routes" / "_w0_06b_probe_bypass.py"
        target.write_text(
            "async def f(reg):\n"
            "    await reg.add_relation(actor_id='u', file_id='f', relation_type='project',\n"
            "                           record_id='p', skip_target_check=True)\n",
            encoding="utf-8")
        try:
            found = guard.check_files([target.relative_to(BACKEND).as_posix()])
        finally:
            target.unlink()
        assert "W06B-RELBYPASS" in _rules(found)


# ═══════════════════════════════════════ finding 3 — scoped physical delete
async def _two_version_file(db):
    reg = FileRegistry(TenantData(db, A))
    file_id = (await _register(reg, text="v1", relations=[
        {"relation_type": m.RELATION_PROJECT, "record_id": PROJECT}]))["file_id"]
    await reg.add_version(actor_id=ACTOR, file_id=file_id, checksum_value=digest("v2"),
                          size_bytes=2, mime_type="image/jpeg", original_name="a.jpg",
                          reason="retake")
    for v in (1, 2):
        await reg.set_provider_location(actor_id=ACTOR, file_id=file_id, version_no=v,
                                        provider_kind=m.PROVIDER_S3_COMPATIBLE,
                                        provider_binding_id="s3", container="bucket",
                                        object_key="obj/v%d" % v)
        await reg.record_integrity_check(
            actor_id=ACTOR, file_id=file_id, version_no=v,
            verdict=IntegrityVerdict(availability=m.AVAILABILITY_AVAILABLE,
                                     checked_at="2026-10-04T00:00:00+00:00"))
    return reg, file_id


CONFIRMED = DeleteReceipt(state=m.DELETE_PROVIDER_CONFIRMED, provider_kind=m.PROVIDER_S3_COMPATIBLE,
                          response_code="OK", confirmed_at="2026-10-04T01:00:00+00:00")
REFUSED = DeleteReceipt(state=m.DELETE_PROVIDER_REFUSED, provider_kind=m.PROVIDER_S3_COMPATIBLE,
                        response_code="403")


class TestDeleteIsScopedToWhatWasAsked:
    def test_deleting_version_1_leaves_version_2_and_the_file_alone(self):
        async def body():
            db = await _db()
            reg, file_id = await _two_version_file(db)
            v2_before = await reg.primary_location(file_id, 2)
            req = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                    version_no=1, reason="old draft")
            assert req["scope"] == m.DELETE_SCOPE_VERSION and len(req["location_ids"]) == 1
            assert (await reg.require_file(file_id))["status"] == m.FILE_ACTIVE
            out = await reg.record_delete_result(actor_id=ACTOR, request_id=req["request_id"],
                                                 receipt=CONFIRMED)
            assert out["original_destroyed"] is True and out["version_no"] == 1
            v1 = await reg.primary_location(file_id, 1)
            assert v1["availability"] == m.AVAILABILITY_MISSING
            assert v1["destroyed_by_request_id"] == req["request_id"]
            assert await reg.primary_location(file_id, 2) == v2_before, "version 2 was touched"
            assert (await reg.require_file(file_id))["status"] == m.FILE_ACTIVE
            answer = await reg.canonical_original(file_id)
            assert answer["available"] is True and answer["version_no"] == 2
            event = await db["audit_events"].find_one(
                {"action": "file.physical_delete.result"}, {"_id": 0})
            assert event["structured_diff"]["scope"] == m.DELETE_SCOPE_VERSION
            assert event["structured_diff"]["location_ids"] == [v1["id"]]
            assert event["structured_diff"]["file_status_changed"] is False
        run(body())

    def test_mutation_unscoped_location_update_is_caught(self, tmp_path):
        """UNSAFE MUTATION: the pre-fix ``update_many({"file_id": ...})``."""
        old = '{"file_id": file_id, "id": {"$in": location_ids}},'
        assert old in REGISTRY_SRC
        found = _guard_source(tmp_path, REGISTRY_SRC.replace(old, '{"file_id": file_id},', 1))
        assert "W06B-DELSCOPE" in _rules(found), found
        assert "W06B-DELSCOPE" not in _rules(_guard_source(tmp_path, REGISTRY_SRC))

    def test_a_whole_file_delete_must_be_asked_for_explicitly(self):
        async def body():
            db = await _db()
            reg, file_id = await _two_version_file(db)
            with pytest.raises(FileRegistryError):
                await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id, reason="r")
            with pytest.raises(FileRegistryError):
                await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id, reason="r",
                                                  version_no=1, whole_file=True)
            assert await db[m.DELETE_REQUESTS_COLLECTION].count_documents({}) == 0
            req = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                    reason="erasure", whole_file=True)
            assert req["scope"] == m.DELETE_SCOPE_FILE and len(req["location_ids"]) == 2
            assert (await reg.require_file(file_id))["status"] == m.FILE_DELETE_REQUESTED
            await reg.record_delete_result(actor_id=ACTOR, request_id=req["request_id"],
                                           receipt=CONFIRMED)
            assert (await reg.require_file(file_id))["status"] == m.FILE_DELETED_AT_PROVIDER
            for v in (1, 2):
                assert (await reg.primary_location(file_id, v))["availability"] == \
                    m.AVAILABILITY_MISSING
        run(body())

    def test_one_location_of_a_version_can_be_targeted_alone(self):
        async def body():
            db = await _db()
            reg, file_id = await _two_version_file(db)
            backup = await reg.set_provider_location(
                actor_id=ACTOR, file_id=file_id, version_no=2,
                provider_kind=m.PROVIDER_SYNOLOGY_NAS, provider_binding_id="nas",
                container="share", object_key="backup/v2", role=m.LOCATION_ROLE_BACKUP)
            primary_before = await reg.primary_location(file_id, 2)
            req = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id, version_no=2,
                                                    location_id=backup["location_id"],
                                                    reason="drop backup copy")
            assert req["location_ids"] == [backup["location_id"]]
            await reg.record_delete_result(actor_id=ACTOR, request_id=req["request_id"],
                                           receipt=CONFIRMED)
            assert await reg.primary_location(file_id, 2) == primary_before
            gone = await reg.current_location(file_id, 2, m.LOCATION_ROLE_BACKUP)
            assert gone["availability"] == m.AVAILABILITY_MISSING
        run(body())

    def test_a_location_added_after_the_request_is_not_covered_by_its_answer(self):
        async def body():
            db = await _db()
            reg, file_id = await _two_version_file(db)
            req = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                    version_no=1, reason="r")
            # a provider migration lands version 1 somewhere new meanwhile
            moved = await reg.set_provider_location(
                actor_id=ACTOR, file_id=file_id, version_no=1,
                provider_kind=m.PROVIDER_GOOGLE_DRIVE, provider_binding_id="gd",
                container="drive", object_key="v1-moved")
            await reg.record_delete_result(actor_id=ACTOR, request_id=req["request_id"],
                                           receipt=CONFIRMED)
            now = await reg.primary_location(file_id, 1)
            assert now["id"] == moved["location_id"]
            assert now["destroyed_at_provider"] is None
            assert now["availability"] == m.AVAILABILITY_UNVERIFIED
        run(body())

    def test_a_request_is_answered_once(self):
        async def body():
            db = await _db()
            reg, file_id = await _two_version_file(db)
            req = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                    version_no=1, reason="r")
            await reg.record_delete_result(actor_id=ACTOR, request_id=req["request_id"],
                                           receipt=REFUSED)
            with pytest.raises(FileRegistryError):
                await reg.record_delete_result(actor_id=ACTOR, request_id=req["request_id"],
                                               receipt=CONFIRMED)
            assert (await reg.primary_location(file_id, 1))["availability"] == \
                m.AVAILABILITY_AVAILABLE
        run(body())

    def test_a_refused_version_delete_changes_nothing(self):
        async def body():
            db = await _db()
            reg, file_id = await _two_version_file(db)
            before = [await reg.primary_location(file_id, v) for v in (1, 2)]
            req = await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                    version_no=1, reason="r")
            out = await reg.record_delete_result(actor_id=ACTOR, request_id=req["request_id"],
                                                 receipt=REFUSED)
            assert out["original_destroyed"] is False
            assert [await reg.primary_location(file_id, v) for v in (1, 2)] == before
            assert (await reg.require_file(file_id))["status"] == m.FILE_ACTIVE
        run(body())

    def test_nothing_to_delete_is_refused_not_recorded(self):
        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            file_id = (await _register(reg))["file_id"]
            with pytest.raises(FileRegistryError):
                await reg.request_physical_delete(actor_id=ACTOR, file_id=file_id,
                                                  version_no=1, reason="r")
            assert await db[m.DELETE_REQUESTS_COLLECTION].count_documents({}) == 0
        run(body())

    def test_the_record_layer_refuses_an_unscoped_request(self):
        base = dict(org_id=A, file_id="file_x", requested_by=ACTOR, reason="r")
        with pytest.raises(m.FileRecordInvalid):
            m.build_delete_request(scope=m.DELETE_SCOPE_VERSION, location_ids=("fl_1",), **base)
        with pytest.raises(m.FileRecordInvalid):
            m.build_delete_request(scope=m.DELETE_SCOPE_FILE, location_ids=("fl_1",),
                                   version_no=1, **base)
        with pytest.raises(m.FileRecordInvalid):
            m.build_delete_request(scope=m.DELETE_SCOPE_FILE, location_ids=(), **base)
        with pytest.raises(m.FileRecordInvalid):
            m.build_delete_request(scope="everything", location_ids=("fl_1",), **base)


# ═══════════════════════════════ finding 4 — deterministic duplicate checksum
def _frozen_clock_and_descending_ids(monkeypatch):
    """The worst case: one timestamp for everything, and ids whose LEXICAL
    order is the reverse of their registration order."""
    monkeypatch.setattr(m, "_now_iso", lambda: "2026-10-04T00:00:00+00:00")
    ids = iter("file_%032x" % n for n in range(10 ** 6, 0, -1))
    monkeypatch.setattr(m, "new_file_id", lambda: next(ids))


class TestDuplicateChecksumIsDeterministic:
    def test_equal_timestamps_still_name_the_first_registered_file(self, monkeypatch):
        _frozen_clock_and_descending_ids(monkeypatch)

        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            first = await _register(reg, text="same", name="first.jpg")
            second = await _register(reg, text="same", name="second.jpg",
                                     on_duplicate=ON_DUPLICATE_NEW_FILE)
            assert second["file_id"] < first["file_id"], "the trap: ids sort the other way"
            heads = await db[m.FILES_COLLECTION].find({}, {"_id": 0}).to_list(None)
            assert len({h["created_at"] for h in heads}) == 1, "the trap: one timestamp"
            for _ in range(20):
                out = await _register(reg, text="same", name="again.jpg")
                assert out["status"] == STATUS_DUPLICATE
                assert out["duplicate_of"] == first["file_id"]
                assert out["candidates"] == [first["file_id"], second["file_id"]]
        run(body())

    def test_the_answer_does_not_depend_on_storage_order(self, monkeypatch):
        _frozen_clock_and_descending_ids(monkeypatch)

        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            first = await _register(reg, text="same")
            await _register(reg, text="same", on_duplicate=ON_DUPLICATE_NEW_FILE)
            await _register(reg, text="same", on_duplicate=ON_DUPLICATE_NEW_FILE)
            # rewrite the physical order of the rows: newest first
            for coll in (m.FILES_COLLECTION, m.VERSIONS_COLLECTION):
                rows = await db[coll].find({}).to_list(None)
                await db[coll].delete_many({})
                for row in reversed(rows):
                    await db[coll].insert_one(row)
            for _ in range(5):
                out = await _register(reg, text="same")
                assert out["duplicate_of"] == first["file_id"]
        run(body())

    def test_registration_numbers_are_distinct_and_increasing(self):
        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            outs = await asyncio.gather(*[_register(reg, text="t%d" % i) for i in range(12)])
            heads = await db[m.FILES_COLLECTION].find({}, {"_id": 0}).to_list(None)
            seqs = sorted(h["registration_seq"] for h in heads)
            assert seqs == list(range(1, 13))
            assert len({o["file_id"] for o in outs}) == 12
            # per tenant: B starts its own count
            reg_b = FileRegistry(TenantData(db, B))
            await _register(reg_b, text="b")
            b_head = await db[m.FILES_COLLECTION].find_one({"org_id": B}, {"_id": 0})
            assert b_head["registration_seq"] == 1
        run(body())

    def test_mutation_without_the_sequence_the_choice_flips(self, monkeypatch):
        """UNSAFE MUTATION: drop the registration sequence (the pre-fix order).

        Under the frozen clock and descending ids, the old ``(created_at, id)``
        order names the SECOND file — the reviewed flake, made certain.
        """
        _frozen_clock_and_descending_ids(monkeypatch)

        async def no_seq(self):
            return None
        monkeypatch.setattr(FileRegistry, "_next_registration_seq", no_seq)

        async def body():
            db = await _db()
            reg = FileRegistry(TenantData(db, A))
            first = await _register(reg, text="same")
            second = await _register(reg, text="same", on_duplicate=ON_DUPLICATE_NEW_FILE)
            out = await _register(reg, text="same")
            assert out["duplicate_of"] == second["file_id"] != first["file_id"]
        run(body())

    def test_the_order_key_is_total_and_led_by_the_sequence(self):
        rows = [{"id": "file_b", "registration_seq": 2, "created_at": "t"},
                {"id": "file_c", "registration_seq": 1, "created_at": "t"},
                {"id": "file_a", "created_at": "t"}]
        assert [r["id"] for r in sorted(rows, key=m.file_order_key)] == \
            ["file_c", "file_b", "file_a"]
        with pytest.raises(m.FileRecordInvalid):
            m.build_file(org_id=A, display_name="x", original_name="x",
                         category=m.CATEGORY_OTHER, uploaded_by=ACTOR, registration_seq=0)
