"""
Tests for Activity Budgets endpoints.
"""
import pytest
import httpx
import os


# Get base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')


def get_auth_token():
    """Get auth token via login."""
    from tests.test_utils import VALID_ADMIN_PASSWORD
    response = httpx.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
    )
    return response.json().get("token")


def get_test_project_id(headers):
    """Get first available project ID."""
    response = httpx.get(f"{BASE_URL}/api/my-sites", headers=headers)
    items = response.json().get("items", [])
    if items:
        return items[0]["id"]
    # Create a project if none exists
    response = httpx.post(
        f"{BASE_URL}/api/projects",
        headers=headers,
        json={"code": "TEST-001", "name": "Test Project", "status": "Active"}
    )
    return response.json().get("id")


def test_activity_types_endpoint(ensure_seed_data, base_url):
    """Test GET /api/activity-types returns list of types."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = httpx.get(f"{base_url}/api/activity-types", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "types" in data
    assert "Общо" in data["types"]
    assert "Бетон" in data["types"]
    assert len(data["types"]) >= 10


def test_upsert_activity_budget_create(ensure_seed_data, base_url):
    """Test creating a new activity budget."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    project_id = get_test_project_id(headers)
    
    response = httpx.post(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers,
        json={
            "type": "Земни",
            "subtype": "Изкоп",
            "labor_budget": 3000,
            "materials_budget": 1000,
            "notes": "Test budget"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "Земни"
    assert data["subtype"] == "Изкоп"
    assert data["labor_budget"] == 3000
    assert data["materials_budget"] == 1000
    assert "id" in data


def test_upsert_activity_budget_update(ensure_seed_data, base_url):
    """Test updating an existing activity budget (upsert)."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    project_id = get_test_project_id(headers)
    
    # First create
    response1 = httpx.post(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers,
        json={
            "type": "Кофраж",
            "subtype": "",
            "labor_budget": 5000,
            "materials_budget": 2000,
        }
    )
    assert response1.status_code == 201
    original_id = response1.json()["id"]
    
    # Then update via same upsert endpoint
    response2 = httpx.post(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers,
        json={
            "type": "Кофраж",
            "subtype": "",
            "labor_budget": 7000,
            "materials_budget": 3000,
        }
    )
    assert response2.status_code == 201
    data = response2.json()
    
    # Should have updated the same record (same ID)
    assert data["id"] == original_id
    assert data["labor_budget"] == 7000
    assert data["materials_budget"] == 3000


def test_list_activity_budgets(ensure_seed_data, base_url):
    """Test listing activity budgets for a project."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    project_id = get_test_project_id(headers)
    
    # Create a budget first
    httpx.post(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers,
        json={"type": "Арматура", "subtype": "", "labor_budget": 4000, "materials_budget": 6000}
    )
    
    response = httpx.get(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) >= 1


def test_activity_budget_summary(ensure_seed_data, base_url):
    """Test the budget summary endpoint returns correct structure."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    project_id = get_test_project_id(headers)
    
    # Create a budget
    httpx.post(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers,
        json={"type": "Бетон", "subtype": "Плоча", "labor_budget": 10000, "materials_budget": 15000}
    )
    
    response = httpx.get(
        f"{base_url}/api/projects/{project_id}/activity-budget-summary",
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    
    # Check structure
    assert "items" in data
    assert "totals" in data
    
    # Check totals structure
    totals = data["totals"]
    assert "labor_budget" in totals
    assert "materials_budget" in totals
    assert "labor_spent" in totals
    assert "materials_spent" in totals
    assert "labor_remaining" in totals
    assert "materials_remaining" in totals
    assert "percent_labor_used" in totals
    assert "percent_materials_used" in totals


def test_delete_activity_budget(ensure_seed_data, base_url):
    """Test deleting an activity budget."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    project_id = get_test_project_id(headers)
    
    # Create
    response1 = httpx.post(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers,
        json={"type": "Зидария", "subtype": "Тухли", "labor_budget": 2000, "materials_budget": 5000}
    )
    budget_id = response1.json()["id"]
    
    # Delete
    response2 = httpx.delete(
        f"{base_url}/api/projects/{project_id}/activity-budgets/{budget_id}",
        headers=headers
    )
    assert response2.status_code == 200
    assert response2.json()["ok"] == True


def test_budget_remaining_calculation(ensure_seed_data, base_url):
    """Test that remaining = budget - spent."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    project_id = get_test_project_id(headers)
    
    # Create a budget with known values
    httpx.post(
        f"{base_url}/api/projects/{project_id}/activity-budgets",
        headers=headers,
        json={"type": "Изолации", "subtype": "", "labor_budget": 8000, "materials_budget": 12000}
    )
    
    response = httpx.get(
        f"{base_url}/api/projects/{project_id}/activity-budget-summary",
        headers=headers
    )
    data = response.json()
    
    # Find our budget
    iso_budget = next((i for i in data["items"] if i["type"] == "Изолации"), None)
    assert iso_budget is not None
    
    # Verify remaining calculation
    assert iso_budget["labor_remaining"] == iso_budget["labor_budget"] - iso_budget["labor_spent"]
    assert iso_budget["materials_remaining"] == iso_budget["materials_budget"] - iso_budget["materials_spent"]
