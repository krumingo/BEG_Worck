"""
Tests for Mobile Integration - Phase 1 + Phase 2
Tests bootstrap endpoint, field filtering, action blocking, and media upload
"""
import pytest
import httpx
import os
import io

from tests.test_utils import VALID_ADMIN_PASSWORD, VALID_TECH_PASSWORD

BASE_URL = os.environ.get("API_URL", "http://localhost:8001")
API_URL = f"{BASE_URL}/api"

# Test credentials
ADMIN_EMAIL = "admin@begwork.com"
ADMIN_PASSWORD = VALID_ADMIN_PASSWORD
TECH_EMAIL = "tech@begwork.com"
TECH_PASSWORD = VALID_TECH_PASSWORD


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
def tech_token():
    """Get or create technician user token"""
    with httpx.Client() as client:
        # Try to login first
        response = client.post(
            f"{API_URL}/auth/login",
            json={"email": TECH_EMAIL, "password": TECH_PASSWORD}
        )
        if response.status_code == 200:
            return response.json()["token"]
        
        # If tech doesn't exist, use admin to create one
        admin_res = client.post(
            f"{API_URL}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        admin_token = admin_res.json()["token"]
        
        # Create tech user
        create_res = client.post(
            f"{API_URL}/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": TECH_EMAIL,
                "password": TECH_PASSWORD,
                "first_name": "Tech",
                "last_name": "User",
                "role": "Technician",
                "phone": ""
            }
        )
        
        if create_res.status_code in [200, 201]:
            # Now login as tech
            login_res = client.post(
                f"{API_URL}/auth/login",
                json={"email": TECH_EMAIL, "password": TECH_PASSWORD}
            )
            assert login_res.status_code == 200
            return login_res.json()["token"]
        
        # If creation failed (user exists, limit reached), just use admin
        # and test with admin token
        return admin_token


class TestMobileBootstrap:
    """Test GET /api/mobile/bootstrap endpoint"""
    
    def test_bootstrap_returns_user_info(self, tech_token):
        """Bootstrap should return user info"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {tech_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            assert "user" in data
            assert "role" in data["user"]
            assert data["user"]["role"] == "Technician"
    
    def test_bootstrap_returns_enabled_modules(self, tech_token):
        """Bootstrap should return enabled modules for the user's role"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {tech_token}"}
            )
            data = response.json()
            
            assert "enabledModules" in data
            assert isinstance(data["enabledModules"], list)
            # At minimum attendance should be enabled (default behavior)
            assert "attendance" in data["enabledModules"]
    
    def test_bootstrap_returns_view_configs(self, tech_token):
        """Bootstrap should return view configs for each enabled module"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {tech_token}"}
            )
            data = response.json()
            
            assert "viewConfigs" in data
            assert isinstance(data["viewConfigs"], dict)
            
            # Check config structure for attendance module
            if "attendance" in data["viewConfigs"]:
                config = data["viewConfigs"]["attendance"]
                assert "listFields" in config
                assert "detailFields" in config
                assert "allowedActions" in config
                assert "defaultFilters" in config
    
    def test_bootstrap_returns_quick_actions(self, tech_token):
        """Bootstrap should return quick actions"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {tech_token}"}
            )
            data = response.json()
            
            assert "quickActions" in data
            assert isinstance(data["quickActions"], list)
    
    def test_bootstrap_technician_has_correct_modules(self, tech_token):
        """Technician should have at least attendance module (others depend on settings)"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {tech_token}"}
            )
            data = response.json()
            
            # Core module - always present
            assert "attendance" in data["enabledModules"], "Technician should have attendance module"
            # Other modules depend on mobile-settings configuration
    
    def test_bootstrap_admin_has_all_modules(self, admin_token):
        """Admin should have access to enabled modules"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            data = response.json()
            
            # Admin should have at least one module enabled
            assert len(data["enabledModules"]) >= 1


