"""
W0-06C — the real-MongoDB gate: concurrency, idempotency and persistence.

The fake in ``test_w0_06c_integrity_monitoring.py`` resolves its awaits without
yielding, so two gathered workers there never actually sit inside the claim at
the same moment. The W0-06C contract therefore requires the duplicate-run and
crash/restart behaviour to be proven on a REAL server, where:

* ``find_one_and_update`` really is one atomic server operation, so two workers
  racing it get one winner and one loser;
* the ``_id`` index really rejects the loser of a first-ever race;
* a ``$inc`` fence token really is monotonic, so a stale worker's fenced write
  really matches nothing;
* the run document, its cursor and its checkpoint really survive the process.

Each worker runs in its OWN process (``multiprocessing``, ``spawn``), with its
own motor client and event loop, against the same database — the real thing the
lease exists for, not two coroutines in one interpreter.

Skipped unless ``W0_06C_REAL_MONGO_URL`` (or ``W0_06B_REAL_MONGO_URL`` /
``W0_06A_REAL_MONGO_URL`` / ``W0_03_REAL_MONGO_URL``) names a plain LOCAL
server::

    W0_06C_REAL_MONGO_URL=mongodb://127.0.0.1:27017 \\
        pytest tests/test_w0_06c_real_mongo.py -v --noconftest

The URL must pass the same local-only guard the W0-03C bootstrap uses (no
Atlas, no NAS, no ``mongodb+srv``). Each test works in its OWN database
``w006c_realmongo_<random>`` plus ``w006c_realsys_<random>`` and drops exactly
those afterwards. Nothing reads ``.env`` or a production value; every provider
is a disposable in-process fake and no customer original is touched.

Required skips: 0. Every test runs when the URL is given.
"""
import asyncio
import hashlib
import multiprocessing
import os
import uuid

import pytest

from app.files import models as m
from app.files.monitoring import (
    FINDING_OPEN,
    FINDING_RESOLVED,
    MONITOR_FINDINGS_COLLECTION,
    MONITOR_RUNS_COLLECTION,
    MONITOR_STATE_COLLECTION,
    FileIntegrityMonitor,
    MonitorLeaseLost,
    MonitorPolicy,
    _Counts,
    _Cursor,
    service_principal,
)
from app.files.registry import FileRegistry
from app.tenancy.data_access import TenantData

REAL_URL = (os.environ.get("W0_06C_REAL_MONGO_URL")
            or os.environ.get("W0_06B_REAL_MONGO_URL")
            or os.environ.get("W0_06A_REAL_MONGO_URL")
            or os.environ.get("W0_03_REAL_MONGO_URL", ""))
DB_PREFIX = "w006c_realmongo_"
SYS_PREFIX = "w006c_realsys_"

A, B = "BEG", "TCB"
SERVICE_A, SERVICE_B, OWNER_A, OWNER_B = "svc-a", "svc-b", "owner-a", "owner-b"
MONITOR_ACTIONS = ["file.integrity.monitor", "file.integrity.monitor.read",
                   "file.integrity.check"]


def _refusal():
    if not REAL_URL:
        return "W0_06C_REAL_MONGO_URL is not set — no disposable local MongoDB given"
    try:
        from app.master_data import index_bootstrap as ib
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        scheme, hosts = parse_mongo_url(REAL_URL)
        ib.check_local(hosts=hosts, scheme=scheme)
    except Exception as exc:                                  # noqa: BLE001
        return "W0_06C_REAL_MONGO_URL refused: %s" % exc
    try:
        import motor.motor_asyncio  # noqa: F401
    except ImportError:
        return "motor is not installed"
    return ""


pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


# ─────────────────────────────────────────────────────── permissions + world
def _install_permissions():
    """The REAL W0-02 Permission Service, with an in-memory assignment table.

    Called in every process, including the spawned worker processes: the
    service principals are ordinary FLOW-002 principals there too.
    """
    from app.permissions import service
    table = {
        (SERVICE_A, A): [{"id": "ra-svc-a", "status": "active", "role_id": "custom",
                          "permissions": list(MONITOR_ACTIONS), "scope_type": "company"}],
        (SERVICE_B, B): [{"id": "ra-svc-b", "status": "active", "role_id": "custom",
                          "permissions": list(MONITOR_ACTIONS), "scope_type": "company"}],
        (OWNER_A, A): [{"id": "ra-oa", "status": "active", "role_id": "owner",
                        "scope_type": "company"}],
        (OWNER_B, B): [{"id": "ra-ob", "status": "active", "role_id": "owner",
                        "scope_type": "company"}],
    }

    async def load(user_id, tenant_id):
        return [dict(a) for a in table.get((user_id, tenant_id), [])]
    service._load_assignments = load


