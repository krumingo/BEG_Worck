"""R85 (Krum 14.11.2026, FG-569): an APPROVED manual akord row (LAB-02 approved quantity ×
labour unit price) goes into the payroll Pay Run — exactly once, and never a second time with
the daily report.

The Pay Run reads the row at the cost THE labor cost (R62, project_labor_cost) gives it:
preview, selected reports, "previously paid" and the payroll lock (batched → paid → reopen)
all see it once. A row whose worker / day / project already has an approved daily report
(or whose quantity belongs to an approved report) is not counted in the Pay Run nor in the
project labor cost (DQ MANUAL_ROW_DUPLICATE_OF_REPORT).

Reuses the R62 harness (tests/test_lab_01_s_r62_one_labor_cost.py): w1 is Hourly 20; the
approved reports pay 180 (160 labor + 20 downtime); the akord setup of
tests/test_lab_02_r62_akord_from_approved_quantity.py gives a 12 × 5 = 60 row on 2026-11-12.
"""
import pytest

from app.routes import pay_runs  # noqa: F401 — loaded before the harness patches db
from tests.test_lab_01_s_r62_one_labor_cost import (  # noqa: F401
    ORG, P, _decision, _key, backend, run)
from tests.test_lab_02_r62_akord_from_approved_quantity import AK_DAY, AK_PKG, _akord_setup, _body

OWNER = {"id": "owner", "org_id": ORG, "role": "Owner", "email": "owner@r62.example"}
FROM, TO = "2026-11-01", "2026-11-15"


async def _approved_akord_row(c, op):
    await _akord_setup(op)
    r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key("admin"))
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await c.post(f"/api/labor-entries/{rid}/approve", json=_decision(cost=60.0), headers=_key("owner"))
    assert r.status_code == 200, r.text
    return rid


async def _w1(review_mode=False):
    prev = await pay_runs.generate_pay_run(OWNER, period_start=FROM, period_end=TO, review_mode=review_mode)
    rows = [r for r in prev["rows"] if r["employee_id"] == "w1"]
    return rows[0] if rows else None


def _manual_reports(row):
    return [r for dc in row["day_cells"] for r in dc["reports"] if str(r["report_id"]).startswith("manual:")]


async def _create(rows, status="confirmed"):
    data = pay_runs.PayRunCreateInput(period_start=FROM, period_end=TO, status=status,
                                      rows=[pay_runs.PayRunRowInput(**r) for r in rows])
    return await pay_runs._create_pay_run(data, OWNER)


def test_r85_an_approved_manual_akord_row_is_in_the_pay_run_once(monkeypatch, backend):
    from app.services.labor_cost import project_labor_cost

    async def scenario(c, op):
        before = await _w1()
        assert before["earned_amount"] == 180.0, before["earned_formula"]
        rid = await _approved_akord_row(c, op)
        row = await _w1()
        assert row["earned_amount"] == 240.0, row["earned_formula"]         # 180 + 60, once
        assert row["akord_amount"] == 60.0
        man = _manual_reports(row)
        assert [m["report_id"] for m in man] == ["manual:" + rid] and man[0]["value"] == 60.0
        assert man[0]["selectable"] is True
        # R62: the Pay Run and THE labor cost are one number
        assert (await project_labor_cost(ORG, P))["total"] == 240.0

        run_ = await _create([{"employee_id": "w1", "paid_now_amount": 240.0}])
        entry = await op.labor_entries.find_one({"id": rid})
        assert (entry["payroll_status"], entry["payroll_source"]) == ("batched", f"pay_run:{run_['id']}")
        # forbidden: the next Pay Run of the same period never pays it again
        row = await _w1()
        assert row is None or not _manual_reports(row)
        assert row is None or row["earned_amount"] == 0.0
        # the review calendar shows it once, locked
        rv = await _w1(review_mode=True)
        man = _manual_reports(rv)
        assert len(man) == 1 and man[0]["selectable"] is False and man[0]["payroll_status"] == "batched"
        # paid → the row is paid; reopen of an unpaid run frees it again (once)
        await pay_runs.mark_pay_run_paid(run_["id"], pay_runs.MarkPaidInput(payment_method="bank_transfer"), OWNER)
        assert (await op.labor_entries.find_one({"id": rid}))["payroll_status"] == "paid"
    run(monkeypatch, scenario, backend)


