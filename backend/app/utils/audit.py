"""
Audit and security logging utilities.
"""
from datetime import datetime, timezone
import uuid
import logging

# Configure security logger
security_logger = logging.getLogger("security")
security_logger.setLevel(logging.INFO)


def log_security_event(event_type: str, user: dict = None, payload: dict = None):
    """
    Log a structured security event for audit trail.
    
    Event types:
        - MEDIA_ACCESS_DENIED: User denied access to media
        - CONTEXT_ACCESS_DENIED: User denied access to context (for linking)
    
    Payload keys (depending on event):
        - media_id, stored_filename (NO full paths)
        - context_type, context_id
        - action, reason
    
    Security: Never logs tokens, passwords, full file paths, or request bodies.
    """
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "user_id": user.get("id") if user else None,
        "org_id": user.get("org_id") if user else None,
        "role": user.get("role") if user else None,
    }
    
    if payload:
        # Sanitize: only allow safe keys
        safe_keys = ["media_id", "stored_filename", "context_type", "context_id", 
                     "action", "reason", "target_context_type", "target_context_id"]
        for key in safe_keys:
            if key in payload:
                event[key] = payload[key]
    
    # Log as structured JSON-like string
    security_logger.warning(f"SECURITY_EVENT: {event}")


async def log_audit(db, org_id: str, user_id: str, user_email: str, action: str, 
                    entity_type: str, entity_id: str = None, changes: dict = None):
    """
    Log an audit entry to the database.
    
    Args:
        db: Database instance
        org_id: Organization ID
        user_id: User ID performing the action
        user_email: User email
        action: Action performed (create, update, delete, etc.)
        entity_type: Type of entity affected
        entity_id: ID of the entity
        changes: Dictionary of changes made
    """
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
