"""
W0-02 — Keep authoritative RoleAssignments in sync with user/role/membership
changes, so there are never two diverging sources of truth.

Used by the migrated write paths (create/update user, add/remove project member).
All of these run only when PERMISSION_SERVICE_MODE != 'off' (see the routes), so
a default deploy is behaviorally unchanged.

Revocation is a status change (no hard delete). Because the Permission Service
reads assignments fresh on every request, a revoke here takes effect on the
very next request, even with an unexpired JWT.

PR-02 identity rules
--------------------
* The identity of an assignment is its LOGICAL KEY
  (user_id, tenant_id, role_id, scope_type, scope_id, module) — the same key
  the non-partial unique index `uniq_assignment` enforces. The helper that
  generates a NEW id is used only when no document owns that key yet; a
  migrated record keeps its old id for its whole life.
* Repeating the same command is a no-op (no second document, no new audit
  event); a real change is written under the existing id with a revision
  guard and audited with before/after.
* A role change revokes ONLY the company assignment this sync owns
  (`migrated_from == "users.role"` or `sync_source == "users.role"`), never an
  independent manual grant of a multi-role user.
* A DuplicateKey on insert is never a silent success: the real existing
  record is read back and must match the intended operation.
"""
from datetime import datetime, timezone

from app.tenancy import registry
from app.tenancy.registry import ConcurrentAssignmentChange
from app.permissions.catalog import (
    LEGACY_ROLE_MAP, PROJECT_MEMBER_ACTIONS, PROJECT_MANAGER_ACTIONS,
)
from app.permissions.audit_hooks import audit_permission_change, _audit_db

SYNC_SOURCE_USER_ROLE = "users.role"       # company assignment mirrors users.role
SYNC_SOURCE_PROJECT_TEAM = "project_team"  # project assignment mirrors project_team


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_duplicate_key(exc: Exception) -> bool:
    return type(exc).__name__ == "DuplicateKeyError" or "duplicate key" in str(exc).lower()


# Backwards-compatible aliases. The canonical off/shadow context now lives in
# app.tenancy.guard (LegacyCompatContext) so the dependency, the sync helpers
# and the audit hooks share ONE definition of "legacy data path".
from app.tenancy.guard import LegacyCompatContext as _CompatCtx  # noqa: E402


def compat_ctx(user: dict) -> "_CompatCtx":
    return _CompatCtx(user)


class SyncTenantUnresolved(RuntimeError):
    """The tenant that owns the legacy business write cannot be determined."""


def sync_tenant_id(ctx) -> str:
    """The tenant that OWNS the business write this sync mirrors.

    PR-06 (tenant boundary). In off/shadow the business write happens on the
    LEGACY data path under ``user["org_id"]``, while ``ctx.tenant_id`` of a
    LegacyCompatContext is only a lookup aid for the shadow EVALUATION and is
    the selected ``active_tenant_id`` when the session has one. Mirroring under
    that id would write authoritative permission state into a tenant that never
    received the business write (legacy org A written, assignment created in
    active tenant B) — exactly the cross-tenant contamination PR-04 forbids.

    So the sync target is always the tenant of the business write:
      * off/shadow (``enforced`` False) -> ``org_id``, the org the legacy write
        used;
      * enforce (resolved TenantContext) -> ``tenant_id``, which IS where the
        business write went (that tenant's own database).

    Shadow evaluation is untouched and keeps comparing the active tenant; only
    the authoritative WRITE is pinned.
    """
    if getattr(ctx, "enforced", False):
        return ctx.tenant_id
    owner = getattr(ctx, "org_id", None)
    if not owner:
        # Refuse rather than fall back to tenant_id: an unknown owner must never
        # be resolved to another tenant. In shadow this surfaces through
        # shadow_sync (logged + recorded), never as a 5xx on a done legacy write.
        raise SyncTenantUnresolved(
            "the legacy business write has no org_id; refusing to mirror a "
            "RoleAssignment into tenant_id=%r" % (getattr(ctx, "tenant_id", None),))
    return owner


