"""
W0-03E-A2B — one-time backfill of the current ownerless legacy records to the
single operating tenant (BUILDING EXPRESS GROUP / BEG).

Owner decision (Issue #38; docs/architecture/W0-03E-A2B_SINGLE_TENANT_BACKFILL.md):
today there is exactly one operating company in BEG_Work, so every current
ownerless tenant-owned legacy record belongs to it. This module turns that
decision into a migration that can only ever do that one thing:

1. :func:`prove_precondition` — resolve the tenant ONLY from trusted
   server-side state (the W0-01 Tenant Registry in the system database and the
   source database's own ``organizations``), never from a hard-coded UUID or
   name, never from a request. It proves that the source database is the
   legacy primary installation, that exactly ONE eligible active operational
   tenant exists in the whole registry, that it is the only registry tenant of
   this database, and that the database holds no second operating
   organization. Any failure is a :class:`PreconditionFailed` with one exact
   code, raised before anything is written.
2. :func:`inventory` / :func:`dry_run` — every collection of the database plus
   every declared tenant-owned collection, classified by
   :mod:`app.tenancy.ownership`:
   ``collection | total | already tenant-bound | ownerless | conflicting |
   platform | migration action``. An unclassified collection holding documents,
   a conflicting owner anywhere, or an ownerless row in a canonical
   ``tenant_id`` store is a blocker. Read-only by construction.
3. :func:`execute` — re-proves the precondition, refuses a stale plan, requires
   a verified Approval (critical migration, CLAUDE.md §8; the default verifier
   is the not-started W0-07 runtime, so it refuses), takes a per-tenant lock,
   and stamps ``org_id`` on ownerless rows only — the predicate is evaluated by
   the server on every batch, so an owner set in the meantime is never
   overwritten. Every batch is journaled. Then it reconciles: zero ownerless,
   zero conflicting, and the journaled count must equal the planned count, or
   the run ends ``verification_failed`` (no silent partial success). A repeated
   request with the same idempotency key resumes an interrupted run or replays
   a completed one.
4. :func:`rollback` — the correction path: only the documents this run
   journaled, and only while they still carry the tenant this run stamped,
   return to exactly the ownerless form they had (missing / ``null`` / ``""``).
   Approval-gated like the forward run.
5. :func:`enforce_invariant` — after a verified zero-ownerless reconciliation,
   install a server-side ``$jsonSchema`` validator on every org-keyed
   collection so that the database itself rejects an ownerless insert or an
   update that removes the owner. The application already stamps the tenant
   server-side (static guard ``A2B-WRITER``); this is the backstop that does not
   depend on any code path. Journaled; removable by :func:`release_invariant`.

The rule is one-time and bounded: once a second operating tenant exists
(registered by :mod:`app.tenancy.onboarding`), :func:`prove_precondition` fails
with ``NOT_EXACTLY_ONE_OPERATIONAL_TENANT`` / ``SHARED_SOURCE_DATABASE`` and the
inference can never run again for any source.

No production migration is authorized. The CLI
(``scripts/w0_03e_a2b_beg_backfill.py``) refuses non-loopback servers and
non-disposable database names for every write.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.tenancy import ownership as own

MIGRATION_ID = "w0-03e-a2b-beg-backfill"
SCHEMA = "beg.w0-03e-a2b.legacy-backfill/v1"

#: System-database collections (W0-01 control plane, beside the registry).
REGISTRY = "tenant_registry"
RUNS = "tenant_migration_runs"
LOCKS = "tenant_migration_locks"
#: The same technical journal W0-02 uses, keyed by ``migration_id``.
JOURNAL = "migration_journal"

ACTION_EXECUTE = "tenant.legacy_backfill.execute"
ACTION_ROLLBACK = "tenant.legacy_backfill.rollback"
ACTION_ENFORCE = "tenant.ownership_invariant.enforce"
SOURCE_FLOW = "W0-03E-A2B"

STATUS_RUNNING = "running"
STATUS_INTERRUPTED = "interrupted"
STATUS_COMPLETED = "completed"
STATUS_VERIFICATION_FAILED = "verification_failed"
STATUS_ROLLED_BACK = "rolled_back"

ACTION_NONE = "NONE"
ACTION_BACKFILL = "BACKFILL_TO_RESOLVED_TENANT"
ACTION_BLOCKED_CONFLICT = "BLOCKED_CONFLICTING_OWNER"
ACTION_BLOCKED_CANONICAL = "BLOCKED_OWNERLESS_CANONICAL_STORE"
ACTION_BLOCKED_UNCLASSIFIED = "BLOCKED_UNCLASSIFIED_COLLECTION"
ACTION_BLOCKED_ROOT = "BLOCKED_SECOND_ORGANIZATION"

DEFAULT_BATCH = 500
MAX_BATCH = 5000
SAMPLE = 20

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://beg.work/w0-03e-a2b/legacy-backfill")

#: Operational tenant statuses (W0-01 ``registry.OPERATIONAL_STATUSES``; literal
#: here so the module imports without a database client).
OPERATIONAL_STATUSES = frozenset({"active", "grace", "restricted"})

#: Methods a read-only handle refuses before the server sees them.
_WRITE_METHODS = frozenset({
    "insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
    "delete_many", "find_one_and_update", "find_one_and_replace", "find_one_and_delete",
    "bulk_write", "create_index", "create_indexes", "drop", "drop_index", "drop_indexes",
    "rename", "aggregate",
})


# ===================================================================== errors
class BackfillRefused(RuntimeError):
    """The migration refused to act. ``code`` is machine-readable."""

    code = "REFUSED"

    def __init__(self, message: str, code: Optional[str] = None, **detail: Any):
        super().__init__(message)
        if code:
            self.code = code
        self.detail = detail


class PreconditionFailed(BackfillRefused):
    code = "PRECONDITION_FAILED"


class StalePlan(BackfillRefused):
    code = "STALE_PLAN"


class ApprovalRequired(BackfillRefused):
    code = "APPROVAL_REQUIRED"


class MigrationBusy(BackfillRefused):
    code = "MIGRATION_BUSY"


class VerificationFailed(BackfillRefused):
    code = "VERIFICATION_FAILED"


class _Interrupted(RuntimeError):
    """Test seam: a simulated crash between two batches."""


# ===================================================================== helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_id_for(tenant_id: str, idempotency_key: str) -> str:
    return str(uuid.uuid5(_NS, "%s\x1f%s" % (tenant_id, idempotency_key)))


def _lock_id(tenant_id: str) -> str:
    return "%s:%s" % (MIGRATION_ID, tenant_id)


def _is_duplicate_key(exc: BaseException) -> bool:
    return type(exc).__name__ == "DuplicateKeyError" or getattr(exc, "code", None) == 11000


def _batch(value: Any) -> int:
    size = DEFAULT_BATCH if value is None else value
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_BATCH:
        raise BackfillRefused("batch_size must be an integer 1..%d" % MAX_BATCH, "BAD_REQUEST")
    return size


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackfillRefused("%s is required" % name, "BAD_REQUEST")
    return value.strip()


class ReadOnlyDb:
    """A database handle that refuses every write before it reaches the server."""

    def __init__(self, db):
        self._db = db

    @property
    def name(self) -> str:
        return self._db.name

    def __getitem__(self, name: str) -> "_ReadOnlyColl":
        return _ReadOnlyColl(self._db[name], name)

    async def list_collection_names(self) -> List[str]:
        return await self._db.list_collection_names()


class _ReadOnlyColl:
    def __init__(self, coll, name: str):
        self._coll, self._name = coll, name

    def __getattr__(self, attr: str):
        if attr in _WRITE_METHODS:
            raise PermissionError("read-only dry run: %s.%s refused" % (self._name, attr))
        return getattr(self._coll, attr)


# ============================================================ 1. precondition
class ResolvedTenant:
    """The one tenant the current legacy source provably belongs to."""

    def __init__(self, record: Mapping[str, Any], source_database: str,
                 platform_owners: Iterable[str]):
        self.record = dict(record)
        self.tenant_id: str = record["id"]
        self.org_id: str = record.get("legacy_org_id") or record["id"]
        self.name: str = record.get("name") or ""
        self.source_database = source_database
        self.platform_owners = sorted(set(platform_owners))

    @property
    def tenant_ids(self) -> List[str]:
        return sorted({self.tenant_id, self.org_id})

    def as_dict(self) -> Dict[str, Any]:
        return {"tenant_id": self.tenant_id, "org_id": self.org_id, "name": self.name,
                "status": self.record.get("status"),
                "is_primary_installation": self.record.get("is_primary_installation"),
                "source_database": self.source_database,
                "platform_owners": self.platform_owners}


def _fail(code: str, message: str, **detail: Any) -> None:
    raise PreconditionFailed(message, code, **detail)


async def prove_precondition(op_db, system_db) -> ResolvedTenant:
    """Prove the one-time rule may apply to ``op_db``, and return its tenant.

    Reads only. Every check names the trusted state it uses; nothing comes
    from a caller. See the module docstring for the rule.
    """
    source = op_db.name
    registry = system_db[REGISTRY]
    tenants = await registry.find({}, {"_id": 0}).to_list(None)
    orgs = await op_db["organizations"].find({}, {"_id": 0}).to_list(None)

    platform_orgs = {o.get("id") for o in orgs
                     if o.get("slug") == own.PLATFORM_ORG_SLUG and o.get("id")}
    platform_owners = platform_orgs | {own.PLATFORM_SYSTEM_OWNER}

    def is_platform(t: Mapping[str, Any]) -> bool:
        return (t.get("id") in platform_orgs or t.get("legacy_org_id") in platform_orgs
                or t.get("slug") == own.PLATFORM_ORG_SLUG)

    claims = [t for t in tenants if t.get("database_name") == source]
    if not claims:
        _fail("NO_REGISTRY_RECORD",
              "no Tenant Registry record names database %r; its rows have no proven owner"
              % source)
    if len(claims) > 1:
        _fail("SHARED_SOURCE_DATABASE",
              "%d Tenant Registry records name database %r; the single-tenant rule cannot "
              "decide which of them wrote an ownerless row" % (len(claims), source),
              tenants=sorted(str(t.get("id")) for t in claims))
    claim = claims[0]
    if not claim.get("id"):
        _fail("REGISTRY_RECORD_INVALID", "the Tenant Registry record has no id")
    if is_platform(claim):
        _fail("PLATFORM_TENANT_NOT_ELIGIBLE",
              "database %r is claimed by the platform organization, not an operating tenant"
              % source)
    if claim.get("status") not in OPERATIONAL_STATUSES:
        _fail("TENANT_NOT_OPERATIONAL",
              "tenant %r is %r; only an active operational tenant can own the legacy data"
              % (claim["id"], claim.get("status")))
    if claim.get("is_primary_installation") is not True:
        _fail("NOT_THE_LEGACY_INSTALLATION",
              "tenant %r is not the primary (legacy) installation in the registry; the "
              "one-time rule applies to the current legacy dataset only, never to a tenant "
              "onboarded later" % claim["id"])

    eligible = [t for t in tenants
                if t.get("status") in OPERATIONAL_STATUSES and not is_platform(t)]
    if len(eligible) != 1 or eligible[0].get("id") != claim["id"]:
        _fail("NOT_EXACTLY_ONE_OPERATIONAL_TENANT",
              "the registry holds %d eligible active operational tenant(s); the owner rule "
              "'all current legacy data belongs to the one operating company' is only true "
              "while there is exactly one" % len(eligible),
              tenants=sorted(str(t.get("id")) for t in eligible))

    org_id = claim.get("legacy_org_id") or claim["id"]
    operating = [o for o in orgs if o.get("id") not in platform_orgs]
    if not any(o.get("id") == org_id for o in operating):
        _fail("REGISTRY_ORG_NOT_IN_SOURCE",
              "the registry maps database %r to organization %r, which that database does "
              "not contain; contradictory provenance" % (source, org_id))
    if len(operating) != 1:
        _fail("SECOND_ORGANIZATION_IN_SOURCE",
              "database %r holds %d operating organizations; it is not a single-tenant "
              "source" % (source, len(operating)),
              organizations=sorted(str(o.get("id")) for o in operating))
    return ResolvedTenant(claim, source, platform_owners)


# ============================================================ 2. inventory
def _row(collection: str, *, cls: str, key: Optional[str]) -> Dict[str, Any]:
    return {"collection": collection, "class": cls, "family": own.family_of(collection),
            "tenant_key": key, "total": 0, "bound": 0, "ownerless": 0, "conflicting": 0,
            "platform": 0, "action": ACTION_NONE, "conflict_sample": [],
            "ownerless_digest": None}


async def _scan(db, collection: str, resolved: ResolvedTenant) -> Dict[str, Any]:
    cls = own.classify_collection(collection)
    key = own.tenant_key_of(collection)
    row = _row(collection, cls=cls, key=key)
    coll = db[collection]
    if cls in (own.CLASS_ORG, own.CLASS_TENANT_ID):
        ownerless_ids: List[str] = []
        cursor = coll.find({}, {"_id": 1, own.ORG_KEY: 1, own.TENANT_ID_KEY: 1, "id": 1})
        async for doc in cursor:
            row["total"] += 1
            state = own.owner_state(doc, collection, tenant_ids=resolved.tenant_ids,
                                    platform_owners=resolved.platform_owners)
            if state == own.OWNER_BOUND:
                row["bound"] += 1
            elif state == own.OWNER_PLATFORM:
                row["platform"] += 1
            elif state == own.OWNER_OWNERLESS:
                row["ownerless"] += 1
                ownerless_ids.append(str(doc.get("_id")))
            else:
                row["conflicting"] += 1
                if len(row["conflict_sample"]) < SAMPLE:
                    row["conflict_sample"].append({
                        "_id": str(doc.get("_id")), "id": doc.get("id"),
                        own.ORG_KEY: doc.get(own.ORG_KEY),
                        own.TENANT_ID_KEY: doc.get(own.TENANT_ID_KEY)})
        row["ownerless_digest"] = _digest(sorted(ownerless_ids)) if ownerless_ids else None
        if row["conflicting"]:
            row["action"] = ACTION_BLOCKED_CONFLICT
        elif row["ownerless"]:
            row["action"] = ACTION_BACKFILL if cls == own.CLASS_ORG else ACTION_BLOCKED_CANONICAL
    elif cls == own.CLASS_ROOT:
        async for doc in coll.find({}, {"_id": 0, "id": 1, "slug": 1}):
            row["total"] += 1
            oid = doc.get("id")
            if oid == resolved.org_id:
                row["bound"] += 1
            elif oid in resolved.platform_owners:
                row["platform"] += 1
            else:
                row["conflicting"] += 1
                row["conflict_sample"].append({"id": oid, "slug": doc.get("slug")})
        if row["conflicting"]:
            row["action"] = ACTION_BLOCKED_ROOT
    else:
        row["total"] = await coll.count_documents({})
        if cls == own.CLASS_UNCLASSIFIED and row["total"]:
            row["action"] = ACTION_BLOCKED_UNCLASSIFIED
    return row


async def inventory(db, resolved: ResolvedTenant) -> List[Dict[str, Any]]:
    """One row per collection: every collection present plus every declared one."""
    present = [n for n in await db.list_collection_names() if not n.startswith("system.")]
    names = sorted(set(present) | set(own.ORG_KEYED) | {own.TENANT_ROOT})
    return [await _scan(db, name, resolved) for name in names]


def _totals(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    out = {"collections": 0, "total": 0, "bound": 0, "ownerless": 0, "conflicting": 0,
           "platform": 0, "authorization_ownerless": 0, "backfill_collections": 0,
           "blocked_collections": 0}
    for r in rows:
        out["collections"] += 1
        for k in ("total", "bound", "ownerless", "conflicting", "platform"):
            out[k] += r[k]
        if r["collection"] in own.AUTHORIZATION_COLLECTIONS:
            out["authorization_ownerless"] += r["ownerless"]
        if r["action"] == ACTION_BACKFILL:
            out["backfill_collections"] += 1
        elif r["action"] != ACTION_NONE:
            out["blocked_collections"] += 1
    return out


def plan_token_of(resolved: ResolvedTenant, rows: Iterable[Mapping[str, Any]]) -> str:
    """The exact version an Approval is about: tenant + every per-collection figure
    + the digest of the exact ownerless ``_id`` set."""
    return _digest({
        "migration": MIGRATION_ID, "tenant_id": resolved.tenant_id, "org_id": resolved.org_id,
        "source": resolved.source_database,
        "rows": [[r["collection"], r["total"], r["bound"], r["ownerless"], r["conflicting"],
                  r["platform"], r["action"], r["ownerless_digest"]] for r in rows],
    })


async def dry_run(op_db, system_db) -> Dict[str, Any]:
    """The whole read-only report. Writes nothing (read-only handles)."""
    ro, ro_sys = ReadOnlyDb(op_db), ReadOnlyDb(system_db)
    report: Dict[str, Any] = {"schema": SCHEMA, "migration_id": MIGRATION_ID,
                              "read_only": True, "executed": False,
                              "source_database": op_db.name}
    try:
        resolved = await prove_precondition(ro, ro_sys)
    except PreconditionFailed as exc:
        report.update({"precondition": {"proven": False, "code": exc.code, "message": str(exc),
                                        "detail": exc.detail},
                       "executable": False, "blockers": [exc.code], "rows": [],
                       "totals": None, "plan_token": None})
        return report
    rows = await inventory(ro, resolved)
    blockers = sorted({r["action"] for r in rows
                       if r["action"] not in (ACTION_NONE, ACTION_BACKFILL)})
    report.update({
        "precondition": {"proven": True, "code": "SINGLE_OPERATING_TENANT_PROVEN",
                         "tenant": resolved.as_dict()},
        "rows": rows,
        "totals": _totals(rows),
        "blockers": blockers,
        "executable": not blockers,
        "plan_token": plan_token_of(resolved, rows),
    })
    return report


# ============================================================ approval
class ApprovalEvidence:
    """Proof that a named approver approved THIS exact plan of THIS tenant."""

    def __init__(self, approval_id: str, tenant_id: str, subject: Mapping[str, Any],
                 approver_id: str, decided_at: str, verifier: str):
        self.approval_id, self.tenant_id = approval_id, tenant_id
        self.subject = dict(subject)
        self.approver_id, self.decided_at, self.verifier = approver_id, decided_at, verifier

    def as_record(self) -> Dict[str, Any]:
        return {"approval_id": self.approval_id, "approver_id": self.approver_id,
                "decided_at": self.decided_at, "verifier": self.verifier}


class ApprovalRuntimeUnavailable:
    """The default verifier: W0-07 is NOT STARTED, so nothing is approved."""

    name = "w0-07-not-started"

    async def verify(self, *, approval_id: str, subject: Mapping[str, Any]) -> ApprovalEvidence:
        raise ApprovalRequired(
            "approval %r cannot be verified: the W0-07 Approval runtime is NOT STARTED; a "
            "caller-supplied approval id is not proof of approval — failing closed" % approval_id)


DEFAULT_APPROVAL_VERIFIER = ApprovalRuntimeUnavailable()


async def _verify_approval(verifier: Any, approval_id: Optional[str], tenant_id: str,
                           subject: Mapping[str, Any]) -> ApprovalEvidence:
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise ApprovalRequired("a legacy ownership migration is a critical migration and "
                               "requires a trusted Approval (CLAUDE.md §8); none was given")
    try:
        evidence = await (verifier or DEFAULT_APPROVAL_VERIFIER).verify(
            approval_id=approval_id, subject=subject)
    except BackfillRefused:
        raise
    except Exception as exc:                                    # noqa: BLE001
        raise ApprovalRequired("approval %r could not be verified (%s)" % (approval_id, exc))
    if not isinstance(evidence, ApprovalEvidence):
        raise ApprovalRequired("the verifier returned no evidence")
    if evidence.approval_id != approval_id or evidence.tenant_id != tenant_id:
        raise ApprovalRequired("approval evidence names another approval or tenant")
    if evidence.subject != dict(subject):
        raise ApprovalRequired("approval %r was given for a different plan" % approval_id)
    if not evidence.approver_id or not evidence.decided_at:
        raise ApprovalRequired("approval evidence has no approver or decision time")
    return evidence


# ============================================================ audit
async def _audit(op_db, resolved: ResolvedTenant, *, action: str, actor_id: str, result: str,
                 run_id: str, idempotency_key: str, diff: Mapping[str, Any],
                 approval_id: Optional[str] = None, reason: Optional[str] = None,
                 error_code: Optional[str] = None) -> None:
    """One canonical W0-04 AuditEvent in the tenant's own chain."""
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=resolved.tenant_id, actor_type=ACTOR_HUMAN, actor_id=actor_id, action=action,
        source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS, result=result,
        entity_type="tenant_legacy_backfill", entity_id=run_id, scope_type="tenant",
        scope_id=resolved.tenant_id, structured_diff=dict(diff), reason=reason,
        approval_id=approval_id, correlation_id=run_id, idempotency_key=idempotency_key,
        error_code=error_code, tool_or_endpoint="scripts/w0_03e_a2b_beg_backfill.py")
    await record_event(op_db, event)


