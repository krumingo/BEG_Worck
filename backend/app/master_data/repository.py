"""
W0-03B1 — per-tenant Master Data repository.

One collection per canonical type (contract §7, Q1 default), resolved through
the existing W0-01 resolver. No second tenancy resolver is introduced here.

The resolver module instantiates a Mongo client at import time, so it is
imported **lazily inside the methods**: importing this module in ``off`` mode
must not create a client, open a socket or touch configuration. The off-mode
inertness test asserts exactly that.

Nothing in W0-03B1 calls this repository from a route. It exists so that
W0-03B2 has a tested foundation to switch on.
"""
from typing import Any, Dict, Optional

from app.master_data.models import ENTITY_TYPES, MasterDataInvalid, validate_entity

COLLECTION_PREFIX = "md_"

#: How many times ``create_pending`` re-reads the open slot before giving up.
#: Contention settles in one or two passes; the bound only stops a livelock.
_MAX_SLOT_ATTEMPTS = 8


def _pending_slot_id(tenant_id: str, entity_type: str, normalized_value: str) -> str:
    """The ``_id`` of the open slot for one text. Deterministic, so every
    concurrent writer addresses the same document and Mongo's built-in unique
    ``_id`` index decides who created it — no new index is needed."""
    import hashlib
    key = "\x1f".join((tenant_id, entity_type, normalized_value)).encode("utf-8")
    return "pending-slot:" + hashlib.sha256(key).hexdigest()


def _is_duplicate_key(exc: BaseException) -> bool:
    """A duplicate ``_id`` (E11000), recognised without importing pymongo here —
    the same test the W0-04 idempotency store uses."""
    return (type(exc).__name__ == "DuplicateKeyError"
            or getattr(exc, "code", None) == 11000
            or "duplicate key" in str(exc).lower())


def collection_name(entity_type: str) -> str:
    """``person`` -> ``md_person``. Type-specific collections keep the future
    unique indexes clean and selective (contract §7, Q1)."""
    if entity_type not in ENTITY_TYPES:
        raise MasterDataInvalid("unknown entity_type: %s" % entity_type)
    return COLLECTION_PREFIX + entity_type