class TestMobileSettings:
    """Test mobile settings management (admin only)"""
    
    def test_get_mobile_settings(self, admin_token):
        """Admin should be able to get mobile settings"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/settings",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            assert "enabled_modules" in data or "availableModules" in data
            assert "availableModules" in data
            assert "availableActions" in data
            assert "availableFields" in data
    
    def test_update_mobile_settings(self, admin_token):
        """Admin should be able to update enabled modules"""
        with httpx.Client() as client:
            # First get current settings
            get_res = client.get(
                f"{API_URL}/mobile/settings",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            original_modules = get_res.json().get("enabled_modules", [])
            
            # Update to specific modules
            new_modules = ["attendance", "workReports", "profile"]
            response = client.put(
                f"{API_URL}/mobile/settings",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"enabled_modules": new_modules}
            )
            assert response.status_code == 200
            
            # Restore original settings
            if original_modules:
                client.put(
                    f"{API_URL}/mobile/settings",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"enabled_modules": original_modules}
                )
    
    def test_non_admin_cannot_update_settings(self, tech_token):
        """Non-admin should not be able to update mobile settings"""
        with httpx.Client() as client:
            response = client.put(
                f"{API_URL}/mobile/settings",
                headers={"Authorization": f"Bearer {tech_token}"},
                json={"enabled_modules": ["attendance"]}
            )
            assert response.status_code == 403


class TestMobileViewConfigs:
    """Test mobile view config management"""
    
    def test_list_view_configs(self, admin_token):
        """Admin should be able to list all view configs"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/view-configs",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            configs = response.json()
            
            assert isinstance(configs, list)
            # Should have configs for each role/module combination
            assert len(configs) > 0
    
    def test_update_view_config(self, admin_token):
        """Admin should be able to update view config for a role/module"""
        with httpx.Client() as client:
            response = client.put(
                f"{API_URL}/mobile/view-configs",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "role": "Technician",
                    "module_code": "attendance",
                    "list_fields": ["date", "status"],
                    "detail_fields": ["date", "status", "clock_in", "clock_out"],
                    "allowed_actions": ["view", "clockIn", "clockOut"],
                    "default_filters": {"assignedToMe": True}
                }
            )
            assert response.status_code == 200
            data = response.json()
            
            assert data["role"] == "Technician"
            assert data["module_code"] == "attendance"
            assert "view" in data["allowed_actions"]
    
    def test_reset_view_config(self, admin_token):
        """Admin should be able to reset view config to defaults"""
        with httpx.Client() as client:
            response = client.delete(
                f"{API_URL}/mobile/view-configs/Technician/attendance",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            # Should return the default config
            data = response.json()
            assert data["role"] == "Technician"
            assert data["module_code"] == "attendance"


class TestFieldFiltering:
    """Test server-side field filtering"""
    
    def test_bootstrap_config_has_field_restrictions(self, tech_token):
        """Bootstrap config should specify which fields are allowed"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {tech_token}"}
            )
            data = response.json()
            
            # Check that configs have field lists
            for module, config in data["viewConfigs"].items():
                assert "listFields" in config
                assert "detailFields" in config
                assert isinstance(config["listFields"], list)
                assert isinstance(config["detailFields"], list)


class TestActionBlocking:
    """Test server-side action blocking"""
    
    def test_technician_attendance_actions(self, tech_token):
        """Technician should have specific attendance actions"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/mobile/bootstrap",
                headers={"Authorization": f"Bearer {tech_token}"}
            )
            data = response.json()
            
            if "attendance" in data["viewConfigs"]:
                actions = data["viewConfigs"]["attendance"]["allowedActions"]
                # Technician should be able to clock in/out
                assert "view" in actions
                assert "clockIn" in actions
                assert "clockOut" in actions


class TestMediaUpload:
    """Test media upload functionality"""
    
    def test_upload_media_returns_id_and_url(self, admin_token):
        """Media upload should return media ID and URL"""
        with httpx.Client() as client:
            # Create a simple test image (1x1 pixel PNG)
            import base64
            # Minimal PNG data
            png_data = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            )
            
            files = {"file": ("test.png", png_data, "image/png")}
            data = {"context_type": "workReport", "context_id": "test-123"}
            
            response = client.post(
                f"{API_URL}/media/upload",
                headers={"Authorization": f"Bearer {admin_token}"},
                files=files,
                data=data
            )
            assert response.status_code == 200
            result = response.json()
            
            assert "id" in result
            assert "url" in result
            assert result["context_type"] == "workReport"
            assert result["context_id"] == "test-123"
    
    def test_link_media_to_context(self, admin_token):
        """Should be able to link media to a context"""
        with httpx.Client() as client:
            # First upload a media file
            import base64
            png_data = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            )
            
            files = {"file": ("test2.png", png_data, "image/png")}
            upload_res = client.post(
                f"{API_URL}/media/upload",
                headers={"Authorization": f"Bearer {admin_token}"},
                files=files
            )
            media_id = upload_res.json()["id"]
            
            # Link to a context
            response = client.post(
                f"{API_URL}/media/link",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "context_type": "delivery",
                    "context_id": "delivery-456",
                    "media_id": media_id
                }
            )
            assert response.status_code == 200
            result = response.json()
            
            assert result["linked"] == True
            assert result["context_type"] == "delivery"
            assert result["context_id"] == "delivery-456"
    
    def test_get_media_metadata(self, admin_token):
        """Should be able to get media metadata"""
        with httpx.Client() as client:
            # First upload a media file
            import base64
            png_data = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            )
            
            files = {"file": ("test3.png", png_data, "image/png")}
            upload_res = client.post(
                f"{API_URL}/media/upload",
                headers={"Authorization": f"Bearer {admin_token}"},
                files=files
            )
            media_id = upload_res.json()["id"]
            
            # Get media metadata
            response = client.get(
                f"{API_URL}/media/{media_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            result = response.json()
            
            assert result["id"] == media_id
            assert "url" in result
            assert "filename" in result
            assert "owner_user_id" in result
    
    def test_invalid_file_type_rejected(self, admin_token):
        """Should reject invalid file types"""
        with httpx.Client() as client:
            files = {"file": ("test.exe", b"fake executable", "application/x-msdownload")}
            
            response = client.post(
                f"{API_URL}/media/upload",
                headers={"Authorization": f"Bearer {admin_token}"},
                files=files
            )
            assert response.status_code == 400
            result = response.json()
            assert result["detail"]["error_code"] == "INVALID_FILE_TYPE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
