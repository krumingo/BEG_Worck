"""
W0-03 — observation hooks for existing automated intake paths.

One job: let a real legacy path *tell* Master Data what it saw, without being
able to break. Every hook here is:

  * a no-op when ``MASTER_DATA_MODE`` is ``off`` — the deployed default — and
    returns before touching anything;
  * incapable of raising into the caller. A hook that can fail an invoice
    upload or an Excel import because a proposal could not be recorded would be
    a worse bug than the one it is meant to help with, so everything is
    swallowed and reported;
  * never able to create a Master record, an alias or a merge: it calls
    ``pending.propose`` and nothing else. Even an exact match is only ever a
    suggestion a person still has to accept (FLOW-032 §"Импорт, OCR и AI
    мапване").

Repeats are safe by construction: ``propose`` counts another sighting on the
open proposal instead of opening a second one, so re-importing the same
spreadsheet or re-sending the same photo leaves the office one decision, not
several.

This is how the end-to-end path is proven in shadow before anything is switched
to enforce.
"""
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.master_data.deps import MODE_OFF, current_mode
from app.master_data.models import (
    ENTITY_ACTIVITY,
    ENTITY_ASSET_TYPE,
    ENTITY_ORGANIZATION,
    ENTITY_UNIT,
)

logger = logging.getLogger(__name__)

#: Cap on what a hook will look at; OCR text can be long and the pending record
#: keeps the raw value, not the document.
MAX_OBSERVED = 200

#: Cap on how many distinct identities one import may propose in a single call.
#: A spreadsheet with ten thousand rows must not turn into ten thousand writes
#: on a path whose failure the caller is not allowed to notice.
MAX_PER_IMPORT = 200

#: The model behind the asset recognition endpoints, required by FLOW-040 §4.4
#: for an ``ACTOR_AI`` event. Kept next to the hook that reports it so the two
#: cannot drift apart silently; ``assets_ai_intake`` passes its own when it has
#: a better one.
ASSET_AI_MODEL = "openai/gpt-4.1-mini"


async def observe_ocr_supplier(user: Optional[Dict[str, Any]],
                               detected: Optional[Dict[str, Any]],
                               source_ref: Optional[str] = None) -> Optional[Any]:
    """Offer an OCR-detected supplier name to pending mapping.

    Returns the outcome when the hook ran, ``None`` when it did nothing. The
    caller is expected to ignore both.
    """
    if _mode_or_none() is None:
        return None

    supplier = (detected or {}).get("supplier_name")
    if not supplier or not isinstance(supplier, str) or not supplier.strip():
        return None

    try:
        from app.master_data.pending import SOURCE_OCR, propose
        ctx = await _context_for(user)
        if ctx is None:
            logger.info("master_data: no resolved tenant on the OCR path; nothing recorded")
            return None
        outcome = await propose(
            ctx,
            entity_type=ENTITY_ORGANIZATION,
            raw_value=supplier.strip()[:MAX_OBSERVED],
            source_channel=SOURCE_OCR,
            source_ref=source_ref,
        )
        logger.info("master_data: OCR supplier observed mode=%s performed=%s would=%s",
                    outcome.mode, outcome.performed, outcome.would_perform)
        return outcome
    except Exception as exc:                           # noqa: BLE001 — deliberate
        # The intake succeeded; a failure to record an observation about it is
        # not the intake's problem.
        logger.warning("master_data: OCR intake hook failed, ignored: %s", exc)
        return None


async def observe_excel_kss_lines(user: Optional[Dict[str, Any]],
                                  lines: Optional[Iterable[Dict[str, Any]]],
                                  source_ref: Optional[str] = None) -> Optional[Dict[str, int]]:
    """Offer the identities an imported spreadsheet carries as free text.

    A КСС row names two of the nine canonical types: the work itself
    (``activity``) and the unit it is measured in (``unit``). Both arrive as
    whatever the author of the spreadsheet typed, which is exactly the input
    FLOW-032 says must go to "За мапване" instead of into Master Data.

    The rows themselves are imported by the existing path exactly as before —
    this only observes them.
    """
    if _mode_or_none() is None:
        return None

    observed: List[Tuple[str, str]] = []
    seen = set()
    for line in (lines or []):
        if not isinstance(line, dict):
            continue
        for entity_type, field in ((ENTITY_ACTIVITY, "smr_type"), (ENTITY_UNIT, "unit")):
            value = line.get(field)
            if not value or not isinstance(value, str) or not value.strip():
                continue
            item = (entity_type, value.strip()[:MAX_OBSERVED])
            if item in seen:
                continue                       # one proposal per distinct value
            seen.add(item)
            observed.append(item)
            if len(observed) >= MAX_PER_IMPORT:
                break
        if len(observed) >= MAX_PER_IMPORT:
            logger.info("master_data: excel import capped at %d observed identities",
                        MAX_PER_IMPORT)
            break

    from app.master_data.pending import SOURCE_EXCEL
    return await _propose_all(user, observed, SOURCE_EXCEL, source_ref, None, "excel import")


