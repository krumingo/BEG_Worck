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

    async def count_documents(self, flt: Optional[Mapping] = None) -> int:
        """The motor name, so a converted call site reads like the original."""
        return await self.count(flt)

    async def distinct(self, key: str, flt: Optional[Mapping] = None) -> List:
        return await self._raw.distinct(key, self._scope.scoped(flt))

    def aggregate(self, pipeline: List[Mapping]):
        """Aggregation restricted to the tenant; every join must be :meth:`TenantData.lookup`."""
        checked = self._scope._check_pipeline(list(pipeline))
        return self._raw.aggregate([{"$match": {TENANT_KEY: self._scope.org_id}}] + checked)

    # --------------------------------------------------------------- writes
    async def insert_one(self, doc: Dict, **kw):
        """Scoped insert. ``**kw`` reaches the driver unchanged, exactly as it
        already does on :meth:`update_one` and :meth:`find_one`, so a caller
        that runs inside a multi-document transaction can pass its ``session``
        without leaving this layer for the raw handle. The tenant stamp is
        applied first and is not something a keyword can switch off."""
        return await self._raw.insert_one(self._own(doc), **kw)

    async def insert_many(self, docs: List[Dict], **kw):
        return await self._raw.insert_many([self._own(d) for d in docs], **kw)

    async def update_one(self, flt: Mapping, update: Mapping, **kw):
        return await self._raw.update_one(self._scope.scoped(flt), update, **kw)

    async def update_many(self, flt: Mapping, update: Mapping, **kw):
        return await self._raw.update_many(self._scope.scoped(flt), update, **kw)

    async def delete_one(self, flt: Mapping):
        return await self._raw.delete_one(self._scope.scoped(flt))

    async def delete_many(self, flt: Optional[Mapping] = None):
        """W0-03E-A2C: a scoped bulk delete. An empty filter deletes only THIS
        tenant's documents, never the collection."""
        return await self._raw.delete_many(self._scope.scoped(flt))

    async def find_one_and_update(self, flt: Mapping, update: Mapping, **kw):
        return await self._raw.find_one_and_update(self._scope.scoped(flt), update, **kw)

    async def find_one_and_delete(self, flt: Mapping, **kw):
        return await self._raw.find_one_and_delete(self._scope.scoped(flt), **kw)

    async def replace_one(self, flt: Mapping, replacement: Dict, **kw):
        """Scoped replace. The replacement document is stamped with this tenant,
        and one that names another tenant is refused — a replace rewrites the
        whole document, so an absent owner would silently unbind the record."""
        return await self._raw.replace_one(self._scope.scoped(flt),
                                           self._own(replacement), **kw)

    async def find_one_and_replace(self, flt: Mapping, replacement: Dict, **kw):
        return await self._raw.find_one_and_replace(self._scope.scoped(flt),
                                                     self._own(replacement), **kw)

    def _own(self, doc: Dict) -> Dict:
        """``doc`` with this tenant stamped; a foreign owner is refused."""
        owner = doc.get(TENANT_KEY)
        if owner is None:
            doc[TENANT_KEY] = self._scope.org_id
        elif owner != self._scope.org_id:
            raise TenantScopeViolation("write into another tenant refused")
        return doc


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
    def for_resolved_org(cls, db, org_id: Any) -> "TenantData":
        """A tenant whose ``org_id`` a caller in the server has ALREADY resolved.

        For module-level helpers that a route hands its own
        ``user["org_id"]``/``ctx.org_id`` down to (the A1 ``HELPER_MODULES``
        tier) and that therefore never see the session document themselves.
        The value is server-side state travelling down a call chain, not a
        request field: the guard's ``A1-CALLERTENANT`` rule still rejects a
        route that feeds a caller-controlled parameter into any ``for_*``
        constructor, and an empty/absent org still fails closed here.
        """
        return cls(db, org_id)

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

    def audit_store_db(self):
        """The database handle of THIS tenant's records, for the W0-04 audit store.

        W0-06A. The canonical AuditEvent store (``app.audit.store``) is not a
        tenant-owned collection in the sense this class scopes: it keys on
        ``tenant_id``, maintains its own per-tenant hash chain, and must be
        appended to with the raw handle rather than through a view that would
        stamp ``org_id`` onto an audit document. What it does require is that an
        event lands in the SAME database as the business write it describes —
        the rule ``app/permissions/audit_hooks.py`` already follows, so that a
        legacy-database write is never chained into another database's history.

        This accessor is that handle, named for its one use. It returns a
        database, not a collection, so it cannot become a way to reach a
        tenant-owned collection unscoped; callers pass it straight to
        ``record_event``, which scopes by ``tenant_id`` itself.
        """
        return self._db

    def deployment_db(self):
        """The database handle for DEPLOYMENT-level work on this tenant's database.

        W0-06C. Two things cannot be expressed through a collection view and are
        not reads or writes of tenant data at all:

        * **readiness** — whether this deployment is a replica set / mongos and
          whether the required unique indexes exist. Both are properties of the
          server and of the collection's schema, answered by ``db.command`` and
          ``index_information``; neither returns a tenant document.
        * **a session** — a multi-document transaction is opened on the CLIENT
          of this database, so several of this tenant's own collections (its
          monitor claim row, its finding, its run document and its audit chain)
          can commit together or not at all.

        Like :meth:`audit_store_db` it returns a database, not a collection, so
        it cannot become a way to read a tenant-owned collection unscoped: every
        document read or written inside such a transaction still goes through a
        :class:`TenantCollection` of this view, which adds the tenant predicate
        and stamps the owner exactly as it does outside one.
        """
        return self._db

    async def update_own_organization(self, update: Mapping, **kw):
        """Update the tenant's OWN ``organizations`` row — W0-03E-A2C.

        The filter is this tenant's id, which for the tenant root IS the tenant
        key, so the write cannot reach another organization's row. Routes that
        edit organization settings (payroll week, asset-intake roles,
        workers-see-pay, company profile) call this instead of
        ``db.organizations.update_one({"id": <a variable>}, ...)``.
        """
        return await self._db["organizations"].update_one({"id": self.org_id}, update, **kw)

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


