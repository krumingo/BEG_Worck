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
actual of 777. Every reader must show 180 (160 labor + 20 downtime — ONE figure, FG-422); after the
Owner's approval of the manual row, every reader shows 230.

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
    # FG-422: an approved DOWNTIME hour — part of THE labor cost "total" (160 labor + 20 downtime)
    await op.employee_daily_reports.insert_one({
        "id": "R-DT", "org_id": ORG, "worker_id": "w1", "submitted_by": "w1", "date": "2026-11-06",
        "hours": 1, "project_id": P, "smr_type": "Шпакловка", "execution_package_id": PKG,
        "cost_type": "DOWNTIME", "status": "APPROVED", "approval_status": "APPROVED", "approved_by": "sm"})
    # a child project (no labor) so that the project aggregate answers
    await op.projects.insert_one({"id": P + "-child", "org_id": ORG, "name": "child", "status": "Active",
                                  "parent_project_id": P})
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
    from app.routes import activity_budgets, centralized_reports, projects, revenue_snapshot  # noqa: F401
    from app.services import morning_briefing, project_financial_results, pulse_generator  # noqa: F401
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    real = appdb.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("app") and getattr(mod, "db", None) is real:
            monkeypatch.setattr(mod, "db", op)
    app = FastAPI()
    from app.routes import activity_budgets, centralized_reports, projects, revenue_snapshot
    for r in (labor_smr.router, revenue_expense.router, full_cost.router, activity_budgets.router,
              centralized_reports.router, projects.router, revenue_snapshot.router):
        app.include_router(r, prefix="/api")

    async def m2(user: dict = Depends(get_current_user)):      # the module gate is not under test
        return user
    app.dependency_overrides[modules.require_m2] = m2
    return app


def _mongomock_has_no_transactions(monkeypatch):
    """EXPLICIT, test backend only: mongomock cannot run MongoDB transactions — the manual
    decisions run their body without a session there. Production refuses (503):
    test_r62_without_transactions_a_decision_is_refused_and_writes_nothing."""
    from app.routes import labor_smr

    async def no_tx(body):
        return await body(None)
    monkeypatch.setattr(labor_smr, "_run_manual_tx", no_tx, raising=False)


def run(monkeypatch, scenario, backend="mongomock", tx=True):
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op)
            if backend == "mongomock" and tx:
                _mongomock_has_no_transactions(monkeypatch)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://r62",
                                         timeout=60) as c:
                return await scenario(c, op)
    return asyncio.run(body())


def _unassigned(by_project):
    """the labor of no SMR (e.g. a manual row without an activity) — not an activity budget's"""
    return round(sum(a["cost"] for a in by_project["by_activity"] if a["activity_name"] == "Общо"), 2)


