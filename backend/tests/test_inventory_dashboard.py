"""
Test file for Inventory Dashboard features (P1)
Tests: Dashboard endpoint, stock alerts, threshold management, movement insights, project remainders
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')


class TestInventoryDashboard:
    """Tests for GET /api/inventory/dashboard endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self, api_client, auth_token):
        """Setup auth for all tests"""
        self.client = api_client
        self.client.headers.update({"Authorization": f"Bearer {auth_token}"})
    
    def test_dashboard_returns_200(self, api_client, auth_token):
        """Test dashboard endpoint returns 200"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_dashboard_contains_overview(self, api_client, auth_token):
        """Test dashboard response contains overview section with required fields"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        assert "overview" in data, "Response missing 'overview'"
        overview = data["overview"]
        
        # Verify all required overview fields
        assert "total_materials" in overview, "Missing total_materials"
        assert "total_value" in overview, "Missing total_value"
        assert "low_stock_count" in overview, "Missing low_stock_count"
        assert "on_projects_count" in overview, "Missing on_projects_count"
        assert "recent_intakes" in overview, "Missing recent_intakes (30 day movements)"
        assert "recent_issues" in overview, "Missing recent_issues (30 day movements)"
        assert "recent_returns" in overview, "Missing recent_returns (30 day movements)"
        
        # Verify types
        assert isinstance(overview["total_materials"], int), "total_materials should be int"
        assert isinstance(overview["total_value"], (int, float)), "total_value should be numeric"
    
    def test_dashboard_contains_stock_with_low_stock_flag(self, api_client, auth_token):
        """Test dashboard stock items include is_low_stock flag based on threshold"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        assert "stock" in data, "Response missing 'stock'"
        stock = data["stock"]
        assert isinstance(stock, list), "stock should be a list"
        
        if len(stock) > 0:
            item = stock[0]
            # Verify stock item structure
            assert "material_name" in item, "Stock item missing material_name"
            assert "unit" in item, "Stock item missing unit"
            assert "qty" in item, "Stock item missing qty"
            assert "value" in item, "Stock item missing value"
            assert "low_stock_threshold" in item, "Stock item missing low_stock_threshold"
            assert "is_low_stock" in item, "Stock item missing is_low_stock flag"
            
            # Verify is_low_stock is boolean
            assert isinstance(item["is_low_stock"], bool), "is_low_stock should be boolean"
    
    def test_low_stock_flag_calculated_correctly(self, api_client, auth_token):
        """Test is_low_stock flag is true when qty <= threshold"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        stock = data["stock"]
        for item in stock:
            if item["qty"] <= item["low_stock_threshold"]:
                assert item["is_low_stock"] == True, f"{item['material_name']} should be is_low_stock=True (qty={item['qty']}, threshold={item['low_stock_threshold']})"
            else:
                assert item["is_low_stock"] == False, f"{item['material_name']} should be is_low_stock=False (qty={item['qty']}, threshold={item['low_stock_threshold']})"
    
    def test_dashboard_contains_top_moved_sorted(self, api_client, auth_token):
        """Test dashboard top_moved materials sorted by move count (descending)"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        assert "top_moved" in data, "Response missing 'top_moved'"
        top_moved = data["top_moved"]
        assert isinstance(top_moved, list), "top_moved should be a list"
        
        if len(top_moved) > 0:
            item = top_moved[0]
            # Verify structure
            assert "material_name" in item, "top_moved item missing material_name"
            assert "moves" in item, "top_moved item missing moves count"
            assert "intake_qty" in item, "top_moved item missing intake_qty"
            assert "issue_qty" in item, "top_moved item missing issue_qty"
            assert "return_qty" in item, "top_moved item missing return_qty"
        
        # Verify sorting by move count (descending)
        if len(top_moved) > 1:
            for i in range(len(top_moved) - 1):
                assert top_moved[i]["moves"] >= top_moved[i+1]["moves"], \
                    f"top_moved not sorted by moves: {top_moved[i]['moves']} should >= {top_moved[i+1]['moves']}"
    
    def test_dashboard_contains_project_remainders(self, api_client, auth_token):
        """Test dashboard project_remainders includes items with remaining > 0"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        assert "project_remainders" in data, "Response missing 'project_remainders'"
        remainders = data["project_remainders"]
        assert isinstance(remainders, list), "project_remainders should be a list"
        
        if len(remainders) > 0:
            item = remainders[0]
            # Verify structure with project info
            assert "project_id" in item, "Missing project_id"
            assert "project_code" in item, "Missing project_code"
            assert "project_name" in item, "Missing project_name"
            assert "material_name" in item, "Missing material_name"
            assert "unit" in item, "Missing unit"
            assert "issued" in item, "Missing issued"
            assert "consumed" in item, "Missing consumed"
            assert "returned" in item, "Missing returned"
            assert "remaining" in item, "Missing remaining"
            
            # All items should have remaining > 0
            for r in remainders:
                assert r["remaining"] > 0, f"project_remainders should only include items with remaining > 0, got {r['material_name']}={r['remaining']}"