async def observe_excel_historical_lines(user: Optional[Dict[str, Any]],
                                         lines: Optional[Iterable[Dict[str, Any]]],
                                         source_ref: Optional[str] = None
                                         ) -> Optional[Dict[str, int]]:
    """The same for the historical-offer import, which keeps its own field names."""
    if _mode_or_none() is None:
        return None

    observed: List[Tuple[str, str]] = []
    seen = set()
    for line in (lines or []):
        if not isinstance(line, dict):
            continue
        for entity_type, field in ((ENTITY_ACTIVITY, "raw_smr_text"), (ENTITY_UNIT, "unit")):
            value = line.get(field)
            if not value or not isinstance(value, str) or not value.strip():
                continue
            item = (entity_type, value.strip()[:MAX_OBSERVED])
            if item in seen:
                continue
            seen.add(item)
            observed.append(item)
        if len(observed) >= MAX_PER_IMPORT:
            break

    from app.master_data.pending import SOURCE_EXCEL
    return await _propose_all(user, observed[:MAX_PER_IMPORT], SOURCE_EXCEL, source_ref,
                              None, "historical import")


async def observe_ai_asset(user: Optional[Dict[str, Any]],
                           suggestion: Optional[Dict[str, Any]],
                           source_ref: Optional[str] = None,
                           model_and_version: Optional[str] = None
                           ) -> Optional[Dict[str, int]]:
    """Offer the kind of machine or tool an AI recognised from a photo.

    The recognition endpoints write nothing themselves — they hand a filled-in
    form to a person. What they *do* invent is an identity: a name for a kind
    of equipment that may or may not already exist in Master Data. That name is
    the proposal; the record stays the office's decision.
    """
    if _mode_or_none() is None:
        return None

    name = (suggestion or {}).get("name")
    if not name or not isinstance(name, str) or not name.strip():
        return None

    from app.master_data.pending import SOURCE_AI
    return await _propose_all(
        user, [(ENTITY_ASSET_TYPE, name.strip()[:MAX_OBSERVED])], SOURCE_AI, source_ref,
        model_and_version or ASSET_AI_MODEL, "ai asset recognition")


# --------------------------------------------------------------------------
# internals — everything below is why a hook cannot break its caller
# --------------------------------------------------------------------------

def _mode_or_none() -> Optional[str]:
    """The mode, or None when Master Data must stay out of the way.

    ``off`` is the deployed default and returns before anything is imported or
    resolved. An unusable mode is a configuration problem that belongs in the
    logs — never in the middle of somebody's invoice upload.
    """
    try:
        mode = current_mode()
    except Exception:                                  # noqa: BLE001
        logger.warning("master_data: unusable MASTER_DATA_MODE; intake hook skipped")
        return None
    return None if mode == MODE_OFF else mode


async def _propose_all(user: Optional[Dict[str, Any]],
                       observed: List[Tuple[str, str]],
                       source_channel: str,
                       source_ref: Optional[str],
                       model_and_version: Optional[str],
                       label: str) -> Optional[Dict[str, int]]:
    """Propose each observed identity. Never raises; reports what happened."""
    if not observed:
        return None
    try:
        from app.master_data.pending import propose
        ctx = await _context_for(user)
        if ctx is None:
            logger.info("master_data: no resolved tenant on the %s path; nothing recorded",
                        label)
            return None

        summary = {"observed": len(observed), "recorded": 0, "repeated": 0, "failed": 0}
        for entity_type, raw_value in observed:
            try:
                outcome = await propose(
                    ctx,
                    entity_type=entity_type,
                    raw_value=raw_value,
                    source_channel=source_channel,
                    source_ref=source_ref,
                    model_and_version=model_and_version,
                )
            except Exception as exc:                   # noqa: BLE001
                # One bad row must not cost the rest of the import its
                # observations, and none of it may reach the caller.
                summary["failed"] += 1
                logger.warning("master_data: %s proposal failed for %r: %s",
                               label, raw_value, exc)
                continue
            if outcome.deduplicated:
                summary["repeated"] += 1
            elif outcome.performed:
                summary["recorded"] += 1
        logger.info("master_data: %s observed %s", label, summary)
        return summary
    except Exception as exc:                           # noqa: BLE001 — deliberate
        logger.warning("master_data: %s intake hook failed, ignored: %s", label, exc)
        return None


async def _context_for(user: Optional[Dict[str, Any]]):
    """Resolve the tenant context for a legacy path that only carries ``user``.

    Uses the existing W0-01 guard — no second resolver — and returns None when
    the tenant cannot be resolved server-side, because guessing one would be
    precisely the thing D-15 forbids.
    """
    if not user:
        return None
    from app.tenancy.guard import TenantContext, _resolve_active_tenant_id
    from app.tenancy import registry

    tenant_id = await _resolve_active_tenant_id(user)
    if not tenant_id:
        return None
    tenant = await registry.get_tenant(tenant_id)
    if not tenant:
        return None
    return TenantContext(tenant=tenant, user=user)