async def count_integer_key_health(db, collection: str, field: str) -> Dict[str, int]:
    """``{"rows": N, "non_integer": M}`` — a DEPLOYMENT readiness figure.

    W0-06C. The integrity monitor's whole cross-process exclusion rests on a
    monotonically increasing INTEGER fence token on each tenant's claim row: a
    row whose fence is missing or is not an integer cannot be compared, so the
    runner must refuse to start against that database. Answering that question
    is not a tenant read — it is a schema-health check over the whole
    collection, which no :class:`TenantData` can express, and running it per
    tenant would be both wrong (one bad row anywhere voids the guarantee) and a
    way to enumerate tenants.

    Like :func:`count_ownerless` it is therefore deliberately not tenant-scoped
    and deliberately discloses nothing: it returns two COUNTS. No document, no
    ``_id``, no tenant id and no field value leaves this function, so it cannot
    become a way to read another tenant's records.
    """
    rows = await db[collection].count_documents({})
    # ``$nor`` of the two BSON integer types rather than ``$not`` of a list of
    # them: it counts an absent field and a non-integer value alike, it keeps
    # ``true`` out (BSON ``bool`` is not ``int``), and it is the one spelling
    # that behaves identically on a real server and in the test double.
    non_integer = await db[collection].count_documents(
        {"$nor": [{field: {"$type": "int"}}, {field: {"$type": "long"}}]})
    return {"rows": int(rows), "non_integer": int(non_integer)}


# ------------------------------------------------------------------ all tenants
async def all_tenant_ids(db, limit: Optional[int] = None) -> List[str]:
    """Every tenant's ``org_id`` — the ONE deliberate platform-level enumeration.

    W0-03E-A2C. A scheduled job (``app/routes/attendance.py::run_reminder_jobs``)
    has to visit every tenant in turn, which no :class:`TenantData` can express:
    a tenant view is one tenant by construction. Rather than leave a raw
    ``db.organizations.find({})`` in a route — indistinguishable, to a reader or
    to the static guard, from the cross-tenant reads W0-03E removed — the
    enumeration lives here, named for what it is, and returns ONLY tenant ids.

    It discloses no tenant's business data: the caller gets identifiers and must
    then build that tenant's own :meth:`TenantData.for_resolved_org` view to read
    anything. Callers are therefore auditable by searching for this one name.
    """
    cursor = db["organizations"].find({}, {"_id": 0, "id": 1})
    docs = await cursor.to_list(limit)
    return [d["id"] for d in docs if isinstance(d.get("id"), str) and d["id"]]


# ------------------------------------------------------------------ public token
async def resolve_owner_by_unique_key(db, collection: str, key: str, value: Any,
                                      projection: Optional[Mapping] = None):
    """``(tenant, doc)`` for a record named by a GLOBALLY UNIQUE EXTERNAL key.

    W0-03E-A2C. Some records are reached by an identifier this installation did
    not mint and no request can guess: a public offer review token, a Stripe
    subscription or customer id. The caller has no session, so there is no tenant
    yet — the record itself is what says which tenant this is about.

    Fail closed, never first-match: the key must select EXACTLY ONE document that
    carries a usable owner. No value, an owner-less row, or two rows sharing the
    key (two tenants, or a corrupt copy) resolves to ``(None, None)``. Everything
    read or written afterwards goes through the returned tenant's view, so one
    external callback can only ever touch the tenant that owns the record.
    """
    if value in (None, ""):
        return None, None
    proj = _proj(projection)
    docs = await db[collection].find({key: value}, proj).limit(2).to_list(2)
    if len(docs) != 1 or not isinstance(docs[0].get(TENANT_KEY), str) or not docs[0][TENANT_KEY]:
        return None, None
    return TenantData.for_owner_of(db, docs[0]), docs[0]


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
# W0-03E-A2: ``project_team`` is a tenant-bound AUTHORIZATION relation, owned by
# ``app.tenancy.project_team``. A1 honoured a row whose *project* resolved in the
# caller's tenant, which the A1 review broke: with one shared legacy database, a
# project id and a user id colliding across tenants let a row written by B
# authorize A, because an ownerless row cannot say who wrote it. Both helpers
# below now carry the tenant predicate on the row itself, so an ownerless or
# foreign row matches nothing. They stay here as the A1 entry points the
# protected modules already call; the rule lives in one place.


async def assigned_project_ids(tenant: TenantData, user: Mapping) -> List[str]:
    """The tenant's projects the session user is actively assigned to.

    Tenant-scoped on the membership row AND on the project: an ownerless or
    another tenant's row grants nothing.
    """
    from app.tenancy import project_team
    return await project_team.assigned_project_ids(tenant, (user or {}).get("id"))


async def is_project_member(tenant: TenantData, user: Mapping, project_id: Any,
                            role_in_project: Optional[str] = None) -> bool:
    """An active team row of THIS tenant for this user on one of its projects."""
    from app.tenancy import project_team
    return await project_team.is_member(tenant, (user or {}).get("id"), project_id,
                                        role_in_project)


def _proj(projection: Optional[Mapping]) -> Optional[Dict]:
    return dict(projection) if projection is not None else None
