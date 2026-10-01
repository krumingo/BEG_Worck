"""
W0-03E-A1 / C01 — the central tenant-safe access layer (``app.tenancy.data_access``).

Unit-level contract of ``TenantData``: the tenant comes only from server-side
state; every read/write is scoped; a foreign tenant in a filter, insert or join
is refused; a relation absent in the tenant is ``None`` (no global, name or
fuzzy fallback); aggregation accepts only scoped joins. A and B share ids and B
is stored first, so an unscoped implementation would return B's documents.

Run:  pytest tests/test_w0_03e_a1_tenant_access.py -v --noconftest
"""
import pytest
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

from app.tenancy.data_access import (
    TenantData, TenantScopeViolation, assigned_project_ids, count_ownerless, is_project_member,
    resolve_review_token,
)
from tests.test_w0_03e_legacy_migration import run

A, B = "org-a", "org-b"


async def _db():
    db = AsyncMongoMockClient()["a1_unit"]
    for org, name in ((B, "B-SECRET"), (A, "A-own")):                  # B first
        await db.projects.insert_one({"id": "p1", "org_id": org, "name": name, "code": name})
        await db.invoice_lines.insert_one({"id": "l1", "org_id": org, "invoice_id": "i1"})
        await db.invoices.insert_one({"id": "i1", "org_id": org, "invoice_no": name})
    await db.projects.insert_one({"id": "p-only-b", "org_id": B, "name": "B-SECRET"})
    await db.projects.insert_one({"id": "p-nobody", "name": "ownerless"})
    await db.organizations.insert_one({"id": B, "name": "B-SECRET"})
    await db.organizations.insert_one({"id": A, "name": "A org"})
    return db


def t(db, org=A):
    return TenantData.for_user(db, {"id": "u", "org_id": org})


def test_the_tenant_comes_only_from_server_side_state():
    db = run(_db())
    for bad in (None, {}, {"id": "u"}, {"id": "u", "org_id": ""}, {"id": "u", "org_id": 7}):
        with pytest.raises(TenantScopeViolation):
            TenantData.for_user(db, bad)
    with pytest.raises(TenantScopeViolation):
        TenantData.for_owner_of(db, {"id": "x"})

    class Ctx:
        org_id = A
    assert TenantData.for_context(db, Ctx()).org_id == A


def test_get_returns_only_the_tenants_record_and_none_for_a_foreign_relation():
    db = run(_db())
    assert run(t(db).projects.get("p1"))["name"] == "A-own"           # B stored first
    assert run(t(db, B).projects.get("p1"))["name"] == "B-SECRET"
    assert run(t(db).projects.get("p-only-b")) is None                # no global fallback
    assert run(t(db).projects.get("p-nobody")) is None                # ownerless is not ours
    assert run(t(db).projects.get(None)) is None and run(t(db).projects.get("")) is None
    with pytest.raises(HTTPException) as exc:
        run(t(db).projects.require("p-only-b"))
    assert exc.value.status_code == 404


def test_get_many_never_returns_a_foreign_document():
    db = run(_db())
    got = run(t(db).projects.get_many(["p1", "p-only-b", "p-nobody", None, ""], {"_id": 0, "name": 1}))
    assert set(got) == {"p1"} and got["p1"]["name"] == "A-own"


def test_a_filter_naming_another_tenant_is_refused_not_rewritten():
    db = run(_db())
    for flt in ({"org_id": B}, {"tenant_id": B}):
        with pytest.raises(TenantScopeViolation):
            run(t(db).projects.find_one(flt))
        with pytest.raises(TenantScopeViolation):
            run(t(db).projects.update_one(flt, {"$set": {"x": 1}}))
    assert run(t(db).projects.count({"org_id": A})) == 1             # same tenant: fine
    assert run(t(db).projects.count()) == 1
    assert run(t(db).projects.distinct("name")) == ["A-own"]


