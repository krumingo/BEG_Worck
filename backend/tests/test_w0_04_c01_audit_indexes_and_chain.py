"""
W0-04-C01 — the audit / idempotency indexes are created by the application, and
the audit chain stays linear under concurrency.

IDEMPOTENCY (IDEM-IDX-1): ``begin_idempotent`` is only "one key = one write" when
``audit_idempotency.id`` is unique; before C01 only a manual script created it.
CHAIN (FG-37): concurrent ``record_event`` forked the chain or lost events.

The database tests run against a REAL, disposable, local MongoDB replica set
(``W0_03_REAL_MONGO_URL``, the same local-only guard as test_w0_03c_real_mongo)
and drop exactly the databases they create::

    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27019/?replicaSet=rs0 \\
        PYTHONPATH=. pytest tests/test_w0_04_c01_audit_indexes_and_chain.py --noconftest
"""
import ast
import asyncio
import uuid
from pathlib import Path

import pytest

from app.audit import indexes as ix
from app.audit import store
from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
from app.audit.idempotency import (
    IDEMPOTENCY_COLLECTION, IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED, begin_idempotent)
from app.audit.store import AUDIT_COLLECTION, record_event, verify_tenant_chain

from tests.test_w0_03c_real_mongo import REAL_URL, _refusal

BACKEND = Path(__file__).resolve().parent.parent
DB_PREFIX = "w004c01_realmongo_"
real_mongo = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


def make_event(tenant="tenant-a", entity="pay-1"):
    return build_event(
        tenant_id=tenant, actor_type=ACTOR_HUMAN, actor_id="user-1", action="payment.created",
        source_flow="FLOW-006", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="payment", entity_id=entity, reason="W0-04-C01 concurrency test")


