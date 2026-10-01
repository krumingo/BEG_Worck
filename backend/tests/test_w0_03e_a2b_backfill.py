"""
W0-03E-A2B / C01 — the one-time BEG legacy ownership backfill.

Phase 1 (fail-closed precondition), Phase 2 (inventory, no ASSUMED SAFE),
Phase 3 (dry run, approval, idempotent/resumable execute, reconciliation,
rollback) and Phase 6 (zero ownerless) over an in-process database. The same
library is driven against a real MongoDB by
``tests/test_w0_03e_a2b_two_tenant_gate.py``.

The legacy fixture puts ownerless rows — in all three ownerless forms
(missing / ``null`` / ``""``) — into EVERY org-keyed collection of
``app.tenancy.ownership.ORG_KEYED``, so every Issue #38 family is exercised,
and bound rows beside them so "never touch a bound row" is checked too.

Run:  pytest tests/test_w0_03e_a2b_backfill.py -v --noconftest
"""
import asyncio
import copy
import uuid

import pytest

from app.tenancy import legacy_backfill as lb
from app.tenancy import ownership as own

#: Not a constant the code knows: every test can use any id/name (Phase 1:
#: "do not hard-code UUID/name"). The default fixture uses this one.
BEG_ORG = "0b1e9f4a-2c11-4b7e-9a53-6d0c8f2e7a01"
BEG_NAME = "BUILDING EXPRESS GROUP"
PLATFORM_ORG = "9f0d2a77-1111-4c1b-8e2e-platform0001"
OTHER_ORG = "5c3a6d10-7e2f-4f61-b0a4-other0000001"
APPROVER = "krum"


def run(coro):
    return asyncio.run(coro)


def mock_dbs(name="w003e_a2b_disposable_op"):
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()
    return client[name], client[name.replace("_op", "_sys")]


class TrustedApproval:
    """A trusted approval for THIS exact subject (test double of W0-07)."""
    name = "test"

    def __init__(self, approver=APPROVER, tamper=None):
        self.approver, self.tamper, self.seen = approver, tamper, []

    async def verify(self, *, approval_id, subject):
        self.seen.append(dict(subject))
        subj = dict(subject)
        if self.tamper:
            subj.update(self.tamper)
        return lb.ApprovalEvidence(approval_id, subject["tenant_id"], subj, self.approver,
                                   "2026-10-01T00:00:00+00:00", self.name)


