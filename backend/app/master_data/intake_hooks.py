"""
W0-03 — observation hooks for existing automated intake paths.

One job: let a real legacy path *tell* Master Data what it saw, without being
able to break. Every hook here is:

  * a no-op when ``MASTER_DATA_MODE`` is ``off`` — the deployed default — and
    returns before touching anything;
  * incapable of raising into the caller. A hook that can fail an invoice
    upload because a proposal could not be recorded would be a worse bug than
    the one it is meant to help with, so everything is swallowed and reported;
  * never able to create a Master record: it calls ``pending.propose`` and
    nothing else.

This is how the end-to-end path is proven in shadow before anything is switched
to enforce.
"""
import logging
from typing import Any, Dict, Optional

from app.master_data.deps import MODE_OFF, current_mode
from app.master_data.models import ENTITY_ORGANIZATION

logger = logging.getLogger(__name__)

#: Cap on what a hook will look at; OCR text can be long and the pending record
#: keeps the raw value, not the document.
MAX_OBSERVED = 200


async def observe_ocr_supplier(user: Optional[Dict[str, Any]],
                               detected: Optional[Dict[str, Any]],
                               source_ref: Optional[str] = None) -> Optional[Any]:
    """Offer an OCR-detected supplier name to pending mapping.

    Returns the outcome when the hook ran, ``None`` when it did nothing. The
    caller is expected to ignore both.
    """
    try:
        if current_mode() == MODE_OFF:
            return None
    except Exception:                                  # noqa: BLE001 — a bad mode must not
        logger.warning("master_data: unusable MASTER_DATA_MODE; intake hook skipped")
        return None                                    # break an invoice upload

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
