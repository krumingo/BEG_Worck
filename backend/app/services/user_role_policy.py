"""
R0-03 (AUD-025) — role changes without escalation; the Owner is protected.

Hierarchy: ``Owner`` > ``Admin`` > every other role.

* nobody changes their OWN role                                  -> 403
* nobody grants a role above their own (an Admin cannot grant Owner) -> 403
* only an Owner changes an Owner: role, ``is_active``, admin password reset,
  deletion                                                       -> 403
* the last active Owner of the firm is never demoted, deactivated or deleted -> 409

Where the roles are read (no second source of roles is created):

* ``off`` / ``shadow``: the legacy ``users.role`` decides authorization in
  these modes, so it decides the rank too.
* ``enforce``: the actor's rank comes ONLY from the authoritative FLOW-002
  RoleAssignments of the active tenant (company scope, active, valid now) —
  the same records the Permission Service decides from; no fallback to
  ``users.role``. The Permission Service grants ``owner`` and ``admin`` the same
  action set, so it holds no hierarchy; this module adds it on top.
  The TARGET counts as an Owner when either source says so (the safe side).
* "Is this target an Owner" and the count of the OTHER active Owners for the
  last-Owner rule (R0-03-C01 F-01) follow the mode too:
  - ``off`` / ``shadow``: ``users.role == "Owner"`` of active tenant users;
  - ``enforce``: active, company-scoped, currently valid ``owner``
    RoleAssignments of the tenant whose User is an active user OF THIS TENANT
    (an identity from another tenant does not keep this company owned).

Approval (CLAUDE.md §8) for changes that touch an Owner is NOT implemented: the
canonical DQ/Approval runtime is not built yet (W0). Until then the rule is
"only an Owner" — recorded as debt, no parallel approval mechanism.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException

OWNER, ADMIN = "Owner", "Admin"
RANK_OWNER, RANK_ADMIN, RANK_OTHER = 2, 1, 0
_LEGACY_RANK = {OWNER: RANK_OWNER, ADMIN: RANK_ADMIN}
_ASSIGNMENT_RANK = {"owner": RANK_OWNER, "admin": RANK_ADMIN}

ERROR_OWN_ROLE = "OWN_ROLE_CHANGE_FORBIDDEN"
ERROR_ROLE_ABOVE_OWN = "ROLE_ABOVE_OWN_FORBIDDEN"
ERROR_OWNER_ONLY = "OWNER_CHANGE_REQUIRES_OWNER"
ERROR_LAST_OWNER = "LAST_ACTIVE_OWNER"


def legacy_rank(role: Optional[str]) -> int:
    return _LEGACY_RANK.get(role or "", RANK_OTHER)


def _forbidden(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"error_code": code, "message": message})


def _assignment_counts_now(a: Mapping[str, Any]) -> bool:
    """Active, company-scoped and inside its validity window (FLOW-002)."""
    from app.permissions.service import _validity_window
    if a.get("status") != "active" or a.get("scope_type") not in (None, "company"):
        return False
    try:
        vf, vt = _validity_window(dict(a))
    except Exception:
        return False
    now = datetime.now(timezone.utc)
    return not ((vf and now < vf) or (vt and now > vt))


async def assignment_rank(user_id: str, tenant_id: str) -> int:
    from app.tenancy import registry
    best = RANK_OTHER
    for a in await registry.list_role_assignments(user_id, tenant_id):
        if _assignment_counts_now(a):
            best = max(best, _ASSIGNMENT_RANK.get(a.get("role_id") or "", RANK_OTHER))
    return best


async def actor_rank(user: Mapping[str, Any], mode: str, tenant_id: Optional[str]) -> int:
    from app.permissions.deps import MODE_ENFORCE
    if mode != MODE_ENFORCE:
        return legacy_rank(user.get("role"))
    return await assignment_rank(user["id"], tenant_id)


async def target_rank(target: Mapping[str, Any], mode: str, tenant_id: Optional[str]) -> int:
    from app.permissions.deps import MODE_ENFORCE
    rank = legacy_rank(target.get("role"))
    if mode == MODE_ENFORCE and rank < RANK_OWNER:
        rank = max(rank, await assignment_rank(target["id"], tenant_id))
    return rank


def _is_active(user: Mapping[str, Any]) -> bool:
    return user.get("is_active", True) is not False


async def _enforce_owner_ids(tenant, tenant_id: Optional[str]) -> set:
    """enforce: ids of the tenant's active users holding a valid company ``owner`` assignment."""
    from app.tenancy import registry
    holders = {a.get("user_id") for a in await registry.list_tenant_role_assignments(tenant_id, "owner")
               if _assignment_counts_now(a) and a.get("user_id")}
    if not holders:
        return set()
    active = await tenant.users.find(
        {"id": {"$in": sorted(holders)}, "is_active": {"$ne": False}}, {"_id": 0, "id": 1}).to_list(None)
    return {u["id"] for u in active}


async def is_owner_for_last_rule(tenant, target: Mapping[str, Any], mode: str,
                                 tenant_id: Optional[str]) -> bool:
    """Does the last-Owner rule apply to ``target`` (mode-dependent, see module doc)?"""
    from app.permissions.deps import MODE_ENFORCE
    if mode != MODE_ENFORCE:
        return legacy_rank(target.get("role")) >= RANK_OWNER
    return await assignment_rank(target["id"], tenant_id) >= RANK_OWNER


