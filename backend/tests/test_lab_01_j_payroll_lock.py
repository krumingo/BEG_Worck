"""
LAB-01-J — FG-91: "already in payroll" is decided from the Pay Run lines, for both report
formats, and every edit path answers 409 (FLOW-028: no silent edit after payment).

The payroll sync never stamps ``payroll_status`` on the old format (employee_id /
report_date; its lines are ``<report id>_<entry id>``), so an Admin PUT could change a
paid old-format report from 8 h to 0 h. Now any confirmed / paid / paying /
payment_failed / reopened run that references the report or one of its entries locks it.

    pytest tests/test_lab_01_j_payroll_lock.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import HTTPException

ORG = "ORG-L01J"
DAY = "2026-11-02"
ADMIN = {"id": "admin", "org_id": ORG, "role": "Admin", "email": "admin@l01j.example"}


async def _harness(monkeypatch, name):
    import sys
    import app.db as appdb
    from mongomock_motor import AsyncMongoMockClient
    op = AsyncMongoMockClient()[name]
    real = appdb.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("app") and getattr(mod, "db", None) is real:
            monkeypatch.setattr(mod, "db", op)
    from app.routes import daily_reports, technician  # noqa: F401 — loaded, then patched
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("app") and getattr(mod, "db", None) is real:
            monkeypatch.setattr(mod, "db", op)
    await op.employee_daily_reports.insert_many([
        # old format, approved and PAID in a run — but no payroll_status on it
        {"id": "OLD", "org_id": ORG, "employee_id": "w", "created_by": "w", "report_date": DAY,
         "approval_status": "APPROVED", "day_entries": [{"id": "e1", "project_id": "P", "hours_worked": 8}],
         "total_hours": 8},
        # new format, approved, selected in a confirmed run (paid_now 0 → never stamped)
        {"id": "NEW", "org_id": ORG, "worker_id": "t", "submitted_by": "t", "date": DAY, "hours": 8,
         "project_id": "P", "status": "APPROVED", "approval_status": "APPROVED"},
        # new format, only in a DRAFT run → not locked
        {"id": "FREE", "org_id": ORG, "worker_id": "t2", "submitted_by": "t2", "date": DAY, "hours": 8,
         "project_id": "P", "status": "APPROVED", "approval_status": "APPROVED"}])
    await op.pay_runs.insert_many([
        {"id": "run-paid", "org_id": ORG, "number": "PR-0001", "status": "paid", "paid_at": DAY,
         "employee_rows": [{"employee_id": "w", "paid_now_amount": 80, "selected_report_ids": [],
                            "day_cells": [{"date": DAY, "reports": [{"report_id": "OLD_e1"}]}]}]},
        {"id": "run-conf", "org_id": ORG, "number": "PR-0002", "status": "confirmed", "paid_at": None,
         "employee_rows": [{"employee_id": "t", "paid_now_amount": 0, "selected_report_ids": ["NEW"]}]},
        {"id": "run-draft", "org_id": ORG, "number": "PR-0003", "status": "draft", "paid_at": None,
         "employee_rows": [{"employee_id": "t2", "paid_now_amount": 0, "selected_report_ids": ["FREE"]}]}])
    return op


def test_fg91_old_format_paid_report_is_409_on_put_and_batch_save(monkeypatch):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "l01j_old")
        before = await op.employee_daily_reports.find_one({"id": "OLD"}, {"_id": 0})
        with pytest.raises(HTTPException) as ex:
            await daily_reports.update_daily_report("OLD", {"day_entries": [
                {"id": "e1", "project_id": "P", "hours_worked": 0}]}, ADMIN)
        assert ex.value.status_code == 409 and "PR-0001" in ex.value.detail
        with pytest.raises(HTTPException) as ex:
            await daily_reports.batch_save_daily_entries(
                {"project_id": "P", "report_date": DAY, "entries": [{"employee_id": "w", "hours_worked": 0}]}, ADMIN)
        assert ex.value.status_code == 409
        assert await op.employee_daily_reports.find_one({"id": "OLD"}, {"_id": 0}) == before
    asyncio.run(body())


def test_fg91_new_format_line_of_a_confirmed_run_is_409(monkeypatch):
    async def body():
        from app.routes import technician
        op = await _harness(monkeypatch, "l01j_new")
        with pytest.raises(HTTPException) as ex:
            await technician.update_draft("NEW", technician.DraftLineUpdate(hours=0.5), ADMIN)
        assert ex.value.status_code == 409 and "PR-0002" in ex.value.detail
        assert (await op.employee_daily_reports.find_one({"id": "NEW"}))["hours"] == 8
    asyncio.run(body())


def test_fg91_a_draft_run_does_not_lock(monkeypatch):
    async def body():
        from app.routes import technician
        await _harness(monkeypatch, "l01j_free")
        out = await technician.update_draft("FREE", technician.DraftLineUpdate(hours=7), ADMIN)
        assert out["hours"] == 7 and out["status"] == "SUBMITTED"     # corrected → back to review
    asyncio.run(body())


def test_fg91_report_in_payroll_helper(monkeypatch):
    async def body():
        from app.services.report_corrections import report_in_payroll, report_line_ids
        from app.tenancy.data_access import TenantData
        op = await _harness(monkeypatch, "l01j_helper")
        t = TenantData.for_resolved_org(op, ORG)
        old = await op.employee_daily_reports.find_one({"id": "OLD"}, {"_id": 0})
        assert report_line_ids(old) == ["OLD", "OLD_e1"]
        assert "PR-0001" in await report_in_payroll(t, ORG, old)
        assert await report_in_payroll(t, ORG, await op.employee_daily_reports.find_one({"id": "FREE"}, {"_id": 0})) is None
        assert await report_in_payroll(t, ORG, {"id": "X", "payroll_status": "paid"}) == "payroll_status=paid"
    asyncio.run(body())
