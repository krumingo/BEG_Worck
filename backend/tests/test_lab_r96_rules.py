"""
LAB-R96-T — step 1 of the approved map "Един вход за труда" (Р100, with Р96, Р101, Р102).

Tests only. They encode the TARGET rules of Р100 against the real routes as they are on
de720f94. A rule that does not hold today is marked
``xfail(strict=True, reason="Р100: <rule> — fixed by LAB-R96 step N")``: the suite is green
today, and the moment a fixing commit makes the behaviour right the test XPASSes, which
``strict`` turns into a hard failure — the fixing commit must remove the marker. A rule that
already holds today is a plain test, so it stays protected.

Р100 steps used in the reasons: 2 = one service "Отчет на труда" (one write path, one line =
person × day × project × activity, conflict "Вече има отчет", presence / backdate / four-eyes
checks); 3 = one read (P&L, ведомост, "Приходи/разходи" read the same approved lines, one
rate/overtime formula); 4 = payment locks the line (both stored report formats). Р101 (the
clock "Започни / Приключи" removed) is done inside step 2.

This file: rules 1 (one line, every other path refused), 5 (presence), 6 (backdating, FLOW-014),
8 (four-eyes), 9 (Р101 clock). ``test_lab_r96_money_rules.py``: rules 2, 3, 4, 7, 10.

Fixture (one tenant, one project ``P``, activity ``A`` = "Шпакловка"):
  W0 hourly 12 €/h, W1 daily 110 €/day, W2 monthly 2200 €/month (22 d × 8 h);
  attendance "Present" on P today for each worker unless the case says otherwise;
  Admin, Owner, SiteManager (member of P), Technician (member of P).

Runs in-process (FastAPI app with the real routers, httpx ASGI transport, a real JWT that
``get_current_user`` resolves) against ``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL``
names a disposable LOCAL MongoDB, again against it — one fresh database per test
(``fixtest_lab_<hex>``), dropped afterwards.

    PYTHONPATH=. pytest tests/test_lab_r96_rules.py tests/test_lab_r96_money_rules.py -v --noconftest -p no:cacheprovider
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27091/?directConnection=true&replicaSet=rs0' \\
        PYTHONPATH=. pytest tests/test_lab_r96_rules.py tests/test_lab_r96_money_rules.py -v --noconftest -p no:cacheprovider
"""
import asyncio
import importlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

