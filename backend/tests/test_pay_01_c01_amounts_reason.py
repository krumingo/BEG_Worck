"""
PAY-01-C01 Part 1 — amounts and reversal reasons (CLAUDE.md §14 validation/DQ, FLOW-006, R23).

Package: ``docs/architecture/tasks/PAY-01-C01_AMOUNTS_REASON_SUBCONTRACTOR.md``.

  PAY-N1  every money-writing POST in ``finance.py`` (payment, invoice quick-pay, transfer,
          account funding, other expense/income, allocate) refuses NaN / ±Infinity / 1e309 /
          "" / -1 / 0 with 422 and writes NOTHING (no payment, allocation or audit row).
          Allocate checks every amount before the first allocation is written.
  PAY-N2  a reversal / cancellation reason longer than 500 characters or carrying control /
          invisible characters (NUL, ESC, bidi, zero-width) → 400, nothing written.

Runs in PERMISSION_SERVICE_MODE off / shadow / enforce, on mongomock and, when
``W0_03_REAL_MONGO_URL`` names a disposable LOCAL MongoDB, on it as well.

    PYTHONPATH=. pytest tests/test_pay_01_c01_amounts_reason.py -q --noconftest -p no:cacheprovider
"""
import pytest

from tests.test_pay_01_payment_reversal import (  # noqa: F401  (fixtures)
    BANK_A, CASH_A, backend, hdr, mode, pay, quick_pay, reverse, run, snap,
)

# Raw JSON tokens: Python's json (used by Starlette) parses NaN/Infinity and turns 1e309 into inf.
# The package list (nan/inf/-inf/1e309/""/-1/0) plus text forms, null, booleans and other
# non-numbers. L1: `true` (→ 1.0) and numeric text ("12.5") are refused before coercion on
# every route, the two Pydantic ones (payment, allocate) included.
BAD = ["NaN", "Infinity", "-Infinity", "1e309", "-1e309", '""', "-1", "0", '"nan"', '"1e309"',
       "null", '"abc"', "true", "false", '"12.5"', "[12.5]", '{"v": 12.5}']


def _body(template: str, token: str) -> bytes:
    return template.replace("@AMOUNT@", token).encode()


def _post(c, url, template, token, who="acct-a"):
    h = dict(hdr(who))
    h["Content-Type"] = "application/json"
    return c.post(url, content=_body(template, token), headers=h)


ENDPOINTS = {
    "payment": ("/api/finance/payments",
                '{"direction": "Inflow", "amount": @AMOUNT@, "date": "2026-11-05", '
                '"method": "BankTransfer", "account_id": "%s"}' % BANK_A),
    "invoice_quick_pay": ("/api/finance/invoices/inv-a1/payments",
                          '{"amount": @AMOUNT@, "method": "BankTransfer", "account_id": "%s"}' % BANK_A),
    "transfer": ("/api/finance/transfers",
                 '{"from_account_id": "%s", "to_account_id": "%s", "amount": @AMOUNT@}' % (BANK_A, CASH_A)),
    "account_funding": ("/api/finance/account-funding", '{"account_id": "%s", "amount": @AMOUNT@}' % BANK_A),
    "other_expense": ("/api/finance/other-expense",
                      '{"project_id": "prj-1", "amount": @AMOUNT@, "method": "Cash"}'),
    "other_income": ("/api/finance/other-income",
                     '{"project_id": "prj-1", "amount": @AMOUNT@, "method": "Cash"}'),
}


# ═══════════════════════════════════════════════════════════ PAY-N1: amounts
@pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
def test_n1_bad_amount_is_422_and_writes_nothing(monkeypatch, backend, mode, endpoint):
    url, template = ENDPOINTS[endpoint]

    async def scenario(c, op):
        before = await snap(op)
        for token in BAD:
            r = await _post(c, url, template, token)
            assert r.status_code == 422, (endpoint, token, r.status_code, r.text)
            assert r.json()["detail"], (endpoint, token)
        assert await snap(op) == before, endpoint            # 0 rows, no audit, no idempotency
        # the same endpoint still accepts a good amount (positive control)
        r = await _post(c, url, template, "12.5")
        assert r.status_code == 201, (endpoint, r.text)
        assert await op.finance_payments.count_documents({}) >= 1
    run(monkeypatch, backend, mode, scenario)


def test_n1_allocate_checks_every_amount_before_writing(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 300.0)
        before = await snap(op)
        for token in BAD:
            body = ('{"allocations": [{"invoice_id": "inv-a1", "amount": 10}, '
                    '{"invoice_id": "inv-a2", "amount": @AMOUNT@}]}')
            r = await _post(c, "/api/finance/payments/%s/allocate" % pid, body, token)
            assert r.status_code == 422, (token, r.status_code, r.text)
            assert await snap(op) == before, token           # the good first item is not written
        r = await c.post("/api/finance/payments/%s/allocate" % pid, headers=hdr("acct-a"),
                         json={"allocations": [{"invoice_id": "inv-a1", "amount": 10}]})
        assert r.status_code == 200, r.text
        assert await op.payment_allocations.count_documents({"payment_id": pid}) == 1
    run(monkeypatch, backend, mode, scenario)


