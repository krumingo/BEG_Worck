"""
Tests for Platform Admin Access Control

Tests verify that:
1. Normal org Admin gets 403 on protected endpoints
2. Platform Admin (is_platform_admin=True) gets 200
3. Protected endpoints: /billing/config, /modules, /mobile-settings, /audit-logs
"""
import pytest
import requests
import uuid

from tests.test_utils import VALID_ADMIN_PASSWORD


class TestPlatformAdminAccessControl:
    """Test suite for platform admin access control"""

    @pytest.fixture(autouse=True)
    def setup(self, base_url, ensure_seed_data):
        """Setup test fixtures"""
        self.base_url = base_url
        
        # Create a regular admin user (NOT platform admin)
        self.regular_admin_email = f"regular_admin_{uuid.uuid4().hex[:8]}@test.com"
        self.regular_admin_password = "RegularAdmin123!"
        
        # Create org via signup
        signup_resp = requests.post(
            f"{self.base_url}/api/billing/signup",
            json={
                "org_name": f"Test Org {uuid.uuid4().hex[:8]}",
                "owner_name": "Regular Admin",
                "owner_email": self.regular_admin_email,
                "password": self.regular_admin_password
            }
        )
        
        if signup_resp.status_code != 200:
            pytest.skip("Could not create test org")
        
        signup_data = signup_resp.json()
        self.regular_admin_token = signup_data.get("token")
        self.regular_admin_user = signup_data.get("user")
        
        # Login as platform admin (admin@begwork.com should be set as platform admin)
        platform_login = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": "admin@begwork.com", "password": VALID_ADMIN_PASSWORD}
        )
        if platform_login.status_code == 200:
            platform_data = platform_login.json()
            self.platform_admin_token = platform_data.get("token")
            self.platform_admin_user = platform_data.get("user")
        else:
            self.platform_admin_token = None
            self.platform_admin_user = None

    def regular_admin_headers(self):
        return {"Authorization": f"Bearer {self.regular_admin_token}"}

    def platform_admin_headers(self):
        return {"Authorization": f"Bearer {self.platform_admin_token}"}

    # ═══════════════════════════════════════════════════════════════════
    # /api/billing/config - Platform Admin Only
    # ═══════════════════════════════════════════════════════════════════

    def test_billing_config_regular_admin_403(self):
        """Regular org admin should get 403 on /billing/config"""
        resp = requests.get(
            f"{self.base_url}/api/billing/config",
            headers=self.regular_admin_headers()
        )
        assert resp.status_code == 403
        assert "PLATFORM_ADMIN_REQUIRED" in str(resp.json())

    def test_billing_config_platform_admin_200(self):
        """Platform admin should get 200 on /billing/config"""
        if not self.platform_admin_token:
            pytest.skip("Platform admin not available")
        
        if not self.platform_admin_user.get("is_platform_admin"):
            pytest.skip("admin@begwork.com is not a platform admin")
        
        resp = requests.get(
            f"{self.base_url}/api/billing/config",
            headers=self.platform_admin_headers()
        )
        assert resp.status_code == 200
        assert "stripe_mock_mode" in resp.json()

    # ═══════════════════════════════════════════════════════════════════
    # /api/feature-flags (PUT) - Platform Admin Only
    # ═══════════════════════════════════════════════════════════════════

    def test_feature_flags_put_regular_admin_403(self):
        """Regular org admin should get 403 on PUT /feature-flags"""
        resp = requests.put(
            f"{self.base_url}/api/feature-flags",
            headers=self.regular_admin_headers(),
            json={"module_code": "M1", "enabled": True}
        )
        assert resp.status_code == 403
        assert "PLATFORM_ADMIN_REQUIRED" in str(resp.json())

    def test_feature_flags_get_regular_admin_200(self):
        """Regular org admin CAN read feature flags (GET)"""
        resp = requests.get(
            f"{self.base_url}/api/feature-flags",
            headers=self.regular_admin_headers()
        )
        assert resp.status_code == 200

    # ═══════════════════════════════════════════════════════════════════
    # /api/mobile/settings - Platform Admin Only
    # ═══════════════════════════════════════════════════════════════════

    def test_mobile_settings_regular_admin_403(self):
        """Regular org admin should get 403 on /mobile/settings"""
        resp = requests.get(
            f"{self.base_url}/api/mobile/settings",
            headers=self.regular_admin_headers()
        )
        assert resp.status_code == 403
        assert "PLATFORM_ADMIN_REQUIRED" in str(resp.json())

    def test_mobile_settings_platform_admin_200(self):
        """Platform admin should get 200 on /mobile/settings"""
        if not self.platform_admin_token:
            pytest.skip("Platform admin not available")
        
        if not self.platform_admin_user.get("is_platform_admin"):
            pytest.skip("admin@begwork.com is not a platform admin")
        
        resp = requests.get(
            f"{self.base_url}/api/mobile/settings",
            headers=self.platform_admin_headers()
        )
        assert resp.status_code == 200

    # ═══════════════════════════════════════════════════════════════════
    # /api/audit-logs - Platform Admin Only
    # ═══════════════════════════════════════════════════════════════════

    def test_audit_logs_regular_admin_403(self):
        """Regular org admin should get 403 on /audit-logs"""
        resp = requests.get(
            f"{self.base_url}/api/audit-logs",
            headers=self.regular_admin_headers()
        )
        assert resp.status_code == 403
        assert "PLATFORM_ADMIN_REQUIRED" in str(resp.json())

    def test_audit_logs_platform_admin_200(self):
        """Platform admin should get 200 on /audit-logs"""
        if not self.platform_admin_token:
            pytest.skip("Platform admin not available")
        
        if not self.platform_admin_user.get("is_platform_admin"):
            pytest.skip("admin@begwork.com is not a platform admin")
        
        resp = requests.get(
            f"{self.base_url}/api/audit-logs",
            headers=self.platform_admin_headers()
        )
        assert resp.status_code == 200
        assert "logs" in resp.json()

    # ═══════════════════════════════════════════════════════════════════
    # /api/auth/me - Should include is_platform_admin
    # ═══════════════════════════════════════════════════════════════════

    def test_auth_me_includes_platform_admin_flag(self):
        """GET /auth/me should include is_platform_admin field"""
        resp = requests.get(
            f"{self.base_url}/api/auth/me",
            headers=self.regular_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        # Field should exist, even if False
        assert "is_platform_admin" in data
        assert data["is_platform_admin"] == False

    def test_auth_me_platform_admin_flag_true(self):
        """Platform admin's /auth/me should have is_platform_admin=True"""
        if not self.platform_admin_token:
            pytest.skip("Platform admin not available")
        
        resp = requests.get(
            f"{self.base_url}/api/auth/me",
            headers=self.platform_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("is_platform_admin") == True
