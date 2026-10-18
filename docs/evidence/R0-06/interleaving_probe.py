"""R0-06-C01 interleaving probe (Codex F-01 reproduction) — no assertions, prints end states.

reopen_first: create confirmed run; reopen parks inside sync_on_reopen; mark-paid; resume.
patch_first:  create draft; PATCH → confirmed parks inside sync_on_confirm; mark-paid; resume.
fail_early:   mark-paid with the first payment effect failing (F-02).

    cd backend
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27018/?directConnection=true' \
        PYTHONPATH=. python ../docs/evidence/R0-06/interleaving_probe.py
"""
import asyncio
import json

import pytest

from tests import test_r0_06_paid_pay_run as t


async def _state(op, run_id, codes):
    pr = await op.pay_runs.find_one({"id": run_id}, {"_id": 0})
    allocs = await op.payroll_payment_allocations.find({"source_pay_run_id": run_id}).to_list(100)
    slips = await op.payment_slips.find({"pay_run_id": run_id}).to_list(100)
    return {"http": codes, "run_status": pr["status"], "paid_effects": pr.get("paid_effects"),
            "allocation_statuses": sorted({a["status"] for a in allocs}),
            "slip_statuses": sorted({s["status"] for s in slips}),
            "salary_outflows": await op.finance_payments.count_documents({"reference": run_id}),
            "counted_as_paid_run": await op.pay_runs.count_documents({"id": run_id, "status": "paid"})}


def interleave(mp, first, sync_name, draft):
    async def scenario(c, op):
        run_id = await t._create(c, "draft" if draft else "confirmed")
        gate = t._pause(mp, sync_name)
        task = asyncio.ensure_future(first(c, run_id))
        await gate["entered"].wait()
        paid = await t._mark_paid(c, run_id)
        gate["resume"].set()
        done = await task
        return await _state(op, run_id, {"first_op": done.status_code, "mark_paid": paid.status_code})
    return scenario


def fail_early(mp):
    async def scenario(c, op):
        from app.routes import pay_runs
        run_id = await t._create(c)
        name = "_reduce_advances" if hasattr(pay_runs, "_reduce_advances") else "_apply_paid_effects"

        async def boom(*a, **kw):
            raise RuntimeError("injected")
        mp.setattr(pay_runs, name, boom)
        try:
            code = (await t._mark_paid(c, run_id)).status_code
        except RuntimeError:
            code = 500
        return await _state(op, run_id, {"mark_paid": code})
    return scenario


out = {}
for backend in ("real", "mongomock"):
    res = {}
    for name, make in (
        ("reopen_first", lambda mp: interleave(mp, lambda c, i: t._reopen(c, i), "sync_on_reopen", False)),
        ("patch_first", lambda mp: interleave(mp, lambda c, i: t._patch(c, i, "confirmed"), "sync_on_confirm", True)),
        ("fail_early", fail_early),
    ):
        mp = pytest.MonkeyPatch()
        try:
            res[name] = t.run(mp, make(mp), backend)
        finally:
            mp.undo()
    out[backend] = res
print(json.dumps(out))