def scratch(test, n_dbs=1):
    """Run ``test(client, [db, ...])`` on fresh databases; drop them afterwards."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        names = [DB_PREFIX + uuid.uuid4().hex[:12] for _ in range(n_dbs)]
        try:
            return await test(client, [client[n] for n in names])
        finally:
            for n in names:
                assert n.startswith(DB_PREFIX)
                await client.drop_database(n)
            client.close()
    return asyncio.run(body())


async def unique_flags(db):
    out = {}
    for coll in (AUDIT_COLLECTION, IDEMPOTENCY_COLLECTION):
        for name, info in (await db[coll].index_information()).items():
            out[(coll, tuple((f, int(d)) for f, d in info["key"]))] = bool(info.get("unique"))
    return out


def assert_all_planned(flags):
    for coll, keys, opts in ix.PLANNED_INDEXES:
        k = (coll, tuple(keys))
        assert k in flags, "missing %s" % (k,)
        assert flags[k] == bool(opts.get("unique")), k


# ─────────────────────────────────────────────── pure checks (no database)

def test_script_and_app_plan_the_same_indexes():
    from scripts import w0_04_bootstrap_audit_indexes as script
    assert script.PLANNED_INDEXES is ix.PLANNED_INDEXES
    assert ix.AUDIT_COLLECTION == store.AUDIT_COLLECTION
    assert ix.IDEMPOTENCY_COLLECTION == IDEMPOTENCY_COLLECTION
    uniques = {(c, tuple(k)) for c, k, o in ix.PLANNED_INDEXES if o.get("unique")}
    assert (IDEMPOTENCY_COLLECTION, (("id", 1),)) in uniques
    assert (AUDIT_COLLECTION, (("tenant_id", 1), ("sequence", 1))) in uniques
    assert (AUDIT_COLLECTION, (("event_id", 1),)) in uniques


def test_startup_ensures_audit_indexes_before_anything_is_written():
    tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup")
    calls = [n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
             for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert "ensure_audit_indexes_for_installation" in calls
    assert calls.index("ensure_audit_indexes_for_installation") < calls.index("seed_data")


def test_classify_conflicts_are_never_skipped():
    plain = {"id_1": {"key": [("id", 1)]}}
    with pytest.raises(ix.AuditIndexConflict):
        ix._classify(plain, [("id", 1)], unique=True)
    taken = {"id_1": {"key": [("other", 1)], "unique": True}}
    with pytest.raises(ix.AuditIndexConflict):
        ix._classify(taken, [("id", 1)], unique=True)
    partial = {"x": {"key": [("id", 1)], "unique": True, "partialFilterExpression": {"a": 1}}}
    with pytest.raises(ix.AuditIndexConflict):
        ix._classify(partial, [("id", 1)], unique=True)
    other_name = {"my_id": {"key": [("id", 1)], "unique": True}}
    assert ix._classify(other_name, [("id", 1)], unique=True) == ("present", "my_id")
    assert ix._classify({}, [("id", 1)], unique=True) == ("missing", None)


class _AlwaysTaken:
    """A collection whose next sequence is always taken by somebody else."""

    def __init__(self, details):
        self.details, self.inserts = details, 0

    async def find_one(self, *a, **kw):
        return None

    async def insert_one(self, doc):
        from pymongo.errors import DuplicateKeyError
        self.inserts += 1
        raise DuplicateKeyError("E11000 duplicate key", 11000, self.details)


def test_contention_is_bounded_and_reported(monkeypatch):
    coll = _AlwaysTaken({"keyPattern": {"tenant_id": 1, "sequence": 1}})
    monkeypatch.setattr(store, "CHAIN_APPEND_MAX_ATTEMPTS", 4)
    with pytest.raises(store.AuditChainContention):
        asyncio.run(record_event({AUDIT_COLLECTION: coll}, make_event()))
    assert coll.inserts == 4


def test_duplicate_event_id_is_not_retried():
    from pymongo.errors import DuplicateKeyError
    coll = _AlwaysTaken({"keyPattern": {"event_id": 1}})
    with pytest.raises(DuplicateKeyError):
        asyncio.run(record_event({AUDIT_COLLECTION: coll}, make_event()))
    assert coll.inserts == 1


# ─────────────────────────────────────────────── real MongoDB (rs0)

@real_mongo
def test_fresh_database_gets_every_index_and_a_restart_changes_nothing():
    async def go(client, dbs):
        db = dbs[0]
        assert IDEMPOTENCY_COLLECTION not in await db.list_collection_names()
        first = await ix.ensure_audit_indexes(db)
        assert len(first["created"]) == len(ix.PLANNED_INDEXES) and not first["present"]
        assert_all_planned(await unique_flags(db))
        before = await unique_flags(db)
        second = await ix.ensure_audit_indexes(db)          # the next start
        assert second["created"] == [] and len(second["present"]) == len(ix.PLANNED_INDEXES)
        assert await unique_flags(db) == before
    scratch(go)


@real_mongo
def test_startup_covers_every_database_the_registry_names():
    async def go(client, dbs):
        op, sysdb, tenant_b = dbs
        await sysdb.tenant_registry.insert_many([
            {"id": "t-a", "database_name": op.name},
            {"id": "t-b", "database_name": tenant_b.name},
            {"id": "t-broken"}])                            # no database_name: nothing to open
        reports = await ix.ensure_audit_indexes_for_installation(op, sysdb)
        assert [r["database"] for r in reports] == [op.name, tenant_b.name]
        assert_all_planned(await unique_flags(op))
        assert_all_planned(await unique_flags(tenant_b))
        again = await ix.ensure_audit_indexes_for_installation(op, sysdb)
        assert all(r["created"] == [] for r in again)
    scratch(go, n_dbs=3)


@real_mongo
def test_onboarding_a_tenant_creates_the_indexes_in_its_database():
    from app.tenancy.onboarding import onboard_tenant

    async def go(client, dbs):
        op, sysdb = dbs
        out = await onboard_tenant(op, sysdb, org_name="W0-04-C01 Firm", owner_email="c01@example.com",
                                   owner_password_hash="h", owner_first_name="C")
        assert out["tenant"]["database_name"] == op.name
        assert_all_planned(await unique_flags(op))
    scratch(go, n_dbs=2)


@real_mongo
def test_six_parallel_begin_with_one_key_have_exactly_one_winner():
    async def go(client, dbs):
        db = dbs[0]
        await ix.ensure_audit_indexes(db)
        for round_ in range(5):
            key = "pay-%d" % round_
            states = await asyncio.gather(*[
                begin_idempotent(db, tenant_id="tenant-a", key=key, action="payment.create",
                                 request_fingerprint="fp") for _ in range(6)])
            statuses = sorted(s["status"] for s in states)
            assert statuses.count(IDEMPOTENCY_STARTED) == 1, statuses
            assert statuses.count(IDEMPOTENCY_DUPLICATE) == 5, statuses
            assert await db[IDEMPOTENCY_COLLECTION].count_documents({"key": key}) == 1
    scratch(go)


@real_mongo
@pytest.mark.parametrize("n", [20, 50])
def test_parallel_record_event_loses_nothing_and_the_chain_stays_linear(n):
    async def go(client, dbs):
        db = dbs[0]
        await ix.ensure_audit_indexes(db)
        await record_event(db, make_event(entity="pay-seed"))
        stored = await asyncio.gather(*[
            record_event(db, make_event(tenant=t, entity="pay-%s-%d" % (t, i)))
            for i in range(n) for t in ("tenant-a", "tenant-b")])
        assert len(stored) == 2 * n
        for t, expected in (("tenant-a", n + 1), ("tenant-b", n)):
            events = await db[AUDIT_COLLECTION].find({"tenant_id": t}, {"_id": 0}).sort(
                "sequence", 1).to_list(None)
            assert [e["sequence"] for e in events] == list(range(1, expected + 1))
            assert len({e["event_id"] for e in events}) == expected
            ok, reason = await verify_tenant_chain(db, t)
            assert ok is True, reason
        returned = {e["event_id"]: e["integrity_hash"] for e in stored}
        persisted = {e["event_id"]: e["integrity_hash"] async for e in db[AUDIT_COLLECTION].find({})}
        assert all(persisted[k] == v for k, v in returned.items())
    scratch(go)


@real_mongo
def test_a_conflicting_existing_index_stops_the_start_and_is_not_dropped():
    async def go(client, dbs):
        db = dbs[0]
        await db[IDEMPOTENCY_COLLECTION].create_index([("id", 1)])        # non-unique, by hand
        with pytest.raises(ix.AuditIndexConflict) as exc:
            await ix.ensure_audit_indexes(db)
        assert "id_1" in str(exc.value)
        info = await db[IDEMPOTENCY_COLLECTION].index_information()
        assert "id_1" in info and not info["id_1"].get("unique")
    scratch(go)


@real_mongo
def test_existing_duplicates_are_reported_never_deleted():
    async def go(client, dbs):
        db = dbs[0]
        await db[IDEMPOTENCY_COLLECTION].insert_many([
            {"id": "idem_t_a_k", "tenant_id": "t", "action": "a", "key": "k", "status": "completed"},
            {"id": "idem_t_a_k", "tenant_id": "t", "action": "a", "key": "k", "status": "completed"}])
        await db[AUDIT_COLLECTION].insert_many([
            {"event_id": "ae_1", "tenant_id": "t", "sequence": 1},
            {"event_id": "ae_2", "tenant_id": "t", "sequence": 1}])
        with pytest.raises(ix.AuditIndexDuplicates) as exc:
            await ix.ensure_audit_indexes(db)
        rep = exc.value.report
        assert rep["collection"] == AUDIT_COLLECTION and rep["keys"] == [("tenant_id", 1), ("sequence", 1)]
        assert rep["duplicate_key"] == {"tenant_id": "t", "sequence": 1}
        assert "w0_04_bootstrap_audit_indexes" in str(exc.value)
        assert await db[AUDIT_COLLECTION].count_documents({}) == 2
        assert await db[IDEMPOTENCY_COLLECTION].count_documents({}) == 2
        names = (await db[AUDIT_COLLECTION].index_information()).keys()
        assert "tenant_id_1_sequence_1" not in names
    scratch(go)


@real_mongo
def test_onboarding_refuses_before_writing_when_the_indexes_cannot_be_built():
    from app.tenancy.onboarding import OnboardingRefused, onboard_tenant

    async def go(client, dbs):
        op, sysdb = dbs
        await op[IDEMPOTENCY_COLLECTION].create_index([("id", 1)])        # conflicting
        with pytest.raises(OnboardingRefused) as exc:
            await onboard_tenant(op, sysdb, org_name="Refused Firm", owner_email="no@example.com",
                                 owner_password_hash="h", owner_first_name="N")
        assert exc.value.code == "AUDIT_INDEXES_UNAVAILABLE"
        assert await op.organizations.count_documents({}) == 0
        assert await op.users.count_documents({}) == 0
        assert await sysdb.tenant_registry.count_documents({}) == 0
    scratch(go, n_dbs=2)


@real_mongo
def test_the_manual_script_lists_every_duplicate_group_and_creates_nothing():
    import os
    import subprocess
    import sys

    async def go(client, dbs):
        db = dbs[0]
        await db[IDEMPOTENCY_COLLECTION].insert_many(
            [{"id": "idem_dup_%d" % (i // 2), "tenant_id": "t", "action": "a", "key": "k%d" % i}
             for i in range(4)])
        env = dict(os.environ, MONGO_URL=REAL_URL, DB_NAME=db.name, PYTHONPATH=str(BACKEND))
        for args in ([], ["--apply"]):
            out = subprocess.run([sys.executable, "scripts/w0_04_bootstrap_audit_indexes.py", *args],
                                 cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
            assert out.returncode == 3, out.stdout + out.stderr
            assert out.stdout.count("DUPLICATE audit_idempotency") == 2, out.stdout
        assert await db[IDEMPOTENCY_COLLECTION].count_documents({}) == 4
        assert list((await db[IDEMPOTENCY_COLLECTION].index_information()).keys()) == ["_id_"]
    scratch(go)


# ─────────────────────────────────────────────── FG-57: fail closed without the chain index

def test_production_handles_are_checked():
    """Every production path hands record_event a Motor database; the guard
    must apply to it (only plain in-memory doubles are exempt)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.db import db as legacy_db
    from app.tenancy import resolver
    assert store._is_mongo_handle(legacy_db)
    assert store._is_mongo_handle(resolver._get_db_by_name("w004c01_never_opened"))
    assert store._is_mongo_handle(AsyncIOMotorClient("mongodb://127.0.0.1:1")["x"])
    assert not store._is_mongo_handle({AUDIT_COLLECTION: object()})


