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
ALLOCATION_VERSION_INDEX = "oh01_allocation_version_key_unique"


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


def allocation_version_key(org_id: str, snapshot_id: str, version: int, project_id: str) -> str:
    """OH01-1: the identity of one allocation row of one version — unique per (org,
    snapshot, version, project). Legacy rows have no key and are not indexed."""
    return "%s|%s|%s|%s" % (org_id, snapshot_id, version, project_id)


async def ensure_allocation_indexes(db) -> None:
    """OH01-1: unique ``version_key`` on allocation rows — a SPARSE single-field index, so
    legacy rows (no key) are not indexed. Idempotent."""
    await db[ALLOCATIONS_COLLECTION].create_index(
        [("version_key", 1)], name=ALLOCATION_VERSION_INDEX, unique=True, sparse=True)


#: FG-86: one ACTIVE overhead snapshot per period — the active one carries this key,
#: a superseded one does not (unique partial index; legacy snapshots are matched by period).
SNAPSHOT_PERIOD_INDEX = "oh01_one_active_snapshot_per_period"
PERIOD_LOCKS_COLLECTION = "overhead_period_locks"


def period_key(period_start: str, period_end: str) -> str:
    return "%s..%s" % (period_start, period_end)


async def ensure_snapshot_indexes(db) -> None:
    """FG-86: unique ``active_period_key`` (it carries the org) for active snapshots — a
    SPARSE single-field index, so superseded, legacy and full_cost.py snapshots (no such
    field) are not indexed. Idempotent."""
    await db["overhead_snapshots"].create_index(
        [("active_period_key", 1)], name=SNAPSHOT_PERIOD_INDEX, unique=True, sparse=True)


async def ensure_overhead_indexes(db) -> None:
    """OH01-3: the OH-01 unique indexes, created at STARTUP (server.py) and at tenant
    onboarding (``onboarding.onboard_tenant``) — never on a request path. Idempotent."""
    await ensure_allocation_indexes(db)
    await ensure_snapshot_indexes(db)
    # the lock rows' collection exists from startup too: a request never creates a
    # collection (no implicit "create" command on a request path)
    await db[PERIOD_LOCKS_COLLECTION].create_index([("org_id", 1), ("name", 1)],
                                                   name="oh01_period_lock_org_name")


async def ensure_overhead_indexes_for_installation(op_db, system_db) -> list:
    """FG-98: application startup — the operational database AND every database the
    Tenant Registry names get the OH-01 indexes (the enumeration of PR #72's
    ``tenant_database_names``). A registry that cannot be read fails the start: startup
    must not pretend it covered databases it could not list."""
    names = [op_db.name]
    records = await system_db["tenant_registry"].find(
        {}, {"_id": 0, "id": 1, "database_name": 1}).to_list(None)
    for r in records:
        name = r.get("database_name")
        if name and name not in names:
            names.append(name)
    for name in names:
        await ensure_overhead_indexes(op_db if name == op_db.name else op_db.client[name])
    return names


#: D6: the org-wide lock name for computing ANY snapshot (overlap checks need it).
COMPUTE_LOCK = "compute"


def period_lock(tenant, period_start: str, period_end: str):
    """The lock of ONE period (compute and allocate of that period)."""
    return overhead_lock(tenant, period_key(period_start, period_end))


@asynccontextmanager
async def overhead_lock(tenant, name: str):
    """OH01-1 / FG-86: ONE writer per overhead period at a time — computing a snapshot and
    allocating any snapshot of that period are serialized. One atomic conditional upsert on
    ``_id`` (unique by definition) of the tenant's ``overhead_period_locks`` row: a held
    lock -> 409 ``ALLOCATION_BUSY``, nothing written; a lock older than
    ALLOCATION_LOCK_STALE_SECONDS (crashed holder) can be taken over (the pattern of PR #70
    ``_row_lock``). Always released by its own token."""
    locks = tenant.collection(PERIOD_LOCKS_COLLECTION)
    lock_id = "%s|%s" % (tenant.org_id, name)
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(seconds=ALLOCATION_LOCK_STALE_SECONDS)).isoformat()
    busy = HTTPException(status_code=409, detail={
        "error_code": "ALLOCATION_BUSY",
        "message": "Режийните за този период се обработват от друга заявка — опитайте отново"})
    try:
        won = await locks.update_one(
            {"_id": lock_id, "$or": [{ALLOCATION_LOCK_FIELD: {"$exists": False}},
                                     {ALLOCATION_LOCK_FIELD + ".at": {"$lt": stale}}]},
            {"$set": {ALLOCATION_LOCK_FIELD: {"token": token, "at": now.isoformat()},
                      "name": name}},
            upsert=True)
    except Exception as exc:     # the row exists and is held: the upsert collided on _id
        if "duplicate" in str(exc).lower() or type(exc).__name__ == "DuplicateKeyError":
            raise busy
        raise
    if won.modified_count != 1 and won.upserted_id is None:
        raise busy
    try:
        yield
    finally:
        await locks.update_one({"_id": lock_id, ALLOCATION_LOCK_FIELD + ".token": token},
                               {"$unset": {ALLOCATION_LOCK_FIELD: ""}})
