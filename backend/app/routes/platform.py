"""
Platform Bootstrap Routes

ONE-TIME USE endpoints for initial platform setup without shell access.
Protected by PLATFORM_BOOTSTRAP_TOKEN environment variable.

SECURITY:
- Remove PLATFORM_BOOTSTRAP_TOKEN from env vars after use to disable endpoint
- All actions are logged as SECURITY_EVENT
- No sensitive data in logs
"""
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr

from app.shared import db

router = APIRouter(prefix="/api/platform", tags=["Platform Bootstrap"])

# Security logger
security_logger = logging.getLogger("security")


class BootstrapPromoteRequest(BaseModel):
    email: EmailStr


def verify_bootstrap_token(token: str) -> bool:
    """Verify the bootstrap token from environment."""
    expected = os.environ.get("PLATFORM_BOOTSTRAP_TOKEN")
    if not expected:
        return False
    return token == expected


@router.post("/bootstrap-promote")
async def bootstrap_promote_platform_admin(
    data: BootstrapPromoteRequest,
    x_bootstrap_token: str = Header(None, alias="X-Bootstrap-Token")
):
    """
    ONE-TIME USE: Promote a user to platform admin without shell access.
    
    SECURITY:
    - Requires X-Bootstrap-Token header matching PLATFORM_BOOTSTRAP_TOKEN env var
    - If token is not set in env, endpoint returns 403 (disabled)
    - After successful promotion, REMOVE the env var to disable this endpoint
    
    Usage:
        curl -X POST "https://your-domain/api/platform/bootstrap-promote" \
            -H "Content-Type: application/json" \
            -H "X-Bootstrap-Token: YOUR_TOKEN" \
            -d '{"email": "admin@example.com"}'
    """
    # Check if bootstrap is enabled
    if not os.environ.get("PLATFORM_BOOTSTRAP_TOKEN"):
        security_logger.warning(
            "SECURITY_EVENT: BOOTSTRAP_ATTEMPT_DISABLED | "
            f"email={data.email} | endpoint=bootstrap-promote"
        )
        raise HTTPException(
            status_code=403,
            detail="Bootstrap endpoint is disabled. PLATFORM_BOOTSTRAP_TOKEN not configured."
        )
    
    # Verify token
    if not x_bootstrap_token or not verify_bootstrap_token(x_bootstrap_token):
        security_logger.warning(
            "SECURITY_EVENT: BOOTSTRAP_INVALID_TOKEN | "
            f"email={data.email} | endpoint=bootstrap-promote"
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing bootstrap token"
        )
    
    # Find user
    user = await db.users.find_one(
        {"email": data.email},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "is_platform_admin": 1}
    )
    
    if not user:
        security_logger.warning(
            f"SECURITY_EVENT: BOOTSTRAP_USER_NOT_FOUND | "
            f"email={data.email} | endpoint=bootstrap-promote"
        )
        raise HTTPException(
            status_code=404,
            detail=f"User with email {data.email} not found"
        )
    
    # Check if already platform admin
    if user.get("is_platform_admin", False):
        security_logger.info(
            f"SECURITY_EVENT: BOOTSTRAP_ALREADY_ADMIN | "
            f"email={data.email} | endpoint=bootstrap-promote"
        )
        return {
            "ok": True,
            "message": "User is already a platform admin",
            "user": {
                "email": user["email"],
                "role": user["role"],
                "is_platform_admin": True
            }
        }
    
    # Promote to platform admin
    now = datetime.now(timezone.utc).isoformat()
    result = await db.users.update_one(
        {"email": data.email},
        {"$set": {
            "is_platform_admin": True,
            "is_active": True,
            "updated_at": now
        }}
    )
    
    if result.modified_count == 0:
        raise HTTPException(
            status_code=500,
            detail="Failed to update user"
        )
    
    # Log security event (no sensitive data)
    security_logger.info(
        f"SECURITY_EVENT: PLATFORM_ADMIN_PROMOTED | "
        f"email={data.email} | endpoint=bootstrap-promote | "
        f"timestamp={now}"
    )
    
    # Also log to audit_logs collection
    await db.audit_logs.insert_one({
        "id": str(__import__("uuid").uuid4()),
        "org_id": "SYSTEM",
        "user_id": "BOOTSTRAP",
        "user_email": "BOOTSTRAP",
        "action": "PLATFORM_ADMIN_PROMOTED",
        "entity_type": "user",
        "entity_id": user["id"],
        "changes": {
            "email": data.email,
            "is_platform_admin": True,
            "promoted_via": "bootstrap-endpoint"
        },
        "timestamp": now
    })
    
    return {
        "ok": True,
        "message": f"Successfully promoted {data.email} to platform admin",
        "user": {
            "email": data.email,
            "role": user["role"],
            "is_platform_admin": True
        },
        "next_steps": [
            "1. Verify by logging in and checking /api/auth/me",
            "2. IMPORTANT: Remove PLATFORM_BOOTSTRAP_TOKEN from environment variables to disable this endpoint"
        ]
    }


@router.get("/bootstrap-status")
async def bootstrap_status():
    """
    Check if bootstrap endpoint is enabled (token configured).
    Does not reveal the actual token.
    """
    is_enabled = bool(os.environ.get("PLATFORM_BOOTSTRAP_TOKEN"))
    return {
        "bootstrap_enabled": is_enabled,
        "message": "Bootstrap endpoint is enabled. Use POST /api/platform/bootstrap-promote with X-Bootstrap-Token header." if is_enabled else "Bootstrap endpoint is disabled. PLATFORM_BOOTSTRAP_TOKEN not configured."
    }
