"""
W0-06A — the canonical File Registry records.

FLOW-016 is the business source of truth: one physical file has ONE stable
``file_id``, and every module points at that id instead of keeping its own copy
or its own provider path. This module is the record layer of that rule — the
builders and validators for the five record types, plus the one vocabulary
(categories, relation types, provider kinds, availability states) the service,
the migration map, the static guard and the tests all read. There is no second
definition of a File anywhere.

The five records and why each exists separately
-----------------------------------------------

``File`` (:data:`FILES_COLLECTION`)
    The business identity and its classification. It is the *document family*:
    ``file_id`` never changes, not when a new version is uploaded, not when the
    tenant migrates to another storage provider. It deliberately does NOT carry
    checksum, size or mime type — those are facts of a VERSION — nor provider
    path or availability, which are facts of a LOCATION. Copying them here
    would create the second source of truth CLAUDE.md §2 rule 12 forbids.

``FileVersion`` (:data:`VERSIONS_COLLECTION`)
    One immutable member of the family. A new version never overwrites an old
    one: it is a new row, the old row stays readable and read-only, and exactly
    one row per family carries ``is_current``. The content facts (checksum,
    size, mime type, original name) live here because they are what differs
    between versions.

``FileRelation`` (:data:`RELATIONS_COLLECTION`)
    One business record this file belongs to. A file reaches many records
    through many relation rows and is still ONE registry record with one
    physical original — that is the "един файл, много връзки" rule. Unlinking
    is per-relation and never touches the file or the provider object.

``ProviderLocation`` (:data:`LOCATIONS_COLLECTION`)
    Where one version of the file physically sits in the TENANT'S OWN storage
    provider, plus the availability of that object. ``object_key`` is a
    provider coordinate, never a business identifier: nothing in BEG_Work may
    resolve a file by it. Credentials are NOT here — the location names a
    provider binding, and the binding's secrets live in encrypted tenant
    configuration the registry never reads.

``DerivedArtifact`` (:data:`DERIVED_COLLECTION`)
    A thumbnail, preview, OCR text or PDF render BEG_Work cached for itself. It
    is a technical derivative, never a business version and never the canonical
    original: :func:`build_derived` refuses a record that claims otherwise, and
    a missing original is reported as missing even when a derivative is still
    in the cache.

``DeleteRequest`` (:data:`DELETE_REQUESTS_COLLECTION`)
    Removing a file from the registry is not a promise that the customer's
    original was destroyed. A physical delete at the provider is a separate,
    explicit action with its own request row, its own provider response and its
    own AuditEvent (FLOW-016 §"Премахване на връзка и изтриване").

Tenancy. Every record carries ``org_id`` — the legacy tenant key of the
operational collections (``app.tenancy.data_access.TENANT_KEY``), the same key
the W0-03E-A2C boundary scopes by. The registry's relations point at
``org_id``-keyed business records, so using any other key here would put half a
relation on each side of the tenant boundary.

Pure and stdlib-only: no database, no FastAPI, no I/O. The service layer
(``app.files.registry``) persists what this module builds.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

#: The tenant key of every File Registry record (same value as
#: ``app.tenancy.data_access.TENANT_KEY``; kept literal so this module stays
#: importable without FastAPI, exactly like ``app.tenancy.ownership``).
ORG_KEY = "org_id"

# --------------------------------------------------------------- collections
FILES_COLLECTION = "file_registry"
VERSIONS_COLLECTION = "file_versions"
RELATIONS_COLLECTION = "file_relations"
LOCATIONS_COLLECTION = "file_provider_locations"
DERIVED_COLLECTION = "file_derived_cache"
DELETE_REQUESTS_COLLECTION = "file_delete_requests"
#: Per-tenant monotonic counters of the registry (W0-06B). Today one: the
#: registration order of files, which is what makes "the oldest file with this
#: checksum" a fact rather than a guess about two equal timestamps.
SEQUENCES_COLLECTION = "file_registry_sequences"

#: Every collection this foundation owns. The static guard reads this set, so a
#: collection added here is in scope from the moment it exists.
REGISTRY_COLLECTIONS: FrozenSet[str] = frozenset({
    FILES_COLLECTION, VERSIONS_COLLECTION, RELATIONS_COLLECTION,
    LOCATIONS_COLLECTION, DERIVED_COLLECTION, DELETE_REQUESTS_COLLECTION,
    SEQUENCES_COLLECTION,
})

#: FLOW-016 source flow id for every AuditEvent this foundation writes.
SOURCE_FLOW = "FLOW-016"

# ------------------------------------------------------------------ id prefix
ID_PREFIX_FILE = "file_"
ID_PREFIX_VERSION = "fv_"
ID_PREFIX_RELATION = "fr_"
ID_PREFIX_LOCATION = "fl_"
ID_PREFIX_DERIVED = "fd_"
ID_PREFIX_DELETE = "fdr_"

# ------------------------------------------------------------------ categories
#: FLOW-016 §"Логическа структура". The physical folder is not the business
#: truth; the category, the version and the relations are.
CATEGORY_CONTRACTS = "contracts_annexes"
CATEGORY_OFFERS = "offers"
CATEGORY_ACTS = "acts_protocols"
CATEGORY_INVOICES = "invoices_financial"
CATEGORY_DRAWINGS = "drawings_projects"
CATEGORY_DAILY_REPORTS = "daily_reports"
CATEGORY_PHOTO_VIDEO = "photos_video"
CATEGORY_DELIVERIES = "deliveries_goods_docs"
CATEGORY_DEFECTS = "defects_warranty"
CATEGORY_SAFETY = "safety_certificates"
CATEGORY_OTHER = "other"

CATEGORIES: FrozenSet[str] = frozenset({
    CATEGORY_CONTRACTS, CATEGORY_OFFERS, CATEGORY_ACTS, CATEGORY_INVOICES,
    CATEGORY_DRAWINGS, CATEGORY_DAILY_REPORTS, CATEGORY_PHOTO_VIDEO,
    CATEGORY_DELIVERIES, CATEGORY_DEFECTS, CATEGORY_SAFETY, CATEGORY_OTHER,
})

# ---------------------------------------------------------------- sensitivity
#: FLOW-016 §"Права и сигурност": access to an object does NOT grant access to
#: payroll, bank, personal, commission or internal financial files. The
#: narrower right wins, so sensitivity is a property of the file itself.
SENSITIVITY_STANDARD = "standard"
SENSITIVITY_RESTRICTED = "restricted"
SENSITIVITY_CONFIDENTIAL = "confidential"

SENSITIVITIES: FrozenSet[str] = frozenset({
    SENSITIVITY_STANDARD, SENSITIVITY_RESTRICTED, SENSITIVITY_CONFIDENTIAL,
})

# -------------------------------------------------------------- file statuses
FILE_ACTIVE = "active"
#: A physical delete at the provider has been requested and not yet answered.
FILE_DELETE_REQUESTED = "delete_requested"
#: The provider confirmed the original is gone. The registry record REMAINS —
#: the history of what the file was attached to is not erased with it.
FILE_DELETED_AT_PROVIDER = "deleted_at_provider"

FILE_STATUSES: FrozenSet[str] = frozenset({
    FILE_ACTIVE, FILE_DELETE_REQUESTED, FILE_DELETED_AT_PROVIDER,
})

# ----------------------------------------------------------- approval states
#: FLOW-016: an approved/signed version can never be replaced in place. The
#: registry refuses to mutate such a version; only a NEW version may follow it.
APPROVAL_NONE = "none"
APPROVAL_APPROVED = "approved"
APPROVAL_SIGNED = "signed"

APPROVAL_STATES: FrozenSet[str] = frozenset({
    APPROVAL_NONE, APPROVAL_APPROVED, APPROVAL_SIGNED,
})
#: The states that make a version evidential. Writing over one is forbidden.
SEALED_APPROVAL_STATES: FrozenSet[str] = frozenset({APPROVAL_APPROVED, APPROVAL_SIGNED})

# ------------------------------------------------------------- relation types
#: Issue #43 §3 / FLOW-016 §"Един файл, много връзки". ``record_id`` names a
#: record of the SAME tenant in the collection paired here; the pairing is what
#: lets the service verify the target exists in this tenant before linking.
RELATION_PROJECT = "project"
RELATION_SUB_PROJECT = "sub_project"
RELATION_SMR = "smr"
RELATION_DAILY_REPORT = "daily_report"
RELATION_OFFER = "offer"
RELATION_CONTRACT = "contract"
RELATION_ANNEX = "annex"
RELATION_ACT = "act"
RELATION_INVOICE = "invoice"
RELATION_DELIVERY = "delivery"
RELATION_TASK = "task"
RELATION_DEFECT = "defect"
RELATION_WARRANTY = "warranty"
RELATION_SUBCONTRACTOR = "subcontractor"
RELATION_ASSET = "asset"
RELATION_REPAIR = "repair"
#: Beyond the Issue #43 §3 minimum: the targets the legacy media contexts and
#: the legacy attachment fields actually point at today. They are here because
#: the migration map must be able to express EVERY existing attachment as a
#: relation; a legacy link with no relation type would have to be dropped, and
#: "the migration silently lost the photo of a repair" is not an acceptable map.
RELATION_SUPPLIER_INVOICE = "supplier_invoice"
RELATION_EXPENSE = "expense"
RELATION_WORK_REPORT = "work_report"
RELATION_ATTENDANCE = "attendance"
RELATION_MACHINE = "machine"
RELATION_SITE = "site"
RELATION_USER_PROFILE = "user_profile"
RELATION_EXTRA_WORK = "extra_work"
RELATION_OCR_INTAKE = "ocr_intake"

#: relation type -> the legacy collection its ``record_id`` lives in. Every one
#: of these is ``ORG_KEYED`` in ``app.tenancy.ownership``, which is what makes a
#: relation verifiable inside one tenant.
RELATION_TARGETS: Dict[str, str] = {
    RELATION_PROJECT: "projects",
    RELATION_SUB_PROJECT: "projects",
    RELATION_SMR: "work_types",
    RELATION_DAILY_REPORT: "daily_work_logs",
    RELATION_OFFER: "offers",
    RELATION_CONTRACT: "offers",
    RELATION_ANNEX: "change_orders",
    RELATION_ACT: "client_acts",
    RELATION_INVOICE: "invoices",
    RELATION_DELIVERY: "deliveries",
    RELATION_TASK: "worker_calendar",
    RELATION_DEFECT: "missing_smr",
    RELATION_WARRANTY: "asset_repairs",
    RELATION_SUBCONTRACTOR: "subcontractors",
    RELATION_ASSET: "asset_items",
    RELATION_REPAIR: "asset_repairs",
    RELATION_SUPPLIER_INVOICE: "supplier_invoices",
    RELATION_EXPENSE: "pending_expenses",
    RELATION_WORK_REPORT: "work_reports",
    RELATION_ATTENDANCE: "attendance_entries",
    RELATION_MACHINE: "machines",
    RELATION_SITE: "sites",
    RELATION_USER_PROFILE: "users",
    RELATION_EXTRA_WORK: "extra_work_drafts",
    RELATION_OCR_INTAKE: "ocr_invoice_intake",
}

RELATION_TYPES: FrozenSet[str] = frozenset(RELATION_TARGETS)

# -------------------------------------------------------------- provider kinds
#: FLOW-016 §"Отговорност на клиента": the tenant brings its own storage. A is
#: the CONTRACT only — no adapter here talks to a real provider and no
#: credential is read (:mod:`app.files.providers`).
PROVIDER_GOOGLE_DRIVE = "google_drive"
PROVIDER_SYNOLOGY_NAS = "synology_nas"
PROVIDER_S3_COMPATIBLE = "s3_compatible"
PROVIDER_ON_PREM_SERVER = "on_prem_server"
#: The in-memory double the contract tests run against. Never a tenant's primary.
PROVIDER_FAKE_MEMORY = "fake_memory"
#: Not a storage provider: the BEG_Work application disk the legacy uploads sit
#: on today. It exists so the migration map can NAME where a legacy byte is now
#: without pretending that location is a customer-managed provider.
PROVIDER_LEGACY_APP_DISK = "legacy_app_disk"

PROVIDER_KINDS: FrozenSet[str] = frozenset({
    PROVIDER_GOOGLE_DRIVE, PROVIDER_SYNOLOGY_NAS, PROVIDER_S3_COMPATIBLE,
    PROVIDER_ON_PREM_SERVER, PROVIDER_FAKE_MEMORY, PROVIDER_LEGACY_APP_DISK,
})
#: The customer-managed providers a tenant may be activated on (FLOW-016
#: onboarding gate). The fake and the legacy app disk are deliberately absent.
CUSTOMER_MANAGED_PROVIDER_KINDS: FrozenSet[str] = frozenset({
    PROVIDER_GOOGLE_DRIVE, PROVIDER_SYNOLOGY_NAS, PROVIDER_S3_COMPATIBLE,
    PROVIDER_ON_PREM_SERVER,
})

LOCATION_ROLE_PRIMARY = "primary"
LOCATION_ROLE_BACKUP = "backup"
LOCATION_ROLES: FrozenSet[str] = frozenset({LOCATION_ROLE_PRIMARY, LOCATION_ROLE_BACKUP})

# ------------------------------------------------------------- availability
#: FLOW-016 §"Периодична проверка": a permission failure is NOT the same thing
#: as a physically missing file, and an externally mutated object is an
#: integrity problem, never an automatic new version. Each gets its own state so
#: the Health Dashboard and the alarm severity can tell them apart.
AVAILABILITY_UNVERIFIED = "unverified"
AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_MISSING = "missing"
AVAILABILITY_CHECKSUM_MISMATCH = "checksum_mismatch"
AVAILABILITY_PERMISSION_DENIED = "permission_denied"
AVAILABILITY_PROVIDER_UNREACHABLE = "provider_unreachable"
#: W0-06B. The location now holds a DIFFERENT provider object (another file id
#: or version) than the one BEG_Work recorded, while its bytes could not be
#: shown to differ: somebody replaced the file outside BEG_Work. Distinct from
#: ``checksum_mismatch`` (bytes proven different) and never a new version.
AVAILABILITY_EXTERNALLY_CHANGED = "externally_changed"

AVAILABILITY_STATES: FrozenSet[str] = frozenset({
    AVAILABILITY_UNVERIFIED, AVAILABILITY_AVAILABLE, AVAILABILITY_MISSING,
    AVAILABILITY_CHECKSUM_MISMATCH, AVAILABILITY_PERMISSION_DENIED,
    AVAILABILITY_PROVIDER_UNREACHABLE, AVAILABILITY_EXTERNALLY_CHANGED,
})
#: States in which the canonical original cannot be served. A cached derivative
#: never substitutes for one of these (FLOW-016 §"Снимки и технически производни").
UNUSABLE_AVAILABILITY: FrozenSet[str] = frozenset({
    AVAILABILITY_MISSING, AVAILABILITY_CHECKSUM_MISMATCH,
    AVAILABILITY_PERMISSION_DENIED, AVAILABILITY_PROVIDER_UNREACHABLE,
    AVAILABILITY_EXTERNALLY_CHANGED,
})

# ---------------------------------------------------------------- derivatives
DERIVED_THUMBNAIL = "thumbnail"
DERIVED_PREVIEW = "compressed_preview"
DERIVED_OCR_TEXT = "ocr_text"
DERIVED_PDF_PREVIEW = "pdf_preview"

DERIVED_KINDS: FrozenSet[str] = frozenset({
    DERIVED_THUMBNAIL, DERIVED_PREVIEW, DERIVED_OCR_TEXT, DERIVED_PDF_PREVIEW,
})

# ------------------------------------------------------------- delete states
DELETE_REQUESTED = "requested"
DELETE_PROVIDER_CONFIRMED = "provider_confirmed"
DELETE_PROVIDER_REFUSED = "provider_refused"
DELETE_PROVIDER_FAILED = "provider_failed"

DELETE_STATES: FrozenSet[str] = frozenset({
    DELETE_REQUESTED, DELETE_PROVIDER_CONFIRMED, DELETE_PROVIDER_REFUSED,
    DELETE_PROVIDER_FAILED,
})

#: What ONE delete request is about (W0-06A review finding 3). A request names
#: exactly one scope, and its provider answer applies to exactly the locations
#: frozen into the request when it was opened — never to "every location of the
#: file". Destroying the whole family is a different, explicit action.
DELETE_SCOPE_VERSION = "version"
DELETE_SCOPE_FILE = "file"
DELETE_SCOPES: FrozenSet[str] = frozenset({DELETE_SCOPE_VERSION, DELETE_SCOPE_FILE})

# ------------------------------------------------------------------- checksum
CHECKSUM_SHA256 = "sha256"
CHECKSUM_ALGORITHMS: FrozenSet[str] = frozenset({CHECKSUM_SHA256})


class FileRecordInvalid(ValueError):
    """The record violates a FLOW-016 rule and must not be written."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FileRecordInvalid("%s is required" % field)
    return value.strip()


