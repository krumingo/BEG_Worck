"""LAB-01-D-C01 probe: decided payroll corrections vs. later run edits (real Mongo).

Run from <wt73>/backend with MONGO_URL pointing at the RS.
E1 rejected correction + new amount        -> untouched, LOCKED DQ raised
E2 approved correction, overpayment gone   -> untouched; is a DQ raised? (gap check)
E3 approved, new amount, then back to old  -> is the LOCKED DQ left open? (stale check)
E4 concurrent: 8 parallel syncs with different amounts on a pending record -> one doc, version sane
"""
import asyncio, os, uuid
from motor.motor_asyncio import AsyncIOMotorClient
from app.tenancy.data_access import TenantData
from app.services import payroll_corrections as pc

ORG = "org-probe"
FAILS = []


def row(eid, amount):
    return {"employee_id": eid, "correction_item": {"amount": amount, "gross_payable": 600,
            "previously_paid": 600 + amount, "paid_now": 0, "reason": "probe"}}


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    dbn = "probe_lab01e_" + uuid.uuid4().hex[:6]
    raw = cli[dbn]
    t = TenantData.for_resolved_org(raw, ORG)
    run = {"id": "run1", "number": "PR-1", "period_start": "2026-10-01", "period_end": "2026-10-07"}

    async def sync(rows):
        return await pc.sync_run_corrections(t, raw, ORG, dict(run, employee_rows=rows), "actor")

    # E1
    await sync([row("w1", 60.0)])
    await raw.payroll_corrections.update_one({"employee_id": "w1"}, {"$set": {"status": "rejected"}})
    before = await raw.payroll_corrections.find_one({"employee_id": "w1"}, {"_id": 0})
    await sync([row("w1", 90.0)])
    after = await raw.payroll_corrections.find_one({"employee_id": "w1"}, {"_id": 0})
    dq = await raw.dq_alerts.find_one({"code": pc.DQ_CODE_LOCKED, "employee_id": "w1"})
    print("E1 untouched:", before == after, "locked DQ:", bool(dq))
    if before != after or not dq:
        FAILS.append("E1")

    # E2
    await sync([row("w2", 50.0)])
    await raw.payroll_corrections.update_one({"employee_id": "w2"}, {"$set": {"status": "approved", "approval_id": "A"}})
    await sync([])  # overpayment of w2 disappeared
    rec = await raw.payroll_corrections.find_one({"employee_id": "w2"}, {"_id": 0})
    dq2 = await raw.dq_alerts.count_documents({"entity_id": rec["id"], "code": pc.DQ_CODE_LOCKED})
    print("E2 status:", rec["status"], "locked DQ when overpayment gone:", dq2)
    if rec["status"] != "approved":
        FAILS.append("E2")
    if dq2 == 0:
        print("  NOTE E2: approved correction stands silently after its overpayment vanished")

    # E3
    await sync([row("w2", 70.0)])
    await sync([row("w2", 50.0)])
    dq3 = await raw.dq_alerts.find_one({"entity_id": rec["id"], "code": pc.DQ_CODE_LOCKED}, {"_id": 0})
    print("E3 LOCKED DQ after amount returned to decided:", dq3 and dq3["status"], dq3 and dq3["new_amount"])

    # E4
    await sync([row("w4", 10.0)])
    await asyncio.gather(*[sync([row("w4", 10.0 + i)]) for i in range(1, 9)])
    docs = await raw.payroll_corrections.find({"employee_id": "w4"}, {"_id": 0}).to_list(20)
    print("E4 docs:", len(docs), "status:", docs[0]["status"], "version:", docs[0]["version"])
    if len(docs) != 1 or docs[0]["status"] != "pending_approval":
        FAILS.append("E4")

    await cli.drop_database(dbn)
    print("FAILS", FAILS or "none")

asyncio.run(main())
