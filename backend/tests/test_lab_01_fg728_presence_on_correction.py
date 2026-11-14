"""
FG-728 (FLOW Guard Q014; FLOW-013 L89: „не може да създаде отчет за човек, който не е
присъстващ на съответния обект"): an R36 correction (PUT /daily-reports/{id}) that moves a day
entry to ANOTHER object requires the worker's presence on that object that day — else 400
PRESENCE_REQUIRED_ON_OBJECT and nothing written (the report, its version, its quantity
approvals and the audit chain unchanged). Checked before the write and again in the
transaction of the write. Nothing else in the correction flow changes.

    pytest tests/test_lab_01_fg728_presence_on_correction.py -v --noconftest
"""
import asyncio

import pytest
from fastapi import HTTPException

from tests.test_lab_01_h_r36 import DAY, ORG, U, _harness, _old_report


async def _state(op):
    return (await op.employee_daily_reports.find_one({"id": "REP"}, {"_id": 0}),
            await op.labor_quantity_approvals.find_one({"id": "qa"}, {"_id": 0}),
            await op.audit_events.count_documents({}))


MOVE_TO_Q = {"day_entries": [{"id": "e1", "project_id": "Q", "hours_worked": 8}]}


@pytest.mark.parametrize("presence", ["none", "on_other_object", "absent", "leave"])
def test_fg728_a_move_to_an_object_without_presence_is_refused(monkeypatch, presence):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "fg728_no_" + presence)
        await _old_report(op)
        if presence == "on_other_object":
            await op.attendance_entries.insert_one({"id": "a1", "org_id": ORG, "date": DAY, "user_id": "w",
                                                    "project_id": "P", "status": "Present"})
        elif presence == "absent":
            await op.attendance_entries.insert_one({"id": "a1", "org_id": ORG, "date": DAY, "user_id": "w",
                                                    "project_id": "Q", "status": "Absent"})
        elif presence == "leave":
            await op.attendance_entries.insert_one({"id": "a1", "org_id": ORG, "date": DAY, "user_id": "w",
                                                    "project_id": "Q", "status": "Present"})
            await op.worker_calendar.insert_one({"org_id": ORG, "date": DAY, "worker_id": "w", "status": "sick"})
        before = await _state(op)
        with pytest.raises(HTTPException) as e:
            await daily_reports.update_daily_report("REP", MOVE_TO_Q, U("owner"))
        assert e.value.status_code == 400, e.value.detail
        assert e.value.detail["code"] == "PRESENCE_REQUIRED_ON_OBJECT" and e.value.detail["project_id"] == "Q"
        assert await _state(op) == before                                  # nothing written
    asyncio.run(body())


def test_fg728_a_move_to_an_object_where_the_worker_was_present_is_corrected(monkeypatch):
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "fg728_ok")
        await _old_report(op)
        await op.attendance_entries.insert_one({"id": "a1", "org_id": ORG, "date": DAY, "user_id": "w",
                                                "project_id": "Q", "status": "Late"})
        out = await daily_reports.update_daily_report("REP", MOVE_TO_Q, U("owner"))
        assert [e["project_id"] for e in out["day_entries"]] == ["Q"]
        assert out["report_version"] == 1 and out["approval_status"] == "SUBMITTED"
        assert (await op.labor_quantity_approvals.find_one({"id": "qa"}))["status"] == "void"
    asyncio.run(body())


def test_fg728_a_correction_on_the_same_object_needs_no_new_presence_check(monkeypatch):
    """unchanged: correcting the hours of an entry on the SAME object is not a move"""
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "fg728_same")
        await _old_report(op)
        out = await daily_reports.update_daily_report("REP", {"day_entries": [
            {"id": "e1", "project_id": "P", "hours_worked": 6}]}, U("owner"))
        assert out["total_hours"] == 6
    asyncio.run(body())


def test_fg728_the_presence_is_checked_again_inside_the_transaction(monkeypatch):
    """the presence disappears between the first check and the write (a concurrent change of
    the attendance) → the check in the transaction refuses; nothing written"""
    async def body():
        from app.routes import daily_reports
        op = await _harness(monkeypatch, "fg728_race")
        await _old_report(op)
        await op.attendance_entries.insert_one({"id": "a1", "org_id": ORG, "date": DAY, "user_id": "w",
                                                "project_id": "Q", "status": "Present"})
        real = daily_reports._require_presence_on_moved_entries
        calls = []

        async def racing(tenant, org_id, report, entries, session=None):
            calls.append(session)
            if len(calls) == 2:                     # the in-transaction check: presence gone
                await op.attendance_entries.update_one({"id": "a1"}, {"$set": {"status": "Absent"}})
            return await real(tenant, org_id, report, entries, session=session)
        monkeypatch.setattr(daily_reports, "_require_presence_on_moved_entries", racing)
        before = await _state(op)
        with pytest.raises(HTTPException) as e:
            await daily_reports.update_daily_report("REP", MOVE_TO_Q, U("owner"))
        assert e.value.detail["code"] == "PRESENCE_REQUIRED_ON_OBJECT" and len(calls) == 2
        assert await _state(op) == before
    asyncio.run(body())
