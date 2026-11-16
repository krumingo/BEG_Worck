"""
FIX-PAY-02 — decision Р104 (Krum, 16.11.2026): reversal of a paid crew-contract tranche,
with two people.

"An Accountant, Admin or Owner requests the reversal with a reason. It takes effect only
when ANOTHER person from these roles approves it (like R81). The reversal returns the money
to the account via a reverse entry in the payment register (FLOW-006) and returns the
tranche to 'pending', no deletion, with history. While waiting for approval the tranche
stays paid."

Canon: CLAUDE.md §2.5, §2.9, §7, §8, §14; FLOW-006 §Корекции, FLOW-028; R29; FG-34 (PAY-01
reversal), FG-45 (a module-owned payment is reversed in its module); FIX-PAY-01 (Р97).

    POST /api/contract-payments/{id}/tranches/{idx}/reversal-request  {reason}
    POST /api/contract-payments/{id}/tranches/{idx}/reversal-approve  {request_id}
    POST /api/contract-payments/{id}/tranches/{idx}/reversal-reject   {request_id}

  1. request -> the tranche stays paid, the ledger is unchanged, the request is recorded;
  2. the requester approving / rejecting his own request -> 403, nothing written;
  3. another person approves -> the Outflow is ``reversed`` (kept), ONE reversal Inflow row,
     the tranche pending with ``payment_history``, generation 1, contract active again, the
     account balance restored, the project P&L contract cost back, the forecast shows the
     tranche again; paying again writes a NEW ledger row (generation 1);
  4. reject -> the request is closed in history, nothing else; a new request is possible;
  5. replay / double approve / approve after reject -> idempotent or 409, nothing written;
  6. no key -> 428; 7. forbidden roles -> 403; 8. tenant isolation -> 404;
  9. a tranche paid before FIX-PAY-01 (no ledger row) -> 409, nothing written;
 10. an approval interrupted after the ledger reversal resumes with the same key.

Runs in PERMISSION_SERVICE_MODE off / shadow / enforce, on mongomock and, when
``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB, on it as well (databases
``fixtest_pay2_*``, dropped afterwards).

    PYTHONPATH=. pytest tests/test_fix_pay_02_tranche_reversal.py -q --noconftest -p no:cacheprovider
"""
import asyncio
import uuid

import pytest

from tests.test_fix_pay_01_tranche_ledger import (
    BANK_A, BANK_B, CASH_A, CP_A, CP_B, CP_LEGACY, MODES, ORG_A, ORG_B, PRJ_A, _app,
    _bootstrap_indexes, _seed, body, hdr, snap,
)
from tests.test_r0_05_pay_run_selected_only import _real_refusal

PAY = "/api/contract-payments/%s/pay-tranche"
REQ = "/api/contract-payments/%s/tranches/%d/reversal-request"
APPROVE = "/api/contract-payments/%s/tranches/%d/reversal-approve"
REJECT = "/api/contract-payments/%s/tranches/%d/reversal-reject"
LEDGER = ("finance_payments", "contract_payments", "audit_logs", "audit_events")


@pytest.fixture(params=["mongomock", pytest.param("real", marks=pytest.mark.skipif(
    bool(_real_refusal()), reason=_real_refusal() or "ok"))])
def backend(request):
    return request.param


@pytest.fixture(params=MODES)
def mode(request):
    return request.param


class _Dbs:
    def __init__(self, backend):
        tag = uuid.uuid4().hex[:10]
        self.backend, self.client = backend, None
        self.names = ("fixtest_pay2_op_" + tag, "fixtest_pay2_sys_" + tag)

    async def __aenter__(self):
        if self.backend == "real":
            from motor.motor_asyncio import AsyncIOMotorClient
            from tests.test_w0_03c_real_mongo import REAL_URL
            self.client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        else:
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
        return self.client[self.names[0]], self.client[self.names[1]]

    async def __aexit__(self, *exc):
        if self.backend == "real":
            for name in self.names:
                assert name.startswith("fixtest_pay2_")
                await self.client.drop_database(name)
            self.client.close()


def run(monkeypatch, backend, mode, scenario):
    import httpx

    async def go():
        async with _Dbs(backend) as (op, sysdb):
            await _bootstrap_indexes(op)
            await _seed(op, sysdb)
            app = _app(monkeypatch, op, sysdb, mode)
            from app.services import cashflow_forecast
            monkeypatch.setattr(cashflow_forecast, "db", op)

            async def _no_payslips(*a, **kw):   # payroll is not under test (and reads app.db)
                return []
            monkeypatch.setattr(cashflow_forecast, "legacy_payslips", _no_payslips)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://fixpay02") as c:
                return await scenario(c, op)
    return asyncio.run(go())


