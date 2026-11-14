"""
PRIV-01 (FLOW Guard FG-726; FLOW-040 §9, §11) — pay and rate values in the legacy
``audit_logs``.

Canon (locked; applied here, not a new business rule):

  * FLOW-040 §9: "банкови сметки, лични номера, заплати и PII се маскират според ролята";
    "before/after използва field-level diff и references".
  * FLOW-040 §11: the Administrator has "няма автоматичен достъп до payroll, банково
    съдържание или лични AI разговори без отделно sensitive-domain право"; Platform
    support gets "business content само чрез break-glass".

Two halves, one key list:

  1. WRITE — ``mask_changes`` runs inside both legacy ``log_audit`` sinks
     (``app/utils/audit.py``, ``app/services/audit.py``). A pay or rate value is never
     stored in clear: the key stays (so the fact that it changed is kept) and its value
     becomes ``MASKED`` — a marker, not a hash (a salary hash is trivially brute-forced).
     The value itself lives only in its source record (``employee_profiles``,
     ``work_types``, ``advances``), which the row already names by
     ``entity_type`` / ``entity_id``.
  2. READ — ``mask_row`` is applied by ``GET /audit-logs`` to every row (also rows
     written before PRIV-01, in clear) for a caller without the payroll read right.

Pure module: no imports from the app, so both sinks and the route can use it.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, Optional

# The Permission Service catalog action that says "this caller reads payroll"
# (app/permissions/finance_read.py: GET /api/pay-runs, rule R20-1, canon CANON_PAY).
# Holders: Owner/Admin through their full set, Accountant. No other role, and
# is_platform_admin is not a role — it never grants it.
PAYROLL_READ_ACTION = "finance.pay_run.read"

# Value that replaces a pay/rate value. The key is kept: "it changed" stays visible.
MASKED: Dict[str, Any] = {"masked": True, "kind": "pay_or_rate", "changed": True}

# Keys whose VALUE is pay or a rate (any depth, case-insensitive). Narrow on purpose:
# "rate" alone would also hide vat_rate / exchange_rate, which are not pay.
_PAY_KEY = re.compile(
    r"(salary|wage|hourly_rate|daily_rate|monthly_rate|overtime_rate|pay_rate|"
    r"^rate_per_(hour|day)$|^insurance_(pct|amount)$|^akord)", re.I)

# Entities whose plain ``amount`` is pay: an advance / loan to a person is deducted from
# their pay (hr.py advance_created). Payment, invoice, overhead amounts are not pay and
# are left as they are (FLOW-040 §11 Finance roles see them; not PRIV-01's finding).
PAY_AMOUNT_ENTITY_TYPES = frozenset({"advance", "employee", "payslip", "pay_run"})
_AMOUNT_KEYS = frozenset({"amount", "remaining_amount", "paid_amount"})

# The row fields that may carry a field-level diff.
_DIFF_FIELDS = ("changes", "details", "before", "after")


def is_pay_key(key: Any, entity_type: Optional[str] = None) -> bool:
    if not isinstance(key, str):
        return False
    if _PAY_KEY.search(key):
        return True
    return (entity_type or "").lower() in PAY_AMOUNT_ENTITY_TYPES and key.lower() in _AMOUNT_KEYS


def _mask(value: Any, entity_type: Optional[str]) -> Any:
    if isinstance(value, dict):
        return {k: (dict(MASKED) if is_pay_key(k, entity_type) else _mask(v, entity_type))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, entity_type) for v in value]
    return value


def mask_changes(changes: Any, entity_type: Optional[str] = None) -> Any:
    """A copy of ``changes`` with every pay/rate value replaced by ``MASKED``."""
    return _mask(changes, entity_type)


def mask_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of one ``audit_logs`` row with every pay/rate value in its diff masked."""
    out = copy.copy(row)
    entity_type = row.get("entity_type")
    for field in _DIFF_FIELDS:
        if field in out:
            out[field] = _mask(out[field], entity_type)
    return out


def has_pay_value(row: Dict[str, Any]) -> bool:
    """True when the row still carries a pay/rate value in clear (a pre-PRIV-01 row)."""
    return mask_row(row) != row