# ------------------------------------------------------------------ the world
#: A meaningful legacy record per identity-bearing family. ``id`` values are
#: the ones the two-tenant gate later collides on.
LEGACY_RECORDS = {
    "projects": [{"id": "P-L", "code": "BEG-P-L", "name": "BEG-PROJECT-L", "status": "Active"}],
    "project_team": [{"id": "T-L", "project_id": "P-L", "user_id": "U-L",
                      "role_in_project": "SiteManager", "active": True}],
    "users": [{"id": "U-T", "email": "tech@beg.test", "first_name": "BEG-TECH",
               "last_name": "L", "role": "Technician", "is_active": True}],
    "persons": [{"id": "PE-L", "first_name": "BEG-PERSON", "last_name": "L"}],
    "companies": [{"id": "CO-L", "name": "BEG-COMPANY-L", "eik": "111111111"}],
    "clients": [{"id": "C-L", "companyName": "BEG-CLIENT-L", "type": "company"}],
    "counterparties": [{"id": "CP-L", "name": "BEG-CP-L", "type": "company"}],
    "subcontractors": [{"id": "S-L", "name": "BEG-SUB-L"}],
    "invoices": [{"id": "I-L", "project_id": "P-L", "invoice_no": "BEG-INV-L",
                  "direction": "Issued", "status": "Sent", "total": 1111.11,
                  "counterparty_name": "BEG-CP-L", "invoice_date": "2026-03-01",
                  "date": "2026-03-01", "currency": "BGN"}],
    "invoice_lines": [{"id": "IL-L", "invoice_id": "I-L", "description": "BEG-LINE-L"}],
    "offers": [{"id": "O-L", "project_id": "P-L", "offer_no": "BEG-OFF-L", "status": "Draft",
                "lines": [], "currency": "BGN", "created_at": "2026-03-01"}],
    "finance_payments": [{"id": "PAY-L", "amount": 1111.11, "direction": "Inflow",
                          "reference": "BEG-PAY-L", "date": "2026-03-02"}],
    "payment_allocations": [{"id": "AL-L", "payment_id": "PAY-L", "invoice_id": "I-L",
                             "amount_allocated": 1111.11}],
    "advances": [{"id": "ADV-L", "user_id": "U-T", "amount": 50}],
    "warehouses": [{"id": "W-L", "name": "BEG-WAREHOUSE-L", "code": "BEG-W"}],
    "location_nodes": [{"id": "LOC-L", "project_id": "P-L", "name": "BEG-LOC-L"}],
    "items": [{"id": "IT-L", "name": "BEG-ITEM-L"}],
    "material_requests": [{"id": "MR-L", "project_id": "P-L"}],
    "work_types": [{"id": "WT-L", "name": "BEG-WORKTYPE-L"}],
    "smr_groups": [{"id": "SG-L", "project_id": "P-L", "name": "BEG-SMR-L"}],
    "asset_item_types": [{"id": "AT-L", "name": "BEG-ASSET-TYPE-L"}],
    "asset_items": [{"id": "AI-L", "name": "BEG-ASSET-L"}],
    "asset_units": [{"id": "AU-L", "name": "BEG-UNIT-L"}],
    "worker_calendar": [{"id": "WC-L", "user_id": "U-T", "date": "2026-03-01"}],
    "media_files": [{"id": "MF-L", "filename": "BEG-FILE-L.jpg"}],
    "audit_logs": [{"id": "AU-LOG-L", "action": "legacy", "entity_type": "project"}],
}


async def seed_legacy(op, sysdb, *, org=BEG_ORG, name=BEG_NAME, registry=True,
                      primary=True, status="active", platform=True, bound_only=False):
    """The current single-tenant BEG legacy dataset, before A2B.

    * ``organizations``: BEG (+ the platform system org);
    * Tenant Registry: BEG as the W0-01 primary installation of THIS database,
      the platform org as a non-primary record of another database;
    * every ORG_KEYED collection: one row per ownerless form + one bound row;
    * the meaningful legacy records above, ownerless (as the legacy writers
      left them), plus the bound BEG SiteManager ``U-L`` who logs in;
    * the platform admin user and its ``SYSTEM`` security log row.
    """
    await op.organizations.insert_one({"id": org, "name": name, "slug": "beg",
                                       "created_at": "2024-01-01"})
    if platform:
        await op.organizations.insert_one({"id": PLATFORM_ORG, "name": "Platform System",
                                           "slug": own.PLATFORM_ORG_SLUG,
                                           "created_at": "2025-01-01"})
        await op.users.insert_one({"id": "platform-admin", "org_id": PLATFORM_ORG,
                                   "email": "root@platform.test", "role": "Admin",
                                   "is_platform_admin": True, "is_active": True})
        await op.audit_logs.insert_one({"id": "boot-1", "org_id": own.PLATFORM_SYSTEM_OWNER,
                                        "action": "BOOTSTRAP_CREATE_PLATFORM_ADMIN"})
    if registry:
        # The W0-01 bootstrap's record shape (scripts/w0_01_bootstrap_tenant_registry.py).
        await sysdb.tenant_registry.insert_one({
            "id": org, "name": name, "slug": "beg", "database_name": op.name,
            "is_primary_installation": primary, "status": status, "schema_version": 1,
            "migrated_from": "organizations"})
        if platform:
            await sysdb.tenant_registry.insert_one({
                "id": PLATFORM_ORG, "name": "Platform System", "slug": own.PLATFORM_ORG_SLUG,
                "database_name": "begwork_tenant_platform-system",
                "is_primary_installation": False, "status": "active"})
    for coll in sorted(own.ORG_KEYED):
        await op[coll].insert_one({"id": coll + "-bound", own.ORG_KEY: org, "marker": "BEG"})
        if bound_only:
            continue
        await op[coll].insert_one({"id": coll + "-missing", "marker": "BEG"})
        await op[coll].insert_one({"id": coll + "-null", own.ORG_KEY: None, "marker": "BEG"})
        await op[coll].insert_one({"id": coll + "-empty", own.ORG_KEY: "", "marker": "BEG"})
    if not bound_only:
        for coll, docs in LEGACY_RECORDS.items():
            for d in docs:
                await op[coll].insert_one(dict(d))
    await op.users.insert_one({"id": "U-L", own.ORG_KEY: org, "email": "sm@beg.test",
                               "first_name": "BEG-SM", "last_name": "L", "role": "SiteManager",
                               "is_active": True})
    await op.users.insert_one({"id": "A-L", own.ORG_KEY: org, "email": "admin@beg.test",
                               "first_name": "BEG-ADMIN", "last_name": "L", "role": "Admin",
                               "is_active": True})
    return op