def _require_owner(org_id: Any) -> str:
    """Ownership is server-derived and never optional.

    An ownerless File Registry row is the defect W0-03E-A2B removed from the
    legacy collections: once written it belongs to no tenant, so no tenant view
    can reach it and no backfill can tell whose it was. Fail closed at build
    time, before the write.
    """
    if not isinstance(org_id, str) or not org_id.strip():
        raise FileRecordInvalid("a File Registry record cannot be written without an owner")
    return org_id.strip()


def _require_choice(value: Any, allowed: FrozenSet[str], field: str) -> str:
    if value not in allowed:
        raise FileRecordInvalid("%s must be one of %s, got %r"
                                % (field, sorted(allowed), value))
    return value


def new_file_id() -> str:
    """A fresh business identity.

    Minted by BEG_Work and meaningless to any provider: it carries no path, no
    bucket, no account and no file name, so it cannot break when the tenant
    moves its storage (FLOW-016 §"Какво НЕ трябва да позволява": a migration may
    never break ``file_id`` and relations).
    """
    return ID_PREFIX_FILE + uuid.uuid4().hex


def checksum(value: Any, algorithm: str = CHECKSUM_SHA256) -> Dict[str, str]:
    """A checksum as ``{"algorithm": ..., "value": ...}``, lower-cased hex."""
    _require_choice(algorithm, CHECKSUM_ALGORITHMS, "checksum algorithm")
    text = _require_text(value, "checksum value").lower()
    if algorithm == CHECKSUM_SHA256 and (len(text) != 64 or
                                         any(c not in "0123456789abcdef" for c in text)):
        raise FileRecordInvalid("sha256 checksum must be 64 hex characters")
    return {"algorithm": algorithm, "value": text}


