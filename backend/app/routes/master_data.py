"""
Master Data API (FLOW-032) — pending mapping and human review.

Six endpoints, one rule: an automated channel proposes, a person decides.

    POST   /api/master-data/pending              record a proposal (ai|ocr|excel|import)
    GET    /api/master-data/pending              the review queue
    GET    /api/master-data/pending/{id}/matches candidates for one proposal
    POST   /api/master-data/pending/{id}/approve map to an existing record, or create one
    POST   /api/master-data/pending/{id}/reject  close it; Master Data untouched
    GET    /api/master-data/{entity_type}/{id}   read one canonical record

Every endpoint takes its tenant from the W0-01 guard, never from the body. With
``MASTER_DATA_MODE=off`` — the deployed default — they answer honestly that the
feature is off rather than pretending to work.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.master_data import matching, models, pending as pending_mod, review, service
from app.master_data.deps import (
    MODE_OFF,
    MasterDataConfigError,
    MasterDataTenantContextMissing,
    current_mode,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.service import MasterDataAuditFailed, MasterDataRefused
from app.tenancy.guard import TenantContext, get_tenant_context

router = APIRouter(prefix="/master-data", tags=["Master Data"])


class ProposeBody(BaseModel):
    entity_type: str
    raw_value: str
    source_channel: str
    source_ref: Optional[str] = None
    model_and_version: Optional[str] = None


class ApproveBody(BaseModel):
    confirmation: bool = False
    canonical_entity_id: Optional[str] = None
    create_new: bool = False
    display_name: Optional[str] = None


class RejectBody(BaseModel):
    reason: str


def _mode_or_503() -> str:
    """A misconfigured mode is a server problem, not a client one."""
    try:
        return current_mode()
    except MasterDataConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _off_payload(mode: str) -> Dict[str, Any]:
    return {"mode": mode, "performed": False,
            "detail": "master data is off (MASTER_DATA_MODE)"}


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, MasterDataTenantContextMissing):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, MasterDataRefused):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, MasterDataInvalid):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, MasterDataAuditFailed):
        # The state may have changed but the evidence did not — never report success.
        return HTTPException(status_code=500, detail=str(exc))
    raise exc


@router.post("/pending", status_code=201)
async def create_pending(body: ProposeBody, ctx: TenantContext = Depends(get_tenant_context)):
    """Record what an automated channel could not recognise."""
    mode = _mode_or_503()
    try:
        outcome = await pending_mod.propose(
            ctx,
            entity_type=body.entity_type,
            raw_value=body.raw_value,
            source_channel=body.source_channel,
            source_ref=body.source_ref,
            model_and_version=body.model_and_version,
            mode=mode,
        )
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if not outcome.performed:
        return {"mode": outcome.mode, "performed": False,
                "would_perform": outcome.would_perform, "detail": outcome.reason}
    return {"mode": outcome.mode, "performed": True, "pending": outcome.pending}


@router.get("/pending")
async def list_pending(
    entity_type: Optional[str] = Query(default=None),
    status: str = Query(default=pending_mod.STATUS_PENDING),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """The review queue for this tenant."""
    mode = _mode_or_503()
    if mode == MODE_OFF:
        return {"mode": mode, "items": [], "detail": _off_payload(mode)["detail"]}
    try:
        items = await review.list_pending(ctx, entity_type=entity_type, status=status,
                                          limit=limit, mode=mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": mode, "count": len(items), "items": items}


@router.get("/pending/{pending_id}/matches")
async def pending_matches(
    pending_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Candidate Master records for one proposal.

    Read-only and non-binding: an exact match is shown, never applied.
    """
    mode = _mode_or_503()
    if mode == MODE_OFF:
        return {"mode": mode, "candidates": []}
    try:
        candidates = await review.suggest_matches(ctx, pending_id=pending_id,
                                                  limit=limit, mode=mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": mode, "count": len(candidates), "candidates": candidates,
            "note": "candidates only; approval is a human decision"}


@router.post("/pending/{pending_id}/approve")
async def approve_pending(
    pending_id: str,
    body: ApproveBody,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Map the proposal to an existing record, or create a new official one."""
    mode = _mode_or_503()
    try:
        outcome = await review.approve(
            ctx,
            pending_id=pending_id,
            confirmation=body.confirmation,
            canonical_entity_id=body.canonical_entity_id,
            create_new=body.create_new,
            display_name=body.display_name,
            mode=mode,
        )
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": outcome.mode, "performed": outcome.performed,
            "would_perform": outcome.would_perform, "entity_id": outcome.entity_id,
            "created_master": outcome.created_master, "detail": outcome.reason}


@router.post("/pending/{pending_id}/reject")
async def reject_pending(
    pending_id: str,
    body: RejectBody,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Close the proposal. No Master record is created, changed or merged."""
    mode = _mode_or_503()
    try:
        outcome = await review.reject(ctx, pending_id=pending_id, reason=body.reason, mode=mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": outcome.mode, "performed": outcome.performed,
            "would_perform": outcome.would_perform, "detail": outcome.reason}


@router.get("/{entity_type}/{entity_id}")
async def get_entity(entity_type: str, entity_id: str,
                     ctx: TenantContext = Depends(get_tenant_context)):
    """Read one canonical record, scoped to this tenant."""
    mode = _mode_or_503()
    if mode == MODE_OFF:
        return _off_payload(mode)
    if entity_type not in models.ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="unknown entity_type: %s" % entity_type)
    try:
        doc = await service.get_entity(ctx, entity_type=entity_type,
                                       entity_id=entity_id, mode=mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if not doc:
        raise HTTPException(status_code=404, detail="not found in this tenant")
    return doc
