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
import sys
import threading
import traceback

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
    """A logging filter that masks credentials anywhere in a log record.

    Redacting ``msg`` and ``args`` is not sufficient. ``Logger.exception()`` attaches the
    live exception as ``exc_info``, and the *formatter* renders that traceback long after
    every filter has run -- so a credential quoted inside an exception message reached the
    handler untouched. The same applies to ``stack_info``.

    So this filter flattens the whole record here: the message is rendered (applying
    ``args``), the traceback and stack are formatted, the three are redacted together, and
    ``exc_info``/``exc_text``/``stack_info`` are cleared so nothing is left for a later
    formatter to render unredacted. The result is idempotent, which matters because this
    filter is installed on both the logger and its handlers.
    """

    def __init__(self, secret: str = "") -> None:
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info or record.exc_text or record.stack_info:
            self._flatten(record)
            return True
        record.msg = redact(record.msg, self._secret)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: redact(value, self._secret) for key, value in record.args.items()}
            else:
                record.args = tuple(redact(value, self._secret) for value in record.args)
        return True

    def _flatten(self, record: logging.LogRecord) -> None:
        try:
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must not defeat redaction
            rendered = f"{record.msg!r} % {record.args!r}"
        parts = [rendered]
        if record.exc_info:
            parts.append("".join(traceback.format_exception(*record.exc_info)).rstrip())
        elif record.exc_text:
            parts.append(str(record.exc_text).rstrip())
        if record.stack_info:
            parts.append(str(record.stack_info).rstrip())

        record.msg = redact("\n".join(parts), self._secret)
        # Cleared so no formatter can re-render the unredacted originals. Safe because
        # the redacted text of both is now part of the message.
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None


class RedactingFormatter(logging.Formatter):
    """A formatter that redacts its own complete output.

    Defence in depth for the case the filter cannot cover: a handler attached by
    embedding code, or a future change that drops the filter. Redacting the final string
    catches anything either path missed.
    """

    def __init__(self, fmt: str | None = None, secret: str = "") -> None:
        super().__init__(fmt)
        self._secret = secret

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self._secret)


def install_excepthooks(secret: str = "") -> None:
    """Redact tracebacks that Python itself prints for an uncaught exception.

    An exception escaping the main thread or a worker bypasses ``logging`` entirely and is
    written straight to stderr by the interpreter, which in a container is a process log
    like any other. These hooks route that text through redaction first.
    """

    def _print(exc_type, value, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, value, tb))
        sys.stderr.write(redact(text, secret))
        sys.stderr.flush()

    def main_hook(exc_type, value, tb) -> None:
        _print(exc_type, value, tb)

    def thread_hook(args) -> None:
        _print(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def configure_logging(secret: str = "", level: int = logging.INFO) -> logging.Logger:
    """Install the redacting filter on the dashboard's logger and its handler."""
    logger = logging.getLogger("begwork.dashboard")
    logger.setLevel(level)
    logger.propagate = False
    redacting = RedactingFilter(secret)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)-7s %(message)s", secret=secret)
        )
        logger.addHandler(handler)
    # The filter goes on both: on the logger to cover the record, and on each handler so
    # a handler added later by embedding code cannot bypass it.
    logger.filters = [redacting]
    for handler in logger.handlers:
        handler.filters = [redacting]
    install_excepthooks(secret)
    return logger
