"""
W0-03E — legacy migration runner: execute, resume, verify, reconcile, roll back,
and the human decision on a pending legacy mapping.

**What a run writes, and only this:**

  * new official Master records (``md_<type>``), each anchored on one legacy
    document and carrying ``legacy_refs[{collection, legacy_id, org_id, run_id}]``;
  * one more ``legacy_refs`` entry on a Master record, when the plan attaches a
    legacy document by an authoritative identity;
  * one reverse-reference row per legacy document in ``md_legacy_refs`` — status
    ``mapped`` / ``pending`` / ``blocked`` — so every old id is accounted for and
    resolves deterministically, **including** the ones a person still has to map;
  * bookkeeping: the run (``md_migration_runs``), a per-tenant lock
    (``md_migration_locks``), the tenant's migration state
    (``md_migration_state``), the W0-04 idempotency registry and canonical
    AuditEvents.

**Never:** a legacy collection (the legacy routes keep working on the same data —
that is the staged migration and the first line of rollback), a hard delete, a
merge, an alias, a pending-mapping decision taken by the machine.

**Approval — fail closed.** CLAUDE.md §8 lists "критична миграция/rollback" as a
mandatory Approval case, and no canonical rule says which migrations are not
critical, so every execute, rollback and mapping decision needs trusted Approval
evidence from an ``ApprovalVerifier`` (the W0-03D seam). W0-07 is NOT STARTED:
the build's only verifier refuses everything, so **no migration write can run in
this build**. The dry run, the reconciliation report, the old-id resolution and
the refusal paths are what is live.

**Recoverable, not atomic.** There is no transaction across Master records,
reverse-reference rows, the run and the audit chain, so a run is a sequence of
idempotent steps under a per-tenant lock, checkpointed after every batch:

    idempotency key reserved -> lock taken -> run document (frozen plan)
    -> per batch: every item re-checked against its source fingerprint, Master
       written by a deterministic id, reverse-reference row written, one batch
       AuditEvent, checkpoint moved
    -> every planned item verified -> reconciliation evidence
    -> completion AuditEvent -> idempotency completed -> lock released

A failure records the interruption (run ``interrupted``, key ``failed``, lock kept
for the SAME run). Repeating the SAME request resumes after the checkpoint and
re-applies the interrupted batch idempotently. A run is never reported
successful before verification and its AuditEvent: no silent partial success.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.master_data import legacy_plan as lp
from app.master_data import legacy_sources as ls
from app.master_data import models
from app.master_data.deps import (
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataTenantContextMissing,
    require_tenant_context,
    resolve_mode,
)
from app.master_data.merge import (
    MasterDataApprovalRequired,
    _verify_approval,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.service import (
    SOURCE_FLOW,
    MasterDataAuditFailed,
    MasterDataRefused,
    _reject_tenant_override,
    _require_actor,
)

RUNS_COLLECTION = "md_migration_runs"
LOCK_COLLECTION = "md_migration_locks"
STATE_COLLECTION = "md_migration_state"

ACTION_EXECUTE = "master_data.legacy_migration.execute"
ACTION_ROLLBACK = "master_data.legacy_migration.rollback"
ACTION_RESOLVE = "master_data.legacy_mapping.resolve"

#: Provenance of a Master record this runner creates.
SOURCE_LEGACY_MIGRATION = "legacy_migration"

RUN_RUNNING = "running"
RUN_INTERRUPTED = "interrupted"
RUN_VERIFICATION_FAILED = "verification_failed"
RUN_COMPLETED = "completed"
RUN_ROLLED_BACK = "rolled_back"

DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 500
MAX_REASON = 500
SAMPLE = 20

DECIDE_MAP = "map"
DECIDE_CREATE = "create_new"
DECIDE_DECLINE = "decline"

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://beg.work/master-data/legacy-migration")


# ---------------------------------------------------------------- exceptions
class MigrationStalePlan(MasterDataRefused):
    """The legacy data, a Master record or a reverse reference changed since the dry run."""


class MigrationBusy(MasterDataRefused):
    """Another migration, rollback or mapping decision of this tenant holds the lock."""


class MigrationConflict(MasterDataRefused):
    """A write found state it did not expect; the run stops rather than guess."""


class MigrationVerificationFailed(MasterDataRefused):
    """The run wrote its batches, but the result does not match the plan."""


class _Interrupted(RuntimeError):
    """Raised by ``_fail_after`` to model a crash between two steps (tests only)."""


def _maybe_fail(fail_after: Optional[str], step: str) -> None:
    if fail_after == step:
        raise _Interrupted("simulated interruption after %s" % step)


# ------------------------------------------------------------------ helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_for(tenant_id: str, idempotency_key: str) -> str:
    return str(uuid.uuid5(_NS, "%s:run:%s" % (tenant_id, idempotency_key)))


def master_id_for(tenant_id: str, run_id: str, collection: str, legacy_id: str) -> str:
    """The id of the Master record a run anchors on one legacy document —
    the same on every retry of that run."""
    return str(uuid.uuid5(_NS, "%s:%s:%s:%s" % (tenant_id, run_id, collection, legacy_id)))


def _op_id(tenant_id: str, kind: str, idempotency_key: str) -> str:
    return str(uuid.uuid5(_NS, "%s:%s:%s" % (tenant_id, kind, idempotency_key)))


def _is_duplicate_key(exc: BaseException) -> bool:
    return (type(exc).__name__ == "DuplicateKeyError"
            or getattr(exc, "code", None) == 11000
            or "duplicate key" in str(exc).lower())


def _require_text(value: Any, name: str) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise MasterDataInvalid("%s is required" % name)
    return value.strip()


def _reason(reason: Optional[str], required: bool) -> Optional[str]:
    if reason is None or (isinstance(reason, str) and not reason.strip()):
        if required:
            raise MasterDataInvalid("a reason is required")
        return None
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        raise MasterDataInvalid("reason must be text of at most %d characters" % MAX_REASON)
    return reason.strip()


def _batch_size(value: Any) -> int:
    if value is None:
        return DEFAULT_BATCH_SIZE
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_BATCH_SIZE:
        raise MasterDataInvalid("batch_size must be an integer between 1 and %d" % MAX_BATCH_SIZE)
    return value


def _repository_for(ctx: Any):
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)


def _coll(entity_type: str) -> str:
    from app.master_data.repository import collection_name
    return collection_name(entity_type)


class MigrationOutcome:
    """What a migration operation did. ``performed`` only after every write,
    its verification and its canonical AuditEvent."""

    __slots__ = ("mode", "performed", "kind", "run_id", "status", "reason", "would_perform",
                 "replayed", "resumed", "checkpoint", "batches", "evidence", "entity_id")

    def __init__(self, mode: str, performed: bool, kind: str, **kw):
        self.mode, self.performed, self.kind = mode, performed, kind
        for slot in self.__slots__[3:]:
            setattr(self, slot, kw.get(slot, False if slot in ("replayed", "resumed") else None))

    def as_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self) -> str:                                   # pragma: no cover
        return "MigrationOutcome(%r)" % (self.as_dict(),)


# ==================================================================== audit
async def _audit(ctx: Any, *, action: str, result: str, entity_id: str, actor_id: str,
                 reason: str, idempotency_key: Optional[str] = None,
                 approval_id: Optional[str] = None, correlation_id: Optional[str] = None,
                 diff: Optional[Dict[str, Any]] = None, error_code: Optional[str] = None,
                 entity_type: str = "master_data.legacy_migration",
                 entity_version: Optional[str] = None) -> Dict[str, Any]:
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=ctx.tenant_id, actor_type=ACTOR_HUMAN, actor_id=actor_id, action=action,
        source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS, result=result,
        entity_type=entity_type, entity_id=entity_id, entity_version=entity_version,
        structured_diff=diff, reason=reason[:MAX_REASON], approval_id=approval_id,
        idempotency_key=idempotency_key, correlation_id=correlation_id, error_code=error_code,
        source_channel=SOURCE_LEGACY_MIGRATION)
    return await record_event(await ctx.db(), event)


async def _audit_once(ctx: Any, db, *, action: str, idempotency_key: str, **kw) -> None:
    """The success event of one step, never twice — also across retries."""
    from app.audit.store import AUDIT_COLLECTION
    existing = await db[AUDIT_COLLECTION].find_one(
        {"tenant_id": ctx.tenant_id, "action": action, "idempotency_key": idempotency_key,
         "result": "success"}, {"_id": 0})
    if existing is None:
        await _audit(ctx, action=action, result="success", idempotency_key=idempotency_key, **kw)


_CODES = ((MasterDataApprovalRequired, "APPROVAL_REQUIRED"), (MigrationStalePlan, "STALE_PLAN"),
          (MigrationBusy, "MIGRATION_BUSY"), (MigrationConflict, "MIGRATION_CONFLICT"),
          (MigrationVerificationFailed, "VERIFICATION_FAILED"))


def error_code(exc: Exception) -> str:
    for cls, code in _CODES:
        if isinstance(exc, cls):
            return code
    return "REFUSED"


async def _audit_refusal(ctx: Any, *, action: str, entity_id: str, actor_id: str,
                         exc: Exception, idempotency_key: Optional[str],
                         approval_id: Optional[str], correlation_id: Optional[str]) -> None:
    from app.audit.envelope import RESULT_DENIED, RESULT_FAILURE
    try:
        await _audit(ctx, action=action + "_refused",
                     result=RESULT_DENIED if isinstance(exc, MasterDataApprovalRequired)
                     else RESULT_FAILURE,
                     entity_id=entity_id, actor_id=actor_id, reason=str(exc),
                     idempotency_key=idempotency_key, correlation_id=correlation_id,
                     error_code=error_code(exc),
                     # never in the envelope's approval_id: it was not verified
                     diff={"claimed_approval_id": approval_id} if approval_id else None)
    except Exception as audit_exc:                    # noqa: BLE001
        raise MasterDataAuditFailed("%s was refused (%s) and the refusal's AuditEvent also "
                                    "failed (%s)" % (action, exc, audit_exc)) from exc


# ===================================================================== lock
def _lock_id(tenant_id: str) -> str:
    return "migration-lock:" + lp.digest(tenant_id)


async def _take_lock(db, tenant_id: str, holder: str, attempt: str, now: str,
                     takeover_from: Optional[str] = None) -> None:
    """One migration operation per tenant. Built on the built-in unique ``_id``.

    The SAME operation may take the lock back only after its previous attempt
    recorded the interruption; ``takeover_from`` lets a rollback take the lock
    of the interrupted run it is about to undo — nothing else.
    """
    lid = _lock_id(tenant_id)
    try:
        await db[LOCK_COLLECTION].update_one({"_id": lid, "tenant_id": tenant_id, "holder": None},
                               {"$set": {"holder": holder, "attempt": attempt, "interrupted": False,
                                         "taken_at": now}}, upsert=True)
    except Exception as exc:                          # noqa: BLE001 — only a duplicate is expected
        if not _is_duplicate_key(exc):
            raise
    current = await db[LOCK_COLLECTION].find_one({"_id": lid, "tenant_id": tenant_id}) or {}
    reclaimable = current.get("interrupted") is True and current.get("attempt") != attempt and (
        current.get("holder") == holder or current.get("holder") == takeover_from)
    if reclaimable:
        await db[LOCK_COLLECTION].update_one({"_id": lid, "tenant_id": tenant_id, "holder": current.get("holder"),
                                "attempt": current.get("attempt"), "interrupted": True},
                               {"$set": {"holder": holder, "attempt": attempt, "interrupted": False,
                                         "retaken_at": now}})
        current = await db[LOCK_COLLECTION].find_one({"_id": lid, "tenant_id": tenant_id}) or {}
    if current.get("holder") != holder or current.get("attempt") != attempt:
        busy = MigrationBusy("another migration operation of this tenant is in progress or was "
                             "interrupted (%s); finish or roll back that one first"
                             % current.get("holder"))
        busy.same_operation = current.get("holder") == holder
        raise busy


async def _release_lock(db, tenant_id: str, holder: str, attempt: str) -> None:
    await db[LOCK_COLLECTION].update_one(
        {"_id": _lock_id(tenant_id), "tenant_id": tenant_id, "holder": holder, "attempt": attempt},
        {"$set": {"holder": None, "attempt": None, "interrupted": False, "released_at": _now()}})


async def _mark_interrupted(db, tenant_id: str, holder: str, attempt: str) -> None:
    await db[LOCK_COLLECTION].update_one(
        {"_id": _lock_id(tenant_id), "tenant_id": tenant_id, "holder": holder, "attempt": attempt},
        {"$set": {"interrupted": True, "interrupted_at": _now()}})


# ============================================================ item writing
def _entry(org_id: str, run_id: Optional[str], item: Dict[str, Any]) -> Dict[str, Any]:
    entry = {"collection": item["collection"], "legacy_id": item["legacy_id"], "org_id": org_id,
             "run_id": run_id}
    if item.get("roles"):
        entry["roles"] = sorted(item["roles"])
    return entry


def _target_id(tenant_id: str, run_id: str, ref: Optional[Dict[str, Any]]) -> Optional[str]:
    if not ref:
        return None
    if ref.get("entity_id"):
        return ref["entity_id"]
    coll, legacy_id = ref["anchor"]
    return master_id_for(tenant_id, run_id, coll, legacy_id)


def _identifiers(entity_type: str, item: Dict[str, Any]) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for ident in item.get("identifiers") or []:
        if ident["kind"] not in models.IDENTIFIER_KINDS.get(entity_type, ()):
            continue
        built = models.new_identifier(entity_type, ident["kind"], ident["value"])
        if built["key"] not in seen:
            seen.add(built["key"])
            out.append(built)
    return out


def build_master(*, tenant_id: str, entity_id: str, entity_type: str, display_name: str,
                 entry: Dict[str, Any], item: Dict[str, Any], relations: Dict[str, Any],
                 actor_id: str, run_id: Optional[str], now: str) -> Dict[str, Any]:
    doc = models.build_entity(tenant_id=tenant_id, entity_type=entity_type,
                              display_name=display_name, legacy_refs=[entry],
                              entity_id=entity_id, now=now)
    doc["identifiers"] = _identifiers(entity_type, item)
    doc.update({
        "source": SOURCE_LEGACY_MIGRATION, "migration_run_id": run_id,
        "schema_version": lp.MIGRATION_SCHEMA_VERSION, "created_by": actor_id,
        "name_scope": item.get("name_scope"),
        "legacy_attributes": dict(item.get("attributes") or {}),
    })
    doc.update(relations)
    models.validate_entity(doc)
    return doc


async def _insert_master(db, doc: Dict[str, Any], entry: Dict[str, Any]) -> None:
    try:
        await db[_coll(doc["entity_type"])].insert_one(dict(doc, _id=doc["id"]))
    except Exception as exc:                          # noqa: BLE001 — only a duplicate is expected
        if not _is_duplicate_key(exc):
            raise
        existing = await db[_coll(doc["entity_type"])].find_one(
            {"id": doc["id"], "tenant_id": doc["tenant_id"]}, {"_id": 0})
        if not existing or entry not in (existing.get("legacy_refs") or []):
            raise MigrationConflict("Master %s exists with other content" % doc["id"])


async def _attach(db, tenant_id: str, entity_type: str, entity_id: str, entry: Dict[str, Any],
                  identifiers: List[Dict[str, Any]], now: str) -> None:
    update: Dict[str, Any] = {"$addToSet": {"legacy_refs": entry}, "$set": {"updated_at": now}}
    result = await db[_coll(entity_type)].update_one({"id": entity_id, "tenant_id": tenant_id,
                                    "status": models.STATUS_ACTIVE}, update)
    doc = await db[_coll(entity_type)].find_one({"id": entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if getattr(result, "modified_count", 0) != 1 and (
            not doc or entry not in (doc.get("legacy_refs") or [])):
        raise MigrationConflict("Master %s %s is not an active record of this tenant; the legacy "
                                "id %s/%s cannot be attached" % (entity_type, entity_id,
                                                                 entry["collection"], entry["legacy_id"]))
    have = {i.get("key") for i in (doc.get("identifiers") or [])}
    for ident in identifiers:
        if ident["key"] not in have:
            await db[_coll(entity_type)].update_one({"id": entity_id, "tenant_id": tenant_id,
                                   "identifiers.key": {"$ne": ident["key"]}},
                                  {"$push": {"identifiers": ident}})


async def _write_ref(db, row: Dict[str, Any]) -> None:
    """Insert the reverse reference; a retry finds its own row, a rolled-back row
    is taken over by compare-and-set, anything else is a conflict."""
    try:
        await db[lp.REFS_COLLECTION].insert_one(dict(row))
        return
    except Exception as exc:                          # noqa: BLE001 — only a duplicate is expected
        if not _is_duplicate_key(exc):
            raise
    existing = await db[lp.REFS_COLLECTION].find_one({"_id": row["_id"], "tenant_id": row["tenant_id"]}) or {}
    same = all(existing.get(k) == row.get(k)
               for k in ("run_id", "status", "entity_id", "collection", "legacy_id"))
    if same:
        return
    if existing.get("status") == lp.REF_ROLLED_BACK:
        prior = {k: existing.get(k) for k in ("run_id", "status", "entity_id", "updated_at")}
        new = {k: v for k, v in row.items() if k not in ("_id", "history")}
        result = await db[lp.REFS_COLLECTION].update_one({"_id": row["_id"], "tenant_id": row["tenant_id"],
                                        "status": lp.REF_ROLLED_BACK, "run_id": existing.get("run_id")},
                                       {"$set": new, "$push": {"history": prior}})
        if getattr(result, "modified_count", 0) == 1:
            return
    raise MigrationConflict("legacy %s/%s is already accounted for (status %s, run %s)"
                            % (row["collection"], row["legacy_id"], existing.get("status"),
                               existing.get("run_id")))


def _ref_row(*, tenant_id: str, org_id: str, item: Dict[str, Any], status: str,
             entity_id: Optional[str], run_id: Optional[str], plan_token: Optional[str],
             now: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    row = {"_id": lp.ref_row_id(tenant_id, item["collection"], item["legacy_id"]),
           "tenant_id": tenant_id, "collection": item["collection"],
           "legacy_id": item["legacy_id"], "org_id": org_id,
           "entity_type": item.get("entity_type"), "entity_id": entity_id, "status": status,
           "reason_code": item.get("reason_code"), "candidates": item.get("candidates") or [],
           "candidate_types": item.get("candidate_types") or [],
           "display_name": item.get("display_name"), "fingerprint": item.get("fingerprint"),
           "run_id": run_id, "plan_token": plan_token,
           "schema_version": lp.MIGRATION_SCHEMA_VERSION, "history": [],
           "created_at": now, "updated_at": now}
    row.update(extra or {})
    return row


async def _source_unchanged(db, org_id: str, item: Dict[str, Any]) -> None:
    doc = await db[item["collection"]].find_one({"id": item["legacy_id"], "org_id": org_id},
                                                {"_id": 0})
    if doc is None or lp.digest({k: v for k, v in doc.items() if k != "_id"}) != item["fingerprint"]:
        raise MigrationStalePlan("legacy %s/%s changed or disappeared after the dry run; roll "
                                 "back or finish, then plan again"
                                 % (item["collection"], item["legacy_id"]))


async def _apply_item(db, *, tenant_id: str, org_id: str, run_id: str, plan_token: str,
                      item: Dict[str, Any], actor_id: str, now: str) -> Optional[str]:
    await _source_unchanged(db, org_id, item)
    decision = item["decision"]
    if decision in (lp.DECISION_PENDING, lp.DECISION_BLOCKED):
        status = lp.REF_PENDING if decision == lp.DECISION_PENDING else lp.REF_BLOCKED
        await _write_ref(db, _ref_row(tenant_id=tenant_id, org_id=org_id, item=item, status=status,
                                      entity_id=None, run_id=run_id, plan_token=plan_token, now=now))
        return None
    entry = _entry(org_id, run_id, item)
    relations = {rel: _target_id(tenant_id, run_id, ref)
                 for rel, ref in (item.get("relations") or {}).items()}
    if decision == lp.DECISION_CREATE:
        entity_id = master_id_for(tenant_id, run_id, item["collection"], item["legacy_id"])
        await _insert_master(db, build_master(
            tenant_id=tenant_id, entity_id=entity_id, entity_type=item["entity_type"],
            display_name=item["display_name"], entry=entry, item=item, relations=relations,
            actor_id=actor_id, run_id=run_id, now=now), entry)
    else:
        entity_id = _target_id(tenant_id, run_id, item["target"])
        own_anchor = bool((item.get("target") or {}).get("anchor"))
        await _attach(db, tenant_id, item["entity_type"], entity_id, entry,
                      _identifiers(item["entity_type"], item) if own_anchor else [], now)
    await _write_ref(db, _ref_row(tenant_id=tenant_id, org_id=org_id, item=item,
                                  status=lp.REF_MAPPED, entity_id=entity_id, run_id=run_id,
                                  plan_token=plan_token, now=now))
    return entity_id


# ============================================================= verification
async def verify_items(db, tenant_id: str, org_id: str, run_id: str,
                       items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every planned item, checked against what is stored. Read-only."""
    failures = []
    expected_status = {lp.DECISION_CREATE: lp.REF_MAPPED, lp.DECISION_ATTACH: lp.REF_MAPPED,
                       lp.DECISION_PENDING: lp.REF_PENDING, lp.DECISION_BLOCKED: lp.REF_BLOCKED}
    for item in items:
        row = await db[lp.REFS_COLLECTION].find_one(
            {"_id": lp.ref_row_id(tenant_id, item["collection"], item["legacy_id"]),
             "tenant_id": tenant_id}, {"_id": 0})
        problem = None
        if row is None:
            problem = "no reverse reference"
        elif row.get("run_id") != run_id or row.get("status") != expected_status[item["decision"]]:
            problem = "reverse reference is %s/%s" % (row.get("status"), row.get("run_id"))
        elif row["status"] == lp.REF_MAPPED:
            master = await db[_coll(item["entity_type"])].find_one(
                {"id": row.get("entity_id"), "tenant_id": tenant_id}, {"_id": 0})
            if master is None or _entry(org_id, run_id, item) not in (master.get("legacy_refs") or []):
                problem = "Master %s does not carry the legacy reference" % row.get("entity_id")
        if problem:
            failures.append({"collection": item["collection"], "legacy_id": item["legacy_id"],
                             "problem": problem})
    return failures


