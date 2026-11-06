# Synthetic bootstrap: authoritative company assignment for the two seeded admins
# (same document shape app/permissions/sync.grant_company_role writes).
import asyncio, sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
from app.db import db
from app.tenancy import registry
from app.permissions.sync import company_assignment_id
async def main():
    for u in await db.users.find({"role": "Admin"}, {"_id": 0}).to_list(10):
        tid = u["org_id"]
        doc = {"id": company_assignment_id(u["id"], tid, "admin"), "user_id": u["id"], "tenant_id": tid,
               "role_id": "admin", "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
               "max_amount": None, "valid_from": datetime.now(timezone.utc).isoformat(), "valid_to": None,
               "status": "active", "created_by": "bot-seed", "approved_by": "bot-seed", "sync_source": "users.role"}
        try: await registry.insert_role_assignment(doc); print("granted", u["email"])
        except Exception as e: print("skip", u["email"], type(e).__name__)
asyncio.run(main())