# ============================================================ lock
async def _take_lock(system_db, tenant_id: str, run_id: str, attempt: str) -> None:
    lid = _lock_id(tenant_id)
    locks = system_db[LOCKS]
    try:
        await locks.insert_one({"_id": lid, "tenant_id": tenant_id, "holder": run_id,
                                "attempt": attempt, "interrupted": False, "taken_at": _now()})
        return
    except Exception as exc:                                    # noqa: BLE001
        if not _is_duplicate_key(exc):
            raise
    current = await locks.find_one({"_id": lid}) or {}
    free = current.get("holder") is None
    own_interrupted = current.get("holder") == run_id and current.get("interrupted") is True
    if free or own_interrupted:
        res = await locks.update_one(
            {"_id": lid, "holder": current.get("holder"), "attempt": current.get("attempt")},
            {"$set": {"holder": run_id, "attempt": attempt, "interrupted": False,
                      "taken_at": _now()}})
        if res.matched_count == 1:
            return
    raise MigrationBusy("another ownership migration of tenant %r is in progress (%s)"
                        % (tenant_id, current.get("holder")))


async def _release_lock(system_db, tenant_id: str, run_id: str, attempt: str,
                        interrupted: bool = False) -> None:
    patch = ({"interrupted": True, "interrupted_at": _now()} if interrupted
             else {"holder": None, "attempt": None, "interrupted": False, "released_at": _now()})
    await system_db[LOCKS].update_one(
        {"_id": _lock_id(tenant_id), "holder": run_id, "attempt": attempt}, {"$set": patch})


