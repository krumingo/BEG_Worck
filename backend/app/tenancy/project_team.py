"""
W0-03E-A2 — ``project_team`` as a tenant-bound authorization relation.

Why it exists. A1 built the one tenant-safe access layer for identity-bearing
records (``app.tenancy.data_access``) and left ``project_team`` as a documented
residual: the legacy rows carry no tenant key, so A1 honoured a row whenever
its *project* resolved inside the caller's tenant. The A1 review reproduced the
hole that leaves: with ONE shared legacy database holding tenants A and B, a
project id ``p1`` present in both and a user id ``u1`` present in both, a team
row written by **B** — the only team row in the database — made
``assigned_project_ids()`` return ``['p1']`` and
``is_project_member(..., 'p1', 'SiteManager')`` return ``True`` for A's user.
Resolving the project in A *after* reading an ownerless row never establishes
who wrote that row.

The rule this module implements (W0-03E-A2 assignment, TENANCY_MODEL.md §2/§6
D-15, CLAUDE.md §3):

* ``project_team`` is an **authorization relation**, so it is tenant-bound like
  every other operational record: each row carries ``org_id``.
* A new row is stamped with the **server-resolved active tenant** only — the
  ``TenantData`` the caller was built from. A tenant value from a path, query,
  form or JSON body is never an input (that is already enforced one layer down
  by :meth:`TenantData.scoped` / :meth:`TenantCollection.insert_one`).
* Every authorization read carries ``org_id`` **and** ``project_id`` **and**
  ``user_id`` (plus ``role_in_project`` where a role decides), never an id pair
  alone. ``_require`` below refuses a call that is missing one.
* An **ownerless** row (no ``org_id``) and a **foreign** row (another tenant's
  ``org_id``) grant exactly zero authorization: the tenant predicate simply
  does not match them. There is no global, name, role or id inference, and no
  "the project exists here, so the row must be ours" fallback.
* The project is still required to exist in the tenant, so a row that survives
  the tenant predicate but points at a project the tenant does not own grants
  nothing either. Two independent fail-closed checks, not one.

Every read and write goes through the A1 :class:`TenantData` collection view,
so this module adds no second access path: ``scoped()`` appends the tenant
predicate last and refuses a filter naming another tenant, and ``insert_one``
stamps the tenant and refuses a foreign owner.

Legacy rows that predate the tenant key are classified, never guessed:
``scripts/w0_03e_a2_project_team_provenance.py`` is the read-only dry run and
``PROVENANCE_*`` below are the only two outcomes. An ``UNRESOLVED_PROVENANCE``
row stays ownerless and therefore stays unauthorized — fail closed — until a
human resolves it.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.tenancy.data_access import TENANT_KEY, TenantData, TenantScopeViolation

#: The legacy collection this module owns. Nothing else may query it for
#: authorization (``scripts/w0_03e_a1_tenant_access_guard.py``, A2-TEAM).
COLLECTION = "project_team"

#: The role that may manage a project from a membership row (legacy value).
ROLE_SITE_MANAGER = "SiteManager"

#: Provenance of a legacy row, decided by the dry run — never by this module.
#: ``PROVEN_TENANT``: the row's source database is provably single-tenant and
#: verified against the Tenant Registry, so the row belongs to that tenant.
#: ``UNRESOLVED_PROVENANCE``: shared, unknown or contradictory source. It
#: carries no tenant, authorizes nothing, and waits for a human decision.
PROVENANCE_PROVEN = "PROVEN_TENANT"
PROVENANCE_UNRESOLVED = "UNRESOLVED_PROVENANCE"
PROVENANCE_OUTCOMES = (PROVENANCE_PROVEN, PROVENANCE_UNRESOLVED)


class ProjectTeamAuthorizationIncomplete(TenantScopeViolation):
    """An authorization query was missing the tenant, the project or the user.

    A programming error, raised before the database is touched: a membership
    question answered from fewer keys than these is the A1 defect.
    """


def _rel(tenant: TenantData):
    """The tenant's view of the relation (A1 layer; applies the tenant predicate)."""
    if not isinstance(tenant, TenantData):
        raise ProjectTeamAuthorizationIncomplete(
            "project_team needs a server-resolved TenantData, got %r" % type(tenant).__name__)
    return tenant.collection(COLLECTION)


