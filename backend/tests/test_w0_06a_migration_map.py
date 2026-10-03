"""
W0-06A — the legacy migration map is deterministic, complete and honest.

The map is a PLAN. It will be reviewed before anything is executed and then
executed against real customer data, so three properties matter more than
anything it contains:

*Deterministic.* The same legacy row must produce the same plan every time, on
every machine — otherwise a plan cannot be diffed, an interrupted migration
cannot be resumed, and a review approves something other than what runs.

*Tenant-safe by construction.* The derived ``file_id`` must differ per tenant
for the same legacy id, or the migration would re-create the exact collision
W0-03E spent three cycles removing.

*Honest.* Every row the legacy data cannot fully answer must come out BLOCKED
with a named reason. A plan that quietly skips, guesses or drops a row is worse
than no plan, because it looks finished.

    pytest tests/test_w0_06a_migration_map.py -v --noconftest
"""
import pytest

from app.files import migration_map as mm
from app.files import models as m


ROW_MEDIA = {"id": "m-1", "org_id": "BEG", "stored_filename": "abc.jpg",
             "filename": "site.jpg", "url": "/api/media/file/abc.jpg",
             "context_type": "project", "context_id": "P-1", "checksum": None}


# ═══════════════════════════════════════════════════════════ determinism
class TestDeterminism:
    def test_the_same_row_plans_identically_every_time(self):
        plans = [mm.plan_row(mm.SOURCES_BY_KEY["media_files"], dict(ROW_MEDIA))
                 for _ in range(5)]
        assert all(p.as_dict() == plans[0].as_dict() for p in plans)

    def test_a_derived_file_id_is_stable_and_tenant_scoped(self):
        a = mm.deterministic_file_id("BEG", "media_files", "m-1")
        assert a == mm.deterministic_file_id("BEG", "media_files", "m-1")
        assert a != mm.deterministic_file_id("TCB", "media_files", "m-1")
        assert a != mm.deterministic_file_id("BEG", "project_photos", "m-1")
        assert a != mm.deterministic_file_id("BEG", "media_files", "m-2")

    def test_a_derived_id_is_shaped_like_a_native_one(self):
        """A consumer must not be able to tell a migrated file from a new one."""
        derived = mm.deterministic_file_id("BEG", "media_files", "m-1")
        native = m.new_file_id()
        assert derived.startswith(m.ID_PREFIX_FILE)
        assert len(derived) == len(native)

    def test_a_derived_id_needs_both_an_owner_and_a_reference(self):
        for org, ref in (("", "m-1"), ("  ", "m-1"), ("BEG", ""), ("BEG", "   ")):
            with pytest.raises(ValueError):
                mm.deterministic_file_id(org, "media_files", ref)

    def test_plan_rows_is_ordered_independently_of_input_order(self):
        rows = [dict(ROW_MEDIA, id="m-%d" % i) for i in range(5)]
        forward = [e.as_dict() for e in mm.plan_rows({"media_files": rows})]
        backward = [e.as_dict() for e in mm.plan_rows({"media_files": list(reversed(rows))})]
        assert forward == backward

    def test_blockers_are_sorted_and_deduplicated(self):
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"],
                            {"id": "m-1", "context_type": "message", "context_id": "x"})
        assert list(entry.blockers) == sorted(set(entry.blockers))


