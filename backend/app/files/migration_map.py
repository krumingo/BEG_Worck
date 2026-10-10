"""
W0-06A — the deterministic legacy migration map.

The inventory says WHERE every file-bearing field is today. This module says
what each of them becomes:

    legacy reference -> file_id -> provider location -> relations

It is a PLAN, not a migration. Nothing here opens a database, reads a byte,
copies, moves or deletes a customer file, or touches a provider: W0-06A is
explicitly inventory, contract and foundation. The planner is a pure function
of one legacy row, so the same row produces the same plan on every run, on
every machine, in a dry run and in the eventual real migration — which is what
makes the plan reviewable before anything is executed.

Determinism of ``file_id``
--------------------------

A migrated file's id is derived, not drawn at random:
:func:`deterministic_file_id` hashes ``(org_id, source key, legacy reference)``.
Three consequences, all of them needed:

* re-running the plan maps a legacy row to the SAME ``file_id``, so an
  interrupted migration can be resumed and a plan can be diffed against a
  previous one;
* the same legacy id in two tenants produces two DIFFERENT ``file_id`` values,
  because the owner is inside the hash — the collision case that W0-03E-A2C
  spent a whole cycle on cannot reappear through the migration;
* the id still carries nothing about the provider, the path or the file name,
  so it remains a pure business identity.

What a plan entry promises, and what it does not
------------------------------------------------

Each entry names the legacy reference it came from, the file identity it will
become, the provider location the bytes will be registered at, and the business
relations the row implies. Where the legacy data cannot answer one of those
questions, the entry says so in ``blockers`` and is NOT executable. Nothing is
ASSUMED SAFE: a row with no owner, a context type with no target collection, an
attachment that is an opaque string with no media record behind it — each
becomes a named blocker that a human must resolve before that row migrates.

Stdlib-only: no database, no FastAPI, no I/O.
"""
from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from app.files import models as m

#: Where the legacy bytes physically are today. Not a customer-managed provider
#: and deliberately named so: the whole point of FLOW-016 is that this is the
#: wrong place for a customer original, and the map must be able to say that
#: without pretending the application disk is a provider.
LEGACY_UPLOADS_ROOT = "/app/backend/uploads"
LEGACY_PROJECT_UPLOADS_ROOT = "/app/backend/uploads/projects"

#: The binding id a planned location carries until the tenant's real Primary
#: Storage Provider is connected (FLOW-016 onboarding gate, a later slice).
#: It is a placeholder by name, so no plan can be mistaken for a real target.
UNBOUND_PROVIDER_BINDING = "UNBOUND_PENDING_ONBOARDING"

# ------------------------------------------------------------------ blockers
#: A row cannot be migrated until a human answers. Each is a QUESTION about
#: real data, never a judgement that the row is fine.
BLOCKER_NO_OWNER = "NO_OWNER"
BLOCKER_NO_BYTES = "NO_PHYSICAL_OBJECT"
BLOCKER_OPAQUE_ATTACHMENT = "OPAQUE_ATTACHMENT_REFERENCE"
BLOCKER_UNMAPPED_CONTEXT = "UNMAPPED_CONTEXT_TYPE"
BLOCKER_NO_RELATION = "NO_BUSINESS_RELATION"
BLOCKER_INLINE_BASE64 = "INLINE_BASE64_NOT_A_FILE"
BLOCKER_NO_CHECKSUM = "CHECKSUM_UNKNOWN_UNTIL_READ"
#: The row owns no bytes: it becomes a relation on, or a pointer to, a File
#: that ANOTHER source must register first. Derived rather than declared
#: per source, so a source added later cannot forget it.
BLOCKER_DEPENDS_ON_REGISTERED_FILE = "DEPENDS_ON_A_FILE_NOT_YET_REGISTERED"

BLOCKERS: FrozenSet[str] = frozenset({
    BLOCKER_NO_OWNER, BLOCKER_NO_BYTES, BLOCKER_OPAQUE_ATTACHMENT,
    BLOCKER_UNMAPPED_CONTEXT, BLOCKER_NO_RELATION, BLOCKER_INLINE_BASE64,
    BLOCKER_NO_CHECKSUM, BLOCKER_DEPENDS_ON_REGISTERED_FILE,
})

