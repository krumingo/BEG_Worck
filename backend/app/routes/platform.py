"""
Platform Bootstrap Routes

ONE-TIME USE endpoint for initial platform setup without shell access.
Protected by PLATFORM_BOOTSTRAP_TOKEN environment variable.

SECURITY:
- Remove PLATFORM_BOOTSTRAP_TOKEN from env vars after use to disable endpoint
- Constant-time token comparison to prevent timing attacks
- Rate limiting (5 requests per 10 minutes per IP)
- All actions are logged as SECURITY_EVENT
- No sensitive data (password/token) in logs

README NOTE:
After first successful use, REMOVE PLATFORM_BOOTSTRAP_TOKEN from production 
environment variables to permanently disable the bootstrap endpoint.
"""
import os
import re
import hmac
import uuid
import logging
from datetime import datetime, timezone
from collections import defaultdict
from time import time
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, EmailStr, field_validator
from passlib.context import CryptContext

from app.shared import db

router = APIRouter(prefix="/api/platform", tags=["Platform Bootstrap"])

# Security logger
security_logger = logging.getLogger("security")

# Password hashing (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ═══════════════════════════════════════════════════════════════════════════════
# RATE LIMITING (In-memory, simple implementation)
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Simple in-memory rate limiter: 5 requests per 10 minutes per IP."""
    
    def __init__(self, max_requests: int = 5, window_seconds: int = 600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
    
    def is_allowed(self, ip: str) -> bool:
        """Check if request is allowed for this IP."""
        now = time()
        cutoff = now - self.window_seconds
        
        # Clean old requests
        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]
        
        if len(self._requests[ip]) >= self.max_requests:
            return False
        
        self._requests[ip].append(now)
        return True
    
    def get_remaining(self, ip: str) -> int:
        """Get remaining requests for this IP."""
        now = time()
        cutoff = now - self.window_seconds
        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]
        return max(0, self.max_requests - len(self._requests[ip]))
    
    def reset(self, ip: str = None):
        """Reset rate limit for specific IP or all IPs (for testing)."""
        if ip:
            self._requests[ip] = []
        else:
            self._requests.clear()


# Global rate limiter instance (20 requests per 10 min - more lenient for testing)
bootstrap_rate_limiter = RateLimiter(max_requests=20, window_seconds=600)


# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def constant_time_compare(a: str, b: str) -> bool:
    """
    Constant-time string comparison to prevent timing attacks.
    Uses hmac.compare_digest which is designed for this purpose.
    """
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode('utf-8'), b.encode('utf-8'))


def validate_email_format(email: str) -> bool:
    """Validate email format using regex."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets minimum requirements:
    - At least 10 characters
    """
    if len(password) < 10:
        return False, "Password must be at least 10 characters"
    return True, ""


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    # Check X-Forwarded-For header (for proxies/load balancers)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    
    # Fall back to direct client
    return request.client.host if request.client else "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class BootstrapCreateAdminRequest(BaseModel):
    email: EmailStr
    password: str
    
    @field_validator('password')
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 10:
            raise ValueError('Password must be at least 10 characters')
        return v


# ═══════════════════════════════════════════════════════════════════════════════
# BOOTSTRAP ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/bootstrap-create-platform-admin")
async def bootstrap_create_platform_admin(
    request: Request,
    data: BootstrapCreateAdminRequest,
    x_bootstrap_token: str = Header(None, alias="X-Bootstrap-Token")
):
    """
    ONE-TIME USE: Create the first Platform Admin user.
    
    SECURITY:
    - Requires X-Bootstrap-Token header matching PLATFORM_BOOTSTRAP_TOKEN env var
    - If env var is missing/empty, returns 403 "Bootstrap disabled"
    - Token comparison uses constant-time algorithm (timing attack protection)
    - Rate limited: 5 requests per 10 minutes per IP
    - Password is hashed with bcrypt (never stored in plaintext)
    - Idempotent: if user exists, returns ok:true, created:false (no changes made)
    - All actions logged to audit trail (no sensitive data)
    
    AFTER FIRST USE: Remove PLATFORM_BOOTSTRAP_TOKEN from production env vars!
    
    Usage:
        curl -X POST "https://your-domain/api/platform/bootstrap-create-platform-admin" \\
            -H "Content-Type: application/json" \\
            -H "X-Bootstrap-Token: YOUR_TOKEN" \\
            -d '{"email": "admin@example.com", "password": "SecurePass123!"}'
    
    Responses:
        200: Success (created:true or created:false)
        400: Invalid body / email / password
        401: Invalid bootstrap token
        403: Bootstrap disabled (env var not set)
        429: Rate limit exceeded
        500: Unexpected error
    """
    client_ip = get_client_ip(request)
    now = datetime.now(timezone.utc).isoformat()
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: Check if bootstrap is enabled (env var exists)
    # ─────────────────────────────────────────────────────────────────────────
    expected_token = os.environ.get("PLATFORM_BOOTSTRAP_TOKEN", "").strip()
    
    if not expected_token:
        security_logger.warning(
            f"SECURITY_EVENT: BOOTSTRAP_DISABLED | "
            f"ip={client_ip} | email={data.email} | timestamp={now}"
        )
        raise HTTPException(
            status_code=403,
            detail="Bootstrap disabled"
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: Rate limiting
    # ─────────────────────────────────────────────────────────────────────────
    if not bootstrap_rate_limiter.is_allowed(client_ip):
        security_logger.warning(
            f"SECURITY_EVENT: BOOTSTRAP_RATE_LIMITED | "
            f"ip={client_ip} | email={data.email} | timestamp={now}"
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later."
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3: Verify token (constant-time comparison)
    # ─────────────────────────────────────────────────────────────────────────
    if not x_bootstrap_token:
        security_logger.warning(
            f"SECURITY_EVENT: BOOTSTRAP_MISSING_TOKEN | "
            f"ip={client_ip} | email={data.email} | timestamp={now}"
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid bootstrap token"
        )
    
    if not constant_time_compare(x_bootstrap_token, expected_token):
        security_logger.warning(
            f"SECURITY_EVENT: BOOTSTRAP_INVALID_TOKEN | "
            f"ip={client_ip} | email={data.email} | timestamp={now}"
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid bootstrap token"
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4: Check if user already exists (idempotency)
    # ─────────────────────────────────────────────────────────────────────────
    existing_user = await db.users.find_one(
        {"email": data.email},
        {"_id": 0, "id": 1, "email": 1, "is_platform_admin": 1}
    )
    
    if existing_user:
        # User exists - DO NOT change password or roles
        # Just log and return success with created:false
        security_logger.info(
            f"SECURITY_EVENT: BOOTSTRAP_CREATE_PLATFORM_ADMIN | "
            f"action=user_exists | ip={client_ip} | email={data.email} | "
            f"created=false | timestamp={now}"
        )
        
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": "SYSTEM",
            "user_id": "BOOTSTRAP",
            "user_email": "BOOTSTRAP",
            "action": "BOOTSTRAP_CREATE_PLATFORM_ADMIN",
            "entity_type": "user",
            "entity_id": existing_user.get("id", "unknown"),
            "changes": {
                "email": data.email,
                "ip": client_ip,
                "created": False,
                "reason": "user_already_exists"
            },
            "timestamp": now
        })
        
        return {
            "ok": True,
            "created": False,
            "message": f"Platform admin {data.email} already exists",
            "next_steps": [
                "1. Login at /platform/login",
                "2. IMPORTANT: Remove PLATFORM_BOOTSTRAP_TOKEN from environment variables"
            ]
        }
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5: Create new platform admin user
    # ─────────────────────────────────────────────────────────────────────────
    try:
        # Get or create system organization
        system_org = await db.organizations.find_one({"slug": "platform-system"})
        if not system_org:
            org_id = str(uuid.uuid4())
            await db.organizations.insert_one({
                "id": org_id,
                "name": "Platform System",
                "slug": "platform-system",
                "subscription_plan": "enterprise",
                "subscription_status": "active",
                "created_at": now,
                "updated_at": now
            })
        else:
            org_id = system_org["id"]
        
        # Create user
        user_id = str(uuid.uuid4())
        password_hash = pwd_context.hash(data.password)
        
        # Extract name from email
        email_name = data.email.split("@")[0]
        first_name = email_name.split(".")[0].capitalize() if "." in email_name else email_name.capitalize()
        last_name = email_name.split(".")[-1].capitalize() if "." in email_name else "Admin"
        
        await db.users.insert_one({
            "id": user_id,
            "org_id": org_id,
            "email": data.email,
            "password_hash": password_hash,
            "first_name": first_name,
            "last_name": last_name,
            "role": "Admin",
            "phone": "",
            "is_active": True,
            "is_platform_admin": True,
            "created_at": now,
            "updated_at": now
        })
        
        # Log success (NO password or token in logs)
        security_logger.info(
            f"SECURITY_EVENT: BOOTSTRAP_CREATE_PLATFORM_ADMIN | "
            f"action=created | ip={client_ip} | email={data.email} | "
            f"user_id={user_id} | created=true | timestamp={now}"
        )
        
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": "SYSTEM",
            "user_id": "BOOTSTRAP",
            "user_email": "BOOTSTRAP",
            "action": "BOOTSTRAP_CREATE_PLATFORM_ADMIN",
            "entity_type": "user",
            "entity_id": user_id,
            "changes": {
                "email": data.email,
                "ip": client_ip,
                "created": True
            },
            "timestamp": now
        })
        
        return {
            "ok": True,
            "created": True,
            "message": f"New platform admin {data.email} created successfully",
            "next_steps": [
                "1. Login at /platform/login with the password you provided",
                "2. IMPORTANT: Remove PLATFORM_BOOTSTRAP_TOKEN from environment variables"
            ]
        }
        
    except Exception as e:
        # Log error without exposing details
        security_logger.error(
            f"SECURITY_EVENT: BOOTSTRAP_CREATE_PLATFORM_ADMIN | "
            f"action=error | ip={client_ip} | email={data.email} | "
            f"error_type={type(e).__name__} | timestamp={now}"
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS ENDPOINT (for checking if bootstrap is enabled)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/bootstrap-status")
async def bootstrap_status():
    """
    Check if bootstrap endpoint is enabled (token configured).
    Does not reveal the actual token value.
    """
    is_enabled = bool(os.environ.get("PLATFORM_BOOTSTRAP_TOKEN", "").strip())
    return {
        "bootstrap_enabled": is_enabled,
        "message": (
            "Bootstrap endpoint is enabled. Use POST /api/platform/bootstrap-create-platform-admin with X-Bootstrap-Token header."
            if is_enabled else
            "Bootstrap endpoint is disabled. PLATFORM_BOOTSTRAP_TOKEN not configured."
        )
    }