# ============================================================ 3. execute
def _ownerless_form(doc: Mapping[str, Any]) -> str:
    """How exactly a document was ownerless — restored verbatim by rollback."""
    if own.ORG_KEY not in doc:
        return "missing"
    return "null" if doc[own.ORG_KEY] is None else "empty"


def _safe_other_key(resolved: ResolvedTenant) -> Dict[str, Any]:
    """The ``tenant_id`` side of a stamp: absent, or already this tenant."""
    return {"$or": [{own.TENANT_ID_KEY: {"$exists": False}}, {own.TENANT_ID_KEY: None},
                    {own.TENANT_ID_KEY: ""}, {own.TENANT_ID_KEY: {"$in": resolved.tenant_ids}}]}


async def _stamp_collection(op_db, system_db, resolved: ResolvedTenant, *, collection: str,
                            run_id: str, size: int, fail_after: Optional[str]) -> int:
    """Stamp every still-ownerless row of one collection. Returns rows modified."""
    coll = op_db[collection]
    pred = {"$and": [own.ownerless_predicate(own.ORG_KEY), _safe_other_key(resolved)]}
    docs = await coll.find(pred, {"_id": 1, own.ORG_KEY: 1}).sort("_id", 1).to_list(None)
    modified = 0
    for start in range(0, len(docs), size):
        chunk = docs[start:start + size]
        by_form: Dict[str, List[Any]] = {}
        for d in chunk:
            by_form.setdefault(_ownerless_form(d), []).append(d["_id"])
        for form, ids in sorted(by_form.items()):
            # The server re-evaluates "still ownerless" on every document: a row
            # that gained an owner since the read is not matched, so it can
            # never be overwritten. ``modified`` counts what really changed.
            res = await coll.update_many({"$and": [{"_id": {"$in": ids}}, pred]},
                                         {"$set": {own.ORG_KEY: resolved.org_id}})
            await system_db[JOURNAL].insert_one({
                "migration_id": MIGRATION_ID, "run_id": run_id, "kind": "stamped",
                "tenant_id": resolved.tenant_id, "org_id": resolved.org_id,
                "collection": collection, "ownerless_form": form, "ids": ids,
                "matched": res.matched_count, "modified": res.modified_count,
                "applied_at": _now(), "reverted_at": None})
            modified += res.modified_count
        if fail_after == "batch:%s" % collection:
            raise _Interrupted(collection)
    return modified