async def snapshot(db):
    out = {}
    for name in sorted(await db.list_collection_names()):
        docs = [d async for d in db[name].find({})]
        out[name] = sorted((repr(sorted(d.items())) for d in docs))
    return out


async def world(**kw):
    op, sysdb = mock_dbs()
    await seed_legacy(op, sysdb, **kw)
    return op, sysdb


async def execute_plan(op, sysdb, key="run-1", approval=None, **kw):
    report = await lb.dry_run(op, sysdb)
    return report, await lb.execute(op, sysdb, plan_token=report["plan_token"],
                                    idempotency_key=key, actor_id=APPROVER,
                                    approval_id="APR-1",
                                    approval_verifier=approval or TrustedApproval(), **kw)


# ============================================================ Phase 1
def test_the_tenant_is_resolved_from_registry_state_only():
    async def body():
        op, sysdb = await world()
        t = await lb.prove_precondition(op, sysdb)
        assert (t.tenant_id, t.org_id, t.name) == (BEG_ORG, BEG_ORG, BEG_NAME)
        assert t.source_database == op.name
        assert PLATFORM_ORG in t.platform_owners and own.PLATFORM_SYSTEM_OWNER in t.platform_owners
    run(body())


@pytest.mark.parametrize("org,name", [(str(uuid.uuid4()), "Фирма Едно"),
                                      (str(uuid.uuid4()), "Any Operating Company")])
def test_nothing_is_hard_coded_any_single_operating_tenant_resolves(org, name):
    async def body():
        op, sysdb = await world(org=org, name=name)
        t = await lb.prove_precondition(op, sysdb)
        assert (t.tenant_id, t.name) == (org, name)
        report = await lb.dry_run(op, sysdb)
        assert report["executable"], report["blockers"]
    run(body())


async def _refusal(mutate):
    op, sysdb = await world()
    await mutate(op, sysdb)
    with pytest.raises(lb.PreconditionFailed) as exc:
        await lb.prove_precondition(op, sysdb)
    report = await lb.dry_run(op, sysdb)
    assert report["executable"] is False and report["blockers"] == [exc.value.code]
    return exc.value.code


async def _no_registry(op, sysdb):
    await sysdb.tenant_registry.delete_many({"id": BEG_ORG})


async def _shared(op, sysdb):
    await sysdb.tenant_registry.insert_one({"id": OTHER_ORG, "database_name": op.name,
                                            "status": "active"})


async def _not_primary(op, sysdb):
    await sysdb.tenant_registry.update_one({"id": BEG_ORG},
                                           {"$set": {"is_primary_installation": False}})


