"""
LAB-02 — quantity entry + approval and the piece rate per SMR (R33, Krum 07.11.2026).

docs/architecture/tasks/LAB-02_QUANTITY_APPROVAL_PIECE_RATE.md — tests:

* akord: 120 m2 approved × 5 → 600 in the Pay Run and in "spent";
* a worker cannot approve their own work; a report change voids the approval;
  DOWNTIME is a separate line (approver classification with a reason);
* the piece rate is set by finance roles only (version + history + AuditEvent) and a later
  change does not touch an approved quantity; R29 Idempotency-Key on every money write;
* roles × 3 PERMISSION_SERVICE_MODE values.

mongomock always; real Mongo when W0_03_REAL_MONGO_URL names a disposable local MongoDB.

    pytest tests/test_lab_02_quantity_approval.py -v --noconftest
"""
import asyncio
import uuid

import pytest

from tests.pay_run_idempotency import EVENT_HOOKS

ORG = "ORG-LAB02"
P_START, P_END = "2026-11-02", "2026-11-08"
DAY = "2026-11-02"
ROLES = {
    "owner": "Owner", "admin": "Admin", "acct": "Accountant", "sm": "SiteManager",
    "sm-other": "SiteManager", "tech": "Technician", "w-ak": "Worker", "w-month": "Worker",
}


def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


async def _seed(op):
    from app.tenancy import project_team
    from app.tenancy.data_access import TenantData
    await op.organizations.insert_one({"id": ORG, "name": "LAB-02"})
    for uid, role in ROLES.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@lab02.example", "first_name": uid, "last_name": "X"})
    await op.employee_profiles.insert_many([
        {"org_id": ORG, "user_id": "w-ak", "pay_type": "Akord", "hourly_rate": 15},
        {"org_id": ORG, "user_id": "w-month", "pay_type": "Monthly", "monthly_salary": 2200,
         "working_days_per_month": 22}])
    await op.projects.insert_many([{"id": "P", "org_id": ORG, "name": "Обект P"},
                                   {"id": "Q", "org_id": ORG, "name": "Обект Q"}])
    tenant = TenantData.for_resolved_org(op, ORG)
    await project_team.add_member(tenant, member_id="m1", project_id="P", user_id="sm",
                                  role_in_project=project_team.ROLE_SITE_MANAGER)
    await project_team.add_member(tenant, member_id="m2", project_id="Q", user_id="sm-other",
                                  role_in_project=project_team.ROLE_SITE_MANAGER)
    await op.execution_packages.insert_many([
        {"id": "pkg-sh", "org_id": ORG, "project_id": "P", "activity_name": "Шпакловка", "unit": "м2"},
        {"id": "pkg-q", "org_id": ORG, "project_id": "Q", "activity_name": "Боя", "unit": "м2"}])
    # one new-style report line of the akord worker (40 h over the week as one line of 8 h)
    await op.employee_daily_reports.insert_many([
        {"id": "R-AK", "org_id": ORG, "worker_id": "w-ak", "submitted_by": "w-ak", "date": DAY,
         "hours": 8, "project_id": "P", "smr_type": "Шпакловка", "status": "Draft",
         "payroll_status": "none", "created_at": DAY + "T17:00:00"},
        {"id": "R-M", "org_id": ORG, "worker_id": "w-month", "submitted_by": "w-month", "date": DAY,
         "hours": 8, "project_id": "P", "smr_type": "Шпакловка", "status": "APPROVED",
         "payroll_status": "none", "created_at": DAY + "T17:00:00"}])


def _token(uid):
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token({"user_id": uid, "org_id": ORG, "role": ROLES[uid]})}


def H(uid, key=True):
    h = _token(uid)
    if key:
        h["Idempotency-Key"] = "k-" + uuid.uuid4().hex
    return h


def _app(monkeypatch, op, mode="off"):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.master_data.deps import ENV_MODE
    from app.routes import labor_quantities, pay_runs
    from app.services import labor_cost, payroll_sync, report_normalizer
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    for m in (appdb, deps_auth, pay_runs, payroll_sync, report_normalizer, labor_cost, labor_quantities):
        monkeypatch.setattr(m, "db", op)
    app = FastAPI()
    app.include_router(pay_runs.router, prefix="/api")
    app.include_router(labor_quantities.router, prefix="/api")
    return app


