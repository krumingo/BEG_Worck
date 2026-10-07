"""
W0-06C — the periodic integrity runner: exclusion, bounds, history and alarms.

Everything here is driven through the REAL W0-06B stack: the real Permission
Service (only its assignment loader is in memory), the real registry, the real
provider adapters over disposable in-process fakes, and the real
``FileIntegrityService.check``. The monitor is never given a shortcut.

What each group proves:

* ``TestPolicy``        — every bound is explicit; no cadence/threshold is invented.
* ``TestAuthorization`` — FLOW-002 fails CLOSED before a provider is contacted.
* ``TestExclusion``     — two workers, one run; a crashed claim is taken over;
                          a stale worker can no longer commit.
* ``TestBoundedWalk``   — bounded pages, a durable cursor, resume after a crash,
                          and every original checked exactly once.
* ``TestFindingTypes``  — all five W0-06B findings, each still its own thing;
                          an outage is never evidence of missing/corrupt bytes.
* ``TestLifecycle``     — open / observed / resolved / reopened, one open alarm
                          per identity, and TYPE-SPECIFIC resolution proof.
* ``TestRetry``         — bounded retry with deterministic backoff; transient
                          vs persistent only under an explicit policy.
* ``TestAffected``      — affected records and groups, refreshed when relations
                          change, with the severity and alarm level following.
* ``TestIsolation``     — two tenants share nothing.
* ``TestAuditEvidence`` — correlated FLOW-040 trail, and no secret, token,
                          signed URL or document byte anywhere.
* ``TestProjection``    — the read projection enforces FLOW-002 and sensitivity.

    pytest tests/test_w0_06c_integrity_monitoring.py -v --noconftest
"""
import asyncio
import copy
import hashlib
from datetime import datetime, timezone

import pytest

from app.files import models as m
from app.files.access import FileAccessService
from app.files.authorization import FileAccessDenied
from app.files.integrity import FINDING_SCHEMA, FileIntegrityService
from app.files.monitoring import (
    ACTION_MONITOR_READ,
    ACTION_MONITOR_RUN,
    ALARM_CRITICAL,
    ALARM_INFORMATIONAL,
    ALARM_LEVELS,
    ALARM_WARNING,
    FINDING_OPEN,
    FINDING_RESOLVED,
    MONITOR_COLLECTIONS,
    MODULE_PROBE,
    MONITOR_FINDINGS_COLLECTION,
    MONITOR_RUNS_COLLECTION,
    MONITOR_STATE_COLLECTION,
    OUTAGE_PERSISTENT,
    OUTAGE_TRANSIENT,
    OUTAGE_UNCLASSIFIED,
    TRANSITION_OBSERVED,
    TRANSITION_OPENED,
    TRANSITION_REOPENED,
    TRANSITION_RESOLVED,
    FileIntegrityMonitor,
    MonitorConfigurationRefused,
    MonitorEvidenceRefused,
    MonitorLeaseLost,
    MonitorPolicy,
    ServicePrincipal,
    _Counts,
    _Cursor,
    _Lease,
    alarm_level,
    assert_no_secrets,
    finding_identity,
    resolution_proof,
    sanitize_error,
    service_principal,
)
from app.files.registry import FileRegistry
from app.tenancy.data_access import TenantData
from tests.w0_06b_support import (
    A,
    B,
    OWNER_A,
    OWNER_B,
    accepted,
    configure,
    ctx,
    install_permissions,
    service_for,
    world,
)

pytest.importorskip("mongomock_motor")

DATA = b"%PDF-1.7 act 14 signed original "

#: The tenant-scoped service principals of the runner. They are ORDINARY
#: FLOW-002 principals: the assignment below is what lets them run, and the
#: ``NO_RIGHTS`` one deliberately has none.
SERVICE_A, SERVICE_B, NO_RIGHTS, READER = "svc-a", "svc-b", "svc-none", "reader-a"
#: C02 scope principals: a project-scoped reader, a module-restricted reader,
#: and one holding BOTH a module-restricted and an unrestricted grant.
PM_P0, MODULE_READER, BOTH_GRANTS = "pm-p0", "mod-reader", "both-grants"

MONITOR_ACTIONS = ["file.integrity.monitor", "file.integrity.monitor.read",
                   "file.integrity.check"]

#: A fixed clock, used where a deterministic marker matters.
FROZEN = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)

#: The ONLY reason each finding type is allowed to close with.
PROOFS = {
    "missing_original": "identified_original_present_and_compared",
    "checksum_mismatch": "canonical_checksum_and_size_match",
    "permission_failure": "authorized_content_read_succeeded",
    "provider_unavailable": "provider_verification_succeeded",
    "external_change": "recorded_provider_identity_matches_again",
}

ALL_KINDS = sorted(m.CUSTOMER_MANAGED_PROVIDER_KINDS)
#: The default kind for the behaviour tests. W0-06B already proves all four
#: adapters report the same five states; W0-06C is provider-NEUTRAL because it
#: only ever reads ``FileIntegrityService.check``'s result, and
#: ``test_every_provider_kind_...`` runs the whole cycle on each of them.
KIND = m.PROVIDER_S3_COMPATIBLE


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _perms(monkeypatch):
    install_permissions(monkeypatch, {
        (SERVICE_A, A): [{"id": "ra-svc-a", "status": "active", "role_id": "custom",
                          "permissions": list(MONITOR_ACTIONS), "scope_type": "company"}],
        (SERVICE_B, B): [{"id": "ra-svc-b", "status": "active", "role_id": "custom",
                          "permissions": list(MONITOR_ACTIONS), "scope_type": "company"}],
        # A principal of tenant A with a live assignment that does NOT list the
        # monitor actions: deny-by-default must still refuse it.
        (NO_RIGHTS, A): [{"id": "ra-none", "status": "active", "role_id": "custom",
                          "permissions": ["file.open"], "scope_type": "company"}],
        # Read-only: may list alarms, may NOT run, and holds no sensitivity right.
        (READER, A): [{"id": "ra-reader", "status": "active", "role_id": "custom",
                       "permissions": ["file.integrity.monitor.read"],
                       "scope_type": "company"}],
        # PROJECT-scoped: may read alarms of project P-0 and nothing else.
        (PM_P0, A): [{"id": "ra-pm", "status": "active", "role_id": "custom",
                      "permissions": ["file.integrity.monitor.read"],
                      "scope_type": "project", "scope_id": "P-0"}],
        # Company-scoped but MODULE-restricted: the C01 hole. Nothing maps a
        # finding onto a module, so the projection must refuse it outright.
        (MODULE_READER, A): [{"id": "ra-mod", "status": "active", "role_id": "custom",
                              "permissions": ["file.integrity.monitor.read"],
                              "scope_type": "company", "module": "M2"}],
        # Both: the module-restricted grant must not take away what the
        # unrestricted one gives.
        (BOTH_GRANTS, A): [{"id": "ra-both-mod", "status": "active", "role_id": "custom",
                            "permissions": ["file.integrity.monitor.read"],
                            "scope_type": "company", "module": "M2"},
                           {"id": "ra-both-open", "status": "active", "role_id": "custom",
                            "permissions": ["file.integrity.monitor.read"],
                            "scope_type": "company"}],
    })


def principal(user=SERVICE_A, tenant=A) -> ServicePrincipal:
    return service_principal(tenant_id=tenant, user_id=user)


# ───────────────────────────────────────────────────────────── the test world
async def _activated(org=A, owner=OWNER_A, db=None, sysdb=None, kind=KIND, **backend_kw):
    """One tenant with an ACTIVE provider binding on its own provider root.

    ``backend_kw`` reaches the fake backend, which is how a second tenant gets a
    container of its own: W0-06B refuses to activate two tenants on one root
    (``ROOT_CLAIMED_BY_ANOTHER_TENANT``), and that rule is not weakened here.
    """
    if db is None:
        db, sysdb = await world()
    backends = {}
    svc = service_for(db, sysdb, org, backends)
    binding_id, backend = await configure(svc, owner, kind, **backend_kw)
    backends[binding_id] = backend
    out = await svc.activate(ctx(owner, org), binding_id=binding_id,
                             responsibility=accepted(owner))
    assert out["activated"], out
    return db, sysdb, svc, FileRegistry(TenantData(db, org)), backend, binding_id


async def _upload(access, org, owner, name, *, relations=(), category=m.CATEGORY_ACTS,
                  sensitivity=m.SENSITIVITY_STANDARD):
    out = await access.upload(
        ctx(owner, org), data=DATA + name.encode(), display_name=name,
        original_name=name + ".pdf", category=category, mime_type="application/pdf",
        sensitivity=sensitivity, relations=list(relations))
    assert out["status"] == "registered", out
    return out["file_id"]


async def _world(files=1, relations_per_file=2, org=A, owner=OWNER_A, kind=KIND, **upload_kw):
    """A tenant with an active provider and ``files`` uploaded originals."""
    db, sysdb, svc, reg, backend, binding_id = await _activated(org=org, owner=owner, kind=kind)
    for index in range(max(relations_per_file, 1)):
        await db["projects"].insert_one({"id": "P-%d" % index, "org_id": org,
                                         "name": "site %d" % index})
    access = FileAccessService(reg, svc)
    file_ids = []
    for index in range(files):
        rels = [{"relation_type": m.RELATION_PROJECT, "record_id": "P-%d" % r}
                for r in range(relations_per_file)]
        file_ids.append(await _upload(access, org, owner, "doc%02d" % index,
                                      relations=rels, **upload_kw))
    return {"db": db, "sysdb": sysdb, "svc": svc, "reg": reg, "backend": backend,
            "binding_id": binding_id, "access": access, "file_ids": file_ids, "org": org}


def monitor(w, *, policy=None, worker_id=None, clock=None, sleep=None, integrity=None):
    return FileIntegrityMonitor(
        w["reg"], w["svc"], integrity=integrity,
        policy=policy or MonitorPolicy(max_attempts=1),
        worker_id=worker_id, clock=clock, sleep=sleep)


class _Racing(FileIntegrityMonitor):
    """A monitor whose claim really suspends, so two coroutines can race it.

    ``mongomock`` resolves its awaits without yielding to the event loop, so two
    gathered ``run_once`` calls would otherwise run strictly one after the
    other and never reach the claim at the same time. One ``sleep(0)`` inside
    the claim puts both workers inside it before either proceeds, which is the
    interleaving this exclusion has to survive. The real simultaneous-start
    proof is in ``test_w0_06c_real_mongo.py``, on a real server.
    """

    def __init__(self, registry, storage, **kw):
        kw.setdefault("policy", MonitorPolicy(max_attempts=1))
        super().__init__(registry, storage, **kw)

    async def _claim(self):
        await asyncio.sleep(0)
        return await super()._claim()

    async def _page(self, cursor, limit):
        # A suspension INSIDE the run, so the other worker reaches its claim
        # while this one still holds it.
        await asyncio.sleep(0)
        return await super()._page(cursor, limit)


def _store(backend):
    """The fake provider's object table, whatever that adapter family calls it."""
    return backend.objects if hasattr(backend, "objects") else backend.files


def _snapshot(w):
    """Everything an injection can break, so the CUSTOMER can restore it later."""
    backend = w["backend"]
    return (copy.deepcopy(_store(backend)), set(backend.denied), backend.offline)


def _repair(w, snapshot):
    """The customer restores the original. BEG_Work repairs nothing itself."""
    backend = w["backend"]
    saved, denied, offline = snapshot
    store = _store(backend)
    store.clear()
    store.update(copy.deepcopy(saved))
    backend.denied.clear()
    backend.denied.update(denied)
    backend.offline = offline


async def _inject(w, file_id, how, *, version_no=1):
    """Break one original at the provider, the way W0-06B's own fakes do."""
    location = await w["reg"].primary_location(file_id, version_no)
    key = location["object_key"]
    if how == "mutate":
        w["backend"].mutate(key, b"tampered bytes")
    elif how == "offline":
        w["backend"].offline = True
    else:
        getattr(w["backend"], how)(key)
    return location


async def _findings(w, **flt):
    return await w["db"][MONITOR_FINDINGS_COLLECTION].find(
        dict(flt), {"_id": 0}).to_list(None)


