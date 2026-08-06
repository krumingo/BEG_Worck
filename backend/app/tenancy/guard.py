"""
W0-01 Tenant Foundation — Tenant Guard.

The single place where the active tenant of a request is decided.

Iron rules (D-15 / TENANCY_MODEL.md):
  - the tenant is resolved server-side from the authenticated session;
  - a tenant_id arriving in a form, query string or JSON body is NEVER trusted;
  - cross-tenant access is denied by default;
  - every denial is explicit, never a silent empty result.

This module is additive. Existing routes keep working unchanged until
they are migrated one by one in later steps.
"""
from fastapi import Depends, HTTPException, Request
from typing import Dict, Any, Optional

from app.deps.auth import get_current_user
from app.tenancy import registry
from app.tenancy.resolver import (
    get_tenant_db,
    TenantNotFound,
    TenantNotOperational,
)


class TenantContext:
    """Everything a request needs to know about its tenant."""

    def __init__(self, tenant: Dict[str, Any], user: Dict[str, Any],
                 membership: Optional[Dict[str, Any]] = None):
        self.tenant = tenant
        self.user = user
        self.membership = membership or {}

    @property
    def tenant_id(self) -> str:
        return self.tenant["id"]

    @property
    def user_id(self) -> str:
        return self.user["id"]

    @property
    def status(self) -> str:
        return self.tenant.get("status", registry.TENANT_STATUS_ACTIVE)

    @property
    def is_operational(self) -> bool:
        return self.status in registry.OPERATIONAL_STATUSES

    async def db(self, require_operational: bool = False):
        return await get_tenant_db(self.tenant_id, require_operational=require_operational)

    def owns(self, record: Optional[Dict[str, Any]]) -> bool:
        """
        True only if the record demonstrably belongs to this tenant.

        A record with neither tenant_id nor org_id is treated as NOT owned:
        unknown ownership is denied, never assumed.
        """
        if not record:
            return False
        owner = record.get("tenant_id") or record.get("org_id")
        return owner == self.tenant_id

    def assert_owns(self, record: Optional[Dict[str, Any]], what: str = "record") -> Dict[str, Any]:
        """Raise 404 if the record is missing or belongs to another tenant.

        404 rather than 403 on purpose: a foreign id must not be confirmed
        as existing.
        """
        if not self.owns(record):
            raise HTTPException(status_code=404, detail=f"{what} not found")
        return record  # type: ignore[return-value]


async def _resolve_active_tenant_id(user: Dict[str, Any]) -> str:
    """
    Determine the active tenant for this session, server-side only.

    Order:
      1. explicit active tenant recorded on the user;
      2. the user's single membership, when there is exactly one;
      3. legacy org_id, for installations predating memberships.
    """
    explicit = user.get("active_tenant_id")
    if explicit:
        return explicit

    memberships = await registry.get_memberships_for_user(user["id"])
    if len(memberships) == 1:
        return memberships[0]["tenant_id"]
    if len(memberships) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "TENANT_NOT_SELECTED",
                "message": "User belongs to several tenants; an active tenant must be selected",
                "tenants": [m["tenant_id"] for m in memberships],
            },
        )

    legacy = user.get("org_id")
    if legacy:
        return legacy

    raise HTTPException(
        status_code=403,
        detail={"error_code": "NO_TENANT", "message": "User is not assigned to any tenant"},
    )


async def get_tenant_context(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> TenantContext:
    """
    FastAPI dependency: the guarded entry point for tenant-scoped routes.

    Any tenant_id supplied by the client is ignored and logged as a
    rejected override attempt.
    """
    tenant_id = await _resolve_active_tenant_id(user)

    claimed = request.query_params.get("tenant_id")
    if claimed and claimed != tenant_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "TENANT_OVERRIDE_DENIED",
                "message": "The active tenant is determined by the session, not by the request",
            },
        )

    tenant = await registry.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "TENANT_NOT_REGISTERED", "message": "Unknown tenant"},
        )

    membership = await registry.get_membership(user["id"], tenant_id)
    if not membership and not user.get("org_id") == tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "TENANT_ACCESS_DENIED", "message": "No access to this tenant"},
        )

    return TenantContext(tenant=tenant, user=user, membership=membership)


async def require_operational_tenant(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    """Dependency for write paths: blocks suspended / read-only tenants."""
    if not ctx.is_operational:
        raise HTTPException(
            status_code=402,
            detail={
                "error_code": "TENANT_READ_ONLY",
                "message": f"Tenant is '{ctx.status}'. Existing data stays available; new records are blocked.",
                "status": ctx.status,
            },
        )
    return ctx


async def get_tenant_db_for_request(ctx: TenantContext = Depends(get_tenant_context)):
    """Convenience dependency returning the resolved database handle."""
    try:
        return await ctx.db()
    except TenantNotFound:
        raise HTTPException(status_code=403, detail="Unknown tenant")
    except TenantNotOperational as exc:
        raise HTTPException(status_code=402, detail=str(exc))
