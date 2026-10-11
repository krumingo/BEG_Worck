"""
LIVE-OPS-01 / TASK 5B — static guards for the material request safe-write core.

STATIC evidence only (reported as such): it complements, never replaces, the
real-Mongo runtime suite ``test_live_ops_b_request_commands.py``.

    pytest tests/test_live_ops_b_static.py -q --noconftest
"""
import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SERVICE = "app/services/material_request_commands.py"
ROUTES = "app/routes/material_request_commands.py"
WRITE_METHODS = {"insert_one", "insert_many", "update_one", "update_many", "replace_one",
                 "delete_one", "delete_many", "find_one_and_update", "find_one_and_replace",
                 "find_one_and_delete", "bulk_write"}
#: Collections TASK 5B must never write.
FOREIGN = {"warehouse_transactions", "warehouse_batches", "material_consumption_log",
           "project_material_ops", "material_entries", "asset_units", "asset_custody",
           "asset_repairs", "asset_movements", "md_item", "md_pending_mapping", "warehouses",
           "supplier_invoices", "audit_logs"}


def _writes(rel):
    """(collection, method, line) for every write call whose target names a collection."""
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    consts = {t.id: n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)
              and isinstance(n.value.value, str)}
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in WRITE_METHODS):
            continue
        target = node.func.value
        name = None
        if isinstance(target, ast.Attribute):
            name = target.attr
        elif isinstance(target, ast.Subscript):
            s = target.slice
            if isinstance(s, ast.Constant):
                name = s.value
            elif isinstance(s, ast.Name):
                name = consts.get(s.id, s.id)
        out.append((name, node.func.attr, node.lineno))
    return out


def test_the_command_service_is_the_only_writer_of_material_requests():
    offenders = []
    for p in sorted((BACKEND / "app").rglob("*.py")):
        rel = p.relative_to(BACKEND).as_posix()
        for name, method, line in _writes(rel):
            if name == "material_requests" and rel != SERVICE:
                offenders.append("%s:%d %s" % (rel, line, method))
    assert not offenders, offenders
    assert [m for n, m, _ in _writes(SERVICE) if n == "material_requests"] == [
        "insert_one", "update_one"]


def test_request_command_modules_write_no_foreign_collection():
    for rel in (SERVICE, ROUTES):
        bad = [(n, m, l) for n, m, l in _writes(rel) if n in FOREIGN]
        assert not bad, (rel, bad)
    # the routes module writes nothing directly; everything goes through the service
    assert [w for w in _writes(ROUTES) if w[0] not in (None,)] == []


def test_only_named_command_routes_exist_for_writes():
    from app.routes import material_request_commands as r
    writes = sorted((sorted(rt.methods - {"HEAD", "OPTIONS"})[0], rt.path)
                    for rt in r.router.routes if rt.methods - {"GET", "HEAD", "OPTIONS"})
    assert writes == sorted([
        ("POST", "/material-requests"),
        ("PATCH", "/material-requests/{req_id}/draft"),
        ("POST", "/material-requests/{req_id}/submit"),
        ("POST", "/material-requests/{req_id}/approve"),
        ("POST", "/material-requests/{req_id}/reject"),
        ("POST", "/material-requests/{req_id}/cancel"),
        # retired legacy writers (410)
        ("PUT", "/material-requests/{req_id}"),
        ("DELETE", "/material-requests/{req_id}"),
        ("POST", "/material-requests/from-offer/{offer_id}"),
    ])
    from app.routes import procurement
    assert not [rt.path for rt in procurement.router.routes if "material-requests" in rt.path]


def test_request_actions_are_deny_by_default_outside_owner_admin():
    from app.permissions.catalog import CANONICAL_ROLES, LEGACY_ROLES, ACTIONS
    actions = {a for a in ACTIONS if a.startswith("material_request.")}
    assert actions == {"material_request.create", "material_request.edit_draft",
                       "material_request.submit", "material_request.approve",
                       "material_request.cancel", "material_request.cancel_approved"}
    for rid, role in {**CANONICAL_ROLES, **LEGACY_ROLES}.items():
        granted = actions & set(role["actions"])
        if rid in ("owner", "admin"):
            assert granted == actions
        else:
            assert not granted, (rid, granted)


def _functions_reading_role(rel):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    found = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            is_sub = (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                      and node.slice.value == "role")
            is_get = (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "get" and node.args
                      and isinstance(node.args[0], ast.Constant) and node.args[0].value == "role")
            if is_sub or is_get:
                found.add(fn.name)
    return found


def test_no_write_is_decided_by_a_session_role_name():
    # the command service never looks at a role name at all
    assert _functions_reading_role(SERVICE) == set()
    # the routes read it ONLY in the documented legacy READ-visibility boundary
    assert _functions_reading_role(ROUTES) == {"_legacy_visible_project_ids"}


def test_the_decider_makes_exactly_one_permission_decision():
    tree = ast.parse((BACKEND / ROUTES).read_text(encoding="utf-8"))
    decide = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "decide")
    calls = [n for n in ast.walk(decide) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "evaluate_permission"]
    assert len(calls) == 1
    assert "material_request.create" not in ast.unparse(decide)


def test_the_index_gate_keeps_no_positive_cache():
    from app.services import material_request_commands as mrc
    assert not hasattr(mrc, "_index_ok_cache")
    src = ast.unparse(next(n for n in ast.walk(ast.parse((BACKEND / SERVICE).read_text()))
                           if isinstance(n, ast.AsyncFunctionDef)
                           and n.name == "assert_required_indexes"))
    assert "cache" not in src.split('"""')[-1]
    # the bootstrap tool and the runtime gate share ONE requirement list
    boot = (BACKEND / "scripts/live_ops_b_bootstrap.py").read_text(encoding="utf-8")
    assert "REQUIRED_UNIQUE_INDEXES" in boot and "missing_required_indexes" in boot


def test_missing_required_indexes_is_exact():
    from app.services.material_request_commands import missing_required_indexes
    full = {
        "audit_events": {"a": {"unique": True, "key": [("event_id", 1)]},
                         "b": {"unique": True, "key": [("tenant_id", 1), ("sequence", 1)]}},
        "audit_idempotency": {"c": {"unique": True, "key": [("id", 1)]}},
        "material_requests": {"d": {"unique": True, "key": [("org_id", 1), ("request_number", 1)],
                                    "partialFilterExpression": {"request_number": {"$type": "string"}}}},
    }
    assert missing_required_indexes(full) == []
    for coll, name, broken in (
            ("audit_events", "b", {"unique": False, "key": [("tenant_id", 1), ("sequence", 1)]}),
            ("audit_events", "b", {"unique": True, "key": [("sequence", 1), ("tenant_id", 1)]}),
            ("material_requests", "d", {"unique": True, "key": [("org_id", 1), ("request_number", 1)],
                                        "partialFilterExpression": {"status": "draft"}})):
        bad = {k: dict(v) for k, v in full.items()}
        bad[coll] = {**bad[coll], name: broken}
        assert [m["collection"] for m in missing_required_indexes(bad)] == [coll]
    # a non-partial unique index is wider than required and is accepted
    wide = {**full, "material_requests": {"d": {"unique": True,
                                                "key": [("org_id", 1), ("request_number", 1)]}}}
    assert missing_required_indexes(wide) == []


def test_audit_store_session_is_optional_and_backward_compatible():
    import inspect
    from app.audit import store, idempotency
    for fn in (store.record_event, idempotency.begin_idempotent, idempotency.complete_idempotent):
        p = inspect.signature(fn).parameters["session"]
        assert p.default is None and p.kind == p.KEYWORD_ONLY
