"""
Shared dependencies and globals for routes.
This module is imported by route files to access db, auth, and config.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timezone, timedelta
from typing import List
import os
import uuid

# Load env first
from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# Database
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'begwork')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-key')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Constants
ROLES = ["Admin", "Owner", "SiteManager", "Technician", "Accountant", "Warehousekeeper", "Driver", "Viewer"]

MODULES = {
    "M0": {"name": "Core / SaaS", "description": "Tenants, auth, roles, settings, audit, billing"},
    "M1": {"name": "Projects", "description": "Project management and tracking"},
    "M2": {"name": "Estimates / BOQ", "description": "Offers, activities, bill of quantities"},
    "M3": {"name": "Attendance & Reports", "description": "Daily attendance, work reports, reminders"},
    "M4": {"name": "HR / Payroll", "description": "Hourly/daily/monthly pay, advances, payslips"},
    "M5": {"name": "Finance", "description": "Invoices, payments, cash/bank management"},
    "M6": {"name": "AI Invoice Capture", "description": "Upload, parse, approval queue"},
    "M7": {"name": "Inventory", "description": "Items, stock movements, warehouses"},
    "M8": {"name": "Assets & QR", "description": "Checkout/checkin, maintenance, warranty"},
    "M9": {"name": "Admin Console / BI", "description": "Statistics, alerts, overhead costs"},
}

SUBSCRIPTION_PLANS = {
    "free": {
        "name": "Free Trial",
        "price": 0,
        "stripe_price_id": None,
        "allowed_modules": ["M0", "M1", "M3"],
        "limits": {"users": 3, "projects": 2, "monthly_invoices": 5, "storage_mb": 100},
        "trial_days": 14,
        "description": "14-day trial with basic features",
    },
    "pro": {
        "name": "Professional",
        "price": 49.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_PRO"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M9"],
        "limits": {"users": 20, "projects": 50, "monthly_invoices": 500, "storage_mb": 2000},
        "trial_days": 0,
        "description": "Full access to all features",
    },
    "enterprise": {
        "name": "Enterprise",
        "price": 149.00,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ID_ENTERPRISE"),
        "allowed_modules": ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"],
        "limits": {"users": 100, "projects": 500, "monthly_invoices": 5000, "storage_mb": 20000},
        "trial_days": 0,
        "description": "Unlimited users and premium support",
        "support_priority": "priority",
        "custom_integrations": True,
    }
}

LIMIT_WARNING_THRESHOLD = 0.8

# Auth helpers
def hash_password(pw: str) -> str:
    return pwd_context.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    return jwt.encode({**data, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Account disabled")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

async def get_user_project_ids(user_id: str) -> List[str]:
    members = await db.project_team.find({"user_id": user_id, "active": True}, {"_id": 0, "project_id": 1}).to_list(1000)
    return [m["project_id"] for m in members]

async def can_access_project(user: dict, project_id: str) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    member = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True})
    return member is not None

async def can_manage_project(user: dict, project_id: str) -> bool:
    if user["role"] in ["Admin", "Owner"]:
        return True
    if user["role"] == "SiteManager":
        member = await db.project_team.find_one({"project_id": project_id, "user_id": user["id"], "active": True, "role_in_project": "SiteManager"})
        return member is not None
    return False

# Module access checks
async def check_module_access_for_org(org_id: str, module_code: str) -> tuple:
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return False, "No subscription"
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    status = sub.get("status", "")
    trial_ends_at = sub.get("trial_ends_at")
    
    if status == "trialing" and trial_ends_at:
        now = datetime.now(timezone.utc)
        try:
            trial_end_dt = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
            if now >= trial_end_dt:
                await db.subscriptions.update_one(
                    {"org_id": org_id},
                    {"$set": {"status": "past_due", "updated_at": now.isoformat()}}
                )
                status = "past_due"
        except (ValueError, TypeError):
            pass
    
    if status in ["canceled", "past_due", "incomplete"]:
        if module_code == "M0":
            return True, None
        return False, f"Subscription {status}. Please upgrade your plan."
    
    allowed = module_code in plan["allowed_modules"]
    return allowed, None if allowed else "Module not in your current plan"

async def require_module(module_code: str, user: dict) -> dict:
    allowed, reason = await check_module_access_for_org(user["org_id"], module_code)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason or f"Module {module_code} not available")
    return user

async def require_m2(user: dict = Depends(get_current_user)):
    return await require_module("M2", user)

async def require_m4(user: dict = Depends(get_current_user)):
    return await require_module("M4", user)

async def require_m5(user: dict = Depends(get_current_user)):
    return await require_module("M5", user)

async def require_m9(user: dict = Depends(get_current_user)):
    return await require_module("M9", user)

async def get_plan_limits(org_id: str) -> dict:
    sub = await db.subscriptions.find_one({"org_id": org_id}, {"_id": 0})
    if not sub:
        return SUBSCRIPTION_PLANS["free"]["limits"]
    plan = SUBSCRIPTION_PLANS.get(sub.get("plan_id", "free"), SUBSCRIPTION_PLANS["free"])
    return plan.get("limits", SUBSCRIPTION_PLANS["free"]["limits"])

async def enforce_limit(org_id: str, resource_type: str):
    limits = await get_plan_limits(org_id)
    
    if resource_type == "users":
        count = await db.users.count_documents({"org_id": org_id})
        limit = limits.get("users", 3)
        if count >= limit:
            raise HTTPException(status_code=403, detail={
                "error_code": "LIMIT_USERS_EXCEEDED",
                "current": count,
                "limit": limit,
                "message": f"Plan limit exceeded for users. Current: {count}, Limit: {limit}",
            })
    elif resource_type == "projects":
        count = await db.projects.count_documents({"org_id": org_id})
        limit = limits.get("projects", 2)
        if count >= limit:
            raise HTTPException(status_code=403, detail={
                "error_code": "LIMIT_PROJECTS_EXCEEDED",
                "current": count,
                "limit": limit,
                "message": f"Plan limit exceeded for projects. Current: {count}, Limit: {limit}",
            })
    elif resource_type == "invoices":
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        count = await db.invoices.count_documents({"org_id": org_id, "created_at": {"$gte": month_start}})
        limit = limits.get("monthly_invoices", 5)
        if count >= limit:
            raise HTTPException(status_code=403, detail={
                "error_code": "LIMIT_INVOICES_EXCEEDED",
                "current": count,
                "limit": limit,
                "message": f"Plan limit exceeded for invoices. Current: {count}, Limit: {limit}",
            })

# Audit logging
async def log_audit(org_id: str, user_id: str, user_email: str, action: str, entity_type: str, entity_id: str = None, changes: dict = None):
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


# ══════════════════════════════════════════════════════════════════════════════
# MEDIA ACL - Central access control for media files
# ══════════════════════════════════════════════════════════════════════════════
#
# Access Rules:
# 1. MUST be same org_id (cross-org access never allowed)
# 2. Admin/Owner roles can access ALL media in their org
# 3. Non-admin users:
#    - No context (context_type=None): only owner can access
#    - With context: must have access to the linked entity
#
# Context-based rules:
#   workReport  -> user is author OR has project access (via project_team)
#   delivery    -> user is assigned driver OR has project access
#   attendance  -> user owns the entry OR is SiteManager of the project
#   project     -> user is in project team
#   profile     -> user owns the profile (same user_id)
#   machine     -> user has project access (machines are project-scoped)
#   message     -> user is sender or recipient (future: check message record)
#   [unknown]   -> DENY (safe default)
#
# Actions:
#   "meta"     -> view metadata only
#   "download" -> serve file bytes
#   "link"     -> link media to a context
#   "delete"   -> remove media (owner or admin only)
# ══════════════════════════════════════════════════════════════════════════════

MEDIA_CONTEXT_TYPES = ["workReport", "delivery", "machine", "attendance", "profile", "message", "project"]

async def check_media_access(user: dict, media: dict, action: str = "meta") -> tuple:
    """
    Check if user can access a media item.
    
    Args:
        user: Current user dict (from get_current_user)
        media: Media record dict (from db.media_files)
        action: One of "meta", "download", "link", "delete"
    
    Returns:
        (allowed: bool, reason: str or None)
    
    Legacy Safety:
        - Missing org_id: deny (unless admin can somehow verify)
        - Missing owner_user_id: deny for non-admin (safe default)
        - Missing context: only owner can access
    """
    # Rule 0: Legacy safety - missing org_id
    if not media.get("org_id"):
        if user.get("role") in ["Admin", "Owner"]:
            # Admin can access orphaned media for cleanup purposes
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
    # Non-admin cannot access media with unknown owner (safe default)
    if not owner_user_id:
        return False, "Media record is corrupted (missing owner)"
    
    # Rule 4a: Owner always has access to their own media
    if owner_user_id == user_id:
        return True, None
    
    # Rule 4b: Delete action requires ownership or admin
    if action == "delete":
        return False, "Only owner or admin can delete media"
    
    # Rule 4c: No context = only owner can access (already checked above)
    if not context_type or not context_id:
        return False, "Media has no context; only owner can access"
    
    # Rule 4d: Context-based access check
    allowed, reason = await check_context_access(user, context_type, context_id)
    return allowed, reason


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
        # User is author OR has project access
        report = await db.work_reports.find_one(
            {"id": context_id, "org_id": org_id},
            {"_id": 0, "user_id": 1, "project_id": 1}
        )
        if not report:
            return False, "Work report not found"
        if report.get("user_id") == user_id:
            return True, None
        # Check project access
        project_id = report.get("project_id")
        if project_id and await can_access_project(user, project_id):
            return True, None
        return False, "No access to this work report"
    
    elif context_type == "delivery":
        # User is assigned driver OR has project access
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
        # User owns entry OR is SiteManager of the project
        entry = await db.attendance_entries.find_one(
            {"id": context_id, "org_id": org_id},
            {"_id": 0, "user_id": 1, "project_id": 1}
        )
        if not entry:
            return False, "Attendance entry not found"
        if entry.get("user_id") == user_id:
            return True, None
        # SiteManager can view attendance of their projects
        project_id = entry.get("project_id")
        if project_id and user_role == "SiteManager":
            if await can_manage_project(user, project_id):
                return True, None
        return False, "No access to this attendance entry"
    
    elif context_type == "project":
        # User is in project team
        if await can_access_project(user, context_id):
            return True, None
        return False, "No access to this project"
    
    elif context_type == "profile":
        # User owns the profile (profile context_id = user_id)
        if context_id == user_id:
            return True, None
        return False, "Cannot access another user's profile media"
    
    elif context_type == "machine":
        # Machines are project-scoped; check project access
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
        # Future: check if user is sender or recipient
        # For now, allow if user is in the same org (messages are org-scoped)
        # This is a placeholder - implement proper message ACL when messages module exists
        return True, None
    
    else:
        # Unknown context type - deny by default (safe)
        return False, f"Unknown context type: {context_type}"


async def enforce_media_access(user: dict, media: dict, action: str = "meta"):
    """
    Enforce media access - raises HTTPException if denied.
    
    Usage:
        await enforce_media_access(user, media, "download")
    """
    allowed, reason = await check_media_access(user, media, action)
    if not allowed:
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
    
    Usage:
        await enforce_context_access(user, "workReport", report_id)
    """
    # Admin/Owner can access any context in their org
    if user.get("role") in ["Admin", "Owner"]:
        return
    
    allowed, reason = await check_context_access(user, context_type, context_id)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "CONTEXT_ACCESS_DENIED",
                "reason": reason or "Access denied to target context",
                "context_type": context_type,
            }
        )
