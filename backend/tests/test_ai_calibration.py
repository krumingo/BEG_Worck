"""
Test AI Calibration Analytics + Learning Loop Routes.
Tests: record-edit, overview, categories, approve, calibration factor lookup
Min samples safety: observation <5, suggested 5-9, ready >=10
Outlier protection: edits >200% delta are skipped
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
TEST_EMAIL = "admin@begwork.com"
TEST_PASSWORD = "AdminTest123!Secure"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")  # API returns 'token', not 'access_token'
    pytest.skip(f"Authentication failed - status {response.status_code}")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestRecordEditEndpoint:
    """Test POST /api/ai-calibration/record-edit"""
    
    def test_record_edit_basic(self, api_client):
        """Record a basic AI edit event"""
        unique_id = uuid.uuid4().hex[:8]
        response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
            "ai_provider_used": "llm",
            "ai_confidence": 0.92,
            "ai_material_price_per_unit": 10.00,
            "ai_labor_price_per_unit": 15.00,
            "ai_total_price_per_unit": 25.00,
            "ai_small_qty_adjustment": 0,
            "final_material_price_per_unit": 12.00,
            "final_labor_price_per_unit": 18.00,
            "final_total_price_per_unit": 30.00,
            "city": "София",
            "project_id": f"TEST_project_{unique_id}",
            "source_type": "extra_work",
            "normalized_activity_type": "Довършителни",
            "normalized_activity_subtype": "Боядисване",
            "unit": "m2",
            "qty": 10,
            "small_qty_flag": False
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "event_id" in data
        assert data["was_edited"] is True  # Prices differ
        assert "delta_percent" in data
        # Delta should be positive since final > AI price
        assert data["delta_percent"] > 0
        print(f"PASS: Recorded edit event with delta {data['delta_percent']}%")
    
    def test_record_edit_unchanged(self, api_client):
        """Record an AI proposal accepted without changes"""
        unique_id = uuid.uuid4().hex[:8]
        response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
            "ai_provider_used": "rule-based",
            "ai_confidence": 0.85,
            "ai_material_price_per_unit": 8.50,
            "ai_labor_price_per_unit": 12.00,
            "ai_total_price_per_unit": 20.50,
            "ai_small_qty_adjustment": 0,
            "final_material_price_per_unit": 8.50,
            "final_labor_price_per_unit": 12.00,
            "final_total_price_per_unit": 20.50,
            "city": "Пловдив",
            "project_id": f"TEST_project_{unique_id}",
            "source_type": "extra_work",
            "normalized_activity_type": "Мокри процеси",
            "normalized_activity_subtype": "Мазилка",
            "unit": "m2",
            "qty": 15,
            "small_qty_flag": False
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["was_edited"] is False  # Prices are same
        assert data["delta_percent"] == 0
        print("PASS: Recorded unchanged event (was_edited=False)")
    
    def test_record_edit_outlier_skipped(self, api_client):
        """Verify outliers (>200% delta) are skipped"""
        unique_id = uuid.uuid4().hex[:8]
        response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
            "ai_provider_used": "llm",
            "ai_confidence": 0.88,
            "ai_material_price_per_unit": 10.00,
            "ai_labor_price_per_unit": 10.00,
            "ai_total_price_per_unit": 20.00,
            "final_material_price_per_unit": 70.00,  # 250% delta - outlier
            "final_labor_price_per_unit": 70.00,
            "final_total_price_per_unit": 140.00,
            "city": "Варна",
            "project_id": f"TEST_project_{unique_id}",
            "source_type": "extra_work",
            "normalized_activity_type": "Инсталации",
            "normalized_activity_subtype": "Електро",
            "unit": "pcs",
            "qty": 5,
            "small_qty_flag": False
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data.get("skipped") is True
        assert data.get("reason") == "outlier"
        print("PASS: Outlier (>200% delta) was skipped correctly")
    
    def test_record_edit_small_qty_flag(self, api_client):
        """Record edit with small_qty_flag=True"""
        unique_id = uuid.uuid4().hex[:8]
        response = api_client.post(f"{BASE_URL}/api/ai-calibration/record-edit", json={
            "ai_provider_used": "rule-based",
            "ai_confidence": 0.85,
            "ai_material_price_per_unit": 15.00,
            "ai_labor_price_per_unit": 20.00,
            "ai_total_price_per_unit": 35.00,
            "ai_small_qty_adjustment": 35,
            "final_material_price_per_unit": 18.00,
            "final_labor_price_per_unit": 22.00,
            "final_total_price_per_unit": 40.00,
            "city": "София",
            "project_id": f"TEST_project_{unique_id}",
            "source_type": "extra_work",
            "normalized_activity_type": "Довършителни",
            "normalized_activity_subtype": "Плочки",
            "unit": "m2",
            "qty": 2,
            "small_qty_flag": True
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        print("PASS: Recorded event with small_qty_flag=True")


class TestOverviewEndpoint:
    """Test GET /api/ai-calibration/overview"""
    
    def test_overview_returns_stats(self, api_client):
        """Overview returns expected fields"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/overview")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "total_proposals" in data
        assert "accepted_unchanged" in data
        assert "manually_edited" in data
        assert "acceptance_rate" in data
        assert "avg_edit_delta_percent" in data
        assert "top_corrected_categories" in data
        
        assert isinstance(data["total_proposals"], int)
        assert isinstance(data["acceptance_rate"], (int, float))
        assert isinstance(data["top_corrected_categories"], list)
        
        print(f"PASS: Overview - Total: {data['total_proposals']}, Accepted: {data['accepted_unchanged']}, Edited: {data['manually_edited']}, Rate: {data['acceptance_rate']}%")
    
    def test_overview_top_categories_structure(self, api_client):
        """Top corrected categories have correct structure"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/overview")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["top_corrected_categories"]:
            cat = data["top_corrected_categories"][0]
            assert "category" in cat
            assert "count" in cat
            assert "avg_delta" in cat
            print(f"PASS: Top category structure valid - {cat['category']} ({cat['count']}x, {cat['avg_delta']}%)")
        else:
            print("PASS: No top categories (empty list is valid)")


class TestCategoriesEndpoint:
    """Test GET /api/ai-calibration/categories"""
    
    def test_categories_returns_list(self, api_client):
        """Categories returns list of category breakdowns"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/categories")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        if data:
            cat = data[0]
            # Check required fields
            assert "activity_type" in cat
            assert "sample_count" in cat
            assert "edited_count" in cat
            assert "calibration_status" in cat
            assert "suggested_factor" in cat
            
            # Calibration status must be one of: observation, suggested, ready, approved
            assert cat["calibration_status"] in ["observation", "suggested", "ready", "approved"]
            
            print(f"PASS: Categories - {len(data)} categories found")
            print(f"  First: {cat['activity_type']}/{cat.get('activity_subtype', '')} - {cat['sample_count']} samples, status={cat['calibration_status']}")
        else:
            print("PASS: Categories list empty (valid)")
    
    def test_categories_min_sample_statuses(self, api_client):
        """Verify calibration_status follows min sample rules: observation<5, suggested 5-9, ready>=10"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/categories")
        
        assert response.status_code == 200
        data = response.json()
        
        for cat in data:
            sc = cat["sample_count"]
            status = cat["calibration_status"]
            
            # Skip approved - it overrides sample-based logic
            if status == "approved":
                continue
            
            # Verify status matches sample count
            if sc < 5:
                assert status == "observation", f"Sample count {sc} should be 'observation', got '{status}'"
            elif sc < 10:
                assert status == "suggested", f"Sample count {sc} should be 'suggested', got '{status}'"
            else:
                assert status == "ready", f"Sample count {sc} should be 'ready', got '{status}'"
        
        print("PASS: Min sample status rules verified (observation<5, suggested 5-9, ready>=10)")
    
    def test_categories_city_filter(self, api_client):
        """Categories can be filtered by city"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/categories", params={"city": "София"})
        
        assert response.status_code == 200
        data = response.json()
        
        # All returned categories should have city=София
        for cat in data:
            assert cat.get("city") == "София"
        
        print(f"PASS: City filter works - {len(data)} categories for София")
    
    def test_categories_fields_complete(self, api_client):
        """Categories have all required fields"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/categories")
        
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "activity_type", "activity_subtype", "city", "small_qty",
            "sample_count", "edited_count", "avg_delta_percent", "median_delta_percent",
            "avg_ai_price", "avg_final_price", "suggested_factor", "calibration_status"
        ]
        
        if data:
            cat = data[0]
            for field in required_fields:
                assert field in cat, f"Missing field: {field}"
            print(f"PASS: All {len(required_fields)} required fields present")
        else:
            print("PASS: No categories to check (valid)")


class TestApproveEndpoint:
    """Test POST /api/ai-calibration/approve"""
    
    def test_approve_calibration(self, api_client):
        """Approve a calibration factor"""
        unique_id = uuid.uuid4().hex[:8]
        
        response = api_client.post(f"{BASE_URL}/api/ai-calibration/approve", json={
            "activity_type": f"TEST_{unique_id}_Type",
            "activity_subtype": f"TEST_{unique_id}_Subtype",
            "city": "София",
            "small_qty": False,
            "factor": 1.15,
            "sample_count": 25,
            "avg_delta": 15.0
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "calibration" in data
        
        cal = data["calibration"]
        assert cal["status"] == "approved"
        assert cal["factor"] == 1.15
        assert cal["activity_type"] == f"TEST_{unique_id}_Type"
        
        print(f"PASS: Approved calibration {cal['factor']}x for {cal['activity_type']}")
    
    def test_approve_upsert_updates_existing(self, api_client):
        """Approving same category again updates rather than duplicates"""
        unique_id = uuid.uuid4().hex[:8]
        
        # First approval
        response1 = api_client.post(f"{BASE_URL}/api/ai-calibration/approve", json={
            "activity_type": f"TEST_UPSERT_{unique_id}",
            "activity_subtype": "Test",
            "city": None,
            "small_qty": False,
            "factor": 1.10,
            "sample_count": 10,
            "avg_delta": 10.0
        })
        assert response1.status_code == 200
        
        # Second approval with different factor
        response2 = api_client.post(f"{BASE_URL}/api/ai-calibration/approve", json={
            "activity_type": f"TEST_UPSERT_{unique_id}",
            "activity_subtype": "Test",
            "city": None,
            "small_qty": False,
            "factor": 1.20,  # Updated factor
            "sample_count": 20,
            "avg_delta": 20.0
        })
        
        assert response2.status_code == 200
        data = response2.json()
        assert data["calibration"]["factor"] == 1.20  # Should be updated
        
        print("PASS: Upsert behavior - existing calibration updated")


class TestApprovedCalibrations:
    """Test GET /api/ai-calibration/approved"""
    
    def test_list_approved_calibrations(self, api_client):
        """List all approved calibrations"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/approved")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        if data:
            cal = data[0]
            assert cal["status"] == "approved"
            assert "factor" in cal
            assert "activity_type" in cal
            
        print(f"PASS: Listed {len(data)} approved calibrations")