async def _monitor_check_events(w, actor=SERVICE_A):
    """The ``file.integrity.checked`` events the RUNNER caused, in order.

    An upload verifies its own round trip, so the collection already holds the
    uploader's checks. The runner is the only caller using the tenant's service
    principal, which is what separates the two.
    """
    return await w["db"]["audit_events"].find(
        {"action": "file.integrity.checked", "actor_id": actor},
        {"_id": 0}).sort("sequence", 1).to_list(None)


async def _result_for(w, file_id, version_no=1):
    """One raw W0-06B result, for the resolution-proof rules."""
    return await FileIntegrityService(w["reg"], w["svc"]).check(
        principal(), file_id=file_id, version_no=version_no)


async def _sleep_recorder(sink):
    async def sleeper(seconds):
        sink.append(seconds)
    return sleeper


# ══════════════════════════════════════════════════════════════════ the policy
class TestPolicy:
    @pytest.mark.parametrize("kw", [
        {"batch_size": 0}, {"batch_size": -1}, {"max_items_per_run": 0},
        {"max_scanned_per_run": 0}, {"max_attempts": 0}, {"lease_ttl_seconds": 0},
        {"backoff_base_seconds": -1}, {"persistent_outage_after": 0},
        {"recheck_after_seconds": -1}, {"roles": ()}, {"roles": ("sideways",)},
        {"categories": ("nope",)}, {"sensitivities": ("nope",)},
        {"backoff_base_seconds": 4, "backoff_max_seconds": 1},
        {"max_items_per_run": 50, "max_scanned_per_run": 10},
        {"batch_size": True}, {"max_attempts": 2.5},
    ])
    def test_a_nonsense_bound_is_refused_not_silently_corrected(self, kw):
        with pytest.raises(MonitorConfigurationRefused):
            MonitorPolicy(**kw)

    def test_no_cadence_and_no_outage_threshold_are_invented(self):
        policy = MonitorPolicy()
        assert policy.recheck_after_seconds is None
        assert policy.persistent_outage_after is None
        assert policy.roles == (m.LOCATION_ROLE_PRIMARY,)
        assert policy.categories == () and policy.sensitivities == ()

    def test_backoff_is_deterministic_bounded_and_zero_on_the_first_attempt(self):
        policy = MonitorPolicy(max_attempts=6, backoff_base_seconds=0.5,
                               backoff_max_seconds=2.0)
        assert [policy.backoff_for(a) for a in range(1, 7)] == [0.0, 0.5, 1.0, 2.0, 2.0, 2.0]
        assert MonitorPolicy().backoff_for(3) == 0.0

    def test_the_policy_of_a_run_is_stored_as_its_own_evidence(self):
        async def body():
            w = await _world(files=1)
            policy = MonitorPolicy(batch_size=3, max_items_per_run=5, max_scanned_per_run=9)
            out = await monitor(w, policy=policy).run_once(principal())
            assert out["policy"] == policy.as_record()
            stored = await w["db"][MONITOR_RUNS_COLLECTION].find_one({"id": out["run_id"]})
            assert stored["policy"] == policy.as_record()
        run(body())

    def test_the_three_collections_are_tenant_owned_and_classified(self):
        from app.tenancy import ownership
        assert MONITOR_COLLECTIONS == {MONITOR_STATE_COLLECTION, MONITOR_RUNS_COLLECTION,
                                       MONITOR_FINDINGS_COLLECTION}
        for name in MONITOR_COLLECTIONS:
            assert ownership.classify_collection(name) == ownership.CLASS_ORG
            assert ownership.tenant_key_of(name) == ownership.ORG_KEY
            # the monitor is NOT a second File Registry: its collections are
            # deliberately outside REGISTRY_COLLECTIONS
            assert name not in m.REGISTRY_COLLECTIONS

    def test_a_cross_tenant_service_or_registry_pair_cannot_be_built(self):
        async def body():
            w = await _world(files=1)
            other = await _activated(org=B, owner=OWNER_B, db=w["db"], sysdb=w["sysdb"],
                                     bucket="tenant-b-bucket")
            with pytest.raises(MonitorConfigurationRefused):
                FileIntegrityMonitor(w["reg"], other[2])
            with pytest.raises(MonitorConfigurationRefused):
                FileIntegrityMonitor(w["reg"], w["svc"],
                                     integrity=FileIntegrityService(other[3], other[2]))
        run(body())

    @pytest.mark.parametrize("kw", [{"user_id": "", "tenant_id": A},
                                    {"user_id": SERVICE_A, "tenant_id": "  "},
                                    {"user_id": None, "tenant_id": A}])
    def test_an_incomplete_service_principal_is_refused(self, kw):
        with pytest.raises(MonitorConfigurationRefused):
            ServicePrincipal(**kw)


# ═══════════════════════════════════════════════════════════════ FLOW-002 gate
class TestAuthorization:
    def test_a_principal_without_the_monitor_action_is_refused_before_any_provider(self):
        async def body():
            w = await _world(files=2)
            mon = monitor(w)
            before = len(w["backend"].requests)
            with pytest.raises(FileAccessDenied) as denied:
                await mon.run_once(principal(NO_RIGHTS))
            assert denied.value.action == ACTION_MONITOR_RUN
            assert denied.value.reason_code == "ACTION_NOT_ALLOWED"
            # fail CLOSED: no provider traffic, no claim, no run, no finding
            assert len(w["backend"].requests) == before
            assert await w["db"][MONITOR_STATE_COLLECTION].count_documents({}) == 0
            assert await w["db"][MONITOR_RUNS_COLLECTION].count_documents({}) == 0
            assert await w["db"][MONITOR_FINDINGS_COLLECTION].count_documents({}) == 0
        run(body())

    def test_a_session_less_or_cross_tenant_caller_is_refused(self):
        async def body():
            w = await _world(files=1)
            mon = monitor(w)
            with pytest.raises(FileAccessDenied) as no_session:
                await mon.run_once(ctx(None, A))
            assert no_session.value.reason_code == "NO_SESSION"
            with pytest.raises(FileAccessDenied) as foreign:
                await mon.run_once(principal(SERVICE_B, B))
            assert foreign.value.reason_code == "CROSS_TENANT"
            assert await w["db"][MONITOR_RUNS_COLLECTION].count_documents({}) == 0
        run(body())

    @pytest.mark.parametrize("status,reason", [("revoked", "ASSIGNMENT_REVOKED"),
                                               ("inactive", "ASSIGNMENT_INACTIVE")])
    def test_a_revoked_or_inactive_assignment_stops_the_runner(self, monkeypatch,
                                                               status, reason):
        async def body():
            w = await _world(files=1)
            install_permissions(monkeypatch, {
                (SERVICE_A, A): [{"id": "ra-svc-a", "status": status, "role_id": "custom",
                                  "permissions": list(MONITOR_ACTIONS),
                                  "scope_type": "company"}]})
            with pytest.raises(FileAccessDenied) as denied:
                await monitor(w).run_once(principal())
            assert denied.value.reason_code == reason
        run(body())

    def test_the_denial_itself_is_an_audited_security_event(self):
        async def body():
            w = await _world(files=1)
            with pytest.raises(FileAccessDenied):
                await monitor(w).run_once(principal(NO_RIGHTS))
            event = await w["db"]["audit_events"].find_one(
                {"action": "file.access.denied"}, {"_id": 0})
            assert event and event["result"] == "failure"
            assert event["error_code"] == "ACTION_NOT_ALLOWED"
            assert event["retention_class"] == "R3"
            assert event["tenant_id"] == A
            assert event["structured_diff"]["action"] == ACTION_MONITOR_RUN
        run(body())

    def test_an_authorized_service_principal_runs(self):
        async def body():
            w = await _world(files=2)
            out = await monitor(w).run_once(principal())
            assert out["status"] == "completed" and out["exhausted"] is True
            assert out["counts"]["checked"] == 2 and out["counts"]["ok"] == 2
            assert out["finding_schema"] == FINDING_SCHEMA
            assert out["tenant_id"] == A and out["worker_id"]
        run(body())


