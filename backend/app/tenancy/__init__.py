"""
W0-01 Tenant Foundation.

Additive package: Tenant Registry, database resolver and Tenant Guard.
No existing collection is modified and no existing route is changed by
importing this package.

Canon: FLOW-050, FLOW-002, D-15.
"""
from app.tenancy.registry import (
    system_db,
    tenant_registry,
    tenant_memberships,
    tenant_role_assignments,
    get_tenant,
    get_memberships_for_user,
    CURRENT_SCHEMA_VERSION,
)
from app.tenancy.resolver import (
    get_tenant_db,
    get_tenant_db_info,
    TenantNotFound,
    TenantNotOperational,
)
from app.tenancy.guard import (
    TenantContext,
    get_tenant_context,
    require_operational_tenant,
    get_tenant_db_for_request,
)

__all__ = [
    "system_db",
    "tenant_registry",
    "tenant_memberships",
    "tenant_role_assignments",
    "get_tenant",
    "get_memberships_for_user",
    "CURRENT_SCHEMA_VERSION",
    "get_tenant_db",
    "get_tenant_db_info",
    "TenantNotFound",
    "TenantNotOperational",
    "TenantContext",
    "get_tenant_context",
    "require_operational_tenant",
    "get_tenant_db_for_request",
]
