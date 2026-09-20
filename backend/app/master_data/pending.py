"""
W0-03B2 — Pending Mapping foundation.

Where automated input goes instead of into Master Data. Excel, OCR, AI and
imports may **propose**; they may never create, map or merge an official
record. FLOW-032 §"Импорт, OCR и AI мапване": *"Неразпознатото влиза в «За
мапване». Офисът избира съществуващ Master или предлага нов."*

What this slice deliberately does NOT do:
  * resolve a pending record — the human workflow is W0-03B3;
  * map, link or merge anything, **even on an exact match**;
  * fuzzy matching policy, normalization, aliases or unique indexes — W0-03C.

A suggestion is a suggestion. Nothing here turns one into a link.

Repeated input is **idempotent**: while a proposal for the same normalized text
is open, another sighting is counted on that row rather than opening a second
one. Re-running an import, re-sending a photo or retrying a request therefore
leaves the office one thing to decide, not a queue full of copies.

Canon: FLOW-032, TENANCY_MODEL.md §2/§6 (D-15),
docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md §4.2.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

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
from app.master_data.service import (
    SOURCE_FLOW,
    MasterDataAuditFailed,
    MasterDataRefused,
    _reject_tenant_override,
    _require_actor,
)

#: The automated channels that are allowed to propose.
SOURCE_AI = "ai"
SOURCE_OCR = "ocr"
SOURCE_EXCEL = "excel"
SOURCE_IMPORT = "import"
PENDING_SOURCES = frozenset({SOURCE_AI, SOURCE_OCR, SOURCE_EXCEL, SOURCE_IMPORT})

#: Lifecycle of a pending row. Only ``pending`` may be *created*; the rest are
#: reached through the human review workflow (W0-03B3, ``review.py``) and never
#: by an automated channel.
STATUS_PENDING = "pending"
STATUS_RESOLVING = "resolving"      # claimed by one approver; a compare-and-set
STATUS_RESOLVED = "resolved"
STATUS_REJECTED = "rejected"
PENDING_STATUSES = frozenset({STATUS_PENDING, STATUS_RESOLVING, STATUS_RESOLVED, STATUS_REJECTED})
CREATABLE_STATUSES = frozenset({STATUS_PENDING})

PENDING_COLLECTION = "md_pending_mapping"

#: ``source_ref`` is a reference, never the payload: an import row, a file id,
#: an OCR job. Bounded so a caller cannot smuggle a document — or a secret —
#: into the audit trail through it.
MAX_SOURCE_REF = 200
MAX_RAW_VALUE = 2000
MAX_SUGGESTIONS = 20


class PendingOutcome:
    """Deliberately not a ``MasterDataOutcome``: a pending record is not a
    Master record, and the type keeps the two from being confused.

    ``performed`` is True only when a pending row was written **and** audited.
    ``would_perform`` is what shadow reports.
    """

    __slots__ = ("mode", "performed", "pending", "reason", "would_perform", "deduplicated")

    def __init__(self, mode: str, performed: bool, pending: Optional[Dict[str, Any]] = None,
                 reason: Optional[str] = None, would_perform: Optional[bool] = None,
                 deduplicated: bool = False):
        self.mode = mode
        self.performed = performed
        self.pending = pending
        self.reason = reason
        self.would_perform = would_perform
        #: True when the same text was already waiting and this sighting was
        #: counted on the open row instead of opening a second one.
        self.deduplicated = deduplicated

    def __repr__(self) -> str:                                   # pragma: no cover
        return ("PendingOutcome(mode=%r, performed=%r, would_perform=%r, reason=%r)"
                % (self.mode, self.performed, self.would_perform, self.reason))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_suggestion(entity_id: str, score: Optional[float] = None,
                     reason: Optional[str] = None) -> Dict[str, Any]:
    """One candidate Master record. A candidate, and nothing more.

    A score of 1.0 is still only a score: this slice never acts on it.
    """
    if not entity_id or not isinstance(entity_id, str):
        raise MasterDataInvalid("a suggestion needs the candidate's entity_id")
    suggestion: Dict[str, Any] = {"entity_id": entity_id}
    if score is not None:
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            raise MasterDataInvalid("suggestion score must be a number between 0 and 1")
        suggestion["score"] = float(score)
    if reason:
        suggestion["reason"] = str(reason)[:200]
    return suggestion


def build_pending(
    *,
    tenant_id: str,
    entity_type: str,
    raw_value: str,
    source_channel: str,
    created_by: str,
    source_ref: Optional[str] = None,
    suggested_matches: Optional[List[Dict[str, Any]]] = None,
    pending_id: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one pending-mapping document. Pure; writes nothing."""
    if not tenant_id or not isinstance(tenant_id, str):
        raise MasterDataInvalid("tenant_id is required and must come from the server-side resolver")
    if entity_type not in models.ENTITY_TYPES:
        raise MasterDataInvalid(
            "unknown entity_type '%s'; FLOW-032 fixes: %s"
            % (entity_type, ", ".join(sorted(models.ENTITY_TYPES)))
        )
    if source_channel not in PENDING_SOURCES:
        raise MasterDataInvalid(
            "source_channel must be one of %s; a human path does not belong in pending mapping"
            % ", ".join(sorted(PENDING_SOURCES))
        )
    if not raw_value or not isinstance(raw_value, str) or not raw_value.strip():
        raise MasterDataInvalid("raw_value is required: the pending record exists to hold it")
    if len(raw_value) > MAX_RAW_VALUE:
        raise MasterDataInvalid("raw_value exceeds %d characters" % MAX_RAW_VALUE)
    if not created_by or not isinstance(created_by, str):
        raise MasterDataInvalid("created_by is required and comes from the authenticated context")

    ref = _validate_source_ref(source_ref)

    suggestions = list(suggested_matches or [])
    if len(suggestions) > MAX_SUGGESTIONS:
        raise MasterDataInvalid("at most %d suggestions per pending record" % MAX_SUGGESTIONS)
    for s in suggestions:
        if not isinstance(s, dict) or not s.get("entity_id"):
            raise MasterDataInvalid("each suggestion needs an entity_id")

    stamp = now or _now()
    doc = {
        "id": pending_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "entity_type": entity_type,
        "raw_value": raw_value.strip(),
        # The deterministic comparison key, stored with the version that
        # produced it — the same rule Master records carry, so "already
        # waiting" and "already exists" are decided by one rule, not two.
        "normalized_value": models.normalize_name(raw_value),
        "normalization_version": models.NORMALIZATION_VERSION,
        "source_channel": source_channel,
        "source_ref": ref,
        "suggested_matches": suggestions,
        "status": STATUS_PENDING,
        # Never set by this slice. They exist so the shape is stable for
        # W0-03B3, and so nothing here can quietly fill them in.
        "resolved_entity_id": None,
        "resolved_by": None,
        "resolved_at": None,
        "created_by": created_by,
        # How many times an automated channel has seen this text while the
        # proposal was open. A re-imported spreadsheet or a re-sent photo must
        # not leave the office the same decision twice.
        "occurrences": 1,
        "first_seen_at": stamp,
        "last_seen_at": stamp,
        "created_at": stamp,
        "updated_at": stamp,
    }
    validate_pending(doc)
    return doc