# ═════════════════════════════════════════════════════════ concurrent exclusion
class TestExclusion:
    def test_two_workers_started_together_produce_exactly_one_run(self):
        async def body():
            w = await _world(files=4)
            one, two = (_Racing(w["reg"], w["svc"], worker_id="w-1"),
                        _Racing(w["reg"], w["svc"], worker_id="w-2"))
            first, second = await asyncio.gather(one.run_once(principal()),
                                                 two.run_once(principal()))
            assert sorted([first["status"], second["status"]]) == ["completed",
                                                                   "skipped_locked"]
            locked = first if first["status"] == "skipped_locked" else second
            assert locked["run_id"] is None and locked["counts"]["checked"] == 0
            # one run document, and every original checked exactly once
            assert await w["db"][MONITOR_RUNS_COLLECTION].count_documents({}) == 1
            assert len(await _monitor_check_events(w)) == 4
            assert await w["db"][MONITOR_STATE_COLLECTION].count_documents({}) == 1
        run(body())

    def test_a_second_worker_is_locked_out_while_a_claim_is_live(self):
        async def body():
            w = await _world(files=1)
            one, two = monitor(w, worker_id="w-1"), monitor(w, worker_id="w-2")
            held = await one._claim()
            assert held is not None and held.fence == 1
            assert await two._claim() is None
            out = await two.run_once(principal())
            assert out["status"] == "skipped_locked"
            assert await w["db"][MONITOR_RUNS_COLLECTION].count_documents({}) == 0
            assert await _monitor_check_events(w) == []
        run(body())

    def test_an_expired_claim_is_taken_over_with_a_strictly_newer_fence(self):
        async def body():
            w = await _world(files=1)
            one, two = monitor(w, worker_id="w-1"), monitor(w, worker_id="w-2")
            held = await one._claim()
            await w["db"][MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-1"}, {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            taken = await two._claim()
            assert taken is not None
            assert taken.holder == "w-2" and taken.fence > held.fence
        run(body())

    def test_a_stale_worker_can_no_longer_renew_commit_or_close(self):
        async def body():
            w = await _world(files=3)
            one, two = monitor(w, worker_id="w-1"), monitor(w, worker_id="w-2")
            stale = await one._claim()
            row = await one._open_run(principal(), stale, run_id=None)
            await w["db"][MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-1"}, {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            fresh = await two._claim()
            await two._open_run(principal(), fresh, run_id=row["id"])
            counts, cursor = _Counts(scanned=99, checked=99), _Cursor()
            with pytest.raises(MonitorLeaseLost):
                await one._renew(stale)
            with pytest.raises(MonitorLeaseLost):
                await one._checkpoint(row, stale, counts, cursor, "fl_whatever")
            with pytest.raises(MonitorLeaseLost):
                await one._finish_run(row, stale, counts, cursor,
                                      status="completed", exhausted=True)
            # the new owner's run was not rewound and the stale counts never landed
            after = await w["db"][MONITOR_RUNS_COLLECTION].find_one({"id": row["id"]})
            assert after["lease_holder"] == "w-2" and after["fence"] == fresh.fence
            assert after["counts"]["checked"] == 0 and after["status"] == "running"
            assert "fl_whatever" not in (after.get("processed_location_ids") or [])
        run(body())

    def test_a_stale_worker_cannot_overwrite_the_new_owners_result(self):
        async def body():
            w = await _world(files=1)
            one, two = monitor(w, worker_id="w-1"), monitor(w, worker_id="w-2")
            stale = await one._claim()
            await w["db"][MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-1"}, {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            fresh = await two._claim()
            await one._release(stale, run_id="fir_stale", status="completed",
                               result={"counts": {"checked": 999}}, next_due_at=None)
            state = await w["db"][MONITOR_STATE_COLLECTION].find_one({})
            assert state["holder"] == "w-2" and state["fence"] == fresh.fence
            assert state["last_run_id"] is None and state["runs_total"] == 0
        run(body())

    def test_the_claim_is_released_with_the_last_next_and_result_metadata(self):
        async def body():
            w = await _world(files=2)
            # 0 seconds = "every candidate is due whenever a pass is triggered",
            # which is still an EXPLICIT policy value and not an assumed cadence.
            mon = monitor(w, policy=MonitorPolicy(recheck_after_seconds=0))
            out = await mon.run_once(principal())
            state = await mon.monitor_state(principal())
            assert state["holder"] is None            # released, so the next pass can run
            assert state["last_run_id"] == out["run_id"]
            assert state["last_status"] == "completed"
            assert state["last_result"]["counts"]["checked"] == 2
            assert state["runs_total"] == 1 and state["last_run_at"]
            assert state["next_due_at"] and state["next_due_at"] == out["next_due_at"]
        run(body())

    def test_without_a_cadence_there_is_no_next_due_date(self):
        async def body():
            w = await _world(files=1)
            mon = monitor(w)
            out = await mon.run_once(principal())
            assert out["next_due_at"] is None
            assert (await mon.monitor_state(principal()))["next_due_at"] is None
        run(body())


# ══════════════════════════════════════════════════════════════ bounded walk
class TestBoundedWalk:
    def test_a_run_never_checks_more_than_its_bound_and_resumes_where_it_stopped(self):
        async def body():
            w = await _world(files=5)
            policy = MonitorPolicy(batch_size=2, max_items_per_run=2, max_scanned_per_run=50)
            mon = monitor(w, policy=policy)
            passes = [await mon.run_once(principal()) for _ in range(3)]
            # the provider bound is never exceeded, in any pass
            assert [p["counts"]["checked"] for p in passes] == [2, 2, 2]
            assert len({p["run_id"] for p in passes}) == 3
            # and three bounded passes have covered all five originals: a bound
            # stops a pass, it never loses a file
            events = await _monitor_check_events(w)
            assert len({e["entity_id"] for e in events}) == 5
            # each pass left a durable cursor to carry on from
            assert all(p["cursor"]["last_id"] for p in passes)
        run(body())

    def test_a_crashed_run_is_taken_over_and_finishes_without_skipping_or_repeating(self):
        async def body():
            w = await _world(files=6)
            crashed = monitor(w, worker_id="w-crash",
                              policy=MonitorPolicy(batch_size=2, max_items_per_run=3,
                                                   max_scanned_per_run=50))
            lease = await crashed._claim()
            row = await crashed._open_run(principal(), lease, run_id=None)
            counts, cursor, processed = _Counts(), _Cursor(), set()
            await crashed._walk(principal(), row, lease, counts, cursor, processed)
            assert counts.checked == 3
            # the process dies here: the run stays `running` and the claim is
            # never released. Only its expiry lets anyone else continue.
            await w["db"][MONITOR_STATE_COLLECTION].update_one(
                {"holder": "w-crash"},
                {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
            rescuer = monitor(w, worker_id="w-rescue",
                              policy=MonitorPolicy(batch_size=4, max_items_per_run=100,
                                                   max_scanned_per_run=100))
            out = await rescuer.run_once(principal())
            assert out["run_id"] == row["id"]       # the SAME run, resumed
            assert out["status"] == "completed" and out["exhausted"] is True
            assert out["counts"]["checked"] == 6    # 3 inherited + 3 finished
            assert await w["db"][MONITOR_RUNS_COLLECTION].count_documents({}) == 1
            stored = await w["db"][MONITOR_RUNS_COLLECTION].find_one({"id": out["run_id"]})
            assert stored["takeovers"] == 1 and stored["resumed_at"]
            assert stored["fence"] > lease.fence
            events = await _monitor_check_events(w)
            assert len(events) == 6 and len({e["entity_id"] for e in events}) == 6
        run(body())

    def test_a_finished_run_is_history_and_is_never_reopened(self):
        async def body():
            w = await _world(files=1)
            mon = monitor(w)
            out = await mon.run_once(principal())
            for run_id in (out["run_id"], "fir_nope"):
                with pytest.raises(MonitorConfigurationRefused):
                    await mon.run_once(principal(), run_id=run_id)
                # a refused run must RELEASE the claim, not wedge the tenant
                state = await w["db"][MONITOR_STATE_COLLECTION].find_one({})
                assert state["holder"] is None
            # and an ordinary pass still works afterwards
            assert (await mon.run_once(principal()))["status"] == "completed"
        run(body())

    def test_a_re_checked_item_never_raises_a_second_alarm(self):
        """A crash between the check and its checkpoint makes the resumed run
        walk that location again. The second check is a REAL check and gets its
        own FLOW-040 event; what must not double is the finding and the alarm.
        """
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            mon = monitor(w, worker_id="w-1")
            lease = await mon._claim()
            row = await mon._open_run(principal(), lease, run_id=None)
            counts = _Counts()
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            await mon._check_one(principal(), row, lease, counts, location)
            await mon._check_one(principal(), row, lease, counts, location)
            assert counts.checked == 2                 # two checks really happened
            assert len(await _monitor_check_events(w)) == 2      # both audited
            rows = await _findings(w)
            assert len(rows) == 1                      # ONE open alarm, not two
            assert rows[0]["occurrences"] == 2
            assert rows[0]["state"] == FINDING_OPEN
            opened = await w["db"]["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"})
            assert opened == 1                         # the alarm was raised ONCE
            assert [t["transition"] for t in rows[0]["transitions"]] == [
                TRANSITION_OPENED, TRANSITION_OBSERVED]
        run(body())

    def test_an_item_already_walked_in_this_run_is_not_walked_again(self):
        async def body():
            w = await _world(files=2)
            mon = monitor(w, policy=MonitorPolicy(batch_size=1, max_items_per_run=10,
                                                  max_scanned_per_run=10))
            out = await mon.run_once(principal())
            assert out["counts"]["checked"] == 2 and out["exhausted"] is True
            events = await _monitor_check_events(w)
            # each original checked exactly once, although every check moves the
            # location forward in the walk's own ordering
            assert len(events) == 2 and len({e["entity_id"] for e in events}) == 2
            stored = await w["db"][MONITOR_RUNS_COLLECTION].find_one({"id": out["run_id"]})
            assert len(stored["processed_location_ids"]) == 2
        run(body())

    def test_only_current_versions_are_checked(self):
        async def body():
            w = await _world(files=1)
            file_id = w["file_ids"][0]
            location = await w["reg"].primary_location(file_id, 1)
            await w["reg"].add_version(
                actor_id=OWNER_A, file_id=file_id,
                checksum_value=m.checksum(hashlib.sha256(b"v2").hexdigest()),
                size_bytes=2, mime_type="application/pdf", original_name="doc00.pdf",
                reason="new scan",
                provider_location={"provider_kind": location["provider_kind"],
                                   "provider_binding_id": location["provider_binding_id"],
                                   "container": location["container"],
                                   "object_key": "v2/object"})
            out = await monitor(w).run_once(principal())
            assert out["counts"]["skipped_not_current"] == 1
            assert out["counts"]["checked"] == 1
            events = await _monitor_check_events(w)
            assert [e["entity_version"] for e in events] == ["2"]
        run(body())

    def test_never_verified_locations_are_walked_first_and_only_once(self):
        """The walk's two phases, both exercised, with no file lost between them.

        An upload verifies its own round trip, so an uploaded original already
        has a ``last_verified_at``. A location recorded WITHOUT a check — a new
        version, a provider migration — has none, and FLOW-016 puts the
        never-checked originals first.
        """
        async def body():
            w = await _world(files=2)
            location = await w["reg"].primary_location(w["file_ids"][0], 1)
            # two more versions, each with a location nobody has checked yet
            for file_id, payload in zip(w["file_ids"], (b"v2a", b"v2b")):
                await w["reg"].add_version(
                    actor_id=OWNER_A, file_id=file_id,
                    checksum_value=m.checksum(hashlib.sha256(payload).hexdigest()),
                    size_bytes=len(payload), mime_type="application/pdf",
                    original_name="doc.pdf", reason="rescan",
                    provider_location={"provider_kind": location["provider_kind"],
                                       "provider_binding_id": location["provider_binding_id"],
                                       "container": location["container"],
                                       "object_key": "v2/%s" % file_id})
            unverified = await w["db"][m.LOCATIONS_COLLECTION].find(
                {"last_verified_at": None}, {"_id": 0}).to_list(None)
            assert len(unverified) == 2
            out = await monitor(w, policy=MonitorPolicy(
                batch_size=1, max_items_per_run=10, max_scanned_per_run=10)
            ).run_once(principal())
            assert out["exhausted"] is True
            # the two current (version 2) originals were checked; the two
            # superseded version-1 originals were skipped as not current
            assert out["counts"]["checked"] == 2
            assert out["counts"]["skipped_not_current"] == 2
            assert out["cursor"]["phase"] == "verified"
            events = await _monitor_check_events(w)
            assert len(events) == 2 and {e["entity_version"] for e in events} == {"2"}
            assert len({e["entity_id"] for e in events}) == 2
        run(body())

    def test_a_category_scope_restriction_excludes_out_of_scope_files(self):
        async def body():
            w = await _world(files=1)
            await _upload(w["access"], A, OWNER_A, "photo", category=m.CATEGORY_PHOTO_VIDEO)
            mon = monitor(w, policy=MonitorPolicy(categories=(m.CATEGORY_ACTS,)))
            out = await mon.run_once(principal())
            assert out["counts"]["checked"] == 1
            assert out["counts"]["skipped_out_of_scope"] == 1
            assert out["counts"]["scanned"] == 2
        run(body())

    def test_a_recently_verified_original_is_not_due_under_a_cadence(self):
        async def body():
            w = await _world(files=2)
            first = await monitor(w).run_once(principal())
            assert first["counts"]["checked"] == 2
            # everything was just verified, so nothing is due again yet
            again = await monitor(w, policy=MonitorPolicy(recheck_after_seconds=86400)
                                  ).run_once(principal())
            assert again["counts"]["checked"] == 0
            assert again["counts"]["skipped_not_due"] == 2
            # with no cadence configured, a triggered run checks them again
            third = await monitor(w).run_once(principal())
            assert third["counts"]["checked"] == 2
        run(body())

    def test_the_scan_bound_stops_the_walk_even_when_nothing_is_checkable(self):
        async def body():
            w = await _world(files=4)
            mon = monitor(w, policy=MonitorPolicy(
                batch_size=2, max_items_per_run=1, max_scanned_per_run=2,
                categories=(m.CATEGORY_INVOICES,)))
            out = await mon.run_once(principal())
            assert out["counts"]["checked"] == 0
            assert out["counts"]["scanned"] == 2 and out["exhausted"] is False
        run(body())

    def test_the_cursor_and_the_checkpoint_are_durable(self):
        async def body():
            w = await _world(files=3)
            mon = monitor(w, policy=MonitorPolicy(batch_size=1, max_items_per_run=1,
                                                  max_scanned_per_run=10))
            out = await mon.run_once(principal())
            stored = await w["db"][MONITOR_RUNS_COLLECTION].find_one({"id": out["run_id"]})
            assert stored["cursor"]["phase"] in ("unverified", "verified")
            assert stored["cursor"]["last_id"]
            assert stored["cursor"] == out["cursor"]
            assert len(stored["processed_location_ids"]) == 1
            assert stored["counts"]["checked"] == 1
            assert stored["status"] == "completed" and stored["exhausted"] is False
        run(body())

    @pytest.mark.parametrize("kind", ALL_KINDS)
    def test_every_provider_kind_runs_the_same_cycle(self, kind):
        async def body():
            w = await _world(files=1, kind=kind)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["finding_type"] == "missing_original"
            assert found["provider_kind"] == kind
            _repair(w, snapshot)
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 1
            found, = await _findings(w)
            assert found["state"] == FINDING_RESOLVED
            assert found["resolution"]["reason"] == PROOFS["missing_original"]
        run(body())


# ═══════════════════════════════════════════════════════════════ finding types
class TestFindingTypes:
    @pytest.mark.parametrize("inject,availability,finding_type,severity,level", [
        # With TWO affected records the W0-06B severity already separates proven
        # loss/corruption from an access problem, and the alarm level follows it.
        ("remove", m.AVAILABILITY_MISSING, "missing_original", "critical", ALARM_CRITICAL),
        ("mutate", m.AVAILABILITY_CHECKSUM_MISMATCH, "checksum_mismatch", "critical",
         ALARM_CRITICAL),
        ("replace", m.AVAILABILITY_EXTERNALLY_CHANGED, "external_change", "critical",
         ALARM_CRITICAL),
        ("deny", m.AVAILABILITY_PERMISSION_DENIED, "permission_failure", "high",
         ALARM_WARNING),
        ("offline", m.AVAILABILITY_PROVIDER_UNREACHABLE, "provider_unavailable", "high",
         ALARM_WARNING),
    ])
    def test_each_w0_06b_finding_opens_its_own_alarm_with_its_own_evidence(
            self, inject, availability, finding_type, severity, level):
        async def body():
            w = await _world(files=1, relations_per_file=2)
            await _inject(w, w["file_ids"][0], inject)
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_opened"] == 1
            found, = await _findings(w)
            assert found["finding_type"] == finding_type
            assert found["availability"] == availability
            assert found["state"] == FINDING_OPEN
            assert found["schema"] == FINDING_SCHEMA
            assert found["severity"] == severity         # two affected records
            assert found["alarm_level"] == level
            assert found["affected_record_count"] == 2
            assert found["affected_by_group"] == {"projects": ["P-0", "P-1"]}
            assert found["provider_binding_id"] == w["binding_id"]
            assert found["provider_kind"] == KIND
            assert found["location_id"] and found["version_no"] == 1
            assert found["role"] == m.LOCATION_ROLE_PRIMARY
            assert found["occurrences"] == 1 and found["first_seen"] == found["last_seen"]
            assert found["evidence"]["availability"] == availability
            assert found["recovery"]["owner"] == "customer"
            # the W0-07 hand-off travels unchanged and unconsumed
            assert found["dq_handoff"] == {"consumer": "W0-07", "state": "not_consumed",
                                           "blocking": True}
            assert [t["transition"] for t in found["transitions"]] == [TRANSITION_OPENED]
        run(body())

    def test_an_outage_is_never_turned_into_missing_or_corrupt_bytes(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "offline")
            for _ in range(3):
                await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["finding_type"] == "provider_unavailable"
            assert found["availability"] == m.AVAILABILITY_PROVIDER_UNREACHABLE
            assert found["state"] == FINDING_OPEN
            # the recorded expectation is untouched: nothing was "observed"
            assert found["evidence"]["observed"]["checksum"] is None
            assert found["evidence"]["expected"]["checksum"]
            # and the original was never adopted or re-versioned
            assert await w["db"][m.VERSIONS_COLLECTION].count_documents(
                {"file_id": w["file_ids"][0]}) == 1
        run(body())

    def test_an_externally_replaced_object_is_never_adopted_as_a_new_version(self):
        async def body():
            w = await _world(files=1)
            location = await _inject(w, w["file_ids"][0], "replace")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["finding_type"] == "external_change"
            after = await w["db"][m.LOCATIONS_COLLECTION].find_one({"id": location["id"]})
            # the canonical expectation is EXACTLY what it was
            assert after["expected_checksum"] == location["expected_checksum"]
            assert after["provider_file_id"] == location["provider_file_id"]
            assert after["provider_version_id"] == location["provider_version_id"]
            assert await w["db"][m.VERSIONS_COLLECTION].count_documents(
                {"file_id": w["file_ids"][0]}) == 1
        run(body())

    def test_a_file_attached_to_nothing_is_informational_not_critical(self):
        async def body():
            w = await _world(files=0)
            file_id = await _upload(w["access"], A, OWNER_A, "orphan")
            await _inject(w, file_id, "remove")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["affected_record_count"] == 0
            assert found["severity"] == "low" and found["alarm_level"] == ALARM_INFORMATIONAL
            assert found["dq_handoff"]["blocking"] is False
        run(body())

    def test_a_single_affected_record_warns_rather_than_escalating(self):
        async def body():
            w = await _world(files=1, relations_per_file=1)
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["affected_record_count"] == 1
            assert found["severity"] == "high" and found["alarm_level"] == ALARM_WARNING
        run(body())

    def test_the_alarm_levels_are_a_total_deterministic_map_of_the_b_severity(self):
        assert alarm_level("none") is None
        assert [alarm_level(s) for s in ("info", "low", "medium", "high", "critical")] == [
            ALARM_INFORMATIONAL, ALARM_INFORMATIONAL, ALARM_WARNING, ALARM_WARNING,
            ALARM_CRITICAL]
        assert alarm_level(None) is None and alarm_level("invented") is None
        for availability in m.AVAILABILITY_STATES:
            for count in (0, 1, 2, 7):
                level = alarm_level(m.severity_of(availability, count))
                assert level is None or level in ALARM_LEVELS

    def test_one_identity_per_tenant_file_version_location_binding_and_type(self):
        same = dict(org_id=A, file_id="file_1", version_no=1, location_id="fl_1",
                    provider_binding_id="bind-1", finding_type="missing_original")
        assert finding_identity(**same) == finding_identity(**same)
        for name, value in [("org_id", B), ("file_id", "file_2"), ("version_no", 2),
                            ("location_id", "fl_2"), ("provider_binding_id", "bind-2"),
                            ("finding_type", "checksum_mismatch")]:
            assert finding_identity(**dict(same, **{name: value})) != finding_identity(**same)
        # the length prefix keeps a value containing the separator unambiguous
        assert finding_identity(**dict(same, file_id="a|1")) != \
            finding_identity(**dict(same, file_id="a", location_id="1|fl_1"))


# ═══════════════════════════════════════════════════════════════════ lifecycle
class TestLifecycle:
    def test_a_repeated_problem_is_observed_once_not_alarmed_again(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            for _ in range(4):
                await monitor(w).run_once(principal())
            rows = await _findings(w)
            assert len(rows) == 1                       # ONE open alarm, not four
            found = rows[0]
            assert found["occurrences"] == 4 and found["state"] == FINDING_OPEN
            assert found["consecutive_observations"] == 4
            assert found["last_seen"] > found["first_seen"]
            kinds = [t["transition"] for t in found["transitions"]]
            assert kinds == [TRANSITION_OPENED] + [TRANSITION_OBSERVED] * 3
            assert len(set(found["transition_keys"])) == len(found["transition_keys"])
            opened = await w["db"]["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"})
            assert opened == 1                          # the alarm was raised ONCE
        run(body())

    def test_the_same_transition_at_the_same_marker_is_appended_only_once(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            mon = monitor(w)
            await mon.run_once(principal())
            found, = await _findings(w)
            result = await _result_for(w, w["file_ids"][0])
            row = await w["db"][MONITOR_RUNS_COLLECTION].find_one({}, {"_id": 0})
            lease = _Lease(holder=row["lease_holder"], fence=row["fence"], expires_at="")
            args = dict(marker="2026-10-07T12:00:00.000000+00:00", severity="critical",
                        finding_type="missing_original")
            first = await mon._transition(principal(), row, lease, found["id"],
                                          TRANSITION_OBSERVED, result, **args)
            second = await mon._transition(principal(), row, lease, found["id"],
                                           TRANSITION_OBSERVED, result, **args)
            assert first is True and second is False
            after, = await _findings(w)
            assert [t["transition"] for t in after["transitions"]] == [
                TRANSITION_OPENED, TRANSITION_OBSERVED]
            observed = await w["db"]["audit_events"].count_documents(
                {"action": "file.integrity.finding.observed"})
            assert observed == 1
        run(body())

    @pytest.mark.parametrize("inject,finding_type,kind", [
        ("remove", "missing_original", KIND),
        ("mutate", "checksum_mismatch", KIND),
        ("offline", "provider_unavailable", KIND),
        # A permission finding can only be closed by bytes BEG_Work actually
        # READ, so its positive case needs a provider that reads them. On a
        # provider that answers with its own digest from `stat` the finding
        # stays open — proven in `test_a_permission_finding_is_not_closed_...`.
        ("deny", "permission_failure", m.PROVIDER_ON_PREM_SERVER),
    ])
    def test_a_repaired_original_resolves_with_a_type_specific_proof(self, inject,
                                                                     finding_type, kind):
        async def body():
            w = await _world(files=1, kind=kind)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], inject)
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["finding_type"] == finding_type and found["state"] == FINDING_OPEN
            _repair(w, snapshot)
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 1
            found, = await _findings(w)
            assert found["state"] == FINDING_RESOLVED and found["resolved_at"]
            assert found["resolution_blocked_reason"] is None
            assert found["consecutive_observations"] == 0
            assert found["resolution"]["reason"] == PROOFS[finding_type]
            assert found["resolution"]["method"] in ("server_checksum", "read_and_hash")
            if finding_type == "permission_failure":
                assert found["resolution"]["method"] == "read_and_hash"
            assert found["resolution"]["run_id"] == out["run_id"]
            assert [t["transition"] for t in found["transitions"]] == [
                TRANSITION_OPENED, TRANSITION_RESOLVED]
        run(body())

    def test_a_failure_after_a_resolution_reopens_the_same_finding_with_its_history(self):
        async def body():
            w = await _world(files=1)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w).run_once(principal())
            _repair(w, snapshot)
            await monitor(w).run_once(principal())
            await _inject(w, w["file_ids"][0], "remove")
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_reopened"] == 1
            rows = await _findings(w)
            assert len(rows) == 1                        # reopened, never duplicated
            found = rows[0]
            assert found["state"] == FINDING_OPEN and found["reopened_at"]
            assert found["resolved_at"] is None
            assert found["consecutive_observations"] == 1
            assert found["occurrences"] == 2
            assert [t["transition"] for t in found["transitions"]] == [
                TRANSITION_OPENED, TRANSITION_RESOLVED, TRANSITION_REOPENED]
            # the whole history is still readable, including the earlier closure
            assert found["first_seen"] < found["reopened_at"]
        run(body())

    def test_a_mere_successful_retry_does_not_close_an_unproven_finding(self):
        """``ok`` with nothing compared is not evidence that the bytes are back."""
        reachable = {"ok": True, "availability": m.AVAILABILITY_AVAILABLE, "method": "none",
                     "expected": {"checksum": {"algorithm": "sha256", "value": "a"},
                                  "size_bytes": 3, "provider_file_id": "o1",
                                  "provider_version_id": "v1"},
                     "observed": {"checksum": None, "size_bytes": None,
                                  "provider_file_id": None, "provider_version_id": None}}
        for finding_type in PROOFS:
            proven, reason = resolution_proof(finding_type, reachable)
            assert proven is False, finding_type
            assert reason.startswith(("incomplete_proof:", "requires_explicit_decision:"))
        # a size-only comparison is not a content comparison either
        sized = dict(reachable, method="size_only")
        assert resolution_proof("missing_original", sized) == (
            False, "incomplete_proof:no_content_comparison")
        # An OUTAGE is no exception: "the provider answered" is not a complete
        # verification. `available` can come back with nothing compared at all.
        assert resolution_proof("provider_unavailable", reachable) == (
            False, "incomplete_proof:no_content_comparison")

    def test_a_still_failing_result_never_resolves_anything(self):
        failing = {"ok": False, "availability": m.AVAILABILITY_MISSING, "method": "none",
                   "expected": {}, "observed": {}}
        for finding_type in PROOFS:
            proven, reason = resolution_proof(finding_type, failing)
            assert proven is False and reason == "still_failing:missing"
        assert resolution_proof(None, failing) == (False, "unknown_finding_type")
        assert resolution_proof("invented", failing) == (False, "unknown_finding_type")

    def test_a_checksum_finding_needs_the_canonical_checksum_and_size_back(self):
        base = {"ok": True, "availability": m.AVAILABILITY_AVAILABLE,
                "method": "server_checksum",
                "expected": {"checksum": {"algorithm": "sha256", "value": "aa"},
                             "size_bytes": 10},
                "observed": {"checksum": {"algorithm": "sha256", "value": "aa"},
                             "size_bytes": 10}}
        assert resolution_proof("checksum_mismatch", base) == (
            True, "canonical_checksum_and_size_match")
        for observed, reason in [
                ({"checksum": {"algorithm": "sha256", "value": "bb"}, "size_bytes": 10},
                 "incomplete_proof:checksum_still_differs"),
                ({"checksum": {"algorithm": "md5", "value": "aa"}, "size_bytes": 10},
                 "incomplete_proof:checksum_still_differs"),
                ({"checksum": {"algorithm": "sha256", "value": "aa"}, "size_bytes": 11},
                 "incomplete_proof:size_still_differs"),
                ({"checksum": None, "size_bytes": 10},
                 "incomplete_proof:no_observed_checksum"),
                ({"checksum": {"algorithm": "sha256", "value": "aa"}, "size_bytes": None},
                 "incomplete_proof:no_observed_size")]:
            assert resolution_proof("checksum_mismatch", dict(base, observed=observed)) == (
                False, reason)

    def test_a_missing_finding_needs_the_object_identified_again(self):
        base = {"ok": True, "availability": m.AVAILABILITY_AVAILABLE,
                "method": "read_and_hash",
                "expected": {"provider_file_id": "o1"},
                "observed": {"provider_file_id": "o1"}}
        assert resolution_proof("missing_original", base) == (
            True, "identified_original_present_and_compared")
        other = dict(base, observed={"provider_file_id": "o2"})
        assert resolution_proof("missing_original", other) == (
            False, "incomplete_proof:provider_object_not_identified")

    def test_an_external_change_is_never_closed_without_the_recorded_identity(self):
        unidentified = {"ok": True, "availability": m.AVAILABILITY_AVAILABLE,
                        "method": "read_and_hash",
                        "expected": {"provider_file_id": None, "provider_version_id": None},
                        "observed": {"provider_file_id": "new-object",
                                     "provider_version_id": "new-version"}}
        assert resolution_proof("external_change", unidentified) == (
            False, "requires_explicit_decision:no_recorded_provider_identity")
        unobserved = {"ok": True, "availability": m.AVAILABILITY_AVAILABLE,
                      "method": "read_and_hash",
                      "expected": {"provider_file_id": "o1", "provider_version_id": None},
                      "observed": {"provider_file_id": None, "provider_version_id": None}}
        assert resolution_proof("external_change", unobserved) == (
            False, "requires_explicit_decision:provider_file_id_unobserved")
        moved = {"ok": True, "availability": m.AVAILABILITY_AVAILABLE,
                 "method": "read_and_hash",
                 "expected": {"provider_file_id": "o1", "provider_version_id": "v1"},
                 "observed": {"provider_file_id": "o1", "provider_version_id": "v2"}}
        assert resolution_proof("external_change", moved) == (
            False, "requires_explicit_decision:provider_version_id_still_differs")
        restored = dict(moved, observed={"provider_file_id": "o1",
                                         "provider_version_id": "v1"})
        assert resolution_proof("external_change", restored) == (
            True, "recorded_provider_identity_matches_again")

    def test_a_healthy_provider_does_not_close_a_still_replaced_object(self):
        async def body():
            w = await _world(files=1)
            location = await _inject(w, w["file_ids"][0], "replace")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["finding_type"] == "external_change"
            # the provider answers perfectly well again and the BYTES are right;
            # the recorded object identity is still not the one on file
            w["backend"].mutate(location["object_key"], DATA + b"doc00")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["state"] == FINDING_OPEN
            assert found["resolution"] is None
            assert found["occurrences"] == 2
        run(body())

    def test_two_different_problems_on_one_location_are_two_findings(self):
        async def body():
            w = await _world(files=1)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], "offline")
            await monitor(w).run_once(principal())
            w["backend"].offline = False
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w).run_once(principal())
            rows = sorted(await _findings(w), key=lambda r: r["finding_type"])
            assert [r["finding_type"] for r in rows] == ["missing_original",
                                                         "provider_unavailable"]
            # a check that proves the file is GONE does not close the outage
            outage = rows[1]
            assert outage["state"] == FINDING_OPEN
            assert outage["resolution_blocked_reason"] == "still_failing:missing"
            # restoring everything closes both, each by its own proof
            _repair(w, snapshot)
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 2
            closed = await _findings(w)
            assert {r["state"] for r in closed} == {FINDING_RESOLVED}
            assert {r["resolution"]["reason"] for r in closed} == {
                PROOFS["missing_original"], PROOFS["provider_unavailable"]}
        run(body())


