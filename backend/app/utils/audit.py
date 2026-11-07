"""
Audit and security logging utilities.
"""
from datetime import datetime, timezone
import uuid
import logging

from pymongo.errors import DuplicateKeyError

from app.db import db

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


async def log_audit(org_id: str, user_id: str, user_email: str, action: str, 
                    entity_type: str, entity_id: str = None, changes: dict = None,
                    db_handle=None, session=None, entry_id: str = None):
    """
    Log an audit entry to the database.
    
    Args:
        org_id: Organization ID
        user_id: User ID performing the action
        user_email: User email
        action: Action performed (create, update, delete, etc.)
        entity_type: Type of entity affected
        entity_id: ID of the entity
        changes: Dictionary of changes made
        entry_id: SEC-01-C03 (audit of #69 @ da47777) — a durable id for the row, derived
            from the operation's Idempotency-Key. It is also the row's ``_id``, so a retry of
            the same operation that writes the entry again hits the unique ``_id`` and is
            skipped: one audit row per durable operation. Absent -> a fresh id, as before.
    """
    entry = {
        "id": entry_id or str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "user_email": user_email,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "changes": changes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # W0-02 PR-04: a migrated enforce route passes its tenant-resolved handle so
    # the legacy audit row lands in the SAME database as the business write.
    # AUTH-01 C01: ``session`` lets the audit row commit or roll back together
    # with the business write it records (one Mongo transaction).
    if entry_id is None:
        await (db if db_handle is None else db_handle).audit_logs.insert_one(entry, session=session)
        return
    entry["_id"] = entry_id
    try:
        await (db if db_handle is None else db_handle).audit_logs.insert_one(entry, session=session)
    except DuplicateKeyError as exc:
        pattern = (getattr(exc, "details", None) or {}).get("keyPattern") or {}
        if set(pattern) != {"_id"}:
            raise                       # another unique index: a real error
        # the same durable operation already wrote this entry (a retry after a crash)