async def _journaled(system_db, run_id: str) -> int:
    rows = await system_db[JOURNAL].find(
        {"migration_id": MIGRATION_ID, "run_id": run_id, "kind": "stamped",
         "reverted_at": None}, {"modified": 1}).to_list(None)
    return sum(r.get("modified", 0) for r in rows)


async def reconcile(op_db, resolved: ResolvedTenant, plan_rows: List[Mapping[str, Any]],
                    journaled: int) -> Dict[str, Any]:
    """Post-run proof: re-inventory and compare against the frozen plan."""
    after = await inventory(op_db, resolved)
    by_name = {r["collection"]: r for r in after}
    problems: List[str] = []
    planned = 0
    for p in plan_rows:
        if p["action"] != ACTION_BACKFILL:
            continue
        planned += p["ownerless"]
        a = by_name.get(p["collection"]) or _row(p["collection"], cls=p["class"],
                                                  key=p["tenant_key"])
        if a["bound"] < p["bound"] + p["ownerless"]:
            problems.append("%s: bound %d < planned %d + %d" % (
                p["collection"], a["bound"], p["bound"], p["ownerless"]))
    totals = _totals(after)
    if totals["ownerless"]:
        problems.append("ownerless rows remain: %d" % totals["ownerless"])
    if totals["conflicting"]:
        problems.append("conflicting rows: %d" % totals["conflicting"])
    if totals["authorization_ownerless"]:
        problems.append("ownerless authorization rows: %d" % totals["authorization_ownerless"])
    if journaled != planned:
        problems.append("journaled %d row(s) but the plan backfills %d" % (journaled, planned))
    return {"ok": not problems, "problems": problems, "planned": planned,
            "journaled": journaled, "totals_after": totals, "rows_after": after}