# ═══════════════════════════════════════════════════════════════ retry/backoff
class TestRetry:
    def test_a_transient_outage_is_retried_within_one_run_and_then_succeeds(self):
        async def body():
            w = await _world(files=1)
            waits = []
            w["backend"].offline = True

            async def sleeper(seconds):
                waits.append(seconds)
                w["backend"].offline = False     # the provider comes back
            mon = monitor(w, sleep=sleeper, policy=MonitorPolicy(
                max_attempts=3, backoff_base_seconds=0.25, backoff_max_seconds=1.0))
            out = await mon.run_once(principal())
            assert waits == [0.25]
            assert out["counts"]["attempts"] == 2 and out["counts"]["retries"] == 1
            assert out["counts"]["checked"] == 1 and out["counts"]["ok"] == 1
            assert await _findings(w) == []       # no alarm for a recovered attempt
        run(body())

    def test_a_persistent_outage_exhausts_the_bounded_attempts_and_stops(self):
        async def body():
            w = await _world(files=1)
            waits = []
            w["backend"].offline = True
            mon = monitor(w, sleep=await _sleep_recorder(waits), policy=MonitorPolicy(
                max_attempts=4, backoff_base_seconds=0.5, backoff_max_seconds=1.0))
            out = await mon.run_once(principal())
            assert waits == [0.5, 1.0, 1.0]       # bounded and capped, never endless
            assert out["counts"]["attempts"] == 4 and out["counts"]["retries"] == 3
            assert out["counts"]["checked"] == 1
            found, = await _findings(w)
            assert found["finding_type"] == "provider_unavailable"
        run(body())

    @pytest.mark.parametrize("inject", ["remove", "mutate", "deny", "replace"])
    def test_a_determinate_failure_is_never_retried_into_another_answer(self, inject):
        async def body():
            w = await _world(files=1)
            waits = []
            await _inject(w, w["file_ids"][0], inject)
            mon = monitor(w, sleep=await _sleep_recorder(waits),
                          policy=MonitorPolicy(max_attempts=5, backoff_base_seconds=0.1,
                                               backoff_max_seconds=0.1))
            out = await mon.run_once(principal())
            assert out["counts"]["attempts"] == 1 and out["counts"]["retries"] == 0
            assert waits == []
        run(body())

    def test_without_an_approved_threshold_an_outage_is_not_classified(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "offline")
            for _ in range(3):
                await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["outage_persistence"] == OUTAGE_UNCLASSIFIED
            assert found["state"] == FINDING_OPEN     # and never silently closed
        run(body())

    def test_an_explicit_policy_classifies_transient_then_persistent(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "offline")
            policy = MonitorPolicy(persistent_outage_after=3)
            seen = []
            for _ in range(4):
                await monitor(w, policy=policy).run_once(principal())
                found, = await _findings(w)
                seen.append((found["consecutive_observations"], found["outage_persistence"]))
            assert seen == [(1, OUTAGE_TRANSIENT), (2, OUTAGE_TRANSIENT),
                            (3, OUTAGE_PERSISTENT), (4, OUTAGE_PERSISTENT)]
            # persistent is a LABEL on the outage; it is still an outage and the
            # finding is still open
            found, = await _findings(w)
            assert found["finding_type"] == "provider_unavailable"
            assert found["availability"] == m.AVAILABILITY_PROVIDER_UNREACHABLE
            assert found["state"] == FINDING_OPEN
        run(body())

    def test_only_an_outage_carries_a_persistence_label(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w, policy=MonitorPolicy(persistent_outage_after=2)
                          ).run_once(principal())
            found, = await _findings(w)
            assert found["finding_type"] == "missing_original"
            assert found["outage_persistence"] is None
        run(body())


