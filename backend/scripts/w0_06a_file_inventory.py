#!/usr/bin/env python3
"""
W0-06A — generate the active-backend file/media/document inventory.

Issue #43 §1 asks for every existing file/media/document path and writer in the
active backend, each published as

    path | function/route | current storage location | current id/path/url field
        | tenant field | business relation | read/write/delete behaviour
        | migration action

with no ``ASSUMED SAFE``. This script produces that document, and — this is the
point — it does not produce it from a list somebody typed. It SCANS the code
for file-bearing sites and cross-checks what it finds against the declared
sources in :mod:`app.files.migration_map`:

* a site the scan finds that no declared source accounts for makes the run FAIL
  (``UNACCOUNTED``), so the inventory cannot be quietly incomplete;
* a declared source whose writers no longer exist makes the run FAIL
  (``STALE``), so the inventory cannot describe code that is gone;
* the static guard's own freeze list is compared against the same scan, so the
  document, the guard and the migration plan describe one reality.

A site is "file-bearing" when it persists one of the pointer fields the guard
knows (``url``, ``stored_filename``, ``photo_b64``, ``file_url``, ...), writes
bytes to disk, or deletes a stored object. Reads and projections are not sites:
they store no identity, and including them would bury the fifteen real ones.

Pure AST plus the two stdlib-only application modules, loaded by file path: no
database, no application import, no network.

    python scripts/w0_06a_file_inventory.py              # write the doc
    python scripts/w0_06a_file_inventory.py --out -      # stdout
    python scripts/w0_06a_file_inventory.py --check      # verify only, exit 1 on drift
    python scripts/w0_06a_file_inventory.py --summary    # counts only
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import w0_06a_file_registry_guard as guard  # noqa: E402

BACKEND = guard.BACKEND
DOC = BACKEND.parent / "docs" / "architecture" / "W0-06A_FILE_INVENTORY.md"

_migration = guard._migration
_models = guard._models

#: Writing bytes to the application disk.
BYTE_WRITE_CALLS = frozenset({"write_bytes", "write_text", "copyfileobj"})
#: Reading an UploadFile body — the moment a customer file enters the process.
UPLOAD_MARKERS = frozenset({"UploadFile"})


class Site(NamedTuple):
    """One file-bearing place in the code."""
    path: str
    function: str
    kind: str          # POINTER_WRITE | BYTE_WRITE | PHYSICAL_DELETE | UPLOAD_ENTRY
    detail: str
    line: int

    @property
    def site_id(self) -> str:
        return "%s::%s" % (self.path, self.function)


class _Scanner(ast.NodeVisitor):
    def __init__(self, rel: str, tree: ast.Module):
        self.rel = rel
        self.sites: List[Site] = []
        self.functions: List[str] = []
        self.scopes: List[guard.DocumentScope] = []
        self.literals: Dict[str, str] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                    and isinstance(stmt.targets[0], ast.Name) \
                    and isinstance(stmt.value, ast.Constant) \
                    and isinstance(stmt.value.value, str):
                self.literals[stmt.targets[0].id] = stmt.value.value

    @property
    def _fn(self) -> str:
        return self.functions[-1] if self.functions else "<module>"

    def visit_FunctionDef(self, node):
        self.functions.append(node.name)
        self.scopes.append(guard.DocumentScope(node))
        self._check_upload_entry(node)
        self.generic_visit(node)
        self.scopes.pop()
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef   # type: ignore[assignment]

    @property
    def _scope(self):
        return self.scopes[-1] if self.scopes else None

    def _check_upload_entry(self, node) -> None:
        """A route that accepts an uploaded file: where a customer byte arrives."""
        for arg in list(node.args.args) + list(node.args.kwonlyargs):
            ann = arg.annotation
            name = None
            if isinstance(ann, ast.Name):
                name = ann.id
            elif isinstance(ann, ast.Attribute):
                name = ann.attr
            elif isinstance(ann, ast.Subscript):
                inner = ann.slice
                if isinstance(inner, ast.Name):
                    name = inner.id
            if name in UPLOAD_MARKERS:
                self.sites.append(Site(self.rel, node.name, "UPLOAD_ENTRY",
                                       "accepts %s" % arg.arg, node.lineno))
                return

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in guard.WRITE_METHODS:
                for field, value in guard._persisted_fields(node, func.attr, self._scope):
                    line = getattr(value, "lineno", node.lineno)
                    if field in guard.POINTER_FIELDS:
                        self.sites.append(Site(self.rel, self._fn, "POINTER_WRITE",
                                               field, line))
                    elif field in guard.ATTACHMENT_REFERENCE_FIELDS:
                        self.sites.append(Site(self.rel, self._fn, "ATTACHMENT_REFERENCE",
                                               field, line))
            if func.attr in BYTE_WRITE_CALLS:
                self.sites.append(Site(self.rel, self._fn, "BYTE_WRITE",
                                       func.attr, node.lineno))
            if func.attr in guard.DELETE_CALLS:
                self.sites.append(Site(self.rel, self._fn, "PHYSICAL_DELETE",
                                       func.attr, node.lineno))
        self.generic_visit(node)

    def visit_With(self, node: ast.With):
        """``with open(path, "wb") as f: f.write(content)`` — the legacy upload shape."""
        for item in node.items:
            call = item.context_expr
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                    and call.func.id == "open" and len(call.args) >= 2:
                mode = call.args[1]
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                        and ("w" in mode.value or "a" in mode.value):
                    self.sites.append(Site(self.rel, self._fn, "BYTE_WRITE",
                                           'open(..., %r)' % mode.value, node.lineno))
        self.generic_visit(node)


def scan() -> List[Site]:
    """Every file-bearing site of the active backend, sorted and stable."""
    sites: List[Site] = []
    for rel in guard.active_backend_files():
        if rel in guard.FOUNDATION_MODULES:
            # The File Registry itself is the destination, not a legacy source.
            continue
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"), filename=rel)
        scanner = _Scanner(rel, tree)
        scanner.visit(tree)
        sites.extend(scanner.sites)
    return sorted(set(sites))


def declared_site_ids() -> Set[str]:
    """Every ``path::function`` the migration map or the guard freeze list names."""
    out: Set[str] = set(guard.LEGACY_POINTER_SITES)
    out |= set(guard.LEGACY_PHYSICAL_DELETE_SITES)
    for source in _migration.LEGACY_SOURCES:
        out.update(source.writers)
    return out


#: Declared writers whose file field is set through a DYNAMIC field list, so no
#: static scan can see it as a document key. Each is named with the exact shape,
#: and the declaration is enforced: the module and the function must exist, and
#: the stated marker must still be present in the function. This is the honest
#: alternative to either a false "clean" or an unexplained failure.
DYNAMIC_FIELD_WRITERS: Dict[str, str] = {
    "app/routes/work_logs.py::update_change_order":
        'copies fields by name from a literal list (``for field in [..., "attachments"]``), '
        'so "attachments" is a loop variable at the write, not a document key',
}


def _dynamic_writer_problems() -> List[str]:
    """Prove each declared dynamic writer still exists and still looks that way."""
    out: List[str] = []
    for site_id in sorted(DYNAMIC_FIELD_WRITERS):
        path, _, function = site_id.partition("::")
        full = BACKEND / path
        if not full.is_file():
            out.append("%s (module missing)" % site_id)
            continue
        tree = ast.parse(full.read_text(encoding="utf-8"), filename=path)
        target = next((n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == function), None)
        if target is None:
            out.append("%s (function missing)" % site_id)
            continue
        literals = {c.value for c in ast.walk(target)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if not literals & (guard.POINTER_FIELDS | guard.ATTACHMENT_REFERENCE_FIELDS):
            out.append("%s (no longer names a file field; remove the declaration)" % site_id)
    return out


def _no_content_writers() -> Set[str]:
    """Writers of sources whose verdict is ``NO_FILE_CONTENT``.

    ``excel_import_templates`` stores a column mapping and no file, so its
    writer correctly contains no file-bearing code. It is still declared,
    because a reader of the inventory must see the verdict rather than find the
    collection missing and have to work out why.
    """
    return {w for source in _migration.LEGACY_SOURCES
            if source.action == _migration.ACTION_NONE for w in source.writers}


def _upload_entries_are_covered(sites: Sequence[Site]) -> List[str]:
    """An upload route whose function writes no pointer and no byte is reported.

    Several routes accept an ``UploadFile`` and parse it in memory without ever
    persisting it (the Excel and offer importers). Those are not file sources,
    and saying so explicitly is the difference between an inventory and a
    list of greps.
    """
    persisting = {s.site_id for s in sites if s.kind in ("POINTER_WRITE", "BYTE_WRITE")}
    return sorted({s.site_id for s in sites
                   if s.kind == "UPLOAD_ENTRY" and s.site_id not in persisting})


def reconcile(sites: Sequence[Site]) -> Dict[str, List[str]]:
    """``{problem: [detail]}``. Empty means the code and the declarations agree."""
    declared = declared_site_ids()
    problems: Dict[str, List[str]] = {"UNACCOUNTED": [], "STALE": [],
                                      "DYNAMIC_DECLARATION": []}

    for site in sites:
        if site.kind == "UPLOAD_ENTRY":
            continue        # judged separately: an in-memory parse is not a source
        if site.site_id not in declared:
            problems["UNACCOUNTED"].append(
                "%s (%s %s, line %d)" % (site.site_id, site.kind, site.detail, site.line))

    present = {s.site_id for s in sites}
    for site_id in sorted(declared):
        path, _, function = site_id.partition("::")
        full = BACKEND / path
        if not full.is_file():
            problems["STALE"].append("%s (module missing)" % site_id)
            continue
        tree = ast.parse(full.read_text(encoding="utf-8"), filename=path)
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if function not in names:
            problems["STALE"].append("%s (function missing)" % site_id)
        elif site_id not in present and site_id not in _no_content_writers() \
                and site_id not in DYNAMIC_FIELD_WRITERS:
            problems["STALE"].append("%s (declared but no file-bearing code found)" % site_id)

    dynamic = _dynamic_writer_problems()
    if dynamic:
        problems["DYNAMIC_DECLARATION"] = dynamic

    return {k: v for k, v in problems.items() if v}


# ------------------------------------------------------------------ rendering
def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |"


def render(sites: Sequence[Site]) -> str:
    by_site: Dict[str, List[Site]] = defaultdict(list)
    for s in sites:
        by_site[s.site_id].append(s)
    problems = reconcile(sites)
    uncovered_uploads = _upload_entries_are_covered(sites)

    lines: List[str] = []
    add = lines.append
    add("# W0-06A — active-backend file / media / document inventory")
    add("")
    add("> Generated by `backend/scripts/w0_06a_file_inventory.py`. Do not edit by hand.")
    add("> Task W0-06A / C01, Issue #43 §1, canon FLOW-016.")
    add("")
    add("Every file-bearing site of the active backend (`app/**/*.py` + `server.py`), found")
    add("by scanning the code rather than by listing it. The scan is cross-checked against")
    add("the declared sources in `app/files/migration_map.py` and the freeze list in")
    add("`backend/scripts/w0_06a_file_registry_guard.py`: a site the scan finds that no")
    add("source accounts for fails the run, and so does a declaration whose code is gone.")
    add("There is no `ASSUMED SAFE` row and no exclusion.")
    add("")
    add("## 1. Sources — the required Issue #43 §1 row")
    add("")
    add(_row(["path", "function / route", "current storage location",
              "current id / path / url field", "tenant field", "business relation",
              "read / write / delete behaviour", "migration action"]))
    add(_row(["---"] * 8))
    for source in _migration.LEGACY_SOURCES:
        writers = ", ".join(w.split("::")[-1] for w in source.writers) or "(no writer)"
        paths = sorted({w.split("::")[0] for w in source.writers}) or [source.collection]
        add(_row([
            "<br>".join(paths),
            "%s<br>collection `%s`" % (writers, source.collection),
            source.physical_root or "no bytes of its own",
            "`%s`%s" % (source.legacy_reference_field,
                        (" + " + ", ".join("`%s`" % f for f in source.pointer_fields))
                        if source.pointer_fields else ""),
            "`%s`" % source.tenant_field,
            source.business_relation,
            source.behaviour,
            source.migration_action,
        ]))
    add("")

    add("## 2. Every file-bearing site found by the scan")
    add("")
    add(_row(["site", "kind", "detail", "line", "accounted for by"]))
    add(_row(["---"] * 5))
    declared = declared_site_ids()
    source_of: Dict[str, str] = {}
    for source in _migration.LEGACY_SOURCES:
        for writer in source.writers:
            source_of[writer] = source.key
    for site_id in sorted(by_site):
        for s in sorted(by_site[site_id], key=lambda x: (x.kind, x.detail, x.line)):
            if s.kind == "UPLOAD_ENTRY":
                owner = source_of.get(site_id) or ("in-memory parse, nothing persisted"
                                                   if site_id in uncovered_uploads else "—")
            elif s.kind == "PHYSICAL_DELETE":
                owner = ("frozen legacy delete path"
                         if site_id in guard.LEGACY_PHYSICAL_DELETE_SITES else "UNACCOUNTED")
            else:
                owner = source_of.get(site_id,
                                      "frozen pointer site" if site_id in declared
                                      else "UNACCOUNTED")
            add(_row([site_id, s.kind, "`%s`" % s.detail, str(s.line), owner]))
    add("")

    add("## 3. Upload routes that persist nothing")
    add("")
    add("These accept an `UploadFile`, parse it in memory and never store it. They are")
    add("NOT file sources and have nothing to migrate — stated here so their absence from")
    add("section 1 is a verdict rather than an omission.")
    add("")
    for site_id in uncovered_uploads:
        add("- `%s`" % site_id)
    if not uncovered_uploads:
        add("- (none)")
    add("")

    add("## 4. Writers a static scan cannot see as a document key")
    add("")
    add("Declared explicitly. Each is proven to exist and to still name a file field; the")
    add("scan cannot show it as a document key because the field is set through a dynamic")
    add("list. Listed so the gap is visible rather than silent.")
    add("")
    for site_id, why in sorted(DYNAMIC_FIELD_WRITERS.items()):
        add("- `%s` — %s" % (site_id, why))
    add("")

    add("## 5. Reconciliation")
    add("")
    if not problems:
        add("**Clean.** Every file-bearing site the scan found is accounted for by a declared")
        add("source or by the frozen legacy list, and every declaration still matches real code.")
    else:
        for kind, items in sorted(problems.items()):
            add("### %s" % kind)
            add("")
            for item in items:
                add("- %s" % item)
            add("")
    add("")

    add("## 6. Counts")
    add("")
    counts: Dict[str, int] = defaultdict(int)
    for s in sites:
        counts[s.kind] += 1
    add(_row(["metric", "value"]))
    add(_row(["---", "---"]))
    add(_row(["declared legacy sources", str(len(_migration.LEGACY_SOURCES))]))
    add(_row(["distinct file-bearing sites", str(len(by_site))]))
    for kind in sorted(counts):
        add(_row(["sites of kind %s" % kind, str(counts[kind])]))
    add(_row(["frozen pointer sites (guard)", str(len(guard.LEGACY_POINTER_SITES))]))
    add(_row(["frozen physical-delete sites (guard)",
              str(len(guard.LEGACY_PHYSICAL_DELETE_SITES))]))
    add(_row(["reconciliation problems", str(sum(len(v) for v in problems.values()))]))
    add("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--out", default=str(DOC), help="output path, or - for stdout")
    parser.add_argument("--check", action="store_true",
                        help="verify the scan reconciles; write nothing")
    parser.add_argument("--summary", action="store_true", help="print counts only")
    args = parser.parse_args(list(argv))

    sites = scan()
    problems = reconcile(sites)

    if args.summary or args.check:
        print("W0-06A file inventory: %d site(s), %d declared source(s), %d problem(s)"
              % (len(sites), len(_migration.LEGACY_SOURCES),
                 sum(len(v) for v in problems.values())))
        for kind, items in sorted(problems.items()):
            for item in items:
                print("  %s %s" % (kind, item))
        return 1 if problems else 0

    text = render(sites)
    if args.out == "-":
        sys.stdout.write(text)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print("wrote %s (%d site(s), %d problem(s))"
              % (out, len(sites), sum(len(v) for v in problems.values())))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
