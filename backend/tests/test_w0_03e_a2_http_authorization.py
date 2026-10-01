"""
W0-03E-A2 / C01 — the A/B membership collision over the ACTUAL HTTP routes.

Helpers alone are not the proof. This module drives the real FastAPI routes
(httpx ASGI transport) as a **SiteManager** — the role whose access is decided
by a ``project_team`` row rather than by a tenant-wide Admin role — through the
project-team routes, the finance invoice list/detail, offers list/detail, the
reports/export projections and the A1 protected access paths.

The world is ONE shared legacy database holding tenants A and B. Project id
``p-shared`` exists in BOTH. User id ``sm-1`` exists in BOTH. The team row is
written by **B** first, with the SAME project id, the SAME user id and the SAME
role. On the A1 head that row authorized A's SiteManager on A's project. Here
every route must answer 403/404/empty for A, and B must keep its own access.

Then the matrix is repeated with an **ownerless** row (the
``UNRESOLVED_PROVENANCE`` case) and with a **proven A** row, so the same routes
prove deny and allow from the same fixtures. Finally A writes a membership and
the stored row must carry A's tenant, with B's data byte-for-byte unchanged.

Run:  pytest tests/test_w0_03e_a2_http_authorization.py -v --noconftest
"""
import pytest

from app.master_data.deps import ENV_MODE
from app.tenancy import project_team as pt
from tests.test_w0_03e_legacy_migration import ORG_A, ORG_B, run

PID = "p-shared"
SM_ID = "sm-1"
ROLE = pt.ROLE_SITE_MANAGER

#: The SiteManager of tenant A. Same id as B's SiteManager — the collision.
SM_A = {"id": SM_ID, "org_id": ORG_A, "role": "SiteManager", "email": "sm@a",
        "first_name": "Site", "last_name": "A"}
SM_B = {**SM_A, "org_id": ORG_B, "email": "sm@b"}

#: Values that exist ONLY in tenant B. None may ever appear in A's response.
B_MARKERS = ("B-SECRET-PROJECT", "B-SECRET-OFFER", "B-SECRET-INVOICE", "B-SECRET-CP")


async def _world(db, team_rows=()):
    """B inserted first everywhere, so a tenant-blind query returns B's copy."""
    for org, mark in ((ORG_B, "B-SECRET"), (ORG_A, "A-own")):
        await db.projects.insert_one({
            "id": PID, "org_id": org, "status": "Active",
            "name": ("B-SECRET-PROJECT" if org == ORG_B else "A-own-project"),
            "code": ("B-SECRET-PROJECT" if org == ORG_B else "A-OWN-1")})
        await db.users.insert_one({"id": SM_ID, "org_id": org, "role": "SiteManager",
                                   "email": "sm@x", "first_name": mark, "last_name": "M",
                                   "is_active": True})
        await db.invoices.insert_one({
            "id": "inv-" + org, "org_id": org, "project_id": PID, "direction": "Inflow",
            "status": "Unpaid", "total": (999999 if org == ORG_B else 100),
            "invoice_no": ("B-SECRET-INVOICE" if org == ORG_B else "A-INV-1"),
            "date": "2026-03-01", "currency": "BGN",
            "counterparty_name": ("B-SECRET-CP" if org == ORG_B else "A-CP")})
        await db.offers.insert_one({
            "id": "off-" + org, "org_id": org, "project_id": PID, "status": "Draft",
            "offer_no": ("B-SECRET-OFFER" if org == ORG_B else "A-OFF-1"),
            "created_at": "2026-03-01", "items": [], "currency": "BGN"})
    # a second A user who may be added to a team
    await db.users.insert_one({"id": "w-a", "org_id": ORG_A, "role": "Technician",
                               "email": "w@a", "first_name": "W", "last_name": "A",
                               "is_active": True})
    for row in team_rows:
        await db.project_team.insert_one(dict(row))
    return db


def _row(org=None, rid="t-b", project_id=PID, user_id=SM_ID, role=ROLE):
    row = {"id": rid, "project_id": project_id, "user_id": user_id,
           "role_in_project": role, "active": True}
    if org is not None:
        row["org_id"] = org
    return row


def _app(monkeypatch, db, user):
    """The real routers, every module database handle pointed at ``db``."""
    from fastapi import FastAPI

    from app.deps import auth as deps_auth
    from app.deps.auth import get_current_user, require_admin
    from app.deps.modules import require_m2, require_m4, require_m5
    from app.routes import dashboard, finance, hr, offers, projects, reports
    from app.services import paid_labor

    async def _noop(*a, **kw):
        return None

    async def _user():
        return dict(user)
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    monkeypatch.setattr(paid_labor, "db", db)
    # deps.auth holds THE project authorization gate; it must see the same world
    monkeypatch.setattr(deps_auth, "db", db)
    app = FastAPI()
    for module in (finance, offers, reports, dashboard, hr, projects):
        monkeypatch.setattr(module, "db", db)
        if hasattr(module, "log_audit"):
            monkeypatch.setattr(module, "log_audit", _noop)
        app.include_router(module.router, prefix="/api")
    for dep in (get_current_user, require_admin, require_m2, require_m4, require_m5):
        app.dependency_overrides[dep] = _user
    return app


