"""Credentials must not reach any process log, including a traceback.

Regression suite for the C02 review finding: ``Logger.exception()`` attaches the live
exception as ``exc_info``, and the *formatter* renders that traceback after every filter
has already run. Redacting only ``msg`` and ``args`` therefore left a credential quoted
inside an exception message fully visible in the log, even though the browser-facing
``last_error`` was clean.

Every token in this file is assembled at runtime from harmless fragments. No real
credential appears here, in a comment, or in any output these tests produce.
"""

from __future__ import annotations

import io
import logging
import sys
import threading
import traceback

import pytest
from app.github import GitHubReadOnlyClient, TransportError
from app.projection import project
from app.redact import (
    PLACEHOLDER,
    RedactingFilter,
    RedactingFormatter,
    configure_logging,
    install_excepthooks,
    redact,
)
from app.refresh import Refresher
from app.settings import Settings

# Assembled rather than written as a literal so no PAT-shaped string is committed.
SYNTHETIC_TOKEN = "gh" + "p_" + "SYNTHETICtoken0123456789abcdefQRS"
SYNTHETIC_PAT = "github" + "_pat_" + "11SYNTHETIC0abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def captured_log():
    """A logger configured exactly as production configures it, writing into a buffer."""
    logger = logging.getLogger("begwork.test.redaction")
    logger.handlers.clear()
    logger.filters.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s", secret=SYNTHETIC_TOKEN))
    redacting = RedactingFilter(SYNTHETIC_TOKEN)
    handler.addFilter(redacting)
    logger.addFilter(redacting)
    logger.addHandler(handler)
    try:
        yield logger, buffer
    finally:
        logger.handlers.clear()
        logger.filters.clear()


# ------------------------------------------------------- the traceback path


def test_a_traceback_carrying_a_token_is_redacted(captured_log):
    """The exact defect: the credential lived in ``exc_info``, not in ``msg``."""
    logger, buffer = captured_log
    try:
        raise ValueError("upstream refused: " + SYNTHETIC_TOKEN)
    except ValueError:
        logger.exception("refresh raised unexpectedly")

    output = buffer.getvalue()
    assert SYNTHETIC_TOKEN not in output
    assert PLACEHOLDER in output
    # The traceback is still there -- redaction must not cost the diagnostic.
    assert "Traceback" in output
    assert "ValueError" in output
    assert "refresh raised unexpectedly" in output


def test_a_chained_exception_is_redacted_through_the_whole_chain(captured_log):
    """``raise ... from ...`` renders both exceptions; both must be clean."""
    logger, buffer = captured_log
    try:
        try:
            raise TransportError("HTTP 401 Authorization: Bearer " + SYNTHETIC_TOKEN)
        except TransportError as cause:
            raise RuntimeError("giving up after " + SYNTHETIC_PAT) from cause
    except RuntimeError:
        logger.exception("round failed")

    output = buffer.getvalue()
    assert SYNTHETIC_TOKEN not in output
    assert SYNTHETIC_PAT not in output
    assert "The above exception was the direct cause" in output or "During handling" in output


def test_stack_info_is_redacted(captured_log):
    logger, buffer = captured_log
    logger.error("state was %s", SYNTHETIC_TOKEN, stack_info=True)
    output = buffer.getvalue()
    assert SYNTHETIC_TOKEN not in output
    assert "Stack (most recent call last)" in output


def test_the_filter_clears_exc_info_so_a_later_formatter_cannot_re_render_it():
    """The mechanism, asserted directly.

    If ``exc_info`` survived the filter, any handler with a plain ``logging.Formatter``
    would render the original traceback unredacted.
    """
    redacting = RedactingFilter(SYNTHETIC_TOKEN)
    try:
        raise ValueError("carrying " + SYNTHETIC_TOKEN)
    except ValueError:
        record = logging.LogRecord(
            "t", logging.ERROR, __file__, 1, "boom", (), sys.exc_info()
        )
    redacting.filter(record)

    assert record.exc_info is None
    assert record.exc_text is None
    assert SYNTHETIC_TOKEN not in record.getMessage()

    # A plain formatter, which does nothing of its own, now produces clean output.
    rendered = logging.Formatter("%(message)s").format(record)
    assert SYNTHETIC_TOKEN not in rendered
    assert PLACEHOLDER in rendered


def test_the_filter_is_idempotent_across_logger_and_handler():
    """It is installed on both, so it runs twice on the same record."""
    redacting = RedactingFilter(SYNTHETIC_TOKEN)
    try:
        raise ValueError("carrying " + SYNTHETIC_TOKEN)
    except ValueError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), sys.exc_info())
    redacting.filter(record)
    first = record.getMessage()
    redacting.filter(record)
    assert record.getMessage() == first
    assert SYNTHETIC_TOKEN not in record.getMessage()


def test_a_bad_format_string_still_gets_redacted(captured_log):
    """A formatting error must not become an escape hatch for the credential."""
    logger, buffer = captured_log
    try:
        raise ValueError("carrying " + SYNTHETIC_TOKEN)
    except ValueError:
        # Deliberately mismatched: more placeholders than arguments.
        logger.exception("two placeholders %s %s", SYNTHETIC_TOKEN)
    output = buffer.getvalue()
    assert SYNTHETIC_TOKEN not in output


