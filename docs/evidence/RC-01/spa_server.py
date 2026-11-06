#!/usr/bin/env python3
"""RC-01 local check only: serve frontend/build as a SPA (unknown paths -> index.html).

    python docs/evidence/RC-01/spa_server.py frontend/build 3000

Binds 127.0.0.1 only. Stdlib; not used in any deployment.
"""
import functools
import http.server
import os
import sys


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.exists(path):
            self.path = "/index.html"
        return super().send_head()


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "frontend/build")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    handler = functools.partial(SpaHandler, directory=root)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print("serving %s on http://127.0.0.1:%d" % (root, port), flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
