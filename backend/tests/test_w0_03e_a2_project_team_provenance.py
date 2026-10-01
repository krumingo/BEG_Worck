"""
W0-03E-A2 / C01 — ``project_team`` as a tenant-bound authorization relation.

The A1 review blocked A1 on a deterministic counterexample this module pins
down. One shared legacy database holds tenants A and B. Project id ``p1``
exists in BOTH. User id ``u1`` exists in BOTH. The ONLY team row in the
database was written by B, with the SAME project id, the SAME user id and the
SAME role, and it was inserted FIRST. On the A1 head, A's user ``u1`` got
``assigned_project_ids() == ['p1']`` and
``is_project_member(..., 'p1', 'SiteManager') is True``, because resolving the
project in A *after* reading an ownerless row never establishes who wrote it.

A2's rule: the row itself carries the tenant, every authorization read carries
``org_id`` + ``project_id`` + ``user_id`` (+ role), and an ownerless or foreign
row grants exactly zero. This module proves, at unit level:

  * the A/B collision matrix — B's row gives no A access, in both directions;
  * an A-proven row authorizes A and ONLY A;
  * an ownerless legacy row is DENY everywhere;
  * a forged tenant (a caller-supplied ``org_id``) is refused, not honoured;
  * a new write is stamped from the server-resolved tenant and cannot be
    pointed at another tenant's project;
  * an authorization question missing the tenant, the project or the user is a
    refusal, not a lucky answer;
  * the migration dry run classifies by PROVEN SOURCE only, counts
    proven/unresolved/conflicting, and an unresolved row stays DENY.

Run:  pytest tests/test_w0_03e_a2_project_team_provenance.py -v --noconftest
"""
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.tenancy import project_team as pt
from app.tenancy.data_access import (
    TenantData, TenantScopeViolation, assigned_project_ids, is_project_member,
)
from tests.test_w0_03e_legacy_migration import run

A, B = "org-a", "org-b"
ROLE = pt.ROLE_SITE_MANAGER


def t(db, org=A):
    """The tenant view a route gets: the session user's own server-side org."""
    return TenantData.for_user(db, {"id": "u1", "org_id": org})


async def _collision_db(team_rows=()):
    """The hardest world: p1 and u1 exist in BOTH tenants, B written first."""
    db = AsyncMongoMockClient()["a2_unit"]
    for org, mark in ((B, "B-SECRET"), (A, "A-own")):                  # B first
        await db.projects.insert_one({"id": "p1", "org_id": org, "name": mark, "code": mark})
        await db.users.insert_one({"id": "u1", "org_id": org, "first_name": mark})
    await db.projects.insert_one({"id": "p-only-b", "org_id": B, "name": "B-SECRET"})
    for row in team_rows:
        await db.project_team.insert_one(dict(row))
    return db


def _row(org=None, project_id="p1", user_id="u1", role=ROLE, rid="t1", active=True):
    row = {"id": rid, "project_id": project_id, "user_id": user_id,
           "role_in_project": role, "active": active}
    if org is not None:
        row["org_id"] = org
    return row


# ---------------------------------------------------------- A/B collision matrix
def test_b_only_row_gives_no_a_access_even_when_project_user_and_role_collide():
    """The exact A1 counterexample. B's row is the only one in the database."""
    db = run(_collision_db([_row(org=B)]))
    user_a = {"id": "u1", "org_id": A}
    # A's project p1 really does exist — that is what fooled A1.
    assert run(t(db).projects.get("p1"))["name"] == "A-own"
    assert run(pt.assigned_project_ids(t(db), "u1")) == []
    assert run(pt.is_member(t(db), "u1", "p1")) is False
    assert run(pt.is_member(t(db), "u1", "p1", ROLE)) is False
    assert run(pt.member_row(t(db), "u1", "p1")) is None
    # the A1 entry points the protected modules call, same answer
    assert run(assigned_project_ids(t(db), user_a)) == []
    assert run(is_project_member(t(db), user_a, "p1")) is False
    assert run(is_project_member(t(db), user_a, "p1", ROLE)) is False
    # ...and B, who DID write the row, still has its own access
    assert run(pt.assigned_project_ids(t(db, B), "u1")) == ["p1"]
    assert run(pt.is_member(t(db, B), "u1", "p1", ROLE)) is True