def _ident(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectTeamAuthorizationIncomplete(
            "a project_team authorization query needs a concrete %s" % what)
    return value


def membership_filter(user_id: Any, project_id: Any,
                      role_in_project: Optional[str] = None,
                      active: bool = True) -> Dict[str, Any]:
    """The only shape an authorization query may have: user AND project (AND role).

    The tenant key is NOT added here — :meth:`TenantData.scoped` appends it
    last, so a caller can neither forget it nor override it.
    """
    flt: Dict[str, Any] = {"project_id": _ident(project_id, "project_id"),
                           "user_id": _ident(user_id, "user_id")}
    if active:
        flt["active"] = True
    if role_in_project:
        flt["role_in_project"] = role_in_project
    return flt


# --------------------------------------------------------------------- reads
async def member_row(tenant: TenantData, user_id: Any, project_id: Any,
                     role_in_project: Optional[str] = None,
                     projection: Optional[Mapping] = None) -> Optional[Dict]:
    """This tenant's active membership row for (user, project[, role]), or ``None``.

    ``None`` for an ownerless row, a foreign row, and for a project the tenant
    does not own. Never a row the tenant cannot prove is its own.
    """
    # Validate the tenant and the keys BEFORE any read: a membership question
    # missing one of them is a programming error and must be a refusal, never
    # an accidental answer. Only then is the project resolved in the tenant.
    rel = _rel(tenant)
    flt = membership_filter(user_id, project_id, role_in_project)
    if not await tenant.projects.get(project_id, {"_id": 0, "id": 1}):
        return None
    return await rel.find_one(flt, projection if projection is not None else {"_id": 0})


async def is_member(tenant: TenantData, user_id: Any, project_id: Any,
                    role_in_project: Optional[str] = None) -> bool:
    """Is (user, project[, role]) an active membership of THIS tenant?"""
    return await member_row(tenant, user_id, project_id, role_in_project,
                            {"_id": 1}) is not None


async def assigned_project_ids(tenant: TenantData, user_id: Any,
                               role_in_project: Optional[str] = None,
                               limit: int = 1000) -> List[str]:
    """The tenant's projects this user is actively assigned to.

    The inverse of :func:`is_member`: the project id is what is being asked
    for, so it cannot be an input. Both fail-closed checks still apply — the
    rows are read with the tenant predicate, and every id is then confirmed to
    be a project of this tenant. Order is the row order, de-duplicated.
    """
    rel = _rel(tenant)
    flt: Dict[str, Any] = {"user_id": _ident(user_id, "user_id"), "active": True}
    if role_in_project:
        flt["role_in_project"] = role_in_project
    rows = await rel.find(flt, {"_id": 0, "project_id": 1}).to_list(limit)
    seen, ids = set(), []
    for row in rows:
        pid = row.get("project_id")
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)
    own = await tenant.projects.get_many(ids, {"_id": 0, "id": 1})
    return [i for i in ids if i in own]


async def managed_project_ids(tenant: TenantData, user_id: Any,
                              limit: int = 1000) -> List[str]:
    """The tenant's projects this user manages (``SiteManager`` membership)."""
    return await assigned_project_ids(tenant, user_id, ROLE_SITE_MANAGER, limit)


