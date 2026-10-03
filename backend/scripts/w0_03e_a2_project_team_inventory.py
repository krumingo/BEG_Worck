#!/usr/bin/env python3
"""
W0-03E-A2 — machine-generated inventory of the ``project_team`` relation surface.

Every writer and every authorization reader of ``project_team`` in the whole
``app/`` tree, as ``path:function | route | kind | accessor | tenant predicate |
at base | action``. The point of generating it is that it cannot drift from the
code and cannot quietly omit a path: the A2 static guard rule (``A2-TEAM``)
rejects any access this script would not be able to classify, so a site that is
missing here fails the guard instead of disappearing.

``at base`` compares the SAME function at a base revision (default: the A1 head
``4b7f986``, read with ``git show``): ``bare@base`` means the function reached
``project_team`` there without a tenant predicate — the A1 defect — and the A2
row is ``FIXED``. ``scoped@base`` was already tenant-scoped → ``SAFE``.
``new@A2`` is a site A2 introduced.

Read-only: no import of the checked code, no database.

    cd backend && python scripts/w0_03e_a2_project_team_inventory.py > inventory.md
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import w0_03e_a1_tenant_access_guard as g  # noqa: E402

A1_HEAD = "4b7f9869c288a9b9596bb8d2c02136b0fb749acb"
RELATION_MODULE = "app/tenancy/project_team.py"

#: Accessor → (kind, what the predicate is). The relation module is the only
#: place that touches the collection, and it does so through TenantData, so the
#: tenant predicate of every row below is applied by ``TenantData.scoped()``.
ACCESSORS: Dict[str, Tuple[str, str]] = {
    "is_member": ("authorization read", "org_id+project_id+user_id[+role]"),
    "member_row": ("authorization read", "org_id+project_id+user_id[+role]"),
    "assigned_project_ids": ("authorization read", "org_id+user_id → tenant projects"),
    "managed_project_ids": ("authorization read", "org_id+user_id+role=SiteManager"),
    "project_rows": ("roster read", "org_id+project_id ∈ tenant projects"),
    "project_member_ids": ("roster read", "org_id+project_id ∈ tenant projects"),
    "user_rows": ("history read", "org_id+user_id"),
    "active_member_count": ("roster read", "org_id+project_id ∈ tenant projects"),
    "row_by_id": ("authorization read", "org_id+id+project_id"),
    "add_member": ("WRITE", "org_id stamped from active tenant"),
    "build_row": ("WRITE", "org_id stamped from active tenant"),
    "deactivate_member": ("WRITE", "org_id+id+project_id"),
    "deactivate_project": ("WRITE", "org_id+project_id"),
    "tenant_for": ("tenant resolution", "session user org_id (server-side)"),
    "tenant_for_org": ("tenant resolution", "caller-resolved org_id (server-side)"),
    # the A1 entry points, which now delegate to the relation module
    "is_project_member": ("authorization read", "org_id+project_id+user_id[+role]"),
}

#: ``TenantData`` collection views of the relation, used where a route needs a
#: raw predicate the accessors do not wrap (still tenant-scoped by the layer).
COLLECTION_CALLS = {"find", "find_one", "count", "delete_many", "update_many", "insert_one"}


def _route_of(fn: ast.AST) -> str:
    for dec in getattr(fn, "decorator_list", []):
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args \
                and isinstance(dec.args[0], ast.Constant):
            return "%s %s" % (dec.func.attr.upper(), dec.args[0].value)
    return "(helper)"


def _base_source(rel: str, base: str) -> Optional[str]:
    try:
        return subprocess.run(["git", "show", "%s:backend/%s" % (base, rel)],
                              cwd=BACKEND.parent, capture_output=True, text=True,
                              check=True).stdout
    except subprocess.CalledProcessError:
        return None


def _base_state(rel: str, func: str, base: str) -> str:
    """How that function reached ``project_team`` at the base revision."""
    source = _base_source(rel, base)
    if source is None:
        return "new@A2"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "unparsed@base"
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != func:
            continue
        scoped, bare = False, False
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                owner = sub.func.value
                # both spellings the base used: db.project_team.<m>(...) and
                # tenant._db["project_team"].<m>(...)
                names = {n.attr for n in ast.walk(owner) if isinstance(n, ast.Attribute)}
                names |= {n.slice.value for n in ast.walk(owner)
                          if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                          and isinstance(n.slice.value, str)}
                if "project_team" not in names:
                    continue
                literal = sub.args[0] if sub.args else None
                keys = ({k.value for k in literal.keys if isinstance(k, ast.Constant)}
                        if isinstance(literal, ast.Dict) else set())
                if keys & {"org_id", "tenant_id"}:
                    scoped = True
                else:
                    bare = True
        if bare:
            return "bare@base"
        if scoped:
            return "scoped@base"
        return "absent@base"
    return "new@A2"


def build(base: str) -> List[Tuple]:
    rows: List[Tuple] = []
    for rel in g.team_relation_files():
        if rel == RELATION_MODULE:
            continue
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        # module-level and nested functions alike
        parents: Dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def enclosing(node):
            cur = parents.get(node)
            while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cur = parents.get(cur)
            return cur

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            attr, owner = node.func.attr, node.func.value
            owner_src = ast.unparse(owner)
            is_relation = owner_src.endswith("project_team") or owner_src.endswith("pt")
            is_collection = ("collection('project_team')" in ast.unparse(node.func)
                             or 'collection("project_team")' in ast.unparse(node.func))
            if is_relation and attr in ACCESSORS:
                kind, predicate = ACCESSORS[attr]
                accessor = "project_team.%s()" % attr
            elif is_collection and attr in COLLECTION_CALLS:
                kind = "WRITE" if attr in ("insert_one", "delete_many", "update_many") else "read"
                predicate = "org_id (TenantData.scoped)"
                accessor = "tenant.collection('project_team').%s()" % attr
            else:
                continue
            fn = enclosing(node)
            name = fn.name if fn else "(module)"
            state = _base_state(rel, name, base) if fn else "new@A2"
            action = "FIXED" if state == "bare@base" else (
                "SAFE" if state in ("scoped@base", "new@A2", "absent@base") else "REVIEW")
            rows.append(("%s:%s" % (rel, name), _route_of(fn) if fn else "(module)",
                         kind, accessor, predicate, state, action))
    return sorted(set(rows))


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=A1_HEAD)
    args = ap.parse_args(argv)
    rows = build(args.base)
    bare = [r for r in rows if r[5] == "bare@base"]
    print("| path:function | route | kind | accessor | tenant predicate | at base | action |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    counts = defaultdict(int)
    for r in rows:
        counts[r[2]] += 1
    print("\nTotals: %d access site(s) — %s" % (
        len(rows), ", ".join("%s %d" % kv for kv in sorted(counts.items()))))
    print("At the A1 head %s: %d site(s) reached project_team with no tenant predicate "
          "(all FIXED)." % (args.base[:7], len(bare)))
    # a bare access that survives would be an A2-TEAM guard violation, not a row here
    units, violations = g.check_protected_surface()
    print("Static guard: %d unit(s), %d violation(s)." % (units, len(violations)))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
