"""
PAY-01-C01 Addendum B — decision R29 (Krum, 06.11.2026): a money write without an
Idempotency-Key is refused (protection against a double payment).

Every money POST/DELETE in ``finance.py`` — payment, invoice quick-pay, transfer,
account funding, other expense, other income, allocate, payment reversal, allocation
cancel:

  * no ``Idempotency-Key`` → 428 ``IDEMPOTENCY_KEY_REQUIRED``, nothing written;
  * the same key and the same request again → the same response, ONE set of rows;
  * the same key with a different request → 409 ``IDEMPOTENCY_KEY_REUSED``, nothing written;
  * the same key while the first attempt is still running → 409 ``IDEMPOTENCY_IN_PROGRESS``;
  * keys are per tenant: tenant B may use a key tenant A already used.

Runs in PERMISSION_SERVICE_MODE off / shadow / enforce, on mongomock and, when
``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB, on it as well.
"""
import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    BANK_A, BANK_B, CASH_A, ORG_A, backend, hdr, mode, pay, quick_pay, reverse, run, snap,
)

ROWS = ("finance_payments", "payment_allocations")


async def _counts(op):
    return {c: await op[c].count_documents({}) for c in ROWS}


# endpoint → (url, valid body, a different valid body, new rows: payments, allocations)
def _writes(pid=None):
    return {
        "payment": ("/api/finance/payments",
                    {"direction": "Inflow", "amount": 10, "date": "2026-11-06", "method": "BankTransfer",
                     "account_id": BANK_A},
                    {"direction": "Inflow", "amount": 11, "date": "2026-11-06", "method": "BankTransfer",
                     "account_id": BANK_A}, (1, 0)),
        "invoice_quick_pay": ("/api/finance/invoices/inv-a1/payments",
                              {"amount": 10, "method": "BankTransfer", "account_id": BANK_A},
                              {"amount": 12, "method": "BankTransfer", "account_id": BANK_A}, (1, 1)),
        "transfer": ("/api/finance/transfers",
                     {"from_account_id": BANK_A, "to_account_id": CASH_A, "amount": 10},
                     {"from_account_id": BANK_A, "to_account_id": CASH_A, "amount": 13}, (2, 0)),
        "account_funding": ("/api/finance/account-funding", {"account_id": BANK_A, "amount": 10},
                            {"account_id": BANK_A, "amount": 14}, (1, 0)),
        "other_expense": ("/api/finance/other-expense",
                          {"project_id": "prj-1", "amount": 10, "method": "Cash"},
                          {"project_id": "prj-1", "amount": 15, "method": "Cash"}, (1, 0)),
        "other_income": ("/api/finance/other-income",
                         {"project_id": "prj-1", "amount": 10, "method": "Cash"},
                         {"project_id": "prj-1", "amount": 16, "method": "Cash"}, (1, 0)),
        "allocate": ("/api/finance/payments/%s/allocate" % pid,
                     {"allocations": [{"invoice_id": "inv-a1", "amount": 10}]},
                     {"allocations": [{"invoice_id": "inv-a1", "amount": 17}]}, (0, 1)),
    }


ENDPOINTS = sorted(_writes())


async def _setup(c, endpoint):
    pid = await pay(c, 300.0) if endpoint == "allocate" else None
    return _writes(pid)[endpoint]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_r29_no_key_is_428_and_writes_nothing(monkeypatch, backend, mode, endpoint):
    async def scenario(c, op):
        url, body, _, _ = await _setup(c, endpoint)
        before = await snap(op)
        for key in (False, "", "   "):
            r = await c.post(url, json=body, headers=hdr("acct-a", key))
            assert r.status_code == 428, (endpoint, repr(key), r.text)
            assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
        assert await snap(op) == before                     # no row, no audit, no key record
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_r29_same_key_replays_one_write(monkeypatch, backend, mode, endpoint):
    async def scenario(c, op):
        url, body, other, (n_pay, n_alloc) = await _setup(c, endpoint)
        c0 = await _counts(op)
        key = "k-r29-" + endpoint
        r1 = await c.post(url, json=body, headers=hdr("acct-a", key))
        assert r1.status_code in (200, 201), r1.text
        c1 = await _counts(op)
        assert c1["finance_payments"] - c0["finance_payments"] == n_pay, endpoint
        assert c1["payment_allocations"] - c0["payment_allocations"] == n_alloc, endpoint
        before = await snap(op)
        r2 = await c.post(url, json=body, headers=hdr("acct-a", key))   # double click / retry
        assert r2.status_code == r1.status_code and r2.json() == r1.json(), (r1.text, r2.text)
        assert await snap(op) == before                     # nothing written the second time
        # the same key for a DIFFERENT request → 409, nothing written
        r3 = await c.post(url, json=other, headers=hdr("acct-a", key))
        assert r3.status_code == 409, r3.text
        assert r3.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REUSED"
        assert await snap(op) == before
        # a new key → a new write
        r4 = await c.post(url, json=other, headers=hdr("acct-a", key + "-2"))
        assert r4.status_code in (200, 201), r4.text
    run(monkeypatch, backend, mode, scenario)


