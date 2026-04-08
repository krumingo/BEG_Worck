"""
Tests for Budget Labor Forecast module.
Run: pytest backend/tests/test_budget_labor.py -v
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
    projects = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
    return projects[0]["id"]


@pytest.fixture(scope="module")
def budget_id(auth_headers, project_id):
    """Create a test activity budget."""
    r = httpx.post(f"{API}/projects/{project_id}/activity-budgets", json={
        "type": "Довършителни",
        "subtype": "Шпакловка",
        "labor_budget": 5000,
        "materials_budget": 3000,
        "coefficient": 1.2,
        "planned_people_per_day": 3,
        "planned_target_days": 10,
    }, headers=auth_headers)
    assert r.status_code == 201
    return r.json()["id"]


# ── Test 1: Forecast calculation ──────────────────────────────────

def test_forecast(auth_headers, budget_id):
    r = httpx.get(f"{API}/activity-budgets/{budget_id}/forecast", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["labor_budget"] == 5000
    assert d["coefficient"] == 1.2
    assert d["avg_daily_wage"] > 0
    assert d["man_days"] > 0
    # man_days = 5000 / avg_daily / 1.2
    expected_md = round(5000 / d["avg_daily_wage"] / 1.2, 2)
    assert abs(d["man_days"] - expected_md) < 0.01
    assert d["min_days"] is not None  # planned_people_per_day = 3
    assert d["min_people"] is not None  # planned_target_days = 10


# ── Test 2: Avg daily wage auto-compute ───────────────────────────

def test_avg_daily_wage(auth_headers, budget_id):
    r = httpx.get(f"{API}/activity-budgets/{budget_id}/forecast", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    # Should be DEFAULT_DAILY_WAGE (200) if no team profiles, or computed from team
    assert d["avg_daily_wage"] >= 0


# ── Test 3: Burn tracking ─────────────────────────────────────────

def test_burn_tracking(auth_headers, budget_id):
    r = httpx.get(f"{API}/activity-budgets/{budget_id}/burn", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "labor_budget" in d
    assert "actual_cost" in d
    assert "actual_hours" in d
    assert "burn_pct" in d
    assert "on_track" in d
    assert d["labor_budget"] == 5000


# ── Test 4: Budget health for project ─────────────────────────────

def test_budget_health(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/budget-health", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "total_budget" in d
    assert "total_spent" in d
    assert "total_remaining" in d
    assert "burn_pct" in d
    assert "activities" in d
    assert d["total_budget"] >= 5000  # at least our test budget


# ── Test 5: Earned value calculation ──────────────────────────────

def test_earned_value(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/earned-value", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "BAC" in d
    assert "EV" in d
    assert "AC" in d
    assert "CPI" in d
    assert "SPI" in d
    assert "EAC" in d
    assert "status" in d


# ── Test 6: Edge case - no work sessions yet (burn = 0%) ──────────

def test_burn_zero(auth_headers, project_id):
    # Create budget with unique type (no work sessions match)
    r = httpx.post(f"{API}/projects/{project_id}/activity-budgets", json={
        "type": "Земни",
        "subtype": "Изкопи",
        "labor_budget": 10000,
    }, headers=auth_headers)
    bid = r.json()["id"]

    burn = httpx.get(f"{API}/activity-budgets/{bid}/burn", headers=auth_headers)
    assert burn.status_code == 200
    assert burn.json()["actual_cost"] == 0
    assert burn.json()["burn_pct"] == 0
    assert burn.json()["on_track"] is True


# ── Test 7: Warnings from budget_progress ─────────────────────────

def test_progress_warnings(auth_headers, project_id):
    r = httpx.get(f"{API}/progress-warnings/{project_id}", headers=auth_headers)
    assert r.status_code == 200
    # Should have warnings structure
    assert "warnings" in r.json()
    assert "total" in r.json()


# ── Test 8: Budget with new fields persisted ──────────────────────

def test_budget_new_fields(auth_headers, project_id):
    r = httpx.post(f"{API}/projects/{project_id}/activity-budgets", json={
        "type": "Инсталации",
        "subtype": "Електро",
        "labor_budget": 8000,
        "coefficient": 1.5,
        "planned_people_per_day": 2,
        "planned_target_days": 15,
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["coefficient"] == 1.5
    assert d["planned_people_per_day"] == 2
    assert d["planned_target_days"] == 15

    # Verify via list
    lr = httpx.get(f"{API}/projects/{project_id}/activity-budgets", headers=auth_headers)
    budgets = lr.json()["items"]
    electro = next((b for b in budgets if b["type"] == "Инсталации"), None)
    assert electro is not None
    assert electro["coefficient"] == 1.5
