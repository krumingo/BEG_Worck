"""
W0-02 — Keep authoritative RoleAssignments in sync with user/role/membership
changes, so there are never two diverging sources of truth.

Used by the migrated write paths (create/update user, add/remove project member).
All of these run only when PERMISSION_SERVICE_MODE != 'off' (see the routes), so
a default deploy is behaviorally unchanged.

Revocation is a status change (no hard delete). Because the Permission Service
reads assignments fresh on every request, a revoke here takes effect on the
very next request, even with an unexpired JWT.
"""
from datetime import datetime, timezone

from app.tenancy import registry
from app.permissions.catalog import (
    LEGACY_ROLE_MAP, PROJECT_MEMBER_ACTIONS, PROJECT_MANAGER_ACTIONS,
)
from app.permissions.audit_hooks import audit_permission_change


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _CompatCtx:
    """Minimal context for non-migrated write paths that still need to keep
    assignments in sync. tenant_id is resolved from the session (active tenant,
    else legacy org_id — a lookup aid, not a rule that tenant_id == org_id)."""
    def __init__(self, user: dict):
        self.user = user
        self.user_id = user["id"]
        self.tenant_id = user.get("active_tenant_id") or user.get("org_id")

    async def db(self):
        from app.db import db as global_db
        return global_db


def compat_ctx(user: dict) -> "_CompatCtx":
    return _CompatCtx(user)


def company_assignment_id(user_id: str, tenant_id: str, role_id: str) -> str:
    return f"ra_{user_id}_{tenant_id}_{role_id}_company"


def project_assignment_id(user_id: str, tenant_id: str, project_id: str) -> str:
    return f"ra_{user_id}_{tenant_id}_proj_{project_id}"


async def grant_company_role(ctx, user_id: str, legacy_role: str, *, actor_id: str):
    """Set the user's company-scope assignment to their (mapped) role.

    Revokes any OTHER active company assignment first, so a role CHANGE does not
    leave a stale broad grant active (the "at least one assignment allows" rule
    would otherwise keep the old access). Emits granted/updated/revoked audit.
    """
    role_id = LEGACY_ROLE_MAP.get(legacy_role, legacy_role)
    tid = ctx.tenant_id

    for a in await registry.list_role_assignments(user_id, tid):
        if (a.get("scope_type") == "company" and a.get("status") == "active"
                and a.get("role_id") not in (role_id, None)):
            rev = await registry.revoke_role_assignment(
                a["id"], by=actor_id, reason=f"company role changed to {role_id}")
            await audit_permission_change(ctx, "revoked", rev or a, before=a, after=rev)

    aid = company_assignment_id(user_id, tid, role_id)
    before = await registry.get_role_assignment(aid)
    assignment = {
        "id": aid, "user_id": user_id, "tenant_id": tid, "role_id": role_id,
        "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
        "max_amount": None, "valid_from": before.get("valid_from") if before else _now(),
        "valid_to": None, "status": "active", "created_by": actor_id, "approved_by": actor_id,
    }
    stored = await registry.upsert_role_assignment(assignment)
    await audit_permission_change(
        ctx, "updated" if before else "granted", stored,
        before=before, after=stored, reason=f"company role {role_id}")
    return stored


async def sync_project_membership(ctx, user_id: str, member_role_id: str,
                                  project_id: str, role_in_project: str, active: bool,
                                  *, actor_id: str):
    """Mirror one project_team membership into a project-scope assignment.

    active member  -> project assignment with budget.read (SiteManager: +write);
    inactive/removed -> the assignment is revoked (next request loses access).
    """
    tid = ctx.tenant_id
    aid = project_assignment_id(user_id, tid, project_id)
    before = await registry.get_role_assignment(aid)

    if not active:
        if before and before.get("status") == "active":
            rev = await registry.revoke_role_assignment(
                aid, by=actor_id, reason=f"removed from project {project_id}")
            await audit_permission_change(ctx, "revoked", rev or before, before=before, after=rev)
        return None

    perms = list(PROJECT_MANAGER_ACTIONS if role_in_project == "SiteManager"
                 else PROJECT_MEMBER_ACTIONS)
    assignment = {
        "id": aid, "user_id": user_id, "tenant_id": tid,
        "role_id": member_role_id, "scope_type": "project", "scope_id": project_id,
        "module": None, "permissions": perms, "max_amount": None,
        "valid_from": before.get("valid_from") if before else _now(), "valid_to": None,
        "status": "active", "created_by": actor_id, "approved_by": actor_id,
        "migrated_from": "project_team",
    }
    stored = await registry.upsert_role_assignment(assignment)
    await audit_permission_change(
        ctx, "updated" if before else "granted", stored,
        before=before, after=stored, reason=f"project {project_id} membership ({role_in_project})")
    return stored
