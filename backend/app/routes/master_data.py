"""
Master Data API (FLOW-032) — pending mapping and human review.

Six endpoints, one rule: an automated channel proposes, a person decides.

    POST   /api/master-data/pending              record a proposal (ai|ocr|excel|import)
    GET    /api/master-data/pending              the review queue
    GET    /api/master-data/pending/{id}/matches candidates for one proposal
    POST   /api/master-data/pending/{id}/approve map to an existing record, or create one
    POST   /api/master-data/pending/{id}/reject  close it; Master Data untouched
    GET    /api/master-data/{entity_type}/{id}   read one canonical record

W0-03D merge/redirect (feature-off; execution fails closed without a trusted
Approval, which W0-07 does not provide yet):

    POST   /api/master-data/merge/preview          what a merge would do; never writes
    POST   /api/master-data/merge                  merge exactly the previewed state
    POST   /api/master-data/merge/unmerge/preview  what reversing a merge would do
    POST   /api/master-data/merge/unmerge          reverse it, appending history
    GET    /api/master-data/{type}/{id}/resolve        old id -> canonical record
    GET    /api/master-data/{type}/{id}/merge-history  immutable merge/unmerge events

W0-03E legacy migration (feature-off; every write fails closed without a trusted
Approval — CLAUDE.md §8 "критична миграция/rollback"):

    GET    /api/master-data/legacy/plan                 dry run: inventory + deterministic plan
    POST   /api/master-data/legacy/migration            execute exactly one dry-run plan
    GET    /api/master-data/legacy/migration/{run_id}   run status, checkpoint, evidence
    GET    /api/master-data/legacy/reconcile            counts; zero lost references proof
    POST   /api/master-data/legacy/rollback/preview     what undoing a run would do
    POST   /api/master-data/legacy/rollback             undo a run (archive, never delete)
    GET    /api/master-data/legacy/mappings             legacy records waiting for a person
    POST   /api/master-data/legacy/mappings/decide      map / create_new / decline one of them
    GET    /api/master-data/legacy/resolve              old legacy id -> canonical record
    GET    /api/master-data/legacy/advances/mapping-report  guest_name advances, read-only

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
from pydantic import BaseModel, ConfigDict

from app.deps.auth import get_current_user
from app.master_data import legacy_adapter, legacy_migration, legacy_plan
from app.master_data import merge as merge_mod, models, pending as pending_mod, review, service
from app.master_data.deps import (
    MODE_ENFORCE,
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
ACTION_MERGE_PREVIEW = "master_data.merge.preview"
ACTION_MERGE_EXECUTE = "master_data.merge.execute"
ACTION_UNMERGE_EXECUTE = "master_data.unmerge.execute"
ACTION_MIGRATION_PLAN = "master_data.migration.plan"
ACTION_MIGRATION_EXECUTE = "master_data.migration.execute"
ACTION_MIGRATION_ROLLBACK = "master_data.migration.rollback"
ACTION_MIGRATION_MAP = "master_data.migration.map"
ACTION_LEGACY_DELETE = "master_data.legacy.delete"

#: Actions whose refusal by the in-memory catalog check is written to the audit
#: chain while Master Data enforces. (Under W0-02 enforce the Permission
#: Service already audits significant denials itself.)
DENIAL_AUDITED_ACTIONS = frozenset({ACTION_MERGE_EXECUTE, ACTION_UNMERGE_EXECUTE,
                                    ACTION_MIGRATION_EXECUTE, ACTION_MIGRATION_ROLLBACK,
                                    ACTION_MIGRATION_MAP, ACTION_LEGACY_DELETE})


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


class _Strict(BaseModel):
    """A merge body refuses unknown keys — a ``tenant_id`` in it is a 422, not
    a silently dropped field (D-15)."""
    model_config = ConfigDict(extra="forbid")


class MergePreviewBody(_Strict):
    entity_type: str
    source_id: str
    target_id: str


class MergeBody(_Strict):
    entity_type: str
    source_id: str
    target_id: str
    preview_token: str
    idempotency_key: str
    confirmation: bool = False
    approval_id: Optional[str] = None
    reason: Optional[str] = None


class UnmergePreviewBody(_Strict):
    entity_type: str
    source_id: str


class UnmergeBody(_Strict):
    entity_type: str
    source_id: str
    merge_event_id: str
    preview_token: str
    idempotency_key: str
    reason: str
    confirmation: bool = False
    approval_id: Optional[str] = None


class MigrationBody(_Strict):
    plan_token: str
    idempotency_key: str
    confirmation: bool = False
    approval_id: Optional[str] = None
    sources: Optional[list] = None
    batch_size: Optional[int] = None


class RollbackPreviewBody(_Strict):
    run_id: str


class RollbackBody(_Strict):
    run_id: str
    preview_token: str
    idempotency_key: str
    reason: str
    confirmation: bool = False
    approval_id: Optional[str] = None


class MappingDecisionBody(_Strict):
    collection: str
    legacy_id: str
    decision: str
    idempotency_key: str
    confirmation: bool = False
    canonical_entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    display_name: Optional[str] = None
    reason: Optional[str] = None
    approval_id: Optional[str] = None


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
        detail = {"error_code": "PERMISSION_DENIED",
                  "message": "This role may not perform %s" % action}
        if mode == MODE_ENFORCE and action in DENIAL_AUDITED_ACTIONS:
            detail["denial_audit"] = await _audit_catalog_denial(action, request, user)
        raise HTTPException(status_code=403, detail=detail)


class _CatalogDenial:
    reason_code = "ACTION_NOT_ALLOWED"
    effective_assignment_ids: list = []


async def _audit_catalog_denial(action: str, request: Request, user: Dict[str, Any]) -> str:
    """Record a refused merge/unmerge in the tenant's canonical audit chain.

    The tenant comes from the same W0-01 guard as every other request. A caller
    without a resolvable tenant has nothing to attribute the event to; the
    request is refused either way, and the answer says whether evidence exists.
    """
    from app.permissions.audit_hooks import audit_permission_denied
    try:
        ctx = await get_tenant_context(request, user)
    except HTTPException:
        return "not_recorded_no_tenant"
    try:
        await audit_permission_denied(ctx, action, module="master_data",
                                      resource_type="master_data.merge",
                                      decision=_CatalogDenial(), request=request)
    except Exception:                                   # noqa: BLE001 — refused regardless
        return "failed"
    return "recorded"


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
    if isinstance(exc, merge_mod.MasterDataApprovalRequired):
        return HTTPException(status_code=403, detail={"error_code": "APPROVAL_REQUIRED",
                                                      "message": str(exc)})
    if isinstance(exc, merge_mod.MasterDataStalePreview):
        return HTTPException(status_code=409, detail={"error_code": "STALE_PREVIEW",
                                                      "message": str(exc)})
    if isinstance(exc, merge_mod.MasterDataRedirectCycle):
        return HTTPException(status_code=409, detail={"error_code": "REDIRECT_CYCLE",
                                                      "message": str(exc)})
    if isinstance(exc, (legacy_migration.MigrationStalePlan, legacy_migration.MigrationBusy,
                        legacy_migration.MigrationConflict,
                        legacy_migration.MigrationVerificationFailed)):
        return HTTPException(status_code=409, detail={"error_code": legacy_migration.error_code(exc),
                                                      "message": str(exc)})
    if isinstance(exc, legacy_adapter.LegacyOrgMismatch):
        return HTTPException(status_code=403, detail={"error_code": "LEGACY_ORG_MISMATCH",
                                                      "message": str(exc)})
    if isinstance(exc, legacy_adapter.LegacyReferenceInconsistent):
        return HTTPException(status_code=409, detail={"error_code": "LEGACY_REFERENCE_INCONSISTENT",
                                                      "message": str(exc)})
    if isinstance(exc, merge_mod.MasterDataMergeBusy):
        return HTTPException(status_code=409, detail={"error_code": "MERGE_BUSY",
                                                      "message": str(exc)})
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
    source_channel: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    gate: Gate = Depends(_guard(ACTION_PENDING_READ)),
):
    """The review queue for this tenant."""
    if gate.off:
        return {"mode": gate.mode, "count": 0, "items": [],
                "detail": _off_payload(gate.mode)["detail"]}
    try:
        items = await review.list_pending(gate.ctx, entity_type=entity_type, status=status,
                                          source_channel=source_channel, limit=limit,
                                          mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": gate.mode, "count": len(items), "items": items}


@router.get("/pending/{pending_id}/matches")
async def pending_matches(
    pending_id: str,
    q: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    gate: Gate = Depends(_guard(ACTION_PENDING_READ)),
):
    """Candidate Master records for one proposal.

    Read-only and non-binding: an exact match is shown, never applied. ``q``
    turns this into a lookup for a person typing a spelling themselves; the
    automatic path stays exact either way.
    """
    if gate.off:
        return {"mode": gate.mode, "count": 0, "candidates": []}
    try:
        candidates = await review.suggest_matches(gate.ctx, pending_id=pending_id, query=q,
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


@router.post("/merge/preview")
async def merge_preview(body: MergePreviewBody,
                        gate: Gate = Depends(_guard(ACTION_MERGE_PREVIEW))):
    """Show a person what merging two records would do. Writes nothing."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        preview = await merge_mod.preview_merge(gate.ctx, entity_type=body.entity_type,
                                                source_id=body.source_id,
                                                target_id=body.target_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if preview is None:
        return {"mode": gate.mode, "preview": None,
                "detail": "shadow: the canonical store is not read before enforce"}
    return {"mode": gate.mode, "preview": preview}


