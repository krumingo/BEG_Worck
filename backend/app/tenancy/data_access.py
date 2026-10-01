"""
W0-03E-A1 — the one tenant-safe data access layer for the protected surface.

Why it exists. W0-03E/C03 and W0-03E-R1 each fixed one leak (``/prices``
invoice join; offer XLSX/PDF project join) and each review then reproduced
another one in a neighbouring route (finance invoice list/detail enriched
``project_code``/``project_name`` with ``db.projects.find_one({"id": ...})``).
The defect is the pattern, not the route: a related record resolved by its id
alone returns whichever tenant's document the database finds first when ids
collide in a shared legacy database. This module removes the pattern instead
of patching instances of it.

Contract (TENANCY_MODEL.md D-15, CLAUDE.md §3):

* The tenant is fixed ONCE per request from server-side state only:
  :meth:`TenantData.for_user` takes the ``org_id`` of the session user that
  ``get_current_user`` loaded from the database by the verified JWT user id;
  :meth:`TenantData.for_context` takes the W0-01 ``TenantContext.org_id``;
  :meth:`TenantData.for_owner_of` serves a public token link and uses the
  ``org_id`` of the one record the token itself resolved. A tenant value from
  a query string, form or JSON body is never an input to this module.
* Every read and every filtered write adds the tenant predicate. A caller
  filter that names a DIFFERENT ``org_id``/``tenant_id`` is refused
  (:class:`TenantScopeViolation`), never silently widened or rewritten.
* A related record that does not exist in the caller's tenant is ``None`` —
  the caller renders it as absent. There is no global-id, name or fuzzy
  fallback anywhere in this module.
* Aggregations get the tenant ``$match`` as their FIRST stage, and every join
  must be a :meth:`TenantData.lookup` stage (``$lookup`` immediately followed by
  a ``$filter`` of the joined array on the tenant). A raw ``$lookup``,
  ``$graphLookup``, ``$unionWith``, ``$out`` or ``$merge`` is refused before
  the database is touched. ``$filter`` (not a ``$lookup`` sub-pipeline) is used
  because it works on every MongoDB version and in the test double.
* Legacy ``org_id`` is the tenant key of the legacy operational collections;
  canonical Master Data (``md_*``) keeps using ``tenant_id`` through the
  W0-03 repository, which this module does not replace.

The static guard ``scripts/w0_03e_a1_tenant_access_guard.py`` rejects any
direct database access in the protected modules that bypasses this layer.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from fastapi import HTTPException

#: The tenant key the legacy operational collections carry.
TENANT_KEY = "org_id"

#: Entity name → legacy collection. The identity-bearing records of the
#: W0-03E surface; ``TenantData.collection`` serves any other tenant-owned one.
ENTITY_COLLECTIONS: Dict[str, str] = {
    "project": "projects",
    "client": "clients",
    "company": "companies",
    "user": "users",
    "warehouse": "warehouses",
    "invoice": "invoices",
    "counterparty": "counterparties",
    "person": "persons",
    "payment": "finance_payments",
    "allocation": "payment_allocations",
    "account": "financial_accounts",
    "offer": "offers",
    "subcontractor": "subcontractors",
}

#: Aggregation stages that read another collection. Only the scoped
#: ``lookup`` pair is allowed; the rest would bypass the tenant predicate.
_FORBIDDEN_STAGES = ("$graphLookup", "$unionWith", "$out", "$merge")


class TenantScopeViolation(RuntimeError):
    """A query tried to leave the request's tenant. Programming error: fail closed."""


class _ScopedLookup(dict):
    """A ``$lookup`` stage built by :meth:`TenantData.lookup` (marker type)."""


class _ScopedLookupFilter(dict):
    """The tenant ``$filter`` stage paired with a :class:`_ScopedLookup`."""


