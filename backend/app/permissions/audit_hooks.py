"""
W0-02 — Permission audit hooks (writes through the canonical W0-04 store).

Permission changes and security-significant denials are recorded as canonical
AuditEvents (FLOW-040), retention class R3 (security/access). No JWT payloads
or secrets are ever passed in — build_event also masks secret-looking keys.
"""
from typing import Optional, Dict, Any

from app.audit.envelope import (
    build_event,
    ACTOR_HUMAN,
    ACTOR_AI,
    RESULT_DENIED,
    RETENTION_R3_SECURITY_ACCESS,
)
from app.audit.store import record_event
from app.permissions.catalog import is_significant_action, ALWAYS_AUDIT_REASONS

SOURCE_FLOW = "FLOW-002"


async def _audit_db(ctx):
    """Resolve the audit database for this tenant.

    In PR-1 the primary tenant's database is the operational database. Prefer
    the tenant-resolved handle; fall back to the global operational handle when
    the context is a compatibility context (off/shadow mode) that has no
    registry-backed database_name yet.
    """
    try:
        return await ctx.db()
    except Exception:
        from app.db import db as global_db
        return global_db


def should_audit_denial(action: str, reason_code: str) -> bool:
    return reason_code in ALWAYS_AUDIT_REASONS or is_significant_action(action)


async def audit_permission_change(
    ctx,
    kind: str,                      # "granted" | "updated" | "revoked" | "migrated"
    assignment: Dict[str, Any],
    *,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    actor_type: str = ACTOR_HUMAN,
) -> Dict[str, Any]:
    event = build_event(
        tenant_id=ctx.tenant_id,
        actor_type=actor_type,
        actor_id=ctx.user_id,
        action=f"permission.role_assignment.{kind}",
        source_flow=SOURCE_FLOW,
        retention_class=RETENTION_R3_SECURITY_ACCESS,
        entity_type="role_assignment",
        entity_id=assignment.get("id"),
        scope_type=assignment.get("scope_type"),
        scope_id=assignment.get("scope_id"),
        structured_diff={"before": before, "after": after},
        reason=reason or f"role_assignment {kind}",
        effective_role_assignments=[assignment.get("id")] if assignment.get("id") else [],
    )
    return await record_event(await _audit_db(ctx), event)


async def audit_permission_denied(
    ctx,
    action: str,
    *,
    module: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    scope_type: Optional[str] = None,
    scope_id: Optional[str] = None,
    decision=None,
    request=None,
    actor_type: str = ACTOR_HUMAN,
) -> Optional[Dict[str, Any]]:
    """Record a denial ONLY when it is security/business significant."""
    reason_code = getattr(decision, "reason_code", "DENIED")
    if not should_audit_denial(action, reason_code):
        return None

    tool_or_endpoint = None
    request_id = None
    if request is not None:
        try:
            tool_or_endpoint = f"{request.method} {request.url.path}"
            request_id = request.headers.get("x-request-id")
        except Exception:
            pass

    event = build_event(
        tenant_id=ctx.tenant_id,
        actor_type=actor_type,
        actor_id=ctx.user_id,
        action="permission.denied",
        source_flow=SOURCE_FLOW,
        retention_class=RETENTION_R3_SECURITY_ACCESS,
        result=RESULT_DENIED,
        entity_type=resource_type,
        entity_id=resource_id,
        scope_type=scope_type,
        scope_id=scope_id,
        effective_role_assignments=getattr(decision, "effective_assignment_ids", []) or [],
        error_code=reason_code,
        tool_or_endpoint=tool_or_endpoint,
        request_id=request_id,
        reason=f"denied {action} (module={module}, reason={reason_code})",
    )
    return await record_event(await _audit_db(ctx), event)
