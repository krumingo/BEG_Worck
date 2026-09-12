"""W0-02 permission facade. Load DB-backed modules only when a public API is used.

Importing the package, catalog or validation helper does not create a DB client.
This changes import timing only; public service/dependency names are preserved.
"""
from importlib import import_module

_EXPORTS = {'PermissionDecision': ('app.permissions.service', 'PermissionDecision'), 'evaluate_permission': ('app.permissions.service', 'evaluate_permission'), 'has_permission': ('app.permissions.service', 'has_permission'), 'filter_readable': ('app.permissions.service', 'filter_readable'), 'ALLOWED': ('app.permissions.service', 'ALLOWED'), 'REASON_NO_ASSIGNMENT': ('app.permissions.service', 'REASON_NO_ASSIGNMENT'), 'REASON_ACTION_NOT_ALLOWED': ('app.permissions.service', 'REASON_ACTION_NOT_ALLOWED'), 'REASON_MODULE_NOT_ALLOWED': ('app.permissions.service', 'REASON_MODULE_NOT_ALLOWED'), 'REASON_SCOPE_MISMATCH': ('app.permissions.service', 'REASON_SCOPE_MISMATCH'), 'REASON_ASSIGNMENT_EXPIRED': ('app.permissions.service', 'REASON_ASSIGNMENT_EXPIRED'), 'REASON_ASSIGNMENT_REVOKED': ('app.permissions.service', 'REASON_ASSIGNMENT_REVOKED'), 'REASON_CROSS_TENANT': ('app.permissions.service', 'REASON_CROSS_TENANT'), 'REASON_AMOUNT_LIMIT_EXCEEDED': ('app.permissions.service', 'REASON_AMOUNT_LIMIT_EXCEEDED'), 'REASON_ASSIGNMENT_INACTIVE': ('app.permissions.service', 'REASON_ASSIGNMENT_INACTIVE'), 'REASON_ASSIGNMENT_INVALID': ('app.permissions.service', 'REASON_ASSIGNMENT_INVALID'), 'require_permission': ('app.permissions.deps', 'require_permission'), 'current_mode': ('app.permissions.deps', 'current_mode')}
__all__ = list(_EXPORTS)


def __getattr__(name):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, member = target
    value = getattr(import_module(module), member)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
