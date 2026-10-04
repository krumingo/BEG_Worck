"""
W0-06B — the FLOW-002 check in front of every storage and file-access action.

Every consequential call of :mod:`app.files.storage`, :mod:`app.files.access`
and :mod:`app.files.integrity` passes through :func:`authorize` BEFORE it
touches a provider or the registry. The decision is the W0-02 Permission
Service's (``app.permissions.service.evaluate_permission``): fresh
RoleAssignments, deny by default, no cache, no JWT claims.

Two rules are added here because they are about FILES, not roles:

* the context's tenant must be the tenant whose view the service holds — a
  caller of tenant B asking tenant A's service is refused as ``CROSS_TENANT``
  before any assignment is even read;
* a file's sensitivity is an extra, narrower right (FLOW-016: access to an
  object does not grant payroll, bank, personal or internal financial files) —
  :func:`sensitivity_action` names the action a restricted or confidential file
  additionally requires.
"""
from __future__ import annotations

from typing import Any, Optional

from app.files import models as m
from app.permissions import service as permission_service

CROSS_TENANT = permission_service.REASON_CROSS_TENANT

SENSITIVITY_ACTIONS = {
    m.SENSITIVITY_RESTRICTED: "file.sensitivity.restricted",
    m.SENSITIVITY_CONFIDENTIAL: "file.sensitivity.confidential",
}


class FileAccessDenied(PermissionError):
    """FLOW-002 refused the action. Carries the action and the reason code."""

    def __init__(self, action: str, reason_code: str):
        super().__init__("%s denied: %s" % (action, reason_code))
        self.action = action
        self.reason_code = reason_code


def sensitivity_action(sensitivity: Optional[str]) -> Optional[str]:
    return SENSITIVITY_ACTIONS.get(sensitivity or m.SENSITIVITY_STANDARD)


async def authorize(ctx: Any, action: str, *, org_id: str, scope_type: Optional[str] = None,
                    scope_id: Optional[str] = None):
    """Allow or raise :class:`FileAccessDenied`. Never widens anything."""
    if ctx is None or not getattr(ctx, "user_id", None):
        raise FileAccessDenied(action, "NO_SESSION")
    if getattr(ctx, "tenant_id", None) != org_id:
        raise FileAccessDenied(action, CROSS_TENANT)
    decision = await permission_service.evaluate_permission(
        ctx, action, scope_type=scope_type, scope_id=scope_id, resource_tenant_id=org_id)
    if not decision.allowed:
        raise FileAccessDenied(action, decision.reason_code)
    return decision