async def _suspended(op, sysdb):
    await sysdb.tenant_registry.update_one({"id": BEG_ORG}, {"$set": {"status": "suspended"}})


async def _second_tenant_elsewhere(op, sysdb):
    await sysdb.tenant_registry.insert_one({"id": OTHER_ORG, "database_name": "begwork_b",
                                            "status": "active"})


async def _second_org_in_source(op, sysdb):
    await op.organizations.insert_one({"id": OTHER_ORG, "name": "Second", "slug": "second"})


async def _registry_org_missing(op, sysdb):
    await op.organizations.delete_many({"id": BEG_ORG})


async def _platform_claims(op, sysdb):
    await sysdb.tenant_registry.delete_many({})
    await sysdb.tenant_registry.insert_one({"id": PLATFORM_ORG, "database_name": op.name,
                                            "status": "active", "is_primary_installation": True})


@pytest.mark.parametrize("mutate,code", [
    (_no_registry, "NO_REGISTRY_RECORD"),
    (_shared, "SHARED_SOURCE_DATABASE"),
    (_not_primary, "NOT_THE_LEGACY_INSTALLATION"),
    (_suspended, "TENANT_NOT_OPERATIONAL"),
    (_second_tenant_elsewhere, "NOT_EXACTLY_ONE_OPERATIONAL_TENANT"),
    (_second_org_in_source, "SECOND_ORGANIZATION_IN_SOURCE"),
    (_registry_org_missing, "REGISTRY_ORG_NOT_IN_SOURCE"),
    (_platform_claims, "PLATFORM_TENANT_NOT_ELIGIBLE"),
])
def test_the_precondition_fails_closed_with_one_exact_code(mutate, code):
    assert run(_refusal(mutate)) == code


def test_a_failed_precondition_writes_nothing_and_execute_refuses():
    async def body():
        op, sysdb = await world()
        await _second_org_in_source(op, sysdb)
        before = await snapshot(op), await snapshot(sysdb)
        with pytest.raises(lb.PreconditionFailed):
            await lb.execute(op, sysdb, plan_token="x", idempotency_key="k", actor_id="a",
                             approval_id="A", approval_verifier=TrustedApproval())
        assert (await snapshot(op), await snapshot(sysdb)) == before
    run(body())


# ============================================================ Phase 2
def test_the_inventory_covers_every_family_and_counts_every_ownerless_form():
    async def body():
        op, sysdb = await world()
        report = await lb.dry_run(op, sysdb)
        rows = {r["collection"]: r for r in report["rows"]}
        assert set(own.ORG_KEYED) <= set(rows)
        families = {r["family"] for r in report["rows"]}
        assert set(own.FAMILIES) <= families
        for coll in own.ORG_KEYED:
            r = rows[coll]
            extra = len(LEGACY_RECORDS.get(coll, ()))
            bound = 1 + (2 if coll == "users" else 0)
            assert (r["ownerless"], r["bound"], r["conflicting"]) == (3 + extra, bound, 0), r
            assert r["action"] == lb.ACTION_BACKFILL
        assert rows["users"]["platform"] == 1 and rows["audit_logs"]["platform"] == 1
        assert rows["organizations"]["bound"] == 1 and rows["organizations"]["platform"] == 1
        t = report["totals"]
        assert t["authorization_ownerless"] == rows["project_team"]["ownerless"] + rows[
            "users"]["ownerless"]
        assert t["conflicting"] == 0 and report["executable"] and report["blockers"] == []
        for r in report["rows"]:
            assert r["action"] in (lb.ACTION_NONE, lb.ACTION_BACKFILL), r
    run(body())


