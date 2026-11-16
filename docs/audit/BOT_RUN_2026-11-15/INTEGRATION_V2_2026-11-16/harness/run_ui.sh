#!/usr/bin/env bash
# INTEGRATION_V2: UI role-bot run on a fresh company in a disposable Mongo (default 27192),
# backend+build of the integration worktree on port 8768, writes serialized (serve.py).
# Usage: run_ui.sh <worktree> <minutes>   (the Mongo container must already be a fresh rs0)
set -euo pipefail
TREE=$1; MIN=${2:-30}
H=$TREE/docs/audit/BOT_RUN_2026-11-15/INTEGRATION_V2_2026-11-16/harness
PY=/tmp/claude-0/venv/bin/python
export BOT_MONGO=${BOT_MONGO:-"mongodb://127.0.0.1:27192/?directConnection=true"} BOT_DB=demoint2ui_begwork
export BOT_RUN=${BOT_RUN:-/tmp/claude-0/demo_int2/ui/run} BOT_PORT=8768 BOT_TREE=$TREE
mkdir -p "$BOT_RUN"; cd "$TREE/backend"
MONGO_URL=$BOT_MONGO DB_NAME=$BOT_DB BEG_SYSTEM_DB=demoint2ui_system $PY scripts/create_company.py \
  --name "Демо Интеграция 2 UI ООД" --admin-email demo@example.com --admin-password 'Demo12345!'
$PY "$H/insert_subscription.py"
(MONGO_URL=$BOT_MONGO DB_NAME=$BOT_DB BEG_SYSTEM_DB=demoint2ui_system JWT_SECRET=demo-only-secret BOT_SERIALIZE_WRITES=1 \
  setsid nohup $PY -m uvicorn serve:app --app-dir "$H" --host 127.0.0.1 --port 8768 > "$BOT_RUN/uvicorn.log" 2>&1 &)
for i in $(seq 1 40); do curl -sf -o /dev/null http://127.0.0.1:8768/api/health && break; sleep 2; done
(setsid nohup $PY "$H/watch.py" > "$BOT_RUN/watch.log" 2>&1 &)
sleep 2
$PY "$H/seed.py" > "$BOT_RUN/seed.log" 2>&1
sleep 2
wc -l < "$BOT_RUN/backend.jsonl" > "$BOT_RUN/backend_offset.txt"
wc -l < "$BOT_RUN/db.jsonl" > "$BOT_RUN/db_offset.txt"
date -u +%s > "$BOT_RUN/run_start.txt"
cd "$BOT_RUN" && BOT_BASE=http://localhost:8768 DURATION_MIN=$MIN timeout $(( MIN * 60 + 600 )) node "$H/bot.js" > bot_stdout.log 2>&1
echo "bots done rc=$?"