# ═══════════════════════════════════════════════════════════ affected records
class TestAffected:
    def test_every_canonical_group_of_affected_records_is_named(self):
        async def body():
            w = await _world(files=0)
            records = {
                m.RELATION_PROJECT: ("projects", "P-9", {"name": "Sofia"}),
                m.RELATION_OFFER: ("offers", "O-1", {"offer_no": "OF-7"}),
                m.RELATION_ACT: ("client_acts", "ACT-1", {"act_number": "14"}),
                m.RELATION_INVOICE: ("invoices", "I-1", {"invoice_no": "2026-001"}),
                m.RELATION_DELIVERY: ("deliveries", "DL-1", {"number": "DL-1"}),
                m.RELATION_DAILY_REPORT: ("daily_work_logs", "DR-1", {"date": "2026-10-04"}),
                m.RELATION_TASK: ("worker_calendar", "T-1", {"title": "pour slab"}),
                m.RELATION_DEFECT: ("missing_smr", "D-1", {"title": "crack"}),
                m.RELATION_REPAIR: ("asset_repairs", "R-1", {"title": "pump"}),
                m.RELATION_SUBCONTRACTOR: ("subcontractors", "S-1", {"name": "Sub"}),
            }
            for relation_type, (coll, rid, extra) in records.items():
                target = m.RELATION_TARGETS[relation_type]
                await w["db"][target].insert_one({"id": rid, "org_id": A, **extra})
            file_id = await _upload(
                w["access"], A, OWNER_A, "act14",
                relations=[{"relation_type": t, "record_id": rid}
                           for t, (_, rid, _) in records.items()])
            await _inject(w, file_id, "remove")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert set(found["affected_by_group"]) == {
                "projects", "offers_contracts_annexes", "acts_invoices", "deliveries",
                "daily_reports", "tasks", "defects_warranties", "assets_repairs", "other"}
            assert found["affected_record_count"] == len(records)
            assert all(r["exists"] and r["label"] for r in found["affected_records"])
            assert found["alarm_level"] == ALARM_CRITICAL
        run(body())

    def test_a_dangling_target_stays_explicit(self):
        async def body():
            w = await _world(files=1)
            await w["db"]["projects"].delete_one({"id": "P-1", "org_id": A})
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            dangling = [r for r in found["affected_records"] if r["record_id"] == "P-1"]
            assert dangling and dangling[0]["exists"] is False
            assert dangling[0]["label"] is None
            assert found["affected_record_count"] == 2      # still reported, not hidden
        run(body())

    def test_a_new_relation_refreshes_the_count_the_severity_and_the_alarm(self):
        async def body():
            w = await _world(files=0, relations_per_file=1)
            file_id = await _upload(w["access"], A, OWNER_A, "orphan")
            await _inject(w, file_id, "remove")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["affected_record_count"] == 0
            assert found["alarm_level"] == ALARM_INFORMATIONAL
            # the file is attached to two business records afterwards
            for index in (0, 1):
                await w["db"]["projects"].insert_one(
                    {"id": "PX-%d" % index, "org_id": A, "name": "late %d" % index})
                await w["reg"].add_relation(actor_id=OWNER_A, file_id=file_id,
                                            relation_type=m.RELATION_PROJECT,
                                            record_id="PX-%d" % index)
            out = await monitor(w).refresh_affected_records(principal())
            assert out["examined"] == 1 and out["updated"] == 1
            found, = await _findings(w)
            assert found["affected_record_count"] == 2
            assert found["affected_by_group"] == {"projects": ["PX-0", "PX-1"]}
            assert found["severity"] == "critical" and found["alarm_level"] == ALARM_CRITICAL
            assert found["affected_as_of"]
            event = await w["db"]["audit_events"].find_one(
                {"action": "file.integrity.finding.affected_refreshed"}, {"_id": 0})
            assert event["structured_diff"]["previous_alarm_level"] == ALARM_INFORMATIONAL
            assert event["structured_diff"]["alarm_level"] == ALARM_CRITICAL
        run(body())

    def test_a_removed_relation_lowers_the_alarm_and_the_refresh_is_idempotent(self):
        async def body():
            w = await _world(files=1, relations_per_file=2)
            file_id = w["file_ids"][0]
            await _inject(w, file_id, "remove")
            await monitor(w).run_once(principal())
            assert (await _findings(w))[0]["alarm_level"] == ALARM_CRITICAL
            await w["reg"].remove_relation(actor_id=OWNER_A, file_id=file_id,
                                           relation_type=m.RELATION_PROJECT,
                                           record_id="P-0", reason="wrong link")
            first = await monitor(w).refresh_affected_records(principal())
            assert first["updated"] == 1
            found, = await _findings(w)
            assert found["affected_record_count"] == 1
            assert found["affected_by_group"] == {"projects": ["P-1"]}
            assert found["severity"] == "high" and found["alarm_level"] == ALARM_WARNING
            second = await monitor(w).refresh_affected_records(principal())
            assert second["updated"] == 0        # nothing changed: nothing written
        run(body())

    def test_a_resolved_finding_is_not_refreshed(self):
        async def body():
            w = await _world(files=1)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w).run_once(principal())
            _repair(w, snapshot)
            await monitor(w).run_once(principal())
            out = await monitor(w).refresh_affected_records(principal())
            assert out["examined"] == 0 and out["updated"] == 0
        run(body())

    def test_the_refresh_needs_the_monitor_right(self):
        async def body():
            w = await _world(files=1)
            with pytest.raises(FileAccessDenied):
                await monitor(w).refresh_affected_records(principal(READER))
        run(body())


