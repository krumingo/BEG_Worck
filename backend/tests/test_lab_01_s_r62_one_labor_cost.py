"""
LAB-01-S — R62 (Krum 09.11.2026, FG-340 / FG-58 / FG-390): the labor cost of a project is
ONE number in every reader, from ONE canonical source (app.services.labor_cost.
project_labor_cost):

* only APPROVED reports count, priced hourly × rate or akord (approved quantity × piece
  rate); drafts / unapproved reports never count anywhere;
* a manual labor row counts only after it is approved by a SECOND person — the Owner /
  Управител or the Accountant, never the one who entered it (FG-58, R66); other roles → 403;
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
    from app.routes import activity_budgets, centralized_reports, projects, revenue_snapshot, work_sessions  # noqa: F401
    from app.routes import daily_reports  # noqa: F401
    from app.services import morning_briefing, project_financial_results, pulse_generator  # noqa: F401
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    real = appdb.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("app") and getattr(mod, "db", None) is real:
            monkeypatch.setattr(mod, "db", op)
    app = FastAPI()
    from app.routes import activity_budgets, centralized_reports, projects, revenue_snapshot, work_sessions
    for r in (labor_smr.router, revenue_expense.router, full_cost.router, activity_budgets.router,
              centralized_reports.router, projects.router, revenue_snapshot.router,
              work_sessions.router, daily_reports.router):
        app.include_router(r, prefix="/api")

    async def m2(user: dict = Depends(get_current_user)):      # the module gate is not under test
        return user
    app.dependency_overrides[modules.require_m2] = m2
    app.dependency_overrides[modules.require_m4] = m2
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


@pytest.mark.parametrize("who", ["admin", "sm", "w1"])
def test_r62_only_the_owner_or_the_accountant_decides_a_manual_row(monkeypatch, who):
    async def scenario(c, op):
        # R73: the row's creator may reject / reverse it — here nobody of `who` created it
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {"created_by": "acct"}})
        for kind in ("approve", "reject"):
            r = await c.post(f"/api/labor-entries/le-man/{kind}", json=_decision(reason="x"), headers=_key(who))
            assert r.status_code == 403, (who, kind, r.text)
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
        assert set((await _numbers(c)).values()) == {180.0}
    run(monkeypatch, scenario)


@pytest.mark.parametrize("creator,approver", [("owner", "owner"), ("acct", "acct")])
def test_r66_the_one_who_entered_the_row_never_approves_it(monkeypatch, creator, approver):
    """R66 (Krum 09.11.2026): creator ≠ approver, always — 403 SAME_PERSON_APPROVAL."""
    async def scenario(c, op):
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {"created_by": creator}})
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key(approver))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "SAME_PERSON_APPROVAL", r.text
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
        assert await op.audit_events.count_documents({"entity_id": "le-man"}) == 0
        assert set((await _numbers(c)).values()) == {180.0}
    run(monkeypatch, scenario)


@pytest.mark.parametrize("creator,approver", [("owner", "acct"), ("acct", "owner")])
def test_r66_a_second_person_approves(monkeypatch, creator, approver):
    """R66: a row the Owner entered is approved by the Accountant (and the other way round)."""
    async def scenario(c, op):
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {"created_by": creator}})
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key(approver))
        assert r.status_code == 200, r.text
        assert r.json()["approved_by"] == approver
        assert set((await _numbers(c)).values()) == {230.0}
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


def test_r62_a_manual_akord_row_without_an_approved_quantity_is_refused(monkeypatch):
    """R62 + R33 (FLOW Guard): the akord quantity is the LAB-02 APPROVED quantity — a manual
    row never brings a second, typed quantity. Without a LAB-02 source (this branch) a
    manual akord row is refused, with or without a quantity; nothing is stored."""
    async def scenario(c, op):
        await op.execution_packages.insert_one({"id": "pkg-ak", "org_id": ORG, "project_id": P, "activity_name": "Боя",
                                                "labor_pay_type": "Akord", "labor_piece_rate": 5, "labor_terms_version": 3})
        body = {"project_id": P, "employee_id": "w1", "hours": 8, "date": "2026-11-09", "execution_package_id": "pkg-ak"}
        for b in (body, dict(body, quantity=12)):
            r = await c.post("/api/labor-entries", json=b, headers=_key("admin"))
            assert r.status_code == 422 and r.json()["detail"]["code"] == "AKORD_NEEDS_APPROVED_QUANTITY", r.text
        assert await op.labor_entries.count_documents({"execution_package_id": "pkg-ak"}) == 0
    run(monkeypatch, scenario)


def test_r62_a_manual_row_never_repeats_hours_of_an_approved_report(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries", json={"project_id": P, "employee_id": "w1", "hours": 2, "date": DAY,
                                                     "execution_package_id": PKG},     # FG-461: an SMR package
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


def test_r62_the_decision_routes_carry_their_action_first():
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
    assert holders == {"owner", "accountant"}         # R66: Owner / Управител or the Accountant


def test_r62_work_session_time_screens_show_hours_and_never_a_second_official_cost(monkeypatch, backend):
    """R62 ("Едно число навсякъде") / FG-462: the work_sessions screens (list, active,
    my-today, summary, overtime) are TIME screens — the hours of the sessions, and for one
    site the ONE official figure approved_labor_cost (= project_labor_cost total, 180). The
    session money (5000 here) is never shown, not even as a labelled estimate."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    session_money = {"total_cost", "overtime_cost", "labor_cost", "hourly_rate_at_date",
                     "cost_basis", "cost_note", "cost_is_official"}

    def money_in(v):
        if isinstance(v, dict):
            return (session_money & set(v)) | {k for x in v.values() for k in money_in(x)}
        if isinstance(v, list):
            return {k for x in v for k in money_in(x)}
        return set()

    async def scenario(c, op):
        await op.work_sessions.update_one({"id": "ws"}, {"$set": {
            "worker_id": "w1", "worker_name": "Работник", "started_at": DAY + "T08:00:00",
            "ended_at": DAY + "T18:00:00", "duration_hours": 10.0, "is_overtime": True,
            "hourly_rate_at_date": 500}})
        await op.work_sessions.insert_one({
            "id": "ws-today", "org_id": ORG, "site_id": P, "worker_id": "owner",
            "started_at": today + "T07:00:00", "ended_at": today + "T09:00:00",
            "duration_hours": 2.0, "labor_cost": 300.0, "is_overtime": False})
        rng = "date_from=2026-11-01&date_to=2026-11-08"   # every seeded report; not today

        r = await c.get(f"/api/work-sessions/summary?site_id={P}&{rng}", headers=_token("owner"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_hours"] == 10.0 and d["overtime_hours"] == 10.0           # hours stay
        assert d["approved_labor_cost"] == 180.0                                  # THE number
        assert not money_in(d), d
        r = await c.get(f"/api/work-sessions/summary?{rng}", headers=_token("owner"))
        assert r.json()["approved_labor_cost"] is None and not money_in(r.json())

        for url in (f"/api/work-sessions/overtime?{rng}", f"/api/work-sessions?{rng}",
                    "/api/work-sessions/active", "/api/work-sessions/my-today"):
            r = await c.get(url, headers=_token("owner"))
            assert r.status_code == 200, (url, r.text)
            assert not money_in(r.json()), (url, r.json())
        ot = (await c.get(f"/api/work-sessions/overtime?{rng}", headers=_token("owner"))).json()
        assert ot["workers"][0]["overtime_hours"] == 10.0
        me = (await c.get("/api/work-sessions/my-today", headers=_token("owner"))).json()
        assert me["total_hours"] == 2.0

        # no finance right: hours only — not even the official figure
        r = await c.get(f"/api/work-sessions/summary?site_id={P}&{rng}", headers=_token("w1"))
        assert r.status_code == 200, r.text
        assert r.json()["total_hours"] == 10.0 and "approved_labor_cost" not in r.json()
    run(monkeypatch, scenario, backend)

# ═══════════════════════════════════════════════ FLOW Guard pass 38 (FG-460 … FG-463, FG-424)

async def _legacy_manual(op, rid, created_by="admin", **kw):
    """A legacy manual row (before FG-461): free-text SMR, maybe no package / no creator."""
    doc = {"id": rid, "org_id": ORG, "project_id": P, "employee_id": "w1", "date": "2026-11-07",
           "hours": 1, "hourly_rate": 30, "labor_cost": 30, "source": "manual",
           "approval_status": "pending", "version": 1, "reversed_by_entry_id": None}
    if created_by:
        doc["created_by"] = created_by
    doc.update(kw)
    await op.labor_entries.insert_one(doc)


def test_fg460_the_activity_parts_add_up_to_the_report_total(monkeypatch, backend):
    """FG-460: an SMR without a budget and an SMR-less approved manual row are "без бюджет"
    rows — the activities add up to the centralized report's labor total."""
    async def scenario(c, op):
        await _legacy_manual(op, "le-free", activity_name="Нещо без бюджет")            # unbudgeted
        await _legacy_manual(op, "le-none", employee_id="sm", date="2026-11-08")        # no SMR at all
        for rid in ("le-man", "le-free", "le-none"):
            r = await c.post(f"/api/labor-entries/{rid}/approve",
                             json=_decision(cost=50.0 if rid == "le-man" else 30.0), headers=_key("owner"))
            assert r.status_code == 200, (rid, r.text)
        full = (await c.get(f"/api/projects/{P}/centralized-reports", headers=_token("owner"))).json()
        acts = (await c.get(f"/api/projects/{P}/centralized-reports/activities", headers=_token("owner"))).json()["activities"]
        total = full["finance"]["total_clean_labor"]
        assert total == 290.0, total                                   # 180 + 50 + 30 + 30
        assert round(sum(a["clean_labor_cost"] for a in acts), 2) == total, acts
        assert round(sum(a["clean_labor_cost"] for a in full["activities"]), 2) == total
        nb = {a["activity_name"]: a["clean_labor_cost"] for a in acts if a.get("without_budget")}
        assert nb.get("Нещо без бюджет") == 30.0 and nb.get("Без СМР") == 30.0, nb
    run(monkeypatch, scenario, backend)


def test_fg461_a_new_manual_row_names_its_smr_package_never_free_text(monkeypatch):
    async def scenario(c, op):
        base = {"project_id": P, "employee_id": "w1", "hours": 2, "date": "2026-11-12"}
        r = await c.post("/api/labor-entries", json=dict(base, activity_name="Каквото и да е"), headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "SMR_REFERENCE_REQUIRED", r.text
        await op.execution_packages.insert_one({"id": "pkg-other", "org_id": ORG, "project_id": "prj-x",
                                                "activity_name": "Чужд"})
        r = await c.post("/api/labor-entries", json=dict(base, execution_package_id="pkg-other"), headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "SMR_REFERENCE_INVALID", r.text
        r = await c.post("/api/labor-entries", json=dict(base, execution_package_id=PKG, activity_name="Боя"),
                         headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "FREE_TEXT_SMR", r.text
        r = await c.post("/api/labor-entries", json=dict(base, execution_package_id=PKG), headers=_key("admin"))
        assert r.status_code == 201, r.text
        assert r.json()["activity_name"] == "Шпакловка"                # the package's SMR
        assert await op.labor_entries.count_documents({"date": "2026-11-12"}) == 1
    run(monkeypatch, scenario)


def test_fg461_a_legacy_row_is_mapped_to_its_package_smr_or_flagged(monkeypatch):
    """A legacy row named like ONE package of the project is counted on that package's SMR
    budget; a row that cannot be mapped keeps its text with DQ MANUAL_ROW_NO_SMR_REF."""
    from app.services.labor_cost import project_labor_cost

    async def scenario(c, op):
        await _legacy_manual(op, "le-map", activity_name="  шпакловка ")
        await _legacy_manual(op, "le-dq", activity_name="Непознато", employee_id="sm")
        for rid in ("le-map", "le-dq"):
            r = await c.post(f"/api/labor-entries/{rid}/approve", json=_decision(cost=30.0), headers=_key("owner"))
            assert r.status_code == 200, r.text
        lc = await project_labor_cost(ORG, P)
        recs = {r["manual_entry_id"]: r for r in lc["lines"] if r.get("manual_entry_id")}
        assert recs["le-map"]["smr_type"] == "Шпакловка" and recs["le-map"]["execution_package_id"] == PKG
        assert recs["le-map"]["dq"] == []
        assert "MANUAL_ROW_NO_SMR_REF" in recs["le-dq"]["dq"]
        assert any(w["code"] == "MANUAL_ROW_NO_SMR_REF" for w in lc["dq_warnings"])
        assert lc["by_package"][PKG]["labor"] >= 30.0
    run(monkeypatch, scenario)


def test_fg463_the_same_hours_are_never_counted_twice(monkeypatch):
    """FG-463: a 2nd manual row for the same worker, project and day → 409 (create and
    approve); a report over an approved manual row → 409; a manual row over an approved
    report → 409 (FG-423)."""
    async def scenario(c, op):
        # le-man (pending, w1, 2026-11-05) exists → a 2nd row of that day is refused
        r = await c.post("/api/labor-entries", json={"project_id": P, "employee_id": "w1", "hours": 1,
                                                     "date": "2026-11-05", "execution_package_id": PKG},
                         headers=_key("admin"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_MANUAL_ROW", r.text
        # a legacy 2nd row of that day: the first approved wins, the second approval is refused
        await _legacy_manual(op, "le-dup", date="2026-11-05")
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 200, r.text
        r = await c.post("/api/labor-entries/le-dup/approve", json=_decision(cost=30.0), headers=_key("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_MANUAL_ROW", r.text
        # a report of that day cannot be approved on top of the approved manual row
        await op.employee_daily_reports.insert_one({
            "id": "R-OVER", "org_id": ORG, "worker_id": "w1", "date": "2026-11-05", "hours": 2,
            "project_id": P, "smr_type": "Шпакловка", "status": "SUBMITTED", "submitted_by": "w1"})
        r = await c.post("/api/daily-reports/R-OVER/approve", json={}, headers=_token("sm"))
        assert r.status_code == 409, r.text
        rep = await op.employee_daily_reports.find_one({"id": "R-OVER"})
        assert rep["status"] == "SUBMITTED"
        assert set((await _numbers(c)).values()) == {230.0}                 # 180 + 50, once
    run(monkeypatch, scenario)


def test_fg424_a_row_without_a_creator_is_approved_by_an_owner_only(monkeypatch):
    async def scenario(c, op):
        await _legacy_manual(op, "le-anon", created_by=None, execution_package_id=PKG)
        r = await c.post("/api/labor-entries/le-anon/approve", json=_decision(cost=30.0), headers=_key("acct"))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "UNKNOWN_CREATOR_OWNER_ONLY", r.text
        assert (await op.labor_entries.find_one({"id": "le-anon"}))["approval_status"] == "pending"
        r = await c.post("/api/labor-entries/le-anon/approve", json=_decision(cost=30.0), headers=_key("owner"))
        assert r.status_code == 200, r.text
    run(monkeypatch, scenario)


def test_fg424_the_audit_event_names_the_real_approver_role(monkeypatch):
    from app.services.labor_cost import project_labor_cost

    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("acct"))
        assert r.status_code == 200, r.text
        assert r.json()["approved_by"] == "acct" and r.json()["approved_by_role"] == "Accountant"
        ev = await op.audit_events.find_one({"entity_id": "le-man"})
        assert "Accountant" in ev["reason"] and "Owner" not in ev["reason"], ev["reason"]
        rec = [x for x in (await project_labor_cost(ORG, P))["lines"] if x.get("manual_entry_id") == "le-man"][0]
        assert "Счетоводителя" in rec["formula"] and "Собственика" not in rec["formula"]
    run(monkeypatch, scenario)


def test_fg463_a_retried_create_replays_its_row_and_is_not_a_duplicate(monkeypatch):
    """The duplicate check runs after the idempotent replay: the same key returns the row it
    wrote; only a NEW request for the same worker, project and day is refused."""
    async def scenario(c, op):
        body = {"project_id": P, "employee_id": "w1", "hours": 2, "date": "2026-11-13",
                "execution_package_id": PKG}
        h = _key("admin")
        r1 = await c.post("/api/labor-entries", json=body, headers=h)
        r2 = await c.post("/api/labor-entries", json=body, headers=h)
        assert r1.status_code == 201 and r2.status_code in (200, 201), (r1.text, r2.text)
        assert r1.json()["id"] == r2.json()["id"]
        r3 = await c.post("/api/labor-entries", json=body, headers=_key("admin"))
        assert r3.status_code == 409 and r3.json()["detail"]["code"] == "DUPLICATE_MANUAL_ROW", r3.text
        assert await op.labor_entries.count_documents({"date": "2026-11-13"}) == 1
    run(monkeypatch, scenario)


# ═══════════════════════════════════════════════ R73 (Krum, canon a11a4c41)

def test_r73_the_creator_rejects_his_own_row_and_the_audit_names_him(monkeypatch, backend):
    """R73: the creator MAY reject his own manual row — recorded with who, in which role,
    when (AuditEvent); he never approves it (R66)."""
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("admin"))
        assert r.status_code == 403, r.text                                  # creator: no approval
        r = await c.post("/api/labor-entries/le-man/reject", json=_decision(reason="грешен ден"),
                         headers=_key("admin"))
        assert r.status_code == 200, r.text
        row = r.json()
        assert (row["approval_status"], row["rejected_by"], row["rejected_by_role"]) == ("rejected", "admin", "Admin")
        assert row["rejected_at"]
        ev = await op.audit_events.find_one({"entity_id": "le-man"}, {"_id": 0})
        assert ev["action"] == "labor.manual_entry.rejected" and ev["actor_id"] == "admin"
        assert ev["structured_diff"]["actor"] == {"user_id": "admin", "role": "Admin", "is_creator": True}
        assert "Admin" in ev["reason"] and ev["occurred_at"]                  # who, role, when
        assert set((await _numbers(c)).values()) == {180.0}                  # never counted
    run(monkeypatch, scenario, backend)


@pytest.mark.parametrize("creator", ["owner", "acct"])
def test_r73_r66_a_deciding_creator_still_never_approves_his_row(monkeypatch, creator):
    async def scenario(c, op):
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {"created_by": creator}})
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key(creator))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "SAME_PERSON_APPROVAL", r.text
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
    run(monkeypatch, scenario)


def test_r73_the_creator_reverses_his_own_approved_row(monkeypatch):
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 200, r.text
        r = await c.post("/api/labor-entries/le-man/reverse", json=_decision(version=2, reason="двойно"),
                         headers=_key("admin"))
        assert r.status_code == 200, r.text
        assert (r.json()["reversed_by"], r.json()["reversed_by_role"]) == ("admin", "Admin")
        ev = await op.audit_events.find_one({"entity_id": "le-man", "action": "labor.manual_entry.reversed"})
        assert ev["structured_diff"]["actor"]["is_creator"] is True
        assert set((await _numbers(c)).values()) == {180.0}
    run(monkeypatch, scenario)


def test_r73_a_creator_who_lost_the_right_to_enter_labor_cannot_act(monkeypatch):
    """The creator path still needs the R16 right on the row's project (a Technician who is
    not a member of the project gets 403)."""
    async def scenario(c, op):
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {"created_by": "w1"}})
        r = await c.post("/api/labor-entries/le-man/reject", json=_decision(reason="x"), headers=_key("w1"))
        assert r.status_code == 403, r.text
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "pending"
    run(monkeypatch, scenario)


# ═══════════════════════════════════════════════ LAB73-R1 (AUDIT-2 probe): FG-463 is atomic
# The audit probe's cases (docs/audit/probes/lab01/test_probe_lab01t_fg463_race.py) — real
# Mongo only (the race needs real transactions), ten runs each.

@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only")
@pytest.mark.parametrize("i", range(10))
def test_lab73_r1_t1_two_concurrent_approvals_of_overlapping_rows(monkeypatch, i):
    async def scenario(c, op):
        await _legacy_manual(op, "le-dup", date="2026-11-05")
        a, b = await asyncio.gather(
            c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner")),
            c.post("/api/labor-entries/le-dup/approve", json=_decision(cost=30.0), headers=_key("acct")))
        st = {r["id"]: r["approval_status"] async for r in op.labor_entries.find(
            {"id": {"$in": ["le-man", "le-dup"]}}, {"_id": 0, "id": 1, "approval_status": 1})}
        assert list(st.values()).count("approved") == 1, (st, a.text, b.text)
        assert sorted([a.status_code, b.status_code]) == [200, 409], (a.text, b.text)
    run(monkeypatch, scenario, backend="real")


@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only")
@pytest.mark.parametrize("i", range(10))
def test_lab73_r1_t2_two_concurrent_creates_of_the_same_day(monkeypatch, i):
    async def scenario(c, op):
        body = {"project_id": P, "employee_id": "w1", "hours": 1, "date": "2026-11-09",
                "execution_package_id": PKG}
        a, b = await asyncio.gather(c.post("/api/labor-entries", json=body, headers=_key("admin")),
                                    c.post("/api/labor-entries", json=body, headers=_key("owner")))
        n = await op.labor_entries.count_documents({"employee_id": "w1", "date": "2026-11-09",
                                                    "source": "manual"})
        assert n == 1, (n, a.text, b.text)
        assert sorted([a.status_code, b.status_code]) == [201, 409], (a.text, b.text)
    run(monkeypatch, scenario, backend="real")


@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only")
@pytest.mark.parametrize("i", range(10))
def test_lab73_r1_t3_a_report_and_a_manual_row_of_the_same_day_approved_concurrently(monkeypatch, i):
    """The report of le-man's day (w1, 2026-11-05) is approved by the SiteManager while the
    Owner approves le-man: at most one of the two counts."""
    async def scenario(c, op):
        await op.employee_daily_reports.insert_one({
            "id": "R-RACE", "org_id": ORG, "worker_id": "w1", "date": "2026-11-05", "hours": 2,
            "project_id": P, "smr_type": "Шпакловка", "status": "SUBMITTED", "submitted_by": "w1"})
        a, b = await asyncio.gather(
            c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner")),
            c.post("/api/daily-reports/R-RACE/approve", json={}, headers=_token("sm")))
        man = (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"]
        rep = (await op.employee_daily_reports.find_one({"id": "R-RACE"}))["status"]
        assert [man == "approved", rep == "APPROVED"].count(True) == 1, (man, rep, a.text, b.text)
        assert 409 in (a.status_code, b.status_code), (a.text, b.text)
    run(monkeypatch, scenario, backend="real")


@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only")
@pytest.mark.parametrize("i", range(5))
def test_lab73_r1_a_concurrent_retry_of_the_same_key_writes_one_row(monkeypatch, i):
    """Two concurrent POST /labor-entries with the SAME Idempotency-Key: one row (the
    key-derived id), both answers name it — never 409 for the key's own row."""
    async def scenario(c, op):
        body = {"project_id": P, "employee_id": "w1", "hours": 1, "date": "2026-11-14",
                "execution_package_id": PKG}
        h = _key("admin")
        a, b = await asyncio.gather(c.post("/api/labor-entries", json=body, headers=h),
                                    c.post("/api/labor-entries", json=body, headers=h))
        n = await op.labor_entries.count_documents({"employee_id": "w1", "date": "2026-11-14"})
        assert n == 1, (n, a.text, b.text)
        ok = [r for r in (a, b) if r.status_code in (200, 201)]
        assert ok and all(r.json()["id"] == ok[0].json()["id"] for r in ok), (a.text, b.text)
        assert all(r.status_code in (200, 201, 409) for r in (a, b)), (a.text, b.text)
        assert not any(r.status_code == 409 and "DUPLICATE" in r.text for r in (a, b)), (a.text, b.text)
    run(monkeypatch, scenario, backend="real")


# ═══════════════════════════════════════════════ FLOW Guard pass 39 (FG-490 … FG-492)

@pytest.mark.parametrize("bad", ["2026-10-05T00:00:00", "2026-10-05 ", "05.10.2026", "2026-13-01", ""])
def test_fg491_a_manual_row_date_is_an_iso_day_only(monkeypatch, bad):
    async def scenario(c, op):
        body = {"project_id": P, "employee_id": "w1", "hours": 1, "date": bad, "execution_package_id": PKG}
        r = await c.post("/api/labor-entries", json=body, headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_DATE", r.text
        assert await op.labor_entries.count_documents({"source": "manual"}) == 1      # only le-man
        r = await c.post("/api/labor-entries", json=dict(body, date="2026-10-05"), headers=_key("admin"))
        assert r.status_code == 201 and r.json()["date"] == "2026-10-05", r.text
    run(monkeypatch, scenario)


def test_fg491_a_legacy_non_iso_date_is_the_same_day_and_flagged_never_rewritten(monkeypatch):
    from app.services.labor_cost import project_labor_cost

    async def scenario(c, op):
        await _legacy_manual(op, "le-old", date="05.10.2026", employee_id="sm",
                             execution_package_id=PKG)
        r = await c.post("/api/labor-entries", json={"project_id": P, "employee_id": "sm", "hours": 1,
                                                     "date": "2026-10-05", "execution_package_id": PKG},
                         headers=_key("admin"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_MANUAL_ROW", r.text
        r = await c.post("/api/labor-entries/le-old/approve", json=_decision(cost=30.0), headers=_key("owner"))
        assert r.status_code == 200, r.text
        lc = await project_labor_cost(ORG, P)
        rec = [x for x in lc["lines"] if x.get("manual_entry_id") == "le-old"][0]
        assert "MANUAL_ROW_NON_ISO_DATE" in rec["dq"]
        assert any(w["code"] == "MANUAL_ROW_NON_ISO_DATE" and w["normalized"] == "2026-10-05"
                   for w in lc["dq_warnings"])
        assert (await op.labor_entries.find_one({"id": "le-old"}))["date"] == "05.10.2026"   # untouched
    run(monkeypatch, scenario)


@pytest.mark.parametrize("entry_project", [None, P])
def test_fg490_an_old_style_batch_report_over_an_approved_manual_row_is_refused(monkeypatch, entry_project):
    """FG-490: an old-style report (employee_id + day_entries) of le-man's day — with no
    project (the whole tenant) or with P — is not approved on top of the approved row."""
    async def scenario(c, op):
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 200, r.text
        await op.employee_daily_reports.insert_one({
            "id": "R-OLD", "org_id": ORG, "employee_id": "w1", "report_date": "2026-11-05",
            "day_entries": [{"id": "e1", "project_id": entry_project, "hours_worked": 2,
                             "work_description": "Шпакловка"}],
            "status": "SUBMITTED", "submitted_by": "w1"})
        r = await c.post("/api/daily-reports/R-OLD/approve", json={}, headers=_token("sm"))
        assert r.status_code == 409, r.text
        assert (await op.employee_daily_reports.find_one({"id": "R-OLD"}))["status"] == "SUBMITTED"
        assert set((await _numbers(c)).values()) == {230.0}
    run(monkeypatch, scenario)


def test_fg490_a_projectless_report_claims_the_workers_day_on_every_project(monkeypatch):
    """The other direction: an approved old-style report without a project blocks a manual
    row of that worker and day on any project (create and approve)."""
    async def scenario(c, op):
        await op.employee_daily_reports.insert_one({
            "id": "R-OLD2", "org_id": ORG, "employee_id": "w1", "report_date": "2026-11-05",
            "day_entries": [{"id": "e1", "hours_worked": 2, "work_description": "x"}],
            "status": "SUBMITTED", "submitted_by": "w1"})
        r = await c.post("/api/daily-reports/R-OLD2/approve", json={}, headers=_token("sm"))
        assert r.status_code == 200, r.text
        r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "DUPLICATE_OF_APPROVED_REPORT", r.text
    run(monkeypatch, scenario)


def test_fg492_a_correction_names_the_row_it_replaces_and_every_create_is_audited(monkeypatch):
    async def scenario(c, op):
        body = {"project_id": P, "employee_id": "w1", "hours": 3, "date": "2026-11-05",
                "execution_package_id": PKG}
        r = await c.post("/api/labor-entries/le-man/reject", json=_decision(reason="грешни часове"),
                         headers=_key("owner"))
        assert r.status_code == 200, r.text
        r = await c.post("/api/labor-entries", json=body, headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "CORRECTION_LINK_REQUIRED", r.text
        assert r.json()["detail"]["replaces"] == ["le-man"]
        r = await c.post("/api/labor-entries", json=dict(body, corrects_entry_id="no-such"), headers=_key("admin"))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "CORRECTION_LINK_INVALID", r.text
        r = await c.post("/api/labor-entries", json=dict(body, corrects_entry_id="le-man"), headers=_key("admin"))
        assert r.status_code == 201, r.text
        new = r.json()
        assert new["corrects_entry_id"] == "le-man" and new["approval_status"] == "pending"
        ev = await op.audit_events.find_one({"entity_id": new["id"]}, {"_id": 0})
        assert ev["action"] == "labor.manual_entry.created" and ev["actor_id"] == "admin"
        assert ev["structured_diff"]["after"]["corrects_entry_id"] == "le-man"
        assert ev["structured_diff"]["actor"] == {"user_id": "admin", "role": "Admin"}
        # a first row of a day (nothing replaced) is audited too, without a link
        r = await c.post("/api/labor-entries", json=dict(body, date="2026-11-20"), headers=_key("admin"))
        assert r.status_code == 201 and r.json()["corrects_entry_id"] is None, r.text
        assert await op.audit_events.count_documents({"action": "labor.manual_entry.created"}) == 2
    run(monkeypatch, scenario)


# ═══════════════════════════════════════════════ FLOW Guard pass 40 (FG-500, FG-502)

def test_fg502_the_work_session_writes_answer_with_hours_only(monkeypatch):
    """start / end / split / PUT answer with the session's hours — no labor_cost and no
    hourly_rate_at_date, to the worker or anyone (R62 / R20)."""
    async def scenario(c, op):
        await op.employee_profiles.update_one({"user_id": "owner"}, {"$set": {
            "org_id": ORG, "user_id": "owner", "hourly_rate": 30, "pay_type": "Hourly"}}, upsert=True)
        money = {"labor_cost", "hourly_rate_at_date"}
        s1 = await c.post("/api/work-sessions/start", json={"site_id": P}, headers=_token("owner"))
        assert s1.status_code == 201 and not money & set(s1.json()), s1.text
        e1 = await c.post("/api/work-sessions/end", json={}, headers=_token("owner"))
        assert e1.status_code == 200 and not money & set(e1.json()), e1.text
        sid = e1.json()["id"]
        stored = await op.work_sessions.find_one({"id": sid})
        assert "labor_cost" in stored                            # the time record keeps its fields
        await op.work_sessions.update_one({"id": sid}, {"$set": {
            "started_at": "2026-11-03T07:00:00+00:00", "ended_at": "2026-11-03T15:00:00+00:00"}})
        u = await c.put(f"/api/work-sessions/{sid}", json={"notes": "x", "ended_at": "2026-11-03T16:00:00+00:00"},
                        headers=_token("owner"))
        assert u.status_code == 200 and not money & set(u.json()), u.text
        sp = await c.post(f"/api/work-sessions/{sid}/split", json={"splits": [{"hours": 4}, {"hours": 5}]},
                          headers=_token("owner"))
        assert sp.status_code == 200, sp.text
        assert all(not money & set(n) for n in sp.json()["new_sessions"]), sp.json()
    run(monkeypatch, scenario)


def test_fg500_a_legacy_non_iso_approved_row_stays_in_its_date_window(monkeypatch):
    from app.services.labor_cost import project_labor_cost

    async def scenario(c, op):
        await _legacy_manual(op, "le-old", date="06.11.2026", employee_id="sm", execution_package_id=PKG,
                             approval_status="approved", approved_by="owner", approved_by_role="Owner")
        win = await project_labor_cost(ORG, P, "2026-11-06", "2026-11-06")
        rec = [x for x in win["lines"] if x.get("manual_entry_id") == "le-old"]
        assert rec and rec[0]["date"] == "2026-11-06" and rec[0]["amount"] == 30.0, win["lines"]
        assert "MANUAL_ROW_NON_ISO_DATE" in rec[0]["dq"]                     # still flagged for a human
        assert not [x for x in (await project_labor_cost(ORG, P, "2026-11-07", "2026-11-30"))["lines"]
                    if x.get("manual_entry_id") == "le-old"]
        assert (await op.labor_entries.find_one({"id": "le-old"}))["date"] == "06.11.2026"   # never rewritten
    run(monkeypatch, scenario)
