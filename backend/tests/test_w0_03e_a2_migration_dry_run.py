"""
W0-03E-A2 / C01 — the project-team provenance dry run is read-only and deterministic.

``scripts/w0_03e_a2_project_team_provenance.py`` classifies every legacy
``project_team`` row as ``PROVEN_TENANT`` or ``UNRESOLVED_PROVENANCE`` and
counts proven / unresolved / conflicting. It executes nothing: the handle it
reads through refuses every write method before the server is reached, so the
report proves by construction that it wrote nothing.

What is asserted here:

  * a provably single-tenant source, verified against the W0-01 Tenant
    Registry, is the ONLY thing that produces a backfill plan;
  * a shared, unknown, contradictory or multi-tenant source yields an empty
    plan — no guess from project id, user id, name, role or coincidence;
  * the dry run writes nothing, including the DQ/pending collection;
  * the report states the DQ-model blocker explicitly rather than inventing a
    new approval flow;
  * a non-loopback or ``mongodb+srv`` target is refused with exit code 2.

Run:  pytest tests/test_w0_03e_a2_migration_dry_run.py -v --noconftest
"""
import subprocess
import sys
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.tenancy import project_team as pt
from tests.test_w0_03e_legacy_migration import ORG_A, ORG_B, run

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
from scripts import w0_03e_a2_project_team_provenance as dry  # noqa: E402

SCRIPT = BACKEND / "scripts" / "w0_03e_a2_project_team_provenance.py"
DB_A, SHARED = "begwork_a", "begwork_shared"


def _registry(database, org_id=ORG_A, tid="tenant-a"):
    return {"id": tid, "legacy_org_id": org_id, "database_name": database,
            "status": "active", "schema_version": 1}


async def _source(name, *, orgs=(ORG_A,), rows=()):
    """A source operational database plus its system (registry) database."""
    client = AsyncMongoMockClient()
    db, system = client[name], client["begwork_system_test"]
    for org in orgs:
        await db.projects.insert_one({"id": "p1", "org_id": org, "name": "P " + org})
        await db.users.insert_one({"id": "u1", "org_id": org})
    for row in rows:
        await db.project_team.insert_one(dict(row))
    return db, system


def _row(org=None, rid="t1", project_id="p1", user_id="u1"):
    row = {"id": rid, "project_id": project_id, "user_id": user_id,
           "role_in_project": pt.ROLE_SITE_MANAGER, "active": True}
    if org is not None:
        row["org_id"] = org
    return row


# -------------------------------------------------------------- proven source
def test_a_verified_single_tenant_source_may_backfill_its_own_rows():
    db, system = run(_source(DB_A, orgs=(ORG_A,), rows=[_row(org=None, rid="o1"),
                                                        _row(org=ORG_A, rid="a1")]))
    run(system.tenant_registry.insert_one(_registry(DB_A)))
    r = run(dry.build_report(db, system))
    assert r["read_only"] is True and r["executed_migration"] is False
    assert r["provenance"]["proven"] is True
    assert r["provenance"]["org_id"] == ORG_A
    assert r["provenance"]["reason"] == "SINGLE_TENANT_SOURCE_VERIFIED"
    assert r["counts"] == {"total": 2, "stamped": 1, "proven": 2,
                           "unresolved": 0, "conflicting": 0, "backfillable": 1}
    # only the ownerless row is planned, and only to its own proven tenant
    assert r["backfill_plan"] == [{"id": "o1", "org_id": ORG_A}]


def test_the_registry_is_the_authority_not_the_data_alone():
    """Data says A, the registry says B: a contradiction is never resolved."""
    db, system = run(_source(DB_A, orgs=(ORG_A,), rows=[_row(org=None)]))
    run(system.tenant_registry.insert_one(_registry(DB_A, org_id=ORG_B, tid="tenant-b")))
    r = run(dry.build_report(db, system))
    assert r["provenance"]["proven"] is False
    assert r["provenance"]["reason"] == "REGISTRY_DATA_MISMATCH"
    assert r["backfill_plan"] == []
    assert r["counts"]["unresolved"] == 1


# ------------------------------------------------------------ unproven sources
@pytest.mark.parametrize("name,orgs,claims,reason", [
    ("unknown_db", (ORG_A,), [], "NO_REGISTRY_RECORD"),
    (SHARED, (ORG_A, ORG_B), [_registry(SHARED)], "MULTI_TENANT_DATA_IN_SOURCE"),
    (SHARED, (ORG_A,), [_registry(SHARED), _registry(SHARED, ORG_B, "tenant-b")],
     "SHARED_SOURCE_DATABASE"),
])
def test_an_unproven_source_plans_nothing(name, orgs, claims, reason):
    db, system = run(_source(name, orgs=orgs, rows=[_row(org=None, rid="o1"),
                                                    _row(org=None, rid="o2")]))
    for c in claims:
        run(system.tenant_registry.insert_one(dict(c)))
    r = run(dry.build_report(db, system))
    assert r["provenance"]["proven"] is False
    assert r["provenance"]["reason"] == reason
    assert r["backfill_plan"] == []
    assert r["counts"]["unresolved"] == 2
    assert r["counts"]["backfillable"] == 0
    assert r["reasons"][pt.ROW_NO_PROVEN_SOURCE] == 2


