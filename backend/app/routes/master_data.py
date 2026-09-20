"""
Master Data API (FLOW-032) — pending mapping and human review.

Six endpoints, one rule: an automated channel proposes, a person decides.

    POST   /api/master-data/pending              record a proposal (ai|ocr|excel|import)
    GET    /api/master-data/pending              the review queue
    GET    /api/master-data/pending/{id}/matches candidates for one proposal
    POST   /api/master-data/pending/{id}/approve map to an existing record, or create one
    POST   /api/master-data/pending/{id}/reject  close it; Master Data untouched
    GET    /api/master-data/{entity_type}/{id}   read one canonical record

Everything a request must pass before a handler runs lives in ``_guard`` below,
in a fixed order, so no endpoint can get it wrong by accident:

  1. **the mode**, from a single validator. A typo in ``MASTER_DATA_MODE``
     refuses with 503 before authorization, before a tenant is resolved, before
     a repository exists, before Mongo and before audit;
  2. **authorization** for the specific canonical action. A forbidden user is
     refused here — before any repository, any tenant database and any write;
  3. **off is inert**: the guard returns without resolving a tenant, without
     importing the resolver, without building a repository and without an audit
     call. The handler answers honestly that the feature is off;
  4. only ``shadow`` and ``enforce`` resolve a tenant, and only through the
     existing W0-01 guard — server-side, never from the body, the query string
     or a header (D-15).

Authentication itself (``get_current_user``) reads the user document; that is
the platform's existing auth path, the same one every other route uses, and it
is deliberately outside this boundary. What the off-inertness tests assert is
that no Master Data machinery — resolver, registry, repository, audit — is
touched.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.deps.auth import get_current_user
from app.master_data import models, pending as pending_mod, review, service
from app.master_data.deps import (
    MODE_OFF,
    MasterDataConfigError,
    MasterDataTenantContextMissing,
    current_mode,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.service import MasterDataAuditFailed, MasterDataRefused
from app.permissions import catalog, deps as permission_deps
from app.tenancy.guard import TenantContext, get_tenant_context

router = APIRouter(prefix="/master-data", tags=["Master Data"])

# --- canonical actions (app/permissions/catalog.py) -------------------------
ACTION_PROPOSE = "master_data.pending.propose"
ACTION_PENDING_READ = "master_data.pending.read"
ACTION_APPROVE = "master_data.pending.approve"
ACTION_REJECT = "master_data.pending.reject"
ACTION_ENTITY_READ = "master_data.entity.read"


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


class Gate:
    """What every Master Data handler receives: a validated mode, and — only
    when the mode is not ``off`` — a server-side resolved tenant context."""

    __slots__ = ("mode", "ctx", "action")

    def __init__(self, mode: str, action: str, ctx: Optional[TenantContext] = None):
        self.mode = mode
        self.action = action
        self.ctx = ctx

    @property
    def off(self) -> bool:
        return self.mode == MODE_OFF


def _mode_or_503() -> str:
    """A misconfigured mode is a server problem, not a client one."""
    try:
        return current_mode()
    except MasterDataConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _role_actions(user: Dict[str, Any]) -> set:
    """Actions the caller's role grants, from the canonical catalog.

    Most sessions still carry a legacy role string, so it is translated through
    the existing migration map; a session that already carries a canonical role
    id works unchanged.
    """
    role = (user or {}).get("role")
    if not role or not isinstance(role, str):
        return set()
    return catalog.role_actions(catalog.LEGACY_ROLE_MAP.get(role, role))


async def _authorize(action: str, request: Request, user: Dict[str, Any],
                     mode: str) -> None:
    """Refuse a caller who may not perform this action.

    In ``PERMISSION_SERVICE_MODE=enforce`` the decision comes only from the
    Permission Service, through the existing ``require_permission`` dependency.
    No second evaluator is introduced here.

    In W0-02 ``off`` and ``shadow`` that service does not decide yet — it leaves
    the decision to each route's legacy check — and Master Data has no legacy
    check to inherit, because these endpoints are new. Leaving them open until
    W0-02 reaches enforce would mean shipping an unauthorized approval
    endpoint, so the canonical catalog decides instead: in memory, from the role
    the session already carries, with no registry lookup and no database read.

    The same in-memory check is used while **Master Data itself is off**, even
    if W0-02 enforces. Evaluating the Permission Service means a registry
    lookup, and a switched-off feature must not read a database to tell a
    caller that it is switched off. Off stays inert, and still closed: a role
    with no grant is refused rather than told what the endpoint does.
    """
    if mode != MODE_OFF and permission_deps.current_mode() == permission_deps.MODE_ENFORCE:
        dependency = permission_deps.require_permission(action, module="master_data")
        await dependency(request, user)
        return

    if action not in _role_actions(user):
        raise HTTPException(
            status_code=403,
            detail={"error_code": "PERMISSION_DENIED",
                    "message": "This role may not perform %s" % action},
        )


def _guard(action: str):
    """Build the dependency for one endpoint. The order is the contract."""

    async def dependency(request: Request,
                         user: Dict[str, Any] = Depends(get_current_user)) -> Gate:
        mode = _mode_or_503()                          # 1. an unusable mode refuses first
        await _authorize(action, request, user, mode)  # 2. then who is asking
        if mode == MODE_OFF:
            return Gate(mode, action)              # 3. off touches nothing further
        ctx = await get_tenant_context(request, user)   # 4. server-side tenant only
        return Gate(mode, action, ctx)

    return dependency


def _off_payload(mode: str) -> Dict[str, Any]:
    return {"mode": mode, "performed": False,
            "detail": "master data is off (MASTER_DATA_MODE)"}


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
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
async def create_pending(body: ProposeBody, gate: Gate = Depends(_guard(ACTION_PROPOSE))):
    """Record what an automated channel could not recognise."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await pending_mod.propose(
            gate.ctx,
            entity_type=body.entity_type,
            raw_value=body.raw_value,
            source_channel=body.source_channel,
            source_ref=body.source_ref,
            model_and_version=body.model_and_version,
            mode=gate.mode,
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
    gate: Gate = Depends(_guard(ACTION_PENDING_READ)),
):
    """The review queue for this tenant."""
    if gate.off:
        return {"mode": gate.mode, "count": 0, "items": [],
                "detail": _off_payload(gate.mode)["detail"]}
    try:
        items = await review.list_pending(gate.ctx, entity_type=entity_type, status=status,
                                          limit=limit, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": gate.mode, "count": len(items), "items": items}


@router.get("/pending/{pending_id}/matches")
async def pending_matches(
    pending_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    gate: Gate = Depends(_guard(ACTION_PENDING_READ)),
):
    """Candidate Master records for one proposal.

    Read-only and non-binding: an exact match is shown, never applied.
    """
    if gate.off:
        return {"mode": gate.mode, "count": 0, "candidates": []}
    try:
        candidates = await review.suggest_matches(gate.ctx, pending_id=pending_id,
                                                  limit=limit, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": gate.mode, "count": len(candidates), "candidates": candidates,
            "note": "candidates only; approval is a human decision"}


@router.post("/pending/{pending_id}/approve")
async def approve_pending(
    pending_id: str,
    body: ApproveBody,
    gate: Gate = Depends(_guard(ACTION_APPROVE)),
):
    """Map the proposal to an existing record, or create a new official one."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await review.approve(
            gate.ctx,
            pending_id=pending_id,
            confirmation=body.confirmation,
            canonical_entity_id=body.canonical_entity_id,
            create_new=body.create_new,
            display_name=body.display_name,
            mode=gate.mode,
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
    gate: Gate = Depends(_guard(ACTION_REJECT)),
):
    """Close the proposal. No Master record is created, changed or merged."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await review.reject(gate.ctx, pending_id=pending_id,
                                      reason=body.reason, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": outcome.mode, "performed": outcome.performed,
            "would_perform": outcome.would_perform, "detail": outcome.reason}


@router.get("/{entity_type}/{entity_id}")
async def get_entity(entity_type: str, entity_id: str,
                     gate: Gate = Depends(_guard(ACTION_ENTITY_READ))):
    """Read one canonical record, scoped to this tenant."""
    if gate.off:
        return _off_payload(gate.mode)
    if entity_type not in models.ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="unknown entity_type: %s" % entity_type)
    try:
        doc = await service.get_entity(gate.ctx, entity_type=entity_type,
                                       entity_id=entity_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if not doc:
        raise HTTPException(status_code=404, detail="not found in this tenant")
    return doc
