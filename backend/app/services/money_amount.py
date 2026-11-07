"""
PAY-01-C01 — money amount and reversal reason rules (CLAUDE.md §14 validation/DQ, FLOW-006).

Pure logic, no DB access. Kept in its own module so SEC-01-C03 (#69), which applies the same
amount rule to its own routes, does not conflict with PAY-01 (#70); the two are unified at merge.

* An amount is a JSON number, finite and > 0. NaN, ±Infinity, 1e309 (→ inf), None,
  booleans, strings (numeric text too), 0 and negatives are refused with **422** — before
  anything is written.
* A reversal / cancellation reason is at most 500 characters and contains no character of
  Unicode category Cc, Cf, Zl, Zp or Cs (NUL, ESC, C1, soft hyphen, bidi, zero-width, BOM,
  tag characters, line/paragraph separators, lone surrogates); otherwise **400**.
"""
import math
import unicodedata
from typing import Any, Optional

from fastapi import HTTPException

REASON_MAX_LEN = 500

# Unicode categories refused in a reason: Cc control (NUL, ESC, DEL, C1), Cf format (soft
# hyphen, zero-width, bidi, BOM, tag characters U+E0000…), Zl/Zp line/paragraph separators,
# Cs lone surrogates (cannot be stored as UTF-8).
_REFUSED_CATEGORIES = {"Cc", "Cf", "Zl", "Zp", "Cs"}

# Invisible characters that are not Unicode category Cc but still hide or reorder text.
_INVISIBLE = {
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",          # zero-width, LRM/RLM
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",          # bidi embeddings/overrides
    "\u2060", "\u2061", "\u2062", "\u2063", "\u2064",          # word joiner, invisible ops
    "\u2066", "\u2067", "\u2068", "\u2069",                    # bidi isolates
    "\u206a", "\u206b", "\u206c", "\u206d", "\u206e", "\u206f",
    "\u061c", "\u180e", "\ufeff",                              # ALM, MVS, BOM/ZWNBSP
}


def _amount_error(field: str, message: str) -> HTTPException:
    # A plain-string detail: the finance pages show ``err.response.data.detail`` as is.
    suffix = "" if field == "amount" else " (%s)" % field
    return HTTPException(status_code=422, detail=message + suffix)


def is_number(value: Any) -> bool:
    """True only for a JSON number (int or float). Booleans, strings, None, lists... are not."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def strict_number(value: Any) -> Any:
    """Pydantic ``mode="before"`` check: refuse a non-number BEFORE coercion (``true`` → 1.0,
    ``"12"`` → 12.0). Raises ValueError, which Pydantic turns into 422."""
    if not is_number(value):
        raise ValueError("Сумата трябва да е число")
    return value


def positive_amount(value: Any, field: str = "amount", places: Optional[int] = None) -> float:
    """Return ``value`` as a finite float > 0 (rounded to ``places`` if given), or raise 422.

    Only a JSON number is accepted: booleans, strings (also numeric text), None and other
    types are refused before any coercion (PAY-01-C01 L1)."""
    if value is None:
        raise _amount_error(field, "Сумата е задължителна")
    if not is_number(value):
        raise _amount_error(field, "Сумата трябва да е число")
    try:
        amount = float(value)
    except (OverflowError, ValueError):                       # int too large for a float
        raise _amount_error(field, "Сумата трябва да е крайно число")
    if not math.isfinite(amount):
        raise _amount_error(field, "Сумата трябва да е крайно число")
    if places is not None:
        amount = round(amount, places)
    if amount <= 0:
        raise _amount_error(field, "Сумата трябва да е положителна")
    return amount


def reason_problem(reason: str) -> Optional[str]:
    """Why ``reason`` is not acceptable as a reversal/cancel reason, or None if it is."""
    if len(reason) > REASON_MAX_LEN:
        return "REASON_TOO_LONG"
    for ch in reason:
        if ch in _INVISIBLE or unicodedata.category(ch) in _REFUSED_CATEGORIES:
            return "REASON_INVALID_CHARS"
    return None


def check_reason(reason: str) -> None:
    """Raise 400 when the (already stripped, non-empty) reason breaks the length/character rule."""
    problem = reason_problem(reason)
    if problem == "REASON_TOO_LONG":
        raise HTTPException(status_code=400, detail={
            "error_code": problem,
            "message": "Причината е най-много %d знака" % REASON_MAX_LEN})
    if problem:
        raise HTTPException(status_code=400, detail={
            "error_code": problem,
            "message": "Причината съдържа контролни или невидими знаци"})
