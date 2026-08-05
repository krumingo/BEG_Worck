"""
W0-01 Tenant Foundation — Database resolver.

Maps tenant_id -> that tenant's MongoDB database, using ONLY the
Tenant Registry. Connections are cached per database name.

Canon: D-15 — database-per-tenant, server-side resolution.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Dict
import os
from pathlib import Path
from dotenv import load_dotenv

from app.tenancy import registry

_root = Path(__file__).parent.parent.parent
load_dotenv(_root / '.env')

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')

_client = AsyncIOMotorClient(MONGO_URL)
_db_cache: Dict[str, AsyncIOMotorDatabase] = {}


class TenantNotFound(Exception):
    """Registry has no record for this tenant id."""


class TenantNotOperational(Exception):
    """Tenant exists but its subscription state forbids this operation."""


def _get_db_by_name(db_name: str) -> AsyncIOMotorDatabase:
    if db_name not in _db_cache:
        _db_cache[db_name] = _client[db_name]
    return _db_cache[db_name]


async def get_tenant_db(tenant_id: str, require_operational: bool = False) -> AsyncIOMotorDatabase:
    """
    Return the database handle for a tenant.

    require_operational=True is used by write paths: a suspended or
    read-only tenant can still be read and exported, but not written to.
    """
    tenant = await registry.get_tenant(tenant_id)
    if not tenant:
        raise TenantNotFound(f"Unknown tenant: {tenant_id}")

    if require_operational and tenant.get("status") not in registry.OPERATIONAL_STATUSES:
        raise TenantNotOperational(
            f"Tenant {tenant_id} is '{tenant.get('status')}' and cannot accept new records"
        )

    return _get_db_by_name(registry.resolve_database_name(tenant))


async def get_tenant_db_info(tenant_id: str) -> dict:
    """Diagnostics helper: which database a tenant resolves to."""
    tenant = await registry.get_tenant(tenant_id)
    if not tenant:
        raise TenantNotFound(f"Unknown tenant: {tenant_id}")
    return {
        "tenant_id": tenant_id,
        "name": tenant.get("name"),
        "database_name": registry.resolve_database_name(tenant),
        "status": tenant.get("status"),
        "schema_version": tenant.get("schema_version"),
    }
