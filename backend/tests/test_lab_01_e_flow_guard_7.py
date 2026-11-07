"""
LAB-01-E — FLOW Guard pass 7 on 00324ab (FLOW-019/028, CLAUDE.md §8, R29).

* FG-78: PUT /technician/draft/{id} — only the draft's owner, only while Draft.
* FG-79: POST /daily-reports/batch-save — an existing report is changed only by its
  owner and only while DRAFT / REJECTED; checked for all before any write; a content
  change bumps the version and voids the approvals.
* FG-80: one correction per underlying overpayment (employee + period + source), the
  same across runs; POST /pay-runs is idempotent under ``Idempotency-Key`` (R29).

    pytest tests/test_lab_01_e_flow_guard_7.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import HTTPException

from tests.test_lab_01_labor_cost import (  # noqa: F401 — the shared harness
    DAYS, ORG, P_END, P_START, _token, backend, run,
)


async def _db(monkeypatch, name):
    from mongomock_motor import AsyncMongoMockClient
    from app.routes import daily_reports, technician
    from app.services import labor_cost
    op = AsyncMongoMockClient()[name]
    for m in (daily_reports, technician, labor_cost):
        monkeypatch.setattr(m, "db", op)
    return op


# ═══════════════════════════════════════════════════════════════ FG-78
def test_fg78_technician_draft_owner_only_and_draft_only(monkeypatch):
    async def body():
        from app.routes import technician
        op = await _db(monkeypatch, "lab01e_tech")
        await op.employee_daily_reports.insert_many([
            {"id": "d-1", "org_id": ORG, "worker_id": "tech2", "submitted_by": "tech2", "date": DAYS[0],
             "hours": 8, "status": "Draft", "project_id": "prj"},
            {"id": "d-2", "org_id": ORG, "worker_id": "tech2", "submitted_by": "tech2", "date": DAYS[1],
             "hours": 8, "status": "Submitted", "project_id": "prj"}])
        before = await op.employee_daily_reports.find({}, {"_id": 0}).to_list(10)
        tech1 = {"id": "tech1", "org_id": ORG, "role": "Technician"}
        tech2 = {"id": "tech2", "org_id": ORG, "role": "Technician"}
        for did, hours in (("d-1", 0.5), ("d-2", 12)):
            with pytest.raises(HTTPException) as ex:
                await technician.update_draft(did, technician.DraftLineUpdate(hours=hours), tech1)
            assert ex.value.status_code == 403
        # the owner cannot edit a SUBMITTED report either
        with pytest.raises(HTTPException) as ex:
            await technician.update_draft("d-2", technician.DraftLineUpdate(hours=12), tech2)
        assert ex.value.status_code == 400
        assert await op.employee_daily_reports.find({}, {"_id": 0}).to_list(10) == before
        out = await technician.update_draft("d-1", technician.DraftLineUpdate(hours=7), tech2)
        assert out["hours"] == 7 and out["report_version"] == 1
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ FG-79
def test_fg79_batch_save_owner_and_status_checked_before_any_write(monkeypatch):
    async def body():
        from app.routes import daily_reports
        op = await _db(monkeypatch, "lab01e_batch")
        await op.employee_daily_reports.insert_many([
            {"id": "R-APP", "org_id": ORG, "employee_id": "tech2", "report_date": DAYS[0],
             "approval_status": "APPROVED", "created_by": "tech2",
             "day_entries": [{"id": "e1", "project_id": "prj", "hours_worked": 8}], "total_hours": 8},
            {"id": "R-DRAFT", "org_id": ORG, "employee_id": "tech3", "report_date": DAYS[0],
             "approval_status": "DRAFT", "created_by": "tech1",
             "day_entries": [{"id": "e1", "project_id": "prj", "hours_worked": 8}], "total_hours": 8}])
        await op.labor_quantity_approvals.insert_one({
            "id": "qa-d", "org_id": ORG, "report_id": "R-DRAFT", "entry_id": "e1", "report_version": 0,
            "approved_quantity": 10, "status": "approved", "approved_by": "boss"})
        before = await op.employee_daily_reports.find({}, {"_id": 0}).to_list(10)
        tech1 = {"id": "tech1", "org_id": ORG, "role": "Technician"}
        tech2 = {"id": "tech2", "org_id": ORG, "role": "Technician"}

        def batch(emps, hours=14):
            return {"project_id": "prj", "report_date": DAYS[0],
                    "entries": [{"employee_id": e, "hours_worked": hours} for e in emps]}
        # not the owner of tech2's APPROVED report → 403; tech3's draft in the same batch is NOT written
        with pytest.raises(HTTPException) as ex:
            await daily_reports.batch_save_daily_entries(batch(["tech3", "tech2"]), tech1)
        assert ex.value.status_code == 403
        # the owner, but the report is APPROVED → 409
        with pytest.raises(HTTPException) as ex:
            await daily_reports.batch_save_daily_entries(batch(["tech2"]), tech2)
        assert ex.value.status_code == 409
        assert await op.employee_daily_reports.find({}, {"_id": 0}).to_list(10) == before
        assert (await op.labor_quantity_approvals.find_one({"id": "qa-d"}))["status"] == "approved"
        # the creator of tech3's DRAFT may change it → version bump + approvals void
        res = await daily_reports.batch_save_daily_entries(batch(["tech3"], 6), tech1)
        assert res["employees_saved"] == 1
        d = await op.employee_daily_reports.find_one({"id": "R-DRAFT"}, {"_id": 0})
        assert d["total_hours"] == 6 and d["report_version"] == 1
        assert (await op.labor_quantity_approvals.find_one({"id": "qa-d"}))["status"] == "void"
        # a NEW report for someone else is still created (its creator becomes its owner)
        res = await daily_reports.batch_save_daily_entries(batch(["tech4"], 5), tech1)
        assert res["employees_saved"] == 1
        new = await op.employee_daily_reports.find_one({"employee_id": "tech4"}, {"_id": 0})
        assert new["approval_status"] == "DRAFT" and new["created_by"] == "tech1"
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ FG-80
def _old_run(op):
    return op.pay_runs.insert_one({
        "id": "run-old", "org_id": ORG, "number": "PR-0001", "status": "confirmed", "version": 1,
        "period_start": P_START, "period_end": P_END, "week_number": 41, "paid_at": None,
        "employee_rows": [{"employee_id": "w-akord", "earned_amount": 660.0, "paid_now_amount": 660.0}],
        "totals": {"earned": 660.0}, "history": []})


def _body(status="draft"):
    return {"run_type": "weekly", "period_start": P_START, "period_end": P_END,
            "rows": [{"employee_id": "w-akord"}], "status": status}


def test_fg80_one_correction_per_overpayment_across_runs(monkeypatch, backend):
    async def scenario(c, op):
        await _old_run(op)
        ids = []
        for i in range(3):
            r = await c.post("/api/pay-runs", json=_body(), headers=dict(_token(), **{"Idempotency-Key": f"k-{i}"}))
            assert r.status_code == 200, r.text
            ids.append(r.json()["id"])
        assert len(set(ids)) == 3                                     # three different runs
        recs = await op.payroll_corrections.find({}, {"_id": 0}).to_list(10)
        assert len(recs) == 1                                         # ONE overpayment of 60, not 3 × 60
        rec = recs[0]
        assert rec["amount"] == 60.0 and sorted(rec["pay_run_ids"]) == sorted(ids)
        assert rec["idempotency_key"] == (f"overpayment:employee:w-akord:period:{P_START}..{P_END}"
                                          ":source:paid_pay_runs_of_period")
        assert await op.audit_events.count_documents({"entity_id": rec["id"]}) == 1
        assert await op.dq_alerts.count_documents({}) == 1
        for rid in ids:                                               # every run names the same record
            run_ = await op.pay_runs.find_one({"id": rid}, {"_id": 0})
            assert run_["employee_rows"][0]["correction_item"]["correction_id"] == rec["id"]
    run(monkeypatch, scenario, backend)


def test_fg80_r29_pay_run_create_is_idempotent(monkeypatch, backend):
    async def scenario(c, op):
        h = dict(_token(), **{"Idempotency-Key": "same-key"})
        # no key → 428, nothing written
        r = await c.post("/api/pay-runs", json=_body(), headers=dict(_token(), **{"Idempotency-Key": "  "}))
        assert r.status_code == 428
        assert await op.pay_runs.count_documents({}) == 0
        first = await c.post("/api/pay-runs", json=_body(), headers=h)
        assert first.status_code == 200, first.text
        again = await c.post("/api/pay-runs", json=_body(), headers=h)
        assert again.status_code == 200, again.text
        assert again.json()["id"] == first.json()["id"] and again.json()["idempotent_replay"] is True
        assert await op.pay_runs.count_documents({}) == 1             # no second run
        # the same key with ANOTHER body → 409, nothing written
        other = await c.post("/api/pay-runs", json=_body("confirmed"), headers=h)
        assert other.status_code == 409
        assert await op.pay_runs.count_documents({}) == 1
        # a refused request does not burn the key: fix the cause, retry with the same key
        bad = {"run_type": "weekly", "period_start": P_START, "period_end": P_END,
               "rows": [{"employee_id": "nobody"}], "status": "draft"}
        hk = dict(_token(), **{"Idempotency-Key": "retry-key"})
        assert (await c.post("/api/pay-runs", json=bad, headers=hk)).status_code == 400
        assert (await c.post("/api/pay-runs", json=bad, headers=hk)).status_code == 400  # re-run, not replay
        assert await op.pay_runs.count_documents({}) == 1
        # keys are per tenant and per action
        rec = await op.audit_idempotency.find_one({"key": "same-key"}, {"_id": 0})
        assert (rec["tenant_id"], rec["action"], rec["status"]) == (ORG, "pay_run.create", "completed")
    run(monkeypatch, scenario, backend)


def test_fg80_no_header_at_all_is_refused(monkeypatch):
    """Without the test hook: a client that sends no Idempotency-Key gets 428."""
    async def body():
        import httpx
        from tests.test_lab_01_labor_cost import _Db, _app, _seed
        async with _Db("mongomock") as op:
            await _seed(op)
            app = _app(monkeypatch, op)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x") as c:
                r = await c.post("/api/pay-runs", json=_body(), headers=_token())
                assert r.status_code == 428
                assert await op.pay_runs.count_documents({}) == 0
    asyncio.run(body())