def _client(monkeypatch, db, user):
    import httpx
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(monkeypatch, db, user)),
                             base_url="http://t")


def _no_b(body, where):
    text = str(body)
    for marker in B_MARKERS:
        assert marker not in text, "%s leaked %s: %s" % (where, marker, text[:400])
    assert "999999" not in text, "%s leaked a B amount: %s" % (where, text[:400])


async def _probe(c, expect_access, is_tenant_a=True):
    """Every membership-decided route, as one caller. Returns {path: body}.

    The B-marker assertion applies only to tenant A's responses: B's own
    records legitimately carry B's values, and asserting otherwise would test
    the fixture rather than the boundary.
    """
    seen = {}
    own_project = "inv-" + (ORG_A if is_tenant_a else ORG_B)
    other_project = "inv-" + (ORG_B if is_tenant_a else ORG_A)
    own_offer = "off-" + (ORG_A if is_tenant_a else ORG_B)
    other_offer = "off-" + (ORG_B if is_tenant_a else ORG_A)

    async def get(path, *, allow=(200,)):
        r = await c.get(path)
        assert r.status_code in allow, (path, r.status_code, r.text[:300])
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
        if is_tenant_a:
            _no_b(body, path)
        seen[path] = (r.status_code, body)
        return r.status_code, body

    # --- project team routes (the relation's own surface)
    status, body = await get("/api/projects/%s" % PID, allow=(200, 403, 404))
    assert (status == 200) is expect_access, ("project detail", status)
    status, body = await get("/api/projects/%s/team" % PID, allow=(200, 403, 404))
    assert (status == 200) is expect_access, ("team list", status)
    if status == 200:
        assert all(m.get("user_id") != "nobody" for m in body)
    # --- the assigned-projects projection
    _, projects_body = await get("/api/projects")
    assert [p["id"] for p in projects_body] == ([PID] if expect_access else [])
    # --- finance invoice list + detail (A1 assigned_project_ids)
    _, invoices = await get("/api/finance/invoices")
    assert [i["id"] for i in invoices] == ([own_project] if expect_access else [])
    await get("/api/finance/invoices/%s" % own_project, allow=(200, 403, 404))
    # the other tenant's invoice is never readable here, membership or not
    st, _ = await get("/api/finance/invoices/%s" % other_project, allow=(403, 404))
    assert st in (403, 404)
    # --- offers list + detail
    _, offers_body = await get("/api/offers")
    assert [o["id"] for o in offers_body] == ([own_offer] if expect_access else [])
    st, _ = await get("/api/offers/%s" % own_offer, allow=(200, 403, 404))
    assert (st == 200) is expect_access, ("offer detail", st)
    await get("/api/offers/%s" % other_offer, allow=(403, 404))
    # --- a reports/export projection
    await get("/api/finance/stats", allow=(200, 403))
    return seen


def _matrix(monkeypatch, db, user, expect_access):
    async def body():
        async with _client(monkeypatch, db, user) as c:
            return await _probe(c, expect_access, is_tenant_a=user["org_id"] == ORG_A)
    return run(body())


# ------------------------------------------------------------------ the matrix
@pytest.fixture
def world(request):
    from mongomock_motor import AsyncMongoMockClient
    rows = getattr(request, "param", ())
    db = AsyncMongoMockClient()["a2_http"]
    run(_world(db, rows))
    return db


@pytest.mark.parametrize("world", [(_row(org=ORG_B),)], indirect=True)
def test_a_b_only_row_authorizes_nothing_on_any_route(monkeypatch, world):
    """The A1 counterexample, over HTTP: same project, user and role, B's row."""
    seen = _matrix(monkeypatch, world, SM_A, expect_access=False)
    assert seen, "no route was exercised"
    # B, who wrote the row, still has its own access through the same routes
    _matrix(monkeypatch, world, SM_B, expect_access=True)


@pytest.mark.parametrize("world", [(_row(org=None, rid="t-ownerless"),)], indirect=True)
def test_an_ownerless_row_authorizes_nothing_on_any_route(monkeypatch, world):
    """UNRESOLVED_PROVENANCE at the HTTP boundary: deny for BOTH tenants."""
    _matrix(monkeypatch, world, SM_A, expect_access=False)
    _matrix(monkeypatch, world, SM_B, expect_access=False)


