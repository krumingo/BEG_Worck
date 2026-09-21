"""
W0-03C — the planned per-tenant unique keys, and the read-only duplicate report that
must be clean before any of them is built.

Contract (docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md §6 "W0-03C"):

  * a read-only duplicate report on a restored copy is a **precondition** — without it
    no index is created;
  * building an index is **refused** while duplicates exist, and the refusal names the
    records that block it instead of trying a partial build;
  * alias mapping never merges; the report never merges, fixes or deletes anything.

This module is the single source of truth for *which* unique keys exist. The report
(here) and the bootstrap (``index_bootstrap.py``) both read ``CANONICAL_KEYS``, so the
report can never check a different key than the one the bootstrap would build.

Every key starts with ``tenant_id``: FLOW-032 and TENANCY_MODEL §6 make Master Data per
tenant, so two tenants may legitimately hold the same ЕИК, alias or tag name.

How a key is evaluated here mirrors how MongoDB builds a unique index:
  * only documents matching the partial filter take part;
  * an array field contributes one key per element (a multikey index), and the same key
    twice inside ONE document is not a duplicate;
  * a missing field would index as ``null`` — every key below either names a field that
    is always present or excludes documents without it in the partial filter.

Pure and stdlib-only on purpose: the same code runs in the backend, in the tests and on
the NAS against an export of a restored copy (``python:3.11-slim``, no network).
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.master_data.models import (
    ENTITY_ITEM,
    ENTITY_ORGANIZATION,
    ENTITY_PERSON,
    ENTITY_PHYSICAL_ASSET,
    ENTITY_TAG,
    ENTITY_TYPES,
    ENTITY_UNIT,
    IDENTIFIER_KINDS,
    STATUS_ACTIVE,
    identifier_key,
)
from app.master_data.normalize import NORMALIZATION_VERSION

REPORT_SCHEMA = "beg.master-data-duplicate-report/v1"
REPORT_SET_SCHEMA = "beg.master-data-duplicate-report-set/v1"
EXPORT_SCHEMA = "beg.master-data-uniqueness-export/v1"
INDEX_PREFIX = "md_uq_"

#: The pending-mapping queue (W0-03B2). Kept as literals so this module stays importable
#: without the service layer; ``test_w0_03c_uniqueness`` asserts they match pending.py.
PENDING_COLLECTION = "md_pending_mapping"
PENDING_STATUS_OPEN = "pending"

#: Identifier kinds that are personal data: the report never prints them in full.
SENSITIVE_KINDS = frozenset({"egn"})


def collection_for(entity_type: str) -> str:
    return "md_" + entity_type


def mask_value(kind: Optional[str], value: Any) -> Any:
    """Personal identifiers are shown as ``12****90`` — enough for a human to find the
    record, not enough to leak it through a report."""
    if kind not in SENSITIVE_KINDS or not isinstance(value, str):
        return value
    raw = value.split(":", 1)[1] if value.startswith(kind + ":") else value
    shown = raw[:2] + "****" + raw[-2:] if len(raw) > 4 else "****"
    return "%s:%s" % (kind, shown) if value.startswith(kind + ":") else shown


@dataclass(frozen=True)
class UniqueKey:
    """One planned unique index."""

    name: str
    collection: str
    fields: Tuple[str, ...]
    partial: Optional[Dict[str, Any]]
    description: str
    entity_type: Optional[str] = None
    sensitive_kind: Optional[str] = None

    def index_spec(self) -> Dict[str, Any]:
        spec: Dict[str, Any] = {"keys": [(f, 1) for f in self.fields], "name": self.name, "unique": True}
        if self.partial:
            spec["partialFilterExpression"] = self.partial
        return spec


def _canonical_keys() -> List[UniqueKey]:
    keys: List[UniqueKey] = []
    for entity_type in sorted(ENTITY_TYPES):
        coll = collection_for(entity_type)
        keys.append(UniqueKey(
            name=INDEX_PREFIX + "id", collection=coll, entity_type=entity_type,
            fields=("tenant_id", "id"), partial=None,
            description="the canonical id is never reused inside a tenant — merged and "
                        "archived records keep theirs (contract §5.2)"))
        keys.append(UniqueKey(
            name=INDEX_PREFIX + "alias", collection=coll, entity_type=entity_type,
            fields=("tenant_id", "aliases.normalized"),
            partial={"status": STATUS_ACTIVE, "aliases.normalized": {"$exists": True}},
            description="a confirmed spelling points at ONE active record — FLOW-032 reuses "
                        "an alias automatically, so it must be unambiguous"))
        if entity_type in (ENTITY_TAG, ENTITY_UNIT):
            keys.append(UniqueKey(
                name=INDEX_PREFIX + "name", collection=coll, entity_type=entity_type,
                fields=("tenant_id", "normalized_name"),
                partial={"status": STATUS_ACTIVE},
                description="for tags and units the name IS the identity (contract §5.1); "
                            "variants are aliases, not second records"))
        if entity_type in IDENTIFIER_KINDS:
            keys.append(UniqueKey(
                name=INDEX_PREFIX + "identifier", collection=coll, entity_type=entity_type,
                fields=("tenant_id", "identifiers.key"),
                partial={"status": STATUS_ACTIVE, "identifiers.key": {"$exists": True}},
                description="one active record per %s (FLOW-032: ЕИК/идентификатор е ключов "
                            "контрол срещу дублиране)" % "/".join(IDENTIFIER_KINDS[entity_type]),
                sensitive_kind="egn" if entity_type == ENTITY_PERSON else None))
    keys.append(UniqueKey(
        name=INDEX_PREFIX + "open_pending", collection=PENDING_COLLECTION,
        fields=("tenant_id", "entity_type", "normalized_value"),
        partial={"status": PENDING_STATUS_OPEN},
        description="one open proposal per text — the database-level guarantee behind the "
                    "open-slot mechanism of PR #19"))
    return keys


#: The plan. Order is stable, so reports and bootstrap runs compare cleanly.
CANONICAL_KEYS: Tuple[UniqueKey, ...] = tuple(_canonical_keys())


# ---------------------------------------------------------------- evaluating a key

def _path_values(doc: Any, path: str, missing: bool = False) -> List[Any]:
    """Values MongoDB sees for ``path``: arrays expand, a missing field gives ``[]``.

    ``missing=True`` is the index-key view: an array element that lacks the field still
    produces a ``null`` key (``{aliases: [{normalized: "x"}, {}]}`` indexes ``"x"`` AND
    ``null``). Where the server could be more lenient than this, the report errs on the
    strict side — a false "blocked" only stops a build, it never lets a bad one through.
    """
    head, _, rest = path.partition(".")
    if isinstance(doc, list):
        out: List[Any] = []
        for item in doc:
            values = _path_values(item, path, missing)
            out.extend(values if values or not missing else [None])
        return out
    if not isinstance(doc, dict) or head not in doc:
        return []
    value = doc[head]
    if rest:
        return _path_values(value, rest, missing)
    if isinstance(value, list):
        return list(value)
    return [value]


def _matches_partial(doc: Dict[str, Any], partial: Optional[Dict[str, Any]]) -> bool:
    for path, cond in (partial or {}).items():
        values = _path_values(doc, path)
        if isinstance(cond, dict):
            if set(cond) != {"$exists"}:
                raise ValueError("unsupported partial filter operator in %r" % cond)
            present = len(values) > 0      # MongoDB: a present null still "exists"
            if present != bool(cond["$exists"]):
                return False
        elif cond not in values:
            return False
    return True


def index_keys(doc: Dict[str, Any], key: UniqueKey) -> List[Tuple[Any, ...]]:
    """The index entries ``doc`` produces for ``key`` (deduplicated, like MongoDB does
    within one document). ``[]`` when the document is outside the partial filter."""
    if not _matches_partial(doc, key.partial):
        return []
    per_field = []
    for path in key.fields:
        values = _path_values(doc, path, missing=True)
        per_field.append(values if values else [None])
    seen, out = set(), []
    for combo in product(*per_field):
        marker = repr(combo)
        if marker not in seen:
            seen.add(marker)
            out.append(tuple(combo))
    return out


def _record_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: doc.get(k) for k in _VIEW_FIELDS if doc.get(k) is not None}


def blocking_groups(docs: Iterable[Dict[str, Any]], key: UniqueKey) -> Tuple[int, List[Dict[str, Any]]]:
    """``(documents_considered, groups)`` — every group is one index key that two or more
    documents share, i.e. exactly what would make the unique build fail."""
    buckets: Dict[str, Dict[str, Any]] = {}
    considered = 0
    for doc in docs:
        entries = index_keys(doc, key)
        if not entries:
            continue
        considered += 1
        for entry in entries:
            marker = repr(entry)
            bucket = buckets.setdefault(marker, {"key": list(entry), "records": []})
            bucket["records"].append(doc)
    groups = []
    for bucket in buckets.values():
        distinct = {id(d) for d in bucket["records"]}
        if len(distinct) < 2:
            continue
        entry = bucket["key"]
        shown = [mask_value(key.sensitive_kind, v) for v in entry]
        groups.append({
            "tenant_id": entry[0],
            "key": dict(zip(key.fields, shown)),
            "records": [_record_view(d) for d in bucket["records"]],
        })
    groups.sort(key=lambda g: (str(g["tenant_id"]), repr(g["key"])))
    return considered, groups


# ---------------------------------------------------------------- legacy projection

@dataclass(frozen=True)
class LegacyKey:
    """A key the canonical model will enforce, projected onto today's legacy
    collections: which records would collide once W0-03E migrates them."""

    entity_type: str
    kind: str
    sources: Tuple[Tuple[str, str], ...]          # (collection, field)
    name_fields: Tuple[str, ...] = ("name",)


LEGACY_KEYS: Tuple[LegacyKey, ...] = (
    LegacyKey(ENTITY_ORGANIZATION, "eik",
              (("companies", "eik"), ("clients", "eik"), ("counterparties", "eik"),
               ("subcontractors", "eik")), ("name", "companyName")),
    LegacyKey(ENTITY_ORGANIZATION, "vat",
              (("companies", "vat_number"), ("clients", "vat_number"),
               ("counterparties", "vat_number"), ("subcontractors", "vat_number")),
              ("name", "companyName")),
    LegacyKey(ENTITY_PERSON, "egn", (("persons", "egn"),), ("first_name", "last_name")),
    LegacyKey(ENTITY_ITEM, "sku", (("items", "sku"),), ("name",)),
    LegacyKey(ENTITY_PHYSICAL_ASSET, "serial", (("asset_units", "serial_no"),), ("qr_id",)),
    LegacyKey(ENTITY_PHYSICAL_ASSET, "qr", (("asset_units", "qr_id"),), ("serial_no",)),
    LegacyKey(ENTITY_PHYSICAL_ASSET, "inventory", (("asset_units", "inventory_no"),), ("qr_id",)),
)


def legacy_collections() -> List[str]:
    return sorted({coll for lk in LEGACY_KEYS for coll, _ in lk.sources})


def legacy_fields(collection: str) -> List[str]:
    """What an export of ``collection`` must contain for the projection — and nothing more."""
    wanted = {"id", "org_id"}
    for lk in LEGACY_KEYS:
        for coll, fld in lk.sources:
            if coll == collection:
                wanted.add(fld)
                wanted.update(lk.name_fields)
    return sorted(wanted)


#: Fields every canonical record view shows (``_record_view``).
_VIEW_FIELDS = ("id", "display_name", "raw_value", "status", "entity_type")


def canonical_collections(keys: Sequence[UniqueKey] = CANONICAL_KEYS) -> List[str]:
    return sorted({k.collection for k in keys})


def canonical_fields(collection: str, keys: Sequence[UniqueKey] = CANONICAL_KEYS) -> List[str]:
    """What an export of a canonical collection must contain to evaluate every key on it:
    the key fields, the partial-filter fields, ``tenant_id`` and the record view."""
    wanted = {"tenant_id"} | set(_VIEW_FIELDS)
    for key in keys:
        if key.collection == collection:
            wanted.update(key.fields)
            wanted.update((key.partial or {}).keys())
    return sorted(wanted)


def export_plan() -> Dict[str, Any]:
    """The contract between the NAS export (``ops/dr/w0_03c_export.js``) and this module:
    exactly these collections and fields, nothing more. A test keeps the two identical."""
    return {"schema": EXPORT_SCHEMA,
            "canonical": {c: canonical_fields(c) for c in canonical_collections()},
            "legacy": {c: legacy_fields(c) for c in legacy_collections()}}


def legacy_projection(collections: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Group legacy records by ``(org_id, <kind>:<normalized value>)``.

    ``within_collection`` groups would block the canonical index once migrated 1:1 — the
    same identity twice in one collection, a merge case for W0-03D. ``across_collections``
    groups are the five-collections-for-one-company pattern of the inventory (§2.2): they
    become ONE canonical organization with several roles, not two records.
    Informational only: nothing here gates the bootstrap, and nothing is changed.
    """
    out = []
    for lk in LEGACY_KEYS:
        buckets: Dict[Tuple[Any, str], List[Dict[str, Any]]] = {}
        for coll, fld in lk.sources:
            for doc in collections.get(coll) or []:
                k = identifier_key(lk.kind, doc.get(fld) if isinstance(doc.get(fld), str) else None)
                if not k:
                    continue
                buckets.setdefault((doc.get("org_id"), k), []).append(
                    {"collection": coll, "id": doc.get("id"), "org_id": doc.get("org_id"),
                     "name": " ".join(str(doc.get(n)) for n in lk.name_fields if doc.get(n)) or None})
        groups = []
        for (org_id, k), recs in sorted(buckets.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
            if len(recs) < 2:
                continue
            per_coll: Dict[str, int] = {}
            for r in recs:
                per_coll[r["collection"]] = per_coll.get(r["collection"], 0) + 1
            groups.append({
                "org_id": org_id,
                "key": mask_value(lk.kind, k),
                "within_collection": sorted(c for c, n in per_coll.items() if n > 1),
                "across_collections": len(per_coll) > 1,
                "records": recs,
            })
        out.append({
            "entity_type": lk.entity_type, "kind": lk.kind,
            "sources": ["%s.%s" % s for s in lk.sources],
            "groups": groups,
            "within_collection_groups": sum(1 for g in groups if g["within_collection"]),
            "tenantless_records": sum(1 for (org, _), recs in buckets.items() if org is None
                                      for _r in recs),
        })
    return out


# ---------------------------------------------------------------- the report

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_report(canonical: Dict[str, Optional[List[Dict[str, Any]]]],
                 legacy: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                 *, source: Dict[str, Any], keys: Sequence[UniqueKey] = CANONICAL_KEYS,
                 now: Optional[str] = None) -> Dict[str, Any]:
    """Assemble the report from already-read documents.

    ``canonical`` maps collection name -> documents (``None`` when the collection does not
    exist). A canonical document without ``tenant_id`` is itself a blocker: every key is
    per tenant, and such a record would index under ``null``.
    """
    indexes, clean = [], True
    tenantless: List[Dict[str, Any]] = []
    for coll, docs in canonical.items():
        for d in docs or []:
            if not d.get("tenant_id"):
                tenantless.append(dict(_record_view(d), collection=coll))
    if tenantless:
        clean = False
    for key in keys:
        docs = canonical.get(key.collection)
        considered, groups = blocking_groups(docs or [], key)
        indexes.append({
            "name": key.name, "collection": key.collection, "entity_type": key.entity_type,
            "fields": list(key.fields), "partial": key.partial, "description": key.description,
            "collection_present": docs is not None,
            "documents_considered": considered,
            "blocking_groups": groups,
            "clean": not groups,
        })
        if groups:
            clean = False
    report: Dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at": now or _now(),
        "normalization_version": NORMALIZATION_VERSION,
        "source": dict(source, read_only=True),
        "canonical": {
            "clean": clean,
            "tenantless_records": tenantless,
            "indexes": indexes,
            "blocked_indexes": sorted({"%s.%s" % (i["collection"], i["name"])
                                       for i in indexes if not i["clean"]}),
        },
        "rule": "read-only: nothing is merged, fixed or deleted; a blocked index is not built",
    }
    if legacy is not None:
        report["legacy_projection"] = legacy_projection(legacy)
    return report