ORG = "ORG-LABR96"
P = "prj-lab-p"
P2 = "prj-lab-p2"           # a second object (presence "elsewhere")
A = "Шпакловка"
WT_A = "wt-lab-a"           # /daily-logs work type for A
GRP_A = "grp-lab-a"         # SMR group for A
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
WEEK = ((datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d"), TODAY)

W0, W1, W2 = "w0-hourly", "w1-daily", "w2-monthly"
PROFILES = {
    W0: {"pay_type": "Hourly", "hourly_rate": 12},
    W1: {"pay_type": "Daily", "daily_rate": 110},
    W2: {"pay_type": "Monthly", "monthly_salary": 2200, "working_days_per_month": 22,
         "standard_hours_per_day": 8},
}
STAFF = {"admin": "Admin", "owner": "Owner", "sm": "SiteManager", "tech": "Technician"}
DB_PREFIX = "fixtest_lab_"
LABOR_COLLECTIONS = ("employee_daily_reports", "work_reports", "daily_work_logs",
                     "smr_group_reports", "work_sessions", "missing_smr", "attendance_entries")
ROUTERS = ("technician", "daily_reports", "attendance", "work_logs", "smr_groups", "pay_runs",
           "project_pnl", "work_sessions", "revenue_expense")


def r100(step, rule):
    return pytest.mark.xfail(strict=True, reason="Р100: %s — fixed by LAB-R96 step %s" % (rule, step))


# ═══════════════════════════════════════════════════════════════════ backends
def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


class _Db:
    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, DB_PREFIX + uuid.uuid4().hex[:10]

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
            assert self.name.startswith(DB_PREFIX)
            await self.client.drop_database(self.name)
            self.client.close()


# ═══════════════════════════════════════════════════════════════════ fixture data
async def seed(op, present=(W0, W1, W2)):
    await op.organizations.insert_one({"id": ORG, "name": "LAB R96"})
    await op.subscriptions.insert_one({"org_id": ORG, "plan_id": "enterprise", "status": "active"})
    for uid, role in STAFF.items():
        await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                   "email": uid + "@labr96.example", "first_name": uid,
                                   "last_name": "Staff"})
    for wid, prof in PROFILES.items():
        await op.users.insert_one({"id": wid, "org_id": ORG, "role": "Worker", "is_active": True,
                                   "email": wid + "@labr96.example", "first_name": wid.upper(),
                                   "last_name": "Worker"})
        await op.employee_profiles.insert_one(dict(prof, org_id=ORG, user_id=wid))
    await op.projects.insert_many([
        {"id": P, "org_id": ORG, "name": "Обект P", "code": "P-1", "status": "Active"},
        {"id": P2, "org_id": ORG, "name": "Обект P2", "code": "P-2", "status": "Active"}])
    for uid, role in (("sm", "SiteManager"), ("tech", "Technician")):
        await op.project_team.insert_one({"id": "pt-" + uid, "org_id": ORG, "project_id": P,
                                          "user_id": uid, "role_in_project": role, "active": True})
    await op.work_types.insert_one({"id": WT_A, "org_id": ORG, "name": A, "is_active": True})
    await op.smr_groups.insert_one({"id": GRP_A, "org_id": ORG, "project_id": P, "name": A})
    await op.financial_accounts.insert_one({"id": "acc-lab-cash", "org_id": ORG, "type": "Cash",
                                            "name": "Каса"})
    for wid in present:
        await mark(op, wid, "Present")


async def mark(op, wid, status, project=P, day=TODAY):
    await op.attendance_entries.insert_one({
        "id": "att-%s-%s-%s" % (wid, project, day), "org_id": ORG, "date": day,
        "project_id": project, "user_id": wid, "status": status, "marked_by_user_id": "sm"})


def headers(uid):
    from app.deps.auth import create_token
    role = STAFF.get(uid, "Worker")
    return {"Authorization": "Bearer " + create_token({"user_id": uid, "org_id": ORG, "role": role})}


def _patch_db(monkeypatch, op):
    """Point every loaded ``app.*`` module's ``db`` at the scratch database."""
    from app.master_data.deps import ENV_MODE
    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for name in ROUTERS:
        importlib.import_module("app.routes." + name)
    for name in ("app.services.hours_validator", "app.services.project_guards",
                 "app.utils.audit", "app.audit.store"):
        try:
            importlib.import_module(name)
        except ImportError:
            pass
    import app.db as appdb
    monkeypatch.setattr(appdb, "db", op)
    for mname, mod in list(sys.modules.items()):
        if mod is None or not (mname == "app" or mname.startswith("app.")):
            continue
        cur = getattr(mod, "db", None)
        if cur is not None and "Database" in type(cur).__name__:
            monkeypatch.setattr(mod, "db", op)


def _app():
    from fastapi import FastAPI
    app = FastAPI()
    for name in ROUTERS:
        app.include_router(importlib.import_module("app.routes." + name).router, prefix="/api")
    return app


def run(monkeypatch, backend, scenario, present=(W0, W1, W2)):
    """Fresh seeded database + in-process client; ``scenario(c, op)``."""
    import httpx

    async def body():
        async with _Db(backend) as op:
            await seed(op, present)
            _patch_db(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()),
                                         base_url="http://labr96") as c:
                return await scenario(c, op)
    return asyncio.run(body())


# ═══════════════════════════════════════════════════════════════════ the paths
async def tech_report(c, wid=W0, hours=8, day=TODAY, who="tech", project=P):
    return await c.post("/api/technician/daily-report", headers=headers(who), json={
        "project_id": project, "date": day,
        "entries": [{"worker_id": wid, "worker_name": wid.upper(), "smr_type": A, "hours": hours}]})


