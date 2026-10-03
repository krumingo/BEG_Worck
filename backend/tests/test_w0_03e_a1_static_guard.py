"""
W0-03E-A1 / C01 — the static guard is effective, not cosmetic.

``scripts/w0_03e_a1_tenant_access_guard.py`` must (1) pass the corrected tree,
(2) FAIL when the exact R1 defect — ``db.projects.find_one({"id": project_id})``
— is injected into a protected module, and (3) fail on every known way around
it: an alias, a dynamic collection, ``getattr``, a pre-bound collection import,
a raw ``$lookup``/``$unionWith``/``$graphLookup``, a ``**`` spread after the
tenant key, a tenant taken from a request parameter, a hand-built
``TenantData``, an unrecognised handle, and a renamed protected function. There
is no allowlist; nothing here is satisfied by an exclusion.

Run:  pytest tests/test_w0_03e_a1_static_guard.py -v --noconftest
"""
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import w0_03e_a1_tenant_access_guard as guard  # noqa: E402

FINANCE = BACKEND / "app" / "routes" / "finance.py"
ANCHOR = "    if invoice.get(\"project_id\"):\n        p = await tenant.projects.get("


def rules(source, rel="app/routes/finance.py", **kw):
    return {v[2] for v in guard.check_source(source, rel, **kw)}


def inject(snippet):
    """The real finance.py with ``snippet`` added inside ``get_invoice``."""
    src = FINANCE.read_text(encoding="utf-8")
    assert src.count(ANCHOR) == 1
    return src.replace(ANCHOR, snippet + ANCHOR)


# ------------------------------------------------------------ the corrected tree
def test_the_whole_protected_surface_is_clean():
    units, violations = guard.check_protected_surface()
    assert violations == [], "\n".join("%s:%d %s %s" % v for v in violations)
    assert units >= 40


def test_the_script_exits_zero_on_the_corrected_tree():
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "w0_03e_a1_tenant_access_guard.py")],
                       cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 violation(s)" in r.stdout


def test_the_surface_covers_every_module_named_by_the_assignment():
    named = {"app/routes/finance.py", "app/routes/offers.py", "app/routes/reports.py",
             "app/routes/dashboard.py", "app/master_data/legacy_adapter.py",
             "app/master_data/legacy_plan.py", "app/master_data/legacy_migration.py"}
    assert named <= set(guard.PROTECTED_MODULES)
    assert "import_client_invoice" in guard.PROTECTED_FUNCTIONS["app/routes/projects.py"]
    assert "list_advances" in guard.PROTECTED_FUNCTIONS["app/routes/hr.py"]
    for coll in ("projects", "clients", "companies", "users", "warehouses", "invoices",
                 "counterparties", "persons", "finance_payments", "payment_allocations"):
        assert coll in guard.IDENTITY_COLLECTIONS


# ------------------------------------------------- the R1 defect, injected
def test_the_r1_bare_project_lookup_is_rejected():
    bad = inject('        p = await db.projects.find_one({"id": project_id})\n')
    assert "A1-IDENTITY" in rules(bad)


def test_the_script_fails_on_an_injected_unsafe_file(tmp_path):
    target = tmp_path / "finance.py"
    target.write_text(inject('        p = await db.projects.find_one({"id": project_id})\n'),
                      encoding="utf-8")
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "w0_03e_a1_tenant_access_guard.py"),
                        str(target)], cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "A1-IDENTITY db.projects.find_one" in r.stdout


def test_even_a_scoped_direct_identity_read_must_use_the_layer():
    """No bypass of the central layer, even when the raw read is correct today."""
    bad = inject('        p = await db.projects.find_one({"id": pid, "org_id": user["org_id"]})\n')
    assert "A1-IDENTITY" in rules(bad)