def checksum_key(value: Optional[Mapping[str, Any]]) -> Optional[str]:
    """``"<algorithm>:<value>"`` — the comparable form used for duplicate lookup."""
    if not value:
        return None
    algo, digest = value.get("algorithm"), value.get("value")
    if not isinstance(algo, str) or not isinstance(digest, str) or not algo or not digest:
        return None
    return "%s:%s" % (algo, digest.lower())


# --------------------------------------------------------------------- File
def build_file(
    *,
    org_id: str,
    display_name: str,
    original_name: str,
    category: str,
    uploaded_by: str,
    sensitivity: str = SENSITIVITY_STANDARD,
    file_id: Optional[str] = None,
    status: str = FILE_ACTIVE,
    uploaded_at: Optional[str] = None,
    registration_seq: Optional[int] = None,
) -> Dict[str, Any]:
    """The family head: a stable identity plus its classification.

    ``current_version_no`` starts at 0 and the first
    :func:`build_version` moves it to 1 — a File with no version has no content
    yet, and saying so explicitly is better than implying a version 1 that was
    never written.

    ``registration_seq`` is the tenant's monotonic registration counter,
    allocated atomically by the service. It is immutable and is the first key
    of :func:`file_order_key`, so the order of two files never depends on a
    clock that can return the same instant twice (W0-06A review finding 4).
    """
    if registration_seq is not None and (not isinstance(registration_seq, int)
                                         or isinstance(registration_seq, bool)
                                         or registration_seq < 1):
        raise FileRecordInvalid("registration_seq must be an integer >= 1")
    now = _now_iso()
    return {
        "id": file_id or new_file_id(),
        ORG_KEY: _require_owner(org_id),
        "display_name": _require_text(display_name, "display_name"),
        "original_name": _require_text(original_name, "original_name"),
        "category": _require_choice(category, CATEGORIES, "category"),
        "sensitivity": _require_choice(sensitivity, SENSITIVITIES, "sensitivity"),
        "status": _require_choice(status, FILE_STATUSES, "status"),
        # Content facts live on the VERSION, provider facts on the LOCATION.
        # Only the pointer to the current member of the family lives here.
        "current_version_no": 0,
        "version_count": 0,
        "registration_seq": registration_seq,
        "uploaded_by": _require_text(uploaded_by, "uploaded_by"),
        "uploaded_at": uploaded_at or now,
        "created_at": now,
        "updated_at": now,
    }