def test_n1_non_finance_role_still_403_before_amount(monkeypatch, backend, mode):
    url, template = ENDPOINTS["payment"]

    async def scenario(c, op):
        before = await snap(op)
        r = await _post(c, url, template, "NaN", who="viewer-a")
        assert r.status_code == 403, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ PAY-N2: reason
BAD_REASONS = {
    "too_long": "а" * 501,
    "nul": "грешка\x00скрито",
    "esc": "грешка\x1b[31m",
    "bidi_override": "грешка \u202eтекст",
    "bidi_isolate": "грешка \u2066текст\u2069",
    "zero_width": "гре\u200bшка",
    "bom": "гре\ufeffшка",
    "c1": "гре\x85шка",
    "soft_hyphen": "гре\u00adшка",                     # Cf
    "tag_char": "грешка\U000e0041",                   # Cf (tag LATIN CAPITAL A)
    "line_separator": "ред 1\u2028ред 2",             # Zl
    "paragraph_separator": "ред 1\u2029ред 2",        # Zp
}


@pytest.mark.parametrize("kind", sorted(BAD_REASONS))
def test_n2_bad_reason_on_payment_reversal_is_400(monkeypatch, backend, mode, kind):
    async def scenario(c, op):
        pid = await pay(c, 40.0)
        before = await snap(op)
        r = await reverse(c, pid, key="k-n2-" + kind, reason=BAD_REASONS[kind])
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["error_code"] in ("REASON_TOO_LONG", "REASON_INVALID_CHARS")
        r = await c.request("DELETE", "/api/finance/payments/" + pid,
                            params={"reason": BAD_REASONS[kind]}, headers=hdr("acct-a"))
        assert r.status_code == 400, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("kind", ["too_long", "nul", "bidi_override", "zero_width"])
def test_n2_bad_reason_on_allocation_cancel_is_400(monkeypatch, backend, mode, kind):
    async def scenario(c, op):
        res = await quick_pay(c, "inv-a1", 30.0)
        before = await snap(op)
        r = await c.request("DELETE", "/api/finance/invoices/inv-a1/payments/" + res["allocation_id"],
                            json={"reason": BAD_REASONS[kind]}, headers=hdr("acct-a", "k-n2a-" + kind))
        assert r.status_code == 400, r.text
        assert await snap(op) == before
    run(monkeypatch, backend, mode, scenario)


def test_n2_reason_of_exactly_500_chars_is_accepted(monkeypatch, backend, mode):
    async def scenario(c, op):
        pid = await pay(c, 40.0)
        reason = "Сторно, ред 2 — 50%: " + "я" * 479
        assert len(reason) == 500
        r = await reverse(c, pid, reason=reason)
        assert r.status_code == 200, r.text
        orig = await op.finance_payments.find_one({"id": pid}, {"_id": 0})
        assert orig["status"] == "reversed" and orig["reversal_reason"] == reason
    run(monkeypatch, backend, mode, scenario)


# ═══════════════════════════════════════════════════════════ helper (pure)
def test_helper_positive_amount():
    from fastapi import HTTPException
    from app.services.money_amount import positive_amount
    assert positive_amount(12.5) == 12.5
    assert positive_amount(12) == 12.0
    assert positive_amount(12.346, places=2) == 12.35
    for bad in (float("nan"), float("inf"), float("-inf"), "1e309", "", "  ", None, True, False,
                -1, 0, "0", "12.50", "abc", [], {}, [12.5], 0.004, 10 ** 400):
        with pytest.raises(HTTPException) as e:
            positive_amount(bad, places=2)
        assert e.value.status_code == 422 and isinstance(e.value.detail, str), bad


def test_helper_strict_number():
    from app.models.finance import AllocationInput, PaymentCreate
    from pydantic import ValidationError
    assert PaymentCreate(direction="Inflow", amount=12, date="d", account_id="a").amount == 12.0
    assert AllocationInput(invoice_id="i", amount=1.5).amount == 1.5
    for bad in (True, False, "12", "12.5", None, [1]):
        with pytest.raises(ValidationError):
            PaymentCreate(direction="Inflow", amount=bad, date="d", account_id="a")
        with pytest.raises(ValidationError):
            AllocationInput(invoice_id="i", amount=bad)


def test_helper_reason_problem():
    from app.services.money_amount import reason_problem
    assert reason_problem("грешно въведено") is None
    assert reason_problem("Сторно: ф-ра 12/2026, 50% — dup (a+b)") is None   # normal text
    assert reason_problem("x" * 500) is None
    assert reason_problem("x" * 501) == "REASON_TOO_LONG"
    for ch in ("\x00", "\x1b", "\x7f", "\x85", "\t", "\u200b", "\u200d", "\u202a", "\u202e",
               "\u2066", "\u2069", "\ufeff", "\u061c",
               "\u00ad", "\U000e0041", "\U000e0001", "\u2028", "\u2029", "\ud800"):
        assert reason_problem("a" + ch + "b") == "REASON_INVALID_CHARS", repr(ch)
