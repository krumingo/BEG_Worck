"""
Read-only canonical warehouse views (TASK 5C).

These endpoints never write. They project directly off the canonical
ledger (`warehouse_transactions`) so the UI never shows stale projected
numbers inconsistent with the ledger. Permission scope is per project /
location; a user with no read grant for a location receives 403.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.db import db
from app.deps.auth import get_current_user
from app.tenancy.data_access import TenantData
from app.tenancy.guard import TenantContext
from app.permissions.deps import require_permission

from app.services.warehouse_movements import LocationKey, LocationType, MovementState
from app.services.warehouse_movements.queries import (
    item_balance_by_location,
    movement_history,
    stock_at,
    integrity_warnings,
)
from app.services.warehouse_movements.errors import WarehouseMovementError
from app.permissions.service import evaluate_permission


router = APIRouter(prefix="/warehouse/canonical", tags=["warehouse_canonical_queries"])


def _tenant_for(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


async def _authorized_scope_locations(ctx, user) -> Optional[List]:
    """Return the (scope_type, scope_id) tuples the caller is allowed
    to see at project / location granularity, computed via the REAL
    Permission Service decision engine (CODEX C13.5).

    * `None` means the caller holds a company-level (module-wide) grant
      for `warehouse.read_stock` — they see everything.
    * `[]` means the caller holds NO relevant grant — they see
      NOTHING. The caller must deny or return empty; NOT fall back to
      unrestricted (which would be fail-open).
    * `[(scope_type, scope_id), ...]` is the exact authorized set.

    No JWT-embedded assignments; no `role_assignments` on the user
    dict. The Permission Service's own `_evaluate_one` decides each
    assignment under the same semantics `evaluate_permission` uses on
    the write path, so a RoleAssignment that is EXPIRED
    (`valid_to` < now), REVOKED (`status="revoked"`), WRONG MODULE
    (`module != "warehouse"`), or that lacks `warehouse.read_stock`
    is denied by `_evaluate_one` and never contributes to the scope
    set — matching the write-path semantics exactly.

    Required inputs: `ctx.user_id` and `ctx.tenant_id`. If the ctx
    does not carry them, we treat the session as absent and return
    `[]` (deny-closed), never fall back to the user dict's embedded
    identity.
    """
    from app.permissions.service import (
        _load_assignments, _evaluate_one, ALLOWED,
    )
    from datetime import datetime, timezone

    user_id = getattr(ctx, "user_id", None) if ctx is not None else None
    tenant_id = getattr(ctx, "tenant_id", None) if ctx is not None else None
    if not user_id or not tenant_id:
        # No server-resolved session identity → deny-closed. We do
        # NOT fall back to the raw user dict's `id`/`org_id`: the
        # TenantContext is the only authority.
        return []

    assignments = await _load_assignments(user_id, tenant_id)
    if not assignments:
        return []

    now = datetime.now(timezone.utc)
    allowed: List[Tuple[str, str]] = []
    for a in assignments:
        # Walk every assignment through the SAME decision engine the
        # write path uses. We ask it to decide against the exact
        # scope the assignment carries, so a project-scoped grant is
        # tested at ("project", <id>), a location-scoped grant at
        # ("location", <id>), and a company grant at (None, None).
        a_scope_type = a.get("scope_type")
        a_scope_id = a.get("scope_id")
        try:
            reason = _evaluate_one(
                a, "warehouse.read_stock",
                module="warehouse",
                scope_type=a_scope_type if a_scope_type != "company" else None,
                scope_id=a_scope_id if a_scope_type != "company" else None,
                amount=None, now=now,
            )
        except Exception:
            # Malformed assignment: deny itself only. Never a crash
            # of the whole walk.
            continue
        if reason is not ALLOWED:
            continue
        # The assignment is live, in-window, carries the capability,
        # and matches the warehouse module. Its granted scope now
        # enters the authorized set.
        if a_scope_type in (None, "company"):
            # Company-wide grant = unrestricted — short-circuit.
            return None
        if a_scope_type and a_scope_id:
            allowed.append((a_scope_type, a_scope_id))
    # Deny-by-default: empty list means EMPTY RESULT, not unrestricted.
    return allowed


async def _authorize_resource_scope(
    ctx: TenantContext, *, action: str,
    location_type: Optional[str], location_id: Optional[str],
    project_id: Optional[str],
) -> None:
    """CODEX C06 — reads enforce RESOURCE scope, not just module.

    If the caller references a specific location or project, the
    Permission Service re-evaluates `action` against that exact scope;
    a module-wide grant is NOT enough to look at every warehouse.
    """
    scopes = []
    if project_id:
        scopes.append(("project", project_id))
    if location_id and location_type not in {
        None, LocationType.IN_TRANSIT.value,
        LocationType.UNRESOLVED.value,
        LocationType.SUPPLIER.value,
    }:
        scopes.append(("location", location_id))
    for scope_type, scope_id in scopes:
        decision = await evaluate_permission(
            ctx, action, module="warehouse",
            scope_type=scope_type, scope_id=scope_id,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail={
                "error_code": "PERMISSION_DENIED",
                "action": action,
                "scope_type": scope_type,
                "scope_id": scope_id,
            })


def _tenant_from_ctx(ctx: TenantContext) -> TenantData:
    """CODEX C13.5 — build the data path from the server-resolved
    TenantContext, NEVER from the raw user dict.

    `require_permission(...)` already resolves `ctx.tenant_id` on the
    server; using it here means the data layer sees exactly the tenant
    the Permission Service decided on, and cross-tenant leakage via a
    forged `user["org_id"]` is impossible.
    """
    return TenantData.for_resolved_org(db, ctx.org_id)


# ───────────── FG-23 (Р20) — money only for finance roles ─────────────
# Р20 (Крум 06.11.2026): the company's money is seen only by Owner / Admin /
# Accountant. Warehouse, site_manager, technician, viewer, driver (and every
# other role) see the canonical stock and history as QUANTITIES only — no
# total_value, unit_value or valued layers. Decided from the caller's active
# RoleAssignments (same records / validity as the Permission Service).
FINANCE_VALUE_ROLES = frozenset({"owner", "admin", "accountant"})
VALUE_KEYS = frozenset({"unit_value", "total_value", "movement_value", "value",
                        "line_value", "layer_value"})


async def _sees_values(ctx) -> bool:
    from datetime import datetime, timezone
    from app.permissions import service as perm
    from app.services.warehouse_movements.write_off_policy import _active_assignments
    user_id = getattr(ctx, "user_id", None)
    tenant_id = getattr(ctx, "tenant_id", None)
    if not user_id or not tenant_id:
        return False
    active = _active_assignments(await perm._load_assignments(user_id, tenant_id),
                                 datetime.now(timezone.utc))
    return any(a.get("role_id") in FINANCE_VALUE_ROLES for a in active)


def strip_values(obj: Any) -> Any:
    """Drop every money key (recursively); quantities stay."""
    if isinstance(obj, dict):
        return {k: strip_values(v) for k, v in obj.items() if k not in VALUE_KEYS}
    if isinstance(obj, list):
        return [strip_values(v) for v in obj]
    return obj


async def _values_for(ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    if await _sees_values(ctx):
        return data
    out = strip_values(data)
    out["values_hidden"] = True       # FG-23 / Р20 — the screen shows quantities only
    return out


@router.get("/stock/{item_id}")
async def read_stock(
    item_id: str,
    location_type: str = Query(...),
    location_id: str = Query(...),
    state: str = Query("free"),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    try:
        key = LocationKey(
            location_type=LocationType(location_type),
            location_id=location_id,
            state=MovementState(state),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "BAD_LOCATION",
                                                     "message": str(exc)})
    await _authorize_resource_scope(
        ctx, action="warehouse.read_stock",
        location_type=location_type, location_id=location_id, project_id=None,
    )
    tenant = _tenant_from_ctx(ctx)
    return await _values_for(ctx, await stock_at(
        tenant.warehouse_transactions,
        tenant_id=ctx.tenant_id, item_id=item_id, location=key,
    ))


@router.get("/balance/{item_id}")
async def read_balance_by_location(
    item_id: str,
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    """CODEX C11.7 + C13.5 — balances are filtered by the caller's
    authorized location/project RoleAssignments, resolved via the
    real Permission Service decision engine against the
    server-resolved TenantContext. A caller permitted on warehouse A
    but not B will not see B's balance here; expired/revoked grants
    deny; empty-grant → empty result.
    """
    tenant = _tenant_from_ctx(ctx)
    allowed = await _authorized_scope_locations(ctx, user=None)
    rows = await item_balance_by_location(
        tenant.warehouse_transactions,
        tenant_id=ctx.tenant_id, item_id=item_id,
        allowed_locations=allowed,
    )
    from app.services.warehouse_movements.queries import ledger_checkpoint
    checkpoint = await ledger_checkpoint(
        tenant.warehouse_transactions, tenant_id=ctx.tenant_id,
    )
    return {
        "tenant_id": ctx.tenant_id,
        "item_id": item_id,
        "balances": rows,
        "ledger_checkpoint": checkpoint,
    }


@router.get("/history")
async def read_history(
    item_id: Optional[str] = None,
    location_type: Optional[str] = None,
    location_id: Optional[str] = None,
    project_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    cursor_after: Optional[str] = None,
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_history", module="warehouse")),
) -> Dict[str, Any]:
    await _authorize_resource_scope(
        ctx, action="warehouse.read_history",
        location_type=location_type, location_id=location_id,
        project_id=project_id,
    )
    tenant = _tenant_from_ctx(ctx)
    return await _values_for(ctx, await movement_history(
        tenant.warehouse_transactions,
        tenant_id=ctx.tenant_id, item_id=item_id,
        location_type=location_type, location_id=location_id,
        project_id=project_id, since_iso=since, until_iso=until,
        limit=limit, cursor_after=cursor_after,
    ))


PROJECT_SCOPED_WARNING_CODES = frozenset({
    "UNRESOLVED_IN_TRANSIT_AGING",
    # 5C-C26 — Path B overlap warnings are about one project.
    "PATH_B_LEGACY_OVERLAP_UNPROVEN", "PATH_B_LINK_QTY_UNVERIFIED",
    "PATH_B_LINK_AMBIGUOUS",
})


@router.get("/integrity-warnings")
async def read_integrity_warnings(
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    """CODEX C11.7 + C13.5 — integrity warnings are filtered to the
    caller's authorized locations/projects, resolved via the real
    Permission Service decision engine. Owner/Admin sees everything
    (their scope includes every warehouse); a scoped operator sees
    only warnings in their own scope. Expired/revoked RoleAssignments
    deny.
    """
    tenant = _tenant_from_ctx(ctx)
    data = await integrity_warnings(
        tenant.warehouse_transactions, tenant_id=ctx.tenant_id,
    )
    # 5C-C26 (FG-17 per FLOW-043 D-04) — Path A / Path B overlaps that the
    # data cannot prove (or whose quantity cannot be verified), per project,
    # from the same helper every finance report uses.
    from app.services.canonical_material_cost import path_b_integrity_warnings
    data["warnings"].extend(await path_b_integrity_warnings(tenant, ctx.tenant_id))
    allowed = await _authorized_scope_locations(ctx, user=None)
    if allowed is not None:
        allowed_set = {tuple(x) for x in allowed}
        filtered = []
        for w in data.get("warnings", []):
            loc = w.get("location")
            dispatch_loc = ("warehouse", loc.get("id")) if loc else None
            if loc and (loc.get("type"), loc.get("id")) not in allowed_set:
                continue
            if w.get("code") in PROJECT_SCOPED_WARNING_CODES:
                # scope match on project
                if w.get("project_id") and ("project", w["project_id"]) not in allowed_set:
                    continue
            filtered.append(w)
        data["warnings"] = filtered
        data["scope"] = "authorized_subset"
    return data