# ═════════════════════════════════════════════════════════ what it produces
class TestPlanShape:
    def test_a_media_row_becomes_identity_location_and_relation(self):
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"], ROW_MEDIA)
        assert entry.action == mm.ACTION_REGISTER
        assert entry.legacy_reference == "m-1"
        assert entry.file_id == mm.deterministic_file_id("BEG", "media_files", "m-1")
        assert entry.current_physical_location == "/app/backend/uploads/abc.jpg"
        assert [(r.relation_type, r.record_id) for r in entry.relations] == \
            [(m.RELATION_PROJECT, "P-1")]

    def test_the_planned_object_key_is_derived_from_the_identity_not_the_name(self):
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"], ROW_MEDIA)
        assert entry.provider_object_key.startswith("tenants/BEG/files/")
        assert entry.file_id in entry.provider_object_key
        assert "site.jpg" not in entry.provider_object_key
        assert entry.provider_object_key.endswith(".jpg")

    def test_the_planned_key_separates_tenants_even_in_one_container(self):
        a = mm.planned_object_key("BEG", "file_aaaa", "x.pdf")
        b = mm.planned_object_key("TCB", "file_aaaa", "x.pdf")
        assert a.startswith("tenants/BEG/") and b.startswith("tenants/TCB/") and a != b

    def test_a_hostile_file_name_cannot_escape_the_planned_key(self):
        key = mm.planned_object_key("BEG", "file_x", "../../etc/passwd")
        assert ".." not in key.split("/")[-1]
        assert mm.planned_object_key("BEG", "file_x", "a" * 40 + ".verylongextension") \
            .endswith("file_x")

    def test_no_plan_entry_points_at_a_real_provider(self):
        """W0-06A activates nothing: every planned location is the application
        disk, bound to a placeholder, until provider onboarding runs."""
        entries = mm.plan_rows({"media_files": [ROW_MEDIA]})
        for entry in entries:
            assert entry.provider_kind == m.PROVIDER_LEGACY_APP_DISK
            assert entry.provider_binding_id == mm.UNBOUND_PROVIDER_BINDING
            assert entry.provider_kind not in m.CUSTOMER_MANAGED_PROVIDER_KINDS


# ══════════════════════════════════════════════════════════════ honesty
class TestNothingIsAssumedSafe:
    def test_an_ownerless_row_is_blocked_not_guessed_into_a_tenant(self):
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"],
                            dict(ROW_MEDIA, org_id=None))
        assert mm.BLOCKER_NO_OWNER in entry.blockers
        assert entry.file_id is None
        assert entry.executable is False

    def test_a_row_with_no_context_is_blocked_not_attached_to_nothing(self):
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"],
                            {"id": "m-1", "org_id": "BEG", "stored_filename": "a.jpg"})
        assert mm.BLOCKER_NO_RELATION in entry.blockers

    def test_the_message_context_has_no_target_and_says_so(self):
        """``message`` is in the legacy context enum and has no collection in
        the active backend. A migration cannot invent one."""
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"],
                            dict(ROW_MEDIA, context_type="message", context_id="x"))
        assert mm.BLOCKER_UNMAPPED_CONTEXT in entry.blockers
        assert any("no target collection" in n for n in entry.notes)
        assert "message" not in mm.MEDIA_CONTEXT_RELATIONS

    def test_the_self_referential_ocr_context_is_not_turned_into_a_relation(self):
        """``ocr_invoice`` stores the media row's OWN id as its context id.
        Reading that as a business relation would invent a link."""
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"],
                            dict(ROW_MEDIA, context_type="ocr_invoice", context_id="m-1"))
        assert entry.relations == ()
        assert mm.BLOCKER_NO_RELATION in entry.blockers

    def test_no_register_row_is_executable_without_a_checksum(self):
        """No legacy row stores one, so computing it means READING the bytes —
        a provider operation W0-06A does not perform."""
        entry = mm.plan_row(mm.SOURCES_BY_KEY["media_files"], ROW_MEDIA)
        assert mm.BLOCKER_NO_CHECKSUM in entry.blockers
        assert entry.executable is False

    def test_the_inline_base64_sources_are_blocked_as_such(self):
        for key in ("asset_intake_photo", "asset_item_photo"):
            entry = mm.plan_row(mm.SOURCES_BY_KEY[key],
                                {"id": "a-1", "org_id": "BEG", "photo_b64": "data:..."})
            assert mm.BLOCKER_INLINE_BASE64 in entry.blockers, key

    def test_the_opaque_attachment_sources_are_blocked_as_such(self):
        for key in ("daily_work_log_attachments", "change_order_attachments",
                    "missing_smr_attachments", "scan_docs", "extra_work_photos",
                    "work_report_photos"):
            entry = mm.plan_row(mm.SOURCES_BY_KEY[key],
                                {"id": "x-1", "org_id": "BEG"})
            assert mm.BLOCKER_OPAQUE_ATTACHMENT in entry.blockers, key

    def test_the_no_content_source_is_a_verdict_not_a_blocker(self):
        entry = mm.plan_row(mm.SOURCES_BY_KEY["excel_import_templates"],
                            {"id": "t-1", "org_id": "BEG"})
        assert entry.action == mm.ACTION_NONE
        assert entry.blockers == ()
        assert entry.file_id is None
        assert entry.notes

    def test_a_no_content_row_is_counted_apart_from_executable_work(self):
        """A row with nothing to migrate is neither done nor blocked."""
        summary = mm.summarise(mm.plan_rows({
            "excel_import_templates": [{"id": "t-1", "org_id": "BEG"}],
            "media_files": [dict(ROW_MEDIA)]}))
        assert summary["entries"] == 2
        assert summary["no_content"] == 1
        assert summary["executable"] == 0 and summary["blocked"] == 1

    def test_nothing_in_the_plan_is_executable_in_w0_06a(self):
        """The whole point: W0-06A produces the plan and moves no file."""
        rows = {key: [{"id": "x-1", "org_id": "BEG", "stored_filename": "a.jpg",
                       "context_type": "project", "context_id": "P-1",
                       "original_file_url": "/api/media/u.pdf", "avatar_url": "/a.jpg",
                       "project_id": "P-1", "linked_invoice_id": "I-1",
                       "matched_item_id": "A-1", "media_id": "m-1", "site_id": "P-1"}]
                for key in mm.SOURCES_BY_KEY}
        entries = mm.plan_rows(rows)
        content_bearing = [e for e in entries if e.action != mm.ACTION_NONE]
        assert content_bearing, "the fixture must exercise the real sources"
        assert all(not e.executable for e in content_bearing), \
            [e.source_key for e in content_bearing if e.executable]