def test_mongomock_handle_gets_the_chain_index_before_its_first_append():
    from mongomock_motor import AsyncMongoMockClient

    async def go():
        db = AsyncMongoMockClient()["w004c01_mock_%s" % uuid.uuid4().hex[:8]]
        await record_event(db, make_event())
        info = await db[AUDIT_COLLECTION].index_information()
        assert any(store._protects_chain(i) for i in info.values()), info
    asyncio.run(go())


@real_mongo
def test_fg57_no_index_parallel_appends_do_not_fork():
    """FG-57: a database that missed startup/onboarding (no indexes at all) —
    20 parallel appends still give one linear chain, every round."""
    async def go(client, dbs):
        for db in dbs:
            assert AUDIT_COLLECTION not in await db.list_collection_names()
            stored = await asyncio.gather(*[
                record_event(db, make_event(entity="pay-%d" % i)) for i in range(20)])
            assert sorted(e["sequence"] for e in stored) == list(range(1, 21))
            assert await db[AUDIT_COLLECTION].count_documents({}) == 20
            ok, reason = await verify_tenant_chain(db, "tenant-a")
            assert ok is True, reason
            info = await db[AUDIT_COLLECTION].index_information()
            assert any(store._protects_chain(i) for i in info.values())
    scratch(go, n_dbs=10)