def test_the_dry_run_writes_nothing_and_its_token_ignores_storage_order():
    async def body():
        op, sysdb = await world()
        before = await snapshot(op), await snapshot(sysdb)
        first = await lb.dry_run(op, sysdb)
        assert (await snapshot(op), await snapshot(sysdb)) == before
        assert first["read_only"] is True and first["executed"] is False
        # same data, reversed insertion order
        op2, sys2 = mock_dbs()
        for name in await op.list_collection_names():
            docs = [d async for d in op[name].find({}, {"_id": 0})]
            for d in reversed(docs):
                await op2[name].insert_one(d)
        for d in [d async for d in sysdb.tenant_registry.find({}, {"_id": 0})]:
            await sys2.tenant_registry.insert_one(d)
        second = await lb.dry_run(op2, sys2)
        assert [(r["collection"], r["ownerless"], r["bound"]) for r in first["rows"]] == [
            (r["collection"], r["ownerless"], r["bound"]) for r in second["rows"]]
    run(body())


def test_the_read_only_handle_refuses_every_write():
    op, _ = mock_dbs()
    ro = lb.ReadOnlyDb(op)
    for method in ("insert_one", "update_many", "delete_many", "aggregate", "drop"):
        with pytest.raises(PermissionError):
            getattr(ro["projects"], method)


async def _foreign_row(op, sysdb):
    await op.invoices.insert_one({"id": "I-X", own.ORG_KEY: OTHER_ORG, "total": 5})


async def _malformed_owner(op, sysdb):
    await op.projects.insert_one({"id": "P-X", own.ORG_KEY: 42})


async def _contradiction(op, sysdb):
    await op.payment_allocations.insert_one({"id": "AL-X", own.TENANT_ID_KEY: OTHER_ORG})


async def _platform_owner_elsewhere(op, sysdb):
    await op.invoices.insert_one({"id": "I-P", own.ORG_KEY: PLATFORM_ORG})


async def _unclassified(op, sysdb):
    await op.mystery_legacy_stuff.insert_one({"id": "z"})


async def _ownerless_canonical(op, sysdb):
    await op.md_person.insert_one({"id": "md-1", "display_name": "x"})


@pytest.mark.parametrize("mutate,blocker", [
    (_foreign_row, lb.ACTION_BLOCKED_CONFLICT),
    (_malformed_owner, lb.ACTION_BLOCKED_CONFLICT),
    (_contradiction, lb.ACTION_BLOCKED_CONFLICT),
    (_platform_owner_elsewhere, lb.ACTION_BLOCKED_CONFLICT),
    (_unclassified, lb.ACTION_BLOCKED_UNCLASSIFIED),
    (_ownerless_canonical, lb.ACTION_BLOCKED_CANONICAL),
])
def test_conflicting_or_unclassified_data_blocks_the_whole_migration(mutate, blocker):
    async def body():
        op, sysdb = await world()
        await mutate(op, sysdb)
        report = await lb.dry_run(op, sysdb)
        assert report["executable"] is False and blocker in report["blockers"]
        assert report["precondition"]["proven"] is True
        before = await snapshot(op)
        with pytest.raises(lb.BackfillRefused) as exc:
            await lb.execute(op, sysdb, plan_token=report["plan_token"], idempotency_key="k",
                             actor_id=APPROVER, approval_id="A", approval_verifier=TrustedApproval())
        assert exc.value.code == "BLOCKED"
        assert await snapshot(op) == before, "a blocked migration must write nothing"
        sample = [r for r in report["rows"] if r["action"] == blocker][0]
        assert sample["conflicting"] or sample["ownerless"] or sample["total"]
    run(body())


# ============================================================ Phase 3
@pytest.mark.parametrize("approval_id,verifier,code", [
    (None, None, "APPROVAL_REQUIRED"),
    ("APR-1", None, "APPROVAL_REQUIRED"),                       # default: W0-07 not started
    ("APR-1", TrustedApproval(tamper={"plan_token": "other"}), "APPROVAL_REQUIRED"),
])
def test_execute_without_a_verified_approval_writes_nothing(approval_id, verifier, code):
    async def body():
        op, sysdb = await world()
        report = await lb.dry_run(op, sysdb)
        before = await snapshot(op), await snapshot(sysdb)
        with pytest.raises(lb.BackfillRefused) as exc:
            await lb.execute(op, sysdb, plan_token=report["plan_token"], idempotency_key="k",
                             actor_id=APPROVER, approval_id=approval_id,
                             approval_verifier=verifier)
        assert exc.value.code == code
        assert (await snapshot(op), await snapshot(sysdb)) == before
    run(body())


