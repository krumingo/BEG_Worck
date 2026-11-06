"""
Required indexes on the canonical ledger / idempotency collections.

Every one of these backs an invariant that the service relies on:

  - unique (`tenant_id`, `movement_id`) — a movement_id cannot be reused;
  - unique (`tenant_id`, `idempotency_key`, `action`) on `audit_idempotency`
    — two concurrent requests under one key cannot both insert;
  - compound (`tenant_id`, `item_id`, `destination.location_type`,
    `destination.location_id`, `destination.state`, `recorded_at`) for
    stock projection scans without truncation (>1000 rows);
  - compound (`tenant_id`, `item_id`, `source.location_type`,
    `source.location_id`, `source.state`, `recorded_at`) for FIFO reads;
  - partial unique (`tenant_id`, `dispatch_movement_id`, `action`) on
    acceptance rows: cannot double-accept the same dispatch.

The service verifies presence on first use and FAILS CLOSED
(IndexMissingError) if any required index is absent. This is required
by TASK 5C: "Verify indexes first and fail closed if absent".
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from app.services.warehouse_movements.errors import IndexMissingError


MOVEMENTS_COLLECTION = "warehouse_transactions"
IDEMPOTENCY_COLLECTION = "audit_idempotency"


class RequiredIndex:
    __slots__ = ("name", "collection", "keys", "unique", "partial_filter",
                 "stricter_full_unique_ok")

    def __init__(
        self,
        name: str,
        collection: str,
        keys: List[Tuple[str, int]],
        *,
        unique: bool = False,
        partial_filter: Dict | None = None,
        stricter_full_unique_ok: bool = False,
    ) -> None:
        self.name = name
        self.collection = collection
        self.keys = keys
        self.unique = unique
        self.partial_filter = partial_filter
        # 5C-C24 F-55-C23-02: a unique index WITHOUT a partial filter on the
        # same keys is strictly stronger than the partial one (it covers
        # every row, canonical ones included). Where this flag is set such
        # an index — e.g. the pre-C24 `wh_movements_unique_movement_id`
        # built on a database with no legacy rows — satisfies the
        # requirement as-is; it is never dropped or rebuilt.
        self.stricter_full_unique_ok = stricter_full_unique_ok

    def matches(self, mongo_index: Dict) -> bool:
        """Return True if `mongo_index` meets or exceeds our requirement.

        A loose match is fine: the Mongo index may carry more fields or
        extra options, but must at least cover our prefix in order, with
        our uniqueness constraint, and (if we required a partial filter)
        the same filter expression.

        PyMongo's `index_information()` returns the `key` entry as a
        **list of (field, direction) tuples**, not a dict (CODEX C05 /
        `indexes.py:58` fix). Earlier revisions called `.items()` on it
        and crashed against a real server. The normalization below
        accepts either shape so unit tests that pass a dict and real
        PyMongo output both work.
        """
        raw = mongo_index.get("key", [])
        if isinstance(raw, dict):
            mongo_keys = list(raw.items())
        else:
            # list of (field, direction) tuples, exactly as PyMongo returns
            mongo_keys = [(k, v) for k, v in raw]
        want_prefix = [(k, int(v)) for k, v in self.keys]
        got_prefix = [(k, int(v)) for k, v in mongo_keys[: len(self.keys)]]
        if got_prefix != want_prefix:
            return False
        if self.unique and not mongo_index.get("unique", False):
            return False
        if self.partial_filter is not None:
            got_filter = mongo_index.get("partialFilterExpression")
            if got_filter is None and self.unique and self.stricter_full_unique_ok:
                return True
            if got_filter is None or dict(got_filter) != self.partial_filter:
                return False
        return True


# Required index set for TASK 5C.
#
# Covers v6 contract §9.3 "verified unique indexes" preconditions:
#   - AuditEvent (tenant_id, sequence), event_id, idempotency keys;
#   - acceptance_line_id;
#   - supplier-origin (tenant_id, supplier_source_line_key);
#   - FIFO server-sequence ordering stability.
#
# CODEX C03 fix: the single-accept-per-dispatch unique index was wrong
# — contract §10 explicitly requires MULTIPLE partial acceptances per
# dispatch. The uniqueness constraint moves down to `acceptance_line_id`
# (one acceptance "line" per discrete acceptance event); supplier-origin
# gets its own tenant-scoped uniqueness.
AUDIT_EVENTS_COLLECTION = "audit_events"

# 5C-C24 F-55-C23-02 — the rows the canonical movement-id uniqueness
# applies to: exactly the canonical ledger rows (string `movement_id`).
CANONICAL_MOVEMENT_FILTER: Dict = {"movement_id": {"$type": "string"}}

REQUIRED_INDEXES: List[RequiredIndex] = [
    # --- warehouse_transactions ---
    # 5C-C24 F-55-C23-02 — PARTIAL unique: canonical rows only.
    # Real legacy history in `main`'s `procurement.issue_to_project` shape
    # (`id`, `org_id`, `type`, `lines`; no `tenant_id`, no `movement_id`)
    # indexed as `{tenant_id: null, movement_id: null}`, so the second
    # legacy row failed the old full unique index with E11000 and the
    # canonical writer stayed fail-closed. Every canonical row carries a
    # string `movement_id` (envelope `mv_<uuid>`, server-issued), so the
    # filter `{movement_id: {$type: "string"}}` covers ALL canonical
    # movements and none of the legacy rows (absent or null id). History
    # is neither deleted nor given fake canonical ids.
    RequiredIndex(
        name="wh_movements_unique_movement_id",
        collection=MOVEMENTS_COLLECTION,
        keys=[("tenant_id", 1), ("movement_id", 1)],
        unique=True,
        partial_filter=CANONICAL_MOVEMENT_FILTER,
        stricter_full_unique_ok=True,
    ),
    # Server-ledger sequence per tenant: stable FIFO ordering tie-break
    # (CODEX C09 — "FIFO ordering has stable canonical sequence tie-break").
    RequiredIndex(
        name="wh_movements_unique_sequence",
        collection=MOVEMENTS_COLLECTION,
        keys=[("tenant_id", 1), ("ledger_sequence", 1)],
        unique=True,
        # Legacy rows (pre-TASK-5C) have no `ledger_sequence`; the sparse
        # partial filter admits them while still guaranteeing uniqueness
        # across every canonical writer row.
        partial_filter={"ledger_sequence": {"$exists": True}},
    ),
    # Multi-partial acceptance uniqueness (CODEX C03).
    # One acceptance_line_id per acceptance event — many may reference
    # the same dispatch_movement_id. Enforced at the service level by a
    # per-tenant uuid; the unique index catches a replay collision.
    RequiredIndex(
        name="wh_movements_unique_acceptance_line",
        collection=MOVEMENTS_COLLECTION,
        keys=[("tenant_id", 1), ("acceptance_line_id", 1)],
        unique=True,
        partial_filter={"acceptance_line_id": {"$exists": True}},
    ),
    # Supplier-origin uniqueness per v6 §9.3 and §10 "Supplier-origin
    # uniqueness": one `supplier_delivery_origin` per linked supplier
    # source line per tenant; a second concurrent create cannot win.
    RequiredIndex(
        name="wh_movements_unique_supplier_origin",
        collection=MOVEMENTS_COLLECTION,
        keys=[("tenant_id", 1), ("supplier_source_line_key", 1)],
        unique=True,
        partial_filter={"supplier_source_line_key": {"$exists": True}},
    ),
    RequiredIndex(
        name="wh_movements_destination_scan",
        collection=MOVEMENTS_COLLECTION,
        keys=[
            ("tenant_id", 1),
            ("item_id", 1),
            ("destination.location_type", 1),
            ("destination.location_id", 1),
            ("destination.state", 1),
            ("ledger_sequence", 1),
        ],
    ),
    RequiredIndex(
        name="wh_movements_source_scan",
        collection=MOVEMENTS_COLLECTION,
        keys=[
            ("tenant_id", 1),
            ("item_id", 1),
            ("source.location_type", 1),
            ("source.location_id", 1),
            ("source.state", 1),
            ("ledger_sequence", 1),
        ],
    ),
    # --- audit idempotency ---
    RequiredIndex(
        name="wh_idempotency_unique_claim",
        collection=IDEMPOTENCY_COLLECTION,
        keys=[("tenant_id", 1), ("action", 1), ("key", 1)],
        unique=True,
    ),
    # --- audit events (contract §9.3) ---
    RequiredIndex(
        name="wh_audit_unique_sequence",
        collection=AUDIT_EVENTS_COLLECTION,
        keys=[("tenant_id", 1), ("sequence", 1)],
        unique=True,
    ),
    RequiredIndex(
        name="wh_audit_unique_event_id",
        collection=AUDIT_EVENTS_COLLECTION,
        keys=[("event_id", 1)],
        unique=True,
    ),
]


async def ensure_required_indexes(db) -> List[str]:
    """Create any missing indexes, idempotently. Returns names created.

    Safe to call on every warm start. In production this should be
    executed by the migration-readiness `verify` step before the service
    is turned on; a cold runtime verify is also permitted for tests.
    """
    created: List[str] = []
    by_collection: Dict[str, List[RequiredIndex]] = {}
    for ri in REQUIRED_INDEXES:
        by_collection.setdefault(ri.collection, []).append(ri)

    conflicts: List[str] = []
    for coll_name, required in by_collection.items():
        existing = await db[coll_name].index_information()
        existing_list = [{"key": doc["key"], "unique": doc.get("unique", False),
                          "partialFilterExpression": doc.get("partialFilterExpression")}
                         for name, doc in existing.items()]
        for ri in required:
            if any(ri.matches(ex) for ex in existing_list):
                continue
            if ri.name in existing:
                # 5C-C24 F-55-C23-02 — an index with OUR name but other
                # options (e.g. non-unique, or another partial filter). It
                # is never dropped or rebuilt automatically: that is an
                # operator migration step (CLAUDE.md §8). Record the
                # conflict, create nothing under that name, and let the
                # service stay fail-closed (INDEX_MISSING) until resolved.
                doc = existing[ri.name]
                conflicts.append(
                    f"{coll_name}:{ri.name} exists with other options "
                    f"(key={list(doc.get('key', []))}, "
                    f"unique={doc.get('unique', False)}, "
                    f"partialFilterExpression={doc.get('partialFilterExpression')}); "
                    f"required unique={ri.unique}, "
                    f"partialFilterExpression={ri.partial_filter}"
                )
                continue
            options: Dict = {"name": ri.name}
            if ri.unique:
                options["unique"] = True
            if ri.partial_filter is not None:
                options["partialFilterExpression"] = ri.partial_filter
            await db[coll_name].create_index(ri.keys, **options)
            created.append(ri.name)
    if conflicts:
        raise IndexOptionsConflictError(conflicts, created)
    return created


class IndexOptionsConflictError(Exception):
    """5C-C24 F-55-C23-02 — a required index name is taken by an index with
    other options. Carries the conflicts and whatever WAS created."""

    def __init__(self, conflicts: List[str], created: List[str]) -> None:
        super().__init__("index option conflict (not dropped): " + "; ".join(conflicts))
        self.conflicts = conflicts
        self.created = created


async def ensure_required_indexes_at_startup(db) -> Dict:
    """5C-C19 F-1b — application-startup hook (`server.py`).

    Before C19 `ensure_required_indexes` had no caller outside tests,
    so a fresh enforce deploy answered 503 `INDEX_MISSING` on every
    canonical write until something created the indexes by hand. The
    canonical routes write to the request tenant's database handle
    (`TenantData.for_user(db, user)._db`), i.e. the same `db` the other
    startup indexes are created on, so this runs on that handle right
    next to them.

    Idempotent (existing matching indexes are skipped). It never drops
    or rewrites an index and never touches documents.

    5C-C24 F-55-C23-02 — the paths for `wh_movements_unique_movement_id`:
      * absent → created PARTIAL (canonical rows only), so legacy
        `procurement.issue_to_project` history (no tenant_id/movement_id)
        is admitted untouched;
      * present as the C24 partial index → skipped (repeated startup);
      * present as the pre-C24 FULL unique index → accepted as is (it is
        strictly stronger; it can only exist where no legacy rows were
        present), never dropped;
      * present under this name with any OTHER options → NOT dropped: the
        result is `ok=False` with `conflicts` naming the index, its options
        and the required ones; the writer stays fail-closed until an
        operator replaces it under Approval (critical migration,
        CLAUDE.md §8): inspect it, then — per tenant database, never
        automatically — drop that one index and re-run this hook, which
        creates the partial unique index. No document is touched. A failure (e.g.
    pre-existing data violating a unique key) is logged and returned —
    startup continues and the service stays FAIL-CLOSED: its own
    `verify_required_indexes` still refuses writes with INDEX_MISSING.
    """
    log = logging.getLogger(__name__)
    try:
        created = await ensure_required_indexes(db)
    except IndexOptionsConflictError as exc:
        log.error("warehouse canonical indexes not ensured: %s", exc)
        return {"ok": False, "created": exc.created, "error": str(exc),
                "conflicts": exc.conflicts}
    except Exception as exc:  # noqa: BLE001 — logged, service stays fail-closed
        log.error("warehouse canonical indexes not ensured: %s", exc)
        return {"ok": False, "created": [], "error": str(exc)}
    if created:
        log.info("warehouse canonical indexes created: %s", created)
    return {"ok": True, "created": created, "error": None}


async def verify_required_indexes(db) -> None:
    """Raise `IndexMissingError` if any required index is absent.

    Used by the service's first-write path in enforce mode to guarantee
    fail-closed behavior without a cold start requirement.
    """
    missing: List[str] = []
    by_collection: Dict[str, List[RequiredIndex]] = {}
    for ri in REQUIRED_INDEXES:
        by_collection.setdefault(ri.collection, []).append(ri)
    for coll_name, required in by_collection.items():
        try:
            existing_info = await db[coll_name].index_information()
        except Exception as exc:
            raise IndexMissingError(
                f"cannot inspect indexes on {coll_name}: {exc}",
                context={"collection": coll_name},
            ) from exc
        existing_list = [{"key": doc["key"], "unique": doc.get("unique", False),
                          "partialFilterExpression": doc.get("partialFilterExpression")}
                         for name, doc in existing_info.items()]
        for ri in required:
            if not any(ri.matches(ex) for ex in existing_list):
                missing.append(f"{coll_name}:{ri.name}")
    if missing:
        raise IndexMissingError(
            f"required indexes missing (fail-closed): {missing}",
            context={"missing": missing},
        )
