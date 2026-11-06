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
  * project-bound roles (site_manager, LEGACY_TECHNICIAN — and project_manager,
    Р30: only as the team's manager) act on a project only with an active,
    in-date ``project_team`` row on EVERY project the command touches, and
    never on a warehouse / person / vehicle location — the legacy equivalent
    of their project-scope assignments (project + project bucket); company roles
    (owner, admin, warehouse, procurement, accountant, …) are company-wide;
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


async def _projects_touched(tenant_db, org_id: str, inp) -> Set[str]:
    from app.services.warehouse_movements.service import resolve_subproject_parent
    out: Set[str] = set()
    if inp.project_id:
        out.add(inp.project_id)
    for key in (inp.source, inp.destination, inp.transfer_target):
        if key is None:
            continue
        if key.location_type == LocationType.PROJECT:
            out.add(key.location_id)
        elif key.location_type == LocationType.SUBPROJECT:
            out.add(await resolve_subproject_parent(tenant_db, org_id, key.location_id))
    return out


async def ensure_legacy(ctx, tenant_db, inp, *, now: Optional[datetime] = None) -> str:
    """Р28 — decide a canonical command from the legacy session role."""
    from app.permissions.catalog import role_actions
    from app.services.warehouse_movements.write_off_policy import (
        PROJECT_MANAGER_TEAM_ROLE, ensure_project_write_off_legacy, member_in_date,
    )
    from app.tenancy.data_access import TenantData

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
    if role_id in PROJECT_BOUND_ROLES | PM_ROLES:
        # Same scope as their enforce assignments (project + its bucket): a
        # warehouse / person / vehicle location is outside it. The keys the
        # enforce gate checks: source and (transfer target or destination);
        # in-transit / unresolved / supplier carry no scope there either.
        for key in (inp.source, inp.transfer_target or inp.destination):
            if key is None or key.location_type in (
                    LocationType.IN_TRANSIT, LocationType.UNRESOLVED, LocationType.SUPPLIER,
                    LocationType.PROJECT, LocationType.SUBPROJECT):
                continue
            raise _deny("location outside the role's project scope",
                        scope_type="location", scope_id=key.location_id)
        tenant = TenantData.for_resolved_org(tenant_db, org_id)
        team_role = PROJECT_MANAGER_TEAM_ROLE if role_id in PM_ROLES else None
        for project_id in sorted(await _projects_touched(tenant_db, org_id, inp)):
            if not await member_in_date(tenant, user["id"], project_id, now=now,
                                        role_in_project=team_role):
                raise _deny("not a member of the project with valid dates",
                            scope_type="project", scope_id=project_id)
    return role_id