def _ctx(user, tenant):
    from types import SimpleNamespace
    return SimpleNamespace(user_id=user, tenant_id=tenant)


def _digest(data: bytes) -> dict:
    return {"algorithm": m.CHECKSUM_SHA256, "value": hashlib.sha256(data).hexdigest()}


async def _build_world(db, sysdb, *, org=A, owner=OWNER_A, files=1, relations=2,
                       bucket="tenant-bucket"):
    """An activated tenant with ``files`` uploaded originals, on a real database."""
    from app.files.access import FileAccessService
    from app.files.credentials import CredentialVault
    from app.files.storage import RESPONSIBILITY_VERSION, StorageProviderService
    from tests import w0_06b_fake_backends as fb

    tenant = TenantData(db, org)
    backends = {}

    def transport_for(row):
        backend = backends.get(row["id"]) or backends.get(row["provider_kind"])
        return backend.transport if backend is not None else None

    svc = StorageProviderService(tenant, sysdb,
                                 vault=CredentialVault(tenant, master_key=b"0" * 32),
                                 transport_for=transport_for)
    backend, binding, creds = fb.build(m.PROVIDER_S3_COMPATIBLE, org_id=org, bucket=bucket)
    out = await svc.configure_binding(
        _ctx(owner, org), role=m.LOCATION_ROLE_PRIMARY,
        provider_kind=m.PROVIDER_S3_COMPATIBLE, container=binding.container,
        root_prefix=binding.root_prefix, endpoint=binding.endpoint,
        account=binding.account, credentials=creds)
    binding_id = out["binding_id"]
    backends[binding_id] = backend
    activated = await svc.activate(
        _ctx(owner, org), binding_id=binding_id,
        responsibility={"accepted": True, "version": RESPONSIBILITY_VERSION,
                        "accepted_by": owner})
    assert activated["activated"], activated

    reg = FileRegistry(tenant)
    for index in range(max(relations, 1)):
        await db["projects"].insert_one({"id": "P-%d" % index, "org_id": org,
                                         "name": "site %d" % index})
    access = FileAccessService(reg, svc)
    file_ids = []
    for index in range(files):
        name = "doc%02d" % index
        uploaded = await access.upload(
            _ctx(owner, org), data=b"%PDF original " + name.encode(), display_name=name,
            original_name=name + ".pdf", category=m.CATEGORY_ACTS,
            mime_type="application/pdf", sensitivity=m.SENSITIVITY_STANDARD,
            relations=[{"relation_type": m.RELATION_PROJECT, "record_id": "P-%d" % r}
                       for r in range(relations)])
        assert uploaded["status"] == "registered", uploaded
        file_ids.append(uploaded["file_id"])
    return {"db": db, "sysdb": sysdb, "svc": svc, "reg": reg, "backend": backend,
            "binding_id": binding_id, "access": access, "file_ids": file_ids, "org": org}


async def _w004_indexes(db):
    """The W0-04 bootstrap indexes (scripts/w0_04_bootstrap_audit_indexes.py)."""
    await db["audit_events"].create_index([("event_id", 1)], unique=True)
    await db["audit_events"].create_index([("tenant_id", 1), ("sequence", 1)], unique=True)
    await db["audit_idempotency"].create_index("id", unique=True)


