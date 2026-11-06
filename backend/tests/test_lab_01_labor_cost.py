"""
LAB-01 — labor cost per FLOW-019 / FLOW-028 (CLAUDE.md §7, R31), from approved reports only.

docs/architecture/tasks/LAB-01_LABOR_COST_PER_FLOW_019_028.md — tests:

* akord 40 h, 120 m2 approved × 5 → 600 by quantity (not by hours); an unapproved
  quantity does not count; no piece rate → DQ + 0;
* salary: only approved hours; a draft does not count; no rate → DQ, not 25;
* downtime apart; the SMR sum = the sum of the lines; the Pay Run and "изхарчено" give
  ONE number for one person / period;
* the labor sync reads approved work reports only;
* an existing confirmed Pay Run is not re-priced; an open one only by an explicit edit,
  with old → new kept in its history.

Pure-function cases run without a database. The route cases run in-process against
``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB,
again against it (one database per test, dropped afterwards). Authentication is real.

    pytest tests/test_lab_01_labor_cost.py -v --noconftest
    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27017 pytest tests/test_lab_01_labor_cost.py -v --noconftest
"""
import asyncio
import uuid

import pytest

from app.services.labor_cost import (
    DQ_AKORD_NO_APPROVED_QTY, DQ_AKORD_NO_PIECE_RATE, DQ_MISSING_RATE,
    compute_person_labor,
)

ORG = "ORG-LAB01"
P_START, P_END = "2026-10-05", "2026-10-11"
DAYS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]


def _ln(rid, day="2026-10-05", hours=8, status="APPROVED", **kw):
    d = {"id": rid, "worker_id": "w", "date": day, "hours": hours, "status": status,
         "project_id": "prj", "smr_type": "Шпакловка"}
    d.update(kw)
    return d


# ═══════════════════════════════════════════════════════════════ pure: akord
def test_akord_is_approved_quantity_times_piece_rate_not_hours():
    # 40 h; the profile has an hourly rate 20 → hours × rate would be 800 (FG-48)
    prof = {"pay_type": "Akord", "hourly_rate": 20}
    lines = [_ln("r%d" % i, DAYS[i], 8, approved_quantity=24, unit="m2", piece_rate=5) for i in range(5)]
    lc = compute_person_labor(prof, lines)
    assert lc["total"] == 600.0 and lc["akord_total"] == 600.0
    assert all(r["amount"] == 120.0 and r["pay_type"] == "Akord" for r in lc["lines"])
    assert lc["approved_hours"] == 40
    assert "m2 × 5" in lc["lines"][0]["formula"]
    assert lc["dq_warnings"] == []


def test_akord_unapproved_quantity_does_not_count():
    prof = {"pay_type": "Akord", "hourly_rate": 20}
    # quantity entered but not approved; and a whole report still a draft
    lines = [_ln("r1", quantity=120, unit="m2", piece_rate=5),
             _ln("r2", status="DRAFT", approved_quantity=120, piece_rate=5)]
    lc = compute_person_labor(prof, lines)
    assert lc["total"] == 0.0
    assert [r["report_id"] for r in lc["excluded"]] == ["r2"]
    assert [w["code"] for w in lc["dq_warnings"]] == [DQ_AKORD_NO_APPROVED_QTY]


def test_akord_without_piece_rate_is_dq_and_zero_never_the_hourly_rate():
    prof = {"pay_type": "Akord", "hourly_rate": 20}
    lc = compute_person_labor(prof, [_ln("r1", approved_quantity=120, unit="m2")])
    assert lc["total"] == 0.0
    assert [w["code"] for w in lc["dq_warnings"]] == [DQ_AKORD_NO_PIECE_RATE]


def test_pay_type_and_piece_rate_come_from_the_line_or_smr_before_the_profile():
    prof = {"pay_type": "Daily", "daily_rate": 100}
    terms = {"pkg-1": {"id": "pkg-1", "labor_pay_type": "Akord", "labor_piece_rate": 4}}
    lines = [_ln("a", DAYS[0], 8, execution_package_id="pkg-1", approved_quantity=50),   # SMR → akord
             _ln("b", DAYS[1], 8, pay_type="Akord", piece_rate=3, approved_quantity=10),  # line → akord
             _ln("c", DAYS[2], 8)]                                                          # profile → daily
    lc = compute_person_labor(prof, lines, terms)
    by = {r["report_id"]: r for r in lc["lines"]}
    assert (by["a"]["pay_type_source"], by["a"]["amount"]) == ("smr", 200.0)
    assert (by["b"]["pay_type_source"], by["b"]["amount"]) == ("line", 30.0)
    assert (by["c"]["pay_type_source"], by["c"]["amount"]) == ("profile", 100.0)
    assert lc["total"] == 330.0


