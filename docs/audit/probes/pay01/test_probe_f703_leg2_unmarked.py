"""CLAUDE AUDIT probe — #70 0713a81 (F-70-03). A transfer reversal interrupted AFTER leg 1 is
fully reversed (row + event) but BEFORE leg 2 is marked reversed. Then:
  N1: a NEW key on the URL leg (leg 1) → 409 "already reversed"; does leg 2 stay ACTIVE?
  N2: the SAME key retried → 200, both legs reversed (expected to pass).
  N3: a NEW key on leg 2's URL → recovers both legs?
Copy into backend/tests/ and run with W0_03_REAL_MONGO_URL set (mongomock + real).
"""
import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    BANK_A, CASH_A, backend, hdr, mode, reverse, run,
)


def _fail_before_nth(monkeypatch, module, name, nth):
    original = getattr(module, name)
    state = {"n": 0}

    async def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == nth:
            raise RuntimeError("synthetic interruption before call %d of %s" % (nth, name))
        return await original(*a, **k)
    monkeypatch.setattr(module, name, flaky)
    return lambda: setattr(module, name, original)


async def _setup(c, op, monkeypatch, key):
    from app.routes import finance
    r = await c.post("/api/finance/transfers", headers=hdr("acct-a"),
                     json={"from_account_id": BANK_A, "to_account_id": CASH_A, "amount": 50})
    assert r.status_code == 201, r.text
    legs = await op.finance_payments.find({"transfer_id": r.json()["transfer_id"]}, {"_id": 0}).to_list(None)
    leg1, leg2 = sorted(l["id"] for l in legs)        # the URL leg sorts first in delete_payment
    restore = _fail_before_nth(monkeypatch, finance, "_reverse_one", 2)   # leg 1 done; leg 2 never marked
    with pytest.raises(RuntimeError):
        await reverse(c, leg1, key=key)
    restore()
    s1 = (await op.finance_payments.find_one({"id": leg1})).get("status")
    s2 = (await op.finance_payments.find_one({"id": leg2})).get("status")
    assert s1 == "reversed" and s2 != "reversed", (s1, s2)
    return leg1, leg2


async def _state(op, leg):
    row = await op.finance_payments.find_one({"id": leg}, {"_id": 0})
    return row.get("status"), await op.finance_payments.count_documents({"reverses_payment_id": leg})


def test_n1_new_key_on_leg1_leaves_leg2_active(monkeypatch, backend, mode):
    async def scenario(c, op):
        leg1, leg2 = await _setup(c, op, monkeypatch, "k-n1-a")
        r = await reverse(c, leg1, key="k-n1-b")
        print("N1 new key on leg1 →", r.status_code, "leg1", await _state(op, leg1), "leg2", await _state(op, leg2))
        assert (await _state(op, leg2))[0] == "reversed", "transfer left HALF-reversed: leg 2 still counts"
    run(monkeypatch, backend, mode, scenario)


def test_n2_same_key_recovers(monkeypatch, backend, mode):
    async def scenario(c, op):
        leg1, leg2 = await _setup(c, op, monkeypatch, "k-n2")
        r = await reverse(c, leg1, key="k-n2")
        assert r.status_code == 200, r.text
        assert await _state(op, leg1) == ("reversed", 1) and await _state(op, leg2) == ("reversed", 1)
    run(monkeypatch, backend, mode, scenario)


def test_n3_new_key_on_leg2_recovers(monkeypatch, backend, mode):
    async def scenario(c, op):
        leg1, leg2 = await _setup(c, op, monkeypatch, "k-n3-a")
        r = await reverse(c, leg2, key="k-n3-b")
        print("N3 new key on leg2 →", r.status_code)
        assert await _state(op, leg1) == ("reversed", 1) and await _state(op, leg2) == ("reversed", 1)
    run(monkeypatch, backend, mode, scenario)
