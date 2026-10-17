"""
AUTH-01 — the one bounded, case-insensitive email comparison for authentication.

Login, forgot-password, the local recovery CLI and the user-create duplicate
check all compare an email the same way: ``strip().lower()``. Nothing stored is
rewritten (no migration): legacy rows keep the exact spelling they were saved
with, and the lookup is what tolerates case and surrounding whitespace.

The lookup never guesses. :func:`email_match_filter` selects every row whose
email differs from the input only by case or surrounding whitespace, and the
callers treat more than one such row as AMBIGUOUS and fail closed — login is
refused, no reset token is issued, the CLI exits non-zero — instead of picking
"the right one".

Pure functions; no database access lives here.
"""
import re
from typing import Any, Iterable, List, Mapping, Optional

#: RFC 5321 path limit. Anything longer cannot be a deliverable address and is
#: rejected before it reaches a query.
MAX_EMAIL_LENGTH = 254

#: How many candidate rows a lookup reads. Two already proves ambiguity; a few
#: more lets an operator report show what collides.
MATCH_LIMIT = 5


def normalize_email(value: Any) -> Optional[str]:
    """``strip().lower()`` of a usable login identifier, else ``None``.

    ``None`` for a non-string, an empty or over-long value, or one with inner
    whitespace / control characters — a caller treats that exactly like "no such
    account". The address FORMAT is deliberately not judged here: login must keep
    working for every row it worked for before, whatever its spelling.
    """
    if not isinstance(value, str):
        return None
    norm = value.strip().lower()
    if not norm or len(norm) > MAX_EMAIL_LENGTH:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in norm):
        return None
    return norm


def email_match_filter(normalized: str) -> dict:
    """Mongo filter matching ``normalized`` case-insensitively, whole value only.

    The input is escaped and anchored, so it can never act as a pattern; leading
    and trailing whitespace stored by older writers is tolerated.
    """
    if normalize_email(normalized) != normalized:
        raise ValueError("email_match_filter needs a normalize_email() result")
    return {"email": {"$regex": r"^\s*" + re.escape(normalized) + r"\s*$", "$options": "i"}}


def matching(docs: Iterable[Mapping], normalized: str) -> List[Mapping]:
    """The rows whose stored email normalizes to ``normalized``.

    Re-checks in Python what the database matched, so the decision does not rest
    on the server's regex case-folding rules.
    """
    out = []
    for doc in docs:
        stored = doc.get("email") if isinstance(doc, Mapping) else None
        if isinstance(stored, str) and stored.strip().lower() == normalized:
            out.append(doc)
    return out


def mask_email(value: Any) -> str:
    """``k***@begfull.bg`` — for operator/log lines that must not echo an address."""
    if not isinstance(value, str) or "@" not in value:
        return "<invalid>"
    local, _, domain = value.strip().partition("@")
    return (local[:1] or "?") + "***@" + domain
