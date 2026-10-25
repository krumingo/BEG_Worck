"""
Authentication routes - /api/auth/*
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
import logging
import uuid

from app.db import db
from app.deps.auth import (
    get_current_user, require_admin, require_platform_admin,
    verify_password, create_token, hash_password,
)
from app.deps.modules import enforce_limit
from app.utils.audit import log_audit
from app.services import auth_events, password_reset, rate_limit
from app.utils.client_ip import client_ip
from app.master_data.legacy_adapter import guarded_identity_delete
from app.constants import ROLES
from app.tenancy.guard import TenantContext
from app.tenancy.data_access import TenantData
from app.permissions.deps import require_permission, MODE_SHADOW, MODE_ENFORCE
from app.permissions.sync import grant_company_role, shadow_sync
from app.permissions.workflow import (
    RecoverableWrite, fingerprint_without, ERROR_SYNC_FAILED, ERROR_WRITE_INCOMPLETE,
)
from app.tenancy.identity import (
    ERROR_DUPLICATE_IDENTITY, ERROR_EMAIL_EXISTS, ERROR_IDENTITY_CHECK_UNAVAILABLE,
    IdentityCheckUnavailable, email_match_filter, installation_databases,
    installation_databases_for, normalize_email, users_with_email,
)
from app.services.user_role_policy import (
    audit_user_change, check_owner_only, check_user_update, role_audit_diff,
)


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

def _tenant_of(tdb, ctx) -> TenantData:
    """The context's tenant on the handle the route writes to."""
    return TenantData.for_context(tdb, ctx)


def identity_check_unavailable() -> HTTPException:
    """R0-03-C01 F-03: the installation could not be fully checked — refuse, write nothing."""
    return HTTPException(status_code=503, detail={
        "error_code": ERROR_IDENTITY_CHECK_UNAVAILABLE,
        "message": "The email cannot be checked right now; nothing was created"})


def _email_exists() -> HTTPException:
    """R0-03: the same refusal on every creation path; no company is named."""
    return HTTPException(status_code=409, detail={
        "error_code": ERROR_EMAIL_EXISTS, "message": "This email is already registered"})


router = APIRouter(tags=["auth"])
logger = logging.getLogger("beg.auth")

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

def _password_matches(password: str, password_hash) -> bool:
    try:
        return bool(password_hash) and verify_password(password, password_hash)
    except Exception:          # malformed/unknown hash: never a match
        return False


