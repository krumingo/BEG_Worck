"""
LAB-01-S — R62 (Krum 09.11.2026, FG-340 / FG-58 / FG-390): the labor cost of a project is
ONE number in every reader, from ONE canonical source (app.services.labor_cost.
project_labor_cost):

* only APPROVED reports count, priced hourly × rate or akord (approved quantity × piece
  rate); drafts / unapproved reports never count anywhere;
* a manual labor row counts only after the Owner approved it (FG-58); any other role → 403;
* the readers: P&L, /project-profit (no hours × rate fallback over all work_reports),
  /project-net-profit, the package actual labor cost (no labor_entries / cached field) and
  the budget alarm's "spent" (FG-390, no work_sessions).

One project carries every competing source: an approved report (8 h × 20 = 160), a draft
report (8 h), a draft work_report (10 h), a synced labor row of 999 (a projection), a
pending manual row of 50, finished work sessions worth 5000 and a stale cached package
actual of 777. Every reader must show 160; after the Owner's approval of the manual row,
every reader shows 210.

    pytest tests/test_lab_01_s_r62_one_labor_cost.py -v --noconftest
"""
import asyncio
import sys
import uuid

import pytest

ORG = "ORG-R62"
P = "prj-r62"
PKG = "pkg-r62"
DAY = "2026-11-02"
USERS = {"owner": "Owner", "admin": "Admin", "acct": "Accountant", "sm": "SiteManager", "w1": "Technician"}


def _real_refusal():
    try:
        from tests.test_w0_03c_real_mongo import _refusal
        return _refusal()
    except Exception as exc:                                       # noqa: BLE001
        return str(exc)


@pytest.fixture(params=["mongomock", "real"])
def backend(request):
    if request.param == "real" and _real_refusal():
        pytest.skip(_real_refusal())
    return request.param


class _Db:
    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, "r62_" + uuid.uuid4().hex[:10]

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.name]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            await self.client.drop_database(self.name)
            self.client.close()


async def _seed(op):
    await op.organizations.insert_one({"id": ORG, "name": "R62"})
    for uid, role in USERS.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@r62.example", "first_name": uid, "last_name": ""})
    await op.projects.insert_one({"id": P, "org_id": ORG, "name": "R62 обект", "status": "Active"})
    await op.employee_profiles.insert_one({"org_id": ORG, "user_id": "w1", "pay_type": "Hourly",
                                           "hourly_rate": 20})
    await op.execution_packages.insert_one({
        "id": PKG, "org_id": ORG, "project_id": P, "activity_name": "Шпакловка", "unit": "м2",
        "labor_budget_total": 1000, "sale_total": 5000, "budget_total": 3000,
        "actual_labor_cost": 777})                                 # stale cache — must not show
    await op.activity_budgets.insert_one({"id": "ab", "org_id": ORG, "project_id": P,
                                          "type": "Шпакловка", "labor_budget": 1000})
    # the approved report — THE labor cost: 8 h × 20 = 160
    await op.employee_daily_reports.insert_one({
        "id": "R-OK", "org_id": ORG, "worker_id": "w1", "submitted_by": "w1", "date": DAY,
        "hours": 8, "project_id": P, "smr_type": "Шпакловка", "execution_package_id": PKG,
        "status": "APPROVED", "approval_status": "APPROVED", "approved_by": "sm"})
    # a draft report of the same worker — never counts
    await op.employee_daily_reports.insert_one({
        "id": "R-DR", "org_id": ORG, "worker_id": "w1", "submitted_by": "w1", "date": "2026-11-03",
        "hours": 8, "project_id": P, "smr_type": "Шпакловка", "execution_package_id": PKG,
        "status": "DRAFT", "approval_status": "DRAFT"})
    # a draft work report of the old module — the removed /project-profit fallback read it
    await op.work_reports.insert_one({"id": "WR-D", "org_id": ORG, "project_id": P, "user_id": "w1",
                                      "date": "2026-11-04", "status": "Draft",
                                      "lines": [{"activity_name": "Шпакловка", "hours": 10}]})
    # a synced labor row (projection of reports) — never added a second time
    await op.labor_entries.insert_one({
        "id": "le-sync", "org_id": ORG, "project_id": P, "employee_id": "w1",
        "execution_package_id": PKG, "date": DAY, "hours": 8, "hourly_rate": 124.875,
        "labor_cost": 999, "source": "work_report_sync", "reversed_by_entry_id": None})
    # a manual row waiting for the Owner — counts only after approval
    await op.labor_entries.insert_one({
        "id": "le-man", "org_id": ORG, "project_id": P, "employee_id": "w1",
        "execution_package_id": PKG, "date": "2026-11-05", "hours": 2, "hourly_rate": 25,
        "labor_cost": 50, "source": "manual", "approval_status": "pending", "created_by": "admin",
        "reversed_by_entry_id": None})
    # finished work sessions worth 5000 — the old alarm "spent"
    await op.work_sessions.insert_one({"id": "ws", "org_id": ORG, "site_id": P,
                                       "ended_at": "2026-11-02T18:00", "labor_cost": 5000})


def _token(uid):
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token({"user_id": uid, "org_id": ORG, "role": USERS[uid]})}