def test_the_formatter_alone_redacts_even_without_the_filter():
    """Defence in depth for a handler attached by embedding code."""
    logger = logging.getLogger("begwork.test.formatter-only")
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(RedactingFormatter("%(message)s", secret=SYNTHETIC_TOKEN))
    logger.addHandler(handler)
    try:
        try:
            raise ValueError("carrying " + SYNTHETIC_TOKEN)
        except ValueError:
            logger.exception("no filter installed here")
        assert SYNTHETIC_TOKEN not in buffer.getvalue()
    finally:
        logger.handlers.clear()


# --------------------------------------------- end to end through a refresh round


def test_an_unexpected_exception_in_a_round_leaks_nothing_to_logs_or_the_api(
    fake_github, captured_log, monkeypatch
):
    """The reported scenario, end to end.

    An unexpected (non-transport) exception whose message carries the configured token
    must leave it out of the process log *and* out of everything the browser can read.
    """
    logger, buffer = captured_log
    monkeypatch.setattr("app.refresh.LOGGER", logger)

    def explode(method, url, headers, timeout):
        raise ValueError("unexpected failure carrying " + SYNTHETIC_TOKEN)

    fake_github.request = explode
    settings = Settings(
        repository="krumingo/BEG_Worck", branch="codex/claude-queue", token=SYNTHETIC_TOKEN
    )
    client = GitHubReadOnlyClient(
        repository=settings.repository, token=SYNTHETIC_TOKEN, transport=fake_github
    )
    refresher = Refresher(client, settings)
    state = refresher.tick()

    log_output = buffer.getvalue()
    assert "Traceback" in log_output, "the diagnostic must survive redaction"
    assert SYNTHETIC_TOKEN not in log_output
    assert PLACEHOLDER in log_output

    assert SYNTHETIC_TOKEN not in (state.last_error or "")

    import json as _json

    payload = _json.dumps(project(state))
    assert SYNTHETIC_TOKEN not in payload


def test_a_transport_error_quoting_the_auth_header_leaks_nothing(fake_github, captured_log, monkeypatch):
    """The warning path, which uses ``%s`` rather than ``exception()``."""
    logger, buffer = captured_log
    monkeypatch.setattr("app.refresh.LOGGER", logger)

    fake_github.fail_everything = TransportError(
        "HTTP 401 for .../contents: Authorization: Bearer " + SYNTHETIC_TOKEN, status=401
    )
    settings = Settings(
        repository="krumingo/BEG_Worck", branch="codex/claude-queue", token=SYNTHETIC_TOKEN
    )
    client = GitHubReadOnlyClient(
        repository=settings.repository, token=SYNTHETIC_TOKEN, transport=fake_github
    )
    state = Refresher(client, settings).tick()

    assert SYNTHETIC_TOKEN not in buffer.getvalue()
    assert SYNTHETIC_TOKEN not in (state.last_error or "")


# ------------------------------------------------------------- uncaught exceptions


def test_an_uncaught_exception_printed_by_the_interpreter_is_redacted(capsys):
    """An escaping exception bypasses logging and is written straight to stderr."""
    original_hook = sys.excepthook
    original_thread_hook = threading.excepthook
    try:
        install_excepthooks(SYNTHETIC_TOKEN)
        try:
            raise ValueError("escaped carrying " + SYNTHETIC_TOKEN)
        except ValueError:
            sys.excepthook(*sys.exc_info())
        captured = capsys.readouterr()
        assert SYNTHETIC_TOKEN not in captured.err
        assert PLACEHOLDER in captured.err
        assert "ValueError" in captured.err
    finally:
        sys.excepthook = original_hook
        threading.excepthook = original_thread_hook


def test_an_uncaught_exception_in_a_thread_is_redacted(capsys):
    original_hook = sys.excepthook
    original_thread_hook = threading.excepthook
    try:
        install_excepthooks(SYNTHETIC_TOKEN)

        def explode():
            raise ValueError("thread carrying " + SYNTHETIC_TOKEN)

        worker = threading.Thread(target=explode)
        worker.start()
        worker.join(timeout=5)

        captured = capsys.readouterr()
        assert SYNTHETIC_TOKEN not in captured.err
        assert PLACEHOLDER in captured.err
    finally:
        sys.excepthook = original_hook
        threading.excepthook = original_thread_hook


def test_configure_logging_installs_both_the_filter_and_the_excepthooks():
    original_hook = sys.excepthook
    original_thread_hook = threading.excepthook
    try:
        logger = configure_logging(SYNTHETIC_TOKEN)
        assert any(isinstance(item, RedactingFilter) for item in logger.filters)
        for handler in logger.handlers:
            assert any(isinstance(item, RedactingFilter) for item in handler.filters)
            assert isinstance(handler.formatter, RedactingFormatter)
        assert sys.excepthook is not original_hook
        assert threading.excepthook is not original_thread_hook
    finally:
        sys.excepthook = original_hook
        threading.excepthook = original_thread_hook
        logging.getLogger("begwork.dashboard").handlers.clear()
        logging.getLogger("begwork.dashboard").filters.clear()


def test_redaction_of_a_raw_traceback_string():
    """The primitive the hooks rely on."""
    try:
        raise ValueError("carrying " + SYNTHETIC_TOKEN)
    except ValueError:
        text = traceback.format_exc()
    assert SYNTHETIC_TOKEN in text
    assert SYNTHETIC_TOKEN not in redact(text, SYNTHETIC_TOKEN)
