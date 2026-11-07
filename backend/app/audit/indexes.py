"""
W0-04-C01 — the audit and idempotency indexes exist in every tenant database.

``begin_idempotent`` (one key = one write, CLAUDE.md §14) and the AuditEvent hash
chain (FLOW-040 §8, one event per ``(tenant_id, sequence)``) are only safe when
their UNIQUE indexes exist. Before W0-04-C01 the indexes were created only by the
manual ``scripts/w0_04_bootstrap_audit_indexes.py --apply``, so a database nobody
ran it on accepted six winners for one idempotency key and forked the chain.

:func:`ensure_audit_indexes` is called at application startup for the operational
database and every database the Tenant Registry names, and by tenant onboarding
for the database the new tenant writes to. The manual script stays for checking.

The rules, in order:

* **idempotent** — an index with the planned keys and the planned uniqueness is
  kept as it is, whatever its name; a second start changes nothing;
* **nothing is dropped** — an index with the planned keys but another uniqueness
  (or another key under the planned name) is a conflict: :class:`AuditIndexConflict`,
  the start fails with a clear message, it is never "made room" for;
* **nothing is deleted** — MongoDB refuses to build a unique index over existing
  duplicates and builds nothing; that refusal becomes :class:`AuditIndexDuplicates`
  carrying the first duplicate key the server names. The records stay exactly as
  they are, for a human to decide; the manual script's dry run lists every
  duplicate group (read only).
"""
import hashlib
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

AUDIT_COLLECTION = "audit_events"            # = app.audit.store.AUDIT_COLLECTION
IDEMPOTENCY_COLLECTION = "audit_idempotency"  # = app.audit.idempotency.IDEMPOTENCY_COLLECTION

