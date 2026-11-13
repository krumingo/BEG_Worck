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
from app.services.auth_tx import run_in_transaction
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

# SEC-03 FG-517 / FG-535: redaction errs on the side of hiding. Anything that LOOKS
# like an IBAN or a ЕГН/ЛНЧ is replaced — checksum valid or not, any case, with
# spaces, NBSP, several spaces or dashes between the groups, and next to commas,
# dots or other numbers. Over-redaction (e.g. a 10-digit phone or invoice number)
# is accepted; a leaked personal id is not.
_SEP = r"[ \t\u00a0\u202f\-]"
# IBAN: 2 letters + 2 digits, then alphanumeric groups separated by _SEP runs.
_IBAN_START = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}")
_IBAN_GROUP = re.compile(r"(%s*)([A-Za-z0-9]+)" % _SEP)
IBAN_MIN_LEN, IBAN_MAX_LEN = 15, 34
# ЕГН / ЛНЧ (both 10 digits) and any longer id: a run of digits, single _SEP
# characters allowed between them, of 10 digits or more.


def _redact_ibans(text: str) -> str:
    """From every possible IBAN start, take the following alphanumeric groups up to
    the LAST group that contains a digit (bank codes like BNBG are kept inside, but
    trailing words such as "and more" are not swallowed); redact when the compact
    length is IBAN-like (15–34). No checksum: a mistyped IBAN is still personal."""
    out, pos = [], 0
    for m in _IBAN_START.finditer(text):
        if m.start() < pos:
            continue
        compact, end_ok, i = m.group(0), m.end(), m.end()
        while len(compact) < IBAN_MAX_LEN:
            g = _IBAN_GROUP.match(text, i)
            if not g or not g.group(2).isascii():
                break
            compact += g.group(2)
            i = g.end()
            if any(ch.isdigit() for ch in g.group(2)):
                end_ok = i
        compact_ok = re.sub(r"[^A-Za-z0-9]", "", text[m.start():end_ok])
        if IBAN_MIN_LEN <= len(compact_ok):
            out.append(text[pos:m.start()])
            out.append(REDACTED)
            pos = end_ok
    out.append(text[pos:])
    return "".join(out)


# SEC-03 FG-604: one switch for EVERY ЕГН-shaped form (bare 10 digits, 6+4 and
# 2+2+2+4 with any single separator). False (default, until Krum decides):
# everything ЕГН-shaped is hidden. True: only those whose month + checksum are valid.
REDACT_EGN_REQUIRE_CHECKSUM = False

# Unicode spaces (NBSP, thin, hair, figure, narrow NBSP, ideographic …) become a
# plain space; invisible characters (zero-width, soft hyphen …) are dropped.
_UNICODE_SPACES = re.compile("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
_INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u180e]")
# Any run of digits with single separators between them (space . - / _), not
# touching further digits. Exactly 10 digits = ЕГН/ЛНЧ-shaped (the switch
# applies); 11 or more = a long id, always hidden.
_ID_RUN = re.compile(r"(?<!\d)\d(?:[ .\-/_]?\d)*(?!\d)")
_EGN_WEIGHTS = (2, 4, 8, 5, 10, 9, 7, 3, 6)


def egn_checksum_valid(digits: str) -> bool:
    if len(digits) != 10 or not digits.isdigit():
        return False
    month = int(digits[2:4])
    if not (1 <= month <= 12 or 21 <= month <= 32 or 41 <= month <= 52):
        return False
    check = sum(int(d) * w for d, w in zip(digits, _EGN_WEIGHTS)) % 11
    return (0 if check == 10 else check) == int(digits[9])


def _redact_digit_ids(text: str) -> str:
    def repl(m):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) > 10:
            return REDACTED
        if len(digits) == 10 and (not REDACT_EGN_REQUIRE_CHECKSUM or egn_checksum_valid(digits)):
            return REDACTED
        return m.group(0)
    return _ID_RUN.sub(repl, text)


def redact_personal(text: str) -> str:
    """Replace anything IBAN-like and any ЕГН/ЛНЧ-shaped or longer digit id before
    the model sees it (one rule for every ЕГН form, governed by
    REDACT_EGN_REQUIRE_CHECKSUM)."""
    if not text:
        return text
    text = _UNICODE_SPACES.sub(" ", _INVISIBLE.sub("", text))
    return _redact_digit_ids(_redact_ibans(text))


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


class AIPhotoNeedsFileRegistry(RuntimeError):
    """SEC-03 FG-522 (CLAUDE.md §4): the original photo must be stored before any AI
    processing, and the canonical File Registry (W0-06) does not exist yet."""

    def __init__(self):
        super().__init__(AI_PHOTO_NEEDS_FILE_REGISTRY_MESSAGE)


