"""
W0-03E-A2B / C01 — the static guard: writers, authorization scripts, scope.

Issue #38 Phase 4–6: every new protected tenant-owned record must carry the
server-resolved tenant; static/CI guards must detect a new ownerless writer
path. The guard must PASS the clean tree on Windows and POSIX and FAIL a
deliberate ownerless writer, a bare-id lookup and a tenantless authorization
mutation. This module proves each of those, plus that the ownership scope the
guard and the backfill share leaves no collection of the application
unclassified (no ASSUMED SAFE).

Run:  pytest tests/test_w0_03e_a2b_static_guard.py -v --noconftest
"""
import ast
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import w0_03e_a1_tenant_access_guard as guard  # noqa: E402

from app.tenancy import ownership as own  # noqa: E402

SCRIPT = BACKEND / "scripts" / "w0_03e_a1_tenant_access_guard.py"
ROUTE = "app/routes/projects.py"


def writer_rules(src, rel=ROUTE):
    return [(v[2], v[3]) for v in guard.check_writers(src, rel)]


def rules(src, rel=ROUTE):
    return {r for r, _ in writer_rules(src, rel)}


HEAD = '''
from fastapi import APIRouter, Depends
from app.db import db
router = APIRouter()
'''


# ------------------------------------------------------------ the clean tree
def test_the_clean_tree_passes_with_every_writer_judged():
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
    assert r.stdout.strip().endswith("0 violation(s)")
    # the writer rule really judged the tree: every module of app/ + server.py + scripts
    assert "server.py" in guard.writer_files()
    assert set(guard.WRITER_SCRIPTS) <= set(guard.writer_files())
    assert len(guard.writer_files()) > 150


def test_the_clean_tree_verdict_is_identical_for_windows_style_paths():
    """Writer and team rules key on backend-relative POSIX paths on any host."""
    for rel in ("app/routes/projects.py", "app/services/alarm_engine.py",
                "app/services/paid_labor.py", "scripts/w0_02_bootstrap_permissions.py"):
        win = str(PureWindowsPath(rel))
        _, key = guard._rel(win)
        assert key == rel
        a = subprocess.run([sys.executable, str(SCRIPT), rel], cwd=BACKEND,
                           capture_output=True, text=True)
        b = subprocess.run([sys.executable, str(SCRIPT), win], cwd=BACKEND,
                           capture_output=True, text=True)
        assert (a.returncode, a.stdout) == (b.returncode, b.stdout), rel
        # explicit-file mode applies the A1 whole-module rules too; the writer
        # and team rules alone must be clean for every one of these files
        assert "A2B-" not in a.stdout and "A2-TEAM" not in a.stdout, a.stdout
    assert all("\\" not in f for f in guard.writer_files())


def test_the_guard_needs_no_application_import():
    """Pure AST: runs with site-packages disabled (no motor, no FastAPI)."""
    r = subprocess.run([sys.executable, "-S", str(SCRIPT)], cwd=BACKEND,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1000:] + r.stdout[-1000:]


# ------------------------------------------------------------ A2B-WRITER
UNSAFE_WRITERS = {
    "literal without org_id": '''
@router.post("/x")
async def create(user: dict = Depends(get_current_user)):
    await db.invoices.insert_one({"id": "1", "total": 5})
''',
    "named doc without org_id": '''
@router.post("/x")
async def create(user: dict = Depends(get_current_user)):
    doc = {"id": "1"}
    await db.projects.insert_one(doc)
''',
    "subscript collection": '''
async def helper(org_id):
    await db["finance_payments"].insert_one({"id": "1"})
''',
    "insert_many of unproven list": '''
async def helper(rows):
    await db.payment_allocations.insert_many(rows)
''',
    "upsert without owner": '''
async def helper(key):
    await db.settings.update_one({"_id": key}, {"$set": {"v": 1}}, upsert=True)
''',
    "replace without owner": '''
async def helper(doc_id, data):
    await db.offers.replace_one({"id": doc_id}, {"id": doc_id, **data})
''',
    "pre-bound collection import": '''
from app.db import invoices
async def helper():
    await invoices.insert_one({"id": "1"})
''',
    "project_team via raw handle": '''
async def helper():
    await db.project_team.insert_one({"id": "1", "project_id": "p", "user_id": "u"})
''',
}


@pytest.mark.parametrize("name", sorted(UNSAFE_WRITERS))
def test_an_ownerless_writer_fails_the_guard(name):
    found = rules(HEAD + UNSAFE_WRITERS[name])
    assert "A2B-WRITER" in found, (name, found)


