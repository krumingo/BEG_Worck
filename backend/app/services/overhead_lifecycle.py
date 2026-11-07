"""
OH-01 — overhead records are never hard-deleted; a re-allocation is a new version.

Package: ``docs/architecture/tasks/OH-01_OVERHEAD_NO_HARD_DELETE.md`` (CLAUDE.md §2.9 no
hard delete of used/financial records, §7 correction instead of edit, §14 consequential
write; FLOW-024 "the allocation keeps its version"; R29 a money write without an
``Idempotency-Key`` is refused).

What lives here (the route ``app/routes/overhead.py`` keeps its own tenant reads/writes):

* ``KeyedWrite`` — one overhead money write under a REQUIRED ``Idempotency-Key`` on the
  canonical W0-04 registry (``app.audit.idempotency`` through ``RecoverableWrite``):

    no key                    -> 428 ``IDEMPOTENCY_KEY_REQUIRED``, nothing written (R29);
    same key + same body      -> the original result, nothing written again;
    same key + different body -> 409 ``IDEMPOTENCY_CONFLICT``, nothing written;
    same key while running    -> 409 ``IDEMPOTENCY_IN_PROGRESS``;
    a failed attempt          -> the same request may finish it (ids derive from the key).

  The key is scoped per tenant, per action and per user (as SEC-01-C03 ``MoneyWrite``,
  PR #69 — when #69 is in main this class can be replaced by ``MoneyWrite`` 1:1).

* ``audit_overhead_event`` — the canonical append-only AuditEvent (FLOW-040 envelope,
  ``source_flow=FLOW-024``) for an archive and for a new allocation version, written to the
  SAME database handle the overhead collections use.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.audit.idempotency import (
    IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED, request_fingerprint,
)
from app.permissions.workflow import RecoverableWrite

ERROR_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
ERROR_IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
ERROR_OVERHEAD_WRITE_FAILED = "OVERHEAD_WRITE_FAILED"
MAX_KEY_LENGTH = 200

STATUS_ARCHIVED = "archived"
#: A legacy record without ``status`` is active (OH-01: no data migration).
NOT_ARCHIVED = {"$ne": STATUS_ARCHIVED}
#: The current allocation version: ``superseded_by`` absent or null.
CURRENT_VERSION = None

_NS = uuid.UUID("0b1c0a7e-0d01-4c24-9f1a-0e0000000001")

#: OH01-1: one allocation of a snapshot at a time (the lock pattern of PR #70 ``_row_lock``).
ALLOCATION_LOCK_FIELD = "allocation_lock"
ALLOCATION_LOCK_STALE_SECONDS = 30
ALLOCATIONS_COLLECTION = "project_overhead_allocations"
#: OH01-1: no two rows of the same snapshot, version and project — two concurrent writers
#: can never both produce "version N" (legacy rows without a version are not covered).
ALLOCATION_VERSION_INDEX = "oh01_snapshot_version_project_unique"


def require_key(raw_key: Optional[str]) -> str:
    """The trimmed ``Idempotency-Key``; 428 when absent (R29), 422 when too long."""
    key = (raw_key or "").strip()
    if len(key) > MAX_KEY_LENGTH:
        raise HTTPException(status_code=422, detail={
            "error_code": "IDEMPOTENCY_KEY_INVALID",
            "message": "Idempotency-Key is longer than %d characters" % MAX_KEY_LENGTH})
    if not key:
        raise HTTPException(status_code=428, detail={
            "error_code": ERROR_KEY_REQUIRED,
            "message": "Записът на режийни изисква заглавие Idempotency-Key"})
    return key


class KeyedWrite:
    """One overhead write under a required ``Idempotency-Key``.

    Usage (after the permission check and the reads, right before the writes)::

        kw = await KeyedWrite.begin(db, user, "overhead.x.archive", key, body)
        if kw.replay_id:
            return <the stored result of kw.replay_id>
        async with kw:
            ... writes, ids from kw.new_id(...) ...
            kw.result_id = "<id>"
    """

    def __init__(self, db, user: Dict[str, Any], action: str, key: str):
        self.db = db
        self.user = user
        self.action = action
        self.key = key
        self.wf: Optional[RecoverableWrite] = None
        self.replay_id: Optional[str] = None
        self.result_id: Optional[str] = None

    @classmethod
    async def begin(cls, db, user: Dict[str, Any], action: str, key: str,
                    body: Any) -> "KeyedWrite":
        kw = cls(db, user, action, "%s:%s" % (user["id"], require_key(key)))
        kw.wf = await RecoverableWrite(
            db, tenant_id=user["org_id"], action=action, key=kw.key,
            fingerprint=request_fingerprint(body)).begin()      # 409 on a different body
        state = kw.wf.state
        if kw.wf.already_completed:
            kw.replay_id = kw.wf.completed_reference
        elif (state.get("status") == IDEMPOTENCY_DUPLICATE
              and state.get("prior_status") == IDEMPOTENCY_STARTED):
            raise HTTPException(status_code=409, detail={
                "error_code": ERROR_IDEMPOTENCY_IN_PROGRESS,
                "message": "Същата заявка още се изпълнява; опитайте отново след малко",
                **kw.wf.record_ref})
        return kw

    def new_id(self, name: str) -> str:
        """The SAME id on every attempt of this key (a resumed attempt never duplicates)."""
        return str(uuid.uuid5(_NS, "%s\x1f%s\x1f%s\x1f%s" % (
            self.user["org_id"], self.action, self.key, name)))

    async def refuse(self, exc: HTTPException) -> HTTPException:
        """A business refusal (409 used/archived) after the key was reserved: the key is
        recorded FAILED, so the same request may be repeated once the cause is gone."""
        await self.wf.fail(str(exc.status_code))
        return exc

    async def __aenter__(self) -> "KeyedWrite":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            await self.wf.complete(self.result_id)
            return False
        await self.wf.fail(ERROR_OVERHEAD_WRITE_FAILED)
        return False


async def audit_overhead_event(db, user: Dict[str, Any], *, action: str, entity_type: str,
                               entity_id: str, reason: Optional[str],
                               structured_diff: Optional[Dict[str, Any]] = None,
                               idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Append the canonical AuditEvent (FLOW-040 envelope) for an OH-01 write."""
    from app.audit.envelope import (
        ACTOR_HUMAN, RESULT_SUCCESS, RETENTION_R1_CRITICAL_BUSINESS, build_event,
    )
    from app.audit.store import record_event
    event = build_event(
        tenant_id=user["org_id"],
        actor_type=ACTOR_HUMAN,
        actor_id=user["id"],
        action=action,
        source_flow="FLOW-024",
        retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        result=RESULT_SUCCESS,
        entity_type=entity_type,
        entity_id=entity_id,
        structured_diff=structured_diff,
        reason=reason,
        source_channel="api",
        idempotency_key=idempotency_key,
    )
    return await record_event(db, event)