# ─────────────────────────────────────────────────────────────────── helpers
async def pay(c, idx=0, who="acct-a", account=CASH_A, cp=CP_A):
    r = await c.post(PAY % cp, json=body(idx, account), headers=hdr(who))
    assert r.status_code == 200, r.text
    return r.json()["tranches"][idx]["payment_id"]


async def request(c, idx=0, who="acct-a", reason="грешна сума", key=None, cp=CP_A):
    return await c.post(REQ % (cp, idx), json={"reason": reason}, headers=hdr(who, key))


async def tranche(op, cp_id=CP_A, idx=0):
    doc = await op.contract_payments.find_one({"id": cp_id}, {"_id": 0})
    return doc["tranches"][idx], doc


async def balance(op, account):
    from app.services.payment_state import active_payments
    acc = await op.financial_accounts.find_one({"id": account}, {"_id": 0})
    total = acc.get("opening_balance", 0)
    for row in await op.finance_payments.find(active_payments({"account_id": account}),
                                              {"_id": 0}).to_list(None):
        total += row["amount"] if row["direction"] == "Inflow" else -row["amount"]
    return round(total, 2)


async def api_balance(c, account, who="acct-a"):
    r = await c.get("/api/finance/accounts", headers=hdr(who, False))
    assert r.status_code == 200, r.text
    return next(a for a in r.json() if a["id"] == account)["current_balance"]


async def contract_cost():
    from app.services.project_pnl import compute_project_pnl
    return (await compute_project_pnl(ORG_A, PRJ_A))["expense"]["contract_cost"]


async def forecast_has(cp_id):
    from app.services.cashflow_forecast import build_cashflow_forecast
    f = await build_cashflow_forecast(ORG_A, 30, "2026-11-10")
    return any(i.get("source_type") == "contract_payment" and i.get("source_id") == cp_id
               for i in f["outgoing"])


# ═══════════════════════════════════════════════════════════ 1. request only
def test_01_request_keeps_tranche_paid_and_ledger_unchanged(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c)
        bal = await balance(op, CASH_A)
        ledger0 = await snap(op, ("finance_payments",))
        r = await request(c, reason="  грешна сума  ")
        assert r.status_code == 200, r.text
        tr, doc = await tranche(op)
        assert tr["status"] == "paid" and tr["payment_id"] == pid      # stays paid
        req = tr["reversal_request"]
        assert req["status"] == "pending" and req["reason"] == "грешна сума"
        assert req["requested_by"] == "acct-a" and req["requested_at"] and req["id"]
        assert req["payment_id"] == pid
        assert r.json()["tranches"][0]["reversal_request"]["id"] == req["id"]
        assert await snap(op, ("finance_payments",)) == ledger0          # money untouched
        assert await balance(op, CASH_A) == bal
        assert await contract_cost() == 470.0                            # 400 + legacy 70
        audits = await op.audit_logs.find({"action": "contract_tranche_reversal_requested"},
                                          {"_id": 0}).to_list(None)
        assert len(audits) == 1 and audits[0]["changes"]["request_id"] == req["id"]
        # one open request per tranche
        r2 = await request(c, who="owner-a", reason="друга")
        assert r2.status_code == 409, r2.text
        assert r2.json()["detail"]["error_code"] == "REVERSAL_REQUEST_ALREADY_OPEN"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 2. second person
def test_02_requester_cannot_decide_own_request(monkeypatch, backend, mode):
    async def scenario(c, op):
        await pay(c)
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        before = await snap(op)
        for url in (APPROVE, REJECT):
            r = await c.post(url % (CP_A, 0), json={"request_id": rid}, headers=hdr("acct-a"))
            assert r.status_code == 403, r.text
            assert r.json()["detail"]["error_code"] == "REVERSAL_SECOND_PERSON_REQUIRED"
        assert await snap(op) == before
        assert (await tranche(op))[0]["status"] == "paid"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 3. approval
