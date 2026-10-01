#!/usr/bin/env python3
"""
W0-03E-A1 — machine-generated inventory of the protected read/write surface.

For every unit the static guard protects (``PROTECTED_MODULES``,
``PROTECTED_FUNCTIONS``, ``HELPER_MODULES``) this lists each database access
per function: ``path | entity | lookup key | tenant predicate | risk | action``.
``risk``/``action`` compare the same function at a base revision (default: the
A1 starting head ``2cd40a3``, read with ``git show``): a collection the base
function reached WITHOUT a literal tenant predicate is ``BARE@base`` and the A1
row is ``FIXED``; one that was already scoped is ``scoped@base`` → ``SAFE``
(migrated to the access layer where it is an identity collection). Read-only:
no import of the checked code, no database.

    python scripts/w0_03e_a1_inventory.py [--base <rev>] > inventory.md
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import w0_03e_a1_tenant_access_guard as g  # noqa: E402

LAYER_HELPERS = {"resolve_review_token": ("offers", "review_token (unique, fail-closed)"),
                 "assigned_project_ids": ("project_team→projects", "user_id → tenant projects"),
                 "is_project_member": ("project_team→projects", "project_id+user_id → tenant project"),
                 "count_ownerless": ("<legacy collection>", "org_id null/missing (no tenant data)")}


def _route_of(fn) -> str:
    for dec in fn.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args \
                and isinstance(dec.args[0], ast.Constant):
            return "%s %s" % (dec.func.attr.upper(), dec.args[0].value)
    return "(helper)"


def _key(call: ast.Call, method: str) -> str:
    if method in ("get", "require"):
        return "id = %s" % ast.unparse(call.args[0])[:40] if call.args else "id"
    if method == "get_many":
        return "id ∈ %s" % ast.unparse(call.args[0])[:40] if call.args else "id ∈ …"
    if method == "aggregate":
        return "pipeline"
    arg = call.args[0] if call.args else None
    if isinstance(arg, ast.Dict):
        keys = [ast.unparse(k) for k in arg.keys if k is not None]
        keys = [k for k in keys if k.strip("'\"") not in g.TENANT_KEYS]
        return ", ".join(k.strip("'\"") for k in keys)[:60] or "(tenant only)"
    if arg is None:
        return "(tenant only)" if method in ("find", "count", "find_one", "distinct") else "—"
    return ast.unparse(arg)[:40]


def _accesses(fn) -> List[Tuple[str, str, str, str, bool]]:
    """(collection, method, key, predicate, scoped) for each access in ``fn``."""
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in LAYER_HELPERS:
            coll, key = LAYER_HELPERS[func.id]
            out.append((coll, func.id, key, "data_access helper", True))
            continue
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr == "own_organization":
            out.append(("organizations", "own_organization", "id = tenant org_id", "TenantData", True))
            continue
        if func.attr == "lookup" and isinstance(func.value, (ast.Name, ast.Call)):
            coll = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "?"
            out.append((coll, "$lookup", "%s → id" % (ast.unparse(node.args[1]) if len(node.args) > 1
                                                       else "?"), "TenantData.lookup $filter org_id", True))
            continue
        recv = func.value
        if g._is_tenant_view(recv):
            out.append((recv.attr, func.attr, _key(node, func.attr), "TenantData org_id (session)", True))
            continue
        is_coll, name = g._collection_of(recv)
        if is_coll and func.attr in (g.FILTER_FIRST | g.FILTER_SECOND | g.PIPELINE | g.NO_FILTER):
            if func.attr in g.NO_FILTER:
                continue
            flt = g._arg(node, 1 if func.attr in g.FILTER_SECOND else 0, "filter")
            own_org = (name == "organizations" and isinstance(flt, ast.Dict) and len(flt.keys) == 1
                       and isinstance(flt.keys[0], ast.Constant) and flt.keys[0].value == "id"
                       and ast.unparse(flt.values[0]).endswith(("['org_id']", "org_id")))
            if own_org:
                out.append((name, func.attr, "id = " + ast.unparse(flt.values[0]),
                            "own org (id IS the tenant key)", True))
                continue
            if func.attr in g.PIPELINE:
                scoped = g._pipeline_scoped(g._arg(node, 0, "pipeline"))
                pred = "first $match org_id" if scoped else "NONE"
            else:
                scoped = g._dict_has_tenant(flt)
                val = g._tenant_value(flt)
                pred = ("literal %s" % ast.unparse(val)[:40]) if val is not None else (
                    "repository _scope(tenant_id)" if scoped else "NONE")
            out.append((name or "<dynamic>", func.attr, _key(node, func.attr), pred, scoped))
    return out


def _functions(tree, names: Optional[Set[str]]):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (names is None or node.name in names):
            yield node


def _base_bare(src: Optional[str], fn_name: str) -> Dict[str, bool]:
    """collection -> True when the base function read it without a tenant predicate."""
    if src is None:
        return {}
    out: Dict[str, bool] = defaultdict(bool)
    for fn in _functions(ast.parse(src), {fn_name}):
        for coll, _m, _k, _p, scoped in _accesses(fn):
            out[coll] |= not scoped
            out.setdefault(coll, False)
    return out


def _git_show(rev: str, rel: str) -> Optional[str]:
    r = subprocess.run(["git", "show", "%s:backend/%s" % (rev, rel)], cwd=BACKEND,
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def build(base: str) -> List[Tuple]:
    units = [(m, None) for m in g.PROTECTED_MODULES + g.HELPER_MODULES]
    units += [(m, set(f)) for m, f in g.PROTECTED_FUNCTIONS.items()]
    rows = []
    for rel, names in units:
        src = (BACKEND / rel).read_text(encoding="utf-8")
        base_src = _git_show(base, rel)
        for fn in _functions(ast.parse(src), names):
            base_map = _base_bare(base_src, fn.name)
            seen = set()
            for coll, method, key, pred, scoped in _accesses(fn):
                sig = (coll, method, key, pred)
                if sig in seen:
                    continue
                seen.add(sig)
                if not scoped:
                    risk, action = "UNSCOPED", "BLOCKED"
                elif base_map.get(coll):
                    risk, action = "BARE@base", "FIXED"
                elif coll in base_map:
                    risk, action = "scoped@base", "SAFE"
                else:
                    risk, action = "new read", "SAFE"
                rows.append(("%s:%s" % (rel, fn.name), _route_of(fn), coll, "%s(%s)" % (method, key),
                             pred, risk, action))
    return rows


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="2cd40a377b67beb4cc60bf211e42708e2a69f881")
    args = ap.parse_args(argv)
    rows = build(args.base)
    print("| path | route | entity (collection) | access (lookup key) | tenant predicate | risk | action |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    counts = defaultdict(int)
    for r in rows:
        counts[r[-1]] += 1
    print("\nTotals: %d accesses — %s" % (len(rows), ", ".join("%s %d" % kv for kv in sorted(counts.items()))))
    return 1 if counts.get("BLOCKED") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
