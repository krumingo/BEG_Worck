"""
Read-only canonical warehouse views (TASK 5C).

These endpoints never write. They project directly off the canonical
ledger (`warehouse_transactions`) so the UI never shows stale projected
numbers inconsistent with the ledger. Permission scope is per project /
location; a user with no read grant for a location receives 403.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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


@router.get("/stock/{item_id}")
async def read_stock(
    item_id: str,
    location_type: str = Query(...),
    location_id: str = Query(...),
    state: str = Query("free"),
    user: dict = Depends(get_current_user),
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
    tenant = _tenant_for(user)
    return await stock_at(
        tenant.warehouse_transactions,
        tenant_id=tenant.org_id, item_id=item_id, location=key,
    )


@router.get("/balance/{item_id}")
async def read_balance_by_location(
    item_id: str,
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    tenant = _tenant_for(user)
    rows = await item_balance_by_location(
        tenant.warehouse_transactions,
        tenant_id=tenant.org_id, item_id=item_id,
    )
    return {"tenant_id": tenant.org_id, "item_id": item_id, "balances": rows}


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
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_history", module="warehouse")),
) -> Dict[str, Any]:
    await _authorize_resource_scope(
        ctx, action="warehouse.read_history",
        location_type=location_type, location_id=location_id,
        project_id=project_id,
    )
    tenant = _tenant_for(user)
    return await movement_history(
        tenant.warehouse_transactions,
        tenant_id=tenant.org_id, item_id=item_id,
        location_type=location_type, location_id=location_id,
        project_id=project_id, since_iso=since, until_iso=until,
        limit=limit, cursor_after=cursor_after,
    )


@router.get("/integrity-warnings")
async def read_integrity_warnings(
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    tenant = _tenant_for(user)
    return await integrity_warnings(
        tenant.warehouse_transactions, tenant_id=tenant.org_id,
    )