def test_03_other_person_approves_reversal_takes_effect(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.routes.hr import _tranche_ledger_id
        cost0 = await contract_cost()                                    # 70 (legacy)
        bal0 = await balance(op, CASH_A)
        api0 = await api_balance(c, CASH_A)
        assert await forecast_has(CP_A)
        pid = await pay(c, 0)
        await pay(c, 1, who="admin-a", account=BANK_A)
        _, doc = await tranche(op)
        assert doc["status"] == "completed" and not await forecast_has(CP_A)
        assert await balance(op, CASH_A) == bal0 - 400.0
        assert await contract_cost() == cost0 + 650.0
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]

        r = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a"))
        assert r.status_code == 200, r.text
        # the ledger: original kept as reversed, ONE reversal Inflow row, nothing deleted
        orig = await op.finance_payments.find_one({"id": pid}, {"_id": 0})
        assert orig["status"] == "reversed" and orig["reversal_reason"] == "грешна сума"
        assert orig["reversed_by"] == "owner-a" and orig["amount"] == 400.0
        revs = await op.finance_payments.find({"reverses_payment_id": pid}, {"_id": 0}).to_list(None)
        assert len(revs) == 1
        rev = revs[0]
        assert rev["status"] == "reversal" and rev["direction"] == "Inflow"
        assert rev["amount"] == 400.0 and rev["account_id"] == CASH_A
        assert rev["id"] == orig["reversed_by_payment_id"]
        assert rev["contract_payment_id"] == CP_A and rev["tranche_index"] == 0
        assert await op.finance_payments.count_documents({}) == 3          # 2 payments + 1 reversal
        # the tranche: pending, with history, next generation
        tr, doc = await tranche(op)
        assert tr["status"] == "pending" and tr["payment_id"] is None
        assert tr["paid_date"] is None and tr["account_id"] is None
        assert tr["reversal_request"] is None and tr["payment_generation"] == 1
        (h,) = tr["payment_history"]
        assert h["payment_id"] == pid and h["reversal_payment_id"] == rev["id"]
        assert h["requested_by"] == "acct-a" and h["approved_by"] == "owner-a"
        assert h["account_id"] == CASH_A and h["paid_date"] == "2026-11-16" and h["amount"] == 400.0
        (d,) = tr["reversal_history"]
        assert d["id"] == rid and d["status"] == "approved" and d["decided_by"] == "owner-a"
        assert doc["status"] == "active"                                  # completed -> active
        assert doc["tranches"][1]["status"] == "paid"                     # the other tranche
        # money and results back
        assert await balance(op, CASH_A) == bal0
        assert await api_balance(c, CASH_A) == api0
        assert await contract_cost() == cost0 + 250.0                     # tranche 0 not cost
        assert await forecast_has(CP_A)                                    # pending again
        # the finance list hides the reversed pair by default
        lst = await c.get("/api/finance/payments", headers=hdr("acct-a", False))
        assert lst.status_code == 200, lst.text
        listed = [x.get("id") for x in lst.json()]
        assert pid not in listed and rev["id"] not in listed
        audits = await op.audit_logs.find({"action": "contract_tranche_reversed"}, {"_id": 0}).to_list(None)
        assert len(audits) == 1
        assert await op.audit_events.count_documents(
            {"action": "finance.payment.reversed", "entity_id": pid}) == 1
        # the generic finance reversal still refuses the tranche's rows (FG-45)
        rr = await c.request("DELETE", "/api/finance/payments/" + rev["id"],
                             json={"reason": "x"}, headers=hdr("acct-a"))
        assert rr.status_code == 409, rr.text

        # paid again -> a NEW ledger row, generation 1
        pid2 = await pay(c, 0, who="admin-a", account=BANK_A)
        assert pid2 != pid and pid2 == _tranche_ledger_id(ORG_A, CP_A, 0, 1)
        new = await op.finance_payments.find_one({"id": pid2}, {"_id": 0})
        assert "status" not in new and new["account_id"] == BANK_A and new["amount"] == 400.0
        assert await contract_cost() == cost0 + 650.0
        tr, doc = await tranche(op)
        assert tr["status"] == "paid" and len(tr["payment_history"]) == 1
        assert doc["status"] == "completed"
        # and that payment can be reversed again: generation 2
        rid2 = (await request(c, who="admin-a", reason="пак")).json()["tranches"][0]["reversal_request"]["id"]
        r = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid2}, headers=hdr("acct-a"))
        assert r.status_code == 200, r.text
        tr, _ = await tranche(op)
        assert tr["payment_generation"] == 2 and len(tr["payment_history"]) == 2
        assert await op.finance_payments.count_documents({"reverses_payment_id": pid2}) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 4. rejection