class _Db:
    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, "lab02_" + uuid.uuid4().hex[:10]

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


def run(monkeypatch, scenario, backend="mongomock", mode="off"):
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op, mode)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lab02",
                                         event_hooks=EVENT_HOOKS) as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def _set_rate(c, rate=5, who="acct", pay_type="Akord"):
    return await c.put("/api/labor-terms/pkg-sh", json={"labor_pay_type": pay_type, "labor_piece_rate": rate,
                                                       "reason": "договор"}, headers=H(who))


async def _approve_flow(c, op, qty=120):
    """finance sets 5/м2 → worker enters qty → report approved → SiteManager approves."""
    assert (await _set_rate(c)).status_code == 200
    r = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": qty}, headers=H("w-ak", False))
    assert r.status_code == 200, r.text
    await op.employee_daily_reports.update_one({"id": "R-AK"}, {"$set": {"status": "APPROVED"}})
    ver = (await op.employee_daily_reports.find_one({"id": "R-AK"}))["report_version"]
    r = await c.post("/api/labor-quantities/approve", json={
        "report_id": "R-AK", "report_version": ver, "approved_quantity": qty,
        "execution_package_id": "pkg-sh", "note": "измерено"}, headers=H("sm"))
    assert r.status_code == 200, r.text
    return r.json()


async def _preview(c):
    r = await c.get("/api/pay-runs/generate", params={"period_start": P_START, "period_end": P_END},
                    headers=_token("admin"))
    assert r.status_code == 200, r.text
    return {x["employee_id"]: x for x in r.json()["rows"]}


# ═══════════════════════════════════════════════════════════════ the akord flow
def test_akord_120_m2_approved_times_5_is_600_in_pay_run_and_spent(monkeypatch, backend):
    async def scenario(c, op):
        from app.services.labor_cost import project_labor_cost
        rec = await _approve_flow(c, op)
        assert (rec["approved_quantity"], rec["unit"], rec["piece_rate"], rec["labor_pay_type"]) == (120, "м2", 5, "Akord")
        assert rec["approved_by"] == "sm" and rec["status"] == "approved"
        rows = await _preview(c)
        assert rows["w-ak"]["earned_amount"] == 600.0               # 120 × 5, not 8 h × 15
        spent = await project_labor_cost(ORG, "P", P_START, P_END)
        assert round(sum(r["amount"] for r in spent["lines"] if r["worker_id"] == "w-ak"), 2) == 600.0
        actions = sorted([a["action"] async for a in op.audit_events.find({}, {"_id": 0})])
        assert actions == ["daily_report.edited", "labor_quantity.approved", "labor_terms.set"]
    run(monkeypatch, scenario, backend)


def test_a_worker_cannot_approve_their_own_work(monkeypatch, backend):
    async def scenario(c, op):
        assert (await _set_rate(c)).status_code == 200
        # the SiteManager's own line on his project
        await op.employee_daily_reports.insert_one({
            "id": "R-SM", "org_id": ORG, "worker_id": "sm", "submitted_by": "sm", "date": DAY, "hours": 8,
            "project_id": "P", "status": "APPROVED", "quantity": 50})
        r = await c.post("/api/labor-quantities/approve", json={
            "report_id": "R-SM", "report_version": 0, "approved_quantity": 50,
            "execution_package_id": "pkg-sh"}, headers=H("sm"))
        assert r.status_code == 403
        assert await op.labor_quantity_approvals.count_documents({}) == 0
    run(monkeypatch, scenario, backend)


def test_a_report_change_voids_the_approval(monkeypatch, backend):
    async def scenario(c, op):
        await _approve_flow(c, op)
        assert (await _preview(c))["w-ak"]["earned_amount"] == 600.0
        # an approver corrects the approved report (R36) → version + 1, approval void
        r = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 130}, headers=H("admin", False))
        assert r.status_code == 200, r.text
        assert (await op.labor_quantity_approvals.find_one({}))["status"] == "void"
        # LAB-01-I: the corrected report is SUBMITTED again — nothing of it is payable
        assert "w-ak" not in await _preview(c)
        assert (await op.employee_daily_reports.find_one({"id": "R-AK"}))["status"] == "SUBMITTED"
        # an approval for the OLD version is refused (stale)
        r = await c.post("/api/labor-quantities/approve", json={
            "report_id": "R-AK", "report_version": 1, "approved_quantity": 130,
            "execution_package_id": "pkg-sh"}, headers=H("sm"))
        assert r.status_code == 409
    run(monkeypatch, scenario, backend)


