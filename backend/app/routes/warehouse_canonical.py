"""
Canonical warehouse command routes (TASK 5C).

Every endpoint:

  * uses `require_permission(...)` from the Permission Service (enforce
    is the required mode for canonical writes; `off`/`shadow` are
    refused at the service level);
  * loads a tenant-scoped `TenantData` from the session user, never from
    a request field;
  * delegates to `CommandService.execute()` — the ONLY writer onto
    `warehouse_transactions`.

Routes are intentionally thin: no business logic lives here. On error
the service's typed `WarehouseMovementError` subclasses are rendered as
HTTP 4xx with their `error_code`.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, validator

from app.db import db, client as mongo_client
from app.deps.auth import get_current_user
from app.tenancy.data_access import TenantData
from app.tenancy.guard import TenantContext
from app.permissions.deps import require_permission

from app.services.warehouse_movements import (
    CanonicalAction,
    LocationKey,
    LocationType,
    MovementState,
    WarehouseMovementError,
)
from app.services.warehouse_movements.service import (
    CommandInput,
    CommandService,
)

router = APIRouter(prefix="/warehouse/canonical", tags=["warehouse_canonical"])


# -----------------------------------------------------------------------
# Request / response bodies
# -----------------------------------------------------------------------
class LocationBody(BaseModel):
    location_type: str
    location_id: str
    state: str = "free"

    def to_key(self) -> LocationKey:
        return LocationKey(
            location_type=LocationType(self.location_type),
            location_id=self.location_id,
            state=MovementState(self.state),
        )


class MovementCommandBody(BaseModel):
    """Request body for the canonical movement endpoint.

    CODEX C06: `confirmed_by`, `confirmed_at`, and
    `item_is_pending_mapping` were previously client-authored. They have
    been **removed** from the request contract — the server derives all
    three from storage and the authenticated session.
    """
    action: str
    item_id: str
    unit: str
    quantity: str
    idempotency_key: str = Field(..., min_length=1)
    source: Optional[LocationBody] = None
    destination: Optional[LocationBody] = None
    unit_value: Optional[str] = None
    currency: str = "BGN"
    lot_id: Optional[str] = None
    request_id: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_line_id: Optional[str] = None
    delivery_id: Optional[str] = None
    dispatch_movement_id: Optional[str] = None
    reservation_movement_id: Optional[str] = None
    project_id: Optional[str] = None
    subproject_id: Optional[str] = None
    smr_id: Optional[str] = None
    work_package_id: Optional[str] = None
    correlation_id: Optional[str] = None
    requested_quantity: Optional[str] = None
    accepted_quantity: Optional[str] = None
    file_ids: Optional[List[str]] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    corrects_movement_id: Optional[str] = None
    revision_evidence: Optional[Dict[str, Any]] = None
    occurred_at: Optional[str] = None

    @validator("action")
    def _known_action(cls, v: str) -> str:
        if v not in {a.value for a in CanonicalAction}:
            raise ValueError(f"unknown canonical action: {v!r}")
        return v


class MovementCommandResponse(BaseModel):
    movement_id: str
    audit_event_id: str
    replay: bool
    envelope: Dict[str, Any]


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------
def _service() -> CommandService:
    """A fresh CommandService over the shared Mongo client.

    Instances are cheap; keeping one around is fine but a per-request
    instance keeps tests independent.
    """
    return CommandService(mongo_client)


def _tenant_for(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


def _render_error(exc: WarehouseMovementError) -> HTTPException:
    """Map canonical errors to HTTP responses with stable error codes."""
    status = {
        "PERMISSION_DENIED": 403,
        "CROSS_TENANT": 403,
        "IDEMPOTENCY_CONFLICT": 409,
        "INVARIANT_VIOLATION": 422,
        "NEGATIVE_STOCK": 422,
        "ORIGIN_ACCEPTANCE_OVERRUN": 422,
        "QUARANTINE_STATE_VIOLATION": 422,
        "MASTER_IDENTITY_MISSING": 422,
        "FREE_TEXT_INTO_ACTIONABLE_STOCK": 422,
        "VALUE_FROM_CLIENT_REFUSED": 400,
        "INDEX_MISSING": 503,
        "TRANSACTIONS_NOT_SUPPORTED": 503,
        "AUDIT_CHAIN_WRITE_FAILED": 500,
        "FILE_REGISTRY_UNAVAILABLE": 503,
        "APPROVAL_RUNTIME_UNAVAILABLE": 503,
        "LEGACY_WRITER_RETIRED": 410,
        "UNKNOWN_ACTION": 400,
        "MIGRATION_EXECUTION_REFUSED": 405,
    }.get(exc.error_code, 500)
    return HTTPException(
        status_code=status,
        detail={"error_code": exc.error_code, "message": exc.message,
                "context": exc.context},
    )


# -----------------------------------------------------------------------
# Single canonical endpoint — the action chooses which movement is written.
# -----------------------------------------------------------------------
@router.post("/movements", response_model=MovementCommandResponse)
async def post_movement(
    body: MovementCommandBody,
    request: Request,
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.write_command",     # outer gate; per-action gate runs inside the service
        module="warehouse",
    )),
) -> MovementCommandResponse:
    """One endpoint; the `action` field in the body chooses the behavior.

    The outer `require_permission` is a coarse route gate (`warehouse.write_command`)
    kept wide so the service's per-action, per-scope gate decides. The
    service then calls `evaluate_permission` for the exact action string
    (`warehouse.receive_from_supplier`, `warehouse.consume_smr`, ...).
    """
    tenant = _tenant_for(user)
    service = _service()
    try:
        inp = CommandInput(
            action=CanonicalAction(body.action),
            tenant_id=tenant.org_id,
            actor_id=str(user.get("id") or user.get("_id") or "unknown"),
            item_id=body.item_id,
            unit=body.unit,
            quantity=Decimal(body.quantity),
            source=body.source.to_key() if body.source else None,
            destination=body.destination.to_key() if body.destination else None,
            idempotency_key=body.idempotency_key,
            unit_value=Decimal(body.unit_value) if body.unit_value else Decimal("0"),
            currency=body.currency,
            lot_id=body.lot_id,
            request_id=body.request_id,
            invoice_id=body.invoice_id,
            invoice_line_id=body.invoice_line_id,
            delivery_id=body.delivery_id,
            dispatch_movement_id=body.dispatch_movement_id,
            reservation_movement_id=body.reservation_movement_id,
            project_id=body.project_id,
            subproject_id=body.subproject_id,
            smr_id=body.smr_id,
            work_package_id=body.work_package_id,
            correlation_id=body.correlation_id,
            requested_quantity=body.requested_quantity,
            accepted_quantity=body.accepted_quantity,
            file_ids=body.file_ids,
            reason=body.reason,
            notes=body.notes,
            corrects_movement_id=body.corrects_movement_id,
            revision_evidence=body.revision_evidence,
            occurred_at=body.occurred_at,
            # C06: `confirmed_by`, `confirmed_at`, pending-mapping are
            # all SERVER-DERIVED by the command service — never
            # accepted from the request body.
        )
        result = await service.execute(
            ctx=ctx,
            tenant_db=tenant._db,            # pylint: disable=protected-access
            tenant_collection=tenant.warehouse_transactions,
            inp=inp,
        )
    except WarehouseMovementError as exc:
        raise _render_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "BAD_REQUEST",
                                                     "message": str(exc)})

    return MovementCommandResponse(
        movement_id=result.movement_id,
        audit_event_id=result.audit_event_id,
        replay=result.replay,
        envelope=result.envelope,
    )
