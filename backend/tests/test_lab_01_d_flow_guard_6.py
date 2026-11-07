"""
LAB-01-D — FLOW Guard pass 6 on c422cbd (FLOW-028, CLAUDE.md §7/§8).

* FG-72: a labor approval binds to (report id, report version, entry id); entry ids are
  unique per report; any change or reset of a report voids its approvals; one approval
  is counted at most once (two entries with the same id do not pay 240 for one 120).
* FG-73: PUT /daily-reports/{id} — only the report owner edits their own draft.
* FG-66: the FLOW-028 correction is a record (payroll_corrections) with an AuditEvent,
  routed to Approval as pending (W0-07 not started) with a DQ alert; never auto-applied.
* FG-76: one "spent" number — the budget-burn warning reads the LAB-01 calculation,
  not work_sessions (expected-actual already does since LAB-01).

Uses the harness of tests/test_lab_01_labor_cost.py (mongomock + real Mongo when
``W0_03_REAL_MONGO_URL`` names a disposable local MongoDB).

    pytest tests/test_lab_01_d_flow_guard_6.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.services.labor_cost import DQ_DUPLICATE_ENTRY, compute_person_labor
from tests.test_lab_01_labor_cost import (  # noqa: F401 — the shared harness
    DAYS, ORG, P_END, P_START, _preview, _token, backend, run,
)

PK = {"pkg-ak": {"id": "pkg-ak", "project_id": "prj", "labor_pay_type": "Akord", "labor_piece_rate": 5}}


def _old_line(entry_id, version=0, hours=8):
    """A normalized old-style line (report doc REP, entry ``entry_id``)."""
    return {"id": "REP_" + entry_id, "report_doc_id": "REP", "entry_id": entry_id,
            "report_version": version, "worker_id": "w", "date": DAYS[0], "hours": hours,
            "status": "APPROVED", "project_id": "prj", "smr_type": "Шпакловка"}


def _approval(entry_id, version=0, qty=24, **kw):
    return dict({"id": "qa-" + entry_id, "report_id": "REP", "entry_id": entry_id,
                 "report_version": version, "approved_quantity": qty, "status": "approved",
                 "approved_by": "boss", "execution_package_id": "pkg-ak"}, **kw)


def _terms(*recs):
    from app.services.labor_cost import record_approval_key
    return {"packages": PK, "quantities": {record_approval_key(r): r for r in recs}}


# ═══════════════════════════════════════════════════════════════ FG-72 (pure)
def test_fg72_two_entries_with_the_same_id_share_no_quantity():
    prof = {"pay_type": "Akord"}
    lc = compute_person_labor(prof, [_old_line("e1"), _old_line("e1")], _terms(_approval("e1")))
    assert lc["total"] == 120.0                                   # 24 × 5 once, not 240
    assert [w["code"] for w in lc["dq_warnings"]].count(DQ_DUPLICATE_ENTRY) == 1


def test_fg72_approval_of_another_version_or_entry_does_not_count():
    prof = {"pay_type": "Akord"}
    # the report changed (version 1); the approval is for version 0
    assert compute_person_labor(prof, [_old_line("e1", version=1)], _terms(_approval("e1", 0)))["total"] == 0.0
    # another entry of the same report
    assert compute_person_labor(prof, [_old_line("e2")], _terms(_approval("e1")))["total"] == 0.0
    # the exact (report, version, entry)
    assert compute_person_labor(prof, [_old_line("e1", 3)], _terms(_approval("e1", 3)))["total"] == 120.0


def test_fg72_load_terms_binds_exact_key_counts_once_and_ignores_void(monkeypatch):
    async def body():
        from mongomock_motor import AsyncMongoMockClient
        from app.services.labor_cost import load_smr_terms
        from app.tenancy.data_access import TenantData
        op = AsyncMongoMockClient()["lab01d_terms"]
        await op.execution_packages.insert_one(dict(PK["pkg-ak"], org_id=ORG))
        await op.labor_quantity_approvals.insert_many([
            dict(_approval("e1", 0, qty=24, id="qa-1", approved_at="2026-10-05T10:00"), org_id=ORG),
            dict(_approval("e1", 0, qty=99, id="qa-2", approved_at="2026-10-05T11:00"), org_id=ORG),  # 2nd
            dict(_approval("e2", 0, qty=50, status="void"), org_id=ORG),                              # void
            dict(_approval("e3", 0, qty=50), org_id=ORG),                                             # old version
        ])
        tenant = TenantData.for_resolved_org(op, ORG)
        lines = [_old_line("e1"), _old_line("e2"), _old_line("e3", version=1)]
        terms = await load_smr_terms(tenant, ORG, lines)
        assert list(terms["quantities"].values()) == [terms["quantities"]["REP|e1|0"]]
        assert terms["quantities"]["REP|e1|0"]["id"] == "qa-1"       # the earliest one only
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ FG-72 / FG-73 (PUT)
async def _put_harness(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient
    from app.routes import daily_reports
    from app.services import labor_cost
    op = AsyncMongoMockClient()["lab01d_put"]
    monkeypatch.setattr(daily_reports, "db", op)
    monkeypatch.setattr(labor_cost, "db", op)
    await op.employee_daily_reports.insert_one({
        "id": "REP", "org_id": ORG, "employee_id": "w", "report_date": DAYS[0],
        "approval_status": "DRAFT",
        "day_entries": [{"id": "e1", "project_id": "prj", "hours_worked": 8}]})
    await op.labor_quantity_approvals.insert_one(dict(_approval("e1"), org_id=ORG))
    return op, daily_reports


def test_fg73_put_only_by_the_report_owner(monkeypatch):
    async def body():
        op, dr = await _put_harness(monkeypatch)
        before = await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0})
        # FG-73: a technician who is neither the author nor an approver → 403
        with pytest.raises(HTTPException) as ex:
            await dr.update_daily_report("REP", {"day_entries": [
                {"id": "e1", "project_id": "prj", "hours_worked": 0.5}]},
                {"id": "tech", "org_id": ORG, "role": "Technician"})
        assert ex.value.status_code == 403
        assert await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0}) == before
        out = await dr.update_daily_report("REP", {"notes": "own"}, {"id": "w", "org_id": ORG, "role": "Worker"})
        assert out["notes"] == "own"
        # R36 (LAB-01-H): Admin is an approver and may correct it — audited
        out = await dr.update_daily_report("REP", {"notes": "admin fix"},
                                           {"id": "admin", "org_id": ORG, "role": "Admin"})
        assert out["notes"] == "admin fix" and out["corrected_by"] == "admin"
        assert await op.audit_events.count_documents({"entity_id": "REP", "action": "daily_report.corrected"}) == 1
    asyncio.run(body())


def test_fg72_put_refuses_duplicate_entry_ids_and_a_change_voids_approvals(monkeypatch):
    async def body():
        op, dr = await _put_harness(monkeypatch)
        owner = {"id": "w", "org_id": ORG, "role": "Worker"}
        with pytest.raises(HTTPException) as ex:
            await dr.update_daily_report("REP", {"day_entries": [
                {"id": "e1", "project_id": "prj", "hours_worked": 4},
                {"id": "e1", "project_id": "prj", "hours_worked": 4}]}, owner)
        assert ex.value.status_code == 400
        qa = await op.labor_quantity_approvals.find_one({"id": "qa-e1"}, {"_id": 0})
        assert qa["status"] == "approved"                          # a refused edit voids nothing
        out = await dr.update_daily_report("REP", {"day_entries": [
            {"id": "e1", "project_id": "prj", "hours_worked": 6}]}, owner)
        assert out["report_version"] == 1
        qa = await op.labor_quantity_approvals.find_one({"id": "qa-e1"}, {"_id": 0})
        assert qa["status"] == "void" and qa["void_reason"] == "report_edited"
    asyncio.run(body())


def test_fg72_reject_voids_approvals(monkeypatch):
    async def body():
        op, dr = await _put_harness(monkeypatch)
        rep = await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0})
        res = await dr.reject_report_one(rep, {"id": "boss", "org_id": ORG, "role": "Admin"}, "x")
        assert res["status"] == "ok"
        qa = await op.labor_quantity_approvals.find_one({"id": "qa-e1"}, {"_id": 0})
        assert qa["status"] == "void" and qa["void_reason"] == "report_rejected"
        assert (await op.employee_daily_reports.find_one({"id": "REP"}))["report_version"] == 1
    asyncio.run(body())


# ═══════════════════════════════════════════════════════════════ FG-72 (Pay Run, DB)
def test_fg72_pay_run_counts_one_approval_once(monkeypatch, backend):
    async def scenario(c, op):
        await op.execution_packages.insert_one(dict(PK["pkg-ak"], org_id=ORG, project_id="prj-1"))
        # an old-style report whose two entries carry the SAME id (written straight to the DB)
        await op.employee_daily_reports.insert_one({
            "id": "REP-DUP", "org_id": ORG, "employee_id": "w-akord", "report_date": "2026-10-11",
            "approval_status": "APPROVED", "payroll_status": "none",
            "day_entries": [{"id": "e1", "project_id": "prj-1", "hours_worked": 4},
                            {"id": "e1", "project_id": "prj-1", "hours_worked": 4}]})
        await op.labor_quantity_approvals.insert_one({
            "id": "qa-dup", "org_id": ORG, "report_id": "REP-DUP", "entry_id": "e1", "report_version": 0,
            "approved_quantity": 24, "execution_package_id": "pkg-ak", "status": "approved",
            "approved_by": "admin"})
        rows = await _preview(c)
        # 600 from the seed + 120 once (not 240)
        assert rows["w-akord"]["earned_amount"] == 720.0
        assert DQ_DUPLICATE_ENTRY in [w["code"] for w in rows["w-akord"]["labor_dq_warnings"]]
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════ FG-66
def test_fg66_correction_is_a_pending_record_with_audit_and_dq_never_applied(monkeypatch, backend):
    async def scenario(c, op):
        await op.pay_runs.insert_one({
            "id": "run-old", "org_id": ORG, "number": "PR-0001", "status": "confirmed", "version": 1,
            "period_start": P_START, "period_end": P_END, "week_number": 41, "paid_at": None,
            "employee_rows": [{"employee_id": "w-akord", "earned_amount": 660.0, "paid_now_amount": 660.0}],
            "totals": {"earned": 660.0}, "history": []})
        body = {"run_type": "weekly", "period_start": P_START, "period_end": P_END,
                "rows": [{"employee_id": "w-akord"}], "status": "draft"}
        r = await c.post("/api/pay-runs", json=body, headers=_token())
        assert r.status_code == 200, r.text
        run_ = r.json()
        item = run_["employee_rows"][0]["correction_item"]
        recs = await op.payroll_corrections.find({}, {"_id": 0}).to_list(10)
        assert len(recs) == 1
        rec = recs[0]
        assert rec["id"] == item["correction_id"]
        assert (rec["status"], rec["approval_status"], rec["applied"]) == (
            "pending_approval", "awaiting_approval_runtime", False)
        assert (rec["amount"], rec["employee_id"], rec["source_pay_run_id"]) == (60.0, "w-akord", "run-old")
        assert rec["pay_run_ids"] == [run_["id"]]
        audits = await op.audit_events.find({"entity_id": rec["id"]}, {"_id": 0}).to_list(10)
        assert [a["action"] for a in audits] == ["payroll.correction.created"]
        assert audits[0]["source_flow"] == "FLOW-028" and audits[0]["retention_class"] == "R1"
        dq = await op.dq_alerts.find({}, {"_id": 0}).to_list(10)
        assert len(dq) == 1 and dq[0]["status"] == "open" and dq[0]["entity_id"] == rec["id"]
        # never applied: no payment, no deduction, no advance created by it
        for coll in ("finance_payments", "payroll_payment_allocations", "advances"):
            assert await op[coll].count_documents({}) == 0, coll
        # an edit with the same result is idempotent (no second record / event)
        r = await c.patch("/api/pay-runs/" + run_["id"], json=body, headers=_token())
        assert r.status_code == 200, r.text
        assert await op.payroll_corrections.count_documents({}) == 1
        assert await op.audit_events.count_documents({"entity_id": rec["id"]}) == 1
        assert await op.dq_alerts.count_documents({}) == 1
        # LAB-01-G (F2): a recomputation that shows no overpayment does NOT supersede it —
        # only an explicit approved decision does; a DQ alert asks a person
        before = await op.payroll_corrections.find_one({"id": rec["id"]}, {"_id": 0})
        await op.pay_runs.update_one({"id": "run-old"}, {"$set": {"employee_rows.0.paid_now_amount": 600}})
        r = await c.patch("/api/pay-runs/" + run_["id"], json=body, headers=_token())
        assert r.status_code == 200, r.text
        after = await op.payroll_corrections.find_one({"id": rec["id"]}, {"_id": 0})
        assert {k: v for k, v in after.items() if k != "pay_run_ids"} == \
               {k: v for k, v in before.items() if k != "pay_run_ids"}
        recomputed = await op.dq_alerts.find_one({"code": "PAYROLL_CORRECTION_RECOMPUTED"}, {"_id": 0})
        assert recomputed["recorded_amount"] == 60.0 and recomputed["new_amount"] == 0.0
        assert await op.audit_events.count_documents({"entity_id": rec["id"]}) == 1
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════════════ FG-76
def test_fg76_budget_burn_uses_the_lab01_number_not_work_sessions(monkeypatch, backend):
    async def scenario(c, op):
        from app.routes import budget_progress
        monkeypatch.setattr(budget_progress, "db", op)
        await op.activity_budgets.insert_one({"id": "b1", "org_id": ORG, "project_id": "prj-1",
                                              "type": "Шпакловка", "labor_budget": 1000})
        await op.execution_packages.insert_one({"id": "ep1", "org_id": ORG, "project_id": "prj-1",
                                                "activity_name": "x", "progress_percent": 10})
        # unapproved / session time worth 5000 — must NOT burn the budget
        await op.work_sessions.insert_one({"id": "ws1", "org_id": ORG, "site_id": "prj-1",
                                           "ended_at": "2026-10-05T18:00", "labor_cost": 5000})
        user = {"id": "admin", "org_id": ORG, "role": "Admin"}
        res = await budget_progress.get_progress_warnings("prj-1", user)
        kinds = [w["type"] for w in res["warnings"]]
        assert "budget_overrun" not in kinds                       # 825 approved of 1000
        assert "budget_burn_high" in kinds                         # 82.5 % burn at 10 % progress
    run(monkeypatch, scenario, backend)


# ═══════════════════════════════════════════════════════ LAB-01-D-C01 (audit notes on 21d4ed1)
def test_c01_void_runs_before_the_content_write(monkeypatch):
    """(b) the version bump + void happen BEFORE the report content/status is written."""
    async def body():
        op, dr = await _put_harness(monkeypatch)
        seen = []
        real = dr.void_labor_approvals

        async def spy(tenant, org_id, report_id, actor_id, reason, **kw):
            doc = await op.employee_daily_reports.find_one({"id": report_id}, {"_id": 0})
            seen.append((reason, doc["day_entries"][0]["hours_worked"], doc["approval_status"]))
            return await real(tenant, org_id, report_id, actor_id, reason, **kw)
        monkeypatch.setattr(dr, "void_labor_approvals", spy)
        owner = {"id": "w", "org_id": ORG, "role": "Worker"}
        await dr.update_daily_report("REP", {"day_entries": [
            {"id": "e1", "project_id": "prj", "hours_worked": 6}]}, owner)
        rep = await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0})
        await dr.reject_report_one(rep, {"id": "boss", "org_id": ORG, "role": "Admin"}, "x")
        # at void time the OLD content / status was still stored
        assert seen == [("report_edited", 8, "DRAFT"), ("report_rejected", 6, "DRAFT")]
        assert (await op.employee_daily_reports.find_one({"id": "REP"}))["report_version"] == 2

        # and when the content write fails after the void, the approvals stay void (safe side)
        await op.labor_quantity_approvals.insert_one(dict(_approval("e1", 2, id="qa-v2"), org_id=ORG))
        await op.employee_daily_reports.update_one({"id": "REP"}, {"$set": {"approval_status": "DRAFT"}})
        from app.tenancy import data_access

        real_update = data_access.TenantCollection.update_one

        async def failing_update(self, flt, update, *a, **kw):
            if "$set" in update and "day_entries" in update["$set"]:
                raise RuntimeError("write failed")
            return await real_update(self, flt, update, *a, **kw)
        monkeypatch.setattr(data_access.TenantCollection, "update_one", failing_update)
        with pytest.raises(RuntimeError):
            await dr.update_daily_report("REP", {"day_entries": [
                {"id": "e1", "project_id": "prj", "hours_worked": 1}]}, owner)
        assert (await op.labor_quantity_approvals.find_one({"id": "qa-v2"}))["status"] == "void"
    asyncio.run(body())


def test_c01_decided_corrections_are_never_rewritten(monkeypatch, backend):
    """(a) a run edit never rewrites a correction — decided or pending (LAB-01-G)."""
    async def scenario(c, op):
        await op.pay_runs.insert_one({
            "id": "run-old", "org_id": ORG, "number": "PR-0001", "status": "confirmed", "version": 1,
            "period_start": P_START, "period_end": P_END, "week_number": 41, "paid_at": None,
            "employee_rows": [{"employee_id": "w-akord", "earned_amount": 660.0, "paid_now_amount": 660.0}],
            "totals": {"earned": 660.0}, "history": []})
        body = {"run_type": "weekly", "period_start": P_START, "period_end": P_END,
                "rows": [{"employee_id": "w-akord"}], "status": "draft"}
        run_ = (await c.post("/api/pay-runs", json=body, headers=_token())).json()
        rec = await op.payroll_corrections.find_one({}, {"_id": 0})
        assert rec["amount"] == 60.0

        def strip(d):
            return {k: v for k, v in d.items() if k != "pay_run_ids"}
        for state, code in (({"status": "approved", "approval_id": "APR-1"}, "PAYROLL_CORRECTION_CHANGED_AFTER_DECISION"),
                            ({"status": "pending_approval", "applied": True}, "PAYROLL_CORRECTION_CHANGED_AFTER_DECISION"),
                            ({"status": "pending_approval", "applied": False, "approval_id": None},
                             "PAYROLL_CORRECTION_RECOMPUTED")):
            await op.payroll_corrections.update_one({"id": rec["id"]}, {"$set": state})
            before = await op.payroll_corrections.find_one({"id": rec["id"]}, {"_id": 0})
            for paid in (700.0, 600.0):          # another overpayment, then none
                await op.pay_runs.update_one({"id": "run-old"}, {"$set": {"employee_rows.0.paid_now_amount": paid}})
                r = await c.patch("/api/pay-runs/" + run_["id"], json=body, headers=_token())
                assert r.status_code == 200, r.text
                assert strip(await op.payroll_corrections.find_one({"id": rec["id"]}, {"_id": 0})) == strip(before), state
            alert = await op.dq_alerts.find_one({"code": code}, {"_id": 0})
            assert alert and alert["recorded_amount"] == 60.0, state
            await op.pay_runs.update_one({"id": "run-old"}, {"$set": {"employee_rows.0.paid_now_amount": 660.0}})
        assert await op.payroll_corrections.count_documents({}) == 1
        assert await op.audit_events.count_documents({"entity_id": rec["id"]}) == 1  # only "created"
    run(monkeypatch, scenario, backend)
