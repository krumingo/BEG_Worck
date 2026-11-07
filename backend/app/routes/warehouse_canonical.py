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
    # 5C-C21 F-13 — the receiving warehouse of transfer_warehouse_to_warehouse
    # (credited only on acceptance; `destination` stays in_transit).
    transfer_target: Optional[LocationBody] = None

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


async def _response(ctx, result) -> "MovementCommandResponse":
    """FG-23 (Р20) / audit C26A-1 — the command response is the stored
    envelope (fresh or idempotent replay); a role without a finance right
    gets it without money (unit_value, layer_allocations[*].unit_value, …)."""
    from app.routes.warehouse_canonical_queries import _values_for
    # Р32 / Р34 / Р35: the envelope shows money only to the roles that see
    # it on THIS movement (a keeper never on an issue to a project).
    envelope = await _values_for(ctx, dict(result.envelope or {}), whole=True)
    return MovementCommandResponse(
        movement_id=result.movement_id, audit_event_id=result.audit_event_id,
        replay=result.replay, envelope=envelope)


def _tenant_for(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


def _render_error(exc: WarehouseMovementError) -> HTTPException:
    """Map canonical errors to HTTP responses with stable error codes."""
    status = {
        "PERMISSION_DENIED": 403,
        "CROSS_TENANT": 403,
        "IDEMPOTENCY_CONFLICT": 409,
        "INVARIANT_VIOLATION": 422,
        "INVOICE_LINE_PROJECT_MISMATCH": 422,
        "INVOICE_LINE_QTY_EXCEEDED": 422,
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
            transfer_target=body.transfer_target.to_key() if body.transfer_target else None,
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

    return await _response(ctx, result)


# -----------------------------------------------------------------------
# 5C-C26 Addendum B — Р27: a dedicated endpoint for the write-off („фира")
# FROM A PROJECT, gated by its own catalog action `warehouse.project_writeoff`
# (PROJECT_WRITEOFF_RULE) instead of the coarse `warehouse.write_command`.
# Every other warehouse command is unchanged.
# -----------------------------------------------------------------------
class ProjectWriteOffBody(BaseModel):
    project_id: str = Field(..., min_length=1)
    subproject_id: Optional[str] = None
    item_id: str
    unit: str
    quantity: str
    idempotency_key: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    file_ids: List[str] = Field(..., min_items=1)
    notes: Optional[str] = None
    occurred_at: Optional[str] = None


async def require_project_writeoff(
    request: Request, user: dict = Depends(get_current_user),
) -> TenantContext:
    """Route gate of POST /project-writeoff — resolves the session in EVERY
    Permission Service mode (5C-C26c). The Р27 decision needs the project
    from the body and runs in the handler BEFORE any write:
      * off / shadow — the legacy session role (LegacyCompatContext), same
        Р27 table (``ensure_project_write_off_legacy``); shadow also computes
        the RoleAssignment decision and only LOGS a mismatch;
      * enforce — Tenant Guard + RoleAssignments (``ensure_project_write_off``).
    """
    from app.permissions.deps import MODE_ENFORCE, current_mode
    from app.tenancy.guard import LegacyCompatContext, get_tenant_context
    mode = current_mode()
    if mode != MODE_ENFORCE:
        return LegacyCompatContext(user, mode=mode)
    ctx = await get_tenant_context(request, user)
    ctx.mode = mode
    return ctx


async def _r27_decide(ctx, user: dict, tenant, project_id: str, request) -> None:
    """Р27 in all three modes; raises PermissionDeniedError on a denial."""
    import logging
    from app.permissions.deps import MODE_ENFORCE, MODE_SHADOW
    from app.services.warehouse_movements.errors import PermissionDeniedError
    from app.services.warehouse_movements.write_off_policy import (
        ensure_project_write_off, ensure_project_write_off_legacy,
    )
    mode = getattr(ctx, "mode", None)
    if mode == MODE_ENFORCE:
        await ensure_project_write_off(
            ctx, tenant._db,                    # pylint: disable=protected-access
            org_id=tenant.org_id, project_id=project_id)
        return
    legacy_exc = None
    try:
        await ensure_project_write_off_legacy(
            user, tenant._db,                   # pylint: disable=protected-access
            org_id=tenant.org_id, project_id=project_id)
    except PermissionDeniedError as exc:
        legacy_exc = exc
    if mode == MODE_SHADOW:
        # Observe only: the new decision never changes the outcome.
        try:
            await ensure_project_write_off(
                ctx, tenant._db,                # pylint: disable=protected-access
                org_id=tenant.org_id, project_id=project_id)
            new_allow = True
        except Exception:                       # unverified counts as deny
            new_allow = False
        if new_allow != (legacy_exc is None):
            logging.getLogger(__name__).warning(
                "PERMISSION_SHADOW_MISMATCH action=warehouse.project_writeoff "
                "legacy_allow=%s new_allow=%s project=%s",
                legacy_exc is None, new_allow, project_id)
    if legacy_exc is not None:
        raise legacy_exc


@router.post("/project-writeoff", response_model=MovementCommandResponse,
             status_code=201)
async def post_project_writeoff(
    body: ProjectWriteOffBody,
    request: Request,
    user: dict = Depends(get_current_user),
    ctx: TenantContext = Depends(require_project_writeoff),
) -> MovementCommandResponse:
    from app.permissions.audit_hooks import audit_permission_denied
    from app.permissions.catalog import PROJECT_WRITEOFF_ACTION
    from app.services.warehouse_movements.errors import PermissionDeniedError
    from app.permissions.deps import MODE_ENFORCE
    tenant = _tenant_for(user)
    # 5C-C26d (C26B-1 / FG-38): with a subproject source the project is the
    # subproject's parent FROM THE DATABASE; Р27 is decided against that real
    # project. 5C-C26h (FG-55): the rights check runs FIRST — a parent
    # mismatch / unknown subproject (422) is answered only to a caller Р27
    # allows on the real project; everyone else gets the same 403.
    real_project = body.project_id
    binding_error = None
    if body.subproject_id:
        from app.services.warehouse_movements.errors import InvariantViolationError
        from app.services.warehouse_movements.service import resolve_subproject_parent
        try:
            real_project = await resolve_subproject_parent(
                tenant._db, tenant.org_id, body.subproject_id)  # pylint: disable=protected-access
        except WarehouseMovementError as exc:
            real_project, binding_error = body.subproject_id, exc
        if binding_error is None and real_project != body.project_id:
            binding_error = InvariantViolationError(
                "project_id must be the parent project of the subproject",
                context={"subproject_id": body.subproject_id,
                         "project_id": body.project_id})
    try:
        await _r27_decide(ctx, user, tenant, real_project, request)
    except PermissionDeniedError as exc:
        class _Decision:
            allowed = False
            reason_code = exc.context.get("reason_code", "DENIED")
        if getattr(ctx, "mode", None) == MODE_ENFORCE:
            # W0-02: the denial AuditEvent is written in enforce (the tenant
            # database is resolved there); off / shadow just refuse.
            await audit_permission_denied(
                ctx, PROJECT_WRITEOFF_ACTION, module="warehouse",
                resource_type="project", resource_id=real_project,
                scope_type="project", scope_id=real_project,
                decision=_Decision(), request=request)
        if body.subproject_id:
            # FG-55: the denial names only what the caller sent — never the
            # DB-resolved parent project.
            exc.context = dict(exc.context, scope_type="subproject",
                               scope_id=body.subproject_id)
        raise _render_error(exc) from exc
    if binding_error is not None:
        raise _render_error(binding_error)

    source_type = LocationType.SUBPROJECT if body.subproject_id else LocationType.PROJECT
    source_id = body.subproject_id or body.project_id
    service = _service()
    try:
        result = await service.execute(
            ctx=ctx,
            tenant_db=tenant._db,            # pylint: disable=protected-access
            tenant_collection=tenant.warehouse_transactions,
            inp=CommandInput(
                action=CanonicalAction.WRITE_OFF,
                tenant_id=tenant.org_id,
                actor_id=str(user.get("id") or user.get("_id") or "unknown"),
                item_id=body.item_id, unit=body.unit,
                quantity=Decimal(body.quantity),
                source=LocationKey(source_type, source_id),
                project_id=body.project_id,
                subproject_id=body.subproject_id,
                idempotency_key=body.idempotency_key,
                file_ids=body.file_ids, reason=body.reason, notes=body.notes,
                occurred_at=body.occurred_at,
            ),
        )
    except WarehouseMovementError as exc:
        raise _render_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "BAD_REQUEST",
                                                     "message": str(exc)})
    return await _response(ctx, result)
