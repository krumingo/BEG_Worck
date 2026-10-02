"""
W0-03E-A2C — the whole-active-backend tenant boundary guard must be EFFECTIVE.

Two halves, and the second is the one that matters. A guard that reports a clean
tree proves nothing on its own: the W0-03E-A2B review found
``app/routes/invoice_lines.py`` with 37 violations while the A1 guard reported
"403 units, 0 violations", because that module was not in its hand-written scope.
So this file proves:

1. the real tree is clean, and the guard actually LOOKED at the whole active
   backend — every ``app/**/*.py``, ``server.py`` and every declared operator
   script — with ``app/routes/invoice_lines.py`` named explicitly, since that is
   the module whose omission caused this task;
2. every rule REJECTS a deliberately unsafe mutation, including mutations
   injected into the real modules rather than only into synthetic snippets;
3. the narrow exemption tiers cannot rot or be widened in silence;
4. results are identical for Windows and POSIX path spellings.

Pure AST and pure path handling: no database, no application import, so this
file is runnable anywhere the repository is checked out.
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import w0_03e_a2c_tenant_boundary_guard as guard  # noqa: E402


# ════════════════════════════════════════════════════════ 1. the real tree
def test_the_whole_active_backend_is_clean():
    units, violations = guard.check_active_backend()
    assert violations == [], "\n".join("%s:%d: %s %s" % v for v in violations)
    assert units > 150, units


def test_the_guard_actually_covers_the_whole_active_backend():
    """Scope is derived from the filesystem, not from a hand-written list."""
    covered = set(guard.active_backend_files())
    on_disk = {p.relative_to(BACKEND).as_posix() for p in (BACKEND / "app").rglob("*.py")}
    missing = on_disk - covered
    assert missing == set(), "application modules outside the guard: %s" % sorted(missing)
    assert "server.py" in covered
    # The module whose omission from the A1 scope caused W0-03E-A2C.
    assert "app/routes/invoice_lines.py" in covered


def test_every_route_module_is_covered():
    routes = {p.relative_to(BACKEND).as_posix() for p in (BACKEND / "app" / "routes").glob("*.py")}
    assert routes, "no route modules found"
    assert routes <= set(guard.active_backend_files())


# ═══════════════════════════════════════════ 2. deliberate unsafe mutations
#: (rule, source) — each snippet is judged as a route module, which is the tier
#: with no relaxation at all.
UNSAFE = [
    # A bare business id on a tenant-owned collection: the Issue #41 §2 read.
    ("A2C-READ", '''
async def totals(invoice_id, user=Depends(x)):
    return await db.invoice_lines.find_one({"id": invoice_id})
'''),
    # An unscoped aggregate.
    ("A2C-READ", '''
async def rollup(user=Depends(x)):
    return await db.invoice_lines.aggregate([{"$group": {"_id": "$invoice_id"}}]).to_list(10)
'''),
    # A tenantless write FILTER after a scoped read: the Issue #41 §3 defect,
    # exactly as `update_invoice_line` had it.
    ("A2C-WRITE", '''
async def edit(line_id, user=Depends(x)):
    line = await db.invoice_lines.find_one({"id": line_id, "org_id": user["org_id"]})
    await db.invoice_lines.update_one({"id": line_id}, {"$set": {"qty": 1}})
'''),
    ("A2C-WRITE", '''
async def wipe(line_id, user=Depends(x)):
    await db.invoice_lines.delete_one({"id": line_id})
'''),
    # An identity collection raw, even WITH a hand-written predicate.
    ("A2C-IDENTITY", '''
async def enrich(pid, user=Depends(x)):
    return await db.projects.find_one({"id": pid, "org_id": user["org_id"]})
'''),
    # A globally colliding settings identity.
    ("A2C-SETTINGS", '''
async def save(user=Depends(x)):
    await db.settings.update_one({"_id": "worker_rates", "org_id": user["org_id"]},
                                {"$set": {"rates": {}}}, upsert=True)
'''),
    # An id-only join: the enrichment leak on the FOREIGN side.
    ("A2C-LOOKUP", '''
async def summary(user=Depends(x)):
    return await db.asset_units.aggregate([
        {"$match": {"org_id": user["org_id"]}},
        {"$lookup": {"from": "asset_items", "localField": "item_id",
                     "foreignField": "id", "as": "item"}},
    ]).to_list(10)
'''),
    # A collection bound to a name, which hides its filter.
    ("A2C-DYNAMIC", '''
async def hidden(user=Depends(x)):
    coll = db.invoice_lines
    return await coll.find({}).to_list(10)
'''),
    ("A2C-DYNAMIC", '''
async def dynamic(name, user=Depends(x)):
    return await getattr(db, name).find({}).to_list(10)
'''),
    # The tenant read from the REQUEST.
    ("A2C-CALLERTENANT", '''
@router.get("/x")
async def listing(org_id: str, user=Depends(x)):
    return await db.invoice_lines.find({"org_id": org_id}).to_list(10)
'''),
    ("A2C-CTOR", '''
async def build(user=Depends(x)):
    return TenantData(db, user["org_id"])
'''),
    ("A2C-RAWIMPORT", '''
from app.db import invoices
'''),
    # A collection app.tenancy.ownership does not classify: fail closed.
    ("A2C-UNCLASSIFIED", '''
async def novel(user=Depends(x)):
    return await db.brand_new_collection.find_one({"org_id": user["org_id"]})
'''),
]


@pytest.mark.parametrize("rule,source", UNSAFE, ids=[f"{r}-{i}" for i, (r, _) in enumerate(UNSAFE)])
def test_an_unsafe_snippet_is_rejected(rule, source):
    found = guard.check_source(source, "app/routes/pretend.py")
    rules = {v[2] for v in found}
    assert rule in rules, "expected %s, got %s for:%s" % (rule, sorted(rules) or "nothing", source)


def test_the_safe_form_of_each_pattern_passes():
    """The guard rejects the unsafe shape, not the operation."""
    safe = '''
async def totals(invoice_id, user=Depends(x)):
    tenant = _tenant(user)
    line = await tenant.invoice_lines.get(invoice_id)
    await tenant.invoice_lines.update_one({"id": invoice_id}, {"$set": {"qty": 1}})
    await tenant.invoice_lines.delete_one({"id": invoice_id})
    project = await tenant.projects.get("p1")
    await tenant.settings.update_one({"_id": settings_id(WORKER_RATES, tenant.org_id)},
                                     {"$set": {"rates": {}}}, upsert=True)
    rows = await tenant.asset_units.aggregate([
        *tenant.lookup("asset_items", "item_id", "item"),
    ]).to_list(10)
    return line, project, rows
'''
    assert guard.check_source(safe, "app/routes/pretend.py") == []


# ───────────────────────────── mutations injected into the REAL modules
#: (module, safe text present today, unsafe replacement, expected rule). These
#: edit real application code, so they prove the guard's verdict on the shipped
#: tree rather than on a snippet.
REAL_MUTATIONS = [
    ("app/routes/invoice_lines.py",
     "invoice = await tenant.invoices.get(invoice_id)",
     'invoice = await db.invoices.find_one({"id": invoice_id})',
     "A2C-IDENTITY"),
    ("app/routes/invoice_lines.py",
     'await tenant.invoice_lines.update_one({"id": line_id}, {"$set": {\n        **update,',
     'await db.invoice_lines.update_one({"id": line_id}, {"$set": {\n        **update,',
     "A2C-WRITE"),
    ("app/routes/warehouses.py",
     '*tenant.lookup("asset_items", "item_id", "item"),',
     '{"$lookup": {"from": "asset_items", "localField": "item_id",\n                     "foreignField": "id", "as": "item"}},',
     "A2C-LOOKUP"),
    # The write's _id reverted to the global literal the A2B review found.
    ("app/routes/full_cost.py",
     '{"_id": row_id},',
     '{"_id": "employee_cost_config"},',
     "A2C-SETTINGS"),
    # ...and the same identity hidden behind a local name is still caught.
    ("app/routes/full_cost.py",
     'row_id = settings_id(EMPLOYEE_COST_CONFIG, tenant.org_id)',
     'row_id = "employee_cost_config"',
     "A2C-SETTINGS"),
]


@pytest.mark.parametrize("rel,safe,unsafe,rule", REAL_MUTATIONS,
                         ids=[f"{m[0].split('/')[-1]}-{m[3]}" for m in REAL_MUTATIONS])
def test_a_mutation_of_a_real_module_is_rejected(rel, safe, unsafe, rule):
    original = (BACKEND / rel).read_text(encoding="utf-8")
    assert guard.check_source(original, rel) == [], "%s is not clean to begin with" % rel
    assert original.count(safe) >= 1, "anchor missing in %s: %r" % (rel, safe[:60])
    mutated = original.replace(safe, unsafe, 1)
    assert mutated != original
    found = guard.check_source(mutated, rel)
    assert rule in {v[2] for v in found}, (
        "the guard accepted an unsafe mutation of %s; got %s" % (rel, sorted({v[2] for v in found})))


def test_the_settings_id_fix_is_what_closes_the_collision():
    """Reverting the settings identity to a global literal is rejected everywhere."""
    for rel in ("app/routes/extra_works.py", "app/routes/full_cost.py",
                "app/routes/labor_smr.py", "app/routes/work_sessions.py"):
        src = (BACKEND / rel).read_text(encoding="utf-8")
        assert "settings_id(" in src, "%s no longer derives its settings _id" % rel


# ══════════════════════════════════════════ 3. the tiers cannot rot silently
def test_every_exempted_module_exists():
    for rel in (guard.TENANCY_CORE + guard.OPERATOR_SCRIPTS + guard.TENANT_DB_SCOPED):
        assert (BACKEND / rel).is_file(), "exempted module no longer exists: %s" % rel


def test_every_declared_pre_tenant_function_still_exists():
    """A renamed function must FAIL the guard, not shrink its scope."""
    for rel in list(guard.PRE_TENANT_FUNCTIONS) + list(guard.READ_ONLY_DIAGNOSTIC):
        assert (BACKEND / rel).is_file(), rel
        assert guard.check_module(rel) == [], rel
    # and a renamed one is caught
    rel = "app/routes/auth.py"
    src = (BACKEND / rel).read_text(encoding="utf-8")
    renamed = src.replace("async def login(", "async def signin(", 1)
    assert renamed != src
    rules = {v[2] for v in guard.check_source(renamed, rel)}
    assert "A2C-SCOPE" in rules, rules


def test_a_pre_tenant_function_may_not_reach_a_business_collection():
    """The exemption is per collection, not a blanket pass for the function."""
    src = '''
async def login(req):
    user = await db.users.find_one({"email": req.email})
    rows = await db.invoice_lines.find({}).to_list(10)
    return user, rows
'''
    rules = {v[2] for v in guard.check_source(src, "app/routes/auth.py")}
    assert "A2C-READ" in rules, rules


def test_a_per_tenant_database_module_may_not_take_the_shared_handle():
    """The TENANT_DB_SCOPED exemption is proven, not trusted."""
    rel = guard.TENANT_DB_SCOPED[0]
    src = (BACKEND / rel).read_text(encoding="utf-8")
    assert guard.check_source(src, rel) == []
    rules = {v[2] for v in guard.check_source("from app.db import db\n" + src, rel)}
    assert "A2C-SHAREDDB" in rules, rules


def test_a_read_only_diagnostic_may_not_write():
    src = '''
async def smoke_test():
    n = await db.users.count_documents({})
    await db.invoices.update_one({"id": "x"}, {"$set": {"total": 0}})
    return n
'''
    rules = {v[2] for v in guard.check_source(src, "scripts/smoke_test.py")}
    assert "A2C-DIAGNOSTIC" in rules, rules


def test_the_tiers_stay_small():
    """A growing exemption list is the failure mode; keep it visible and bounded."""
    assert len(guard.TENANCY_CORE) <= 10, guard.TENANCY_CORE
    assert len(guard.TENANT_DB_SCOPED) <= 16, guard.TENANT_DB_SCOPED
    assert len(guard.PRE_TENANT_FUNCTIONS) <= 10, sorted(guard.PRE_TENANT_FUNCTIONS)
    assert len(guard.READ_ONLY_DIAGNOSTIC) <= 5, sorted(guard.READ_ONLY_DIAGNOSTIC)


# ═════════════════════════════════════════════ 4. Windows / POSIX portability
def test_windows_and_posix_spellings_agree():
    rel = "app/routes/invoice_lines.py"
    posix = guard.check_files([rel])
    windows = guard.check_files([rel.replace("/", "\\")])
    absolute = guard.check_files([str(BACKEND / rel)])
    assert posix == windows == absolute == []


def test_reported_paths_are_always_posix():
    src = 'async def f(user=Depends(x)):\n    return await db.invoice_lines.find_one({"id": 1})\n'
    for spelling in ("app/routes/pretend.py", "app\\routes\\pretend.py"):
        found = guard.check_source(src, spelling)
        assert found, spelling
    units = guard.active_backend_files()
    assert all("\\" not in u for u in units)


def test_scope_listing_is_stable_and_sorted():
    first = guard.active_backend_files()
    assert first == sorted(first)
    assert first == guard.active_backend_files()