async def daily_report(c, wid=W0, hours=8, day=TODAY, who="admin", notes=None):
    return await c.post("/api/daily-reports", headers=headers(who), json={
        "employee_id": wid, "report_date": day, "day_status": "WORKING", "notes": notes,
        "day_entries": [{"project_id": P, "work_description": A, "hours_worked": hours}]})


async def batch_save(c, wid=W0, hours=8, day=TODAY, who="admin"):
    return await c.post("/api/daily-reports/batch-save", headers=headers(who), json={
        "project_id": P, "report_date": day,
        "entries": [{"employee_id": wid, "work_description": A, "hours_worked": hours}]})


async def work_report_draft(c, wid=W0, hours=8, day=TODAY, who=None):
    """The worker's own report (``/work-reports/draft`` then its lines)."""
    r = await c.post("/api/work-reports/draft", headers=headers(wid),
                     json={"project_id": P, "date": day})
    if r.status_code < 300:
        rl = await c.put("/api/work-reports/" + r.json()["id"], headers=headers(wid),
                         json={"lines": [{"activity_name": A, "hours": hours}]})
        assert rl.status_code == 200, rl.text
    return r


async def daily_log(c, wid=W0, hours=8, day=TODAY, who="admin"):
    return await c.post("/api/daily-logs", headers=headers(who), json={
        "site_id": P, "date": day, "work_type_id": WT_A,
        "entries": [{"user_id": wid, "hours": hours}]})


async def smr_group_report(c, wid=W0, hours=8, day=TODAY, who="admin"):
    """The group SMR report has no person/day fields of its own; the line carries them."""
    return await c.post("/api/smr-groups/%s/report" % GRP_A, headers=headers(who), json={
        "mode": "per_line", "line_reports": [{"worker_id": wid, "date": day, "smr_type": A,
                                              "hours": hours}]})


SECOND_PATHS = {
    "technician_again": tech_report,
    "daily_reports": daily_report,
    "batch_save": batch_save,
    "work_report_draft": work_report_draft,
    "daily_logs": daily_log,
    "smr_group_report": smr_group_report,
}


async def approve(c, rid, who="admin"):
    return await c.post("/api/daily-reports/%s/approve" % rid, headers=headers(who), json={})


async def snapshot(op, collections=LABOR_COLLECTIONS):
    import bson
    snap = {}
    for coll in collections:
        docs = await op[coll].find({}, {"_id": 0}).to_list(10000)
        snap[coll] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d)}) for d in docs)
    return snap


def changed(before, after):
    return sorted(k for k in before if before[k] != after[k])


def is_conflict(r):
    text = r.text.lower()
    return 400 <= r.status_code < 500 and ("already exists" in text or "вече има" in text)


# ═══════════════════════════════════════════════════════════════════ rule 1
@pytest.mark.parametrize("path", list(SECOND_PATHS))   # xfail removed: fixed by LAB-R96 step 2
def test_r1_second_entry_for_same_person_day_project_activity_is_refused(monkeypatch, backend, path):
    """Rule 1 (Р100: "Един ред = човек × ден × обект × дейност. Втори вход за същото показва
    видим конфликт „Вече има отчет“"; Р96; FLOW-013/014).

    After the technician daily report for W0 8 h on P / A today, a second entry for the
    same W0 / day / P / A through ``path`` must be refused (4xx, "already exists" /
    "вече има") and write nothing.

    Today on de720f94 every path accepts it and writes a second line:
      technician_again  200, a 2nd Draft line in employee_daily_reports (16 h for the day);
      daily_reports     201, an old-format report (employee_id/day_entries, 8 h) — the
                        duplicate check only looks at old-format reports;
      batch_save        200 {"employees_saved": 1}, an old-format report;
      work_report_draft 201, a work_reports draft of W0 (+ 8 h line);
      daily_logs        201, a daily_work_logs row with W0 8 h;
      smr_group_report  200, a smr_group_reports row with 8 h.
    """
    async def scenario(c, op):
        first = await tech_report(c)
        assert first.status_code == 200, first.text
        before = await snapshot(op)
        r = await SECOND_PATHS[path](c)
        after = await snapshot(op)
        assert is_conflict(r), (path, r.status_code, r.text[:300])
        assert changed(before, after) == [], (path, changed(before, after))
    run(monkeypatch, backend, scenario)