# ═══════════════════════════════════════════════════════════════ pure: salary
def test_salary_only_approved_hours_draft_excluded():
    prof = {"pay_type": "Hourly", "hourly_rate": 12.5}
    lines = [_ln("r1", DAYS[0], 8), _ln("r2", DAYS[1], 8, status="DRAFT"),
             _ln("r3", DAYS[2], 8, status="SUBMITTED")]
    lc = compute_person_labor(prof, lines)
    assert lc["total"] == 100.0
    assert sorted(r["report_id"] for r in lc["excluded"]) == ["r2", "r3"]


def test_missing_rate_is_dq_not_a_default_rate():
    for prof in ({"pay_type": "Hourly"}, {"pay_type": "Daily"}, {}):
        lc = compute_person_labor(prof, [_ln("r1")])
        assert lc["total"] == 0.0, prof
        assert [w["code"] for w in lc["dq_warnings"]] == [DQ_MISSING_RATE], prof


def test_downtime_is_its_own_cost_and_the_line_sum_is_the_total():
    prof = {"pay_type": "Monthly", "monthly_salary": 2200, "working_days_per_month": 22}
    lines = [_ln("r1", DAYS[0], 6), _ln("d1", DAYS[0], 2, cost_type="DOWNTIME"),
             _ln("r2", DAYS[1], 3, smr_type="Боя"), _ln("r3", DAYS[1], 4),
             _ln("r4", DAYS[2], 7)]
    lc = compute_person_labor(prof, lines)
    assert lc["total"] == 300.0                        # 3 days × 100
    by = {r["report_id"]: r for r in lc["lines"]}
    assert by["d1"]["cost_type"] == "DOWNTIME" and by["d1"]["amount"] == 25.0
    assert by["r1"]["amount"] == 75.0
    assert lc["downtime_total"] == 25.0 and lc["labor_total"] == 275.0
    assert round(sum(r["amount"] for r in lc["lines"]), 2) == lc["total"]


def test_split_keeps_cents_exact():
    prof = {"pay_type": "Daily", "daily_rate": 100}
    lines = [_ln("a", DAYS[0], 1), _ln("b", DAYS[0], 1), _ln("c", DAYS[0], 1)]
    lc = compute_person_labor(prof, lines)
    assert sorted(r["amount"] for r in lc["lines"]) == [33.33, 33.33, 33.34]
    assert lc["total"] == 100.0


# ═══════════════════════════════════════════════════════════════ database
def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


WORKERS = {
    # worker → profile
    "w-akord": {"pay_type": "Akord", "hourly_rate": 15},
    "w-month": {"pay_type": "Monthly", "monthly_salary": 2200, "working_days_per_month": 22},
    "w-norate": {"pay_type": "Hourly"},
}


def _report(rid, wid, day, project, hours, status="APPROVED", **kw):
    d = {"id": rid, "org_id": ORG, "worker_id": wid, "date": day, "hours": hours,
         "project_id": project, "smr_type": kw.pop("smr_type", "Шпакловка"),
         "status": status, "payroll_status": "none", "created_at": day + "T17:00:00"}
    d.update(kw)
    return d


async def _seed(op):
    await op.organizations.insert_one({"id": ORG, "name": "Org LAB-01"})
    await op.users.insert_one({"id": "admin", "org_id": ORG, "role": "Admin", "is_active": True,
                               "email": "admin@lab01.example", "first_name": "A", "last_name": "Admin"})
    await op.projects.insert_many([{"id": "prj-1", "org_id": ORG, "name": "Site 1"},
                                   {"id": "prj-2", "org_id": ORG, "name": "Site 2"}])
    for wid, prof in WORKERS.items():
        await op.users.insert_one({"id": wid, "org_id": ORG, "role": "Worker", "is_active": True,
                                   "email": wid + "@lab01.example", "first_name": wid, "last_name": "W"})
        await op.employee_profiles.insert_one(dict(prof, org_id=ORG, user_id=wid))
    reps = []
    # akord: 40 h, 5 × 24 m2 approved × 5 EUR → 600; one more line with an UNAPPROVED quantity
    for i, d in enumerate(DAYS):
        reps.append(_report("ak-%d" % i, "w-akord", d, "prj-1", 8, approved_quantity=24,
                            quantity=24, unit="m2", piece_rate=5))
    reps.append(_report("ak-x", "w-akord", "2026-10-10", "prj-1", 4, quantity=30, unit="m2", piece_rate=5))
    # monthly: 100 / day; split between two projects on one day; a downtime line; a draft
    reps += [
        _report("m-1", "w-month", DAYS[0], "prj-1", 8),
        _report("m-2a", "w-month", DAYS[1], "prj-1", 4),
        _report("m-2b", "w-month", DAYS[1], "prj-2", 4),
        _report("m-3", "w-month", DAYS[2], "prj-1", 6, smr_type="Боя"),
        _report("m-3d", "w-month", DAYS[2], "prj-1", 2, cost_type="DOWNTIME"),
        _report("m-4", "w-month", DAYS[3], "prj-1", 8, status="Draft"),
    ]
    reps.append(_report("n-1", "w-norate", DAYS[0], "prj-1", 8))
    await op.employee_daily_reports.insert_many(reps)