def company_assignment_id(user_id: str, tenant_id: str, role_id: str) -> str:
    """Id for a NEW company assignment. Never used to look an existing one up."""
    return f"ra_{user_id}_{tenant_id}_{role_id}_company"


def project_assignment_id(user_id: str, tenant_id: str, project_id: str) -> str:
    """Id for a NEW project assignment. Never used to look an existing one up."""
    return f"ra_{user_id}_{tenant_id}_proj_{project_id}"


def _company_sync_owned(a: dict) -> bool:
    """True for the company assignment that mirrors users.role (migrated by
    W0-01/W0-02 or created by grant_company_role). Manual grants are not."""
    return a.get("scope_type") == "company" and (
        a.get("migrated_from") == SYNC_SOURCE_USER_ROLE
        or a.get("sync_source") == SYNC_SOURCE_USER_ROLE)


async def _audit_if_missing(ctx, kind: str, assignment: dict, *, before, reason: str):
    """Write the grant/update audit event for `assignment` at its current
    revision unless it already exists (retry after an audit failure must not
    lose the event, and a plain replay must not duplicate it)."""
    if before is None and not assignment.get("sync_source"):
        # A record this sync never wrote (e.g. an untouched migration mirror)
        # gets no retroactive grant event: a plain replay is a no-op.
        return None
    db = await _audit_db(ctx)
    rev = assignment.get("revision")
    existing = await db["audit_events"].find_one({
        "entity_type": "role_assignment", "entity_id": assignment.get("id"),
        "action": {"$in": ["permission.role_assignment.granted",
                            "permission.role_assignment.updated"]},
        "structured_diff.after.revision": rev,
    }, {"_id": 0, "event_id": 1})
    if existing:
        return None
    return await audit_permission_change(ctx, kind, assignment, before=before,
                                         after=assignment, reason=reason)


async def _reactivate(ctx, existing: dict, patch: dict, *, actor_id: str, reason: str):
    """Reactivate a revoked/inactive record under ITS OWN id (revision-guarded)."""
    patch = {**patch, "status": "active", "approved_by": actor_id,
             "reactivated_at": _now(), "reactivated_by": actor_id}
    for _attempt in (1, 2):
        try:
            stored = await registry.patch_role_assignment(
                existing["id"], patch, expected_revision=existing.get("revision"),
                unset=["revoked_at", "revoked_by", "revoke_reason"])
            break
        except ConcurrentAssignmentChange:
            existing = await registry.get_role_assignment(existing["id"])
            if existing is None:
                raise
            if existing.get("status") == "active":
                stored = existing  # a concurrent identical command already did it
                break
    else:  # pragma: no cover
        raise ConcurrentAssignmentChange(existing["id"])
    await _audit_if_missing(ctx, "granted", stored, before=existing, reason=reason)
    return stored