# ---------------------------------------------------------------- read-only database access

class ReadOnlyViolation(RuntimeError):
    """The duplicate report tried to change the database it inspects."""


_READ_METHODS = frozenset({"find", "find_one", "count_documents", "index_information",
                           "list_indexes", "estimated_document_count"})


class ReadOnlyCollection:
    __slots__ = ("_coll",)

    def __init__(self, coll):
        self._coll = coll

    def __getattr__(self, name):
        if name in _READ_METHODS:
            return getattr(self._coll, name)
        raise ReadOnlyViolation("the duplicate report may not call %s()" % name)


class ReadOnlyDatabase:
    """Only reads get through. The report is handed this, never the raw handle."""

    __slots__ = ("_db",)

    def __init__(self, db):
        self._db = db

    def __getitem__(self, name):
        return ReadOnlyCollection(self._db[name])

    async def list_collection_names(self):
        return await self._db.list_collection_names()

    def __getattr__(self, name):
        raise ReadOnlyViolation("the duplicate report may not call database.%s()" % name)


async def _read_all(db, name: str, projection: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    cursor = db[name].find({}, projection if projection is not None else {"_id": 0})
    return await cursor.to_list(length=None)


async def duplicate_report(db, *, database: str, include_legacy: bool = False,
                           keys: Sequence[UniqueKey] = CANONICAL_KEYS,
                           now: Optional[str] = None) -> Dict[str, Any]:
    """Read a database and report exactly which records block each planned index.

    Read-only by construction: the handle is wrapped so that any write, index or drop
    call raises ``ReadOnlyViolation`` instead of reaching the server.
    """
    ro = db if isinstance(db, ReadOnlyDatabase) else ReadOnlyDatabase(db)
    present = set(await ro.list_collection_names())
    canonical: Dict[str, Optional[List[Dict[str, Any]]]] = {}
    for coll in sorted({k.collection for k in keys}):
        canonical[coll] = await _read_all(ro, coll) if coll in present else None
    legacy = None
    if include_legacy:
        legacy = {}
        for coll in legacy_collections():
            if coll in present:
                proj = {f: 1 for f in legacy_fields(coll)}
                proj["_id"] = 0
                legacy[coll] = await _read_all(ro, coll, proj)
    return build_report(canonical, legacy, source={"kind": "mongo", "database": database},
                        keys=keys, now=now)


def report_from_export(export: Dict[str, Any], *, now: Optional[str] = None) -> Dict[str, Any]:
    """The same report from an export of ONE database
    (``{"database", "exported_at", "collections": {name: [docs]}}``) — how it runs on the NAS
    against a restored copy, with no driver and no network."""
    collections = export.get("collections") or {}
    canonical = {c: collections.get(c) for c in canonical_collections()}
    legacy = {c: collections.get(c) or [] for c in legacy_collections()}
    return build_report(canonical, legacy,
                        source={"kind": "export", "database": export.get("database"),
                                "exported_at": export.get("exported_at")},
                        now=now)


def report_set_from_export(export: Dict[str, Any], *, now: Optional[str] = None) -> Dict[str, Any]:
    """A report per database of a multi-database export
    (``{"schema", "exported_at", "databases": {name: {"collections": {...}}}}``).

    Every tenant has its own database (TENANCY_MODEL §3), so each is judged on its own and
    the set is clean only when every database is. A single-database export is accepted too.
    """
    if "databases" not in export:
        single = report_from_export(export, now=now)
        databases = [single]
    else:
        if export.get("schema") not in (None, EXPORT_SCHEMA):
            raise ValueError("unknown export schema %r" % export.get("schema"))
        databases = [report_from_export(dict(body or {}, database=name,
                                             exported_at=export.get("exported_at")), now=now)
                     for name, body in sorted((export.get("databases") or {}).items())]
    return {
        "schema": REPORT_SET_SCHEMA,
        "generated_at": now or _now(),
        "exported_at": export.get("exported_at"),
        "normalization_version": NORMALIZATION_VERSION,
        "clean": bool(databases) and all(r["canonical"]["clean"] for r in databases),
        "summary": [summarize(r) for r in databases],
        "databases": databases,
        "rule": "read-only: nothing is merged, fixed or deleted; a blocked index is not built",
    }


def summarize(report: Dict[str, Any]) -> Dict[str, Any]:
    """The few numbers a human reads first; the details stay in the report."""
    canonical = report["canonical"]
    out = {
        "database": report["source"].get("database"),
        "canonical_clean": canonical["clean"],
        "blocked_indexes": canonical["blocked_indexes"],
        "blocking_groups": sum(len(i["blocking_groups"]) for i in canonical["indexes"]),
        "tenantless_canonical_records": len(canonical["tenantless_records"]),
        "canonical_documents": {i["collection"]: i["documents_considered"]
                                for i in canonical["indexes"] if i["name"] == INDEX_PREFIX + "id"},
    }
    if "legacy_projection" in report:
        out["legacy"] = [{"key": "%s.%s" % (lp["entity_type"], lp["kind"]),
                          "groups": len(lp["groups"]),
                          "within_collection_groups": lp["within_collection_groups"],
                          "tenantless_records": lp["tenantless_records"]}
                         for lp in report["legacy_projection"]]
    return out
