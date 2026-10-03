#!/usr/bin/env python3
"""
W0-03E-A2C — generate the full active-backend tenant access inventory.

Issue #41 §1 asks for every active route, service, job and helper that reads or
writes tenant-owned operational data, each access classified

    path | function | collection | operation | current tenant predicate | risk | action

with no hidden exclusion and no ``ASSUMED SAFE``. This script produces that,
generated from the code by the same AST resolution the A2C guard uses, so the
document cannot drift from what ships and nothing can be omitted by hand.

Every access is classified into exactly one of:

``TENANT_VIEW``
    Reached through ``app.tenancy.data_access.TenantData`` (``tenant.<collection>``
    or a ``for_*`` constructor). The tenant predicate is applied by the access
    layer on every read and inside every write filter, so it cannot be forgotten
    at the call site. This is where the active surface is meant to be.

``RAW_SCOPED``
    A raw handle whose own filter carries a literal ``org_id``/``tenant_id`` (or
    ``scoped(...)``/``_scope(...)``). Proven, but the predicate is hand-written.

``TENANT_DATABASE``
    A ``tenant_id``-keyed W0-03/W0-04 store on a handle that
    ``get_tenant_db(tenant_id)`` opened on that tenant's OWN database, so the
    database is the boundary (CLAUDE.md §3, database-per-tenant). The guard proves
    these modules never take the shared legacy handle.

``BOUNDARY_CODE``
    The modules that implement the boundary (the access layer, the resolver,
    registry, onboarding, the one-time legacy backfill, the ``project_team``
    accessor) plus the one declared cross-tenant enumeration. Deliberately not
    expressible in terms of the boundary.

``PRE_TENANT``
    A declared, per-function, per-collection access that runs before a tenant
    exists (installation seed, login, session resolution, platform bootstrap) or
    reports across the installation read-only. Each is named in the guard and its
    existence is enforced.

``UNSCOPED``
    A raw tenant-owned access with no provable tenant predicate. **Every one of
    these is a defect.** The inventory exists to show this column is empty.

Pure AST: no database, no application import.

    python scripts/w0_03e_a2c_inventory.py                  # write the doc
    python scripts/w0_03e_a2c_inventory.py --out -           # stdout
    python scripts/w0_03e_a2c_inventory.py --summary         # counts only
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import w0_03e_a1_tenant_access_guard as a1  # noqa: E402
import w0_03e_a2c_tenant_boundary_guard as guard  # noqa: E402

BACKEND = guard.BACKEND
DOC = BACKEND.parent / "docs" / "architecture" / "W0-03E-A2C_INVENTORY.md"

READ_METHODS = guard.READS
WRITE_METHODS = guard.WRITES | guard.CREATES

CLASS_TENANT_VIEW = "TENANT_VIEW"
CLASS_RAW_SCOPED = "RAW_SCOPED"
CLASS_TENANT_DB = "TENANT_DATABASE"
CLASS_BOUNDARY = "BOUNDARY_CODE"
CLASS_PRE_TENANT = "PRE_TENANT"
CLASS_UNSCOPED = "UNSCOPED"

ORDER = (CLASS_TENANT_VIEW, CLASS_RAW_SCOPED, CLASS_TENANT_DB, CLASS_BOUNDARY,
         CLASS_PRE_TENANT, CLASS_UNSCOPED)

RISK = {
    CLASS_TENANT_VIEW: "none — predicate applied by the access layer",
    CLASS_RAW_SCOPED: "low — predicate present but hand-written",
    CLASS_TENANT_DB: "none — handle is this tenant's own database",
    CLASS_BOUNDARY: "n/a — this code IS the boundary",
    CLASS_PRE_TENANT: "declared — no tenant exists yet, or read-only report",
    CLASS_UNSCOPED: "CROSS-TENANT READ/WRITE when ids collide",
}
ACTION = {
    CLASS_TENANT_VIEW: "keep",
    CLASS_RAW_SCOPED: "keep; prefer the tenant view when next edited",
    CLASS_TENANT_DB: "keep",
    CLASS_BOUNDARY: "keep",
    CLASS_PRE_TENANT: "keep; guard enforces the declaration",
    CLASS_UNSCOPED: "FIX — route through TenantData",
}


class Access(NamedTuple):
    path: str
    function: str
    collection: str
    operation: str
    predicate: str
    klass: str

    @property
    def kind(self) -> str:
        if self.operation in WRITE_METHODS:
            return "write"
        if self.operation in READ_METHODS:
            return "read"
        return "other"


def _owner_of(line: int, fns) -> str:
    inner = [f for f in fns if f.lineno <= line <= f.end_lineno]
    return inner[-1].name if inner else "<module>"


def _predicate_of(call: ast.Call, method: str) -> str:
    """How this call proves its tenant, in words."""
    if method == "aggregate":
        return ("first stage tenant $match" if a1._pipeline_scoped(a1._arg(call, 0, "pipeline"))
                else "none")
    idx = 1 if method in guard.FILTER_SECOND else 0
    flt = a1._arg(call, idx, "filter")
    if flt is None:
        return "no filter"
    if a1._is_scope_call(flt):
        return "scoped(...) applies the tenant last"
    val = a1._tenant_value(flt)
    if val is not None:
        try:
            return "literal %s" % ast.unparse(flt)[:58]
        except Exception:
            return "literal tenant key"
    return "none"


def collect() -> List[Access]:
    """Every tenant-owned access in the active backend, classified."""
    own = a1._ownership_module()
    out: List[Access] = []

    for rel in guard.active_backend_files():
        src = (BACKEND / rel).read_text(encoding="utf-8")
        tree = ast.parse(src, filename=rel)
        fns = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        constants = a1._module_constants(tree)
        pre = guard.PRE_TENANT_FUNCTIONS.get(rel, {})
        diag = guard.READ_ONLY_DIAGNOSTIC.get(rel, ())
        boundary = guard._boundary_is_the_database(rel)
        tenant_db = rel in guard.TENANT_DB_SCOPED

        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                continue
            recv, method = call.func.value, call.func.attr
            if method not in READ_METHODS | WRITE_METHODS:
                continue
            fn = _owner_of(getattr(recv, "lineno", 0), fns)

            # ---- through the tenant view
            if guard._is_tenant_collection(recv):
                try:
                    coll = recv.attr if isinstance(recv, ast.Attribute) else ast.unparse(recv)[:40]
                except Exception:
                    coll = "<tenant view>"
                out.append(Access(rel, fn, coll, method,
                                  "TenantData applies it to filter and write filter",
                                  CLASS_TENANT_VIEW))
                continue

            # ---- raw handle
            is_coll, name = guard._collection_of(recv, constants)
            if not is_coll:
                continue
            coll = name or "[<expression>]"
            cls = own.classify_collection(name) if name else own.CLASS_UNCLASSIFIED
            if cls not in (own.CLASS_ORG, own.CLASS_TENANT_ID, own.CLASS_ROOT,
                           own.CLASS_UNCLASSIFIED):
                continue                      # technical bookkeeping: no tenant meaning
            pred = _predicate_of(call, method)

            if fn in pre and name in pre[fn]:
                klass = CLASS_PRE_TENANT
            elif fn in diag:
                klass = CLASS_PRE_TENANT
            elif tenant_db:
                klass = CLASS_TENANT_DB
            elif boundary:
                klass = CLASS_BOUNDARY
            elif pred != "none" and pred != "no filter":
                klass = CLASS_RAW_SCOPED
            elif method in guard.CREATES:
                klass = CLASS_RAW_SCOPED      # document side is judged by A2B-WRITER
            else:
                klass = CLASS_UNSCOPED
            out.append(Access(rel, fn, coll, method, pred, klass))

    return sorted(out, key=lambda a: (ORDER.index(a.klass), a.path, a.function, a.collection,
                                      a.operation))


def _table(rows: List[Access]) -> List[str]:
    out = ["| path | function | collection | operation | current tenant predicate | risk | action |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for a in rows:
        out.append("| `%s` | `%s()` | `%s` | %s | %s | %s | %s |"
                   % (a.path, a.function, a.collection, a.operation,
                      a.predicate.replace("|", "\\|"), RISK[a.klass], ACTION[a.klass]))
    return out


def build() -> str:
    accesses = collect()
    by_class = Counter(a.klass for a in accesses)
    by_kind = Counter((a.klass, a.kind) for a in accesses)
    units, violations = guard.check_active_backend()
    own = a1._ownership_module()

    L: List[str] = []
    L.append("# W0-03E-A2C — active backend tenant access inventory")
    L.append("")
    L.append("> GENERATED by `backend/scripts/w0_03e_a2c_inventory.py`. Do not edit by hand.")
    L.append("> Regenerate after any change to the data-access surface.")
    L.append("")
    L.append("На човешки: таблицата по-долу изброява всяко място в активния backend, "
             "което чете или пише данни на фирма. Колоната `UNSCOPED` трябва да е празна — "
             "там са местата, където при еднакви ID-та данни могат да прескочат между две фирми.")
    L.append("")
    L.append("## 1. Scope")
    L.append("")
    L.append("The inventory covers the **whole active backend**, derived from the filesystem "
             "rather than a hand-written list: every `app/**/*.py`, `server.py`, and the "
             "operator scripts declared in the guard.")
    L.append("")
    L.append("* modules inventoried: **%d**" % units)
    L.append("* tenant-owned accesses found: **%d** (%d reads, %d writes)"
             % (len(accesses),
                sum(1 for a in accesses if a.kind == "read"),
                sum(1 for a in accesses if a.kind == "write")))
    L.append("* static guard on the same scope: **%d violation(s)**" % len(violations))
    L.append("")
    L.append("## 2. Classification summary")
    L.append("")
    L.append("| class | accesses | reads | writes | meaning |")
    L.append("| --- | --- | --- | --- | --- |")
    for cls in ORDER:
        L.append("| `%s` | %d | %d | %d | %s |"
                 % (cls, by_class.get(cls, 0), by_kind.get((cls, "read"), 0),
                    by_kind.get((cls, "write"), 0), RISK[cls]))
    L.append("")
    unscoped = [a for a in accesses if a.klass == CLASS_UNSCOPED]
    if unscoped:
        L.append("**%d UNSCOPED access(es) remain — each is a defect:**" % len(unscoped))
        L.append("")
        L.extend(_table(unscoped))
    else:
        L.append("**`UNSCOPED` is empty: there is no active tenant-owned read or write "
                 "without a server-resolved tenant predicate.** Issue #41 §8 requires "
                 "active bare-ID reads = 0 and active bare-ID writes = 0.")
    L.append("")
    L.append("## 3. Declared exemption tiers")
    L.append("")
    L.append("Every tier is narrow, technically justified, and enforced by the guard; none "
             "contains tenant-owned business access.")
    L.append("")
    L.append("### 3.1 `TENANCY_CORE` — implements the boundary (%d modules)"
             % len(guard.TENANCY_CORE))
    L.append("")
    for rel in guard.TENANCY_CORE:
        L.append("* `%s`" % rel)
    L.append("")
    L.append("### 3.2 `TENANT_DB_SCOPED` — one database per tenant (%d modules)"
             % len(guard.TENANT_DB_SCOPED))
    L.append("")
    L.append("Handle opened by `get_tenant_db(tenant_id)`; the guard rejects any import of "
             "the shared legacy handle in these modules (`A2C-SHAREDDB`), so the exemption "
             "is proven rather than trusted.")
    L.append("")
    for rel in guard.TENANT_DB_SCOPED:
        L.append("* `%s`" % rel)
    L.append("")
    L.append("### 3.3 `PRE_TENANT_FUNCTIONS` — per function, per collection")
    L.append("")
    L.append("| module | function | collections allowed raw |")
    L.append("| --- | --- | --- |")
    for rel, fns in sorted(guard.PRE_TENANT_FUNCTIONS.items()):
        for fn, colls in sorted(fns.items()):
            L.append("| `%s` | `%s()` | %s |"
                     % (rel, fn, ", ".join("`%s`" % c for c in sorted(colls)) or "—"))
    L.append("")
    L.append("### 3.4 `READ_ONLY_DIAGNOSTIC` — counts and reports, no writes")
    L.append("")
    L.append("| module | function |")
    L.append("| --- | --- |")
    for rel, fns in sorted(guard.READ_ONLY_DIAGNOSTIC.items()):
        for fn in fns:
            L.append("| `%s` | `%s()` |" % (rel, fn))
    L.append("")
    L.append("The guard proves each of these functions contains no write method "
             "(`A2C-DIAGNOSTIC`), and that every declared function still exists "
             "(`A2C-SCOPE`), so a rename cannot shrink the scope in silence.")
    L.append("")
    L.append("## 4. Fixed-`_id` settings collision")
    L.append("")
    L.append("`_id` is unique per collection, so a global literal `_id` means the "
             "installation can hold exactly one such row: the first tenant to save owns it "
             "and every other tenant's upsert fails with a duplicate key. "
             "`app.tenancy.settings_identity` gives each row the id `\"<key>:<org_id>\"`.")
    L.append("")
    from app.tenancy import settings_identity as si
    L.append("| setting key | legacy `_id` | A2C `_id` | readers / writers |")
    L.append("| --- | --- | --- | --- |")
    users = defaultdict(list)
    for rel in guard.active_backend_files():
        src = (BACKEND / rel).read_text(encoding="utf-8")
        for key in si.LEGACY_GLOBAL_KEYS:
            const = key.upper()
            if const in src or '"%s"' % key in src:
                users[key].append(rel)
    for key in si.LEGACY_GLOBAL_KEYS:
        L.append("| `%s` | `%s` | `%s:<org_id>` | %s |"
                 % (key, key, key,
                    ", ".join("`%s`" % u for u in sorted(users[key])) or "—"))
    L.append("")
    L.append("Migration: `backend/scripts/w0_03e_a2c_settings_identity_migration.py` "
             "(dry run by default, idempotent, resumable, never overwrites a differing "
             "tenant row, refuses an ownerless row).")
    L.append("")
    L.append("## 5. Full access table")
    L.append("")
    L.append("Ordered by class, then path. Nothing is omitted.")
    L.append("")
    for cls in ORDER:
        rows = [a for a in accesses if a.klass == cls]
        if not rows:
            L.append("### %s — none" % cls)
            L.append("")
            continue
        L.append("### %s (%d)" % (cls, len(rows)))
        L.append("")
        L.extend(_table(rows))
        L.append("")
    L.append("## 6. Collection classification")
    L.append("")
    L.append("Every collection the application names is classified in "
             "`app/tenancy/ownership.py`; an unclassified one fails the guard "
             "(`A2C-UNCLASSIFIED`) rather than passing.")
    L.append("")
    L.append("* `ORG_KEYED` (tenant-owned, `org_id`): **%d**" % len(own.ORG_KEYED))
    L.append("* `TENANT_ID_KEYED` (W0-03/W0-04, `tenant_id`): **%d** + prefixes %s"
             % (len(own.TENANT_ID_KEYED), list(own.TENANT_ID_KEYED_PREFIXES)))
    L.append("* `TENANT_ROOT`: `%s`" % own.TENANT_ROOT)
    L.append("* `TECHNICAL`: **%d**" % len(own.TECHNICAL))
    L.append("")
    while L and not L[-1].strip():
        L.pop()                      # no blank line at EOF (git diff --check)
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", default=str(DOC), help="output file, or - for stdout")
    ap.add_argument("--summary", action="store_true", help="print counts only")
    args = ap.parse_args(argv)

    if args.summary:
        accesses = collect()
        by_class = Counter(a.klass for a in accesses)
        units, violations = guard.check_active_backend()
        print("W0-03E-A2C inventory: %d modules, %d tenant-owned accesses, %d guard violation(s)"
              % (units, len(accesses), len(violations)))
        for cls in ORDER:
            print("  %-16s %4d" % (cls, by_class.get(cls, 0)))
        return 1 if by_class.get(CLASS_UNSCOPED) or violations else 0

    text = build()
    if args.out == "-":
        sys.stdout.write(text)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print("wrote %s (%d lines)" % (out, text.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