def _validate_source_ref(source_ref: Optional[str]) -> Optional[str]:
    if source_ref is None:
        return None
    if not isinstance(source_ref, str):
        raise MasterDataInvalid("source_ref must be a string reference")
    ref = source_ref.strip()
    if not ref:
        return None
    if len(ref) > MAX_SOURCE_REF:
        raise MasterDataInvalid(
            "source_ref exceeds %d characters — it is a reference (import row, file id, "
            "OCR job), not the payload" % MAX_SOURCE_REF
        )
    if "://" in ref and "@" in ref.split("://", 1)[1].split("/", 1)[0]:
        raise MasterDataInvalid("source_ref must not carry credentials")
    return ref


def validate_pending(doc: Dict[str, Any]) -> None:
    """Raise MasterDataInvalid unless the document is a valid pending record."""
    if not isinstance(doc, dict):
        raise MasterDataInvalid("pending record must be a document")
    for field in ("id", "tenant_id", "entity_type", "raw_value", "source_channel",
                  "status", "created_by"):
        if not doc.get(field):
            raise MasterDataInvalid("missing required field: %s" % field)
    if doc["entity_type"] not in models.ENTITY_TYPES:
        raise MasterDataInvalid("unknown entity_type: %s" % doc["entity_type"])
    if not doc.get("normalized_value"):
        raise MasterDataInvalid(
            "normalized_value is required: it is what makes a repeated sighting "
            "idempotent instead of a second row")
    if doc["source_channel"] not in PENDING_SOURCES:
        raise MasterDataInvalid("unknown source_channel: %s" % doc["source_channel"])
    if doc["status"] not in CREATABLE_STATUSES:
        raise MasterDataInvalid(
            "status %r cannot be written by W0-03B2; resolution is W0-03B3" % doc["status"])
    # The resolution fields must be empty: a pending record that arrives
    # already resolved would be an automatic mapping by the back door.
    for field in ("resolved_entity_id", "resolved_by", "resolved_at"):
        if doc.get(field):
            raise MasterDataInvalid(
                "%s must be empty: this slice never resolves a pending record" % field)
    if not isinstance(doc.get("suggested_matches", []), list):
        raise MasterDataInvalid("suggested_matches must be a list")