@router.post("/merge")
async def merge_records(body: MergeBody, gate: Gate = Depends(_guard(ACTION_MERGE_EXECUTE))):
    """Merge exactly the previewed state. Refused without trusted Approval."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await merge_mod.merge(
            gate.ctx, entity_type=body.entity_type, source_id=body.source_id,
            target_id=body.target_id, preview_token=body.preview_token,
            idempotency_key=body.idempotency_key, confirmation=body.confirmation,
            approval_id=body.approval_id, reason=body.reason, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return outcome.as_dict()


@router.post("/merge/unmerge/preview")
async def unmerge_preview(body: UnmergePreviewBody,
                          gate: Gate = Depends(_guard(ACTION_MERGE_PREVIEW))):
    """Show a person what reversing the current merge of a record would do."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        preview = await merge_mod.preview_unmerge(gate.ctx, entity_type=body.entity_type,
                                                  source_id=body.source_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if preview is None:
        return {"mode": gate.mode, "preview": None,
                "detail": "shadow: the canonical store is not read before enforce"}
    return {"mode": gate.mode, "preview": preview}


@router.post("/merge/unmerge")
async def unmerge_record(body: UnmergeBody,
                         gate: Gate = Depends(_guard(ACTION_UNMERGE_EXECUTE))):
    """Reverse a merge by appending history. Refused without trusted Approval."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await merge_mod.unmerge(
            gate.ctx, entity_type=body.entity_type, source_id=body.source_id,
            merge_event_id=body.merge_event_id, preview_token=body.preview_token,
            idempotency_key=body.idempotency_key, reason=body.reason,
            confirmation=body.confirmation, approval_id=body.approval_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return outcome.as_dict()


# ============================================================ W0-03E legacy
def _shadow_read(gate: Gate, key: str) -> Dict[str, Any]:
    return {"mode": gate.mode, key: None,
            "detail": "shadow: the canonical store is not read before enforce"}


@router.get("/legacy/plan")
async def legacy_plan_dry_run(sources: Optional[str] = Query(default=None, max_length=500),
                              gate: Gate = Depends(_guard(ACTION_MIGRATION_PLAN))):
    """The dry run: every legacy identity document and its planned decision. Never writes."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        plan = await legacy_plan.plan(gate.ctx, mode=gate.mode,
                                      sources=sources.split(",") if sources else None)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if plan is None:
        return _shadow_read(gate, "plan")
    return {"mode": gate.mode, "plan": plan}


