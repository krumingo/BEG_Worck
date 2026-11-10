"""R81 (Krum 09.11.2026, FG-532; refines R73 / R77): a creator's reversal of an approved
manual labor row is only REQUESTED. The old amount stays counted (project cost and payroll)
until a second person approves the corrected row — then the reversal and the new row take
effect together, atomically (the day goes old → new, never 0). A rejected replacement leaves
the old row and cancels the reversal. A reversal with no replacement takes effect only when a
second person confirms it.

Reuses the R62 harness (tests/test_lab_01_s_r62_one_labor_cost.py): le-man is a pending
manual row of w1 on 2026-11-05 (50), entered by the Admin; the approved reports make 180.
"""
import asyncio

import pytest

from tests.test_lab_01_s_r62_one_labor_cost import (  # noqa: F401
    P, PKG, _decision, _key, _numbers, _real_refusal, backend, run)

DAY = "2026-11-05"


async def _approved_then_reversal_requested(c, op):
    r = await c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner"))
    assert r.status_code == 200, r.text
    r = await c.post("/api/labor-entries/le-man/reverse", json=_decision(version=2, reason="грешни часове"),
                     headers=_key("admin"))                                       # the creator
    assert r.status_code == 200 and r.json()["pending_reversal"], r.text
    assert set((await _numbers(c)).values()) == {230.0}                           # still counted


async def _replacement(c, hours=3):
    r = await c.post("/api/labor-entries", json={"project_id": P, "employee_id": "w1", "hours": hours,
                                                 "date": DAY, "execution_package_id": PKG,
                                                 "corrects_entry_id": "le-man"}, headers=_key("admin"))
    assert r.status_code == 201, r.text
    return r.json()


def test_r81_the_reversal_and_the_replacement_take_effect_together(monkeypatch, backend):
    async def scenario(c, op):
        await _approved_then_reversal_requested(c, op)
        new = await _replacement(c)                    # 3 h × the profile's 20 = 60
        assert new["corrects_entry_id"] == "le-man" and new["labor_cost"] == 60.0
        assert set((await _numbers(c)).values()) == {230.0}                       # old 50 still in
        # forbidden: the creator never approves the replacement (R66)
        r = await c.post(f"/api/labor-entries/{new['id']}/approve", json=_decision(cost=60.0), headers=_key("admin"))
        assert r.status_code == 403, r.text
        r = await c.post(f"/api/labor-entries/{new['id']}/approve", json=_decision(cost=60.0), headers=_key("acct"))
        assert r.status_code == 200, r.text
        old = await op.labor_entries.find_one({"id": "le-man"})
        assert (old["approval_status"], old["reversed_by"], old["reversal_requested_by"]) == ("reversed", "acct", "admin")
        rev = await op.labor_entries.find_one({"id": old["reversed_by_entry_id"]})
        assert rev["approval_status"] == "reversal" and rev["labor_cost"] == -50.0
        assert set((await _numbers(c)).values()) == {240.0}                       # 180 + 60, never 180
    run(monkeypatch, scenario, backend)


def test_r81_a_rejected_replacement_leaves_the_old_row_and_cancels_the_reversal(monkeypatch, backend):
    async def scenario(c, op):
        await _approved_then_reversal_requested(c, op)
        new = await _replacement(c)
        r = await c.post(f"/api/labor-entries/{new['id']}/reject", json=_decision(cost=60.0, reason="не"),
                         headers=_key("owner"))
        assert r.status_code == 200, r.text
        old = await op.labor_entries.find_one({"id": "le-man"})
        assert old["approval_status"] == "approved" and old.get("pending_reversal") is None
        assert old["reversed_by_entry_id"] is None and old["cancelled_reversals"][0]["replacement_rejected"] == new["id"]
        assert (await op.labor_entries.find_one({"id": old["cancelled_reversals"][0]["reversal_entry_id"]}))[
            "approval_status"] == "cancelled"
        assert set((await _numbers(c)).values()) == {230.0}
    run(monkeypatch, scenario, backend)


