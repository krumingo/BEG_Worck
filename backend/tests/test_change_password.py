"""
Tests for POST /api/auth/change-password endpoint
"""
import pytest
import requests

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = "admin123"
STRONG_PASSWORD = "NewSecure123!Pass"
WEAK_PASSWORD = "weak"


class TestChangePassword:
    """Test suite for change-password endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self, base_url):
        """Setup test fixtures"""
        self.base_url = base_url
        # Login to get token
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        if login_resp.status_code == 200:
            self.token = login_resp.json().get("token")
        else:
            # If admin is disabled, skip tests
            pytest.skip("Admin user not available for testing")

    def get_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_change_password_success(self):
        """Test successful password change with valid current and strong new password"""
        # Change to new password
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": ADMIN_PASSWORD,
                "new_password": STRONG_PASSWORD
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") == True

        # Verify new password works
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": STRONG_PASSWORD}
        )
        assert login_resp.status_code == 200

        # Revert to original password for other tests
        new_token = login_resp.json().get("token")
        revert_resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": STRONG_PASSWORD,
                "new_password": ADMIN_PASSWORD
            },
            headers={"Authorization": f"Bearer {new_token}"}
        )
        assert revert_resp.status_code == 200

    def test_change_password_wrong_current(self):
        """Test failure when current password is incorrect -> 403"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": "wrongPassword123!",
                "new_password": STRONG_PASSWORD
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
                "current_password": ADMIN_PASSWORD,
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
                "current_password": ADMIN_PASSWORD,
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
                "current_password": ADMIN_PASSWORD,
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
                "current_password": ADMIN_PASSWORD,
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
                "current_password": ADMIN_PASSWORD,
                "new_password": "NoSpecialChar123"
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 400
        assert "special" in resp.json().get("detail", "").lower()

    def test_change_password_same_as_current(self):
        """Test failure when new password is same as current -> 400"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": ADMIN_PASSWORD,
                "new_password": ADMIN_PASSWORD
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 400
        assert "different" in resp.json().get("detail", "").lower()

    def test_change_password_no_auth(self):
        """Test failure when no auth token provided -> 403"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": ADMIN_PASSWORD,
                "new_password": STRONG_PASSWORD
            }
        )
        assert resp.status_code == 403
