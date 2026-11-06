#!/usr/bin/env bash
# Usage: backend_ctl.sh <worktree> [ENV assignments]  — restart ONLY the backend (same DB/env as start_stack.sh)
set -euo pipefail
WT="$(cd "$1" && pwd)"; shift; RUN=${BOT_RUN_DIR:-/tmp/botrun}; VENV=${BOT_VENV:-/tmp/botvenv}
[ -f "$RUN/backend.pid" ] && kill "$(cat "$RUN/backend.pid")" 2>/dev/null || true
pkill -f "uvicorn server:app --host 127.0.0.1 --port 8001" 2>/dev/null || true; sleep 1
cd "$WT/backend"
env ENV=development MONGO_URL="mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true" DB_NAME=bot_op BEG_SYSTEM_DB=bot_sys JWT_SECRET=bot-local-secret \
  SEED_ADMIN_EMAIL=admin@bot-a.test SEED_ADMIN_PASSWORD='BotPass-12345!' CORS_ORIGINS='*' "$@" \
  nohup "$VENV/bin/uvicorn" server:app --host 127.0.0.1 --port 8001 >"$RUN/backend.log" 2>&1 &
echo $! >"$RUN/backend.pid"
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8001/api/version >/dev/null 2>&1 && break; sleep 1; done
curl -s http://127.0.0.1:8001/api/version; echo