@real_mongo
def test_fg57_conflicting_chain_index_refuses_to_append():
    async def go(client, dbs):
        db = dbs[0]
        await db[AUDIT_COLLECTION].create_index([("tenant_id", 1), ("sequence", 1)])  # non-unique
        for _ in range(2):                                   # no positive result is cached
            with pytest.raises(store.AuditChainUnprotected) as exc:
                await record_event(db, make_event())
            assert "refusing to write" in str(exc.value)
        assert await db[AUDIT_COLLECTION].count_documents({}) == 0
        info = await db[AUDIT_COLLECTION].index_information()
        assert not info["tenant_id_1_sequence_1"].get("unique")      # not dropped
    scratch(go)


@real_mongo
def test_fg57_existing_fork_refuses_to_append_and_deletes_nothing():
    async def go(client, dbs):
        db = dbs[0]
        await db[AUDIT_COLLECTION].insert_many([
            {"event_id": "ae_1", "tenant_id": "tenant-a", "sequence": 1},
            {"event_id": "ae_2", "tenant_id": "tenant-a", "sequence": 1}])
        with pytest.raises(store.AuditChainUnprotected):
            await record_event(db, make_event())
        assert await db[AUDIT_COLLECTION].count_documents({}) == 2
        assert "tenant_id_1_sequence_1" not in await db[AUDIT_COLLECTION].index_information()
    scratch(go)