def scratch(test):
    """Run ``test(db, sysdb)`` in fresh databases on the real server; drop them after."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        name, sys_name = DB_PREFIX + uuid.uuid4().hex[:12], SYS_PREFIX + uuid.uuid4().hex[:12]
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        try:
            db, sysdb = client[name], client[sys_name]
            await _w004_indexes(db)
            for org in (A, B):
                await sysdb["tenant_registry"].insert_one(
                    {"id": org, "legacy_org_id": org, "status": "active",
                     "storage_provider": None, "storage_status": "not_configured"})
            return await test(db, sysdb)
        finally:
            await client.drop_database(name)
            await client.drop_database(sys_name)
            client.close()
    _install_permissions()
    return asyncio.run(body())


def monitor(w, *, policy=None, worker_id=None):
    return FileIntegrityMonitor(w["reg"], w["svc"],
                                policy=policy or MonitorPolicy(max_attempts=1),
                                worker_id=worker_id)


def principal(user=SERVICE_A, tenant=A):
    return service_principal(tenant_id=tenant, user_id=user)


# ══════════════════════════════════════════════ cross-PROCESS claim exclusion
def _claim_in_child(url, db_name, sys_name, worker_id, barrier, queue):
    """Claim the tenant's monitor row in a SEPARATE process, then report."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        _install_permissions()
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
        try:
            db, sysdb = client[db_name], client[sys_name]
            from app.files.credentials import CredentialVault
            from app.files.storage import StorageProviderService
            tenant = TenantData(db, A)
            svc = StorageProviderService(tenant, sysdb,
                                         vault=CredentialVault(tenant, master_key=b"0" * 32))
            mon = FileIntegrityMonitor(FileRegistry(tenant), svc,
                                       policy=MonitorPolicy(), worker_id=worker_id)
            barrier.wait(timeout=30)          # both processes claim at once
            lease = await mon._claim()
            return None if lease is None else {"holder": lease.holder, "fence": lease.fence}
        finally:
            client.close()
    try:
        queue.put((worker_id, asyncio.run(body())))
    except Exception as exc:                                      # noqa: BLE001
        queue.put((worker_id, "ERROR:%s:%s" % (type(exc).__name__, exc)))


class TestCrossProcessExclusion:
    def test_two_processes_claiming_at_once_produce_exactly_one_holder(self):
        async def test(db, sysdb):
            await _build_world(db, sysdb, files=1)
            ctx = multiprocessing.get_context("spawn")
            barrier, queue = ctx.Barrier(2), ctx.Queue()
            children = [ctx.Process(target=_claim_in_child,
                                    args=(REAL_URL, db.name, sysdb.name,
                                          "proc-%d" % index, barrier, queue))
                        for index in range(2)]
            for child in children:
                child.start()
            answers = dict(queue.get(timeout=60) for _ in children)
            for child in children:
                child.join(timeout=60)
                assert child.exitcode == 0, child.exitcode
            assert not any(isinstance(v, str) for v in answers.values()), answers
            winners = [v for v in answers.values() if v is not None]
            assert len(winners) == 1, answers      # one holder, one locked out
            assert winners[0]["fence"] == 1
            rows = await db[MONITOR_STATE_COLLECTION].find({}).to_list(None)
            assert len(rows) == 1                  # and exactly ONE control row
            assert rows[0]["holder"] == winners[0]["holder"]
            assert rows[0]["fence"] == 1
            assert rows[0]["org_id"] == A
        scratch(test)

    def test_many_sequential_claims_never_double_hold_and_the_fence_only_grows(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1)
            fences = []
            for index in range(6):
                holder = monitor(w, worker_id="w-%d" % index)
                lease = await holder._claim()
                assert lease is not None
                # while it is held, nobody else gets in
                assert await monitor(w, worker_id="other-%d" % index)._claim() is None
                fences.append(lease.fence)
                await holder._abandon_claim(lease)
            assert fences == sorted(set(fences)) and fences == [1, 2, 3, 4, 5, 6]
        scratch(test)


