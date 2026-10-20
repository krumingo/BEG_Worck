"""
R0-05 — a Pay Run processes ONLY the selected employees (AUD-023).

The 11 cases of docs/architecture/tasks/R0-05_PAY_RUN_SELECTED_ONLY.md,
positive and forbidden:

1. 3 employees with approved reports, 1 selected → exactly 1 row and 1 slip;
   the other two get no row, no slip, no allocation and their reports stay unbatched;
2. 2 of 3 selected → exactly 2 rows;
3. all selected → as before (earned per employee equals the preview);
4. an employee outside the preview for the period → 400, nothing written;
5. empty ``rows`` → 400, nothing written;
6. a row without ``paid_now_amount`` → paid_now = 0, not the remaining amount;
7. ``selected_report_ids`` of another employee / another tenant → 400, nothing written;
8. with ``selected_report_ids`` the earned amount comes from those reports only;
9. PATCH with the same cases 1–8 → the same behaviour (a refused PATCH leaves
   the stored run byte-equal);
10. Admin/Owner work, every other role → 403;
11. two tenants: a Pay Run of A does not touch B's employees.

The preview (``GET /pay-runs/generate``) still lists every employee — it is a preview.

Runs in-process against ``mongomock_motor`` and, when ``W0_03_REAL_MONGO_URL``
names a disposable LOCAL MongoDB, again against it — one database per test,
dropped afterwards. Authentication is real: a JWT the route verifies and a user
``get_current_user`` loads from the database.

    pytest tests/test_r0_05_pay_run_selected_only.py -v --noconftest
    W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:27018 pytest tests/test_r0_05_pay_run_selected_only.py -v --noconftest
"""
import asyncio
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

ORG_A, ORG_B = "ORG-R005-A", "ORG-R005-B"
P_START, P_END = "2026-10-05", "2026-10-11"
DAYS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]

# employee → (pay profile, expected earned for the 5 approved 8h days)
EMPLOYEES_A = {
    "emp-a1": ({"pay_type": "Daily", "daily_rate": 100}, 500.0),
    "emp-a2": ({"pay_type": "Hourly", "hourly_rate": 12.5}, 500.0),
    "emp-a3": ({"pay_type": "Daily", "daily_rate": 80}, 400.0),
}
IDLE_A = "emp-a4"          # active employee of A with NO reports → not in the preview
EMP_B = "emp-b1"
WRITE_COLLECTIONS = ("pay_runs", "payment_slips", "pay_run_allocations",
                     "payroll_payment_allocations", "finance_payments")


def _real_refusal():
    from tests.test_w0_03c_real_mongo import _refusal
    return _refusal()


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    """``mongomock`` always; ``real`` when W0_03_REAL_MONGO_URL is a local MongoDB."""
    return request.param


# ═══════════════════════════════════════════════════════════════════ helpers
def rid(eid, day):
    return "rep-%s-%s" % (eid, day[-2:])


def _report(org, eid, day, project):
    return {"id": rid(eid, day), "org_id": org, "worker_id": eid, "date": day, "hours": 8,
            "project_id": project, "status": "APPROVED", "payroll_status": "none",
            "created_at": day + "T17:00:00"}


async def _seed(op):
    for org in (ORG_A, ORG_B):
        await op.organizations.insert_one({"id": org, "name": "Org " + org})
    users = [("admin-a", ORG_A, "Admin"), ("owner-a", ORG_A, "Owner"),
             ("tech-a", ORG_A, "Technician"), ("acct-a", ORG_A, "Accountant"),
             ("admin-b", ORG_B, "Admin")]
    for uid, org, role in users:
        await op.users.insert_one({"id": uid, "org_id": org, "role": role, "is_active": True,
                                   "email": uid + "@r005.example", "first_name": uid,
                                   "last_name": "Staff"})
    await op.projects.insert_many([{"id": "prj-a", "org_id": ORG_A, "name": "Site A"},
                                   {"id": "prj-b", "org_id": ORG_B, "name": "Site B"}])
    staff = [(eid, ORG_A, prof) for eid, (prof, _) in EMPLOYEES_A.items()]
    staff += [(IDLE_A, ORG_A, {"pay_type": "Daily", "daily_rate": 90}),
              (EMP_B, ORG_B, {"pay_type": "Daily", "daily_rate": 70})]
    for eid, org, prof in staff:
        await op.users.insert_one({"id": eid, "org_id": org, "role": "Worker", "is_active": True,
                                   "email": eid + "@r005.example", "first_name": eid.upper(),
                                   "last_name": "Worker"})
        await op.employee_profiles.insert_one(dict(prof, org_id=org, user_id=eid))
    reports = [_report(ORG_A, eid, d, "prj-a") for eid in EMPLOYEES_A for d in DAYS]
    reports += [_report(ORG_B, EMP_B, d, "prj-b") for d in DAYS]
    await op.employee_daily_reports.insert_many(reports)


