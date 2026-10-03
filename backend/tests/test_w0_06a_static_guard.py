"""
W0-06A — the static guard, proven by MUTATION.

A guard that only reports "0 violations" proves nothing: a guard with a typo in
its rule reports exactly the same thing. So every rule here is tested twice —
the real tree must be clean, and a deliberately broken copy of a real module
must be REJECTED, with that rule, on that line.

Each mutation is the exact mistake the rule exists to stop:

* writing a File Registry collection outside the registry service;
* building a registry record without its owner;
* assembling a FileRelation by hand, or with a hard-coded tenant;
* storing a provider path/URL as a file's identity at a NEW site;
* deleting a stored object with ``os.remove`` / ``Path.unlink`` at a new site;
* letting a cached preview claim to be the canonical original;
* reaching the in-memory provider double from the runtime surface;
* naming a ``file_*`` collection the models module does not declare.

The freeze lists are tested too: a declared site that no longer exists must be
reported (``W06A-STALE``), so the inventory cannot describe code that is gone.

    pytest tests/test_w0_06a_static_guard.py -v --noconftest
"""
import ast
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import w0_06a_file_registry_guard as guard          # noqa: E402
import w0_06a_file_inventory as inventory           # noqa: E402


def check_source(tmp_path, source: str, name="probe.py"):
    """Run the guard over a snippet written into a real module path.

    The snippet is written UNDER the backend tree (so the guard's relative-path
    logic is the same one it uses in production) and removed afterwards.
    """
    target = BACKEND / "app" / "routes" / ("_w0_06a_probe_%s" % name)
    target.write_text(source, encoding="utf-8")
    try:
        return guard.check_files([target.relative_to(BACKEND).as_posix()])
    finally:
        target.unlink()


def rules(violations):
    return {v[2] for v in violations}


# ═══════════════════════════════════════════════════════ the tree is clean
class TestTheRealTreeIsClean:
    def test_the_active_backend_has_no_violation(self):
        units, violations = guard.check_active_backend()
        assert units > 150, "the guard must see the whole active backend"
        assert violations == [], "\n".join("%s:%d: %s %s" % v for v in violations)

    def test_the_guard_covers_every_module_not_a_hand_written_list(self):
        """W0-03E-A2C's lesson: a guard scoped by a list reports clean on the
        one file nobody added to it."""
        files = set(guard.active_backend_files())
        assert "server.py" in files
        for required in ("app/routes/media.py", "app/routes/projects.py",
                         "app/routes/scan_docs.py", "app/files/registry.py",
                         "app/services/ocr_invoice.py"):
            assert required in files
        on_disk = {p.relative_to(BACKEND).as_posix() for p in (BACKEND / "app").rglob("*.py")}
        assert on_disk <= files, "a module of app/ escaped the guard's scope"

    def test_the_inventory_reconciles_with_the_code(self):
        problems = inventory.reconcile(inventory.scan())
        assert problems == {}, problems

    def test_the_inventory_finds_every_known_file_bearing_module(self):
        modules = {s.path for s in inventory.scan()}
        for required in ("app/routes/media.py", "app/routes/projects.py",
                         "app/routes/scan_docs.py", "app/routes/procurement.py",
                         "app/routes/assets_intake_pending.py", "app/routes/work_logs.py",
                         "app/routes/missing_smr.py", "app/routes/technician.py",
                         "app/services/ocr_invoice.py"):
            assert required in modules, "%s is missing from the inventory scan" % required


# ═══════════════════════════════════════════════════ W06A-REGISTRY-WRITE
class TestRegistryWriteRule:
    def test_a_registry_write_from_a_route_is_rejected(self, tmp_path):
        found = check_source(tmp_path, '''
async def leak(tenant, doc):
    await tenant.file_registry.insert_one(doc)
''')
        assert "W06A-REGISTRY-WRITE" in rules(found)

    def test_every_registry_collection_and_write_method_is_covered(self, tmp_path):
        for collection in sorted(guard.REGISTRY_COLLECTIONS):
            for method in ("insert_one", "update_one", "delete_one", "replace_one",
                           "find_one_and_update", "delete_many"):
                found = check_source(tmp_path, '''
async def leak(tenant, doc):
    await tenant.%s.%s({"id": "x"}, doc)
''' % (collection, method))
                assert "W06A-REGISTRY-WRITE" in rules(found), "%s.%s" % (collection, method)

    def test_naming_the_collection_through_a_constant_does_not_hide_it(self, tmp_path):
        found = check_source(tmp_path, '''
from app.files.models import FILES_COLLECTION

async def leak(tenant, doc):
    await tenant.collection(FILES_COLLECTION).insert_one(doc)
''')
        assert "W06A-REGISTRY-WRITE" in rules(found)

    def test_a_subscript_handle_does_not_hide_it(self, tmp_path):
        found = check_source(tmp_path, '''
async def leak(db, doc):
    await db["file_relations"].insert_one(doc)
''')
        assert "W06A-REGISTRY-WRITE" in rules(found)

    def test_reading_a_registry_collection_is_allowed(self, tmp_path):
        """The rule is about WRITES. A read-only projection is how a later
        slice will render a file list, and refusing it would make the rule
        unusable rather than safe."""
        found = check_source(tmp_path, '''
async def show(tenant, file_id):
    return await tenant.file_registry.find_one({"id": file_id}, {"_id": 0})
''')
        assert "W06A-REGISTRY-WRITE" not in rules(found)


