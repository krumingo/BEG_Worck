"""
W0-02 — Permission Service core (FLOW-002).

evaluate_permission() is the single authoritative authorization decision.
It reads ONLY the current RoleAssignment records for (user, tenant) from the
system database via the registry. It never reads role/permissions/scope from
the JWT (guardrail G2), and there is no cache: every call reads fresh, so a
revoke or expiry takes effect on the very next request.

Deny-by-default: no applicable, in-validity, active assignment => deny.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Callable, Any

from app.tenancy import registry
from app.permissions.catalog import role_actions

# --- decision reason codes -------------------------------------------------
ALLOWED = "ALLOWED"
REASON_NO_ASSIGNMENT = "NO_ASSIGNMENT"
REASON_ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
REASON_MODULE_NOT_ALLOWED = "MODULE_NOT_ALLOWED"
REASON_SCOPE_MISMATCH = "SCOPE_MISMATCH"
REASON_ASSIGNMENT_EXPIRED = "ASSIGNMENT_EXPIRED"
REASON_ASSIGNMENT_REVOKED = "ASSIGNMENT_REVOKED"
REASON_CROSS_TENANT = "CROSS_TENANT"
REASON_AMOUNT_LIMIT_EXCEEDED = "AMOUNT_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason_code: str
    effective_assignment_ids: List[str] = field(default_factory=list)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


async def _load_assignments(user_id: str, tenant_id: str) -> List[dict]:
    """All RoleAssignment records for (user, tenant), any status.

    Kept as a thin wrapper so tests can monkeypatch it without a database.
    """
    return await registry.list_role_assignments(user_id, tenant_id)


def _scope_covers(a_type: Optional[str], a_id: Optional[str],
                  req_type: Optional[str], req_id: Optional[str]) -> bool:
    """Containment: company >= any narrower scope; otherwise exact match.

    Note (PR-1 simplification): project->object containment across levels is
    not resolved here (it needs a project/object relation lookup). For the
    migrated routes the requested scope is either company or an exact
    project/object id, which this covers. Cross-level containment is a
    documented follow-up.
    """
    if a_type in (None, "company"):
        return True
    if req_type is None:
        # a company-level request cannot be satisfied by a narrower assignment
        return False
    return a_type == req_type and a_id == req_id


async def evaluate_permission(
    ctx,
    action: str,
    *,
    module: Optional[str] = None,
    scope_type: Optional[str] = None,
    scope_id: Optional[str] = None,
    amount: Optional[float] = None,
    resource_tenant_id: Optional[str] = None,
) -> PermissionDecision:
    """Authoritative decision. See module docstring."""
    # Cross-tenant: a resource that belongs to another tenant is never allowed,
    # regardless of role (guardrail: cross-tenant denied by default).
    if resource_tenant_id is not None and resource_tenant_id != ctx.tenant_id:
        return PermissionDecision(False, REASON_CROSS_TENANT, [])

    assignments = await _load_assignments(ctx.user_id, ctx.tenant_id)
    if not assignments:
        return PermissionDecision(False, REASON_NO_ASSIGNMENT, [])

    now = datetime.now(timezone.utc)
    matched: List[str] = []
    best_reason = REASON_ACTION_NOT_ALLOWED  # most informative denial seen

    for a in assignments:
        if a.get("status") == "revoked":
            best_reason = _prefer(best_reason, REASON_ASSIGNMENT_REVOKED)
            continue
        vf, vt = _parse(a.get("valid_from")), _parse(a.get("valid_to"))
        if (vf and now < vf) or (vt and now > vt):
            best_reason = _prefer(best_reason, REASON_ASSIGNMENT_EXPIRED)
            continue

        allowed_actions = set(a.get("permissions") or []) or role_actions(a.get("role_id", ""))
        if action not in allowed_actions:
            best_reason = _prefer(best_reason, REASON_ACTION_NOT_ALLOWED)
            continue

        a_module = a.get("module")
        if module and a_module and a_module != module:
            best_reason = _prefer(best_reason, REASON_MODULE_NOT_ALLOWED)
            continue

        if not _scope_covers(a.get("scope_type"), a.get("scope_id"), scope_type, scope_id):
            best_reason = _prefer(best_reason, REASON_SCOPE_MISMATCH)
            continue

        max_amount = a.get("max_amount")
        if amount is not None and max_amount is not None and amount > max_amount:
            best_reason = _prefer(best_reason, REASON_AMOUNT_LIMIT_EXCEEDED)
            continue

        matched.append(a["id"])

    if matched:
        return PermissionDecision(True, ALLOWED, matched)
    return PermissionDecision(False, best_reason, [])


# Order denial reasons from least to most specific, so the reported reason is
# the most useful one seen across assignments.
_REASON_RANK = {
    REASON_ACTION_NOT_ALLOWED: 0,
    REASON_MODULE_NOT_ALLOWED: 1,
    REASON_SCOPE_MISMATCH: 2,
    REASON_AMOUNT_LIMIT_EXCEEDED: 3,
    REASON_ASSIGNMENT_EXPIRED: 4,
    REASON_ASSIGNMENT_REVOKED: 5,
}


def _prefer(current: str, candidate: str) -> str:
    return candidate if _REASON_RANK.get(candidate, -1) > _REASON_RANK.get(current, -1) else current


async def has_permission(ctx, action: str, *, module=None, scope_type=None,
                         scope_id=None, amount=None, resource_tenant_id=None) -> bool:
    d = await evaluate_permission(ctx, action, module=module, scope_type=scope_type,
                                  scope_id=scope_id, amount=amount,
                                  resource_tenant_id=resource_tenant_id)
    return d.allowed


async def filter_readable(ctx, records: List[dict], action: str,
                          scope_getter: Callable[[dict], Any]) -> List[dict]:
    """Return only the records the user may read.

    scope_getter(record) -> (scope_type, scope_id). Denies silently (returns a
    shorter list) so the existence of forbidden records is not leaked.
    """
    out: List[dict] = []
    for r in records:
        stype, sid = scope_getter(r)
        if await has_permission(ctx, action, scope_type=stype, scope_id=sid,
                                resource_tenant_id=r.get("tenant_id") or r.get("org_id")):
            out.append(r)
    return out
