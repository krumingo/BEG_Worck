#!/usr/bin/env python3
"""
W0-03E-A1 — static guard: no tenant-unsafe data access in the protected modules.

Deterministic AST check (no imports of the checked code, no database). Exit
code 0 = clean, 1 = violations (printed as ``path:line: RULE message``),
2 = usage/parse error. CI-runnable as a plain script and enforced in the test
suite by ``tests/test_w0_03e_a1_static_guard.py``.

    python scripts/w0_03e_a1_tenant_access_guard.py            # the protected set
    python scripts/w0_03e_a1_tenant_access_guard.py FILE ...   # explicit files

Rules, applied to every module in ``PROTECTED_MODULES``:

  A1-IDENTITY   ``db.<identity collection>`` (projects, clients, companies,
                users, warehouses, invoices, counterparties, persons,
                finance_payments, payment_allocations, financial_accounts,
                offers, subcontractors, organizations) may not appear at all —
                read, write or alias. Those records are reached only through
                ``app.tenancy.data_access.TenantData``.
  A1-UNSCOPED   any other ``db.<collection>.<method>(filter, ...)`` must pass a
                literal dict filter carrying ``org_id`` or ``tenant_id``
                (aggregate: first stage ``{"$match": {"org_id": ...}}``).
                A filter in a variable cannot be proven and is rejected.
  A1-DYNAMIC    ``getattr(db, ...)``, ``db.get_collection(...)`` and a bare
                collection alias (``coll = db.x`` / ``coll = db[name]``) hide
                the collection from this check. ``db[<expression>].<method>``
                is judged like A1-UNSCOPED: it must carry its own literal
                tenant predicate, whatever the collection turns out to be.
  A1-LOOKUP     a raw ``$lookup`` / ``$graphLookup`` / ``$unionWith`` stage;
                joins are built only by ``TenantData.lookup``.
  A1-RECEIVER   a find/update/delete/aggregate call on a receiver that is
                neither a recognised raw handle nor a TenantData collection
                (``tenant.<c>`` / ``_tenant(user).<c>``), unless its own filter
                is proven (literal tenant key, or ``scoped(...)``/``_scope(...)``,
                which apply the tenant key last).
  A1-RAWIMPORT  ``from app.db import <collection>`` (a pre-bound collection).
  A1-CTOR       ``TenantData(...)`` built directly instead of through
                ``for_user`` / ``for_context`` / ``for_owner_of``.
  A1-CALLERTENANT  inside an HTTP route, a tenant value (``org_id``/``tenant_id``
                in a filter, or the argument of ``TenantData.for_*``) that
                reads a caller-controlled parameter — any route parameter not
                injected with ``Depends(...)`` (path, query or body).

W0-03E-A2 adds one rule that is applied to the WHOLE ``app/`` tree rather than
to the protected set, because ``project_team`` is an authorization relation and
a membership question answered anywhere decides access everywhere:

  A2-TEAM       any ``project_team`` access that is not through
                ``app.tenancy.project_team`` — ``db.project_team``,
                ``db["project_team"]``, a module-level alias of either, or
                ``from app.db import project_team``. A bare membership lookup
                by ``project_id``/``user_id`` alone is the A1 defect: in one
                shared legacy database an ownerless row written by tenant B
                authorized tenant A. Scoping the filter by hand does not help,
                because the next route forgets; the relation has one accessor.

W0-03E-A2B adds the writer side, also over the WHOLE ``app/`` tree (plus
``server.py`` and the operator scripts in ``WRITER_SCRIPTS``), because after the
single-tenant backfill no tenant-owned record may ever be created ownerless:

  A2B-WRITER    a write that can CREATE a document in a tenant-owned
                (``org_id``-keyed, ``app.tenancy.ownership.ORG_KEYED``)
                collection — ``insert_one``, ``insert_many``, ``replace_one``,
                ``find_one_and_replace``, or an ``update_*``/``find_one_and_update``
                with ``upsert=True`` — whose document is not PROVEN to carry an
                ``org_id`` key. Proven means: a dict literal with the key; a
                name assigned such a literal, or given the key by
                ``name["org_id"] = ...``, ``name.update({...})``/
                ``name.setdefault("org_id", ...)`` in the same function;
                ``dict(x, org_id=...)``; a list literal / comprehension of such
                dicts, or a list filled by ``.append(<proven>)`` or whose loop
                variable is given the key; for an upsert, the key in the filter
                or in ``$set``/``$setOnInsert``. Writes through a ``TenantData``
                collection (``tenant.<c>``/``_tenant(...).<c>``) stamp the
                tenant themselves and are not judged here.
  A2B-OVERRIDE  a ``**spread`` placed AFTER the ``org_id`` key of a written
                document (the spread could replace the server's tenant), or —
                inside an HTTP route — an ``org_id`` value that reads a
                caller-controlled route parameter.
  A2B-ALIAS     a tenant-owned collection bound to a name
                (``coll = db.invoices``), which would hide its writes.

``A2-TEAM`` additionally covers the authorization-deriving scripts in
``AUTHZ_SCRIPTS`` (the W0-02 permission bootstrap), which must read
memberships through ``app.tenancy.project_team`` like the application.

There is no allowlist. A line that cannot be proven safe is a violation; the
fix is to route it through the access layer, not to exclude it.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parent.parent

#: The W0-03E protected read surface (A1 inventory, see
#: docs/architecture/W0-03E_LEGACY_MIGRATION.md §14). Whole modules: no
#: function-level carve-outs.
PROTECTED_MODULES: Tuple[str, ...] = (
    "app/routes/finance.py",
    "app/routes/offers.py",
    "app/routes/reports.py",
    "app/routes/dashboard.py",
    "app/master_data/legacy_adapter.py",
    "app/master_data/legacy_plan.py",
    "app/master_data/legacy_migration.py",
    "app/master_data/intake_hooks.py",
    "app/master_data/repository.py",
    "app/routes/ocr_invoice.py",
    "app/routes/assets_batch_intake.py",
    "app/routes/master_data.py",
)

#: W0-03E entry points inside route files whose REST is outside the W0-03E
#: surface (contract §6: the remaining legacy ``org_id`` uses are not this
#: package). Each named function is checked whole, with every rule; a name
#: that no longer exists fails the guard instead of silently shrinking scope.
PROTECTED_FUNCTIONS: Dict[str, Tuple[str, ...]] = {
    "app/routes/projects.py": ("import_client_invoice", "update_person", "delete_person",
                               "update_company", "delete_company"),
    "app/routes/hr.py": ("list_advances", "create_advance"),
    "app/routes/clients.py": ("update_client", "delete_client"),
    "app/routes/counterparties.py": ("update_counterparty", "delete_counterparty"),
    "app/routes/locations.py": ("update_location", "delete_location"),
    "app/routes/smr_groups.py": ("update_group", "delete_group"),
    "app/routes/assets_items.py": ("update_asset_item", "delete_asset_item"),
    "app/routes/assets_units.py": ("update_asset_unit", "delete_asset_unit"),
    "app/routes/auth.py": ("update_user", "delete_user"),
    "app/routes/items.py": ("get_item",),
    "app/routes/subcontractors.py": ("get_subcontractor",),
    "app/routes/warehouses.py": ("delete_warehouse", "dev_reset_warehouses"),
}

#: Helpers the protected modules call that receive an already server-resolved
#: org from their caller. Every rule applies except A1-IDENTITY: an identity
#: collection may be read directly here, but only with a literal tenant
#: predicate (A1-UNSCOPED), so the helper cannot be a bare-id bypass.
HELPER_MODULES: Tuple[str, ...] = (
    "app/services/paid_labor.py",
    "app/deps/modules.py",
    "app/utils/audit.py",
)

#: Identity-bearing legacy collections: only TenantData may touch them.
IDENTITY_COLLECTIONS = frozenset({
    "projects", "clients", "companies", "users", "warehouses", "invoices",
    "counterparties", "persons", "finance_payments", "payment_allocations",
    "financial_accounts", "offers", "subcontractors", "organizations",
})

#: Names that hold a raw database handle in the protected modules.
DB_NAMES = frozenset({"db", "_db", "legacy_db", "tenant_db", "database", "raw_db"})

FILTER_FIRST = frozenset({
    "find", "find_one", "count_documents", "update_one", "update_many", "replace_one",
    "delete_one", "delete_many", "find_one_and_update", "find_one_and_replace",
    "find_one_and_delete", "watch",
})
FILTER_SECOND = frozenset({"distinct"})
PIPELINE = frozenset({"aggregate"})
NO_FILTER = frozenset({"insert_one", "insert_many", "bulk_write", "create_index", "create_indexes",
                       "index_information", "drop_index", "estimated_document_count"})
TENANT_KEYS = frozenset({"org_id", "tenant_id"})
JOIN_STAGES = frozenset({"$lookup", "$graphLookup", "$unionWith"})

Violation = Tuple[str, int, str, str]


def _is_db(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in DB_NAMES
    if isinstance(node, ast.Attribute):          # self.db / self._db / module.db
        return node.attr in DB_NAMES
    if isinstance(node, ast.Await):              # (await ctx.db()) / (await repo.db())
        call = node.value
        return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr in DB_NAMES)
    return False


def _is_tenant_view(node: ast.AST) -> bool:
    """``tenant.<collection>`` / ``_tenant(user).<collection>`` — a TenantCollection."""
    if not isinstance(node, ast.Attribute):
        return False
    base = node.value
    if isinstance(base, ast.Name):
        return base.id == "tenant"
    return isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == "_tenant"


def _collection_of(node: ast.AST) -> Tuple[bool, Optional[str]]:
    """(is a raw collection expression, literal collection name or None)."""
    if isinstance(node, ast.Attribute) and _is_db(node.value):
        return True, node.attr
    if isinstance(node, ast.Subscript) and _is_db(node.value):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return True, key.value
        return True, None
    return False, None


def _tenant_value(node: ast.AST) -> Optional[ast.AST]:
    """The value of the literal tenant key of a filter dict, if any."""
    if not isinstance(node, ast.Dict):
        return None
    found = None
    for k, v in zip(node.keys, node.values):
        if k is None:            # {**other}: it could override a tenant key written BEFORE it
            found = None
            continue
        if isinstance(k, ast.Constant) and k.value in TENANT_KEYS:
            found = None if (isinstance(v, ast.Constant) and v.value is None) else v
    return found


#: Scope builders that apply the tenant key LAST, so a caller key cannot
#: override it: ``TenantData.scoped`` and the W0-03 ``MasterDataRepository._scope``.
SCOPE_BUILDERS = frozenset({"scoped", "_scope"})


def _is_scope_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in SCOPE_BUILDERS)


def _dict_has_tenant(node: ast.AST) -> bool:
    return _tenant_value(node) is not None or _is_scope_call(node)


def _is_route(fn: ast.AST) -> bool:
    for dec in getattr(fn, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in (
                "get", "post", "put", "patch", "delete", "api_route", "websocket"):
            return True
    return False


def _caller_params(fn: ast.AST) -> frozenset:
    """Route parameters the caller controls: every one not injected by Depends()."""
    args = fn.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    pairs = list(zip(positional, defaults)) + list(zip(args.kwonlyargs, args.kw_defaults))
    out = set()
    for arg, default in pairs:
        injected = (isinstance(default, ast.Call) and isinstance(default.func, ast.Name)
                    and default.func.id in ("Depends", "Security"))
        if not injected:
            out.add(arg.arg)
    return frozenset(out)


def _pipeline_scoped(node: ast.AST) -> bool:
    if not isinstance(node, ast.List) or not node.elts:
        return False
    first = node.elts[0]
    if not isinstance(first, ast.Dict):
        return False
    for k, v in zip(first.keys, first.values):
        if isinstance(k, ast.Constant) and k.value == "$match":
            return _dict_has_tenant(v)
    return False


def _arg(call: ast.Call, index: int, name: str) -> Optional[ast.AST]:
    if len(call.args) > index:
        return call.args[index]
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


class _Checker(ast.NodeVisitor):
    def __init__(self, rel: str, helper: bool = False):
        self.rel = rel
        self.helper = helper
        self.out: List[Violation] = []
        self._consumed: set = set()      # collection nodes already judged as call receivers
        self._caller: frozenset = frozenset()   # caller-controlled names of the enclosing route

    def add(self, node: ast.AST, rule: str, msg: str) -> None:
        self.out.append((self.rel, getattr(node, "lineno", 0), rule, msg))

    def visit_FunctionDef(self, node) -> None:
        saved = self._caller
        self._caller = _caller_params(node) if _is_route(node) else frozenset()
        self.generic_visit(node)
        self._caller = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_tenant_source(self, node: ast.AST, value: Optional[ast.AST]) -> None:
        if value is None or not self._caller:
            return
        used = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
        bad = sorted(used & self._caller)
        if bad:
            self.add(node, "A1-CALLERTENANT",
                     "tenant value reads caller-controlled route parameter(s) %s" % ", ".join(bad))

    # db.<coll>.<method>(...)
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            is_coll, name = _collection_of(func.value)
            if is_coll:
                self._consumed.add(id(func.value))
                self._judge(node, func.attr, name)
            elif _is_db(func.value) and func.attr in ("get_collection", "__getitem__", "__getattr__"):
                self.add(node, "A1-DYNAMIC", "db.%s(...) hides the collection" % func.attr)
            elif (func.attr in FILTER_FIRST | PIPELINE and not _is_tenant_view(func.value)
                  and not (node.args and isinstance(node.args[0], ast.Constant))
                  and not (func.attr in FILTER_FIRST and _dict_has_tenant(_arg(node, 0, "filter")))):
                # a database call on a handle this guard cannot see (an alias, a
                # helper's return value, a repository attribute): not provable
                self.add(node, "A1-RECEIVER", "%s.%s: unrecognised database handle"
                         % (ast.unparse(func.value)[:60], func.attr))
        if isinstance(func, ast.Name) and func.id == "getattr" and node.args and _is_db(node.args[0]):
            self.add(node, "A1-DYNAMIC", "getattr(db, ...) hides the collection")
        if isinstance(func, ast.Name) and func.id == "TenantData":
            self.add(node, "A1-CTOR", "build TenantData with for_user/for_context/for_owner_of")
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id == "TenantData" and func.attr.startswith("for_")):
            for arg in node.args[1:]:
                self._check_tenant_source(node, arg)
        # every literal filter / $match anywhere in a route: its tenant value
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Dict):
                    self._check_tenant_source(node, _tenant_value(sub))
        self.generic_visit(node)

    def _judge(self, node: ast.Call, method: str, name: Optional[str]) -> None:
        # db[<expression>]: the collection is unknown, so the call must prove its
        # own tenant predicate exactly like any non-identity collection.
        if name is not None and name in IDENTITY_COLLECTIONS and not self.helper:
            self.add(node, "A1-IDENTITY",
                     "db.%s.%s: identity collection outside TenantData" % (name, method))
            return
        if method in NO_FILTER:
            return
        if method in FILTER_FIRST:
            flt = _arg(node, 0, "filter")
            if not _dict_has_tenant(flt):
                self.add(node, "A1-UNSCOPED", "db.%s.%s: filter has no literal org_id/tenant_id"
                         % (name or "[<expression>]", method))
            return
        if method in FILTER_SECOND:
            flt = _arg(node, 1, "filter")
            if not _dict_has_tenant(flt):
                self.add(node, "A1-UNSCOPED", "db.%s.%s: filter has no literal org_id/tenant_id"
                         % (name or "[<expression>]", method))
            return
        if method in PIPELINE:
            if not _pipeline_scoped(_arg(node, 0, "pipeline")):
                self.add(node, "A1-UNSCOPED", "db.%s.aggregate: first stage is not a tenant $match"
                         % (name or "[<expression>]"))
            return
        self.add(node, "A1-UNSCOPED", "db.%s.%s: unrecognised database method"
                 % (name or "[<expression>]", method))

    # any other appearance of a raw collection (alias, argument, return value)
    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._raw_appearance(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._raw_appearance(node)
        self.generic_visit(node)

    def _raw_appearance(self, node: ast.AST) -> None:
        is_coll, name = _collection_of(node)
        if not is_coll or id(node) in self._consumed:
            return
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            return
        if name in IDENTITY_COLLECTIONS and not self.helper:
            self.add(node, "A1-IDENTITY", "db.%s: identity collection outside TenantData" % name)
        else:
            self.add(node, "A1-DYNAMIC", "db.%s used as a value; call it directly with a tenant filter"
                     % (name or "[<expression>]"))

    def visit_Dict(self, node: ast.Dict) -> None:
        for k in node.keys:
            if isinstance(k, ast.Constant) and k.value in JOIN_STAGES:
                self.add(node, "A1-LOOKUP", "raw %s stage; use TenantData.lookup" % k.value)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "app.db":
            for alias in node.names:
                if alias.name != "db":
                    self.add(node, "A1-RAWIMPORT", "from app.db import %s" % alias.name)
        self.generic_visit(node)


def check_source(source: str, rel: str, functions: Optional[Iterable[str]] = None,
                 helper: bool = False) -> List[Violation]:
    """Check a whole module, or only the named top-level functions of it."""
    tree = ast.parse(source, filename=rel)
    checker = _Checker(rel, helper=helper)
    # calls first so their receivers are known before attribute visits
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if _collection_of(node.func.value)[0]:
                checker._consumed.add(id(node.func.value))
    if functions is None:
        checker.visit(tree)
    else:
        wanted = set(functions)
        defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in sorted(wanted - set(defs)):
            checker.out.append((rel, 0, "A1-SCOPE", "protected function %s() not found" % name))
        for name in sorted(wanted & set(defs)):
            checker.visit(defs[name])
    return sorted(set(checker.out), key=lambda v: (v[0], v[1], v[2], v[3]))


#: The authorization relation and its one accessor module (W0-03E-A2).
TEAM_COLLECTION = "project_team"
TEAM_RELATION_MODULE = "app/tenancy/project_team.py"

#: Where a ``project_team`` access may legitimately appear: the relation module
#: itself (which reaches it through ``TenantData``), and the two A1 helper
#: entry points that delegate to it. There is no allowlist for a route.
TEAM_ALLOWED_MODULES: Tuple[str, ...] = (TEAM_RELATION_MODULE,)


def check_team_relation(source: str, rel: str) -> List[Violation]:
    """A2-TEAM: ``project_team`` reached outside ``app.tenancy.project_team``.

    Deterministic and allowlist-free. It fires on a raw handle attribute
    (``db.project_team``), a subscript (``db["project_team"]``), an alias of
    either, and on importing the pre-bound collection from ``app.db``. The
    collection name appearing as a *string* argument to the relation module's
    own accessors is not an access and is not reported.
    """
    out: List[Violation] = []
    if rel in TEAM_ALLOWED_MODULES:
        return out
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [(rel, exc.lineno or 0, "A2-TEAM", "could not parse: %s" % exc.msg)]

    def report(node, how: str) -> None:
        out.append((rel, getattr(node, "lineno", 0), "A2-TEAM",
                    "%s reaches '%s' outside app.tenancy.project_team; use its "
                    "accessors so the tenant predicate cannot be forgotten" % (how, TEAM_COLLECTION)))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == TEAM_COLLECTION:
            report(node, "attribute access")
        elif isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == TEAM_COLLECTION:
                report(node, "subscript access")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.db"):
            for alias in node.names:
                if alias.name == TEAM_COLLECTION:
                    report(node, "pre-bound import")
    return sorted(set(out), key=lambda v: (v[0], v[1], v[2], v[3]))


def team_relation_files() -> List[str]:
    """Every module of the application tree, as backend-relative POSIX paths."""
    return sorted(p.relative_to(BACKEND).as_posix()
                  for p in (BACKEND / "app").rglob("*.py"))


def check_team_relation_tree() -> Tuple[int, List[Violation]]:
    """A2-TEAM over the whole ``app/`` tree."""
    found: List[Violation] = []
    files = team_relation_files()
    for rel in files:
        found.extend(check_team_relation((BACKEND / rel).read_text(encoding="utf-8"), rel))
    return len(files), found


def _rel(p: str) -> Tuple[Path, str]:
    """``(absolute path, backend-relative POSIX path)``.

    W0-03E-A2: the relative part is always built with ``as_posix()``. It is
    compared against ``HELPER_MODULES`` / ``PROTECTED_MODULES``, which are
    POSIX strings, and ``str(PurePath)`` yields ``app\\services\\paid_labor.py``
    on Windows. The A1 review hit exactly that: the membership test was false,
    so three helper modules were judged by the wrong (stricter) tier and the
    clean tree reported four violations with exit 1 on Windows and 0 on POSIX.
    A guard whose verdict depends on the host separator proves nothing, so the
    comparison key is normalized here, once, for every caller.
    """
    given = p
    if "\\" in given and not Path(given).exists():
        # A Windows-style argument handed to a POSIX interpreter: ``Path`` would
        # treat the whole string as ONE file name. Normalize so the CLI behaves
        # the same on both platforms.
        given = given.replace("\\", "/")
    path = Path(given)
    if not path.is_absolute():
        path = BACKEND / path
    rel = (path.relative_to(BACKEND).as_posix() if path.is_relative_to(BACKEND)
           else Path(given).as_posix())
    return path, rel


def check_files(paths: Iterable[str]) -> List[Violation]:
    """Explicit files: whole-module, all rules (helper modules keep their tier)."""
    found: List[Violation] = []
    for p in paths:
        path, rel = _rel(p)
        source = path.read_text(encoding="utf-8")
        found.extend(check_source(source, rel, helper=rel in HELPER_MODULES))
        found.extend(check_team_relation(source, rel))
        found.extend(check_writers(source, rel))
    return found


def check_protected_surface() -> Tuple[int, List[Violation]]:
    """The whole configured W0-03E surface: modules, functions and helpers."""
    found = check_files(PROTECTED_MODULES + HELPER_MODULES)
    for p, names in PROTECTED_FUNCTIONS.items():
        path, rel = _rel(p)
        found.extend(check_source(path.read_text(encoding="utf-8"), rel, functions=names))
    units = len(PROTECTED_MODULES) + len(HELPER_MODULES) + sum(map(len, PROTECTED_FUNCTIONS.values()))
    # W0-03E-A2: the authorization relation is checked over the whole app tree.
    team_units, team_found = check_team_relation_tree()
    # W0-03E-A2B: the authorization-deriving scripts, and every writer.
    for rel in AUTHZ_SCRIPTS:
        found.extend(check_team_relation((BACKEND / rel).read_text(encoding="utf-8"), rel))
    writer_units, writer_found = check_writer_tree()
    return (units + team_units + len(AUTHZ_SCRIPTS) + writer_units,
            found + team_found + writer_found)


# ============================================================== W0-03E-A2B
#: Scripts that derive AUTHORIZATION from memberships: A2-TEAM applies to them.
AUTHZ_SCRIPTS: Tuple[str, ...] = ("scripts/w0_02_bootstrap_permissions.py",)

#: Operator scripts that create tenant-owned records: A2B-WRITER applies.
WRITER_SCRIPTS: Tuple[str, ...] = ("scripts/create_company.py",)


def _ownership_module():
    """``app/tenancy/ownership.py`` loaded by file path.

    It is stdlib-only; importing it as ``app.tenancy.ownership`` would run the
    package ``__init__`` (database clients), and the guard must stay a pure
    AST check that needs no application dependency on any platform.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_w0_03e_a2b_ownership", BACKEND / "app" / "tenancy" / "ownership.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _org_keyed() -> frozenset:
    """The tenant-owned collections — read from the ONE classification."""
    return frozenset(_ownership_module().ORG_KEYED)