def test_r85_reopen_frees_the_row_and_an_explicit_second_selection_is_refused(monkeypatch):
    async def scenario(c, op):
        rid = await _approved_akord_row(c, op)
        run_ = await _create([{"employee_id": "w1", "paid_now_amount": 60.0,
                               "selected_report_ids": ["manual:" + rid]}])
        assert (await op.labor_entries.find_one({"id": rid}))["payroll_status"] == "batched"
        assert run_["employee_rows"][0]["earned_amount"] == 60.0             # the selected row only
        # forbidden: a second run selecting the same manual row
        with pytest.raises(Exception) as ex:
            await _create([{"employee_id": "w1", "paid_now_amount": 10.0,
                            "selected_report_ids": ["manual:" + rid]}])
        assert getattr(ex.value, "status_code", None) == 400, ex.value
        await pay_runs.reopen_pay_run(run_["id"], pay_runs.PayRunReopenInput(reason="грешка"), OWNER)
        entry = await op.labor_entries.find_one({"id": rid})
        assert (entry["payroll_status"], entry.get("payroll_source")) == ("none", None)
        row = await _w1()
        assert len(_manual_reports(row)) == 1 and row["akord_amount"] == 60.0
    run(monkeypatch, scenario)


@pytest.mark.parametrize("report", [
    {"date": AK_DAY, "project_id": P},          # the same worker, day and project
    {"date": AK_DAY, "project_id": None},       # a project-less report of that day
    {"id": "R-Q", "date": "2026-11-13", "project_id": P}])   # the report the quantity came from
def test_r85_a_daily_report_and_the_same_work_are_never_counted_twice(monkeypatch, backend, report):
    from app.services.labor_cost import project_labor_cost

    async def scenario(c, op):
        rid = await _approved_akord_row(c, op)
        rep = {"id": "R-SAME", "org_id": ORG, "worker_id": "w1", "submitted_by": "w1", "hours": 8,
               "smr_type": "Боя", "execution_package_id": AK_PKG, "status": "APPROVED",
               "approval_status": "APPROVED", "approved_by": "sm", "quantity": 12, "approved_quantity": 12}
        rep.update(report)
        await op.employee_daily_reports.insert_one(rep)
        row = await _w1()
        assert not _manual_reports(row), _manual_reports(row)
        assert any(w["code"] == "MANUAL_ROW_DUPLICATE_OF_REPORT" and w["report_id"] == "manual:" + rid
                   for w in row["labor_dq_warnings"]), row["labor_dq_warnings"]
        lc = await project_labor_cost(ORG, P)
        assert not [x for x in lc["lines"] if x.get("manual_entry_id") == rid]
        assert any(w["code"] == "MANUAL_ROW_DUPLICATE_OF_REPORT" for w in lc["dq_warnings"])
        # the report alone pays the day: the manual row adds nothing on top of it
        total = lc["total"]
        await op.labor_entries.update_one({"id": rid}, {"$set": {"approval_status": "rejected"}})
        assert (await _w1())["earned_amount"] == row["earned_amount"]
        assert (await project_labor_cost(ORG, P))["total"] == total
    run(monkeypatch, scenario, backend)


def test_r85_a_pending_or_an_hourly_manual_row_is_not_paid_by_this_rule(monkeypatch):
    """Only APPROVED manual AKORD rows (R85). A pending one waits; an hourly manual row is
    outside R85 (asked of Krum — not changed)."""
    async def scenario(c, op):
        await _akord_setup(op)
        r = await c.post("/api/labor-entries", json=_body(quantity_approval_id="qa-1"), headers=_key("admin"))
        assert r.status_code == 201, r.text
        assert not _manual_reports(await _w1())                         # pending
        await op.labor_entries.update_one({"id": "le-man"}, {"$set": {"approval_status": "approved",
                                                                       "approved_by": "owner"}})
        row = await _w1()
        assert not _manual_reports(row) and row["earned_amount"] == 180.0  # hourly manual row: not here
    run(monkeypatch, scenario)