async def project_rows(tenant: TenantData, project_ids: Iterable[Any],
                       projection: Optional[Mapping] = None,
                       active_only: bool = True, limit: int = 1000,
                       user_ids: Optional[Iterable[Any]] = None) -> List[Dict]:
    """The tenant's membership rows of these projects (roster read, not a gate).

    The caller has already been authorized for the projects; this returns WHO
    is on them. Tenant-scoped all the same, so another tenant's row is never
    listed in this tenant's roster, and every project is confirmed to be the
    tenant's own.

    ``active_only=False`` keeps the historical rows too, for a caller whose
    legacy query had no ``active`` predicate — the tenant predicate is added
    either way. ``user_ids`` narrows the roster server-side, so a caller that
    wants only some members does not have to read ``limit`` rows first and
    filter them in Python (which would change WHICH rows the limit cuts off).
    """
    rel = _rel(tenant)
    wanted = [p for p in dict.fromkeys(project_ids) if p]
    if not wanted:
        return []
    own = await tenant.projects.get_many(wanted, {"_id": 0, "id": 1})
    mine = [p for p in wanted if p in own]
    if not mine:
        return []
    flt: Dict[str, Any] = {"project_id": {"$in": mine}}
    if active_only:
        flt["active"] = True
    if user_ids is not None:
        users = [u for u in dict.fromkeys(user_ids) if u]
        if not users:
            return []
        flt["user_id"] = {"$in": users}
    return await rel.find(
        flt, projection if projection is not None else {"_id": 0}).to_list(limit)


async def user_rows(tenant: TenantData, user_id: Any,
                    projection: Optional[Mapping] = None,
                    active_only: bool = True, limit: int = 1000) -> List[Dict]:
    """This tenant's membership rows of one user (assignment history read).

    Tenant-scoped on the row, which is what makes an ownerless or foreign row
    invisible. Unlike :func:`assigned_project_ids` it does NOT drop a row whose
    project is gone, because its callers render the assignment history and
    resolve each project themselves.
    """
    rel = _rel(tenant)
    flt: Dict[str, Any] = {"user_id": _ident(user_id, "user_id")}
    if active_only:
        flt["active"] = True
    return await rel.find(
        flt, projection if projection is not None else {"_id": 0}).to_list(limit)


async def project_member_ids(tenant: TenantData, project_id: Any,
                             active_only: bool = True, limit: int = 1000) -> List[str]:
    """The user ids on one of the tenant's projects, de-duplicated, in row order."""
    rows = await project_rows(tenant, [project_id], {"_id": 0, "user_id": 1},
                              active_only=active_only, limit=limit)
    out: List[str] = []
    for row in rows:
        uid = row.get("user_id")
        if uid and uid not in out:
            out.append(uid)
    return out


async def active_member_count(tenant: TenantData, project_id: Any) -> int:
    """How many active members the tenant's project has; 0 for a foreign project."""
    rel = _rel(tenant)
    pid = _ident(project_id, "project_id")
    if not await tenant.projects.get(pid, {"_id": 0, "id": 1}):
        return 0
    return await rel.count({"project_id": pid, "active": True})


async def tenant_active_rows(tenant: TenantData, projection: Optional[Mapping] = None,
                             limit: Optional[int] = None) -> List[Dict]:
    """Every active membership row of THIS tenant (W0-03E-A2B, W0-02 bootstrap).

    The permission bootstrap derives project-scope RoleAssignments from
    memberships. It reads them here — tenant predicate applied by the A1 layer —
    so a row of another tenant, or an ownerless row, is never an input to a
    permission. Not an authorization answer by itself.
    """
    return await _rel(tenant).find(
        {"active": True}, projection if projection is not None else {"_id": 0}).to_list(limit)


async def ownerless_row_count(db) -> int:
    """How many rows carry NO tenant at all (missing / ``null`` / ``""``).

    A data-quality figure, deliberately not tenant-scoped and therefore
    disclosing nothing about any tenant: a row counted here belongs to none.
    After the W0-03E-A2B backfill it must be zero; a consumer that derives
    authorization from memberships (the W0-02 bootstrap) refuses to run while
    it is not.
    """
    from app.tenancy.ownership import ownerless_predicate
    return await db[COLLECTION].count_documents(ownerless_predicate(TENANT_KEY))


