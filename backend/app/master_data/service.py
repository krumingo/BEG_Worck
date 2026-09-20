"""
W0-03B1 — the only entry point into Master Data.

Everything a caller can do goes through here, so the guarantees live in one
place:

  * the mode is validated **first**, from a single validator, whether it came
    from the environment or from an explicit argument. An unknown mode refuses
    before a tenant is resolved, before a repository exists, before Mongo and
    before audit;
  * ``off`` is **inert** — it returns before a repository is built, before the
    resolver is imported, before any audit call, with no pending record.
    Nothing observable changes;
  * ``shadow`` **observes**. It performs no write, creates no official Master,
    emits no AuditEvent, and — importantly — never raises where the legacy path
    used to succeed: a refusal becomes an observation in the outcome;
  * ``enforce`` writes, and a successful outcome is never returned without the
    canonical W0-04 AuditEvent;
  * the tenant comes solely from a resolver-backed context;
  * a tenant identifier in the payload is **refused**, not ignored;
  * an official Master Person is created only by an explicit human
    confirmation — no domain (advance, payroll, brigade, attendance) and no
    automated source (AI, OCR, Excel, import) can create one as a side effect.

The last rule is Krum's decision of 20.09.2026 (contract §4.5) plus FLOW-032
§"Импорт, OCR и AI мапване". It is enforced at the foundation so a later slice
cannot reintroduce the side effect by accident.
"""
from typing import Any, Dict, List, Optional

from app.master_data import models
from app.master_data.deps import (
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataTenantContextMissing,
    require_tenant_context,
    resolve_mode,
)
from app.master_data.models import MasterDataInvalid

#: The flow this layer implements; used as the AuditEvent source.
SOURCE_FLOW = "FLOW-032"

# --- provenance ------------------------------------------------------------
SOURCE_EXPLICIT_CONFIRMATION = "explicit_confirmation"

#: Sources that may never create an official Master record. They produce a
#: pending-mapping entry instead — which W0-03B2 introduces.
AUTOMATED_SOURCES = frozenset({
    "ai", "ocr", "excel", "import", "advance", "payroll", "attendance",
    "brigade", "intake", "migration",
})

#: A person is stricter than everything else: only an explicit confirmation.
PERSON_CREATION_SOURCES = frozenset({SOURCE_EXPLICIT_CONFIRMATION})


class MasterDataRefused(Exception):
    """The operation is refused by a rule, not by a technical failure."""


class MasterDataAuditFailed(Exception):
    """The record was written but the canonical AuditEvent was not.

    Raised so that a caller can never read "success" out of a write that left
    no evidence. See the failure semantics in ``_audit_created``.
    """


class MasterDataOutcome:
    """What the service did — deliberately explicit, so ``off`` and ``shadow``
    are visible rather than mistaken for success.

    ``performed`` is True only when a record was actually written **and**
    audited. ``would_perform`` is what shadow reports: whether enforce would
    have gone through, with ``reason`` carrying the refusal when it would not.
    """

    __slots__ = ("mode", "performed", "entity", "reason", "would_perform")

    def __init__(self, mode: str, performed: bool,
                 entity: Optional[Dict[str, Any]] = None, reason: Optional[str] = None,
                 would_perform: Optional[bool] = None):
        self.mode = mode
        self.performed = performed
        self.entity = entity
        self.reason = reason
        self.would_perform = would_perform

    def __repr__(self) -> str:                                   # pragma: no cover
        return ("MasterDataOutcome(mode=%r, performed=%r, would_perform=%r, reason=%r)"
                % (self.mode, self.performed, self.would_perform, self.reason))


def _reject_tenant_override(payload: Optional[Dict[str, Any]]) -> None:
    """A tenant key in caller-supplied data is a refusal, never a silent drop.

    Ignoring it would let a caller believe the value was honoured; refusing
    makes the attempt visible (TENANCY_MODEL.md §2).
    """
    if not payload:
        return
    offending = sorted(k for k in payload if k in models.RESERVED_TENANT_KEYS)
    if offending:
        raise MasterDataRefused(
            "tenant identity cannot come from the payload (%s); it is resolved server-side"
            % ", ".join(offending)
        )


def _check_source(entity_type: str, source: Optional[str]) -> None:
    if not source:
        raise MasterDataRefused("source is required: an unattributed Master record is not allowed")
    normalized = source.strip().lower()
    if entity_type == models.ENTITY_PERSON:
        if normalized not in PERSON_CREATION_SOURCES:
            raise MasterDataRefused(
                "an official Master Person is created only by %s; '%s' would be a side effect "
                "(contract §4.5 — Krum, 20.09.2026)"
                % (SOURCE_EXPLICIT_CONFIRMATION, source)
            )
        return
    if normalized in AUTOMATED_SOURCES:
        raise MasterDataRefused(
            "'%s' may not create an official Master record; it belongs in pending mapping "
            "(FLOW-032 §Импорт, OCR и AI мапване)" % source
        )


def _require_actor(ctx: Any) -> str:
    """The AuditEvent actor comes from the authenticated context or nowhere.

    An event with an invented actor is worse than no event: it is evidence that
    lies. If the context carries no user, the write is refused.
    """
    actor_id = getattr(ctx, "user_id", None)
    if not actor_id or not isinstance(actor_id, str):
        raise MasterDataTenantContextMissing(
            "the tenant context carries no user_id; refusing to write without a real audit actor"
        )
    return actor_id