def test_the_collision_is_symmetric_an_a_only_row_gives_no_b_access():
    db = run(_collision_db([_row(org=A)]))
    assert run(pt.is_member(t(db, B), "u1", "p1", ROLE)) is False
    assert run(pt.assigned_project_ids(t(db, B), "u1")) == []
    assert run(pt.is_member(t(db), "u1", "p1", ROLE)) is True


def test_a_proven_row_authorizes_only_a_when_both_tenants_have_one():
    db = run(_collision_db([_row(org=B, rid="tb"), _row(org=A, rid="ta")]))
    for org in (A, B):
        assert run(pt.is_member(t(db, org), "u1", "p1", ROLE)) is True
        assert run(pt.assigned_project_ids(t(db, org), "u1")) == ["p1"]
    # each tenant sees exactly its OWN row, never the other's
    assert run(pt.member_row(t(db), "u1", "p1"))["id"] == "ta"
    assert run(pt.member_row(t(db, B), "u1", "p1"))["id"] == "tb"


def test_an_ownerless_legacy_row_authorizes_nobody():
    """The UNRESOLVED_PROVENANCE case at runtime: no tenant, so no access."""
    db = run(_collision_db([_row(org=None)]))
    for org in (A, B):
        assert run(pt.assigned_project_ids(t(db, org), "u1")) == []
        assert run(pt.is_member(t(db, org), "u1", "p1")) is False
        assert run(pt.is_member(t(db, org), "u1", "p1", ROLE)) is False
        assert run(pt.member_row(t(db, org), "u1", "p1")) is None
        assert run(pt.project_rows(t(db, org), ["p1"])) == []
        assert run(pt.project_member_ids(t(db, org), "p1")) == []
        assert run(pt.user_rows(t(db, org), "u1", active_only=False)) == []
        assert run(pt.active_member_count(t(db, org), "p1")) == 0


def test_an_empty_or_malformed_tenant_stamp_is_not_a_tenant():
    db = run(_collision_db([_row(org=""), _row(org=None, rid="t2"),
                            _row(org=7, rid="t3")]))
    for org in (A, B):
        assert run(pt.assigned_project_ids(t(db, org), "u1")) == []
        assert run(pt.is_member(t(db, org), "u1", "p1", ROLE)) is False


def test_a_row_on_a_project_of_another_tenant_grants_nothing():
    db = run(_collision_db([_row(org=A, project_id="p-only-b")]))
    assert run(pt.assigned_project_ids(t(db), "u1")) == []
    assert run(pt.is_member(t(db), "u1", "p-only-b")) is False
    assert run(pt.active_member_count(t(db), "p-only-b")) == 0


# -------------------------------------------------------------- forged tenant
def test_a_caller_supplied_tenant_is_refused_not_honoured():
    db = run(_collision_db([_row(org=B)]))
    rel = t(db).collection(pt.COLLECTION)
    for forged in ({"org_id": B}, {"tenant_id": B},
                   {"project_id": "p1", "user_id": "u1", "org_id": B}):
        with pytest.raises(TenantScopeViolation):
            run(rel.find_one(forged))
    with pytest.raises(TenantScopeViolation):
        run(rel.insert_one(_row(org=B, rid="forged")))
    # the forged write never happened
    assert run(db.project_team.count_documents({"id": "forged"})) == 0


def test_a_body_tenant_cannot_ride_in_on_a_new_row():
    db = run(_collision_db())
    for key in ("org_id", "tenant_id"):
        with pytest.raises(TenantScopeViolation):
            pt.build_row(t(db), member_id="m", project_id="p1", user_id="u1",
                         role_in_project=ROLE, extra={key: B})


def test_an_authorization_question_missing_a_key_is_refused():
    db = run(_collision_db([_row(org=A)]))
    tenant = t(db)
    for project_id in (None, "", 5):
        with pytest.raises(pt.ProjectTeamAuthorizationIncomplete):
            run(pt.is_member(tenant, "u1", project_id))
    for user_id in (None, "", {}):
        with pytest.raises(pt.ProjectTeamAuthorizationIncomplete):
            run(pt.is_member(tenant, user_id, "p1"))
    for not_a_tenant in (None, "org-a", {"org_id": A}):
        with pytest.raises(pt.ProjectTeamAuthorizationIncomplete):
            run(pt.is_member(not_a_tenant, "u1", "p1"))


