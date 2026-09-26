"""Entry point: ``python -m app``.

Startup order matters. The first refresh round runs before the socket is opened so a
browser that connects immediately gets a verified snapshot rather than an empty shell;
but a failure in that first round is not fatal -- the dashboard comes up showing
OFFLINE with no snapshot, which is the truthful thing to show, and the loop keeps
trying under backoff.
"""

from __future__ import annotations

import signal
import sys
import threading

from . import __version__
from .github import GitHubReadOnlyClient
from .redact import configure_logging
from .refresh import RefreshLoop, Refresher
from .server import make_server
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_environment()
    logger = configure_logging(settings.token)
    logger.info("BEG_WORK web dashboard %s starting", __version__)
    logger.info("configuration: %s", settings.redacted())
    if not settings.has_token:
        logger.warning(
            "No BEGWORK_GITHUB_TOKEN is set. Reads will be unauthenticated and subject to "
            "the low anonymous rate limit; a private repository will not be readable."
        )

    client = GitHubReadOnlyClient(
        repository=settings.repository,
        token=settings.token,
        api_base=settings.api_base,
        timeout=settings.request_timeout_seconds,
    )
    refresher = Refresher(client, settings)
    refresher.tick()

    loop = RefreshLoop(refresher)
    loop.start()

    server = make_server(refresher, settings)

    def _stop_serving() -> None:
        loop.stop()
        server.shutdown()

    def shutdown(signum, _frame) -> None:
        logger.info("signal %s received, shutting down", signum)
        # `shutdown()` blocks until `serve_forever()` returns, and this handler runs on
        # the very thread that is inside `serve_forever()`. Calling it here would wait
        # for a loop that cannot advance until the handler returns -- a deadlock, which
        # under `docker stop` means a 10 s wait and then SIGKILL. Running it on another
        # thread lets the handler return so the loop can exit promptly.
        threading.Thread(target=_stop_serving, name="begwork-shutdown", daemon=True).start()

    for name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), shutdown)

    logger.info("serving on http://%s:%s/ (read-only projection)", settings.host, settings.port)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        loop.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
