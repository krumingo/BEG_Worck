"""
W0-03E — the inventoried legacy identity sources and the fields that point at them.

Pure and stdlib-only. This module answers two questions and nothing else:

  * **which legacy collections hold identities**, and how one legacy document
    is read as a canonical Master candidate (``SOURCES``, ``extract``);
  * **which fields in other collections store a legacy identity id**
    (``REFERENCES``), so a migration can count every reference before and after
    and a delete can tell whether an identity is in use.

Every mapping below is technical: it reads fields the legacy writers already
write (inventory in docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md
§2 and the W0-03E implementation note). Where the legacy document does not say
authoritatively what it is, the extractor does **not** decide — it returns a
pending reason and a person decides later:

  * a ``clients`` row shaped like a natural person (first/last name, no company
    name or ЕИК) and a ``counterparties`` row of type ``person`` are not turned
    into an organization: ``ENTITY_TYPE_AMBIGUOUS``;
  * ``smr_groups`` are project-scoped groupings of work lines (they carry
    ``project_id``/``location_id``). FLOW-032 forbids a project row from becoming
    a Master СМР record, so a group is always ``PROJECT_SCOPED_ACTIVITY``: a
    person may map it to an official activity, nothing creates one from it.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.master_data.models import (
    ENTITY_ACTIVITY,
    ENTITY_ASSET_TYPE,
    ENTITY_ITEM,
    ENTITY_LOCATION,
    ENTITY_ORGANIZATION,
    ENTITY_PERSON,
    ENTITY_PHYSICAL_ASSET,
    identifier_key,
)
from app.master_data.normalize import normalize_name

# ------------------------------------------------------------ reason codes
#: A legacy record that a person must map. Nothing is created or attached.
PENDING_NAME_MATCH = "NAME_MATCH_NO_AUTHORITY"
PENDING_IDENTIFIER_CONFLICT = "IDENTIFIER_CONFLICT"
PENDING_DUPLICATE_IN_SOURCE = "DUPLICATE_IDENTIFIER_IN_SOURCE"
PENDING_ENTITY_TYPE = "ENTITY_TYPE_AMBIGUOUS"
PENDING_PROJECT_SCOPED = "PROJECT_SCOPED_ACTIVITY"
PENDING_PARENT = "PARENT_UNRESOLVED"
PENDING_EXISTING_CONFLICT = "EXISTING_MASTER_CONFLICT"
#: A legacy record that cannot be migrated as it is. Preserved and reported.
BLOCKED_NO_NAME = "NO_DISPLAY_NAME"
BLOCKED_ORPHAN = "ORPHAN_REFERENCE"
BLOCKED_BAD_ID = "INVALID_LEGACY_ID"

PENDING_REASONS = frozenset({
    PENDING_NAME_MATCH, PENDING_IDENTIFIER_CONFLICT, PENDING_DUPLICATE_IN_SOURCE,
    PENDING_ENTITY_TYPE, PENDING_PROJECT_SCOPED, PENDING_PARENT, PENDING_EXISTING_CONFLICT,
})
BLOCKED_REASONS = frozenset({BLOCKED_NO_NAME, BLOCKED_ORPHAN, BLOCKED_BAD_ID})


@dataclass
class Extract:
    """One legacy document read as a Master candidate."""
    entity_type: Optional[str]
    display_name: str = ""
    identifiers: List[Tuple[str, str]] = field(default_factory=list)   # (kind, raw value)
    #: Where a name must be unique to count as "the same name". ``None`` means a
    #: name never identifies this kind of record (a physical asset, a profile).
    name_scope: Optional[Tuple[str, ...]] = None
    roles: List[str] = field(default_factory=list)
    #: (collection, legacy id) this record IS, by a foreign key the legacy writer
    #: maintains — ``employee_profiles.user_id``. Not a guess: the same person.
    same_as: Optional[Tuple[str, str]] = None
    #: (relation name, collection, legacy id) — a parent the Master record points at.
    parent: Optional[Tuple[str, str, str]] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    pending_reason: Optional[str] = None
    blocked_reason: Optional[str] = None
    candidate_types: List[str] = field(default_factory=list)


def _s(doc: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = doc.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _full_name(doc: Dict[str, Any]) -> str:
    return " ".join(p for p in (_s(doc, "first_name"), _s(doc, "last_name")) if p)


def _ids(doc: Dict[str, Any], pairs) -> List[Tuple[str, str]]:
    out = []
    for kind, field_name in pairs:
        value = doc.get(field_name)
        if isinstance(value, (str, int)) and identifier_key(kind, str(value)):
            out.append((kind, str(value)))
    return out


_ORG_IDS = (("eik", "eik"), ("vat", "vat_number"))


def _users(doc):
    return Extract(ENTITY_PERSON, _full_name(doc) or _s(doc, "name", "email"),
                   name_scope=("person",))


def _persons(doc):
    return Extract(ENTITY_PERSON, _full_name(doc) or _s(doc, "name"),
                   identifiers=_ids(doc, (("egn", "egn"),)), name_scope=("person",))


def _employee_profiles(doc):
    user_id = _s(doc, "user_id")
    if not user_id:
        return Extract(ENTITY_PERSON, blocked_reason=BLOCKED_ORPHAN)
    return Extract(ENTITY_PERSON, same_as=("users", user_id))


def _companies(doc):
    return Extract(ENTITY_ORGANIZATION, _s(doc, "name"), identifiers=_ids(doc, _ORG_IDS),
                   name_scope=("organization",), roles=["client"],
                   attributes={"legacy_role": "project_owner"})


def _clients(doc):
    company = _s(doc, "companyName", "name")
    ids = _ids(doc, _ORG_IDS)
    if company or ids:
        return Extract(ENTITY_ORGANIZATION, company or _full_name(doc), identifiers=ids,
                       name_scope=("organization",), roles=["client"])
    # A private individual: the legacy row does not say it is an organization.
    return Extract(None, _full_name(doc), pending_reason=PENDING_ENTITY_TYPE,
                   candidate_types=[ENTITY_PERSON, ENTITY_ORGANIZATION])


#: counterparties.type -> roles. ``supplier`` is the legacy model default
#: (models/finance.py), so a row without a type is what the writer meant by it.
_COUNTERPARTY_ROLES = {"supplier": ["supplier"], "client": ["client"],
                       "both": ["client", "supplier"], "": ["supplier"]}


def _counterparties(doc):
    kind = _s(doc, "type").lower()
    if kind == "person" or kind not in _COUNTERPARTY_ROLES:
        return Extract(None, _s(doc, "name"), pending_reason=PENDING_ENTITY_TYPE,
                       candidate_types=[ENTITY_PERSON, ENTITY_ORGANIZATION],
                       attributes={"legacy_type": kind or None})
    return Extract(ENTITY_ORGANIZATION, _s(doc, "name"), identifiers=_ids(doc, _ORG_IDS),
                   name_scope=("organization",), roles=list(_COUNTERPARTY_ROLES[kind]))


def _subcontractors(doc):
    return Extract(ENTITY_ORGANIZATION, _s(doc, "name"), identifiers=_ids(doc, _ORG_IDS),
                   name_scope=("organization",), roles=["subcontractor"])


def _work_types(doc):
    return Extract(ENTITY_ACTIVITY, _s(doc, "name"), name_scope=("activity",))


def _smr_groups(doc):
    return Extract(ENTITY_ACTIVITY, _s(doc, "name"), name_scope=("activity",),
                   pending_reason=PENDING_PROJECT_SCOPED,
                   attributes={"project_id": doc.get("project_id"),
                               "location_id": doc.get("location_id")})


def _items(doc):
    return Extract(ENTITY_ITEM, _s(doc, "name"), identifiers=_ids(doc, (("sku", "sku"),)),
                   name_scope=("item", normalize_name(_s(doc, "unit"))),
                   attributes={"unit": doc.get("unit"), "brand": doc.get("brand")})


def _asset_item_types(doc):
    return Extract(ENTITY_ASSET_TYPE, _s(doc, "label_bg", "key"), name_scope=("asset_category",),
                   attributes={"asset_level": "category", "legacy_key": doc.get("key")})


def _asset_items(doc):
    return Extract(ENTITY_ASSET_TYPE, _s(doc, "name"),
                   name_scope=("asset_model", normalize_name(_s(doc, "brand")),
                               normalize_name(_s(doc, "model"))),
                   attributes={"asset_level": "model", "legacy_type_key": doc.get("type"),
                               "brand": doc.get("brand"), "model": doc.get("model"),
                               "article_no": doc.get("article_no")})


def _asset_units(doc):
    label = _s(doc, "inventory_no", "serial_no", "qr_id") or _s(doc, "id")
    item_id = _s(doc, "item_id")
    return Extract(ENTITY_PHYSICAL_ASSET, "Актив %s" % label,
                   identifiers=_ids(doc, (("serial", "serial_no"), ("qr", "qr_id"),
                                          ("inventory", "inventory_no"))),
                   parent=("asset_type_id", "asset_items", item_id) if item_id else None,
                   attributes={"legacy_status": doc.get("status")})


def _warehouses(doc):
    return Extract(ENTITY_LOCATION, _s(doc, "name", "code"), name_scope=("warehouse",),
                   attributes={"location_kind": "warehouse", "code": doc.get("code"),
                               "legacy_type": doc.get("type")})


def _location_nodes(doc):
    parent_id = _s(doc, "parent_id")
    return Extract(ENTITY_LOCATION, _s(doc, "name"),
                   name_scope=("node", str(doc.get("project_id") or ""), parent_id),
                   parent=("parent_id", "location_nodes", parent_id) if parent_id else None,
                   attributes={"location_kind": doc.get("type"), "project_id": doc.get("project_id"),
                               "code": doc.get("code")})


@dataclass(frozen=True)
class Source:
    collection: str
    entity_type: str            # the canonical type the source maps to (contract §6 W0-03E)
    extractor: Callable[[Dict[str, Any]], Extract]
    #: the legacy flag an archive sets instead of a hard delete; None = no archive field
    active_field: Optional[str] = None


#: Order matters: it is the deterministic precedence of the plan. A record that
#: several sources describe is anchored on the first source that has it.
SOURCES: Tuple[Source, ...] = (
    Source("users", ENTITY_PERSON, _users, "is_active"),
    Source("persons", ENTITY_PERSON, _persons, "is_active"),
    Source("employee_profiles", ENTITY_PERSON, _employee_profiles, "active"),
    Source("companies", ENTITY_ORGANIZATION, _companies, "is_active"),
    Source("clients", ENTITY_ORGANIZATION, _clients, "is_active"),
    Source("counterparties", ENTITY_ORGANIZATION, _counterparties, "active"),
    Source("subcontractors", ENTITY_ORGANIZATION, _subcontractors, "active"),
    Source("work_types", ENTITY_ACTIVITY, _work_types, "is_active"),
    Source("smr_groups", ENTITY_ACTIVITY, _smr_groups, None),
    Source("items", ENTITY_ITEM, _items, "is_active"),
    Source("asset_item_types", ENTITY_ASSET_TYPE, _asset_item_types, None),
    Source("asset_items", ENTITY_ASSET_TYPE, _asset_items, "is_active"),
    Source("asset_units", ENTITY_PHYSICAL_ASSET, _asset_units, "is_active"),
    Source("warehouses", ENTITY_LOCATION, _warehouses, "active"),
    Source("location_nodes", ENTITY_LOCATION, _location_nodes, None),
)
SOURCE_BY_COLLECTION = {s.collection: s for s in SOURCES}
SOURCE_ORDER = {s.collection: i for i, s in enumerate(SOURCES)}


def source(collection: str) -> Source:
    try:
        return SOURCE_BY_COLLECTION[collection]
    except KeyError:
        from app.master_data.models import MasterDataInvalid
        raise MasterDataInvalid("%r is not an inventoried legacy identity source" % (collection,))


def extract(collection: str, doc: Dict[str, Any]) -> Extract:
    """Read one legacy document. Never raises on content: a document that cannot
    be read becomes a blocked or pending candidate with a reason."""
    ex = source(collection).extractor(doc)
    if ex.entity_type is not None and not ex.blocked_reason and not ex.same_as \
            and not ex.display_name:
        ex.blocked_reason = BLOCKED_NO_NAME
    return ex


# ------------------------------------------------------------ references
@dataclass(frozen=True)
class Reference:
    """``collection.field`` stores the id of a ``target`` legacy identity."""
    collection: str
    field: str
    target: str
    where: Tuple[Tuple[str, Any], ...] = ()
    #: the field holds the target's ``key`` rather than its ``id``
    by_key: Optional[str] = None


def _r(collection, fld, target, where=(), by_key=None):
    return Reference(collection, fld, target, tuple(where), by_key)


#: The main stored references to the inventoried identities (file:line evidence
#: in the W0-03E implementation note). Nested array fields use dotted paths.
REFERENCES: Tuple[Reference, ...] = (
    _r("employee_profiles", "user_id", "users"),
    _r("project_team", "user_id", "users"),
    _r("advances", "user_id", "users"),
    _r("finance_payments", "user_id", "users"),
    _r("attendance_entries", "user_id", "users"),
    _r("work_reports", "user_id", "users"),
    _r("employee_daily_reports", "employee_id", "users"),
    _r("work_sessions", "worker_id", "users"),
    _r("contract_payments", "worker_id", "users"),
    _r("asset_custody", "custodian_user_id", "users"),
    _r("brigades", "leader_user_id", "users"),
    _r("brigades", "member_ids", "users"),
    _r("projects", "default_site_manager_id", "users"),
    _r("asset_units", "location_id", "users", where=(("location_type", "employee"),)),
    _r("projects", "owner_id", "persons", where=(("owner_type", "person"),)),
    _r("projects", "owner_id", "companies", where=(("owner_type", "company"),)),
    _r("counterparties", "client_id", "clients"),
    _r("sales", "client_id", "clients"),
    _r("invoices", "supplier_counterparty_id", "counterparties"),
    _r("supplier_invoices", "supplier_id", "counterparties"),
    _r("warehouse_batches", "supplier_id", "counterparties"),
    _r("subcontractor_packages", "subcontractor_id", "subcontractors"),
    _r("subcontractor_acts", "subcontractor_id", "subcontractors"),
    _r("subcontractor_payments", "subcontractor_id", "subcontractors"),
    _r("daily_work_logs", "work_type_id", "work_types"),
    _r("missing_smr", "group_id", "smr_groups"),
    _r("extra_work_drafts", "group_id", "smr_groups"),
    _r("smr_analyses", "lines.group_id", "smr_groups"),
    _r("sales", "item_id", "items"),
    _r("warehouse_batches", "item_id", "items"),
    _r("material_consumption_log", "item_id", "items"),
    _r("asset_items", "type", "asset_item_types", by_key="key"),
    _r("asset_units", "item_id", "asset_items"),
    _r("asset_custody", "unit_id", "asset_units"),
    _r("asset_movements", "unit_id", "asset_units"),
    _r("asset_repairs", "unit_id", "asset_units"),
    _r("warehouse_transactions", "warehouse_id", "warehouses"),
    _r("sales", "warehouse_id", "warehouses"),
    _r("warehouse_batches", "warehouse_id", "warehouses"),
    _r("material_consumption_log", "warehouse_id", "warehouses"),
    _r("asset_units", "location_id", "warehouses", where=(("location_type", "warehouse"),)),
    _r("location_nodes", "parent_id", "location_nodes"),
    _r("missing_smr", "location_id", "location_nodes"),
    _r("extra_work_drafts", "location_id", "location_nodes"),
    _r("material_waste", "location_id", "location_nodes"),
    _r("smr_groups", "location_id", "location_nodes"),
)


def references_to(collection: str) -> List[Reference]:
    return [r for r in REFERENCES if r.target == collection]


def values_at(doc: Dict[str, Any], path: str) -> List[str]:
    """Every non-empty string at a dotted path, descending into arrays."""
    head, _, tail = path.partition(".")
    value = doc.get(head) if isinstance(doc, dict) else None
    items = value if isinstance(value, list) else [value]
    out: List[str] = []
    for item in items:
        if tail:
            out.extend(values_at(item, tail) if isinstance(item, dict) else [])
        elif isinstance(item, str) and item:
            out.append(item)
    return out
