"""
Media ACL (Access Control List) dependencies.

Central access control for media files.

Access Rules:
1. MUST be same org_id (cross-org access never allowed)
2. Admin/Owner roles can access ALL media in their org
3. Non-admin users:
   - No context (context_type=None): only owner can access
   - With context: must have access to the linked entity

Context-based rules:
  workReport  -> user is author OR has project access (via project_team)
  delivery    -> user is assigned driver OR has project access
  attendance  -> user owns the entry OR is SiteManager of the project
  project     -> user is in project team
  profile     -> user owns the profile (same user_id)
  machine     -> user has project access (machines are project-scoped)
  message     -> user is sender or recipient (future: check message record)
  [unknown]   -> DENY (safe default)

Actions:
  "meta"     -> view metadata only
  "download" -> serve file bytes
  "link"     -> link media to a context
  "delete"   -> remove media (owner or admin only)
"""
from fastapi import HTTPException
import logging

from app.db import db
from app.deps.auth import can_access_project, can_manage_project

# Media context types
MEDIA_CONTEXT_TYPES = ["workReport", "delivery", "machine", "attendance", "profile", "message", "project"]

# Security logger
security_logger = logging.getLogger("security")


def log_security_event(event_type: str, user: dict = None, payload: dict = None):
    """
    Log a structured security event for audit trail.
    """
    from datetime import datetime, timezone
    
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "user_id": user.get("id") if user else None,
        "org_id": user.get("org_id") if user else None,
        "role": user.get("role") if user else None,
    }
    
    if payload:
        safe_keys = ["media_id", "stored_filename", "context_type", "context_id", 
                     "action", "reason", "target_context_type", "target_context_id"]
        for key in safe_keys:
            if key in payload:
                event[key] = payload[key]
    
    security_logger.warning(f"SECURITY_EVENT: {event}")


async def check_context_access(user: dict, context_type: str, context_id: str) -> tuple:
    """
    Check if user has access to a specific context entity.
    
    Returns:
        (allowed: bool, reason: str or None)
    """
    user_id = user.get("id")
    user_role = user.get("role")
    org_id = user.get("org_id")
    
    if context_type == "workReport":
        report = await db.work_reports.find_one(
            {"id": context_id, "org_id": org_id},
            {"_id": 0, "user_id": 1, "project_id": 1}
        )
        if not report:
            return False, "Work report not found"
        if report.get("user_id") == user_id:
            return True, None
        project_id = report.get("project_id")
        if project_id and await can_access_project(user, project_id):
            return True, None
        return False, "No access to this work report"
    
    elif context_type == "delivery":
        delivery = await db.deliveries.find_one(
            {"id": context_id, "org_id": org_id},
            {"_id": 0, "driver_user_id": 1, "project_id": 1}
        )
        if not delivery:
            return False, "Delivery not found"
        if delivery.get("driver_user_id") == user_id:
            return True, None
        project_id = delivery.get("project_id")
        if project_id and await can_access_project(user, project_id):
            return True, None
        return False, "No access to this delivery"
    
    elif context_type == "attendance":
        entry = await db.attendance_entries.find_one(
            {"id": context_id, "org_id": org_id},
            {"_id": 0, "user_id": 1, "project_id": 1}
        )
        if not entry:
            return False, "Attendance entry not found"
        if entry.get("user_id") == user_id:
            return True, None
        project_id = entry.get("project_id")
        if project_id and user_role == "SiteManager":
            if await can_manage_project(user, project_id):
                return True, None
        return False, "No access to this attendance entry"
    
    elif context_type == "project":
        if await can_access_project(user, context_id):
            return True, None
        return False, "No access to this project"
    
    elif context_type == "profile":
        if context_id == user_id:
            return True, None
        return False, "Cannot access another user's profile media"
    
    elif context_type == "machine":
        machine = await db.machines.find_one(
            {"id": context_id, "org_id": org_id},
            {"_id": 0, "project_id": 1}
        )
        if not machine:
            return False, "Machine not found"
        project_id = machine.get("project_id")
        if project_id and await can_access_project(user, project_id):
            return True, None
        return False, "No access to this machine"
    
    elif context_type == "message":
        # TODO: Implement proper message ACL when messages module is built
        # For now, allow any user in the same org
        return True, None
    
    else:
        return False, f"Unknown context type: {context_type}"


async def check_media_access(user: dict, media: dict, action: str = "meta") -> tuple:
    """
    Check if user can access a media item.
    
    Args:
        user: Current user dict (from get_current_user)
        media: Media record dict (from db.media_files)
        action: One of "meta", "download", "link", "delete"
    
    Returns:
        (allowed: bool, reason: str or None)
    """
    # Rule 0: Legacy safety - missing org_id
    if not media.get("org_id"):
        if user.get("role") in ["Admin", "Owner"]:
            return True, None
        return False, "Media record is corrupted (missing org_id)"
    
    # Rule 1: Must be same org
    if media.get("org_id") != user.get("org_id"):
        return False, "Media belongs to different organization"
    
    # Rule 2: Admin/Owner can access everything in their org
    if user.get("role") in ["Admin", "Owner"]:
        return True, None
    
    user_id = user.get("id")
    owner_user_id = media.get("owner_user_id")
    context_type = media.get("context_type")
    context_id = media.get("context_id")
    
    # Rule 3: Legacy safety - missing owner_user_id
    if not owner_user_id:
        return False, "Media record is corrupted (missing owner)"
    
    # Rule 4a: Owner always has access to their own media
    if owner_user_id == user_id:
        return True, None
    
    # Rule 4b: Delete action requires ownership or admin
    if action == "delete":
        return False, "Only owner or admin can delete media"
    
    # Rule 4c: No context = only owner can access
    if not context_type or not context_id:
        return False, "Media has no context; only owner can access"
    
    # Rule 4d: Context-based access check
    allowed, reason = await check_context_access(user, context_type, context_id)
    return allowed, reason


async def enforce_media_access(user: dict, media: dict, action: str = "meta"):
    """
    Enforce media access - raises HTTPException if denied.
    Logs security event before denying.
    """
    allowed, reason = await check_media_access(user, media, action)
    if not allowed:
        log_security_event(
            "MEDIA_ACCESS_DENIED",
            user=user,
            payload={
                "media_id": media.get("id"),
                "stored_filename": media.get("stored_filename"),
                "context_type": media.get("context_type"),
                "context_id": media.get("context_id"),
                "action": action,
                "reason": reason,
            }
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "MEDIA_ACCESS_DENIED",
                "reason": reason or "Access denied",
                "action": action,
            }
        )


async def enforce_context_access(user: dict, context_type: str, context_id: str):
    """
    Enforce context access - raises HTTPException if denied.
    Used to verify user can access a target context before linking media to it.
    """
    # Admin/Owner can access any context in their org
    if user.get("role") in ["Admin", "Owner"]:
        return
    
    allowed, reason = await check_context_access(user, context_type, context_id)
    if not allowed:
        log_security_event(
            "CONTEXT_ACCESS_DENIED",
            user=user,
            payload={
                "target_context_type": context_type,
                "target_context_id": context_id,
                "reason": reason,
            }
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "CONTEXT_ACCESS_DENIED",
                "reason": reason or "Access denied to target context",
                "context_type": context_type,
            }
        )