def test_a_stale_plan_is_refused():
    async def body():
        op, sysdb = await world()
        report = await lb.dry_run(op, sysdb)
        await op.projects.insert_one({"id": "P-NEW-OWNERLESS"})
        with pytest.raises(lb.StalePlan):
            await lb.execute(op, sysdb, plan_token=report["plan_token"], idempotency_key="k",
                             actor_id=APPROVER, approval_id="A", approval_verifier=TrustedApproval())
    run(body())


def test_execute_backfills_every_ownerless_row_and_touches_nothing_else():
    async def body():
        op, sysdb = await world()
        before = {c: {d["id"]: d async for d in op[c].find({}, {"_id": 0})}
                  for c in await op.list_collection_names()}
        report, result = await execute_plan(op, sysdb)
        assert result["status"] == lb.STATUS_COMPLETED and result["replayed"] is False
        rec = result["reconciliation"]
        assert rec["ok"] and rec["journaled"] == rec["planned"] == report["totals"]["ownerless"]
        t = rec["totals_after"]
        assert (t["ownerless"], t["conflicting"], t["authorization_ownerless"]) == (0, 0, 0)
        after = {c: {d["id"]: d async for d in op[c].find({}, {"_id": 0})}
                 for c in await op.list_collection_names()
                 if not c.startswith("audit_") or c == "audit_logs"}
        for coll, docs in before.items():
            for rid, old in docs.items():
                new = after[coll][rid]
                if coll in own.ORG_KEYED and own.is_missing_owner(old.get(own.ORG_KEY)):
                    assert new[own.ORG_KEY] == BEG_ORG
                    rest_old = {k: v for k, v in old.items() if k != own.ORG_KEY}
                    rest_new = {k: v for k, v in new.items() if k != own.ORG_KEY}
                    assert rest_old == rest_new, "only org_id may change (business ids kept)"
                else:
                    assert new == old, "a bound/platform/root row must be untouched"
        # project_team: the authorization relation is tenant-bound now
        assert await op.project_team.count_documents(own.ownerless_predicate()) == 0
        run_doc = await sysdb[lb.RUNS].find_one({"_id": result["run_id"]})
        assert run_doc["status"] == lb.STATUS_COMPLETED
        assert run_doc["approval"]["approver_id"] == APPROVER
        # canonical AuditEvents in BEG's own chain: started + completed
        from app.audit.store import verify_tenant_chain
        events = await op.audit_events.find({"tenant_id": BEG_ORG}).to_list(None)
        assert [e["structured_diff"]["phase"] for e in events] == ["started", "completed"]
        assert all(e["approval_id"] == "APR-1" and e["actor_id"] == APPROVER for e in events)
        assert (await verify_tenant_chain(op, BEG_ORG))[0] is True
        lock = await sysdb[lb.LOCKS].find_one({})
        assert lock["holder"] is None, "the lock is released"
        verified = await lb.verify_ownership(op, sysdb)
        assert verified["ok"] and verified["ownerless"] == 0
    run(body())


