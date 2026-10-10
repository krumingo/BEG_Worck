"""
W0-06D — the focused gate for legacy file/media adoption READINESS.

Every test here asks one of the questions the contract
(`docs/architecture/W0-06D_LEGACY_ADOPTION_READINESS.md`) says must be answered
before a migration could even be proposed:

* does the scan cover ALL declared sources, or just the convenient ones;
* does it reconcile BOTH directions, or only the DB side;
* can a path from a database row escape the allowlisted root, or follow a link
  out of it;
* is "the object is missing" ever confused with "we could not read the storage";
* do two tenants with colliding ids, names and checksums stay separate;
* can the application disk ever come out as an executable in-place adoption;
* is the plan the same on a rerun, and refused once anything observed drifts;
* does the projection hide what a reader must not see;
* and does the whole thing really move, delete or overwrite nothing.

The permission decisions are the REAL W0-02 Permission Service's; only its
assignment loader is in-memory. The physical inventory runs against a real
temporary directory, because a fake filesystem could not prove a symlink
refusal. No live tenant, NAS, Drive, S3 or Atlas is touched, and no customer
original exists outside the fixtures these tests create and delete.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

from app.files import adoption_readiness as ar
from app.files import migration_map as mp
from app.files import models as m
from app.files.access import FileAccessService
from app.files.authorization import FileAccessDenied
from app.files.registry import FileRegistry
from app.tenancy.data_access import TenantData
from tests.w0_06b_support import (
    A,
    B,
    OWNER_A,
    OWNER_B,
    accepted,
    configure,
    ctx,
    install_permissions,
    service_for,
    world,
)

pytest.importorskip("mongomock_motor")

#: Tenant-scoped service principals of the readiness scanner. Ordinary FLOW-002
#: principals: the assignment below is what lets them run.
OPERATOR_A, OPERATOR_B = "adopt-a", "adopt-b"
#: May READ the projection and nothing else — the narrowed-view case.
READER_A = "adopt-read-a"
#: Has a live assignment that does NOT list the adoption actions.
NO_RIGHTS = "adopt-none"

ADOPTION_ACTIONS = ["file.adoption.scan", "file.adoption.read"]

FROZEN = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)
KIND = m.PROVIDER_S3_COMPATIBLE


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _perms(monkeypatch):
    install_permissions(monkeypatch, {
        (OPERATOR_A, A): [{"id": "ra-ad-a", "status": "active", "role_id": "custom",
                           "permissions": list(ADOPTION_ACTIONS),
                           "scope_type": "company"}],
        (OPERATOR_B, B): [{"id": "ra-ad-b", "status": "active", "role_id": "custom",
                           "permissions": list(ADOPTION_ACTIONS),
                           "scope_type": "company"}],
        (READER_A, A): [{"id": "ra-ad-r", "status": "active", "role_id": "custom",
                         "permissions": ["file.adoption.read"],
                         "scope_type": "company"}],
        (NO_RIGHTS, A): [{"id": "ra-ad-n", "status": "active", "role_id": "custom",
                          "permissions": ["file.open"], "scope_type": "company"}],
    })


# ───────────────────────────────────────────────────────────── the fixtures
class _Roots:
    """A real temporary legacy root. Created per test and removed afterwards."""

    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="w006d_")
        self.uploads = os.path.join(self.base, "uploads")
        self.projects = os.path.join(self.uploads, "projects")
        os.makedirs(self.projects, exist_ok=True)
        #: A directory OUTSIDE every allowlisted root, for the escape tests.
        self.outside = os.path.join(self.base, "elsewhere")
        os.makedirs(self.outside, exist_ok=True)

    def write(self, relative, data=b"legacy original bytes"):
        path = os.path.join(self.uploads, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def write_outside(self, name, data=b"not yours"):
        path = os.path.join(self.outside, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def roots(self):
        return [self.uploads, self.projects]

    def remove(self):
        shutil.rmtree(self.base, ignore_errors=True)


@pytest.fixture
def roots():
    made = _Roots()
    try:
        yield made
    finally:
        made.remove()


#: The declared production roots, mounted at the test fixture's roots. This is
#: the same mapping a real scan needs: `migration_map` names the LIVE
#: application's directories, and the machine doing the scanning has them
#: somewhere else. The safety gate still applies to the real root.
def declared_map(roots_obj):
    return {mp.LEGACY_PROJECT_UPLOADS_ROOT: roots_obj.projects,
            mp.LEGACY_UPLOADS_ROOT: roots_obj.uploads}


def inventory(roots_obj, *, allow_content_read=True, mapped=True, **budget):
    return ar.LegacyRootInventory(
        roots_obj.roots(),
        budget=ar.ScanBudget(allow_content_read=allow_content_read, **budget),
        declared_roots=declared_map(roots_obj) if mapped else None)


async def _tenant_world(org=A, *, projects=("P-1",)):
    """A tenant view plus the business records the planned relations name.

    C02: the planned relation target is now RESOLVED in this tenant, so a
    fixture that omits the project is testing ``BUSINESS_RELATION_AMBIGUOUS``
    whether it meant to or not. The projects are created by default and
    ``projects=()`` is the explicit way to ask for an unresolvable target.
    """
    db, sysdb = await world()
    for project_id in projects:
        await db["projects"].insert_one({"id": project_id, "org_id": org,
                                         "name": "site " + project_id})
    return db, sysdb, FileRegistry(TenantData(db, org))


def readiness(registry, *, inv=None, clock=None, sources=mp.LEGACY_SOURCES):
    return ar.LegacyAdoptionReadiness(registry, inventory=inv,
                                      clock=clock or (lambda: FROZEN), sources=sources)


async def _seed(db, org, collection, rows):
    for row in rows:
        await db[collection].insert_one(dict(row, org_id=org))


def _code_identifiers(module):
    """Every identifier and non-docstring string literal of a module's CODE.

    Used by the "invents no approval rule" assertions: the module's own
    docstring states that it does NOT invent an approver, a deadline or an
    SLA, so a plain text search would match the disclaimer instead of a
    violation. This looks at what the code actually names.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(module))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name.lower())
        elif isinstance(node, ast.arg):
            names.add(node.arg.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                names.add(node.value.lower())
    return names


def _media_row(media_id, stored, **extra):
    """One ``media_files`` row, the richest declared source."""
    return dict({"id": media_id, "stored_filename": stored, "filename": stored,
                 "url": "/uploads/" + stored, "context_type": "project",
                 "context_id": "P-1", "owner_user_id": "u-1"}, **extra)


# ══════════════════════════════════════════════════ declared source coverage
class TestDeclaredSourceCoverage:
    """The scan must cover every declared source, and refuse an undeclared one."""

    def test_the_declared_map_is_the_only_source_registry(self):
        assert len(mp.LEGACY_SOURCES) == 16
        assert set(mp.SOURCES_BY_KEY) == {s.key for s in mp.LEGACY_SOURCES}
        # W0-06D adds no source of its own anywhere in its module.
        import inspect
        source = inspect.getsource(ar)
        assert "LEGACY_SOURCES" in source
        assert "LegacySource(" not in source, "W0-06D must not declare a source"

    def test_every_declared_source_is_scanned_and_classified(self):
        """All 16, not a sample: an unscanned source reads as a clean one."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            # one row per declared source, with the fields that source reads
            for source in mp.LEGACY_SOURCES:
                await _seed(db, A, source.collection, [{
                    "id": "legacy-%s" % source.key,
                    "stored_filename": "%s.bin" % source.key,
                    "filename": "%s.bin" % source.key,
                    "url": "/uploads/%s.bin" % source.key,
                    "avatar_url": "/uploads/%s.bin" % source.key,
                    "original_file_url": "/uploads/%s.bin" % source.key,
                    "context_type": "project", "context_id": "P-1",
                    "project_id": "P-1", "site_id": "P-1", "invoice_id": "I-1",
                    "asset_id": "AS-1", "user_id": "u-1", "expense_id": "E-1",
                    "supplier_invoice_id": "SI-1", "work_report_id": "WR-1",
                }])
            out = await readiness(reg).scan(ctx(OPERATOR_A, A))
            seen = {i["source_key"] for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW}
            assert seen == {s.key for s in mp.LEGACY_SOURCES}, \
                "unscanned sources: %s" % sorted({s.key for s in mp.LEGACY_SOURCES} - seen)
            # and every item really carries a state from the declared vocabulary
            for item in out["item_records"]:
                assert item["state"] in ar.READINESS_STATES
                assert item["proposed_action"] in ar.PROPOSED_ACTIONS
            assert out["declared_sources"] == 16
        run(body())

    def test_an_undeclared_source_is_refused_not_skipped(self):
        async def body():
            db, sysdb, reg = await _tenant_world()
            with pytest.raises(ar.AdoptionScanRefused) as refused:
                await readiness(reg).scan(ctx(OPERATOR_A, A),
                                          source_keys=["media_files", "invented_source"])
            assert "invented_source" in str(refused.value)
            # nothing was written for the half it did recognise
            assert await db[ar.ADOPTION_SCANS_COLLECTION].count_documents({}) == 0
            assert await db[ar.ADOPTION_ITEMS_COLLECTION].count_documents({}) == 0
        run(body())

    def test_a_service_built_on_an_undeclared_source_is_refused_at_construction(self):
        async def body():
            db, sysdb, reg = await _tenant_world()
            fake = mp.LegacySource(
                key="not_declared", collection="x", legacy_reference_field="id",
                pointer_fields=("u",), physical_root=None, tenant_field="org_id",
                action=mp.ACTION_REGISTER, category=m.CATEGORY_OTHER,
                sensitivity=m.SENSITIVITY_STANDARD, business_relation="", behaviour="",
                migration_action="")
            with pytest.raises(ar.AdoptionScanRefused):
                readiness(reg, sources=(fake,))
        run(body())

    def test_the_generated_inventory_still_matches_the_code(self):
        """The contract's "regenerate/reconcile against the final head"."""
        import subprocess
        import sys
        out = subprocess.run([sys.executable, "scripts/w0_06a_file_inventory.py",
                              "--check"], capture_output=True, text=True)
        assert out.returncode == 0, out.stdout + out.stderr


# ══════════════════════════════════════════════════════ path safety (read-only)
class TestPathSafety:
    """A path from a database row is untrusted input."""

    def test_a_path_inside_the_root_is_accepted(self, roots):
        roots.write("ok.pdf")
        safe, refusal = ar.path_within_root(roots.uploads,
                                            os.path.join(roots.uploads, "ok.pdf"))
        assert safe is True and refusal is None

    def test_a_climbing_path_is_refused(self, roots):
        roots.write_outside("secret.pdf")
        safe, refusal = ar.path_within_root(
            roots.uploads, os.path.join(roots.uploads, "..", "elsewhere", "secret.pdf"))
        assert safe is False and refusal == ar.REASON_PATH_OUTSIDE_ROOT

    def test_a_root_looking_prefix_is_refused(self, roots):
        """`/uploads-evil` starts with `/uploads` and is a different directory."""
        sibling = roots.uploads + "-evil"
        os.makedirs(sibling, exist_ok=True)
        with open(os.path.join(sibling, "x.pdf"), "wb") as handle:
            handle.write(b"x")
        safe, refusal = ar.path_within_root(roots.uploads,
                                           os.path.join(sibling, "x.pdf"))
        assert safe is False and refusal == ar.REASON_PATH_OUTSIDE_ROOT

    def test_a_symlink_is_refused_even_when_it_points_inside_the_root(self, roots):
        """Resolving inside the root is not a safety property of a link."""
        target = roots.write("real.pdf")
        link = os.path.join(roots.uploads, "link.pdf")
        os.symlink(target, link)
        safe, refusal = ar.path_within_root(roots.uploads, link)
        assert safe is False and refusal == ar.REASON_PATH_IS_LINK

    def test_a_symlink_out_of_the_root_is_refused_as_a_link(self, roots):
        outside = roots.write_outside("escape.pdf")
        link = os.path.join(roots.uploads, "escape.pdf")
        os.symlink(outside, link)
        safe, refusal = ar.path_within_root(roots.uploads, link)
        assert safe is False and refusal == ar.REASON_PATH_IS_LINK

    def test_a_symlinked_directory_on_the_way_is_refused(self, roots):
        os.makedirs(os.path.join(roots.outside, "deep"), exist_ok=True)
        with open(os.path.join(roots.outside, "deep", "f.pdf"), "wb") as handle:
            handle.write(b"f")
        os.symlink(os.path.join(roots.outside, "deep"),
                   os.path.join(roots.uploads, "deep"))
        safe, refusal = ar.path_within_root(
            roots.uploads, os.path.join(roots.uploads, "deep", "f.pdf"))
        assert safe is False and refusal == ar.REASON_PATH_IS_LINK

    @pytest.mark.parametrize("bad", [None, "", 0, [], {}])
    def test_a_non_path_is_refused(self, roots, bad):
        safe, refusal = ar.path_within_root(roots.uploads, bad)
        assert safe is False and refusal == ar.REASON_PATH_OUTSIDE_ROOT

    def test_the_walk_never_follows_a_symlinked_directory(self, roots):
        roots.write("inside.pdf")
        with open(os.path.join(roots.outside, "outside.pdf"), "wb") as handle:
            handle.write(b"o")
        os.symlink(roots.outside, os.path.join(roots.uploads, "linked"))
        objects = inventory(roots).walk()
        names = {o.relative_path for o in objects}
        assert "inside.pdf" in names
        assert not any("outside.pdf" in n for n in names)

    def test_an_object_named_by_a_row_outside_every_root_is_a_refusal_not_absence(
            self, roots):
        """The decisive distinction: refused to look is not proven absent."""
        roots.write_outside("elsewhere.pdf")
        seen = inventory(roots).observe_path(
            os.path.join(roots.outside, "elsewhere.pdf"))
        assert seen is not None
        assert seen.refusal == ar.REASON_PATH_OUTSIDE_ROOT
        assert seen.refusal != ar.REASON_ORIGINAL_ABSENT
        assert seen.checksum is None

    def test_nothing_in_the_module_opens_a_file_for_writing(self):
        """The no-move/no-delete/no-overwrite invariant, read off the source."""
        import inspect
        source = inspect.getsource(ar)
        for forbidden in ("os.remove", "os.unlink", "os.rename", "os.replace",
                          "shutil.move", "shutil.copy", "shutil.rmtree", "os.rmdir",
                          "os.truncate", "os.chmod", "os.makedirs", "os.mkdir",
                          '"wb"', "'wb'", '"w"', "'w'", '"a"', "'a'", '"r+"'):
            assert forbidden not in source, "W0-06D must not %s" % forbidden
        assert 'open(path, "rb")' in source      # the one read-only open


# ═══════════════════════════════════════════════════════════ checksum budget
class TestChecksumBudget:
    def test_content_is_not_read_unless_explicitly_permitted(self, roots):
        roots.write("a.pdf", b"bytes")
        inv = inventory(roots, allow_content_read=False)
        obj, = [o for o in inv.walk() if o.relative_path == "a.pdf"]
        assert obj.checksum is None
        assert obj.checksum_reason == ar.REASON_CONTENT_READ_NOT_PERMITTED
        # C02: the counters live on the PASS, not on the reusable inventory
        assert inv.last_pass.bytes_read == 0 and inv.last_pass.checksums_read == 0
        assert obj.size_bytes == 5                # stat is fine; reading is not

    def test_a_permitted_read_produces_the_real_checksum(self, roots):
        roots.write("a.pdf", b"bytes")
        inv = inventory(roots)
        obj, = [o for o in inv.walk() if o.relative_path == "a.pdf"]
        assert obj.checksum == m.checksum(hashlib.sha256(b"bytes").hexdigest())
        assert obj.checksum_reason is None
        assert inv.last_pass.checksums_read == 1 and inv.last_pass.bytes_read == 5

    def test_the_object_count_budget_stops_the_walk_and_says_so(self, roots):
        for index in range(5):
            roots.write("f%d.pdf" % index)
        inv = inventory(roots, max_objects=2)
        objects = inv.walk()
        assert len(objects) == 2
        assert inv.last_pass.truncated is True
        assert inv.as_record()["truncated"] is True

    def test_the_checksum_count_budget_leaves_a_reason_not_a_silent_none(self, roots):
        for index in range(3):
            roots.write("f%d.pdf" % index, b"x" * (index + 1))
        inv = inventory(roots, max_checksum_objects=1)
        objects = inv.walk()
        hashed = [o for o in objects if o.checksum]
        unhashed = [o for o in objects if not o.checksum]
        assert len(hashed) == 1 and len(unhashed) == 2
        assert all(o.checksum_reason == ar.REASON_BUDGET_EXHAUSTED for o in unhashed)

    def test_the_byte_budget_is_respected(self, roots):
        roots.write("big.pdf", b"x" * 100)
        roots.write("small.pdf", b"y" * 10)
        inv = inventory(roots, max_checksum_bytes=50)
        objects = {o.relative_path: o for o in inv.walk()}
        assert objects["big.pdf"].checksum is None
        assert objects["big.pdf"].checksum_reason == ar.REASON_BUDGET_EXHAUSTED
        assert objects["small.pdf"].checksum is not None
        assert inv.last_pass.bytes_read <= 50

    def test_an_object_larger_than_the_per_object_cap_is_never_hashed(self, roots):
        roots.write("huge.pdf", b"z" * 200)
        inv = inventory(roots, max_object_bytes=100)
        obj, = [o for o in inv.walk() if o.relative_path == "huge.pdf"]
        assert obj.checksum is None
        assert obj.checksum_reason == ar.REASON_BUDGET_EXHAUSTED

    @pytest.mark.parametrize("field", ["max_objects", "max_checksum_objects",
                                       "max_checksum_bytes", "max_object_bytes"])
    def test_a_nonsense_budget_is_refused(self, field):
        with pytest.raises(ar.AdoptionScanRefused):
            ar.ScanBudget(**{field: -1})

    def test_an_inventory_without_a_root_is_refused(self):
        with pytest.raises(ar.AdoptionScanRefused):
            ar.LegacyRootInventory([])
        with pytest.raises(ar.AdoptionScanRefused):
            ar.LegacyRootInventory(["", None])


# ═══════════════════════════════════════ both directions of the reconciliation
class TestReconciliation:
    def test_a_db_row_whose_original_is_there_is_matched_not_orphaned(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("m1.pdf", b"one")
            await _seed(db, A, "media_files", [_media_row("md-1", "m1.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(ctx(OPERATOR_A, A))
            rows = [i for i in out["item_records"] if i["source_key"] == "media_files"]
            assert len(rows) == 1
            assert rows[0]["observed"]["state"] == "present"
            assert rows[0]["observed"]["checksum"] == m.checksum(
                hashlib.sha256(b"one").hexdigest())
            # and the object is NOT also reported as an orphan
            orphans = [i for i in out["item_records"]
                       if i["direction"] == ar.DIRECTION_PHYSICAL_OBJECT]
            assert orphans == []
        run(body())

    def test_a_db_row_without_its_original_is_missing_original(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "media_files", [_media_row("md-1", "gone.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(ctx(OPERATOR_A, A))
            row, = [i for i in out["item_records"] if i["source_key"] == "media_files"]
            assert row["state"] == ar.MISSING_ORIGINAL
            assert ar.REASON_ORIGINAL_ABSENT in row["reasons"]
            assert row["proposed_action"] == ar.PROPOSE_BLOCKED_FUTURE_STEP
        run(body())

    def test_a_physical_object_no_row_claims_is_an_orphan(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("stray.pdf", b"stray")
            out = await readiness(reg, inv=inventory(roots)).scan(ctx(OPERATOR_A, A))
            orphan, = [i for i in out["item_records"]
                       if i["direction"] == ar.DIRECTION_PHYSICAL_OBJECT]
            assert orphan["state"] == ar.ORPHAN_PHYSICAL_FILE
            assert ar.REASON_UNATTRIBUTED_OBJECT in orphan["reasons"]
            assert ar.REASON_OWNERSHIP_UNVERIFIED in orphan["reasons"]
            assert orphan["org_id"] is None, "an orphan has no owner"
            assert orphan["proposed_action"] == ar.PROPOSE_NEEDS_HUMAN_DECISION
        run(body())

    def test_an_orphan_is_not_owned_because_its_path_resembles_a_tenant_root(
            self, roots):
        """The heuristic the contract forbids, asked for directly."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            # a path that mentions the tenant and a plausible project
            roots.write(os.path.join("BEG", "projects", "P-1", "looks-owned.pdf"),
                        b"nope")
            out = await readiness(reg, inv=inventory(roots)).scan(ctx(OPERATOR_A, A))
            orphan, = [i for i in out["item_records"]
                       if i["direction"] == ar.DIRECTION_PHYSICAL_OBJECT]
            assert orphan["state"] == ar.ORPHAN_PHYSICAL_FILE
            assert orphan["org_id"] is None
            assert orphan["plan"] is None
            assert orphan["relations"] == []
        run(body())

    def test_a_pointer_without_an_owning_file_is_an_orphan_db_record(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "invoices", [{"id": "I-1", "scan_doc_id": "SD-1",
                                             "invoice_id": "I-1"}])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["invoice_scan_pointer"])
            row, = out["item_records"]
            assert row["state"] == ar.ORPHAN_DB_RECORD
            assert ar.REASON_POINTER_WITHOUT_FILE in row["reasons"]
            assert row["proposed_action"] == ar.PROPOSE_NEEDS_HUMAN_DECISION
        run(body())

    def test_a_scan_without_a_physical_inventory_says_unknown_not_missing(self):
        """No inventory is a legitimate configuration, and it proves nothing."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "media_files", [_media_row("md-1", "whatever.pdf")])
            out = await readiness(reg, inv=None).scan(ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = out["item_records"]
            assert row["observed"]["state"] == "unknown"
            assert row["state"] != ar.MISSING_ORIGINAL
            assert ar.REASON_ORIGINAL_ABSENT not in row["reasons"]
        run(body())

    def test_an_inaccessible_object_is_never_reported_as_missing(self, roots):
        """Provider/filesystem outage must not be mislabelled absence."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            path = roots.write("locked.pdf", b"locked")
            await _seed(db, A, "media_files", [_media_row("md-1", "locked.pdf")])

            class _Unreadable(ar.LegacyRootInventory):
                def _observe_uncached(self, root, relative, absolute, pass_):
                    return ar.PhysicalObject(
                        relative_path=relative, root=root, size_bytes=None,
                        checksum=None, readable=False,
                        refusal=ar.REASON_SOURCE_INACCESSIBLE,
                        checksum_reason=ar.REASON_SOURCE_INACCESSIBLE)
            inv = _Unreadable(roots.roots(),
                              budget=ar.ScanBudget(allow_content_read=True),
                              declared_roots=declared_map(roots))
            out = await readiness(reg, inv=inv).scan(ctx(OPERATOR_A, A),
                                                     source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["state"] != ar.MISSING_ORIGINAL
            assert ar.REASON_SOURCE_INACCESSIBLE in row["reasons"]
            assert ar.REASON_ORIGINAL_ABSENT not in row["reasons"]
            assert os.path.exists(path)           # and nothing happened to it
        run(body())


# ════════════════════════════════════════════════ two tenants, one filename
class TestTenantCollision:
    """Same id, same name, same bytes, two tenants. Never one identity."""

    def test_the_same_legacy_id_in_two_tenants_derives_two_file_ids(self):
        one = mp.deterministic_file_id(A, "media_files", "md-1")
        two = mp.deterministic_file_id(B, "media_files", "md-1")
        assert one != two, "the owner must be inside the derived identity"

    def test_two_tenants_with_colliding_rows_scan_independently(self, roots):
        async def body():
            db, sysdb = await world()
            reg_a = FileRegistry(TenantData(db, A))
            reg_b = FileRegistry(TenantData(db, B))
            # identical id, identical stored filename, identical bytes
            roots.write("shared.pdf", b"identical bytes")
            await _seed(db, A, "media_files", [_media_row("md-1", "shared.pdf")])
            await _seed(db, B, "media_files", [_media_row("md-1", "shared.pdf")])

            out_a = await readiness(reg_a, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            out_b = await readiness(reg_b, inv=inventory(roots)).scan(
                ctx(OPERATOR_B, B), source_keys=["media_files"])

            a_rows = [i for i in out_a["item_records"]
                      if i["direction"] == ar.DIRECTION_DB_ROW]
            b_rows = [i for i in out_b["item_records"]
                      if i["direction"] == ar.DIRECTION_DB_ROW]
            assert len(a_rows) == 1 and len(b_rows) == 1
            assert a_rows[0]["org_id"] == A and b_rows[0]["org_id"] == B
            assert a_rows[0]["plan"]["file_id"] != b_rows[0]["plan"]["file_id"]
            assert a_rows[0]["id"] != b_rows[0]["id"]
            assert a_rows[0]["fingerprint"] != b_rows[0]["fingerprint"]
            # neither item mentions the other tenant anywhere
            import json
            assert B not in json.dumps(a_rows[0])
            assert A not in json.dumps(b_rows[0])
            # and the stored records are scoped: A's scan holds only A's items
            stored_a = await db[ar.ADOPTION_ITEMS_COLLECTION].find(
                {"org_id": A}, {"_id": 0}).to_list(None)
            assert {r["org_id"] for r in stored_a} == {A}
        run(body())

    def test_a_cross_tenant_caller_is_refused_before_any_read(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world(A)
            await _seed(db, A, "media_files", [_media_row("md-1", "x.pdf")])
            service = readiness(reg, inv=inventory(roots))
            with pytest.raises(FileAccessDenied) as denied:
                await service.scan(ctx(OPERATOR_B, B))
            assert denied.value.reason_code == "CROSS_TENANT"
            assert await db[ar.ADOPTION_SCANS_COLLECTION].count_documents({}) == 0
            # and the refusal is audited
            events = await db["audit_events"].find(
                {"action": "file.access.denied"}, {"_id": 0}).to_list(None)
            assert len(events) == 1
            assert events[0]["structured_diff"]["reason_code"] == "CROSS_TENANT"
        run(body())

    def test_one_tenants_scan_is_never_visible_to_the_other(self, roots):
        async def body():
            db, sysdb = await world()
            reg_a = FileRegistry(TenantData(db, A))
            reg_b = FileRegistry(TenantData(db, B))
            await _seed(db, A, "media_files", [_media_row("md-a", "a.pdf")])
            await _seed(db, B, "media_files", [_media_row("md-b", "b.pdf")])
            roots.write("a.pdf"); roots.write("b.pdf")
            await readiness(reg_a, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            b_view = await readiness(reg_b, inv=inventory(roots)).list_items(
                ctx(OPERATOR_B, B), include_source_reference=True)
            assert b_view == [], "tenant B must not see tenant A's readiness items"
        run(body())


# ═════════════════════════════════════════ registry comparison and duplicates
async def _registered(db, sysdb, org, owner, name, data, *, relations=()):
    """A real registered File in ``org``, through the real W0-06B services."""
    backends = {}
    svc = service_for(db, sysdb, org, backends)
    binding_id, backend = await configure(svc, owner, KIND,
                                          bucket="bucket-%s" % org.lower())
    backends[binding_id] = backend
    activated = await svc.activate(ctx(owner, org), binding_id=binding_id,
                                   responsibility=accepted(owner))
    assert activated["activated"], activated
    reg = FileRegistry(TenantData(db, org))
    await db["projects"].insert_one({"id": "P-1", "org_id": org, "name": "site"})
    access = FileAccessService(reg, svc)
    out = await access.upload(
        ctx(owner, org), data=data, display_name=name, original_name=name,
        category=m.CATEGORY_PHOTO_VIDEO, mime_type="application/pdf",
        sensitivity=m.SENSITIVITY_STANDARD,
        relations=list(relations) or [{"relation_type": m.RELATION_PROJECT,
                                       "record_id": "P-1"}])
    assert out["status"] == "registered", out
    return reg, svc, out["file_id"]


class TestRegistryComparison:
    def test_an_identical_already_registered_file_is_recognised(self, roots):
        """Same tenant, same identity, verified customer-managed location."""
        async def body():
            db, sysdb = await world()
            data = b"already registered bytes"
            reg, svc, file_id = await _registered(db, sysdb, A, OWNER_A, "reg.pdf", data)
            # a legacy row whose DERIVED id is exactly that registered file
            legacy = "md-already"
            derived = mp.deterministic_file_id(A, "media_files", legacy)
            # register a second file under the derived id by seeding the row and
            # pointing the registry at the same content through its own id
            await _seed(db, A, "media_files", [_media_row(legacy, "reg.pdf")])
            roots.write("reg.pdf", data)
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            # the derived id is NOT the uploaded file's id, so this is a
            # duplicate candidate, never an auto-merge
            assert row["plan"]["file_id"] == derived
            assert row["state"] == ar.DUPLICATE_CANDIDATE
            assert row["registry"]["duplicate_of"] == [file_id]
            assert ar.REASON_DUPLICATE_SAME_CHECKSUM in row["reasons"]
            assert row["proposed_action"] == ar.PROPOSE_NEEDS_HUMAN_DECISION
        run(body())

    def test_a_duplicate_candidate_is_never_merged(self, roots):
        async def body():
            db, sysdb = await world()
            data = b"the same content twice"
            reg, svc, file_id = await _registered(db, sysdb, A, OWNER_A, "one.pdf", data)
            before_files = await db[m.FILES_COLLECTION].count_documents({})
            before_rel = await db[m.RELATIONS_COLLECTION].count_documents({})
            await _seed(db, A, "media_files", [_media_row("md-dup", "dup.pdf")])
            roots.write("dup.pdf", data)
            await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            # nothing in the File Registry moved
            assert await db[m.FILES_COLLECTION].count_documents({}) == before_files
            assert await db[m.RELATIONS_COLLECTION].count_documents({}) == before_rel
        run(body())

    def test_a_different_checksum_for_the_same_identity_is_a_conflict(self, roots):
        """Louder than already-registered: the same comparison, opposite answer."""
        async def body():
            db, sysdb = await world()
            reg, svc, _file_id = await _registered(db, sysdb, A, OWNER_A, "c.pdf",
                                                   b"registered content")
            legacy = "md-conflict"
            derived = mp.deterministic_file_id(A, "media_files", legacy)
            # make the registry hold the DERIVED id, with different content
            await db[m.FILES_COLLECTION].insert_one({
                "id": derived, "org_id": A, "status": m.FILE_ACTIVE,
                "category": m.CATEGORY_PHOTO_VIDEO,
                "sensitivity": m.SENSITIVITY_STANDARD, "created_at": "2026-01-01"})
            await db[m.VERSIONS_COLLECTION].insert_one({
                "file_id": derived, "org_id": A, "version_no": 1, "is_current": True,
                "checksum": m.checksum(hashlib.sha256(b"something else").hexdigest()),
                "checksum_key": m.checksum_key(
                    m.checksum(hashlib.sha256(b"something else").hexdigest())),
                "size_bytes": 14, "created_at": "2026-01-01"})
            await _seed(db, A, "media_files", [_media_row(legacy, "c2.pdf")])
            roots.write("c2.pdf", b"on disk content")
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["state"] == ar.CHECKSUM_CONFLICT
            assert ar.REASON_CHECKSUM_DIFFERS in row["reasons"]
            assert row["registry"]["checksum_matches"] is False
            assert row["proposed_action"] == ar.PROPOSE_NEEDS_HUMAN_DECISION
        run(body())

    def test_an_unknown_checksum_is_not_a_conflict(self, roots):
        """No legacy row stores a checksum; unread is not mismatched."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "media_files", [_media_row("md-1", "u.pdf")])
            roots.write("u.pdf", b"unread")
            out = await readiness(reg, inv=inventory(roots, allow_content_read=False)
                                  ).scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["state"] != ar.CHECKSUM_CONFLICT
            assert ar.REASON_CHECKSUM_DIFFERS not in row["reasons"]
            assert ar.REASON_CONTENT_READ_NOT_PERMITTED in row["reasons"]
            assert row["registry"]["checksum_matches"] is None
        run(body())


# ══════════════════════════════════ the application disk is never adoptable
class TestAdoptInPlaceInvariant:
    """`ADOPT_IN_PLACE` must be structurally unreachable for a legacy row."""

    def test_the_legacy_app_disk_is_not_a_customer_managed_provider(self):
        assert m.PROVIDER_LEGACY_APP_DISK not in m.CUSTOMER_MANAGED_PROVIDER_KINDS
        # and every planned legacy location says legacy_app_disk
        for source in mp.LEGACY_SOURCES:
            entry = mp.plan_row(source, {"id": "x", "org_id": A,
                                         "stored_filename": "f.pdf"})
            assert entry.provider_kind == m.PROVIDER_LEGACY_APP_DISK
            assert entry.provider_binding_id == mp.UNBOUND_PROVIDER_BINDING

    def test_no_scanned_legacy_row_is_ever_proposed_for_adopt_in_place(self, roots):
        """Across all 16 declared sources, with bytes present and readable."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            for source in mp.LEGACY_SOURCES:
                name = "%s.bin" % source.key
                roots.write(name, b"bytes of " + source.key.encode())
                await _seed(db, A, source.collection, [{
                    "id": "lg-%s" % source.key, "stored_filename": name,
                    "filename": name, "url": "/uploads/" + name,
                    "avatar_url": "/uploads/" + name,
                    "original_file_url": "/uploads/" + name,
                    "context_type": "project", "context_id": "P-1",
                    "project_id": "P-1", "checksum": None}])
            out = await readiness(reg, inv=inventory(roots)).scan(ctx(OPERATOR_A, A))
            proposals = {i["proposed_action"] for i in out["item_records"]}
            assert ar.PROPOSE_ADOPT_IN_PLACE not in proposals, \
                "a legacy app-disk row must never be an executable in-place adoption"
            assert out["summary"]["by_proposed_action"].get(
                ar.PROPOSE_ADOPT_IN_PLACE, 0) == 0
            assert out["summary"]["ready"] == 0
            assert out["executable"] is False and out["dry_run"] is True
        run(body())

    def test_adopt_in_place_needs_a_verified_customer_managed_location(self):
        """The rule, exercised directly on the pure proposal function."""
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=True, has_owning_file=True,
            evidence_complete=True, relations_match=True) == ar.PROPOSE_ADOPT_IN_PLACE
        # C02: a verified location WITHOUT the observed evidence is not enough
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=True, has_owning_file=True,
            evidence_complete=False, relations_match=True) \
            == ar.PROPOSE_REGISTER_REFERENCE_ONLY
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=True, has_owning_file=False,
            evidence_complete=False, relations_match=False) \
            == ar.PROPOSE_BLOCKED_FUTURE_STEP
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=False, has_owning_file=True,
            evidence_complete=True, relations_match=True) \
            == ar.PROPOSE_REGISTER_REFERENCE_ONLY
        # C02: an owning file with an UNPROVEN relation is a decision, not a reference
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=False, has_owning_file=True,
            evidence_complete=True, relations_match=False) \
            == ar.PROPOSE_BLOCKED_FUTURE_STEP
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=False,
            has_owning_file=False) == ar.PROPOSE_BLOCKED_FUTURE_STEP

    def test_inline_base64_sources_are_blocked_not_adoptable(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "asset_intake_pending",
                        [{"id": "ai-1", "photo_base64": "ZGF0YQ==", "asset_id": "AS-1",
                          "project_id": "P-1"}])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["asset_intake_photo"])
            row, = out["item_records"]
            assert mp.BLOCKER_INLINE_BASE64 in row["blockers"]
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
            assert row["state"] in (ar.BLOCKED, ar.BUSINESS_RELATION_AMBIGUOUS,
                                    ar.TENANT_AMBIGUOUS, ar.MISSING_ORIGINAL)
        run(body())

    def test_the_module_exposes_no_apply_path_at_all(self):
        public = {n for n in dir(ar.LegacyAdoptionReadiness) if not n.startswith("_")}
        # ``org_id`` is set in ``__init__``, so it is not on the class.
        for forbidden in ("apply", "apply_plan", "adopt", "commit", "execute",
                          "migrate", "run_migration", "adopt_in_place"):
            assert forbidden not in public, "W0-06D must not expose %s" % forbidden
        # what it DOES expose
        assert public == {"scan", "validate_plan", "list_items", "decisions_required",
                          "now", "scans", "items"}


# ════════════════════════════════════ determinism and stale-plan refusal
class TestDeterminismAndDrift:
    def test_the_same_inputs_produce_a_byte_identical_plan(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            for index in range(4):
                roots.write("f%d.pdf" % index, b"bytes %d" % index)
                await _seed(db, A, "media_files",
                            [_media_row("md-%d" % index, "f%d.pdf" % index)])
            service = readiness(reg, inv=inventory(roots))
            first = await service.scan(ctx(OPERATOR_A, A), scan_id="s1",
                                        source_keys=["media_files"], persist=False)
            second = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), scan_id="s2", source_keys=["media_files"],
                persist=False)
            assert first["plan_hash"] == second["plan_hash"]
            assert [i["fingerprint"] for i in first["item_records"]] == \
                   [i["fingerprint"] for i in second["item_records"]]
            assert [i["id"] for i in first["item_records"]] == \
                   [i["id"] for i in second["item_records"]]
            assert first["summary"] == second["summary"]
        run(body())

    def test_the_order_does_not_depend_on_iteration_order(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            names = ["zeta.pdf", "alpha.pdf", "mid.pdf"]
            for index, name in enumerate(names):
                roots.write(name, b"x" * (index + 1))
                await _seed(db, A, "media_files", [_media_row("md-%s" % name, name)])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"], persist=False)
            keys = [(i["direction"], i["source_key"] or "", i["legacy_reference"],
                     i["org_id"] or "") for i in out["item_records"]]
            assert keys == sorted(keys)
        run(body())

    def test_a_fingerprint_ignores_the_clock_and_the_item_id(self, roots):
        """A fingerprint that moved with the clock would refuse every plan."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("t.pdf", b"t")
            await _seed(db, A, "media_files", [_media_row("md-1", "t.pdf")])
            early = await readiness(reg, inv=inventory(roots),
                                     clock=lambda: FROZEN).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"], persist=False)
            later = await readiness(
                reg, inv=inventory(roots),
                clock=lambda: datetime(2027, 5, 5, tzinfo=timezone.utc)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"], persist=False)
            assert early["item_records"][0]["scanned_at"] \
                != later["item_records"][0]["scanned_at"]
            assert early["plan_hash"] == later["plan_hash"]
        run(body())

    def test_a_validated_plan_is_accepted_when_nothing_moved(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("v.pdf", b"v")
            await _seed(db, A, "media_files", [_media_row("md-1", "v.pdf")])
            service = readiness(reg, inv=inventory(roots))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            answer = await service.validate_plan(ctx(OPERATOR_A, A),
                                                  scan_id=out["id"])
            assert answer["valid"] is True and answer["drift"] == []
            assert answer["executable"] is False
            assert "no apply path" in answer["note"]
            events = await db["audit_events"].find(
                {"action": ar.AUDIT_PLAN_VALIDATED}, {"_id": 0}).to_list(None)
            assert len(events) == 1
        run(body())

    @pytest.mark.parametrize("how", ["content", "deleted", "row_changed", "new_row"])
    def test_any_observed_drift_refuses_the_stale_plan(self, roots, how):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("d.pdf", b"original")
            await _seed(db, A, "media_files", [_media_row("md-1", "d.pdf")])
            service = readiness(reg, inv=inventory(roots))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])

            if how == "content":
                roots.write("d.pdf", b"CHANGED")           # the customer replaced it
            elif how == "deleted":
                os.remove(os.path.join(roots.uploads, "d.pdf"))
            elif how == "row_changed":
                await db["media_files"].update_one(
                    {"id": "md-1"}, {"$set": {"context_id": "P-OTHER"}})
            else:
                roots.write("extra.pdf", b"appeared")

            fresh = readiness(reg, inv=inventory(roots))
            with pytest.raises(ar.AdoptionPlanStale) as stale:
                await fresh.validate_plan(ctx(OPERATOR_A, A), scan_id=out["id"])
            assert stale.value.scan_id == out["id"]
            assert stale.value.drifted, "the drift must name what changed"
            refusals = await db["audit_events"].find(
                {"action": ar.AUDIT_PLAN_REFUSED}, {"_id": 0}).to_list(None)
            assert len(refusals) == 1
            assert refusals[0]["error_code"] == "PLAN_STALE"
            assert refusals[0]["result"] == "failure"
            # the refusal names the drift without exposing the new value
            import json
            payload = json.dumps(refusals[0]["structured_diff"])
            assert "CHANGED" not in payload
            assert "drifted_items" in payload
            # the stored plan was NOT rewritten by the validation
            stored = await db[ar.ADOPTION_SCANS_COLLECTION].find_one({"id": out["id"]})
            assert stored["plan_hash"] == out["plan_hash"]
        run(body())

    def test_a_validation_does_not_persist_a_second_scan(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("p.pdf", b"p")
            await _seed(db, A, "media_files", [_media_row("md-1", "p.pdf")])
            service = readiness(reg, inv=inventory(roots))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            before_scans = await db[ar.ADOPTION_SCANS_COLLECTION].count_documents({})
            before_items = await db[ar.ADOPTION_ITEMS_COLLECTION].count_documents({})
            await service.validate_plan(ctx(OPERATOR_A, A), scan_id=out["id"])
            assert await db[ar.ADOPTION_SCANS_COLLECTION].count_documents({}) \
                == before_scans
            assert await db[ar.ADOPTION_ITEMS_COLLECTION].count_documents({}) \
                == before_items
        run(body())

    def test_validating_an_unknown_plan_is_refused(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            with pytest.raises(ar.AdoptionScanRefused):
                await readiness(reg, inv=inventory(roots)).validate_plan(
                    ctx(OPERATOR_A, A), scan_id="adsc_nope")
        run(body())

    def test_the_drift_report_names_the_fields_not_the_values(self):
        before = {"org_id": A, "plan": {"file_id": "f1"}, "registry": {},
                  "relations": [], "observed": {"checksum": {"value": "aa"},
                                                "size_bytes": 1}}
        after = {"org_id": A, "plan": {"file_id": "f1"}, "registry": {},
                 "relations": [], "observed": {"checksum": {"value": "bb"},
                                               "size_bytes": 2}}
        fields = ar._drifted_fields(before, after)
        assert sorted(fields) == ["observed.checksum", "observed.size_bytes"]
        assert not any("bb" in f for f in fields)


# ═══════════════════════════════════════════ FLOW-002 and the redacted view
class TestAuthorizationAndProjection:
    def test_a_principal_without_the_scan_right_cannot_scan(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            with pytest.raises(FileAccessDenied) as denied:
                await readiness(reg, inv=inventory(roots)).scan(ctx(NO_RIGHTS, A))
            assert denied.value.action == ar.ACTION_ADOPTION_SCAN
            assert await db[ar.ADOPTION_SCANS_COLLECTION].count_documents({}) == 0
        run(body())

    def test_no_session_is_refused(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            with pytest.raises(FileAccessDenied) as denied:
                await readiness(reg, inv=inventory(roots)).scan(ctx(None, A))
            assert denied.value.reason_code == "NO_SESSION"
        run(body())

    def test_a_reader_may_read_but_not_scan(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("r.pdf", b"r")
            await _seed(db, A, "media_files", [_media_row("md-1", "r.pdf")])
            service = readiness(reg, inv=inventory(roots))
            await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            with pytest.raises(FileAccessDenied):
                await service.scan(ctx(READER_A, A), source_keys=["media_files"])
            rows = await service.list_items(ctx(READER_A, A))
            assert rows, "the reader may see the readiness"
        run(body())

    def test_the_reader_view_hides_the_protected_source_reference(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("secret-name.pdf", b"s")
            await _seed(db, A, "media_files",
                        [_media_row("md-secret", "secret-name.pdf")])
            service = readiness(reg, inv=inventory(roots))
            await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])

            narrow, = [r for r in await service.list_items(
                ctx(READER_A, A), include_source_reference=True)
                if r["direction"] == ar.DIRECTION_DB_ROW]
            assert narrow["source_reference_redacted"] is True
            assert "legacy_reference" not in narrow
            assert "collection" not in narrow
            assert "plan" not in narrow
            # but the readiness itself is visible
            assert narrow["state"] in ar.READINESS_STATES
            assert narrow["source_key"] == "media_files"

            full, = [r for r in await service.list_items(
                ctx(OPERATOR_A, A), include_source_reference=True)
                if r["direction"] == ar.DIRECTION_DB_ROW]
            assert full["legacy_reference"] == "md-secret"
            assert full["plan"]["file_id"]
            assert "source_reference_redacted" not in full
        run(body())

    def test_no_projection_ever_carries_a_filesystem_path(self, roots):
        async def body():
            import json
            db, sysdb, reg = await _tenant_world()
            roots.write("in-a-path.pdf", b"p")
            await _seed(db, A, "media_files", [_media_row("md-1", "in-a-path.pdf")])
            service = readiness(reg, inv=inventory(roots))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            for view in (await service.list_items(ctx(OPERATOR_A, A),
                                                   include_source_reference=True)):
                payload = json.dumps(view)
                assert roots.base not in payload
                assert "/app/backend/uploads" not in payload
                assert "relative_path" not in payload
            # and the stored item does not keep the absolute path either
            stored = json.dumps(await db[ar.ADOPTION_ITEMS_COLLECTION].find(
                {}, {"_id": 0}).to_list(None))
            assert roots.base not in stored
            assert "current_physical_location" not in stored
            # nor does any AuditEvent
            events = json.dumps(await db["audit_events"].find(
                {}, {"_id": 0}).to_list(None))
            assert roots.base not in events
            assert "/app/backend/uploads" not in events
        run(body())

    def test_the_decisions_list_is_a_list_and_not_an_approval(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "media_files", [_media_row("md-1", "absent.pdf")])
            service = readiness(reg, inv=inventory(roots))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            pending = await service.decisions_required(ctx(OPERATOR_A, A),
                                                        scan_id=out["id"])
            assert pending and all(p["decision_required"] for p in pending)
            # there is nothing to approve WITH. Checked on the CODE, not the
            # prose: the module's docstring says it invents no approver, and a
            # plain text search would trip on that sentence.
            assert _code_identifiers(ar).isdisjoint({
                "approve", "reject", "assign", "approver", "approved_by",
                "approval", "sla", "deadline", "due_at", "escalate"})
        run(body())


# ═══════════════════════════════════════════════════ FLOW-040 audit trail
class TestAuditTrail:
    def test_a_scan_is_audited_start_and_finish_with_one_correlation(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("a.pdf", b"a")
            await _seed(db, A, "media_files", [_media_row("md-1", "a.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            events = await db["audit_events"].find(
                {"action": {"$regex": "^file.adoption"}}, {"_id": 0}
            ).sort("sequence", 1).to_list(None)
            actions = [e["action"] for e in events]
            assert actions[0] == ar.AUDIT_SCAN_STARTED
            assert actions[-1] == ar.AUDIT_SCAN_FINISHED
            assert {e["correlation_id"] for e in events} == {out["id"]}
            assert {e["tenant_id"] for e in events} == {A}
            assert {e["actor_id"] for e in events} == {OPERATOR_A}
            finished = events[-1]
            assert finished["structured_diff"]["dry_run"] is True
            assert finished["structured_diff"]["plan_hash"] == out["plan_hash"]
        run(body())

    def test_a_decision_required_item_is_audited_with_its_evidence_hash(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "media_files", [_media_row("md-1", "missing.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            item, = [i for i in out["item_records"]
                     if i["direction"] == ar.DIRECTION_DB_ROW]
            events = await db["audit_events"].find(
                {"action": ar.AUDIT_DECISION_REQUIRED}, {"_id": 0}).to_list(None)
            assert len(events) == 1
            assert events[0]["structured_diff"]["evidence_hash"] == item["fingerprint"]
            assert events[0]["idempotency_key"] == item["fingerprint"]
            assert events[0]["structured_diff"]["state"] == item["state"]
        run(body())

    def test_the_audit_chain_stays_intact_across_scans(self, roots):
        async def body():
            from app.audit import store
            db, sysdb, reg = await _tenant_world()
            roots.write("c.pdf", b"c")
            await _seed(db, A, "media_files", [_media_row("md-1", "c.pdf")])
            service = readiness(reg, inv=inventory(roots))
            for index in range(3):
                await service.scan(ctx(OPERATOR_A, A), scan_id="s%d" % index,
                                    source_keys=["media_files"])
            intact, reason = await store.verify_tenant_chain(db, A)
            assert intact is True, reason
        run(body())

    def test_no_secret_or_credential_can_reach_an_audit_event(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("k.pdf", b"k")
            await _seed(db, A, "media_files",
                        [_media_row("md-1", "k.pdf", access_key="AKIAEXAMPLE",
                                    password="hunter2", token="tok-123")])
            await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            import json
            payload = json.dumps(await db["audit_events"].find(
                {}, {"_id": 0}).to_list(None))
            for secret in ("AKIAEXAMPLE", "hunter2", "tok-123"):
                assert secret not in payload
            stored = json.dumps(await db[ar.ADOPTION_ITEMS_COLLECTION].find(
                {}, {"_id": 0}).to_list(None))
            for secret in ("AKIAEXAMPLE", "hunter2", "tok-123"):
                assert secret not in stored
        run(body())


# ══════════════════════════════════════════════════════ the precedence itself
class TestPrecedence:
    def test_every_declared_state_is_in_the_precedence(self):
        assert set(ar.STATE_PRECEDENCE) | {ar.NO_CONTENT} == ar.READINESS_STATES
        assert len(ar.STATE_PRECEDENCE) == len(set(ar.STATE_PRECEDENCE))

    @pytest.mark.parametrize("winner,also", [
        (ar.UNSUPPORTED_SOURCE, ar.TENANT_AMBIGUOUS),
        (ar.TENANT_AMBIGUOUS, ar.CHECKSUM_CONFLICT),
        (ar.CHECKSUM_CONFLICT, ar.ALREADY_REGISTERED),
        (ar.CHECKSUM_CONFLICT, ar.DUPLICATE_CANDIDATE),
        (ar.BUSINESS_RELATION_AMBIGUOUS, ar.MISSING_ORIGINAL),
        (ar.MISSING_ORIGINAL, ar.ORPHAN_DB_RECORD),
        (ar.ORPHAN_DB_RECORD, ar.ALREADY_REGISTERED),
        (ar.ALREADY_REGISTERED, ar.DUPLICATE_CANDIDATE),
    ])
    def test_the_documented_order_decides_when_two_conditions_hold(self, winner, also):
        state = ar.readiness_state(direction=ar.DIRECTION_DB_ROW,
                                   candidates={winner: True, also: True},
                                   has_blockers=False)
        assert state == winner

    def test_a_blocked_row_is_never_ready(self):
        state = ar.readiness_state(direction=ar.DIRECTION_DB_ROW,
                                   candidates={ar.READY_TO_ADOPT: True},
                                   has_blockers=True)
        assert state == ar.BLOCKED

    def test_ready_needs_both_no_blockers_and_its_own_condition(self):
        assert ar.readiness_state(direction=ar.DIRECTION_DB_ROW,
                                  candidates={ar.READY_TO_ADOPT: True},
                                  has_blockers=False) == ar.READY_TO_ADOPT
        assert ar.readiness_state(direction=ar.DIRECTION_DB_ROW, candidates={},
                                  has_blockers=False) == ar.BLOCKED

    def test_an_unknown_direction_is_refused(self):
        with pytest.raises(ar.AdoptionScanRefused):
            ar.readiness_state(direction="sideways", candidates={}, has_blockers=False)


# ════════════════════════════════════════ the no-move / no-delete invariant
class TestNothingIsTouched:
    def test_a_full_scan_changes_no_byte_on_disk_and_no_legacy_row(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            paths = {}
            for index in range(4):
                name = "keep%d.pdf" % index
                path = roots.write(name, b"content %d" % index)
                paths[path] = (os.path.getsize(path), os.path.getmtime(path),
                               open(path, "rb").read())
                await _seed(db, A, "media_files", [_media_row("md-%d" % index, name)])
            legacy_before = await db["media_files"].find({}, {"_id": 0}).to_list(None)
            registry_before = {
                name: await db[name].count_documents({})
                for name in (m.FILES_COLLECTION, m.VERSIONS_COLLECTION,
                             m.RELATIONS_COLLECTION, m.LOCATIONS_COLLECTION)}

            service = readiness(reg, inv=inventory(roots))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            try:
                await service.validate_plan(ctx(OPERATOR_A, A), scan_id=out["id"])
            except ar.AdoptionPlanStale:                 # pragma: no cover
                pytest.fail("a scan must not drift against itself")

            for path, (size, mtime, data) in paths.items():
                assert os.path.exists(path), "an original was removed"
                assert os.path.getsize(path) == size
                assert os.path.getmtime(path) == mtime, "an original was rewritten"
                with open(path, "rb") as handle:
                    assert handle.read() == data
            assert await db["media_files"].find({}, {"_id": 0}).to_list(None) \
                == legacy_before, "a legacy row was modified"
            for name, count in registry_before.items():
                assert await db[name].count_documents({}) == count, \
                    "%s was written by a readiness scan" % name
            # the only new documents are the scan's own
            assert await db[ar.ADOPTION_SCANS_COLLECTION].count_documents({}) == 1
            assert await db[ar.ADOPTION_ITEMS_COLLECTION].count_documents({}) == 4
        run(body())

    def test_an_orphan_object_is_left_exactly_where_it_was(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            path = roots.write("orphan.pdf", b"nobody claims me")
            before = (os.path.getsize(path), os.path.getmtime(path))
            await readiness(reg, inv=inventory(roots)).scan(ctx(OPERATOR_A, A),
                                                             source_keys=["media_files"])
            assert os.path.exists(path)
            assert (os.path.getsize(path), os.path.getmtime(path)) == before
        run(body())


# ════════════════════════════════════════════════════════════ the summary
class TestSummary:
    def test_no_content_is_counted_apart_from_ready_and_blocked(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            await _seed(db, A, "excel_import_templates", [{"id": "tpl-1"}])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["excel_import_templates"])
            row, = out["item_records"]
            assert row["state"] == ar.NO_CONTENT
            assert row["proposed_action"] == ar.PROPOSE_NO_ACTION
            assert out["summary"]["no_content"] == 1
            assert out["summary"]["ready"] == 0
            assert out["summary"]["decision_required"] == 0
        run(body())

    def test_the_summary_counts_states_actions_and_reasons(self, roots):
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("present.pdf", b"here")
            roots.write("stray.pdf", b"stray")
            await _seed(db, A, "media_files", [_media_row("md-1", "present.pdf"),
                                               _media_row("md-2", "gone.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            summary = out["summary"]
            assert summary["items"] == 3                      # 2 rows + 1 orphan
            assert summary["orphan_physical"] == 1
            assert sum(summary["by_state"].values()) == 3
            assert sum(summary["by_proposed_action"].values()) == 3
            assert summary["by_reason"]
            assert out["items"] == 3
        run(body())


class TestVerifiedLocationIsRequired:
    """"Verified" is the provider's answer, not our hope.

    The gap this closes: a registered file whose location IS customer-managed
    but whose availability is anything other than ``available`` must not come
    out adoptable. Without this, a provider that has never been verified — or
    one that is currently unreachable — would support an in-place adoption.
    """

    @staticmethod
    async def _registry_holding(db, org, legacy, *, availability, kind, data=b"bytes"):
        """Seed the registry with the DERIVED identity at a chosen location."""
        derived = mp.deterministic_file_id(org, "media_files", legacy)
        digest = m.checksum(hashlib.sha256(data).hexdigest())
        await db[m.FILES_COLLECTION].insert_one({
            "id": derived, "org_id": org, "status": m.FILE_ACTIVE,
            "category": m.CATEGORY_PHOTO_VIDEO,
            "sensitivity": m.SENSITIVITY_STANDARD, "created_at": "2026-01-01"})
        await db[m.VERSIONS_COLLECTION].insert_one({
            "file_id": derived, "org_id": org, "version_no": 1, "is_current": True,
            "checksum": digest, "checksum_key": m.checksum_key(digest),
            "size_bytes": len(data), "created_at": "2026-01-01"})
        await db[m.LOCATIONS_COLLECTION].insert_one({
            "file_id": derived, "org_id": org, "version_no": 1,
            "role": m.LOCATION_ROLE_PRIMARY, "provider_kind": kind,
            "provider_binding_id": "pb-1", "availability": availability,
            "superseded_at": None, "created_at": "2026-01-01"})
        await db[m.RELATIONS_COLLECTION].insert_one({
            "file_id": derived, "org_id": org, "relation_type": m.RELATION_PROJECT,
            "record_id": "P-1", "active": True, "removed_at": None,
            "created_at": "2026-01-01"})
        return derived, digest

    @pytest.mark.parametrize("availability", [
        m.AVAILABILITY_UNVERIFIED, m.AVAILABILITY_PROVIDER_UNREACHABLE,
        m.AVAILABILITY_MISSING, m.AVAILABILITY_EXTERNALLY_CHANGED])
    def test_an_unverified_customer_managed_location_is_not_adoptable(
            self, roots, availability):
        async def body():
            db, sysdb, reg = await _tenant_world()
            data = b"customer managed bytes"
            await self._registry_holding(db, A, "md-v", availability=availability,
                                         kind=m.PROVIDER_S3_COMPATIBLE, data=data)
            roots.write("v.pdf", data)
            await _seed(db, A, "media_files", [_media_row("md-v", "v.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["customer_managed"] is True
            assert row["registry"]["verified_location"] is False
            assert row["state"] != ar.READY_TO_ADOPT
            assert row["state"] != ar.ALREADY_REGISTERED
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
        run(body())

    def test_a_verified_customer_managed_location_is_already_registered(self, roots):
        """The positive case, so the guard is not vacuously strict."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            data = b"customer managed bytes"
            await self._registry_holding(db, A, "md-v",
                                         availability=m.AVAILABILITY_AVAILABLE,
                                         kind=m.PROVIDER_S3_COMPATIBLE, data=data)
            roots.write("v.pdf", data)
            await _seed(db, A, "media_files", [_media_row("md-v", "v.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["verified_location"] is True
            assert row["registry"]["checksum_matches"] is True
            assert row["state"] == ar.ALREADY_REGISTERED
            assert row["proposed_action"] == ar.PROPOSE_NO_ACTION
        run(body())

    def test_a_verified_location_on_the_app_disk_is_not_customer_managed(self, roots):
        """Even AVAILABLE, the application disk supports no in-place adoption."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            data = b"on the app disk"
            await self._registry_holding(db, A, "md-d",
                                         availability=m.AVAILABILITY_AVAILABLE,
                                         kind=m.PROVIDER_LEGACY_APP_DISK, data=data)
            roots.write("d.pdf", data)
            await _seed(db, A, "media_files", [_media_row("md-d", "d.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["customer_managed"] is False
            assert row["registry"]["verified_location"] is False
            assert ar.REASON_NOT_CUSTOMER_MANAGED in row["reasons"]
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
        run(body())

    def test_the_walk_refuses_a_symlinked_directory_by_not_following_links(self,
                                                                           roots):
        """`os.walk(followlinks=False)` is the guarantee; the filter is belt."""
        import inspect
        source = inspect.getsource(ar.LegacyRootInventory.walk)
        assert "followlinks=False" in source
        roots.write("real.pdf", b"r")
        with open(os.path.join(roots.outside, "hidden.pdf"), "wb") as handle:
            handle.write(b"h")
        os.symlink(roots.outside, os.path.join(roots.uploads, "linked"))
        objects = inventory(roots).walk()
        assert {o.relative_path for o in objects} == {"real.pdf"}


# ════════════════════════════ C02 — the four independently reproduced defects
#
# Each class below starts from the counterexample the C01 independent review
# executed, asserts the behaviour it got (now refused) and then asserts the
# positive case, so none of the new guards is vacuously strict.
# Evidence: coordination/REVIEWS/W0-06D.md, C01 section, defects 1-4.

#: The review's defect-1 shape: a same-tenant registered File whose location
#: stores `availability=available`, while the scan observed NOTHING.
UNOBSERVED = {"state": "unknown", "size_bytes": None, "checksum": None,
              "checksum_reason": None, "refusal": None, "relative_path": None,
              "registered_size": None}


def _registry(**over):
    """A `_registry_state`-shaped dict with everything absent by default."""
    base = {"file_exists": False, "version_no": None, "checksum_matches": None,
            "size_matches": None, "registered_size": None, "availability": None,
            "provider_kind": None, "customer_managed": False,
            "verified_location": False, "relation_count": 0,
            "relations_registered": [], "relations_missing": [],
            "relation_targets_missing": [], "relations_match": False,
            "duplicate_of": []}
    base.update(over)
    return base


def _classifier(registry=None):
    """The pure classifier, reachable without a database.

    `_classify` touches no state of its own, so an unbound call is the honest
    way to exercise it — and it is how the review reproduced both
    classification defects in the first place.
    """
    async def body():
        db, sysdb, reg = await _tenant_world()
        return readiness(reg)
    return run(body())


class TestDefect1ReadinessNeedsObservedEvidence:
    """A stored location status is not proof about THIS legacy original."""

    #: A `media_files` plan with its relation resolvable and the W0-06A
    #: `CHECKSUM_UNKNOWN_UNTIL_READ` blocker cleared, so the only thing left
    #: deciding readiness is W0-06D's own evidence. (No real legacy row stores
    #: a checksum, which is why `test_a_row_without_a_legacy_checksum_stays_blocked`
    #: pins the ordinary case separately.)
    @staticmethod
    def _plan(**over):
        row = _media_row("md-1", "x.pdf")
        row.update({"org_id": A, "checksum": "a" * 64})
        row.update(over)
        return mp.plan_row(mp.SOURCES_BY_KEY["media_files"], row)

    def test_the_review_counterexample_is_now_refused(self):
        """Verified location, observed nothing: C01 said READY/ADOPT_IN_PLACE."""
        service = _classifier()
        state, reasons, evidence = service._classify(
            direction=ar.DIRECTION_DB_ROW, plan=self._plan(), observed=UNOBSERVED,
            registry=_registry(file_exists=True, customer_managed=True,
                               verified_location=True,
                               availability=m.AVAILABILITY_AVAILABLE),
            source=mp.SOURCES_BY_KEY["media_files"])
        assert state != ar.READY_TO_ADOPT
        assert state != ar.ALREADY_REGISTERED
        assert evidence is False
        assert ar.REASON_ORIGINAL_NOT_OBSERVED in reasons
        assert ar.REASON_SIZE_UNKNOWN in reasons
        assert ar.propose_action(
            state, at_customer_managed_location=True, has_owning_file=True,
            evidence_complete=evidence, relations_match=False) \
            != ar.PROPOSE_ADOPT_IN_PLACE

    @pytest.mark.parametrize("missing", [
        "original", "checksum", "size", "same_object", "location", "owner"])
    def test_each_single_piece_of_missing_evidence_blocks_readiness(self, missing):
        """Every clause is necessary: drop one and readiness is gone."""
        service = _classifier()
        digest = m.checksum(hashlib.sha256(b"bytes").hexdigest())
        observed = {"state": "present", "size_bytes": 5, "checksum": digest,
                    "checksum_reason": None, "refusal": None,
                    "relative_path": "x.pdf", "registered_size": 5}
        registry = _registry(file_exists=True, customer_managed=True,
                             verified_location=True, checksum_matches=True,
                             size_matches=True, registered_size=5,
                             availability=m.AVAILABILITY_AVAILABLE)
        plan = self._plan()
        if missing == "original":
            observed["state"] = "unknown"
        elif missing == "checksum":
            observed["checksum"] = None
        elif missing == "size":
            observed["size_bytes"] = None
        elif missing == "same_object":
            registry["checksum_matches"] = None
            registry["size_matches"] = None
        elif missing == "location":
            registry["verified_location"] = False
        else:
            plan = mp.plan_row(mp.SOURCES_BY_KEY["media_files"],
                               _media_row("md-1", "x.pdf"))        # no org_id
        state, _reasons, evidence = service._classify(
            direction=ar.DIRECTION_DB_ROW, plan=plan, observed=observed,
            registry=registry, source=mp.SOURCES_BY_KEY["media_files"])
        assert evidence is False, "missing %s must not count as complete" % missing
        assert state != ar.READY_TO_ADOPT

    def test_complete_evidence_does_reach_readiness(self):
        """The positive case, so the guard is not vacuously strict."""
        service = _classifier()
        digest = m.checksum(hashlib.sha256(b"bytes").hexdigest())
        state, reasons, evidence = service._classify(
            direction=ar.DIRECTION_DB_ROW, plan=self._plan(),
            observed={"state": "present", "size_bytes": 5, "checksum": digest,
                      "checksum_reason": None, "refusal": None,
                      "relative_path": "x.pdf", "registered_size": 5},
            registry=_registry(file_exists=True, customer_managed=True,
                               verified_location=True, checksum_matches=True,
                               size_matches=True, registered_size=5,
                               availability=m.AVAILABILITY_AVAILABLE),
            source=mp.SOURCES_BY_KEY["media_files"])
        assert evidence is True
        assert state == ar.READY_TO_ADOPT
        assert ar.REASON_ORIGINAL_NOT_OBSERVED not in reasons
        assert ar.propose_action(
            state, at_customer_managed_location=True, has_owning_file=True,
            evidence_complete=evidence, relations_match=False) \
            == ar.PROPOSE_ADOPT_IN_PLACE

    def test_a_row_without_a_legacy_checksum_stays_blocked(self):
        """The ordinary real case: no legacy row stores a checksum.

        W0-06A adds `CHECKSUM_UNKNOWN_UNTIL_READ` to every REGISTER row, and a
        row with any blocker is never ready. So even with complete W0-06D
        evidence the state is BLOCKED, and that is correct — the readiness
        guard added here is the SECOND lock, not a replacement for the first.
        """
        service = _classifier()
        digest = m.checksum(hashlib.sha256(b"bytes").hexdigest())
        plan = mp.plan_row(mp.SOURCES_BY_KEY["media_files"],
                           _media_row("md-1", "x.pdf") | {"org_id": A})
        assert mp.BLOCKER_NO_CHECKSUM in plan.blockers
        state, _reasons, evidence = service._classify(
            direction=ar.DIRECTION_DB_ROW, plan=plan,
            observed={"state": "present", "size_bytes": 5, "checksum": digest,
                      "checksum_reason": None, "refusal": None,
                      "relative_path": "x.pdf", "registered_size": 5},
            registry=_registry(file_exists=True, customer_managed=True,
                               verified_location=True, checksum_matches=True,
                               size_matches=True, registered_size=5),
            source=mp.SOURCES_BY_KEY["media_files"])
        assert evidence is True              # W0-06D's own evidence IS complete
        assert state == ar.BLOCKED           # and the W0-06A blocker still wins

    def test_an_unobserved_row_is_refused_end_to_end(self, roots):
        """Through the real scan: a registered file with the original absent."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            data = b"registered but not on disk"
            await TestVerifiedLocationIsRequired._registry_holding(
                db, A, "md-gone", availability=m.AVAILABILITY_AVAILABLE,
                kind=m.PROVIDER_S3_COMPATIBLE, data=data)
            # the row exists, the registry says available, the ORIGINAL is gone
            await _seed(db, A, "media_files", [_media_row("md-gone", "gone.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["state"] == ar.MISSING_ORIGINAL
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
            assert ar.REASON_ORIGINAL_NOT_OBSERVED in row["reasons"]
            assert out["summary"]["ready"] == 0
        run(body())

    def test_a_size_mismatch_against_the_registry_is_a_conflict(self, roots):
        """Same checksum shape, different size: not the same object."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            data = b"twelve bytes"
            await TestVerifiedLocationIsRequired._registry_holding(
                db, A, "md-s", availability=m.AVAILABILITY_AVAILABLE,
                kind=m.PROVIDER_S3_COMPATIBLE, data=data)
            # the registry's version says len(data); put different bytes on disk
            await db[m.VERSIONS_COLLECTION].update_one(
                {"file_id": mp.deterministic_file_id(A, "media_files", "md-s")},
                {"$set": {"size_bytes": 999}})
            roots.write("s.pdf", data)
            await _seed(db, A, "media_files", [_media_row("md-s", "s.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["size_matches"] is False
            assert row["state"] == ar.CHECKSUM_CONFLICT
            assert ar.REASON_SIZE_DIFFERS in row["reasons"]
            assert row["proposed_action"] == ar.PROPOSE_NEEDS_HUMAN_DECISION
        run(body())


class TestDefect2RelationIdentityNotCount:
    """A relation COUNT is not a relation identity."""

    def test_the_review_counterexample_is_now_refused(self):
        """Plan wants project=missing-project; registry has one OTHER relation."""
        service = _classifier()
        digest = m.checksum(hashlib.sha256(b"bytes").hexdigest())
        plan = mp.plan_row(mp.SOURCES_BY_KEY["media_files"],
                           {"id": "md-1", "org_id": A, "stored_filename": "x.pdf",
                            "context_type": "project",
                            "context_id": "missing-project"})
        state, reasons, _evidence = service._classify(
            direction=ar.DIRECTION_DB_ROW, plan=plan,
            observed={"state": "present", "size_bytes": 5, "checksum": digest,
                      "checksum_reason": None, "refusal": None,
                      "relative_path": "x.pdf", "registered_size": 5},
            # one unrelated relation, matching checksum, available location
            registry=_registry(file_exists=True, customer_managed=True,
                               verified_location=True, checksum_matches=True,
                               size_matches=True, relation_count=1,
                               relations_missing=[["project", "missing-project"]],
                               relation_targets_missing=[["project",
                                                          "missing-project"]],
                               relations_match=False),
            source=mp.SOURCES_BY_KEY["media_files"])
        assert state != ar.ALREADY_REGISTERED
        assert state == ar.BUSINESS_RELATION_AMBIGUOUS
        assert ar.REASON_RELATION_TARGET_MISSING in reasons
        assert ar.REASON_RELATION_NOT_REGISTERED in reasons

    def test_an_unrelated_registered_relation_is_not_already_registered(self, roots):
        """End to end: the file carries a relation to ANOTHER record."""
        async def body():
            db, sysdb, reg = await _tenant_world(projects=("P-1", "P-OTHER"))
            data = b"content"
            derived, _digest = await TestVerifiedLocationIsRequired._registry_holding(
                db, A, "md-r", availability=m.AVAILABILITY_AVAILABLE,
                kind=m.PROVIDER_S3_COMPATIBLE, data=data)
            # repoint the registered relation at a DIFFERENT project
            await db[m.RELATIONS_COLLECTION].update_one(
                {"file_id": derived}, {"$set": {"record_id": "P-OTHER"}})
            roots.write("r.pdf", data)
            await _seed(db, A, "media_files", [_media_row("md-r", "r.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["relation_count"] == 1    # the count is nonzero
            assert row["registry"]["relations_match"] is False
            assert row["registry"]["relations_missing"] == [["project", "P-1"]]
            assert row["state"] != ar.ALREADY_REGISTERED
            assert row["proposed_action"] != ar.PROPOSE_NO_ACTION
            assert ar.REASON_RELATION_NOT_REGISTERED in row["reasons"]
        run(body())

    def test_a_relation_to_a_target_that_does_not_exist_is_ambiguous(self, roots):
        """The target is resolved in THIS tenant, not taken on trust."""
        async def body():
            db, sysdb, reg = await _tenant_world(projects=())
            roots.write("t.pdf", b"t")
            await _seed(db, A, "media_files", [_media_row("md-t", "t.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["relation_targets_missing"] == [["project", "P-1"]]
            assert row["state"] == ar.BUSINESS_RELATION_AMBIGUOUS
            assert ar.REASON_RELATION_TARGET_MISSING in row["reasons"]
            assert row["proposed_action"] == ar.PROPOSE_NEEDS_HUMAN_DECISION
        run(body())

    def test_a_target_that_exists_only_in_the_other_tenant_does_not_count(self,
                                                                          roots):
        """Relation isolation: a colliding id in tenant B resolves to nothing here."""
        async def body():
            db, sysdb = await world()
            # P-1 exists ONLY in tenant B
            await db["projects"].insert_one({"id": "P-1", "org_id": B, "name": "b"})
            reg_a = FileRegistry(TenantData(db, A))
            roots.write("x.pdf", b"x")
            await _seed(db, A, "media_files", [_media_row("md-x", "x.pdf")])
            out = await readiness(reg_a, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["relation_targets_missing"] == [["project", "P-1"]]
            assert row["state"] == ar.BUSINESS_RELATION_AMBIGUOUS
        run(body())

    def test_the_exact_relation_match_does_reach_already_registered(self, roots):
        """The positive case: same type, same target, target verified."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            data = b"exactly registered"
            await TestVerifiedLocationIsRequired._registry_holding(
                db, A, "md-ok", availability=m.AVAILABILITY_AVAILABLE,
                kind=m.PROVIDER_S3_COMPATIBLE, data=data)
            roots.write("ok.pdf", data)
            await _seed(db, A, "media_files", [_media_row("md-ok", "ok.pdf")])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["registry"]["relations_match"] is True
            assert row["registry"]["relations_registered"] == [["project", "P-1"]]
            assert row["registry"]["relations_missing"] == []
            assert row["state"] == ar.ALREADY_REGISTERED
            assert row["proposed_action"] == ar.PROPOSE_NO_ACTION
        run(body())

    def test_register_reference_only_needs_the_proven_relation(self):
        """A pointer with an owning file but no proven relation is a decision."""
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=False,
            has_owning_file=True, evidence_complete=False, relations_match=True) \
            == ar.PROPOSE_REGISTER_REFERENCE_ONLY
        assert ar.propose_action(
            ar.READY_TO_ADOPT, at_customer_managed_location=False,
            has_owning_file=True, evidence_complete=False, relations_match=False) \
            == ar.PROPOSE_BLOCKED_FUTURE_STEP

    def test_an_empty_proposed_relation_set_is_never_a_match(self):
        """Nothing proposed proves nothing registered."""
        service = _classifier()
        digest = m.checksum(hashlib.sha256(b"b").hexdigest())
        plan = mp.plan_row(mp.SOURCES_BY_KEY["excel_import_templates"],
                           {"id": "t-1", "org_id": A})
        state, reasons, _ev = service._classify(
            direction=ar.DIRECTION_DB_ROW, plan=plan,
            observed={"state": "present", "size_bytes": 1, "checksum": digest,
                      "checksum_reason": None, "refusal": None,
                      "relative_path": "t", "registered_size": 1},
            registry=_registry(file_exists=True, verified_location=True,
                               customer_managed=True, checksum_matches=True,
                               size_matches=True, relations_match=False),
            source=mp.SOURCES_BY_KEY["excel_import_templates"])
        assert state == ar.NO_CONTENT          # this source owns nothing anyway


class TestDefect3BudgetIsPerPass:
    """A budget belongs to a PASS, so unchanged inputs decide the same way."""

    def test_the_review_counterexample_is_now_deterministic(self, roots):
        """Same inputs, one-object limit, two calls: C01 drifted on the second."""
        roots.write("one.pdf", b"one")
        inv = inventory(roots, max_checksum_objects=1)
        first = inv.observe_path("/app/backend/uploads/one.pdf", inv.open_pass())
        second = inv.observe_path("/app/backend/uploads/one.pdf", inv.open_pass())
        assert first.checksum is not None
        assert second.checksum == first.checksum, "a fresh pass must start fresh"
        assert second.checksum_reason is None

    def test_a_reused_inventory_carries_no_spent_budget_into_the_next_pass(self,
                                                                           roots):
        for index in range(3):
            roots.write("f%d.pdf" % index, b"x" * (index + 1))
        inv = inventory(roots, max_checksum_objects=2)
        for _attempt in range(4):
            objects = inv.walk()                     # each walk is its own pass
            hashed = [o for o in objects if o.checksum]
            assert len(hashed) == 2, "the budget was carried over"
            assert inv.last_pass.checksums_read == 2

    def test_repeated_validation_at_an_exact_limit_never_invents_drift(self, roots):
        """The actual failure the review described, end to end."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            # exactly as many objects as the budget allows to hash
            for index in range(2):
                roots.write("e%d.pdf" % index, b"bytes %d" % index)
                await _seed(db, A, "media_files",
                            [_media_row("md-%d" % index, "e%d.pdf" % index)])
            service = readiness(reg, inv=inventory(roots, max_checksum_objects=2))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            # five validations in a row, nothing touched in between
            for _attempt in range(5):
                answer = await service.validate_plan(ctx(OPERATOR_A, A),
                                                      scan_id=out["id"])
                assert answer["valid"] is True
                assert answer["plan_hash"] == out["plan_hash"]
            refusals = await db["audit_events"].count_documents(
                {"action": ar.AUDIT_PLAN_REFUSED})
            assert refusals == 0, "a stale plan was reported with nothing drifted"
        run(body())

    def test_a_db_row_and_the_physical_walk_share_one_charge(self, roots):
        """One object, one charge — the review's "shared limit" requirement.

        The walk sees the object and the DB row names the same object. With a
        one-object hash budget that must still work: the row reuses the walk's
        observation instead of paying for it a second time.
        """
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("shared.pdf", b"shared bytes")
            await _seed(db, A, "media_files", [_media_row("md-1", "shared.pdf")])
            service = readiness(reg, inv=inventory(roots, max_checksum_objects=1))
            out = await service.scan(ctx(OPERATOR_A, A), source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["observed"]["checksum"] == m.checksum(
                hashlib.sha256(b"shared bytes").hexdigest())
            assert row["observed"]["checksum_reason"] is None
            # charged once, not twice
            assert out["inventory"]["checksums_read"] == 1
            assert out["inventory"]["bytes_read"] == len(b"shared bytes")
            # and the orphan direction did not duplicate it
            assert [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_PHYSICAL_OBJECT] == []
            # repeated validation still agrees
            answer = await service.validate_plan(ctx(OPERATOR_A, A),
                                                  scan_id=out["id"])
            assert answer["valid"] is True
        run(body())

    def test_two_objects_sharing_a_one_object_limit_are_deterministic(self, roots):
        """At the limit, the SAME object wins every pass — sorted order decides."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            for name in ("a.pdf", "b.pdf"):
                roots.write(name, b"content of " + name.encode())
                await _seed(db, A, "media_files",
                            [_media_row("md-" + name, name)])
            service = readiness(reg, inv=inventory(roots, max_checksum_objects=1))
            hashes = []
            for _attempt in range(3):
                out = await service.scan(ctx(OPERATOR_A, A),
                                          source_keys=["media_files"], persist=False)
                hashes.append(out["plan_hash"])
                hashed = [i for i in out["item_records"]
                          if (i["observed"] or {}).get("checksum")]
                assert len(hashed) == 1
            assert len(set(hashes)) == 1, "the same inputs produced two plans"
        run(body())

    def test_the_object_walk_budget_is_also_per_pass(self, roots):
        for index in range(4):
            roots.write("w%d.pdf" % index)
        inv = inventory(roots, max_objects=2)
        for _attempt in range(3):
            assert len(inv.walk()) == 2
            assert inv.last_pass.truncated is True
            assert inv.last_pass.objects_seen == 2

    def test_a_pass_reports_its_own_counters(self, roots):
        roots.write("p.pdf", b"abc")
        inv = inventory(roots)
        pass_ = inv.open_pass()
        inv.walk(pass_)
        assert pass_.as_record()["checksums_read"] == 1
        assert pass_.as_record()["bytes_read"] == 3
        assert pass_.as_record()["truncated"] is False
        assert pass_.as_record()["budget"]["allow_content_read"] is True


class TestDefect4StreamingCapsAreEnforced:
    """A cap checked once before the read is not a cap."""

    class _Lying:
        """A handle that returns more than it was asked for.

        The review's injected-stream counterexample: reported size 1, both
        caps 1, and a stream of three bytes was read and hashed in full.
        """

        def __init__(self, payload):
            self._payload = payload
            self._done = False

        def read(self, _want):
            if self._done:
                return b""
            self._done = True
            return self._payload                     # ignores `_want` entirely

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_the_review_counterexample_now_fails_closed(self, roots):
        """Reported size 1, caps 1, stream b"abc": must be refused."""
        path = roots.write("lying.pdf", b"a")        # stat reports 1 byte
        inv = ar.LegacyRootInventory(
            roots.roots(),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=1,
                                 max_checksum_bytes=1),
            declared_roots=declared_map(roots),
            opener=lambda _p: self._Lying(b"abc"))
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 1, pass_)
        assert checksum is None, "an over-long stream was hashed"
        assert reason == ar.REASON_BUDGET_EXHAUSTED
        assert pass_.checksums_read == 0
        # the bytes really were read, so they are charged honestly
        assert pass_.bytes_read == 3

    def test_a_file_that_grew_after_the_stat_is_refused(self, roots):
        """The growing-file case: stat said 4, the stream has 400."""
        path = roots.write("grow.pdf", b"abcd")
        inv = ar.LegacyRootInventory(
            roots.roots(),
            budget=ar.ScanBudget(allow_content_read=True,
                                 max_object_bytes=1024, max_checksum_bytes=1024),
            declared_roots=declared_map(roots),
            opener=lambda _p: self._Lying(b"x" * 400))
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 4, pass_)
        assert checksum is None
        assert reason == ar.REASON_BUDGET_EXHAUSTED
        assert pass_.checksums_read == 0

    def test_the_remaining_byte_budget_is_enforced_during_the_read(self, roots):
        """Not just the per-object cap: what is LEFT of the pass budget too."""
        path = roots.write("left.pdf", b"ab")
        inv = ar.LegacyRootInventory(
            roots.roots(),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=1024,
                                 max_checksum_bytes=10),
            declared_roots=declared_map(roots),
            opener=lambda _p: self._Lying(b"z" * 50))
        pass_ = inv.open_pass()
        pass_.bytes_read = 9                      # only one byte of budget left
        checksum, reason = inv._checksum(path, 2, pass_)
        assert checksum is None
        assert reason == ar.REASON_BUDGET_EXHAUSTED

    def test_an_honest_stream_at_exactly_the_cap_still_succeeds(self, roots):
        """The positive case: the guard must not refuse a conforming object."""
        path = roots.write("exact.pdf", b"abcd")
        inv = ar.LegacyRootInventory(
            roots.roots(),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=4,
                                 max_checksum_bytes=4),
            declared_roots=declared_map(roots))
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 4, pass_)
        assert reason is None
        assert checksum == m.checksum(hashlib.sha256(b"abcd").hexdigest())
        assert pass_.bytes_read == 4 and pass_.checksums_read == 1

    def test_a_real_oversized_file_is_refused_through_the_scan(self, roots):
        """End to end, with a real file and no injected opener."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("big.pdf", b"y" * 200)
            await _seed(db, A, "media_files", [_media_row("md-1", "big.pdf")])
            out = await readiness(reg, inv=inventory(roots, max_object_bytes=50)
                                  ).scan(ctx(OPERATOR_A, A),
                                          source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["observed"]["checksum"] is None
            assert row["observed"]["checksum_reason"] == ar.REASON_BUDGET_EXHAUSTED
            assert row["state"] != ar.READY_TO_ADOPT
            assert out["inventory"]["bytes_read"] == 0, "an over-cap object was read"
        run(body())

    def test_the_bytes_actually_read_are_never_understated(self, roots):
        """An overrun charges what it read, so a later object cannot sneak in."""
        path = roots.write("over.pdf", b"ab")
        inv = ar.LegacyRootInventory(
            roots.roots(),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=2,
                                 max_checksum_bytes=100),
            declared_roots=declared_map(roots),
            opener=lambda _p: self._Lying(b"q" * 60))
        pass_ = inv.open_pass()
        inv._checksum(path, 2, pass_)
        assert pass_.bytes_read == 60


# ══════════════════════════ C02 review — the three remaining counterexamples
#: A host that cannot create a symlink cannot test the link gate. The five
#: C01 failures in the independent review were exactly this: `WinError 1314`,
#: a missing OS privilege, raised while BUILDING the fixture. Such a result is
#: not a pass and not a failure of the guard — it is an untested guard, so it
#: is marked as skipped, loudly, instead of being counted either way.
def _symlinks_work():
    probe = tempfile.mkdtemp(prefix="w006d_linkprobe_")
    try:
        os.symlink(probe, os.path.join(probe, "l"))
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)


SYMLINKS = _symlinks_work()
needs_symlinks = pytest.mark.skipif(
    not SYMLINKS, reason="this host cannot create a symlink, so the link gate "
                         "cannot be exercised here — NOT a pass")


class _Spy:
    """An opener that records every path it was asked to open."""

    def __init__(self):
        self.opened = []

    def __call__(self, path):
        self.opened.append(path)
        return open(path, "rb")


class TestC02Defect1ObjectBudgetBindsEveryEntryPath:
    """`max_objects` belongs to the object, not to how it was reached."""

    def test_the_review_counterexample_a_db_row_at_cap_zero(self, roots):
        """`max_objects=0`, an EXISTING file named by a row: zero reads."""
        roots.write("big.pdf", b"z" * 4096)
        spy = _Spy()
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots), opener=spy,
            budget=ar.ScanBudget(max_objects=0, allow_content_read=True))
        pass_ = inv.open_pass()
        seen = inv.observe_path("/app/backend/uploads/big.pdf", pass_)
        assert seen.checksum is None, "an object beyond the cap was hashed"
        assert seen.refusal == ar.REASON_OBJECT_BUDGET_EXHAUSTED
        assert seen.readable is False
        assert pass_.objects_seen == 0
        assert pass_.bytes_read == 0
        assert pass_.truncated is True
        assert spy.opened == [], "the file was opened although the cap was 0"

    def test_a_row_naming_an_object_past_the_cap_is_not_read(self, roots):
        """The service-level regression the review asked for, not a helper test.

        The walk spends the whole object budget on the object it reaches
        first; the legacy DB row then names a DIFFERENT object. Before the fix
        that row was observed and hashed anyway, because only ``walk`` charged
        the limit.
        """
        async def body():
            db, sysdb, reg = await _tenant_world()
            # two objects on disk; the budget allows ONE
            roots.write("aaa.pdf", b"first object")
            roots.write("zzz.pdf", b"second object")
            await _seed(db, A, "media_files", [_media_row("md-1", "zzz.pdf")])
            spy = _Spy()
            inv = ar.LegacyRootInventory(
                roots.roots(), declared_roots=declared_map(roots), opener=spy,
                budget=ar.ScanBudget(max_objects=1, allow_content_read=True))
            out = await readiness(reg, inv=inv).scan(ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            # the walk reached aaa.pdf first and spent the one charge there
            assert out["inventory"]["objects_seen"] == 1
            assert out["inventory"]["truncated"] is True
            assert row["observed"]["checksum"] is None
            assert row["observed"]["refusal"] == ar.REASON_OBJECT_BUDGET_EXHAUSTED
            # and zzz.pdf was never opened
            assert all("zzz" not in path for path in spy.opened), spy.opened
            # a refusal is never a missing original and never readiness
            assert row["state"] not in (ar.MISSING_ORIGINAL, ar.READY_TO_ADOPT)
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
            assert ar.REASON_OBJECT_BUDGET_EXHAUSTED in row["reasons"]
        run(body())

    def test_the_same_object_is_still_charged_only_once(self, roots):
        """The C02 shared-limit accounting must survive the new charge point."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            roots.write("shared.pdf", b"shared bytes")
            await _seed(db, A, "media_files", [_media_row("md-1", "shared.pdf")])
            inv = inventory(roots, max_objects=1)
            out = await readiness(reg, inv=inv).scan(ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            # ONE object, ONE charge — the row reuses the walk's observation
            assert out["inventory"]["objects_seen"] == 1
            assert out["inventory"]["truncated"] is False
            assert row["observed"]["checksum"] is not None
            assert row["observed"]["refusal"] is None
        run(body())

    def test_an_exhausted_budget_refuses_every_later_object(self, roots):
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            roots.write(name, b"content " + name.encode())
        inv = inventory(roots, max_objects=2)
        pass_ = inv.open_pass()
        inv.walk(pass_)
        assert pass_.objects_seen == 2
        # a third object, named directly, is now beyond the budget
        later = inv.observe_path("/app/backend/uploads/c.pdf", pass_)
        assert later.refusal == ar.REASON_OBJECT_BUDGET_EXHAUSTED
        assert later.checksum is None
        assert pass_.objects_seen == 2, "the cap was exceeded"

    def test_the_cap_is_per_pass_not_per_inventory(self, roots):
        """Defect 1's fix must not undo C02's defect 3."""
        roots.write("one.pdf", b"one")
        inv = inventory(roots, max_objects=1)
        for _attempt in range(3):
            pass_ = inv.open_pass()
            seen = inv.observe_path("/app/backend/uploads/one.pdf", pass_)
            assert seen.checksum is not None, "a fresh pass started exhausted"
            assert pass_.objects_seen == 1

    @pytest.mark.parametrize("claimed_state", ["absent", "absent_or_unreadable"])
    def test_a_budget_refusal_is_not_an_absent_original(self, claimed_state):
        """The classifier distinction, directly and at its hardest.

        ``absent`` is the deliberately adversarial half: even if a caller
        asserts the object is absent, a refusal saying the scan was not
        PERMITTED to look says nothing about whether the bytes are there.
        Reporting `MISSING_ORIGINAL` from a truncated inventory would be the
        exact mislabelling the contract forbids, so the refusal has to
        override the claim rather than the other way round.
        """
        state, reasons, evidence = _classifier()._classify(
            direction=ar.DIRECTION_DB_ROW,
            plan=TestDefect1ReadinessNeedsObservedEvidence._plan(),
            source=mp.SOURCES_BY_KEY["media_files"],
            observed={"state": claimed_state, "size_bytes": None,
                      "checksum": None, "checksum_reason": None,
                      "refusal": ar.REASON_OBJECT_BUDGET_EXHAUSTED,
                      "relative_path": None, "registered_size": None},
            registry=_registry(file_exists=True, verified_location=True,
                               checksum_matches=True, size_matches=True,
                               relations_match=True))
        assert state != ar.MISSING_ORIGINAL, \
            "a budget refusal was reported as a proven absence"
        assert state != ar.READY_TO_ADOPT
        assert evidence is False
        # and the refusal itself is on the record, not just its effect
        assert ar.REASON_OBJECT_BUDGET_EXHAUSTED in reasons


class TestC02Defect2TheReadNeverExceedsTheCap:
    """The caps bound the physical read, not merely the verdict."""

    class _Stream:
        def __init__(self, payload):
            self.payload = payload
            self.asked = []
            self.done = False

        def read(self, want):
            self.asked.append(want)
            if self.done:
                return b""
            self.done = True
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_the_review_counterexample_zero_caps_read_zero_bytes(self, roots):
        """size 0, both caps 0, a stream offering one byte: nothing is read."""
        path = roots.write("z.pdf", b"x")
        stream = self._Stream(b"x")
        opened = []

        def opener(target):
            opened.append(target)
            return stream

        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=0,
                                 max_checksum_bytes=0),
            opener=opener)
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 0, pass_)
        assert checksum is None
        assert pass_.bytes_read == 0, "a byte was read past a zero cap"
        assert pass_.bytes_read <= inv.budget.max_checksum_bytes
        assert stream.asked == [], "the stream was read at a zero cap"
        # Nothing may be read, so the object is not opened either: an `open`
        # is an action in its own right — it can block on a FIFO, fail on a
        # permission, and it touches the original. A zero budget buys nothing.
        assert opened == [], "the object was opened at a zero budget"
        assert reason == ar.REASON_SIZE_UNCERTAIN

    def test_no_read_ever_asks_for_more_than_is_owed(self, roots):
        """The ceiling+1 probe is gone: every request is within the budget."""
        path = roots.write("exact.pdf", b"abcd")
        stream = self._Stream(b"abcd")
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=4,
                                 max_checksum_bytes=4),
            opener=lambda _p: stream)
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 4, pass_)
        assert reason is None and checksum is not None
        assert stream.asked, "nothing was read at all"
        assert max(stream.asked) <= 4, stream.asked
        assert sum(min(a, 4) for a in stream.asked[:1]) <= 4
        assert pass_.bytes_read == 4 <= inv.budget.max_checksum_bytes

    @pytest.mark.parametrize("cap", [0, 1, 2, 7, 64])
    def test_the_physical_bytes_read_never_exceed_the_cap(self, roots, cap):
        """The invariant, swept across limits, with a real file."""
        path = roots.write("sweep.pdf", b"y" * 64)
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=cap,
                                 max_checksum_bytes=cap))
        pass_ = inv.open_pass()
        inv._checksum(path, 64, pass_)
        assert pass_.bytes_read <= cap, (pass_.bytes_read, cap)

    def test_a_file_that_grew_after_the_stat_is_refused_without_an_overread(self,
                                                                           roots):
        """Growth is caught by a second stat, not by an over-cap byte."""
        path = roots.write("grow.pdf", b"abcd")

        class Growing:
            def __init__(self, target):
                self.handle = open(target, "rb")
                self.target = target

            def read(self, want):
                data = self.handle.read(want)
                # the file grows underneath the scan, mid-read
                with open(self.target, "ab") as more:
                    more.write(b"MORE")
                return data

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.handle.close()
                return False

        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=16,
                                 max_checksum_bytes=16),
            opener=lambda p: Growing(p))
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 4, pass_)
        assert checksum is None, "a file that grew mid-read was hashed"
        assert reason == ar.REASON_SIZE_UNCERTAIN
        assert pass_.bytes_read <= 16
        assert pass_.checksums_read == 0

    def test_a_stream_that_ends_early_is_refused(self, roots):
        """Shrinkage is the same uncertainty, not a checksum of a prefix."""
        path = roots.write("short.pdf", b"abcd")
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=16,
                                 max_checksum_bytes=16),
            opener=lambda _p: self._Stream(b"ab"))
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 4, pass_)
        assert checksum is None
        assert reason == ar.REASON_SIZE_UNCERTAIN
        assert pass_.bytes_read == 2, "the bytes read were not charged honestly"

    def test_an_unknown_size_cannot_be_hashed_at_all(self, roots):
        """A read with no ceiling is not a budgeted read."""
        path = roots.write("u.pdf", b"abcd")
        inv = inventory(roots)
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, None, pass_)
        assert checksum is None
        assert reason == ar.REASON_SIZE_UNCERTAIN
        assert pass_.bytes_read == 0

    def test_a_handle_returning_more_than_asked_is_charged_and_refused(self,
                                                                       roots):
        """We ask for what is owed; a lying handle is still charged honestly."""
        path = roots.write("lie.pdf", b"a")
        stream = self._Stream(b"abc")
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots),
            budget=ar.ScanBudget(allow_content_read=True, max_object_bytes=1,
                                 max_checksum_bytes=1),
            opener=lambda _p: stream)
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 1, pass_)
        assert checksum is None
        assert reason == ar.REASON_BUDGET_EXHAUSTED
        assert stream.asked == [1], "more than the cap was REQUESTED"
        assert pass_.bytes_read == 3, "the bytes that arrived were not charged"
        assert pass_.checksums_read == 0

    def test_a_genuinely_empty_object_still_gets_its_checksum(self, roots):
        """The positive edge: nothing to read is not a refusal."""
        path = roots.write("empty.pdf", b"")
        inv = inventory(roots)
        pass_ = inv.open_pass()
        checksum, reason = inv._checksum(path, 0, pass_)
        assert reason is None
        assert checksum == m.checksum(hashlib.sha256(b"").hexdigest())
        assert pass_.bytes_read == 0
        assert pass_.checksums_read == 1

    def test_a_real_scan_at_an_exact_limit_reads_exactly_the_limit(self, roots):
        """End to end, through the service, with no injected opener."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            payload = b"w" * 12
            roots.write("fit.pdf", payload)
            await _seed(db, A, "media_files", [_media_row("md-1", "fit.pdf")])
            inv = inventory(roots, max_object_bytes=12, max_checksum_bytes=12)
            out = await readiness(reg, inv=inv).scan(ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            assert out["inventory"]["bytes_read"] == 12
            assert out["inventory"]["bytes_read"] <= 12
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["observed"]["checksum"] == m.checksum(
                hashlib.sha256(payload).hexdigest())
        run(body())


class TestC02Defect3TheWalkGatesFileEntriesToo:
    """A symlink FILE is a link, whichever entry path finds it."""

    @needs_symlinks
    def test_the_review_counterexample_an_in_root_link_to_an_outside_target(
            self, roots):
        """A real symlink file, in a real root, pointing really outside it."""
        secret = roots.write_outside("secret.pdf", b"NOT YOURS")
        link = os.path.join(roots.uploads, "escape.pdf")
        os.symlink(secret, link)
        spy = _Spy()
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots), opener=spy,
            budget=ar.ScanBudget(allow_content_read=True))
        # the gate says no, on its own
        safe, refusal = ar.path_within_root(roots.uploads, link)
        assert safe is False
        # and the WALK now agrees with the gate
        found = {o.relative_path: o for o in inv.walk()}
        assert "escape.pdf" in found, "the entry vanished instead of being refused"
        entry = found["escape.pdf"]
        assert entry.checksum is None, "a symlink out of the root was hashed"
        assert entry.refusal == ar.REASON_PATH_IS_LINK
        assert entry.readable is False
        assert spy.opened == [], "the link target was opened"
        assert inv.last_pass.bytes_read == 0

    @needs_symlinks
    def test_an_in_root_link_to_an_in_root_target_is_also_refused(self, roots):
        """"It resolves inside today" is not a safety property."""
        roots.write("real.pdf", b"inside bytes")
        link = os.path.join(roots.uploads, "alias.pdf")
        os.symlink(os.path.join(roots.uploads, "real.pdf"), link)
        inv = inventory(roots)
        found = {o.relative_path: o for o in inv.walk()}
        assert found["alias.pdf"].refusal == ar.REASON_PATH_IS_LINK
        assert found["alias.pdf"].checksum is None
        # the real file beside it is unaffected
        assert found["real.pdf"].checksum is not None

    @needs_symlinks
    def test_the_two_entry_paths_now_agree(self, roots):
        """The inconsistency the review named: walk vs observe_path."""
        secret = roots.write_outside("s.pdf", b"outside")
        os.symlink(secret, os.path.join(roots.uploads, "both.pdf"))
        inv = inventory(roots)
        pass_ = inv.open_pass()
        walked = {o.relative_path: o for o in inv.walk(pass_)}["both.pdf"]
        told = inv.observe_path("/app/backend/uploads/both.pdf", pass_)
        assert walked.refusal == ar.REASON_PATH_IS_LINK
        assert told.refusal == ar.REASON_PATH_IS_LINK
        assert walked.checksum is told.checksum is None

    @needs_symlinks
    def test_a_refused_link_consumes_the_object_budget(self, roots):
        """A refused entry is still an enumerated entry, so it pays.

        C03 asserted the opposite here, and the C03 independent review showed
        that reading to be wrong: a budget that only charges the entries which
        turn out to be readable does not bound the inventory at all. The link
        sorts FIRST, so with one charge available it takes it and the real
        file beside it is refused for budget — which is the honest answer, and
        the pass says so with `truncated`.
        """
        roots.write("real.pdf", b"real")
        os.symlink(roots.write_outside("x.pdf", b"x"),
                   os.path.join(roots.uploads, "aaa_link.pdf"))
        inv = inventory(roots, max_objects=1)
        objects = inv.walk()
        assert len(objects) == 1, [o.relative_path for o in objects]
        assert objects[0].relative_path == "aaa_link.pdf"
        assert objects[0].refusal == ar.REASON_PATH_IS_LINK
        assert inv.last_pass.objects_seen == 1
        assert inv.last_pass.truncated is True

    @needs_symlinks
    def test_a_symlinked_file_is_refused_through_the_service(self, roots):
        """Service level: a legacy row whose object is a link out of the root."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            secret = roots.write_outside("payroll.pdf", b"ANOTHER TENANTS BYTES")
            os.symlink(secret, os.path.join(roots.uploads, "linked.pdf"))
            await _seed(db, A, "media_files", [_media_row("md-1", "linked.pdf")])
            spy = _Spy()
            inv = ar.LegacyRootInventory(
                roots.roots(), declared_roots=declared_map(roots), opener=spy,
                budget=ar.ScanBudget(allow_content_read=True))
            out = await readiness(reg, inv=inv).scan(ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert row["observed"]["checksum"] is None
            assert row["observed"]["refusal"] == ar.REASON_PATH_IS_LINK
            assert row["state"] not in (ar.MISSING_ORIGINAL, ar.READY_TO_ADOPT)
            assert ar.REASON_PATH_IS_LINK in row["reasons"]
            assert spy.opened == []
            # and nothing about the other tenant's bytes is anywhere
            assert "ANOTHER" not in repr(out["item_records"])
            assert "payroll" not in repr(out["item_records"])
        run(body())

    def test_every_walked_file_passed_the_gate(self, roots):
        """The invariant itself, with no link involved: positive control."""
        for name in ("a.pdf", "projects/b.pdf", "deep/c.pdf"):
            roots.write(name, b"content of " + name.encode())
        inv = inventory(roots)
        for obj in inv.walk():
            if obj.refusal is not None:
                continue
            absolute = os.path.join(obj.root, obj.relative_path)
            safe, refusal = ar.path_within_root(obj.root, absolute)
            assert safe is True, (obj.relative_path, refusal)
            assert obj.checksum is not None


# ════════════════════════════ C03 review — the inventory is actually bounded
class TestC03BoundedInventoryChargesEveryEntry:
    """`max_objects` bounds the ENUMERATION, not just the readable part of it.

    The C03 independent review's counterexample: a directory of refused
    symlinks produced one `PhysicalObject` per entry with `objects_seen` stuck
    at 0 and `truncated` never set, so both the work and the output grew with
    the directory while the configured limit said otherwise. C03 had charged
    only the entries that passed the gate — a reading these tests now forbid.
    """

    @staticmethod
    def _refused_links(roots, count, prefix="link"):
        """`count` real in-root symlinks, each to a real target outside it."""
        made = []
        for index in range(count):
            target = roots.write_outside("t%d.pdf" % index, b"SECRET %d" % index)
            link = os.path.join(roots.uploads, "%s%d.pdf" % (prefix, index))
            os.symlink(target, link)
            made.append(os.path.basename(link))
        return made

    @needs_symlinks
    def test_the_review_counterexample_three_refused_entries_one_allowance(
            self, roots):
        """Exactly the assignment's acceptance condition."""
        self._refused_links(roots, 3)
        spy = _Spy()
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots), opener=spy,
            budget=ar.ScanBudget(max_objects=1, allow_content_read=True))
        pass_ = inv.open_pass()
        found = inv.walk(pass_)
        assert len(found) <= 1, [o.relative_path for o in found]
        assert pass_.objects_seen == 1
        assert pass_.truncated is True
        # still refused before any stat, open or read
        assert found[0].refusal == ar.REASON_PATH_IS_LINK
        assert found[0].checksum is None
        assert pass_.bytes_read == 0
        assert spy.opened == [], "a refused path was opened"

    @needs_symlinks
    @pytest.mark.parametrize("entries", [3, 5, 12])
    def test_the_output_does_not_grow_with_the_directory(self, roots, entries):
        """The property the review named: work bounded by the limit, not the tree."""
        self._refused_links(roots, entries)
        inv = inventory(roots, max_objects=2)
        found = inv.walk()
        assert len(found) <= 2, len(found)
        assert inv.last_pass.objects_seen == 2
        assert inv.last_pass.truncated is True

    @needs_symlinks
    def test_a_zero_cap_enumerates_nothing_at_all(self, roots):
        """Zero means zero, refused entries included."""
        self._refused_links(roots, 3)
        roots.write("real.pdf", b"real bytes")
        spy = _Spy()
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots), opener=spy,
            budget=ar.ScanBudget(max_objects=0, allow_content_read=True))
        pass_ = inv.open_pass()
        assert inv.walk(pass_) == []
        assert pass_.objects_seen == 0
        assert pass_.truncated is True
        assert pass_.bytes_read == 0
        assert spy.opened == []

    @needs_symlinks
    def test_safe_and_refused_entries_share_one_allowance_in_either_order(
            self, roots):
        """Mixed order: whichever two come first spend the two charges."""
        # "aaa_link" sorts before "mmm_real", "zzz_link" after
        target = roots.write_outside("t.pdf", b"outside")
        os.symlink(target, os.path.join(roots.uploads, "aaa_link.pdf"))
        roots.write("mmm_real.pdf", b"readable bytes")
        os.symlink(target, os.path.join(roots.uploads, "zzz_link.pdf"))
        inv = inventory(roots, max_objects=2)
        found = inv.walk()
        assert [o.relative_path for o in found] == ["aaa_link.pdf",
                                                    "mmm_real.pdf"]
        assert found[0].refusal == ar.REASON_PATH_IS_LINK
        assert found[1].checksum is not None, "the safe object was not read"
        assert inv.last_pass.objects_seen == 2
        assert inv.last_pass.truncated is True

    @needs_symlinks
    def test_each_distinct_refused_link_is_charged_separately(self, roots):
        """Two different links to the SAME target are two entries, not one.

        This is why a refused entry is keyed by the path as enumerated: it has
        been refused precisely so that its link is NOT followed, so resolving
        it to decide identity would collapse two refusals into one charge.
        """
        target = roots.write_outside("one.pdf", b"shared target")
        os.symlink(target, os.path.join(roots.uploads, "a.pdf"))
        os.symlink(target, os.path.join(roots.uploads, "b.pdf"))
        inv = inventory(roots, max_objects=5)
        found = inv.walk()
        assert len(found) == 2
        assert {o.refusal for o in found} == {ar.REASON_PATH_IS_LINK}
        assert inv.last_pass.objects_seen == 2, "two refusals shared one charge"

    @needs_symlinks
    def test_the_same_refused_entry_seen_twice_is_charged_once(self, roots):
        """Cache semantics are preserved for refusals too: one entry, one charge."""
        target = roots.write_outside("t.pdf", b"outside")
        os.symlink(target, os.path.join(roots.uploads, "link.pdf"))
        inv = inventory(roots, max_objects=5)
        pass_ = inv.open_pass()
        walked = {o.relative_path: o for o in inv.walk(pass_)}["link.pdf"]
        assert pass_.objects_seen == 1
        # the SAME entry, now named by a DB row, in the same pass
        told = inv.observe_path("/app/backend/uploads/link.pdf", pass_)
        assert told.refusal == ar.REASON_PATH_IS_LINK
        assert walked.refusal == told.refusal
        assert pass_.objects_seen == 1, "one entry was charged twice"

    def test_a_safe_object_is_still_charged_once_across_both_entry_paths(self,
                                                                        roots):
        """The C02 shared-limit guarantee, unchanged by this correction."""
        roots.write("shared.pdf", b"shared bytes")
        inv = inventory(roots, max_objects=1)
        pass_ = inv.open_pass()
        inv.walk(pass_)
        assert pass_.objects_seen == 1
        told = inv.observe_path("/app/backend/uploads/shared.pdf", pass_)
        assert told.checksum is not None, "the cached observation was lost"
        assert told.refusal is None
        assert pass_.objects_seen == 1
        assert pass_.checksums_read == 1

    @needs_symlinks
    def test_a_repeated_pass_starts_with_the_whole_allowance(self, roots):
        """C02's per-pass budget survives: refusals do not leak between passes."""
        self._refused_links(roots, 3)
        inv = inventory(roots, max_objects=2)
        for _attempt in range(4):
            found = inv.walk()
            assert len(found) == 2
            assert inv.last_pass.objects_seen == 2
            assert inv.last_pass.truncated is True

    @needs_symlinks
    def test_a_db_row_naming_a_link_is_charged(self, roots):
        """The DB-row entry path charges the same allowance as the walk."""
        target = roots.write_outside("t.pdf", b"outside")
        os.symlink(target, os.path.join(roots.uploads, "row.pdf"))
        spy = _Spy()
        inv = ar.LegacyRootInventory(
            roots.roots(), declared_roots=declared_map(roots), opener=spy,
            budget=ar.ScanBudget(max_objects=5, allow_content_read=True))
        pass_ = inv.open_pass()
        told = inv.observe_path("/app/backend/uploads/row.pdf", pass_)
        assert told.refusal == ar.REASON_PATH_IS_LINK
        assert pass_.objects_seen == 1, "the DB-row refusal was not charged"
        assert spy.opened == []

    @needs_symlinks
    def test_a_refused_entry_beyond_the_cap_reports_the_budget_not_the_link(
            self, roots):
        """Once the allowance is gone, the budget is the first thing in the way."""
        self._refused_links(roots, 2)
        inv = inventory(roots, max_objects=1)
        pass_ = inv.open_pass()
        inv.walk(pass_)
        assert pass_.objects_seen == 1
        later = inv.observe_path("/app/backend/uploads/link1.pdf", pass_)
        assert later.refusal == ar.REASON_OBJECT_BUDGET_EXHAUSTED
        assert later.checksum is None
        assert pass_.objects_seen == 1


class TestC03BoundedInventoryThroughTheService:
    """Service-level: the scan and its stored plan report the truth."""

    @needs_symlinks
    def test_a_scan_over_refused_entries_is_bounded_and_says_so(self, roots):
        """The plan's inventory record must show the limit was reached."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            TestC03BoundedInventoryChargesEveryEntry._refused_links(roots, 3)
            spy = _Spy()
            inv = ar.LegacyRootInventory(
                roots.roots(), declared_roots=declared_map(roots), opener=spy,
                budget=ar.ScanBudget(max_objects=1, allow_content_read=True))
            out = await readiness(reg, inv=inv).scan(ctx(OPERATOR_A, A),
                                                      source_keys=["media_files"])
            assert out["inventory"]["objects_seen"] == 1
            assert out["inventory"]["truncated"] is True
            assert out["inventory"]["bytes_read"] == 0
            physical = [i for i in out["item_records"]
                        if i["direction"] == ar.DIRECTION_PHYSICAL_OBJECT]
            assert len(physical) <= 1, len(physical)
            assert spy.opened == [], "a refused path was opened"
            # nothing about the refused targets is anywhere in the plan
            assert "SECRET" not in repr(out["item_records"])
            assert "t0.pdf" not in repr(out["item_records"])
        run(body())

    @needs_symlinks
    def test_a_row_is_bounded_too_and_the_plan_revalidates(self, roots):
        """A legacy row whose object is a refused link, under a spent budget."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            TestC03BoundedInventoryChargesEveryEntry._refused_links(roots, 2)
            await _seed(db, A, "media_files", [_media_row("md-1", "link1.pdf")])
            spy = _Spy()
            inv = ar.LegacyRootInventory(
                roots.roots(), declared_roots=declared_map(roots), opener=spy,
                budget=ar.ScanBudget(max_objects=1, allow_content_read=True))
            service = readiness(reg, inv=inv)
            out = await service.scan(ctx(OPERATOR_A, A),
                                      source_keys=["media_files"])
            assert out["inventory"]["objects_seen"] == 1
            assert out["inventory"]["truncated"] is True
            row, = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            # the walk spent the allowance, so the row is budget-refused
            assert row["observed"]["refusal"] == \
                ar.REASON_OBJECT_BUDGET_EXHAUSTED
            assert row["observed"]["checksum"] is None
            # never a proven absence and never readiness
            assert row["state"] not in (ar.MISSING_ORIGINAL, ar.READY_TO_ADOPT)
            assert row["proposed_action"] != ar.PROPOSE_ADOPT_IN_PLACE
            assert spy.opened == []
            # and the same bounded inputs revalidate without inventing drift
            for _attempt in range(3):
                answer = await service.validate_plan(ctx(OPERATOR_A, A),
                                                      scan_id=out["id"])
                assert answer["valid"] is True, answer
                assert answer["plan_hash"] == out["plan_hash"]
        run(body())

    @needs_symlinks
    def test_a_bounded_scan_is_deterministic_across_repeats(self, roots):
        """Same inputs, same limit, same plan — every time."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            TestC03BoundedInventoryChargesEveryEntry._refused_links(roots, 4)
            roots.write("zzz_real.pdf", b"readable")
            hashes = []
            for _attempt in range(3):
                inv = ar.LegacyRootInventory(
                    roots.roots(), declared_roots=declared_map(roots),
                    budget=ar.ScanBudget(max_objects=2, allow_content_read=True))
                out = await readiness(reg, inv=inv).scan(
                    ctx(OPERATOR_A, A), source_keys=["media_files"],
                    persist=False)
                hashes.append(out["plan_hash"])
                assert out["inventory"]["objects_seen"] == 2
                assert out["inventory"]["truncated"] is True
            assert len(set(hashes)) == 1, "a bounded scan was not deterministic"
        run(body())

    def test_an_unbounded_scan_still_sees_everything(self, roots):
        """The positive control: the limit must not refuse ordinary work."""
        async def body():
            db, sysdb, reg = await _tenant_world()
            for index in range(3):
                roots.write("ok%d.pdf" % index, b"bytes %d" % index)
                await _seed(db, A, "media_files",
                            [_media_row("md-%d" % index, "ok%d.pdf" % index)])
            out = await readiness(reg, inv=inventory(roots)).scan(
                ctx(OPERATOR_A, A), source_keys=["media_files"])
            assert out["inventory"]["objects_seen"] == 3
            assert out["inventory"]["truncated"] is False
            rows = [i for i in out["item_records"]
                    if i["direction"] == ar.DIRECTION_DB_ROW]
            assert len(rows) == 3
            assert all(r["observed"]["checksum"] for r in rows)
            assert all(r["observed"]["refusal"] is None for r in rows)
        run(body())
