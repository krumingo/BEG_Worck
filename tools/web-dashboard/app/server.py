"""The web host: stdlib HTTP only.

There is no web framework and no bundler, which is the point. The browser is served
static files and one JSON document; the GitHub token never leaves the server process
because there is no build step that could inline it and no response that carries it.

Routing is an explicit allowlist. A generic static handler rooted at a directory is
how path-traversal bugs happen, and this process has a credential in memory, so files
are served only from a fixed table.
"""

from __future__ import annotations

import http.server
import json
import logging
import mimetypes
import pathlib
import socketserver
import urllib.parse

from . import __version__
from .projection import project
from .redact import redact
from .refresh import Refresher
from .settings import Settings

LOGGER = logging.getLogger("begwork.dashboard")

STATIC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "static"

# path -> filename in static/. Nothing outside this table is reachable.
STATIC_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.css": "app.css",
    "/app.js": "app.js",
    "/manifest.webmanifest": "manifest.webmanifest",
    "/sw.js": "sw.js",
    "/icon-192.png": "icon-192.png",
    "/icon-512.png": "icon-512.png",
    "/favicon.svg": "favicon.svg",
}

NO_STORE = "no-store, no-cache, must-revalidate"


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    server_version = f"BEGWorkDashboard/{__version__}"
    protocol_version = "HTTP/1.1"

    # Set by make_server.
    refresher: Refresher
    settings: Settings

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/state":
            self._send_json(200, project(self.refresher.current()))
            return
        if path == "/healthz":
            self._send_json(200, self._health(), cache=NO_STORE)
            return
        if path in STATIC_ROUTES:
            self._send_static(STATIC_ROUTES[path])
            return
        self._send_json(404, {"error": "not found", "path": path})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        path = urllib.parse.urlsplit(self.path).path
        if path in STATIC_ROUTES or path in {"/api/state", "/healthz"}:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _health(self) -> dict:
        """Liveness plus readiness detail.

        This returns 200 whenever the process can serve, so a container health check
        does not restart a dashboard that is merely waiting out a GitHub outage --
        restarting would throw away the cached snapshot, which is the one thing still
        worth showing. Readiness is reported in the body instead of in the status code.
        """
        state = self.refresher.current()
        return {
            "status": "ok",
            "version": __version__,
            "link": state.link.value,
            "control_state_status": state.status.label if state.status is not None else None,
            "snapshot_available": state.has_data,
            "last_verified_at": (
                state.last_success_at.isoformat(timespec="seconds").replace("+00:00", "Z")
                if state.last_success_at
                else None
            ),
            "age_seconds": state.age_seconds,
            "aged": state.is_aged,
            "consecutive_failures": state.consecutive_failures,
            "rounds": state.rounds,
        }

    def _send_json(self, status: int, payload: dict, cache: str = NO_STORE) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=None).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self._send_common_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str) -> None:
        target = STATIC_ROOT / filename
        try:
            body = target.read_bytes()
        except OSError:
            self._send_json(404, {"error": "missing asset", "asset": filename})
            return
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if content_type.startswith("text/") or filename.endswith((".js", ".webmanifest", ".svg")):
            content_type = f"{content_type}; charset=utf-8" if "charset" not in content_type else content_type
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The app shell must not be cached hard: an updated container should take effect
        # on reload rather than after a browser cache expiry nobody can predict.
        self.send_header("Cache-Control", "no-cache" if filename.endswith((".html", ".js", ".css", ".webmanifest")) else "max-age=86400")
        self._send_common_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # The UI is self-contained: no external script, style, font or image. Saying so
        # in a CSP means an injected third-party request cannot execute.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
            "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        # Routed through the redacting logger rather than stderr, so a credential that
        # somehow reached a URL cannot be written out verbatim.
        LOGGER.info("%s %s", self.address_string(), redact(format % args, self.settings.token))


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(refresher: Refresher, settings: Settings) -> ThreadingHTTPServer:
    handler = type(
        "BoundDashboardHandler",
        (DashboardHandler,),
        {"refresher": refresher, "settings": settings},
    )
    return ThreadingHTTPServer((settings.host, settings.port), handler)