def test_the_membership_filter_always_names_user_and_project():
    flt = pt.membership_filter("u1", "p1", ROLE)
    assert flt == {"project_id": "p1", "user_id": "u1", "active": True,
                   "role_in_project": ROLE}
    # the tenant key is NOT here: TenantData.scoped() appends it last, so a
    # caller can neither forget it nor override it
    assert "org_id" not in flt and "tenant_id" not in flt


# --------------------------------------------------------------------- writes
def test_a_new_row_is_stamped_from_the_server_resolved_tenant():
    db = run(_collision_db())
    row = run(pt.add_member(t(db), member_id="m1", project_id="p1", user_id="u1",
                            role_in_project=ROLE))
    assert row["org_id"] == A
    stored = run(db.project_team.find_one({"id": "m1"}, {"_id": 0}))
    assert stored["org_id"] == A
    assert run(pt.is_member(t(db), "u1", "p1", ROLE)) is True
    assert run(pt.is_member(t(db, B), "u1", "p1", ROLE)) is False


def test_a_member_cannot_be_added_to_another_tenants_project():
    db = run(_collision_db())
    with pytest.raises(TenantScopeViolation):
        run(pt.add_member(t(db), member_id="m2", project_id="p-only-b",
                          user_id="u1", role_in_project=ROLE))
    assert run(db.project_team.count_documents({})) == 0


def test_deactivation_touches_only_the_tenants_own_rows():
    db = run(_collision_db([_row(org=B, rid="tb"), _row(org=A, rid="ta")]))
    run(pt.deactivate_member(t(db), member_id="tb", project_id="p1"))   # B's row, as A
    assert run(db.project_team.find_one({"id": "tb"}, {"_id": 0}))["active"] is True
    run(pt.deactivate_member(t(db), member_id="ta", project_id="p1"))
    assert run(db.project_team.find_one({"id": "ta"}, {"_id": 0}))["active"] is False
    assert run(pt.is_member(t(db, B), "u1", "p1", ROLE)) is True        # B unharmed


def test_deactivating_a_project_leaves_the_other_tenant_alone():
    db = run(_collision_db([_row(org=B, rid="tb"), _row(org=A, rid="ta")]))
    run(pt.deactivate_project(t(db), "p1"))
    assert run(pt.is_member(t(db), "u1", "p1", ROLE)) is False
    assert run(pt.is_member(t(db, B), "u1", "p1", ROLE)) is True


# ---------------------------------------------------------------- provenance
REG_A = {"id": "tenant-a", "legacy_org_id": A, "database_name": "begwork_a",
         "status": "active"}
REG_B = {"id": "tenant-b", "legacy_org_id": B, "database_name": "begwork_b",
         "status": "active"}


def test_a_single_tenant_source_verified_against_the_registry_is_proven():
    p = pt.verify_source_provenance("begwork_a", [REG_A], [A])
    assert p.proven is True and p.org_id == A
    assert p.reason == "SINGLE_TENANT_SOURCE_VERIFIED"


def test_every_unproven_source_shape_is_refused():
    cases = {
        "NO_REGISTRY_RECORD": ("begwork_a", [], [A]),
        "SHARED_SOURCE_DATABASE": ("shared", [dict(REG_A, database_name="shared"),
                                              dict(REG_B, database_name="shared")], [A, B]),
        "MULTI_TENANT_DATA_IN_SOURCE": ("begwork_a", [REG_A], [A, B]),
        "REGISTRY_DATA_MISMATCH": ("begwork_a", [REG_A], [B]),
        "REGISTRY_ORG_UNRESOLVED": ("begwork_a", [{"database_name": "begwork_a"}], [A]),
    }
    for reason, (database, claims, observed) in cases.items():
        p = pt.verify_source_provenance(database, claims, observed)
        assert p.proven is False, reason
        assert p.org_id is None, reason
        assert p.reason == reason, (reason, p.reason)


def test_an_empty_source_is_not_proven_multi_tenant_but_is_still_single_tenant():
    """No data yet, one registry claim: nothing contradicts the claim."""
    p = pt.verify_source_provenance("begwork_a", [REG_A], [])
    assert p.proven is True and p.org_id == A


