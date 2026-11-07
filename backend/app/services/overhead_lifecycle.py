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


#: R38 (Krum 07.11.2026): the label of an overhead figure whose period is being recomputed.
RECALCULATING_LABEL = "преизчислява се"


def recalculating_fields(recalculating: bool) -> Dict[str, Any]:
    """FG-116: the SAME two fields on every overhead reader (as project_pnl)."""
    return {"overhead_recalculating": bool(recalculating),
            "overhead_label": RECALCULATING_LABEL if recalculating else None}


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


# ---------------------------------------------------------------------------
# OH74-04: an operation's audit is written ONCE, whatever step bookkeeping says.
# RecoverableWrite.step runs the callback BEFORE it records the step as done; a crash in
# between re-runs the callback on the same-key retry. Only one attempt of a key runs at a
# time (a concurrent one gets IDEMPOTENCY_IN_PROGRESS), so "is there already an event of
# THIS operation?" before the write is the dedup (the rule of PAY-01 ``_audit_once``).
# ---------------------------------------------------------------------------

async def audit_overhead_event_once(db, user: Dict[str, Any], *, action: str,
                                    entity_id: str, idempotency_key: str, **kw) -> None:
    from app.audit.store import AUDIT_COLLECTION
    # ``is not None``: a projected event may legitimately come back as ``{}``
    if await db[AUDIT_COLLECTION].find_one(
            {"tenant_id": user["org_id"], "action": action, "entity_id": entity_id,
             "idempotency_key": idempotency_key, "result": "success"},
            {"_id": 1}) is not None:
        return
    await audit_overhead_event(db, user, action=action, entity_id=entity_id,
                               idempotency_key=idempotency_key, **kw)


async def legacy_audit_once(db, user: Dict[str, Any], action: str, entity_type: str,
                            entity_id: str, changes: Dict[str, Any], operation_key: str) -> None:
    """The legacy ``audit_logs`` row of one operation, once (it carries the operation key)."""
    from app.utils.audit import log_audit
    if await db["audit_logs"].find_one(
            {"org_id": user["org_id"], "action": action, "entity_id": entity_id,
             "changes.operation_key": operation_key}, {"_id": 1}) is not None:
        return
    await log_audit(user["org_id"], user["id"], user["email"], action, entity_type, entity_id,
                    {**changes, "operation_key": operation_key})


# ---------------------------------------------------------------------------
# OH74-03: ONE authoritative "current allocation" pointer per period. A new batch is
# inserted STAGED (not current), then published by a single atomic write of the pointer;
# every reader follows the pointer. Until that write the previous batch stays current
# (and, R38, labelled) — there is no moment with 0 or with both.
# ---------------------------------------------------------------------------

def _pointer_id(org_id: str, pkey: str) -> str:
    return "%s|%s" % (org_id, pkey)


async def publish_allocation_batch(tenant, period_start: str, period_end: str,
                                   batch_id: str, version: int) -> None:
    """The single publish write: the period's pointer now names ``batch_id``. It lives on
    the period's lock row (``overhead_period_locks``, written under that lock)."""
    pkey = period_key(period_start, period_end)
    await tenant.collection(PERIOD_LOCKS_COLLECTION).update_one(
        {"_id": _pointer_id(tenant.org_id, pkey)},
        {"$set": {"name": pkey, "current_allocation_batch_id": batch_id,
                  "current_allocation_version": version,
                  "published_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True)


async def _read_current_pointers(tenant) -> Dict[str, str]:
    """{period_key: current batch id} of every published period of the tenant. Read FIRST
    (OH74-05); a separate function so a test can pause a reader right after it."""
    ptrs = await tenant.collection(PERIOD_LOCKS_COLLECTION).find(
        {"current_allocation_batch_id": {"$exists": True}},
        {"_id": 0, "name": 1, "current_allocation_batch_id": 1}).to_list(None)
    return {p["name"]: p["current_allocation_batch_id"] for p in ptrs if p.get("name")}


async def current_allocations(tenant, flt: Dict[str, Any],
                              projection: Optional[Dict[str, Any]] = None) -> list:
    """OH74-03/05: the CURRENT allocation rows matching ``flt`` — the one rule every reader
    (project P&L, financial results, snapshot detail, /overhead/allocations, full_cost,
    profit views) follows.

    Read order is the consistency guarantee (OH74-05): the publish POINTERS are read first,
    the rows after. A batch's rows are inserted (staged) BEFORE its pointer is written and
    are never deleted, so whatever pointer this reader saw, that batch's rows are there when
    the rows are read — the reader sees the old version or the new one, never neither
    (0) and never both.

    A row is current when its period has a pointer (as read above) and the row is in that
    batch; for a period without a pointer (legacy data), a row without a batch id. A staged
    row (batch id, not published in the pointers read) is never current."""
    current = await _read_current_pointers(tenant)
    proj = None
    if projection is not None:
        proj = {**projection, "_id": 0, "overhead_snapshot_id": 1, "allocation_batch_id": 1}
    rows = await tenant.project_overhead_allocations.find(flt, proj or {"_id": 0}).to_list(None)
    sids = sorted({r.get("overhead_snapshot_id") for r in rows if r.get("overhead_snapshot_id")})
    snaps = await tenant.overhead_snapshots.find(
        {"id": {"$in": sids}}, {"_id": 0, "id": 1, "period_start": 1, "period_end": 1}
    ).to_list(None) if sids else []
    pkey_of = {s["id"]: period_key(s["period_start"], s["period_end"])
               for s in snaps if s.get("period_start") and s.get("period_end")}
    period_of = {s["id"]: (s.get("period_start"), s.get("period_end")) for s in snaps}
    out = []
    for r in rows:
        pk = pkey_of.get(r.get("overhead_snapshot_id"))
        if pk in current:
            keep = r.get("allocation_batch_id") == current[pk]
        else:
            # no pointer in THIS reader's view: only pre-OH-01 rows (no batch id). Not
            # ``superseded_by`` — the history step may set it concurrently (OH74-05).
            keep = not r.get("allocation_batch_id")
        if keep:
            row = r if projection is None else \
                {k: v for k, v in r.items() if k in projection or k == "recalculating"}
            # FG-89: readers that group by month get the period of the row's snapshot
            ps, pe = period_of.get(r.get("overhead_snapshot_id"), (None, None))
            out.append({**row, "period_start": ps, "period_end": pe})
    return out


async def project_overhead_current(tenant, project_id: str) -> Dict[str, Any]:
    """FG-89: THE project overhead — the sum of its current (published) allocations. The
    one figure P&L, net profit, alerts, risk and revenue/profit views read."""
    rows = await current_allocations(tenant, {"org_id": tenant.org_id, "project_id": project_id})
    return {"amount": round(sum(r.get("allocated_amount", 0) for r in rows), 2),
            "rows": rows, "recalculating": any(r.get("recalculating") for r in rows)}