class TestInventoryThreshold:
    """Tests for PUT /api/inventory/threshold endpoint"""
    
    def test_threshold_update_success(self, api_client, auth_token):
        """Test updating threshold for a material"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        
        # Update threshold to 10
        response = api_client.put(f"{BASE_URL}/api/inventory/threshold", json={
            "material_name": "TEST_Posting_Material_1",
            "unit": "бр",
            "threshold": 10
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("ok") == True, "Response should have ok=True"
        assert data.get("threshold") == 10, f"Expected threshold=10, got {data.get('threshold')}"
        
        # Verify change in dashboard
        dash_response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        stock = dash_response.json()["stock"]
        test_mat = next((s for s in stock if s["material_name"] == "TEST_Posting_Material_1" and s["unit"] == "бр"), None)
        assert test_mat is not None, "TEST_Posting_Material_1 not found in stock"
        assert test_mat["low_stock_threshold"] == 10, f"Threshold not updated in dashboard, got {test_mat['low_stock_threshold']}"
        
        # Reset threshold back to 5
        api_client.put(f"{BASE_URL}/api/inventory/threshold", json={
            "material_name": "TEST_Posting_Material_1",
            "unit": "бр",
            "threshold": 5
        })
    
    def test_threshold_update_changes_is_low_stock_flag(self, api_client, auth_token):
        """Test that threshold change affects is_low_stock flag"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        
        # Get current stock for TEST_Posting_Material_1 (has qty=19.45)
        dash_response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        stock = dash_response.json()["stock"]
        test_mat = next((s for s in stock if s["material_name"] == "TEST_Posting_Material_1"), None)
        initial_is_low = test_mat["is_low_stock"] if test_mat else None
        
        # Set threshold to 25 (higher than qty 19.45) - should mark as low stock
        api_client.put(f"{BASE_URL}/api/inventory/threshold", json={
            "material_name": "TEST_Posting_Material_1",
            "unit": "бр",
            "threshold": 25
        })
        
        dash_response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        stock = dash_response.json()["stock"]
        test_mat = next((s for s in stock if s["material_name"] == "TEST_Posting_Material_1"), None)
        assert test_mat["is_low_stock"] == True, "Should be is_low_stock=True when threshold (25) > qty (19.45)"
        
        # Reset threshold back to 5
        api_client.put(f"{BASE_URL}/api/inventory/threshold", json={
            "material_name": "TEST_Posting_Material_1",
            "unit": "бр",
            "threshold": 5
        })
        
        dash_response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        stock = dash_response.json()["stock"]
        test_mat = next((s for s in stock if s["material_name"] == "TEST_Posting_Material_1"), None)
        assert test_mat["is_low_stock"] == False, "Should be is_low_stock=False when threshold (5) < qty (19.45)"
    
    def test_threshold_requires_auth(self, api_client):
        """Test threshold endpoint requires authentication"""
        response = api_client.put(f"{BASE_URL}/api/inventory/threshold", json={
            "material_name": "TEST_Posting_Material_1",
            "unit": "бр",
            "threshold": 5
        })
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"


class TestInventoryOverview:
    """Integration test for inventory overview consistency"""
    
    def test_low_stock_count_matches_stock_items(self, api_client, auth_token):
        """Test that overview.low_stock_count matches actual low stock items in stock list"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        overview_count = data["overview"]["low_stock_count"]
        actual_count = sum(1 for s in data["stock"] if s["is_low_stock"])
        
        assert overview_count == actual_count, f"overview.low_stock_count ({overview_count}) != actual low stock items ({actual_count})"
    
    def test_total_materials_matches_stock_length(self, api_client, auth_token):
        """Test that overview.total_materials matches stock array length"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        overview_count = data["overview"]["total_materials"]
        actual_count = len(data["stock"])
        
        assert overview_count == actual_count, f"overview.total_materials ({overview_count}) != stock length ({actual_count})"
    
    def test_on_projects_count_matches_remainders(self, api_client, auth_token):
        """Test that on_projects_count matches project_remainders count"""
        api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
        
        response = api_client.get(f"{BASE_URL}/api/inventory/dashboard")
        data = response.json()
        
        overview_count = data["overview"]["on_projects_count"]
        actual_count = len(data["project_remainders"])
        
        # Note: on_projects_count may be limited to 30 max in project_remainders
        assert overview_count >= actual_count or overview_count == actual_count, \
            f"overview.on_projects_count ({overview_count}) should be >= project_remainders length ({actual_count})"


# Fixtures
@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture
def auth_token(api_client):
    """Get authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@begwork.com",
        "password": "AdminTest123!Secure"
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Authentication failed - skipping authenticated tests")
