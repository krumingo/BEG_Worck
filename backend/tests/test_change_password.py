"""
Tests for POST /api/auth/change-password endpoint
"""
import pytest
import requests

from tests.test_utils import (
    VALID_ADMIN_PASSWORD,
    VALID_STRONG_PASSWORD,
    generate_valid_password
)

# Test credentials using valid passwords
ADMIN_EMAIL = "admin@begwork.com"


class TestChangePassword:
    """Test suite for change-password endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self, base_url, ensure_seed_data):
        """Setup test fixtures."""
        self.base_url = base_url
        self.current_password = VALID_ADMIN_PASSWORD
        
        # Login with valid password
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": VALID_ADMIN_PASSWORD}
        )
        
        if login_resp.status_code != 200:
            pytest.skip(f"Admin login failed: {login_resp.text}")
        
        self.token = login_resp.json().get("token")

    def get_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_change_password_success(self):
        """Test successful password change with valid current and strong new password"""
        new_pwd = generate_valid_password()
        
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": new_pwd
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 200, f"Change password failed: {resp.text}"
        data = resp.json()
        assert data.get("ok") == True

        # Verify new password works
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": new_pwd}
        )
        assert login_resp.status_code == 200

        # CLEANUP: Reset password back to original for other tests
        new_token = login_resp.json().get("token")
        reset_resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": new_pwd,
                "new_password": VALID_ADMIN_PASSWORD
            },
            headers={"Authorization": f"Bearer {new_token}"}
        )
        assert reset_resp.status_code == 200, f"Password reset failed: {reset_resp.text}"

    def test_change_password_wrong_current(self):
        """Test failure when current password is incorrect -> 403"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": "totallyWrongPassword123!",
                "new_password": VALID_STRONG_PASSWORD
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 403
        assert "incorrect" in resp.json().get("detail", "").lower()

    def test_change_password_weak_too_short(self):
        """Test failure when new password is too short -> 400"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": "Short1!"
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 400
        assert "10 characters" in resp.json().get("detail", "")

    def test_change_password_weak_no_uppercase(self):
        """Test failure when new password has no uppercase -> 400"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": "alllowercase123!"
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 400
        assert "uppercase" in resp.json().get("detail", "").lower()

    def test_change_password_weak_no_lowercase(self):
        """Test failure when new password has no lowercase -> 400"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": "ALLUPPERCASE123!"
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 400
        assert "lowercase" in resp.json().get("detail", "").lower()

    def test_change_password_weak_no_digit(self):
        """Test failure when new password has no digit -> 400"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": "NoDigitsHere!@#"
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 400
        assert "digit" in resp.json().get("detail", "").lower()

    def test_change_password_weak_no_special(self):
        """Test failure when new password has no special char -> 400"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": "NoSpecialChar123"
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 400
        assert "special" in resp.json().get("detail", "").lower()

    def test_change_password_no_auth(self):
        """Test failure when not authenticated -> 403"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": VALID_STRONG_PASSWORD
            }
        )
        assert resp.status_code == 403
