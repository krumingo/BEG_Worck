"""
TASK 5C migration-readiness routes — DRY RUN ONLY.

Every endpoint here is read-only. The POST that would "execute" the
migration always returns 405 Method Not Allowed (the service refuses
with `MigrationExecutionRefusedError`). The reports provide inventory /
dry-run / verify so a later approved migration can be planned safely.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.db import db
from app.deps.auth import get_current_user
from app.tenancy.data_access import TenantData
from app.tenancy.guard import TenantContext
from app.permissions.deps import require_permission

from app.services.warehouse_movements.migration_readiness import (
    free_text_to_item_report,
    main_to_central_report,
    legacy_writer_inventory_report,
    ledger_batch_reconciliation_report,
    execute_migration,
)
from app.services.warehouse_movements.errors import (
    MigrationExecutionRefusedError,
    WarehouseMovementError,
)

router = APIRouter(prefix="/warehouse/migration-readiness", tags=["warehouse_migration"])


def _tenant_for(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


@router.get("/free-text-to-item")
async def free_text_to_item(
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.migration.readiness", module="warehouse")),
) -> Dict[str, Any]:
    tenant = _tenant_for(user)
    return await free_text_to_item_report(
        tenant.warehouse_transactions, tenant_id=tenant.org_id,
    )


@router.get("/main-to-central")
async def main_to_central(
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.migration.readiness", module="warehouse")),
) -> Dict[str, Any]:
    tenant = _tenant_for(user)
    return await main_to_central_report(
        tenant._db, tenant_id=tenant.org_id,  # pylint: disable=protected-access
    )


@router.get("/legacy-writer-inventory")
async def legacy_writer_inventory(
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.migration.readiness", module="warehouse")),
) -> Dict[str, Any]:
    return legacy_writer_inventory_report()


@router.get("/ledger-batch-reconciliation")
async def ledger_batch_reconciliation(
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.migration.readiness", module="warehouse")),
) -> Dict[str, Any]:
    tenant = _tenant_for(user)
    return await ledger_batch_reconciliation_report(
        tenant._db, tenant_id=tenant.org_id,  # pylint: disable=protected-access
    )


@router.post("/execute")
async def execute_migration_route(
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.migration.execute", module="warehouse")),
) -> None:
    """TASK 5C hard boundary: refuse any execute call."""
    try:
        await execute_migration()
    except MigrationExecutionRefusedError as exc:
        raise HTTPException(
            status_code=405,
            detail={"error_code": exc.error_code, "message": exc.message},
        ) from exc
    # Unreachable; the service always raises.
    raise HTTPException(status_code=500, detail={"error_code": "UNREACHABLE"})
