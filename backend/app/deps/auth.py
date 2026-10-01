"""
Authentication and authorization dependencies.
"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timezone, timedelta
from typing import List
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
_root = Path(__file__).parent.parent
load_dotenv(_root / '.env')

from app.db import db

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-key')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

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

async def require_admin(request: Request, user: dict = Depends(get_current_user)):
    """Admin/Owner gate.

    W0-02: flag-aware wrapper. In 'off'/'shadow' the behavior is IDENTICAL to
    before (legacy role string). In 'enforce' the decision comes only from the
    Permission Service via the Tenant Guard — no fallback to user["role"].
    """
    # Import inside the function to avoid an import cycle with app.permissions.
    from app.permissions.deps import current_mode, MODE_ENFORCE, require_legacy_data_path
    if current_mode() == MODE_ENFORCE:
        from app.tenancy.guard import get_tenant_context
        from app.permissions.service import evaluate_permission
        ctx = await get_tenant_context(request, user)
        decision = await evaluate_permission(ctx, "admin.access")
        if not decision.allowed:
            raise HTTPException(status_code=403, detail="Admin access required")
        # W0-02 PR-04 §5: every require_admin route still reads/writes through
        # the legacy GLOBAL handle with user["org_id"]. That is only correct
        # when the active tenant's database IS that handle and the identity's
        # legacy org is that tenant. Anything else would authorize against one
        # tenant and touch another tenant's data -> refuse (409) before any
        # write instead of silently activating an unsupported scenario.
        await require_legacy_data_path(ctx, db)
        if user.get("org_id") != ctx.org_id:
            raise HTTPException(status_code=409, detail={
                "error_code": "TENANT_DATA_PATH_NOT_MIGRATED",
                "message": "This admin operation is not yet available when the active tenant "
                           "differs from the identity's legacy organization"})
        return user
    # off / shadow — unchanged legacy behavior.
    if user["role"] not in ["Admin", "Owner"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ---------------------------------------------------------------------------
# W0-03E-A2 — project access from the tenant-bound authorization relation.
#
# These three helpers are THE project authorization gate of the legacy routes.
# Until A2 they read ``project_team`` by id pair alone, so in one shared legacy
# database a row written by tenant B authorized tenant A's user on A's
# same-id project (the defect the A1 review reproduced). They now go through
# ``app.tenancy.project_team``, which carries the tenant predicate on the row
# itself: an ownerless legacy row and another tenant's row both grant zero.
#
# The tenant is the session user's own ``org_id`` — the document
# ``get_current_user`` loaded server-side from the database by the verified JWT
# user id (``TenantData.for_user``), never a path, query, form or body value.
# The signatures are unchanged, so every existing caller becomes tenant-bound
# without a route-local membership query of its own.
# ---------------------------------------------------------------------------

def _team_tenant(user: dict):
    from app.tenancy.project_team import tenant_for
    return tenant_for(db, user)


async def get_user_project_ids(user_id: str, user: dict = None) -> List[str]:
    """Project ids of the user's active memberships, inside ONE tenant.

    ``user`` is the session document that fixes the tenant; without it the
    tenant cannot be resolved server-side, so the answer is empty — fail
    closed, never a cross-tenant list.

    ``user_id`` must be the id. Two callers in ``work_logs.py`` pass the whole
    session dict instead (``get_user_project_ids(user)``); that already
    returned an empty list before A2, because the dict never matched a
    ``user_id`` field, so those routes deny non-admins today. A2 keeps that
    result exactly: widening it would grant access that the system does not
    grant now, which is a business decision, not a tenant-provenance fix. It is
    recorded as debt in docs/architecture/W0-03E_LEGACY_MIGRATION.md §15.
    """
    if not isinstance(user_id, str) or not user_id:
        return []
    if not user or not user.get("org_id"):
        return []
    from app.tenancy import project_team
    return await project_team.assigned_project_ids(_team_tenant(user), user_id)


async def can_access_project(user: dict, project_id: str) -> bool:
    """May this user see this project? Admin/Owner tenant-wide, else membership."""
    if user["role"] in ["Admin", "Owner"]:
        return True
    from app.tenancy import project_team
    return await project_team.is_member(_team_tenant(user), user["id"], project_id)


async def can_manage_project(user: dict, project_id: str) -> bool:
    """May this user manage this project? Admin/Owner, or a SiteManager membership."""
    if user["role"] in ["Admin", "Owner"]:
        return True
    if user["role"] == "SiteManager":
        from app.tenancy import project_team
        return await project_team.is_member(_team_tenant(user), user["id"], project_id,
                                            project_team.ROLE_SITE_MANAGER)
    return False


async def require_platform_admin(user: dict = Depends(get_current_user)):
    """
    Require platform admin access for system management routes.
    
    Platform admins can access:
    - /api/billing/* (except public endpoints)
    - /api/mobile-settings/*
    - /api/modules/*
    - /api/audit-logs
    
    Regular org Admin/Owner users do NOT have platform admin access by default.
    The is_platform_admin flag must be explicitly set to True.
    """
    if not user.get("is_platform_admin", False):
        raise HTTPException(
            status_code=403, 
            detail={
                "error_code": "PLATFORM_ADMIN_REQUIRED",
                "message": "Platform administrator access required"
            }
        )
    return user
