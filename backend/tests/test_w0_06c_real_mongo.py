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
from app.files.integrity import FileIntegrityService
from app.files.monitoring import (
    FINDING_OPEN,
    FINDING_RESOLVED,
    MONITOR_FINDINGS_COLLECTION,
    MONITOR_RUNS_COLLECTION,
    MONITOR_STATE_COLLECTION,
    FileIntegrityMonitor,
    MongoTransactionRunner,
    MonitorLeaseLost,
    MonitorNotReady,
    MonitorTransactionUnavailable,
    READINESS_FAILED,
    READINESS_READY,
    SCHEDULER_DISABLED,
    SCHEDULER_ENABLED,
    TOPOLOGY_REPLICA_SET,
    TOPOLOGY_STANDALONE,
    BLOCKER_MISSING_INDEX,
    BLOCKER_NO_TRANSACTIONS,
    ensure_monitor_indexes,
    monitor_readiness,
    prepare_monitor_runtime,
    _Lease,
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
                       bucket="tenant-bucket", checksum_support=True):
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
    # ``checksum_support=False`` makes the adapter READ the bytes instead of
    # trusting a provider-reported digest — the only evidence that closes a
    # permission finding.
    backend, binding, creds = fb.build(m.PROVIDER_S3_COMPATIBLE, org_id=org, bucket=bucket,
                                       checksum_support=checksum_support)
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
    # the monitor's own indexes, including the unique finding identity: the
    # uniqueness this package relies on is the SERVER's, so the gate has to
    # create it rather than assume it.
    created = await ensure_monitor_indexes(tenant)
    assert "uniq_integrity_finding_identity" in created, created
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


