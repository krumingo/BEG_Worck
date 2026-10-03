#!/usr/bin/env python3
"""
W0-03E-A2C — static guard: the tenant boundary over the WHOLE active backend.

Why this guard exists in addition to the A1/A2/A2B guard. The A1 guard proved
its rules work, but it applied them to a hand-listed ``PROTECTED_MODULES`` set.
The W0-03E-A2B review (``coordination/REVIEWS/W0-03E-A2B.md``) then found a
registered financial route, ``app/routes/invoice_lines.py``, that was simply not
on that list: a clean "403 units, 0 violations" run never looked at it, while
the same rules applied to it directly produced 37 violations and one of them was
an exploitable cross-tenant financial write. A guard whose scope is a list is a
guard that reports clean on the one file nobody added.

So this guard has no module list. Its scope is every Python module of the active
backend (``app/**/*.py`` plus ``server.py``) and the operator scripts that write
tenant-owned data, and it decides what a rule demands from the COLLECTION rather
than from the file: the one classification in ``app.tenancy.ownership`` says
whether a collection is tenant-owned (``ORG_KEYED``), a ``tenant_id``-keyed
W0-03/W0-04 store, the tenant root, or technical bookkeeping. A collection that
is in none of those classes is a violation, not a pass, so a newly added
collection cannot slip through by being unknown.

Exit code 0 = clean, 1 = violations (``path:line: RULE message``), 2 = usage or
parse error. CI-runnable as a plain script; enforced by
``tests/test_w0_03e_a2c_static_guard.py``.

    python scripts/w0_03e_a2c_tenant_boundary_guard.py            # whole active backend
    python scripts/w0_03e_a2c_tenant_boundary_guard.py FILE ...   # explicit files

Rules
-----

``A2C-READ``
    A read (``find``, ``find_one``, ``count_documents``, ``distinct``,
    ``aggregate``, ``watch``) through a RAW database handle on a tenant-owned
    collection whose filter does not provably carry the tenant key. "Provably"
    means a dict literal containing ``org_id``/``tenant_id`` (or
    ``scoped(...)``/``_scope(...)``, which append the tenant last); a filter
    held in a variable cannot be proven and is rejected. For ``aggregate`` the
    FIRST stage must be the tenant ``$match``. This is the bare-ID read of
    Issue #41 §2 — ``find_one({"id": x})`` returns whichever tenant's document
    the database reaches first once ids collide.

``A2C-WRITE``
    An ``update_one``/``update_many``/``delete_one``/``delete_many``/
    ``replace_one``/``find_one_and_update``/``find_one_and_replace``/
    ``find_one_and_delete`` through a raw handle on a tenant-owned collection
    whose FILTER does not provably carry the tenant key. Issue #41 §3: a prior
    tenant-scoped read is explicitly not enough, because between the read and
    the write the filter is a bare business id again — which is exactly how
    ``update_invoice_line`` proved an A line and then wrote B's.

``A2C-IDENTITY``
    An identity-bearing collection (``app.tenancy.data_access.ENTITY_COLLECTIONS``
    plus ``organizations``) touched through a raw handle at all — read, write or
    as a bare value — outside the tenancy core and the operator scripts. Those
    records are reached only through ``TenantData``. Being the join target of
    every enrichment, they are the collections where a bare id does the most
    damage, so for them a hand-written predicate is not accepted either.

``A2C-SETTINGS``
    A write to a tenant-owned collection whose ``_id`` is a bare global string
    literal (in the filter or in ``$set``/``$setOnInsert``). ``_id`` is unique
    per collection, so a global literal means the installation can hold exactly
    one such row: the first tenant to save owns it and every other tenant's
    upsert fails with a duplicate key. Use
    ``app.tenancy.settings_identity.settings_id(key, org_id)``. An ``_id`` built
    from the tenant (a ``settings_id(...)`` call, or an f-string/concatenation
    naming the org) is accepted.

``A2C-UNCLASSIFIED``
    A collection reached by name that ``app.tenancy.ownership`` does not
    classify. Fail closed: classify it there first, so the inventory, the
    backfill and this guard all see it.

``A2C-DYNAMIC``
    ``getattr(db, ...)``, ``db.get_collection(...)``, or a raw collection used as
    a value (``coll = db.x``, passing ``db.x`` to a helper) — all of which hide
    the collection, and therefore its class, from this check. ``db[<expression>]``
    is judged like an unclassified collection: it must carry its own literal
    tenant predicate whatever it turns out to be.

``A2C-LOOKUP``
    A raw ``$lookup``/``$graphLookup``/``$unionWith`` stage. The foreign side of
    a join is a read too, and an id-only join is the enrichment leak of
    Issue #41 §2; joins are built only by ``TenantData.lookup``, which filters
    the joined array on the tenant before any later stage can read it.

``A2C-CTOR`` / ``A2C-CALLERTENANT``
    ``TenantData(...)`` built directly instead of through a ``for_*``
    constructor; and, inside an HTTP route, a tenant value (in a filter, or
    passed to a ``for_*`` constructor) that reads a caller-controlled route
    parameter — any parameter not injected with ``Depends``/``Security``. The
    tenant is server-side state; a request may not name it.

``A2C-RAWIMPORT``
    ``from app.db import <anything but db>``. ``app/db/__init__.py`` no longer
    pre-binds collections (W0-03E-A2C removed them), and a new pre-bound handle
    would be a ready-made bypass.

The authorization relation (``A2-TEAM``) and the ownerless-create rules
(``A2B-WRITER``/``A2B-OVERRIDE``/``A2B-ALIAS``) already apply to the whole tree
and are not reimplemented here: this guard RUNS them from
``w0_03e_a1_tenant_access_guard`` so one command covers the whole boundary, and
reports them under their own rule names.

Scope tiers
-----------

There is no allowlist for a route, a service or a job. Two narrow tiers exist,
each justified by what the code must do and neither containing tenant-owned
business access:

``TENANCY_CORE``
    The modules that IMPLEMENT the boundary and therefore cannot be expressed in
    terms of it: the access layer itself, the tenant resolver/registry/guard,
    tenant onboarding, the one-time legacy backfill (whose whole job is to find
    rows that have no owner yet) and the ``project_team`` accessor. ``A2C-READ``,
    ``A2C-WRITE`` and ``A2C-IDENTITY`` are relaxed to "must carry a literal
    tenant predicate" — raw access is allowed, an UNSCOPED one is still not.

``OPERATOR_SCRIPTS``
    ``scripts/`` entry points a human runs against a database (bootstrap,
    backfill, migration reports, company creation). Same relaxation, same
    requirement of a literal predicate. They are inventoried, never exempt.

A module in neither tier gets the full rules. Pure AST: this guard never imports
the code it checks and never opens a database.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import w0_03e_a1_tenant_access_guard as a1  # noqa: E402

BACKEND = a1.BACKEND
Violation = Tuple[str, int, str, str]

# --------------------------------------------------------------------- scope
#: Modules that implement the tenant boundary itself (see "Scope tiers").
TENANCY_CORE: Tuple[str, ...] = (
    "app/db/__init__.py",
    "app/tenancy/data_access.py",
    "app/tenancy/guard.py",
    "app/tenancy/legacy_backfill.py",
    "app/tenancy/onboarding.py",
    "app/tenancy/project_team.py",
    "app/tenancy/registry.py",
    "app/tenancy/resolver.py",
)

#: Modules whose database handle is itself resolved PER TENANT, so the database
#: is the boundary rather than a predicate inside the query.
#:
#: BEG_Work is database-per-tenant for the canonical W0-03 Master Data and W0-04
#: audit stores (CLAUDE.md §3; ``app.tenancy.resolver.get_tenant_db``): these
#: modules never see the one shared legacy database, they receive a handle that
#: ``get_tenant_db(tenant_id)`` already opened on the tenant's own database, and
#: ``MasterDataRepository._scope()`` pins ``tenant_id`` on top of that. W0-04
#: idempotency goes further: its ``id`` IS ``idem_<tenant_id>_<action>_<key>``,
#: so the tenant travels inside the key the filter names.
#:
#: The tier is not taken on trust. :func:`_shared_handle_violations` proves the
#: mechanism for every module listed here by rejecting any import of the shared
#: legacy handle (``from app.db import db``) — the moment a module on this list
#: reaches the shared database, the database stops being its boundary and the
#: guard says so (``A2C-SHAREDDB``) instead of quietly exempting it.
TENANT_DB_SCOPED: Tuple[str, ...] = (
    "app/audit/envelope.py",
    "app/audit/idempotency.py",
    "app/audit/store.py",
    "app/master_data/index_bootstrap.py",
    "app/master_data/merge.py",
    "app/master_data/models.py",
    "app/master_data/pending.py",
    "app/master_data/review.py",
    "app/master_data/service.py",
    "app/master_data/uniqueness.py",
    "app/permissions/audit_hooks.py",
    "app/permissions/service.py",
    "app/permissions/sync.py",
    "app/permissions/workflow.py",
)

#: Operator entry points under ``scripts/`` that legitimately reach a database
#: directly. Listed explicitly so a new script is in full scope by default.
OPERATOR_SCRIPTS: Tuple[str, ...] = (
    "scripts/create_company.py",
    "scripts/w0_01_bootstrap_tenant_registry.py",
    "scripts/w0_02_bootstrap_permissions.py",
    "scripts/w0_02_permission_inventory.py",
    "scripts/w0_02_validation_seed.py",
    "scripts/w0_02_validation_snapshot.py",
    "scripts/w0_03c_master_data_uniqueness.py",
    "scripts/w0_03e_a2b_beg_backfill.py",
    "scripts/w0_03e_a2c_settings_identity_migration.py",
    "scripts/w0_03e_legacy_migration_report.py",
    "scripts/w0_04_bootstrap_audit_indexes.py",
    "scripts/backfill_asset_qr.py",
    "scripts/migrate_m19_8_freeze_report_split.py",
    "scripts/promote_platform_admin.py",
    "scripts/seed_finance_data.py",
    "scripts/smoke_test.py",
)

#: The one module that legitimately builds a ``$lookup`` stage: it is the
#: scoped-join constructor itself (``TenantData.lookup`` emits the ``$lookup`` +
#: tenant ``$filter`` pair that every other module must use).
LOOKUP_BUILDER = "app/tenancy/data_access.py"

#: The two collections that DEFINE a tenant rather than belong to one: a user's
#: own record (which carries the ``org_id`` every other query is scoped by) and
#: the organization row (whose ``id`` IS that ``org_id``).
IDENTITY_DEFINING: FrozenSet[str] = frozenset({"users", "organizations"})

#: Named functions that run BEFORE a tenant exists, or ACROSS the installation
#: on purpose, with the exact collections each is allowed to reach raw.
#:
#: This is deliberately per-FUNCTION and per-COLLECTION rather than per module:
#: ``app/routes/auth.py`` is a large route module and only ``login`` runs without
#: a session, so exempting the whole file would let a future unscoped
#: ``db.users.find_one({"id": x})`` elsewhere in it pass unnoticed — the exact
#: shape of the ``invoice_lines`` defect that made this task necessary.
#:
#: Three properties are ENFORCED, so the list cannot rot or widen silently:
#:  1. a declared function must exist (otherwise ``A2C-SCOPE``);
#:  2. inside it, only the declared collections may be reached raw — any other
#:     tenant-owned collection is judged by the normal rules;
#:  3. a function declared :data:`READ_ONLY_DIAGNOSTIC` may name any collection
#:     but may not contain a single write method.
PRE_TENANT_FUNCTIONS: Dict[str, Dict[str, FrozenSet[str]]] = {
    # The installation seed creates the FIRST organization and its admin: there is
    # no tenant to scope by until it has run.
    "app/core/seed.py": {"seed_data": IDENTITY_DEFINING},
    # Resolves the session user from the VERIFIED JWT user id. This is where the
    # request's tenant comes from, so it cannot be scoped by it.
    "app/deps/auth.py": {"get_current_user": frozenset({"users"})},
    # Login by email, before any session exists.
    "app/routes/auth.py": {"login": frozenset({"users"})},
    # Platform-admin bootstrap: creates the platform system organization and its
    # user (ownership.PLATFORM_ROWS_ALLOWED), which belong to no tenant.
    "app/routes/platform.py": {"bootstrap_create_platform_admin": IDENTITY_DEFINING},
    # Operator tool: promotes a platform administrator by email across the
    # installation. Touches the identity record only.
    "scripts/promote_platform_admin.py": {"promote_platform_admin": frozenset({"users"})},
    # Operator seed: looks up the installation's organization to seed against.
    "scripts/seed_finance_data.py": {"seed_finance_data": frozenset({"organizations"})},
    # The settings-identity migration itself: it moves ``settings`` rows ACROSS
    # tenants onto per-tenant ids, deriving each row's tenant from that row's own
    # ``org_id`` and never guessing one. ``settings`` is the only collection it
    # may touch.
    "scripts/w0_03e_a2c_settings_identity_migration.py": {"migrate": frozenset({"settings"})},
    # One-off M19.8 migration: enumerates tenants from the tenant root, then reads
    # and writes each tenant's own reports with its ``org_id`` in every filter.
    "scripts/migrate_m19_8_freeze_report_split.py": {"main": frozenset({"organizations"})},
}

#: Functions that only COUNT or REPORT across the installation. They may name any
#: collection, and the guard proves they contain no write method at all.
READ_ONLY_DIAGNOSTIC: Dict[str, Tuple[str, ...]] = {
    # Installation health check: one count_documents({}) per expected collection.
    "scripts/smoke_test.py": ("smoke_test",),
    # W0-04 audit index bootstrap: counts and distinct over the audit stores.
    "scripts/w0_04_bootstrap_audit_indexes.py": ("run",),
    # The read-only database wrapper of the legacy migration report: its
    # __getitem__ hands back a collection proxy that refuses every write method.
    "scripts/w0_03e_legacy_migration_report.py": ("__getitem__",),
}

#: Identity-bearing collections: raw access refused outside the two tiers.
IDENTITY_COLLECTIONS: FrozenSet[str] = a1.IDENTITY_COLLECTIONS

READS = frozenset({"find", "find_one", "count_documents", "distinct", "aggregate", "watch"})
WRITES = frozenset({"update_one", "update_many", "delete_one", "delete_many", "replace_one",
                    "find_one_and_update", "find_one_and_replace", "find_one_and_delete"})
CREATES = frozenset({"insert_one", "insert_many"})
NO_FILTER = frozenset({"bulk_write", "create_index", "create_indexes", "index_information",
                       "drop_index", "drop_indexes", "estimated_document_count", "drop",
                       "list_indexes", "aggregate_raw_batches"})
FILTER_SECOND = frozenset({"distinct"})
JOIN_STAGES = frozenset({"$lookup", "$graphLookup", "$unionWith"})


#: Attribute names on a database handle that are the DATABASE's own API, not a
#: collection: ``db.list_collection_names()``, ``db.command(...)``, ``db.name``.
#: A1's ``_collection_of`` treats every ``db.<attr>`` as a collection, which also
#: catches ordinary string/own-object methods on a variable named ``database``
#: (``database.lower()`` in the W0-03C index bootstrap). None of them reaches a
#: document, so none can cross the tenant boundary.
DATABASE_API: FrozenSet[str] = frozenset({
    "list_collection_names", "list_collections", "command", "name", "client",
    "drop_collection", "create_collection", "validate_collection", "dereference",
    "with_options", "codec_options", "read_preference", "write_concern",
    "read_concern", "aggregate", "watch", "get_collection", "cursor_command",
    # ordinary str/object methods seen on a handle-named variable
    "lower", "upper", "strip", "startswith", "endswith", "split", "format",
    "encode", "decode", "replace", "join", "get", "items", "keys", "values",
})


def _ownership():
    return a1._ownership_module()


def _collection_of(node: ast.AST, constants: Optional[Dict[str, str]] = None
                   ) -> Tuple[bool, Optional[str]]:
    """Like A1's, with two refinements.

    A database-level API attribute (``db.list_collection_names``) is not a
    collection. And ``db[SETTINGS_COLLECTION]``, where the module binds that name
    to a string literal, resolves to the real collection name instead of
    ``None`` — otherwise naming a collection through a constant, which is good
    practice, would make it invisible to every collection-aware rule.
    """
    is_coll, name = a1._collection_of(node)
    if is_coll and name is not None and name in DATABASE_API:
        return False, None
    if is_coll and name is None and constants and isinstance(node, ast.Subscript) \
            and isinstance(node.slice, ast.Name):
        return True, constants.get(node.slice.id)
    return is_coll, name


def active_backend_files() -> List[str]:
    """Every module of the active backend, backend-relative POSIX, sorted.

    ``app/**/*.py`` + ``server.py`` + :data:`OPERATOR_SCRIPTS`. Tests and the
    guard/inventory tooling itself are not application code and are not checked.
    """
    files: Set[str] = {"server.py"}
    for p in (BACKEND / "app").rglob("*.py"):
        files.add(p.relative_to(BACKEND).as_posix())
    files.update(s for s in OPERATOR_SCRIPTS if (BACKEND / s).is_file())
    return sorted(f for f in files if (BACKEND / f).is_file())


def _relaxed(rel: str) -> bool:
    """True where a raw handle may name an identity collection at all."""
    return rel in TENANCY_CORE or rel in OPERATOR_SCRIPTS or rel in TENANT_DB_SCOPED


def _boundary_is_the_database(rel: str) -> bool:
    """True where the HANDLE is already tenant-scoped, so a predicate is not the boundary.

    :data:`TENANCY_CORE` implements the boundary and therefore cannot be
    expressed in terms of it (``count_ownerless`` and ``resolve_review_token``
    are deliberately not tenant-scoped, and documented as such in
    ``app/tenancy/data_access.py``). :data:`TENANT_DB_SCOPED` is on its own
    per-tenant database. Both are proven, not assumed: the tier list is asserted
    whole by ``tests/test_w0_03e_a2c_static_guard.py`` and the shared-handle
    check below.
    """
    return rel in TENANCY_CORE or rel in TENANT_DB_SCOPED


def _shared_handle_violations(rel: str, tree: ast.Module) -> List[Violation]:
    """A2C-SHAREDDB: a per-tenant-database module reaching the shared legacy handle."""
    if rel not in TENANT_DB_SCOPED:
        return []
    out: List[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.db"):
            out.append((rel, node.lineno, "A2C-SHAREDDB",
                        "this module is exempted from the predicate rules because its database "
                        "handle is opened per tenant by get_tenant_db(); importing the shared "
                        "legacy handle removes that guarantee, so the exemption no longer holds"))
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.db":
                    out.append((rel, node.lineno, "A2C-SHAREDDB",
                                "per-tenant-database module imports the shared legacy handle"))
    return out


# ------------------------------------------------------------- tenant views
def _is_tenant_collection(node: ast.AST) -> bool:
    """``<TenantData>.<collection>`` — a ``TenantCollection``, already scoped.

    Recognises the idioms the application uses: a ``tenant`` name (or any
    ``*_tenant`` name), the ``_tenant(user)`` helper every route defines, a
    direct ``TenantData.for_*(...)`` call, and ``.collection(...)``/
    ``.entity(...)`` on any of them.
    """
    if isinstance(node, ast.Call):                 # tenant.collection("x") / .entity("y")
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in ("collection", "entity"):
            return _is_tenant_base(f.value)
        return False
    if isinstance(node, ast.Attribute):
        return _is_tenant_base(node.value)
    return False


def _is_tenant_base(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "tenant" or node.id.endswith("_tenant")
    if isinstance(node, ast.Attribute):            # self.tenant / ctx.tenant
        return node.attr == "tenant" or node.attr.endswith("_tenant")
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and (f.id == "_tenant" or f.id.endswith("_tenant")):
            return True
        if (isinstance(f, ast.Attribute) and f.attr.startswith("for_")
                and isinstance(f.value, ast.Name) and f.value.id == "TenantData"):
            return True
        if isinstance(f, ast.Attribute) and f.attr in ("collection", "entity"):
            return _is_tenant_base(f.value)
    if isinstance(node, ast.Await):
        return _is_tenant_base(node.value)
    return False


# --------------------------------------------------------------- _id checks
def _dict_entry(node: ast.AST, key: str) -> Optional[ast.AST]:
    if not isinstance(node, ast.Dict):
        return None
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _literal_strings_in(fn: ast.AST) -> Dict[str, str]:
    """``{name: value}`` for locals assigned a plain string literal in ``fn``.

    So ``row_id = "worker_rates"`` followed by ``{"_id": row_id}`` is recognised
    as the same globally colliding identity as writing the literal inline; only a
    COMPUTED id (``settings_id(key, org)``) escapes the rule.
    """
    out: Dict[str, str] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _id_is_global_literal(value: ast.AST, literals: Optional[Dict[str, str]] = None) -> bool:
    """True only for a BARE STRING LITERAL ``_id`` — the globally colliding case.

    A value that is computed (``settings_id(key, org)``, an f-string, a
    concatenation, or a variable such as the migration's ``lock:<tenant>`` id)
    is not judged here: it cannot be proven global, and those writes carry their
    own literal tenant predicate, which ``A2C-WRITE`` checks independently. Only
    a constant string is certainly the same id for every tenant.
    """
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return True
    if isinstance(value, ast.Name) and literals and value.id in literals:
        return True
    return False


class _BoundaryChecker(ast.NodeVisitor):
    """The A2C rules over one module."""

    def __init__(self, rel: str, tree: ast.Module):
        self.rel = rel
        self.tree = tree
        self.relaxed = _relaxed(rel)
        self.db_is_boundary = _boundary_is_the_database(rel)
        self.own = _ownership()
        self.constants = a1._module_constants(tree)
        self.out: List[Violation] = []
        self._consumed: Set[int] = set()
        self._caller: FrozenSet[str] = frozenset()
        self._literals: Dict[str, str] = {}                 # locals holding a string literal
        self._pre_tenant: Optional[FrozenSet[str]] = None   # allowed collections, if any
        self._diagnostic = False
        self._fn_allow = PRE_TENANT_FUNCTIONS.get(rel, {})
        self._fn_diag = READ_ONLY_DIAGNOSTIC.get(rel, ())

    # -------------------------------------------------------------- helpers
    def add(self, node: ast.AST, rule: str, msg: str) -> None:
        self.out.append((self.rel, getattr(node, "lineno", 0), rule, msg))

    def _class_of(self, name: Optional[str]) -> str:
        if name is None:
            return self.own.CLASS_UNCLASSIFIED
        return self.own.classify_collection(name)

    def _needs_tenant(self, cls: str) -> bool:
        return cls in (self.own.CLASS_ORG, self.own.CLASS_TENANT_ID, self.own.CLASS_ROOT,
                       self.own.CLASS_UNCLASSIFIED)

    # --------------------------------------------------------------- routes
    def visit_FunctionDef(self, node) -> None:
        saved = (self._caller, self._pre_tenant, self._diagnostic, self._literals)
        self._caller = a1._caller_params(node) if a1._is_route(node) else frozenset()
        self._literals = _literal_strings_in(node)
        if node.name in self._fn_allow:
            self._pre_tenant = self._fn_allow[node.name]
        if node.name in self._fn_diag:
            self._diagnostic = True
            for sub_node in ast.walk(node):
                if (isinstance(sub_node, ast.Call) and isinstance(sub_node.func, ast.Attribute)
                        and sub_node.func.attr in WRITES | CREATES):
                    self.add(sub_node, "A2C-DIAGNOSTIC",
                             "%s() is declared read-only in READ_ONLY_DIAGNOSTIC, so it may name "
                             "any collection; it contains the write %s(), which that declaration "
                             "does not cover" % (node.name, sub_node.func.attr))
        self.generic_visit(node)
        self._caller, self._pre_tenant, self._diagnostic, self._literals = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_tenant_source(self, node: ast.AST, value: Optional[ast.AST]) -> None:
        if value is None or not self._caller:
            return
        used = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
        bad = sorted(used & self._caller)
        if bad:
            self.add(node, "A2C-CALLERTENANT",
                     "tenant value reads caller-controlled route parameter(s) %s" % ", ".join(bad))

    # ----------------------------------------------------------------- calls
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            is_coll, name = _collection_of(func.value, self.constants)
            if is_coll:
                self._consumed.add(id(func.value))
                self._judge(node, func.attr, name)
            elif _is_tenant_collection(func.value) and func.attr in WRITES:
                # The tenant view adds org_id to the filter, which does NOT make a
                # global literal _id safe: _id is unique per COLLECTION, so the
                # second tenant's upsert still fails with a duplicate key.
                self._check_settings_id(node, ast.unparse(func.value)[:60])
            elif a1._is_db(func.value) and func.attr in ("get_collection", "__getitem__",
                                                         "__getattr__"):
                self.add(node, "A2C-DYNAMIC", "db.%s(...) hides the collection" % func.attr)
        if isinstance(func, ast.Name) and func.id == "getattr" and node.args and a1._is_db(
                node.args[0]):
            self.add(node, "A2C-DYNAMIC", "getattr(db, ...) hides the collection")
        if isinstance(func, ast.Name) and func.id == "TenantData":
            self.add(node, "A2C-CTOR", "build TenantData with a for_* constructor")
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id == "TenantData" and func.attr.startswith("for_")):
            for arg in node.args[1:]:
                self._check_tenant_source(node, arg)
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Dict):
                    self._check_tenant_source(node, a1._tenant_value(sub))
        self.generic_visit(node)

    def _judge(self, node: ast.Call, method: str, name: Optional[str]) -> None:
        cls = self._class_of(name)
        shown = name or "[<expression>]"

        if self._diagnostic and method in READS:
            return          # counts/reports only; the write check ran at the def
        if self._pre_tenant is not None and name in self._pre_tenant:
            return          # declared pre-tenant access to a declared collection

        if name is not None and cls == self.own.CLASS_UNCLASSIFIED:
            self.add(node, "A2C-UNCLASSIFIED",
                     "db.%s.%s: %r is not classified in app.tenancy.ownership; classify it "
                     "so the inventory, the backfill and this guard all see it" % (shown, method, name))
            # still judge its predicate below — fail closed, not instead-of

        if method in NO_FILTER:
            # Index and collection administration carries neither a filter nor a
            # document, so it cannot cross the tenant boundary. The startup index
            # bootstrap in ``server.py`` is exactly this.
            return

        if (name in IDENTITY_COLLECTIONS and not self.relaxed):
            self.add(node, "A2C-IDENTITY",
                     "db.%s.%s: identity collection outside TenantData" % (shown, method))
            return

        if method in CREATES:
            return          # the document side is judged by A2B-WRITER

        if not self._needs_tenant(cls):
            return          # TECHNICAL bookkeeping: no tenant meaning

        if self.db_is_boundary:
            return          # the handle itself is this tenant's database

        if method == "aggregate":
            if not a1._pipeline_scoped(a1._arg(node, 0, "pipeline")):
                self.add(node, "A2C-READ", "db.%s.aggregate: first stage is not a tenant $match"
                         % shown)
            return

        if method in READS:
            idx, kw = (1, "filter") if method in FILTER_SECOND else (0, "filter")
            if not a1._dict_has_tenant(a1._arg(node, idx, kw)):
                self.add(node, "A2C-READ",
                         "db.%s.%s: filter has no literal org_id/tenant_id — a bare business id "
                         "returns whichever tenant's document is found first" % (shown, method))
            return

        if method in WRITES:
            flt = a1._arg(node, 0, "filter")
            if not a1._dict_has_tenant(flt):
                self.add(node, "A2C-WRITE",
                         "db.%s.%s: the write FILTER has no literal org_id/tenant_id; a prior "
                         "tenant-scoped read is not enough" % (shown, method))
            self._check_settings_id(node, shown, flt)
            return

        self.add(node, "A2C-READ", "db.%s.%s: unrecognised database method" % (shown, method))

    def _check_settings_id(self, node: ast.Call, shown: str,
                           flt: Optional[ast.AST] = "unset") -> None:
        """A2C-SETTINGS: a globally colliding literal ``_id`` on a tenant-owned write."""
        if flt == "unset":
            flt = a1._arg(node, 0, "filter")
        candidates = []
        if flt is not None:
            candidates.append(_dict_entry(flt, "_id"))
        upd = a1._arg(node, 1, "update")
        if isinstance(upd, ast.Dict):
            for k, v in zip(upd.keys, upd.values):
                if isinstance(k, ast.Constant) and k.value in ("$set", "$setOnInsert"):
                    candidates.append(_dict_entry(v, "_id"))
        repl = a1._arg(node, 1, "replacement")
        if repl is not None:
            candidates.append(_dict_entry(repl, "_id"))
        for value in candidates:
            if value is None:
                continue
            if _id_is_global_literal(value, self._literals):
                self.add(node, "A2C-SETTINGS",
                         "db.%s: _id is a global literal, so the collection can hold exactly one "
                         "such row and a second tenant's upsert collides; derive it with "
                         "app.tenancy.settings_identity.settings_id(key, org_id)" % shown)
                return

    # ----------------------------------------------- raw collection as value
    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._raw_appearance(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._raw_appearance(node)
        self.generic_visit(node)

    def _raw_appearance(self, node: ast.AST) -> None:
        is_coll, name = _collection_of(node, self.constants)
        if not is_coll or id(node) in self._consumed:
            return
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            return
        if self._diagnostic or (self._pre_tenant is not None and name in self._pre_tenant):
            return
        if name in IDENTITY_COLLECTIONS and not self.relaxed:
            self.add(node, "A2C-IDENTITY", "db.%s: identity collection outside TenantData" % name)
        elif self.db_is_boundary:
            return          # handle already scoped to one tenant's database
        else:
            self.add(node, "A2C-DYNAMIC",
                     "db.%s used as a value; call it directly so its filter is visible"
                     % (name or "[<expression>]"))

    def visit_Dict(self, node: ast.Dict) -> None:
        if self.rel == LOOKUP_BUILDER:
            self.generic_visit(node)
            return
        for k in node.keys:
            if isinstance(k, ast.Constant) and k.value in JOIN_STAGES:
                self.add(node, "A2C-LOOKUP",
                         "raw %s stage: the joined side is an unscoped read; use TenantData.lookup"
                         % k.value)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "app.db":
            for alias in node.names:
                if alias.name not in ("db", "client", "mongo_url", "db_name"):
                    self.add(node, "A2C-RAWIMPORT",
                             "from app.db import %s: a pre-bound handle hides the tenant predicate"
                             % alias.name)
        self.generic_visit(node)


def _declared_functions_exist(rel: str, tree: ast.Module) -> List[Violation]:
    """A2C-SCOPE: every function named in the two exemption lists must still exist.

    A renamed or deleted function would otherwise shrink the guard's scope in
    silence — the failure mode this whole task exists to remove.
    """
    present = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    out: List[Violation] = []
    for name in sorted(set(PRE_TENANT_FUNCTIONS.get(rel, {})) - present):
        out.append((rel, 0, "A2C-SCOPE",
                    "PRE_TENANT_FUNCTIONS names %s(), which no longer exists here" % name))
    for name in sorted(set(READ_ONLY_DIAGNOSTIC.get(rel, ())) - present):
        out.append((rel, 0, "A2C-SCOPE",
                    "READ_ONLY_DIAGNOSTIC names %s(), which no longer exists here" % name))
    return out


def check_source(source: str, rel: str) -> List[Violation]:
    """The A2C rules over one module (``rel`` is backend-relative POSIX)."""
    rel = normalize_rel(rel)
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        return [(rel, exc.lineno or 0, "A2C-READ", "could not parse: %s" % exc.msg)]
    checker = _BoundaryChecker(rel, tree)
    checker.out.extend(_shared_handle_violations(rel, tree))
    checker.out.extend(_declared_functions_exist(rel, tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if _collection_of(node.func.value)[0]:
                checker._consumed.add(id(node.func.value))
    checker.visit(tree)
    return sorted(set(checker.out), key=lambda v: (v[0], v[1], v[2], v[3]))


def _inherits_app_rules(rel: str) -> bool:
    """Whether the inherited A2-TEAM / A2B-WRITER rules cover this module.

    Those two rules were defined by W0-03E-A2 and A2B over the application tree
    plus the authorization/writer scripts they named, and they PASSED there at
    the A2C base head. A2C widens its OWN rules to every operator script, but it
    does not retroactively widen those two onto fixture seeders such as
    ``scripts/w0_02_validation_seed.py``, whose job is to write raw legacy and
    deliberately ownerless rows into a throwaway validation database.
    """
    return (rel == "server.py" or rel.startswith("app/")
            or rel in a1.AUTHZ_SCRIPTS or rel in a1.WRITER_SCRIPTS)


def check_module(rel: str) -> List[Violation]:
    """A2C rules + the inherited A2-TEAM / A2B-WRITER rules."""
    rel = normalize_rel(rel)
    source = (BACKEND / rel).read_text(encoding="utf-8")
    out = check_source(source, rel)
    if _inherits_app_rules(rel):
        out.extend(a1.check_team_relation(source, rel))
        out.extend(a1.check_writers(source, rel))
    return sorted(set(out), key=lambda v: (v[0], v[1], v[2], v[3]))


def check_active_backend() -> Tuple[int, List[Violation]]:
    files = active_backend_files()
    found: List[Violation] = []
    for rel in files:
        found.extend(check_module(rel))
    return len(files), found


def normalize_rel(raw: str) -> str:
    """One backend-relative POSIX spelling, whatever the caller wrote.

    W0-03E-A2C. ``app\\routes\\invoice_lines.py`` is a single opaque filename to
    :class:`pathlib.PurePosixPath` and ``app/routes/invoice_lines.py`` is one to
    ``PureWindowsPath``, so a guard that hands the raw string to ``Path`` reports
    a different (or empty) result per platform — a CI run on one OS would pass a
    file the other OS checks. Separators are normalised before any path logic, so
    the verdict is identical on both.
    """
    return str(raw).replace("\\", "/")


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


def main(argv: List[str]) -> int:
    try:
        if argv:
            units, violations = len(argv), check_files(argv)
        else:
            units, violations = check_active_backend()
    except (OSError, SyntaxError) as exc:
        print("guard error: %s" % exc, file=sys.stderr)
        return 2
    for rel, line, rule, msg in violations:
        print("%s:%d: %s %s" % (rel, line, rule, msg))
    print("W0-03E-A2C tenant boundary guard: %d module(s) checked, %d violation(s)"
          % (units, len(violations)))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
