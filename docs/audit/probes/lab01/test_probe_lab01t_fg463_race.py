"""CLAUDE AUDIT probe — #73 LAB-01-T (b766f34), FG-463. Copy into backend/tests/; real Mongo RS
(W0_03_REAL_MONGO_URL). Reuses the PR's own harness (tests.test_lab_01_s_r62_one_labor_cost).
  T1 ×10  Two pending manual rows of the SAME worker, project and day exist (le-man 50 and a
          legacy le-dup 30, both entered by the Admin). The Owner approves le-man while the
          Accountant approves le-dup, at the same time. FG-463 says the same hours never count
          twice: at most ONE of them may end approved.
"""
import asyncio

import pytest

from tests.test_lab_01_s_r62_one_labor_cost import (  # noqa: F401
    _decision, _key, _legacy_manual, _real_refusal, run)


@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only")
@pytest.mark.parametrize("i", range(10))
def test_t1_two_concurrent_approvals_of_overlapping_rows(monkeypatch, i):
    async def scenario(c, op):
        await _legacy_manual(op, "le-dup", date="2026-11-05")
        a, b = await asyncio.gather(
            c.post("/api/labor-entries/le-man/approve", json=_decision(), headers=_key("owner")),
            c.post("/api/labor-entries/le-dup/approve", json=_decision(cost=30.0), headers=_key("acct")))
        st = {r["id"]: r["approval_status"] async for r in op.labor_entries.find(
            {"id": {"$in": ["le-man", "le-dup"]}}, {"_id": 0, "id": 1, "approval_status": 1})}
        print("T1 run %d: owner->le-man %s, acct->le-dup %s | stored %s" % (i, a.status_code, b.status_code, st))
        assert list(st.values()).count("approved") <= 1, "both overlapping rows approved: %s" % st
    run(monkeypatch, scenario, backend="real")


@pytest.mark.skipif(bool(_real_refusal()), reason="real Mongo only")
@pytest.mark.parametrize("i", range(10))
def test_t2_two_concurrent_creates_of_the_same_day(monkeypatch, i):
    """T2 ×10: two POST /labor-entries for w1 on a NEW day (2026-11-09), different keys, at
    the same time. FG-463: a 2nd live manual row of that day → 409; at most ONE row stored."""
    from tests.test_lab_01_s_r62_one_labor_cost import P, PKG

    async def scenario(c, op):
        body = {"project_id": P, "employee_id": "w1", "hours": 1, "date": "2026-11-09",
                "execution_package_id": PKG}
        a, b = await asyncio.gather(c.post("/api/labor-entries", json=body, headers=_key("admin")),
                                    c.post("/api/labor-entries", json=body, headers=_key("owner")))
        n = await op.labor_entries.count_documents({"employee_id": "w1", "date": "2026-11-09",
                                                    "source": "manual"})
        print("T2 run %d: create %s / %s | rows stored %d" % (i, a.status_code, b.status_code, n))
        assert n <= 1, "two live manual rows of the same worker/project/day"
    run(monkeypatch, scenario, backend="real")