async def _audit_proposed(ctx: Any, pending: Dict[str, Any], actor_id: str,
                          model_and_version: Optional[str]) -> Dict[str, Any]:
    """Canonical W0-04 AuditEvent for one pending proposal.

    Same integration model as ``app/permissions/audit_hooks.py`` and
    ``master_data.service``: the event goes into the tenant database the
    context resolved, through ``build_event`` + ``record_event``.

    Two FLOW-040 rules shaped this and are worth stating, because they are easy
    to break by convenience:

      * an ``ACTOR_AI`` event **requires** ``model_and_version`` (§4.4), so an
        AI-channel proposal without one is refused rather than attributed to an
        anonymous model;
      * ``confirmation_required`` marks an AI action that needed a human before
        it could be executed. Recording a proposal is not such an action — it
        *is* the request for a human. Setting it here with ``RESULT_SUCCESS``
        would demand a ``confirmed_by`` that by definition does not exist yet,
        so it stays False and the pending record's own ``status`` carries the
        "awaits a human" meaning.

    Failure semantics are the same as in ``service._audit_created``: the write
    and the audit chain share no transaction, the order is write then audit,
    and a failed audit makes the operation unsuccessful rather than silently
    leaving an unaudited row behind.
    """
    from app.audit.envelope import (
        ACTOR_AI,
        ACTOR_HUMAN,
        RESULT_SUCCESS,
        RETENTION_R2_PROJECT_OPERATIONAL,
        RETENTION_R4_AI_CONTENT,
        build_event,
    )
    from app.audit.store import record_event

    is_ai = pending["source_channel"] == SOURCE_AI
    event = build_event(
        tenant_id=ctx.tenant_id,
        actor_type=ACTOR_AI if is_ai else ACTOR_HUMAN,
        actor_id=actor_id,
        action="master_data.pending.proposed",
        source_flow=SOURCE_FLOW,
        retention_class=RETENTION_R4_AI_CONTENT if is_ai else RETENTION_R2_PROJECT_OPERATIONAL,
        result=RESULT_SUCCESS,
        entity_type="master_data.pending",
        entity_id=pending["id"],
        source_channel=pending["source_channel"],
        tool_or_endpoint=pending.get("source_ref"),
        model_and_version=model_and_version if is_ai else None,
        confirmation_required=False,     # see the docstring
        reason="pending mapping proposal recorded; no Master record created",
    )
    db = await ctx.db()
    return await record_event(db, event)


