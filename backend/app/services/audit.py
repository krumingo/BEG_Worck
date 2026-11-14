"""
Audit logging service.
"""
from datetime import datetime, timezone
import uuid
from app.db import db
from app.tenancy.data_access import TenantData
from app.audit.pay_masking import mask_changes

async def log_audit(org_id: str, user_id: str, user_email: str, action: str, 
                    entity_type: str, entity_id: str = None, changes: dict = None):
    """Create an audit log entry."""
    tenant = TenantData.for_resolved_org(db, org_id)
    entry = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "changes": mask_changes(changes, entity_type),   # PRIV-01 (FG-726): no pay in clear
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await tenant.audit_logs.insert_one(entry)
    return entry