SAFE_WRITERS = {
    "literal": '''
@router.post("/x")
async def create(user: dict = Depends(get_current_user)):
    await db.invoices.insert_one({"id": "1", "org_id": user["org_id"]})
''',
    "named + subscript stamp": '''
async def helper(org_id, data):
    doc = dict(data)
    doc["org_id"] = org_id
    await db.projects.insert_one(doc)
''',
    "spread first, owner last": '''
async def helper(org_id, ev):
    await db.alarm_events.insert_one({**ev, "org_id": org_id})
''',
    "appended list": '''
async def helper(org_id, items):
    rows = []
    for i in items:
        rows.append({"id": i, "org_id": org_id})
    await db.planned_materials.insert_many(rows)
''',
    "comprehension": '''
async def helper(org_id, items):
    await db.planned_materials.insert_many([{"id": i, "org_id": org_id} for i in items])
''',
    "upsert with owner in filter": '''
async def helper(org_id):
    await db.org_counters.find_one_and_update({"org_id": org_id, "k": 1}, {"$inc": {"v": 1}}, upsert=True)
''',
    "factory": '''
async def helper(org_id):
    def _doc():
        return {"id": "1", "org_id": org_id}
    doc = _doc()
    await db.users.insert_one(doc)
''',
    "tenant view stamps itself": '''
async def helper(tenant):
    await tenant.invoices.insert_one({"id": "1"})
''',
}


@pytest.mark.parametrize("name", sorted(SAFE_WRITERS))
def test_a_proven_writer_passes(name):
    assert writer_rules(HEAD + SAFE_WRITERS[name]) == [], name


def test_a_spread_after_the_owner_can_override_it():
    src = HEAD + '''
@router.post("/x")
async def create(data: dict, user: dict = Depends(get_current_user)):
    await db.offers.insert_one({"id": "1", "org_id": user["org_id"], **data})
'''
    assert "A2B-OVERRIDE" in rules(src)


def test_an_owner_read_from_the_request_is_an_override():
    src = HEAD + '''
@router.post("/x/{org_id}")
async def create(org_id: str, user: dict = Depends(get_current_user)):
    await db.clients.insert_one({"id": "1", "org_id": org_id})
'''
    assert "A2B-OVERRIDE" in rules(src)
    body = HEAD + '''
@router.post("/x")
async def create(data: dict, user: dict = Depends(get_current_user)):
    doc = {"id": "1"}
    doc["org_id"] = data["org_id"]
    await db.clients.insert_one(doc)
'''
    assert "A2B-OVERRIDE" in rules(body)


def test_an_alias_of_a_tenant_owned_collection_is_refused():
    src = HEAD + '''
async def helper(org_id):
    coll = db.warehouse_batches
    await coll.insert_one({"id": "1"})
'''
    assert "A2B-ALIAS" in rules(src)


def test_an_injected_ownerless_writer_fails_the_real_script(tmp_path):
    """End to end through the CLI on a copy of a real route module."""
    src = (BACKEND / "app/routes/sales.py").read_text(encoding="utf-8")
    src += '''

@router.post("/sales/__injected__")
async def injected(user: dict = Depends(get_current_user)):
    await db.sales.insert_one({"id": "x", "total": 1})
'''
    target = BACKEND / "app" / "routes" / "_w0_03e_a2b_injected_tmp.py"
    target.write_text(src, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(SCRIPT)], cwd=BACKEND,
                           capture_output=True, text=True)
    finally:
        target.unlink()
    assert r.returncode == 1, r.stdout[-1500:]
    assert "_w0_03e_a2b_injected_tmp.py" in r.stdout and "A2B-WRITER" in r.stdout
    clean = subprocess.run([sys.executable, str(SCRIPT)], cwd=BACKEND,
                           capture_output=True, text=True)
    assert clean.returncode == 0


# ------------------------------------------------------------ bare id + authorization
def test_a_bare_id_lookup_still_fails_the_guard():
    src = '''
from app.db import db
async def get_invoice(invoice_id):
    return await db.invoices.find_one({"id": invoice_id})
'''
    found = {v[2] for v in guard.check_source(src, "app/routes/finance.py")}
    assert "A1-IDENTITY" in found


def test_a_tenantless_authorization_mutation_fails_the_guard():
    for src in ('''
async def add(pid, uid):
    await db.project_team.insert_one({"project_id": pid, "user_id": uid})
''', '''
async def add(pid, uid):
    await db["project_team"].update_one({"project_id": pid}, {"$set": {"active": True}})
'''):
        assert {v[2] for v in guard.check_team_relation(src, "app/routes/hr.py")} == {"A2-TEAM"}


def test_the_w0_02_bootstrap_is_under_the_team_rule():
    rel = "scripts/w0_02_bootstrap_permissions.py"
    assert rel in guard.AUTHZ_SCRIPTS
    clean = (BACKEND / rel).read_text(encoding="utf-8")
    assert guard.check_team_relation(clean, rel) == []
    unsafe = clean + '''

async def _bare():
    return await op_db.project_team.find({"active": True}).to_list(None)
'''
    assert {v[2] for v in guard.check_team_relation(unsafe, rel)} == {"A2-TEAM"}


# ------------------------------------------------------------ the shared scope
_DB_API = frozenset({
    "list_collection_names", "list_collections", "command", "client", "name",
    "get_collection", "create_collection", "drop_collection", "collection", "entity",
    "own_organization", "scoped", "lookup", "get", "org_id", "db", "lower",
})


