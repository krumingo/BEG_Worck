"""
W0-03B1 — the only entry point into Master Data.

Everything a caller can do goes through here, so the guarantees live in one
place:

  * ``MASTER_DATA_MODE=off`` is **inert** — it returns before a repository is
    built, before the resolver is imported, before any audit call, and with no
    pending record. Nothing observable changes;
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
    MODE_OFF,
    current_mode,
    require_tenant_context,
)
from app.master_data.models import MasterDataInvalid

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


class MasterDataOutcome:
    """What the service did — deliberately explicit, so ``off`` is visible.

    ``performed`` is False in off mode, and ``entity`` is then None. A caller
    cannot mistake "did nothing" for "succeeded".
    """

    __slots__ = ("mode", "performed", "entity", "reason")

    def __init__(self, mode: str, performed: bool,
                 entity: Optional[Dict[str, Any]] = None, reason: Optional[str] = None):
        self.mode = mode
        self.performed = performed
        self.entity = entity
        self.reason = reason

    def __repr__(self) -> str:                                   # pragma: no cover
        return "MasterDataOutcome(mode=%r, performed=%r, reason=%r)" % (
            self.mode, self.performed, self.reason)


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


async def create_entity(
    ctx: Any,
    *,
    entity_type: str,
    display_name: str,
    source: Optional[str] = None,
    legacy_refs: Optional[List[Dict[str, Any]]] = None,
    payload: Optional[Dict[str, Any]] = None,
    mode: Optional[str] = None,
    repository=None,
) -> MasterDataOutcome:
    """Create one canonical Master record.

    In ``off`` mode this returns an inert outcome **before touching anything**.
    """
    effective = mode or current_mode()
    if effective == MODE_OFF:
        return MasterDataOutcome(MODE_OFF, False, None, "master data is off")

    ctx = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    _check_source(entity_type, source)

    entity = models.build_entity(
        tenant_id=ctx.tenant_id,
        entity_type=entity_type,
        display_name=display_name,
        legacy_refs=legacy_refs,
    )

    repo = repository if repository is not None else _repository_for(ctx)
    await repo.create(entity)
    return MasterDataOutcome(effective, True, entity)


async def get_entity(
    ctx: Any,
    *,
    entity_type: str,
    entity_id: str,
    mode: Optional[str] = None,
    repository=None,
) -> Optional[Dict[str, Any]]:
    """Read one canonical Master record. ``off`` returns None without a read."""
    effective = mode or current_mode()
    if effective == MODE_OFF:
        return None

    ctx = require_tenant_context(ctx)
    if entity_type not in models.ENTITY_TYPES:
        raise MasterDataInvalid("unknown entity_type: %s" % entity_type)
    repo = repository if repository is not None else _repository_for(ctx)
    return await repo.get(entity_type, entity_id)


def _repository_for(ctx: Any):
    """Build the repository for an already-validated context.

    Imported lazily so that ``off`` never pulls in the resolver (which opens a
    Mongo client at import time).
    """
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)