def _token(user_id, org_id, role):
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token(
        {"user_id": user_id, "org_id": org_id, "role": role})}


H = {
    "admin-a": lambda: _token("admin-a", ORG_A, "Admin"),
    "owner-a": lambda: _token("owner-a", ORG_A, "Owner"),
    "tech-a": lambda: _token("tech-a", ORG_A, "Technician"),
    "acct-a": lambda: _token("acct-a", ORG_A, "Accountant"),
    "admin-b": lambda: _token("admin-b", ORG_B, "Admin"),
}


def _app(monkeypatch, op):
    from fastapi import FastAPI
    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.master_data.deps import ENV_MODE
    from app.routes import pay_runs
    from app.services import payroll_sync, report_normalizer

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, pay_runs, payroll_sync, report_normalizer):
        monkeypatch.setattr(module, "db", op)
    app = FastAPI()
    app.include_router(pay_runs.router, prefix="/api")
    return app


class _Db:
    """A fresh, empty database on the chosen backend; a real one is dropped on exit."""

    def __init__(self, backend):
        self.backend, self.client, self.name = backend, None, "r0_05_" + uuid.uuid4().hex[:10]

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


def run(monkeypatch, scenario, backend="mongomock"):
    """Fresh seeded database + in-process client; ``scenario(c, op)``."""
    import httpx

    async def body():
        async with _Db(backend) as op:
            await _seed(op)
            app = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://r005") as c:
                return await scenario(c, op)
    return asyncio.run(body())


def row(eid, paid=None, report_ids=None):
    r = {"employee_id": eid}
    if paid is not None:
        r["paid_now_amount"] = paid
    if report_ids is not None:
        r["selected_report_ids"] = report_ids
    return r


def body(rows, status="confirmed"):
    return {"run_type": "weekly", "period_start": P_START, "period_end": P_END,
            "rows": rows, "status": status}


async def _create(c, rows, status="confirmed", who="admin-a"):
    return await c.post("/api/pay-runs", json=body(rows, status), headers=H[who]())


async def _patch(c, run_id, rows, status="confirmed", who="admin-a"):
    return await c.patch("/api/pay-runs/" + run_id, json=body(rows, status), headers=H[who]())


async def _snapshot(op):
    """Byte-level snapshot of every collection a Pay Run writes + the report statuses."""
    import bson
    snap = {}
    for coll in WRITE_COLLECTIONS + ("employee_daily_reports",):
        docs = await op[coll].find({}, {"_id": 0}).to_list(10000)
        snap[coll] = sorted(bson.BSON.encode({k: d[k] for k in sorted(d)}) for d in docs)
    return snap


async def _batched(op, org=ORG_A):
    docs = await op.employee_daily_reports.find(
        {"org_id": org, "payroll_status": "batched"}, {"_id": 0, "id": 1}).to_list(1000)
    return sorted(d["id"] for d in docs)