# ══════════════════════════════════════════════════════ cross-PROCESS runs
def _run_in_child(url, db_name, sys_name, worker_id, bucket, barrier, queue):
    """A whole ``run_once`` in a SEPARATE process, started with the others."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        _install_permissions()
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
        try:
            db, sysdb = client[db_name], client[sys_name]
            from app.files.credentials import CredentialVault
            from app.files.storage import StorageProviderService
            from tests import w0_06b_fake_backends as fb
            tenant = TenantData(db, A)
            backend, _, _ = fb.build(m.PROVIDER_S3_COMPATIBLE, org_id=A, bucket=bucket)
            # Each process re-creates the fake transport from the SAME stored
            # binding: the objects are not shared, which is harmless here —
            # the lease decides who may check at all, which is what is tested.
            svc = StorageProviderService(
                tenant, sysdb, vault=CredentialVault(tenant, master_key=b"0" * 32),
                transport_for=lambda row: backend.transport)
            mon = FileIntegrityMonitor(
                FileRegistry(tenant), svc,
                policy=MonitorPolicy(batch_size=2, max_items_per_run=20,
                                     max_scanned_per_run=40),
                worker_id=worker_id)
            barrier.wait(timeout=30)
            out = await mon.run_once(service_principal(tenant_id=A, user_id=SERVICE_A))
            return {"status": out["status"], "run_id": out["run_id"],
                    "checked": out["counts"]["checked"]}
        finally:
            client.close()
    try:
        queue.put((worker_id, asyncio.run(body())))
    except Exception as exc:                                      # noqa: BLE001
        queue.put((worker_id, "ERROR:%s:%s" % (type(exc).__name__, exc)))


class TestCrossProcessRun:
    def test_three_processes_running_at_once_leave_one_run_and_no_double_check(self):
        async def test(db, sysdb):
            # four originals for the three competing processes to find
            await _build_world(db, sysdb, files=4)
            ctx = multiprocessing.get_context("spawn")
            barrier, queue = ctx.Barrier(3), ctx.Queue()
            children = [ctx.Process(target=_run_in_child,
                                    args=(REAL_URL, db.name, sysdb.name, "run-%d" % index,
                                          "tenant-bucket", barrier, queue))
                        for index in range(3)]
            for child in children:
                child.start()
            answers = dict(queue.get(timeout=120) for _ in children)
            for child in children:
                child.join(timeout=120)
                assert child.exitcode == 0, child.exitcode
            assert not any(isinstance(v, str) for v in answers.values()), answers
            statuses = sorted(v["status"] for v in answers.values())
            assert statuses == ["completed", "skipped_locked", "skipped_locked"], answers
            # exactly one run document, and each original checked exactly once
            runs = await db[MONITOR_RUNS_COLLECTION].find({}).to_list(None)
            assert len(runs) == 1 and runs[0]["status"] == "completed"
            assert runs[0]["counts"]["checked"] == 4
            assert len(set(runs[0]["processed_location_ids"])) == 4
            checks = await db["audit_events"].find(
                {"action": "file.integrity.checked", "actor_id": SERVICE_A},
                {"_id": 0}).to_list(None)
            assert len(checks) == 4
            assert len({c["entity_id"] for c in checks}) == 4
            states = await db[MONITOR_STATE_COLLECTION].find({}).to_list(None)
            assert len(states) == 1 and states[0]["holder"] is None
            assert states[0]["runs_total"] == 1
        scratch(test)


# ═══════════════════════════════════════════════════ fencing and persistence
class TestFencingAndPersistence:
    def test_a_stale_worker_cannot_commit_after_a_takeover(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=3)
            one, two = monitor(w, worker_id="w-1"), monitor(w, worker_id="w-2")
            stale = await one._claim()
            row = await one._open_run(principal(), stale, run_id=None)
            await db[MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-1"},
                {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            fresh = await two._claim()
            assert fresh.fence > stale.fence
            await two._open_run(principal(), fresh, run_id=row["id"])
            counts, cursor = _Counts(scanned=42, checked=42), _Cursor()
            for coro in (one._renew(stale),
                         one._checkpoint(row, stale, counts, cursor, "fl_ghost"),
                         one._finish_run(row, stale, counts, cursor,
                                         status="completed", exhausted=True)):
                with pytest.raises(MonitorLeaseLost):
                    await coro
            after = await db[MONITOR_RUNS_COLLECTION].find_one({"id": row["id"]})
            assert after["fence"] == fresh.fence and after["lease_holder"] == "w-2"
            assert after["status"] == "running" and after["counts"]["checked"] == 0
            assert "fl_ghost" not in (after.get("processed_location_ids") or [])
            # the stale worker cannot publish its result either
            await one._release(stale, run_id="fir_ghost", status="completed",
                               result={"counts": {"checked": 42}}, next_due_at=None)
            state = await db[MONITOR_STATE_COLLECTION].find_one({})
            assert state["holder"] == "w-2" and state["last_run_id"] is None
        scratch(test)

    def test_a_crashed_run_is_resumed_from_its_durable_checkpoint(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=6)
            crashed = monitor(w, worker_id="w-crash",
                              policy=MonitorPolicy(batch_size=2, max_items_per_run=3,
                                                   max_scanned_per_run=50))
            lease = await crashed._claim()
            row = await crashed._open_run(principal(), lease, run_id=None)
            counts, cursor, processed = _Counts(), _Cursor(), set()
            await crashed._walk(principal(), row, lease, counts, cursor, processed)
            assert counts.checked == 3
            # the checkpoint is on the server, not in this process's memory
            stored = await db[MONITOR_RUNS_COLLECTION].find_one({"id": row["id"]})
            assert stored["status"] == "running"
            assert stored["counts"]["checked"] == 3
            assert len(stored["processed_location_ids"]) == 3
            assert stored["cursor"]["last_id"]
            # the process is gone; only the claim's expiry lets anyone continue
            await db[MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-crash"},
                {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            rescuer = monitor(w, worker_id="w-rescue",
                              policy=MonitorPolicy(batch_size=4, max_items_per_run=100,
                                                   max_scanned_per_run=100))
            out = await rescuer.run_once(principal())
            assert out["run_id"] == row["id"] and out["status"] == "completed"
            assert out["exhausted"] is True and out["counts"]["checked"] == 6
            assert await db[MONITOR_RUNS_COLLECTION].count_documents({}) == 1
            checks = await db["audit_events"].find(
                {"action": "file.integrity.checked", "actor_id": SERVICE_A},
                {"_id": 0}).to_list(None)
            assert len(checks) == 6 and len({c["entity_id"] for c in checks}) == 6
        scratch(test)

    def test_the_finding_history_survives_and_never_duplicates_an_alarm(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            full = w["backend"]._full(key)
            saved = dict(w["backend"].objects[full])
            w["backend"].remove(key)
            for _ in range(3):
                await monitor(w).run_once(principal())
            rows = await db[MONITOR_FINDINGS_COLLECTION].find({}, {"_id": 0}).to_list(None)
            assert len(rows) == 1                     # ONE open alarm after three passes
            found = rows[0]
            assert found["state"] == FINDING_OPEN and found["occurrences"] == 3
            assert found["finding_type"] == "missing_original"
            assert found["alarm_level"] == "critical" and found["affected_record_count"] == 2
            assert [t["transition"] for t in found["transitions"]] == [
                "open", "observed", "observed"]
            assert len(set(found["transition_keys"])) == 3
            opened = await db["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"})
            assert opened == 1
            # the customer restores the original; a type-specific proof closes it
            w["backend"].objects[full] = saved
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 1
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["state"] == FINDING_RESOLVED
            assert found["resolution"]["reason"] == "identified_original_present_and_compared"
            # and it reopens, in place, when it breaks again
            w["backend"].remove(key)
            await monitor(w).run_once(principal())
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 1
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["state"] == FINDING_OPEN and found["reopened_at"]
            assert [t["transition"] for t in found["transitions"]] == [
                "open", "observed", "observed", "resolved", "reopened"]
        scratch(test)

    def test_the_audit_chain_stays_intact_across_runs_on_a_real_server(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=3)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            runs = [await monitor(w).run_once(principal()) for _ in range(2)]
            rows = await db["audit_events"].find({"tenant_id": A}, {"_id": 0}).sort(
                "sequence", 1).to_list(None)
            sequences = [r["sequence"] for r in rows]
            # the W0-04 unique (tenant_id, sequence) index plus a dense chain
            assert sequences == list(range(1, len(rows) + 1))
            assert len({r["event_id"] for r in rows}) == len(rows)
            for started in runs:
                correlated = [r for r in rows if r.get("correlation_id") == started["run_id"]]
                assert correlated, started["run_id"]
                assert {r["tenant_id"] for r in correlated} == {A}
        scratch(test)


# ═══════════════════════════════════════════════════════════ tenant isolation
class TestRealIsolation:
    def test_two_tenants_claim_run_and_alarm_independently(self):
        async def test(db, sysdb):
            a = await _build_world(db, sysdb, org=A, owner=OWNER_A, files=2)
            b = await _build_world(db, sysdb, org=B, owner=OWNER_B, files=1,
                                   bucket="tenant-b-bucket")
            a["backend"].remove(
                (await a["reg"].primary_location(a["file_ids"][0], 1))["object_key"])
            b["backend"].remove(
                (await b["reg"].primary_location(b["file_ids"][0], 1))["object_key"])
            # A holds its claim; B is not blocked by it
            held = await monitor(a, worker_id="w-a")._claim()
            assert held is not None
            assert await monitor(b, worker_id="w-b")._claim() is not None
            await monitor(a, worker_id="w-a")._abandon_claim(held)

            out_a = await monitor(a).run_once(principal(SERVICE_A, A))
            assert out_a["counts"]["checked"] == 2
            for collection in (MONITOR_STATE_COLLECTION, MONITOR_RUNS_COLLECTION,
                               MONITOR_FINDINGS_COLLECTION):
                owners = {r["org_id"] for r in await db[collection].find({}).to_list(None)}
                assert owners <= {A, B} and A in owners, collection
            a_rows = await monitor(a).list_findings(principal(SERVICE_A, A))
            assert {r["org_id"] for r in a_rows} == {A}
            blob = repr(a_rows)
            assert b["file_ids"][0] not in blob and b["binding_id"] not in blob
            assert "P-B" not in blob
        scratch(test)

    def test_the_same_business_id_in_two_tenants_resolves_to_this_tenant_only(self):
        async def test(db, sysdb):
            a = await _build_world(db, sysdb, org=A, owner=OWNER_A, files=0)
            await _build_world(db, sysdb, org=B, owner=OWNER_B, files=0,
                               bucket="tenant-b-bucket")
            for org in (A, B):
                await db["projects"].insert_one({"id": "P-SHARED", "org_id": org,
                                                 "name": "name in " + org})
            uploaded = await a["access"].upload(
                _ctx(OWNER_A, A), data=b"%PDF shared", display_name="shared",
                original_name="shared.pdf", category=m.CATEGORY_ACTS,
                mime_type="application/pdf", sensitivity=m.SENSITIVITY_STANDARD,
                relations=[{"relation_type": m.RELATION_PROJECT, "record_id": "P-SHARED"}])
            file_id = uploaded["file_id"]
            a["backend"].remove(
                (await a["reg"].primary_location(file_id, 1))["object_key"])
            await monitor(a).run_once(principal(SERVICE_A, A))
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one(
                {"org_id": A, "file_id": file_id}, {"_id": 0})
            assert found["affected_record_count"] == 1
            assert [r["label"] for r in found["affected_records"]] == ["name in " + A]
            assert "name in " + B not in repr(found)
        scratch(test)


# ══════════════════════════════════════════════════════════════ sanity gates
class TestRealSanity:
    def test_the_monitor_collections_persist_their_documents_as_written(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1)
            w["backend"].remove(
                (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"])
            out = await monitor(w, policy=MonitorPolicy(recheck_after_seconds=0)
                                ).run_once(principal())
            state = await db[MONITOR_STATE_COLLECTION].find_one({}, {"_id": 0})
            assert state["last_run_id"] == out["run_id"]
            assert state["next_due_at"] == out["next_due_at"]
            assert state["last_result"]["counts"] == out["counts"]
            stored_run = await db[MONITOR_RUNS_COLLECTION].find_one(
                {"id": out["run_id"]}, {"_id": 0})
            assert stored_run["cursor"] == out["cursor"]
            assert stored_run["policy"] == out["policy"]
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["schema"] == "beg.w0-06b.file_integrity_finding/v1"
            assert found["dq_handoff"] == {"consumer": "W0-07", "state": "not_consumed",
                                           "blocking": True}
        scratch(test)

    def test_no_secret_token_or_provider_path_is_persisted_anywhere(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1)
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            w["backend"].deny(location["object_key"])
            await monitor(w).run_once(principal())
            from tests.w0_06b_fake_backends import SECRET_MARKERS
            findings = repr(await db[MONITOR_FINDINGS_COLLECTION].find(
                {}, {"_id": 0}).to_list(None))
            runs = repr(await db[MONITOR_RUNS_COLLECTION].find({}, {"_id": 0}).to_list(None))
            events = repr(await db["audit_events"].find({}, {"_id": 0}).to_list(None))
            for blob, label in ((findings, "findings"), (runs, "runs")):
                assert location["object_key"] not in blob, label
                assert location["container"] not in blob, label
                for marker in ("Signature=", "X-Amz-", "Bearer", "%PDF", "://"):
                    assert marker not in blob, "%s/%s" % (label, marker)
            for marker in SECRET_MARKERS:
                for blob, label in ((findings, "findings"), (runs, "runs"),
                                    (events, "audit")):
                    assert marker not in blob, "%s/%s" % (label, marker)
        scratch(test)