def test_a_price_change_does_not_touch_an_approved_quantity(monkeypatch, backend):
    async def scenario(c, op):
        await _approve_flow(c, op)
        r = await _set_rate(c, 7)
        assert r.status_code == 200 and r.json()["labor_terms_version"] == 2
        assert (await _preview(c))["w-ak"]["earned_amount"] == 600.0  # still 120 × 5
        hist = await op.labor_terms_history.find({}, {"_id": 0}).sort("version", 1).to_list(10)
        assert [(h["before"]["labor_piece_rate"], h["after"]["labor_piece_rate"]) for h in hist] == [(None, 5), (5, 7)]
    run(monkeypatch, scenario, backend)


def test_reapproval_corrects_and_keeps_the_old_record(monkeypatch, backend):
    async def scenario(c, op):
        first = await _approve_flow(c, op)
        r = await c.post("/api/labor-quantities/approve", json={
            "report_id": "R-AK", "report_version": first["report_version"], "approved_quantity": 100,
            "execution_package_id": "pkg-sh", "note": "премерено"}, headers=H("admin"))
        assert r.status_code == 200, r.text
        recs = {x["id"]: x for x in await op.labor_quantity_approvals.find({}, {"_id": 0}).to_list(10)}
        assert recs[first["id"]]["status"] == "void" and recs[r.json()["id"]]["replaces"] == [first["id"]]
        assert (await _preview(c))["w-ak"]["earned_amount"] == 500.0
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════ DOWNTIME
def test_downtime_is_classified_by_the_approver_with_a_reason(monkeypatch, backend):
    async def scenario(c, op):
        body = {"report_id": "R-M", "report_version": 0, "cost_type": "DOWNTIME",
                "reason": "липса на материал", "responsible_party": "доставчик"}
        assert (await c.post("/api/labor-quantities/classify", json=dict(body, reason=""),
                             headers=H("sm"))).status_code == 422
        assert (await c.post("/api/labor-quantities/classify", json=body, headers=H("w-month"))).status_code == 403
        assert (await c.post("/api/labor-quantities/classify", json=body, headers=H("sm-other"))).status_code == 403
        r = await c.post("/api/labor-quantities/classify", json=body, headers=H("sm"))
        assert r.status_code == 200, r.text
        row = (await _preview(c))["w-month"]
        assert row["downtime_amount"] == 100.0 and row["labor_amount"] == 0.0 and row["earned_amount"] == 100.0
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════ R29 / idempotency
def test_money_writes_need_an_idempotency_key_and_replay(monkeypatch, backend):
    async def scenario(c, op):
        body = {"labor_pay_type": "Akord", "labor_piece_rate": 5, "reason": "x"}
        assert (await c.put("/api/labor-terms/pkg-sh", json=body, headers=H("acct", False))).status_code == 428
        h = H("acct")
        a = await c.put("/api/labor-terms/pkg-sh", json=body, headers=h)
        b = await c.put("/api/labor-terms/pkg-sh", json=body, headers=h)
        assert a.status_code == b.status_code == 200 and b.json()["idempotent_replay"] is True
        assert await op.labor_terms_history.count_documents({}) == 1
        assert (await c.put("/api/labor-terms/pkg-sh", json=dict(body, labor_piece_rate=6), headers=h)).status_code == 409
        # akord without a price, a negative / non-finite price → 422
        for bad in ({"labor_pay_type": "Akord", "labor_piece_rate": 0}, {"labor_pay_type": "Akord", "labor_piece_rate": -1},
                    {"labor_pay_type": "Weird", "labor_piece_rate": 1}):
            assert (await c.put("/api/labor-terms/pkg-sh", json=bad, headers=H("acct"))).status_code == 422, bad
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════ roles × 3 modes
EXPECT = {
    # role:           GET terms, PUT terms, GET pending, approve
    "owner":    (200, 200, 200, 200),
    "admin":    (200, 200, 200, 200),
    "acct":     (200, 200, 403, 403),
    "sm":       (403, 403, 200, 200),
    "sm-other": (403, 403, 403, 403),
    "tech":     (403, 403, 403, 403),
    "w-month":  (403, 403, 403, 403),
}


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_roles_times_three_modes(monkeypatch, mode):
    async def scenario(c, op):
        await op.employee_daily_reports.update_one({"id": "R-AK"}, {"$set": {"status": "APPROVED", "quantity": 120}})
        got = {}
        for who in EXPECT:
            g = await c.get("/api/labor-terms", params={"project_id": "P"}, headers=_token(who))
            p = await c.put("/api/labor-terms/pkg-sh", json={"labor_pay_type": "Akord", "labor_piece_rate": 5},
                            headers=H(who))
            pend = await c.get("/api/labor-quantities/pending", params={"project_id": "P"}, headers=_token(who))
            if pend.status_code == 200:
                items = {i["report_id"]: i for i in pend.json()["items"]}
                assert items["R-AK"]["state"] in ("waiting", "approved")
            ver = (await op.employee_daily_reports.find_one({"id": "R-AK"})).get("report_version", 0)
            a = await c.post("/api/labor-quantities/approve", json={
                "report_id": "R-AK", "report_version": ver, "approved_quantity": 120,
                "execution_package_id": "pkg-sh"}, headers=H(who))
            got[who] = (g.status_code, p.status_code, pend.status_code, a.status_code)
        assert got == EXPECT, got
    run(monkeypatch, scenario, "mongomock", mode)