def _run_view(run: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in run.items() if k not in ("_id", "plan_rows")}


async def execute(op_db, system_db, *, plan_token: str, idempotency_key: str, actor_id: str,
                  approval_id: Optional[str] = None, approval_verifier: Any = None,
                  batch_size: Optional[int] = None,
                  _fail_after: Optional[str] = None) -> Dict[str, Any]:
    """Apply exactly the approved dry-run plan. See the module docstring."""
    token = _text(plan_token, "plan_token (execution without a dry run is refused)")
    key = _text(idempotency_key, "idempotency_key")
    actor = _text(actor_id, "actor_id")
    size = _batch(batch_size)
    resolved = await prove_precondition(op_db, system_db)
    run_id = run_id_for(resolved.tenant_id, key)
    runs = system_db[RUNS]
    run = await runs.find_one({"_id": run_id})
    if run and run.get("status") == STATUS_COMPLETED:
        return {"run_id": run_id, "status": STATUS_COMPLETED, "replayed": True,
                "run": _run_view(run)}
    if run and run.get("status") == STATUS_ROLLED_BACK:
        raise BackfillRefused("run %s was rolled back; plan again under a new key" % run_id,
                              "ROLLED_BACK")
    if run is None:
        report = await dry_run(op_db, system_db)
        if report["blockers"]:
            raise BackfillRefused("the dry run has blockers: %s" % ", ".join(report["blockers"]),
                                  "BLOCKED", blockers=report["blockers"])
        if report["plan_token"] != token:
            raise StalePlan("the data changed since the dry run (plan token mismatch); "
                            "run the dry run again")
        plan_rows = report["rows"]
    else:
        if run.get("plan_token") != token:
            raise StalePlan("run %s was started for another plan" % run_id)
        plan_rows = run["plan_rows"]
    subject = {"action": ACTION_EXECUTE, "tenant_id": resolved.tenant_id,
               "source_database": resolved.source_database, "plan_token": token}
    evidence = await _verify_approval(approval_verifier, approval_id, resolved.tenant_id, subject)

    attempt = uuid.uuid4().hex
    await _take_lock(system_db, resolved.tenant_id, run_id, attempt)
    try:
        if run is None:
            run = {"_id": run_id, "run_id": run_id, "migration_id": MIGRATION_ID,
                   "tenant_id": resolved.tenant_id, "org_id": resolved.org_id,
                   "source_database": resolved.source_database, "plan_token": token,
                   "idempotency_key": key, "actor_id": actor, "approval": evidence.as_record(),
                   "plan_rows": plan_rows, "plan_totals": _totals(plan_rows),
                   "status": STATUS_RUNNING, "attempts": 1, "started_at": _now()}
            await runs.insert_one(dict(run))
            await _audit(op_db, resolved, action=ACTION_EXECUTE, actor_id=actor,
                         result="success", run_id=run_id, idempotency_key=key,
                         approval_id=approval_id, reason="started",
                         diff={"phase": "started", "plan_token": token,
                               "planned": _totals(plan_rows)})
        else:
            await runs.update_one({"_id": run_id}, {"$set": {"status": STATUS_RUNNING,
                                                              "resumed_at": _now()},
                                                     "$inc": {"attempts": 1}})
        for row in plan_rows:
            if row["action"] == ACTION_BACKFILL:
                await _stamp_collection(op_db, system_db, resolved, collection=row["collection"],
                                        run_id=run_id, size=size, fail_after=_fail_after)
        result = await reconcile(op_db, resolved, plan_rows, await _journaled(system_db, run_id))
    except BaseException:
        await runs.update_one({"_id": run_id}, {"$set": {"status": STATUS_INTERRUPTED,
                                                          "interrupted_at": _now()}})
        await _release_lock(system_db, resolved.tenant_id, run_id, attempt, interrupted=True)
        raise
    status = STATUS_COMPLETED if result["ok"] else STATUS_VERIFICATION_FAILED
    await runs.update_one({"_id": run_id}, {"$set": {
        "status": status, "finished_at": _now(), "reconciliation": {
            k: v for k, v in result.items() if k != "rows_after"}}})
    await _audit(op_db, resolved, action=ACTION_EXECUTE, actor_id=actor,
                 result="success" if result["ok"] else "failure", run_id=run_id,
                 idempotency_key=key, approval_id=approval_id, reason=status,
                 error_code=None if result["ok"] else "VERIFICATION_FAILED",
                 diff={"phase": status, "planned": result["planned"],
                       "journaled": result["journaled"], "after": result["totals_after"],
                       "problems": result["problems"]})
    await _release_lock(system_db, resolved.tenant_id, run_id, attempt)
    if not result["ok"]:
        raise VerificationFailed("post-run reconciliation failed: %s"
                                 % "; ".join(result["problems"]), problems=result["problems"])
    return {"run_id": run_id, "status": status, "replayed": False,
            "reconciliation": result}