async def _assert_only(op, run, eids):
    """The run, its slips and allocations name exactly ``eids``; reports batched only for them."""
    assert sorted(r["employee_id"] for r in run["employee_rows"]) == sorted(eids)
    assert run["totals"]["employees"] == len(eids)
    slips = await op.payment_slips.find({"pay_run_id": run["id"]}, {"_id": 0}).to_list(100)
    assert sorted(s["employee_id"] for s in slips) == sorted(eids)
    allocs = await op.pay_run_allocations.find({"pay_run_id": run["id"]}, {"_id": 0}).to_list(100)
    assert sorted(a["employee_id"] for a in allocs) == sorted(eids)
    v2 = await op.payroll_payment_allocations.find(
        {"source_pay_run_id": run["id"]}, {"_id": 0}).to_list(100)
    assert {a["worker_id"] for a in v2} <= set(eids)
    others = [e for e in EMPLOYEES_A if e not in eids]
    for e in others:
        assert await op.payment_slips.count_documents({"employee_id": e}) == 0
        assert await op.pay_run_allocations.count_documents({"employee_id": e}) == 0
        assert await op.payroll_payment_allocations.count_documents({"worker_id": e}) == 0
    batched = await _batched(op)
    assert not [b for b in batched if any(b.startswith("rep-%s-" % e) for e in others)], batched


# ═══════════════════════════════════════════════════════════════════ preview
def test_00_preview_still_lists_every_employee(monkeypatch, backend):
    async def scenario(c, op):
        r = await c.get("/api/pay-runs/generate", params={"period_start": P_START, "period_end": P_END},
                        headers=H["admin-a"]())
        assert r.status_code == 200, r.text
        rows = {x["employee_id"]: x for x in r.json()["rows"]}
        assert sorted(rows) == sorted(EMPLOYEES_A)          # all three, B and the idle one absent
        for eid, (_, earned) in EMPLOYEES_A.items():
            assert rows[eid]["earned_amount"] == earned
            assert rows[eid]["paid_now_amount"] == 0
        assert await op.pay_runs.count_documents({}) == 0   # preview writes nothing
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 1
def test_01_one_of_three_selected_gives_one_row_one_slip(monkeypatch, backend):
    async def scenario(c, op):
        r = await _create(c, [row("emp-a1", paid=500)])
        assert r.status_code == 200, r.text
        run = r.json()
        await _assert_only(op, run, ["emp-a1"])
        assert run["totals"]["paid"] == 500 and run["totals"]["earned"] == 500
        assert await op.payment_slips.count_documents({}) == 1
        assert await _batched(op) == sorted(rid("emp-a1", d) for d in DAYS)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 2
def test_02_two_of_three_selected_gives_two_rows(monkeypatch, backend):
    async def scenario(c, op):
        r = await _create(c, [row("emp-a1", paid=100), row("emp-a3", paid=400)])
        assert r.status_code == 200, r.text
        await _assert_only(op, r.json(), ["emp-a1", "emp-a3"])
        paid = {x["employee_id"]: x["paid_now_amount"] for x in r.json()["employee_rows"]}
        assert paid == {"emp-a1": 100, "emp-a3": 400}
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 3
def test_03_all_selected_behaves_as_before(monkeypatch, backend):
    async def scenario(c, op):
        r = await _create(c, [row(e, paid=earned) for e, (_, earned) in EMPLOYEES_A.items()])
        assert r.status_code == 200, r.text
        run = r.json()
        await _assert_only(op, run, list(EMPLOYEES_A))
        for er in run["employee_rows"]:
            earned = EMPLOYEES_A[er["employee_id"]][1]
            assert er["earned_amount"] == earned and er["paid_now_amount"] == earned
            assert er["remaining_after_payment"] == 0 and er["approved_days"] == 5
            assert er["selected_report_ids"] == []
        assert run["totals"]["earned"] == 1400 and run["totals"]["paid"] == 1400
        assert len(await _batched(op)) == 15
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 4 + 5
@pytest.mark.parametrize("rows", [
    [row(IDLE_A, paid=0)],                               # A's employee without reports
    [row("emp-a1", paid=10), row(IDLE_A)],               # mixed: one valid, one outside
    [row(EMP_B, paid=0)],                                # B's employee
    [row("no-such-employee")],
    [row("emp-a1", paid=10), row("emp-a1", paid=20)],   # duplicate
    [],                                                  # 5: empty rows
], ids=["idle", "mixed", "tenant-b", "unknown", "duplicate", "empty"])
@pytest.mark.parametrize("status", ["draft", "confirmed"])
def test_04_05_outside_preview_or_empty_is_400_and_nothing_written(monkeypatch, backend, rows, status):
    async def scenario(c, op):
        before = await _snapshot(op)
        r = await _create(c, rows, status=status)
        assert r.status_code == 400, r.text
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 6
def test_06_row_without_amount_pays_zero_not_the_remaining(monkeypatch, backend):
    async def scenario(c, op):
        r = await _create(c, [row("emp-a2"), row("emp-a1", paid=500)])
        assert r.status_code == 200, r.text
        rows = {x["employee_id"]: x for x in r.json()["employee_rows"]}
        assert rows["emp-a2"]["paid_now_amount"] == 0
        assert rows["emp-a2"]["remaining_after_payment"] == 500
        slip = await op.payment_slips.find_one({"employee_id": "emp-a2"}, {"_id": 0})
        assert slip["paid_now_amount"] == 0
        assert r.json()["totals"]["paid"] == 500
        # a zero row batches nothing (sync_on_confirm skips paid_now == 0, unchanged)
        assert await _batched(op) == sorted(rid("emp-a1", d) for d in DAYS)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 7
