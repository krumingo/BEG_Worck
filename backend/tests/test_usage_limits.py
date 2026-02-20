"""
Tests for Usage Tracking & Limits Enforcement (Plan Limits Patch)
Tests limit checking, enforcement on create operations, and usage endpoint
"""
import pytest
import httpx
import os

from tests.test_utils import VALID_ADMIN_PASSWORD, VALID_STRONG_PASSWORD

BASE_URL = os.environ.get("API_URL", "http://localhost:8001")
API_URL = f"{BASE_URL}/api"

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD


@pytest.fixture(scope="module")
def admin_token():
    """Get admin user token"""
    with httpx.Client() as client:
        response = client.post(
            f"{API_URL}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        return response.json()["token"]


@pytest.fixture(scope="module")
def free_org_token():
    """Create a new org on free plan for limit testing"""
    unique_email = f"limit_test_{os.urandom(4).hex()}@example.com"
    with httpx.Client() as client:
        response = client.post(
            f"{API_URL}/billing/signup",
            json={
                "org_name": "Limit Test Corp",
                "owner_name": "Limit Tester",
                "owner_email": unique_email,
                "password": "testpass123",
            }
        )
        assert response.status_code == 200
        return response.json()["token"]


class TestUsageEndpoint:
    """Test GET /api/billing/usage endpoint"""
    
    def test_usage_returns_all_resources(self, admin_token):
        """Usage endpoint should return all tracked resources"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/billing/usage",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            assert "usage" in data
            assert "plan_id" in data
            assert "plan_name" in data
            assert "computed_at" in data
            
            resources = [item["resource"] for item in data["usage"]]
            assert "users" in resources
            assert "projects" in resources
            assert "invoices" in resources
            assert "storage" in resources
    
    def test_usage_item_structure(self, admin_token):
        """Each usage item should have required fields"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/billing/usage",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            data = response.json()
            
            for item in data["usage"]:
                assert "resource" in item
                assert "current" in item
                assert "limit" in item
                assert "percent" in item
                assert "warning" in item
                assert "exceeded" in item
    
    def test_usage_percent_calculation(self, admin_token):
        """Percent should be correctly calculated"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/billing/usage",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            data = response.json()
            
            for item in data["usage"]:
                if item["limit"] > 0:
                    expected_percent = round((item["current"] / item["limit"]) * 100, 1)
                    assert item["percent"] == expected_percent


class TestLimitEnforcement:
    """Test limit enforcement on create operations"""
    
    def test_free_plan_user_limit(self, free_org_token):
        """Free plan should block creating 4th user (limit is 3)"""
        with httpx.Client() as client:
            headers = {"Authorization": f"Bearer {free_org_token}"}
            
            # Check current usage first
            usage_res = client.get(f"{API_URL}/billing/usage", headers=headers)
            usage = usage_res.json()
            users_usage = next(u for u in usage["usage"] if u["resource"] == "users")
            current_users = users_usage["current"]
            limit = users_usage["limit"]  # Should be 3
            
            # Try to create users up to and past the limit
            created = 0
            for i in range(limit - current_users + 1):  # Try to exceed by 1
                unique_email = f"testuser_{os.urandom(4).hex()}@example.com"
                response = client.post(
                    f"{API_URL}/users",
                    headers=headers,
                    json={
                        "email": unique_email,
                        "password": "testpass123",
                        "first_name": f"Test{i}",
                        "last_name": "User",
                        "role": "Technician",
                        "phone": "",
                    }
                )
                
                if response.status_code == 201:
                    created += 1
                elif response.status_code == 403:
                    # Should be blocked with proper error code
                    data = response.json()
                    assert "detail" in data
                    detail = data["detail"]
                    assert detail.get("error_code") == "LIMIT_USERS_EXCEEDED"
                    break
            
            # Verify we hit the limit
            assert created <= limit - current_users
    
    def test_free_plan_project_limit(self, free_org_token):
        """Free plan should block creating 3rd project (limit is 2)"""
        with httpx.Client() as client:
            headers = {"Authorization": f"Bearer {free_org_token}"}
            
            # Check current usage
            usage_res = client.get(f"{API_URL}/billing/usage", headers=headers)
            usage = usage_res.json()
            projects_usage = next(u for u in usage["usage"] if u["resource"] == "projects")
            current = projects_usage["current"]
            limit = projects_usage["limit"]  # Should be 2
            
            # Try to create projects up to and past the limit
            created = 0
            for i in range(limit - current + 1):  # Try to exceed by 1
                unique_code = f"P{os.urandom(3).hex().upper()}"
                response = client.post(
                    f"{API_URL}/projects",
                    headers=headers,
                    json={
                        "code": unique_code,
                        "name": f"Test Project {i}",
                        "status": "Active",
                        "type": "Private",
                        "start_date": "2026-01-01",
                        "end_date": "2026-12-31",
                        "planned_days": 100,
                        "budget_planned": 10000,
                        "default_site_manager_id": None,
                        "tags": [],
                        "notes": "",
                    }
                )
                
                if response.status_code == 201:
                    created += 1
                elif response.status_code == 403:
                    data = response.json()
                    detail = data["detail"]
                    assert detail.get("error_code") == "LIMIT_PROJECTS_EXCEEDED"
                    break
            
            # Verify we hit the limit
            assert created <= limit - current
    
    def test_limit_error_includes_counts(self, free_org_token):
        """Limit error should include current and limit counts"""
        with httpx.Client() as client:
            headers = {"Authorization": f"Bearer {free_org_token}"}
            
            # Keep creating users until blocked
            for i in range(10):
                unique_email = f"user_{os.urandom(4).hex()}@example.com"
                response = client.post(
                    f"{API_URL}/users",
                    headers=headers,
                    json={
                        "email": unique_email,
                        "password": "testpass123",
                        "first_name": "Test",
                        "last_name": "User",
                        "role": "Technician",
                        "phone": "",
                    }
                )
                
                if response.status_code == 403:
                    data = response.json()
                    detail = data["detail"]
                    assert "current" in detail
                    assert "limit" in detail
                    assert isinstance(detail["current"], int)
                    assert isinstance(detail["limit"], int)
                    break


class TestWarningThreshold:
    """Test warning threshold (80%)"""
    
    def test_warning_at_80_percent(self, admin_token):
        """Warning should be True when usage >= 80%"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/billing/usage",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            data = response.json()
            
            for item in data["usage"]:
                if item["percent"] >= 80:
                    assert item["warning"] == True
                elif item["percent"] < 80:
                    assert item["warning"] == False


class TestPlanLimits:
    """Test that plan limits are correctly configured"""
    
    def test_free_plan_limits(self):
        """Free plan should have correct limits"""
        with httpx.Client() as client:
            response = client.get(f"{API_URL}/billing/plans")
            plans = response.json()
            free_plan = next(p for p in plans if p["id"] == "free")
            
            assert free_plan["limits"]["users"] == 3
            assert free_plan["limits"]["projects"] == 2
            assert free_plan["limits"]["monthly_invoices"] == 5
            assert free_plan["limits"]["storage_mb"] == 100
    
    def test_pro_plan_limits(self):
        """Pro plan should have correct limits"""
        with httpx.Client() as client:
            response = client.get(f"{API_URL}/billing/plans")
            plans = response.json()
            pro_plan = next(p for p in plans if p["id"] == "pro")
            
            assert pro_plan["limits"]["users"] == 20
            assert pro_plan["limits"]["projects"] == 50
            assert pro_plan["limits"]["monthly_invoices"] == 500
            assert pro_plan["limits"]["storage_mb"] == 2000
    
    def test_enterprise_plan_limits(self):
        """Enterprise plan should have correct limits"""
        with httpx.Client() as client:
            response = client.get(f"{API_URL}/billing/plans")
            plans = response.json()
            enterprise_plan = next(p for p in plans if p["id"] == "enterprise")
            
            assert enterprise_plan["limits"]["users"] == 100
            assert enterprise_plan["limits"]["projects"] == 500
            assert enterprise_plan["limits"]["monthly_invoices"] == 5000
            assert enterprise_plan["limits"]["storage_mb"] == 20000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