# ─────────────────────────────────────────────── lazy guard for begin_idempotent

@real_mongo
def test_no_index_parallel_begin_with_one_key_have_exactly_one_winner():
    """A database that missed startup AND onboarding: 6 parallel reservations
    with one key still give exactly one winner (before: 6 of 6)."""
    async def go(client, dbs):
        for db in dbs:
            assert IDEMPOTENCY_COLLECTION not in await db.list_collection_names()
            states = await asyncio.gather(*[
                begin_idempotent(db, tenant_id="tenant-a", key="pay-1", action="payment.create",
                                 request_fingerprint="fp") for _ in range(6)])
            statuses = [s["status"] for s in states]
            assert statuses.count(IDEMPOTENCY_STARTED) == 1, statuses
            assert await db[IDEMPOTENCY_COLLECTION].count_documents({}) == 1
            assert await ix.unique_index_present(db, IDEMPOTENCY_COLLECTION, [("id", 1)])
    scratch(go, n_dbs=10)


@real_mongo
def test_begin_refuses_on_a_conflicting_idempotency_index():
    from app.audit.idempotency import IdempotencyUnprotected

    async def go(client, dbs):
        db = dbs[0]
        await db[IDEMPOTENCY_COLLECTION].create_index([("id", 1)])          # non-unique
        for _ in range(2):
            with pytest.raises(IdempotencyUnprotected) as exc:
                await begin_idempotent(db, tenant_id="t", key="k", action="a")
            assert "refusing to write" in str(exc.value)
        assert await db[IDEMPOTENCY_COLLECTION].count_documents({}) == 0
        info = await db[IDEMPOTENCY_COLLECTION].index_information()
        assert not info["id_1"].get("unique")                              # not dropped
    scratch(go)


@real_mongo
def test_begin_refuses_over_existing_duplicate_reservations_and_deletes_nothing():
    from app.audit.idempotency import IdempotencyUnprotected

    async def go(client, dbs):
        db = dbs[0]
        dup = {"id": "idem_t_a_k", "tenant_id": "t", "action": "a", "key": "k", "status": "completed"}
        await db[IDEMPOTENCY_COLLECTION].insert_many([dict(dup), dict(dup)])
        with pytest.raises(IdempotencyUnprotected):
            await begin_idempotent(db, tenant_id="t", key="other", action="a")
        assert await db[IDEMPOTENCY_COLLECTION].count_documents({}) == 2
    scratch(go)


@real_mongo
def test_check_only_mode_never_builds_an_index_and_ensure_chain_index_does():
    """The #56 merge: inside an open transaction record_event checks only
    (create=False); ensure_chain_index() is called before the transaction."""
    async def go(client, dbs):
        db = dbs[0]
        with pytest.raises(store.AuditChainUnprotected) as exc:
            await store._require_chain_index(db, create=False)
        assert "before the transaction starts" in str(exc.value)
        assert AUDIT_COLLECTION not in await db.list_collection_names()
        await store.ensure_chain_index(db)
        await store._require_chain_index(db, create=False)                 # now passes
        assert await ix.unique_index_present(db, AUDIT_COLLECTION, store.CHAIN_INDEX_KEYS)
    scratch(go)


# ─────────────────────────────────────────────── F-69-01: FAILED -> STARTED retake has one winner