AI_PHOTO_NEEDS_FILE_REGISTRY_MESSAGE = (
    "AI по снимка изисква файлов регистър (W0-06): оригиналът трябва да се запази преди обработка")
#: Flipped only when W0-06 stores the original through the File Registry first.
PHOTO_AI_FILE_REGISTRY_READY = False

#: SEC-03 FG-519 (FLOW-050): one row per completed AI action, per tenant — the
#: count the monthly AI budget (Start 100 / Control 500 / Pro 2000 + add-ons)
#: is measured against. No ledger existed on main; this is the one.
AI_USAGE_LEDGER = "ai_usage_ledger"


def require_photo_ai() -> None:
    if not PHOTO_AI_FILE_REGISTRY_READY:
        raise AIPhotoNeedsFileRegistry()


def _usage(response) -> dict:
    u = getattr(response, "usage", None)
    def _n(name):
        try:
            return int(getattr(u, name, 0) or 0)
        except (TypeError, ValueError):
            return 0
    return {"input_tokens": _n("input_tokens"), "output_tokens": _n("output_tokens")}


class AIAuditFailed(AIProviderError):
    """SEC-03 FG-536: the AuditEvent + ledger row of a completed call could not be
    committed together; nothing is counted and the AI result is not returned."""


async def _record_call(org_id: str, user_id: Optional[str], feature: str, outcome: str,
                       usage: dict, error_type: Optional[str] = None) -> None:
    """Canonical AuditEvent of one AI call — metadata only: no prompt, no response,
    no personal data, no key. A COMPLETED call also writes its ledger row, and both
    commit in ONE transaction (FG-536): if the audit fails, no counted action remains."""
    from datetime import datetime, timezone
    import uuid
    from app.audit.envelope import (ACTOR_HUMAN, RESULT_FAILURE, RESULT_SUCCESS,
                                    RETENTION_R4_AI_CONTENT, build_event)
    from app.audit.store import record_event
    now = datetime.now(timezone.utc)
    event = build_event(
        tenant_id=org_id, actor_type=ACTOR_HUMAN, actor_id=user_id or "unknown",
        action="ai.call.%s" % outcome, source_flow="FLOW-050",
        retention_class=RETENTION_R4_AI_CONTENT,
        result=RESULT_SUCCESS if outcome == "completed" else RESULT_FAILURE,
        entity_type="ai_call", entity_id=feature,
        # "usage_in"/"usage_out", not "*_tokens": the AuditEvent masker treats any key
        # containing "token" as a credential, and these are plain counts.
        structured_diff={"feature": feature, "outcome": outcome,
                         "usage_in": usage["input_tokens"], "usage_out": usage["output_tokens"]},
        model_and_version=model_and_version(), source_channel="api",
        tool_or_endpoint="ai_provider.complete:%s" % feature, error_code=error_type,
    )
    if outcome != "completed":
        await record_event(db, event)
        return
    row = {"id": str(uuid.uuid4()), "org_id": org_id, "user_id": user_id, "feature": feature,
           "model_and_version": model_and_version(), "actions": 1,
           "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
           "period": now.strftime("%Y-%m"), "occurred_at": now.isoformat(),
           "audit_event_id": event["event_id"]}

    async def body(session):
        await TenantData.for_resolved_org(db, org_id).collection(AI_USAGE_LEDGER).insert_one(
            dict(row), session=session)
        await record_event(db, dict(event), session=session)
    try:
        await run_in_transaction(db, body)
    except Exception as exc:
        logger.warning("AI call audit/ledger not committed: %s", type(exc).__name__)
        raise AIAuditFailed("AI call could not be recorded (%s)" % type(exc).__name__) from None


async def complete(org_id: Optional[str], *, user_id: Optional[str], feature: str,
                   system: str, text: str, images: Optional[List[str]] = None,
                   max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """One model call; returns the text of the answer.

    Raises :class:`AINotConfigured` (caller falls back / answers "AI не е
    настроен"), :class:`AIPhotoNeedsFileRegistry` (photos, until W0-06) or
    :class:`AIProviderError` (the call itself failed). Every call that reaches
    the provider writes an AuditEvent; a completed one also a ledger row.
    """
    if images:
        require_photo_ai()
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
        await _record_call(org_id, user_id, feature, "failed",
                           {"input_tokens": 0, "output_tokens": 0}, type(exc).__name__)
        raise AIProviderError("AI provider call failed (%s)" % type(exc).__name__) from None
    await _record_call(org_id, user_id, feature, "completed", _usage(response))
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
