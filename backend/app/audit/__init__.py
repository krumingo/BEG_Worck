"""
W0-04 — Canonical AuditEvent + Idempotency foundation.

Additive package: one append-only AuditEvent envelope for the whole
system and one idempotency registry for consequential writes.
No existing collection is modified and no existing route is changed by
importing this package.

Canon: FLOW-040 (Business Lock), FLOW-043 (one common AuditEvent),
CLAUDE.md v15 rules 8 and 9, IMPLEMENTATION_WAVES.md W0-04.
"""
from app.audit.envelope import (
    build_event,
    validate_event,
    mask_sensitive,
    AuditEventInvalid,
    ACTOR_HUMAN,
    ACTOR_AI,
    ACTOR_SYSTEM,
    ACTOR_EXTERNAL,
    RETENTION_R1_CRITICAL_BUSINESS,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RETENTION_R3_SECURITY_ACCESS,
    RETENTION_R4_AI_CONTENT,
    RETENTION_R5_TECHNICAL_DIAGNOSTIC,
    RETENTION_CLASSES,
    RESULT_SUCCESS,
    RESULT_FAILURE,
    RESULT_DENIED,
)
from app.audit.store import (
    record_event,
    record_correction,
    record_reversal,
    record_annotation,
    verify_chain,
    chain_hashes,
    AuditAppendOnlyViolation,
)
from app.audit.idempotency import (
    IdempotencyConflict,
    begin_idempotent,
    complete_idempotent,
    fail_idempotent,
    IDEMPOTENCY_STARTED,
    IDEMPOTENCY_DUPLICATE,
    IDEMPOTENCY_COMPLETED,
)

__all__ = [
    "build_event",
    "validate_event",
    "mask_sensitive",
    "AuditEventInvalid",
    "ACTOR_HUMAN",
    "ACTOR_AI",
    "ACTOR_SYSTEM",
    "ACTOR_EXTERNAL",
    "RETENTION_R1_CRITICAL_BUSINESS",
    "RETENTION_R2_PROJECT_OPERATIONAL",
    "RETENTION_R3_SECURITY_ACCESS",
    "RETENTION_R4_AI_CONTENT",
    "RETENTION_R5_TECHNICAL_DIAGNOSTIC",
    "RETENTION_CLASSES",
    "RESULT_SUCCESS",
    "RESULT_FAILURE",
    "RESULT_DENIED",
    "record_event",
    "record_correction",
    "record_reversal",
    "record_annotation",
    "verify_chain",
    "chain_hashes",
    "AuditAppendOnlyViolation",
    "IdempotencyConflict",
    "begin_idempotent",
    "complete_idempotent",
    "fail_idempotent",
    "IDEMPOTENCY_STARTED",
    "IDEMPOTENCY_DUPLICATE",
    "IDEMPOTENCY_COMPLETED",
]
