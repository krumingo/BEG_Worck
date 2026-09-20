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
