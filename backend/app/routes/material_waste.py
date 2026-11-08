"""
Routes - Material Waste Tracking v1.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

from app.db import db
from app.deps.auth import get_current_user
from app.services.material_waste import build_material_waste_summary
from app.tenancy.data_access import TenantData


def _tenant(user: dict) -> TenantData:
    """The request's tenant — from the server-loaded session user only (W0-03E-A2C)."""
    return TenantData.for_user(db, user)

router = APIRouter(tags=["Material Waste"])


class WasteEntryCreate(BaseModel):
    material_name: str
    item_id: Optional[str] = None
    activity_type: Optional[str] = None
    smr_type: Optional[str] = None
    location_id: Optional[str] = None
    qty: float
    unit: str = "бр"
    waste_type: str = "damaged"
    notes: Optional[str] = None
    date: Optional[str] = None
    # WH-FIX-01 (FG-159) — the canonical write-off's inputs.
    subproject_id: Optional[str] = None
    file_ids: Optional[List[str]] = None
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None
    occurred_at: Optional[str] = None


@router.get("/projects/{project_id}/material-waste")
async def get_material_waste(
    project_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    return await build_material_waste_summary(user["org_id"], project_id, date_from, date_to)


@router.get("/projects/{project_id}/material-waste/compact")
async def get_compact_waste(project_id: str, user: dict = Depends(get_current_user)):
    full = await build_material_waste_summary(user["org_id"], project_id)
    materials = full["materials"]
    return {
        "summary": full["summary"],
        "top_overuse": sorted([m for m in materials if m["status"] == "overuse"], key=lambda x: x["variance_vs_planned"], reverse=True)[:5],
        "top_waste": sorted(materials, key=lambda x: x["wasted_qty"], reverse=True)[:5],
    }


@router.post("/projects/{project_id}/material-waste", status_code=201)
async def create_waste_entry(project_id: str, data: WasteEntryCreate, request: Request,
                             user: dict = Depends(get_current_user),
                             idempotency_key_header: Optional[str] = Header(
                                 None, alias="Idempotency-Key")):
    """WH-FIX-01 (FG-159, Р10 / Р27 / Р37; FLOW-009): a waste („фира") from
    the project is a CANONICAL write-off movement through the single writer
    (the same path as POST /warehouse/canonical/project-writeoff): Р27
    rights in every mode, a FIFO value from the ledger (never from the
    client), evidence, an Idempotency-Key and the AuditEvent of the command
    service. The former free row in `material_waste_entries` (no value, no
    movement, no rights, no AuditEvent) is no longer written; the register
    stays readable as history.

    Required: `item_id` (a Master item — free text cannot be written off),
    `file_ids` (evidence), an `Idempotency-Key` header (or
    `idempotency_key`) and a reason (`reason`, else the `waste_type`)."""
    from app.routes import warehouse_canonical as canon
    # WHFIX81-05: the Р27 rights are decided FIRST (as the canonical endpoint,
    # FG-55): a caller without the right gets 403 whatever the body holds.
    ctx = await canon.require_project_writeoff(request, user)
    await _r27_first(canon, ctx, user, project_id, data.subproject_id, request)
    if not data.item_id:
        raise HTTPException(status_code=422, detail={
            "error_code": "MASTER_IDENTITY_MISSING",
            "message": "a waste needs a Master item (item_id); free text cannot be written off"})
    key = (idempotency_key_header or data.idempotency_key or "").strip()
    if not key:
        raise HTTPException(status_code=428, detail={
            "error_code": "IDEMPOTENCY_KEY_REQUIRED",
            "message": "send an Idempotency-Key header"})
    reason = (data.reason or data.waste_type or "").strip()
    try:
        body = canon.ProjectWriteOffBody(
            project_id=project_id, subproject_id=data.subproject_id,
            item_id=data.item_id, unit=data.unit, quantity=str(data.qty),
            idempotency_key=key, reason=reason, file_ids=data.file_ids or [],
            notes=data.notes, occurred_at=data.occurred_at)
    except Exception as exc:                      # pydantic validation → 422
        raise HTTPException(status_code=422, detail={
            "error_code": "INVALID_WASTE", "message": str(exc)})
    result = await canon.post_project_writeoff(body, request, user=user, ctx=ctx)
    return {"movement_id": result.movement_id, "audit_event_id": result.audit_event_id,
            "replay": result.replay, "envelope": result.envelope,
            "source": "warehouse_write_off"}


async def _r27_first(canon, ctx, user, project_id, subproject_id, request) -> None:
    """Р27 on the project (a subproject → its DB parent) in every mode; the
    denial is audited in enforce exactly as POST /project-writeoff does."""
    from app.permissions.audit_hooks import audit_permission_denied
    from app.permissions.catalog import PROJECT_WRITEOFF_ACTION
    from app.permissions.deps import MODE_ENFORCE
    from app.services.warehouse_movements.errors import (
        PermissionDeniedError, WarehouseMovementError,
    )
    tenant = canon._tenant_for(user)
    real = project_id
    if subproject_id:
        from app.services.warehouse_movements.service import resolve_subproject_parent
        try:
            real = await resolve_subproject_parent(tenant._db, tenant.org_id, subproject_id)
        except WarehouseMovementError:
            real = subproject_id
    try:
        await canon._r27_decide(ctx, user, tenant, real, request)
    except PermissionDeniedError as exc:
        if getattr(ctx, "mode", None) == MODE_ENFORCE:
            class _Decision:
                allowed = False
                reason_code = exc.context.get("reason_code", "DENIED")
            await audit_permission_denied(
                ctx, PROJECT_WRITEOFF_ACTION, module="warehouse", resource_type="project",
                resource_id=real, scope_type="project", scope_id=real,
                decision=_Decision(), request=request)
        raise canon._render_error(exc) from exc


@router.get("/projects/{project_id}/material-waste/log")
async def get_waste_log(project_id: str, user: dict = Depends(get_current_user)):
    tenant = _tenant(user)
    items = await tenant.material_waste_entries.find(
        {"org_id": user["org_id"], "project_id": project_id}, {"_id": 0}
    ).sort("date", -1).to_list(200)
    return {"items": items, "total": len(items)}