def test_r1_holds_today_old_format_report_twice_is_refused(monkeypatch, backend):
    """Rule 1, the part that holds today: ``POST /daily-reports`` twice for the same
    employee and date → 400 "Report already exists …", nothing written. (Р100, FLOW-014.)"""
    async def scenario(c, op):
        assert (await daily_report(c)).status_code == 201
        before = await snapshot(op)
        r = await daily_report(c)
        assert r.status_code == 400 and "already exists" in r.text, r.text
        assert changed(before, await snapshot(op)) == []
    run(monkeypatch, backend, scenario)


def test_r1_holds_today_daily_log_twice_is_refused(monkeypatch, backend):
    """Rule 1, the part that holds today: ``POST /daily-logs`` twice for the same site,
    date and work type → 400 "… already exists", nothing written. (Р100.)"""
    async def scenario(c, op):
        assert (await daily_log(c)).status_code == 201
        before = await snapshot(op)
        r = await daily_log(c)
        assert r.status_code == 400 and "already exists" in r.text, r.text
        assert changed(before, await snapshot(op)) == []
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ rule 5
async def _not_present(op, case):
    if case == "sick":
        await mark(op, W0, "SickLeave")
    elif case == "elsewhere":
        await mark(op, W0, "Present", project=P2)


PRESENCE_TODAY = {   # (path, case) → holds today?
    ("technician", "absent"): True, ("technician", "sick"): True,
    ("technician", "elsewhere"): True,
    ("work_report_draft", "absent"): True, ("work_report_draft", "sick"): True,
    ("work_report_draft", "elsewhere"): False,
}
PRESENCE_PATHS = {"technician": tech_report, "daily_reports": daily_report,
                  "batch_save": batch_save, "work_report_draft": work_report_draft,
                  "daily_logs": daily_log, "smr_group_report": smr_group_report}


def _presence_cases():
    out = []
    for path in PRESENCE_PATHS:
        for case in ("absent", "sick", "elsewhere"):
            if case == "elsewhere" and path not in ("technician", "work_report_draft"):
                continue
            # every case holds since LAB-R96 step 2 (one presence check in the service)
            out.append(pytest.param(path, case, id="%s-%s" % (path, case)))
    return out


@pytest.mark.parametrize("path,case", _presence_cases())
def test_r5_report_for_person_not_present_on_project_day_is_refused(monkeypatch, backend, path, case):
    """Rule 5 (Р100 one service with the FLOW-013 presence check on every path; FLOW-013
    L89-90 "отчет само за присъстващ на обекта"; FG-641).

    W0 is ``absent`` (no attendance), on ``sick`` leave (attendance SickLeave on P), or Present
    only ``elsewhere`` (on P2). A report for W0 on P today must be refused (4xx), nothing
    written.

    Today on de720f94: only the technician path checks (400 PRESENCE_REQUIRED_ON_OBJECT /
    "… е SickLeave"); ``/work-reports/draft`` checks presence for the day but not the object
    (absent/sick → 400, elsewhere → 201). ``/daily-reports`` 201, ``batch-save`` 200,
    ``/daily-logs`` 201, the SMR group report 200 — no presence check at all.
    """
    async def scenario(c, op):
        await _not_present(op, case)
        before = await snapshot(op)
        r = await PRESENCE_PATHS[path](c)
        after = await snapshot(op)
        assert 400 <= r.status_code < 500, (path, case, r.status_code, r.text[:300])
        assert changed(before, after) == [], (path, case, changed(before, after))
    run(monkeypatch, backend, scenario, present=(W1, W2))


# ═══════════════════════════════════════════════════════════════════ rule 6
BACKDATE_PATHS = {   # path → (writer, who) — every writer is a non-Admin/Owner role
    "technician": (tech_report, "tech"),
    "daily_reports": (daily_report, "sm"),
    "batch_save": (batch_save, "sm"),
    "work_report_draft": (work_report_draft, None),
    "daily_logs": (daily_log, "sm"),
}