def test_r29_key_in_progress_is_409(monkeypatch, backend, mode):
    async def scenario(c, op):
        from app.audit.idempotency import begin_idempotent
        # the first attempt reserved the key and has not finished (in flight / crashed)
        await begin_idempotent(op, tenant_id=ORG_A, key="k-busy", action="finance.transfer.create")
        before = await snap(op)
        r = await c.post("/api/finance/transfers", headers=hdr("acct-a", "k-busy"),
                         json={"from_account_id": BANK_A, "to_account_id": CASH_A, "amount": 10})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


def test_r29_failed_attempt_can_be_retried(monkeypatch, backend, mode):
    """A refused attempt (404 account) marks the key failed; the same key may try again."""
    async def scenario(c, op):
        body = {"account_id": "acc-missing", "amount": 10}
        r = await c.post("/api/finance/account-funding", json=body, headers=hdr("acct-a", "k-fail"))
        assert r.status_code == 404, r.text
        rec = await op.audit_idempotency.find_one({"key": "k-fail"}, {"_id": 0})
        assert rec["status"] == "failed"
        r = await c.post("/api/finance/account-funding", json=body, headers=hdr("acct-a", "k-fail"))
        assert r.status_code == 404, r.text                 # re-run, not a 409
        assert await op.finance_payments.count_documents({}) == 0
    run(monkeypatch, backend, mode, scenario)


def test_r29_keys_are_per_tenant(monkeypatch, backend, mode):
    async def scenario(c, op):
        r_a = await c.post("/api/finance/account-funding", headers=hdr("acct-a", "k-shared"),
                           json={"account_id": BANK_A, "amount": 10})
        r_b = await c.post("/api/finance/account-funding", headers=hdr("admin-b", "k-shared"),
                           json={"account_id": BANK_B, "amount": 10})
        assert r_a.status_code == r_b.status_code == 201, (r_a.text, r_b.text)
        assert r_a.json()["id"] != r_b.json()["id"]
        rows = await op.finance_payments.find({}, {"_id": 0, "org_id": 1, "account_id": 1}).to_list(None)
        assert sorted((r["org_id"], r["account_id"]) for r in rows) == sorted(
            [(ORG_A, BANK_A), ("ORG-PAY01-B", BANK_B)])
    run(monkeypatch, backend, mode, scenario)


def test_r29_reversal_without_key_is_428(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 40.0)
        before = await snap(op)
        r = await reverse(c, pid, key=False)
        assert r.status_code == 428, r.text
        assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


def test_r29_allocation_cancel_without_key_is_428(monkeypatch, backend, mode):
    async def scenario(c, op):
        res = await quick_pay(c, "inv-a1", 30.0)
        before = await snap(op)
        r = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/" + res["allocation_id"],
                            json={"reason": "грешка"}, headers=hdr("acct-a", False))
        assert r.status_code == 428, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


def test_r29_non_finance_role_still_403_first(monkeypatch, backend, mode):
    async def scenario(c, op):
        before = await snap(op)
        r = await c.post("/api/finance/transfers", headers=hdr("viewer-a", False),
                         json={"from_account_id": BANK_A, "to_account_id": CASH_A, "amount": 10})
        assert r.status_code == 403, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)
