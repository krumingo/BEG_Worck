"""
Tests for POST /api/admin/set-password/{user_id} endpoint
Admin-only password reset functionality
"""
import pytest
import requests
import uuid


# Test credentials - using seed data from conftest
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "admin123"
TECH_EMAIL = "tech@begwork.com"
TECH_PASSWORD = "TechUser123!"
STRONG_PASSWORD = "AdminReset123!New"


class TestAdminSetPassword:
    """Test suite for admin set-password endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self, base_url, ensure_seed_data):
        """Setup test fixtures"""
        self.base_url = base_url
        
        # Login as admin
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        if login_resp.status_code != 200:
            pytest.skip("Admin user not available for testing")
        
        admin_data = login_resp.json()
        self.admin_token = admin_data.get("token")
        self.admin_user = admin_data.get("user")
        
        # Login as technician (non-admin)
        tech_login = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": TECH_EMAIL, "password": TECH_PASSWORD}
        )
        if tech_login.status_code == 200:
            tech_data = tech_login.json()
            self.tech_token = tech_data.get("token")
            self.tech_user = tech_data.get("user")
        else:
            self.tech_token = None
            self.tech_user = None

    def admin_headers(self):
        return {"Authorization": f"Bearer {self.admin_token}"}

    def tech_headers(self):
        return {"Authorization": f"Bearer {self.tech_token}"}

    def test_admin_set_password_success(self):
        """Test admin can reset password for another user"""
        if not self.tech_user:
            pytest.skip("Technician user not available")
        
        resp = requests.post(
            f"{self.base_url}/api/admin/set-password/{self.tech_user['id']}",
            json={"new_password": STRONG_PASSWORD},
            headers=self.admin_headers()
        )
        assert resp.status_code == 200
        assert resp.json().get("ok") == True
        
        # Verify new password works
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": TECH_EMAIL, "password": STRONG_PASSWORD}
        )
        assert login_resp.status_code == 200
        
        # Reset back to original password for other tests
        requests.post(
            f"{self.base_url}/api/admin/set-password/{self.tech_user['id']}",
            json={"new_password": TECH_PASSWORD},
            headers=self.admin_headers()
        )

    def test_admin_cannot_reset_own_password(self):
        """Test admin cannot use this endpoint for their own password -> 400"""
        resp = requests.post(
            f"{self.base_url}/api/admin/set-password/{self.admin_user['id']}",
            json={"new_password": STRONG_PASSWORD},
            headers=self.admin_headers()
        )
        assert resp.status_code == 400
        assert "own password" in resp.json().get("detail", "").lower()

    def test_non_admin_cannot_reset_password(self):
        """Test non-admin user cannot use this endpoint -> 403"""
        if not self.tech_token:
            pytest.skip("Technician user not available")
        
        # Get another user to try to reset
        users_resp = requests.get(
            f"{self.base_url}/api/users",
            headers=self.admin_headers()
        )
        users = users_resp.json()
        target = next((u for u in users if u["id"] != self.tech_user["id"]), None)
        if not target:
            pytest.skip("No other user available")
        
        resp = requests.post(
            f"{self.base_url}/api/admin/set-password/{target['id']}",
            json={"new_password": STRONG_PASSWORD},
            headers=self.tech_headers()
        )
        assert resp.status_code == 403

    def test_reset_password_weak_password(self):
        """Test password strength validation still applies -> 400"""
        if not self.tech_user:
            pytest.skip("Technician user not available")
        
        resp = requests.post(
            f"{self.base_url}/api/admin/set-password/{self.tech_user['id']}",
            json={"new_password": "weak"},
            headers=self.admin_headers()
        )
        assert resp.status_code == 400
        assert "10 characters" in resp.json().get("detail", "")

    def test_reset_password_user_not_found(self):
        """Test resetting password for non-existent user -> 404"""
        fake_id = str(uuid.uuid4())
        resp = requests.post(
            f"{self.base_url}/api/admin/set-password/{fake_id}",
            json={"new_password": STRONG_PASSWORD},
            headers=self.admin_headers()
        )
        assert resp.status_code == 404

    def test_reset_password_no_auth(self):
        """Test without auth token -> 403"""
        if not self.tech_user:
            pytest.skip("Technician user not available")
        
        resp = requests.post(
            f"{self.base_url}/api/admin/set-password/{self.tech_user['id']}",
            json={"new_password": STRONG_PASSWORD}
        )
        assert resp.status_code == 403

    def test_audit_log_created(self):
        """Test that password reset creates audit log entry"""
        if not self.tech_user:
            pytest.skip("Technician user not available")
        
        # Reset password
        resp = requests.post(
            f"{self.base_url}/api/admin/set-password/{self.tech_user['id']}",
            json={"new_password": STRONG_PASSWORD},
            headers=self.admin_headers()
        )
        assert resp.status_code == 200
        
        # Check audit logs
        logs_resp = requests.get(
            f"{self.base_url}/api/audit-logs?limit=5",
            headers=self.admin_headers()
        )
        assert logs_resp.status_code == 200
        logs = logs_resp.json().get("logs", [])
        
        # Find the password reset log
        reset_log = next(
            (log for log in logs if log.get("action") == "admin_password_reset" 
             and log.get("entity_id") == self.tech_user["id"]),
            None
        )
        assert reset_log is not None
        assert reset_log.get("entity_type") == "user"
        assert reset_log.get("changes", {}).get("target_email") == TECH_EMAIL
        
        # Reset back to original
        requests.post(
            f"{self.base_url}/api/admin/set-password/{self.tech_user['id']}",
            json={"new_password": TECH_PASSWORD},
            headers=self.admin_headers()
        )