class MasterDataRepository:
    """Reads and writes one tenant's Master Data.

    The tenant is fixed at construction from an already-resolved context; the
    repository has no way to widen its own scope and never accepts a tenant
    identifier per call.
    """

    def __init__(self, tenant_id: str, db=None):
        if not tenant_id or not isinstance(tenant_id, str):
            raise MasterDataInvalid("repository requires a resolved tenant_id")
        self.tenant_id = tenant_id
        self._db = db          # injected in tests; otherwise resolved lazily

    async def db(self, require_operational: bool = False):
        if self._db is not None:
            return self._db
        # imported here on purpose — see the module docstring
        from app.tenancy.resolver import get_tenant_db
        return await get_tenant_db(self.tenant_id, require_operational=require_operational)

    async def _collection(self, entity_type: str, require_operational: bool = False):
        handle = await self.db(require_operational=require_operational)
        return handle[collection_name(entity_type)]

    def _scope(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Every query is pinned to this tenant. A caller cannot override it:
        the tenant key is applied last."""
        query = dict(extra or {})
        query["tenant_id"] = self.tenant_id
        return query

    async def get(self, entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
        coll = await self._collection(entity_type)
        return await coll.find_one(self._scope({"id": entity_id}), {"_id": 0})

    async def create_pending(self, pending: Dict[str, Any]) -> tuple:
        """Record one pending-mapping row, idempotently — also under concurrency.

        While a proposal for the same normalized text is open in this tenant,
        another sighting is **counted on that row** instead of opening a second
        one: ``occurrences`` grows, ``last_seen_at`` and the ``last_source_*``
        fields move, and every channel that saw the text is kept in
        ``source_channels`` (the first sighting stays in ``source_channel`` /
        ``source_ref``).

        **Why not a plain upsert.** An upsert whose filter is not covered by a
        unique index is not atomic: two importers can both find nothing and
        both insert. W0-03 adds no index (that is C), so the only uniqueness
        this code may rely on is the one every Mongo collection already has —
        ``_id``. Two steps use it:

          1. an *open slot* per ``(tenant, type, normalized value)`` in
             ``md_pending_slots``, whose ``_id`` is derived from that key,
             names the one row that is open for it. The first writer's id wins;
             everybody else reads the same answer;
          2. the row itself is written **by that ``_id``**, so of any number of
             concurrent writers exactly one inserts it and the rest can only
             count their sighting on it.

        When the named row is no longer ``pending`` (resolved, rejected, or
        being resolved) the slot is stale and is moved to a new row with a
        compare-and-set, so a text seen again after a decision opens a fresh
        proposal — the same behaviour as before, without the race.

        Returns ``(row, created)`` — ``created`` is True for exactly one writer.
        """
        from app.master_data.pending import (
            PENDING_COLLECTION, PENDING_SLOT_COLLECTION, STATUS_PENDING, validate_pending)
        validate_pending(pending)
        if pending["tenant_id"] != self.tenant_id:
            raise MasterDataInvalid(
                "refusing to write a pending record of tenant %s through the repository of tenant %s"
                % (pending["tenant_id"], self.tenant_id)
            )
        now = pending.get("last_seen_at") or pending.get("created_at")
        channel = pending["source_channel"]
        insert_doc = dict(pending)
        # Maintained by the update operators on every sighting, so they must
        # not also be handed to $setOnInsert — Mongo refuses a path in two
        # operators.
        for field in ("occurrences", "last_seen_at", "updated_at", "source_channels",
                      "last_source_channel", "last_source_ref"):
            insert_doc.pop(field, None)
        sighting = {
            "$inc": {"occurrences": 1},
            "$set": {"last_seen_at": now, "updated_at": now,
                     "last_source_channel": channel,
                     "last_source_ref": pending.get("source_ref")},
            "$addToSet": {"source_channels": channel},
        }

        handle = await self.db(require_operational=True)
        slots = handle[PENDING_SLOT_COLLECTION]
        rows = handle[PENDING_COLLECTION]
        slot_id = _pending_slot_id(self.tenant_id, pending["entity_type"],
                                   pending["normalized_value"])

        for _attempt in range(_MAX_SLOT_ATTEMPTS):
            # 1. which row is open for this text? The first writer names it.
            try:
                await slots.update_one(
                    self._scope({"_id": slot_id}),
                    {"$setOnInsert": {"pending_id": pending["id"],
                                      "entity_type": pending["entity_type"],
                                      "normalized_value": pending["normalized_value"],
                                      "created_at": now}},
                    upsert=True,
                )
            except Exception as exc:                  # noqa: BLE001 — only a duplicate is expected
                if not _is_duplicate_key(exc):
                    raise
            slot = await slots.find_one(self._scope({"_id": slot_id}))
            if not slot or not slot.get("pending_id"):
                continue
            owner = slot["pending_id"]

            # 2. count this sighting on that row — or create it, by _id.
            row_doc = dict(insert_doc, id=owner)
            try:
                result = await rows.update_one(
                    self._scope({"_id": owner, "status": STATUS_PENDING}),
                    dict(sighting, **{"$setOnInsert": row_doc}),
                    upsert=True,
                )
            except Exception as exc:                  # noqa: BLE001 — only a duplicate is expected
                if not _is_duplicate_key(exc):
                    raise
                existing = await rows.find_one(self._scope({"_id": owner}), {"_id": 0})
                if existing is not None and existing.get("status") != STATUS_PENDING:
                    # The slot names a row that is already decided: move it to
                    # a fresh one. Only one writer's compare-and-set succeeds;
                    # the others read the new owner on the next pass.
                    await slots.update_one(
                        self._scope({"_id": slot_id, "pending_id": owner}),
                        {"$set": {"pending_id": pending["id"], "replaced_at": now}},
                    )
                continue          # a concurrent insert of the same row: count on it now
            stored = await rows.find_one(self._scope({"_id": owner}), {"_id": 0})
            created = getattr(result, "upserted_id", None) is not None
            return (stored if stored is not None else row_doc), created

        raise MasterDataInvalid(
            "could not settle the open pending row for this text after %d attempts"
            % _MAX_SLOT_ATTEMPTS)

    async def get_pending(self, pending_id: str) -> Optional[Dict[str, Any]]:
        from app.master_data.pending import PENDING_COLLECTION
        handle = await self.db()
        return await handle[PENDING_COLLECTION].find_one(self._scope({"id": pending_id}), {"_id": 0})

    async def list_pending(self, *, entity_type: Optional[str] = None,
                           status: str = "pending", source_channel: Optional[str] = None,
                           limit: int = 50) -> list:
        from app.master_data.pending import PENDING_COLLECTION
        query = self._scope({"status": status})
        if entity_type:
            query["entity_type"] = entity_type
        if source_channel:
            # Every channel that saw the text, not only the first one: a row
            # first seen by OCR and then by an Excel import is an Excel
            # proposal too, and filtering by Excel must not hide it.
            query["$or"] = [{"source_channels": source_channel},
                            {"source_channel": source_channel}]
        handle = await self.db()
        cursor = handle[PENDING_COLLECTION].find(query, {"_id": 0})
        return await cursor.to_list(length=min(int(limit), 200))

    async def search_by_text(self, entity_type: str, query: str, limit: int = 10) -> list:
        """Records a PERSON may pick from, for text they typed themselves.

        This is a lookup, not matching. Nothing here is ever used to link
        anything automatically: it exists so the office can find the record it
        already has in mind when the proposal's own text does not normalize
        onto it. The automatic path stays exact — FLOW-032 Q7b forbids fuzzy
        auto-matching, and showing options to a human is not that.
        """
        import re
        from app.master_data.normalize import normalize_name

        needle = normalize_name(query or "")
        if not needle:
            return []
        pattern = {"$regex": re.escape(needle), "$options": "i"}
        coll = await self._collection(entity_type)
        cursor = coll.find(
            self._scope({"status": "active",
                         "$or": [{"normalized_name": pattern},
                                 {"aliases.normalized": pattern}]}),
            {"_id": 0},
        )
        return await cursor.to_list(length=min(int(limit), 50))

    async def claim_pending(self, pending_id: str, *, actor_id: str,
                            now: str) -> Optional[Dict[str, Any]]:
        """Atomically take a pending row out of ``pending``.

        This is the whole concurrency story, and it is the ONLY way into the
        body of an approval: the transition ``pending -> resolving`` is a
        compare-and-set, so of two simultaneous approvals only one can proceed
        and only one canonical record can ever be created. Returns None when
        somebody else got there first.

        A row already in ``resolving`` is never re-entered — not even by the
        reviewer who claimed it. There is no way to tell a caller that died from
        one that is still working, so letting a second request in on the grounds
        that it carries the same actor would put two callers inside the body at
        once, which is precisely what this compare-and-set exists to prevent.
        """
        from app.master_data.pending import PENDING_COLLECTION, STATUS_PENDING, STATUS_RESOLVING
        handle = await self.db(require_operational=True)
        result = await handle[PENDING_COLLECTION].update_one(
            self._scope({"id": pending_id, "status": STATUS_PENDING}),
            {"$set": {"status": STATUS_RESOLVING, "claimed_by": actor_id,
                      "claimed_at": now, "updated_at": now}},
        )
        if getattr(result, "modified_count", 0) != 1:
            return None
        return await handle[PENDING_COLLECTION].find_one(
            self._scope({"id": pending_id}), {"_id": 0})

    async def release_pending(self, pending_id: str, *, actor_id: str, now: str) -> None:
        """Give a claimed row back after a failure, so it stays workable.

        Only the holder of the claim can release it. Nothing in this package can
        currently reach this with somebody else's row, and that is exactly why
        the condition is written down: it keeps the claim the single thing that
        decides who may act on a row.
        """
        from app.master_data.pending import PENDING_COLLECTION, STATUS_PENDING, STATUS_RESOLVING
        handle = await self.db(require_operational=True)
        await handle[PENDING_COLLECTION].update_one(
            self._scope({"id": pending_id, "status": STATUS_RESOLVING,
                         "claimed_by": actor_id}),
            {"$set": {"status": STATUS_PENDING, "claimed_by": None,
                      "claimed_at": None, "updated_at": now}},
        )

    async def finish_pending(self, pending_id: str, *, entity_id: str, actor_id: str,
                             now: str) -> bool:
        from app.master_data.pending import PENDING_COLLECTION, STATUS_RESOLVED, STATUS_RESOLVING
        handle = await self.db(require_operational=True)
        result = await handle[PENDING_COLLECTION].update_one(
            self._scope({"id": pending_id, "status": STATUS_RESOLVING,
                         "claimed_by": actor_id}),
            {"$set": {"status": STATUS_RESOLVED, "resolved_entity_id": entity_id,
                      "resolved_by": actor_id, "resolved_at": now, "updated_at": now}},
        )
        return getattr(result, "modified_count", 0) == 1

    async def reject_pending(self, pending_id: str, *, reason: str, actor_id: str,
                             now: str) -> bool:
        from app.master_data.pending import PENDING_COLLECTION, STATUS_PENDING, STATUS_REJECTED
        handle = await self.db(require_operational=True)
        result = await handle[PENDING_COLLECTION].update_one(
            self._scope({"id": pending_id, "status": STATUS_PENDING}),
            {"$set": {"status": STATUS_REJECTED, "rejection_reason": reason,
                      "resolved_by": actor_id, "resolved_at": now, "updated_at": now}},
        )
        return getattr(result, "modified_count", 0) == 1

    async def find_by_normalized(self, entity_type: str, normalized: str,
                                 limit: int = 10) -> list:
        coll = await self._collection(entity_type)
        cursor = coll.find(self._scope({"normalized_name": normalized,
                                        "status": "active"}), {"_id": 0})
        return await cursor.to_list(length=min(int(limit), 100))

    async def find_by_alias(self, entity_type: str, normalized: str,
                            limit: int = 10) -> list:
        coll = await self._collection(entity_type)
        cursor = coll.find(self._scope({"aliases.normalized": normalized,
                                        "status": "active"}), {"_id": 0})
        return await cursor.to_list(length=min(int(limit), 100))

    async def add_alias(self, entity_type: str, entity_id: str,
                        alias: Dict[str, Any], now: str) -> bool:
        """Attach a human-confirmed spelling variant. Never called automatically.

        Idempotent by the normalized spelling: the same variant added twice —
        by a retried approval, a double click, or two people confirming the
        same text — leaves exactly one entry. The filter carries the condition,
        so the check and the write are one atomic operation rather than a
        read-then-write that two callers can interleave.

        Returns True when the record ends up carrying the spelling, including
        when it already did; False only when the record is not in this tenant.
        """
        normalized = (alias or {}).get("normalized")
        if not normalized:
            raise MasterDataInvalid("an alias must carry its normalized form")
        coll = await self._collection(entity_type, require_operational=True)
        result = await coll.update_one(
            self._scope({"id": entity_id, "aliases.normalized": {"$ne": normalized}}),
            {"$push": {"aliases": alias}, "$set": {"updated_at": now}},
        )
        if getattr(result, "modified_count", 0) == 1:
            return True
        # Nothing was written. Either the spelling is already there — which is
        # the end state the caller asked for — or the record is not ours.
        doc = await coll.find_one(self._scope({"id": entity_id}), {"_id": 0})
        if not doc:
            return False
        return any((a or {}).get("normalized") == normalized
                   for a in (doc.get("aliases") or []))

    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        validate_entity(entity)
        if entity["tenant_id"] != self.tenant_id:
            raise MasterDataInvalid(
                "refusing to write an entity of tenant %s through the repository of tenant %s"
                % (entity["tenant_id"], self.tenant_id)
            )
        coll = await self._collection(entity["entity_type"], require_operational=True)
        await coll.insert_one(dict(entity))
        return entity