def _named_collections():
    """Every collection name the application code reaches, by AST."""
    names = {}
    for path in sorted((BACKEND / "app").rglob("*.py")) + [BACKEND / "server.py"]:
        rel = path.relative_to(BACKEND).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = guard._module_constants(tree)
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Attribute) and guard._is_writer_db(node.value):
                name = node.attr
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "tenant":
                name = node.attr
            elif isinstance(node, ast.Subscript) and guard._is_writer_db(node.value):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    name = key.value
                elif isinstance(key, ast.Name):
                    name = consts.get(key.id)
            if name and name not in _DB_API and not name.startswith("_"):
                names.setdefault(name, rel)
        for local, coll in guard._prebound(tree).items():
            if coll not in _DB_API:
                names.setdefault(coll, rel)
    return names


def test_every_collection_the_application_names_is_classified():
    named = _named_collections()
    assert len(named) > 100
    unclassified = {n: rel for n, rel in named.items()
                    if own.classify_collection(n) == own.CLASS_UNCLASSIFIED}
    # system-database collections are the W0-01 control plane, not tenant data
    control_plane = {"tenant_registry", "tenant_memberships", "tenant_role_assignments",
                     "migration_journal", "tenant_migration_runs", "tenant_migration_locks"}
    unclassified = {n: r for n, r in unclassified.items() if n not in control_plane}
    assert unclassified == {}, "classify these in app/tenancy/ownership.py: %s" % unclassified


def test_the_issue_38_minimum_families_are_covered():
    need = {
        own.FAMILY_PROJECTS: {"projects", "project_team"},
        own.FAMILY_PEOPLE: {"users", "persons", "employee_profiles"},
        own.FAMILY_PARTIES: {"companies", "clients", "counterparties", "subcontractors"},
        own.FAMILY_COMMERCIAL: {"offers", "invoices", "invoice_lines", "client_acts"},
        own.FAMILY_PAYMENTS: {"finance_payments", "payment_allocations", "advances"},
        own.FAMILY_WAREHOUSE: {"warehouses", "location_nodes"},
        own.FAMILY_MATERIALS: {"items", "material_requests"},
        own.FAMILY_WORK: {"work_types", "smr_groups"},
        own.FAMILY_ASSETS: {"asset_item_types", "asset_items", "asset_units"},
        own.FAMILY_TASKS: {"worker_calendar"},
        own.FAMILY_FILES: {"media_files", "scan_docs"},
        own.FAMILY_AUDIT: {"audit_logs"},
    }
    for family, colls in need.items():
        for c in colls:
            assert own.ORG_KEYED.get(c) == family, (c, family)
    assert own.classify_collection("md_person") == own.CLASS_TENANT_ID
    assert own.classify_collection("audit_events") == own.CLASS_TENANT_ID
    assert own.classify_collection("organizations") == own.CLASS_ROOT
    assert own.classify_collection("never_heard_of_it") == own.CLASS_UNCLASSIFIED


@pytest.mark.parametrize("doc,coll,state", [
    ({"org_id": "A"}, "invoices", own.OWNER_BOUND),
    ({}, "invoices", own.OWNER_OWNERLESS),
    ({"org_id": None}, "invoices", own.OWNER_OWNERLESS),
    ({"org_id": ""}, "invoices", own.OWNER_OWNERLESS),
    ({"org_id": "B"}, "invoices", own.OWNER_CONFLICT),
    ({"org_id": 7}, "invoices", own.OWNER_CONFLICT),
    ({"org_id": "  "}, "invoices", own.OWNER_CONFLICT),
    ({"tenant_id": "B"}, "invoices", own.OWNER_CONFLICT),
    ({"org_id": "A", "tenant_id": "B"}, "invoices", own.OWNER_CONFLICT),
    ({"org_id": "A", "tenant_id": "A"}, "invoices", own.OWNER_BOUND),
    ({"tenant_id": "A"}, "invoices", own.OWNER_OWNERLESS),
    ({"org_id": "P"}, "users", own.OWNER_PLATFORM),
    ({"org_id": "P"}, "invoices", own.OWNER_CONFLICT),
    ({"tenant_id": "A"}, "md_person", own.OWNER_BOUND),
    ({}, "md_person", own.OWNER_OWNERLESS),
])
def test_owner_state(doc, coll, state):
    assert own.owner_state(doc, coll, tenant_ids=["A"], platform_owners=["P"]) == state


def test_the_committed_inventory_matches_the_code():
    """§1 (scope + writer paths) and §3 (residual debt) are generated from the
    code; the committed document must not drift from it."""
    import w0_03e_a2b_inventory as inv
    committed = inv.DOC.read_text(encoding="utf-8")
    fresh = inv.build(None)

    def sections(text, *names):
        out = {}
        for name in names:
            start = text.index(name)
            nxt = text.find("\n## ", start + 1)
            out[name] = text[start:nxt if nxt != -1 else len(text)]
        return out
    names = ("## 1. Protected ownership scope", "## 3. Residual debt")
    assert sections(committed, *names) == sections(fresh, *names), (
        "regenerate: python scripts/w0_03e_a2b_inventory.py --report <gate evidence>")