async def row_by_id(tenant: TenantData, member_id: Any, project_id: Any,
                    projection: Optional[Mapping] = None) -> Optional[Dict]:
    """One membership row of this tenant by its own id, within one project."""
    return await _rel(tenant).find_one(
        {"id": _ident(member_id, "member_id"), "project_id": _ident(project_id, "project_id")},
        projection if projection is not None else {"_id": 0})


# -------------------------------------------------------------------- writes
def build_row(tenant: TenantData, *, member_id: str, project_id: str, user_id: str,
              role_in_project: str, active: bool = True,
              from_date: Any = None, to_date: Any = None,
              extra: Optional[Mapping] = None) -> Dict[str, Any]:
    """A new membership row stamped with the server-resolved active tenant.

    ``extra`` may not carry a tenant key: the stamp is the request's tenant,
    not something a caller can supply (a body value reaching this would be the
    override A2 forbids).
    """
    row: Dict[str, Any] = {
        "id": _ident(member_id, "member id"),
        "project_id": _ident(project_id, "project_id"),
        "user_id": _ident(user_id, "user_id"),
        "role_in_project": role_in_project,
        "active": bool(active),
        "from_date": from_date,
        "to_date": to_date,
    }
    for key, value in dict(extra or {}).items():
        if key in (TENANT_KEY, "tenant_id"):
            raise TenantScopeViolation(
                "a project_team row takes its tenant from the server-resolved "
                "session, never from the caller")
        row[key] = value
    row[TENANT_KEY] = tenant.org_id
    return row


async def add_member(tenant: TenantData, *, member_id: str, project_id: str, user_id: str,
                     role_in_project: str, active: bool = True,
                     from_date: Any = None, to_date: Any = None,
                     extra: Optional[Mapping] = None) -> Dict[str, Any]:
    """Insert one membership row into THIS tenant. The caller checks permission first.

    The project must be the tenant's own, so a membership can never be created
    against another tenant's project even when the ids collide.
    """
    rel = _rel(tenant)
    if not await tenant.projects.get(_ident(project_id, "project_id"), {"_id": 0, "id": 1}):
        raise TenantScopeViolation("cannot add a member to a project of another tenant")
    row = build_row(tenant, member_id=member_id, project_id=project_id, user_id=user_id,
                    role_in_project=role_in_project, active=active,
                    from_date=from_date, to_date=to_date, extra=extra)
    await rel.insert_one(dict(row))
    return row


async def deactivate_member(tenant: TenantData, *, member_id: str, project_id: str):
    """Deactivate one of the tenant's own rows (``active=False``; never a delete)."""
    return await _rel(tenant).update_one(
        {"id": _ident(member_id, "member id"), "project_id": _ident(project_id, "project_id")},
        {"$set": {"active": False}})


async def deactivate_project(tenant: TenantData, project_id: str):
    """Deactivate every membership of one of the tenant's projects."""
    return await _rel(tenant).update_many(
        {"project_id": _ident(project_id, "project_id")}, {"$set": {"active": False}})


# -------------------------------------------------------------- provenance
# The legacy rows predate the tenant key. A2 decides each one by PROVEN SOURCE
# or not at all: no inference from a project id, a user id, a name, a role or a
# coincident record, because two tenants in one shared legacy database can have
# all of those equal — that is exactly the collision the A1 review reproduced.
#
# The only evidence accepted for a deterministic backfill is that the row's
# SOURCE DATABASE is provably single-tenant, verified against the W0-01 Tenant
# Registry. All three conditions must hold:
#
#   1. exactly ONE registry tenant maps to that database (``database_name``);
#   2. the database's own tenant-keyed records carry exactly ONE distinct
#      non-empty ``org_id``;
#   3. that observed ``org_id`` IS the registry tenant's legacy org.
#
# A shared database, an unknown database, a database no registry record claims,
# a database two records claim, or any contradiction between (2) and (3) leaves
# every ownerless row UNRESOLVED_PROVENANCE. An UNRESOLVED row keeps no tenant,
# so the tenant predicate never matches it and it authorizes nothing — fail
# closed while a human decides.