# ============================================================ 4. rollback
async def rollback(op_db, system_db, *, run_id: str, idempotency_key: str, actor_id: str,
                   approval_id: Optional[str] = None,
                   approval_verifier: Any = None) -> Dict[str, Any]:
    """Return the run's journaled rows to exactly their prior ownerless form.

    Only rows that still carry the tenant this run stamped are touched; a row
    whose owner changed since is reported, never forced. Never deletes a row.
    """
    rid = _text(run_id, "run_id")
    key = _text(idempotency_key, "idempotency_key")
    actor = _text(actor_id, "actor_id")
    run = await system_db[RUNS].find_one({"_id": rid})
    if not run:
        raise BackfillRefused("unknown run %s" % rid, "NOT_FOUND")
    if run.get("status") == STATUS_ROLLED_BACK:
        return {"run_id": rid, "status": STATUS_ROLLED_BACK, "replayed": True}
    resolved = ResolvedTenant({"id": run["tenant_id"], "legacy_org_id": run["org_id"]},
                            run["source_database"], ())
    if op_db.name != run["source_database"]:
        raise BackfillRefused("run %s belongs to database %r" % (rid, run["source_database"]),
                              "WRONG_DATABASE")
    subject = {"action": ACTION_ROLLBACK, "tenant_id": resolved.tenant_id,
               "source_database": resolved.source_database, "run_id": rid}
    await _verify_approval(approval_verifier, approval_id, resolved.tenant_id, subject)
    attempt = uuid.uuid4().hex
    await _take_lock(system_db, resolved.tenant_id, rid, attempt)
    restored, skipped = 0, 0
    try:
        entries = await system_db[JOURNAL].find(
            {"migration_id": MIGRATION_ID, "run_id": rid, "kind": "stamped",
             "reverted_at": None}).to_list(None)
        for e in entries:
            coll = op_db[e["collection"]]
            flt = {"_id": {"$in": e["ids"]}, own.ORG_KEY: resolved.org_id}
            update = ({"$unset": {own.ORG_KEY: ""}} if e["ownerless_form"] == "missing"
                      else {"$set": {own.ORG_KEY: None if e["ownerless_form"] == "null" else ""}})
            res = await coll.update_many(flt, update)
            restored += res.modified_count
            skipped += len(e["ids"]) - res.matched_count
            await system_db[JOURNAL].update_one({"_id": e["_id"]},
                                                {"$set": {"reverted_at": _now(),
                                                          "reverted_count": res.modified_count}})
        await system_db[RUNS].update_one({"_id": rid}, {"$set": {
            "status": STATUS_ROLLED_BACK, "rolled_back_at": _now(),
            "rollback": {"restored": restored, "skipped_owner_changed": skipped,
                         "idempotency_key": key, "actor_id": actor}}})
        await _audit(op_db, resolved, action=ACTION_ROLLBACK, actor_id=actor, result="success",
                     run_id=rid, idempotency_key=key, approval_id=approval_id,
                     reason="rolled_back",
                     diff={"restored": restored, "skipped_owner_changed": skipped})
    finally:
        await _release_lock(system_db, resolved.tenant_id, rid, attempt)
    return {"run_id": rid, "status": STATUS_ROLLED_BACK, "replayed": False,
            "restored": restored, "skipped_owner_changed": skipped}


