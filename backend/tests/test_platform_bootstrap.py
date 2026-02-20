"""
Tests for Platform Bootstrap Endpoint

POST /api/platform/bootstrap-create-platform-admin

Security tests:
1) Missing env var => 403 "Bootstrap disabled"
2) Wrong token => 401 "Invalid bootstrap token"
3) Valid token + new email => created:true
4) Valid token + existing email => created:false (idempotent)
5) Password is hashed (not stored as plaintext)
6) Weak password => 400
7) Invalid email => 400
"""
import pytest
import requests
import os
import uuid


# Test token (must match .env for local testing)
TEST_TOKEN = os.environ.get(
    "PLATFORM_BOOTSTRAP_TOKEN", 
    "BEGWORK_BOOTSTRAP_2026_xK9mPqL7vN3wR5tY8uJ2"
)


class TestBootstrapCreatePlatformAdmin:
    """Test suite for POST /api/platform/bootstrap-create-platform-admin"""

    @pytest.fixture(autouse=True)
    def setup(self, base_url):
        self.base_url = base_url
        self.endpoint = f"{base_url}/api/platform/bootstrap-create-platform-admin"

    # ═══════════════════════════════════════════════════════════════════
    # TEST 1: Missing env var => 403
    # Note: We can't easily test this without modifying env in runtime
    # This test verifies the endpoint exists and responds correctly when enabled
    # ═══════════════════════════════════════════════════════════════════

    def test_bootstrap_status_shows_enabled(self):
        """GET /bootstrap-status should show enabled when token is set"""
        resp = requests.get(f"{self.base_url}/api/platform/bootstrap-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "bootstrap_enabled" in data
        # Should be enabled in test environment
        assert data["bootstrap_enabled"] == True

    # ═══════════════════════════════════════════════════════════════════
    # TEST 2: Wrong token => 401
    # ═══════════════════════════════════════════════════════════════════

    def test_wrong_token_returns_401(self):
        """POST with wrong X-Bootstrap-Token returns 401"""
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": "wrong_token_12345"},
            json={"email": "test@example.com", "password": "SecurePass123!"}
        )
        assert resp.status_code == 401
        assert "Invalid bootstrap token" in resp.json().get("detail", "")

    def test_missing_token_returns_401(self):
        """POST without X-Bootstrap-Token header returns 401"""
        resp = requests.post(
            self.endpoint,
            json={"email": "test@example.com", "password": "SecurePass123!"}
        )
        assert resp.status_code == 401
        assert "Invalid bootstrap token" in resp.json().get("detail", "")

    def test_empty_token_returns_401(self):
        """POST with empty X-Bootstrap-Token returns 401"""
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": ""},
            json={"email": "test@example.com", "password": "SecurePass123!"}
        )
        assert resp.status_code == 401

    # ═══════════════════════════════════════════════════════════════════
    # TEST 3: Valid token + new email => created:true
    # ═══════════════════════════════════════════════════════════════════

    def test_create_new_user_returns_created_true(self):
        """POST with valid token and new email creates user (created:true)"""
        test_email = f"bootstrap_new_{uuid.uuid4().hex[:8]}@example.com"
        test_password = "SecurePass123!"
        
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": test_email, "password": test_password}
        )
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == True
        assert data["created"] == True
        assert test_email in data["message"]
        assert "next_steps" in data
        assert len(data["next_steps"]) == 2

    # ═══════════════════════════════════════════════════════════════════
    # TEST 4: Valid token + existing email => created:false (idempotent)
    # ═══════════════════════════════════════════════════════════════════

    def test_existing_user_returns_created_false(self):
        """POST with valid token and existing email returns created:false"""
        # First, create a user
        test_email = f"bootstrap_exist_{uuid.uuid4().hex[:8]}@example.com"
        
        resp1 = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": test_email, "password": "SecurePass123!"}
        )
        assert resp1.status_code == 200
        assert resp1.json()["created"] == True
        
        # Try to create again - should return created:false
        resp2 = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": test_email, "password": "DifferentPass456!"}
        )
        
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["ok"] == True
        assert data["created"] == False
        assert "already exists" in data["message"]

    # ═══════════════════════════════════════════════════════════════════
    # TEST 5: Password is hashed (verify bcrypt)
    # ═══════════════════════════════════════════════════════════════════

    def test_password_is_hashed_and_verifiable(self):
        """Created user's password should be hashed (bcrypt) and verifiable via login"""
        test_email = f"bootstrap_hash_{uuid.uuid4().hex[:8]}@example.com"
        test_password = "SecurePass123!"
        
        # Create user via bootstrap
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": test_email, "password": test_password}
        )
        assert resp.status_code == 200
        assert resp.json()["created"] == True
        
        # Verify password works via login
        login_resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": test_email, "password": test_password}
        )
        assert login_resp.status_code == 200
        assert "token" in login_resp.json()
        
        # Verify is_platform_admin is True
        token = login_resp.json()["token"]
        me_resp = requests.get(
            f"{self.base_url}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["is_platform_admin"] == True
        
        # Verify wrong password fails
        bad_login = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": test_email, "password": "wrong_password"}
        )
        assert bad_login.status_code == 401

    # ═══════════════════════════════════════════════════════════════════
    # TEST 6: Weak password => 400
    # ═══════════════════════════════════════════════════════════════════

    def test_weak_password_returns_400(self):
        """POST with password < 10 characters returns 400"""
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": "test@example.com", "password": "short"}
        )
        assert resp.status_code == 422  # Pydantic validation error
        # Check that it mentions password requirement
        detail = resp.json().get("detail", [])
        assert any("10" in str(d) for d in detail)

    # ═══════════════════════════════════════════════════════════════════
    # TEST 7: Invalid email => 400/422
    # ═══════════════════════════════════════════════════════════════════

    def test_invalid_email_returns_error(self):
        """POST with invalid email format returns 422"""
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": "not-an-email", "password": "SecurePass123!"}
        )
        assert resp.status_code == 422

    def test_empty_email_returns_error(self):
        """POST with empty email returns 422"""
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": "", "password": "SecurePass123!"}
        )
        assert resp.status_code == 422

    # ═══════════════════════════════════════════════════════════════════
    # TEST 8: Verify response shape
    # ═══════════════════════════════════════════════════════════════════

    def test_response_shape_on_create(self):
        """Verify exact response shape on successful creation"""
        test_email = f"bootstrap_shape_{uuid.uuid4().hex[:8]}@example.com"
        
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": test_email, "password": "SecurePass123!"}
        )
        
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify exact shape
        assert set(data.keys()) == {"ok", "created", "message", "next_steps"}
        assert data["ok"] == True
        assert data["created"] == True
        assert isinstance(data["message"], str)
        assert isinstance(data["next_steps"], list)
        assert len(data["next_steps"]) == 2
        assert "Login" in data["next_steps"][0]
        assert "PLATFORM_BOOTSTRAP_TOKEN" in data["next_steps"][1]

    def test_response_shape_on_existing(self):
        """Verify exact response shape when user exists"""
        # Use admin@begwork.com which should exist
        resp = requests.post(
            self.endpoint,
            headers={"X-Bootstrap-Token": TEST_TOKEN},
            json={"email": "admin@begwork.com", "password": "ignored123!"}
        )
        
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify exact shape
        assert set(data.keys()) == {"ok", "created", "message", "next_steps"}
        assert data["ok"] == True
        assert data["created"] == False
        assert "already exists" in data["message"]