# ════════════════════════════════════════════════════════════ tenant isolation
class TestIsolation:
    @staticmethod
    async def _two_tenants():
        a = await _world(files=2)
        db, sysdb = a["db"], a["sysdb"]
        _, _, svc_b, reg_b, backend_b, binding_b = await _activated(
            org=B, owner=OWNER_B, db=db, sysdb=sysdb, bucket="tenant-b-bucket")
        await db["projects"].insert_one({"id": "P-B", "org_id": B, "name": "B site"})
        access_b = FileAccessService(reg_b, svc_b)
        file_b = await _upload(access_b, B, OWNER_B, "bdoc",
                               relations=[{"relation_type": m.RELATION_PROJECT,
                                           "record_id": "P-B"}])
        b = {"db": db, "sysdb": sysdb, "svc": svc_b, "reg": reg_b, "backend": backend_b,
             "binding_id": binding_b, "access": access_b, "file_ids": [file_b], "org": B}
        return a, b

    def test_two_tenants_have_their_own_claim_run_and_findings(self):
        async def body():
            a, b = await self._two_tenants()
            db, file_b = a["db"], b["file_ids"][0]
            await _inject(a, a["file_ids"][0], "remove")
            await _inject(b, file_b, "mutate")

            out_a = await monitor(a).run_once(principal(SERVICE_A, A))
            out_b = await monitor(b).run_once(principal(SERVICE_B, B))
            assert out_a["counts"]["checked"] == 2 and out_b["counts"]["checked"] == 1

            # separate control rows, separate runs, separate findings
            for collection, expected in ((MONITOR_STATE_COLLECTION, [A, B]),
                                         (MONITOR_RUNS_COLLECTION, [A, B]),
                                         (MONITOR_FINDINGS_COLLECTION, [A, B])):
                rows = await db[collection].find({}).to_list(None)
                assert sorted(r["org_id"] for r in rows) == expected, collection

            a_rows = await monitor(a).list_findings(principal(SERVICE_A, A))
            b_rows = await monitor(b).list_findings(principal(SERVICE_B, B))
            assert {r["org_id"] for r in a_rows} == {A}
            assert {r["org_id"] for r in b_rows} == {B}
            # no label, file or provider identifier of B appears in A's view
            blob = repr(a_rows)
            assert "P-B" not in blob and b["binding_id"] not in blob and file_b not in blob
        run(body())

    def test_a_cross_tenant_read_of_the_projection_is_refused(self):
        async def body():
            a, b = await self._two_tenants()
            await _inject(b, b["file_ids"][0], "remove")
            await monitor(b).run_once(principal(SERVICE_B, B))
            # tenant A's principal, through A's monitor: B's finding is unreachable
            assert await monitor(a).list_findings(principal(SERVICE_A, A)) == []
            assert await monitor(a).list_findings(
                principal(SERVICE_A, A), file_id=b["file_ids"][0]) == []
            # and B's own principal cannot borrow A's view
            with pytest.raises(FileAccessDenied) as denied:
                await monitor(a).list_findings(principal(SERVICE_B, B))
            assert denied.value.reason_code == "CROSS_TENANT"
        run(body())

    def test_one_tenants_claim_never_blocks_another(self):
        async def body():
            a, b = await self._two_tenants()
            assert await monitor(a, worker_id="w-a")._claim() is not None
            assert await monitor(b, worker_id="w-b")._claim() is not None
            states = await a["db"][MONITOR_STATE_COLLECTION].find({}).to_list(None)
            assert sorted(s["org_id"] for s in states) == [A, B]
        run(body())

    def test_the_affected_records_of_a_finding_come_from_this_tenant_only(self):
        async def body():
            a = await _world(files=0)
            # the SAME business id exists in both tenants
            for org in (A, B):
                await a["db"]["projects"].insert_one({"id": "P-SHARED", "org_id": org,
                                                      "name": "name in " + org})
            file_id = await _upload(a["access"], A, OWNER_A, "shared",
                                    relations=[{"relation_type": m.RELATION_PROJECT,
                                                "record_id": "P-SHARED"}])
            await _inject(a, file_id, "remove")
            await monitor(a).run_once(principal())
            found, = await _findings(a)
            assert [r["label"] for r in found["affected_records"]] == ["name in " + A]
            assert found["affected_record_count"] == 1
        run(body())


# ═══════════════════════════════════════════════════════════ audit and secrets
class TestAuditEvidence:
    def test_every_event_of_one_run_is_correlated_to_that_run(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            out = await monitor(w).run_once(principal())
            rows = await w["db"]["audit_events"].find(
                {"correlation_id": out["run_id"]}, {"_id": 0}).sort("sequence", 1).to_list(None)
            assert [r["action"] for r in rows] == ["file.integrity.monitor.started",
                                                   "file.integrity.finding.opened",
                                                   "file.integrity.monitor.finished"]
            assert {r["tenant_id"] for r in rows} == {A}
            assert {r["actor_type"] for r in rows} == {"system"}
            assert {r["actor_id"] for r in rows} == {SERVICE_A}
            assert {r["source_flow"] for r in rows} == {"FLOW-016"}
            assert {r["retention_class"] for r in rows} == {"R2"}
            opened = rows[1]
            assert opened["result"] == "failure"
            assert opened["entity_type"] == "file_integrity_finding"
            assert opened["related_file_ids"] == [w["file_ids"][0]]
            assert opened["structured_diff"]["finding_type"] == "missing_original"
            assert opened["structured_diff"]["alarm_level"] == ALARM_CRITICAL
            assert opened["structured_diff"]["affected_record_count"] == 2
            assert opened["idempotency_key"]
            assert rows[2]["structured_diff"]["counts"]["checked"] == 1
        run(body())

    def test_a_failed_run_is_audited_and_the_claim_is_released(self):
        async def body():
            w = await _world(files=1)

            class Exploding:
                org_id = A
                resolver = FileIntegrityService(w["reg"], w["svc"]).resolver

                async def check(self, *a, **kw):
                    raise RuntimeError("provider library blew up at https://nas/x?token=1")
            mon = monitor(w, integrity=Exploding())
            with pytest.raises(RuntimeError):
                await mon.run_once(principal())
            finished = await w["db"]["audit_events"].find_one(
                {"action": "file.integrity.monitor.finished"}, {"_id": 0})
            assert finished["result"] == "failure"
            assert finished["error_code"] == "RuntimeError"
            assert "blew up" not in repr(finished)        # the message is not stored
            assert "token=1" not in repr(finished)
            state = await w["db"][MONITOR_STATE_COLLECTION].find_one({})
            assert state["holder"] is None and state["last_status"] == "failed"
            stored = await w["db"][MONITOR_RUNS_COLLECTION].find_one({})
            assert stored["status"] == "failed" and stored["error"] == "RuntimeError"
            # the next pass can run: a crashed run never wedges the tenant
            assert (await monitor(w).run_once(principal()))["status"] == "completed"
        run(body())

    @pytest.mark.parametrize("inject", ["remove", "deny", "mutate", "replace", "offline"])
    def test_no_provider_coordinate_credential_or_token_reaches_a_finding(self, inject):
        async def body():
            w = await _world(files=1)
            location = await _inject(w, w["file_ids"][0], inject)
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            blob = repr(found)
            assert location["object_key"] not in blob
            assert location["container"] not in blob
            for marker in ("secret", "password", "token", "signature=", "x-amz-",
                           "://", "bearer"):
                assert marker not in blob.lower(), marker
            assert "%PDF" not in blob                       # no document bytes
            events = await w["db"]["audit_events"].find({}, {"_id": 0}).to_list(None)
            audit_blob = repr(events)
            for marker in ("Signature=", "X-Amz-Credential", "refresh_token", "Bearer ",
                           "%PDF"):
                assert marker not in audit_blob, marker
            from tests.w0_06b_fake_backends import SECRET_MARKERS
            for marker in SECRET_MARKERS:
                assert marker not in blob and marker not in audit_blob, marker
        run(body())

    @pytest.mark.parametrize("value", [
        {"access_token": "abc"}, {"password": "p"}, {"provider_secret": "s"},
        {"nested": [{"refresh_token": "r"}]}, {"url": "https://x/y?Signature=abc"},
        {"error": "GET https://nas.local/file?token=abc failed"},
        {"note": "Authorization: Bearer eyJ"}, {"pem": "-----BEGIN PRIVATE KEY-----"},
        {"a": {"b": {"credential": "x"}}}, ["plain", {"ciphertext": "x"}],
    ])
    def test_a_secret_like_field_or_url_is_refused_outright(self, value):
        with pytest.raises(MonitorEvidenceRefused):
            assert_no_secrets(value)

    @pytest.mark.parametrize("value", [
        {"checksum": {"algorithm": "sha256", "value": "deadbeef"}},
        {"size_bytes": 12, "provider_file_id": "obj-1", "provider_version_id": "v2"},
        {"credential_names": ["access_key"], "secret_present": True},
        {"error": "ProviderPermissionDenied: 403"}, {"availability": "missing"},
        {"finding_type": "missing_original", "alarm_level": "critical"},
    ])
    def test_ordinary_evidence_is_allowed_through(self, value):
        assert assert_no_secrets(value) is None

    def test_a_provider_error_is_capped_and_redacted(self):
        assert sanitize_error(None) is None and sanitize_error("") is None
        assert sanitize_error("  ProviderError:  503  ") == "ProviderError: 503"
        assert sanitize_error("failed for https://nas/x?token=1") == "PROVIDER_ERROR_REDACTED"
        assert len(sanitize_error("x" * 5000)) == 200


# ═════════════════════════════════════════════════════════ the read projection
class TestProjection:
    def test_the_projection_needs_its_own_read_right(self):
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            await monitor(w).run_once(principal())
            with pytest.raises(FileAccessDenied) as denied:
                await monitor(w).list_findings(principal(NO_RIGHTS))
            assert denied.value.action == ACTION_MONITOR_READ
            with pytest.raises(FileAccessDenied):
                await monitor(w).monitor_state(principal(NO_RIGHTS))
            # a read-only principal may list but may not run
            assert len(await monitor(w).list_findings(ctx(READER, A))) == 1
            with pytest.raises(FileAccessDenied):
                await monitor(w).run_once(ctx(READER, A))
        run(body())

    def test_a_confidential_file_is_hidden_from_a_caller_without_that_right(self):
        async def body():
            w = await _world(files=1)
            secret = await _upload(w["access"], A, OWNER_A, "payroll",
                                   category=m.CATEGORY_INVOICES,
                                   sensitivity=m.SENSITIVITY_CONFIDENTIAL)
            await _inject(w, w["file_ids"][0], "remove")
            await _inject(w, secret, "remove")
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_opened"] == 2
            # the service principal holds the full monitor set but no sensitivity
            # right, so the confidential file's alarm is not listed for it
            visible = await monitor(w).list_findings(principal())
            assert [r["file_id"] for r in visible] == [w["file_ids"][0]]
            # the finding still EXISTS; it is the projection that is narrower
            assert len(await _findings(w)) == 2
        run(body())

    def test_the_projection_filters_by_state_level_type_and_file(self):
        async def body():
            w = await _world(files=2)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], "remove")
            await _inject(w, w["file_ids"][1], "deny")
            await monitor(w).run_once(principal())
            mon = monitor(w)
            assert len(await mon.list_findings(principal())) == 2
            assert len(await mon.list_findings(principal(), state=FINDING_OPEN)) == 2
            assert len(await mon.list_findings(
                principal(), finding_type="missing_original")) == 1
            assert len(await mon.list_findings(principal(), file_id=w["file_ids"][1])) == 1
            # the two findings carry DIFFERENT levels, because W0-06B gives a
            # proven-missing original and an access problem different severities
            assert len(await mon.list_findings(
                principal(), alarm_level_in=[ALARM_CRITICAL])) == 1
            assert len(await mon.list_findings(
                principal(), alarm_level_in=[ALARM_WARNING])) == 1
            assert len(await mon.list_findings(
                principal(), alarm_level_in=[ALARM_CRITICAL, ALARM_WARNING])) == 2
            assert await mon.list_findings(
                principal(), alarm_level_in=[ALARM_INFORMATIONAL]) == []
            _repair(w, snapshot)
            await monitor(w).run_once(principal())
            # The missing original closes on this provider's own digest. The
            # permission finding does NOT: this backend answers `stat` with a
            # server checksum and never reads the bytes, so the access that
            # failed was never proven restored.
            resolved = await mon.list_findings(principal(), state=FINDING_RESOLVED)
            still_open = await mon.list_findings(principal(), state=FINDING_OPEN)
            assert [r["finding_type"] for r in resolved] == ["missing_original"]
            assert [r["finding_type"] for r in still_open] == ["permission_failure"]
            assert still_open[0]["resolution_blocked_reason"] == \
                "incomplete_proof:no_authorized_read"
            for bad in ({"state": "invented"}, {"alarm_level_in": ["loud"]}):
                with pytest.raises(MonitorConfigurationRefused):
                    await mon.list_findings(principal(), **bad)
        run(body())