async def _audit_created(ctx: Any, entity: Dict[str, Any], source: str, actor_id: str) -> Dict[str, Any]:
    """Append the canonical W0-04 AuditEvent for a Master Data creation.

    Uses the existing canonical API (``build_event`` + ``record_event``) and the
    existing integration model from ``app/permissions/audit_hooks.py``: the
    event is written into the SAME tenant database the context resolved. No
    second audit mechanism is introduced.

    **Failure semantics — stated plainly, because there is no transaction.**
    The operational write and the audit chain live in two collections with no
    shared transaction, so this is *not* atomic. The order is: write first,
    then audit. Auditing first would risk an event claiming a write that never
    happened, which corrupts the evidence chain — the worse of the two
    failures. Consequently, if this call fails the record may already exist
    while no event describes it; the caller then receives
    ``MasterDataAuditFailed`` and **must not** treat the operation as
    successful. Reconciling such an unaudited record is W0-04B/W0-03E work, not
    something this slice papers over, and nothing here is deleted to
    compensate: FLOW-032 forbids hard-deleting Master records.
    """
    # imported lazily: off and shadow must not pull the audit stack in either
    from app.audit.envelope import (
        ACTOR_HUMAN,
        RETENTION_R1_CRITICAL_BUSINESS,
        RESULT_SUCCESS,
        build_event,
    )
    from app.audit.store import record_event

    event = build_event(
        tenant_id=ctx.tenant_id,
        actor_type=ACTOR_HUMAN,
        actor_id=actor_id,
        action="master_data.%s.created" % entity["entity_type"],
        source_flow=SOURCE_FLOW,
        retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        result=RESULT_SUCCESS,
        entity_type="master_data.%s" % entity["entity_type"],
        entity_id=entity["id"],
        source_channel=source,
        reason="canonical Master Data record created",
    )
    db = await ctx.db()
    return await record_event(db, event)


def _observe(mode: str, check) -> MasterDataOutcome:
    """Run the enforce guards without writing and without raising.

    Shadow exists to measure, so a refusal that would stop enforce must arrive
    as information, not as an exception on a path that used to work.
    """
    try:
        check()
    except (MasterDataRefused, MasterDataInvalid, MasterDataTenantContextMissing) as exc:
        return MasterDataOutcome(mode, False, None, str(exc), would_perform=False)
    return MasterDataOutcome(
        mode, False, None,
        "shadow: would create; nothing written (pending mapping arrives in W0-03B2)",
        would_perform=True,
    )


async def create_entity(
    ctx: Any,
    *,
    entity_type: str,
    display_name: str,
    source: Optional[str] = None,
    legacy_refs: Optional[List[Dict[str, Any]]] = None,
    payload: Optional[Dict[str, Any]] = None,
    mode: Any = None,
    repository=None,
) -> MasterDataOutcome:
    """Create one canonical Master record.

    ``off`` returns an inert outcome before touching anything. ``shadow``
    returns an observation and writes nothing. Only ``enforce`` writes, and
    only with a canonical AuditEvent.
    """
    effective = resolve_mode(mode)          # fail-closed, before everything else

    if effective == MODE_OFF:
        return MasterDataOutcome(MODE_OFF, False, None, "master data is off")

    if effective == MODE_SHADOW:
        def _check():
            validated = require_tenant_context(ctx)
            _reject_tenant_override(payload)
            _check_source(entity_type, source)
            models.build_entity(                     # pure, in memory, discarded
                tenant_id=validated.tenant_id,
                entity_type=entity_type,
                display_name=display_name,
                legacy_refs=legacy_refs,
            )
            _require_actor(validated)
        return _observe(MODE_SHADOW, _check)

    # --- enforce -----------------------------------------------------------
    ctx = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    _check_source(entity_type, source)
    actor_id = _require_actor(ctx)

    entity = models.build_entity(
        tenant_id=ctx.tenant_id,
        entity_type=entity_type,
        display_name=display_name,
        legacy_refs=legacy_refs,
    )

    repo = repository if repository is not None else _repository_for(ctx)
    await repo.create(entity)

    try:
        await _audit_created(ctx, entity, source, actor_id)
    except Exception as exc:                          # noqa: BLE001 — re-raised below
        raise MasterDataAuditFailed(
            "master data record %s was written but its canonical AuditEvent failed (%s); "
            "the operation is NOT successful" % (entity["id"], exc)
        ) from exc

    return MasterDataOutcome(MODE_ENFORCE, True, entity)


async def get_entity(
    ctx: Any,
    *,
    entity_type: str,
    entity_id: str,
    mode: Any = None,
    repository=None,
) -> Optional[Dict[str, Any]]:
    """Read one canonical Master record.

    ``off`` returns None without a read. **``shadow`` also returns None without
    a read**, deliberately: in shadow the canonical store is not yet a source of
    truth — nothing has been written to it — so answering from it would give a
    caller data the legacy path does not have and would change behaviour, which
    is exactly what shadow must not do. Reads start in ``enforce``.
    """
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None

    ctx = require_tenant_context(ctx)
    if entity_type not in models.ENTITY_TYPES:
        raise MasterDataInvalid("unknown entity_type: %s" % entity_type)
    repo = repository if repository is not None else _repository_for(ctx)
    return await repo.get(entity_type, entity_id)


def _repository_for(ctx: Any):
    """Build the repository for an already-validated context.

    Imported lazily so that ``off`` and ``shadow`` never pull in the resolver
    (which opens a Mongo client at import time).
    """
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)