def test_rows_are_classified_by_proven_source_only():
    proven = pt.verify_source_provenance("begwork_a", [REG_A], [A])
    unproven = pt.verify_source_provenance("shared", [], [A, B])
    ownerless, stamped_a, stamped_b = _row(org=None), _row(org=A, rid="ta"), _row(org=B, rid="tb")

    # proven single-tenant source -> its own ownerless rows may be backfilled
    d = pt.classify_row(ownerless, proven)
    assert d == {"outcome": pt.PROVENANCE_PROVEN,
                 "reason": pt.ROW_PROVEN_SINGLE_TENANT_SOURCE,
                 "org_id": A, "backfill": A}
    # unproven source -> never, whatever the ids look like
    d = pt.classify_row(ownerless, unproven)
    assert d == {"outcome": pt.PROVENANCE_UNRESOLVED,
                 "reason": pt.ROW_NO_PROVEN_SOURCE, "org_id": None, "backfill": None}
    # an already-stamped row is never re-stamped
    assert pt.classify_row(stamped_a, proven)["backfill"] is None
    assert pt.classify_row(stamped_a, proven)["reason"] == pt.ROW_ALREADY_STAMPED
    # a stamp its own source cannot have written is a contradiction -> fail closed
    d = pt.classify_row(stamped_b, proven)
    assert d["outcome"] == pt.PROVENANCE_UNRESOLVED
    assert d["reason"] == pt.ROW_STAMP_CONFLICTS_WITH_SOURCE
    assert d["backfill"] is None


def test_the_dry_run_counts_proven_unresolved_and_conflicting():
    proven = pt.verify_source_provenance("begwork_a", [REG_A], [A])
    rows = [_row(org=None, rid="o1"), _row(org=None, rid="o2"),
            _row(org=A, rid="a1"), _row(org=B, rid="b1")]
    out = pt.classify_rows(rows, proven)
    assert out["counts"] == {"total": 4, "stamped": 1, "proven": 3,
                             "unresolved": 1, "conflicting": 1, "backfillable": 2}
    assert [d["id"] for d in out["decisions"]] == ["a1", "b1", "o1", "o2"]  # deterministic

    shared = pt.verify_source_provenance("shared", [], [A, B])
    out = pt.classify_rows(rows, shared)
    assert out["counts"] == {"total": 4, "stamped": 2, "proven": 2,
                             "unresolved": 2, "conflicting": 0, "backfillable": 0}
    assert out["reasons"][pt.ROW_NO_PROVEN_SOURCE] == 2


def test_an_unresolved_row_still_denies_after_the_dry_run():
    """The dry run writes nothing, so the row stays ownerless and stays denied."""
    db = run(_collision_db([_row(org=None)]))
    shared = pt.verify_source_provenance("shared", [], [A, B])
    out = pt.classify_rows(run(db.project_team.find({}, {"_id": 0}).to_list(None)), shared)
    assert out["counts"]["unresolved"] == 1 and out["counts"]["backfillable"] == 0
    for org in (A, B):
        assert run(pt.is_member(t(db, org), "u1", "p1", ROLE)) is False


def test_provenance_never_guesses_from_ids_names_roles_or_coincidence():
    """Two tenants, identical ids and role, one ownerless row: no winner."""
    db = run(_collision_db([_row(org=None)]))
    rows = run(db.project_team.find({}, {"_id": 0}).to_list(None))
    # two registry records claim the database -> shared source, nothing proven
    shared = pt.verify_source_provenance("shared_legacy", [REG_A, REG_B], [A, B])
    assert shared.proven is False and shared.reason == "SHARED_SOURCE_DATABASE"
    assert all(d["backfill"] is None for d in pt.classify_rows(rows, shared)["decisions"])
    # one claim, but the data in it belongs to two tenants -> also nothing proven
    mixed = pt.verify_source_provenance("shared_legacy",
                                        [dict(REG_A, database_name="shared_legacy")], [A, B])
    assert mixed.proven is False and mixed.reason == "MULTI_TENANT_DATA_IN_SOURCE"
    assert all(d["backfill"] is None for d in pt.classify_rows(rows, mixed)["decisions"])