def test_the_same_request_is_replayed_not_reapplied():
    async def body():
        op, sysdb = await world()
        report, first = await execute_plan(op, sysdb)
        journal = await sysdb[lb.JOURNAL].count_documents({})
        snap = await snapshot(op)
        again = await lb.execute(op, sysdb, plan_token=report["plan_token"],
                                 idempotency_key="run-1", actor_id=APPROVER,
                                 approval_id="APR-1", approval_verifier=TrustedApproval())
        assert again["replayed"] is True and again["run_id"] == first["run_id"]
        assert await sysdb[lb.JOURNAL].count_documents({}) == journal
        assert await snapshot(op) == snap
        # a NEW key re-plans: there is nothing left to do, and nothing changes
        report2 = await lb.dry_run(op, sysdb)
        assert report2["totals"]["ownerless"] == 0
        second = await lb.execute(op, sysdb, plan_token=report2["plan_token"],
                                  idempotency_key="run-2", actor_id=APPROVER,
                                  approval_id="APR-2", approval_verifier=TrustedApproval())
        assert second["reconciliation"]["journaled"] == 0
    run(body())


def test_an_interrupted_run_is_resumed_by_the_same_request():
    async def body():
        op, sysdb = await world()
        report = await lb.dry_run(op, sysdb)
        kw = dict(plan_token=report["plan_token"], idempotency_key="run-1", actor_id=APPROVER,
                  approval_id="APR-1", approval_verifier=TrustedApproval(), batch_size=2)
        with pytest.raises(lb._Interrupted):
            await lb.execute(op, sysdb, _fail_after="batch:invoices", **kw)
        run_doc = await sysdb[lb.RUNS].find_one({})
        assert run_doc["status"] == lb.STATUS_INTERRUPTED
        partial = await lb.dry_run(op, sysdb)
        assert 0 < partial["totals"]["ownerless"] < report["totals"]["ownerless"]
        # a different request cannot take the interrupted lock
        with pytest.raises(lb.MigrationBusy):
            await lb.execute(op, sysdb, plan_token=partial["plan_token"],
                             idempotency_key="other", actor_id=APPROVER, approval_id="A",
                             approval_verifier=TrustedApproval())
        result = await lb.execute(op, sysdb, **kw)
        assert result["status"] == lb.STATUS_COMPLETED
        rec = result["reconciliation"]
        assert rec["journaled"] == rec["planned"] == report["totals"]["ownerless"]
        assert (await sysdb[lb.RUNS].find_one({}))["attempts"] == 2
    run(body())


def test_an_owner_set_after_planning_is_never_overwritten_and_fails_verification():
    async def body():
        op, sysdb = await world()
        report = await lb.dry_run(op, sysdb)
        kw = dict(plan_token=report["plan_token"], idempotency_key="run-1", actor_id=APPROVER,
                  approval_id="APR-1", approval_verifier=TrustedApproval())
        with pytest.raises(lb._Interrupted):
            await lb.execute(op, sysdb, _fail_after="batch:advances", **kw)
        # between the attempts, an ownerless row of a later collection gains a
        # DIFFERENT owner (a concurrent writer / a bad import)
        await op.warehouses.update_one({"id": "warehouses-missing"},
                                       {"$set": {own.ORG_KEY: OTHER_ORG}})
        with pytest.raises(lb.VerificationFailed) as exc:
            await lb.execute(op, sysdb, **kw)
        assert any("conflicting" in p for p in exc.value.detail["problems"])
        doc = await op.warehouses.find_one({"id": "warehouses-missing"})
        assert doc[own.ORG_KEY] == OTHER_ORG, "a foreign owner is never overwritten"
        run_doc = await sysdb[lb.RUNS].find_one({})
        assert run_doc["status"] == lb.STATUS_VERIFICATION_FAILED, "no silent partial success"
        failed = await op.audit_events.find_one({"error_code": "VERIFICATION_FAILED"})
        assert failed and failed["result"] == "failure"
    run(body())