async def _assert_not_last_owner(tenant, target: Mapping[str, Any], mode: str,
                                 tenant_id: Optional[str]) -> None:
    """409 when ``target`` is the only active Owner of its firm. ``tenant`` is a TenantData."""
    from app.permissions.deps import MODE_ENFORCE
    if not _is_active(target):
        return
    if mode == MODE_ENFORCE:
        others = len((await _enforce_owner_ids(tenant, tenant_id)) - {target["id"]})
    else:
        others = await tenant.users.count_documents(
            {"role": OWNER, "is_active": {"$ne": False}, "id": {"$ne": target["id"]}})
    if others == 0:
        raise HTTPException(status_code=409, detail={
            "error_code": ERROR_LAST_OWNER,
            "message": "The last active Owner of the company cannot be demoted, deactivated or deleted"})


async def check_user_update(tenant, *, actor: Mapping[str, Any], target: Mapping[str, Any],
                            update: Mapping[str, Any], mode: str, tenant_id: Optional[str]) -> None:
    """Refuse a ``PUT /users/{id}`` that escalates or touches an Owner without being one.

    Called before any write. Only ``role`` and ``is_active`` are guarded; names,
    phone and avatar stay as before.
    """
    from app.permissions.deps import MODE_ENFORCE
    role_change = "role" in update and update["role"] != target.get("role")
    if (not role_change and "role" in update and update["role"] != OWNER and mode == MODE_ENFORCE
            and await assignment_rank(target["id"], tenant_id) >= RANK_OWNER):
        # enforce: the users.role mirror may already say e.g. "Admin" while the
        # authoritative assignment is owner; the sync would revoke that owner
        # assignment, so this IS a role change (R0-03-C01 F-01).
        role_change = True
    active_change = "is_active" in update and bool(update["is_active"]) != _is_active(target)
    if not (role_change or active_change):
        return
    a_rank = await actor_rank(actor, mode, tenant_id)
    t_rank = await target_rank(target, mode, tenant_id)
    if role_change and target["id"] == actor["id"]:
        raise _forbidden(ERROR_OWN_ROLE, "You cannot change your own role")
    if role_change and legacy_rank(update["role"]) > a_rank:
        raise _forbidden(ERROR_ROLE_ABOVE_OWN, "You cannot grant a role above your own")
    if t_rank >= RANK_OWNER and a_rank < RANK_OWNER:
        raise _forbidden(ERROR_OWNER_ONLY, "Only an Owner can change an Owner")
    removes = (role_change and update["role"] != OWNER) or \
        (active_change and update["is_active"] is False)
    if removes and await is_owner_for_last_rule(tenant, target, mode, tenant_id):
        await _assert_not_last_owner(tenant, target, mode, tenant_id)


async def check_owner_only(tenant, *, actor: Mapping[str, Any], target: Mapping[str, Any],
                           mode: str, tenant_id: Optional[str], deleting: bool = False) -> None:
    """Admin password reset / deletion: only an Owner acts on an Owner; never the last one."""
    t_rank = await target_rank(target, mode, tenant_id)
    if t_rank < RANK_OWNER:
        return
    if await actor_rank(actor, mode, tenant_id) < RANK_OWNER:
        raise _forbidden(ERROR_OWNER_ONLY, "Only an Owner can change an Owner")
    if deleting and await is_owner_for_last_rule(tenant, target, mode, tenant_id):
        await _assert_not_last_owner(tenant, target, mode, tenant_id)


def role_audit_diff(target: Mapping[str, Any], update: Mapping[str, Any]) -> Dict[str, Any]:
    """before/after of the guarded fields actually changing (never a hash or password)."""
    before, after = {}, {}
    for key in ("role", "is_active", "email"):
        if key in update and update[key] != target.get(key):
            before[key], after[key] = target.get(key), update[key]
    return {"before": before, "after": after}


async def audit_user_change(database, *, tenant_id: str, actor_id: str, action: str,
                            target_id: Optional[str], diff: Optional[Dict[str, Any]] = None,
                            reason: str, result: str = "success", actor_type: str = "human",
                            error_code: Optional[str] = None,
                            tool_or_endpoint: Optional[str] = None,
                            session=None) -> Dict[str, Any]:
    """One canonical W0-04 AuditEvent (FLOW-040, R3 security/access) in ``database``.

    ``session``: write inside the caller's MongoDB transaction (R0-04 reset/recovery).

    ``database`` is the same handle the business write used. ``diff`` carries
    before/after of role / is_active / email only — never a password or hash
    (``build_event`` masks and ``validate_event`` refuses secret-looking keys).
    """
    from app.audit.envelope import build_event, RETENTION_R3_SECURITY_ACCESS
    from app.audit.store import record_event
    event = build_event(
        tenant_id=tenant_id, actor_type=actor_type, actor_id=actor_id, action=action,
        source_flow="FLOW-002", retention_class=RETENTION_R3_SECURITY_ACCESS, result=result,
        entity_type="user", entity_id=target_id, structured_diff=diff, reason=reason,
        error_code=error_code, tool_or_endpoint=tool_or_endpoint)
    return await record_event(database, event, session=session)
