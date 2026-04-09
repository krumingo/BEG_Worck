"""
Tests for Price Modifiers module.
Run: pytest backend/tests/test_price_modifiers.py -v
"""
import pytest
import httpx
from pathlib import Path

BASE_URL = ""
fe_env = Path(__file__).parent.parent.parent / "frontend" / ".env"
if fe_env.exists():
    for line in fe_env.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

API = f"{BASE_URL}/api"
EMAIL = "admin@begwork.com"
PASSWORD = "AdminTest123!Secure"


@pytest.fixture(scope="module")
def auth_headers():
    r = httpx.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def project_id(auth_headers):
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    projects = r.json() if isinstance(r.json(), list) else r.json()
    return projects[0]["id"]


# ── Test 1: Org default CRUD ──────────────────────────────────────

def test_org_default_get(auth_headers):
    r = httpx.get(f"{API}/price-modifiers/org", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "modifiers" in d or "is_default" in d


def test_org_default_update(auth_headers):
    r = httpx.put(f"{API}/price-modifiers/org", json={
        "modifiers": {"waste_pct": 12, "profit_pct": 25},
        "auto_rules": {"floor_per_floor_pct": 2.0},
    }, headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["modifiers"]["waste_pct"] == 12
    assert d["modifiers"]["profit_pct"] == 25
    assert d["auto_rules"]["floor_per_floor_pct"] == 2.0


# ── Test 2: Project override ──────────────────────────────────────

def test_project_override(auth_headers, project_id):
    r = httpx.put(f"{API}/price-modifiers/project/{project_id}", json={
        "modifiers": {"center_pct": 5, "overhead_pct": 18},
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["modifiers"]["center_pct"] == 5

    # Read back
    r2 = httpx.get(f"{API}/price-modifiers/project/{project_id}", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["modifiers"]["center_pct"] == 5


# ── Test 3: Effective modifiers (merged) ───────────────────────────

def test_effective_merged(auth_headers, project_id):
    r = httpx.get(f"{API}/price-modifiers/effective/{project_id}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    mods = d["modifiers"]
    # Should have org defaults merged with project overrides
    assert mods["waste_pct"] == 12  # from org
    assert mods["center_pct"] == 5  # from project
    assert mods["overhead_pct"] == 18  # from project
    assert mods["profit_pct"] == 25  # from org


# ── Test 4: Auto floor calculation ────────────────────────────────

def test_auto_floor(auth_headers, project_id):
    # Set floors on the project
    httpx.put(f"{API}/projects/{project_id}", json={
        "object_details": {"floors_count": 5, "is_inhabited": False},
    }, headers=auth_headers)

    r = httpx.get(f"{API}/price-modifiers/effective/{project_id}", headers=auth_headers)
    mods = r.json()["modifiers"]
    # floor_pct = (5 - 2) × 2.0 (from org auto_rules) = 6.0
    assert mods["floor_pct"] == 6.0


# ── Test 5: Auto inhabited calculation ─────────────────────────────

def test_auto_inhabited(auth_headers, project_id):
    httpx.put(f"{API}/projects/{project_id}", json={
        "object_details": {"floors_count": 5, "is_inhabited": True},
    }, headers=auth_headers)

    r = httpx.get(f"{API}/price-modifiers/effective/{project_id}", headers=auth_headers)
    mods = r.json()["modifiers"]
    assert mods["inhabited_pct"] == 10  # default inhabited_value


# ── Test 6: Calculate endpoint (full breakdown) ────────────────────

def test_calculate_breakdown(auth_headers, project_id):
    r = httpx.post(f"{API}/price-modifiers/calculate", json={
        "base_cost": 100,
        "project_id": project_id,
    }, headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["base_cost"] == 100
    assert d["final_price"] > 100  # modifiers add to price
    assert len(d["breakdown"]) >= 2  # at least base + some modifiers
    assert d["total_markup_pct"] > 0

    # Verify step-by-step
    steps = d["breakdown"]
    assert steps[0]["label"] == "Себестойност"
    assert steps[0]["value"] == 100


# ── Test 7: Integration with SMR Analysis recalculate ──────────────

def test_recalculate_with_modifiers(auth_headers, project_id):
    # Create analysis with a line
    a = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id, "name": "Modifiers Integration Test",
    }, headers=auth_headers).json()
    aid = a["id"]
    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Шпакловка", "qty": 50, "labor_price_per_unit": 8,
    }, headers=auth_headers)

    # Recalculate with modifiers
    r = httpx.post(f"{API}/smr-analyses/{aid}/recalculate-with-modifiers", headers=auth_headers)
    assert r.status_code == 200
    ln = r.json()["lines"][0]
    assert ln["final_price_per_unit"] > 8  # modifiers applied
    assert "modifiers_applied" in ln


# ── Test 8: Line-level breakdown ───────────────────────────────────

def test_line_breakdown(auth_headers, project_id):
    # Use the analysis from test 7
    analyses = httpx.get(f"{API}/smr-analyses?project_id={project_id}", headers=auth_headers).json()["items"]
    mod_analysis = next((a for a in analyses if "Modifiers" in a.get("name", "")), None)
    if not mod_analysis:
        pytest.skip("No modifiers analysis")

    aid = mod_analysis["id"]
    line_id = mod_analysis["lines"][0]["line_id"]

    r = httpx.get(f"{API}/smr-analyses/{aid}/lines/{line_id}/modifier-breakdown", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "breakdown" in d
    assert d["base_cost"] >= 0
    assert d["final_price"] >= d["base_cost"]
    assert d["smr_type"] == "Шпакловка"


# ── Test 9: Delete project override ────────────────────────────────

def test_delete_project_override(auth_headers, project_id):
    r = httpx.delete(f"{API}/price-modifiers/project/{project_id}", headers=auth_headers)
    assert r.status_code == 200

    # Effective should fall back to org defaults
    r2 = httpx.get(f"{API}/price-modifiers/effective/{project_id}", headers=auth_headers)
    mods = r2.json()["modifiers"]
    # center_pct should be back to org default (0 since we only set waste and profit)
    assert mods["center_pct"] == 0
