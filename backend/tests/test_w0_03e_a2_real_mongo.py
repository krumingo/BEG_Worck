"""
W0-03E-A2 / C01 — the membership collision and provenance matrix on a REAL MongoDB.

The in-memory double cannot prove index behaviour, driver semantics or the
document order a real server returns, and the A1 defect was precisely about
WHICH document a tenant-blind query finds first. So the same worlds run against
a fresh scratch database on a local server that ``W0_03_REAL_MONGO_URL`` names.
The URL is refused unless it is loopback (W0-03C ``check_local``); every
database is created with a random ``w003c_realmongo_`` name and dropped after
the test. Never Atlas, NAS, production or a real BEG database.

Each test first asserts that a tenant-blind ``find_one({"id": ...})`` really
does return tenant B's copy on this server — the precondition that makes the
collision real — and only then that A is denied.

Run:  W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:<port> \
      pytest tests/test_w0_03e_a2_real_mongo.py -v --noconftest
"""
import pytest

from app.tenancy import project_team as pt
from app.tenancy.data_access import TenantData, assigned_project_ids, is_project_member
from tests.test_w0_03c_real_mongo import _refusal, scratch
from tests.test_w0_03e_a2_http_authorization import (
    PID, SM_A, SM_B, SM_ID, _probe, _client, _row, _world,
)
from tests.test_w0_03e_legacy_migration import ORG_A, ORG_B

pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")

ROLE = pt.ROLE_SITE_MANAGER


def _t(db, org):
    return TenantData.for_user(db, {"id": SM_ID, "org_id": org})


async def _assert_b_wins_a_blind_lookup(db):
    """The precondition: on this server a tenant-blind lookup finds B's copy."""
    for coll, rid in (("projects", PID), ("users", SM_ID)):
        doc = await db[coll].find_one({"id": rid})
        assert doc is not None and doc["org_id"] == ORG_B, (coll, doc)


def test_a_b_only_row_authorizes_nothing_on_a_real_server():
    async def body(db, _name):
        await _world(db, [_row(org=ORG_B)])
        await _assert_b_wins_a_blind_lookup(db)
        user_a = {"id": SM_ID, "org_id": ORG_A}
        # the A1 helpers the protected modules call
        assert await assigned_project_ids(_t(db, ORG_A), user_a) == []
        assert await is_project_member(_t(db, ORG_A), user_a, PID) is False
        assert await is_project_member(_t(db, ORG_A), user_a, PID, ROLE) is False
        # the relation's own accessors
        assert await pt.member_row(_t(db, ORG_A), SM_ID, PID) is None
        assert await pt.project_rows(_t(db, ORG_A), [PID]) == []
        assert await pt.active_member_count(_t(db, ORG_A), PID) == 0
        # B, which wrote the row, keeps its own access
        assert await pt.is_member(_t(db, ORG_B), SM_ID, PID, ROLE) is True
        return True
    assert scratch(body) is True


def test_an_ownerless_row_authorizes_neither_tenant_on_a_real_server():
    async def body(db, _name):
        await _world(db, [_row(org=None, rid="t-ownerless")])
        await _assert_b_wins_a_blind_lookup(db)
        for org in (ORG_A, ORG_B):
            assert await pt.assigned_project_ids(_t(db, org), SM_ID) == []
            assert await pt.is_member(_t(db, org), SM_ID, PID, ROLE) is False
        # the row is really there — it simply owns nothing
        assert await db.project_team.count_documents({}) == 1
        return True
    assert scratch(body) is True


def test_a_proven_row_authorizes_only_its_own_tenant_on_a_real_server():
    async def body(db, _name):
        await _world(db, [_row(org=ORG_B, rid="t-b"), _row(org=ORG_A, rid="t-a")])
        await _assert_b_wins_a_blind_lookup(db)
        assert (await pt.member_row(_t(db, ORG_A), SM_ID, PID))["id"] == "t-a"
        assert (await pt.member_row(_t(db, ORG_B), SM_ID, PID))["id"] == "t-b"
        for org in (ORG_A, ORG_B):
            assert await pt.assigned_project_ids(_t(db, org), SM_ID) == [PID]
        return True
    assert scratch(body) is True


@pytest.mark.parametrize("rows,expect_a,expect_b", [
    ((_row(org=ORG_B),), False, True),
    ((_row(org=None, rid="t-own"),), False, False),
    ((_row(org=ORG_A, rid="t-a"),), True, False),
    ((_row(org=ORG_B, rid="t-b"), _row(org=ORG_A, rid="t-a")), True, True),
])
def test_the_http_matrix_on_a_real_server(monkeypatch, rows, expect_a, expect_b):
    """The actual routes, over the real driver, for every provenance shape."""
    async def body(db, _name):
        await _world(db, rows)
        await _assert_b_wins_a_blind_lookup(db)
        async with _client(monkeypatch, db, SM_A) as c:
            await _probe(c, expect_a, is_tenant_a=True)
        async with _client(monkeypatch, db, SM_B) as c:
            await _probe(c, expect_b, is_tenant_a=False)
        return True
    assert scratch(body) is True


