"""
W0-03B3 — human review of pending proposals.

The other half of the pending contract: an automated channel may propose, and a
**person** decides. FLOW-032 §"Права": *"теренен потребител: предлага нов
запис/алиас; офис: мапва и коригира в разрешения scope"*.

Three decisions, and nothing else:
  * **approve to an existing Master** — the raw text becomes a confirmed alias
    of that record, so the same text maps itself next time (FLOW-032: *"След
    потвърждение алиасът може да се използва автоматично следващия път"*);
  * **approve as a new Master** — creates the official record through the normal
    service path, with ``explicit_confirmation`` provenance;
  * **reject** — the proposal is closed and **no Master record is touched**.

Concurrency, stated plainly because it is the part that can quietly corrupt
data: two people clicking approve at the same moment must not produce two
canonical records. The transition ``pending -> resolving`` is a compare-and-set
in the database; whoever loses it is refused. Everything after the claim is
done by exactly one caller.

That claim is the **only** way in, and it does not make an exception for the
reviewer who already holds it. Two requests from the same person — a double
click, or a client retrying a slow response — are two callers, and a claim that
let the second one in because it recognised the actor would put both inside the
body at once. A row in ``resolving`` is therefore never re-entered; it is either
released back to the queue by the attempt that failed, or it stays claimed and
becomes reconciliation work.

The other half of the same problem is a *partial* failure: an approval that
created the official record and then failed before it could close the pending
row. The record cannot be deleted to compensate — FLOW-032 forbids hard-deleting
Master records — so instead the identifier of a record created by approving a
given pending row is **derived from that row** (``models.derived_entity_id``).
A retry therefore computes the same identifier, finds the record already there,
and finishes the job. No second official record, no compensating deletion, and
no dependence on a unique index that does not exist yet — the exclusion comes
from the claim above, which is what keeps the retry sequential.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.master_data import matching, models
from app.master_data.deps import (
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataTenantContextMissing,
    require_tenant_context,
    resolve_mode,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.pending import (
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RESOLVED,
)
from app.master_data.service import (
    SOURCE_EXPLICIT_CONFIRMATION,
    SOURCE_FLOW,
    MasterDataAuditFailed,
    MasterDataRefused,
    _require_actor,
    create_entity,
)

MAX_REJECTION_REASON = 500


class ReviewOutcome:
    """The result of one human decision."""

    __slots__ = ("mode", "performed", "decision", "pending_id", "entity_id", "reason",
                 "would_perform", "created_master")

    def __init__(self, mode: str, performed: bool, decision: Optional[str] = None,
                 pending_id: Optional[str] = None, entity_id: Optional[str] = None,
                 reason: Optional[str] = None, would_perform: Optional[bool] = None,
                 created_master: bool = False):
        self.mode = mode
        self.performed = performed
        self.decision = decision
        self.pending_id = pending_id
        self.entity_id = entity_id
        self.reason = reason
        self.would_perform = would_perform
        self.created_master = created_master

    def __repr__(self) -> str:                                   # pragma: no cover
        return ("ReviewOutcome(mode=%r, performed=%r, decision=%r, entity_id=%r, reason=%r)"
                % (self.mode, self.performed, self.decision, self.entity_id, self.reason))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repository_for(ctx: Any):
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)


def _repo(ctx: Any, repository):
    return repository if repository is not None else _repository_for(ctx)


async def _audit(ctx: Any, *, action: str, pending: Dict[str, Any], actor_id: str,
                 entity_id: Optional[str], reason: Optional[str]) -> Dict[str, Any]:
    """Canonical W0-04 event for a human decision.

    ``ACTOR_HUMAN`` without exception: this module exists precisely because a
    person decided. Retention R1 — an approval creates or confirms an official
    identity, which is critical business history.

    Same failure semantics as elsewhere in the package: the state change and the
    audit chain share no transaction, the write happens first, and a failed
    audit makes the operation unsuccessful rather than silently leaving an
    unaudited decision behind.
    """
    from app.audit.envelope import (
        ACTOR_HUMAN,
        RESULT_SUCCESS,
        RETENTION_R1_CRITICAL_BUSINESS,
        build_event,
    )
    from app.audit.store import record_event

    event = build_event(
        tenant_id=ctx.tenant_id,
        actor_type=ACTOR_HUMAN,
        actor_id=actor_id,
        action=action,
        source_flow=SOURCE_FLOW,
        retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        result=RESULT_SUCCESS,
        entity_type="master_data.pending",
        entity_id=pending["id"],
        source_channel=pending.get("source_channel"),
        after_reference=entity_id,
        reason=reason or "human decision on a pending mapping proposal",
    )
    db = await ctx.db()
    return await record_event(db, event)


async def list_pending(
    ctx: Any,
    *,
    entity_type: Optional[str] = None,
    status: str = STATUS_PENDING,
    limit: int = 50,
    mode: Any = None,
    repository=None,
) -> List[Dict[str, Any]]:
    """The review queue. ``off`` and ``shadow`` return nothing, without a read."""
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return []
    ctx = require_tenant_context(ctx)
    if entity_type is not None and entity_type not in models.ENTITY_TYPES:
        raise MasterDataInvalid("unknown entity_type: %s" % entity_type)
    return await _repo(ctx, repository).list_pending(
        entity_type=entity_type, status=status, limit=limit)


async def suggest_matches(
    ctx: Any,
    *,
    pending_id: str,
    limit: int = 10,
    mode: Any = None,
    repository=None,
) -> List[Dict[str, Any]]:
    """Candidates for one pending row. Read-only; links nothing."""
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return []
    ctx = require_tenant_context(ctx)
    repo = _repo(ctx, repository)
    row = await repo.get_pending(pending_id)
    if not row:
        raise MasterDataRefused("pending record %s not found in this tenant" % pending_id)
    return await matching.find_candidates(
        repo, entity_type=row["entity_type"], raw_value=row["raw_value"], limit=limit)


async def approve(
    ctx: Any,
    *,
    pending_id: str,
    confirmation: bool = False,
    canonical_entity_id: Optional[str] = None,
    create_new: bool = False,
    display_name: Optional[str] = None,
    mode: Any = None,
    repository=None,
) -> ReviewOutcome:
    """Resolve one pending proposal — to an existing record or a new one.

    ``confirmation=True`` is required and is the human act itself: FLOW-032
    forbids free text becoming an official Master without review, and Krum's
    decision of 20.09.2026 makes explicit confirmation the only provenance that
    may create a Master Person.
    """
    effective = resolve_mode(mode)
    if effective == MODE_OFF:
        return ReviewOutcome(MODE_OFF, False, reason="master data is off")

    if effective == MODE_SHADOW:
        try:
            _validate_approval(ctx, canonical_entity_id, create_new, confirmation)
        except (MasterDataRefused, MasterDataInvalid, MasterDataTenantContextMissing) as exc:
            return ReviewOutcome(MODE_SHADOW, False, reason=str(exc), would_perform=False)
        return ReviewOutcome(
            MODE_SHADOW, False, pending_id=pending_id,
            reason="shadow: would approve; no official data changed", would_perform=True)

    ctx, actor_id = _validate_approval(ctx, canonical_entity_id, create_new, confirmation)
    repo = _repo(ctx, repository)
    now = _now()

    # --- the compare-and-set that makes concurrent approvals safe ----------
    claimed = await repo.claim_pending(pending_id, actor_id=actor_id, now=now)
    if claimed is None:
        raise MasterDataRefused(
            "pending record %s is not open for approval — another reviewer resolved or "
            "claimed it first" % pending_id)

    reused_record = False
    try:
        if create_new:
            # Derived from the pending row, not invented: the same approval
            # retried lands on the same record instead of creating a second one.
            entity_id = models.derived_entity_id(ctx.tenant_id, pending_id)
            created_master = True
            existing = await repo.get(claimed["entity_type"], entity_id)
            if existing is not None:
                # An earlier attempt wrote the record, was audited, and then
                # failed to close the row. Finish its work rather than
                # duplicating it. A record whose creation event failed cannot
                # arrive here: that attempt keeps the row claimed and is
                # reconciliation work (W0-04B/W0-03E), not something a retry
                # papers over.
                reused_record = True
            else:
                outcome = await create_entity(
                    ctx,
                    entity_type=claimed["entity_type"],
                    display_name=(display_name or claimed["raw_value"]),
                    source=SOURCE_EXPLICIT_CONFIRMATION,
                    entity_id=entity_id,
                    mode=MODE_ENFORCE,
                    repository=repo,
                )
                entity_id = outcome.entity["id"]
        else:
            target = await repo.get(claimed["entity_type"], canonical_entity_id)
            if not target:
                raise MasterDataRefused(
                    "canonical record %s does not exist in this tenant" % canonical_entity_id)
            if target.get("status") != models.STATUS_ACTIVE:
                raise MasterDataRefused(
                    "canonical record %s is %s and cannot receive a mapping"
                    % (canonical_entity_id, target.get("status")))
            # The alias is what makes the same raw text map itself next time —
            # and it is added only here, after a human said so.
            alias = models.new_alias(claimed["raw_value"], added_by=actor_id, now=now)
            await repo.add_alias(claimed["entity_type"], canonical_entity_id, alias, now)
            entity_id = canonical_entity_id
            created_master = False

        if not await repo.finish_pending(pending_id, entity_id=entity_id,
                                         actor_id=actor_id, now=now):
            raise MasterDataRefused(
                "pending record %s changed state while being approved" % pending_id)
    except MasterDataAuditFailed:
        raise
    except Exception:
        # Hand the row back so a person can retry; nothing is left half-claimed.
        await repo.release_pending(pending_id, actor_id=actor_id, now=now)
        raise

    try:
        await _audit(ctx, action="master_data.pending.approved", pending=claimed,
                     actor_id=actor_id, entity_id=entity_id,
                     reason="approved as new Master" if created_master else "mapped to existing Master")
    except Exception as exc:                          # noqa: BLE001
        raise MasterDataAuditFailed(
            "pending record %s was approved but its canonical AuditEvent failed (%s); "
            "the operation is NOT successful" % (pending_id, exc)) from exc

    return ReviewOutcome(
        MODE_ENFORCE, True, decision=STATUS_RESOLVED, pending_id=pending_id,
        entity_id=entity_id, created_master=created_master,
        reason=("the record created by an earlier interrupted attempt was reused; "
                "no second Master record was created") if reused_record else None)


async def reject(
    ctx: Any,
    *,
    pending_id: str,
    reason: str,
    mode: Any = None,
    repository=None,
) -> ReviewOutcome:
    """Close a proposal without touching Master Data at all."""
    effective = resolve_mode(mode)
    if effective == MODE_OFF:
        return ReviewOutcome(MODE_OFF, False, reason="master data is off")

    if effective == MODE_SHADOW:
        try:
            validated = require_tenant_context(ctx)
            _require_actor(validated)
            _validate_reason(reason)
        except (MasterDataRefused, MasterDataInvalid, MasterDataTenantContextMissing) as exc:
            return ReviewOutcome(MODE_SHADOW, False, reason=str(exc), would_perform=False)
        return ReviewOutcome(MODE_SHADOW, False, pending_id=pending_id,
                             reason="shadow: would reject; no official data changed",
                             would_perform=True)

    ctx = require_tenant_context(ctx)
    actor_id = _require_actor(ctx)
    _validate_reason(reason)

    repo = _repo(ctx, repository)
    now = _now()
    row = await repo.get_pending(pending_id)
    if not row:
        raise MasterDataRefused("pending record %s not found in this tenant" % pending_id)
    if not await repo.reject_pending(pending_id, reason=reason, actor_id=actor_id, now=now):
        raise MasterDataRefused(
            "pending record %s is not open for rejection — it was already resolved" % pending_id)

    try:
        await _audit(ctx, action="master_data.pending.rejected", pending=row,
                     actor_id=actor_id, entity_id=None, reason=reason)
    except Exception as exc:                          # noqa: BLE001
        raise MasterDataAuditFailed(
            "pending record %s was rejected but its canonical AuditEvent failed (%s); "
            "the operation is NOT successful" % (pending_id, exc)) from exc

    return ReviewOutcome(MODE_ENFORCE, True, decision=STATUS_REJECTED, pending_id=pending_id)


def _validate_reason(reason: str) -> None:
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise MasterDataInvalid("a rejection must say why")
    if len(reason) > MAX_REJECTION_REASON:
        raise MasterDataInvalid("rejection reason exceeds %d characters" % MAX_REJECTION_REASON)


def _validate_approval(ctx: Any, canonical_entity_id: Optional[str], create_new: bool,
                       confirmation: bool):
    validated = require_tenant_context(ctx)
    actor_id = _require_actor(validated)
    if confirmation is not True:
        raise MasterDataRefused(
            "approval requires explicit human confirmation; an automated caller cannot "
            "approve a pending proposal (FLOW-032, contract §4.5)")
    if create_new and canonical_entity_id:
        raise MasterDataInvalid(
            "choose one: map to an existing record, or create a new one — not both")
    if not create_new and not canonical_entity_id:
        raise MasterDataInvalid(
            "approval needs either canonical_entity_id or create_new=True")
    return validated, actor_id
