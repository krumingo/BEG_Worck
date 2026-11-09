"""
SEC-03 / Р76 — the ONE AI provider adapter: Anthropic (Claude), called directly
through the official ``anthropic`` Python SDK (version pinned in
requirements.txt). Nothing goes through Emergent any more.

Rules (CLAUDE.md §10, §16; FLOW-040 §4.4):

* The API key comes ONLY from the environment / secret store
  (``ANTHROPIC_API_KEY``) and the model ONLY from configuration
  (``ANTHROPIC_MODEL``). There is no key and no model id in the code.
* Without key or model — or while the tenant's ``ai_enabled`` flag is off
  (the default) — every AI function gets :class:`AINotConfigured`
  ("AI не е настроен"); callers fall back to their manual / rule-based path,
  so AI is never a single point of failure.
* The adapter never writes a business record. Callers return a proposal that a
  person confirms through the normal (permission-checked) write path.
* Text sent to the model is minimised: ЕГН and IBAN are replaced before the
  call. Nothing of the request, the response or the key is logged.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Callable, List, Optional

from app.db import db
from app.tenancy.data_access import TenantData

logger = logging.getLogger(__name__)

API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL_ENV = "ANTHROPIC_MODEL"
PROVIDER = "anthropic"
#: Per-tenant feature flag (``feature_flags`` row, ``module_code``); absent = off.
AI_FLAG = "ai_enabled"
AI_NOT_CONFIGURED_MESSAGE = "AI не е настроен"
REDACTED = "[скрито]"
DEFAULT_MAX_TOKENS = 2000
REQUEST_TIMEOUT_SECONDS = 60.0


class AINotConfigured(RuntimeError):
    """AI is not available for this call (no key / no model / tenant flag off)."""

    def __init__(self, reason: str):
        super().__init__(AI_NOT_CONFIGURED_MESSAGE)
        self.reason = reason


class AIProviderError(RuntimeError):
    """The provider call failed. The message never carries request content or the key."""


# ── configuration ──────────────────────────────────────────────────

def _api_key() -> str:
    return (os.environ.get(API_KEY_ENV) or "").strip()


def model_name() -> str:
    return (os.environ.get(MODEL_ENV) or "").strip()


def model_and_version() -> str:
    """For AuditEvents (FLOW-040 §4.4): ``anthropic/<configured model>``."""
    return "%s/%s" % (PROVIDER, model_name() or "unconfigured")


def is_configured() -> bool:
    return bool(_api_key() and model_name())


async def ai_enabled_for_tenant(org_id: Optional[str]) -> bool:
    if not org_id:
        return False
    tenant = TenantData.for_resolved_org(db, org_id)
    row = await tenant.feature_flags.find_one(
        {"org_id": org_id, "module_code": AI_FLAG}, {"_id": 0, "enabled": 1})
    return bool(row and row.get("enabled") is True)


async def require_ai(org_id: Optional[str]) -> None:
    """Raise :class:`AINotConfigured` unless AI may be used for this tenant now."""
    if not _api_key():
        raise AINotConfigured("no_api_key")
    if not model_name():
        raise AINotConfigured("no_model")
    if not await ai_enabled_for_tenant(org_id):
        raise AINotConfigured("disabled_for_tenant")


# ── data minimisation ─────────────────────────────────────────────

# IBAN: 2 letters, 2 check digits, 11–30 alphanumerics (spaces allowed in groups).
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
# ЕГН: exactly 10 digits, not part of a longer number.
_EGN_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")


def redact_personal(text: str) -> str:
    """Replace IBAN and ЕГН in text that is about to leave for the model."""
    if not text:
        return text
    text = _IBAN_RE.sub(REDACTED, text)
    return _EGN_RE.sub(REDACTED, text)


_DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,", re.IGNORECASE)
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def image_block(image_base64: str) -> dict:
    """An Anthropic image content block from a base64 string (optionally a data URL)."""
    data = (image_base64 or "").strip()
    media_type = None
    m = _DATA_URL_RE.match(data)
    if m:
        media_type = m.group(1).lower()
        data = data[m.end():]
    if media_type is None:
        try:
            head = base64.b64decode(data[:64] + "=" * (-len(data[:64]) % 4), validate=False)
        except (ValueError, TypeError):
            head = b""
        for magic, mt in _MAGIC:
            if head.startswith(magic):
                media_type = mt
                break
        else:
            media_type = "image/webp" if head[8:12] == b"WEBP" else "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


# ── the call ──────────────────────────────────────────────────────

def _default_client_factory(api_key: str):
    try:
        import anthropic
    except ImportError as exc:  # the pinned SDK is part of requirements.txt
        raise AINotConfigured("sdk_missing") from exc
    return anthropic.AsyncAnthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=1)


#: Replaced by tests with a fake; production uses the official SDK.
client_factory: Callable[[str], object] = _default_client_factory


async def complete(org_id: Optional[str], *, system: str, text: str,
                   images: Optional[List[str]] = None,
                   max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """One model call; returns the text of the answer.

    Raises :class:`AINotConfigured` (caller falls back / answers "AI не е
    настроен") or :class:`AIProviderError` (the call itself failed).
    """
    await require_ai(org_id)
    content: List[dict] = [image_block(b) for b in (images or []) if b]
    content.append({"type": "text", "text": redact_personal(text)})
    client = client_factory(_api_key())
    try:
        response = await client.messages.create(
            model=model_name(),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        # Type only: an SDK error text can echo request details.
        logger.warning("AI provider call failed: %s", type(exc).__name__)
        raise AIProviderError("AI provider call failed (%s)" % type(exc).__name__) from None
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("```"))
    return text.strip()