# ═══════════════════════════════════════════════════════════ coverage
class TestCoverage:
    def test_every_source_key_is_unique_and_stable(self):
        keys = [s.key for s in mm.LEGACY_SOURCES]
        assert len(keys) == len(set(keys))
        # The key is part of every derived file_id, so renaming one silently
        # re-maps every file it produced. Pinned here on purpose.
        assert set(keys) == {
            "media_files", "project_photos", "scan_docs", "supplier_invoice_file",
            "missing_smr_attachments", "daily_work_log_attachments",
            "change_order_attachments", "pending_expense_receipt", "asset_intake_photo",
            "asset_item_photo", "user_avatar", "excel_import_templates",
            "extra_work_photos", "work_report_photos", "invoice_scan_pointer",
            "ocr_intake_media"}

    def test_every_issue_43_minimum_family_is_covered(self):
        collections = {s.collection for s in mm.LEGACY_SOURCES}
        for required in ("media_files",                 # uploads / media / photos
                         "project_photos",              # project files
                         "supplier_invoices",           # invoice attachments
                         "scan_docs",                   # OCR / document import
                         "daily_work_logs",             # daily reports
                         "work_reports",                # field daily reports
                         "change_orders",               # annex attachments
                         "missing_smr",                 # defect media
                         "asset_items",                 # asset files
                         "asset_intake_pending",        # asset intake photos
                         "ocr_invoice_intake",          # OCR import path
                         "users",                       # avatars
                         "invoices"):                   # provider pointer on a record
            assert required in collections, required

    def test_every_media_context_type_has_a_verdict(self):
        """Nothing in the legacy enum is left unaddressed."""
        from app.deps import media_acl
        for context in media_acl.MEDIA_CONTEXT_TYPES:
            assert (context in mm.MEDIA_CONTEXT_RELATIONS
                    or context in mm.UNMAPPED_MEDIA_CONTEXTS), context

    def test_every_mapped_context_resolves_to_a_real_relation_type(self):
        for context, relation in mm.MEDIA_CONTEXT_RELATIONS.items():
            assert relation in m.RELATION_TYPES, context
            assert relation in m.RELATION_TARGETS

    def test_every_declared_writer_is_a_path_and_a_function(self):
        for source in mm.LEGACY_SOURCES:
            for writer in source.writers:
                path, sep, function = writer.partition("::")
                assert sep == "::" and path.endswith(".py") and function, writer

    def test_the_summary_counts_what_a_reviewer_needs(self):
        entries = mm.plan_rows({"media_files": [ROW_MEDIA, dict(ROW_MEDIA, id="m-2")]})
        summary = mm.summarise(entries)
        assert summary["entries"] == 2
        assert summary["blocked"] == 2 and summary["executable"] == 0
        assert summary["no_content"] == 0
        assert summary["relations_planned"] == 2
        assert mm.BLOCKER_NO_CHECKSUM in summary["by_blocker"]
