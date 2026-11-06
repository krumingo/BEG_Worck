#!/usr/bin/env bash
# Usage: setup.sh <worktree of PR head> — clean enforce-mode stack, two synthetic tenants, "real install" start state.
# NO audit/index workarounds: canonical indexes come from the application's own startup hook; the legacy
# unique index warehouse_batches(org_id,batch_number) comes from fifo_service at startup; a legacy batch row is inserted.
set -euo pipefail
WT="$(cd "${1:?worktree}" && pwd)"; HERE="$(cd "$(dirname "$0")" && pwd)"; VENV=${BOT_VENV:-/tmp/botvenv}
"$HERE/../runner/start_stack.sh" "$WT" PERMISSION_SERVICE_MODE=${BOT_MODE:-enforce} FILE_REGISTRY_ENABLED=1
export ENV=development MONGO_URL="mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true" DB_NAME=bot_op BEG_SYSTEM_DB=bot_sys JWT_SECRET=bot-local-secret
cd "$WT/backend"
SEED_ADMIN_EMAIL=admin@bot-b.test SEED_ADMIN_PASSWORD='BotPass-12345!' "$VENV/bin/python" -c "import asyncio; from app.core.seed import seed_data; asyncio.run(seed_data())" 2>&1 | grep -E "Seed|seed" || true
cat > /tmp/botrun/setup_orgs.js <<'JS'
db.organizations.updateOne({email:"admin@bot-b.test"},{$set:{name:"BOT Firm B",slug:"bot-firm-b"}});
db.organizations.updateOne({email:"admin@bot-a.test"},{$set:{name:"BOT Firm A",slug:"bot-firm-a"}});
const a = db.organizations.findOne({email:"admin@bot-a.test"});
// legacy warehouse batch, as an installed tenant would have (legacy shape, has batch_number)
db.warehouse_batches.insertOne({id:"legacy-batch-1", org_id:a.id, batch_number:"LEG-0001", item_id:"legacy-item", material_name:"Legacy cement", warehouse_id:"legacy-wh", quantity:5, remaining_quantity:5, unit:"bag", unit_price:4, status:"active", received_at:"2026-01-05T00:00:00+00:00", created_at:"2026-01-05T00:00:00+00:00"});
JS
docker cp /tmp/botrun/setup_orgs.js botmongo:/setup_orgs.js; docker exec botmongo mongosh --quiet bot_op /setup_orgs.js >/dev/null
"$VENV/bin/python" scripts/w0_01_bootstrap_tenant_registry.py --apply 2>&1 | grep -E "db=|complete"
"$VENV/bin/python" "$HERE/grant_admins.py" 2>&1 | grep -E "granted|skip"
echo "setup done"