def test_rollback_restores_the_exact_ownerless_forms_and_skips_changed_rows():
    async def body():
        op, sysdb = await world()
        pristine = await snapshot(op)
        _, result = await execute_plan(op, sysdb)
        # one stamped row is legitimately moved to another owner afterwards
        await op.items.update_one({"id": "items-null"}, {"$set": {own.ORG_KEY: OTHER_ORG}})
        with pytest.raises(lb.ApprovalRequired):
            await lb.rollback(op, sysdb, run_id=result["run_id"], idempotency_key="rb",
                              actor_id=APPROVER, approval_id="RB-1")
        out = await lb.rollback(op, sysdb, run_id=result["run_id"], idempotency_key="rb",
                                actor_id=APPROVER, approval_id="RB-1",
                                approval_verifier=TrustedApproval())
        assert out["skipped_owner_changed"] == 1
        for coll in ("projects", "project_team", "invoices"):
            for rid, form in (("-missing", "missing"), ("-null", None), ("-empty", "")):
                doc = await op[coll].find_one({"id": coll + rid}, {"_id": 0})
                if form == "missing":
                    assert own.ORG_KEY not in doc
                else:
                    assert doc[own.ORG_KEY] == form
            assert (await op[coll].find_one({"id": coll + "-bound"}))[own.ORG_KEY] == BEG_ORG
        assert (await op.items.find_one({"id": "items-null"}))[own.ORG_KEY] == OTHER_ORG
        # apart from that one row and the audit chain, the data is as before
        now = await snapshot(op)
        for name in pristine:
            if name in ("items",) or name.startswith("audit_"):
                continue
            assert now[name] == pristine[name], name
        again = await lb.rollback(op, sysdb, run_id=result["run_id"], idempotency_key="rb",
                                  actor_id=APPROVER, approval_id="RB-1",
                                  approval_verifier=TrustedApproval())
        assert again["replayed"] is True
        actions = [e["action"] async for e in op.audit_events.find({}, {"action": 1})]
        assert actions.count(lb.ACTION_ROLLBACK) == 1
    run(body())


def test_the_one_time_rule_can_never_run_again_once_a_second_tenant_exists():
    async def body():
        from app.tenancy.onboarding import onboard_tenant
        op, sysdb = await world()
        await execute_plan(op, sysdb)
        await onboard_tenant(op, sysdb, org_name="TEST COMPANY B", owner_email="b@b.test",
                             owner_password_hash="x", owner_first_name="B")
        with pytest.raises(lb.PreconditionFailed) as exc:
            await lb.prove_precondition(op, sysdb)
        assert exc.value.code == "SHARED_SOURCE_DATABASE"
        # an ownerless row appearing now is never inferred to be anybody's
        await op.projects.insert_one({"id": "P-AMBIGUOUS"})
        report = await lb.dry_run(op, sysdb)
        assert report["executable"] is False and report["plan_token"] is None
        verified = await lb.verify_ownership(op, sysdb)
        assert verified["ok"] is False and verified["ownerless"] == 1
    run(body())


def test_verify_ownership_reports_unknown_owners():
    async def body():
        op, sysdb = await world(bound_only=True)
        assert (await lb.verify_ownership(op, sysdb))["ok"] is True
        await op.invoices.insert_one({"id": "I-X", own.ORG_KEY: OTHER_ORG})
        out = await lb.verify_ownership(op, sysdb)
        assert out["ok"] is False and out["unknown_owner"] == 1
    run(body())


# ============================================================ CLI safety
def test_the_cli_refuses_remote_and_non_disposable_targets(capsys):
    from scripts import w0_03e_a2b_beg_backfill as cli
    for url in ("mongodb+srv://x.mongodb.net", "mongodb://10.0.0.5:27017",
                "mongodb://nas.local:27017"):
        assert cli.main(["--mongo-url", url, "--db", "w003e_a2b_disposable_x",
                         "--system-db", "w003e_a2b_disposable_s"]) == cli.EXIT_REFUSED
    for flags in (["--execute"], ["--enforce"], ["--rollback"], ["--release-invariant"]):
        assert cli.main(["--mongo-url", "mongodb://127.0.0.1:1", "--db", "begwork",
                         "--system-db", "begwork_system", *flags]) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "not a disposable test database" in err and "No production" in err