def test_04_reject_closes_request_only(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c)
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        ledger0 = await snap(op, ("finance_payments",))
        r = await c.post(REJECT % (CP_A, 0), json={"request_id": rid, "reason": "сумата е вярна"},
                         headers=hdr("admin-a"))
        assert r.status_code == 200, r.text
        tr, _ = await tranche(op)
        assert tr["status"] == "paid" and tr["payment_id"] == pid
        assert tr.get("reversal_request") is None and not tr.get("payment_history")
        (d,) = tr["reversal_history"]
        assert d["status"] == "rejected" and d["decided_by"] == "admin-a"
        assert d["decision_reason"] == "сумата е вярна"
        assert await snap(op, ("finance_payments",)) == ledger0
        assert await op.audit_logs.count_documents({"action": "contract_tranche_reversal_rejected"}) == 1
        # a rejected request cannot be approved afterwards
        r = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a"))
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "REVERSAL_REQUEST_NOT_OPEN"
        assert await snap(op, ("finance_payments",)) == ledger0
        # a new request is possible
        r = await request(c, who="owner-a", reason="все пак")
        assert r.status_code == 200, r.text
        assert r.json()["tranches"][0]["reversal_request"]["id"] != rid
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 5. idempotency
def test_05_replay_and_double_approve(monkeypatch, backend, mode):
    async def scenario(c, op):
        await pay(c)
        r1 = await request(c, key="k-req")
        assert r1.status_code == 200, r1.text
        after = await snap(op)
        r = await request(c, key="k-req")                                   # replay
        assert r.status_code == 200 and r.json() == r1.json()
        assert await snap(op) == after
        r = await request(c, key="k-req", reason="друга причина")           # same key, other body
        assert r.status_code == 409, r.text
        assert await snap(op) == after
        rid = r1.json()["tranches"][0]["reversal_request"]["id"]

        a1 = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a", "k-ap"))
        assert a1.status_code == 200, a1.text
        done = await snap(op)
        a2 = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a", "k-ap"))
        assert a2.status_code == 200 and a2.json() == a1.json()             # replay
        assert await snap(op) == done
        for who, url in (("owner-a", APPROVE), ("admin-a", APPROVE), ("admin-a", REJECT)):
            r = await c.post(url % (CP_A, 0), json={"request_id": rid}, headers=hdr(who))
            assert r.status_code == 409, r.text                               # new key: decided
            assert r.json()["detail"]["error_code"] == "REVERSAL_REQUEST_NOT_OPEN"
        money = ("finance_payments", "contract_payments", "audit_logs", "audit_events")
        assert await snap(op, money) == {k: done[k] for k in money}           # nothing written
        assert await op.finance_payments.count_documents({"status": "reversal"}) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 6. no key