# ════════════════════════════════════════════ C02 / defect 1 — stale worker
class _TakeoverDuringCheck:
    """An integrity service that lets another worker take the tenant MID-CALL.

    This is the interleaving the C01 review found and the C01 tests missed: the
    worker is not stopped between two database writes, it is stopped inside the
    one await that actually takes time — the provider call. Everything the
    monitor does with the result (finding, history, alarm, AuditEvent) happens
    after this returns, so this is the only place a guard can sit.
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
            await self._on_call()          # the takeover happens HERE
        return result


class TestStaleWorkerSideEffects:
    """A worker that lost its claim writes NOTHING — not even a finding."""

    def test_a_takeover_during_the_provider_call_blocks_every_write(self):
        async def body():
            w = await _world(files=1, relations_per_file=2)
            await _inject(w, w["file_ids"][0], "remove")
            rescuer = monitor(w, worker_id="w-2")
            taken = {}

            async def take_over():
                # B's claim becomes possible and B takes it, while A is still
                # inside the provider call.
                await w["db"][MONITOR_STATE_COLLECTION].update_one(
                    {"holder": "w-1"},
                    {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
                taken["lease"] = await rescuer._claim()
                assert taken["lease"] is not None

            inner = FileIntegrityService(w["reg"], w["svc"])
            doomed = monitor(w, worker_id="w-1",
                             integrity=_TakeoverDuringCheck(inner, on_call=take_over))
            with pytest.raises(MonitorLeaseLost):
                await doomed.run_once(principal())

            # NOTHING of A's reached the tenant: no finding, no history, no
            # alarm, no finding AuditEvent, and no advanced checkpoint.
            assert await _findings(w) == []
            for action in ("file.integrity.finding.opened",
                           "file.integrity.finding.observed",
                           "file.integrity.finding.resolved",
                           "file.integrity.finding.reopened"):
                assert await w["db"]["audit_events"].count_documents(
                    {"action": action}) == 0, action
            runs = await w["db"][MONITOR_RUNS_COLLECTION].find({}, {"_id": 0}).to_list(None)
            assert len(runs) == 1
            assert runs[0]["counts"]["checked"] == 0
            assert runs[0]["processed_location_ids"] == []
            assert runs[0]["status"] == "running"      # A never closed it either
            # the check itself DID happen and is audited: that is the truth
            assert len(await _monitor_check_events(w)) == 1
            # and B, the rightful owner, can still finish the work properly
            await rescuer._abandon_claim(taken["lease"])
            out = await rescuer.run_once(principal(), run_id=runs[0]["id"])
            assert out["status"] == "completed" and out["counts"]["findings_opened"] == 1
            found, = await _findings(w)
            assert found["finding_type"] == "missing_original"
            assert found["fence"] == out["fence"]
        run(body())

    def test_an_expired_claim_blocks_writes_even_with_no_takeover(self):
        """Nobody has taken over yet, but anyone MAY — so writing is the hazard."""
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")

            async def expire():
                await w["db"][MONITOR_STATE_COLLECTION].update_one(
                    {"holder": "w-1"},
                    {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})

            inner = FileIntegrityService(w["reg"], w["svc"])
            doomed = monitor(w, worker_id="w-1",
                             integrity=_TakeoverDuringCheck(inner, on_call=expire))
            with pytest.raises(MonitorLeaseLost):
                await doomed.run_once(principal())
            assert await _findings(w) == []
            assert await w["db"]["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"}) == 0
        run(body())

    def test_a_takeover_mid_run_stops_the_walk_before_the_second_item(self):
        async def body():
            w = await _world(files=4)
            for file_id in w["file_ids"]:
                await _inject(w, file_id, "remove")
            rescuer = monitor(w, worker_id="w-2")

            async def take_over():
                await w["db"][MONITOR_STATE_COLLECTION].update_one(
                    {"holder": "w-1"},
                    {"$set": {"expires_at": "2000-01-01T00:00:00.000000+00:00"}})
                assert await rescuer._claim() is not None

            inner = FileIntegrityService(w["reg"], w["svc"])
            # the first item is committed normally; the takeover lands during
            # the SECOND provider call
            doomed = monitor(w, worker_id="w-1",
                             integrity=_TakeoverDuringCheck(inner, on_call=take_over,
                                                            calls_before=1))
            with pytest.raises(MonitorLeaseLost):
                await doomed.run_once(principal())
            # exactly one finding — the item A committed while it still held
            rows = await _findings(w)
            assert len(rows) == 1
            opened = await w["db"]["audit_events"].count_documents(
                {"action": "file.integrity.finding.opened"})
            assert opened == 1
            runs = await w["db"][MONITOR_RUNS_COLLECTION].find({}, {"_id": 0}).to_list(None)
            assert runs[0]["counts"]["checked"] == 1
            assert len(runs[0]["processed_location_ids"]) == 1
        run(body())

    def test_a_stale_worker_cannot_overwrite_a_newer_owners_finding(self):
        """The fence on the finding itself, not just the cursor."""
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            # the rightful owner records the finding at a high fence
            owner = monitor(w, worker_id="w-new")
            for _ in range(3):            # claim/release cycles push the fence up
                held = await owner._claim()
                assert held is not None
                await owner._abandon_claim(held)
            out = await owner.run_once(principal())
            found, = await _findings(w)
            high_fence = found["fence"]
            assert high_fence == out["fence"] and high_fence >= 4

            # a straggler from fence 1 tries to write the same finding
            stale = monitor(w, worker_id="w-old")
            lease = _Lease(holder="w-old", fence=1, expires_at="")
            run_row = await w["db"][MONITOR_RUNS_COLLECTION].find_one({}, {"_id": 0})
            result = await _result_for(w, w["file_ids"][0])
            with pytest.raises(MonitorLeaseLost):
                await stale._observe(principal(), run_row, lease, _Counts(),
                                     await w["reg"].primary_location(w["file_ids"][0], 1),
                                     result, "missing_original", "critical")
            after, = await _findings(w)
            assert after["fence"] == high_fence           # untouched
            assert after["occurrences"] == found["occurrences"]
            assert after["transitions"] == found["transitions"]
        run(body())

    def test_the_fence_guard_still_accepts_the_current_owner(self):
        """The guard must not block the worker that legitimately holds the claim."""
        async def body():
            w = await _world(files=1)
            await _inject(w, w["file_ids"][0], "remove")
            mon = monitor(w)
            for _ in range(4):                 # four honest consecutive passes
                out = await mon.run_once(principal())
                assert out["status"] == "completed"
            found, = await _findings(w)
            assert found["occurrences"] == 4
            assert found["fence"] == out["fence"]
            assert [t["transition"] for t in found["transitions"]] == [
                TRANSITION_OPENED] + [TRANSITION_OBSERVED] * 3
        run(body())


# ════════════════════════════════════════ C02 / defect 2 — fail-closed proof
class TestFailClosedResolutionProof:
    """The three C01 counterexamples, each reproduced and each now refused."""

    #: `ok`, complete and matching — the shape every case below weakens.
    COMPLETE = {"ok": True, "availability": m.AVAILABILITY_AVAILABLE,
                "method": "read_and_hash",
                "expected": {"checksum": {"algorithm": "sha256", "value": "aa"},
                             "size_bytes": 10, "provider_file_id": "o1",
                             "provider_version_id": "v1"},
                "observed": {"checksum": {"algorithm": "sha256", "value": "aa"},
                             "size_bytes": 10, "provider_file_id": "o1",
                             "provider_version_id": "v1"}}

    def test_counterexample_a_permission_failure_on_a_stat_derived_digest(self):
        """A provider-reported digest comes from `stat`, which is not a read."""
        stat_only = dict(self.COMPLETE, method="server_checksum")
        assert resolution_proof("permission_failure", stat_only) == (
            False, "incomplete_proof:no_authorized_read")
        for method in ("none", "size_only", None):
            assert resolution_proof("permission_failure", dict(
                self.COMPLETE, method=method)) == (
                    False, "incomplete_proof:no_authorized_read")
        # only bytes actually read close it
        assert resolution_proof("permission_failure", self.COMPLETE) == (
            True, "authorized_content_read_succeeded")

    def test_counterexample_b_provider_unavailable_with_nothing_compared(self):
        """`available` can come back having compared nothing at all."""
        nothing = dict(self.COMPLETE, method="none",
                       observed={"checksum": None, "size_bytes": None,
                                 "provider_file_id": None, "provider_version_id": None})
        assert resolution_proof("provider_unavailable", nothing) == (
            False, "incomplete_proof:no_content_comparison")
        assert resolution_proof("provider_unavailable", dict(
            self.COMPLETE, method="size_only")) == (
                False, "incomplete_proof:no_content_comparison")
        # a complete verification does close it, on either content method
        for method in ("server_checksum", "read_and_hash"):
            assert resolution_proof("provider_unavailable",
                                    dict(self.COMPLETE, method=method)) == (
                True, "provider_verification_succeeded")

    def test_counterexample_c_checksum_mismatch_without_the_observed_size(self):
        """The canonical size is known, so a verdict that did not see it is not proof."""
        no_size = dict(self.COMPLETE,
                       observed=dict(self.COMPLETE["observed"], size_bytes=None))
        assert resolution_proof("checksum_mismatch", no_size) == (
            False, "incomplete_proof:no_observed_size")
        no_sum = dict(self.COMPLETE,
                      observed=dict(self.COMPLETE["observed"], checksum=None))
        assert resolution_proof("checksum_mismatch", no_sum) == (
            False, "incomplete_proof:no_observed_checksum")
        # and with no canonical checksum on file there is nothing to close against
        unrecorded = dict(self.COMPLETE,
                          expected=dict(self.COMPLETE["expected"], checksum=None))
        assert resolution_proof("checksum_mismatch", unrecorded) == (
            False, "incomplete_proof:no_checksum_comparison")
        assert resolution_proof("checksum_mismatch", self.COMPLETE) == (
            True, "canonical_checksum_and_size_match")

    @pytest.mark.parametrize("finding_type", sorted(PROOFS))
    def test_no_finding_type_closes_on_an_incomplete_observation(self, finding_type):
        """One rule for all five: what the record expects must be observed."""
        for weakened in (
                dict(self.COMPLETE, method="none"),
                dict(self.COMPLETE, method="size_only"),
                dict(self.COMPLETE,
                     observed=dict(self.COMPLETE["observed"], checksum=None)),
                dict(self.COMPLETE,
                     observed=dict(self.COMPLETE["observed"], size_bytes=None))):
            proven, reason = resolution_proof(finding_type, weakened)
            if finding_type == "external_change":
                # identity, not content, is what this type turns on
                continue
            assert proven is False, (finding_type, weakened["method"])
            assert reason.startswith("incomplete_proof:")

    def test_missing_also_needs_the_observed_size_and_checksum(self):
        for observed, reason in (
                (dict(self.COMPLETE["observed"], size_bytes=None),
                 "incomplete_proof:no_observed_size"),
                (dict(self.COMPLETE["observed"], checksum=None),
                 "incomplete_proof:no_observed_checksum"),
                (dict(self.COMPLETE["observed"], size_bytes=99),
                 "incomplete_proof:size_still_differs")):
            assert resolution_proof("missing_original",
                                    dict(self.COMPLETE, observed=observed)) == (False, reason)

    def test_a_permission_finding_is_not_closed_by_a_stat_only_provider(self):
        """End to end, on a real adapter that answers with its own digest."""
        async def body():
            w = await _world(files=1, kind=m.PROVIDER_S3_COMPATIBLE)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], "deny")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["finding_type"] == "permission_failure"
            _repair(w, snapshot)                 # access really is back
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 0
            found, = await _findings(w)
            assert found["state"] == FINDING_OPEN
            assert found["resolution"] is None
            assert found["resolution_blocked_reason"] == \
                "incomplete_proof:no_authorized_read"
            # the provider IS healthy again — the result is `available`
            assert (await _result_for(w, w["file_ids"][0]))["ok"] is True
        run(body())

    def test_a_permission_finding_closes_on_a_provider_that_reads(self):
        async def body():
            w = await _world(files=1, kind=m.PROVIDER_SYNOLOGY_NAS)
            snapshot = _snapshot(w)
            await _inject(w, w["file_ids"][0], "deny")
            await monitor(w).run_once(principal())
            assert (await _findings(w))[0]["finding_type"] == "permission_failure"
            _repair(w, snapshot)
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_resolved"] == 1
            found, = await _findings(w)
            assert found["state"] == FINDING_RESOLVED
            assert found["resolution"]["reason"] == "authorized_content_read_succeeded"
            assert found["resolution"]["method"] == "read_and_hash"
        run(body())


# ═══════════════════════════════════ C02 / defect 3 — projection authorization
class TestProjectionScope:
    """Tenant, project, module and sensitivity — all four, before disclosure."""

    @staticmethod
    async def _two_projects():
        """One alarm on project P-0 + P-1, one on P-1 only, one on no project."""
        w = await _world(files=0, relations_per_file=2)
        for index in (0, 1):
            await w["db"]["projects"].insert_one(
                {"id": "P-%d" % index, "org_id": A, "name": "site %d" % index})
        await w["db"]["invoices"].insert_one(
            {"id": "INV-9", "org_id": A, "invoice_no": "2026-009"})
        shared = await _upload(w["access"], A, OWNER_A, "shared", relations=[
            {"relation_type": m.RELATION_PROJECT, "record_id": "P-0"},
            {"relation_type": m.RELATION_PROJECT, "record_id": "P-1"},
            {"relation_type": m.RELATION_INVOICE, "record_id": "INV-9"}])
        other = await _upload(w["access"], A, OWNER_A, "otherproj", relations=[
            {"relation_type": m.RELATION_PROJECT, "record_id": "P-1"}])
        orphan = await _upload(w["access"], A, OWNER_A, "orphan")
        for file_id in (shared, other, orphan):
            await _inject(w, file_id, "remove")
        out = await monitor(w).run_once(principal())
        assert out["counts"]["findings_opened"] == 3
        return w, {"shared": shared, "other": other, "orphan": orphan}

    def test_a_project_scoped_caller_cannot_ask_for_the_whole_tenant(self):
        async def body():
            w, _ = await self._two_projects()
            with pytest.raises(FileAccessDenied) as denied:
                await monitor(w).list_findings(ctx(PM_P0, A))
            assert denied.value.reason_code == "SCOPE_MISMATCH"
            assert denied.value.action == ACTION_MONITOR_READ
        run(body())

    def test_a_project_scoped_caller_cannot_ask_for_another_project(self):
        async def body():
            w, _ = await self._two_projects()
            with pytest.raises(FileAccessDenied) as denied:
                await monitor(w).list_findings(ctx(PM_P0, A), project_id="P-1")
            assert denied.value.reason_code == "SCOPE_MISMATCH"
        run(body())

    def test_a_project_scoped_caller_sees_only_its_own_project_narrowed(self):
        async def body():
            w, files = await self._two_projects()
            rows = await monitor(w).list_findings(ctx(PM_P0, A), project_id="P-0")
            # only the alarm that touches P-0; not P-1's and not the orphan's
            assert [r["file_id"] for r in rows] == [files["shared"]]
            found = rows[0]
            # the ALARM is intact: type, severity, level, state, total weight
            assert found["finding_type"] == "missing_original"
            assert found["alarm_level"] == ALARM_CRITICAL
            assert found["affected_record_count"] == 3
            # but only P-0's record is disclosed — P-1's label and the invoice
            # number are withheld, not guessed into this project
            assert [r["record_id"] for r in found["affected_records"]] == ["P-0"]
            assert found["affected_by_group"] == {"projects": ["P-0"]}
            assert found["disclosure"] == {"scope": "project", "project_id": "P-0",
                                           "affected_records_withheld": 2,
                                           "provider_identifiers": False}
            blob = repr(found)
            assert "P-1" not in blob and "INV-9" not in blob
            assert "2026-009" not in blob and "site 1" not in blob
            # and no provider identifier reaches a project-scoped caller
            for field in ("provider_binding_id", "provider_kind", "location_id",
                          "evidence"):
                assert field not in found, field
            assert w["binding_id"] not in blob
        run(body())

    def test_a_company_scoped_caller_sees_the_whole_finding(self):
        async def body():
            w, files = await self._two_projects()
            rows = await monitor(w).list_findings(ctx(READER, A))
            assert len(rows) == 3
            shared = [r for r in rows if r["file_id"] == files["shared"]][0]
            assert shared["disclosure"] == {"scope": "company", "project_id": None,
                                            "affected_records_withheld": 0,
                                            "provider_identifiers": True}
            assert shared["affected_record_count"] == 3
            assert len(shared["affected_records"]) == 3
            assert shared["provider_binding_id"] == w["binding_id"]
            assert shared["provider_kind"] == KIND and shared["location_id"]
            assert shared["evidence"]["availability"] == m.AVAILABILITY_MISSING
            # a company caller may still narrow the view itself
            narrowed = await monitor(w).list_findings(ctx(READER, A), project_id="P-1")
            assert sorted(r["file_id"] for r in narrowed) == sorted(
                [files["shared"], files["other"]])
            assert all(r["disclosure"]["scope"] == "company" for r in narrowed)
            assert all(r["provider_binding_id"] == w["binding_id"] for r in narrowed)
        run(body())

    def test_a_module_restricted_grant_is_refused_outright(self):
        async def body():
            w, _ = await self._two_projects()
            with pytest.raises(FileAccessDenied) as denied:
                await monitor(w).list_findings(ctx(MODULE_READER, A))
            assert denied.value.reason_code == "MODULE_NOT_ALLOWED"
            assert denied.value.action == ACTION_MONITOR_READ
            # the same restriction applies to the tenant-wide monitor state
            with pytest.raises(FileAccessDenied) as state_denied:
                await monitor(w).monitor_state(ctx(MODULE_READER, A))
            assert state_denied.value.reason_code == "MODULE_NOT_ALLOWED"
            # and the refusal is an audited security event, not a silent empty list
            events = await w["db"]["audit_events"].find(
                {"action": "file.access.denied", "error_code": "MODULE_NOT_ALLOWED"},
                {"_id": 0}).to_list(None)
            assert len(events) == 2
            assert {e["retention_class"] for e in events} == {"R3"}
            assert {e["tenant_id"] for e in events} == {A}
            assert events[0]["structured_diff"]["module_probe"] == MODULE_PROBE
        run(body())

    def test_an_unrestricted_grant_beside_a_module_restricted_one_still_works(self):
        async def body():
            w, _ = await self._two_projects()
            rows = await monitor(w).list_findings(ctx(BOTH_GRANTS, A))
            assert len(rows) == 3
            assert all(r["disclosure"]["scope"] == "company" for r in rows)
            assert await monitor(w).monitor_state(ctx(BOTH_GRANTS, A)) is not None
        run(body())

    def test_a_project_scoped_caller_cannot_read_the_tenant_wide_monitor_state(self):
        async def body():
            w, _ = await self._two_projects()
            with pytest.raises(FileAccessDenied) as denied:
                await monitor(w).monitor_state(ctx(PM_P0, A))
            assert denied.value.reason_code == "SCOPE_MISMATCH"
        run(body())

    def test_the_project_scope_denial_is_audited_with_the_requested_scope(self):
        async def body():
            w, _ = await self._two_projects()
            with pytest.raises(FileAccessDenied):
                await monitor(w).list_findings(ctx(PM_P0, A), project_id="P-1")
            event = await w["db"]["audit_events"].find_one(
                {"action": "file.access.denied", "error_code": "SCOPE_MISMATCH"},
                {"_id": 0})
            assert event["structured_diff"]["scope_type"] == "project"
            assert event["structured_diff"]["scope_id"] == "P-1"
            assert event["retention_class"] == "R3"
        run(body())

    def test_sensitivity_still_narrows_a_project_scoped_view(self):
        """All four dimensions compose; none replaces another."""
        async def body():
            w = await _world(files=0)
            await w["db"]["projects"].insert_one(
                {"id": "P-0", "org_id": A, "name": "site 0"})
            payroll = await _upload(w["access"], A, OWNER_A, "payroll",
                                    category=m.CATEGORY_INVOICES,
                                    sensitivity=m.SENSITIVITY_CONFIDENTIAL,
                                    relations=[{"relation_type": m.RELATION_PROJECT,
                                                "record_id": "P-0"}])
            plain = await _upload(w["access"], A, OWNER_A, "plain",
                                  relations=[{"relation_type": m.RELATION_PROJECT,
                                              "record_id": "P-0"}])
            for file_id in (payroll, plain):
                await _inject(w, file_id, "remove")
            out = await monitor(w).run_once(principal())
            assert out["counts"]["findings_opened"] == 2
            rows = await monitor(w).list_findings(ctx(PM_P0, A), project_id="P-0")
            assert [r["file_id"] for r in rows] == [plain]
            assert payroll not in {r["file_id"] for r in rows}
            assert len(await _findings(w)) == 2      # both still recorded
        run(body())

    def test_a_cross_tenant_caller_is_still_refused_at_every_scope(self):
        async def body():
            w, _ = await self._two_projects()
            for kwargs in ({}, {"project_id": "P-0"}):
                with pytest.raises(FileAccessDenied) as denied:
                    await monitor(w).list_findings(principal(SERVICE_B, B), **kwargs)
                assert denied.value.reason_code == "CROSS_TENANT"
        run(body())

    def test_only_a_relation_that_targets_projects_counts_as_a_project(self):
        """A site is not a project: that mapping is a business rule, not ours."""
        from app.files.monitoring import PROJECT_RELATION_TYPES
        assert PROJECT_RELATION_TYPES == {m.RELATION_PROJECT, m.RELATION_SUB_PROJECT}
        assert {m.RELATION_TARGETS[r] for r in PROJECT_RELATION_TYPES} == {"projects"}
        assert m.RELATION_TARGETS[m.RELATION_SITE] == "sites"
        assert m.RELATION_SITE not in PROJECT_RELATION_TYPES

        async def body():
            w = await _world(files=0)
            await w["db"]["sites"].insert_one({"id": "P-0", "org_id": A, "name": "yard"})
            # a SITE whose id collides with the project the caller is scoped to
            file_id = await _upload(w["access"], A, OWNER_A, "sitedoc", relations=[
                {"relation_type": m.RELATION_SITE, "record_id": "P-0"}])
            await _inject(w, file_id, "remove")
            await monitor(w).run_once(principal())
            found, = await _findings(w)
            assert found["affected_by_group"] == {"projects": ["P-0"]}
            # ...is still not disclosed to a project-scoped caller, because the
            # id belongs to `sites`, not to `projects`
            assert await monitor(w).list_findings(ctx(PM_P0, A), project_id="P-0") == []
        run(body())