#: Names that hold a raw database handle anywhere in the app tree.
WRITER_DB_NAMES = DB_NAMES | frozenset({"tdb", "op_db", "sys_db", "system_db", "db_handle"})
CREATE_METHODS = frozenset({"insert_one", "insert_many", "replace_one", "find_one_and_replace"})
UPSERT_METHODS = frozenset({"update_one", "update_many", "find_one_and_update"})
OWNER_KEY = "org_id"


def _is_writer_db(node: ast.AST) -> bool:
    if isinstance(node, ast.IfExp):              # (db if h is None else h)
        return _is_writer_db(node.body) and _is_writer_db(node.orelse)
    if isinstance(node, ast.Name):
        return node.id in WRITER_DB_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in WRITER_DB_NAMES
    if isinstance(node, ast.Await):
        call = node.value
        return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr in WRITER_DB_NAMES)
    return False


def _module_constants(tree: ast.Module) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            out[node.targets[0].id] = node.value.value
    return out


def _prebound(tree: ast.Module) -> Dict[str, str]:
    """``from app.db import invoices [as inv]`` -> {local name: collection}."""
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.db":
            for alias in node.names:
                if alias.name != "db":
                    out[alias.asname or alias.name] = alias.name
    return out


def _dict_owner(node: ast.AST) -> Tuple[bool, bool, Optional[ast.AST]]:
    """(has the owner key, a spread follows it, the owner value)."""
    has, spread_after, value = False, False, None
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if k is None:
                if has:
                    spread_after = True
                continue
            if isinstance(k, ast.Constant) and k.value == OWNER_KEY:
                has, spread_after, value = True, False, v
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict"):
        for kw in node.keywords:
            if kw.arg == OWNER_KEY:
                has, value = True, kw.value
        if not has and node.args:
            return _dict_owner(node.args[0])
    return has, spread_after, value