@pytest.mark.parametrize("path", list(BACKDATE_PATHS))   # xfail removed: fixed by LAB-R96 step 2
def test_r6_backdated_report_by_non_admin_is_refused(monkeypatch, backend, path):
    """Rule 6 (FLOW-014: a report for a past date only by Admin/Owner, with a reason; Р100
    one service).

    W0 Present on P YESTERDAY; a Technician / SiteManager / the worker himself reports W0 on
    P for yesterday → must be refused (4xx), nothing written.

    Today on de720f94 no path checks the date: technician 200, ``/daily-reports`` (SiteManager)
    201, ``batch-save`` (SiteManager) 200, ``/work-reports/draft`` (W0) 201, ``/daily-logs``
    (SiteManager, project member) 201. (The SMR group report has no date field — not
    exercised.)
    """
    writer, who = BACKDATE_PATHS[path]

    async def scenario(c, op):
        await mark(op, W0, "Present", day=YESTERDAY)
        before = await snapshot(op)
        r = await writer(c, day=YESTERDAY, who=who)
        after = await snapshot(op)
        assert 400 <= r.status_code < 500, (path, r.status_code, r.text[:300])
        assert changed(before, after) == [], (path, changed(before, after))
    run(monkeypatch, backend, scenario)


def test_r6_holds_today_admin_may_backdate_with_reason(monkeypatch, backend):
    """Rule 6, the allowed side (FLOW-014): Admin reports W0 for yesterday with a reason
    (``notes``) on ``/daily-reports`` → 201. Holds today (no date check at all)."""
    async def scenario(c, op):
        await mark(op, W0, "Present", day=YESTERDAY)
        r = await daily_report(c, day=YESTERDAY, who="admin", notes="Забравен отчет — по телефона")
        assert r.status_code == 201, r.text
    run(monkeypatch, backend, scenario)


def test_r6_holds_today_today_report_by_technician_is_accepted(monkeypatch, backend):
    """Rule 6 control: the technician's report for TODAY (W0 Present on P) → 200, one Draft
    line of 8 h for W0 / P / A."""
    async def scenario(c, op):
        r = await tech_report(c)
        assert r.status_code == 200, r.text
        rows = await op.employee_daily_reports.find({"worker_id": W0}, {"_id": 0}).to_list(10)
        assert [(x["date"], x["project_id"], x["smr_type"], x["hours"], x["status"])
                for x in rows] == [(TODAY, P, A, 8, "Draft")]
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ rule 8
def test_r8_site_manager_cannot_approve_own_technician_report(monkeypatch, backend):
    """Rule 8 (Р100 "Одобрява друг човек"; taken from #75 four-eyes; FLOW-014 approval).

    The SiteManager submits the technician daily report for W0 8 h, then approves it himself
    → must be 403 and the report stays unapproved.

    Today on de720f94: 200, the report becomes APPROVED with approved_by == submitted_by
    == "sm" and a work_session (labor_cost 96) is written.
    """
    async def scenario(c, op):
        r = await tech_report(c, who="sm")
        assert r.status_code == 200, r.text
        rid = r.json()["draft_report_ids"][0]
        ra = await approve(c, rid, who="sm")
        doc = await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        assert ra.status_code == 403, (ra.status_code, doc.get("approved_by"), doc.get("submitted_by"))
        assert doc.get("status") != "APPROVED"
        assert await op.work_sessions.count_documents({"approved_report_id": rid}) == 0
    run(monkeypatch, backend, scenario)


def test_r8_admin_cannot_approve_own_daily_report(monkeypatch, backend):
    """Rule 8 on the office path: Admin creates W0's report on ``/daily-reports`` and approves
    it himself → must be 403. Today on de720f94: 200, approval_status APPROVED, approved_by
    == created_by == "admin"."""
    async def scenario(c, op):
        r = await daily_report(c, who="admin")
        assert r.status_code == 201, r.text
        ra = await approve(c, r.json()["id"], who="admin")
        doc = await op.employee_daily_reports.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert ra.status_code == 403, (ra.status_code, doc.get("approved_by"), doc.get("created_by"))
        assert doc.get("approval_status") != "APPROVED"
    run(monkeypatch, backend, scenario)


