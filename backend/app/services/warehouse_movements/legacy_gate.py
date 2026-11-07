"""
5C-C26e — Р28 (Крум 06.11.2026): the canonical warehouse writes in all three
Permission Service modes (off / shadow / enforce), and the rights are decided
the same way in all three.

off / shadow have no RoleAssignments decision (W0-02: the legacy session role
decides there — the same pattern as SEC-01 ``require_money_write`` (#69) and
Р27 in 5C-C26c). This gate maps the legacy session role onto its catalog
role (``LEGACY_ROLE_MAP``) and applies the SAME rules the enforce gate
applies through the role's RoleAssignment:

  * the role's catalog actions must hold the command's permission action
    (``permission_action_for``) — exactly the set the enforce evaluator reads
    from ``role_actions(role_id)``;
  * PROJECT RELATION (5C-C26f, audit C26E-1 — the same rule in enforce,
    ``ensure_project_relation``): when the action is granted ONLY by
    project-bound roles (site_manager, LEGACY_TECHNICIAN; project_manager,
    Р30: only as the team's manager), the caller needs an active, in-date
    ``project_team`` row on EVERY project the command touches. The product's
    real grant (``permissions.sync.grant_company_role``) gives these roles a
    COMPANY-scope assignment, so a warehouse location they touch (a return to
    the warehouse) is in scope in both modes; company roles (owner, admin,
    warehouse, procurement, accountant, …) need no project relation;
  * a write-off FROM A PROJECT is decided by Р27
    (``write_off_policy.ensure_project_write_off_legacy``).

A denial raises ``PermissionDeniedError`` before anything is written.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Set

from app.services.warehouse_movements.actions import CanonicalAction, permission_action_for
from app.services.warehouse_movements.envelope import LocationKey, LocationType
from app.services.warehouse_movements.errors import PermissionDeniedError

LEGACY_GATE_REASON = "R28_LEGACY_ROLE_NOT_ALLOWED"
PROJECT_BOUND_ROLES = frozenset({"site_manager", "LEGACY_TECHNICIAN"})
PM_ROLES = frozenset({"project_manager"})


def legacy_role_id(user: Optional[dict]) -> Optional[str]:
    from app.permissions.catalog import LEGACY_ROLE_MAP
    return LEGACY_ROLE_MAP.get((user or {}).get("role") or "")


# Actions whose project is a TARGET with no project location in the command
# itself (the lot is in transit / reserved): their project_id is the only
# project reference. Every other action's projects come from its locations.
PROJECT_BY_INTENT = frozenset({
    CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
    CanonicalAction.RESERVE,
    CanonicalAction.RELEASE_RESERVATION,
})


async def _projects_touched(tenant_db, org_id: str, inp) -> Set[str]:
    """5C-C26h (FG-59) — the projects a command TOUCHES, from its locations
    (DB-resolved: a subproject → its parent), never from a body id. An
    unresolvable subproject counts as itself (a project nobody belongs to),
    so the rights check fails closed instead of answering 422 first (FG-55).
    Only for PROJECT_BY_INTENT actions does project_id name the project."""
    from app.services.warehouse_movements.errors import WarehouseMovementError
    from app.services.warehouse_movements.service import resolve_subproject_parent
    out: Set[str] = set()
    if inp.action in PROJECT_BY_INTENT and inp.project_id:
        out.add(inp.project_id)
    for key in (inp.source, inp.destination, inp.transfer_target):
        if key is None:
            continue
        if key.location_type == LocationType.PROJECT:
            out.add(key.location_id)
        elif key.location_type == LocationType.SUBPROJECT:
            try:
                out.add(await resolve_subproject_parent(tenant_db, org_id, key.location_id))
            except WarehouseMovementError:
                out.add(key.location_id)
    return out


async def ensure_project_relation(tenant_db, org_id: str, user_id: str,
                                  granting_roles, project_ids, *,
                                  now: Optional[datetime] = None,
                                  deny=None, deny_no_project=None) -> None:
    """5C-C26f (C26E-1) — THE project-relation rule, both modes.

    ``granting_roles`` — the caller's roles that grant the action. If any of
    them is a company role, no relation is needed. Otherwise every project in
    ``project_ids`` needs an in-date project_team row (any team role for
    site_manager / technician; the manager row for a PM, Р30)."""
    from app.services.warehouse_movements.write_off_policy import (
        PROJECT_MANAGER_TEAM_ROLE, member_in_date,
    )
    from app.tenancy.data_access import TenantData
    roles = set(granting_roles)
    if not roles or roles - (PROJECT_BOUND_ROLES | PM_ROLES):
        return
    if not project_ids:
        # 5C-C26g — audit C26F-1: a project-bound role acts only THROUGH a
        # project. A command that touches no project (quarantine at the
        # central warehouse, accepting a warehouse → warehouse transfer, …)
        # is outside its scope — in every mode.
        raise (deny_no_project or _no_project_denied)()
    tenant = TenantData.for_resolved_org(tenant_db, org_id)
    for project_id in sorted(set(project_ids)):
        ok = False
        if roles & PROJECT_BOUND_ROLES:
            ok = await member_in_date(tenant, user_id, project_id, now=now)
        if not ok and roles & PM_ROLES:
            ok = await member_in_date(tenant, user_id, project_id, now=now,
                                      role_in_project=PROJECT_MANAGER_TEAM_ROLE)
        if not ok:
            raise (deny or _relation_denied)(project_id)


def _relation_denied(project_id: str):
    return PermissionDeniedError(
        "Р28: not a member of the project with valid dates",
        context={"reason_code": RELATION_REASON, "scope_type": "project",
                 "scope_id": project_id})


RELATION_REASON = "R28_PROJECT_RELATION_REQUIRED"
NO_PROJECT_REASON = "R28_PROJECT_REQUIRED"


def _no_project_denied():
    return PermissionDeniedError(
        "Р28: a project-bound role acts only through a project",
        context={"reason_code": NO_PROJECT_REASON})


async def ensure_legacy(ctx, tenant_db, inp, *, now: Optional[datetime] = None) -> str:
    """Р28 — decide a canonical command from the legacy session role."""
    from app.permissions.catalog import role_actions
    from app.services.warehouse_movements.write_off_policy import (
        ensure_project_write_off_legacy,
    )

    user = getattr(ctx, "user", None) or {}
    org_id = inp.tenant_id

    def _deny(detail: str, **context):
        return PermissionDeniedError(
            f"Р28: {detail}",
            context={"action": inp.action.value, "reason_code": LEGACY_GATE_REASON,
                     "decided_by": "legacy_role", "legacy_role": user.get("role"),
                     **context})

    if not user.get("id"):
        raise _deny("no session identity")
    if inp.action == CanonicalAction.WRITE_OFF and inp.project_id:
        return await ensure_project_write_off_legacy(
            user, tenant_db, org_id=org_id, project_id=inp.project_id, now=now)

    role_id = legacy_role_id(user)
    permission = permission_action_for(inp.action)
    if role_id is None or permission not in role_actions(role_id):
        raise _deny(f"role may not {permission}", permission=permission)
    await ensure_project_relation(
        tenant_db, org_id, user["id"], {role_id},
        await _projects_touched(tenant_db, org_id, inp), now=now,
        deny=lambda pid: _deny("not a member of the project with valid dates",
                               scope_type="project", scope_id=pid,
                               reason_code=RELATION_REASON),
        deny_no_project=lambda: _deny("a project-bound role acts only through a project",
                                      reason_code=NO_PROJECT_REASON))
    return role_id


async def ensure_enforce_project_relation(ctx, tenant_db, inp, *, load_assignments=None,
                                          now: Optional[datetime] = None) -> None:
    """5C-C26f (audit C26E-1, HIGH) — enforce half of the project relation.
    After the RoleAssignment gate allowed the command: the roles that grant
    it (active assignments whose permissions / catalog actions hold the
    action) — if ALL are project-bound, the in-date membership is required on
    every project touched, exactly as in off / shadow."""
    from app.permissions import service as perm
    from app.permissions.catalog import role_actions
    from app.services.warehouse_movements.write_off_policy import _active_assignments

    now = now or datetime.now(timezone.utc)
    permission = permission_action_for(inp.action)
    loader = load_assignments or perm._load_assignments
    active = _active_assignments(await loader(ctx.user_id, ctx.tenant_id), now)
    granting = {a.get("role_id") for a in active
                if permission in (set(a.get("permissions") or [])
                                  or role_actions(a.get("role_id") or ""))}
    await ensure_project_relation(
        tenant_db, inp.tenant_id, ctx.user_id, granting,
        await _projects_touched(tenant_db, inp.tenant_id, inp), now=now)


# ───────────── 5C-C26f — F-16: canonical READS through the same gate ─────────────

async def legacy_read_roles(ctx, *, permission: str) -> set:
    """Р28 for the canonical GET routes in off / shadow: the legacy role's
    catalog actions must hold ``permission`` (warehouse.read_stock /
    read_history), exactly as the enforce evaluator reads them; otherwise
    PermissionDeniedError (→ 403). Returns the granting role set (for the
    project relation of a project-filtered read)."""
    from app.permissions.catalog import role_actions
    user = getattr(ctx, "user", None) or {}
    role_id = legacy_role_id(user)
    if not user.get("id") or role_id is None or permission not in role_actions(role_id):
        raise PermissionDeniedError(
            f"Р28: role may not {permission}",
            context={"action": permission, "reason_code": LEGACY_GATE_REASON,
                     "decided_by": "legacy_role", "legacy_role": user.get("role")})
    return {role_id}


async def enforce_read_roles(ctx, *, permission: str, now: Optional[datetime] = None) -> set:
    """The enforce-side granting roles of a read (active assignments)."""
    from app.permissions import service as perm
    from app.permissions.catalog import role_actions
    from app.services.warehouse_movements.write_off_policy import _active_assignments
    now = now or datetime.now(timezone.utc)
    active = _active_assignments(
        await perm._load_assignments(ctx.user_id, ctx.tenant_id), now)
    return {a.get("role_id") for a in active
            if permission in (set(a.get("permissions") or [])
                              or role_actions(a.get("role_id") or ""))}


async def member_projects(tenant_db, org_id: str, user_id: str, roles, *,
                          now: Optional[datetime] = None) -> Set[str]:
    """5C-C26h (FG-60) — the projects a project-bound caller may see: its
    in-date project_team rows (a PM: only the manager rows, Р30)."""
    from app.services.warehouse_movements.write_off_policy import (
        PROJECT_MANAGER_TEAM_ROLE, member_in_date,
    )
    from app.tenancy import project_team
    from app.tenancy.data_access import TenantData
    tenant = TenantData.for_resolved_org(tenant_db, org_id)
    out: Set[str] = set()
    roles = set(roles)
    if roles & PROJECT_BOUND_ROLES:
        for pid in await project_team.assigned_project_ids(tenant, user_id):
            if await member_in_date(tenant, user_id, pid, now=now):
                out.add(pid)
    if roles & PM_ROLES:
        for pid in await project_team.assigned_project_ids(
                tenant, user_id, role_in_project=PROJECT_MANAGER_TEAM_ROLE):
            if await member_in_date(tenant, user_id, pid, now=now,
                                    role_in_project=PROJECT_MANAGER_TEAM_ROLE):
                out.add(pid)
    return out