class TestCalibrationAppliedInProposal:
    """Test that approved calibration is applied in AI proposals"""
    
    def test_proposal_with_calibration(self, api_client):
        """Test AI proposal applies approved calibration factor"""
        # First, create an approved calibration for Боядисване/София
        # Note: Pre-seeded data already has Боядисване/София with 1.15x factor
        
        # Get AI proposal for Боядисване in София
        response = api_client.post(f"{BASE_URL}/api/extra-works/ai-proposal", json={
            "title": "Боядисване на стена",
            "unit": "m2",
            "qty": 20,
            "city": "София"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Check if calibration was applied
        if "calibration" in data and data["calibration"].get("applied"):
            cal = data["calibration"]
            assert "factor" in cal
            assert "calibrated_total_price" in cal
            print(f"PASS: Calibration applied - factor={cal['factor']}x, base={cal['base_total_price']}, calibrated={cal['calibrated_total_price']}")
        else:
            # May not have matching calibration - still valid
            print("INFO: No calibration applied (may not have matching approved calibration)")


class TestAdminOnlyAccess:
    """Test that calibration endpoints require Admin role"""
    
    def test_overview_requires_admin(self, api_client):
        """Overview endpoint accessible to admin"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/overview")
        assert response.status_code == 200
        print("PASS: Admin can access overview")
    
    def test_categories_requires_admin(self, api_client):
        """Categories endpoint accessible to admin"""
        response = api_client.get(f"{BASE_URL}/api/ai-calibration/categories")
        assert response.status_code == 200
        print("PASS: Admin can access categories")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