class _WriterChecker:
    def __init__(self, rel: str, tree: ast.Module, scoped: frozenset):
        self.rel, self.tree, self.scoped = rel, tree, scoped
        self.consts = _module_constants(tree)
        self.prebound = _prebound(tree)
        self.out: List[Violation] = []

    def add(self, node, rule, msg):
        self.out.append((self.rel, getattr(node, "lineno", 0), rule, msg))

    # ---- which collection does a receiver name?
    def _collection(self, node: ast.AST, aliases: Dict[str, str]) -> Optional[str]:
        if isinstance(node, ast.Attribute) and _is_writer_db(node.value):
            return node.attr
        if isinstance(node, ast.Subscript) and _is_writer_db(node.value):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                return key.value
            if isinstance(key, ast.Name):
                return self.consts.get(key.id)
            return None
        if isinstance(node, ast.Name):
            return aliases.get(node.id) or self.prebound.get(node.id)
        return None

    # ---- is a document expression proven to carry the owner?
    def _proven(self, expr: Optional[ast.AST], fn: ast.AST, route_params: frozenset,
                call: ast.Call, many: bool = False) -> bool:
        if expr is None:
            return False
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in (
                "dict", "list") and expr.args and not expr.keywords:
            return self._proven(expr.args[0], fn, route_params, call, many)
        if many:
            if isinstance(expr, (ast.List, ast.Tuple)):
                return bool(expr.elts) and all(
                    self._proven(e, fn, route_params, call) for e in expr.elts)
            if isinstance(expr, ast.ListComp):
                return self._proven(expr.elt, fn, route_params, call)
            if isinstance(expr, ast.Name):
                return self._list_name_proven(expr.id, fn, route_params, call)
            return False
        has, spread_after, value = _dict_owner(expr)
        if has:
            self._judge_value(call, value, spread_after, route_params)
            return True
        if isinstance(expr, ast.Name):
            return self._name_proven(expr.id, fn, route_params, call)
        return False

    def _judge_value(self, call, value, spread_after, route_params):
        if spread_after:
            self.add(call, "A2B-OVERRIDE",
                     "a **spread after the org_id key could replace the server's tenant")
        if value is not None and route_params:
            used = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
            bad = sorted(used & route_params)
            if bad:
                self.add(call, "A2B-OVERRIDE",
                         "org_id value reads caller-controlled route parameter(s) %s"
                         % ", ".join(bad))

    def _name_proven(self, name: str, fn: ast.AST, route_params, call) -> bool:
        ok = False
        for n in ast.walk(fn):
            if isinstance(n, (ast.Assign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id == name and n.value is not None:
                        has, spread_after, value = _dict_owner(n.value)
                        if has:
                            self._judge_value(call, value, spread_after, route_params)
                            ok = True
                        elif self._factory_proven(n.value, route_params, call):
                            ok = True
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                            and t.value.id == name and isinstance(t.slice, ast.Constant)
                            and t.slice.value == OWNER_KEY):
                        self._judge_value(call, n.value, False, route_params)
                        ok = True
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and isinstance(n.func.value, ast.Name) and n.func.value.id == name):
                if n.func.attr == "update" and n.args:
                    has, spread_after, value = _dict_owner(n.args[0])
                    if has:
                        self._judge_value(call, value, spread_after, route_params)
                        ok = True
                if n.func.attr in ("update", "setdefault"):
                    for kw in n.keywords:
                        if kw.arg == OWNER_KEY:
                            ok = True
                if (n.func.attr == "setdefault" and n.args
                        and isinstance(n.args[0], ast.Constant) and n.args[0].value == OWNER_KEY):
                    ok = True
        return ok

    def _factory_proven(self, value: ast.AST, route_params, call) -> bool:
        """``doc = _new_doc()``: a local factory every ``return`` of which is a
        dict literal carrying the owner key."""
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)):
            return False
        defs = [n for n in ast.walk(self.tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == value.func.id]
        if len(defs) != 1:
            return False
        returns = [r for r in ast.walk(defs[0]) if isinstance(r, ast.Return)]
        if not returns:
            return False
        for r in returns:
            has, spread_after, owner = _dict_owner(r.value) if r.value is not None else (
                False, False, None)
            if not has:
                return False
            self._judge_value(call, owner, spread_after, route_params)
        return True

    def _list_name_proven(self, name: str, fn: ast.AST, route_params, call) -> bool:
        """A list filled by ``.append(<proven>)``, built as a proven literal/comp,
        or whose elements are given the key by ``for x in name: x["org_id"] = ...``."""
        appended, all_ok = False, True
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == name
                    and n.func.attr in ("append", "extend")):
                appended = True
                arg = n.args[0] if n.args else None
                if n.func.attr == "extend":
                    all_ok &= self._proven(arg, fn, route_params, call, many=True)
                else:
                    all_ok &= self._proven(arg, fn, route_params, call)
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == name and isinstance(
                            n.value, (ast.List, ast.ListComp)) and (
                            not isinstance(n.value, ast.List) or n.value.elts):
                        appended = True
                        all_ok &= self._proven(n.value, fn, route_params, call, many=True)
            if (isinstance(n, (ast.For, ast.AsyncFor)) and isinstance(n.iter, ast.Name)
                    and n.iter.id == name and isinstance(n.target, ast.Name)):
                var = n.target.id
                for m in ast.walk(n):
                    if (isinstance(m, ast.Assign) and any(
                            isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                            and t.value.id == var and isinstance(t.slice, ast.Constant)
                            and t.slice.value == OWNER_KEY for t in m.targets)):
                        return True
        return appended and all_ok

    def check(self) -> List[Violation]:
        for fn in ast.walk(self.tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route_params = _caller_params(fn) if _is_route(fn) else frozenset()
            aliases: Dict[str, str] = {}
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(
                        n.targets[0], ast.Name):
                    coll = self._collection(n.value, {})
                    if coll is not None and isinstance(n.value, (ast.Attribute, ast.Subscript)):
                        aliases[n.targets[0].id] = coll
                        if coll in self.scoped:
                            self.add(n, "A2B-ALIAS", "tenant-owned collection %r bound to %r "
                                     "hides its writes; call it directly" % (coll, n.targets[0].id))
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                    continue
                method = call.func.attr
                upsert = any(kw.arg == "upsert" and isinstance(kw.value, ast.Constant)
                             and kw.value.value is True for kw in call.keywords)
                if method not in CREATE_METHODS and not (method in UPSERT_METHODS and upsert):
                    continue
                coll = self._collection(call.func.value, aliases)
                if coll is None or coll not in self.scoped:
                    continue
                if method in ("insert_one",):
                    ok = self._proven(_arg(call, 0, "document"), fn, route_params, call)
                elif method == "insert_many":
                    ok = self._proven(_arg(call, 0, "documents"), fn, route_params, call, many=True)
                elif method in ("replace_one", "find_one_and_replace"):
                    ok = self._proven(_arg(call, 1, "replacement"), fn, route_params, call)
                else:
                    flt, upd = _arg(call, 0, "filter"), _arg(call, 1, "update")
                    ok = _dict_owner(flt)[0] if flt is not None else False
                    if ok:
                        self._judge_value(call, _dict_owner(flt)[2], False, route_params)
                    if not ok and isinstance(upd, ast.Dict):
                        for k, v in zip(upd.keys, upd.values):
                            if (isinstance(k, ast.Constant) and k.value in ("$set", "$setOnInsert")
                                    and self._proven(v, fn, route_params, call)):
                                ok = True
                if not ok:
                    self.add(call, "A2B-WRITER",
                             "%s into tenant-owned %r: the document is not proven to carry "
                             "org_id from the server-resolved tenant" % (method, coll))
        return self.out


def check_writers(source: str, rel: str) -> List[Violation]:
    """A2B-WRITER / A2B-OVERRIDE / A2B-ALIAS over one module."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [(rel, exc.lineno or 0, "A2B-WRITER", "could not parse: %s" % exc.msg)]
    out = _WriterChecker(rel, tree, _org_keyed()).check()
    return sorted(set(out), key=lambda v: (v[0], v[1], v[2], v[3]))


def writer_files() -> List[str]:
    """The app tree, ``server.py`` and the writer scripts (POSIX, backend-relative)."""
    files = set(team_relation_files()) | {"server.py"} | set(WRITER_SCRIPTS)
    return sorted(f for f in files if (BACKEND / f).is_file())


def check_writer_tree() -> Tuple[int, List[Violation]]:
    found: List[Violation] = []
    files = writer_files()
    for rel in files:
        found.extend(check_writers((BACKEND / rel).read_text(encoding="utf-8"), rel))
    return len(files), found


def main(argv: List[str]) -> int:
    try:
        if argv:
            units, violations = len(argv), check_files(argv)
        else:
            units, violations = check_protected_surface()
    except (OSError, SyntaxError) as exc:
        print("guard error: %s" % exc, file=sys.stderr)
        return 2
    for rel, line, rule, msg in violations:
        print("%s:%d: %s %s" % (rel, line, rule, msg))
    print("W0-03E-A1 tenant access guard: %d unit(s) checked, %d violation(s)"
          % (units, len(violations)))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