# (collection, keys, options) — the same list the bootstrap script plans.
PLANNED_INDEXES: List[Tuple[str, List[Tuple[str, int]], Dict[str, Any]]] = [
    (AUDIT_COLLECTION, [("event_id", 1)], {"unique": True}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("sequence", 1)], {"unique": True}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("occurred_at", -1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("actor_id", 1), ("occurred_at", -1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("entity_type", 1), ("entity_id", 1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("action", 1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("correlation_id", 1)], {}),
    (AUDIT_COLLECTION, [("tenant_id", 1), ("retention_class", 1)], {}),
    (IDEMPOTENCY_COLLECTION, [("id", 1)], {"unique": True}),
    (IDEMPOTENCY_COLLECTION, [("tenant_id", 1), ("action", 1), ("key", 1)], {"unique": True}),
]


class AuditIndexError(RuntimeError):
    """The audit indexes cannot be guaranteed for a database. Never ignored.

    F-72-01 / FG-117: the message names only an opaque database ref
    (database_ref()), the collection and the index (field names), a safe
    ``code`` and a diagnostic ``ref``. It never carries a
    key value, a reservation id, tenant content or MongoDB's errmsg/keyValue,
    and it is raised ``from None`` so the original driver error is not chained
    into a logged traceback. The rows themselves are listed only by the
    operator report (scripts/w0_04_bootstrap_audit_indexes.py, dry run).
    """

    code = "AUDIT_INDEX_UNAVAILABLE"

    def __init__(self, message: str, *, code: Optional[str] = None, ref: Optional[str] = None):
        self.code = code or type(self).code
        self.ref = ref or new_diagnostic_ref()
        super().__init__("[%s ref=%s] %s" % (self.code, self.ref, message))


class AuditIndexConflict(AuditIndexError):
    """An existing index contradicts the planned one. Nothing is dropped."""

    code = "AUDIT_INDEX_CONFLICT"


class AuditIndexDuplicates(AuditIndexError):
    """Existing records would violate a planned unique index. Nothing is deleted.

    ``report`` holds only safe fields (database_ref, collection, index, keys as
    field names, code, ref) — never the database name or the duplicate values.
    """

    code = "AUDIT_INDEX_DUPLICATES"

    def __init__(self, message: str, report: Dict[str, Any], **kw):
        super().__init__(message, **kw)
        self.report = dict(report, code=self.code, ref=self.ref)


def database_ref(name: Optional[str]) -> str:
    """FG-117: an opaque, stable reference to a tenant database for errors and logs.

    The database name can identify the company, so it never appears in a refusal
    or a log line; the dry-run operator report prints the name next to this ref.
    """
    return "db-" + hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:12]


def describe_report(report: Dict[str, Any]) -> str:
    """A loggable one-line summary of an ensure_audit_indexes() report (no name)."""
    return "%s: created %s" % (database_ref(report.get("database")), report.get("created"))


def new_diagnostic_ref() -> str:
    """A random correlation id for one refusal (it identifies the log line, not data)."""
    return uuid.uuid4().hex[:12]


def safe_reason(exc: BaseException) -> str:
    """A loggable classification of a driver/setup error — never its message."""
    if _is_duplicate_error(exc):
        return "existing duplicates block the unique index"
    if isinstance(exc, AuditIndexError):
        return exc.code
    code = getattr(exc, "code", None)
    if code in (85, 86):                    # IndexOptionsConflict / IndexKeySpecsConflict
        return "a conflicting index with the same keys exists"
    if isinstance(exc, _SafeGuardError):
        return str(exc)
    return "%s%s" % (type(exc).__name__, "" if code is None else " (code %s)" % code)


class _SafeGuardError(RuntimeError):
    """Internal guard outcome whose message is a fixed, data-free sentence."""


def _is_duplicate_error(exc) -> bool:
    return getattr(exc, "code", None) == 11000 or type(exc).__name__ == "DuplicateKeyError"


def index_name(keys: Sequence[Tuple[str, int]]) -> str:
    """MongoDB's default index name for ``keys``."""
    return "_".join("%s_%s" % (field, direction) for field, direction in keys)


def _norm_keys(keys: Iterable) -> List[Tuple[str, int]]:
    return [(str(f), int(d)) for f, d in keys]


def _classify(existing: Dict[str, Dict[str, Any]], keys, unique: bool,
              where: str = "") -> Tuple[str, Optional[str]]:
    """``("present", name)`` / ``("missing", None)``; raises on a conflict.

    ``where`` is an opaque location prefix (database ref + collection), never a name.
    """
    want = _norm_keys(keys)
    planned_name = index_name(want)
    for name, info in existing.items():
        if _norm_keys(info.get("key", [])) != want:
            continue
        has_unique = bool(info.get("unique", False))
        # A partial or sparse index does not protect every document.
        restricted = "partialFilterExpression" in info or bool(info.get("sparse", False))
        if has_unique == unique and not (unique and restricted):
            return "present", name
        raise AuditIndexConflict(
            where + "index %r on %s has unique=%s%s, planned unique=%s — not dropped; "
            "resolve by hand" % (name, want, has_unique,
                                 " (partial/sparse)" if restricted else "", unique))
    if planned_name in existing:
        raise AuditIndexConflict(
            where + "index name %r is taken by keys %s, planned %s — not dropped; resolve by hand"
            % (planned_name, _norm_keys(existing[planned_name].get("key", [])), want))
    return "missing", None


async def ensure_audit_indexes(db) -> Dict[str, Any]:
    """Make sure every planned index exists in ``db``. Idempotent; drops and deletes nothing.

    Returns ``{"database", "present": [...], "created": [...]}`` — for the
    caller, not for a log (log it with describe_report(), FG-117). Raises
    :class:`AuditIndexConflict` or :class:`AuditIndexDuplicates` instead of
    skipping an index silently.
    """
    report: Dict[str, Any] = {"database": db.name, "present": [], "created": []}
    info_cache: Dict[str, Dict[str, Any]] = {}
    for coll, keys, opts in PLANNED_INDEXES:
        unique = bool(opts.get("unique", False))
        if coll not in info_cache:
            info_cache[coll] = await db[coll].index_information()
        state, name = _classify(info_cache[coll], keys, unique,
                                where="%s.%s: " % (database_ref(db.name), coll))
        label = "%s.%s" % (coll, name or index_name(keys))
        if state == "present":
            report["present"].append(label)
            continue
        try:
            created = await db[coll].create_index(keys, **opts)
        except Exception as exc:  # noqa: BLE001
            # MongoDB refuses a unique build over existing duplicates and builds
            # nothing (code 11000). Nothing is deleted: report and stop.
            if not (unique and _is_duplicate_error(exc)):
                raise
            # F-72-01: no keyValue / errmsg here and no exception chaining.
            index = index_name(keys)
            dup = {"database_ref": database_ref(db.name), "collection": coll, "index": index,
                   "keys": _norm_keys(keys)}
            raise AuditIndexDuplicates(
                "%s: existing records violate the planned unique index %s on %s — nothing "
                "deleted; list the duplicate groups with "
                "scripts/w0_04_bootstrap_audit_indexes.py (dry run)" % (
                    database_ref(db.name), index, coll), dup) from None
        info_cache[coll] = await db[coll].index_information()
        report["created"].append("%s.%s" % (coll, created))
    return report


async def tenant_database_names(op_db, system_db) -> List[str]:
    """The operational database plus every database the Tenant Registry names.

    A registry that cannot be read raises: startup must not pretend it covered
    databases it could not list.
    """
    names = [op_db.name]
    try:
        records = await system_db["tenant_registry"].find(
            {}, {"_id": 0, "id": 1, "database_name": 1}).to_list(None)
    except Exception as exc:  # noqa: BLE001
        raise AuditIndexError("the tenant registry cannot be read (%s)"
                              % safe_reason(exc)) from None
    for r in records:
        name = r.get("database_name")
        if name and name not in names:
            names.append(name)
    return names


async def ensure_audit_indexes_for_installation(op_db, system_db) -> List[Dict[str, Any]]:
    """Application startup: every tenant database gets the indexes, or the start fails."""
    reports = []
    for name in await tenant_database_names(op_db, system_db):
        database = op_db if name == op_db.name else op_db.client[name]
        reports.append(await ensure_audit_indexes(database))
    return reports


# ---------------------------------------------------------------------------
# W0-04-C01 FG-57 — the lazy guard used by record_event and begin_idempotent.
# ---------------------------------------------------------------------------

# Databases already proven to carry a guarded index in this process:
# (id(client), database name, collection, keys). Only a positive result is cached.
_unique_index_verified = set()


def is_mongo_handle(handle) -> bool:
    """A real MongoDB database handle (Motor in production, mongomock-motor in
    tests). Every production path passes one: the tenant resolver and the legacy
    handle are both AsyncIOMotorDatabase. Pure in-memory test doubles (no
    client, no indexes) hold no server-side state to protect and are not checked.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorDatabase
        if isinstance(handle, AsyncIOMotorDatabase):
            return True
    except ImportError:  # pragma: no cover
        pass
    return hasattr(handle, "client") and hasattr(handle, "name")


def protects(info: Dict[str, Any], keys) -> bool:
    """True when an index_information() entry is a full unique index on ``keys``."""
    return (_norm_keys(info.get("key", [])) == _norm_keys(keys) and bool(info.get("unique"))
            and "partialFilterExpression" not in info and not info.get("sparse"))


async def unique_index_present(db, coll: str, keys) -> bool:
    indexes = await db[coll].index_information()
    return any(protects(i, keys) for i in indexes.values())


async def require_unique_index(db, coll: str, keys, error_cls, *, create: bool = True) -> None:
    """Fail closed unless ``coll`` carries the full unique index on ``keys``.

    ``create=True``: a missing index is created with exactly the planned
    definition, then checked again. ``create=False`` only checks — for a caller
    inside an open transaction, where an index build would wait for the
    transaction's own collection lock. Any refusal (conflicting index,
    existing duplicates, an error, still absent) raises ``error_cls``; nothing
    is dropped or deleted.
    """
    if not is_mongo_handle(db):
        return
    cache_key = (id(db.client), db.name, coll, tuple(_norm_keys(keys)))
    if cache_key in _unique_index_verified:
        return
    reason = None
    try:
        if not await unique_index_present(db, coll, keys):
            if not create:
                raise _SafeGuardError("the index is absent and cannot be built inside a "
                                      "transaction; call it before the transaction starts")
            await db[coll].create_index(keys, unique=True)
            if not await unique_index_present(db, coll, keys):
                raise _SafeGuardError("the index is still absent after create_index")
    except Exception as exc:  # noqa: BLE001
        reason = safe_reason(exc)
    if reason is not None:
        # F-72-01: a fixed sentence + the classified reason; the driver error
        # (which can quote the duplicate key) is neither formatted nor chained.
        ref = new_diagnostic_ref()
        raise error_cls(
            "[AUDIT_INDEX_UNPROTECTED ref=%s] %s.%s: no unique index %s and it cannot be "
            "created (%s); refusing to write (concurrent writes could duplicate). Operator: "
            "scripts/w0_04_bootstrap_audit_indexes.py (dry run)"
            % (ref, database_ref(db.name), coll, index_name(keys), reason))
    _unique_index_verified.add(cache_key)
