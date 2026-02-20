"""
Tests for Platform Bootstrap Endpoint

POST /api/platform/bootstrap-promote
- Protected by PLATFORM_BOOTSTRAP_TOKEN env var
- Used to promote platform admin without shell access
"""
import pytest
import requests
import os


class TestPlatformBootstrap:
    """Test suite for platform bootstrap endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self, base_url):
        self.base_url = base_url
        # Token from .env (for testing in dev)
        self.valid_token = os.environ.get(
            "PLATFORM_BOOTSTRAP_TOKEN", 
            "BEGWORK_BOOTSTRAP_2026_xK9mPqL7vN3wR5tY8uJ2"
        )

    def test_bootstrap_status(self):
        """GET /api/platform/bootstrap-status returns enabled status"""
        resp = requests.get(f"{self.base_url}/api/platform/bootstrap-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "bootstrap_enabled" in data

    def test_bootstrap_promote_without_token_403(self):
        """POST without X-Bootstrap-Token header returns 403"""
        resp = requests.post(
            f"{self.base_url}/api/platform/bootstrap-promote",
            json={"email": "test@example.com"}
        )
        assert resp.status_code == 403
        assert "Invalid or missing" in resp.json().get("detail", "")

    def test_bootstrap_promote_wrong_token_403(self):
        """POST with wrong token returns 403"""
        resp = requests.post(
            f"{self.base_url}/api/platform/bootstrap-promote",
            headers={"X-Bootstrap-Token": "wrong_token"},
            json={"email": "test@example.com"}
        )
        assert resp.status_code == 403

    def test_bootstrap_promote_user_not_found_404(self):
        """POST with valid token but non-existent user returns 404"""
        resp = requests.post(
            f"{self.base_url}/api/platform/bootstrap-promote",
            headers={"X-Bootstrap-Token": self.valid_token},
            json={"email": "nonexistent_user_12345@example.com"}
        )
        assert resp.status_code == 404
        assert "not found" in resp.json().get("detail", "").lower()

    def test_bootstrap_promote_success(self):
        """POST with valid token and existing user succeeds"""
        # Use admin@begwork.com which should exist from seed
        resp = requests.post(
            f"{self.base_url}/api/platform/bootstrap-promote",
            headers={"X-Bootstrap-Token": self.valid_token},
            json={"email": "admin@begwork.com"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") == True
        assert data.get("user", {}).get("is_platform_admin") == True

    def test_bootstrap_promote_already_admin(self):
        """POST for user already platform admin returns ok with message"""
        # Promote first
        requests.post(
            f"{self.base_url}/api/platform/bootstrap-promote",
            headers={"X-Bootstrap-Token": self.valid_token},
            json={"email": "admin@begwork.com"}
        )
        
        # Promote again
        resp = requests.post(
            f"{self.base_url}/api/platform/bootstrap-promote",
            headers={"X-Bootstrap-Token": self.valid_token},
            json={"email": "admin@begwork.com"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") == True
        assert "already" in data.get("message", "").lower()