def _app(monkeypatch, op):
    from fastapi import Depends, FastAPI
    import app.db as appdb
    from app.deps.auth import get_current_user
    from app.deps import modules
    from app.master_data.deps import ENV_MODE
    from app.routes import full_cost, labor_smr, revenue_expense  # noqa: F401 — loaded, then patched
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    real = appdb.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("app") and getattr(mod, "db", None) is real:
            monkeypatch.setattr(mod, "db", op)
    app = FastAPI()
    for r in (labor_smr.router, revenue_expense.router, full_cost.router):
        app.include_router(r, prefix="/api")

    async def m2(user: dict = Depends(get_current_user)):      # the module gate is not under test
        return user
    app.dependency_overrides[modules.require_m2] = m2
    return app


def run(monkeypatch, scenario, backend="mongomock"):
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://r62") as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def _numbers(c):
    """The project's labor cost as every reader shows it."""
    from app.services.alarm_engine import evaluate_rule
    from app.services.project_pnl import compute_project_pnl
    admin = _token("admin")
    pnl = await compute_project_pnl(ORG, P)
    profit = await c.get(f"/api/project-profit/{P}", headers=admin)
    net = await c.get(f"/api/project-net-profit/{P}", headers=admin)
    pkg = await c.get(f"/api/labor-cost/by-execution-package/{PKG}", headers=admin)
    pkg_net = await c.get(f"/api/execution-packages/{PKG}/net-financial", headers=admin)
    for r in (profit, net, pkg, pkg_net):
        assert r.status_code == 200, r.text
    events = await evaluate_rule({"id": "rule-b", "type": "budget", "name": "бюджет",
                                  "condition": {"metric": "burn_pct", "operator": ">", "threshold": 0},
                                  "cooldown_hours": 0}, ORG)
    burn = [e["context"]["metric_value"] for e in events if e["context"]["entity_id"] == P]
    return {
        "pnl": pnl["expense"]["labor_cost"],
        "project_profit": profit.json()["expenses"]["labor"],
        "project_net_profit": net.json()["costs"]["labor"],
        "package_labor": pkg.json()["labor_actual_cost"],
        "package_net_financial": pkg_net.json()["costs"]["labor"],
        "alarm_spent": round(burn[0] * 1000 / 100, 2) if burn else None,   # burn % of the 1000 budget
    }


# ═══════════════════════════════════════════════════════════════ one number
def test_r62_every_reader_shows_the_same_labor_cost(monkeypatch, backend):
    async def scenario(c, op):
        got = await _numbers(c)
        assert set(got.values()) == {160.0}, got          # approved 8 h × 20 — nothing else
    run(monkeypatch, scenario, backend)


def test_r62_an_owner_approved_manual_row_counts_everywhere(monkeypatch, backend):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", headers=_token("owner"))
        assert r.status_code == 200, r.text
        assert r.json()["approval_status"] == "approved" and r.json()["approved_by"] == "owner"
        got = await _numbers(c)
        assert set(got.values()) == {210.0}, got          # 160 + the approved manual 50
        ev = await op.audit_events.find_one({"entity_id": "le-man"}, {"_id": 0})
        assert ev and ev["actor_id"] == "owner" and ev["structured_diff"]["after"]["approval_status"] == "approved"
        # once only
        again = await c.post("/api/labor-entries/le-man/approve", headers=_token("owner"))
        assert again.status_code == 409 and again.json()["detail"]["code"] == "ALREADY_APPROVED"
    run(monkeypatch, scenario, backend)


@pytest.mark.parametrize("who", ["admin", "acct", "sm", "w1"])
def test_r62_only_the_owner_approves_a_manual_row(monkeypatch, who):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", headers=_token(who))
        assert r.status_code == 403, (who, r.text)
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
        assert set((await _numbers(c)).values()) == {160.0}
    run(monkeypatch, scenario)


def test_r62_a_synced_row_is_not_approved_as_a_manual_row(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-sync/approve", headers=_token("owner"))
        assert r.status_code == 409, r.text
        r = await c.post("/api/labor-entries/nope/approve", headers=_token("owner"))
        assert r.status_code == 404
    run(monkeypatch, scenario)


def test_r62_a_new_manual_row_is_pending_and_a_fake_sync_source_is_refused(monkeypatch):
    async def scenario(c, op):
        h = dict(_token("admin"), **{"Idempotency-Key": uuid.uuid4().hex})
        r = await c.post("/api/labor-entries", json={"project_id": P, "employee_id": "w1", "hours": 3,
                                                     "execution_package_id": PKG}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["approval_status"] == "pending" and r.json()["created_by"] == "admin"
        assert set((await _numbers(c)).values()) == {160.0}
        h = dict(_token("admin"), **{"Idempotency-Key": uuid.uuid4().hex})
        r = await c.post("/api/labor-entries", json={"project_id": P, "hours": 3, "source": "work_report_sync"},
                         headers=h)
        assert r.status_code == 422
    run(monkeypatch, scenario)


def test_r62_the_package_labor_actual_is_not_typed_in(monkeypatch):
    async def scenario(c, op):
        r = await c.put(f"/api/execution-packages/{PKG}", json={"actual_labor_cost": 5}, headers=_token("admin"))
        assert r.status_code == 422, r.text
        assert set((await _numbers(c)).values()) == {160.0}
    run(monkeypatch, scenario)
