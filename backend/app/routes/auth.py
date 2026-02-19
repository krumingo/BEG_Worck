"""
Authentication routes - /api/auth/*
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid

from app.shared import (
    db, ROLES, get_current_user, require_admin, 
    verify_password, create_token, hash_password, 
    log_audit, enforce_limit
)

router = APIRouter(tags=["auth"])

# Pydantic models
class LoginRequest(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    role: str = "Viewer"
    phone: str = ""

class UserUpdate(BaseModel):
    first_name: str = None
    last_name: str = None
    role: str = None
    phone: str = None
    is_active: bool = None

class OrgUpdate(BaseModel):
    name: str = None
    address: str = None
    phone: str = None
    email: str = None
    attendance_start: str = None
    attendance_end: str = None
    work_report_deadline: str = None
    max_reminders_per_day: int = None
    escalation_after_days: int = None
    org_timezone: str = None

class ModuleToggle(BaseModel):
    module_code: str
    enabled: bool

# Auth routes
@router.post("/auth/login")
async def login(req: LoginRequest):
    user = await db.users.find_one({"email": req.email}, {"_id": 0})
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_token({"user_id": user["id"], "org_id": user["org_id"], "role": user["role"]})
    await log_audit(user["org_id"], user["id"], user["email"], "login", "auth")
    return {"token": token, "user": {k: v for k, v in user.items() if k != "password_hash"}}

@router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {k: v for k, v in user.items() if k != "password_hash"}


# ══════════════════════════════════════════════════════════════════════════════
# Change Password
# ══════════════════════════════════════════════════════════════════════════════

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets security requirements:
    - Minimum 10 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter  
    - At least 1 digit
    - At least 1 special character (!@#$%^&*()_+-=[]{}|;:,.<>?)
    
    Returns (is_valid, error_message)
    """
    if len(password) < 10:
        return False, "Password must be at least 10 characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        return False, "Password must contain at least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)"
    return True, ""


@router.post("/auth/change-password")
async def change_password(data: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """
    Change password for the currently authenticated user.
    
    Requires:
    - Valid JWT token
    - Correct current_password
    - new_password meeting security policy
    
    Returns: { ok: true }
    """
    # Fetch fresh user data with password hash
    db_user = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify current password
    if not verify_password(data.current_password, db_user["password_hash"]):
        # Log failed attempt (security event)
        await log_audit(user["org_id"], user["id"], user["email"], "password_change_failed", "auth", 
                       changes={"reason": "Invalid current password"})
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    
    # Validate new password strength
    is_valid, error_msg = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # Check new password is different from current
    if verify_password(data.new_password, db_user["password_hash"]):
        raise HTTPException(status_code=400, detail="New password must be different from current password")
    
    # Update password
    new_hash = hash_password(data.new_password)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": new_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "password_changed_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Log success (security event)
    await log_audit(user["org_id"], user["id"], user["email"], "password_changed", "auth")
    
    return {"ok": True}


# Organization routes
@router.get("/organization")
async def get_organization(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org

@router.put("/organization")
async def update_organization(data: OrgUpdate, user: dict = Depends(require_admin)):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.organizations.update_one({"id": user["org_id"]}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "organization", user["org_id"], update)
    return await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})

# User routes
@router.get("/users")
async def list_users(user: dict = Depends(get_current_user)):
    return await db.users.find({"org_id": user["org_id"]}, {"_id": 0, "password_hash": 0}).to_list(1000)

@router.post("/users", status_code=201)
async def create_user(data: UserCreate, user: dict = Depends(require_admin)):
    await enforce_limit(user["org_id"], "users")
    
    if await db.users.find_one({"email": data.email, "org_id": user["org_id"]}):
        raise HTTPException(status_code=400, detail="Email already exists in this organization")
    if data.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(ROLES)}")
    now = datetime.now(timezone.utc).isoformat()
    new_user = {
        "id": str(uuid.uuid4()),
        "org_id": user["org_id"],
        "email": data.email,
        "password_hash": hash_password(data.password),
        "first_name": data.first_name,
        "last_name": data.last_name,
        "role": data.role,
        "phone": data.phone,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.users.insert_one(new_user)
    await log_audit(user["org_id"], user["id"], user["email"], "created", "user", new_user["id"], {"email": data.email, "role": data.role})
    return {k: v for k, v in new_user.items() if k not in ("password_hash", "_id")}

@router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, user: dict = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"id": user_id}, {"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "user", user_id, update)
    return await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    target = await db.users.find_one({"id": user_id, "org_id": user["org_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.delete_one({"id": user_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "user", user_id)
    return {"ok": True}

# Feature flags routes
@router.get("/feature-flags")
async def list_feature_flags(user: dict = Depends(get_current_user)):
    return await db.feature_flags.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)

@router.put("/feature-flags")
async def toggle_feature_flag(data: ModuleToggle, user: dict = Depends(require_admin)):
    if data.module_code == "M0":
        raise HTTPException(status_code=400, detail="Core module cannot be disabled")
    result = await db.feature_flags.update_one(
        {"org_id": user["org_id"], "module_code": data.module_code},
        {"$set": {"enabled": data.enabled, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": user["id"]}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Module not found")
    await log_audit(user["org_id"], user["id"], user["email"], "toggled", "feature_flag", data.module_code, {"enabled": data.enabled})
    return await db.feature_flags.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)

# ══════════════════════════════════════════════════════════════════════════════
# Admin Set Password (for forgotten passwords)
# ══════════════════════════════════════════════════════════════════════════════

class AdminSetPasswordRequest(BaseModel):
    new_password: str


@router.post("/admin/set-password/{user_id}")
async def admin_set_password(user_id: str, data: AdminSetPasswordRequest, admin: dict = Depends(require_admin)):
    """
    Admin/Owner can set a new password for any user in their organization.
    
    Used when users forget their passwords and need a reset.
    
    Security:
    - Only Admin/Owner roles can use this endpoint
    - Cannot reset own password (use /auth/change-password instead)
    - Full audit logging with admin details
    - Same password strength requirements apply
    
    Returns: { ok: true }
    """
    # Prevent admin from using this to reset their own password
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=400, 
            detail="Cannot use admin reset for your own password. Use the change-password feature instead."
        )
    
    # Find target user in same organization
    target_user = await db.users.find_one(
        {"id": user_id, "org_id": admin["org_id"]},
        {"_id": 0}
    )
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found in your organization")
    
    # Validate new password strength
    is_valid, error_msg = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # Update password
    new_hash = hash_password(data.new_password)
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "password_hash": new_hash,
            "updated_at": now,
            "password_reset_at": now,
            "password_reset_by": admin["id"]
        }}
    )
    
    # Audit log with detailed info (security event)
    await log_audit(
        admin["org_id"], 
        admin["id"], 
        admin["email"], 
        "admin_password_reset", 
        "user", 
        user_id, 
        {
            "target_email": target_user["email"],
            "reset_by_role": admin["role"]
        }
    )
    
    return {"ok": True}


# Audit logs routes
@router.get("/audit-logs")
async def list_audit_logs(user: dict = Depends(require_admin), limit: int = 50, skip: int = 0):
    logs = await db.audit_logs.find(
        {"org_id": user["org_id"]}, {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.audit_logs.count_documents({"org_id": user["org_id"]})
    return {"logs": logs, "total": total}