def _token():
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token(
        {"user_id": "admin", "org_id": ORG, "role": "Admin"})}


def _app(monkeypatch, op):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.master_data.deps import ENV_MODE
    from app.routes import activity_budgets, labor_smr, pay_runs
    from app.services import expected_actual, labor_cost, payroll_sync, project_pnl, report_normalizer
    from app.tenancy import project_team

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, pay_runs, payroll_sync, report_normalizer, labor_cost,
                   labor_smr, expected_actual, activity_budgets, project_pnl, project_team):
        if hasattr(module, "db"):
            monkeypatch.setattr(module, "db", op)
    app = FastAPI()
    app.include_router(pay_runs.router, prefix="/api")
    return app


class _Db:
    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, "lab01_" + uuid.uuid4().hex[:10]

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
            assert self.name not in await self.client.list_database_names()
            self.client.close()


def run(monkeypatch, scenario, backend):
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://lab01") as c:
                return await scenario(c, op)
    return asyncio.run(body())


async def _preview(c):
    r = await c.get("/api/pay-runs/generate", params={"period_start": P_START, "period_end": P_END},
                    headers=_token())
    assert r.status_code == 200, r.text
    return {x["employee_id"]: x for x in r.json()["rows"]}


def test_pay_run_akord_by_quantity_and_unapproved_quantity_out(monkeypatch, backend):
    async def scenario(c, op):
        rows = await _preview(c)
        ak = rows["w-akord"]
        assert ak["earned_amount"] == 600.0              # 120 m2 × 5, not 44 h × 15 = 660
        assert ak["akord_amount"] == 600.0
        assert [w["code"] for w in ak["labor_dq_warnings"]] == [DQ_AKORD_NO_APPROVED_QTY]
        # per-report values in the calendar add up to the row
        vals = [rep["value"] for dc in ak["day_cells"] for rep in dc["reports"]]
        assert round(sum(vals), 2) == 600.0
    run(monkeypatch, scenario, backend)


def test_pay_run_salary_no_draft_no_default_rate(monkeypatch, backend):
    async def scenario(c, op):
        rows = await _preview(c)
        m = rows["w-month"]
        assert m["earned_amount"] == 300.0               # 3 approved days × 100; the draft day out
        assert m["downtime_amount"] == 25.0
        n = rows["w-norate"]
        assert n["earned_amount"] == 0.0                 # no rate → 0 + DQ (never 25/h)
        assert [w["code"] for w in n["labor_dq_warnings"]] == [DQ_MISSING_RATE]
    run(monkeypatch, scenario, backend)


def test_pay_run_and_spent_by_smr_are_one_number(monkeypatch, backend):
    async def scenario(c, op):
        from app.services.labor_cost import project_labor_cost
        from app.services.expected_actual import build_expected_actual
        rows = await _preview(c)
        p1 = await project_labor_cost(ORG, "prj-1", P_START, P_END)
        p2 = await project_labor_cost(ORG, "prj-2", P_START, P_END)
        for wid in ("w-month", "w-akord", "w-norate"):
            per_person = round(sum(r["amount"] for r in p1["lines"] + p2["lines"] if r["worker_id"] == wid), 2)
            assert per_person == rows[wid]["earned_amount"], wid
        # SMR sum = sum of lines; downtime is not inside any SMR
        assert round(sum(v["labor"] for v in p1["by_smr"].values()), 2) == p1["labor_total"]
        assert p1["by_smr"]["Шпакловка"]["labor"] == 600.0 + 100.0 + 50.0
        assert p1["by_smr"]["Боя"]["labor"] == 75.0
        assert p1["downtime_total"] == 25.0
        assert p2["total"] == 50.0
        ea = await build_expected_actual(ORG, "prj-1", P_START, P_END)
        assert ea["summary"]["labor_actual_cost"] == p1["labor_total"] == 825.0
        assert ea["summary"]["downtime_cost"] == 25.0
        assert ea["downtime"]["actual_cost"] == 25.0
        assert {a["name"]: a["actual_cost"] for a in ea["activities"]} == {"Шпакловка": 750.0, "Боя": 75.0}
        # "изхарчено" exposes no per-person money (R31)
        assert "lines" not in ea
    run(monkeypatch, scenario, backend)