def test_pending_list_shows_no_piece_rate_to_a_site_manager(monkeypatch, backend):
    async def scenario(c, op):
        await _approve_flow(c, op)
        sm = await c.get("/api/labor-quantities/pending", params={"project_id": "P"}, headers=_token("sm"))
        fin = await c.get("/api/labor-quantities/pending", params={"project_id": "P"}, headers=_token("admin"))
        sm_item = {i["report_id"]: i for i in sm.json()["items"]}["R-AK"]
        fin_item = {i["report_id"]: i for i in fin.json()["items"]}["R-AK"]
        assert sm_item["approval"]["approved_quantity"] == 120 and "piece_rate" not in sm_item["approval"]
        assert fin_item["approval"]["piece_rate"] == 5
        assert "labor_piece_rate" not in str(sm.json()["packages"])
    run(monkeypatch, scenario, backend)


def test_quantity_entry_follows_r36(monkeypatch, backend):
    async def scenario(c, op):
        # another worker / a technician cannot enter a quantity on someone else's report
        for who in ("w-month", "tech", "sm-other"):
            r = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 1}, headers=H(who, False))
            assert r.status_code == 403, who
        for bad in (-1, "x"):
            r = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": bad}, headers=H("w-ak", False))
            assert r.status_code == 422, bad
        r = await c.put("/api/labor-quantities/entry", content='{"report_id": "R-AK", "quantity": 1e999}',
                        headers=dict(H("w-ak", False), **{"Content-Type": "application/json"}))
        assert r.status_code == 422                                   # non-finite
        # after submit, the author cannot change it any more (400); an approver can (R36)
        await op.employee_daily_reports.update_one({"id": "R-AK"}, {"$set": {"status": "Submitted"}})
        assert (await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 5},
                            headers=H("w-ak", False))).status_code == 400
        assert (await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 5},
                            headers=H("sm", False))).status_code == 200
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════ LAB-01-I four-eyes here too
def test_quantity_correction_reopens_the_report_and_the_corrector_cannot_approve(monkeypatch, backend):
    async def scenario(c, op):
        await _approve_flow(c, op)
        r = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 130},
                        headers=H("admin", False))
        assert r.status_code == 200 and r.json()["status"] == "SUBMITTED"
        doc = await op.employee_daily_reports.find_one({"id": "R-AK"}, {"_id": 0})
        assert doc["approved_by"] is None and doc["correctors"] == ["admin"]
        assert await op.dq_alerts.count_documents({"code": "DAILY_REPORT_CORRECTED_AFTER_APPROVAL"}) == 1
        body = {"report_id": "R-AK", "report_version": doc["report_version"], "approved_quantity": 130,
                "execution_package_id": "pkg-sh"}
        assert (await c.post("/api/labor-quantities/approve", json=body, headers=H("admin"))).status_code == 403
        assert (await c.post("/api/labor-quantities/approve", json=body, headers=H("sm"))).status_code == 200
    run(monkeypatch, scenario, backend)