def test_a_contradictory_stamp_is_counted_as_conflicting_and_stays_denied():
    db, system = run(_source(DB_A, orgs=(ORG_A,), rows=[_row(org=ORG_B, rid="b1")]))
    run(system.tenant_registry.insert_one(_registry(DB_A)))
    r = run(dry.build_report(db, system))
    assert r["counts"]["conflicting"] == 1
    assert r["counts"]["unresolved"] == 1
    assert r["backfill_plan"] == []
    assert r["decisions"][0]["reason"] == pt.ROW_STAMP_CONFLICTS_WITH_SOURCE
    assert r["decisions"][0]["outcome"] == pt.PROVENANCE_UNRESOLVED


def test_the_decisions_are_deterministic_and_fully_reasoned():
    rows = [_row(org=None, rid="o2"), _row(org=None, rid="o1"), _row(org=ORG_A, rid="a1")]
    db, system = run(_source(DB_A, orgs=(ORG_A,), rows=rows))
    run(system.tenant_registry.insert_one(_registry(DB_A)))
    first = run(dry.build_report(db, system))
    second = run(dry.build_report(db, system))
    assert first["decisions"] == second["decisions"]
    assert [d["id"] for d in first["decisions"]] == ["a1", "o1", "o2"]
    assert all(d["outcome"] in pt.PROVENANCE_OUTCOMES and d["reason"]
               for d in first["decisions"])
    assert sum(first["reasons"].values()) == first["counts"]["total"]


# ------------------------------------------------------------------- read-only
def test_the_dry_run_writes_nothing_at_all():
    rows = [_row(org=None, rid="o1"), _row(org=ORG_A, rid="a1")]
    db, system = run(_source(DB_A, orgs=(ORG_A,), rows=rows))
    run(system.tenant_registry.insert_one(_registry(DB_A)))

    async def snapshot(handle, names):
        return {n: await handle[n].find({}, {"_id": 0}).to_list(None) for n in names}
    watched = ("project_team", "projects", "users", "md_pending_mapping", "audit_events")
    before = run(snapshot(db, watched))
    before_sys = run(snapshot(system, ("tenant_registry",)))
    report = run(dry.build_report(db, system))
    assert report["counts"]["total"] == 2
    assert run(snapshot(db, watched)) == before
    assert run(snapshot(system, ("tenant_registry",))) == before_sys
    # the ownerless row is STILL ownerless, so it still authorizes nobody
    stored = run(db.project_team.find_one({"id": "o1"}, {"_id": 0}))
    assert "org_id" not in stored


def test_the_read_only_handle_refuses_a_write_before_the_server():
    from scripts.w0_03e_legacy_migration_report import ReadOnlyDb
    db, _ = run(_source(DB_A))
    ro = ReadOnlyDb(db)
    for method in ("insert_one", "update_many", "delete_many", "bulk_write", "drop"):
        with pytest.raises(PermissionError):
            getattr(ro["project_team"], method)


# ------------------------------------------------- the DQ representation blocker
def test_the_report_states_the_dq_blocker_instead_of_inventing_a_flow():
    dq = dry.dq_representation()
    assert dq["can_represent_unresolved_provenance"] is False
    assert dq["collection"] == "md_pending_mapping"
    invariants = " ".join(b["invariant"] for b in dq["blockers"])
    assert "tenant_id is required" in invariants
    assert "entity_type" in invariants and "source_channel" in invariants
    assert len(dq["blockers"]) == 3
    for b in dq["blockers"]:
        assert b["refusal"] and b["why_it_blocks"]
    # the deny side does not depend on the queue
    assert "authorizes nothing" in dq["consequence"]


def test_the_pending_model_really_does_refuse_an_unowned_row():
    """The blocker is checked against the real model, not asserted in prose."""
    from app.master_data import models, pending
    from app.master_data.models import MasterDataInvalid
    with pytest.raises(MasterDataInvalid):
        pending.build_pending(tenant_id="", entity_type=models.ENTITY_PERSON,
                              raw_value="x", source_channel=pending.SOURCE_IMPORT,
                              created_by="report")
    assert "project_team_membership" not in models.ENTITY_TYPES
    assert not (pending.PENDING_SOURCES & {"legacy", "migration"})


# ------------------------------------------------------------------- the target
@pytest.mark.parametrize("url", ["mongodb+srv://cluster.example/",
                                 "mongodb://10.0.0.5:27017",
                                 "mongodb://nas.local:27017"])
def test_a_non_local_target_is_refused_with_exit_code_two(url):
    r = subprocess.run([sys.executable, str(SCRIPT), "--mongo-url", url, "--db", "x"],
                       cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "refused" in r.stderr


def test_project_team_is_not_its_own_provenance_evidence():
    """The question is who owns its rows, so they cannot vote on the answer."""
    assert "project_team" not in dry.TENANT_KEYED_COLLECTIONS
