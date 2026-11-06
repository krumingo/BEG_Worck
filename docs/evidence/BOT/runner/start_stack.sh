#!/usr/bin/env bash
# Usage: start_stack.sh <worktree_dir> [extra ENV assignments, e.g. ENV=test]
# Starts MongoDB 7 (replica set, 127.0.0.1:27019), FastAPI (127.0.0.1:8001) and a
# production frontend build served on 127.0.0.1:3000. Synthetic data only.
set -euo pipefail
WT="$(cd "${1:?worktree dir}" && pwd)"; shift || true
RUN=${BOT_RUN_DIR:-/tmp/botrun}; VENV=${BOT_VENV:-/tmp/botvenv}
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$RUN"
"$HERE/stop_stack.sh" >/dev/null 2>&1 || true

# 1. docker + mongo
pgrep dockerd >/dev/null || { (nohup dockerd >/tmp/dockerd.log 2>&1 &); sleep 6; }
docker run -d --rm --name botmongo -p 127.0.0.1:27019:27017 mongo:7.0 --replSet rs0 --bind_ip_all >/dev/null
for i in $(seq 1 30); do docker exec botmongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 1; done
docker exec botmongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]})' >/dev/null
for i in $(seq 1 30); do [ "$(docker exec botmongo mongosh --quiet --eval 'rs.status().myState' 2>/dev/null)" = 1 ] && break; sleep 1; done

# 2. python venv (once)
[ -x "$VENV/bin/uvicorn" ] || { python3 -m venv "$VENV"; "$VENV/bin/pip" install -q -r "$WT/backend/requirements.txt"; }

# 3. backend (extra args are ENV-style assignments, e.g. ENV=test BILLING_PROVIDER=mock)
cd "$WT/backend"
env ENV=development MONGO_URL="mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true" \
    DB_NAME=bot_op BEG_SYSTEM_DB=bot_sys JWT_SECRET=bot-local-secret \
    SEED_ADMIN_EMAIL=admin@bot-a.test SEED_ADMIN_PASSWORD='BotPass-12345!' CORS_ORIGINS='*' "$@" \
    nohup "$VENV/bin/uvicorn" server:app --host 127.0.0.1 --port 8001 >"$RUN/backend.log" 2>&1 &
echo $! >"$RUN/backend.pid"
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8001/api/ >/dev/null 2>&1 || curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/openapi.json | grep -q 200 && break; sleep 1; done

# 4. frontend production build
cd "$WT/frontend"
[ -d node_modules ] || yarn install --frozen-lockfile >/dev/null
REACT_APP_BACKEND_URL=http://127.0.0.1:8001 CI=false GENERATE_SOURCEMAP=false yarn build >"$RUN/frontend_build.log" 2>&1
nohup node "$HERE/serve_spa.js" "$WT/frontend/build" 3000 >"$RUN/frontend.log" 2>&1 &
echo $! >"$RUN/frontend.pid"
sleep 1
echo "stack up: UI http://127.0.0.1:3000  API http://127.0.0.1:8001  (admin@bot-a.test / BotPass-12345!)"