class SourceProvenance:
    """Verdict on ONE source database: provably single-tenant, or not.

    Pure value object. ``reason`` is a machine-readable code; ``detail`` is the
    human sentence the dry-run report prints.
    """

    def __init__(self, database: str, org_id: Optional[str] = None,
                 reason: str = "", detail: str = "",
                 registry_org_ids: Iterable[str] = (),
                 observed_org_ids: Iterable[str] = ()):
        self.database = database
        self.org_id = org_id
        self.reason = reason
        self.detail = detail
        self.registry_org_ids = sorted(set(registry_org_ids))
        self.observed_org_ids = sorted(set(observed_org_ids))

    @property
    def proven(self) -> bool:
        """True only for a verified single-tenant source. Never a default."""
        return bool(self.org_id) and self.reason == "SINGLE_TENANT_SOURCE_VERIFIED"

    def as_dict(self) -> Dict[str, Any]:
        return {"database": self.database, "proven": self.proven, "org_id": self.org_id,
                "reason": self.reason, "detail": self.detail,
                "registry_org_ids": self.registry_org_ids,
                "observed_org_ids": self.observed_org_ids}


def verify_source_provenance(database: str, registry_tenants: Iterable[Mapping],
                             observed_org_ids: Iterable[Any]) -> SourceProvenance:
    """Is ``database`` a provably single-tenant source? Pure; reads nothing.

    ``registry_tenants`` are the Tenant Registry records that name this
    database; ``observed_org_ids`` are the distinct non-empty ``org_id`` values
    actually present in that database's tenant-keyed collections.
    """
    claims = [t for t in registry_tenants if t]
    reg_orgs = [str(t.get("legacy_org_id") or t.get("id")) for t in claims
                if (t.get("legacy_org_id") or t.get("id"))]
    observed = sorted({o for o in observed_org_ids if isinstance(o, str) and o})

    def no(reason: str, detail: str) -> SourceProvenance:
        return SourceProvenance(database, None, reason, detail, reg_orgs, observed)

    if not claims:
        return no("NO_REGISTRY_RECORD",
                  "no Tenant Registry record names database %r, so its rows have no "
                  "proven owner" % database)
    if len(claims) > 1:
        return no("SHARED_SOURCE_DATABASE",
                  "%d Tenant Registry records name database %r; a shared source cannot "
                  "prove which tenant wrote a row" % (len(claims), database))
    if len(reg_orgs) != 1:
        return no("REGISTRY_ORG_UNRESOLVED",
                  "the Tenant Registry record for database %r has no usable legacy org"
                  % database)
    if len(observed) > 1:
        return no("MULTI_TENANT_DATA_IN_SOURCE",
                  "database %r holds records of %d tenants (%s); it is not a "
                  "single-tenant source" % (database, len(observed), ", ".join(observed)))
    if len(observed) == 1 and observed[0] != reg_orgs[0]:
        return no("REGISTRY_DATA_MISMATCH",
                  "database %r holds records of %r but the Tenant Registry maps it to "
                  "%r; contradictory provenance" % (database, observed[0], reg_orgs[0]))
    return SourceProvenance(database, reg_orgs[0], "SINGLE_TENANT_SOURCE_VERIFIED",
                            "database %r is claimed by exactly one Tenant Registry "
                            "record and holds only that tenant's records" % database,
                            reg_orgs, observed)


#: Why one row ended up where it did. Machine-readable; the report groups on it.
ROW_ALREADY_STAMPED = "ALREADY_STAMPED"
ROW_PROVEN_SINGLE_TENANT_SOURCE = "PROVEN_SINGLE_TENANT_SOURCE"
ROW_NO_PROVEN_SOURCE = "NO_PROVEN_SOURCE"
ROW_STAMP_CONFLICTS_WITH_SOURCE = "STAMP_CONFLICTS_WITH_SOURCE"


