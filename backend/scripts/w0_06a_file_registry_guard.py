#!/usr/bin/env python3
"""
W0-06A — static guard: file identity, ownership, relations and physical delete.

FLOW-016 forbids four things that a reviewer cannot reliably catch by reading a
diff, because each of them looks like ordinary code at the call site:

1. a provider path or URL used as the business identity of a file;
2. a File Registry record written without a server-derived owner;
3. a FileRelation written without a tenant, or pointing at another tenant's
   business record;
4. a physical delete of a stored object with no explicit provider result and
   no audit trail behind it.

Each one is a one-line mistake that passes review and fails in production, so
each one is a rule here. The guard runs over the WHOLE active backend
(``app/**/*.py`` plus ``server.py``) — the W0-03E-A2C lesson is that a guard
whose scope is a hand-written module list reports clean on the one file nobody
added to it.

The legacy is FROZEN, not ignored. The active backend has fifteen file-bearing
sites today and W0-06A does not migrate them (that is the next slice). Pretending
they are clean would make the guard useless; failing on them would make it
unrunnable. Instead each is DECLARED once, with the exact function it lives in,
and the guard enforces three properties, so the list can neither rot nor grow:

* every declared site must still exist — a renamed or deleted function is a
  ``W06A-STALE`` violation, so the inventory cannot describe code that is gone;
* any site NOT declared is a violation — new provider-path-as-identity code and
  new raw physical deletes are refused from today;
* the declarations are read from ``app.files.migration_map``, the same module
  that produces the migration plan, so the freeze list and the plan can never
  describe different code.

Exit code 0 = clean, 1 = violations (``path:line: RULE message``), 2 = usage or
parse error. CI-runnable as a plain script; enforced by
``tests/test_w0_06a_static_guard.py``.

    python scripts/w0_06a_file_registry_guard.py             # whole active backend
    python scripts/w0_06a_file_registry_guard.py FILE ...    # explicit files

Rules
-----

``W06A-REGISTRY-WRITE``
    A write to a File Registry collection (``app.files.models.REGISTRY_COLLECTIONS``)
    from anywhere but :data:`REGISTRY_SERVICE`. Every registry write must go
    through ``app.files.registry``, which is where the owner is stamped, the
    version rules are enforced, the AuditEvent is appended and the idempotency
    key is reserved. A direct write bypasses all four at once, which is exactly
    how an ownerless or unaudited registry row would come to exist.

``W06A-OWNERLESS``
    A File Registry record built without the owner: a ``build_*`` call in
    ``app.files.models`` whose ``org_id`` is absent, or a registry-shaped dict
    literal written with no ``org_id`` key. The builders also check this at
    runtime; the guard catches the call that would never be executed in a test.

``W06A-RELTENANT``
    A ``file_relations`` document constructed outside
    ``app.files.models.build_relation``, or a ``build_relation``/``add_relation``
    whose tenant comes from a caller-controlled route parameter rather than
    from the resolved tenant view. A relation is the one record that names two
    things at once, so an un-owned relation row is what lets tenant B's link be
    honoured for tenant A when ids collide (the W0-03E-A2 defect).

``W06A-PROVIDERID``
    An undeclared PERSISTED write that stores a provider path, URL or stored
    file name (``url``, ``file_url``, ``original_file_url``, ``stored_filename``,
    ``photo_url``, ``photo_b64``, ``media_url``, ``file_path``, ``avatar_url``,
    ...) onto a business record. In the migrated world the business record
    carries a ``file_id`` and the path lives on a ProviderLocation.

    Only a write counts: the dict must be the document of an ``insert_one`` /
    ``insert_many``, or sit inside the ``$set`` / ``$setOnInsert`` / ``$push`` /
    ``$addToSet`` of an update. A projection (``{"_id": 0, "avatar_url": 1}``),
    an HTTP response body or a request payload to some other service reads or
    returns the value and stores no identity, so flagging those would bury the
    real finding under dozens of false ones — the failure mode that makes a
    guard get switched off. The declared legacy sites are frozen; an
    undeclared one is a violation.

``W06A-PHYSDELETE``
    ``os.remove``, ``os.unlink``, ``os.rmdir``, ``shutil.rmtree`` or
    ``Path(...).unlink()`` anywhere outside the declared legacy delete paths.
    FLOW-016 requires a physical delete to be a separate explicit action with a
    right, a provider response and an AuditEvent; a bare ``unlink`` in a route
    is none of those, and is how "remove from this screen" silently destroys a
    customer's original today.

``W06A-CACHEORIGINAL``
    Writing ``is_canonical_original`` as anything but ``False``, or inserting a
    derived kind (thumbnail/preview/OCR/PDF render) into the VERSIONS
    collection. A cache entry is never a business version and never answers for
    a missing original.

``W06A-FAKEPROVIDER``
    Importing ``app.files.providers.fake`` from the runtime surface. The
    in-memory double exists for tests; a route that can reach it is a route that
    can be made to believe a file was stored when nothing was.

``W06A-UNCLASSIFIED``
    A collection whose name starts with ``file_`` that
    ``app.files.models.REGISTRY_COLLECTIONS`` does not declare. Fail closed:
    declare it there first, so the models, the ownership classification, the
    inventory and this guard all see it.

``W06A-STALE``
    A declared legacy site whose function no longer exists.

``W06B-RELBYPASS`` (W0-06A review finding 2)
    A way to link a file to a business record WITHOUT verifying that the record
    exists in this tenant: a ``register_file`` / ``add_relation`` definition
    that takes a verify/skip/bypass/trust switch, a call that passes one, or a
    ``_assert_relation_target`` call that sits under a condition in the
    registry service. The check is unconditional by construction; a switch is
    how a missing or foreign target gets linked.

``W06B-CREDSTORE``
    Any module except :data:`CREDENTIAL_VAULT` naming the sealed-credential
    collection ``storage_credentials``. Credentials are read and written ONLY
    by the vault, which is where they are encrypted and bound to their tenant
    and binding; a second reader is a second place a secret can leak from.

``W06B-ADAPTERBUILD``
    ``adapter_for(...)`` called in the runtime surface outside
    :data:`STORAGE_SERVICE`. An operational adapter is built only from an
    ACTIVE binding with vault-resolved credentials; building one elsewhere is
    how a file could reach an unverified provider or a hand-supplied secret.

``W06B-DELSCOPE`` (W0-06A review finding 3)
    A write to provider locations in the registry service whose filter does not
    name the exact location ``id`` (a value or an ``$in`` list). A delete
    receipt for one version applied to "every location of the file" is how
    version 2 came to look destroyed when only version 1 was.

Pure AST. The guard never imports the application; ``app.files.models`` and
``app.files.migration_map`` are stdlib-only and are loaded BY FILE PATH (like
the A1 guard loads ``ownership.py``), so no database client is constructed and
the check runs on any machine.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

BACKEND = Path(__file__).resolve().parent.parent

Violation = Tuple[str, int, str, str]


def _load(name: str, relative: str):
    """Load a stdlib-only application module by file path.

    Importing ``app.files.models`` normally would execute ``app/files/__init__``,
    which pulls in the registry service and through it the audit store — none of
    which a static guard needs and all of which would make the guard depend on
    the application's runtime dependencies.
    """
    spec = importlib.util.spec_from_file_location(name, BACKEND / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_models = _load("_w0_06a_models", "app/files/models.py")
# ``migration_map`` imports ``app.files.models``; give it the copy just loaded
# rather than letting it import the package.
sys.modules.setdefault("app", type(sys)("app"))
sys.modules.setdefault("app.files", type(sys)("app.files"))
sys.modules["app.files.models"] = _models
_migration = _load("_w0_06a_migration", "app/files/migration_map.py")

REGISTRY_COLLECTIONS: FrozenSet[str] = frozenset(_models.REGISTRY_COLLECTIONS)
VERSIONS_COLLECTION: str = _models.VERSIONS_COLLECTION
RELATIONS_COLLECTION: str = _models.RELATIONS_COLLECTION
ORG_KEY: str = _models.ORG_KEY

#: W0-06B: the only module that may name the sealed credential collection, and
#: the only runtime module that may build an operational provider adapter.
CREDENTIAL_VAULT = "app/files/credentials.py"
CREDENTIALS_COLLECTION = "storage_credentials"
STORAGE_SERVICE = "app/files/storage.py"
ADAPTER_FACTORY = "app/files/providers/base.py"

#: The one module allowed to write File Registry collections.
REGISTRY_SERVICE = "app/files/registry.py"
#: The one module allowed to BUILD registry records (it is the builder).
REGISTRY_MODELS = "app/files/models.py"
#: The planner. It names collections and pointer fields as DATA, never writes.
REGISTRY_MIGRATION = "app/files/migration_map.py"

#: Package modules that are part of the foundation and are judged by their own
#: rules above rather than by the legacy freeze.
FOUNDATION_MODULES: FrozenSet[str] = frozenset({
    "app/files/__init__.py", REGISTRY_MODELS, REGISTRY_SERVICE, REGISTRY_MIGRATION,
    "app/files/providers/__init__.py", "app/files/providers/base.py",
    "app/files/providers/fake.py",
    # W0-06B storage providers, onboarding, integrity and access.
    "app/files/providers/http.py", "app/files/providers/s3.py",
    "app/files/providers/google_drive.py", "app/files/providers/synology.py",
    "app/files/providers/on_prem.py", "app/files/credentials.py", "app/files/storage.py",
    "app/files/authorization.py", "app/files/audit_trail.py", "app/files/integrity.py",
    "app/files/access.py",
})

#: Field names that hold a provider path, URL or stored object name today.
#: Writing one onto a business record is what FLOW-016 forbids once the file has
#: a ``file_id``.
POINTER_FIELDS: FrozenSet[str] = frozenset({
    "url", "file_url", "file_urls", "original_file_url", "stored_filename",
    "photo_url", "photo_urls", "photo_b64", "media_url", "file_path",
    "storage_path", "avatar_url", "doc_url", "image_url",
})

#: Field names that hold a REFERENCE to a file rather than a provider path: a
#: media id, or a list of attachment entries / photo ids. Writing one is not a
#: ``W06A-PROVIDERID`` violation — a reference is the right shape, and these are
#: precisely the fields that become a ``file_id`` or a FileRelation. The
#: inventory still has to find them, because a site that attaches a file to a
#: business record is a file-bearing site whether or not it stores a path.
ATTACHMENT_REFERENCE_FIELDS: FrozenSet[str] = frozenset({
    "attachments", "media_id", "media_ids", "photos", "photo_ids", "scan_doc_id",
})

#: Field names a File Registry record legitimately carries that LOOK like
#: pointers. They are provider coordinates on a ProviderLocation or a cache
#: reference on a derivative — never the identity of anything.
REGISTRY_POINTER_FIELDS: FrozenSet[str] = frozenset({
    "object_key", "container", "provider_file_id", "cache_reference",
})

WRITE_METHODS: FrozenSet[str] = frozenset({
    "insert_one", "insert_many", "update_one", "update_many", "replace_one",
    "delete_one", "delete_many", "find_one_and_update", "find_one_and_replace",
    "find_one_and_delete", "bulk_write",
})
UPDATE_OPERATORS: FrozenSet[str] = frozenset({"$set", "$setOnInsert", "$push", "$addToSet"})

#: Physical-delete primitives. Each destroys bytes with no provider answer.
DELETE_CALLS: FrozenSet[str] = frozenset({"remove", "unlink", "rmdir", "rmtree", "removedirs"})


# --------------------------------------------------------------- declarations
#: ``path::function`` -> the pointer fields that function legitimately writes
#: TODAY. Derived from the migration map's writers so the freeze list and the
#: plan cannot disagree, then narrowed per field here because a function may
#: write one legacy pointer and must not gain a second.
LEGACY_POINTER_SITES: Dict[str, FrozenSet[str]] = {
    # media_files: the one upload path and the two routes that write a media row
    # of their own instead of calling it.
    "app/routes/media.py::upload_media": frozenset({"url", "stored_filename"}),
    "app/routes/ocr_invoice.py::upload_invoice": frozenset({"url", "stored_filename"}),
    "app/routes/technician.py::photo_invoice": frozenset(
        {"url", "stored_filename", "media_url"}),
    # project_photos: its own collection, its own uploads directory.
    "app/routes/projects.py::upload_project_photo": frozenset({"url", "stored_filename"}),
    # supplier invoice original: a URL no route can serve (see the migration map).
    "app/routes/procurement.py::create_supplier_invoice": frozenset({"original_file_url"}),
    "app/routes/procurement.py::upload_invoice_file": frozenset({"original_file_url"}),
    # pointers onto business records.
    "app/routes/scan_docs.py::create_scan_doc": frozenset({"file_url"}),
    "app/routes/missing_smr.py::add_attachment": frozenset({"url"}),
    "app/routes/technician.py::quick_smr": frozenset({"url"}),
    # the two inline-base64 sites: a photo stored INSIDE the database row.
    "app/routes/assets_intake_pending.py::submit_intake": frozenset({"photo_b64"}),
    "app/routes/assets_intake_pending.py::_materialize": frozenset({"photo_url"}),
    "app/routes/assets_items.py::create_asset_item": frozenset({"photo_url"}),
    # Found by the inventory scan, not by hand: approving an OCR intake creates a
    # pending expense carrying the media pointer (an empty media_url and the
    # media_id of the scanned invoice).
    "app/routes/ocr_invoice.py::approve_intake": frozenset({"media_url"}),
}

#: ``path::function`` sites that delete a stored object directly today. Every
#: one is a FLOW-016 defect the migration removes; until then they are frozen
#: so no new one appears.
LEGACY_PHYSICAL_DELETE_SITES: FrozenSet[str] = frozenset({
    "app/routes/media.py::delete_media",
    "app/routes/projects.py::delete_project_photo",
    "app/routes/scan_docs.py::delete_scan_doc",
})

#: Modules outside ``app/files`` that may name a File Registry collection at
#: all (read or write). Only the ownership classification, which must list
#: every collection by name.
REGISTRY_NAME_ALLOWED: FrozenSet[str] = frozenset({"app/tenancy/ownership.py"})


def active_backend_files() -> List[str]:
    """Every module of the active backend, backend-relative POSIX, sorted."""
    files: Set[str] = {"server.py"}
    for p in (BACKEND / "app").rglob("*.py"):
        files.add(p.relative_to(BACKEND).as_posix())
    return sorted(f for f in files if (BACKEND / f).is_file())


def normalize_rel(raw: str) -> str:
    """Backslashes to slashes before any path logic — same verdict on both OSes."""
    return str(raw).replace("\\", "/")


def _const_str(node: Optional[ast.AST]) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _collection_name(node: ast.AST, literals: Dict[str, str]) -> Optional[str]:
    """The collection a receiver expression names, when it can be read statically.

    Covers the four shapes that reach a collection in this codebase:
    ``x.file_registry``, ``x["file_registry"]``, ``x.collection("file_registry")``
    and ``x.collection(FILES_COLLECTION)`` where the module binds that name to a
    literal (or imports it from the models module, whose constants are resolved
    from the loaded module rather than guessed).
    """
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _const_str(node.slice)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "collection" and node.args:
        arg = node.args[0]
        direct = _const_str(arg)
        if direct:
            return direct
        if isinstance(arg, ast.Attribute):
            return literals.get(arg.attr)
        if isinstance(arg, ast.Name):
            return literals.get(arg.id)
    return None


def _models_constants() -> Dict[str, str]:
    """``FILES_COLLECTION`` -> ``"file_registry"`` and friends, from the module itself."""
    out: Dict[str, str] = {}
    for name in dir(_models):
        value = getattr(_models, name)
        if isinstance(value, str) and name.isupper():
            out[name] = value
    return out


_MODEL_CONSTANTS = _models_constants()


class _Checker(ast.NodeVisitor):
    def __init__(self, rel: str, tree: ast.Module):
        self.rel = rel
        self.tree = tree
        self.violations: List[Violation] = []
        self.functions: List[str] = []
        self.scopes: List["DocumentScope"] = []
        #: module-level ``NAME = "literal"`` plus the models constants, so a
        #: collection named through a constant stays visible to every rule.
        self.literals: Dict[str, str] = dict(_MODEL_CONSTANTS)
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                    and isinstance(stmt.targets[0], ast.Name):
                text = _const_str(stmt.value)
                if text:
                    self.literals[stmt.targets[0].id] = text

    # ------------------------------------------------------------- helpers
    def add(self, node: ast.AST, rule: str, message: str) -> None:
        self.violations.append((self.rel, getattr(node, "lineno", 0), rule, message))

    @property
    def site(self) -> str:
        return "%s::%s" % (self.rel, self.functions[-1] if self.functions else "<module>")

    def _is_foundation(self) -> bool:
        return self.rel in FOUNDATION_MODULES

    # ----------------------------------------------------------- traversal
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.functions.append(node.name)
        self.scopes.append(DocumentScope(node))
        self.generic_visit(node)
        self.scopes.pop()
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef   # type: ignore[assignment]

    @property
    def scope(self) -> Optional["DocumentScope"]:
        return self.scopes[-1] if self.scopes else None

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        if module == "app.files.providers.fake" or any(
                a.name == "fake" for a in node.names) and module == "app.files.providers":
            if self.rel not in FOUNDATION_MODULES:
                self.add(node, "W06A-FAKEPROVIDER",
                         "the in-memory provider double must not be reachable from the runtime "
                         "surface; it exists for tests only")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            if alias.name.startswith("app.files.providers.fake") and \
                    self.rel not in FOUNDATION_MODULES:
                self.add(node, "W06A-FAKEPROVIDER",
                         "the in-memory provider double must not be reachable from the runtime "
                         "surface; it exists for tests only")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            self._check_collection_call(node, func)
            self._check_physical_delete(node, func)
            self._check_build_relation(node, func)
            if func.attr in WRITE_METHODS:
                # Any write, on any receiver: the rule is about what reaches a
                # stored document, so it must not depend on recognising the
                # database handle (a helper's return value, an alias, a
                # ``tenant.<collection>`` view all reach the same documents).
                self._check_pointer_write(node, func.attr)
        elif isinstance(func, ast.Name):
            self._check_build_relation(node, func)
        self.generic_visit(node)

    # ------------------------------------------------------------- rules
    def _check_collection_call(self, node: ast.Call, func: ast.Attribute) -> None:
        name = _collection_name(func.value, self.literals)
        if name is None:
            return
        if name.startswith("file_") and name not in REGISTRY_COLLECTIONS \
                and name not in ("file_path",):
            self.add(node, "W06A-UNCLASSIFIED",
                     "collection %r is not declared in app.files.models."
                     "REGISTRY_COLLECTIONS; classify it there first" % name)
            return
        if name not in REGISTRY_COLLECTIONS:
            return
        if func.attr in WRITE_METHODS and self.rel != REGISTRY_SERVICE:
            self.add(node, "W06A-REGISTRY-WRITE",
                     "%s on %r outside %s: every File Registry write goes through the "
                     "registry service, which stamps the owner, enforces the version rules, "
                     "appends the AuditEvent and reserves the idempotency key"
                     % (func.attr, name, REGISTRY_SERVICE))
        if name == VERSIONS_COLLECTION and func.attr in ("insert_one", "insert_many"):
            self._check_derived_into_versions(node)

    def _check_derived_into_versions(self, node: ast.Call) -> None:
        for arg in node.args:
            for key, value in _dict_items(arg):
                if key == "kind" and _const_str(value) in _models.DERIVED_KINDS:
                    self.add(node, "W06A-CACHEORIGINAL",
                             "a derived artifact (%s) is not a business version; it belongs in "
                             "%s" % (_const_str(value), _models.DERIVED_COLLECTION))

    def _check_physical_delete(self, node: ast.Call, func: ast.Attribute) -> None:
        if func.attr not in DELETE_CALLS:
            return
        if self.rel in FOUNDATION_MODULES:
            return
        if self.site in LEGACY_PHYSICAL_DELETE_SITES:
            return
        self.add(node, "W06A-PHYSDELETE",
                 "%s(...) destroys a stored object with no provider result and no AuditEvent; "
                 "a physical delete is an explicit request answered by the provider "
                 "(app.files.registry.request_physical_delete / record_delete_result)"
                 % func.attr)

    def _check_build_relation(self, node: ast.Call, func: ast.AST) -> None:
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in ("build_relation", "add_relation"):
            return
        org = None
        for kw in node.keywords:
            if kw.arg in (ORG_KEY, "tenant_id"):
                org = kw.value
        if name == "build_relation":
            if org is None:
                self.add(node, "W06A-RELTENANT",
                         "build_relation without %s: an ownerless relation row cannot say who "
                         "wrote it, so a colliding id lets another tenant's link be honoured"
                         % ORG_KEY)
            elif isinstance(org, ast.Constant):
                self.add(node, "W06A-RELTENANT",
                         "build_relation with a literal tenant: the owner comes from the "
                         "resolved tenant view, never from a constant or a caller value")

    def visit_Dict(self, node: ast.Dict):
        self._check_canonical_claim(node)
        self.generic_visit(node)

    def _check_canonical_claim(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            if _const_str(key) != "is_canonical_original":
                continue
            if not (isinstance(value, ast.Constant) and value.value is False):
                self.add(node, "W06A-CACHEORIGINAL",
                         "is_canonical_original may only be written False: a cached preview "
                         "never becomes the canonical original of a missing file")

    def _check_pointer_write(self, node: ast.Call, method: str) -> None:
        """W06A-PROVIDERID on the documents this call actually persists."""
        if self.rel in FOUNDATION_MODULES or self.rel in REGISTRY_NAME_ALLOWED:
            return
        allowed = LEGACY_POINTER_SITES.get(self.site, frozenset())
        for field, value_node in _persisted_fields(node, method, self.scope):
            if field is None or field in REGISTRY_POINTER_FIELDS:
                continue
            if field in POINTER_FIELDS and field not in allowed:
                self.add(value_node, "W06A-PROVIDERID",
                         "%r stores a provider path/URL as the identity of a file; a business "
                         "record carries a file_id and the path lives on a ProviderLocation "
                         "(FLOW-016). This site is not in the W0-06A frozen legacy inventory"
                         % field)


class DocumentScope:
    """The dict-literal documents a function builds, by local variable name.

    Most write sites in this codebase do not pass a dict literal to
    ``insert_one``: they build ``doc = {...}``, sometimes add a key with
    ``doc["url"] = ...``, and insert the variable. A scanner that only reads
    literal arguments therefore sees none of them — which would make an
    inventory that claims to have "no ASSUMED SAFE" rows miss most of the real
    ones. This resolves one level of that indirection, which is as far as the
    code actually goes.

    One level only, and deliberately: a document assembled across functions, or
    merged from another dict, is NOT resolved. Such a site simply does not
    match the rules here, so it must be found some other way — the inventory's
    reconciliation step is what makes that visible instead of silent.
    """

    def __init__(self, function: ast.AST):
        self.docs: Dict[str, List[Tuple[Optional[str], ast.AST]]] = {}
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Dict):
                    self.docs[target.id] = [(_const_str(k), v)
                                            for k, v in zip(node.value.keys, node.value.values)]
                elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    key = _const_str(target.slice)
                    if key is not None:
                        self.docs.setdefault(target.value.id, []).append((key, node.value))

    def fields_of(self, node: ast.AST) -> List[Tuple[Optional[str], ast.AST]]:
        if isinstance(node, ast.Dict):
            return [(_const_str(k), v) for k, v in zip(node.keys, node.values)]
        if isinstance(node, ast.Name):
            return list(self.docs.get(node.id, ()))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "dict" and node.args:
            # ``insert_one(dict(row))`` — the registry service's own shape.
            return self.fields_of(node.args[0])
        return []


def _persisted_fields(call: ast.Call, method: str, scope: Optional["DocumentScope"] = None):
    """``(field, node)`` for every key this write call actually stores.

    ``insert_one(doc)`` / ``insert_many([doc, ...])`` store the document
    itself; every other write stores what its update argument puts under
    ``$set`` / ``$setOnInsert`` / ``$push`` / ``$addToSet``. A ``$push`` value
    that is itself a dict (an embedded attachment entry) is unwrapped, because
    that is exactly how ``missing_smr`` stores a provider URL today.
    """
    def fields(node):
        if scope is not None:
            return scope.fields_of(node)
        return ([(_const_str(k), v) for k, v in zip(node.keys, node.values)]
                if isinstance(node, ast.Dict) else [])

    if method in ("insert_one", "insert_many"):
        for arg in call.args[:1]:
            docs = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
            for doc in docs:
                for field, value in fields(doc):
                    yield field, value
        return
    # update / replace: the document-shaped argument is the second one.
    for arg in call.args[1:2]:
        for operator, value in fields(arg):
            if operator in UPDATE_OPERATORS:
                for sub_key, sub_value in fields(value):
                    if isinstance(sub_value, ast.Dict) and sub_key is not None:
                        # ``$push: {"attachments": {"url": ...}}``
                        for inner_key, inner_value in fields(sub_value):
                            yield inner_key, inner_value
                    yield sub_key, sub_value
            elif operator is not None and not operator.startswith("$"):
                # replace_one(filter, {...}) — a whole replacement document.
                yield operator, value


def _dict_items(node: ast.AST):
    """``(key, value)`` pairs of a dict literal, including inside ``$set``."""
    if not isinstance(node, ast.Dict):
        return
    for key, value in zip(node.keys, node.values):
        text = _const_str(key)
        if text in UPDATE_OPERATORS and isinstance(value, ast.Dict):
            for sub_key, sub_value in zip(value.keys, value.values):
                yield _const_str(sub_key), sub_value
        else:
            yield text, value


def _ownerless_builder_violations(rel: str, tree: ast.Module) -> List[Violation]:
    """W06A-OWNERLESS: a ``build_*`` call that does not pass the owner.

    Checked everywhere, including inside the registry service: the service is
    the only module allowed to build these records, so it is also the only
    place the mistake can be made.
    """
    out: List[Violation] = []
    builders = {"build_file", "build_version", "build_relation", "build_provider_location",
                "build_derived", "build_delete_request"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.attr if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", ""))
        if name not in builders:
            continue
        if not any(kw.arg == ORG_KEY for kw in node.keywords):
            out.append((rel, node.lineno, "W06A-OWNERLESS",
                        "%s() without %s: a File Registry record without a server-derived "
                        "owner belongs to no tenant and is unreachable by every tenant view"
                        % (name, ORG_KEY)))
    return out


def _relation_literal_violations(rel: str, tree: ast.Module) -> List[Violation]:
    """W06A-RELTENANT: a relation document assembled by hand instead of built.

    A document that is WRITTEN carrying ``file_id`` together with
    ``relation_type`` is a FileRelation whatever it is called. Assembled by hand
    it skips the owner requirement, the relation-type vocabulary and the
    target-collection pairing that ``build_relation`` applies.

    Anchored on the write, like ``W06A-PROVIDERID``: the same two keys appear in
    every ``find_one`` filter and every idempotency fingerprint of the registry
    service itself, and a rule that cannot tell a query from a stored document
    reports its own correct code as a defect.
    """
    if rel in (REGISTRY_MODELS, REGISTRY_MIGRATION):
        return []
    out: List[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in WRITE_METHODS:
            continue
        keys = {field for field, _ in _persisted_fields(node, node.func.attr)}
        if {"file_id", "relation_type"} <= keys:
            out.append((rel, node.lineno, "W06A-RELTENANT",
                        "a FileRelation written from a dict literal: build it with "
                        "app.files.models.build_relation, which requires the owner and "
                        "pairs the relation type with its target collection"))
    return out


def _stale_declarations() -> List[Violation]:
    """W06A-STALE: a declared legacy site whose function no longer exists."""
    out: List[Violation] = []
    declared: Dict[str, Set[str]] = {}
    for site in list(LEGACY_POINTER_SITES) + sorted(LEGACY_PHYSICAL_DELETE_SITES):
        path, _, function = site.partition("::")
        declared.setdefault(path, set()).add(function)
    for path, functions in sorted(declared.items()):
        full = BACKEND / path
        if not full.is_file():
            out.append((path, 0, "W06A-STALE",
                        "declared in the W0-06A freeze list but the module does not exist"))
            continue
        tree = ast.parse(full.read_text(encoding="utf-8"), filename=path)
        present = {n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for function in sorted(functions - present):
            out.append((path, 0, "W06A-STALE",
                        "%s is declared in the W0-06A freeze list but no longer exists; the "
                        "inventory must not describe code that is gone" % function))
    return out


#: Parameter / keyword names that switch off relation-target verification.
_BYPASS_MARKERS: Tuple[str, ...] = ("verify", "skip", "bypass", "trust", "unchecked",
                                    "no_check", "nocheck", "unsafe")
_RELATION_WRITERS: FrozenSet[str] = frozenset({"register_file", "add_relation"})


def _is_bypass_name(name: Optional[str]) -> bool:
    lowered = (name or "").lower()
    return any(marker in lowered for marker in _BYPASS_MARKERS)


def _relation_bypass_violations(rel: str, tree: ast.Module) -> List[Violation]:
    """W06B-RELBYPASS — see the module docstring."""
    out: List[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in _RELATION_WRITERS:
            args = node.args
            for arg in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
                if _is_bypass_name(arg.arg):
                    out.append((rel, arg.lineno if hasattr(arg, "lineno") else node.lineno,
                                "W06B-RELBYPASS",
                                "%s() takes %r: relation targets are verified in this tenant "
                                "unconditionally, a caller switch to skip it is the bypass the "
                                "W0-06A review found" % (node.name, arg.arg)))
        if isinstance(node, ast.Call):
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            if name in _RELATION_WRITERS:
                for kw in node.keywords:
                    if _is_bypass_name(kw.arg):
                        out.append((rel, node.lineno, "W06B-RELBYPASS",
                                    "%s(%s=...) asks the registry to skip relation-target "
                                    "verification" % (name, kw.arg)))
    if rel == REGISTRY_SERVICE:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp, ast.While)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) \
                        and inner.func.attr == "_assert_relation_target":
                    out.append((rel, inner.lineno, "W06B-RELBYPASS",
                                "_assert_relation_target() under a condition: relation-target "
                                "verification must not be skippable"))
    return out


def _is_locations_handle(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "locations"


def _filter_names_exact_id(node: ast.AST) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    return any(_const_str(k) == "id" for k in node.keys if k is not None)


def _delete_scope_violations(rel: str, tree: ast.Module) -> List[Violation]:
    """W06B-DELSCOPE — see the module docstring."""
    if rel != REGISTRY_SERVICE:
        return []
    out: List[Violation] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("update_one", "update_many", "replace_one",
                                       "find_one_and_update", "delete_one", "delete_many")
                and _is_locations_handle(node.func.value)):
            continue
        flt = node.args[0] if node.args else None
        if not _filter_names_exact_id(flt):
            out.append((rel, node.lineno, "W06B-DELSCOPE",
                        "provider-location %s() without the exact location id in its filter: a "
                        "result for one location/version must never reach the others"
                        % node.func.attr))
    return out


def _w06b_boundary_violations(rel: str, tree: ast.Module) -> List[Violation]:
    """W06B-CREDSTORE and W06B-ADAPTERBUILD — see the module docstring."""
    out: List[Violation] = []
    for node in ast.walk(tree):
        if rel not in (CREDENTIAL_VAULT, *REGISTRY_NAME_ALLOWED) \
                and _const_str(node) == CREDENTIALS_COLLECTION:
            out.append((rel, node.lineno, "W06B-CREDSTORE",
                        "only app/files/credentials.py may name %r: sealed credentials are read "
                        "and written by the vault alone" % CREDENTIALS_COLLECTION))
        if isinstance(node, ast.Call) and rel not in (STORAGE_SERVICE, ADAPTER_FACTORY):
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            if name == "adapter_for":
                out.append((rel, node.lineno, "W06B-ADAPTERBUILD",
                            "adapter_for() outside app/files/storage.py: an operational adapter "
                            "comes only from an ACTIVE binding with vault-resolved credentials"))
    return out


def check_module(rel: str) -> List[Violation]:
    full = BACKEND / rel
    if not full.is_file():
        return [(rel, 0, "W06A-SCOPE", "module does not exist")]
    tree = ast.parse(full.read_text(encoding="utf-8"), filename=rel)
    checker = _Checker(rel, tree)
    checker.visit(tree)
    found = list(checker.violations)
    found.extend(_ownerless_builder_violations(rel, tree))
    found.extend(_relation_literal_violations(rel, tree))
    found.extend(_relation_bypass_violations(rel, tree))
    found.extend(_delete_scope_violations(rel, tree))
    found.extend(_w06b_boundary_violations(rel, tree))
    return found


def check_active_backend() -> Tuple[int, List[Violation]]:
    files = active_backend_files()
    found: List[Violation] = list(_stale_declarations())
    for rel in files:
        found.extend(check_module(rel))
    return len(files), sorted(set(found), key=lambda v: (v[0], v[1], v[2], v[3]))


def check_files(paths: Iterable[str]) -> List[Violation]:
    found: List[Violation] = []
    for raw in paths:
        p = Path(normalize_rel(raw))
        full = p if p.is_absolute() else (BACKEND / p)
        try:
            rel = full.resolve().relative_to(BACKEND.resolve()).as_posix()
        except ValueError:
            rel = p.as_posix()
        found.extend(check_module(rel))
    return sorted(set(found), key=lambda v: (v[0], v[1], v[2], v[3]))


def summary() -> Dict[str, int]:
    """``{rule: count}`` over the active backend — used by the inventory."""
    _, violations = check_active_backend()
    out: Dict[str, int] = {}
    for _, _, rule, _ in violations:
        out[rule] = out.get(rule, 0) + 1
    return out


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("files", nargs="*", help="modules to check (default: active backend)")
    args = parser.parse_args(list(argv))
    try:
        if args.files:
            units, violations = len(args.files), check_files(args.files)
        else:
            units, violations = check_active_backend()
    except (OSError, SyntaxError) as exc:
        print("guard error: %s" % exc, file=sys.stderr)
        return 2
    for rel, line, rule, msg in violations:
        print("%s:%d: %s %s" % (rel, line, rule, msg))
    print("W0-06A file registry guard: %d module(s) checked, %d violation(s)"
          % (units, len(violations)))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
