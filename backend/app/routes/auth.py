"""
Authentication routes - /api/auth/*
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid

from app.db import db
from app.deps.auth import (
    get_current_user, require_admin, require_platform_admin,
    verify_password, create_token, hash_password,
)
from app.deps.modules import enforce_limit
from app.utils.audit import log_audit
from app.constants import ROLES
from app.tenancy.guard import TenantContext
from app.permissions.deps import require_permission, MODE_SHADOW, MODE_ENFORCE
from app.permissions.sync import grant_company_role, shadow_sync
from app.permissions.workflow import (
    RecoverableWrite, fingerprint_without, ERROR_SYNC_FAILED, ERROR_WRITE_INCOMPLETE,
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
    avatar_url: str = None

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
    # Include is_platform_admin for frontend tab visibility
    response = {k: v for k, v in user.items() if k != "password_hash"}
    response["is_platform_admin"] = user.get("is_platform_admin", False)
    return response


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
async def create_user(
    data: UserCreate,
    ctx: TenantContext = Depends(require_permission(
        "user.create", module="M0", scope="company", resource_type="user",
        legacy_check=lambda user, request: user["role"] in ["Admin", "Owner"],
    )),
):
    user = ctx.user
    # W0-02 PR-04/PR-05: the mode was fixed by the dependency; org/db come from
    # the SAME context (legacy user["org_id"] + global db in off/shadow, the
    # registry-resolved active tenant in enforce).
    org_id = ctx.org_id
    tdb = await ctx.db()
    if data.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(ROLES)}")

    def _public(u):
        return {k: v for k, v in u.items() if k not in ("password_hash", "_id")}

    def _new_user_doc():
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
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

    if ctx.mode != MODE_ENFORCE:
        # ---- legacy path (off / shadow): unchanged business behavior ----------
        await enforce_limit(org_id, "users", db_handle=tdb)
        if await tdb.users.find_one({"email": data.email, "org_id": org_id}):
            raise HTTPException(status_code=400, detail="Email already exists in this organization")
        new_user = _new_user_doc()
        await tdb.users.insert_one(new_user)
        await log_audit(org_id, user["id"], user["email"], "created", "user", new_user["id"],
                        {"email": data.email, "role": data.role}, db_handle=tdb)
        if ctx.mode == MODE_SHADOW:
            # Shadow: the legacy write is the truth and stays done. The sync is
            # observed only — a failure is reported, never turned into an
            # error response or a pretended success.
            await shadow_sync(ctx, tdb, "user.create", new_user["id"],
                              lambda: grant_company_role(ctx, new_user["id"], data.role, actor_id=user["id"]))
        return _public(new_user)

    # ---- enforce: recoverable idempotent workflow (PR-05) ---------------------
    existing = await tdb.users.find_one({"email": data.email, "org_id": org_id}, {"_id": 0})
    try:
        wf = await RecoverableWrite(
            tdb, tenant_id=ctx.tenant_id, action="user.create",
            key=f"user.create:{org_id}:{data.email.strip().lower()}",
            fingerprint=fingerprint_without(data.model_dump(), "password")).begin()
    except HTTPException as exc:
        if exc.status_code == 409 and existing is not None:
            # a DIFFERENT request for an email that already exists: legacy contract
            raise HTTPException(status_code=400, detail="Email already exists in this organization")
        raise
    if existing is not None and not (wf.resumed and wf.step_refs.get("business") == existing["id"]):
        # Legacy contract kept: a new request for an existing email is refused.
        # (Only the retry of an interrupted attempt may continue with its user.)
        if not wf.already_completed and not wf.resumed:
            await wf.fail("EMAIL_EXISTS")
        raise HTTPException(status_code=400, detail="Email already exists in this organization")
    if wf.already_completed:
        done = await tdb.users.find_one({"id": wf.completed_reference, "org_id": org_id}, {"_id": 0})
        if done:
            return _public(done)
    if existing is None:
        await enforce_limit(org_id, "users", db_handle=tdb)

    try:
        async def _business():
            if existing is not None:
                return existing["id"]
            doc = _new_user_doc()
            await tdb.users.insert_one(doc)
            return doc["id"]
        new_id = await wf.step("business", _business, reference=lambda r: r)
        # Authoritative assignment (system DB). A failure here leaves a user with
        # NO assignment => denied everywhere in enforce: the safe side.
        await wf.step("sync", lambda: grant_company_role(ctx, new_id, data.role, actor_id=user["id"]))
        await wf.step("legacy_audit", lambda: log_audit(
            org_id, user["id"], user["email"], "created", "user", new_id,
            {"email": data.email, "role": data.role}, db_handle=tdb))
    except HTTPException:
        raise
    except Exception as exc:
        await wf.fail(ERROR_SYNC_FAILED if "sync" not in wf.steps_done else ERROR_WRITE_INCOMPLETE)
        raise wf.failure_response(
            ERROR_SYNC_FAILED if "sync" not in wf.steps_done else ERROR_WRITE_INCOMPLETE, exc)
    await wf.complete(new_id)
    created = await tdb.users.find_one({"id": new_id, "org_id": org_id}, {"_id": 0})
    return _public(created)

@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    data: UserUpdate,
    ctx: TenantContext = Depends(require_permission(
        "user.update", module="M0", scope="company", resource_type="user",
        legacy_check=lambda u, r: u["role"] in ["Admin", "Owner"],
    )),
):
    user = ctx.user
    org_id = ctx.org_id
    tdb = await ctx.db()
    target = await tdb.users.find_one({"id": user_id, **ctx.owner_filter()})
    if not ctx.owns(target):
        raise HTTPException(status_code=404, detail="User not found")   # foreign == missing
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _business():
        await tdb.users.update_one({"id": user_id, **ctx.owner_filter()}, {"$set": update})
        return user_id

    if ctx.mode != MODE_ENFORCE or "role" not in update:
        # legacy behavior (off/shadow), or an enforce update without a role
        # change (no assignment to sync; single business write + legacy audit).
        await _business()
        await log_audit(org_id, user["id"], user["email"], "updated", "user", user_id, update, db_handle=tdb)
        if ctx.mode == MODE_SHADOW and "role" in update:
            await shadow_sync(ctx, tdb, "user.update", user_id,
                              lambda: grant_company_role(ctx, user_id, update["role"], actor_id=user["id"]))
        return await tdb.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})

    # ---- enforce + role change: authoritative assignment FIRST (PR-05) -------
    # If the business write then fails, users.role is stale but the
    # authoritative assignment already carries the NEW role: no stale broad
    # grant can survive. The failed state is recorded; the same request retried
    # finishes the remaining steps.
    wf = await RecoverableWrite(
        tdb, tenant_id=ctx.tenant_id, action="user.update",
        key=f"user.update:{user_id}:{fingerprint_without(update, 'updated_at')}",
        fingerprint=fingerprint_without(update, "updated_at")).begin()
    if wf.already_completed:
        return await tdb.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    try:
        await wf.step("sync", lambda: grant_company_role(ctx, user_id, update["role"], actor_id=user["id"]))
        await wf.step("business", _business, reference=lambda r: r)
        await wf.step("legacy_audit", lambda: log_audit(
            org_id, user["id"], user["email"], "updated", "user", user_id, update, db_handle=tdb))
    except HTTPException:
        raise
    except Exception as exc:
        code = ERROR_SYNC_FAILED if "sync" not in wf.steps_done else ERROR_WRITE_INCOMPLETE
        await wf.fail(code)
        raise wf.failure_response(code, exc)
    await wf.complete(user_id)
    return await tdb.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})

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

# Feature flags routes (read = any user, write = platform admin)
@router.get("/feature-flags")
async def list_feature_flags(user: dict = Depends(get_current_user)):
    return await db.feature_flags.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)

@router.put("/feature-flags")
async def toggle_feature_flag(data: ModuleToggle, user: dict = Depends(require_platform_admin)):
    """
    Toggle a feature flag (module) on/off for the organization.
    
    SECURITY: This endpoint is restricted to platform administrators only.
    Module configuration affects billing and feature access.
    """
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


# Audit logs routes (Platform Admin only)
@router.get("/audit-logs")
async def list_audit_logs(user: dict = Depends(require_platform_admin), limit: int = 50, skip: int = 0):
    """
    List audit logs for the organization.
    
    SECURITY: This endpoint is restricted to platform administrators only.
    Regular org admins cannot access audit logs as they contain sensitive 
    system-wide information.
    """
    logs = await db.audit_logs.find(
        {"org_id": user["org_id"]}, {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.audit_logs.count_documents({"org_id": user["org_id"]})
    return {"logs": logs, "total": total}
