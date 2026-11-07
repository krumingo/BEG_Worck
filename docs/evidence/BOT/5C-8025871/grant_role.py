# Synthetic: authoritative company-scope assignment for one seeded user (same shape as sync.grant_company_role).
# Usage: python grant_role.py <email> <role_id>   (env as in setup.sh)
import asyncio, sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
from app.db import db
from app.tenancy import registry
from app.permissions.sync import company_assignment_id
async def main(email, role_id):
    u = await db.users.find_one({"email": email}, {"_id": 0})
    tid = u["org_id"]
    doc = {"id": company_assignment_id(u["id"], tid, role_id), "user_id": u["id"], "tenant_id": tid, "role_id": role_id,
           "scope_type": "company", "scope_id": None, "module": None, "permissions": [], "max_amount": None,
           "valid_from": datetime.now(timezone.utc).isoformat(), "valid_to": None, "status": "active",
           "created_by": "bot-seed", "approved_by": "bot-seed", "sync_source": "bot-seed"}
    try: await registry.insert_role_assignment(doc); print("granted", email, role_id)
    except Exception as e: print("skip", email, type(e).__name__)
asyncio.run(main(sys.argv[1], sys.argv[2]))