async def grant_company_role(ctx, user_id: str, legacy_role: str, *, actor_id: str):
    """Set the user's company-scope assignment to their (mapped) role.

    Identity: logical key first (any status). Same role -> same record and id,
    no new document, no duplicate audit. Real change -> revoke ONLY the
    previously synchronized company assignment, then grant under the existing
    identity when the key already has one (e.g. back to an earlier role), else
    create. Emits granted/revoked audit with before/after.
    """
    role_id = LEGACY_ROLE_MAP.get(legacy_role, legacy_role)
    tid = sync_tenant_id(ctx)          # PR-06: tenant of the business write
    reason = f"company role {role_id}"

    # 1. Identity by logical key, whatever the status (PR-02 §1).
    existing = await registry.find_role_assignment_by_key(
        user_id, tid, role_id, "company", None, None)

    # 2. A real change revokes only the synchronized company assignment(s) of
    #    another role — never an independent manual grant (PR-02 §2).
    for a in await registry.list_role_assignments(user_id, tid):
        if (a.get("status") == "active" and a.get("role_id") != role_id
                and _company_sync_owned(a)):
            rev = await registry.revoke_role_assignment(
                a["id"], by=actor_id, reason=f"company role changed to {role_id}")
            await audit_permission_change(ctx, "revoked", rev or a, before=a, after=rev)

    # 3. Same role already active -> replay of the same command: no change
    #    (the audit event is only (re)written if a previous attempt lost it).
    if existing is not None and existing.get("status") == "active":
        await _audit_if_missing(ctx, "granted", existing, before=None, reason=reason)
        return existing

    # 4. Back to an earlier role -> reuse the existing identity (PR-02 §3).
    if existing is not None:
        return await _reactivate(ctx, existing, {"sync_source": SYNC_SOURCE_USER_ROLE},
                                 actor_id=actor_id, reason=reason)

    # 5. Nothing owns the key yet -> create. A duplicate-key race means a
    #    concurrent identical command won: read the real record back (§4).
    new = {
        "id": company_assignment_id(user_id, tid, role_id), "user_id": user_id,
        "tenant_id": tid, "role_id": role_id, "scope_type": "company", "scope_id": None,
        "module": None, "permissions": [], "max_amount": None, "valid_from": _now(),
        "valid_to": None, "status": "active", "created_by": actor_id,
        "approved_by": actor_id, "sync_source": SYNC_SOURCE_USER_ROLE,
    }
    try:
        stored = await registry.insert_role_assignment(new)
    except Exception as exc:
        if not _is_duplicate_key(exc):
            raise
        real = await registry.find_role_assignment_by_key(user_id, tid, role_id, "company", None, None)
        if real is None:
            # The id (not the logical key) collided with a foreign record.
            raise RuntimeError(
                f"assignment id {new['id']} is taken by a record with another logical key") from exc
        if real.get("status") == "active":
            await _audit_if_missing(ctx, "granted", real, before=None, reason=reason)
            return real
        return await _reactivate(ctx, real, {"sync_source": SYNC_SOURCE_USER_ROLE},
                                 actor_id=actor_id, reason=reason)
    await _audit_if_missing(ctx, "granted", stored, before=None, reason=reason)
    return stored


async def _find_project_mirror(user_id: str, tid: str, member_role_id: str, project_id: str):
    """The project-team mirror for (user, project): by logical key first; a
    mirror created under an earlier company role_id is the same membership."""
    by_key = await registry.find_role_assignment_by_key(
        user_id, tid, member_role_id, "project", project_id, None)
    if by_key is not None:
        return by_key
    legacy = await registry.get_role_assignment(project_assignment_id(user_id, tid, project_id))
    if legacy is not None and legacy.get("user_id") == user_id \
            and legacy.get("scope_type") == "project" and legacy.get("scope_id") == project_id:
        return legacy
    return None


