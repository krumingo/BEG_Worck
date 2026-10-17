"""R0-06 concurrency probe — 8 parallel mark-paid on one confirmed run (test 3 seed),
on the real MongoDB and on mongomock. Prints the response codes and the money written.

    cd backend
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27018/?directConnection=true' \
        PYTHONPATH=. python ../docs/evidence/R0-06/concurrency_probe.py
"""
import asyncio
import json

import pytest

from tests import test_r0_06_paid_pay_run as t


async def scenario(c, op):
    run_id = await t._create(c)
    res = await asyncio.gather(*[t._mark_paid(c, run_id) for _ in range(t.CONCURRENT)])
    pays = await op.finance_payments.find({}, {"_id": 0, "user_id": 1, "amount": 1}).to_list(100)
    adv = await op.advances.find_one({"id": t.ADVANCE_A}, {"_id": 0})
    return {"codes": sorted(r.status_code for r in res), "finance_payments": len(pays),
            "outflow_total": sum(p["amount"] for p in pays),
            "advance_remaining": adv["remaining_amount"], "advance_deductions": len(adv["deductions"])}


mp = pytest.MonkeyPatch()
try:
    print(json.dumps({b: t.run(mp, scenario, b) for b in ("real", "mongomock")}))
finally:
    mp.undo()