def test_r8_holds_today_another_person_approves(monkeypatch, backend):
    """Rule 8, the allowed side: Technician submits, Admin (another person) approves → 200,
    APPROVED, approved_by "admin", one work_session for the report."""
    async def scenario(c, op):
        r = await tech_report(c, who="tech")
        rid = r.json()["draft_report_ids"][0]
        ra = await approve(c, rid, who="admin")
        assert ra.status_code == 200, ra.text
        doc = await op.employee_daily_reports.find_one({"id": rid}, {"_id": 0})
        assert (doc["status"], doc["approved_by"], doc["submitted_by"]) == ("APPROVED", "admin", "tech")
        assert await op.work_sessions.count_documents({"approved_report_id": rid}) == 1
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ rule 9
def test_r9_clock_start_is_refused(monkeypatch, backend):
    """Rule 9 (Р101: "сървърът спира да приема нови стартове и спирания"; Р96/Р100: labor only
    through the daily report).

    W0 ``POST /work-sessions/start`` on P → must be 4xx and no work_session written.
    Today on de720f94: 201 and an open work_session (ended_at None, hourly_rate_at_date 12).
    """
    async def scenario(c, op):
        r = await c.post("/api/work-sessions/start", headers=headers(W0), json={"site_id": P})
        assert 400 <= r.status_code < 500, (r.status_code, r.text[:200])
        assert await op.work_sessions.count_documents({}) == 0
    run(monkeypatch, backend, scenario)


async def _seed_open_clock_session(op, wid=W0, started="T08:00:00+00:00", day=TODAY, rate=12):
    sid = "ws-clock-" + wid
    await op.work_sessions.insert_one({
        "id": sid, "org_id": ORG, "worker_id": wid, "worker_name": wid.upper(), "site_id": P,
        "site_name": "Обект P", "smr_type_id": A, "started_at": day + started, "ended_at": None,
        "source_method": "SELF_REPORT", "is_flagged": False, "flag_reason": None,
        "duration_hours": None, "is_overtime": False, "overtime_type": None,
        "overtime_coefficient": 1.0, "hourly_rate_at_date": rate, "labor_cost": None,
        "created_at": day + started, "updated_at": day + started})
    return sid


def test_r9_clock_end_is_refused(monkeypatch, backend):
    """Rule 9 (Р101): an open clock session of W0 (an old record) — ``POST /work-sessions/end``
    → must be 4xx and the record stays as it was. Today on de720f94: 200, the session is
    closed (ended_at set, duration and labor_cost computed from the wall clock)."""
    async def scenario(c, op):
        sid = await _seed_open_clock_session(op)
        before = await snapshot(op, ("work_sessions",))
        r = await c.post("/api/work-sessions/end", headers=headers(W0), json={})
        assert 400 <= r.status_code < 500, (r.status_code, r.text[:200])
        assert changed(before, await snapshot(op, ("work_sessions",))) == []
        assert (await op.work_sessions.find_one({"id": sid}))["ended_at"] is None
    run(monkeypatch, backend, scenario)


def test_r9_holds_today_old_clock_records_stay_in_history(monkeypatch, backend):
    """Rule 9, what stays (Р101 "Старите записи от часовника остават в историята (без
    изтриване)"): an old closed clock session is still listed by ``GET /work-sessions``."""
    async def scenario(c, op):
        sid = await _seed_open_clock_session(op)
        await op.work_sessions.update_one({"id": sid}, {"$set": {
            "ended_at": TODAY + "T16:00:00+00:00", "duration_hours": 8, "labor_cost": 96}})
        r = await c.get("/api/work-sessions", headers=headers("admin"))
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items", body) if isinstance(body, dict) else body
        assert sid in [s["id"] for s in items], body
    run(monkeypatch, backend, scenario)