def _checks(ctx: Any, entity_type: str, raw_value: str, source_channel: str,
            source_ref: Optional[str], suggested_matches: Optional[List[Dict[str, Any]]],
            payload: Optional[Dict[str, Any]], model_and_version: Optional[str]):
    """Everything that must hold before a pending row may be written."""
    validated = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    actor_id = _require_actor(validated)
    if source_channel == SOURCE_AI and not model_and_version:
        raise MasterDataRefused(
            "an AI proposal must name its model (FLOW-040 §4.4); refusing to attribute it "
            "to an anonymous model"
        )
    doc = build_pending(
        tenant_id=validated.tenant_id,
        entity_type=entity_type,
        raw_value=raw_value,
        source_channel=source_channel,
        created_by=actor_id,
        source_ref=source_ref,
        suggested_matches=suggested_matches,
    )
    return validated, actor_id, doc


async def propose(
    ctx: Any,
    *,
    entity_type: str,
    raw_value: str,
    source_channel: str,
    source_ref: Optional[str] = None,
    suggested_matches: Optional[List[Dict[str, Any]]] = None,
    model_and_version: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    mode: Any = None,
    repository=None,
) -> PendingOutcome:
    """Record one proposal from an automated channel.

    The **only** thing an automated source can do. It creates a pending row and
    never a Master record, never a link, never a merge — not even when a
    suggestion matches exactly.
    """
    effective = resolve_mode(mode)          # fail-closed, before everything else

    if effective == MODE_OFF:
        return PendingOutcome(MODE_OFF, False, None, "master data is off")

    if effective == MODE_SHADOW:
        try:
            _checks(ctx, entity_type, raw_value, source_channel, source_ref,
                    suggested_matches, payload, model_and_version)
        except (MasterDataRefused, MasterDataInvalid, MasterDataTenantContextMissing) as exc:
            return PendingOutcome(MODE_SHADOW, False, None, str(exc), would_perform=False)
        return PendingOutcome(
            MODE_SHADOW, False, None,
            "shadow: would record a pending proposal; nothing written",
            would_perform=True,
        )

    # --- enforce -----------------------------------------------------------
    ctx, actor_id, doc = _checks(ctx, entity_type, raw_value, source_channel, source_ref,
                                 suggested_matches, payload, model_and_version)

    repo = repository if repository is not None else _repository_for(ctx)
    stored, created = await repo.create_pending(doc)

    if not created:
        # The same text is already waiting for the office. The sighting was
        # counted on the open row; no second row, and no second AuditEvent —
        # re-running an import is not a new business fact, and one event per
        # repeated row would drown the chain. The row itself carries
        # ``occurrences`` and ``last_seen_at`` as the record of the repeat.
        return PendingOutcome(
            MODE_ENFORCE, True, stored,
            reason="the same text is already waiting for review; this sighting was counted "
                   "on the open proposal (%d so far)" % stored.get("occurrences", 1),
            deduplicated=True)

    try:
        await _audit_proposed(ctx, stored, actor_id, model_and_version)
    except Exception as exc:                          # noqa: BLE001 — re-raised below
        raise MasterDataAuditFailed(
            "pending record %s was written but its canonical AuditEvent failed (%s); "
            "the operation is NOT successful" % (stored["id"], exc)
        ) from exc

    return PendingOutcome(MODE_ENFORCE, True, stored)


async def get_pending(
    ctx: Any,
    *,
    pending_id: str,
    mode: Any = None,
    repository=None,
) -> Optional[Dict[str, Any]]:
    """Read one pending record.

    ``off`` and ``shadow`` return None without a read, for the same reason as
    ``service.get_entity``: in those modes nothing has been written, so
    answering would hand the caller data the legacy path does not have.
    """
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    repo = repository if repository is not None else _repository_for(ctx)
    return await repo.get_pending(pending_id)


def _repository_for(ctx: Any):
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)