def test_r81_a_reversal_without_a_replacement_needs_a_second_person(monkeypatch):
    async def scenario(c, op):
        await _approved_then_reversal_requested(c, op)
        # forbidden: the creator cannot confirm his own reversal
        r = await c.post("/api/labor-entries/le-man/reverse", json=_decision(version=3, reason="x"), headers=_key("admin"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "REVERSAL_PENDING", r.text
        assert set((await _numbers(c)).values()) == {230.0}
        r = await c.post("/api/labor-entries/le-man/reverse", json=_decision(version=3, reason="да"), headers=_key("owner"))
        assert r.status_code == 200 and r.json()["approval_status"] == "reversed", r.text
        assert set((await _numbers(c)).values()) == {180.0}
    run(monkeypatch, scenario)


def test_r81_while_a_replacement_waits_the_reversal_alone_is_not_confirmed(monkeypatch):
    async def scenario(c, op):
        await _approved_then_reversal_requested(c, op)
        await _replacement(c)
        r = await c.post("/api/labor-entries/le-man/reverse", json=_decision(version=3, reason="да"), headers=_key("owner"))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "REPLACEMENT_PENDING", r.text
        assert (await op.labor_entries.find_one({"id": "le-man"}))["approval_status"] == "approved"
    run(monkeypatch, scenario)


@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only (concurrent transactions)")
@pytest.mark.parametrize("i", range(5))
def test_r81_concurrent_approval_and_rejection_of_the_replacement_leave_one_consistent_state(monkeypatch, i):
    async def scenario(c, op):
        await _approved_then_reversal_requested(c, op)
        new = await _replacement(c)
        a, b = await asyncio.gather(
            c.post(f"/api/labor-entries/{new['id']}/approve", json=_decision(cost=60.0), headers=_key("acct")),
            c.post(f"/api/labor-entries/{new['id']}/reject", json=_decision(cost=60.0, reason="не"),
                   headers=_key("owner")))
        assert sorted([a.status_code, b.status_code]) == [200, 409], (a.text, b.text)
        old = await op.labor_entries.find_one({"id": "le-man"})
        nw = await op.labor_entries.find_one({"id": new["id"]})
        if nw["approval_status"] == "approved":
            assert old["approval_status"] == "reversed" and old["reversed_by_entry_id"]
            assert set((await _numbers(c)).values()) == {240.0}
        else:
            assert nw["approval_status"] == "rejected"
            assert old["approval_status"] == "approved" and not old.get("pending_reversal")
            assert set((await _numbers(c)).values()) == {230.0}
    run(monkeypatch, scenario, backend="real")


@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only (concurrent transactions)")
@pytest.mark.parametrize("i", range(5))
def test_r81_a_concurrent_confirm_and_replacement_approval_never_drop_the_day(monkeypatch, i):
    """The reversal is confirmed alone while the replacement is approved: whatever wins, the
    old row is reversed exactly once and the day is never left without the new row once
    it is approved."""
    async def scenario(c, op):
        await _approved_then_reversal_requested(c, op)
        new = await _replacement(c)
        a, b = await asyncio.gather(
            c.post(f"/api/labor-entries/{new['id']}/approve", json=_decision(cost=60.0), headers=_key("acct")),
            c.post("/api/labor-entries/le-man/reverse", json=_decision(version=3, reason="да"),
                   headers=_key("owner")))
        assert a.status_code == 200, a.text                          # the replacement wins
        assert b.status_code == 409, b.text                          # REPLACEMENT_PENDING / STALE
        old = await op.labor_entries.find_one({"id": "le-man"})
        assert old["approval_status"] == "reversed"
        assert await op.labor_entries.count_documents({"reverses_entry_id": "le-man",
                                                        "approval_status": "reversal"}) == 1
        assert set((await _numbers(c)).values()) == {240.0}
    run(monkeypatch, scenario, backend="real")