def _tenant_value(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TenantScopeViolation("no server-resolved tenant for this request")
    return value


class TenantCollection:
    """One collection seen through one tenant. Never returns a foreign document."""

    def __init__(self, scope: "TenantData", name: str):
        self._scope = scope
        self.name = name

    @property
    def _raw(self):
        return self._scope._db[self.name]

    # ---------------------------------------------------------------- reads
    async def get(self, record_id: Any, projection: Optional[Mapping] = None) -> Optional[Dict]:
        """The tenant's record with this ``id``; ``None`` when absent here.

        ``None`` also for an empty/absent id: a missing relation is never
        resolved to anything.
        """
        if record_id in (None, ""):
            return None
        return await self._raw.find_one(self._scope.scoped({"id": record_id}), _proj(projection))

    async def require(self, record_id: Any, projection: Optional[Mapping] = None,
                      detail: str = "Not found") -> Dict:
        """Like :meth:`get` but 404 when absent — a foreign id is not confirmed to exist."""
        doc = await self.get(record_id, projection)
        if not doc:
            raise HTTPException(status_code=404, detail=detail)
        return doc

    async def get_many(self, ids: Iterable[Any], projection: Optional[Mapping] = None) -> Dict[Any, Dict]:
        """``{id: doc}`` for the ids that exist in this tenant; others are simply absent."""
        wanted = sorted({i for i in ids if i not in (None, "")}, key=str)
        if not wanted:
            return {}
        proj = _proj(projection)
        if proj is not None and proj.get("id") == 0:
            raise TenantScopeViolation("get_many needs the id field")
        if proj is not None and any(v for k, v in proj.items() if k != "_id") and "id" not in proj:
            proj = {**proj, "id": 1}
        docs = await self._raw.find(self._scope.scoped({"id": {"$in": wanted}}), proj).to_list(None)
        return {d["id"]: d for d in docs}

    async def find_one(self, flt: Optional[Mapping] = None, projection: Optional[Mapping] = None,
                       **kw) -> Optional[Dict]:
        return await self._raw.find_one(self._scope.scoped(flt), _proj(projection), **kw)

    def find(self, flt: Optional[Mapping] = None, projection: Optional[Mapping] = None, **kw):
        """A motor cursor over the tenant's matching documents."""
        return self._raw.find(self._scope.scoped(flt), _proj(projection), **kw)

    async def count(self, flt: Optional[Mapping] = None) -> int:
        return await self._raw.count_documents(self._scope.scoped(flt))

    async def distinct(self, key: str, flt: Optional[Mapping] = None) -> List:
        return await self._raw.distinct(key, self._scope.scoped(flt))

    def aggregate(self, pipeline: List[Mapping]):
        """Aggregation restricted to the tenant; every join must be :meth:`TenantData.lookup`."""
        checked = self._scope._check_pipeline(list(pipeline))
        return self._raw.aggregate([{"$match": {TENANT_KEY: self._scope.org_id}}] + checked)

    # --------------------------------------------------------------- writes
    async def insert_one(self, doc: Dict):
        owner = doc.get(TENANT_KEY)
        if owner is None:
            doc[TENANT_KEY] = self._scope.org_id
        elif owner != self._scope.org_id:
            raise TenantScopeViolation("insert into another tenant refused")
        return await self._raw.insert_one(doc)

    async def insert_many(self, docs: List[Dict]):
        for doc in docs:
            owner = doc.get(TENANT_KEY)
            if owner is None:
                doc[TENANT_KEY] = self._scope.org_id
            elif owner != self._scope.org_id:
                raise TenantScopeViolation("insert into another tenant refused")
        return await self._raw.insert_many(docs)

    async def update_one(self, flt: Mapping, update: Mapping, **kw):
        return await self._raw.update_one(self._scope.scoped(flt), update, **kw)

    async def update_many(self, flt: Mapping, update: Mapping, **kw):
        return await self._raw.update_many(self._scope.scoped(flt), update, **kw)

    async def delete_one(self, flt: Mapping):
        return await self._raw.delete_one(self._scope.scoped(flt))

    async def find_one_and_update(self, flt: Mapping, update: Mapping, **kw):
        return await self._raw.find_one_and_update(self._scope.scoped(flt), update, **kw)


class TenantData:
    """The request's tenant-bound view of the legacy database.

    Build it with one of the ``for_*`` constructors; never from a caller value.
    """

    def __init__(self, db, org_id: str):
        self._db = db
        self.org_id = _tenant_value(org_id)

    # --------------------------------------------------------- constructors
    @classmethod
    def for_user(cls, db, user: Mapping) -> "TenantData":
        """The session user's tenant (``get_current_user`` loaded it server-side)."""
        if not user:
            raise TenantScopeViolation("no authenticated session")
        return cls(db, user.get(TENANT_KEY))

    @classmethod
    def for_context(cls, db, ctx) -> "TenantData":
        """A W0-01 ``TenantContext`` (or the off/shadow ``LegacyCompatContext``)."""
        return cls(db, ctx.org_id)

    @classmethod
    def for_owner_of(cls, db, record: Mapping) -> "TenantData":
        """The tenant of a record that a server-side secret (a public review
        token) already resolved. The record's own ``org_id`` — never a caller value."""
        if not record:
            raise TenantScopeViolation("no owning record")
        return cls(db, record.get(TENANT_KEY))

    # ----------------------------------------------------------- accessors
    def collection(self, name: str) -> TenantCollection:
        if not isinstance(name, str) or not name or name.startswith("system."):
            raise TenantScopeViolation("invalid collection")
        return TenantCollection(self, name)

    def __getattr__(self, item: str) -> TenantCollection:
        # tenant.projects, tenant.invoices, ... — plain collection names only
        if item.startswith("_"):
            raise AttributeError(item)
        return self.collection(item)

    def entity(self, entity: str) -> TenantCollection:
        try:
            return self.collection(ENTITY_COLLECTIONS[entity])
        except KeyError:
            raise TenantScopeViolation("unknown entity %r" % entity) from None

    async def own_organization(self, projection: Optional[Mapping] = None) -> Optional[Dict]:
        """The tenant's own ``organizations`` record (its ``id`` IS the tenant key)."""
        return await self._db["organizations"].find_one({"id": self.org_id}, _proj(projection))

    # ------------------------------------------------------------- filters
    def scoped(self, flt: Optional[Mapping] = None) -> Dict[str, Any]:
        """``flt`` restricted to this tenant. A different tenant in ``flt`` is refused."""
        out = dict(flt or {})
        for key in (TENANT_KEY, "tenant_id"):
            if key in out and out[key] != self.org_id:
                raise TenantScopeViolation("filter names another tenant")
        out[TENANT_KEY] = self.org_id
        return out

    def lookup(self, collection: str, local_field: str, as_field: str,
               foreign_field: str = "id") -> List[Dict]:
        """A tenant-scoped join: ``$lookup`` + ``$filter`` of the joined array.

        The ``$filter`` runs immediately after the ``$lookup``, before any
        ``$unwind``/``$match``/``$project`` could read the joined documents,
        so a foreign document never reaches a later stage.
        """
        stage = _ScopedLookup({"$lookup": {"from": collection, "localField": local_field,
                                           "foreignField": foreign_field, "as": as_field}})
        flt = _ScopedLookupFilter({"$addFields": {as_field: {"$filter": {
            "input": "$" + as_field, "as": "joined",
            "cond": {"$eq": ["$$joined." + TENANT_KEY, self.org_id]}}}}})
        return [stage, flt]

    def _check_pipeline(self, pipeline: List[Mapping]) -> List[Mapping]:
        for i, stage in enumerate(pipeline):
            if not isinstance(stage, Mapping):
                raise TenantScopeViolation("invalid pipeline stage")
            for op in _FORBIDDEN_STAGES:
                if op in stage:
                    raise TenantScopeViolation("%s is not allowed in a tenant pipeline" % op)
            if "$lookup" in stage:
                nxt = pipeline[i + 1] if i + 1 < len(pipeline) else None
                as_field = stage["$lookup"].get("as")
                if not (isinstance(stage, _ScopedLookup) and isinstance(nxt, _ScopedLookupFilter)
                        and as_field in nxt["$addFields"]
                        and nxt["$addFields"][as_field]["$filter"]["cond"]["$eq"][1] == self.org_id):
                    raise TenantScopeViolation("unscoped $lookup refused; use TenantData.lookup")
            if "$facet" in stage:
                for sub in stage["$facet"].values():
                    self._check_pipeline(list(sub))
        return pipeline


# ------------------------------------------------------------------ ownerless rows
async def count_ownerless(db, collection: str) -> int:
    """How many documents of a legacy collection carry NO tenant key at all.

    W0-03E data-quality figure for the migration dry run. It is deliberately not
    tenant-scoped — and therefore discloses nothing about any tenant: a document
    counted here belongs to none (``org_id`` null or missing). Counting OTHER
    tenants' documents is exactly what W0-03E/C03 removed.
    """
    return await db[collection].count_documents({"$or": [{TENANT_KEY: None},
                                                         {TENANT_KEY: {"$exists": False}}]})


# ------------------------------------------------------------------ public token
async def resolve_review_token(db, token: Any, projection: Optional[Mapping] = None):
    """``(tenant, offer)`` for a public offer-review token; ``(None, None)`` otherwise.

    The token is the only key of an unauthenticated link, so this is the one
    deliberate cross-tenant read: it looks for exactly ONE offer carrying the
    token. No token, an owner-less offer or a token shared by two offers (two
    tenants, or a corrupt copy) resolves to nothing — fail closed, never the
    first match. The tenant of everything read afterwards is that offer's org.
    """
    if not isinstance(token, str) or not token:
        return None, None
    proj = _proj(projection)
    docs = await db["offers"].find({"review_token": token}, proj).limit(2).to_list(2)
    if len(docs) != 1 or not isinstance(docs[0].get(TENANT_KEY), str) or not docs[0][TENANT_KEY]:
        return None, None
    return TenantData.for_owner_of(db, docs[0]), docs[0]


# ------------------------------------------------------------------ project team
# ``project_team`` rows carry no tenant key (legacy schema: project_id, user_id,
# role_in_project, active). A row is honoured only when its project exists in
# the request's tenant; a row whose project id resolves only in another tenant
# grants nothing. Residual (documented, W0-03E_LEGACY_MIGRATION.md §14): when
# BOTH the user id and the project id collide across tenants in one shared
# legacy database, the row itself cannot say which tenant wrote it — that needs
# an ``org_id`` backfill on ``project_team`` (a migration decision). It affects
# only which of the caller's OWN tenant's projects a SiteManager may see; every
# record read after it is tenant-scoped.

async def assigned_project_ids(tenant: TenantData, user: Mapping) -> List[str]:
    """Active team assignments of the session user, limited to the tenant's projects."""
    rows = await tenant._db["project_team"].find(
        {"user_id": user["id"], "active": True}, {"_id": 0, "project_id": 1}).to_list(1000)
    ids = [r["project_id"] for r in rows if r.get("project_id")]
    own = await tenant.projects.get_many(ids, {"_id": 0, "id": 1})
    return [i for i in ids if i in own]


async def is_project_member(tenant: TenantData, user: Mapping, project_id: Any,
                            role_in_project: Optional[str] = None) -> bool:
    """An active team row for this user on a project that exists in the tenant."""
    if not await tenant.projects.get(project_id, {"_id": 0, "id": 1}):
        return False
    flt: Dict[str, Any] = {"project_id": project_id, "user_id": user["id"], "active": True}
    if role_in_project:
        flt["role_in_project"] = role_in_project
    return await tenant._db["project_team"].find_one(flt, {"_id": 1}) is not None


def _proj(projection: Optional[Mapping]) -> Optional[Dict]:
    return dict(projection) if projection is not None else None
