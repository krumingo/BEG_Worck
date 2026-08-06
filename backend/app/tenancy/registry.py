"""
W0-01 Tenant Foundation — Tenant Registry.

Central map of all tenants. Lives in a SEPARATE system database
(BEG_SYSTEM_DB, default 'begwork_system'), never inside a tenant's
operational database.

Canon: FLOW-050, D-15 (TENANCY_MODEL.md).

Read-only in this phase: nothing here mutates tenant business data.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import os
from pathlib import Path
from dotenv import load_dotenv

_root = Path(__file__).parent.parent.parent
load_dotenv(_root / '.env')

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
SYSTEM_DB_NAME = os.environ.get('BEG_SYSTEM_DB', 'begwork_system')

# Database of the very first tenant (the existing installation).
LEGACY_DB_NAME = os.environ.get('DB_NAME', 'begwork')

_system_client = AsyncIOMotorClient(MONGO_URL)
system_db = _system_client[SYSTEM_DB_NAME]

tenant_registry = system_db.tenant_registry
tenant_memberships = system_db.tenant_memberships
tenant_role_assignments = system_db.tenant_role_assignments

# Tenant lifecycle states (FLOW-050).
TENANT_STATUS_ACTIVE = "active"
TENANT_STATUS_GRACE = "grace"
TENANT_STATUS_RESTRICTED = "restricted"
TENANT_STATUS_SUSPENDED = "suspended"
TENANT_STATUS_READ_ONLY = "read_only"

# Statuses that still allow normal operational work.
OPERATIONAL_STATUSES = {TENANT_STATUS_ACTIVE, TENANT_STATUS_GRACE, TENANT_STATUS_RESTRICTED}

CURRENT_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_tenant(tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return the registry record for a tenant, or None."""
    return await tenant_registry.find_one({"id": tenant_id}, {"_id": 0})


async def get_tenant_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    return await tenant_registry.find_one({"slug": slug}, {"_id": 0})


async def list_tenants(include_inactive: bool = True) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if not include_inactive:
        query["status"] = TENANT_STATUS_ACTIVE
    return await tenant_registry.find(query, {"_id": 0}).to_list(1000)


async def get_memberships_for_user(user_id: str) -> List[Dict[str, Any]]:
    """All tenants this user belongs to (active memberships only)."""
    return await tenant_memberships.find(
        {"user_id": user_id, "status": "active"}, {"_id": 0}
    ).to_list(100)


async def get_membership(user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    return await tenant_memberships.find_one(
        {"user_id": user_id, "tenant_id": tenant_id, "status": "active"}, {"_id": 0}
    )


async def get_role_assignments(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """RoleAssignment records (FLOW-002) scoped to one tenant."""
    return await tenant_role_assignments.find(
        {"user_id": user_id, "tenant_id": tenant_id, "status": "active"}, {"_id": 0}
    ).to_list(100)


def resolve_database_name(tenant: Dict[str, Any]) -> str:
    """
    The database name is taken ONLY from the registry record.
    It is never derived from user input or request payloads.
    """
    db_name = tenant.get("database_name")
    if not db_name:
        raise ValueError(f"Tenant {tenant.get('id')} has no database_name in registry")
    return db_name


async def registry_is_initialized() -> bool:
    return await tenant_registry.count_documents({}) > 0