async def ensure_allocation_indexes(db) -> None:
    """OH01-1: the unique (org, snapshot, version, project) index on allocation rows.
    ``create_index`` with the same name and spec is a no-op, so this is idempotent."""
    await db[ALLOCATIONS_COLLECTION].create_index(
        [("org_id", 1), ("overhead_snapshot_id", 1), ("allocation_version", 1), ("project_id", 1)],
        name=ALLOCATION_VERSION_INDEX, unique=True,
        partialFilterExpression={"allocation_version": {"$exists": True}})


@asynccontextmanager
async def snapshot_allocation_lock(snapshots, snapshot_id: str):
    """OH01-1: a short exclusive lock on ONE snapshot row, taken with one atomic conditional
    write (``snapshots`` is the request's tenant-scoped collection). A concurrent holder ->
    409 ``ALLOCATION_BUSY``, nothing written; a lock older than
    ALLOCATION_LOCK_STALE_SECONDS (crashed holder) can be taken over. Always released by
    its own token."""
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(seconds=ALLOCATION_LOCK_STALE_SECONDS)).isoformat()
    won = await snapshots.update_one(
        {"id": snapshot_id, "$or": [{ALLOCATION_LOCK_FIELD: {"$exists": False}},
                                    {ALLOCATION_LOCK_FIELD + ".at": {"$lt": stale}}]},
        {"$set": {ALLOCATION_LOCK_FIELD: {"token": token, "at": now.isoformat()}}})
    if won.modified_count != 1:
        raise HTTPException(status_code=409, detail={
            "error_code": "ALLOCATION_BUSY",
            "message": "Разпределението на този snapshot се изпълнява от друга заявка — опитайте отново"})
    try:
        yield
    finally:
        await snapshots.update_one({"id": snapshot_id, ALLOCATION_LOCK_FIELD + ".token": token},
                                   {"$unset": {ALLOCATION_LOCK_FIELD: ""}})