# --------------------------------------------------------------- the actions
#: The row owns bytes and becomes a File with its own identity.
ACTION_REGISTER = "REGISTER_FILE"
#: The row owns no bytes; it becomes a RELATION on a file another row registers.
ACTION_RELATE = "RELATE_TO_EXISTING_FILE"
#: The field is a provider path/URL that must be REPLACED by a ``file_id``
#: reference once the file it names is registered.
ACTION_REPLACE_WITH_FILE_ID = "REPLACE_POINTER_WITH_FILE_ID"
#: Nothing to migrate, with the reason stated. Never "assumed safe".
ACTION_NONE = "NO_FILE_CONTENT"

#: The legacy media ``context_type`` values (``app.deps.media_acl``) mapped to
#: File Registry relation types. ``message`` is deliberately absent: the active
#: backend has no messages collection, so a media row in that context has no
#: business record to attach to and must be resolved by a human first.
MEDIA_CONTEXT_RELATIONS: Dict[str, str] = {
    "project": m.RELATION_PROJECT,
    "site": m.RELATION_SITE,
    "workReport": m.RELATION_WORK_REPORT,
    "delivery": m.RELATION_DELIVERY,
    "attendance": m.RELATION_ATTENDANCE,
    "machine": m.RELATION_MACHINE,
    "profile": m.RELATION_USER_PROFILE,
    "missingSMR": m.RELATION_DEFECT,
}
#: Context values that exist in the legacy enum with NO target collection.
UNMAPPED_MEDIA_CONTEXTS: FrozenSet[str] = frozenset({"message"})
#: Context values the application writes that are not in the legacy enum at all
#: (``app/routes/ocr_invoice.py`` writes ``ocr_invoice`` with the media row's own
#: id as the context id — a self-reference, not a business relation).
SELF_REFERENTIAL_MEDIA_CONTEXTS: FrozenSet[str] = frozenset({"ocr_invoice"})


def deterministic_file_id(org_id: str, source_key: str, legacy_reference: str) -> str:
    """A stable ``file_id`` for one legacy row of one tenant.

    The owner is inside the digest, so the same legacy id in two tenants never
    produces the same identity. The digest is truncated to 32 hex characters to
    match the shape of a freshly minted :func:`app.files.models.new_file_id`,
    which keeps migrated and native ids indistinguishable to every consumer —
    an id must not reveal that a file arrived through a migration.
    """
    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("a deterministic file_id needs the owning tenant")
    if not isinstance(legacy_reference, str) or not legacy_reference.strip():
        raise ValueError("a deterministic file_id needs a legacy reference")
    digest = hashlib.sha256(
        "\x1f".join((org_id.strip(), source_key, legacy_reference.strip())).encode("utf-8")
    ).hexdigest()
    return m.ID_PREFIX_FILE + digest[:32]


def planned_object_key(org_id: str, file_id: str, original_name: str) -> str:
    """Where the file WOULD sit in the tenant's provider root.

    A provider coordinate derived from the business identity, not the other way
    round: the key exists so a migration can place the object, and nothing ever
    resolves a file by it (FLOW-016 forbids a provider path from being the
    business ID). The tenant segment keeps two tenants' objects apart even when
    they share one bucket.
    """
    suffix = posixpath.splitext(original_name or "")[1].lower()
    if len(suffix) > 12 or any(c in suffix for c in "/\\ "):
        suffix = ""
    return "tenants/%s/files/%s/%s%s" % (org_id, file_id[:10], file_id, suffix)


@dataclass(frozen=True)
class LegacySource:
    """One place the active backend keeps a file or a pointer to one.

    ``key`` is stable and is part of every derived ``file_id``, so renaming a
    source would change the ids it produces — which is why the inventory test
    pins these keys.
    """
    key: str
    collection: str
    #: Human description of the legacy identity: what the row is called today.
    legacy_reference_field: str
    #: The fields that hold a provider path, URL or stored name today.
    pointer_fields: Tuple[str, ...]
    #: Where the bytes physically are, or ``None`` when the row owns no bytes.
    physical_root: Optional[str]
    tenant_field: str
    action: str
    category: str
    sensitivity: str
    #: Prose for the inventory's "business relation" column.
    business_relation: str
    #: Prose for the inventory's "read/write/delete behaviour" column.
    behaviour: str
    #: Prose for the inventory's "migration action" column.
    migration_action: str
    #: Standing blockers that apply to EVERY row of this source.
    standing_blockers: Tuple[str, ...] = ()
    #: The routes/functions that write this source. Named so the guard can
    #: prove the freeze list and the inventory describe the same code.
    writers: Tuple[str, ...] = ()


