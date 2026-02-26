"""
Tests for Activity Budgets endpoints.
"""
import pytest
from httpx import AsyncClient
import uuid


@pytest.mark.asyncio
async def test_activity_types_endpoint(client: AsyncClient, auth_headers: dict):
    """Test GET /api/activity-types returns list of types."""
    response = await client.get("/api/activity-types", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "types" in data
    assert "Общо" in data["types"]
    assert "Бетон" in data["types"]
    assert len(data["types"]) >= 10


@pytest.mark.asyncio
async def test_upsert_activity_budget_create(client: AsyncClient, auth_headers: dict, test_project_id: str):
    """Test creating a new activity budget."""
    response = await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
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


@pytest.mark.asyncio
async def test_upsert_activity_budget_update(client: AsyncClient, auth_headers: dict, test_project_id: str):
    """Test updating an existing activity budget (upsert)."""
    # First create
    response1 = await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
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
    response2 = await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
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


@pytest.mark.asyncio
async def test_list_activity_budgets(client: AsyncClient, auth_headers: dict, test_project_id: str):
    """Test listing activity budgets for a project."""
    # Create a budget first
    await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
        json={"type": "Арматура", "subtype": "", "labor_budget": 4000, "materials_budget": 6000}
    )
    
    response = await client.get(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) >= 1


@pytest.mark.asyncio
async def test_activity_budget_summary(client: AsyncClient, auth_headers: dict, test_project_id: str):
    """Test the budget summary endpoint returns correct structure."""
    # Create a budget
    await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
        json={"type": "Бетон", "subtype": "Плоча", "labor_budget": 10000, "materials_budget": 15000}
    )
    
    response = await client.get(
        f"/api/projects/{test_project_id}/activity-budget-summary",
        headers=auth_headers
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
    
    # Check item structure
    if data["items"]:
        item = data["items"][0]
        assert "type" in item
        assert "subtype" in item
        assert "labor_budget" in item
        assert "labor_spent" in item
        assert "labor_remaining" in item
        assert "percent_labor_used" in item
        assert "has_budget" in item


@pytest.mark.asyncio
async def test_delete_activity_budget(client: AsyncClient, auth_headers: dict, test_project_id: str):
    """Test deleting an activity budget."""
    # Create
    response1 = await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
        json={"type": "Зидария", "subtype": "Тухли", "labor_budget": 2000, "materials_budget": 5000}
    )
    budget_id = response1.json()["id"]
    
    # Delete
    response2 = await client.delete(
        f"/api/projects/{test_project_id}/activity-budgets/{budget_id}",
        headers=auth_headers
    )
    assert response2.status_code == 200
    assert response2.json()["ok"] == True
    
    # Verify deleted
    response3 = await client.get(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers
    )
    budgets = response3.json()["items"]
    budget_ids = [b["id"] for b in budgets]
    assert budget_id not in budget_ids


@pytest.mark.asyncio
async def test_budget_remaining_calculation(client: AsyncClient, auth_headers: dict, test_project_id: str):
    """Test that remaining = budget - spent."""
    # Create a budget with known values
    await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
        json={"type": "Изолации", "subtype": "", "labor_budget": 8000, "materials_budget": 12000}
    )
    
    response = await client.get(
        f"/api/projects/{test_project_id}/activity-budget-summary",
        headers=auth_headers
    )
    data = response.json()
    
    # Find our budget
    iso_budget = next((i for i in data["items"] if i["type"] == "Изолации"), None)
    assert iso_budget is not None
    
    # Verify remaining calculation
    assert iso_budget["labor_remaining"] == iso_budget["labor_budget"] - iso_budget["labor_spent"]
    assert iso_budget["materials_remaining"] == iso_budget["materials_budget"] - iso_budget["materials_spent"]


@pytest.mark.asyncio  
async def test_percent_used_calculation(client: AsyncClient, auth_headers: dict, test_project_id: str):
    """Test that percent_used is calculated correctly."""
    # Create a budget
    await client.post(
        f"/api/projects/{test_project_id}/activity-budgets",
        headers=auth_headers,
        json={"type": "Фасада", "subtype": "", "labor_budget": 10000, "materials_budget": 20000}
    )
    
    response = await client.get(
        f"/api/projects/{test_project_id}/activity-budget-summary",
        headers=auth_headers
    )
    data = response.json()
    
    # Find our budget
    fasada = next((i for i in data["items"] if i["type"] == "Фасада"), None)
    assert fasada is not None
    
    # With 0 spent, percent should be 0
    if fasada["labor_budget"] > 0 and fasada["labor_spent"] == 0:
        assert fasada["percent_labor_used"] == 0
