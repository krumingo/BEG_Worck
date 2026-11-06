#!/usr/bin/env bash
RUN=${BOT_RUN_DIR:-/tmp/botrun}
for f in backend frontend; do [ -f "$RUN/$f.pid" ] && kill "$(cat "$RUN/$f.pid")" 2>/dev/null; rm -f "$RUN/$f.pid"; done
pkill -f "uvicorn server:app --host 127.0.0.1 --port 8001" 2>/dev/null
pkill -f "serve_spa.js" 2>/dev/null
docker rm -f botmongo >/dev/null 2>&1
exit 0
