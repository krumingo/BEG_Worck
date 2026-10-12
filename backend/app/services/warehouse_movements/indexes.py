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

from typing import Dict, List, Tuple

from app.services.warehouse_movements.errors import IndexMissingError


MOVEMENTS_COLLECTION = "warehouse_transactions"
IDEMPOTENCY_COLLECTION = "audit_idempotency"


class RequiredIndex:
    __slots__ = ("name", "collection", "keys", "unique", "partial_filter")

    def __init__(
        self,
        name: str,
        collection: str,
        keys: List[Tuple[str, int]],
        *,
        unique: bool = False,
        partial_filter: Dict | None = None,
    ) -> None:
        self.name = name
        self.collection = collection
        self.keys = keys
        self.unique = unique
        self.partial_filter = partial_filter

    def matches(self, mongo_index: Dict) -> bool:
        """Return True if `mongo_index` meets or exceeds our requirement.

        A loose match is fine: the Mongo index may carry more fields or
        extra options, but must at least cover our prefix in order, with
        our uniqueness constraint, and (if we required a partial filter)
        the same filter expression.
        """
        mongo_keys = list(mongo_index.get("key", {}).items())
        # order-sensitive prefix check
        if mongo_keys[: len(self.keys)] != [(k, v) for k, v in self.keys]:
            return False
        if self.unique and not mongo_index.get("unique", False):
            return False
        if self.partial_filter is not None:
            if mongo_index.get("partialFilterExpression") != self.partial_filter:
                return False
        return True


# Required index set for TASK 5C.
REQUIRED_INDEXES: List[RequiredIndex] = [
    RequiredIndex(
        name="wh_movements_unique_movement_id",
        collection=MOVEMENTS_COLLECTION,
        keys=[("tenant_id", 1), ("movement_id", 1)],
        unique=True,
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
            ("recorded_at", 1),
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
            ("recorded_at", 1),
        ],
    ),
    RequiredIndex(
        name="wh_movements_dispatch_single_accept",
        collection=MOVEMENTS_COLLECTION,
        keys=[("tenant_id", 1), ("dispatch_movement_id", 1), ("action", 1)],
        unique=True,
        partial_filter={"action": "accept_project_delivery"},
    ),
    RequiredIndex(
        name="wh_idempotency_unique_claim",
        collection=IDEMPOTENCY_COLLECTION,
        keys=[("tenant_id", 1), ("action", 1), ("key", 1)],
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

    for coll_name, required in by_collection.items():
        existing = await db[coll_name].index_information()
        existing_list = [{"key": doc["key"], "unique": doc.get("unique", False),
                          "partialFilterExpression": doc.get("partialFilterExpression")}
                         for name, doc in existing.items()]
        for ri in required:
            if any(ri.matches(ex) for ex in existing_list):
                continue
            options: Dict = {"name": ri.name}
            if ri.unique:
                options["unique"] = True
            if ri.partial_filter is not None:
                options["partialFilterExpression"] = ri.partial_filter
            await db[coll_name].create_index(ri.keys, **options)
            created.append(ri.name)
    return created


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
