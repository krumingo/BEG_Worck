"""
W0-06B — the canonical AuditEvent entry point of the storage/file-access slice.

One function, so every storage-provider, onboarding, access and integrity event
is a FLOW-040 envelope appended to the tenant's own chain (the same
``app.audit.store.record_event`` the registry uses, with its W0-06B concurrency
guarantee). ``structured_diff`` is masked by the envelope builder AND checked
here for provider secrets: a credential value can never be audited, even under
an innocent-looking key.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.audit.envelope import ACTOR_HUMAN, RESULT_SUCCESS, build_event
from app.audit.store import record_event
from app.files import models as m

# ------------------------------------------------------------- action names
ACTION_PROVIDER_CONNECTED = "storage.provider.connected"
ACTION_PROVIDER_VERIFIED = "storage.provider.verified"
ACTION_PROVIDER_VERIFICATION_FAILED = "storage.provider.verification_failed"
ACTION_FILE_UPLOADED = "file.uploaded"
ACTION_FILE_OPENED = "file.opened"
ACTION_FILE_DOWNLOADED = "file.downloaded"
ACTION_FILE_SHARED = "file.shared"
ACTION_ACCESS_GRANTED = "file.access.granted"
ACTION_PERMISSION_FAILED = "file.access.denied"

FORBIDDEN_DIFF_KEYS = ("password", "secret", "token", "refresh", "credential", "ciphertext",
                       "nonce", "authorization", "access_key", "sid")


def _scan(value: Any, path: str = "structured_diff") -> None:
    if isinstance(value, Mapping):
        for k, v in value.items():
            low = str(k).lower()
            if any(marker in low for marker in FORBIDDEN_DIFF_KEYS) and v not in (None, False, True):
                if v != "***MASKED***" and not low.endswith(("_names", "_present")):
                    raise ValueError("refusing to audit a secret-like field %s.%s" % (path, k))
            _scan(v, "%s.%s" % (path, k))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _scan(item, "%s[%d]" % (path, i))


async def record(tenant, *, action: str, actor_id: str, retention_class: str,
                 entity_type: str, entity_id: str, result: str = RESULT_SUCCESS,
                 reason: Optional[str] = None, structured_diff: Optional[Dict[str, Any]] = None,
                 related_file_ids: Optional[List[str]] = None, entity_version: Optional[str] = None,
                 idempotency_key: Optional[str] = None, error_code: Optional[str] = None,
                 actor_type: str = ACTOR_HUMAN) -> Dict[str, Any]:
    _scan(structured_diff or {})
    event = build_event(
        tenant_id=tenant.org_id, actor_type=actor_type, actor_id=actor_id, action=action,
        source_flow=m.SOURCE_FLOW, retention_class=retention_class, result=result,
        entity_type=entity_type, entity_id=entity_id, entity_version=entity_version,
        reason=reason, structured_diff=structured_diff, related_file_ids=related_file_ids or [],
        idempotency_key=idempotency_key, error_code=error_code)
    return await record_event(tenant.audit_store_db(), event)
