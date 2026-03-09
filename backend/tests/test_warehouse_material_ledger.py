"""
Tests for Warehouse Stock, Issue, Consumption, Return, and Project Material Ledger
P1: Main Warehouse → Project Allocation + Consumption + Remaining Stock Control

Endpoints tested:
- GET /api/warehouse-stock - returns current stock levels
- POST /api/warehouse-issue - creates issue transaction, reduces warehouse stock
- POST /api/project-consumption - records consumption, validates against project available
- POST /api/warehouse-return - returns material to warehouse from project
- GET /api/project-material-ledger/{id} - returns full ledger with warnings
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestWarehouseAndMaterialLedger:
    """Test suite for warehouse operations and project material ledger"""
    
    @pytest.fixture(autouse=True)
    def setup(self, auth_headers):
        """Setup auth headers for all tests"""
        self.headers = auth_headers
        self.test_project_id = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001
    
    # ============ GET /api/warehouse-stock Tests ============
    
    def test_get_warehouse_stock_success(self):
        """Test GET /api/warehouse-stock returns current stock levels"""
        response = requests.get(f"{BASE_URL}/api/warehouse-stock", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        
        # Each item should have required fields
        if len(data) > 0:
            item = data[0]
            assert "material_name" in item
            assert "unit" in item
            assert "qty" in item
            assert "value" in item
            print(f"Stock items found: {len(data)}")
            for s in data[:5]:  # Print first 5
                print(f"  - {s['material_name']}: {s['qty']} {s['unit']}")
    
    def test_get_warehouse_stock_returns_positive_quantities(self):
        """Stock should only contain items with qty > 0"""
        response = requests.get(f"{BASE_URL}/api/warehouse-stock", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        for item in data:
            assert item["qty"] > 0, f"Stock item {item['material_name']} has non-positive qty: {item['qty']}"
    
    # ============ POST /api/warehouse-issue Tests ============
    
    def test_warehouse_issue_success(self):
        """Test POST /api/warehouse-issue creates issue transaction"""
        # First check available stock
        stock_res = requests.get(f"{BASE_URL}/api/warehouse-stock", headers=self.headers)
        assert stock_res.status_code == 200
        stock = stock_res.json()
        
        if not stock:
            pytest.skip("No stock available to test issue")
        
        # Use existing material with small quantity to avoid depleting all stock
        test_material = stock[0]
        issue_qty = min(0.5, test_material["qty"] * 0.1)  # Issue only 10% or 0.5
        
        payload = {
            "project_id": self.test_project_id,
            "lines": [{
                "material_name": test_material["material_name"],
                "qty_issued": issue_qty,
                "unit": test_material["unit"],
                "unit_price": 1.0,
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/warehouse-issue", json=payload, headers=self.headers)
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "id" in data
        assert data["type"] == "issue"
        assert data["project_id"] == self.test_project_id
        assert "issue_number" in data
        assert data["issue_number"].startswith("WI-")
        assert len(data["lines"]) == 1
        assert data["lines"][0]["qty_issued"] == issue_qty
        
        print(f"Created issue: {data['issue_number']} for {issue_qty} {test_material['unit']} of {test_material['material_name']}")
    
    def test_warehouse_issue_insufficient_stock_returns_400(self):
        """Test POST /api/warehouse-issue validates insufficient stock"""
        # Try to issue more than available
        payload = {
            "project_id": self.test_project_id,
            "lines": [{
                "material_name": "TEST_NonExistent_Material_999",
                "qty_issued": 9999999,
                "unit": "бр",
                "unit_price": 1.0,
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/warehouse-issue", json=payload, headers=self.headers)
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        assert "Недостатъчна наличност" in data["detail"] or "insufficient" in data["detail"].lower()
        print(f"Correctly rejected insufficient stock: {data['detail']}")
    
    def test_warehouse_issue_requires_project_id(self):
        """Test POST /api/warehouse-issue requires project_id"""
        payload = {
            "lines": [{
                "material_name": "Test Material",
                "qty_issued": 1,
                "unit": "бр",
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/warehouse-issue", json=payload, headers=self.headers)
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    
    def test_warehouse_issue_requires_lines(self):
        """Test POST /api/warehouse-issue requires lines"""
        payload = {
            "project_id": self.test_project_id,
            "lines": []
        }
        
        response = requests.post(f"{BASE_URL}/api/warehouse-issue", json=payload, headers=self.headers)
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    
    # ============ POST /api/project-consumption Tests ============
    
    def test_project_consumption_success(self):
        """Test POST /api/project-consumption records consumption"""
        # First get project ledger to see what's available
        ledger_res = requests.get(f"{BASE_URL}/api/project-material-ledger/{self.test_project_id}", headers=self.headers)
        assert ledger_res.status_code == 200
        ledger_data = ledger_res.json()
        ledger = ledger_data.get("ledger", [])
        
        # Find material with remaining_on_project > 0
        available = [m for m in ledger if m.get("remaining_on_project", 0) > 0.1]
        if not available:
            pytest.skip("No materials with remaining quantity on project to test consumption")
        
        test_mat = available[0]
        consume_qty = min(0.1, test_mat["remaining_on_project"] * 0.1)
        
        payload = {
            "project_id": self.test_project_id,
            "lines": [{
                "material_name": test_mat["material_name"],
                "qty_consumed": consume_qty,
                "unit": test_mat["unit"],
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/project-consumption", json=payload, headers=self.headers)
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "id" in data
        assert data["type"] == "consumption"
        assert data["project_id"] == self.test_project_id
        print(f"Recorded consumption: {consume_qty} {test_mat['unit']} of {test_mat['material_name']}")
    
    def test_project_consumption_validates_remaining(self):
        """Test POST /api/project-consumption validates against project available"""
        payload = {
            "project_id": self.test_project_id,
            "lines": [{
                "material_name": "TEST_NonExistent_Material_999",
                "qty_consumed": 9999999,
                "unit": "бр",
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/project-consumption", json=payload, headers=self.headers)
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        assert "Недостатъчно по обекта" in data["detail"] or "insufficient" in data["detail"].lower()
        print(f"Correctly rejected over-consumption: {data['detail']}")
    
    def test_project_consumption_requires_project_id(self):
        """Test consumption requires project_id"""
        payload = {"lines": [{"material_name": "Test", "qty_consumed": 1, "unit": "бр"}]}
        response = requests.post(f"{BASE_URL}/api/project-consumption", json=payload, headers=self.headers)
        assert response.status_code == 400
    
    # ============ POST /api/warehouse-return Tests ============
    
    def test_warehouse_return_success(self):
        """Test POST /api/warehouse-return returns material to warehouse"""
        # First get project ledger to see what's available
        ledger_res = requests.get(f"{BASE_URL}/api/project-material-ledger/{self.test_project_id}", headers=self.headers)
        assert ledger_res.status_code == 200
        ledger_data = ledger_res.json()
        ledger = ledger_data.get("ledger", [])
        
        # Find material with remaining_on_project > 0
        available = [m for m in ledger if m.get("remaining_on_project", 0) > 0.1]
        if not available:
            pytest.skip("No materials with remaining quantity on project to test return")
        
        test_mat = available[0]
        return_qty = min(0.1, test_mat["remaining_on_project"] * 0.1)
        
        payload = {
            "project_id": self.test_project_id,
            "lines": [{
                "material_name": test_mat["material_name"],
                "qty_returned": return_qty,
                "unit": test_mat["unit"],
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/warehouse-return", json=payload, headers=self.headers)
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "id" in data
        assert data["type"] == "return"
        assert data["project_id"] == self.test_project_id
        print(f"Returned: {return_qty} {test_mat['unit']} of {test_mat['material_name']}")
    
    def test_warehouse_return_validates_remaining(self):
        """Test POST /api/warehouse-return validates against project available"""
        payload = {
            "project_id": self.test_project_id,
            "lines": [{
                "material_name": "TEST_NonExistent_Material_999",
                "qty_returned": 9999999,
                "unit": "бр",
            }]
        }
        
        response = requests.post(f"{BASE_URL}/api/warehouse-return", json=payload, headers=self.headers)
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        assert "Недостатъчно по обекта" in data["detail"] or "insufficient" in data["detail"].lower()
        print(f"Correctly rejected over-return: {data['detail']}")
    
    # ============ GET /api/project-material-ledger/{id} Tests ============
    
    def test_project_material_ledger_success(self):
        """Test GET /api/project-material-ledger/{id} returns full ledger"""
        response = requests.get(f"{BASE_URL}/api/project-material-ledger/{self.test_project_id}", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "ledger" in data
        assert "warnings" in data
        
        ledger = data["ledger"]
        assert isinstance(ledger, list)
        
        if len(ledger) > 0:
            item = ledger[0]
            # Check all required fields
            assert "material_name" in item
            assert "unit" in item
            assert "requested" in item
            assert "purchased" in item
            assert "issued_to_project" in item
            assert "consumed" in item
            assert "returned" in item
            assert "remaining_on_project" in item
            
            print(f"Ledger items: {len(ledger)}")
            for m in ledger[:5]:
                print(f"  - {m['material_name']}: issued={m['issued_to_project']}, consumed={m['consumed']}, returned={m['returned']}, remaining={m['remaining_on_project']}")
    
    def test_project_material_ledger_has_warnings(self):
        """Test ledger returns warnings for under_purchased, not_consumed, high_remaining"""
        response = requests.get(f"{BASE_URL}/api/project-material-ledger/{self.test_project_id}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        warnings = data.get("warnings", [])
        assert isinstance(warnings, list)
        
        # Check warning structure if any exist
        if warnings:
            warning = warnings[0]
            assert "material" in warning
            assert "type" in warning
            assert "message" in warning
            
            valid_types = ["under_purchased", "not_consumed", "high_remaining"]
            for w in warnings:
                assert w["type"] in valid_types, f"Unknown warning type: {w['type']}"
            
            print(f"Warnings found: {len(warnings)}")
            for w in warnings:
                print(f"  - [{w['type']}] {w['message']}")
    
    def test_project_material_ledger_remaining_calculation(self):
        """Test remaining = issued - consumed - returned"""
        response = requests.get(f"{BASE_URL}/api/project-material-ledger/{self.test_project_id}", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        ledger = data.get("ledger", [])
        
        for item in ledger:
            expected_remaining = item["issued_to_project"] - item["consumed"] - item["returned"]
            actual_remaining = item["remaining_on_project"]
            
            # Allow small floating point differences
            assert abs(expected_remaining - actual_remaining) < 0.01, \
                f"Remaining calculation mismatch for {item['material_name']}: expected {expected_remaining}, got {actual_remaining}"
        
        print("Remaining calculation verified for all items")
    
    def test_project_material_ledger_404_invalid_project(self):
        """Test ledger returns 404 for invalid project"""
        response = requests.get(f"{BASE_URL}/api/project-material-ledger/invalid-project-id", headers=self.headers)
        assert response.status_code == 404
    
    # ============ Stock Computation Tests ============
    
    def test_stock_computation_after_operations(self):
        """Test stock = intake + returns - issues (verify stock decreases after issue)"""
        # Get initial stock
        stock_before = requests.get(f"{BASE_URL}/api/warehouse-stock", headers=self.headers).json()
        
        if not stock_before:
            pytest.skip("No stock available for computation test")
        
        # Find material with enough quantity
        test_mat = None
        for item in stock_before:
            if item["qty"] >= 1:
                test_mat = item
                break
        
        if not test_mat:
            pytest.skip("No material with qty >= 1 for stock computation test")
        
        initial_qty = test_mat["qty"]
        issue_qty = 0.1
        
        # Issue from warehouse
        issue_payload = {
            "project_id": self.test_project_id,
            "lines": [{
                "material_name": test_mat["material_name"],
                "qty_issued": issue_qty,
                "unit": test_mat["unit"],
                "unit_price": 1.0,
            }]
        }
        
        issue_res = requests.post(f"{BASE_URL}/api/warehouse-issue", json=issue_payload, headers=self.headers)
        assert issue_res.status_code == 201
        
        # Get stock after issue
        stock_after = requests.get(f"{BASE_URL}/api/warehouse-stock", headers=self.headers).json()
        
        # Find same material
        after_qty = 0
        for item in stock_after:
            if item["material_name"] == test_mat["material_name"] and item["unit"] == test_mat["unit"]:
                after_qty = item["qty"]
                break
        
        # Stock should have decreased
        expected_qty = initial_qty - issue_qty
        assert abs(after_qty - expected_qty) < 0.01, \
            f"Stock not correctly reduced: expected {expected_qty}, got {after_qty}"
        
        print(f"Stock computation verified: {initial_qty} - {issue_qty} = {after_qty}")


@pytest.fixture(scope="module")
def auth_headers():
    """Login and get auth headers"""
    login_data = {
        "email": "admin@begwork.com",
        "password": "AdminTest123!Secure"
    }
    response = requests.post(f"{BASE_URL}/api/auth/login", json=login_data)
    if response.status_code != 200:
        pytest.fail(f"Login failed: {response.status_code} - {response.text}")
    
    token = response.json().get("token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
