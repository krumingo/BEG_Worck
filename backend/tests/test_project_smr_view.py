"""
Test file for Project SMR View API endpoint
Tests the GET /api/project-smr-view/{project_id} endpoint
Features: Main offer card, SMR table with mode/labor/progress
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestProjectSMRViewAPI:
    """Tests for Project SMR View endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "AdminTest123!Secure"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json().get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Get project ID for PRJ-001
        projects_response = requests.get(f"{BASE_URL}/api/projects", headers=self.headers)
        assert projects_response.status_code == 200
        projects = projects_response.json()
        prj001 = next((p for p in projects if p.get("code") == "PRJ-001"), None)
        assert prj001 is not None, "PRJ-001 project not found"
        self.project_id = prj001["id"]
    
    def test_smr_view_endpoint_returns_200(self):
        """Test that /api/project-smr-view/{id} returns 200"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        assert response.status_code == 200
        print(f"PASS: SMR view endpoint returns 200")
    
    def test_smr_view_returns_project_info(self):
        """Test that response contains project info"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        
        assert "project_id" in data
        assert data["project_id"] == self.project_id
        assert "project_code" in data
        assert data["project_code"] == "PRJ-001"
        assert "project_name" in data
        assert "currency" in data
        assert data["currency"] == "EUR"
        print(f"PASS: Project info returned correctly")
    
    def test_smr_view_returns_main_offer(self):
        """Test that response contains main offer with correct fields"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        
        assert "main_offer" in data
        main_offer = data["main_offer"]
        assert main_offer is not None, "Main offer should exist"
        
        # Check main offer fields
        assert "id" in main_offer
        assert "offer_no" in main_offer
        assert main_offer["offer_no"] == "OFF-0102"
        assert "status" in main_offer
        assert main_offer["status"] == "Accepted"
        assert "total" in main_offer
        assert main_offer["total"] == 4800
        assert "subtotal" in main_offer
        assert "line_count" in main_offer
        print(f"PASS: Main offer OFF-0102 returned correctly with status=Accepted, total=4800")
    
    def test_smr_view_returns_rows_with_modes(self):
        """Test that response contains SMR rows with mode/labor/progress"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        
        assert "rows" in data
        rows = data["rows"]
        assert len(rows) >= 3, f"Expected at least 3 rows, got {len(rows)}"
        
        # Check first row fields
        row = rows[0]
        required_fields = [
            "id", "activity_name", "unit", "qty", "mode",
            "sale_total", "labor_budget", "labor_actual", "labor_remaining",
            "progress_percent", "has_progress", "flags", "status"
        ]
        for field in required_fields:
            assert field in row, f"Missing field: {field}"
        
        # Check modes exist
        modes = [r["mode"] for r in rows]
        assert "mixed" in modes or "internal" in modes or "akord" in modes
        print(f"PASS: {len(rows)} SMR rows returned with correct fields")
    
    def test_smr_view_mode_labels(self):
        """Test that modes are correctly identified: internal, akord, mixed"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        rows = data["rows"]
        
        modes = {r["mode"] for r in rows}
        # Based on test data, we expect: mixed, akord, internal
        assert "mixed" in modes, "Expected 'mixed' mode for TEST_Activity_1"
        assert "akord" in modes, "Expected 'akord' mode for TEST_Activity_2"
        assert "internal" in modes, "Expected 'internal' mode for Test Activity"
        print(f"PASS: All mode types found: {modes}")
    
    def test_smr_view_progress_values(self):
        """Test progress values are correctly returned"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        rows = data["rows"]
        
        # Find row with 100% progress
        row_100 = next((r for r in rows if r["progress_percent"] == 100), None)
        assert row_100 is not None, "Expected row with 100% progress"
        assert row_100["has_progress"] == True
        
        # Find row with 0% and no_progress flag
        row_0 = next((r for r in rows if r["progress_percent"] == 0), None)
        assert row_0 is not None, "Expected row with 0% progress"
        assert row_0["has_progress"] == False
        assert "no_progress" in row_0["flags"]
        print(f"PASS: Progress values correct (100% and 0% with no_progress flag)")
    
    def test_smr_view_labor_columns(self):
        """Test labor columns are correctly populated"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        rows = data["rows"]
        
        # Check TEST_Activity_1 labor values
        row1 = next((r for r in rows if "TEST_Activity_1" in r["activity_name"]), None)
        assert row1 is not None
        
        assert row1["offer_labor_unit_price"] == 10
        assert row1["labor_budget"] == 1000
        assert row1["labor_actual"] > 0
        assert row1["labor_remaining"] is not None
        assert row1["planned_hours"] is not None
        assert row1["used_hours"] is not None
        print(f"PASS: Labor columns correctly populated")
    
    def test_smr_view_summary(self):
        """Test summary section is correct"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        
        assert "summary" in data
        summary = data["summary"]
        
        assert "total_packages" in summary
        assert summary["total_packages"] >= 3
        assert "total_sale" in summary
        assert "total_labor_budget" in summary
        assert "total_labor_actual" in summary
        assert "with_warnings" in summary
        print(f"PASS: Summary section correct: {summary['total_packages']} packages")
    
    def test_smr_view_flags(self):
        """Test that warning flags are correctly set"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/{self.project_id}", headers=self.headers)
        data = response.json()
        rows = data["rows"]
        
        # Find row with flags
        rows_with_flags = [r for r in rows if len(r["flags"]) > 0]
        assert len(rows_with_flags) > 0, "Expected at least one row with warning flags"
        
        # Check that no_progress flag exists
        no_progress_rows = [r for r in rows if "no_progress" in r["flags"]]
        assert len(no_progress_rows) > 0, "Expected row with 'no_progress' flag"
        print(f"PASS: Warning flags correctly set on {len(rows_with_flags)} rows")
    
    def test_smr_view_invalid_project_returns_404(self):
        """Test that invalid project ID returns 404"""
        response = requests.get(f"{BASE_URL}/api/project-smr-view/invalid-id-123", headers=self.headers)
        assert response.status_code == 404
        print(f"PASS: Invalid project ID returns 404")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
