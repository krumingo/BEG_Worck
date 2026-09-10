"""
W0-02 — Permission Service (FLOW-002).

Central, authoritative authorization for BEG_Work. Authorization is read ONLY
from the current RoleAssignment records (system DB), never from the JWT role.

This package is additive. Existing routes keep working unchanged while
PERMISSION_SERVICE_MODE is 'off' (the default). See deps.py for the three modes.

Canon: FLOW-002. Predecessor: W0-01 Tenant Foundation (app/tenancy).
"""
from app.permissions.service import (
    PermissionDecision,
    evaluate_permission,
    has_permission,
    filter_readable,
    ALLOWED,
    REASON_NO_ASSIGNMENT,
    REASON_ACTION_NOT_ALLOWED,
    REASON_MODULE_NOT_ALLOWED,
    REASON_SCOPE_MISMATCH,
    REASON_ASSIGNMENT_EXPIRED,
    REASON_ASSIGNMENT_REVOKED,
    REASON_CROSS_TENANT,
    REASON_AMOUNT_LIMIT_EXCEEDED,
)
from app.permissions.deps import require_permission, current_mode

__all__ = [
    "PermissionDecision",
    "evaluate_permission",
    "has_permission",
    "filter_readable",
    "require_permission",
    "current_mode",
    "ALLOWED",
    "REASON_NO_ASSIGNMENT",
    "REASON_ACTION_NOT_ALLOWED",
    "REASON_MODULE_NOT_ALLOWED",
    "REASON_SCOPE_MISMATCH",
    "REASON_ASSIGNMENT_EXPIRED",
    "REASON_ASSIGNMENT_REVOKED",
    "REASON_CROSS_TENANT",
    "REASON_AMOUNT_LIMIT_EXCEEDED",
]