def test_a_write_on_a_real_server_is_stamped_and_leaves_b_untouched():
    async def body(db, _name):
        await _world(db, [_row(org=ORG_B, rid="t-b"), _row(org=ORG_A, rid="t-a")])
        before_b = await db.project_team.find({"org_id": ORG_B}, {"_id": 0}).to_list(None)
        row = await pt.add_member(_t(db, ORG_A), member_id="new-1", project_id=PID,
                                  user_id="w-a", role_in_project="Technician")
        assert row["org_id"] == ORG_A
        stored = await db.project_team.find_one({"id": "new-1"}, {"_id": 0})
        assert stored["org_id"] == ORG_A
        assert await pt.is_member(_t(db, ORG_A), "w-a", PID) is True
        assert await pt.is_member(_t(db, ORG_B), "w-a", PID) is False
        after_b = await db.project_team.find({"org_id": ORG_B}, {"_id": 0}).to_list(None)
        assert after_b == before_b, "B's rows must be byte-for-byte unchanged"
        return True
    assert scratch(body) is True


def test_the_tenant_bound_indexes_serve_the_membership_query_on_a_real_server():
    """The (tenant, project, user) index exists and is the one the query uses."""
    async def body(db, _name):
        await _world(db, [_row(org=ORG_A, rid="t-a")])
        await db.project_team.create_index([("org_id", 1), ("project_id", 1), ("user_id", 1)])
        plan = await db.command({
            "explain": {"find": "project_team",
                        "filter": {"org_id": ORG_A, "project_id": PID, "user_id": SM_ID}},
            "verbosity": "queryPlanner"})
        winning = str(plan["queryPlanner"]["winningPlan"])
        assert "IXSCAN" in winning, winning
        assert "org_id" in winning, winning
        return True
    assert scratch(body) is True


def test_the_provenance_dry_run_on_a_real_server_writes_nothing():
    from scripts import w0_03e_a2_project_team_provenance as dry

    async def body(db, name):
        await _world(db, [_row(org=None, rid="o1"), _row(org=ORG_A, rid="a1"),
                          _row(org=ORG_B, rid="b1")])
        system = db.client[name + "_system"]
        try:
            await system.tenant_registry.insert_one({
                "id": "tenant-a", "legacy_org_id": ORG_A, "database_name": db.name,
                "status": "active"})
            # the source holds A's and B's records -> not a single-tenant source
            report = await dry.build_report(db, system)
            assert report["provenance"]["proven"] is False
            assert report["provenance"]["reason"] == "MULTI_TENANT_DATA_IN_SOURCE"
            assert report["backfill_plan"] == []
            assert report["counts"]["total"] == 3
            assert report["counts"]["unresolved"] == 1       # the ownerless row
            assert report["dq_pending_mapping"][
                "can_represent_unresolved_provenance"] is False
            # nothing was written: the ownerless row is still ownerless
            assert "org_id" not in await db.project_team.find_one({"id": "o1"}, {"_id": 0})
            assert await db.md_pending_mapping.count_documents({}) == 0
            # ...so authorization is unchanged by the dry run: each tenant is a
            # member through its OWN stamped row (a1 / b1) and the ownerless o1
            # contributes to neither.
            for org in (ORG_A, ORG_B):
                assert await pt.is_member(_t(db, org), SM_ID, PID, ROLE) is True
                assert (await pt.member_row(_t(db, org), SM_ID, PID))["id"] != "o1"
            return True
        finally:
            await db.client.drop_database(system.name)
    assert scratch(body) is True


def test_a_single_tenant_real_source_is_proven_and_plans_only_its_own_rows():
    from scripts import w0_03e_a2_project_team_provenance as dry

    async def body(db, name):
        # ONE tenant only in this database
        await db.projects.insert_one({"id": PID, "org_id": ORG_A, "status": "Active"})
        await db.users.insert_one({"id": SM_ID, "org_id": ORG_A})
        await db.project_team.insert_one(_row(org=None, rid="o1"))
        system = db.client[name + "_system"]
        try:
            await system.tenant_registry.insert_one({
                "id": "tenant-a", "legacy_org_id": ORG_A, "database_name": db.name,
                "status": "active"})
            report = await dry.build_report(db, system)
            assert report["provenance"]["proven"] is True
            assert report["provenance"]["org_id"] == ORG_A
            assert report["backfill_plan"] == [{"id": "o1", "org_id": ORG_A}]
            # the PLAN exists; the row is still not stamped, so still denied
            assert "org_id" not in await db.project_team.find_one({"id": "o1"}, {"_id": 0})
            assert await pt.is_member(_t(db, ORG_A), SM_ID, PID, ROLE) is False
            return True
        finally:
            await db.client.drop_database(system.name)
    assert scratch(body) is True