# Auth routes
@router.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    # R0-03 (AUTH-01 F-03): the email is normalized, and an email held by more
    # than one User never logs into whichever one the database returns first.
    # The login registry is the global users collection in every mode.
    email = normalize_email(req.email)
    candidates = [u for u in await db.users.find(email_match_filter(email), {"_id": 0}).to_list(50)
                  if email and normalize_email(u.get("email")) == email]
    if len(candidates) > 1:
        # R0-04 (AUTH-01 F-08): every refused duplicate login also leaves a durable,
        # privacy-preserving security event (keyed email ref, no email/password).
        await auth_events.record(
            db, auth_events.LOGIN_AMBIGUOUS, ip=client_ip(request),
            subject=auth_events.keyed_ref(email), detail={"candidates": len(candidates)})
        # Only a caller who knows a password of one of them learns about the
        # duplicate; anyone else gets the ordinary 401.
        if not any(_password_matches(req.password, u.get("password_hash")) for u in candidates):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        for org_id in sorted({u.get("org_id") for u in candidates if u.get("org_id")}):
            await audit_user_change(
                db, tenant_id=org_id, actor_id="auth.login", actor_type="system",
                action="auth.login_refused", target_id=None, result="denied",
                error_code=ERROR_DUPLICATE_IDENTITY, tool_or_endpoint="POST /api/auth/login",
                reason="login refused: the email belongs to %d users" % len(candidates))
        raise HTTPException(status_code=409, detail={
            "error_code": ERROR_DUPLICATE_IDENTITY,
            "message": "This account cannot sign in until its identity is resolved. "
                       "Contact your administrator."})
    user = candidates[0] if candidates else None
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    # AUTH-01 C01 (F-02): the token carries the user's auth_version; a password
    # reset or owner recovery increments it, which ends every older session.
    token = create_token({"user_id": user["id"], "org_id": user["org_id"], "role": user["role"],
                          "av": int(user.get("auth_version", 0) or 0)})
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
    tenant = _tenant(user)
    # Fetch fresh user data with password hash
    # W0-03E-A2B: the session's own record — (id, tenant), never the id alone.
    db_user = await tenant.users.find_one({"id": user["id"], "org_id": user["org_id"]}, {"_id": 0})
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify current password
    if not verify_password(data.current_password, db_user["password_hash"]):
        # Log failed attempt (security event)
        await log_audit(user["org_id"], user["id"], user["email"], "password_change_failed", "auth", 
                       changes={"reason": "Invalid current password"})
        # R0-03-C01 F-04: canonical AuditEvent too — never the password or the hash.
        await audit_user_change(db, tenant_id=user["org_id"], actor_id=user["id"],
                                action="user.own_password_change", target_id=user["id"],
                                result="denied", error_code="INVALID_CURRENT_PASSWORD",
                                reason="own password change refused: current password did not match",
                                tool_or_endpoint="POST /api/auth/change-password")
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
    await tenant.users.update_one(
        {"id": user["id"], "org_id": user["org_id"]},
        {"$set": {
            "password_hash": new_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "password_changed_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Log success (security event)
    await log_audit(user["org_id"], user["id"], user["email"], "password_changed", "auth")
    await audit_user_change(db, tenant_id=user["org_id"], actor_id=user["id"],
                            action="user.own_password_change", target_id=user["id"],
                            reason="own password changed (no hash recorded)",
                            tool_or_endpoint="POST /api/auth/change-password")
    
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# AUTH-01 — Forgot Password / Reset Password (no session)
# ══════════════════════════════════════════════════════════════════════════════

class ForgotPasswordRequest(BaseModel):
    email: str = Field(max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(max_length=password_reset.TOKEN_MAX_LENGTH)
    new_password: str = Field(max_length=256)


# AUTH-01 C01 (F-04): shared per-IP limits (MongoDB counters, all workers).
# The per-email forgot limit lives in password_reset.process_forgot_request.
FORGOT_IP_LIMIT, RESET_IP_LIMIT, IP_WINDOW_SECONDS = 10, 20, 900


def _too_many_requests():
    return HTTPException(status_code=429, detail="Too many requests. Try again later.")


async def _ip_allowed(scope: str, ip: str, limit: int) -> bool:
    hit = await rate_limit.hit(db, scope, ip, limit, IP_WINDOW_SECONDS)
    if not hit.allowed and hit.first_rejection:
        await auth_events.record(db, auth_events.RATE_LIMITED_IP, ip=ip, detail={"scope": scope})
    return hit.allowed


@router.post("/auth/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, request: Request,
                          background_tasks: BackgroundTasks):
    """Always the same answer — it never says whether the account exists.

    Before the response this does the SAME work for every email (F-05): the
    shared per-IP limit and scheduling one background task. Everything that
    depends on the account — the per-email limit, the lookup, the token, the
    audit and the e-mail — runs after the response in
    ``password_reset.process_forgot_request``.
    """
    ip = client_ip(request)
    if not await _ip_allowed("forgot_ip", ip, FORGOT_IP_LIMIT):
        raise _too_many_requests()
    background_tasks.add_task(password_reset.process_forgot_request, db, data.email, ip)
    return {"ok": True, "message": password_reset.GENERIC_REQUEST_MESSAGE}


@router.post("/auth/reset-password")
async def reset_password(data: ResetPasswordRequest, request: Request):
    """Set a new password with a one-time token from the e-mailed link.

    The password policy is checked first (same rules as change-password); then
    an unknown, expired, used or superseded token, or a disabled user, all get
    one generic 400. 400 rather than 401: the frontend treats 401 as "session
    expired" and would leave the page.
    """
    ip = client_ip(request)
    if not await _ip_allowed("reset_ip", ip, RESET_IP_LIMIT):
        raise _too_many_requests()
    is_valid, error_msg = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    try:
        await password_reset.reset_password(db, data.token, hash_password(data.new_password),
                                            requested_ip=ip)
    except password_reset.ResetFailed:
        raise HTTPException(status_code=400, detail={
            "error_code": "RESET_TOKEN_INVALID",
            "message": password_reset.GENERIC_RESET_FAILURE})
    except password_reset.ResetNotCompleted:
        # F-01: the transaction was aborted — the password and the link are unchanged.
        raise HTTPException(status_code=503, detail={
            "error_code": "RESET_NOT_COMPLETED",
            "message": password_reset.RESET_NOT_COMPLETED_MESSAGE})
    return {"ok": True}


# Organization routes
@router.get("/organization")
async def get_organization(user: dict = Depends(get_current_user)):
    org = await _tenant(user).own_organization({"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org

@router.put("/organization")
async def update_organization(data: OrgUpdate, user: dict = Depends(require_admin)):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    tenant = _tenant(user)
    await tenant.update_own_organization({"$set": update})
    await log_audit(user["org_id"], user["id"], user["email"], "updated", "organization", user["org_id"], update)
    return await tenant.own_organization({"_id": 0})

# User routes
@router.get("/users")
async def list_users(user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    return await tenant.users.find({"org_id": user["org_id"]}, {"_id": 0, "password_hash": 0}).to_list(1000)

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
    # R0-03 (AUD-025): nobody creates a user with a role above their own.
    await check_user_update(_tenant_of(tdb, ctx), actor=user, target={"id": None, "role": None},
                            update={"role": data.role}, mode=ctx.mode, tenant_id=ctx.tenant_id)
    # R0-03 (Р6): one email = one User in the whole installation, normalized.
    email = normalize_email(data.email)
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    # R0-03-C02: the whole installation in EVERY mode, fail closed around the full
    # enumeration AND the search. off/shadow read tenant_registry directly (as
    # onboarding does) — no resolver, no Permission Service (W0-02 PR-05). The
    # write still goes to the mode-selected database (tdb).
    try:
        if ctx.mode == MODE_ENFORCE:
            databases = await installation_databases(db, ctx.mode) + [tdb]
        else:
            from app.tenancy import registry as tenant_registry_mod
            databases = await installation_databases_for(db, tenant_registry_mod.system_db) + [tdb]
        matches = await users_with_email(databases, email)
    except IdentityCheckUnavailable:
        raise identity_check_unavailable()

    def _public(u):
        return {k: v for k, v in u.items() if k not in ("password_hash", "_id")}

    def _new_user_doc():
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "email": email,
            "password_hash": hash_password(data.password),
            "first_name": data.first_name,
            "last_name": data.last_name,
            "role": data.role,
            "phone": data.phone,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

    # AUTH-01 F-03 is covered by the R0-03 check above (``matches``: the whole
    # installation, normalized, fail closed); R0-04 keeps that single check.
    if ctx.mode != MODE_ENFORCE:
        # ---- legacy path (off / shadow): unchanged business behavior ----------
        await enforce_limit(org_id, "users", db_handle=tdb)
        if matches:
            raise _email_exists()
        new_user = _new_user_doc()
        await tdb.users.insert_one(new_user)
        await log_audit(org_id, user["id"], user["email"], "created", "user", new_user["id"],
                        {"email": email, "role": data.role}, db_handle=tdb)
        if ctx.mode == MODE_SHADOW:
            # Shadow: the legacy write is the truth and stays done. The sync is
            # observed only — a failure is reported, never turned into an
            # error response or a pretended success.
            await shadow_sync(ctx, tdb, "user.create", new_user["id"],
                              lambda: grant_company_role(ctx, new_user["id"], data.role, actor_id=user["id"]))
        return _public(new_user)

    # ---- enforce: recoverable idempotent workflow (PR-05) ---------------------
    # The only match that may continue is this tenant's own user of an
    # interrupted attempt (checked against the workflow below); any other
    # holder of the email anywhere in the installation refuses the request.
    own = [m for m in matches if m["_database"] == tdb.name and m.get("org_id") == org_id]
    if len(matches) > len(own[:1]):
        raise _email_exists()
    existing = None
    if own:
        existing = await tdb.users.find_one({"id": own[0]["id"], "org_id": org_id}, {"_id": 0})
    try:
        wf = await RecoverableWrite(
            tdb, tenant_id=ctx.tenant_id, action="user.create",
            key=f"user.create:{org_id}:{email}",
            fingerprint=fingerprint_without(data.model_dump(), "password")).begin()
    except HTTPException as exc:
        if exc.status_code == 409 and existing is not None:
            # a DIFFERENT request for an email that already exists
            raise _email_exists()
        raise
    if existing is not None and not (wf.resumed and wf.step_refs.get("business") == existing["id"]):
        # Legacy contract kept: a new request for an existing email is refused.
        # (Only the retry of an interrupted attempt may continue with its user.)
        if not wf.already_completed and not wf.resumed:
            await wf.fail(ERROR_EMAIL_EXISTS)
        raise _email_exists()
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
            {"email": email, "role": data.role}, db_handle=tdb))
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
    # PR-05-R1: the client's operation id. Absent => every request is a NEW command.
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    user = ctx.user
    org_id = ctx.org_id
    tdb = await ctx.db()
    tenant = TenantData.for_context(tdb, ctx)       # W0-03E-A1: every users read below
    target = await tenant.users.get(user_id)
    if not ctx.owns(target):
        raise HTTPException(status_code=404, detail="User not found")   # foreign == missing
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    # R0-03 (AUD-025): no own role change, no grant above one's own rank, only an
    # Owner touches an Owner, the last active Owner stays — refused before any write.
    await check_user_update(tenant, actor=user, target=target, update=update,
                            mode=ctx.mode, tenant_id=ctx.tenant_id)
    diff = role_audit_diff(target, update)
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    async def _audit_change():
        if diff["after"]:
            await audit_user_change(tdb, tenant_id=org_id, actor_id=user["id"], action="user.role_status_changed",
                                    target_id=user_id, diff=diff, reason="user role/status changed",
                                    tool_or_endpoint="PUT /api/users/{user_id}")

    async def _business():
        await tenant.users.update_one({"id": user_id}, {"$set": update})
        return user_id

    if ctx.mode != MODE_ENFORCE or "role" not in update:
        # legacy behavior (off/shadow), or an enforce update without a role
        # change (no assignment to sync; single business write + legacy audit).
        await _business()
        await log_audit(org_id, user["id"], user["email"], "updated", "user", user_id, update, db_handle=tdb)
        await _audit_change()
        if ctx.mode == MODE_SHADOW and "role" in update:
            await shadow_sync(ctx, tdb, "user.update", user_id,
                              lambda: grant_company_role(ctx, user_id, update["role"], actor_id=user["id"]))
        return await tenant.users.get(user_id, {"_id": 0, "password_hash": 0})

    # ---- enforce + role change: authoritative assignment FIRST (PR-05) -------
    # If the business write then fails, users.role is stale but the
    # authoritative assignment already carries the NEW role: no stale broad
    # grant can survive. The failed state is recorded; the same request retried
    # finishes the remaining steps.
    # PR-05-R1: the operation IDENTITY is the client's Idempotency-Key (or a
    # fresh id when none is sent) — never the payload fingerprint. The
    # fingerprint stays only to detect a CONFLICT:
    #   same id + same payload      -> retry / replay, no second effect
    #   same id + different payload -> 409 IDEMPOTENCY_CONFLICT, no write
    #   new  id + same payload      -> a NEW command that must execute
    # Completed history is kept; identity is not a timestamp.
    op_id = (idempotency_key or "").strip()[:200] or str(uuid.uuid4())
    wf = await RecoverableWrite(
        tdb, tenant_id=ctx.tenant_id, action="user.update",
        key=f"user.update:{user_id}:{op_id}",
        fingerprint=fingerprint_without(update, "updated_at")).begin()
    if wf.already_completed:
        return await tenant.users.get(user_id, {"_id": 0, "password_hash": 0})
    try:
        await wf.step("sync", lambda: grant_company_role(ctx, user_id, update["role"], actor_id=user["id"]))
        await wf.step("business", _business, reference=lambda r: r)
        await wf.step("legacy_audit", lambda: log_audit(
            org_id, user["id"], user["email"], "updated", "user", user_id, update, db_handle=tdb))
        await wf.step("r0_03_audit", _audit_change)
    except HTTPException:
        raise
    except Exception as exc:
        code = ERROR_SYNC_FAILED if "sync" not in wf.steps_done else ERROR_WRITE_INCOMPLETE
        await wf.fail(code)
        raise wf.failure_response(code, exc)
    await wf.complete(user_id)
    return await tenant.users.get(user_id, {"_id": 0, "password_hash": 0})

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    tenant = TenantData.for_user(db, user)
    target = await tenant.users.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    # R0-03 (AUD-025): only an Owner deletes an Owner, never the last active one.
    mode, tenant_id = await _admin_mode_and_tenant(request, user)
    await check_owner_only(tenant, actor=user, target=target, mode=mode, tenant_id=tenant_id,
                           deleting=True)
    # W0-03E: the delete is scoped by the org it was checked against; in
    # MASTER_DATA_MODE=enforce a used or migrated identity is archived, not deleted.
    done = await guarded_identity_delete(user, request, db, collection="users", legacy_id=user_id)
    if done is not None:
        return done            # the master-data adapter already wrote its canonical AuditEvent
    await tenant.users.delete_one({"id": user_id})
    await log_audit(user["org_id"], user["id"], user["email"], "deleted", "user", user_id)
    await _audit_delete(user, target)
    return {"ok": True}


async def _admin_mode_and_tenant(request: Request, user: dict):
    """Mode and tenant for the ``require_admin`` routes (they get only the user).

    In enforce ``require_admin`` already resolved the same context; it is
    resolved again here because the rank comes from that tenant's assignments.
    """
    from app.permissions.deps import current_mode
    mode = current_mode()
    if mode != MODE_ENFORCE:
        return mode, user.get("org_id")
    from app.tenancy.guard import get_tenant_context
    return mode, (await get_tenant_context(request, user)).tenant_id


async def _audit_delete(actor: dict, target: dict):
    await audit_user_change(db, tenant_id=actor["org_id"], actor_id=actor["id"], action="user.deleted",
                            target_id=target["id"], reason="user deleted or archived",
                            diff={"before": {"role": target.get("role"),
                                             "is_active": target.get("is_active", True)},
                                  "after": {}},
                            tool_or_endpoint="DELETE /api/users/{user_id}")

# Feature flags routes (read = any user, write = platform admin)
@router.get("/feature-flags")
async def list_feature_flags(user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    return await tenant.feature_flags.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)

@router.put("/feature-flags")
async def toggle_feature_flag(data: ModuleToggle, user: dict = Depends(require_platform_admin)):
    """
    Toggle a feature flag (module) on/off for the organization.
    
    SECURITY: This endpoint is restricted to platform administrators only.
    Module configuration affects billing and feature access.
    """
    tenant = _tenant(user)
    if data.module_code == "M0":
        raise HTTPException(status_code=400, detail="Core module cannot be disabled")
    result = await tenant.feature_flags.update_one(
        {"org_id": user["org_id"], "module_code": data.module_code},
        {"$set": {"enabled": data.enabled, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": user["id"]}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Module not found")
    await log_audit(user["org_id"], user["id"], user["email"], "toggled", "feature_flag", data.module_code, {"enabled": data.enabled})
    return await tenant.feature_flags.find({"org_id": user["org_id"]}, {"_id": 0}).to_list(100)

# ══════════════════════════════════════════════════════════════════════════════
# Admin Set Password (for forgotten passwords)
# ══════════════════════════════════════════════════════════════════════════════

class AdminSetPasswordRequest(BaseModel):
    new_password: str


@router.post("/admin/set-password/{user_id}")
async def admin_set_password(user_id: str, data: AdminSetPasswordRequest, request: Request,
                             admin: dict = Depends(require_admin)):
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
    
    # Find target user in the ADMIN's own tenant
    tenant = _tenant(admin)
    target_user = await tenant.users.get(user_id, {"_id": 0})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found in your organization")
    # R0-03 (AUD-025): only an Owner resets an Owner's password.
    mode, tenant_id = await _admin_mode_and_tenant(request, admin)
    await check_owner_only(tenant, actor=admin, target=target_user, mode=mode, tenant_id=tenant_id)
    
    # Validate new password strength
    is_valid, error_msg = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    # Update password
    new_hash = hash_password(data.new_password)
    now = datetime.now(timezone.utc).isoformat()
    # W0-03E-A2C: the tenant predicate is in the WRITE filter. Proving the target
    # exists in the admin's tenant above said nothing about which tenant's user
    # `{"id": user_id}` alone would have reset once ids collide.
    await tenant.users.update_one(
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
    await audit_user_change(db, tenant_id=admin["org_id"], actor_id=admin["id"],
                            action="user.admin_password_reset", target_id=user_id,
                            reason="password set by an administrator (no hash recorded)",
                            tool_or_endpoint="POST /api/admin/set-password/{user_id}")
    
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
    tenant = _tenant(user)
    logs = await tenant.audit_logs.find(
        {"org_id": user["org_id"]}, {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    total = await tenant.audit_logs.count_documents({"org_id": user["org_id"]})
    return {"logs": logs, "total": total}