# -------------------------------------------------------------- FileVersion
def build_version(
    *,
    org_id: str,
    file_id: str,
    version_no: int,
    checksum_value: Mapping[str, Any],
    size_bytes: int,
    mime_type: str,
    original_name: str,
    created_by: str,
    reason: Optional[str] = None,
    supersedes_version_no: Optional[int] = None,
    approval_state: str = APPROVAL_NONE,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """One immutable member of a document family.

    ``version_no`` 1 is the original upload and needs no reason. Every later
    version MUST say who, when, why and which version it follows (FLOW-016
    §"Версиониране"), because that is the record a reviewer reads when asking
    why the signed copy of a contract changed.
    """
    owner = _require_owner(org_id)
    if not isinstance(version_no, int) or isinstance(version_no, bool) or version_no < 1:
        raise FileRecordInvalid("version_no must be an integer >= 1")
    if version_no > 1:
        if not reason or not str(reason).strip():
            raise FileRecordInvalid("a new version requires an explicit reason")
        if supersedes_version_no != version_no - 1:
            raise FileRecordInvalid(
                "version %d must supersede version %d" % (version_no, version_no - 1))
    elif supersedes_version_no is not None:
        raise FileRecordInvalid("the first version supersedes nothing")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
        raise FileRecordInvalid("size_bytes must be a non-negative integer")
    now = created_at or _now_iso()
    return {
        "id": ID_PREFIX_VERSION + uuid.uuid4().hex,
        ORG_KEY: owner,
        "file_id": _require_text(file_id, "file_id"),
        "version_no": version_no,
        "is_current": True,
        "checksum": checksum(checksum_value.get("value"),
                             checksum_value.get("algorithm", CHECKSUM_SHA256)),
        "checksum_key": checksum_key(checksum_value),
        "size_bytes": size_bytes,
        "mime_type": _require_text(mime_type, "mime_type"),
        "original_name": _require_text(original_name, "original_name"),
        "created_by": _require_text(created_by, "created_by"),
        "created_at": now,
        "reason": (str(reason).strip() if reason else None),
        "supersedes_version_no": supersedes_version_no,
        "superseded_by_version_no": None,
        "superseded_at": None,
        "approval_state": _require_choice(approval_state, APPROVAL_STATES, "approval_state"),
    }


#: Fields of a stored version that describe its CONTENT. Once written they are
#: history: the registry refuses to update any of them, which is what "старите
#: версии са видими и read-only" means in code rather than in prose.
VERSION_IMMUTABLE_FIELDS: FrozenSet[str] = frozenset({
    "id", ORG_KEY, "file_id", "version_no", "checksum", "checksum_key",
    "size_bytes", "mime_type", "original_name", "created_by", "created_at",
    "reason", "supersedes_version_no",
})
#: The only fields a later event may set on an existing version: the two that
#: record that a SUCCESSOR arrived, and the approval seal.
VERSION_MUTABLE_FIELDS: FrozenSet[str] = frozenset({
    "is_current", "superseded_by_version_no", "superseded_at", "approval_state",
})


def assert_version_update_allowed(update: Mapping[str, Any]) -> None:
    """Refuse an update that would rewrite history. Raises :class:`FileRecordInvalid`."""
    touched = {k for k in update if not k.startswith("$")}
    for operator, fields in update.items():
        if operator.startswith("$") and isinstance(fields, Mapping):
            touched |= set(fields)
    forbidden = sorted(touched & VERSION_IMMUTABLE_FIELDS)
    if forbidden:
        raise FileRecordInvalid(
            "a stored FileVersion is read-only; refused update of %s" % forbidden)
    unknown = sorted(touched - VERSION_MUTABLE_FIELDS)
    if unknown:
        raise FileRecordInvalid("unknown FileVersion field(s) %s" % unknown)


# ------------------------------------------------------------- FileRelation
def build_relation(
    *,
    org_id: str,
    file_id: str,
    relation_type: str,
    record_id: str,
    created_by: str,
    role: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """One link between a file and one business record of the SAME tenant.

    The relation carries the owner itself rather than inheriting it from either
    side. W0-03E-A2 proved why: an ownerless relation row cannot say who wrote
    it, so with colliding ids a row written by tenant B is honoured for tenant
    A. The tenant predicate therefore sits on the row.
    """
    owner = _require_owner(org_id)
    rel_type = _require_choice(relation_type, RELATION_TYPES, "relation_type")
    now = created_at or _now_iso()
    return {
        "id": ID_PREFIX_RELATION + uuid.uuid4().hex,
        ORG_KEY: owner,
        "file_id": _require_text(file_id, "file_id"),
        "relation_type": rel_type,
        "target_collection": RELATION_TARGETS[rel_type],
        "record_id": _require_text(record_id, "record_id"),
        "role": (str(role).strip() or None) if role else None,
        "active": True,
        "created_by": _require_text(created_by, "created_by"),
        "created_at": now,
        # Unlink is a state change with an author and a reason, not a hard
        # delete: the history of what this file was attached to survives it
        # (CLAUDE.md §2 rule 9).
        "removed_by": None,
        "removed_at": None,
        "removed_reason": None,
    }


def relation_identity(org_id: str, file_id: str, relation_type: str, record_id: str) -> str:
    """The value that makes one ACTIVE relation unique per tenant.

    Includes the owner, so the same ``(file_id, type, record_id)`` triple in two
    tenants is two different identities and one tenant's relation can never
    collide with — or be mistaken for — another's.
    """
    return "|".join((org_id, file_id, relation_type, record_id))


# ----------------------------------------------------------- ProviderLocation
def build_provider_location(
    *,
    org_id: str,
    file_id: str,
    version_no: int,
    provider_kind: str,
    provider_binding_id: str,
    container: str,
    object_key: str,
    expected_checksum: Optional[Mapping[str, Any]] = None,
    provider_file_id: Optional[str] = None,
    role: str = LOCATION_ROLE_PRIMARY,
    availability: str = AVAILABILITY_UNVERIFIED,
    created_at: Optional[str] = None,
    provider_version_id: Optional[str] = None,
    size_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """Where ONE version physically sits, in the tenant's own provider.

    ``provider_binding_id`` names the tenant's configured provider account; the
    credentials behind it are encrypted tenant configuration this record never
    holds and this package never reads (FLOW-016 §"Права и сигурност": no
    credential and no provider object identifier may reach another tenant, and
    the browser never receives storage credentials at all).

    ``object_key`` is a provider coordinate. It is deliberately NOT indexed as
    an identity and no lookup in this package resolves a file by it.
    """
    owner = _require_owner(org_id)
    if not isinstance(version_no, int) or isinstance(version_no, bool) or version_no < 1:
        raise FileRecordInvalid("version_no must be an integer >= 1")
    now = created_at or _now_iso()
    return {
        "id": ID_PREFIX_LOCATION + uuid.uuid4().hex,
        ORG_KEY: owner,
        "file_id": _require_text(file_id, "file_id"),
        "version_no": version_no,
        "provider_kind": _require_choice(provider_kind, PROVIDER_KINDS, "provider_kind"),
        "provider_binding_id": _require_text(provider_binding_id, "provider_binding_id"),
        "container": _require_text(container, "container"),
        "object_key": _require_text(object_key, "object_key"),
        "provider_file_id": (str(provider_file_id).strip() or None) if provider_file_id else None,
        # W0-06B: the provider's version of the object when it was recorded,
        # and its size — what an integrity check compares to tell "replaced"
        # and "changed" apart from "fine".
        "provider_version_id": ((str(provider_version_id).strip() or None)
                                if provider_version_id else None),
        "expected_size_bytes": size_bytes if isinstance(size_bytes, int)
        and not isinstance(size_bytes, bool) and size_bytes >= 0 else None,
        "role": _require_choice(role, LOCATION_ROLES, "role"),
        "expected_checksum": (checksum(expected_checksum.get("value"),
                                       expected_checksum.get("algorithm", CHECKSUM_SHA256))
                              if expected_checksum else None),
        "observed_checksum": None,
        "observed_size_bytes": None,
        "availability": _require_choice(availability, AVAILABILITY_STATES, "availability"),
        "last_verified_at": None,
        "last_check_error": None,
        # A location is REPLACED, never deleted: a provider migration must leave
        # a readable record of where the file used to be. The field always
        # exists so "the current location" is a filter rather than a guess
        # about a missing key.
        "superseded_at": None,
        # Set only by a CONFIRMED provider receipt of a delete request that
        # named this exact location. Never inferred.
        "destroyed_at_provider": None,
        "destroyed_by_request_id": None,
        "created_at": now,
        "updated_at": now,
    }


# ------------------------------------------------------------ DerivedArtifact
def build_derived(
    *,
    org_id: str,
    file_id: str,
    source_version_no: int,
    kind: str,
    cache_reference: str,
    created_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> Dict[str, Any]:
    """A technical derivative BEG_Work cached for itself.

    ``is_canonical_original`` is written ``False`` and there is no parameter to
    make it anything else: a preview is never the original, a thumbnail is never
    a business version, and a cache entry never answers for a missing file
    (FLOW-016 §"Снимки и технически производни"). The flag is stored rather
    than implied so the static guard and a reader of the raw document both see
    the claim the record makes.
    """
    owner = _require_owner(org_id)
    if not isinstance(source_version_no, int) or isinstance(source_version_no, bool) \
            or source_version_no < 1:
        raise FileRecordInvalid("source_version_no must be an integer >= 1")
    now = created_at or _now_iso()
    return {
        "id": ID_PREFIX_DERIVED + uuid.uuid4().hex,
        ORG_KEY: owner,
        "file_id": _require_text(file_id, "file_id"),
        "source_version_no": source_version_no,
        "kind": _require_choice(kind, DERIVED_KINDS, "kind"),
        "cache_reference": _require_text(cache_reference, "cache_reference"),
        "is_canonical_original": False,
        "regenerable": True,
        "created_at": now,
        "expires_at": expires_at,
    }


# -------------------------------------------------------------- DeleteRequest
def build_delete_request(
    *,
    org_id: str,
    file_id: str,
    requested_by: str,
    reason: str,
    scope: str,
    location_ids: Tuple[str, ...],
    version_no: Optional[int] = None,
    approval_id: Optional[str] = None,
    requested_at: Optional[str] = None,
) -> Dict[str, Any]:
    """An explicit request to destroy the customer's original at the provider.

    Separate from anything the registry does on its own: FLOW-016 forbids
    presenting removal from the File Registry as a guaranteed physical delete.
    The request is answered only by a recorded PROVIDER response.

    ``scope`` is :data:`DELETE_SCOPE_VERSION` (one version, ``version_no``
    required) or :data:`DELETE_SCOPE_FILE` (the whole family, ``version_no``
    forbidden). ``location_ids`` are the exact provider locations the request
    covers, frozen at request time: the provider's answer is applied to these
    rows and to no other, so a receipt for version 1 can never make version 2
    look destroyed.
    """
    owner = _require_owner(org_id)
    _require_choice(scope, DELETE_SCOPES, "delete scope")
    if scope == DELETE_SCOPE_VERSION:
        if not isinstance(version_no, int) or isinstance(version_no, bool) or version_no < 1:
            raise FileRecordInvalid("a version-scoped delete names one version_no >= 1")
    elif version_no is not None:
        raise FileRecordInvalid("a whole-file delete must not name a version_no")
    ids = tuple(location_ids or ())
    if not ids or any(not isinstance(i, str) or not i.strip() for i in ids):
        raise FileRecordInvalid("a delete request must name the exact locations it covers")
    if len(set(ids)) != len(ids):
        raise FileRecordInvalid("a delete request names a location twice")
    now = requested_at or _now_iso()
    return {
        "id": ID_PREFIX_DELETE + uuid.uuid4().hex,
        ORG_KEY: owner,
        "file_id": _require_text(file_id, "file_id"),
        "scope": scope,
        "version_no": version_no,
        "location_ids": sorted(ids),
        "state": DELETE_REQUESTED,
        "requested_by": _require_text(requested_by, "requested_by"),
        "requested_at": now,
        "reason": _require_text(reason, "reason"),
        # FLOW-016 / CLAUDE.md §8: destroying an original is an Approval case.
        # W0-06A records the reference; the DQ/Approval runtime that issues it is
        # W0-05 and is NOT wired here (see W0-06A_FILE_REGISTRY.md §residual).
        "approval_id": approval_id,
        "provider_result": None,
        "resolved_at": None,
    }


def build_provider_result(*, provider_kind: str, state: str, response_code: Optional[str] = None,
                          message: Optional[str] = None, confirmed_at: Optional[str] = None
                          ) -> Dict[str, Any]:
    """The provider's own answer to a delete request — the only thing that may
    move a request out of ``requested``."""
    if state == DELETE_REQUESTED:
        raise FileRecordInvalid("a provider result cannot leave the request unanswered")
    return {
        "provider_kind": _require_choice(provider_kind, PROVIDER_KINDS, "provider_kind"),
        "state": _require_choice(state, DELETE_STATES, "state"),
        "response_code": response_code,
        "message": message,
        "confirmed_at": confirmed_at or _now_iso(),
    }


# ------------------------------------------------------------------ helpers
def is_usable(location: Optional[Mapping[str, Any]]) -> bool:
    """Can the canonical original be served from this location right now?"""
    if not location:
        return False
    return location.get("availability") == AVAILABILITY_AVAILABLE


def severity_of(availability: str, relation_count: int) -> str:
    """FLOW-016 §"Периодична проверка": severity follows the RELATIONS.

    A missing photo attached to nothing is a cache problem; the same failure on
    a file attached to an act, an invoice or a warranty record is a business
    incident, so the number of affected records — not the error itself — decides.
    """
    if availability == AVAILABILITY_AVAILABLE:
        return "none"
    if availability == AVAILABILITY_UNVERIFIED:
        return "info"
    if relation_count == 0:
        return "low"
    if availability in (AVAILABILITY_MISSING, AVAILABILITY_CHECKSUM_MISMATCH,
                        AVAILABILITY_EXTERNALLY_CHANGED):
        return "critical" if relation_count > 1 else "high"
    return "high" if relation_count > 1 else "medium"


def sort_key(record: Mapping[str, Any]) -> Tuple[str, str]:
    """A TOTAL order over records of one tenant.

    Used wherever a choice between several matching records must be the same on
    every run and on every server — duplicate-checksum resolution above all.
    "Whichever one the database returned first" is exactly the non-determinism
    W0-03E removed from the identity lookups.
    """
    return (str(record.get("created_at") or ""), str(record.get("id") or ""))


def file_order_key(record: Mapping[str, Any]) -> Tuple[int, int, str, str]:
    """The TOTAL registration order of File records of one tenant.

    W0-06A review finding 4. :func:`sort_key` orders by ``(created_at, id)``;
    two files registered within one clock tick share ``created_at`` and the
    RANDOM ``id`` then decides, so "the oldest duplicate" silently became "the
    one with the smaller uuid". The order is now led by ``registration_seq`` —
    allocated atomically per tenant, never reused, never rewritten — so the
    first file registered is first on every run, on every server, whatever
    order the database returns rows in and however coarse the clock is.

    A record without a sequence (none exists today: the field was introduced
    before any registry row was written in production) sorts after every
    sequenced one, by the old total order, so the key stays total either way.
    """
    seq = record.get("registration_seq")
    if isinstance(seq, int) and not isinstance(seq, bool):
        return (0, seq, "", str(record.get("id") or ""))
    return (1, 0, str(record.get("created_at") or ""), str(record.get("id") or ""))