async def _numbers(c):
    """The project's labor cost as EVERY reader shows it (R62: one number)."""
    from app.services.alarm_engine import evaluate_rule
    from app.services.project_financial_results import compute_financial_results
    from app.services.project_pnl import compute_project_pnl
    from app.services.pulse_generator import generate_pulse
    admin = _token("admin")

    async def get(path):
        r = await c.get(path, headers=admin)
        assert r.status_code == 200, (path, r.text)
        return r.json()

    pnl = await compute_project_pnl(ORG, P)
    profit = await get(f"/api/project-profit/{P}")
    net = await get(f"/api/project-net-profit/{P}")
    pkg = await get(f"/api/labor-cost/by-execution-package/{PKG}")
    pkg_net = await get(f"/api/execution-packages/{PKG}/net-financial")
    pkg_list = await get(f"/api/execution-packages?project_id={P}")
    by_project = await get(f"/api/labor-cost/by-project/{P}")
    by_period = await get(f"/api/profit-by-period/{P}")
    summary = await get(f"/api/projects/{P}/activity-budget-summary")
    health = await get(f"/api/projects/{P}/budget-health")
    ev = await get(f"/api/projects/{P}/earned-value")
    burn = await get("/api/activity-budgets/ab/burn")
    overview = await get(f"/api/projects/{P}/activities-overview")
    central = await get(f"/api/projects/{P}/centralized-reports")
    aggregate = await get(f"/api/projects/{P}/aggregate")
    site_workers = await get(f"/api/projects/{P}/site-workers")
    finres = await compute_financial_results(ORG, P)
    pulse = await generate_pulse(ORG, P, DAY)
    events = await evaluate_rule({"id": "rule-b", "type": "budget", "name": "бюджет",
                                  "condition": {"metric": "burn_pct", "operator": ">", "threshold": 0},
                                  "cooldown_hours": 0}, ORG)
    burn_ev = [e["context"]["metric_value"] for e in events if e["context"]["entity_id"] == P]
    return {
        "pnl": pnl["expense"]["labor_cost"],
        "project_profit": profit["expenses"]["labor"],
        "project_net_profit": net["costs"]["labor"],
        "package_labor": pkg["labor_actual_cost"],
        "package_net_financial": pkg_net["costs"]["labor"],
        "package_list_actual_labor": pkg_list[0]["actual_labor_cost"],
        "labor_cost_by_project": by_project["total_cost"],
        "profit_by_period": round(sum(p["labor"] for p in by_period["periods"]), 2),
        "activity_budget_summary": summary["totals"]["labor_spent"],
        "budget_health": health["total_spent"],
        "earned_value_ac": ev["AC"],
        # the burn of ONE activity budget is that SMR's figure — here every line is Шпакловка
        # except a manual row without an activity, which the project figures carry
        "budget_burn": burn["actual_cost"] + _unassigned(by_project),
        "activities_overview": overview["totals"]["total_actual_cost"],
        "centralized_reports": central["finance"]["total_clean_labor"],
        "project_aggregate_own": aggregate["work"]["own"]["labor_cost"],
        "site_workers_earned": round(sum(w.get("total_earned", 0) for w in site_workers["workers"]), 2),
        "financial_results_reported": finres["labor"]["reported_labor_value"],
        "financial_results_direct": finres["operating"]["direct_labor"],
        "pulse_budget_spent": pulse["budget_snapshot"]["total_spent"],
        "alarm_spent": round(burn_ev[0] * 1000 / 100, 2) if burn_ev else None,   # burn % of the 1000 budget
    }


# ═══════════════════════════════════════════════════════════════ one number
def test_r62_every_reader_shows_the_same_labor_cost(monkeypatch, backend):
    async def scenario(c, op):
        got = await _numbers(c)
        assert set(got.values()) == {180.0}, {k: v for k, v in got.items() if v != 180.0}   # 8 h × 20 + 1 h downtime
    run(monkeypatch, scenario, backend)


def _key(uid):
    return dict(_token(uid), **{"Idempotency-Key": uuid.uuid4().hex})


def _decision(version=1, cost=50.0, reason=""):
    return {"version": version, "labor_cost": cost, "reason": reason}


def test_r62_an_owner_approved_manual_row_counts_everywhere(monkeypatch, backend):
    async def scenario(c, op):
        h = _key("owner")
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["approval_status"] == "approved" and r.json()["approved_by"] == "owner"
        assert r.json()["version"] == 2
        got = await _numbers(c)
        assert set(got.values()) == {230.0}, {k: v for k, v in got.items() if v != 230.0}   # 180 + manual 50
        ev = [e async for e in op.audit_events.find({"entity_id": "le-man"}, {"_id": 0})]
        assert [(e["action"], e["actor_id"], e["entity_version"]) for e in ev] == [
            ("labor.manual_entry.approved", "owner", "2")]
        assert ev[0]["idempotency_key"] == h["Idempotency-Key"]
        # the same key replays; a new key is a second decision → 409
        again = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=h)
        assert again.status_code == 200 and again.json()["idempotent_replay"] is True
        new = await c.post("/api/labor-entries/le-man/approve", json=_decision(2), headers=_key("owner"))
        assert new.status_code == 409 and new.json()["detail"]["code"] == "ALREADY_APPROVED"
        assert await op.audit_events.count_documents({"entity_id": "le-man"}) == 1
    run(monkeypatch, scenario, backend)


@pytest.mark.parametrize("who", ["admin", "acct", "sm", "w1"])
def test_r62_only_the_owner_decides_a_manual_row(monkeypatch, who):
    async def scenario(c, op):
        for kind in ("approve", "reject"):
            r = await c.post(f"/api/labor-entries/le-man/{kind}", json=_decision(reason="x"), headers=_key(who))
            assert r.status_code == 403, (who, kind, r.text)
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
        assert set((await _numbers(c)).values()) == {180.0}
    run(monkeypatch, scenario)