@pytest.mark.parametrize("world", [(_row(org=ORG_B, rid="t-b"),
                                    _row(org=ORG_A, rid="t-a"))], indirect=True)
def test_a_proven_row_authorizes_its_own_tenant_on_every_route(monkeypatch, world):
    _matrix(monkeypatch, world, SM_A, expect_access=True)
    _matrix(monkeypatch, world, SM_B, expect_access=True)


@pytest.mark.parametrize("world", [(_row(org=ORG_A, rid="t-a"),)], indirect=True)
def test_the_collision_is_symmetric_over_http(monkeypatch, world):
    _matrix(monkeypatch, world, SM_A, expect_access=True)
    _matrix(monkeypatch, world, SM_B, expect_access=False)


# ------------------------------------------------------------------ the writes
@pytest.mark.parametrize("world", [(_row(org=ORG_A, rid="t-a"),)], indirect=True)
def test_a_membership_created_over_http_carries_the_servers_tenant(monkeypatch, world):
    db = world

    async def body():
        async with _client(monkeypatch, db, SM_A) as c:
            r = await c.post("/api/projects/%s/team" % PID,
                             json={"user_id": "w-a", "role_in_project": "Technician"})
            assert r.status_code == 201, (r.status_code, r.text[:400])
            return r.json()
    created = run(body())
    stored = run(db.project_team.find_one({"id": created["id"]}, {"_id": 0}))
    assert stored["org_id"] == ORG_A, "the new row must carry the server-resolved tenant"
    # ...and it authorizes only A
    assert run(pt.is_member(pt.tenant_for(db, SM_A), "w-a", PID)) is True
    assert run(pt.is_member(pt.tenant_for(db, SM_B), "w-a", PID)) is False


@pytest.mark.parametrize("world", [(_row(org=ORG_A, rid="t-a"),)], indirect=True)
def test_a_tenant_in_the_request_body_cannot_steer_the_new_row(monkeypatch, world):
    """A body ``org_id``/``tenant_id`` is not an input; the stamp stays A's."""
    db = world

    async def body():
        async with _client(monkeypatch, db, SM_A) as c:
            r = await c.post("/api/projects/%s/team" % PID,
                             json={"user_id": "w-a", "role_in_project": "Technician",
                                   "org_id": ORG_B, "tenant_id": ORG_B})
            return r.status_code, (r.json() if r.status_code == 201 else r.text)
    status, payload = run(body())
    assert status == 201, (status, str(payload)[:300])
    stored = run(db.project_team.find_one({"id": payload["id"]}, {"_id": 0}))
    assert stored["org_id"] == ORG_A, "a body tenant must never reach the row"
    assert run(db.project_team.count_documents({"org_id": ORG_B})) == 0


@pytest.mark.parametrize("world", [(_row(org=ORG_B, rid="t-b"),)], indirect=True)
def test_a_b_only_row_cannot_be_used_to_write_as_a(monkeypatch, world):
    """No unauthorized write: A has no proven membership, so it may not manage."""
    db = world
    before = run(db.project_team.find({}, {"_id": 0}).to_list(None))

    async def body():
        async with _client(monkeypatch, db, SM_A) as c:
            post = await c.post("/api/projects/%s/team" % PID,
                                json={"user_id": "w-a", "role_in_project": "Technician"})
            delete = await c.delete("/api/projects/%s/team/t-b" % PID)
            return post.status_code, delete.status_code
    post_status, delete_status = run(body())
    assert post_status in (403, 404), post_status
    assert delete_status in (403, 404), delete_status
    after = run(db.project_team.find({}, {"_id": 0}).to_list(None))
    assert after == before, "B's rows must be byte-for-byte unchanged"


@pytest.mark.parametrize("world", [(_row(org=ORG_B, rid="t-b"),
                                    _row(org=ORG_A, rid="t-a"))], indirect=True)
def test_removing_a_member_as_a_never_touches_bs_row(monkeypatch, world):
    db = world

    async def body():
        async with _client(monkeypatch, db, SM_A) as c:
            foreign = await c.delete("/api/projects/%s/team/t-b" % PID)   # B's row id
            own = await c.delete("/api/projects/%s/team/t-a" % PID)
            return foreign.status_code, own.status_code
    foreign_status, own_status = run(body())
    assert foreign_status == 404, foreign_status
    assert own_status == 200, own_status
    assert run(db.project_team.find_one({"id": "t-b"}, {"_id": 0}))["active"] is True
    assert run(db.project_team.find_one({"id": "t-a"}, {"_id": 0}))["active"] is False