# ============================================================ 6. ownership verification
async def verify_ownership(op_db, system_db) -> Dict[str, Any]:
    """Zero-ownerless proof that does NOT depend on the one-tenant precondition.

    After a second tenant is onboarded the backfill precondition fails by
    design, but the invariant "every tenant-owned row has a known owner" must
    still hold. Allowed owners are the Tenant Registry tenants of THIS database
    (and the platform principal where :data:`ownership.PLATFORM_ROWS_ALLOWED`).
    Read-only. ``ok`` is true only with zero ownerless and zero unknown-owner
    rows in every org-keyed and tenant_id-keyed collection, and no unclassified
    collection holding documents.
    """
    ro, ro_sys = ReadOnlyDb(op_db), ReadOnlyDb(system_db)
    claims = await ro_sys[REGISTRY].find({"database_name": op_db.name}, {"_id": 0}).to_list(None)
    owners = sorted({v for t in claims for v in (t.get("id"), t.get("legacy_org_id"))
                     if isinstance(v, str) and v})
    orgs = await ro["organizations"].find({}, {"_id": 0, "id": 1, "slug": 1}).to_list(None)
    platform = sorted({o["id"] for o in orgs if o.get("slug") == own.PLATFORM_ORG_SLUG
                       and o.get("id")} | {own.PLATFORM_SYSTEM_OWNER})
    rows, per_tenant = [], {o: 0 for o in owners}
    present = [n for n in await ro.list_collection_names() if not n.startswith("system.")]
    for name in sorted(set(present) | set(own.ORG_KEYED)):
        cls = own.classify_collection(name)
        key = own.tenant_key_of(name)
        r = {"collection": name, "class": cls, "total": 0, "ownerless": 0, "unknown_owner": 0,
             "platform": 0, "by_tenant": {}}
        if key is None:
            r["total"] = await ro[name].count_documents({})
            rows.append(r)
            continue
        async for doc in ro[name].find({}, {"_id": 1, key: 1}):
            r["total"] += 1
            v = doc.get(key)
            if own.is_missing_owner(v):
                r["ownerless"] += 1
            elif v in owners:
                r["by_tenant"][v] = r["by_tenant"].get(v, 0) + 1
                per_tenant[v] += 1
            elif v in platform and name in own.PLATFORM_ROWS_ALLOWED:
                r["platform"] += 1
            else:
                r["unknown_owner"] += 1
        rows.append(r)
    ownerless = sum(r["ownerless"] for r in rows)
    unknown = sum(r["unknown_owner"] for r in rows)
    unclassified = [r["collection"] for r in rows
                    if r["class"] == own.CLASS_UNCLASSIFIED and r["total"]]
    authz = sum(r["ownerless"] for r in rows if r["collection"] in own.AUTHORIZATION_COLLECTIONS)
    return {"ok": not (ownerless or unknown or unclassified), "source_database": op_db.name,
            "registry_tenants": owners, "ownerless": ownerless, "unknown_owner": unknown,
            "authorization_ownerless": authz, "unclassified": unclassified,
            "rows_per_tenant": per_tenant, "rows": rows}