def test_r62_the_creator_cannot_approve_his_own_row(monkeypatch):
    """Until Krum decides: the approver differs from the creator (here the Owner made it)."""
    async def scenario(c, op):
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {"created_by": "owner"}})
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "SELF_APPROVAL", r.text
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
    run(monkeypatch, scenario)


def test_r62_a_decision_needs_a_key_and_the_exact_version_and_value(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_token("owner"))
        assert r.status_code == 428
        for body in (_decision(version=2), _decision(cost=49.0), _decision(cost=None)):
            r = await c.post("/api/labor-entries/le-man/approve", json=body, headers=_key("owner"))
            assert r.status_code == 409 and r.json()["detail"]["code"] == "STALE_VERSION", (body, r.text)
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
        assert await op.audit_events.count_documents({"entity_id": "le-man"}) == 0
    run(monkeypatch, scenario)


def test_r62_reject_and_reverse(monkeypatch):
    async def scenario(c, op):
        # reject needs a reason; a rejected row never counts and cannot be approved any more
        r = await c.post("/api/labor-entries/le-man/reject", json=_decision(), headers=_key("owner"))
        assert r.status_code == 422
        r = await c.post("/api/labor-entries/le-man/reject", json=_decision(reason="дублира отчет"), headers=_key("owner"))
        assert r.status_code == 200 and r.json()["approval_status"] == "rejected", r.text
        assert set((await _numbers(c)).values()) == {180.0}
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(2), headers=_key("owner"))
        assert r.status_code == 409
        # an approved row is reversed by an appended reversal row (no delete)
        await op.labor_entries.insert_one({
            "id": "le-man2", "org_id": ORG, "project_id": P, "employee_id": "w1", "execution_package_id": PKG,
            "date": "2026-11-07", "hours": 2, "hourly_rate": 25, "labor_cost": 50, "source": "manual",
            "approval_status": "pending", "created_by": "admin", "version": 1, "reversed_by_entry_id": None})
        r = await c.post("/api/labor-entries/le-man2/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 200
        assert set((await _numbers(c)).values()) == {230.0}
        r = await c.post("/api/labor-entries/le-man2/reverse", json=_decision(2, reason="грешен ден"), headers=_key("owner"))
        assert r.status_code == 200 and r.json()["approval_status"] == "reversed", r.text
        rev = await op.labor_entries.find_one({"reverses_entry_id": "le-man2"})
        assert rev and rev["hours"] == -2 and rev["labor_cost"] == -50 and rev["entry_kind"] == "reversal"
        assert await op.labor_entries.find_one({"id": "le-man2"})       # still there
        assert set((await _numbers(c)).values()) == {180.0}
        actions = sorted([e["action"] async for e in op.audit_events.find({"entity_id": {"$in": ["le-man", "le-man2"]}})])
        assert actions == ["labor.manual_entry.approved", "labor.manual_entry.rejected", "labor.manual_entry.reversed"]
    run(monkeypatch, scenario)


def test_r62_a_manual_akord_row_is_quantity_times_the_piece_rate(monkeypatch):
    """FG-423: akord = quantity × the package's piece rate — never hours × rate."""
    async def scenario(c, op):
        await op.execution_packages.insert_one({"id": "pkg-ak", "org_id": ORG, "project_id": P, "activity_name": "Боя",
                                                "labor_pay_type": "Akord", "labor_piece_rate": 5, "labor_terms_version": 3})
        body = {"project_id": P, "employee_id": "w1", "hours": 8, "date": "2026-11-09", "execution_package_id": "pkg-ak"}
        r = await c.post("/api/labor-entries", json=body, headers=_key("admin"))
        assert r.status_code == 422, r.text                 # akord without a quantity
        r = await c.post("/api/labor-entries", json=dict(body, quantity=12), headers=_key("admin"))
        assert r.status_code == 201, r.text
        row = r.json()
        assert (row["labor_cost"], row["pay_type"], row["quantity"], row["piece_rate"], row["labor_terms_version"]) == (60.0, "Akord", 12.0, 5.0, 3)
        assert row["hourly_rate"] is None                   # not 8 h × 20
        await op.execution_packages.insert_one({"id": "pkg-ak0", "org_id": ORG, "project_id": P,
                                                "activity_name": "Без цена", "labor_pay_type": "Akord"})
        r = await c.post("/api/labor-entries", json=dict(body, quantity=12, execution_package_id="pkg-ak0"),
                         headers=_key("admin"))
        assert r.status_code == 422                          # no piece rate → no default
    run(monkeypatch, scenario)


def test_r62_a_manual_row_never_repeats_hours_of_an_approved_report(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries", json={"project_id": P, "employee_id": "w1", "hours": 2, "date": DAY},
                         headers=_key("admin"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_OF_APPROVED_REPORT", r.text
        # the report of the manual row's day got approved meanwhile → its approval is refused
        await op.employee_daily_reports.insert_one({
            "id": "R-LATE", "org_id": ORG, "worker_id": "w1", "date": "2026-11-05", "hours": 2, "project_id": P,
            "smr_type": "Шпакловка", "status": "APPROVED", "approval_status": "APPROVED", "approved_by": "sm"})
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_OF_APPROVED_REPORT", r.text
    run(monkeypatch, scenario)


def test_r62_a_crash_in_the_audit_write_leaves_the_row_pending(monkeypatch):
    """real rs0: the decision and its AuditEvent are ONE transaction."""
    if _real_refusal():
        pytest.skip(_real_refusal())

    async def scenario(c, op):
        from app.audit import store

        async def crash(*a, **kw):
            raise RuntimeError("simulated crash in the audit write")
        monkeypatch.setattr(store, "record_event", crash)
        with pytest.raises(RuntimeError):
            await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        row = await op.labor_entries.find_one({"id": "le-man"})
        assert row["approval_status"] == "pending" and not row.get("approved_by")
        assert await op.audit_events.count_documents({"entity_id": "le-man"}) == 0
    run(monkeypatch, scenario, "real")


def test_r62_without_transactions_a_decision_is_refused_and_writes_nothing(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 503, r.text
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
    run(monkeypatch, scenario, tx=False)


def test_r62_a_synced_row_is_not_decided_as_a_manual_row(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-sync/approve", json=_decision(cost=999.0), headers=_key("owner"))
        assert r.status_code == 409, r.text
        r = await c.post("/api/labor-entries/nope/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 404
    run(monkeypatch, scenario)


def test_r62_a_new_manual_row_is_pending_and_a_fake_sync_source_is_refused(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries", json={"project_id": P, "employee_id": "w1", "hours": 3,
                                                     "date": "2026-11-10", "execution_package_id": PKG},
                         headers=_key("admin"))
        assert r.status_code == 201, r.text
        assert (r.json()["approval_status"], r.json()["created_by"], r.json()["version"]) == ("pending", "admin", 1)
        assert set((await _numbers(c)).values()) == {180.0}
        r = await c.post("/api/labor-entries", json={"project_id": P, "hours": 3, "date": "2026-11-11",
                                                     "source": "work_report_sync"}, headers=_key("admin"))
        assert r.status_code == 422
    run(monkeypatch, scenario)


def test_r62_the_package_labor_actual_is_not_typed_in(monkeypatch):
    async def scenario(c, op):
        r = await c.put(f"/api/execution-packages/{PKG}", json={"actual_labor_cost": 5}, headers=_token("admin"))
        assert r.status_code == 422, r.text
        assert set((await _numbers(c)).values()) == {180.0}
    run(monkeypatch, scenario)


def test_r62_the_decision_routes_carry_the_owner_only_action_first():
    """SEC-01 style: the money-write dependency is each route's first and only marked one."""
    from app.permissions.catalog import CANONICAL_ROLES
    from app.routes.labor_smr import router
    for kind in ("approve", "reject", "reverse"):
        route = next(r for r in router.routes if getattr(r, "path", "") == f"/labor-entries/{{entry_id}}/{kind}")
        calls = [d.call for d in route.dependant.dependencies]
        marked = [c for c in calls if hasattr(c, "sec01_action")]
        assert len(marked) == 1 and calls[0] is marked[0], kind
        assert marked[0].sec01_action == "labor.manual_entry.approve"
    holders = {k for k, v in CANONICAL_ROLES.items() if "labor.manual_entry.approve" in v["actions"]}
    assert holders == {"owner"}
