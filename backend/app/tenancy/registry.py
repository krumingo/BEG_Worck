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


# ---------------------------------------------------------------------------
# W0-02 — RoleAssignment as authoritative source of truth (FLOW-002).
# These operate on the SAME tenant_role_assignments collection W0-01 created,
# now carrying the full authoritative shape (role_id, module, permissions,
# valid_from/valid_to, max_amount, created_by/approved_by, revoked_at/by).
# ---------------------------------------------------------------------------

async def list_role_assignments(user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """ALL assignments for (user, tenant), any status.

    The Permission Service needs revoked/expired records too, so it can report
    ASSIGNMENT_REVOKED / ASSIGNMENT_EXPIRED instead of a bare NO_ASSIGNMENT.
    """
    return await tenant_role_assignments.find(
        {"user_id": user_id, "tenant_id": tenant_id}, {"_id": 0}
    ).to_list(200)


async def get_role_assignment(assignment_id: str) -> Optional[Dict[str, Any]]:
    return await tenant_role_assignments.find_one({"id": assignment_id}, {"_id": 0})


# The logical identity of an assignment (backed by the non-partial unique index
# `uniq_assignment`). Two documents can never share it, whatever their status.
ASSIGNMENT_KEY_FIELDS = ("user_id", "tenant_id", "role_id", "scope_type", "scope_id", "module")


def assignment_key(a: Dict[str, Any]) -> Dict[str, Any]:
    """Logical unique key of an assignment document (None-normalized)."""
    return {f: a.get(f) for f in ASSIGNMENT_KEY_FIELDS}


async def find_role_assignment_by_key(user_id: str, tenant_id: str, role_id: str,
                                      scope_type: str, scope_id: Optional[str] = None,
                                      module: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The ONE document (any status) that owns this logical key, or None.

    PR-02: identity is the logical key, never a freshly generated id. A record
    migrated under an older id keeps that id for its whole life.
    """
    return await tenant_role_assignments.find_one(
        {"user_id": user_id, "tenant_id": tenant_id, "role_id": role_id,
         "scope_type": scope_type, "scope_id": scope_id, "module": module},
        {"_id": 0},
    )


class ConcurrentAssignmentChange(RuntimeError):
    """An optimistic (revision-guarded) update lost a race; caller must re-read."""


async def upsert_role_assignment(a: Dict[str, Any]) -> Dict[str, Any]:
    """Create or replace an assignment by its stable id. Sets updated_at."""
    if not a.get("id"):
        raise ValueError("RoleAssignment requires a stable 'id'")
    a = {**a, "updated_at": _now()}
    a.setdefault("created_at", a["updated_at"])
    a.setdefault("status", "active")
    a.pop("revision", None)
    await tenant_role_assignments.update_one(
        {"id": a["id"]}, {"$set": a, "$setOnInsert": {"revision": 1}}, upsert=True)
    return await get_role_assignment(a["id"]) or a


async def insert_role_assignment(a: Dict[str, Any]) -> Dict[str, Any]:
    """Create-only. Raises the driver's DuplicateKeyError when the logical key
    (or id) already exists — the caller must then read the real record."""
    if not a.get("id"):
        raise ValueError("RoleAssignment requires a stable 'id'")
    a = {**a, "updated_at": _now()}
    a.setdefault("created_at", a["updated_at"])
    a.setdefault("status", "active")
    a.setdefault("revision", 1)
    await tenant_role_assignments.insert_one(dict(a))
    a.pop("_id", None)
    return a


async def patch_role_assignment(assignment_id: str, patch: Dict[str, Any], *,
                                expected_revision: Optional[int],
                                unset: Optional[List[str]] = None) -> Dict[str, Any]:
    """Revision-guarded partial update. Only the given fields change; revision
    is bumped. Lost race -> ConcurrentAssignmentChange (nothing written)."""
    query: Dict[str, Any] = {"id": assignment_id}
    if expected_revision is None:
        query["revision"] = {"$exists": False}
    else:
        query["revision"] = expected_revision
    update: Dict[str, Any] = {"$set": {**patch, "updated_at": _now()}, "$inc": {"revision": 1}}
    if unset:
        update["$unset"] = {f: "" for f in unset}
    res = await tenant_role_assignments.update_one(query, update)
    if res.matched_count != 1:
        raise ConcurrentAssignmentChange(assignment_id)
    return await get_role_assignment(assignment_id)


async def revoke_role_assignment(assignment_id: str, *, by: str, reason: str) -> Optional[Dict[str, Any]]:
    """Revoke = status change + timestamp. Never a hard delete (CLAUDE.md §16)."""
    patch = {
        "status": "revoked",
        "revoked_at": _now(),
        "revoked_by": by,
        "revoke_reason": reason,
        "updated_at": _now(),
    }
    await tenant_role_assignments.update_one({"id": assignment_id}, {"$set": patch, "$inc": {"revision": 1}})
    return await get_role_assignment(assignment_id)


async def ensure_permission_indexes(collection=None) -> None:
    """Indexes for the authoritative RoleAssignment collection (W0-02 §5).

    `collection` lets the bootstrap script build them on ITS guarded handle;
    default is the registry's own collection.
    """
    coll = tenant_role_assignments if collection is None else collection
    # No two identical grants (non-partial: any status).
    await coll.create_index(
        [("user_id", 1), ("tenant_id", 1), ("role_id", 1),
         ("scope_type", 1), ("scope_id", 1), ("module", 1)],
        unique=True, name="uniq_assignment",
    )
    # Hot path of has_permission(): all assignments of a user in a tenant.
    await coll.create_index(
        [("user_id", 1), ("tenant_id", 1), ("status", 1)], name="lookup_active",
    )
    # Admin views.
    await coll.create_index(
        [("tenant_id", 1), ("role_id", 1)], name="by_role",
    )
    await coll.create_index(
        [("tenant_id", 1), ("scope_type", 1), ("scope_id", 1)], name="by_scope",
    )
    # NOTE: no TTL index — valid_to is logical validity, not deletion.
