"""
W0-02 PR-05 — recoverable multi-step write for the migrated enforce paths.

Why: a migrated write touches TWO databases — the business record and the
legacy audit row in the tenant's operational database, and the authoritative
RoleAssignment in the SYSTEM database. A multi-document transaction across
them is not available (and would need a replica set, which is not part of this
change), so the boundary is a *recoverable, idempotent workflow* with a visible
pending/failed state, built on the canonical W0-04 idempotency registry
(`audit_idempotency` in the tenant database):

    reserve key (STARTED)
      -> step "…"   (each step idempotent; marked done with its reference)
      -> COMPLETED (result_reference)
    any failure  -> FAILED (error_code visible); the SAME request retried
                    re-opens the key, skips the steps already done and
                    performs the rest — nothing is done twice.

Order of steps is chosen so that an interruption can only leave the SAFE side:
the authoritative assignment is written before (role change) or is missing
after (new user) a partial failure — never a stale broad grant.

This is bookkeeping for the migrated enforce paths only; off/shadow keep the
legacy path unchanged.
"""
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import HTTPException

from app.audit.idempotency import (
    begin_idempotent, complete_idempotent, fail_idempotent, mark_idempotent_step,
    request_fingerprint, IdempotencyConflict,
    IDEMPOTENCY_COMPLETED, IDEMPOTENCY_DUPLICATE,
)

ERROR_SYNC_FAILED = "PERMISSION_SYNC_FAILED"
ERROR_WRITE_INCOMPLETE = "WRITE_INCOMPLETE"


class RecoverableWrite:
    """One reserved idempotency key + the steps performed under it."""

    def __init__(self, db, *, tenant_id: str, action: str, key: str, fingerprint: Optional[str]):
        self.db = db
        self.tenant_id = tenant_id
        self.action = action
        self.key = key
        self.fingerprint = fingerprint
        self.state: Dict[str, Any] = {}
        self.steps_done: set = set()
        self.step_refs: Dict[str, Any] = {}
        self.completed_reference: Optional[str] = None
        self.resumed = False

    @property
    def record_ref(self) -> Dict[str, str]:
        return {"idempotency_action": self.action, "idempotency_key": self.key}

    async def begin(self) -> "RecoverableWrite":
        """Reserve the key. Raises HTTP 409 on a different payload under the same key."""
        try:
            self.state = await begin_idempotent(
                self.db, tenant_id=self.tenant_id, key=self.key, action=self.action,
                request_fingerprint=self.fingerprint)
        except IdempotencyConflict:
            raise HTTPException(status_code=409, detail={
                "error_code": "IDEMPOTENCY_CONFLICT",
                "message": "The same operation key was already used with a different payload",
                **self.record_ref})
        record = self.state.get("record") or {}
        self.steps_done = set(record.get("steps_done") or [])
        self.step_refs = dict(record.get("step_refs") or {})
        if self.state.get("status") == IDEMPOTENCY_DUPLICATE:
            if self.state.get("prior_status") == IDEMPOTENCY_COMPLETED:
                self.completed_reference = self.state.get("result_reference")
            else:
                self.resumed = True          # an interrupted attempt: continue it
        elif self.state.get("retry_of_failed"):
            self.resumed = True
        return self

    @property
    def already_completed(self) -> bool:
        return self.completed_reference is not None

    async def step(self, name: str, fn: Callable[[], Awaitable[Any]], *,
                   reference: Optional[Callable[[Any], str]] = None) -> Any:
        """Run one idempotent step unless it was already done under this key."""
        if name in self.steps_done:
            return self.step_refs.get(name)
        result = await fn()
        ref = reference(result) if (reference and result is not None) else None
        await mark_idempotent_step(self.db, tenant_id=self.tenant_id, key=self.key,
                                   action=self.action, step=name, reference=ref)
        self.steps_done.add(name)
        if ref is not None:
            self.step_refs[name] = ref
        return ref if ref is not None else result

    async def fail(self, error_code: str) -> None:
        await fail_idempotent(self.db, tenant_id=self.tenant_id, key=self.key,
                              action=self.action, error_code=error_code)

    async def complete(self, result_reference: str) -> None:
        await complete_idempotent(self.db, tenant_id=self.tenant_id, key=self.key,
                                  action=self.action, result_reference=result_reference)

    def failure_response(self, error_code: str, exc: Exception) -> HTTPException:
        """The honest answer for a partially performed write: the state is
        recorded as FAILED, the client may repeat the SAME request to finish it."""
        return HTTPException(status_code=503, detail={
            "error_code": error_code,
            "state": "failed",
            "message": "The write was interrupted after a partial step; the failed state is "
                       "recorded. Repeat the same request to complete it.",
            "steps_done": sorted(self.steps_done),
            "cause": f"{type(exc).__name__}",
            **self.record_ref,
        })


def fingerprint_without(payload: Dict[str, Any], *drop: str) -> str:
    """Fingerprint of a request body minus fields that must never be stored
    (even hashed), e.g. passwords."""
    return request_fingerprint({k: v for k, v in payload.items() if k not in drop})