@pytest.mark.parametrize("bad", [
    [rid("emp-a2", DAYS[0])],                     # another employee of the same tenant
    [rid(EMP_B, DAYS[0])],                        # tenant B's report
    [rid("emp-a1", DAYS[0]), rid(EMP_B, DAYS[1])],  # one good, one foreign
    ["rep-does-not-exist"],
], ids=["other-employee", "other-tenant", "mixed", "unknown"])
def test_07_foreign_report_ids_are_400_and_nothing_written(monkeypatch, backend, bad):
    async def scenario(c, op):
        before = await _snapshot(op)
        r = await _create(c, [row("emp-a1", paid=0, report_ids=bad)])
        assert r.status_code == 400, r.text
        assert "selected_report_ids" in r.json()["detail"]
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 8
def test_08_earned_comes_only_from_selected_reports(monkeypatch, backend):
    async def scenario(c, op):
        chosen = [rid("emp-a1", DAYS[1]), rid("emp-a1", DAYS[3])]
        r = await _create(c, [row("emp-a1", paid=200, report_ids=chosen),
                              row("emp-a2", paid=25, report_ids=[rid("emp-a2", DAYS[0])])])
        assert r.status_code == 200, r.text
        rows = {x["employee_id"]: x for x in r.json()["employee_rows"]}
        a1 = rows["emp-a1"]
        assert a1["earned_amount"] == 200 and a1["approved_days"] == 2 and a1["approved_hours"] == 16
        assert a1["remaining_after_payment"] == 0
        assert a1["selected_report_ids"] == chosen
        assert [d["date"] for d in a1["day_cells"]] == [DAYS[1], DAYS[3]]
        assert rows["emp-a2"]["earned_amount"] == 100        # 8h × 12.5
        # paying more than the selected reports earn is refused (unchanged overpayment rule)
        r2 = await _create(c, [row("emp-a3", paid=81, report_ids=[rid("emp-a3", DAYS[0])])])
        assert r2.status_code == 400 and "Overpayment" in r2.json()["detail"]
        slip = await op.payment_slips.find_one({"employee_id": "emp-a1"}, {"_id": 0})
        assert sorted(line["report_id"] for line in slip["report_lines"]) == sorted(chosen)
        alloc = await op.pay_run_allocations.find_one({"employee_id": "emp-a1"}, {"_id": 0})
        assert [d["date"] for d in alloc["day_allocations"]] == [DAYS[1], DAYS[3]]
        assert await _batched(op) == sorted(chosen + [rid("emp-a2", DAYS[0])])
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 9 — PATCH
async def _draft(c):
    r = await _create(c, [row(e, paid=0) for e in EMPLOYEES_A], status="draft")
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_09a_patch_one_two_all(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _draft(c)
        r = await _patch(c, run_id, [row("emp-a1", paid=50)], status="draft")
        assert r.status_code == 200, r.text
        assert [x["employee_id"] for x in r.json()["employee_rows"]] == ["emp-a1"]
        r = await _patch(c, run_id, [row("emp-a1", paid=50), row("emp-a2", paid=60)], status="draft")
        assert sorted(x["employee_id"] for x in r.json()["employee_rows"]) == ["emp-a1", "emp-a2"]
        r = await _patch(c, run_id, [row(e, paid=10) for e in EMPLOYEES_A], status="draft")
        assert sorted(x["employee_id"] for x in r.json()["employee_rows"]) == sorted(EMPLOYEES_A)
        # confirm with one selected → one row, one slip, no allocation for the others
        r = await _patch(c, run_id, [row("emp-a3", paid=400)])
        assert r.status_code == 200, r.text
        run_doc = r.json()
        assert [x["employee_id"] for x in run_doc["employee_rows"]] == ["emp-a3"]
        slips = await op.payment_slips.find({"pay_run_id": run_id}, {"_id": 0}).to_list(10)
        assert [s["employee_id"] for s in slips] == ["emp-a3"]
        assert await _batched(op) == sorted(rid("emp-a3", d) for d in DAYS)
    run(monkeypatch, scenario, backend)


@pytest.mark.parametrize("rows", [
    [row(IDLE_A)], [row(EMP_B)], [row("emp-a1"), row("emp-a1")], [],
    [row("emp-a1", report_ids=[rid("emp-a2", DAYS[0])])],
    [row("emp-a1", report_ids=[rid(EMP_B, DAYS[0])])],
], ids=["idle", "tenant-b", "duplicate", "empty", "report-other-employee", "report-other-tenant"])
def test_09b_patch_refusals_leave_the_run_byte_equal(monkeypatch, backend, rows):
    async def scenario(c, op):
        run_id = await _draft(c)
        before = await _snapshot(op)
        r = await _patch(c, run_id, rows)
        assert r.status_code == 400, r.text
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


def test_09c_patch_default_zero_and_selected_report_earned(monkeypatch, backend):
    async def scenario(c, op):
        run_id = await _draft(c)
        chosen = [rid("emp-a1", DAYS[0]), rid("emp-a1", DAYS[4]), rid("emp-a1", DAYS[2])]
        r = await _patch(c, run_id, [row("emp-a1", report_ids=chosen), row("emp-a3")], status="draft")
        assert r.status_code == 200, r.text
        rows = {x["employee_id"]: x for x in r.json()["employee_rows"]}
        assert rows["emp-a1"]["paid_now_amount"] == 0 and rows["emp-a3"]["paid_now_amount"] == 0
        assert rows["emp-a1"]["earned_amount"] == 300 and rows["emp-a1"]["approved_days"] == 3
        assert rows["emp-a3"]["remaining_after_payment"] == 400
        # a later PATCH without ids keeps the stored selection (as before) and its earned
        r = await _patch(c, run_id, [row("emp-a1", paid=300)])
        assert r.status_code == 200, r.text
        a1 = r.json()["employee_rows"][0]
        assert a1["selected_report_ids"] == chosen and a1["earned_amount"] == 300
        assert await _batched(op) == sorted(chosen)
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 10
def test_10_admin_and_owner_work_other_roles_are_403(monkeypatch, backend):
    async def scenario(c, op):
        r = await _create(c, [row("emp-a1", paid=0)], status="draft", who="owner-a")
        assert r.status_code == 200, r.text
        run_id = r.json()["id"]
        r = await _patch(c, run_id, [row("emp-a2", paid=0)], status="draft", who="admin-a")
        assert r.status_code == 200, r.text
        before = await _snapshot(op)
        for who in ("tech-a", "acct-a"):
            assert (await _create(c, [row("emp-a1")], who=who)).status_code == 403
            assert (await _patch(c, run_id, [row("emp-a1")], who=who)).status_code == 403
            assert (await _create(c, [], who=who)).status_code == 403   # role before payload
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ 11
def test_11_two_tenants_are_isolated(monkeypatch, backend):
    async def scenario(c, op):
        r = await _create(c, [row("emp-a1", paid=500)])
        assert r.status_code == 200, r.text
        assert EMP_B not in r.text
        assert await _batched(op, ORG_B) == []
        assert await op.payment_slips.count_documents({"org_id": ORG_B}) == 0
        # B sees its own employee in its preview, and only it
        r = await c.get("/api/pay-runs/generate", params={"period_start": P_START, "period_end": P_END},
                        headers=H["admin-b"]())
        assert [x["employee_id"] for x in r.json()["rows"]] == [EMP_B]
        # B cannot select A's employees; A cannot PATCH B's run
        assert (await _create(c, [row("emp-a1")], who="admin-b")).status_code == 400
        rb = await _create(c, [row(EMP_B, paid=350)], who="admin-b")
        assert rb.status_code == 200, rb.text
        await_rows = rb.json()["employee_rows"]
        assert [x["employee_id"] for x in await_rows] == [EMP_B]
        assert await _batched(op, ORG_B) == sorted(rid(EMP_B, d) for d in DAYS)
        assert (await _patch(c, rb.json()["id"], [row("emp-a2")], status="draft")).status_code == 404
        a_slips = await op.payment_slips.find({"org_id": ORG_A}, {"_id": 0}).to_list(10)
        assert [s["employee_id"] for s in a_slips] == ["emp-a1"]
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ C01 / F-01
NON_FINITE = [float("nan"), float("inf"), float("-inf"), "NaN", "-Infinity"]
NON_FINITE_IDS = ["NaN", "Infinity", "-Infinity", "str-NaN", "str--Infinity"]


def _money_rows(where, value):
    if where == "paid_now_amount":
        return [row("emp-a1", paid=value)]
    r = row("emp-a1", paid=0)
    r["adjustments"] = [{"type": "bonus",
                         "title": "probe", "amount": value}]
    return [r]


@pytest.mark.parametrize("value", NON_FINITE, ids=NON_FINITE_IDS)
@pytest.mark.parametrize("where", ["paid_now_amount", "adjustment.amount"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_12_non_finite_money_is_4xx_and_nothing_written(monkeypatch, backend, value, where, method):
    async def scenario(c, op):
        run_id = await _draft(c) if method == "PATCH" else None
        before = await _snapshot(op)
        # raw JSON carrying the NaN / Infinity / -Infinity literals that Python's json and
        # Starlette accept (httpx's own json= refuses to emit them)
        import json
        raw = json.dumps(body(_money_rows(where, value)), allow_nan=True)
        assert ("NaN" in raw) or ("Infinity" in raw)
        headers = dict(H["admin-a"](), **{"Content-Type": "application/json"})
        if run_id:
            r = await c.patch("/api/pay-runs/" + run_id, content=raw, headers=headers)
        else:
            r = await c.post("/api/pay-runs", content=raw, headers=headers)
        assert r.status_code == 422, (r.status_code, r.text[:300])
        field = "paid_now_amount" if where == "paid_now_amount" else "amount"
        assert r.json() == {"detail": "Invalid money value: %s must be a finite number" % field}
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


@pytest.mark.parametrize("value", NON_FINITE[:3], ids=NON_FINITE_IDS[:3])
@pytest.mark.parametrize("field", ["earned_amount", "bonuses_amount", "deductions_amount",
                                   "previously_paid", "paid_now_amount"])
def test_12b_overpayment_guard_refuses_non_finite_without_the_model(field, value):
    """The explicit guard holds even when a value did not come through the Pydantic model."""
    from fastapi import HTTPException
    from app.routes.pay_runs import _validate_no_overpayment
    r = {"employee_id": "emp-a1", "earned_amount": 100, "bonuses_amount": 0,
         "deductions_amount": 0, "previously_paid": 0, "paid_now_amount": 10}
    r[field] = value
    with pytest.raises(HTTPException) as exc:
        _validate_no_overpayment(r)
    assert exc.value.status_code == 400 and field in exc.value.detail


# ═══════════════════════════════════════════════════════════════════ C01 / F-02
def _spy_report_query(monkeypatch):
    """Record every report query the Pay Run route makes."""
    from app.routes import pay_runs
    calls, real = [], pay_runs.fetch_normalized_report_lines

    async def spy(*a, **k):
        calls.append(k.get("worker_id"))
        return await real(*a, **k)
    monkeypatch.setattr(pay_runs, "fetch_normalized_report_lines", spy)
    return calls


@pytest.mark.parametrize("ids", [
    [rid("emp-a1", DAYS[0]), rid("emp-a1", DAYS[0])],
    [rid("emp-a1", DAYS[0]), rid("emp-a1", DAYS[1]), rid("emp-a1", DAYS[0])],
    [rid("emp-a1", DAYS[0])] * 5000,
    [rid("emp-a1", DAYS[0])] + ["rep-filler-%04d" % i for i in range(500)],   # 501 distinct
], ids=["dup-2", "dup-3", "same-x5000", "over-limit-501"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_13_duplicate_or_oversized_selection_is_400_before_the_report_query(
        monkeypatch, backend, ids, method):
    async def scenario(c, op):
        run_id = await _draft(c) if method == "PATCH" else None
        calls = _spy_report_query(monkeypatch)
        before = await _snapshot(op)
        # a VALID selection for emp-a1 comes first in preview order; its query must not run either
        bad_ids = [i.replace("emp-a1", "emp-a3") for i in ids]
        rows = [row("emp-a1", paid=0, report_ids=[rid("emp-a1", DAYS[0])]),
                row("emp-a3", paid=0, report_ids=bad_ids)]
        r = await (_patch(c, run_id, rows) if run_id else _create(c, rows))
        assert r.status_code == 400, r.text[:300]
        assert "selected_report_ids" in r.json()["detail"]
        assert ("duplicates" in r.json()["detail"]) == (len(ids) <= 500)
        assert "employee_id=emp-a3" in r.json()["detail"]
        assert calls[:1] == [None]                   # the preview's own tenant-wide query ran first …
        assert [w for w in calls if w] == [], calls  # … and NO per-employee report query ran at all
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)


def test_13b_limit_boundary_and_canonical_list_is_what_is_persisted(monkeypatch, backend):
    async def scenario(c, op):
        r = await c.get("/api/pay-runs/generate", params={"period_start": P_START, "period_end": P_END},
                        headers=H["admin-a"]())
        order = [x["employee_id"] for x in r.json()["rows"]]
        assert order.index("emp-a1") < order.index("emp-a3")   # premise of test_13
        from app.routes.pay_runs import MAX_SELECTED_REPORT_IDS
        assert MAX_SELECTED_REPORT_IDS == 500
        # exactly 500 distinct ids pass the size check and reach the eligibility check
        ids = [rid("emp-a1", DAYS[0])] + ["rep-filler-%04d" % i for i in range(499)]
        r = await _create(c, [row("emp-a1", paid=0, report_ids=ids)])
        assert r.status_code == 400 and "not eligible" in r.json()["detail"], r.text[:200]
        # a valid selection is persisted exactly as validated (row and slip), and earned matches it
        chosen = [rid("emp-a1", DAYS[2]), rid("emp-a1", DAYS[0])]
        r = await _create(c, [row("emp-a1", paid=200, report_ids=chosen)])
        assert r.status_code == 200, r.text
        er = r.json()["employee_rows"][0]
        assert er["selected_report_ids"] == chosen and er["earned_amount"] == 200
        stored = await op.pay_runs.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert stored["employee_rows"][0]["selected_report_ids"] == chosen
        slip = await op.payment_slips.find_one({"pay_run_id": r.json()["id"]}, {"_id": 0})
        assert slip["selected_report_ids"] == chosen
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════════ C02 / F-01a
HUGE_INT = "1" + "0" * 400        # a JSON integer float() cannot hold (OverflowError)


@pytest.mark.parametrize("where", ["paid_now_amount", "adjustment.amount"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_14_overflowing_integer_money_is_422_and_nothing_written(monkeypatch, backend, where, method):
    async def scenario(c, op):
        import json
        run_id = await _draft(c) if method == "PATCH" else None
        before = await _snapshot(op)
        placeholder = 1234567.891
        raw = json.dumps(body(_money_rows(where, placeholder)))
        assert raw.count(repr(placeholder)) == 1
        raw = raw.replace(repr(placeholder), HUGE_INT)      # a bare integer literal in the JSON
        assert json.loads(raw)["rows"][0] and HUGE_INT in raw
        headers = dict(H["admin-a"](), **{"Content-Type": "application/json"})
        if run_id:
            r = await c.patch("/api/pay-runs/" + run_id, content=raw, headers=headers)
        else:
            r = await c.post("/api/pay-runs", content=raw, headers=headers)
        assert r.status_code == 422, (r.status_code, r.text[:300])
        field = "paid_now_amount" if where == "paid_now_amount" else "amount"
        assert r.json() == {"detail": "Invalid money value: %s must be a finite number" % field}
        assert await _snapshot(op) == before
    run(monkeypatch, scenario, backend)