#: Every file-bearing source of the active backend. This list is the inventory:
#: ``scripts/w0_06a_file_inventory.py`` scans the code and FAILS if it finds a
#: file-bearing site that no source here accounts for, so the list cannot be
#: quietly incomplete.
LEGACY_SOURCES: Tuple[LegacySource, ...] = (
    LegacySource(
        key="media_files",
        collection="media_files",
        legacy_reference_field="id (media_id)",
        pointer_fields=("url", "stored_filename"),
        physical_root=LEGACY_UPLOADS_ROOT,
        tenant_field="org_id",
        action=ACTION_REGISTER,
        category=m.CATEGORY_PHOTO_VIDEO,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation=("exactly ONE, via context_type/context_id — the legacy record "
                           "cannot express a second one, which is the duplication FLOW-016 removes"),
        behaviour=("write: POST /api/media/upload stores bytes on the application disk and "
                   "inserts one row. read: GET /api/media/file/{filename} resolves the row by "
                   "stored_filename. delete: DELETE /api/media/{id} unlinks the file from disk "
                   "AND removes the row — one screen's removal destroys the original"),
        migration_action=("register one File per row; context becomes the first FileRelation; "
                          "url/stored_filename become a ProviderLocation, never the identity"),
        writers=("app/routes/media.py::upload_media",
                 "app/routes/ocr_invoice.py::upload_invoice",
                 "app/routes/technician.py::photo_invoice"),
    ),
    LegacySource(
        key="project_photos",
        collection="project_photos",
        legacy_reference_field="id (photo_id)",
        pointer_fields=("url", "stored_filename"),
        physical_root=LEGACY_PROJECT_UPLOADS_ROOT,
        tenant_field="org_id",
        action=ACTION_REGISTER,
        category=m.CATEGORY_PHOTO_VIDEO,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="project, via project_id (a second project means a second upload today)",
        behaviour=("write: POST /api/projects/{id}/photos writes bytes to uploads/projects and "
                   "inserts one row. read: GET /api/projects/photos/file/{filename}. "
                   "delete: DELETE /api/projects/photos/{id} unlinks the file from disk and "
                   "removes the row"),
        migration_action="register one File per row; project_id becomes a project FileRelation",
        writers=("app/routes/projects.py::upload_project_photo",),
    ),
    LegacySource(
        key="scan_docs",
        collection="scan_docs",
        legacy_reference_field="id (scan_doc_id)",
        pointer_fields=("file_url", "media_id"),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_INVOICES,
        sensitivity=m.SENSITIVITY_RESTRICTED,
        business_relation="invoice, via linked_invoice_id (optional, linked later)",
        behaviour=("write: POST /api/scan-docs records a pointer to a media row the media API "
                   "already created. read: list/detail enrich from invoices. "
                   "delete: DELETE /api/scan-docs/{id} removes the row and then deletes a file "
                   "named by doc['file_path'] or doc['url'] joined onto 'uploads' — a "
                   "provider-path-as-identity delete path, and the fields it reads are not the "
                   "ones the create route writes"),
        migration_action=("no new File: resolve media_id to the File the media_files row "
                          "becomes, then add an invoice FileRelation and replace file_url with "
                          "the file_id"),
        standing_blockers=(BLOCKER_OPAQUE_ATTACHMENT,),
        writers=("app/routes/scan_docs.py::create_scan_doc",),
    ),
    LegacySource(
        key="supplier_invoice_file",
        collection="supplier_invoices",
        legacy_reference_field="original_file_url (the generated uuid filename)",
        pointer_fields=("original_file_url", "original_file_name"),
        physical_root=LEGACY_UPLOADS_ROOT,
        tenant_field="org_id",
        action=ACTION_REGISTER,
        category=m.CATEGORY_INVOICES,
        sensitivity=m.SENSITIVITY_RESTRICTED,
        business_relation="supplier_invoice, via the invoice row the file was uploaded onto",
        behaviour=("write: POST /api/supplier-invoices/{id}/upload-file writes bytes to the "
                   "uploads root and stores the URL '/api/media/{uuid.ext}' on the invoice. "
                   "read: no route serves that URL — the media route serves "
                   "'/api/media/file/{filename}' and requires a media_files row this path never "
                   "creates. delete: none; the bytes are never removed"),
        migration_action=("register one File per invoice that has a file; add a "
                          "supplier_invoice FileRelation; replace original_file_url with the "
                          "file_id. The unreachable-URL defect is recorded as debt and is NOT "
                          "fixed by W0-06A (CLAUDE.md §18)"),
        writers=("app/routes/procurement.py::create_supplier_invoice",
                 "app/routes/procurement.py::upload_invoice_file"),
    ),
    LegacySource(
        key="missing_smr_attachments",
        collection="missing_smr",
        legacy_reference_field="attachments[].media_id",
        pointer_fields=("attachments[].url", "attachments[].filename"),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_DEFECTS,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="defect, via the missing_smr row the attachment array lives on",
        behaviour=("write: POST /api/missing-smr/{id}/attachments pushes {media_id,url,filename} "
                   "onto an embedded array; the mobile report path writes the array inline from "
                   "a list of photo ids. read: the array is returned verbatim. "
                   "delete: DELETE .../attachments/{media_id} pulls the entry and leaves the "
                   "media row and the bytes untouched"),
        migration_action=("no new File: each media_id becomes a defect FileRelation on the File "
                          "the media_files row becomes; the embedded array is replaced by "
                          "relations"),
        standing_blockers=(BLOCKER_OPAQUE_ATTACHMENT,),
        writers=("app/routes/missing_smr.py::add_attachment",
                 "app/routes/missing_smr.py::create_missing_smr",
                 "app/routes/technician.py::quick_smr",
                 "app/routes/technician.py::submit_daily_report"),
    ),
    LegacySource(
        key="daily_work_log_attachments",
        collection="daily_work_logs",
        legacy_reference_field="attachments[] (opaque strings)",
        pointer_fields=("attachments[]",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_DAILY_REPORTS,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="daily_report, via the daily_work_logs row",
        behaviour=("write: POST/PUT /api/daily-logs store a caller-supplied list of strings with "
                   "no validation of what they reference. read: returned verbatim. "
                   "delete: the whole log row is hard-deleted, taking its attachment list with it"),
        migration_action=("resolve each string to a media_files id where possible and add a "
                          "daily_report FileRelation; a string that resolves to nothing is a "
                          "blocker for a human, never dropped"),
        standing_blockers=(BLOCKER_OPAQUE_ATTACHMENT,),
        writers=("app/routes/work_logs.py::create_daily_log",
                 "app/routes/work_logs.py::update_daily_log"),
    ),
    LegacySource(
        key="change_order_attachments",
        collection="change_orders",
        legacy_reference_field="attachments[] (opaque strings)",
        pointer_fields=("attachments[]",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_CONTRACTS,
        sensitivity=m.SENSITIVITY_RESTRICTED,
        business_relation="annex, via the change_orders row",
        behaviour=("write: POST/PUT /api/change-orders store a caller-supplied list of strings. "
                   "read: returned verbatim. delete: no attachment-level delete"),
        migration_action=("resolve each string to a media_files id where possible and add an "
                          "annex FileRelation; unresolved strings are blockers"),
        standing_blockers=(BLOCKER_OPAQUE_ATTACHMENT,),
        writers=("app/routes/work_logs.py::create_change_order",
                 "app/routes/work_logs.py::update_change_order"),
    ),
    LegacySource(
        key="pending_expense_receipt",
        collection="pending_expenses",
        legacy_reference_field="media_id",
        pointer_fields=("media_url",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_INVOICES,
        sensitivity=m.SENSITIVITY_RESTRICTED,
        business_relation="expense, via the pending_expenses row (and project, via project_id)",
        behaviour=("write: the technician expense route creates the media row itself and copies "
                   "its id and url onto the expense. read: media_url is handed to the client. "
                   "delete: none"),
        migration_action=("no new File: add an expense FileRelation on the File the media row "
                          "becomes and replace media_url with the file_id"),
        writers=("app/routes/technician.py::photo_invoice",
                 "app/routes/ocr_invoice.py::approve_intake"),
    ),
    LegacySource(
        key="asset_intake_photo",
        collection="asset_intake_pending",
        legacy_reference_field="id (the pending intake row)",
        pointer_fields=("photo_b64",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_REGISTER,
        category=m.CATEGORY_PHOTO_VIDEO,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="asset, after the intake is approved and materialised into asset_items",
        behaviour=("write: the field-intake route stores the photo as base64 INSIDE the database "
                   "row — there is no file and no provider object at all. read: returned inline. "
                   "delete: the row, and with it the only copy of the photo"),
        migration_action=("decode the base64 to bytes, register one File, upload to the tenant's "
                          "provider, add an asset FileRelation and replace the inline payload "
                          "with the file_id. Requires bytes to be written to a provider, so it "
                          "cannot run before provider onboarding"),
        standing_blockers=(BLOCKER_INLINE_BASE64,),
        writers=("app/routes/assets_intake_pending.py::submit_intake",),
    ),
    LegacySource(
        key="asset_item_photo",
        collection="asset_items",
        legacy_reference_field="id (the asset item)",
        pointer_fields=("photo_url",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_REPLACE_WITH_FILE_ID,
        category=m.CATEGORY_PHOTO_VIDEO,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="asset, via the asset_items row itself",
        behaviour=("write: materialising an approved intake copies the pending row's base64 into "
                   "photo_url as a 'data:' URI — a second copy of the same image in a second "
                   "collection, which is exactly the per-module duplication FLOW-016 forbids. "
                   "read: handed to the client inline. delete: none"),
        migration_action=("do NOT register a second File: point the asset at the file_id the "
                          "intake photo became, add an asset FileRelation, and clear photo_url"),
        standing_blockers=(BLOCKER_INLINE_BASE64,),
        writers=("app/routes/assets_intake_pending.py::_materialize",
                 "app/routes/assets_items.py::create_asset_item"),
    ),
    LegacySource(
        key="user_avatar",
        collection="users",
        legacy_reference_field="avatar_url",
        pointer_fields=("avatar_url",),
        physical_root=LEGACY_UPLOADS_ROOT,
        tenant_field="org_id",
        action=ACTION_REPLACE_WITH_FILE_ID,
        category=m.CATEGORY_OTHER,
        sensitivity=m.SENSITIVITY_RESTRICTED,
        business_relation="user_profile, via the users row",
        behaviour=("write: NO active backend route writes avatar_url — the field is only read, "
                   "by eleven report and dossier routes. read: returned to the client as a URL. "
                   "serve: GET /api/media/avatar/{filename} — before W0-06B it served any file "
                   "in the uploads root without authentication or a media row (another tenant's "
                   "bytes by name alone); since W0-06B/C02 it requires a signed-in session and "
                   "serves only a profile-context upload that is the CURRENT avatar_url of a user "
                   "of the CALLER's tenant, and 404s everything else"),
        migration_action=("register a File per existing avatar, add a user_profile FileRelation "
                          "and replace avatar_url with the file_id. The frontend loads avatars "
                          "with an authenticated request (components/AuthImage.js); there is no "
                          "public avatar URL"),
        standing_blockers=(BLOCKER_NO_BYTES,),
        writers=(),
    ),
    LegacySource(
        key="excel_import_templates",
        collection="excel_import_templates",
        legacy_reference_field="id (template)",
        pointer_fields=(),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_NONE,
        category=m.CATEGORY_OTHER,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="none — the row is a column mapping, not a document",
        behaviour=("write: a parsed column mapping is stored; the uploaded spreadsheet itself is "
                   "read in memory and never persisted. read/delete: ordinary CRUD on the mapping"),
        migration_action=("nothing to migrate: no bytes and no pointer exist. Listed because the "
                          "collection sits in the ownership FAMILY_FILES group and a reader must "
                          "see the verdict rather than its absence"),
        writers=("app/services/excel_import_v2.py::save_import_template",),
    ),
    LegacySource(
        key="extra_work_photos",
        collection="extra_work_drafts",
        legacy_reference_field="photos[] (media ids)",
        pointer_fields=("photos[]",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_PHOTO_VIDEO,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="extra_work, via the extra_work_drafts row (and project, via project_id)",
        behaviour=("write: the extra-work routes store a list of media ids on the draft; the "
                   "bridge from a defect copies the defect's attachment media ids into it, "
                   "which is a SECOND list of references to the same photos. read: returned "
                   "verbatim. delete: none"),
        migration_action=("no new File: each media id becomes an extra_work FileRelation on the "
                          "File the media row becomes; the duplicated list disappears because "
                          "one file can carry both relations"),
        standing_blockers=(BLOCKER_OPAQUE_ATTACHMENT,),
        writers=("app/routes/extra_works.py::create_extra_work",
                 "app/routes/extra_works.py::batch_save_drafts",
                 "app/routes/missing_smr.py::bridge_to_analysis"),
    ),
    LegacySource(
        key="work_report_photos",
        collection="work_reports",
        legacy_reference_field="photos[] (media ids)",
        pointer_fields=("photos[]",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_DAILY_REPORTS,
        sensitivity=m.SENSITIVITY_STANDARD,
        business_relation="work_report, via the work_reports row (and project, via project_id)",
        behaviour=("write: the technician daily-report route stores the caller's list of media "
                   "ids, and re-stores it wholesale on every resubmission of the same day. "
                   "read: returned verbatim. delete: none"),
        migration_action=("no new File: each media id becomes a work_report FileRelation; "
                          "re-submitting a report then adds or removes relations instead of "
                          "replacing a list"),
        standing_blockers=(BLOCKER_OPAQUE_ATTACHMENT,),
        writers=("app/routes/technician.py::submit_daily_report",),
    ),
    LegacySource(
        key="invoice_scan_pointer",
        collection="invoices",
        legacy_reference_field="scan_doc_id",
        pointer_fields=("scan_doc_id",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_REPLACE_WITH_FILE_ID,
        category=m.CATEGORY_INVOICES,
        sensitivity=m.SENSITIVITY_RESTRICTED,
        business_relation="invoice — the financial record the scanned document belongs to",
        behaviour=("write: POST /api/scan-docs/{id}/link sets scan_doc_id on the invoice and "
                   "linked_invoice_id on the scan doc — the same link stored twice, in two "
                   "collections, with nothing keeping them consistent. unlink clears both. "
                   "delete: deleting the scan doc clears the invoice side"),
        migration_action=("the link becomes ONE invoice FileRelation on the file; both "
                          "scan_doc_id and linked_invoice_id are then redundant and are "
                          "removed by the slice that migrates them"),
        writers=("app/routes/scan_docs.py::link_scan_to_invoice",
                 "app/routes/scan_docs.py::unlink_scan_from_invoice"),
    ),
    LegacySource(
        key="ocr_intake_media",
        collection="ocr_invoice_intake",
        legacy_reference_field="media_id",
        pointer_fields=("media_id",),
        physical_root=None,
        tenant_field="org_id",
        action=ACTION_RELATE,
        category=m.CATEGORY_INVOICES,
        sensitivity=m.SENSITIVITY_RESTRICTED,
        business_relation=("ocr_intake, via the intake row; the business invoice relation "
                           "arrives only when the intake is approved into an expense"),
        behaviour=("write: the OCR service stores the media id of the scanned document on the "
                   "intake row. read: the raw-text route re-reads the file from the application "
                   "disk by joining the uploads root with the media row's stored_filename. "
                   "delete: none"),
        migration_action=("no new File: the media id becomes an ocr_intake FileRelation, and "
                          "the re-read path takes the original through the provider adapter "
                          "instead of an application disk path"),
        writers=("app/services/ocr_invoice.py::create_ocr_intake",),
    ),
)

SOURCES_BY_KEY: Dict[str, LegacySource] = {s.key: s for s in LEGACY_SOURCES}

#: Every legacy collection a source accounts for.
COVERED_COLLECTIONS: FrozenSet[str] = frozenset(s.collection for s in LEGACY_SOURCES)


@dataclass(frozen=True)
class PlannedRelation:
    relation_type: str
    record_id: str
    source_field: str


@dataclass(frozen=True)
class PlanEntry:
    """What one legacy row becomes. Pure data; executing it is a later slice."""
    source_key: str
    collection: str
    legacy_reference: str
    org_id: Optional[str]
    action: str
    file_id: Optional[str]
    provider_object_key: Optional[str]
    provider_kind: str
    provider_binding_id: str
    current_physical_location: Optional[str]
    relations: Tuple[PlannedRelation, ...] = ()
    blockers: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()

    @property
    def executable(self) -> bool:
        """A plan entry with any blocker is NOT executable. No exceptions."""
        return not self.blockers

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_key": self.source_key,
            "collection": self.collection,
            "legacy_reference": self.legacy_reference,
            "org_id": self.org_id,
            "action": self.action,
            "file_id": self.file_id,
            "provider_kind": self.provider_kind,
            "provider_binding_id": self.provider_binding_id,
            "provider_object_key": self.provider_object_key,
            "current_physical_location": self.current_physical_location,
            "relations": [{"relation_type": r.relation_type, "record_id": r.record_id,
                           "source_field": r.source_field} for r in self.relations],
            "blockers": list(self.blockers),
            "notes": list(self.notes),
            "executable": self.executable,
        }


def _legacy_reference(source: LegacySource, row: Mapping[str, Any]) -> Optional[str]:
    """The stable thing this row is called today."""
    if source.key == "supplier_invoice_file":
        return row.get("original_file_url") or None
    if source.key == "user_avatar":
        return row.get("avatar_url") or None
    return row.get("id") or None


def _relations_for(source: LegacySource, row: Mapping[str, Any]
                   ) -> Tuple[List[PlannedRelation], List[str], List[str]]:
    """``(relations, blockers, notes)`` implied by one legacy row."""
    relations: List[PlannedRelation] = []
    blockers: List[str] = []
    notes: List[str] = []

    if source.key == "media_files":
        ctx_type, ctx_id = row.get("context_type"), row.get("context_id")
        if not ctx_type or not ctx_id:
            blockers.append(BLOCKER_NO_RELATION)
            notes.append("media row has no context; a human must say what it belongs to")
        elif ctx_type in SELF_REFERENTIAL_MEDIA_CONTEXTS:
            # ``ocr_invoice`` stores the media row's OWN id as its context id.
            # That is a self-reference, not a business relation, and turning it
            # into one would invent a link that does not exist.
            notes.append("context %r points at the media row itself; the real relation is the "
                         "OCR intake that references this media_id" % ctx_type)
            blockers.append(BLOCKER_NO_RELATION)
        elif ctx_type in UNMAPPED_MEDIA_CONTEXTS:
            blockers.append(BLOCKER_UNMAPPED_CONTEXT)
            notes.append("context %r has no target collection in the active backend" % ctx_type)
        elif ctx_type not in MEDIA_CONTEXT_RELATIONS:
            blockers.append(BLOCKER_UNMAPPED_CONTEXT)
            notes.append("unknown context %r" % ctx_type)
        else:
            relations.append(PlannedRelation(MEDIA_CONTEXT_RELATIONS[ctx_type], str(ctx_id),
                                             "context_type/context_id"))
    elif source.key == "project_photos":
        if row.get("project_id"):
            relations.append(PlannedRelation(m.RELATION_PROJECT, str(row["project_id"]),
                                             "project_id"))
        else:
            blockers.append(BLOCKER_NO_RELATION)
    elif source.key == "scan_docs":
        if row.get("linked_invoice_id"):
            relations.append(PlannedRelation(m.RELATION_INVOICE, str(row["linked_invoice_id"]),
                                             "linked_invoice_id"))
        else:
            notes.append("not linked to an invoice yet; the file keeps its identity and gains "
                         "the relation when it is linked")
        if not row.get("media_id"):
            notes.append("no media_id: file_url is the only pointer and may not resolve")
    elif source.key == "supplier_invoice_file":
        if row.get("id"):
            relations.append(PlannedRelation(m.RELATION_SUPPLIER_INVOICE, str(row["id"]), "id"))
        if row.get("project_id"):
            relations.append(PlannedRelation(m.RELATION_PROJECT, str(row["project_id"]),
                                             "project_id"))
    elif source.key == "missing_smr_attachments":
        if row.get("id"):
            relations.append(PlannedRelation(m.RELATION_DEFECT, str(row["id"]), "id"))
    elif source.key == "daily_work_log_attachments":
        if row.get("id"):
            relations.append(PlannedRelation(m.RELATION_DAILY_REPORT, str(row["id"]), "id"))
        if row.get("site_id"):
            relations.append(PlannedRelation(m.RELATION_PROJECT, str(row["site_id"]), "site_id"))
    elif source.key == "change_order_attachments":
        if row.get("id"):
            relations.append(PlannedRelation(m.RELATION_ANNEX, str(row["id"]), "id"))
    elif source.key == "pending_expense_receipt":
        if row.get("id"):
            relations.append(PlannedRelation(m.RELATION_EXPENSE, str(row["id"]), "id"))
        if row.get("project_id"):
            relations.append(PlannedRelation(m.RELATION_PROJECT, str(row["project_id"]),
                                             "project_id"))
    elif source.key == "asset_intake_photo":
        if row.get("matched_item_id"):
            relations.append(PlannedRelation(m.RELATION_ASSET, str(row["matched_item_id"]),
                                             "matched_item_id"))
        else:
            notes.append("intake not yet materialised; the asset relation is added when it is")
    elif source.key == "asset_item_photo":
        if row.get("id"):
            relations.append(PlannedRelation(m.RELATION_ASSET, str(row["id"]), "id"))
    elif source.key == "user_avatar":
        if row.get("id"):
            relations.append(PlannedRelation(m.RELATION_USER_PROFILE, str(row["id"]), "id"))

    return relations, blockers, notes


def plan_row(source: LegacySource, row: Mapping[str, Any]) -> PlanEntry:
    """The plan for ONE legacy row. Pure: same row in, same plan out."""
    org_id = row.get(source.tenant_field)
    org_id = org_id.strip() if isinstance(org_id, str) and org_id.strip() else None
    reference = _legacy_reference(source, row)

    blockers: List[str] = list(source.standing_blockers)
    notes: List[str] = []
    if org_id is None:
        # W0-03E-A2B backfilled the legacy collections, so this should be empty
        # in practice. It is still checked per row: a plan that assumed the
        # backfill is complete would silently migrate an ownerless file into
        # whichever tenant happened to be running the job.
        blockers.append(BLOCKER_NO_OWNER)
    if reference is None:
        blockers.append(BLOCKER_NO_BYTES)
        notes.append("no legacy reference on this row")

    relations, relation_blockers, relation_notes = _relations_for(source, row)
    blockers.extend(relation_blockers)
    notes.extend(relation_notes)

    if source.action == ACTION_NONE:
        return PlanEntry(source_key=source.key, collection=source.collection,
                         legacy_reference=reference or "", org_id=org_id, action=ACTION_NONE,
                         file_id=None, provider_object_key=None,
                         provider_kind=m.PROVIDER_LEGACY_APP_DISK,
                         provider_binding_id=UNBOUND_PROVIDER_BINDING,
                         current_physical_location=None, relations=(),
                         blockers=(), notes=tuple(notes) or ("no file content",))

    file_id = (deterministic_file_id(org_id, source.key, reference)
               if org_id and reference else None)
    original_name = (row.get("filename") or row.get("original_filename")
                     or row.get("original_file_name") or reference or "")
    object_key = (planned_object_key(org_id, file_id, str(original_name))
                  if org_id and file_id and source.action == ACTION_REGISTER else None)

    physical = None
    if source.physical_root and row.get("stored_filename"):
        physical = posixpath.join(source.physical_root, str(row["stored_filename"]))
    elif source.physical_root and reference:
        physical = posixpath.join(source.physical_root, posixpath.basename(str(reference)))

    if source.action == ACTION_REGISTER and not row.get("checksum"):
        # No legacy row stores a checksum. The migration must read the bytes to
        # compute one, which is a provider operation — so no REGISTER row is
        # executable in W0-06A, and the plan says so instead of implying a
        # checksum it does not have.
        blockers.append(BLOCKER_NO_CHECKSUM)
    elif source.action in (ACTION_RELATE, ACTION_REPLACE_WITH_FILE_ID):
        # This row owns no bytes: it points at a File that a REGISTER row must
        # create first, and no REGISTER row can run yet (see above). Derived
        # from the action rather than declared per source, so the dependency
        # holds for every source of this shape, including ones added later.
        blockers.append(BLOCKER_DEPENDS_ON_REGISTERED_FILE)

    return PlanEntry(
        source_key=source.key, collection=source.collection,
        legacy_reference=reference or "", org_id=org_id, action=source.action,
        file_id=file_id, provider_object_key=object_key,
        provider_kind=m.PROVIDER_LEGACY_APP_DISK,
        provider_binding_id=UNBOUND_PROVIDER_BINDING,
        current_physical_location=physical,
        relations=tuple(relations),
        # Sorted and de-duplicated so two runs produce byte-identical plans.
        blockers=tuple(sorted(set(blockers))), notes=tuple(notes))


def plan_rows(rows_by_source: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[PlanEntry]:
    """Plan several sources at once, in a stable order.

    Sorted by ``(source key, legacy reference)`` rather than by iteration order,
    so a plan produced from a cursor and a plan produced from a fixture compare
    equal.
    """
    out: List[PlanEntry] = []
    for key in sorted(rows_by_source):
        source = SOURCES_BY_KEY[key]
        for row in rows_by_source[key]:
            out.append(plan_row(source, row))
    return sorted(out, key=lambda e: (e.source_key, e.legacy_reference, e.org_id or ""))


def summarise(entries: Sequence[PlanEntry]) -> Dict[str, Any]:
    """Counts a reviewer reads before approving a migration.

    ``no_content`` is counted apart from ``executable``: a row with nothing to
    migrate is neither work to do nor work that is blocked, and folding it into
    either number would misstate how much of the migration is ready.
    """
    by_action: Dict[str, int] = {}
    by_blocker: Dict[str, int] = {}
    for e in entries:
        by_action[e.action] = by_action.get(e.action, 0) + 1
        for b in e.blockers:
            by_blocker[b] = by_blocker.get(b, 0) + 1
    with_content = [e for e in entries if e.action != ACTION_NONE]
    return {
        "entries": len(entries),
        "no_content": len(entries) - len(with_content),
        "executable": sum(1 for e in with_content if e.executable),
        "blocked": sum(1 for e in with_content if not e.executable),
        "by_action": dict(sorted(by_action.items())),
        "by_blocker": dict(sorted(by_blocker.items())),
        "relations_planned": sum(len(e.relations) for e in entries),
    }
