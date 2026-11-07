"""LAB-01-E probe (copy to <wt73>/backend/tests/, run one test per process, real Mongo).

P1 8 concurrent POST /pay-runs with the SAME Idempotency-Key, fresh DB (only the indexes the
   app itself creates) -> exactly one pay run expected.
P2 same key, different tenant user? (key scoped per tenant) — covered by PR test; skipped.
P3 period edit on a draft run: correction of the old period stays pending (orphan?)
P4 overlapping periods (week inside month) -> two correction records for one overpayment?
"""
import asyncio
import pytest
from tests.test_lab_01_labor_cost import ORG, P_END, P_START, _token, run  # noqa
from tests.test_lab_01_e_flow_guard_7 import _body, _old_run


def test_p1_concurrent_same_key(monkeypatch):
    async def scenario(c, op):
        await _old_run(op)
        h = dict(_token(), **{"Idempotency-Key": "race-key"})
        rs = await asyncio.gather(*[c.post("/api/pay-runs", json=_body(), headers=h) for _ in range(8)])
        codes = sorted(r.status_code for r in rs)
        n = await op.pay_runs.count_documents({"id": {"$ne": "run-old"}})
        idx = [i["key"] for i in (await op.audit_idempotency.index_information()).values()] \
            if hasattr(op.audit_idempotency, "index_information") else "?"
        print("P1 codes", codes, "runs", n, "idem indexes", idx)
        assert n == 1, f"P1 FAIL: {n} pay runs for one key"
    run(monkeypatch, scenario, "real")


def test_p3_period_edit_orphan(monkeypatch):
    async def scenario(c, op):
        await _old_run(op)
        r = await c.post("/api/pay-runs", json=_body(), headers=dict(_token(), **{"Idempotency-Key": "p3"}))
        rid = r.json()["id"]
        b2 = dict(_body(), period_start="2026-09-01", period_end="2026-09-07")
        p = await c.patch("/api/pay-runs/" + rid, json=b2, headers=_token())
        recs = await op.payroll_corrections.find({}, {"_id": 0}).to_list(10)
        print("P3 patch", p.status_code, [(x["period_start"], x["status"], x.get("pay_run_ids")) for x in recs])
    run(monkeypatch, scenario, "real")


def test_p4_unprotected_registry_fails_closed(monkeypatch):
    """P4 (LAB-01-F, needs #72): duplicate ids in audit_idempotency so the unique index cannot be
    built -> POST /pay-runs must answer 503 and write no run."""
    async def scenario(c, op):
        await _old_run(op)
        await op.audit_idempotency.insert_many([{"id": "dup", "x": 1}, {"id": "dup", "x": 2}])
        r = await c.post("/api/pay-runs", json=_body(), headers=dict(_token(), **{"Idempotency-Key": "p4"}))
        n = await op.pay_runs.count_documents({"id": {"$ne": "run-old"}})
        print("P4", r.status_code, r.text[:120], "runs", n)
        assert n == 0
    run(monkeypatch, scenario, "real")
