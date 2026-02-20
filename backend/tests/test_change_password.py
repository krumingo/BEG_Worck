"""
Tests for POST /api/auth/change-password endpoint
"""
import pytest
import requests
import uuid

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
INITIAL_PASSWORD = "admin123"
STRONG_PASSWORD_1 = "NewSecure123!Pass"
STRONG_PASSWORD_2 = "AnotherStrong456@Pwd"


class TestChangePassword:
    """Test suite for change-password endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self, base_url):
        """Setup test fixtures - reset admin password before each test"""
        self.base_url = base_url
        self.current_password = INITIAL_PASSWORD
        
        # Try to login with initial password
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": INITIAL_PASSWORD}
        )
        
        if login_resp.status_code == 200:
            self.token = login_resp.json().get("token")
        else:
            # Try with strong passwords (in case previous test changed it)
            for pwd in [STRONG_PASSWORD_1, STRONG_PASSWORD_2]:
                login_resp = requests.post(
                    f"{self.base_url}/api/auth/login",
                    json={"email": ADMIN_EMAIL, "password": pwd}
                )
                if login_resp.status_code == 200:
                    self.token = login_resp.json().get("token")
                    self.current_password = pwd
                    break
            else:
                pytest.skip("Admin user not available for testing")

    def get_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_change_password_success(self):
        """Test successful password change with valid current and strong new password"""
        new_pwd = STRONG_PASSWORD_1 if self.current_password != STRONG_PASSWORD_1 else STRONG_PASSWORD_2
        
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": new_pwd
            },
            headers=self.get_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") == True

        # Verify new password works
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": new_pwd}
        )
        assert login_resp.status_code == 200
        
        # CLEANUP: Reset password back to initial for other tests
        new_token = login_resp.json().get("token")
        reset_resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": new_pwd,
                "new_password": INITIAL_PASSWORD
            },
            headers={"Authorization": f"Bearer {new_token}"}
        )
        assert reset_resp.status_code == 200, "Failed to reset password back to initial"

    def test_change_password_wrong_current(self):
        """Test failure when current password is incorrect -> 403"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": "totallyWrongPassword123!",
                "new_password": STRONG_PASSWORD_1
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
        """Test failure when no auth token provided -> 403"""
        resp = requests.post(
            f"{self.base_url}/api/auth/change-password",
            json={
                "current_password": self.current_password,
                "new_password": STRONG_PASSWORD_1
            }
        )
        assert resp.status_code == 403
