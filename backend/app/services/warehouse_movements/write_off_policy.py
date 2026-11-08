"""
5C-C26 Addendum A — FG-21 → Р27 (Крум, 06.11.2026): who may write material
off a PROJECT as „фира".

Р27 follows Р16 (labor / material waste):
  * Owner / Admin / Accountant — on every project of the tenant;
  * project_manager — only on their own projects: Р30 — an active, in-date
    project_team row with role_in_project "SiteManager" (manager);
  * SiteManager / Technician — only on projects where they are members
    with valid dates (project_team row: ``active`` and
    ``from_date <= today <= to_date``; an open bound is open);
  * every other role (warehouse, procurement, office, viewer, driver,
    worker, …) — 403, nothing written.

Where the roles come from: the caller's RoleAssignments in the tenant
(Permission Service ``_load_assignments`` — the same records, the same
status / validity / scope semantics as ``_evaluate_one``). Membership comes
from ``app.tenancy.project_team`` (tenant-bound, A2). The date check is
local here because ``project_team.membership_filter`` on this branch does
not carry dates yet; when PR #69 (membership_filter with from/to dates)
merges, ``_member_in_date`` is replaced by that filter — same rule.

A write-off from a WAREHOUSE is not project cost and keeps the generic
Permission Service gate (``warehouse.write_off`` on the location).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, List, Optional

from app.services.warehouse_movements.errors import PermissionDeniedError

from app.permissions.catalog import PROJECT_WRITEOFF_RULE

# 5C-C26 Addendum B — the table lives in the catalog (one source).
R27_EVERYWHERE = frozenset(r for r, k in PROJECT_WRITEOFF_RULE.items() if k == "everywhere")
R27_OWN_PROJECT = frozenset(r for r, k in PROJECT_WRITEOFF_RULE.items() if k == "own_project")
R27_MEMBER_ONLY = frozenset(r for r, k in PROJECT_WRITEOFF_RULE.items() if k == "member")
R27_REASON = "R27_WRITE_OFF_NOT_ALLOWED"
# Р30 — the project_team role that makes a project "own" for a PM.
PROJECT_MANAGER_TEAM_ROLE = "SiteManager"


def _day(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"invalid membership date {value!r}")


def _member_in_date(row: Optional[dict], today: date) -> bool:
    """An active project_team row whose [from_date, to_date] holds today.
    An unreadable date is NOT an open bound (fail closed)."""
    if not row or not row.get("active", True):
        return False
    try:
        start, end = _day(row.get("from_date")), _day(row.get("to_date"))
    except ValueError:
        return False
    return (start is None or start <= today) and (end is None or today <= end)


async def member_in_date(tenant, user_id: str, project_id: str, *,
                         now: Optional[datetime] = None,
                         role_in_project: Optional[str] = None) -> bool:
    """An active, in-date project_team row of THIS tenant (optionally with
    the given role_in_project)."""
    from app.tenancy import project_team
    now = now or datetime.now(timezone.utc)
    try:
        row = await project_team.member_row(tenant, user_id, project_id,
                                            role_in_project=role_in_project)
    except Exception:
        row = None
    return _member_in_date(row, now.date())


def _active_assignments(assignments: Iterable[dict], now: datetime) -> List[dict]:
    from app.permissions.service import _validity_window
    out = []
    for a in assignments or []:
        if not isinstance(a, dict) or a.get("status") != "active":
            continue
        try:
            vf, vt = _validity_window(a)
        except Exception:
            continue
        if (vf and now < vf) or (vt and now > vt):
            continue
        out.append(a)
    return out


def _covers_project(a: dict, project_id: str) -> bool:
    from app.permissions.service import _scope_covers
    return _scope_covers(a.get("scope_type"), a.get("scope_id"), "project", project_id)


async def ensure_project_write_off(ctx, tenant_db, *, org_id: str, project_id: str,
                                   now: Optional[datetime] = None,
                                   load_assignments=None) -> str:
    """Raise ``PermissionDeniedError`` unless Р27 allows the caller to write
    off from ``project_id``. Returns the deciding role (for the audit)."""
    from app.permissions import service as perm
    from app.tenancy import project_team
    from app.tenancy.data_access import TenantData

    now = now or datetime.now(timezone.utc)
    user_id = getattr(ctx, "user_id", None)
    tenant_id = getattr(ctx, "tenant_id", None)

    def _deny(detail: str):
        return PermissionDeniedError(
            f"Р27: write-off from project denied ({detail})",
            context={"action": "write_off", "reason_code": R27_REASON,
                     "scope_type": "project", "scope_id": project_id})

    if not user_id or not tenant_id or not project_id:
        raise _deny("no session identity")
    loader = load_assignments or perm._load_assignments
    active = _active_assignments(await loader(user_id, tenant_id), now)
    roles = {a.get("role_id") for a in active}

    for a in active:
        if a.get("role_id") in R27_EVERYWHERE and _covers_project(a, project_id):
            return a["role_id"]
    tenant = TenantData.for_resolved_org(tenant_db, org_id)
    if roles & R27_MEMBER_ONLY:
        if await member_in_date(tenant, user_id, project_id, now=now):
            return sorted(roles & R27_MEMBER_ONLY)[0]
    if roles & R27_OWN_PROJECT:
        # Р30 (Крум 06.11.2026, FG-40): a project manager's own project is one
        # where the team row names them the manager (role_in_project
        # "SiteManager"), in date — not any team participation, and not a
        # project-scope RoleAssignment by itself.
        if await member_in_date(tenant, user_id, project_id, now=now,
                                role_in_project=PROJECT_MANAGER_TEAM_ROLE):
            return sorted(roles & R27_OWN_PROJECT)[0]
    if roles & (R27_MEMBER_ONLY | R27_OWN_PROJECT):
        raise _deny("not a member (manager for a PM) of the project with valid dates")
    raise _deny("role may not write off from a project")


# ───────────── 5C-C26c — Р27 in every Permission Service mode ─────────────
#
# off / shadow have no RoleAssignments decision (W0-02: the legacy role
# decides there — same pattern as SEC-01 ``require_money_write`` in #69).
# The legacy session role is mapped with the catalog's LEGACY_ROLE_MAP and
# the SAME PROJECT_WRITEOFF_RULE table is applied, with the same in-date
# membership check. So Р27 gives the same answer in off, shadow and enforce.

async def ensure_project_write_off_legacy(user: dict, tenant_db, *, org_id: str,
                                          project_id: str,
                                          now: Optional[datetime] = None) -> str:
    """Р27 from the legacy session role (off / shadow)."""
    from app.permissions.catalog import LEGACY_ROLE_MAP
    from app.tenancy import project_team
    from app.tenancy.data_access import TenantData

    now = now or datetime.now(timezone.utc)
    user_id = (user or {}).get("id")
    role_id = LEGACY_ROLE_MAP.get((user or {}).get("role") or "")

    def _deny(detail: str):
        return PermissionDeniedError(
            f"Р27: write-off from project denied ({detail})",
            context={"action": "write_off", "reason_code": R27_REASON,
                     "scope_type": "project", "scope_id": project_id,
                     "decided_by": "legacy_role"})

    if not user_id or not project_id:
        raise _deny("no session identity")
    if role_id in R27_EVERYWHERE:
        return role_id
    if role_id in R27_MEMBER_ONLY or role_id in R27_OWN_PROJECT:
        tenant = TenantData.for_resolved_org(tenant_db, org_id)
        if await member_in_date(
                tenant, user_id, project_id, now=now,
                role_in_project=(PROJECT_MANAGER_TEAM_ROLE if role_id in R27_OWN_PROJECT
                                 else None)):
            return role_id
        raise _deny("not a member of the project with valid dates")
    raise _deny("role may not write off from a project")
