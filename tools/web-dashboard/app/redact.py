"""Token redaction for logs and any other outbound text.

The dashboard's credential is a read-only GitHub token. It must never appear in a log
line, an HTTP response, a screenshot or an error message. Two layers do that work:

* the exact configured value is replaced wherever it appears;
* anything shaped like a GitHub credential is replaced even if it is not the
  configured value, so a token that arrives from somewhere unexpected -- a
  copy-pasted URL, a misconfigured header echoed back by an error -- is caught too.

Redaction is a safety net, not the primary control. The primary control is that the
token is only ever read from ``Settings`` inside the server process and is never put
into the projection (see ``projection.py``) or into a browser payload.
"""

from __future__ import annotations

import logging
import re

PLACEHOLDER = "***REDACTED***"

# Documented GitHub credential prefixes, plus the classic 40-hex PAT.
_TOKEN_SHAPES = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|\b[0-9a-f]{40}\b(?=\s*$|[\"'\s,;]))"
)
# Masks the whole remainder of the line: an Authorization value may be several
# tokens ("Bearer <value>"), so stopping at the first word would leave the secret.
_AUTH_HEADER = re.compile(r"(?i)\b(authorization|x-github-token)\b\s*[:=]\s*[^\r\n]+")


def redact(text: object, secret: str = "") -> str:
    """Return ``text`` with credentials masked."""
    rendered = text if isinstance(text, str) else str(text)
    if secret:
        rendered = rendered.replace(secret, PLACEHOLDER)
    rendered = _AUTH_HEADER.sub(lambda match: f"{match.group(1)}: {PLACEHOLDER}", rendered)
    return _TOKEN_SHAPES.sub(PLACEHOLDER, rendered)


class RedactingFilter(logging.Filter):
    """A logging filter that masks credentials in the message and its arguments."""

    def __init__(self, secret: str = "") -> None:
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg, self._secret)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: redact(value, self._secret) for key, value in record.args.items()}
            else:
                record.args = tuple(redact(value, self._secret) for value in record.args)
        return True


def configure_logging(secret: str = "", level: int = logging.INFO) -> logging.Logger:
    """Install the redacting filter on the dashboard's logger and its handler."""
    logger = logging.getLogger("begwork.dashboard")
    logger.setLevel(level)
    logger.propagate = False
    redacting = RedactingFilter(secret)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        logger.addHandler(handler)
    # The filter goes on both: on the logger to cover the record, and on each handler so
    # a handler added later by embedding code cannot bypass it.
    logger.filters = [redacting]
    for handler in logger.handlers:
        handler.filters = [redacting]
    return logger