def classify_row(row: Mapping, provenance: SourceProvenance) -> Dict[str, Any]:
    """Classify ONE legacy ``project_team`` row. Pure; writes nothing.

    Returns ``{outcome, reason, org_id, backfill}``. ``outcome`` is one of
    :data:`PROVENANCE_OUTCOMES`. ``backfill`` is the ``org_id`` a migration
    would stamp, and is ``None`` unless the outcome is ``PROVEN_TENANT`` and
    the row is not already stamped — a row is never re-stamped silently.
    """
    current = row.get(TENANT_KEY)
    current = current if isinstance(current, str) and current else None

    if current:
        if provenance.proven and current != provenance.org_id:
            # The row claims a tenant its own source database cannot have
            # written. Fail closed: a contradiction is never resolved by
            # preferring one side of it.
            return {"outcome": PROVENANCE_UNRESOLVED,
                    "reason": ROW_STAMP_CONFLICTS_WITH_SOURCE,
                    "org_id": current, "backfill": None}
        return {"outcome": PROVENANCE_PROVEN, "reason": ROW_ALREADY_STAMPED,
                "org_id": current, "backfill": None}

    if provenance.proven:
        return {"outcome": PROVENANCE_PROVEN,
                "reason": ROW_PROVEN_SINGLE_TENANT_SOURCE,
                "org_id": provenance.org_id, "backfill": provenance.org_id}

    return {"outcome": PROVENANCE_UNRESOLVED, "reason": ROW_NO_PROVEN_SOURCE,
            "org_id": None, "backfill": None}


def classify_rows(rows: Iterable[Mapping],
                  provenance: SourceProvenance) -> Dict[str, Any]:
    """Deterministic counts and per-row decisions for a whole legacy collection.

    ``proven`` / ``unresolved`` / ``conflicting`` are the three figures the A2
    assignment asks the dry run to report. ``conflicting`` is a subset of
    ``unresolved``: a contradictory row is still refused authorization.
    """
    decisions, counts = [], {"total": 0, "stamped": 0, "proven": 0,
                             "unresolved": 0, "conflicting": 0, "backfillable": 0}
    reasons: Dict[str, int] = {}
    for row in rows:
        d = classify_row(row, provenance)
        counts["total"] += 1
        if d["reason"] == ROW_ALREADY_STAMPED:
            counts["stamped"] += 1
        if d["reason"] == ROW_STAMP_CONFLICTS_WITH_SOURCE:
            counts["conflicting"] += 1
        if d["outcome"] == PROVENANCE_PROVEN:
            counts["proven"] += 1
        else:
            counts["unresolved"] += 1
        if d["backfill"]:
            counts["backfillable"] += 1
        reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
        decisions.append({"id": row.get("id"), "project_id": row.get("project_id"),
                          "user_id": row.get("user_id"), **d})
    decisions.sort(key=lambda d: (str(d.get("id")), str(d.get("project_id")),
                                  str(d.get("user_id"))))
    return {"counts": counts, "reasons": reasons, "decisions": decisions,
            "provenance": provenance.as_dict()}


# ------------------------------------------------------------------ for_user
def tenant_for_org(db, org_id: Any) -> TenantData:
    """The tenant view for a helper that received an already-resolved ``org_id``.

    Used by the module-level reminder/roster helpers, which a route hands its
    own ``user["org_id"]`` down to. See :meth:`TenantData.for_resolved_org`.
    """
    return TenantData.for_resolved_org(db, org_id)


def tenant_for(db, user: Mapping) -> TenantData:
    """The session user's tenant view — the A1 constructor, for route helpers.

    ``user`` is the document ``get_current_user`` loaded server-side from the
    verified JWT user id, so its ``org_id`` is server-side state, not a caller
    value.
    """
    return TenantData.for_user(db, user)
