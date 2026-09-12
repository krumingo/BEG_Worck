"""
W0-02 — FastAPI dependency and feature-flag control for the Permission Service.

PERMISSION_SERVICE_MODE (env), read ONCE per operation (fixed on the returned
context as ``ctx.mode``; handlers must not re-read it):

  off     - existing behavior only. The legacy check (if provided) decides,
            exactly as before, on the legacy data path (LegacyCompatContext).
            NO registry lookup, NO evaluation, NO sync (PR-05).
  shadow  - the legacy check decides the response and the business action runs
            exactly once. The new service is evaluated in parallel and the
            OLD vs NEW comparison is logged. A failed/timed-out evaluation is
            reported as PERMISSION_SHADOW_EVALUATION_FAILED — never as parity,
            ALLOW or a successful sync.
  enforce - the decision for the migrated endpoint comes ONLY from
            Tenant Guard -> Permission Service, and the context is the
            registry-resolved active tenant (authorization, resource ownership,
            database handle and audit database are the same tenant — PR-04).
            A legacy check can NOT override a DENY. There is NO fallback to
            user["role"], and an unknown state (resolver/evaluation error) is
            an error, never an ALLOW.
"""
import os
import asyncio
import inspect
import logging
from typing import Optional, Callable, Awaitable, Any

from fastapi import Depends, HTTPException, Request

from app.deps.auth import get_current_user
from app.tenancy.guard import get_tenant_context, TenantContext, LegacyCompatContext
from app.permissions.service import evaluate_permission
from app.permissions.audit_hooks import audit_permission_denied

logger = logging.getLogger("permissions.shadow")

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"
_VALID_MODES = {MODE_OFF, MODE_SHADOW, MODE_ENFORCE}

# Upper bound for the parallel evaluation in shadow mode. A slow registry must
# never slow down or fail the legacy request path.
SHADOW_EVALUATION_TIMEOUT_S = float(os.environ.get("PERMISSION_SHADOW_TIMEOUT_S", "2.0"))

SHADOW_EVALUATION_FAILED = "SHADOW_EVALUATION_FAILED"


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


def _shadow_category(old_allow: Optional[bool], new_allow: Optional[bool]) -> str:
    if new_allow is None:
        return SHADOW_EVALUATION_FAILED
    if old_allow is None:
        return "NEW_ONLY_ALLOW" if new_allow else "NEW_ONLY_DENY"
    o = "ALLOW" if old_allow else "DENY"
    n = "ALLOW" if new_allow else "DENY"
    return f"OLD_{o}_NEW_{n}"


async def _shadow_evaluate(ctx, action, module, scope, scope_id, amount):
    """Parallel evaluation that can only OBSERVE. Returns the decision or None
    (failed / timed out), never raises into the legacy request."""
    try:
        return await asyncio.wait_for(
            evaluate_permission(ctx, action, module=module, scope_type=scope,
                                scope_id=scope_id, amount=amount),
            timeout=SHADOW_EVALUATION_TIMEOUT_S)
    except Exception as exc:  # includes asyncio.TimeoutError
        logger.warning("PERMISSION_%s action=%s route=%s error=%s",
                       SHADOW_EVALUATION_FAILED, action, getattr(ctx, "_route", "?"),
                       f"{type(exc).__name__}: {exc}")
        return None


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
        mode = current_mode()   # fixed once for the whole operation (PR-05)

        # OFF: behave exactly as before; the new service never runs, never
        # blocks, never looks anything up. Legacy data path.
        if mode == MODE_OFF:
            if legacy_check is not None and (await _run_legacy(legacy_check, user, request)) is False:
                raise HTTPException(status_code=403, detail="Access denied")
            return LegacyCompatContext(user, mode=mode)

        scope_id = request.path_params.get(scope_id_param) if scope_id_param else None
        amount = amount_getter(request) if amount_getter else None

        if mode == MODE_SHADOW:
            # Legacy decides; legacy data path. The new evaluation only observes.
            old_allow = await _run_legacy(legacy_check, user, request)
            ctx = LegacyCompatContext(user, mode=mode)
            ctx._route = request.url.path
            decision = await _shadow_evaluate(ctx, action, module, scope, scope_id, amount)
            new_allow = None if decision is None else decision.allowed
            category = _shadow_category(old_allow, new_allow)
            if category in ("OLD_ALLOW_NEW_DENY", "OLD_DENY_NEW_ALLOW"):
                logger.warning(
                    "PERMISSION_SHADOW_MISMATCH category=%s action=%s route=%s "
                    "legacy_role=%s reason=%s scope=%s/%s",
                    category, action, request.url.path, user.get("role"),
                    decision.reason_code, scope, scope_id,
                )
            elif category == SHADOW_EVALUATION_FAILED:
                logger.warning("PERMISSION_SHADOW category=%s action=%s route=%s (unverified)",
                               category, action, request.url.path)
            else:
                logger.info("PERMISSION_SHADOW category=%s action=%s route=%s",
                            category, action, request.url.path)
            if legacy_check is not None and old_allow is False:
                raise HTTPException(status_code=403, detail="Access denied")
            return ctx

        # ENFORCE: only Tenant Guard -> Permission Service decides. No fallback:
        # a resolver error propagates as its own HTTP error, never as ALLOW.
        ctx = await get_tenant_context(request, user)
        ctx.mode = mode
        decision = await evaluate_permission(
            ctx, action, module=module, scope_type=scope, scope_id=scope_id, amount=amount,
        )
        if not decision.allowed:
            # Denial audit goes to the SAME tenant's database (PR-04). If it
            # cannot be written the request fails; no business write follows.
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


async def require_legacy_data_path(ctx: TenantContext, legacy_db) -> None:
    """PR-04 §5 guard for handlers/helpers that still use the legacy global
    database handle. In enforce, the resolved tenant database MUST be that
    handle; otherwise the operation is refused (409) BEFORE any write, because
    it would authorize against one tenant and touch another tenant's data.
    """
    if not ctx.enforced:
        return
    if not await ctx.data_path_matches(legacy_db):
        raise HTTPException(
            status_code=409,
            detail={"error_code": "TENANT_DATA_PATH_NOT_MIGRATED",
                    "message": "This operation is not yet available for a tenant whose "
                               "database differs from the legacy installation database"},
        )