# ============================================================ reconciliation
async def _resolves(db, tenant_id: str, org_id: str, row: Dict[str, Any]) -> bool:
    from app.master_data.merge import _chain
    try:
        chain = await _chain(db, tenant_id, row["entity_type"], row["entity_id"])
    except MasterDataRefused:
        return False
    if not chain:
        return False
    first = chain[0]
    return any(isinstance(r, dict) and r.get("collection") == row["collection"]
               and r.get("legacy_id") == row["legacy_id"] and r.get("org_id") == org_id
               for r in first.get("legacy_refs") or [])


async def reconcile_state(db, tenant_id: str, org_id: str,
                          collections: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Count every legacy identity document and every stored reference to one,
    and prove that none silently disappeared. Read-only.

      * **accounted** — the legacy document has a live reverse-reference row;
      * **unmigrated** — it has none yet (not planned, or planned later);
      * **broken** — a ``mapped`` row that does not resolve to a Master record of
        this tenant carrying the reference back: a LOST reference;
      * **legacy_gone** — the document no longer exists but its row still
        resolves through the Master record: kept, not lost;
      * **dangling** — a stored reference to an id that is neither a legacy
        document nor a reverse reference of this tenant: pre-existing, reported;
      * forward ``legacy_refs`` of Master records must each have their row, and
        none may name another ``org_id``.
    """
    names = lp.select_sources(collections)
    rows = await db[lp.REFS_COLLECTION].find({"tenant_id": tenant_id}, {"_id": 0}).to_list(None)
    live = {(r["collection"], r["legacy_id"]): r for r in rows if r.get("status") in lp.LIVE_REF_STATUSES}
    sources: Dict[str, Any] = {}
    in_scope: Dict[str, set] = {}
    keys: Dict[str, Dict[str, str]] = {}
    lost_rows: List[Dict[str, Any]] = []
    for name in lp.select_sources(None):
        docs = await db[name].find({"org_id": org_id}, {"_id": 0, "id": 1, "key": 1}).to_list(None)
        ids = {d["id"] for d in docs if isinstance(d.get("id"), str)}
        in_scope[name] = ids
        keys[name] = {d["key"]: d["id"] for d in docs if d.get("key") and d.get("id")}
    for name in names:
        ids = in_scope[name]
        mine = {k[1]: r for k, r in live.items() if k[0] == name}
        by_status: Dict[str, int] = {}
        broken = []
        for legacy_id, row in mine.items():
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
            if row["status"] == lp.REF_MAPPED and not await _resolves(db, tenant_id, org_id, row):
                broken.append(legacy_id)
                lost_rows.append({"collection": name, "legacy_id": legacy_id})
            if row.get("org_id") != org_id:
                broken.append(legacy_id)
                lost_rows.append({"collection": name, "legacy_id": legacy_id,
                                  "problem": "row names another org"})
        sources[name] = {
            "legacy_in_scope": len(ids), "accounted": len(ids & set(mine)),
            "unmigrated": len(ids - set(mine)), "rows": by_status,
            "legacy_gone": len(set(mine) - ids), "broken": len(broken),
            "sample_unmigrated": sorted(ids - set(mine))[:SAMPLE],
            "sample_broken": sorted(broken)[:SAMPLE],
        }

    # stored references, counted field by field
    references = []
    lost_refs = 0
    for ref in ls.REFERENCES:
        if ref.target not in names:
            continue
        docs = await db[ref.collection].find({**dict(ref.where), "org_id": org_id},
                                             {"_id": 0}).to_list(None)
        counts = {"total": 0, "accounted": 0, "unmigrated": 0, "dangling": 0, "lost": 0}
        for doc in docs:
            for value in ls.values_at(doc, ref.field):
                target_id = keys[ref.target].get(value) if ref.by_key else value
                counts["total"] += 1
                row = live.get((ref.target, target_id)) if target_id else None
                if row is not None:
                    if row["status"] == lp.REF_MAPPED and not await _resolves(db, tenant_id, org_id, row):
                        counts["lost"] += 1
                    else:
                        counts["accounted"] += 1
                elif target_id in in_scope[ref.target]:
                    counts["unmigrated"] += 1
                else:
                    counts["dangling"] += 1
        lost_refs += counts["lost"]
        references.append({"collection": ref.collection, "field": ref.field, "target": ref.target,
                           **counts})

    # forward references on Master records
    orphan_forward, foreign = [], []
    for etype in sorted({ls.source(n).entity_type for n in names}):
        masters = await db[_coll(etype)].find({"tenant_id": tenant_id}, {"_id": 0}).to_list(None)
        for m in masters:
            if m.get("archived_by_run"):
                continue        # archived by a rollback: its references are history
            for r in m.get("legacy_refs") or []:
                if not isinstance(r, dict) or r.get("collection") not in names:
                    continue
                if r.get("org_id") not in (None, org_id):
                    foreign.append({"entity_id": m.get("id"), "collection": r.get("collection"),
                                    "legacy_id": r.get("legacy_id")})
                    continue
                row = live.get((r.get("collection"), r.get("legacy_id")))
                if row is None or row.get("entity_id") != m.get("id"):
                    orphan_forward.append({"entity_id": m.get("id"), "collection": r.get("collection"),
                                           "legacy_id": r.get("legacy_id")})
    lost = len(lost_rows) + lost_refs + len(orphan_forward) + len(foreign)
    return {"tenant_id": tenant_id, "org_id": org_id, "sources": sources,
            "references": references, "lost_rows": lost_rows[:SAMPLE],
            "orphan_forward_refs": orphan_forward[:SAMPLE], "foreign_legacy_refs": foreign[:SAMPLE],
            "counts": {"broken_rows": len(lost_rows), "lost_references": lost_refs,
                       "orphan_forward_refs": len(orphan_forward),
                       "foreign_legacy_refs": len(foreign),
                       "unmigrated": sum(s["unmigrated"] for s in sources.values()),
                       "dangling_references": sum(r["dangling"] for r in references)},
            "zero_lost": lost == 0}


async def reconcile(ctx: Any, *, sources: Optional[Iterable[str]] = None, mode: Any = None,
                    repository=None) -> Optional[Dict[str, Any]]:
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    repo = repository if repository is not None else _repository_for(ctx)
    return await reconcile_state(await repo.db(), ctx.tenant_id, lp.legacy_org_id(ctx), sources)


async def run_status(ctx: Any, *, run_id: str, mode: Any = None,
                     repository=None) -> Optional[Dict[str, Any]]:
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    repo = repository if repository is not None else _repository_for(ctx)
    doc = await (await repo.db())[RUNS_COLLECTION].find_one(
        {"_id": _require_text(run_id, "run_id"), "tenant_id": ctx.tenant_id}, {"_id": 0})
    if doc is not None:
        doc.pop("items", None)
    return doc


# =================================================================== common
def _shadow_or_off(effective: str, kind: str, ctx, payload, checks) -> Optional[MigrationOutcome]:
    if effective == MODE_OFF:
        return MigrationOutcome(MODE_OFF, False, kind, reason="master data is off")
    if effective == MODE_SHADOW:
        try:
            validated = require_tenant_context(ctx)
            _reject_tenant_override(payload)
            _require_actor(validated)
            lp.legacy_org_id(validated)
            checks()
        except (MasterDataRefused, MasterDataInvalid, MasterDataTenantContextMissing) as exc:
            return MigrationOutcome(MODE_SHADOW, False, kind, reason=str(exc), would_perform=False)
        return MigrationOutcome(MODE_SHADOW, False, kind, would_perform=None,
                                reason="shadow: nothing read or written; the migration runs "
                                       "only in enforce")
    return None


async def _begin(db, tenant_id: str, action: str, key: str, fingerprint: str):
    """Reserve the idempotency key. Returns (state, replay_reference)."""
    from app.audit.idempotency import (
        IDEMPOTENCY_COLLECTION, IDEMPOTENCY_COMPLETED, IDEMPOTENCY_DUPLICATE, IdempotencyConflict,
        _record_id, begin_idempotent)
    prior = await db[IDEMPOTENCY_COLLECTION].find_one({"id": _record_id(tenant_id, action, key),
                                                       "tenant_id": tenant_id},
                                                      {"_id": 0})
    if prior and prior.get("request_fingerprint") not in (None, fingerprint):
        raise MasterDataRefused("idempotency key %r was already used for a different %s request"
                                % (key, action))
    if prior and prior.get("status") == IDEMPOTENCY_COMPLETED:
        return None, prior.get("result_reference")
    try:
        state = await begin_idempotent(db, tenant_id=tenant_id, key=key, action=action,
                                       request_fingerprint=fingerprint)
    except IdempotencyConflict as exc:
        raise MasterDataRefused(str(exc)) from exc
    if state.get("status") == IDEMPOTENCY_DUPLICATE and state.get("prior_status") == IDEMPOTENCY_COMPLETED:
        return None, state.get("result_reference")
    return state, None


# ================================================================== execute
async def execute(
    ctx: Any,
    *,
    plan_token: str,
    idempotency_key: str,
    confirmation: bool = False,
    approval_id: Optional[str] = None,
    sources: Optional[Iterable[str]] = None,
    batch_size: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    mode: Any = None,
    repository=None,
    approval_verifier: Any = None,
    _fail_after: Optional[str] = None,
) -> MigrationOutcome:
    """Apply exactly the dry-run plan named by ``plan_token`` to this tenant.

    ``off`` is inert; ``shadow`` validates the request without a read and writes
    nothing; ``enforce`` writes only with verified Approval — in this build,
    never (module docstring). A repeated request resumes an interrupted run.
    """
    effective = resolve_mode(mode)

    def args():
        _require_text(plan_token, "plan_token (execution without a dry run is refused)")
        _require_text(idempotency_key, "idempotency_key")
        _batch_size(batch_size)
        lp.select_sources(sources)
        if confirmation is not True:
            raise MasterDataRefused("a migration requires explicit human confirmation of the plan")
    early = _shadow_or_off(effective, "execute", ctx, payload, args)
    if early is not None:
        return early

    ctx = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    actor_id = _require_actor(ctx)
    org_id = lp.legacy_org_id(ctx)
    args()
    size = _batch_size(batch_size)
    collections = lp.select_sources(sources)
    tenant_id = ctx.tenant_id
    key = idempotency_key.strip()
    run_id = run_id_for(tenant_id, key)
    repo = repository if repository is not None else _repository_for(ctx)
    db = await repo.db()
    from app.audit.idempotency import complete_idempotent, fail_idempotent, request_fingerprint
    fingerprint = request_fingerprint({"plan_token": plan_token, "sources": collections,
                                       "batch_size": size, "approval_id": approval_id})

    def outcome(**kw):
        return MigrationOutcome(MODE_ENFORCE, True, "execute", run_id=run_id, **kw)

    async def refuse(exc):
        exc._audited = True
        await _audit_refusal(ctx, action=ACTION_EXECUTE, entity_id=run_id, actor_id=actor_id,
                             exc=exc, idempotency_key=key, approval_id=approval_id,
                             correlation_id=run_id)
        raise exc

    try:
        state, replay = await _begin_readonly(db, tenant_id, key, fingerprint)
    except MasterDataRefused as exc:
        await refuse(exc)
    if replay is not None:
        return outcome(status=RUN_COMPLETED, replayed=True,
                       reason="already completed under this idempotency key")

    run = await db[RUNS_COLLECTION].find_one({"_id": run_id, "tenant_id": tenant_id})
    # --- read-only checks BEFORE any write: the plan, then the approval
    subject = {"action": ACTION_EXECUTE, "tenant_id": tenant_id, "plan_token": plan_token,
               "sources": collections}
    try:
        if run is None:
            fresh = await lp.compute(db, tenant_id, org_id, collections)
            if fresh["plan_token"] != plan_token:
                raise MigrationStalePlan("the legacy data, a Master record or a reverse reference "
                                         "changed since the dry run (token mismatch); plan again")
        elif run.get("plan_token") != plan_token or run.get("sources") != collections:
            raise MigrationStalePlan("run %s was started for another plan" % run_id)
        elif run.get("status") == RUN_ROLLED_BACK:
            raise MasterDataRefused("run %s was rolled back; plan again under a new key" % run_id)
        elif run.get("schema_version") != lp.MIGRATION_SCHEMA_VERSION:
            raise MasterDataRefused("run %s was written by schema version %s, this build is %s"
                                    % (run_id, run.get("schema_version"), lp.MIGRATION_SCHEMA_VERSION))
        evidence = await _verify_approval(ctx, approval_verifier, approval_id, subject)
    except MasterDataRefused as exc:
        await refuse(exc)

    # --- bookkeeping: key, lock
    state, replay = await _begin(db, tenant_id, ACTION_EXECUTE, key, fingerprint)
    if replay is not None:
        return outcome(status=RUN_COMPLETED, replayed=True)
    attempt = uuid.uuid4().hex
    try:
        await _take_lock(db, tenant_id, run_id, attempt, _now())
    except MigrationBusy as exc:
        if not getattr(exc, "same_operation", False):
            await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_EXECUTE,
                                  error_code="MIGRATION_BUSY")
        await refuse(exc)

    resumed = run is not None
    written = False
    try:
        # --- under the lock: re-plan (first attempt) or reuse the frozen plan (resume)
        if run is None:
            fresh = await lp.compute(db, tenant_id, org_id, collections)
            if fresh["plan_token"] != plan_token:
                await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_EXECUTE,
                                      error_code="STALE_PLAN")
                await _release_lock(db, tenant_id, run_id, attempt)
                await refuse(MigrationStalePlan("the plan changed while the lock was taken"))
            before = await reconcile_state(db, tenant_id, org_id, collections)
            run = {"_id": run_id, "id": run_id, "tenant_id": tenant_id, "org_id": org_id,
                   "schema_version": lp.MIGRATION_SCHEMA_VERSION, "plan_version": lp.PLAN_VERSION,
                   "plan_token": plan_token, "sources": collections, "batch_size": size,
                   "items": fresh["items"], "totals": fresh["totals"],
                   "batches": (len(fresh["items"]) + size - 1) // size, "checkpoint": 0,
                   "status": RUN_RUNNING, "idempotency_key": key, "actor_id": actor_id,
                   "approval": evidence.as_record(), "attempts": [],
                   "evidence": {"before": _counts(before)}, "created_at": _now()}
            try:
                await db[RUNS_COLLECTION].insert_one(dict(run))
            except Exception as exc:                  # noqa: BLE001
                if not _is_duplicate_key(exc):
                    raise
                run = await db[RUNS_COLLECTION].find_one({"_id": run_id, "tenant_id": tenant_id})
        # From here the tenant belongs to this run until it completes or is rolled
        # back: an interruption keeps the lock for the SAME run only.
        written = True
        await db[RUNS_COLLECTION].update_one(
            {"_id": run_id, "tenant_id": tenant_id},
            {"$set": {"status": RUN_RUNNING, "updated_at": _now()},
             "$push": {"attempts": {"attempt": attempt, "started_at": _now(), "actor_id": actor_id}}})
        _maybe_fail(_fail_after, "run_started")

        items = run["items"]
        for index in range(int(run.get("checkpoint") or 0), int(run["batches"])):
            batch = items[index * run["batch_size"]:(index + 1) * run["batch_size"]]
            applied = []
            for n, item in enumerate(batch):
                written = True
                entity_id = await _apply_item(db, tenant_id=tenant_id, org_id=org_id, run_id=run_id,
                                              plan_token=plan_token, item=item, actor_id=actor_id,
                                              now=_now())
                applied.append({"collection": item["collection"], "legacy_id": item["legacy_id"],
                                "decision": item["decision"], "entity_id": entity_id})
                _maybe_fail(_fail_after, "item:%d:%d" % (index, n))
            await _audit_once(ctx, db, action="master_data.legacy_migration.batch_applied",
                              idempotency_key="%s:batch:%d" % (key, index), entity_id=run_id,
                              actor_id=actor_id, correlation_id=run_id,
                              approval_id=evidence.approval_id, entity_version=plan_token,
                              reason="legacy migration batch %d of %d applied" % (index + 1, run["batches"]),
                              diff={"batch": index, "items": applied})
            await db[RUNS_COLLECTION].update_one({"_id": run_id, "tenant_id": tenant_id},
                                                 {"$set": {"checkpoint": index + 1, "updated_at": _now()}})
            _maybe_fail(_fail_after, "batch:%d" % index)

        # --- every planned item, verified
        failures = await verify_items(db, tenant_id, org_id, run_id, items)
        if failures:
            await db[RUNS_COLLECTION].update_one(
                {"_id": run_id, "tenant_id": tenant_id},
                {"$set": {"status": RUN_VERIFICATION_FAILED, "verification": failures[:SAMPLE],
                          "updated_at": _now()}})
            await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_EXECUTE,
                                  error_code="VERIFICATION_FAILED")
            await _release_lock(db, tenant_id, run_id, attempt)
            await refuse(MigrationVerificationFailed(
                "%d planned legacy records do not match the plan after the run: %s"
                % (len(failures), failures[:3])))
        _maybe_fail(_fail_after, "verified")
        after = await reconcile_state(db, tenant_id, org_id, collections)
        await db[RUNS_COLLECTION].update_one(
            {"_id": run_id, "tenant_id": tenant_id},
            {"$set": {"evidence.after": _counts(after), "evidence.zero_lost": after["zero_lost"],
                      "updated_at": _now()}})
        await _audit_once(ctx, db, action="master_data.legacy_migration.completed",
                          idempotency_key=key, entity_id=run_id, actor_id=actor_id,
                          correlation_id=run_id, approval_id=evidence.approval_id,
                          entity_version=plan_token,
                          reason="legacy migration completed and verified",
                          diff={"totals": run.get("totals"), "sources": collections,
                                "zero_lost": after["zero_lost"], "after": _counts(after)["counts"]})
        _maybe_fail(_fail_after, "audited")
        await db[RUNS_COLLECTION].update_one(
            {"_id": run_id, "tenant_id": tenant_id},
            {"$set": {"status": RUN_COMPLETED, "completed_at": _now(), "updated_at": _now()}})
        await db[STATE_COLLECTION].update_one(
            {"_id": "state:" + tenant_id, "tenant_id": tenant_id},
            {"$set": {"schema_version": lp.MIGRATION_SCHEMA_VERSION, "last_run_id": run_id,
                      "updated_at": _now()}, "$addToSet": {"completed_runs": run_id}}, upsert=True)
        await complete_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_EXECUTE,
                                  result_reference=run_id)
        await _release_lock(db, tenant_id, run_id, attempt)
        return outcome(status=RUN_COMPLETED, resumed=resumed, batches=run["batches"],
                       checkpoint=run["batches"], evidence={"before": run["evidence"]["before"],
                                                            "after": _counts(after)})
    except (MasterDataRefused, MasterDataInvalid) as exc:
        # A refusal in the middle of a run (a source changed, a write conflict) is
        # recorded like an interruption — the lock stays with this run — and
        # audited once. Refusals that already released the lock are unaffected.
        await _record_interruption(db, tenant_id, run_id, key, attempt, ACTION_EXECUTE, written)
        if isinstance(exc, MasterDataRefused) and not getattr(exc, "_audited", False):
            await refuse(exc)
        raise
    except MasterDataAuditFailed:
        raise
    except Exception as exc:                          # noqa: BLE001 — recorded, then re-raised
        await _record_interruption(db, tenant_id, run_id, key, attempt, ACTION_EXECUTE, written)
        if isinstance(exc, _Interrupted):
            raise
        raise MasterDataAuditFailed(
            "migration run %s was interrupted (%s: %s); it is NOT successful and its state is "
            "recorded — repeat the SAME request to resume after the last checkpoint"
            % (run_id, type(exc).__name__, exc)) from exc


async def _begin_readonly(db, tenant_id: str, key: str, fingerprint: str):
    """Read the registry without reserving: an identical completed request is a replay."""
    from app.audit.idempotency import IDEMPOTENCY_COLLECTION, IDEMPOTENCY_COMPLETED, _record_id
    prior = await db[IDEMPOTENCY_COLLECTION].find_one(
        {"id": _record_id(tenant_id, ACTION_EXECUTE, key), "tenant_id": tenant_id}, {"_id": 0})
    if prior and prior.get("request_fingerprint") not in (None, fingerprint):
        raise MasterDataRefused("idempotency key %r was already used for a different migration "
                                "request" % key)
    if prior and prior.get("status") == IDEMPOTENCY_COMPLETED:
        return prior, prior.get("result_reference")
    return prior, None


def _counts(report: Dict[str, Any]) -> Dict[str, Any]:
    return {"sources": {n: {k: v for k, v in s.items() if not k.startswith("sample")}
                        for n, s in report["sources"].items()},
            "references": [{k: r[k] for k in ("collection", "field", "target", "total",
                                              "accounted", "unmigrated", "dangling", "lost")}
                           for r in report["references"]],
            "counts": report["counts"], "zero_lost": report["zero_lost"]}


async def _record_interruption(db, tenant_id: str, run_id: str, key: str, attempt: str,
                               action: str, written: bool) -> None:
    from app.audit.idempotency import fail_idempotent
    try:
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=action,
                              error_code="WRITE_INCOMPLETE" if written else "INTERRUPTED")
        await db[RUNS_COLLECTION].update_one(
            {"_id": run_id, "tenant_id": tenant_id, "status": RUN_RUNNING},
            {"$set": {"status": RUN_INTERRUPTED, "interrupted_at": _now()}})
        if written:
            await _mark_interrupted(db, tenant_id, run_id, attempt)
        else:
            await _release_lock(db, tenant_id, run_id, attempt)
    except Exception:                                 # noqa: BLE001 — the original error wins
        pass


# ================================================================= rollback
async def _rollback_state(db, tenant_id: str, org_id: str, run_id: str) -> Dict[str, Any]:
    run = await db[RUNS_COLLECTION].find_one({"_id": run_id, "tenant_id": tenant_id}, {"_id": 0})
    if run is None:
        raise MasterDataRefused("run %s is not a migration run of this tenant" % run_id)
    blocking: List[str] = []
    if run.get("status") not in (RUN_COMPLETED, RUN_INTERRUPTED, RUN_VERIFICATION_FAILED,
                                 RUN_ROLLED_BACK):
        blocking.append("run is %s; only a completed, interrupted or failed run can be rolled back"
                        % run.get("status"))
    rows = await db[lp.REFS_COLLECTION].find({"tenant_id": tenant_id, "run_id": run_id},
                                             {"_id": 0}).to_list(None)
    created, attached = [], []
    types = sorted({i["entity_type"] for i in run.get("items") or [] if i.get("entity_type")})
    pending_refs = {p.get("resolved_entity_id") for p in await db["md_pending_mapping"].find(
        {"tenant_id": tenant_id}, {"_id": 0, "resolved_entity_id": 1}).to_list(None)}
    for etype in types:
        for m in await db[_coll(etype)].find({"tenant_id": tenant_id, "migration_run_id": run_id},
                                 {"_id": 0}).to_list(None):
            created.append(m)
            if m.get("status") == models.STATUS_ARCHIVED and m.get("archived_by_run") == run_id:
                continue
            if m.get("status") != models.STATUS_ACTIVE:
                blocking.append("%s %s is %s since the run" % (etype, m["id"], m.get("status")))
            foreign_entries = [r for r in m.get("legacy_refs") or [] if r.get("run_id") != run_id]
            if foreign_entries:
                blocking.append("%s %s carries legacy references added outside this run" % (etype, m["id"]))
            if await db[_coll(etype)].find_one({"tenant_id": tenant_id, "merged_into": m["id"]}, {"_id": 0}):
                blocking.append("%s %s is the target of a merge" % (etype, m["id"]))
            if m["id"] in pending_refs:
                blocking.append("%s %s is used by a resolved pending mapping" % (etype, m["id"]))
            for rel in ("parent_id", "asset_type_id"):
                other = await db[_coll(etype if rel == "parent_id" else models.ENTITY_PHYSICAL_ASSET)] \
                    .find_one({"tenant_id": tenant_id, rel: m["id"],
                               "migration_run_id": {"$ne": run_id}}, {"_id": 0})
                if other:
                    blocking.append("%s %s is referenced by %s of %s outside this run"
                                    % (etype, m["id"], rel, other.get("id")))
        for m in await db[_coll(etype)].find({"tenant_id": tenant_id, "legacy_refs.run_id": run_id,
                                  "migration_run_id": {"$ne": run_id}}, {"_id": 0}).to_list(None):
            attached.append(m)
    token = lp.digest({"run": run, "rows": sorted(rows, key=lambda r: r["legacy_id"]),
                       "created": created, "attached": attached})
    return {"run_id": run_id, "run_status": run.get("status"),
            "rows_to_roll_back": sum(1 for r in rows if r.get("status") in lp.LIVE_REF_STATUSES),
            "masters_to_archive": sorted(m["id"] for m in created
                                         if m.get("status") == models.STATUS_ACTIVE),
            "legacy_refs_to_detach": sorted(m["id"] for m in attached),
            "not_changed": ["every legacy collection", "Master records created before the run "
                            "(only this run's legacy_refs entries are detached)",
                            "nothing is deleted: this run's Master records are archived"],
            "blocking": blocking, "executable": not blocking,
            "preview_token": token, "_rows": rows, "_created": created, "_attached": attached}


def _strip(preview: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in preview.items() if not k.startswith("_")}


async def preview_rollback(ctx: Any, *, run_id: str, mode: Any = None,
                           repository=None) -> Optional[Dict[str, Any]]:
    """What rolling back one run would do. Never writes."""
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    repo = repository if repository is not None else _repository_for(ctx)
    return _strip(await _rollback_state(await repo.db(), ctx.tenant_id, lp.legacy_org_id(ctx),
                                        _require_text(run_id, "run_id")))


async def rollback(ctx: Any, *, run_id: str, preview_token: str, idempotency_key: str,
                   reason: str, confirmation: bool = False, approval_id: Optional[str] = None,
                   payload: Optional[Dict[str, Any]] = None, mode: Any = None, repository=None,
                   approval_verifier: Any = None, _fail_after: Optional[str] = None) -> MigrationOutcome:
    """Undo one run without deleting anything: its reverse-reference rows become
    ``rolled_back`` (history kept), the Master records it created are archived,
    its ``legacy_refs`` entries on older Master records are detached. Refused as
    a whole if anything built on the run since (a merge, a mapping, a child)."""
    effective = resolve_mode(mode)

    def args():
        _require_text(run_id, "run_id")
        _require_text(preview_token, "preview_token (a rollback without a preview is refused)")
        _require_text(idempotency_key, "idempotency_key")
        _reason(reason, required=True)
        if confirmation is not True:
            raise MasterDataRefused("a rollback requires explicit human confirmation of the preview")
    early = _shadow_or_off(effective, "rollback", ctx, payload, args)
    if early is not None:
        return early
    ctx = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    actor_id = _require_actor(ctx)
    org_id = lp.legacy_org_id(ctx)
    args()
    why = _reason(reason, required=True)
    tenant_id, key = ctx.tenant_id, idempotency_key.strip()
    op = _op_id(tenant_id, "rollback", key)
    repo = repository if repository is not None else _repository_for(ctx)
    db = await repo.db()
    from app.audit.idempotency import complete_idempotent, fail_idempotent, request_fingerprint
    fingerprint = request_fingerprint({"run_id": run_id, "preview_token": preview_token,
                                       "reason": why, "approval_id": approval_id})

    async def refuse(exc):
        await _audit_refusal(ctx, action=ACTION_ROLLBACK, entity_id=run_id, actor_id=actor_id,
                             exc=exc, idempotency_key=key, approval_id=approval_id,
                             correlation_id=run_id)
        raise exc

    subject = {"action": ACTION_ROLLBACK, "tenant_id": tenant_id, "run_id": run_id,
               "preview_token": preview_token}
    try:
        state = await _rollback_state(db, tenant_id, org_id, run_id)
        own_retry = state["run_status"] == RUN_ROLLED_BACK
        if not own_retry:
            if state["blocking"]:
                raise MasterDataRefused("rollback refused before any write: " + "; ".join(state["blocking"]))
            if state["preview_token"] != preview_token:
                raise MigrationStalePlan("the run's records changed since the rollback preview")
        evidence = await _verify_approval(ctx, approval_verifier, approval_id, subject)
        _st, replay = await _begin(db, tenant_id, ACTION_ROLLBACK, key, fingerprint)
    except MasterDataRefused as exc:
        await refuse(exc)
    if replay is not None:
        return MigrationOutcome(MODE_ENFORCE, True, "rollback", run_id=run_id, replayed=True,
                                status=RUN_ROLLED_BACK)
    attempt = uuid.uuid4().hex
    try:
        await _take_lock(db, tenant_id, op, attempt, _now(), takeover_from=run_id)
    except MigrationBusy as exc:
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_ROLLBACK,
                              error_code="MIGRATION_BUSY")
        await refuse(exc)
    try:
        now = _now()
        for row in state["_rows"]:
            if row.get("status") in lp.LIVE_REF_STATUSES:
                await db[lp.REFS_COLLECTION].update_one(
                    {"_id": lp.ref_row_id(tenant_id, row["collection"], row["legacy_id"]),
                     "tenant_id": tenant_id, "run_id": run_id, "status": row["status"]},
                    {"$set": {"status": lp.REF_ROLLED_BACK, "rolled_back_at": now,
                              "rolled_back_by": actor_id, "rollback_op": op, "updated_at": now},
                     "$push": {"history": {"status": row["status"], "entity_id": row.get("entity_id"),
                                           "run_id": run_id, "changed_at": now}}})
        _maybe_fail(_fail_after, "rows")
        for m in state["_attached"]:
            await db[_coll(m["entity_type"])].update_one(
                {"id": m["id"], "tenant_id": tenant_id},
                {"$pull": {"legacy_refs": {"run_id": run_id}}, "$set": {"updated_at": now}})
        for m in state["_created"]:
            await db[_coll(m["entity_type"])].update_one(
                {"id": m["id"], "tenant_id": tenant_id, "status": models.STATUS_ACTIVE,
                 "migration_run_id": run_id},
                {"$set": {"status": models.STATUS_ARCHIVED, "archived_reason": "legacy_migration_rollback",
                          "archived_by_run": run_id, "archived_at": now, "archived_by": actor_id,
                          "updated_at": now}})
        await db[RUNS_COLLECTION].update_one(
            {"_id": run_id, "tenant_id": tenant_id},
            {"$set": {"status": RUN_ROLLED_BACK, "rolled_back_at": now, "rollback_op": op,
                      "rollback_reason": why}})
        await db[STATE_COLLECTION].update_one(
            {"_id": "state:" + tenant_id, "tenant_id": tenant_id},
            {"$pull": {"completed_runs": run_id}, "$addToSet": {"rolled_back_runs": run_id},
             "$set": {"updated_at": now}}, upsert=True)
        _maybe_fail(_fail_after, "written")
        await _audit_once(ctx, db, action="master_data.legacy_migration.rolled_back",
                          idempotency_key=key, entity_id=run_id, actor_id=actor_id,
                          correlation_id=run_id, approval_id=evidence.approval_id,
                          entity_version=preview_token, reason=why,
                          diff={"rows": state["rows_to_roll_back"],
                                "archived": state["masters_to_archive"],
                                "detached_from": state["legacy_refs_to_detach"]})
        await complete_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_ROLLBACK,
                                  result_reference=run_id)
        await _release_lock(db, tenant_id, op, attempt)
    except (MasterDataRefused, MasterDataInvalid, MasterDataAuditFailed):
        raise
    except Exception as exc:                          # noqa: BLE001
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_ROLLBACK,
                              error_code="WRITE_INCOMPLETE")
        await _mark_interrupted(db, tenant_id, op, attempt)
        if isinstance(exc, _Interrupted):
            raise
        raise MasterDataAuditFailed("rollback of %s was interrupted (%s); repeat the SAME request"
                                    % (run_id, exc)) from exc
    return MigrationOutcome(MODE_ENFORCE, True, "rollback", run_id=run_id, status=RUN_ROLLED_BACK,
                            evidence=_strip(state))


# ================================================== human mapping decisions
async def list_mappings(ctx: Any, *, status: str = lp.REF_PENDING, collection: Optional[str] = None,
                        limit: int = 50, mode: Any = None, repository=None) -> List[Dict[str, Any]]:
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return []
    ctx = require_tenant_context(ctx)
    query: Dict[str, Any] = {"status": status}
    if collection:
        ls.source(collection)
        query["collection"] = collection
    repo = repository if repository is not None else _repository_for(ctx)
    rows = await (await repo.db())[lp.REFS_COLLECTION].find(
        {**query, "tenant_id": ctx.tenant_id}, {"_id": 0}).sort(
        [("collection", 1), ("legacy_id", 1)]).to_list(length=min(int(limit), 200))
    for row in rows:
        row.pop("fingerprint", None)
    return rows


async def resolve_mapping(
    ctx: Any,
    *,
    collection: str,
    legacy_id: str,
    decision: str,
    idempotency_key: str,
    confirmation: bool = False,
    canonical_entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    display_name: Optional[str] = None,
    reason: Optional[str] = None,
    approval_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    mode: Any = None,
    repository=None,
    approval_verifier: Any = None,
) -> MigrationOutcome:
    """A person decides one pending (or blocked) legacy record:

      * ``map`` — attach it to an existing active Master record of this tenant;
      * ``create_new`` — create an official Master record from it (the explicit
        human confirmation §4.5 requires for a person);
      * ``decline`` — it stays a legacy-only record, explicitly accounted for.

    Nothing is suggested into a decision: the candidates on the row are shown,
    never applied. Critical and approval-bound like the run itself.
    """
    effective = resolve_mode(mode)

    def args():
        ls.source(_require_text(collection, "collection"))
        _require_text(legacy_id, "legacy_id")
        _require_text(idempotency_key, "idempotency_key")
        if decision not in (DECIDE_MAP, DECIDE_CREATE, DECIDE_DECLINE):
            raise MasterDataInvalid("decision must be map, create_new or decline")
        if decision == DECIDE_MAP:
            _require_text(canonical_entity_id, "canonical_entity_id")
        if decision == DECIDE_DECLINE:
            _reason(reason, required=True)
        if confirmation is not True:
            raise MasterDataRefused("a mapping decision requires explicit human confirmation")
    early = _shadow_or_off(effective, "resolve_mapping", ctx, payload, args)
    if early is not None:
        return early
    ctx = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    actor_id = _require_actor(ctx)
    org_id = lp.legacy_org_id(ctx)
    args()
    tenant_id, key = ctx.tenant_id, idempotency_key.strip()
    op = _op_id(tenant_id, "resolve", key)
    row_id = lp.ref_row_id(tenant_id, collection, legacy_id)
    repo = repository if repository is not None else _repository_for(ctx)
    db = await repo.db()
    from app.audit.idempotency import complete_idempotent, fail_idempotent, request_fingerprint
    fingerprint = request_fingerprint({"collection": collection, "legacy_id": legacy_id,
                                       "decision": decision, "target": canonical_entity_id,
                                       "entity_type": entity_type, "display_name": display_name,
                                       "approval_id": approval_id})

    async def refuse(exc):
        await _audit_refusal(ctx, action=ACTION_RESOLVE, entity_id=row_id, actor_id=actor_id,
                             exc=exc, idempotency_key=key, approval_id=approval_id,
                             correlation_id=op)
        raise exc

    async def check():
        row = await db[lp.REFS_COLLECTION].find_one({"_id": row_id, "tenant_id": tenant_id})
        if row is None:
            raise MasterDataRefused("%s/%s has no reverse reference in this tenant; run the "
                                    "migration plan first" % (collection, legacy_id))
        if row.get("resolution_op") == op:
            return row, None, None
        if row.get("status") not in (lp.REF_PENDING, lp.REF_BLOCKED):
            raise MasterDataRefused("%s/%s is %s, not waiting for a decision"
                                    % (collection, legacy_id, row.get("status")))
        if row.get("org_id") != org_id:
            raise MasterDataRefused("the reverse reference names another org; refusing")
        etype = row.get("entity_type")
        if row.get("reason_code") == ls.PENDING_ENTITY_TYPE and decision != DECIDE_DECLINE:
            if entity_type not in (row.get("candidate_types") or []):
                raise MasterDataInvalid("choose the entity_type: one of %s" % row.get("candidate_types"))
            etype = entity_type
        elif entity_type not in (None, etype):
            raise MasterDataInvalid("%s/%s maps to %s, not %s" % (collection, legacy_id, etype, entity_type))
        if decision == DECIDE_CREATE and row.get("reason_code") == ls.PENDING_PROJECT_SCOPED:
            raise MasterDataRefused("a project-scoped group is never an official activity "
                                    "(FLOW-032); map it to one or decline")
        legacy = await db[collection].find_one({"id": legacy_id, "org_id": org_id}, {"_id": 0})
        if decision == DECIDE_MAP:
            target = await db[_coll(etype)].find_one(
                {"id": canonical_entity_id, "tenant_id": tenant_id}, {"_id": 0})
            if target is None or target.get("status") != models.STATUS_ACTIVE:
                raise MasterDataRefused("%s is not an active %s of this tenant"
                                        % (canonical_entity_id, etype))
            if any(r.get("org_id") not in (None, org_id) for r in target.get("legacy_refs") or []):
                raise MasterDataRefused("%s carries a legacy reference of another org" % canonical_entity_id)
        elif decision == DECIDE_CREATE and legacy is None:
            raise MasterDataRefused("%s/%s no longer exists; it can be mapped or declined only"
                                    % (collection, legacy_id))
        return row, etype, legacy

    try:
        row, etype, legacy = await check()
        subject = {"action": ACTION_RESOLVE, "tenant_id": tenant_id, "collection": collection,
                   "legacy_id": legacy_id, "decision": decision, "target": canonical_entity_id,
                   "entity_type": etype}
        evidence = await _verify_approval(ctx, approval_verifier, approval_id, subject)
        _st, replay = await _begin(db, tenant_id, ACTION_RESOLVE, key, fingerprint)
    except MasterDataRefused as exc:
        await refuse(exc)
    if replay is not None:
        return MigrationOutcome(MODE_ENFORCE, True, "resolve_mapping", replayed=True,
                                entity_id=replay)
    attempt = uuid.uuid4().hex
    try:
        await _take_lock(db, tenant_id, op, attempt, _now())
    except MigrationBusy as exc:
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_RESOLVE,
                              error_code="MIGRATION_BUSY")
        await refuse(exc)
    try:
        if row.get("resolution_op") != op:
            row, etype, legacy = await check()
        else:
            etype = row.get("entity_type")
        now = _now()
        item = {"collection": collection, "legacy_id": legacy_id, "entity_type": etype,
                "roles": [], "identifiers": [], "attributes": {}, "name_scope": None}
        entity_id: Optional[str] = row.get("entity_id")
        if row.get("resolution_op") != op:
            if decision == DECIDE_CREATE:
                ex = ls.extract(collection, legacy)
                if ex.entity_type == etype:
                    item.update(roles=ex.roles, attributes=ex.attributes,
                                identifiers=[{"kind": k, "value": v} for k, v in ex.identifiers],
                                name_scope=list(ex.name_scope) if ex.name_scope else None)
                name = (display_name or "").strip() or ex.display_name
                if not name:
                    raise MasterDataInvalid("display_name is required: the legacy record has none")
                entity_id = _op_id(tenant_id, "resolved-master", key)
                entry = _entry(org_id, None, item)
                entry["resolution_op"] = op
                await _insert_master(db, build_master(
                    tenant_id=tenant_id, entity_id=entity_id, entity_type=etype, display_name=name,
                    entry=entry, item=item, relations={}, actor_id=actor_id, run_id=None,
                    now=now), entry)
            elif decision == DECIDE_MAP:
                entity_id = canonical_entity_id
                entry = _entry(org_id, None, item)
                entry["resolution_op"] = op
                await _attach(db, tenant_id, etype, entity_id, entry, [], now)
            status = lp.REF_DECLINED if decision == DECIDE_DECLINE else lp.REF_MAPPED
            result = await db[lp.REFS_COLLECTION].update_one(
                {"_id": row_id, "tenant_id": tenant_id, "status": row.get("status")},
                {"$set": {"status": status, "entity_id": entity_id if status == lp.REF_MAPPED else None,
                          "entity_type": etype, "resolution_op": op, "resolved_by": actor_id,
                          "resolved_at": now, "resolution": decision,
                          "resolution_reason": _reason(reason, decision == DECIDE_DECLINE),
                          "updated_at": now},
                 "$push": {"history": {"status": row.get("status"), "reason_code": row.get("reason_code"),
                                       "changed_at": now}}})
            if getattr(result, "modified_count", 0) != 1:
                raise MigrationConflict("%s/%s changed while it was being decided" % (collection, legacy_id))
        await _audit_once(ctx, db, action="master_data.legacy_mapping.resolved",
                          idempotency_key=key, entity_id=row_id, actor_id=actor_id,
                          correlation_id=op, approval_id=evidence.approval_id,
                          reason=reason or "legacy mapping decided by a person",
                          diff={"collection": collection, "legacy_id": legacy_id,
                                "decision": decision, "entity_type": etype, "entity_id": entity_id,
                                "previous_reason": row.get("reason_code")})
        await complete_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_RESOLVE,
                                  result_reference=entity_id or row_id)
        await _release_lock(db, tenant_id, op, attempt)
    except (MasterDataRefused, MasterDataInvalid) as exc:
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_RESOLVE,
                              error_code=error_code(exc) if isinstance(exc, MasterDataRefused) else "INVALID")
        await _release_lock(db, tenant_id, op, attempt)
        if isinstance(exc, MasterDataRefused):
            await refuse(exc)
        raise
    except MasterDataAuditFailed:
        raise
    except Exception as exc:                          # noqa: BLE001
        await fail_idempotent(db, tenant_id=tenant_id, key=key, action=ACTION_RESOLVE,
                              error_code="WRITE_INCOMPLETE")
        await _mark_interrupted(db, tenant_id, op, attempt)
        raise MasterDataAuditFailed("mapping decision for %s/%s was interrupted (%s); repeat the "
                                    "SAME request" % (collection, legacy_id, exc)) from exc
    return MigrationOutcome(MODE_ENFORCE, True, "resolve_mapping", entity_id=entity_id,
                            status=lp.REF_DECLINED if decision == DECIDE_DECLINE else lp.REF_MAPPED)
