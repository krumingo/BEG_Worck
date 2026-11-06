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
"""
from fastapi import Depends, HTTPException

from app.db import db
from app.permissions.deps import require_permission, require_legacy_data_path
from app.tenancy.guard import TenantContext

# Legacy role strings of the finance roles (same list as the sibling rule above).
FINANCE_WRITE_ROLES = ("Admin", "Owner", "Accountant")


def _legacy_finance_role(user: dict, request) -> bool:
    return user.get("role") in FINANCE_WRITE_ROLES


def require_money_write(action: str, *, module: str, resource_type: str):
    """Dependency for one money-write endpoint. Returns the session user."""
    permission = require_permission(
        action, module=module, scope="company", resource_type=resource_type,
        legacy_check=_legacy_finance_role,
    )

    async def dependency(ctx: TenantContext = Depends(permission)) -> dict:
        if ctx.enforced:
            await require_legacy_data_path(ctx, db)
            if ctx.user.get("org_id") != ctx.org_id:
                raise HTTPException(status_code=409, detail={
                    "error_code": "TENANT_DATA_PATH_NOT_MIGRATED",
                    "message": "This operation is not yet available when the active tenant "
                               "differs from the identity's legacy organization"})
        return ctx.user

    dependency.sec01_action = action      # inspected by tests/test_sec_01_*.py
    return dependency