def test_writes_are_scoped_and_never_touch_the_other_tenant():
    db = run(_db())
    run(t(db).projects.update_one({"id": "p1"}, {"$set": {"name": "A-new"}}))
    run(t(db).projects.delete_one({"id": "p-only-b"}))                 # B-only id: no-op
    assert run(db.projects.find_one({"id": "p1", "org_id": B}))["name"] == "B-SECRET"
    assert run(db.projects.find_one({"id": "p-only-b"})) is not None
    doc = {"id": "p2"}
    run(t(db).projects.insert_one(doc))
    assert doc["org_id"] == A
    with pytest.raises(TenantScopeViolation):
        run(t(db).projects.insert_one({"id": "p3", "org_id": B}))
    with pytest.raises(TenantScopeViolation):
        run(t(db).projects.insert_many([{"id": "p4"}, {"id": "p5", "org_id": B}]))


def test_aggregate_prepends_the_tenant_and_scopes_every_join():
    db = run(_db())
    tenant = t(db)
    rows = run(tenant.invoice_lines.aggregate(
        tenant.lookup("invoices", local_field="invoice_id", as_field="inv")).to_list(None))
    assert len(rows) == 1 and [i["invoice_no"] for i in rows[0]["inv"]] == ["A-own"]


@pytest.mark.parametrize("stage", [
    {"$lookup": {"from": "invoices", "localField": "invoice_id", "foreignField": "id", "as": "inv"}},
    {"$graphLookup": {"from": "projects"}}, {"$unionWith": "projects"}, {"$out": "x"},
    {"$merge": {"into": "x"}}, {"$facet": {"a": [{"$lookup": {"from": "projects"}}]}},
])
def test_aggregate_refuses_any_unscoped_cross_collection_stage(stage):
    db = run(_db())
    with pytest.raises(TenantScopeViolation):
        t(db).invoice_lines.aggregate([stage])


def test_a_lookup_built_for_another_tenant_is_refused():
    db = run(_db())
    with pytest.raises(TenantScopeViolation):
        t(db).invoice_lines.aggregate(t(db, B).lookup("invoices", "invoice_id", "inv"))
    a = t(db)
    stage, flt = a.lookup("invoices", "invoice_id", "inv")
    with pytest.raises(TenantScopeViolation):                         # join without its filter
        a.invoice_lines.aggregate([stage, {"$unwind": "$inv"}])


def test_own_organization_is_the_tenants_own():
    db = run(_db())
    assert run(t(db).own_organization({"_id": 0}))["name"] == "A org"


def test_review_token_resolves_exactly_one_owner_or_nothing():
    db = run(_db())
    run(db.offers.insert_one({"id": "o1", "org_id": A, "review_token": "tok"}))
    tenant, offer = run(resolve_review_token(db, "tok"))
    assert tenant.org_id == A and offer["id"] == "o1"
    run(db.offers.insert_one({"id": "o2", "org_id": B, "review_token": "tok"}))   # collision
    assert run(resolve_review_token(db, "tok")) == (None, None)
    run(db.offers.insert_one({"id": "o3", "review_token": "nobody"}))             # ownerless
    assert run(resolve_review_token(db, "nobody")) == (None, None)
    for bad in (None, "", 5):
        assert run(resolve_review_token(db, bad)) == (None, None)


def test_team_assignments_count_only_for_the_tenants_projects():
    db = run(_db())
    run(db.project_team.insert_one({"user_id": "s1", "project_id": "p-only-b", "active": True,
                                    "role_in_project": "SiteManager"}))
    run(db.project_team.insert_one({"user_id": "s1", "project_id": "p1", "active": True,
                                    "role_in_project": "SiteManager"}))
    user = {"id": "s1", "org_id": A}
    assert run(assigned_project_ids(t(db), user)) == ["p1"]
    assert run(is_project_member(t(db), user, "p1", "SiteManager")) is True
    assert run(is_project_member(t(db), user, "p-only-b")) is False


def test_ownerless_count_discloses_no_tenant():
    db = run(_db())
    assert run(count_ownerless(db, "projects")) == 1