def test_06_no_key_is_428(monkeypatch, backend, mode):
    async def scenario(c, op):
        await pay(c)
        before = await snap(op)
        for key in (False, "", "   "):
            r = await request(c, key=key)
            assert r.status_code == 428, r.text
            assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
        assert await snap(op) == before
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        before = await snap(op)
        for url in (APPROVE, REJECT):
            r = await c.post(url % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a", False))
            assert r.status_code == 428, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 7. forbidden
@pytest.mark.parametrize("who", ["viewer-a", "site-a", "tech-a"])
def test_07_forbidden_roles_are_403(monkeypatch, backend, mode, who):
    async def scenario(c, op):
        await pay(c)
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        before = await snap(op)
        for key in (None, False):
            r = await request(c, who=who, key=key)
            assert r.status_code == 403, r.text
            for url in (APPROVE, REJECT):
                r = await c.post(url % (CP_A, 0), json={"request_id": rid}, headers=hdr(who, key))
                assert r.status_code == 403, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 8. tenants
def test_08_tenant_isolation(monkeypatch, backend, mode):
    async def scenario(c, op):
        await pay(c)
        await pay(c, 0, who="admin-b", account=BANK_B, cp=CP_B)
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        before = await snap(op)
        r = await request(c, who="admin-b")                                  # A's contract
        assert r.status_code == 404, r.text
        for url in (APPROVE, REJECT):
            r = await c.post(url % (CP_A, 0), json={"request_id": rid}, headers=hdr("admin-b"))
            assert r.status_code == 404, r.text
        r = await request(c, who="owner-a", cp=CP_B)                          # B's contract
        assert r.status_code == 404, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 9. legacy / state / reason
def test_09_legacy_paid_without_ledger_and_bad_requests(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await snap(op)
        r = await request(c, cp=CP_LEGACY, idx=0)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "TRANCHE_PAID_WITHOUT_LEDGER_PAYMENT"
        r = await request(c, idx=0)                                           # pending tranche
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "TRANCHE_NOT_PAID"
        r = await request(c, idx=7)
        assert r.status_code == 400, r.text
        assert await snap(op) == before                                       # not even a key
        await pay(c)
        before = await snap(op)
        for reason in ("", "   ", None):
            r = await c.post(REQ % (CP_A, 0), json={"reason": reason}, headers=hdr("acct-a"))
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["error_code"] == "REASON_REQUIRED"
        r = await c.post(APPROVE % (CP_A, 0), json={}, headers=hdr("owner-a"))
        assert r.status_code == 422, r.text
        r = await c.post(APPROVE % (CP_A, 0), json={"request_id": "nope"}, headers=hdr("owner-a"))
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "REVERSAL_REQUEST_NOT_OPEN"
        assert await snap(op) == before
        # a contract with a reversed payment is never hard-deleted
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        assert (await c.post(APPROVE % (CP_A, 0), json={"request_id": rid},
                             headers=hdr("owner-a"))).status_code == 200
        r = await c.delete("/api/contract-payments/" + CP_A, headers=hdr("owner-a", False))
        assert r.status_code == 400, r.text
        assert await op.contract_payments.count_documents({"id": CP_A}) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 10. interrupted approval
def test_10_interrupted_approval_resumes_with_same_key(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.routes import hr as r_hr
        pid = await pay(c)
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        real = r_hr.log_audit
        calls = {"n": 0}

        async def flaky(*a, **kw):
            if a[3] == "contract_tranche_reversed" and calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("crash after the writes")
            return await real(*a, **kw)
        monkeypatch.setattr(r_hr, "log_audit", flaky)
        with pytest.raises(RuntimeError):
            await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a", "k-x"))
        # someone else, a new key: already decided -> 409, nothing written
        r = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("admin-a"))
        assert r.status_code == 409, r.text
        r = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a", "k-x"))
        assert r.status_code == 200, r.text
        assert await op.finance_payments.count_documents({"reverses_payment_id": pid}) == 1
        assert await op.audit_logs.count_documents({"action": "contract_tranche_reversed"}) == 1
        tr, _ = await tranche(op)
        assert tr["status"] == "pending" and len(tr["payment_history"]) == 1
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 11. approve wins over reject
def test_11_claimed_approval_blocks_reject(monkeypatch, backend, mode):
    """Once an approver claimed the request ("approving"), a reject cannot close it — the
    tranche can never end up paid over a reversed payment."""
    async def scenario(c, op):
        await pay(c)
        rid = (await request(c)).json()["tranches"][0]["reversal_request"]["id"]
        await op.contract_payments.update_one(
            {"id": CP_A}, {"$set": {"tranches.0.reversal_request.status": "approving"}})
        r = await c.post(REJECT % (CP_A, 0), json={"request_id": rid}, headers=hdr("admin-a"))
        assert r.status_code == 409, r.text
        r = await c.post(APPROVE % (CP_A, 0), json={"request_id": rid}, headers=hdr("owner-a"))
        assert r.status_code == 200, r.text                                   # resumes
        assert (await tranche(op))[0]["status"] == "pending"
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ 12. one open request (race)
def test_12_second_request_loses_the_race(monkeypatch, backend, mode):
    """Two requests that both read the tranche without a request: the conditional write
    lets only the first one in (on a real MongoDB too — see the null-on-array-path note)."""
    async def scenario(c, op):
        from app.routes import hr as r_hr
        await pay(c)
        first = (await request(c)).json()["tranches"][0]["reversal_request"]
        real = r_hr._load_tranche
        stale = {"n": 0}

        async def stale_once(*a, **kw):
            doc, tr = await real(*a, **kw)
            if stale["n"] == 0:                     # the pre-check reads an old state
                stale["n"] += 1
                tr = {k: v for k, v in tr.items() if k != "reversal_request"}
            return doc, tr
        monkeypatch.setattr(r_hr, "_load_tranche", stale_once)
        r = await request(c, who="owner-a", reason="втора")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "REVERSAL_REQUEST_ALREADY_OPEN"
        tr, _ = await tranche(op)
        assert tr["reversal_request"] == first                                  # not overwritten
    run(monkeypatch, backend, mode, scenario)