def monitor(w, *, policy=None, worker_id=None, integrity=None):
    return FileIntegrityMonitor(w["reg"], w["svc"], integrity=integrity,
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


# ══════════════════════════════════════ C02 — stale-worker side effects, for real
class _TakeoverDuringCheck:
    """An integrity service that lets another worker take the tenant MID-CALL.

    The takeover below is a REAL atomic claim on the real server, executed
    while the first worker is still inside its provider call. That is the
    interleaving the C01 review found: everything the monitor does with the
    result happens after this returns, so the server state the guard reads must
    already belong to the new owner.
    """

    def __init__(self, inner, *, on_call, calls_before=0):
        self._inner = inner
        self._on_call = on_call
        self._calls_before = calls_before
        self.calls = 0
        self.org_id = inner.org_id
        self.resolver = inner.resolver

    async def check(self, *args, **kw):
        result = await self._inner.check(*args, **kw)
        self.calls += 1
        if self.calls > self._calls_before:
            await self._on_call()
        return result


class TestStaleWorkerSideEffectsOnRealMongo:
    def test_a_takeover_during_the_provider_call_commits_nothing(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1, relations=2)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            rescuer = monitor(w, worker_id="w-2")
            taken = {}

            async def take_over():
                await db[MONITOR_STATE_COLLECTION].update_one(
                    {"holder": "w-1"},
                    {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
                taken["lease"] = await rescuer._claim()
                assert taken["lease"] is not None

            doomed = monitor(w, worker_id="w-1",
                             integrity=_TakeoverDuringCheck(
                                 FileIntegrityService(w["reg"], w["svc"]),
                                 on_call=take_over))
            with pytest.raises(MonitorLeaseLost):
                await doomed.run_once(principal())

            # nothing of the stale worker reached the server
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 0
            for action in ("file.integrity.finding.opened",
                           "file.integrity.finding.observed",
                           "file.integrity.finding.resolved",
                           "file.integrity.finding.reopened"):
                assert await db["audit_events"].count_documents({"action": action}) == 0
            runs = await db[MONITOR_RUNS_COLLECTION].find({}, {"_id": 0}).to_list(None)
            assert len(runs) == 1 and runs[0]["status"] == "running"
            assert runs[0]["counts"]["checked"] == 0
            assert runs[0]["processed_location_ids"] == []
            # the new owner holds the claim at a strictly newer fence
            state = await db[MONITOR_STATE_COLLECTION].find_one({}, {"_id": 0})
            assert state["holder"] == "w-2" and state["fence"] > 1

            # and the rightful owner finishes the work properly
            await rescuer._abandon_claim(taken["lease"])
            out = await rescuer.run_once(principal(), run_id=runs[0]["id"])
            assert out["status"] == "completed"
            assert out["counts"]["findings_opened"] == 1
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["finding_type"] == "missing_original"
            assert found["fence"] == out["fence"]
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"}) == 1
        scratch(test)

    def test_a_stale_fence_cannot_overwrite_the_new_owners_finding(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1, relations=2)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            owner = monitor(w, worker_id="w-new")
            for _ in range(3):                  # push the fence up for real
                held = await owner._claim()
                assert held is not None
                await owner._abandon_claim(held)
            out = await owner.run_once(principal())
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["fence"] == out["fence"] >= 4
            before = dict(found)

            stale = monitor(w, worker_id="w-old")
            run_row = await db[MONITOR_RUNS_COLLECTION].find_one({}, {"_id": 0})
            result = await FileIntegrityService(w["reg"], w["svc"]).check(
                principal(), file_id=w["file_ids"][0], version_no=1)
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            with pytest.raises(MonitorLeaseLost):
                await stale._observe(principal(), run_row,
                                     _Lease(holder="w-old", fence=1, expires_at=""),
                                     _Counts(), location, result, "missing_original",
                                     "critical", session=None)
            after = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert after["fence"] == before["fence"]
            assert after["occurrences"] == before["occurrences"]
            assert after["transitions"] == before["transitions"]
        scratch(test)

    def test_the_guard_does_not_block_the_rightful_owner_across_passes(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=2, relations=2)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            mon = monitor(w)
            for _ in range(4):
                out = await mon.run_once(principal())
                assert out["status"] == "completed", out
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["occurrences"] == 4 and found["state"] == FINDING_OPEN
            assert found["fence"] == out["fence"]
            assert [t["transition"] for t in found["transitions"]] == [
                "open", "observed", "observed", "observed"]
        scratch(test)


# ══════════════════════════════ C02 — fail-closed proof, persisted and reread
class TestFailClosedProofOnRealMongo:
    def test_a_permission_finding_stays_open_on_a_stat_only_provider(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1, relations=2)   # server digests
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            w["backend"].deny(location["object_key"])
            await monitor(w).run_once(principal())
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["finding_type"] == "permission_failure"
            # access is genuinely restored
            w["backend"].denied.clear()
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 0
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["state"] == FINDING_OPEN and found["resolution"] is None
            assert found["resolution_blocked_reason"] == \
                "incomplete_proof:no_authorized_read"
            # the blocked reason survives a reread, which is what an operator sees
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents(
                {"state": FINDING_RESOLVED}) == 0
        scratch(test)

    def test_a_permission_finding_closes_when_the_bytes_are_really_read(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1, relations=2,
                                   checksum_support=False)            # forces a read
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            w["backend"].deny(location["object_key"])
            await monitor(w).run_once(principal())
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["finding_type"] == "permission_failure"
            w["backend"].denied.clear()
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 1
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["state"] == FINDING_RESOLVED
            assert found["resolution"]["reason"] == "authorized_content_read_succeeded"
            assert found["resolution"]["method"] == "read_and_hash"
        scratch(test)


# ═════════════════════ C03 — the post-verification boundary, on a real server
class _TakeoverAfterVerification:
    """Wraps the REAL `_verify_lease` and takes the tenant over right after it.

    The C02 review's own counterexample. The read-only verification succeeds
    honestly against the real server, the claim then moves for real, and only a
    conditional write against the claim row can still stop the worker.
    """

    def __init__(self, monitor, *, on_verified):
        self._real = monitor._verify_lease
        self._on_verified = on_verified
        self.calls = 0

    async def __call__(self, lease, *, what):
        await self._real(lease, what=what)
        self.calls += 1
        await self._on_verified()


class TestPostVerificationTakeoverOnRealMongo:
    def test_the_reviewed_interleaving_commits_nothing(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1, relations=2)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            doomed = monitor(w, worker_id="w-A")
            rescuer = monitor(w, worker_id="w-B")
            taken = {}

            async def take_over():
                if taken:
                    return
                await db[MONITOR_STATE_COLLECTION].update_one(
                    {"holder": "w-A"},
                    {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
                taken["lease"] = await rescuer._claim()
                assert taken["lease"] is not None

            doomed._verify_lease = _TakeoverAfterVerification(doomed,
                                                              on_verified=take_over)
            with pytest.raises(MonitorLeaseLost):
                await doomed.run_once(principal())

            assert doomed._verify_lease.calls == 1      # the read DID pass
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 0
            for action in ("file.integrity.finding.opened",
                           "file.integrity.finding.observed",
                           "file.integrity.finding.resolved",
                           "file.integrity.finding.reopened"):
                assert await db["audit_events"].count_documents({"action": action}) == 0
            runs = await db[MONITOR_RUNS_COLLECTION].find({}, {"_id": 0}).to_list(None)
            assert len(runs) == 1 and runs[0]["counts"]["checked"] == 0
            assert runs[0]["processed_location_ids"] == []
            state = await db[MONITOR_STATE_COLLECTION].find_one({}, {"_id": 0})
            assert state["holder"] == "w-B" and state["fence"] > 1

            # the rightful owner still completes the same run
            await rescuer._abandon_claim(taken["lease"])
            out = await rescuer.run_once(principal(), run_id=runs[0]["id"])
            assert out["status"] == "completed"
            assert out["counts"]["findings_opened"] == 1
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["fence"] == out["fence"]
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"}) == 1
        scratch(test)

    def test_an_expired_claim_is_refused_by_the_claim_gate(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=1)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            mon = monitor(w, worker_id="w-1")
            lease = await mon._claim()
            row = await mon._open_run(principal(), lease, run_id=None)
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            result = await FileIntegrityService(w["reg"], w["svc"]).check(
                principal(), file_id=w["file_ids"][0], version_no=1)
            # live claim: the gate lands and RENEWS it on the server
            await mon._claim_gate(lease, session=None, run_id=row["id"],
                                  location=location, result=result)
            state = await db[MONITOR_STATE_COLLECTION].find_one({}, {"_id": 0})
            assert state["last_commit"]["location_id"] == location["id"]
            assert state["last_commit"]["fence"] == lease.fence
            # expired, with nobody taking over: still refused
            await db[MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-1"},
                {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            with pytest.raises(MonitorLeaseLost):
                await mon._claim_gate(lease, session=None, run_id=row["id"],
                                      location=location, result=result)
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 0
        scratch(test)


# ═══════════════ C03 — identity uniqueness under a real concurrent first insert
def _insert_identity_in_child(url, db_name, sys_name, worker_id, finding_id, barrier,
                              queue):
    """Two processes race to create the SAME finding identity on the real server."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        _install_permissions()
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
        try:
            rows = client[db_name][MONITOR_FINDINGS_COLLECTION]
            doc = {"org_id": A, "id": finding_id, "finding_type": "missing_original",
                   "state": FINDING_OPEN, "worker": worker_id, "fence": 1,
                   "file_id": "file_x", "version_no": 1}
            barrier.wait(timeout=30)
            try:
                await rows.insert_one(doc)
                return "inserted"
            except Exception as exc:                                  # noqa: BLE001
                return "refused:%s" % type(exc).__name__
        finally:
            client.close()
    try:
        queue.put((worker_id, asyncio.run(body())))
    except Exception as exc:                                          # noqa: BLE001
        queue.put((worker_id, "ERROR:%s:%s" % (type(exc).__name__, exc)))


class TestIdentityUniquenessOnRealMongo:
    def test_two_processes_creating_one_identity_leave_exactly_one_row(self):
        async def test(db, sysdb):
            await _build_world(db, sysdb, files=1)     # creates the indexes
            finding_id = "fif_" + "a" * 32
            ctx = multiprocessing.get_context("spawn")
            barrier, queue = ctx.Barrier(3), ctx.Queue()
            children = [ctx.Process(target=_insert_identity_in_child,
                                    args=(REAL_URL, db.name, sysdb.name,
                                          "ins-%d" % i, finding_id, barrier, queue))
                        for i in range(3)]
            for child in children:
                child.start()
            answers = dict(queue.get(timeout=120) for _ in children)
            for child in children:
                child.join(timeout=120)
                assert child.exitcode == 0, child.exitcode
            assert not any(str(v).startswith("ERROR") for v in answers.values()), answers
            inserted = [k for k, v in answers.items() if v == "inserted"]
            refused = [v for v in answers.values() if str(v).startswith("refused")]
            assert len(inserted) == 1, answers          # exactly one winner
            assert all("DuplicateKeyError" in r for r in refused), refused
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents(
                {"id": finding_id}) == 1
        scratch(test)

    def test_the_unique_index_exists_on_the_server(self):
        async def test(db, sysdb):
            await _build_world(db, sysdb, files=1)
            names = await db[MONITOR_FINDINGS_COLLECTION].index_information()
            assert "uniq_integrity_finding_identity" in names, sorted(names)
            spec = names["uniq_integrity_finding_identity"]
            assert spec.get("unique") is True
            assert spec["key"] == [("org_id", 1), ("id", 1)]
        scratch(test)

    def test_a_monitor_pass_still_writes_one_finding_per_identity(self):
        async def test(db, sysdb):
            w = await _build_world(db, sysdb, files=2, relations=2)
            for file_id in w["file_ids"]:
                key = (await w["reg"].primary_location(file_id, 1))["object_key"]
                w["backend"].remove(key)
            for _ in range(3):
                await monitor(w).run_once(principal())
            rows = await db[MONITOR_FINDINGS_COLLECTION].find({}, {"_id": 0}).to_list(None)
            assert len(rows) == 2
            assert len({r["id"] for r in rows}) == 2
            assert {r["occurrences"] for r in rows} == {3}
        scratch(test)


# ═══════════════════ C04 — the per-item transaction on a real replica set
#
# This is where the owner architecture decision is actually PROVEN. Everything
# below needs a transaction-capable deployment: a single-node replica set is
# enough and is what the harness starts (fresh dbpath, bound to 127.0.0.1
# only). On a standalone server these tests do not quietly pass — the readiness
# gate refuses the runner, which `TestStandaloneIsRefused` asserts directly.

TXN_ERROR_LABEL = "TransientTransactionError"


async def _topology(db):
    return await MongoTransactionRunner(db).capability()


def _requires_transactions(capability):
    if not capability.get("transactions"):
        pytest.fail(
            "W0-06C/C04 needs a transaction-capable deployment: this URL is a %s. "
            "Start a disposable single-node replica set on 127.0.0.1 and point "
            "W0_06C_REAL_MONGO_URL at it." % capability.get("topology"))


class _GateObserver:
    """Wraps the REAL `_claim_gate` and runs a hook once, INSIDE the transaction.

    The hook fires after the gate's conditional claim write and before any
    finding, transition, AuditEvent or checkpoint write — the exact instant the
    C03 review's counterexample exploited.
    """

    def __init__(self, monitor, *, after_gate):
        self._real = monitor._claim_gate
        self._after = after_gate
        self.calls = 0

    async def __call__(self, lease, *, session, run_id, location, result):
        await self._real(lease, session=session, run_id=run_id, location=location,
                         result=result)
        self.calls += 1
        if self.calls == 1:
            await self._after(session)


def _bound(collection, *, millis=1500):
    """Make one collection's claim write give up instead of waiting for a lock.

    A non-transactional write against a document an open transaction has
    written BLOCKS on the server. That is itself the guarantee being proven, so
    the losing worker is given a server-side time limit: the server kills the
    attempt and it therefore leaves nothing behind, instead of landing later
    and making the assertion racy.
    """
    real = collection.find_one_and_update

    async def bounded(flt, update, **kw):
        kw.setdefault("maxTimeMS", millis)
        return await real(flt, update, **kw)
    collection.find_one_and_update = bounded
    return collection


class TestPerItemTransactionOnRealMongo:
    """Only one valid owner commits; the loser leaves ZERO side effects."""

    @staticmethod
    async def _zero(db, *, runs_checked=0):
        """Nothing a stale worker could have written is there."""
        assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 0
        assert await db["audit_events"].count_documents(
            {"action": {"$regex": "^file\\.integrity\\.finding"}}) == 0
        runs = await db[MONITOR_RUNS_COLLECTION].find({}, {"_id": 0}).to_list(None)
        for row in runs:
            assert row["counts"]["checked"] == runs_checked, row["counts"]
            assert row["processed_location_ids"] == []
            assert row["cursor"]["last_id"] is None

    def test_two_concurrent_per_item_transactions_let_exactly_one_commit(self):
        """A checks the provider, then commits, while B holds a newer claim.

        Both workers reach the per-item transaction with the SAME item: A with
        the fence it started on, B with the fence its takeover minted. They run
        at the same time, each in its own real transaction, so the server has to
        serialise the one document they both write first — the claim row. The
        invariant is the owner decision's, verbatim: only one valid owner
        commits, and the losing worker leaves ZERO finding, transition,
        AuditEvent, checkpoint and run-item result behind.
        """
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=1, relations=2)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            stale = monitor(w, worker_id="w-A")
            current = monitor(w, worker_id="w-B")

            # A claims and opens the run; the provider check happens here, i.e.
            # OUTSIDE both transactions, exactly as the decision requires.
            a_lease = await stale._claim()
            run_row = await stale._open_run(principal(), a_lease, run_id=None)
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            result = await FileIntegrityService(w["reg"], w["svc"]).check(
                principal(), file_id=w["file_ids"][0], version_no=1)

            # B legitimately takes the tenant over: a strictly higher fence.
            await db[MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-A"},
                {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            b_lease = await current._claim()
            assert b_lease is not None and b_lease.fence > a_lease.fence
            b_run = await current._open_run(principal(), b_lease, run_id=run_row["id"])

            # and now BOTH commit the same item, at the same time.
            outcomes = await asyncio.gather(
                stale._persist_item(principal(), run_row, a_lease, _Counts(),
                                    _Cursor(), location, result),
                current._persist_item(principal(), b_run, b_lease, _Counts(),
                                      _Cursor(), location, result),
                return_exceptions=True)
            losers = [o for o in outcomes if isinstance(o, BaseException)]
            winners = [o for o in outcomes if not isinstance(o, BaseException)]
            assert len(winners) == 1, outcomes
            assert len(losers) == 1 and isinstance(losers[0], MonitorLeaseLost), losers
            # exactly ONE of everything the item produces
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 1
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["occurrences"] == 1 and len(found["transitions"]) == 1
            assert found["fence"] == b_lease.fence          # the VALID owner's
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"}) == 1
            assert await db["audit_events"].count_documents(
                {"action": {"$regex": "^file\\.integrity\\.finding"}}) == 1
            row = await db[MONITOR_RUNS_COLLECTION].find_one({"id": run_row["id"]},
                                                             {"_id": 0})
            assert row["counts"]["checked"] == 1            # counted once
            assert row["processed_location_ids"] == [location["id"]]
            assert row["fence"] == b_lease.fence
            state = await db[MONITOR_STATE_COLLECTION].find_one({}, {"_id": 0})
            assert state["last_commit"]["fence"] == b_lease.fence
        scratch(test)

    def test_a_stale_worker_racing_a_newer_owner_never_lands_a_partial_item(self):
        """The same race on four different originals, asserting the invariant."""
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=4, relations=2)
            for index, file_id in enumerate(w["file_ids"]):
                key = (await w["reg"].primary_location(file_id, 1))["object_key"]
                w["backend"].remove(key)
                stale = monitor(w, worker_id="w-A%d" % index)
                current = monitor(w, worker_id="w-B%d" % index)
                a_lease = await stale._claim()
                assert a_lease is not None
                run_row = await stale._open_run(principal(), a_lease,
                                                run_id=None)
                location = await w["reg"].primary_location(file_id, 1)
                result = await FileIntegrityService(w["reg"], w["svc"]).check(
                    principal(), file_id=file_id, version_no=1)
                await db[MONITOR_STATE_COLLECTION].update_one(
                    {"holder": a_lease.holder},
                    {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
                b_lease = await current._claim()
                assert b_lease is not None and b_lease.fence > a_lease.fence
                b_run = await current._open_run(principal(), b_lease,
                                                run_id=run_row["id"])
                results = await asyncio.gather(
                    stale._persist_item(principal(), run_row, a_lease, _Counts(),
                                        _Cursor(), location, result),
                    current._persist_item(principal(), b_run, b_lease, _Counts(),
                                          _Cursor(), location, result),
                    return_exceptions=True)
                assert sum(1 for r in results
                           if isinstance(r, MonitorLeaseLost)) == 1, results
                assert sum(1 for r in results
                           if not isinstance(r, BaseException)) == 1, results
                rows = await db[MONITOR_FINDINGS_COLLECTION].find(
                    {"file_id": file_id}, {"_id": 0}).to_list(None)
                assert len(rows) == 1 and len(rows[0]["transitions"]) == 1
                assert rows[0]["occurrences"] == 1
                assert rows[0]["fence"] == b_lease.fence
                assert await db["audit_events"].count_documents(
                    {"action": {"$regex": "^file\\.integrity\\.finding"},
                     "related_file_ids": file_id}) == 1
                await current._abandon_claim(b_lease)
            # four races, four findings, no duplicate and no partial item
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 4
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"}) == 4
        scratch(test)

    def test_a_higher_fence_taken_before_the_transaction_aborts_it_with_zero_writes(self):
        """The owner decision's 0-match case, end to end on a real server."""
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=1, relations=2)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            doomed = monitor(w, worker_id="w-A")
            rescuer = monitor(w, worker_id="w-B")
            taken = {}

            async def take_over():
                if taken:
                    return
                await db[MONITOR_STATE_COLLECTION].update_one(
                    {"holder": "w-A"},
                    {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
                taken["lease"] = await rescuer._claim()
                assert taken["lease"] is not None
                assert taken["lease"].fence > 1

            # B wins the claim after A's read-only verification and BEFORE A's
            # transaction opens, which is the interleaving C03 could not close.
            doomed._verify_lease = _TakeoverAfterVerification(doomed,
                                                              on_verified=take_over)
            with pytest.raises(MonitorLeaseLost):
                await doomed.run_once(principal())
            await self._zero(db)
            state = await db[MONITOR_STATE_COLLECTION].find_one({}, {"_id": 0})
            assert state["holder"] == "w-B"
            assert "last_commit" not in state       # A's gate matched NOTHING
            # the rightful owner finishes the same run afterwards
            await rescuer._abandon_claim(taken["lease"])
            out = await rescuer.run_once(principal())
            assert out["counts"]["findings_opened"] == 1
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 1
        scratch(test)

    def test_a_lost_claim_inside_the_transaction_rolls_back_every_write(self):
        """The decisive atomicity test: the gate passes, then the claim moves.

        The finding, its transition and its AuditEvent are written INSIDE the
        transaction and the claim is then invalidated before the commit, so the
        commit must take the whole set with it — or nothing. C03's
        counterexample left 1 finding / 1 transition / 1 AuditEvent here; the
        required answer is 0 / 0 / 0.
        """
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=1, relations=2)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            doomed = monitor(w, worker_id="w-A")
            real_apply = doomed._apply_result
            seen = {}

            async def apply_then_lose(principal_, run, lease, counts, location, result,
                                      *, session):
                # the finding, the transition and the AuditEvent are written
                await real_apply(principal_, run, lease, counts, location, result,
                                 session=session)
                seen["inside"] = await db[MONITOR_FINDINGS_COLLECTION].count_documents(
                    {}, session=session)
                # ...and only now does this worker lose the tenant for good
                raise MonitorLeaseLost("the claim moved while the item was being written")
            doomed._apply_result = apply_then_lose

            with pytest.raises(MonitorLeaseLost):
                await doomed.run_once(principal())
            # inside the transaction the finding existed; after the abort it does not
            assert seen["inside"] == 1
            await self._zero(db)
            # the check itself happened and is audited — that is the truth
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.checked", "actor_id": SERVICE_A}) == 1
        scratch(test)

    def test_a_write_conflict_is_replayed_and_commits_exactly_once(self):
        """A write conflict on the claim row replays the body, not the result."""
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=1)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            mon = monitor(w, worker_id="w-1")
            runner = mon._transactions
            bodies = {"n": 0}
            real_gate = mon._claim_gate

            async def conflicting_gate(lease, *, session, run_id, location, result):
                bodies["n"] += 1
                await real_gate(lease, session=session, run_id=run_id,
                                location=location, result=result)
                if bodies["n"] == 1:
                    # the server's own answer to two transactions on one
                    # document (measured in
                    # `test_two_concurrent_per_item_transactions_...`): the
                    # loser is told to retry. The runner must replay the body
                    # against a fresh snapshot and still commit exactly once.
                    from pymongo.errors import OperationFailure
                    raise OperationFailure("injected write conflict", code=112)
            mon._claim_gate = conflicting_gate
            out = await mon.run_once(principal())
            assert bodies["n"] == 2                 # replayed exactly once
            assert runner.retries >= 1
            assert out["counts"]["checked"] == 1    # and counted exactly once
            assert out["counts"]["findings_opened"] == 1
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 1
            found = await db[MONITOR_FINDINGS_COLLECTION].find_one({}, {"_id": 0})
            assert found["occurrences"] == 1 and len(found["transitions"]) == 1
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"}) == 1
            row = await db[MONITOR_RUNS_COLLECTION].find_one({}, {"_id": 0})
            assert row["counts"]["checked"] == 1
        scratch(test)

    def test_a_crash_mid_item_leaves_nothing_and_the_retry_completes_it(self):
        """A process that dies inside the transaction commits nothing."""
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=2)
            for file_id in w["file_ids"]:
                key = (await w["reg"].primary_location(file_id, 1))["object_key"]
                w["backend"].remove(key)
            crashing = monitor(w, worker_id="w-crash")
            real_apply = crashing._apply_result

            async def crash(principal_, run, lease, counts, location, result, *, session):
                await real_apply(principal_, run, lease, counts, location, result,
                                 session=session)
                raise KeyboardInterrupt("the process dies here")
            crashing._apply_result = crash
            with pytest.raises(KeyboardInterrupt):
                await crashing.run_once(principal())
            await self._zero(db)
            # the claim is still held by the dead worker until it expires
            state = await db[MONITOR_STATE_COLLECTION].find_one({}, {"_id": 0})
            assert state["holder"] == "w-crash"
            await db[MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-crash"},
                {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            # the rescuer takes the run over and finishes it without a gap
            rescuer = monitor(w, worker_id="w-rescue",
                              policy=MonitorPolicy(max_attempts=1, batch_size=5,
                                                   max_items_per_run=10,
                                                   max_scanned_per_run=10))
            out = await rescuer.run_once(principal())
            assert out["status"] == "completed" and out["counts"]["checked"] == 2
            assert out["counts"]["findings_opened"] == 2
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 2
            assert await db["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"}) == 2
        scratch(test)

    def test_the_whole_item_is_one_transaction_and_the_provider_call_is_outside_it(self):
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=1)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            mon = monitor(w)
            real = FileIntegrityService(w["reg"], w["svc"])
            state = {"in_transaction": False, "checks_inside": 0}
            real_gate = mon._claim_gate

            async def gate(lease, *, session, run_id, location, result):
                state["in_transaction"] = session.in_transaction
                await real_gate(lease, session=session, run_id=run_id,
                                location=location, result=result)

            class _Watched:
                org_id = real.org_id
                resolver = real.resolver

                async def check(self, *a, **kw):
                    if state["in_transaction"]:
                        state["checks_inside"] += 1
                    return await real.check(*a, **kw)
            mon = monitor(w, integrity=_Watched())
            real_gate = mon._claim_gate
            mon._claim_gate = gate
            out = await mon.run_once(principal())
            assert out["counts"]["checked"] == 1
            assert state["in_transaction"] is True     # the gate IS in a transaction
            assert state["checks_inside"] == 0         # the provider call is not
        scratch(test)


class TestReadinessOnRealMongo:
    def test_a_replica_set_is_ready_and_reports_its_topology(self):
        async def test(db, sysdb):
            capability = await _topology(db)
            _requires_transactions(capability)
            assert capability["topology"] == TOPOLOGY_REPLICA_SET
            assert capability["replica_set"]
            await _build_world(db, sysdb, files=0)
            report = await monitor_readiness(db)
            assert report["status"] == READINESS_READY
            assert report["scheduler"] == SCHEDULER_ENABLED
            assert report["blockers"] == []
            assert report["claims"]["broken_fence_rows"] == 0
        scratch(test)

    def test_the_bootstrap_builds_the_required_indexes_on_the_server(self):
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            before = await monitor_readiness(db)
            assert before["status"] == READINESS_FAILED
            assert BLOCKER_MISSING_INDEX in [b["blocker"] for b in before["blockers"]]
            report = await prepare_monitor_runtime(db)
            assert report["status"] == READINESS_READY
            assert "uniq_integrity_finding_identity" in report["indexes_created"]
            info = await db[MONITOR_FINDINGS_COLLECTION].index_information()
            assert info["uniq_integrity_finding_identity"]["unique"] is True
            # and it is idempotent against the real server
            again = await prepare_monitor_runtime(db)
            assert again["status"] == READINESS_READY
        scratch(test)

    def test_the_runner_refuses_without_the_unique_index_on_a_real_server(self):
        async def test(db, sysdb):
            _requires_transactions(await _topology(db))
            w = await _build_world(db, sysdb, files=1)
            key = (await w["reg"].primary_location(w["file_ids"][0], 1))["object_key"]
            w["backend"].remove(key)
            await db[MONITOR_FINDINGS_COLLECTION].drop_index(
                "uniq_integrity_finding_identity")
            with pytest.raises(MonitorNotReady):
                await monitor(w).run_once(principal())
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 0
            assert await db[MONITOR_RUNS_COLLECTION].count_documents({}) == 0
            assert await db[MONITOR_STATE_COLLECTION].count_documents({}) == 0
        scratch(test)


# ════════════════ C04 — the NEGATIVE deployment gate: a standalone server
#
# The owner decision says a standalone deployment must report scheduler
# readiness FAILED/DISABLED, with no unsafe fallback and no activation. That
# cannot be shown on the replica set the tests above need, so it has its own
# URL and its own disposable server:
#
#     W0_06C_STANDALONE_MONGO_URL=mongodb://127.0.0.1:27996 \
#         pytest tests/test_w0_06c_real_mongo.py -k Standalone --noconftest
#
# Skipped — and reported as SKIPPED, never as passed — when that URL is absent.

STANDALONE_URL = os.environ.get("W0_06C_STANDALONE_MONGO_URL", "")


def _standalone_refusal():
    if not STANDALONE_URL:
        return ("W0_06C_STANDALONE_MONGO_URL is not set — no disposable local "
                "standalone MongoDB given")
    try:
        from app.master_data import index_bootstrap as ib
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        scheme, hosts = parse_mongo_url(STANDALONE_URL)
        ib.check_local(hosts=hosts, scheme=scheme)
    except Exception as exc:                                          # noqa: BLE001
        return "W0_06C_STANDALONE_MONGO_URL refused: %s" % exc
    return ""


def standalone_scratch(test):
    """Run ``test(db)`` in a fresh database on the STANDALONE server; drop it."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        name = DB_PREFIX + "sa_" + uuid.uuid4().hex[:10]
        client = AsyncIOMotorClient(STANDALONE_URL, serverSelectionTimeoutMS=5000)
        try:
            return await test(client[name])
        finally:
            await client.drop_database(name)
            client.close()
    _install_permissions()
    return asyncio.run(body())


@pytest.mark.skipif(bool(_standalone_refusal()), reason=_standalone_refusal() or "ok")
class TestStandaloneIsRefused:
    """A deployment without transactions is not "degraded"; it is refused."""

    def test_a_standalone_server_reports_no_transaction_capability(self):
        async def test(db):
            capability = await MongoTransactionRunner(db).capability()
            assert capability["topology"] == TOPOLOGY_STANDALONE
            assert capability["transactions"] is False
            assert capability["replica_set"] is None
            assert capability["error"] is None            # it answered, it just cannot
        standalone_scratch(test)

    def test_readiness_is_failed_and_the_scheduler_is_disabled(self):
        async def test(db):
            report = await prepare_monitor_runtime(db)
            assert report["status"] == READINESS_FAILED
            assert report["ready"] is False
            assert report["scheduler"] == SCHEDULER_DISABLED
            assert BLOCKER_NO_TRANSACTIONS in [b["blocker"] for b in report["blockers"]]
            # the indexes are still built — that part is always safe — so the
            # ONLY thing standing between this server and the monitor is the
            # topology, and it is reported, not worked around.
            assert "uniq_integrity_finding_identity" in report["indexes_created"]
        standalone_scratch(test)

    def test_the_transaction_runner_refuses_instead_of_falling_back(self):
        async def test(db):
            runner = MongoTransactionRunner(db)
            touched = []

            async def work(_session):                   # pragma: no cover - never runs
                touched.append(1)
                await db["should_not_exist"].insert_one({"_id": 1})
            with pytest.raises(MonitorTransactionUnavailable):
                await runner.run(work, what="write a finding")
            assert touched == []
            assert await db["should_not_exist"].count_documents({}) == 0
        standalone_scratch(test)

    def test_a_real_transaction_really_is_rejected_by_this_server(self):
        """Not an assumption about MongoDB: the server itself says no."""
        async def test(db):
            from motor.motor_asyncio import AsyncIOMotorClient  # noqa: F401
            async with await db.client.start_session() as session:
                session.start_transaction()
                with pytest.raises(Exception) as refused:
                    await db["probe"].insert_one({"_id": 1}, session=session)
                    await session.commit_transaction()
            text = str(refused.value).lower()
            assert "replica set member or mongos" in text or "transaction" in text
            from app.files.monitoring import transactions_unsupported
            assert transactions_unsupported(refused.value) is True
        standalone_scratch(test)

    def test_the_monitor_refuses_to_run_on_a_standalone_deployment(self):
        """End to end: no claim, no run, no provider contact, no finding."""
        async def test(db):
            from app.files.credentials import CredentialVault
            from app.files.storage import StorageProviderService
            tenant = TenantData(db, A)
            svc = StorageProviderService(
                tenant, db, vault=CredentialVault(tenant, master_key=b"0" * 32))
            mon = FileIntegrityMonitor(FileRegistry(tenant), svc,
                                       policy=MonitorPolicy(max_attempts=1))
            with pytest.raises(MonitorNotReady) as refused:
                await mon.run_once(principal())
            assert BLOCKER_NO_TRANSACTIONS in str(refused.value)
            assert await db[MONITOR_STATE_COLLECTION].count_documents({}) == 0
            assert await db[MONITOR_RUNS_COLLECTION].count_documents({}) == 0
            assert await db[MONITOR_FINDINGS_COLLECTION].count_documents({}) == 0
        standalone_scratch(test)
