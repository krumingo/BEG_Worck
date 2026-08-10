"""
W0-04 — Canonical AuditEvent envelope.

One envelope for every audited action in BEG_Work. There is no second
journal: AI Audit, Finance Audit, Security Audit are permission-filtered
VIEWS over these events, never separate stores (FLOW-040 §1, §2).

This module is pure logic: building, validating and masking an event
dict. Persistence (append-only store, hash chain) lives in store.py.

Canon: FLOW-040 §3 (envelope), §6 (retention classes), §9 (data
minimization), §15 (forbidden events).
"""
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import uuid

# ---------------------------------------------------------------------------
# Actor types (FLOW-040 §3: who or which system performed the action)
# ---------------------------------------------------------------------------
ACTOR_HUMAN = "human"
ACTOR_AI = "ai"
ACTOR_SYSTEM = "system"
ACTOR_EXTERNAL = "external_principal"

ACTOR_TYPES = {ACTOR_HUMAN, ACTOR_AI, ACTOR_SYSTEM, ACTOR_EXTERNAL}

# ---------------------------------------------------------------------------
# Retention classes (FLOW-040 §6). R6 (legal/incident hold) is not a class
# assigned at creation — it is a flag applied later, so it is not listed
# among the creation-time classes.
# ---------------------------------------------------------------------------
RETENTION_R1_CRITICAL_BUSINESS = "R1"
RETENTION_R2_PROJECT_OPERATIONAL = "R2"
RETENTION_R3_SECURITY_ACCESS = "R3"
RETENTION_R4_AI_CONTENT = "R4"
RETENTION_R5_TECHNICAL_DIAGNOSTIC = "R5"

RETENTION_CLASSES = {
    RETENTION_R1_CRITICAL_BUSINESS,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RETENTION_R3_SECURITY_ACCESS,
    RETENTION_R4_AI_CONTENT,
    RETENTION_R5_TECHNICAL_DIAGNOSTIC,
}

# Result values
RESULT_SUCCESS = "success"
RESULT_FAILURE = "failure"
RESULT_DENIED = "denied"

# ---------------------------------------------------------------------------
# Required fields. FLOW-040 §15: an event without tenant, actor, timestamp,
# action and source must never be accepted.
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = (
    "event_id",
    "tenant_id",
    "occurred_at",
    "recorded_at",
    "actor_type",
    "actor_id",
    "action",
    "source_flow",
    "retention_class",
    "result",
)

# ---------------------------------------------------------------------------
# Data minimization (FLOW-040 §9): keys that must NEVER be stored in an
# audit event, in any nesting level of payload / diff / reason.
# ---------------------------------------------------------------------------
SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "authorization",
    "private_key",
    "refresh_token",
    "access_key",
)

MASKED_VALUE = "***MASKED***"


class AuditEventInvalid(ValueError):
    """The event violates a FLOW-040 rule and must not be written."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def mask_sensitive(value: Any) -> Any:
    """
    Recursively replace values of secret-looking keys with a mask.

    Returns a new structure; the input is never modified in place.
    FLOW-040 §9: secrets are removed BEFORE the event is written.
    """
    if isinstance(value, dict):
        return {
            k: (MASKED_VALUE if _key_is_sensitive(k) else mask_sensitive(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def build_event(
    *,
    tenant_id: str,
    actor_type: str,
    actor_id: str,
    action: str,
    source_flow: str,
    retention_class: str,
    result: str = RESULT_SUCCESS,
    # entity being acted upon
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_version: Optional[str] = None,
    # scope
    scope_type: Optional[str] = None,
    scope_id: Optional[str] = None,
    # evidence / diff. References, not full payload copies (FLOW-040 §3).
    before_reference: Optional[str] = None,
    after_reference: Optional[str] = None,
    structured_diff: Optional[Dict[str, Any]] = None,
    # why / how
    reason: Optional[str] = None,
    source_channel: Optional[str] = None,
    tool_or_endpoint: Optional[str] = None,
    model_and_version: Optional[str] = None,
    # human confirmation of AI proposals (FLOW-040 §5)
    confirmation_required: bool = False,
    confirmed_by: Optional[str] = None,
    confirmed_at: Optional[str] = None,
    approval_id: Optional[str] = None,
    # correlation
    correlation_id: Optional[str] = None,
    request_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    related_file_ids: Optional[List[str]] = None,
    effective_role_assignments: Optional[List[str]] = None,
    error_code: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a canonical AuditEvent dict, masked and validated.

    Raises AuditEventInvalid when a FLOW-040 rule is violated. The caller
    should treat that as a programming error, never swallow it.
    """
    event: Dict[str, Any] = {
        "event_id": f"ae_{uuid.uuid4()}",
        "tenant_id": tenant_id,
        "occurred_at": occurred_at or _now_iso(),
        "recorded_at": _now_iso(),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "effective_role_assignments": effective_role_assignments or [],
        "scope_type": scope_type,
        "scope_id": scope_id,
        "action": action,
        "source_flow": source_flow,
        "source_channel": source_channel,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity_version": entity_version,
        "before_reference": before_reference,
        "after_reference": after_reference,
        "structured_diff": mask_sensitive(structured_diff) if structured_diff else None,
        "reason": reason,
        "tool_or_endpoint": tool_or_endpoint,
        "model_and_version": model_and_version,
        "confirmation_required": confirmation_required,
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
        "approval_id": approval_id,
        "correlation_id": correlation_id,
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "related_file_ids": related_file_ids or [],
        "retention_class": retention_class,
        "retention_anchor": None,  # set when the related business period closes
        "legal_hold": False,       # R6 flag, applied later, never at creation
        "result": result,
        "error_code": error_code,
        # Integrity fields are assigned by the store at append time.
        "sequence": None,
        "previous_hash": None,
        "integrity_hash": None,
    }
    validate_event(event)
    return event


def validate_event(event: Dict[str, Any]) -> None:
    """Enforce FLOW-040 §15 invariants. Raises AuditEventInvalid."""
    missing = [f for f in REQUIRED_FIELDS if not event.get(f)]
    if missing:
        raise AuditEventInvalid(f"AuditEvent missing required fields: {missing}")

    if event["actor_type"] not in ACTOR_TYPES:
        raise AuditEventInvalid(f"Unknown actor_type: {event['actor_type']}")

    if event["retention_class"] not in RETENTION_CLASSES:
        raise AuditEventInvalid(f"Unknown retention_class: {event['retention_class']}")

    # AI actions must be attributable to a model (FLOW-040 §4.4).
    if event["actor_type"] == ACTOR_AI and not event.get("model_and_version"):
        raise AuditEventInvalid("AI event requires model_and_version")

    # An AI action that required human confirmation cannot be recorded as
    # successfully executed without a confirming human (FLOW-040 §5).
    if (
        event["actor_type"] == ACTOR_AI
        and event.get("confirmation_required")
        and event.get("result") == RESULT_SUCCESS
        and not event.get("confirmed_by")
    ):
        raise AuditEventInvalid(
            "AI action with confirmation_required cannot succeed without confirmed_by"
        )

    # Data minimization: no secret may survive into the stored event.
    _assert_no_secrets(event.get("structured_diff"))


def _assert_no_secrets(value: Any, path: str = "structured_diff") -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if _key_is_sensitive(k) and v != MASKED_VALUE:
                raise AuditEventInvalid(f"Unmasked sensitive key in event: {path}.{k}")
            _assert_no_secrets(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _assert_no_secrets(item, f"{path}[{i}]")