async def sync_project_membership(ctx, user_id: str, member_role_id: str,
                                  project_id: str, role_in_project: str, active: bool,
                                  *, actor_id: str):
    """Mirror one project_team membership into a project-scope assignment.

    active member  -> project assignment with budget.read (SiteManager: +write);
    inactive/removed -> the assignment is revoked (next request loses access).

    An existing mirror keeps its id, valid_from/valid_to and max_amount; only
    the fields that actually follow the membership (status, permissions,
    role_id) change, and only when they differ.
    """
    tid = sync_tenant_id(ctx)          # PR-06: tenant of the business write
    existing = await _find_project_mirror(user_id, tid, member_role_id, project_id)
    reason = f"project {project_id} membership ({role_in_project})"

    if not active:
        if existing and existing.get("status") == "active":
            rev = await registry.revoke_role_assignment(
                existing["id"], by=actor_id, reason=f"removed from project {project_id}")
            await audit_permission_change(ctx, "revoked", rev or existing, before=existing, after=rev)
        return None

    perms = list(PROJECT_MANAGER_ACTIONS if role_in_project == "SiteManager"
                 else PROJECT_MEMBER_ACTIONS)

    if existing is None:
        new = {
            "id": project_assignment_id(user_id, tid, project_id), "user_id": user_id,
            "tenant_id": tid, "role_id": member_role_id, "scope_type": "project",
            "scope_id": project_id, "module": None, "permissions": perms,
            "max_amount": None, "valid_from": _now(), "valid_to": None,
            "status": "active", "created_by": actor_id, "approved_by": actor_id,
            "migrated_from": SYNC_SOURCE_PROJECT_TEAM, "sync_source": SYNC_SOURCE_PROJECT_TEAM,
        }
        try:
            stored = await registry.insert_role_assignment(new)
        except Exception as exc:
            if not _is_duplicate_key(exc):
                raise
            existing = await _find_project_mirror(user_id, tid, member_role_id, project_id)
            if existing is None:
                raise RuntimeError(
                    f"assignment id {new['id']} is taken by a record with another logical key") from exc
        else:
            await _audit_if_missing(ctx, "granted", stored, before=None, reason=reason)
            return stored

    patch = {}
    if sorted(existing.get("permissions") or []) != sorted(perms):
        patch["permissions"] = perms
    if existing.get("role_id") != member_role_id:
        patch["role_id"] = member_role_id
    if existing.get("status") != "active":
        return await _reactivate(ctx, existing, {**patch, "sync_source": SYNC_SOURCE_PROJECT_TEAM},
                                 actor_id=actor_id, reason=reason)
    if not patch:
        await _audit_if_missing(ctx, "granted", existing, before=None, reason=reason)
        return existing          # same command repeated: nothing changes
    stored = await registry.patch_role_assignment(
        existing["id"], {**patch, "approved_by": actor_id, "sync_source": SYNC_SOURCE_PROJECT_TEAM},
        expected_revision=existing.get("revision"))
    await _audit_if_missing(ctx, "updated", stored, before=existing, reason=reason)
    return stored


# ---------------------------------------------------------------------------
# PR-05 — shadow mode: the legacy write is the truth; the sync only observes.
# ---------------------------------------------------------------------------
import logging as _logging

_shadow_log = _logging.getLogger("permissions.shadow")
SHADOW_SYNC_FAILED = "SHADOW_SYNC_FAILED"


async def shadow_sync(ctx, tenant_db, action: str, reference: str, fn) -> bool:
    """Run a best-effort sync after a legacy business write in SHADOW mode.

    Returns True when the sync succeeded. A failure is REPORTED (warning log +
    a FAILED reservation in the canonical idempotency registry of the tenant
    database, key ``shadow-sync:<action>:<reference>``) and never raised: the
    legacy write already happened and the legacy response stays the response.
    It is never counted as parity, ALLOW or a successful sync.
    """
    try:
        await fn()
        return True
    except Exception as exc:
        _shadow_log.warning("PERMISSION_%s action=%s reference=%s error=%s: %s",
                            SHADOW_SYNC_FAILED, action, reference, type(exc).__name__, exc)
        try:
            from app.audit.idempotency import begin_idempotent, fail_idempotent
            key = f"shadow-sync:{action}:{reference}"
            # PR-06: the observation belongs to the tenant of the business write
            # (the database it is written into), not to the active tenant.
            rec_tid = sync_tenant_id(ctx)
            await begin_idempotent(tenant_db, tenant_id=rec_tid, key=key,
                                   action="permission.shadow_sync")
            await fail_idempotent(tenant_db, tenant_id=rec_tid, key=key,
                                  action="permission.shadow_sync", error_code=SHADOW_SYNC_FAILED)
        except Exception as exc2:  # reporting must never break the legacy path
            _shadow_log.warning("PERMISSION_%s_UNRECORDED action=%s reference=%s error=%s",
                                SHADOW_SYNC_FAILED, action, reference, exc2)
        return False
