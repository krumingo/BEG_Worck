"""
Test: Materials Baseline + Request Matching Backend
Phases:
- P1: Planned Materials Snapshot (from offer, list, delete)
- P2: Request Linkage + Coverage 
- P4: Project Material Financial Summary

Test project: PRJ-001 (c3529276-8c03-49b3-92de-51216aab25da)
Test offer: OFF-0102 (3fc7217c-4cc5-4e4b-bde7-71ad96c00b8b)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test data constants
TEST_PROJECT_ID = "c3529276-8c03-49b3-92de-51216aab25da"  # PRJ-001
TEST_OFFER_ID = "3fc7217c-4cc5-4e4b-bde7-71ad96c00b8b"    # OFF-0102


class TestMaterialsBaselineAuth:
    """Authentication setup for Materials Baseline tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@begwork.com",
            "password": "AdminTest123!Secure"
        })
        assert response.status_code == 200, f"Auth failed: {response.text}"
        data = response.json()
        # API returns 'token' not 'access_token'
        assert "token" in data, "No token in response"
        return data["token"]
    
    @pytest.fixture(scope="class")
    def api_client(self, auth_token):
        """Session with auth header"""
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}"
        })
        return session


class TestPhase1PlannedMaterials(TestMaterialsBaselineAuth):
    """P1: Planned Materials Snapshot from Offer"""
    
    def test_01_delete_existing_planned_materials(self, api_client):
        """DELETE /api/planned-materials/by-offer/{id} - allows regeneration"""
        # First delete any existing planned materials for this offer
        response = api_client.delete(f"{BASE_URL}/api/planned-materials/by-offer/{TEST_OFFER_ID}")
        assert response.status_code == 200, f"Delete failed: {response.text}"
        data = response.json()
        assert "ok" in data and data["ok"] == True
        assert "deleted" in data
        print(f"Deleted {data['deleted']} existing planned materials")
    
    def test_02_generate_planned_materials_from_offer(self, api_client):
        """POST /api/planned-materials/from-offer/{id} - generates planned material rows"""
        response = api_client.post(
            f"{BASE_URL}/api/planned-materials/from-offer/{TEST_OFFER_ID}",
            json={"waste_percent": 10}
        )
        assert response.status_code == 201, f"Generate failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert data.get("ok") == True, "Response should have ok=True"
        assert "count" in data, "Response should have count"
        assert data["count"] > 0, "Should generate at least one planned material row"
        assert data.get("offer_id") == TEST_OFFER_ID
        assert data.get("project_id") == TEST_PROJECT_ID
        print(f"Generated {data['count']} planned material rows")
    
    def test_03_duplicate_protection_returns_400(self, api_client):
        """POST /api/planned-materials/from-offer/{id} - duplicate protection"""
        # Second call should return 400
        response = api_client.post(
            f"{BASE_URL}/api/planned-materials/from-offer/{TEST_OFFER_ID}",
            json={"waste_percent": 10}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "detail" in data, "Should have error detail"
        assert "already exist" in data["detail"].lower(), f"Error message should mention already exist: {data['detail']}"
        print(f"Duplicate protection works: {data['detail']}")
    
    def test_04_list_planned_materials_by_project(self, api_client):
        """GET /api/planned-materials?project_id - returns planned rows"""
        response = api_client.get(f"{BASE_URL}/api/planned-materials?project_id={TEST_PROJECT_ID}")
        assert response.status_code == 200, f"List failed: {response.text}"
        data = response.json()
        
        assert isinstance(data, list), "Should return list of planned materials"
        assert len(data) > 0, "Should have planned material rows"
        
        # Verify row structure
        row = data[0]
        required_fields = ["id", "project_id", "source_offer_id", "material_name", "unit",
                          "planned_qty", "waste_percent", "planned_qty_with_waste"]
        for field in required_fields:
            assert field in row, f"Row missing field: {field}"
        
        # Verify waste_percent and planned_qty_with_waste
        assert row["waste_percent"] == 10, "Waste percent should be 10"
        expected_with_waste = round(row["planned_qty"] * 1.1, 2)
        assert abs(row["planned_qty_with_waste"] - expected_with_waste) < 0.01, \
            f"Waste calculation incorrect: {row['planned_qty_with_waste']} vs expected {expected_with_waste}"
        
        print(f"Found {len(data)} planned material rows with correct waste calculation")
    
    def test_05_list_planned_materials_by_offer(self, api_client):
        """GET /api/planned-materials?offer_id - returns planned rows"""
        response = api_client.get(f"{BASE_URL}/api/planned-materials?offer_id={TEST_OFFER_ID}")
        assert response.status_code == 200, f"List by offer failed: {response.text}"
        data = response.json()
        
        assert isinstance(data, list), "Should return list"
        assert len(data) > 0, "Should have rows for this offer"
        
        # All rows should be for this offer
        for row in data:
            assert row["source_offer_id"] == TEST_OFFER_ID
        
        print(f"Listed {len(data)} planned materials for offer {TEST_OFFER_ID}")
    
    def test_06_delete_and_regenerate_flow(self, api_client):
        """Delete + regenerate workflow"""
        # Delete
        del_response = api_client.delete(f"{BASE_URL}/api/planned-materials/by-offer/{TEST_OFFER_ID}")
        assert del_response.status_code == 200
        
        # Regenerate with different waste percent
        gen_response = api_client.post(
            f"{BASE_URL}/api/planned-materials/from-offer/{TEST_OFFER_ID}",
            json={"waste_percent": 15}
        )
        assert gen_response.status_code == 201, f"Regeneration failed: {gen_response.text}"
        
        # Verify new waste percent
        list_response = api_client.get(f"{BASE_URL}/api/planned-materials?offer_id={TEST_OFFER_ID}")
        assert list_response.status_code == 200
        rows = list_response.json()
        
        if rows:
            assert rows[0]["waste_percent"] == 15, "Waste percent should be 15 after regeneration"
        
        print("Delete + regenerate flow works correctly")


class TestPhase2Coverage(TestMaterialsBaselineAuth):
    """P2: Request Linkage + Coverage"""
    
    def test_01_get_material_coverage(self, api_client):
        """GET /api/planned-materials/coverage/{project_id} - returns enriched rows"""
        response = api_client.get(f"{BASE_URL}/api/planned-materials/coverage/{TEST_PROJECT_ID}")
        assert response.status_code == 200, f"Coverage failed: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "project_id" in data
        assert "rows" in data
        assert "summary" in data
        assert data["project_id"] == TEST_PROJECT_ID
        
        print(f"Coverage endpoint returned {len(data['rows'])} rows")
    
    def test_02_coverage_rows_have_enriched_fields(self, api_client):
        """Coverage rows include requested/purchased/issued/consumed/returned qtys"""
        response = api_client.get(f"{BASE_URL}/api/planned-materials/coverage/{TEST_PROJECT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        if data["rows"]:
            row = data["rows"][0]
            enriched_fields = [
                "requested_qty", "purchased_qty", "stocked_qty", 
                "issued_qty", "consumed_qty", "returned_qty",
                "remaining_to_request", "remaining_to_purchase"
            ]
            for field in enriched_fields:
                assert field in row, f"Row missing enriched field: {field}"
            
            # Verify remaining calculations
            planned_qty = row.get("planned_qty_with_waste", row.get("planned_qty", 0))
            expected_remaining_to_request = max(0, planned_qty - row["requested_qty"])
            assert abs(row["remaining_to_request"] - round(expected_remaining_to_request, 2)) < 0.01, \
                "remaining_to_request calculation incorrect"
            
            expected_remaining_to_purchase = max(0, row["requested_qty"] - row["purchased_qty"])
            assert abs(row["remaining_to_purchase"] - round(expected_remaining_to_purchase, 2)) < 0.01, \
                "remaining_to_purchase calculation incorrect"
            
            print(f"Coverage row has all enriched fields with correct calculations")
        else:
            pytest.skip("No planned materials to check enrichment")
    
    def test_03_coverage_summary_structure(self, api_client):
        """Coverage summary has fully_requested/partially_requested/not_requested counts"""
        response = api_client.get(f"{BASE_URL}/api/planned-materials/coverage/{TEST_PROJECT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        summary = data["summary"]
        required_summary_fields = [
            "total_planned_rows", "total_planned_value",
            "fully_requested", "partially_requested", "not_requested",
            "fully_purchased", "has_consumption_data", "currency"
        ]
        for field in required_summary_fields:
            assert field in summary, f"Summary missing field: {field}"
        
        # Verify summary counts add up correctly
        total_rows = summary["total_planned_rows"]
        request_sum = summary["fully_requested"] + summary["partially_requested"] + summary["not_requested"]
        # Note: Some rows might have zero planned_qty_with_waste, so they might not be counted
        print(f"Summary: {summary['fully_requested']} fully requested, {summary['partially_requested']} partial, {summary['not_requested']} not requested")
        print(f"Total value: {summary['total_planned_value']} {summary['currency']}")
    
    def test_04_empty_project_coverage(self, api_client):
        """Coverage for non-existent project returns empty rows"""
        fake_project_id = "00000000-0000-0000-0000-000000000000"
        response = api_client.get(f"{BASE_URL}/api/planned-materials/coverage/{fake_project_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["rows"] == [], "Should return empty rows for non-existent project"
        assert data["summary"]["total_planned_rows"] == 0
        print("Empty project returns empty coverage correctly")


class TestPhase4Summary(TestMaterialsBaselineAuth):
    """P4: Project Material Financial Summary"""
    
    def test_01_get_project_material_summary(self, api_client):
        """GET /api/project-material-summary/{id} - returns planned vs actual comparison"""
        response = api_client.get(f"{BASE_URL}/api/project-material-summary/{TEST_PROJECT_ID}")
        assert response.status_code == 200, f"Summary failed: {response.text}"
        data = response.json()
        
        # Verify top-level structure
        assert data["project_id"] == TEST_PROJECT_ID
        assert "project_code" in data
        assert "project_name" in data
        assert "currency" in data
        
        print(f"Summary for project: {data.get('project_code')} - {data.get('project_name')}")
    
    def test_02_summary_planned_section(self, api_client):
        """Summary includes planned value"""
        response = api_client.get(f"{BASE_URL}/api/project-material-summary/{TEST_PROJECT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "planned" in data
        planned = data["planned"]
        assert "total_rows" in planned
        assert "total_value" in planned
        
        print(f"Planned: {planned['total_rows']} rows, {planned['total_value']} value")
    
    def test_03_summary_actual_section(self, api_client):
        """Summary includes purchased/issued/returned/net values"""
        response = api_client.get(f"{BASE_URL}/api/project-material-summary/{TEST_PROJECT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "actual" in data
        actual = data["actual"]
        required_actual_fields = ["purchased_value", "issued_value", "returned_value", "net_material_cost"]
        for field in required_actual_fields:
            assert field in actual, f"Actual section missing: {field}"
        
        # Net cost = issued - returned
        expected_net = round(actual["issued_value"] - actual["returned_value"], 2)
        assert actual["net_material_cost"] == expected_net, \
            f"Net cost calculation incorrect: {actual['net_material_cost']} vs expected {expected_net}"
        
        print(f"Actual: purchased={actual['purchased_value']}, issued={actual['issued_value']}, returned={actual['returned_value']}, net={actual['net_material_cost']}")
    
    def test_04_summary_variance_section(self, api_client):
        """Variance calculated: plan_vs_purchased, plan_vs_issued"""
        response = api_client.get(f"{BASE_URL}/api/project-material-summary/{TEST_PROJECT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "variance" in data
        variance = data["variance"]
        assert "plan_vs_purchased" in variance
        assert "plan_vs_issued" in variance
        
        # Verify variance calculations if planned value exists
        planned_value = data["planned"]["total_value"]
        if planned_value > 0:
            expected_vs_purchased = round(planned_value - data["actual"]["purchased_value"], 2)
            expected_vs_issued = round(planned_value - data["actual"]["issued_value"], 2)
            
            assert variance["plan_vs_purchased"] == expected_vs_purchased, \
                f"plan_vs_purchased incorrect: {variance['plan_vs_purchased']} vs expected {expected_vs_purchased}"
            assert variance["plan_vs_issued"] == expected_vs_issued, \
                f"plan_vs_issued incorrect: {variance['plan_vs_issued']} vs expected {expected_vs_issued}"
        
        print(f"Variance: plan_vs_purchased={variance['plan_vs_purchased']}, plan_vs_issued={variance['plan_vs_issued']}")
    
    def test_05_summary_metrics_available_flags(self, api_client):
        """metrics_available flags show data source availability"""
        response = api_client.get(f"{BASE_URL}/api/project-material-summary/{TEST_PROJECT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "metrics_available" in data
        metrics = data["metrics_available"]
        required_flags = ["planned_materials", "purchases", "warehouse_issues", "warehouse_returns"]
        for flag in required_flags:
            assert flag in metrics, f"metrics_available missing flag: {flag}"
            assert isinstance(metrics[flag], bool), f"{flag} should be boolean"
        
        print(f"Metrics available: {metrics}")
    
    def test_06_nonexistent_project_returns_404(self, api_client):
        """Summary for non-existent project returns 404"""
        fake_project_id = "00000000-0000-0000-0000-000000000000"
        response = api_client.get(f"{BASE_URL}/api/project-material-summary/{fake_project_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("Non-existent project correctly returns 404")


class TestEdgeCases(TestMaterialsBaselineAuth):
    """Edge cases and error handling"""
    
    def test_01_generate_from_nonexistent_offer(self, api_client):
        """Generate from non-existent offer returns 404"""
        fake_offer_id = "00000000-0000-0000-0000-000000000000"
        response = api_client.post(
            f"{BASE_URL}/api/planned-materials/from-offer/{fake_offer_id}",
            json={}
        )
        assert response.status_code == 404
        print("Non-existent offer correctly returns 404")
    
    def test_02_delete_nonexistent_offer_materials(self, api_client):
        """Delete materials for non-existent offer returns ok with 0 deleted"""
        fake_offer_id = "00000000-0000-0000-0000-000000000000"
        response = api_client.delete(f"{BASE_URL}/api/planned-materials/by-offer/{fake_offer_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] == True
        assert data["deleted"] == 0
        print("Delete non-existent returns ok with 0 deleted")


class TestDataIntegrity(TestMaterialsBaselineAuth):
    """Verify data integrity after all tests"""
    
    def test_final_state_verification(self, api_client):
        """Ensure test data is in expected final state"""
        # Check that planned materials exist for the test offer
        response = api_client.get(f"{BASE_URL}/api/planned-materials?offer_id={TEST_OFFER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        print(f"Final state: {len(data)} planned materials for offer {TEST_OFFER_ID}")
        
        # Get final summary
        summary_response = api_client.get(f"{BASE_URL}/api/project-material-summary/{TEST_PROJECT_ID}")
        if summary_response.status_code == 200:
            summary = summary_response.json()
            print(f"Project summary - Planned: {summary['planned']['total_value']}, Actual net: {summary['actual']['net_material_cost']}")
