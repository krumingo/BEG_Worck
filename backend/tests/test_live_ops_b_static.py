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


def test_the_service_never_reads_role_from_the_jwt_user():
    for rel in (SERVICE, ROUTES):
        src = (BACKEND / rel).read_text(encoding="utf-8")
        assert 'user["role"]' not in src and "user.get(\"role\")" not in src, rel


def test_audit_store_session_is_optional_and_backward_compatible():
    import inspect
    from app.audit import store, idempotency
    for fn in (store.record_event, idempotency.begin_idempotent, idempotency.complete_idempotent):
        p = inspect.signature(fn).parameters["session"]
        assert p.default is None and p.kind == p.KEYWORD_ONLY
