#!/usr/bin/env bash
# Usage: setup.sh <worktree of PR head>   — clean enforce-mode stack + two synthetic tenants
set -euo pipefail
WT="$(cd "${1:?worktree}" && pwd)"; HERE="$(cd "$(dirname "$0")" && pwd)"; VENV=${BOT_VENV:-/tmp/botvenv}
"$HERE/../runner/start_stack.sh" "$WT" PERMISSION_SERVICE_MODE=enforce
export ENV=development MONGO_URL="mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true" DB_NAME=bot_op BEG_SYSTEM_DB=bot_sys JWT_SECRET=bot-local-secret
cd "$WT/backend"
# tenant B = second firm via the real seed path
SEED_ADMIN_EMAIL=admin@bot-b.test SEED_ADMIN_PASSWORD='BotPass-12345!' "$VENV/bin/python" -c "import asyncio; from app.core.seed import seed_data; asyncio.run(seed_data())" 2>&1 | grep -E "Seed|seed" || true
# distinct slugs -> distinct tenant databases
docker exec botmongo mongosh --quiet bot_op --eval '
db.organizations.updateOne({email:"admin@bot-b.test"},{$set:{name:"BOT Firm B",slug:"bot-firm-b"}});
db.organizations.updateOne({email:"admin@bot-a.test"},{$set:{name:"BOT Firm A",slug:"bot-firm-a"}});' >/dev/null
"$VENV/bin/python" scripts/w0_01_bootstrap_tenant_registry.py --apply 2>&1 | grep -E "db=|complete"
# authoritative company assignments for the two seeded admins (shape of sync.grant_company_role)
"$VENV/bin/python" "$HERE/grant_admins.py" 2>&1 | grep -E "granted|skip"
# canonical-warehouse required indexes on both tenant databases (no production step creates them: see README finding F-1)
"$VENV/bin/python" "$HERE/indexes.py" 2>&1 | grep created
echo "setup done"
