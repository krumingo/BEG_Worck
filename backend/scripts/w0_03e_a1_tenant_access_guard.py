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
    return units + team_units, found + team_found


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
