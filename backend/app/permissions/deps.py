"""
W0-02 — FastAPI dependency and feature-flag control for the Permission Service.

PERMISSION_SERVICE_MODE (env), read live on every request so it is testable:

  off     - existing behavior only; the new service NEVER blocks a request.
            The legacy check (if provided) decides, exactly as before.
  shadow  - the legacy check decides the response; the new service runs in
            parallel and the OLD vs NEW comparison is logged. The new service
            does NOT change the result.
  enforce - the decision for the migrated endpoint comes ONLY from
            Tenant Guard -> Permission Service. A legacy check can NOT override
            a DENY. There is NO fallback to user["role"].
"""
import os
import inspect
import logging
from typing import Optional, Callable, Awaitable, Any

from fastapi import Depends, HTTPException, Request

from app.deps.auth import get_current_user
from app.tenancy.guard import get_tenant_context, TenantContext
from app.permissions.service import evaluate_permission
from app.permissions.audit_hooks import audit_permission_denied

logger = logging.getLogger("permissions.shadow")

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"
_VALID_MODES = {MODE_OFF, MODE_SHADOW, MODE_ENFORCE}


def current_mode() -> str:
    mode = os.environ.get("PERMISSION_SERVICE_MODE", MODE_OFF).strip().lower()
    return mode if mode in _VALID_MODES else MODE_OFF


async def _run_legacy(legacy_check, user: dict, request: Request) -> Optional[bool]:
    if legacy_check is None:
        return None
    result = legacy_check(user, request)
    if inspect.isawaitable(result):
        result = await result
    return bool(result)


async def _safe_ctx(request: Request, user: dict) -> TenantContext:
    """Tenant context that never blocks the request (off / shadow).

    Falls back to a compatibility context built from the legacy org_id when the
    strict guard would raise. org_id is only a lookup aid here (guardrail G1);
    the canonical scope stays tenant_id.
    """
    try:
        return await get_tenant_context(request, user)
    except HTTPException:
        return TenantContext(
            tenant={"id": user.get("org_id"), "status": "active"},
            user=user,
        )


def _shadow_category(old_allow: Optional[bool], new_allow: bool) -> str:
    if old_allow is None:
        return "NEW_ONLY_ALLOW" if new_allow else "NEW_ONLY_DENY"
    o = "ALLOW" if old_allow else "DENY"
    n = "ALLOW" if new_allow else "DENY"
    return f"OLD_{o}_NEW_{n}"


def require_permission(
    action: str,
    *,
    module: Optional[str] = None,
    scope: Optional[str] = None,
    scope_id_param: Optional[str] = None,
    resource_type: Optional[str] = None,
    legacy_check: Optional[Callable[[dict, Request], Any]] = None,
    amount_getter: Optional[Callable[[Request], Optional[float]]] = None,
) -> Callable[..., Awaitable[TenantContext]]:
    """Build a FastAPI dependency that authorizes `action` for this route."""

    async def dependency(request: Request,
                         user: dict = Depends(get_current_user)) -> TenantContext:
        mode = current_mode()
        old_allow = await _run_legacy(legacy_check, user, request)

        # OFF: behave exactly as before; the new service never blocks.
        if mode == MODE_OFF:
            if legacy_check is not None and old_allow is False:
                raise HTTPException(status_code=403, detail="Access denied")
            return await _safe_ctx(request, user)

        # SHADOW / ENFORCE need a real evaluation.
        ctx = await _safe_ctx(request, user) if mode == MODE_SHADOW \
            else await get_tenant_context(request, user)

        scope_id = request.path_params.get(scope_id_param) if scope_id_param else None
        amount = amount_getter(request) if amount_getter else None
        decision = await evaluate_permission(
            ctx, action, module=module, scope_type=scope, scope_id=scope_id, amount=amount,
        )

        if mode == MODE_SHADOW:
            category = _shadow_category(old_allow, decision.allowed)
            if category in ("OLD_ALLOW_NEW_DENY", "OLD_DENY_NEW_ALLOW"):
                logger.warning(
                    "PERMISSION_SHADOW_MISMATCH category=%s action=%s route=%s "
                    "legacy_role=%s reason=%s scope=%s/%s",
                    category, action, request.url.path, user.get("role"),
                    decision.reason_code, scope, scope_id,
                )
            else:
                logger.info("PERMISSION_SHADOW category=%s action=%s route=%s",
                            category, action, request.url.path)
            # Legacy still decides the response in shadow.
            if legacy_check is not None and old_allow is False:
                raise HTTPException(status_code=403, detail="Access denied")
            return ctx

        # ENFORCE: only Tenant Guard -> Permission Service decides. No fallback.
        if not decision.allowed:
            await audit_permission_denied(
                ctx, action, module=module, resource_type=resource_type,
                resource_id=scope_id, scope_type=scope, scope_id=scope_id,
                decision=decision, request=request,
            )
            raise HTTPException(
                status_code=403,
                detail={"error_code": "PERMISSION_DENIED",
                        "reason": decision.reason_code, "action": action},
            )
        return ctx

    return dependency