def test_confirmed_pay_run_is_not_repriced_open_one_only_by_edit(monkeypatch, backend):
    async def scenario(c, op):
        old_row = {"employee_id": "w-akord", "first_name": "w-akord", "last_name": "W",
                   "earned_amount": 660.0, "paid_now_amount": 0, "approved_hours": 44,
                   "approved_days": 6, "frozen_hourly_rate": 15, "selected_report_ids": []}
        for rid_, status in (("run-confirmed", "confirmed"), ("run-draft", "draft")):
            await op.pay_runs.insert_one({
                "id": rid_, "org_id": ORG, "number": rid_, "status": status, "version": 1,
                "period_start": P_START, "period_end": P_END, "week_number": 41,
                "employee_rows": [dict(old_row)], "paid_at": None, "op_lock": None,
                "totals": {"earned": 660.0}, "history": []})
        before = await op.pay_runs.find_one({"id": "run-confirmed"}, {"_id": 0})
        r = await c.get("/api/pay-runs/run-confirmed", headers=_token())
        assert r.status_code == 200, r.text
        assert r.json()["employee_rows"][0]["earned_amount"] == 660.0       # read never re-prices
        body = {"run_type": "weekly", "period_start": P_START, "period_end": P_END,
                "rows": [{"employee_id": "w-akord"}], "status": "draft"}
        r = await c.patch("/api/pay-runs/run-confirmed", json=body, headers=_token())
        assert r.status_code == 400                                          # confirmed: not editable
        assert await op.pay_runs.find_one({"id": "run-confirmed"}, {"_id": 0}) == before
        r = await c.patch("/api/pay-runs/run-draft", json=body, headers=_token())
        assert r.status_code == 200, r.text
        run_ = await op.pay_runs.find_one({"id": "run-draft"}, {"_id": 0})
        assert run_["employee_rows"][0]["earned_amount"] == 600.0
        assert run_["employee_rows"][0]["labor_calc"] == "LAB-01"
        assert run_["history"][-1]["labor_recalc"] == [
            {"employee_id": "w-akord", "old_earned": 660.0, "new_earned": 600.0, "calc": "LAB-01"}]
    run(monkeypatch, scenario, backend)


def test_labor_sync_reads_approved_work_reports_only(monkeypatch, backend):
    async def scenario(c, op):
        from app.routes.labor_smr import sync_labor_entries_from_work_reports
        await op.work_reports.insert_many([
            {"id": "wr-ok", "org_id": ORG, "project_id": "prj-1", "user_id": "w-month",
             "date": DAYS[0], "status": "Approved",
             "lines": [{"activity_name": "Шпакловка", "hours": 8}]},
            {"id": "wr-draft", "org_id": ORG, "project_id": "prj-1", "user_id": "w-month",
             "date": DAYS[1], "status": "Draft",
             "lines": [{"activity_name": "Шпакловка", "hours": 8}]},
            {"id": "wr-sub", "org_id": ORG, "project_id": "prj-1", "user_id": "w-month",
             "date": DAYS[2], "status": "Submitted",
             "lines": [{"activity_name": "Шпакловка", "hours": 8}]},
            {"id": "wr-ak", "org_id": ORG, "project_id": "prj-1", "user_id": "w-akord",
             "date": DAYS[0], "status": "Approved",
             "lines": [{"activity_name": "Шпакловка", "hours": 8, "approved_quantity": 30, "piece_rate": 5}]},
            {"id": "wr-nr", "org_id": ORG, "project_id": "prj-1", "user_id": "w-norate",
             "date": DAYS[0], "status": "Approved",
             "lines": [{"activity_name": "Шпакловка", "hours": 8}]},
        ])
        user = {"id": "admin", "org_id": ORG, "role": "Admin"}
        res = await sync_labor_entries_from_work_reports({"project_id": "prj-1"}, user)
        assert res["synced"] == 3
        entries = {e["work_report_id"]: e for e in await op.labor_entries.find({}, {"_id": 0}).to_list(100)}
        assert sorted(entries) == ["wr-ak", "wr-nr", "wr-ok"]
        assert entries["wr-ok"]["labor_cost"] == 100.0
        assert entries["wr-ak"]["labor_cost"] == 150.0                    # 30 × 5, not 8 h × 15
        assert entries["wr-nr"]["labor_cost"] is None                     # no rate → no cost, not 25
        assert entries["wr-nr"]["dq_warnings"] == [DQ_MISSING_RATE]
    run(monkeypatch, scenario, backend)