# ═══════════════════════════════════════════════════════ W06A-OWNERLESS
class TestOwnerlessRule:
    @pytest.mark.parametrize("builder,args", [
        ("build_file", 'display_name="a", original_name="a", category="other", uploaded_by="u"'),
        ("build_version", 'file_id="f", version_no=1, checksum_value={}, size_bytes=1, '
                          'mime_type="x", original_name="a", created_by="u"'),
        ("build_relation", 'file_id="f", relation_type="project", record_id="p", created_by="u"'),
        ("build_provider_location", 'file_id="f", version_no=1, provider_kind="s3_compatible", '
                                    'provider_binding_id="b", container="c", object_key="k"'),
        ("build_derived", 'file_id="f", source_version_no=1, kind="thumbnail", '
                          'cache_reference="c"'),
        ("build_delete_request", 'file_id="f", requested_by="u", reason="r"'),
    ])
    def test_a_builder_without_the_owner_is_rejected(self, tmp_path, builder, args):
        found = check_source(tmp_path, '''
from app.files import models as m

def make():
    return m.%s(%s)
''' % (builder, args))
        assert "W06A-OWNERLESS" in rules(found), builder

    def test_the_same_builder_with_the_owner_passes(self, tmp_path):
        found = check_source(tmp_path, '''
from app.files import models as m

def make(tenant):
    return m.build_file(org_id=tenant.org_id, display_name="a", original_name="a",
                        category="other", uploaded_by="u")
''')
        assert "W06A-OWNERLESS" not in rules(found)


# ═══════════════════════════════════════════════════════ W06A-RELTENANT
class TestRelationTenantRule:
    def test_a_hand_assembled_relation_write_is_rejected(self, tmp_path):
        found = check_source(tmp_path, '''
async def leak(db, file_id):
    await db["something"].insert_one({"file_id": file_id, "relation_type": "project",
                                      "record_id": "P-1"})
''')
        assert "W06A-RELTENANT" in rules(found)

    def test_a_relation_built_with_a_literal_tenant_is_rejected(self, tmp_path):
        found = check_source(tmp_path, '''
from app.files import models as m

def make():
    return m.build_relation(org_id="BEG", file_id="f", relation_type="project",
                            record_id="p", created_by="u")
''')
        assert "W06A-RELTENANT" in rules(found)

    def test_a_query_filter_with_the_same_keys_is_not_a_relation(self, tmp_path):
        """The registry service's own lookups carry both keys. A rule that
        cannot tell a filter from a stored document reports correct code as a
        defect, and a guard that does that gets switched off."""
        found = check_source(tmp_path, '''
async def look(tenant, file_id):
    return await tenant.some_collection.find_one(
        {"file_id": file_id, "relation_type": "project", "record_id": "P-1"})
''')
        assert "W06A-RELTENANT" not in rules(found)