@real_mongo
def test_six_concurrent_retries_of_a_failed_key_have_exactly_one_winner():
    """F-69-01: a request is interrupted (its key ends FAILED); 6 concurrent
    retries must give exactly 1 STARTED — never a second writer. Repeated over
    10 rounds."""
    from app.audit.idempotency import IDEMPOTENCY_IN_PROGRESS, fail_idempotent

    async def go(client, dbs):
        db = dbs[0]
        await ix.ensure_audit_indexes(db)
        for round_ in range(10):
            key = "pay-retry-%d" % round_
            first = await begin_idempotent(db, tenant_id="tenant-a", key=key, action="payment.create",
                                           request_fingerprint="fp")
            assert first["status"] == IDEMPOTENCY_STARTED
            await fail_idempotent(db, tenant_id="tenant-a", key=key, action="payment.create",
                                  error_code="INTERRUPTED")
            states = await asyncio.gather(*[
                begin_idempotent(db, tenant_id="tenant-a", key=key, action="payment.create",
                                 request_fingerprint="fp") for _ in range(6)])
            statuses = [s["status"] for s in states]
            assert statuses.count(IDEMPOTENCY_STARTED) == 1, statuses
            # Every other retry is told the write is running: IN_PROGRESS when it
            # read FAILED and lost the retake, or the ordinary DUPLICATE/STARTED
            # ("still running") when it read the record after the winner's update.
            losers = [s for s in states if s["status"] != IDEMPOTENCY_STARTED]
            assert all(s["status"] == IDEMPOTENCY_IN_PROGRESS
                       or (s["status"] == IDEMPOTENCY_DUPLICATE
                           and s["prior_status"] == IDEMPOTENCY_STARTED) for s in losers), statuses
            assert not any(s.get("retry_of_failed") for s in losers)
            winner = next(s for s in states if s["status"] == IDEMPOTENCY_STARTED)
            assert winner["retry_of_failed"] is True
            rec = await db[IDEMPOTENCY_COLLECTION].find_one({"key": key}, {"_id": 0})
            assert rec["status"] == IDEMPOTENCY_STARTED
            assert rec["attempt_token"] == winner["record"]["attempt_token"]
            assert await db[IDEMPOTENCY_COLLECTION].count_documents({"key": key}) == 1
    scratch(go)


@real_mongo
def test_a_retry_after_the_winner_completed_is_a_replay():
    from app.audit.idempotency import (
        IDEMPOTENCY_COMPLETED, IDEMPOTENCY_IN_PROGRESS, complete_idempotent, fail_idempotent)

    async def go(client, dbs):
        db = dbs[0]
        kw = dict(tenant_id="tenant-a", key="k", action="payment.create")
        await begin_idempotent(db, request_fingerprint="fp", **kw)
        await fail_idempotent(db, error_code="INTERRUPTED", **kw)
        won = await begin_idempotent(db, request_fingerprint="fp", **kw)
        assert won["status"] == IDEMPOTENCY_STARTED and won["retry_of_failed"]
        lost = await begin_idempotent(db, request_fingerprint="fp", **kw)
        # an ordinary STARTED duplicate (not a lost retake) keeps its W0-02 meaning
        assert lost["status"] == IDEMPOTENCY_DUPLICATE and lost["prior_status"] == IDEMPOTENCY_STARTED
        await complete_idempotent(db, result_reference="pay-1", **kw)
        replay = await begin_idempotent(db, request_fingerprint="fp", **kw)
        assert replay["status"] == IDEMPOTENCY_DUPLICATE
        assert replay["prior_status"] == IDEMPOTENCY_COMPLETED and replay["result_reference"] == "pay-1"
        assert IDEMPOTENCY_IN_PROGRESS not in (won["status"], replay["status"])
    scratch(go)


def test_recoverable_write_refuses_with_409_when_a_retry_is_in_progress(monkeypatch):
    from fastapi import HTTPException
    from app.audit.idempotency import IDEMPOTENCY_IN_PROGRESS
    from app.permissions import workflow

    async def lost_retake(*a, **kw):
        return {"status": IDEMPOTENCY_IN_PROGRESS, "prior_status": IDEMPOTENCY_STARTED, "record": {}}
    monkeypatch.setattr(workflow, "begin_idempotent", lost_retake)
    rw = workflow.RecoverableWrite(object(), tenant_id="t", action="a", key="k", fingerprint="fp")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rw.begin())
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
