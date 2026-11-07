"""
SEC-01 (decision R14, Krum 06.11.2026) — money writes only for the finance roles.

Source of the rule: PM-01 §5.1 (``docs/architecture/PM-01_PERMISSION_MODE_REPORT.md``)
proved on real Mongo that Viewer/Driver/Technician/Warehousekeeper could WRITE cash,
bonus and overhead transactions, overhead snapshots, project price modifiers, labor
entries, material waste and the paying client of a project. The established rule of
the sibling write endpoints in the same domain is Owner/Admin/Accountant:

  * ``app/routes/clients.py:27-29``  ``finance_permission`` (used at :177, :243, :282);
  * ``app/routes/finance.py:36-38``  ``finance_permission``;
  * ``app/routes/overhead.py:36-41``  ``check_overhead_access(write=True)``.

``require_money_write`` is the SAME W0-02 mechanism the migrated routes already use
(``require_permission`` with a legacy check in off/shadow, the Permission Service in
enforce — ``app/permissions/deps.py``), so the three modes give one answer:

  off      legacy role check only -> 403 before the handler runs;
  shadow   legacy role check decides, the catalog is evaluated in parallel (parity);
  enforce  Tenant Guard -> Permission Service decides (catalog action below), a denial
           writes the canonical "permission denied" AuditEvent, never a business row.

The handlers still read and write through the legacy global handle with
``user["org_id"]``; in enforce that is only correct when the active tenant's database
IS that handle and the identity's org is that tenant — the exact guard
``require_admin`` applies (``app/deps/auth.py:59-87``). Otherwise 409, before any write.

The dependency is declared BEFORE the module (subscription) dependency of each route,
so a denied role is refused before any read of tenant data.

SEC-01-C01 (R14 + R16, Krum 06.11.2026) extends the same mechanism to EVERY write route
on the same resources:

  * ``require_money_write(..., roles=...)`` — also used with the narrower Owner/Admin
    rule of ``PUT /price-modifiers/org`` (the rule already in that handler);
  * ``require_field_cost_write`` — R16 for labor entries and material waste:
    Owner/Admin/Accountant everywhere; SiteManager/Technician ONLY on a project they are
    a member of (``project_team``, the same membership as ``can_access_project``);
    Viewer/Driver/any other role 403. In enforce the Permission Service decides with
    scope ``project``: a company assignment (Accountant/Owner/Admin) covers every
    project; a SiteManager/Technician has the action only on the project-scope
    assignment that mirrors their membership (``catalog.project_membership_actions``);
  * ``check_money_write`` — the same decision from inside a handler, for writes that
    touch the resource only for some bodies (``owner_*`` of PUT/POST /projects).
"""
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request

from app.db import db
from app.permissions.deps import require_permission, require_legacy_data_path
from app.tenancy.guard import TenantContext

# Legacy role strings of the finance roles (same list as the sibling rule above).
FINANCE_WRITE_ROLES = ("Admin", "Owner", "Accountant")
# SEC-01-C01: PUT /price-modifiers/org keeps its existing, narrower rule.
OWNER_ADMIN_ROLES = ("Admin", "Owner")
# R16: the legacy role strings that may write field costs on MEMBER projects only.
FIELD_MEMBER_ROLES = ("SiteManager", "Technician")


def _legacy_role_check(roles):
    def check(user: dict, request) -> bool:
        return user.get("role") in roles
    return check


_legacy_finance_role = _legacy_role_check(FINANCE_WRITE_ROLES)


async def _legacy_data_path_guard(ctx: TenantContext) -> None:
    if ctx.enforced:
        await require_legacy_data_path(ctx, db)
        if ctx.user.get("org_id") != ctx.org_id:
            raise HTTPException(status_code=409, detail={
                "error_code": "TENANT_DATA_PATH_NOT_MIGRATED",
                "message": "This operation is not yet available when the active tenant "
                           "differs from the identity's legacy organization"})


def require_money_write(action: str, *, module: str, resource_type: str,
                        roles=FINANCE_WRITE_ROLES):
    """Dependency for one money-write endpoint. Returns the session user."""
    permission = require_permission(
        action, module=module, scope="company", resource_type=resource_type,
        legacy_check=_legacy_role_check(tuple(roles)),
    )

    async def dependency(ctx: TenantContext = Depends(permission)) -> dict:
        await _legacy_data_path_guard(ctx)
        return ctx.user

    dependency.sec01_action = action      # inspected by tests/test_sec_01_*.py
    return dependency


async def check_money_write(request: Request, user: dict, action: str, *, module: str,
                            resource_type: str) -> dict:
    """The require_money_write decision, called from inside a handler BEFORE its write."""
    permission = require_permission(
        action, module=module, scope="company", resource_type=resource_type,
        legacy_check=_legacy_finance_role,
    )
    ctx = await permission(request, user)
    await _legacy_data_path_guard(ctx)
    return ctx.user


# ── R16: labor entries and material waste ───────────────────────────────────────
async def _project_id_from_path(request: Request) -> Optional[str]:
    value = request.path_params.get("project_id")
    return value if isinstance(value, str) and value else None


async def _project_id_from_body(request: Request) -> Optional[str]:
    try:
        payload: Any = await request.json()      # already read and cached by FastAPI
    except Exception:                            # noqa: BLE001 — no/invalid body: no project
        return None
    value = payload.get("project_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


_PROJECT_SOURCES = {"path": _project_id_from_path, "body": _project_id_from_body}


def require_field_cost_write(action: str, *, module: str, resource_type: str,
                             project_from: str):
    """R16 dependency. ``project_from``: "path" ({project_id}) or "body" (JSON project_id)."""
    get_project = _PROJECT_SOURCES[project_from]

    async def legacy_check(user: dict, request: Request) -> bool:
        role = user.get("role")
        if role in FINANCE_WRITE_ROLES:
            return True
        if role not in FIELD_MEMBER_ROLES:
            return False
        project_id = await get_project(request)
        if not project_id:
            return False
        from app.tenancy import project_team
        # The tenant is the session user's own (server-loaded), never a request value:
        # another tenant's project id is never a membership of this user.
        return await project_team.is_member(project_team.tenant_for(db, user),
                                            user["id"], project_id)

    permission = require_permission(
        action, module=module, scope="project", resource_type=resource_type,
        scope_id_getter=get_project, legacy_check=legacy_check,
    )

    async def dependency(ctx: TenantContext = Depends(permission)) -> dict:
        await _legacy_data_path_guard(ctx)
        return ctx.user

    dependency.sec01_action = action
    dependency.sec01_rule = "R16"
    return dependency
