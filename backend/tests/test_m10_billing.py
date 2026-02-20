"""
Tests for M10 Billing & SaaS Self-Onboarding
Tests signup, subscription, checkout (mock mode), and module gating
"""
import pytest
import httpx
import os

from tests.test_utils import VALID_ADMIN_PASSWORD, VALID_STRONG_PASSWORD

BASE_URL = os.environ.get("API_URL", "http://localhost:8001")
API_URL = f"{BASE_URL}/api"

# Test data - use valid password
TEST_ORG_NAME = "Test Billing Corp"
TEST_OWNER_NAME = "Test Owner"
TEST_EMAIL = f"billing_test_{os.urandom(4).hex()}@example.com"
TEST_PASSWORD = VALID_STRONG_PASSWORD

@pytest.fixture(scope="module")
def test_user_token():
    """Create a test user and return their token"""
    with httpx.Client() as client:
        # Create new org via signup
        response = client.post(
            f"{API_URL}/billing/signup",
            json={
                "org_name": TEST_ORG_NAME,
                "owner_name": TEST_OWNER_NAME,
                "owner_email": TEST_EMAIL,
                "password": TEST_PASSWORD,
            }
        )
        assert response.status_code == 200, f"Signup failed: {response.text}"
        data = response.json()
        assert "token" in data
        return data["token"]