@router.post("/legacy/migration")
async def legacy_migration_execute(body: MigrationBody,
                                   gate: Gate = Depends(_guard(ACTION_MIGRATION_EXECUTE))):
    """Apply exactly one dry-run plan. Refused without trusted Approval."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await legacy_migration.execute(
            gate.ctx, plan_token=body.plan_token, idempotency_key=body.idempotency_key,
            confirmation=body.confirmation, approval_id=body.approval_id, sources=body.sources,
            batch_size=body.batch_size, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return outcome.as_dict()


@router.get("/legacy/migration/{run_id}")
async def legacy_migration_status(run_id: str,
                                  gate: Gate = Depends(_guard(ACTION_MIGRATION_PLAN))):
    if gate.off:
        return _off_payload(gate.mode)
    try:
        run = await legacy_migration.run_status(gate.ctx, run_id=run_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if run is None and gate.mode == MODE_ENFORCE:
        raise HTTPException(status_code=404, detail="no such run in this tenant")
    return {"mode": gate.mode, "run": run}


@router.get("/legacy/reconcile")
async def legacy_reconcile(sources: Optional[str] = Query(default=None, max_length=500),
                           gate: Gate = Depends(_guard(ACTION_MIGRATION_PLAN))):
    """Before/after counts of every legacy identity and every stored reference to one."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        report = await legacy_migration.reconcile(
            gate.ctx, mode=gate.mode, sources=sources.split(",") if sources else None)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if report is None:
        return _shadow_read(gate, "reconciliation")
    return {"mode": gate.mode, "reconciliation": report}


