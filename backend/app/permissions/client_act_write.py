"""
ACT-01 — who may write a client act and read its remainder (R14, R20; PM-01 §5.1).

Before ACT-01 (main @ 0f870c3) ``POST/PUT /client-acts`` and ``POST /client-acts/from-offer``
were behind ``require_m2`` only — a module (subscription) check: EVERY role of a tenant with
M2, Viewer and Driver included, created and edited acts (PM-01 matrix, ``docs/evidence/
PM-01/matrix.csv``: 404 "Project not found" for all eight roles, i.e. past authorization).

A client act carries client prices and creates a receivable — a money write. The canon:

  * R14 (Krum 06.11.2026): money writes only for Owner/Admin/Accountant;
  * R20: client prices are company finance — Owner/Admin/Accountant only;
  * the sibling act route already guarded by SEC-01-C02 (PR #69):
    ``POST /client-acts/{act_id}/confirm`` -> ``revenue.client_act_confirm.execute``,
    finance roles; SEC-02 (PR #71) names ``finance.client_act.update`` and
    ``finance.client_act_from_offer.execute`` for PUT and from-offer (R20-2) — the same
    action names are used here so the two PRs meet on one catalog entry.

So this narrows the old "any role" to the finance roles; it widens nothing.

The decision is the W0-02 mechanism (``app.permissions.deps.require_permission``):
off — legacy role check; shadow — legacy decides, the catalog is evaluated next to it;
enforce — Tenant Guard -> Permission Service on the catalog action, a denial writes the
canonical "permission denied" AuditEvent and never a business row. In enforce the handler
still uses the legacy data handle, so — as SEC-01 ``money_write`` does — the resolved tenant
database must BE that handle and the identity's org must be the tenant (else 409).
"""
from fastapi import Depends, HTTPException

from app.db import db
from app.permissions.deps import require_legacy_data_path, require_permission
from app.tenancy.guard import TenantContext

FINANCE_ROLES = ("Admin", "Owner", "Accountant")


def _legacy_finance(user: dict, request) -> bool:
    return user.get("role") in FINANCE_ROLES


def require_client_act_right(action: str, *, resource_type: str = "client_act"):
    """Dependency for one client-act write / remainder read. Returns the session user."""
    permission = require_permission(action, module="M2", scope="company",
                                    resource_type=resource_type,
                                    legacy_check=_legacy_finance)

    async def dependency(ctx: TenantContext = Depends(permission)) -> dict:
        if ctx.enforced:
            await require_legacy_data_path(ctx, db)
            if ctx.user.get("org_id") != ctx.org_id:
                raise HTTPException(status_code=409, detail={
                    "error_code": "TENANT_DATA_PATH_NOT_MIGRATED",
                    "message": "This operation is not yet available when the active tenant "
                               "differs from the identity's legacy organization"})
        return ctx.user

    dependency.act01_action = action           # inspected by tests/test_act_01_*.py
    return dependency