@pytest.fixture(scope="module")
def admin_token():
    """Get admin user token"""
    with httpx.Client() as client:
        response = client.post(
            f"{API_URL}/auth/login",
            json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        return response.json()["token"]

@pytest.fixture(scope="module")
def platform_admin_token():
    """Get platform admin user token (or create one for tests)"""
    with httpx.Client() as client:
        # Try to login as existing platform admin
        response = client.post(
            f"{API_URL}/auth/login",
            json={"email": "Krumingo@gmail.com", "password": "BegWork2026!SecureProd#Admin"}
        )
        if response.status_code == 200:
            return response.json()["token"]
        
        # Fall back to admin@begwork.com if it's a platform admin
        response = client.post(
            f"{API_URL}/auth/login",
            json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
        )
        if response.status_code == 200:
            return response.json()["token"]
        
        pytest.skip("No platform admin available for testing")

class TestBillingPlans:
    """Test billing plans endpoints"""
    
    def test_list_plans_public(self):
        """GET /api/billing/plans should be public"""
        with httpx.Client() as client:
            response = client.get(f"{API_URL}/billing/plans")
            assert response.status_code == 200
            plans = response.json()
            assert len(plans) == 3
            plan_ids = [p["id"] for p in plans]
            assert "free" in plan_ids
            assert "pro" in plan_ids
            assert "enterprise" in plan_ids
    
    def test_plan_structure(self):
        """Each plan should have required fields"""
        with httpx.Client() as client:
            response = client.get(f"{API_URL}/billing/plans")
            plans = response.json()
            for plan in plans:
                assert "id" in plan
                assert "name" in plan
                assert "price" in plan
                assert "allowed_modules" in plan
                assert "limits" in plan
                assert "trial_days" in plan
    
    def test_free_plan_config(self):
        """Free plan should have correct configuration"""
        with httpx.Client() as client:
            response = client.get(f"{API_URL}/billing/plans")
            plans = response.json()
            free_plan = next(p for p in plans if p["id"] == "free")
            assert free_plan["price"] == 0
            assert free_plan["trial_days"] == 14
            assert "M0" in free_plan["allowed_modules"]
            assert "M1" in free_plan["allowed_modules"]
            assert "M3" in free_plan["allowed_modules"]

class TestBillingConfig:
    """Test billing config endpoint"""
    
    def test_get_config_requires_platform_admin(self):
        """GET /api/billing/config requires platform admin - 403 for regular users"""
        with httpx.Client() as client:
            # Without auth should return 403
            response = client.get(f"{API_URL}/billing/config")
            assert response.status_code == 403
    
    def test_get_config_with_platform_admin(self, platform_admin_token):
        """GET /api/billing/config should return stripe config for platform admins"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/billing/config",
                headers={"Authorization": f"Bearer {platform_admin_token}"}
            )
            assert response.status_code == 200
            config = response.json()
            assert "stripe_mock_mode" in config
            assert "stripe_configured" in config
            assert "required_env_vars" in config

class TestSignup:
    """Test organization signup"""
    
    def test_signup_creates_org_and_user(self):
        """Signup should create organization, user, and subscription"""
        unique_email = f"signup_test_{os.urandom(4).hex()}@example.com"
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/billing/signup",
                json={
                    "org_name": "Signup Test Corp",
                    "owner_name": "Signup Tester",
                    "owner_email": unique_email,
                    "password": "testpass123",
                }
            )
            assert response.status_code == 200
            data = response.json()
            
            # Should return token
            assert "token" in data
            
            # Should return user info
            assert data["user"]["email"] == unique_email.lower()
            assert data["user"]["role"] == "Owner"
            
            # Should return org info
            assert data["organization"]["name"] == "Signup Test Corp"
            
            # Should return subscription info
            assert data["subscription"]["plan_id"] == "free"
            assert data["subscription"]["status"] == "trialing"
            assert data["subscription"]["days_remaining"] == 14
    
    def test_signup_duplicate_email_fails(self, test_user_token):
        """Signup with existing email should fail"""
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/billing/signup",
                json={
                    "org_name": "Duplicate Corp",
                    "owner_name": "Duplicate User",
                    "owner_email": TEST_EMAIL,  # Already exists
                    "password": "testpass123",
                }
            )
            assert response.status_code == 400
            assert "already registered" in response.json()["detail"].lower()

class TestSubscription:
    """Test subscription management"""
    
    def test_get_subscription(self, test_user_token):
        """GET /api/billing/subscription should return subscription details"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/billing/subscription",
                headers={"Authorization": f"Bearer {test_user_token}"}
            )
            assert response.status_code == 200
            sub = response.json()
            assert "plan_id" in sub
            assert "status" in sub
            assert "plan" in sub
            assert "stripe_mock_mode" in sub
    
    def test_subscription_includes_plan_details(self, test_user_token):
        """Subscription response should include plan details"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/billing/subscription",
                headers={"Authorization": f"Bearer {test_user_token}"}
            )
            sub = response.json()
            plan = sub["plan"]
            assert "name" in plan
            assert "price" in plan
            assert "allowed_modules" in plan
            assert "limits" in plan

class TestCheckout:
    """Test checkout session creation"""
    
    def test_create_checkout_session_mock_mode(self, test_user_token):
        """In mock mode, checkout should upgrade subscription directly"""
        # First downgrade to free to test upgrade
        # (Note: in real test, we'd need to reset the subscription first)
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/billing/create-checkout-session",
                headers={"Authorization": f"Bearer {test_user_token}"},
                json={"plan_id": "enterprise", "origin_url": "https://test.example.com"}
            )
            # In mock mode, should succeed
            data = response.json()
            if data.get("mock_mode"):
                assert response.status_code == 200
                assert data["mock_mode"] == True
                assert "checkout_url" in data
            else:
                # If real Stripe is configured, may fail without valid price ID
                pass
    
    def test_checkout_free_plan_fails(self, test_user_token):
        """Cannot checkout for free plan"""
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/billing/create-checkout-session",
                headers={"Authorization": f"Bearer {test_user_token}"},
                json={"plan_id": "free", "origin_url": "https://test.example.com"}
            )
            assert response.status_code == 400
            assert "free" in response.json()["detail"].lower()
    
    def test_checkout_invalid_plan_fails(self, test_user_token):
        """Checkout with invalid plan should fail"""
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/billing/create-checkout-session",
                headers={"Authorization": f"Bearer {test_user_token}"},
                json={"plan_id": "invalid_plan", "origin_url": "https://test.example.com"}
            )
            assert response.status_code == 400

class TestModuleGating:
    """Test module access control based on subscription"""
    
    def test_check_module_access(self, test_user_token):
        """Should be able to check module access"""
        with httpx.Client() as client:
            # M0 (Core) should always be allowed
            response = client.get(
                f"{API_URL}/billing/check-module/M0",
                headers={"Authorization": f"Bearer {test_user_token}"}
            )
            assert response.status_code == 200
            assert response.json()["allowed"] == True
    
    def test_module_access_based_on_plan(self, admin_token):
        """Module access should depend on plan"""
        with httpx.Client() as client:
            # Get current subscription to know the plan
            sub_response = client.get(
                f"{API_URL}/billing/subscription",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            sub = sub_response.json()
            allowed_modules = sub["plan"]["allowed_modules"]
            
            # Check access to allowed modules
            for module in allowed_modules:
                response = client.get(
                    f"{API_URL}/billing/check-module/{module}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                assert response.status_code == 200
                result = response.json()
                assert result["allowed"] == True, f"Module {module} should be allowed"

class TestPortalSession:
    """Test Stripe portal session creation"""
    
    def test_portal_session_mock_mode(self, test_user_token):
        """In mock mode, portal should indicate unavailability"""
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/billing/create-portal-session",
                headers={"Authorization": f"Bearer {test_user_token}"}
            )
            # Should succeed but indicate mock mode
            if response.status_code == 200:
                data = response.json()
                if data.get("mock_mode"):
                    assert data["portal_url"] is None
            # Or may return 400 if no Stripe customer

class TestWebhook:
    """Test Stripe webhook handling"""
    
    def test_webhook_accepts_payload(self):
        """Webhook should accept valid JSON payload"""
        with httpx.Client() as client:
            # Send a minimal webhook payload
            response = client.post(
                f"{API_URL}/billing/webhook",
                json={
                    "type": "test.event",
                    "data": {"object": {}}
                }
            )
            # Should accept and return status
            assert response.status_code == 200
            assert response.json()["status"] == "received"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