@router.post("/legacy/rollback/preview")
async def legacy_rollback_preview(body: RollbackPreviewBody,
                                  gate: Gate = Depends(_guard(ACTION_MIGRATION_PLAN))):
    if gate.off:
        return _off_payload(gate.mode)
    try:
        preview = await legacy_migration.preview_rollback(gate.ctx, run_id=body.run_id,
                                                          mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if preview is None:
        return _shadow_read(gate, "preview")
    return {"mode": gate.mode, "preview": preview}


@router.post("/legacy/rollback")
async def legacy_rollback(body: RollbackBody,
                          gate: Gate = Depends(_guard(ACTION_MIGRATION_ROLLBACK))):
    """Undo one run by archiving and detaching — never deleting. Refused without Approval."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await legacy_migration.rollback(
            gate.ctx, run_id=body.run_id, preview_token=body.preview_token,
            idempotency_key=body.idempotency_key, reason=body.reason,
            confirmation=body.confirmation, approval_id=body.approval_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return outcome.as_dict()


@router.get("/legacy/mappings")
async def legacy_mappings(status: str = Query(default="pending"),
                          collection: Optional[str] = Query(default=None),
                          limit: int = Query(default=50, ge=1, le=200),
                          gate: Gate = Depends(_guard(ACTION_MIGRATION_PLAN))):
    if gate.off:
        return {"mode": gate.mode, "count": 0, "items": []}
    try:
        items = await legacy_migration.list_mappings(gate.ctx, status=status,
                                                     collection=collection, limit=limit,
                                                     mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": gate.mode, "count": len(items), "items": items,
            "note": "candidates only; every mapping is a human decision"}


@router.post("/legacy/mappings/decide")
async def legacy_mapping_decide(body: MappingDecisionBody,
                                gate: Gate = Depends(_guard(ACTION_MIGRATION_MAP))):
    if gate.off:
        return _off_payload(gate.mode)
    try:
        outcome = await legacy_migration.resolve_mapping(
            gate.ctx, collection=body.collection, legacy_id=body.legacy_id,
            decision=body.decision, idempotency_key=body.idempotency_key,
            confirmation=body.confirmation, canonical_entity_id=body.canonical_entity_id,
            entity_type=body.entity_type, display_name=body.display_name, reason=body.reason,
            approval_id=body.approval_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return outcome.as_dict()


@router.get("/legacy/resolve")
async def legacy_resolve(collection: str = Query(...), legacy_id: str = Query(...),
                         org_id: Optional[str] = Query(default=None),
                         gate: Gate = Depends(_guard(ACTION_ENTITY_READ))):
    """Resolve an old legacy id of THIS tenant. A foreign ``org_id`` is refused."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        resolved = await legacy_adapter.resolve_legacy(gate.ctx, collection=collection,
                                                       legacy_id=legacy_id, org_id=org_id,
                                                       mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if resolved is None:
        if gate.mode != MODE_ENFORCE:
            return {"mode": gate.mode, "resolved": None}
        raise HTTPException(status_code=404, detail="no legacy reference in this tenant")
    return {"mode": gate.mode, **resolved}


@router.get("/legacy/advances/mapping-report")
async def legacy_advance_report(gate: Gate = Depends(_guard(ACTION_MIGRATION_PLAN))):
    """Existing guest_name advances with candidate persons. Read-only; maps nothing."""
    if gate.off:
        return _off_payload(gate.mode)
    if gate.mode != MODE_ENFORCE:
        return _shadow_read(gate, "report")
    try:
        report = await legacy_adapter.advance_mapping_report(
            await gate.ctx.db(), tenant_id=gate.ctx.tenant_id,
            org_id=legacy_plan.legacy_org_id(gate.ctx))
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": gate.mode, "report": report}


@router.get("/{entity_type}/{entity_id}/resolve")
async def resolve_entity(entity_type: str, entity_id: str,
                         gate: Gate = Depends(_guard(ACTION_ENTITY_READ))):
    """Follow redirects from any id — also an old, merged one — to its canonical record."""
    if gate.off:
        return _off_payload(gate.mode)
    try:
        resolved = await merge_mod.resolve(gate.ctx, entity_type=entity_type,
                                           entity_id=entity_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    if resolved is None:
        if gate.mode != MODE_ENFORCE:
            return {"mode": gate.mode, "resolved": None}
        raise HTTPException(status_code=404, detail="not found in this tenant")
    return {"mode": gate.mode, **resolved}


@router.get("/{entity_type}/{entity_id}/merge-history")
async def merge_history(entity_type: str, entity_id: str,
                        gate: Gate = Depends(_guard(ACTION_MERGE_PREVIEW))):
    """Every merge and unmerge that names this record, oldest first."""
    if gate.off:
        return {"mode": gate.mode, "count": 0, "events": []}
    try:
        events = await merge_mod.history(gate.ctx, entity_type=entity_type,
                                         entity_id=entity_id, mode=gate.mode)
    except Exception as exc:                            # noqa: BLE001
        raise _handle(exc)
    return {"mode": gate.mode, "count": len(events), "events": events}


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