# ============================================================ 5. invariant
def ownership_validator() -> Dict[str, Any]:
    """The server-side rule: ``org_id`` is a non-empty string, always."""
    return {"$jsonSchema": {"bsonType": "object", "required": [own.ORG_KEY],
                            "properties": {own.ORG_KEY: {"bsonType": "string",
                                                          "minLength": 1}}}}


async def enforce_invariant(op_db, system_db, *, actor_id: str) -> Dict[str, Any]:
    """Make the database refuse ownerless rows in every org-keyed collection.

    Refused unless the precondition still holds AND the current inventory has
    zero ownerless and zero conflicting rows — the invariant is installed on a
    proven-clean database only. A collection that already has a validator is
    not overwritten (reported as a blocker). Real MongoDB only.
    """
    actor = _text(actor_id, "actor_id")
    resolved = await prove_precondition(op_db, system_db)
    rows = await inventory(op_db, resolved)
    totals = _totals(rows)
    if totals["ownerless"] or totals["conflicting"]:
        raise BackfillRefused("the invariant is installed only on a database with zero "
                              "ownerless and zero conflicting rows (%d / %d)"
                              % (totals["ownerless"], totals["conflicting"]), "NOT_CLEAN")
    existing = {}
    async for info in await _list_collections(op_db):
        existing[info["name"]] = (info.get("options") or {}).get("validator")
    foreign = sorted(n for n in own.ORG_KEYED if existing.get(n))
    if foreign:
        raise BackfillRefused("collections already carry a validator: %s" % ", ".join(foreign),
                              "VALIDATOR_EXISTS")
    installed = []
    for name in sorted(own.ORG_KEYED):
        if name in existing:
            await op_db.command("collMod", name, validator=ownership_validator(),
                                validationLevel="strict", validationAction="error")
        else:
            await op_db.create_collection(name, validator=ownership_validator(),
                                          validationLevel="strict", validationAction="error")
        installed.append({"collection": name, "created": name not in existing})
    await system_db[JOURNAL].insert_one({
        "migration_id": MIGRATION_ID, "kind": "invariant", "tenant_id": resolved.tenant_id,
        "source_database": op_db.name, "collections": installed, "applied_at": _now(),
        "reverted_at": None})
    await _audit(op_db, resolved, action=ACTION_ENFORCE, actor_id=actor, result="success",
                 run_id="invariant:" + op_db.name, idempotency_key="invariant:" + op_db.name,
                 reason="installed", diff={"collections": len(installed)})
    return {"installed": installed}


async def _list_collections(db):
    return await db.list_collections()


async def release_invariant(op_db, system_db) -> Dict[str, Any]:
    """Rollback of :func:`enforce_invariant`: remove the validators it installed."""
    entries = await system_db[JOURNAL].find(
        {"migration_id": MIGRATION_ID, "kind": "invariant", "source_database": op_db.name,
         "reverted_at": None}).to_list(None)
    removed = 0
    for e in entries:
        for c in e["collections"]:
            await op_db.command("collMod", c["collection"], validator={},
                                validationLevel="off")
            removed += 1
        await system_db[JOURNAL].update_one({"_id": e["_id"]},
                                            {"$set": {"reverted_at": _now()}})
    return {"removed": removed}