@pytest.mark.parametrize("snippet,rule", [
    ('        coll = db.projects\n        p = await coll.find_one({"id": pid})\n', "A1-IDENTITY"),
    ('        coll = db["projects"]\n', "A1-IDENTITY"),
    ('        p = await db[name].find_one({"id": pid})\n', "A1-UNSCOPED"),
    ('        p = await getattr(db, "projects").find_one({"id": pid})\n', "A1-DYNAMIC"),
    ('        p = await db.get_collection("projects").find_one({"id": pid})\n', "A1-DYNAMIC"),
    ('        rows = await db.invoice_lines.find({"invoice_id": pid}).to_list(9)\n', "A1-UNSCOPED"),
    ('        rows = await db.invoice_lines.find(query).to_list(9)\n', "A1-UNSCOPED"),
    ('        rows = await db.invoice_lines.find({"org_id": None}).to_list(9)\n', "A1-UNSCOPED"),
    ('        rows = await db.invoice_lines.find({"org_id": org, **extra}).to_list(9)\n', "A1-UNSCOPED"),
    ('        rows = await db.invoice_lines.aggregate([{"$sort": {"x": 1}}]).to_list(9)\n', "A1-UNSCOPED"),
    ('        st = {"$lookup": {"from": "projects", "localField": "p", "foreignField": "id", "as": "j"}}\n',
     "A1-LOOKUP"),
    ('        st = {"$unionWith": "projects"}\n', "A1-LOOKUP"),
    ('        st = {"$graphLookup": {"from": "projects"}}\n', "A1-LOOKUP"),
    ('        t = TenantData(db, user["org_id"])\n', "A1-CTOR"),
    ('        p = await other_handle.projects.find_one({"id": pid})\n', "A1-RECEIVER"),
    ('        p = await (await ctx.db())["projects"].find_one({"id": pid})\n', "A1-IDENTITY"),
    ('        p = await (await ctx.db())[name].find_one({"id": pid})\n', "A1-UNSCOPED"),
])
def test_every_known_bypass_is_rejected(snippet, rule):
    assert rule in rules(inject(snippet))


def test_a_tenant_taken_from_the_request_is_rejected():
    src = (
        "from app.db import db\n"
        "@router.get('/x/{org_id}')\n"
        "async def leak(org_id: str, user: dict = Depends(require_m5)):\n"
        "    return await db.invoice_lines.find({'org_id': org_id}).to_list(9)\n"
        "@router.get('/y')\n"
        "async def leak2(org: str, user: dict = Depends(require_m5)):\n"
        "    return TenantData.for_owner_of(db, {'org_id': org})\n")
    assert "A1-CALLERTENANT" in rules(src)
    ok = src.replace("{'org_id': org_id}", "{'org_id': user['org_id']}") \
            .replace("{'org_id': org}", "user")
    assert "A1-CALLERTENANT" not in rules(ok)


def test_a_pre_bound_collection_import_is_rejected():
    assert "A1-RAWIMPORT" in rules("from app.db import projects\n")


def test_a_renamed_protected_function_fails_instead_of_shrinking_scope():
    src = (BACKEND / "app" / "routes" / "projects.py").read_text(encoding="utf-8")
    renamed = src.replace("async def import_client_invoice(", "async def import_client_invoice_v2(")
    found = guard.check_source(renamed, "app/routes/projects.py", functions=("import_client_invoice",))
    assert [v[2] for v in found] == ["A1-SCOPE"]


def test_a_protected_function_with_a_bare_lookup_fails():
    src = (BACKEND / "app" / "routes" / "hr.py").read_text(encoding="utf-8")
    bad = src.replace('            u = await tenant.users.get(adv["user_id"]',
                      '            u = await db.users.find_one({"id": adv["user_id"]})\n'
                      '            u = await tenant.users.get(adv["user_id"]')
    assert bad != src
    found = guard.check_source(bad, "app/routes/hr.py", functions=("list_advances",))
    assert "A1-IDENTITY" in {v[2] for v in found}


def test_helper_tier_still_requires_a_literal_tenant_predicate():
    src = "async def h(org_id, name):\n    return await db.projects.find_one({'name': name})\n"
    assert "A1-UNSCOPED" in rules(src, rel="app/services/paid_labor.py", helper=True)
    ok = "async def h(org_id, name):\n    return await db.projects.find_one({'name': name, 'org_id': org_id})\n"
    assert rules(ok, rel="app/services/paid_labor.py", helper=True) == set()


def test_the_committed_inventory_is_the_generated_one():
    """docs/architecture/W0-03E-A1_INVENTORY.md is regenerated from code, never hand-edited:
    a new database access in the protected surface must appear in it (and no row is UNSCOPED)."""
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "w0_03e_a1_inventory.py")],
                       cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr
    doc = (BACKEND.parent / "docs" / "architecture" / "W0-03E-A1_INVENTORY.md").read_text(encoding="utf-8")
    assert r.stdout.strip() in doc
    assert "| BLOCKED |" not in r.stdout and "UNSCOPED" not in r.stdout
