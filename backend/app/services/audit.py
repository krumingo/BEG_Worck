"""
Audit logging service.
"""
from datetime import datetime, timezone
import uuid
from app.db import db

async def log_audit(org_id: str, user_id: str, user_email: str, action: str, 
                    entity_type: str, entity_id: str = None, changes: dict = None):
    """Create an audit log entry."""
    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "changes": changes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.audit_logs.insert_one(entry)
    return entry