# ═══════════════════════════════════════════════════════ W06A-PROVIDERID
class TestProviderIdRule:
    @pytest.mark.parametrize("field", ["url", "file_url", "original_file_url",
                                       "stored_filename", "photo_url", "photo_b64",
                                       "media_url", "file_path", "avatar_url"])
    def test_a_new_pointer_write_is_rejected(self, tmp_path, field):
        found = check_source(tmp_path, '''
async def leak(tenant):
    await tenant.invoices.insert_one({"id": "i", "%s": "/app/backend/uploads/x.pdf"})
''' % field)
        assert "W06A-PROVIDERID" in rules(found), field

    def test_a_pointer_written_through_a_local_document_is_still_found(self, tmp_path):
        """Most real write sites build ``doc = {...}`` and insert the variable.
        A rule that only reads literal arguments would miss nearly all of them."""
        found = check_source(tmp_path, '''
async def leak(tenant):
    doc = {"id": "i"}
    doc["stored_filename"] = "x.pdf"
    await tenant.invoices.insert_one(doc)
''')
        assert "W06A-PROVIDERID" in rules(found)

    def test_a_pointer_inside_a_set_or_a_push_is_found(self, tmp_path):
        for update in ('{"$set": {"photo_url": p}}',
                       '{"$push": {"attachments": {"url": p}}}',
                       '{"$setOnInsert": {"file_url": p}}'):
            found = check_source(tmp_path, '''
async def leak(tenant, p):
    await tenant.invoices.update_one({"id": "i"}, %s)
''' % update)
            assert "W06A-PROVIDERID" in rules(found), update

    def test_a_projection_or_a_response_is_not_a_write(self, tmp_path):
        found = check_source(tmp_path, '''
async def show(tenant):
    row = await tenant.users.find_one({"id": "u"}, {"_id": 0, "avatar_url": 1})
    return {"avatar_url": (row or {}).get("avatar_url"), "url": "https://api.example/x"}
''')
        assert "W06A-PROVIDERID" not in rules(found)

    def test_the_registry_own_provider_coordinates_are_not_a_violation(self, tmp_path):
        """``object_key`` and ``container`` on a ProviderLocation ARE provider
        coordinates — that is the record whose job it is to hold them."""
        found = check_source(tmp_path, '''
async def ok(tenant, row):
    await tenant.some_collection.insert_one({"object_key": "k", "container": "c",
                                             "provider_file_id": "p"})
''')
        assert "W06A-PROVIDERID" not in rules(found)

    def test_every_frozen_pointer_site_still_exists(self):
        for site in sorted(guard.LEGACY_POINTER_SITES):
            path, _, function = site.partition("::")
            full = BACKEND / path
            assert full.is_file(), site
            tree = ast.parse(full.read_text(encoding="utf-8"), filename=path)
            names = {n.name for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            assert function in names, site


# ═══════════════════════════════════════════════════════ W06A-PHYSDELETE
class TestPhysicalDeleteRule:
    @pytest.mark.parametrize("call", [
        "os.remove(path)", "os.unlink(path)", "os.rmdir(path)",
        "shutil.rmtree(path)", "path.unlink()",
    ])
    def test_a_new_physical_delete_is_rejected(self, tmp_path, call):
        found = check_source(tmp_path, '''
import os
import shutil

def wipe(path):
    %s
''' % call)
        assert "W06A-PHYSDELETE" in rules(found), call

    def test_the_three_frozen_legacy_delete_paths_are_accepted_and_real(self):
        assert guard.LEGACY_PHYSICAL_DELETE_SITES == frozenset({
            "app/routes/media.py::delete_media",
            "app/routes/projects.py::delete_project_photo",
            "app/routes/scan_docs.py::delete_scan_doc"})
        for site in sorted(guard.LEGACY_PHYSICAL_DELETE_SITES):
            path, _, function = site.partition("::")
            tree = ast.parse((BACKEND / path).read_text(encoding="utf-8"), filename=path)
            names = {n.name for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            assert function in names, site
            assert guard.check_files([path]) == [] or \
                all(v[2] != "W06A-PHYSDELETE" or "%s::%s" % (path, function)
                    in guard.LEGACY_PHYSICAL_DELETE_SITES for v in guard.check_files([path]))

    def test_a_delete_in_a_different_function_of_the_same_module_is_rejected(self, tmp_path):
        """The freeze is per FUNCTION, not per file: a new delete added next to
        a frozen one is the exact way a list-based guard goes stale."""
        source = (BACKEND / "app" / "routes" / "media.py").read_text(encoding="utf-8")
        source += '''

async def delete_everything(path):
    import os
    os.remove(path)
'''
        found = check_source(tmp_path, source, name="media_clone.py")
        assert "W06A-PHYSDELETE" in rules(found)


# ═══════════════════════════════════════════════════ W06A-CACHEORIGINAL
class TestCacheOriginalRule:
    def test_a_cache_entry_claiming_to_be_the_original_is_rejected(self, tmp_path):
        for value in ("True", '"yes"', "1"):
            found = check_source(tmp_path, '''
def make():
    return {"kind": "thumbnail", "is_canonical_original": %s}
''' % value)
            assert "W06A-CACHEORIGINAL" in rules(found), value

    def test_writing_it_false_is_fine(self, tmp_path):
        found = check_source(tmp_path, '''
def make():
    return {"kind": "thumbnail", "is_canonical_original": False}
''')
        assert "W06A-CACHEORIGINAL" not in rules(found)

    def test_a_derived_kind_inserted_as_a_version_is_rejected(self, tmp_path):
        found = check_source(tmp_path, '''
async def leak(tenant):
    await tenant.file_versions.insert_one({"kind": "compressed_preview"})
''')
        assert "W06A-CACHEORIGINAL" in rules(found)


# ═══════════════════════════════════════════════════ W06A-FAKEPROVIDER
class TestFakeProviderRule:
    def test_importing_the_double_from_a_route_is_rejected(self, tmp_path):
        for statement in ("from app.files.providers.fake import FakeStorageProvider",
                          "import app.files.providers.fake"):
            found = check_source(tmp_path, '''
%s

def use():
    return True
''' % statement)
            assert "W06A-FAKEPROVIDER" in rules(found), statement

    def test_importing_the_real_contract_is_fine(self, tmp_path):
        found = check_source(tmp_path, '''
from app.files.providers.base import ProviderBinding, adapter_for

def use(binding):
    return adapter_for(binding)
''')
        assert "W06A-FAKEPROVIDER" not in rules(found)


# ═══════════════════════════════════════════════════ W06A-UNCLASSIFIED
class TestUnclassifiedRule:
    def test_an_undeclared_file_collection_is_rejected(self, tmp_path):
        found = check_source(tmp_path, '''
async def leak(tenant, doc):
    await tenant.file_shadow_registry.insert_one(doc)
''')
        assert "W06A-UNCLASSIFIED" in rules(found)

    def test_a_declared_one_is_not(self, tmp_path):
        found = check_source(tmp_path, '''
async def read(tenant):
    return await tenant.file_registry.find_one({"id": "x"})
''')
        assert "W06A-UNCLASSIFIED" not in rules(found)


# ══════════════════════════════════════════════════════════ W06A-STALE
class TestFreezeListCannotRot:
    def test_a_declaration_whose_function_is_gone_is_reported(self, monkeypatch):
        monkeypatch.setitem(guard.LEGACY_POINTER_SITES,
                            "app/routes/media.py::a_function_that_never_existed",
                            frozenset({"url"}))
        found = guard._stale_declarations()
        assert any(v[2] == "W06A-STALE" for v in found)

    def test_a_declaration_whose_module_is_gone_is_reported(self, monkeypatch):
        monkeypatch.setitem(guard.LEGACY_POINTER_SITES,
                            "app/routes/_gone.py::whatever", frozenset({"url"}))
        found = guard._stale_declarations()
        assert any(v[2] == "W06A-STALE" and "_gone.py" in v[0] for v in found)

    def test_the_inventory_reports_a_file_bearing_site_nobody_declared(self):
        real = inventory.scan()
        intruder = inventory.Site("app/routes/_new.py", "sneaky", "POINTER_WRITE", "url", 7)
        problems = inventory.reconcile(list(real) + [intruder])
        assert any("app/routes/_new.py::sneaky" in item
                   for item in problems.get("UNACCOUNTED", []))

    def test_every_declared_dynamic_writer_is_proven_to_exist(self):
        assert inventory._dynamic_writer_problems() == []
        assert inventory.DYNAMIC_FIELD_WRITERS, \
            "the declaration list must be explicit, even when short"


# ═════════════════════════════════════════════════ the guard is runnable
class TestRunnable:
    def test_main_exits_zero_on_the_clean_tree(self, capsys):
        assert guard.main([]) == 0
        assert "0 violation(s)" in capsys.readouterr().out

    def test_main_exits_one_on_a_violation(self, tmp_path, capsys):
        target = BACKEND / "app" / "routes" / "_w0_06a_probe_main.py"
        target.write_text('''
async def leak(tenant, doc):
    await tenant.file_registry.insert_one(doc)
''', encoding="utf-8")
        try:
            assert guard.main([target.relative_to(BACKEND).as_posix()]) == 1
            assert "W06A-REGISTRY-WRITE" in capsys.readouterr().out
        finally:
            target.unlink()

    def test_a_windows_style_path_gives_the_same_verdict(self):
        assert guard.normalize_rel("app\\\\routes\\\\media.py") == "app//routes//media.py"
        assert guard.check_files(["app/routes/media.py"]) == \
            guard.check_files(["app\\routes\\media.py"])

    def test_the_inventory_check_mode_exits_zero(self, capsys):
        assert inventory.main(["--check"]) == 0
